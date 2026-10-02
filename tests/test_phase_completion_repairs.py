"""Behavioral acceptance checks for gaps found in the seven-phase audit."""
from datetime import date
from decimal import Decimal

import pytest

from src.application.catalog import ArtifactCatalog
from src.application.corporate_actions import CorporateActions
from src.application.jobs import JobStore
from src.application.market_refresh import MarketRefreshPlanner
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore


def corporate_fixture(tmp_path, *, action="RIGHTS", threshold=0.15):
    db = tmp_path / "system.db"
    market = MarketRepository(db, price_gap_threshold=threshold)
    market.upsert_instruments([TrackedInstrument("share", "ISIN", "SHARE", "NSE", "1", date(2026, 1, 1))])
    market.upsert_bars("share", [NormalizedBar("share", date(2026, 5, 1),
        Decimal(200), Decimal(200), Decimal(200), Decimal(200), 100)], "original")
    market.upsert_corporate_action_event({"event_id": "event", "isin": "ISIN",
        "symbol": "SHARE", "instrument_id": "share", "action_type": action,
        "ex_date": "2026-06-15", "raw_source_json": "{}", "state": "MONITORING",
        "ratio_numerator": 1.0 if action == "SPLIT" else None,
        "ratio_denominator": 2.0 if action == "SPLIT" else None})
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(db))
    return market, CorporateActions(db, market, publisher)


def provider_rows(post=98):
    return [{"as_of_date": day, "open": str(price), "high": str(price),
             "low": str(price), "close": str(price), "volume": 100}
            for day, price in [("2026-05-01", 100), ("2026-06-15", post)]]


@pytest.mark.parametrize("action", ["RIGHTS", "DEMERGER"])
def test_monitoring_persists_authoritative_history_before_verification(tmp_path, action):
    market, service = corporate_fixture(tmp_path, action=action)
    result = service.verify_with_kite("event", lambda *_: provider_rows())
    assert result["state"] == "VERIFIED"
    assert market.bars("share")[0]["close"] == "100"
    assert market.market_history_revision("share") != "1"


def test_corporate_monitoring_uses_configured_threshold(tmp_path):
    market, service = corporate_fixture(tmp_path, threshold=0.05)
    result = service.verify_with_kite("event", lambda *_: provider_rows(90))
    assert result["state"] == "MONITORING"
    assert result["discrepancy_pct"] == pytest.approx(10)
    assert market.bars("share")[-1]["close"] == "90"


@pytest.mark.parametrize("defect", ["missing_volume", "duplicate_date", "invalid_ohlc"])
def test_invalid_provider_history_remains_actionable_and_does_not_replace(tmp_path, defect):
    market, service = corporate_fixture(tmp_path)
    rows = provider_rows()
    if defect == "missing_volume":
        rows[0].pop("volume")
    elif defect == "duplicate_date":
        rows.append(dict(rows[0]))
    else:
        rows[0]["high"] = "1"
    before = market.bars("share")
    revision = market.market_history_revision("share")
    result = service.verify_with_kite("event", lambda *_: rows)
    assert result["outcome"] == "invalid_provider_history"
    assert market.bars("share") == before
    assert market.market_history_revision("share") == revision
    assert market.corporate_action_event("event")["state"] == "MONITORING"


def test_provider_replacement_rolls_back_when_event_transition_fails(tmp_path, monkeypatch):
    market, service = corporate_fixture(tmp_path)
    before = market.bars("share")
    revision = market.market_history_revision("share")
    def fail(*_, **__):
        raise RuntimeError("interrupted transition")
    monkeypatch.setattr(market, "transition_corporate_action", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        service.verify_with_kite("event", lambda *_: provider_rows())
    assert market.bars("share") == before
    assert market.market_history_revision("share") == revision
    assert market.corporate_action_event("event")["state"] == "MONITORING"


def refresh_fixture(tmp_path):
    db = tmp_path / "system.db"
    market = MarketRepository(db)
    jobs = JobStore(db)
    market.upsert_instruments([TrackedInstrument(name, name.upper(), name.upper(), "NSE", str(i), date(2026, 1, 1))
        for i, name in enumerate(["member", "exiting", "unrelated"], 1)])
    market.create_universe_snapshot(snapshot_id="snapshot", index_name="NIFTY 500",
        snapshot_date=date(2026, 6, 1), source_url="fixture://membership", raw_csv=b"fixture",
        members=[{"isin": "member", "symbol": "MEMBER", "company_name": "Member",
                  "industry": "IT", "series": "BE"}])
    market.record_exit_eligibility(instrument_id="exiting", isin="exiting", symbol="EXITING",
        decision_date=date(2026, 6, 1), decision_snapshot_id="snapshot", target_session_date=date(2026, 6, 2))
    return market, jobs, MarketRefreshPlanner(db, market, jobs,
        held_instrument_ids=lambda: {"exiting", "unrelated"})


def test_held_exclusions_only_schedule_the_declared_exit_session(tmp_path):
    _, jobs, planner = refresh_fixture(tmp_path)
    result = planner.schedule({"start_date": "2026-06-01", "end_date": "2026-06-10"})
    regular = [jobs.get(job_id) for job_id in result["job_ids"] if job_id not in result["exit_job_ids"]]
    assert [item["symbol"] for job in regular for item in job.payload["items"]] == ["MEMBER"]
    assert len(result["exit_job_ids"]) == 1
    exit_job = jobs.get(result["exit_job_ids"][0])
    assert exit_job.payload == {"symbol": "EXITING", "exchange": "NSE",
        "start_date": "2026-06-02", "end_date": "2026-06-02", "exit_only": True}
    assert planner.schedule({"start_date": "2026-06-01", "end_date": "2026-06-10"})["job_ids"] == result["job_ids"]


def test_later_refresh_does_not_extend_unfilled_exit_coverage(tmp_path):
    _, jobs, planner = refresh_fixture(tmp_path)
    result = planner.schedule({"start_date": "2026-06-03", "end_date": "2026-06-10"})
    assert result["exit_job_ids"] == []
    assert [item["symbol"] for job_id in result["job_ids"] for item in jobs.get(job_id).payload["items"]] == ["MEMBER"]


def replay_fixture(monkeypatch, *, missing_open=False, extra_price=90):
    from src.application import positional_trend_backtest as replay
    days = ["2026-06-04", "2026-06-05", "2026-06-08", "2026-06-09"]
    prices = [100, 100, extra_price, 200]
    rows = [{"as_of_date": day, "open": price, "high": price,
             "low": price, "close": price, "volume": 100,
             "snapshot_id": f"price-{day}"} for day, price in zip(days, prices)]
    if missing_open:
        rows = [row for row in rows if row["as_of_date"] != days[2]]
    def features(_history, _sessions, symbol, _rules):
        assert all(row["as_of_date"] <= days[1] for row in _history)
        return [{"symbol": symbol, "signal_date": days[0], "close": 100,
                 "adx14": 30, "adv30": 200_000_000, "initial_stop_anchor": 90,
                 "filtered": True, "exit_signal": False}]
    monkeypatch.setattr(replay, "feature_series", features)
    membership = {day: {"snapshot_id": "before" if day == days[0] else "after",
                       "symbols": ["TEST"] if day == days[0] else []} for day in days}
    # The purchase opens on Friday using Thursday's signal; membership removal
    # is assessed after Friday's daily analysis. Preserve Friday entry for this
    # fixture by reporting Friday membership until the close decision explicitly.
    membership[days[1]]["symbols"] = ["TEST"]
    return replay, days, rows, membership


def test_universe_exit_uses_next_observed_session_and_reports_provenance(monkeypatch):
    replay, days, rows, membership = replay_fixture(monkeypatch)
    # Include a Thursday signal, Friday entry, Monday removal and Tuesday exit.
    membership[days[2]]["symbols"] = []
    monkeypatch.setattr(replay, "feature_series", lambda *_: [{"symbol": "TEST",
        "signal_date": days[0], "close": 100, "adx14": 30, "adv30": 200_000_000,
        "initial_stop_anchor": 90, "filtered": True, "exit_signal": False}])
    result = replay.simulate({"share": ("TEST", rows)}, days,
        policy=replay.Policy(initial_capital=10_000), start_date=days[0], end_date=days[-1],
        membership_by_day=membership)
    sell = result["fills"][-1]
    assert sell["date"] == days[3]
    assert sell["price"] == 200
    assert sell["decision_date"] == days[2]
    assert sell["target_execution_session"] == days[3]
    assert sell["exit_reason"] == "universe_exit"
    assert sell["universe_snapshot_id"] == "after"
    assert sell["price_source"] == f"price-{days[3]}"
    assert sell["fill_status"] == "FILLED"


def test_extra_exit_session_does_not_change_prior_valuation_or_allow_entries(monkeypatch):
    replay, days, rows, membership = replay_fixture(monkeypatch)
    # A daily exit decision on Friday executes at Monday's opening price.
    def features(history, sessions, symbol, rules):
        assert all(row["as_of_date"] <= days[1] for row in history)
        return [{"symbol": symbol, "signal_date": day, "close": 100,
                 "adx14": 30, "adv30": 200_000_000, "initial_stop_anchor": 90,
                 "filtered": index == 0, "exit_signal": index == 1}
                for index, day in enumerate(days[:2])]
    monkeypatch.setattr(replay, "feature_series", features)
    result = replay.simulate({"share": ("TEST", rows)}, days,
        policy=replay.Policy(initial_capital=10_000), start_date=days[0], end_date=days[1],
        membership_by_day=membership)
    assert [fill["date"] for fill in result["fills"]] == [days[1], days[2]]
    assert [point["date"] for point in result["equity_curve"]] == days[:2]
    assert result["performance"]["final_equity"] == pytest.approx(9997.5)
    assert result["performance"]["open_positions"] == 1
    assert result["holdings_after_exit_session"] == {}


def test_missing_target_open_is_reported_without_using_a_later_price(monkeypatch):
    replay, days, rows, membership = replay_fixture(monkeypatch)
    rows = [row for row in rows if row["as_of_date"] != days[3]]
    rows.append({"as_of_date": "2026-06-10", "open": 500, "high": 500,
                 "low": 500, "close": 500, "volume": 100})
    days.append("2026-06-10")
    membership[days[-1]] = {"snapshot_id": "after", "symbols": []}
    monkeypatch.setattr(replay, "feature_series", lambda *_: [{"symbol": "TEST",
        "signal_date": days[0], "close": 100, "adx14": 30, "adv30": 200_000_000,
        "initial_stop_anchor": 90, "filtered": True, "exit_signal": False}])
    result = replay.simulate({"share": ("TEST", rows)}, days,
        policy=replay.Policy(initial_capital=10_000), start_date=days[0], end_date=days[-1],
        membership_by_day=membership)
    assert [fill["side"] for fill in result["fills"]] == ["BUY"]
    assert result["exit_records"][0]["fill_status"] == "MISSING_OPEN"
    assert result["exit_records"][0]["target_execution_session"] == "2026-06-09"


def test_snapshot_replay_loads_historical_non_eq_members_and_earliest_fallback(tmp_path):
    from src.application.positional_trend_backtest import load_snapshot_universe
    db = tmp_path / "system.db"
    market = MarketRepository(db)
    market.upsert_instruments([TrackedInstrument(name, name.upper(), name.upper(), "NSE", str(index), date(2026, 1, 1))
        for index, name in enumerate(["old", "new"], 1)])
    for snapshot, day, isin, series in [("first", date(2026, 6, 5), "OLD", "BE"),
                                      ("second", date(2026, 6, 8), "NEW", "BZ")]:
        market.create_universe_snapshot(snapshot_id=snapshot, index_name="NIFTY 500",
            snapshot_date=day, source_url="fixture://membership", raw_csv=snapshot.encode(),
            members=[{"isin": isin, "symbol": isin, "company_name": isin,
                      "industry": "IT", "series": series}])
    for name in ["old", "new"]:
        market.upsert_bars(name, [NormalizedBar(name, day, Decimal(100), Decimal(100),
            Decimal(100), Decimal(100), 100) for day in [date(2026, 6, 4), date(2026, 6, 5),
                date(2026, 6, 8), date(2026, 6, 9)]], "source")
    histories, sessions, coverage = load_snapshot_universe(db, end_date="2026-06-08")
    assert set(histories) == {"old", "new"}
    assert coverage["membership_by_day"]["2026-06-04"]["symbols"] == ["OLD"]
    assert coverage["membership_by_day"]["2026-06-04"]["earliest_fallback"] is True
    assert coverage["membership_by_day"]["2026-06-08"]["symbols"] == ["NEW"]
    assert coverage["exit_only_session"] == "2026-06-09"
    assert sessions[-1] == "2026-06-09"


def test_universe_download_rejects_backdated_current_source_without_network(tmp_path):
    from src.application.universe_jobs import UniverseJobs
    class Client:
        def nifty_500_csv(self):
            raise AssertionError("a backdated current-source download must not occur")
    service = UniverseJobs(MarketRepository(tmp_path / "system.db"), Client(),
                           collection_date=lambda: date(2026, 6, 5))
    from src.platform_kernel import DomainValidationError
    with pytest.raises(DomainValidationError, match="actual collection date"):
        service.download_nifty500_constituents({"snapshot_date": "2026-06-04"})


def test_concurrent_universe_collectors_use_the_first_committed_identity(tmp_path, monkeypatch):
    from src.application.universe_jobs import UniverseJobs
    market = MarketRepository(tmp_path / "system.db")
    day = date(2026, 6, 5)
    create = market.create_universe_snapshot
    def competing_collection(**payload):
        create(snapshot_id="winner", index_name="NIFTY 500", snapshot_date=day,
            source_url="fixture://winner", raw_csv=b"winner",
            members=[{"isin": "WINNER", "symbol": "WINNER", "company_name": "Winner",
                      "industry": "IT", "series": "EQ"}])
        return create(**payload)
    monkeypatch.setattr(market, "create_universe_snapshot", competing_collection)
    class Client:
        def nifty_500_csv(self):
            return "fixture://loser", b"Company Name,Industry,Symbol,Series,ISIN Code\nLoser,IT,LOSER,BE,LOSER\n"
    result = UniverseJobs(market, Client(), collection_date=lambda: day).download_nifty500_constituents({})
    assert result["snapshot_id"] == "winner"
    assert market.universe_snapshot_members(result["snapshot_id"])[0]["isin"] == "WINNER"


def test_later_normal_price_gap_does_not_complete_missing_ex_date_monitoring(tmp_path):
    market, service = corporate_fixture(tmp_path)
    rows = provider_rows()
    rows[1]["as_of_date"] = "2026-06-25"
    before = market.bars("share")
    result = service.verify_with_kite("event", lambda *_: rows)
    assert result["state"] == "MONITORING"
    assert result["outcome"] == "incomplete_ex_date_window"
    assert market.bars("share") == before


def test_split_processing_uses_verified_provider_history_before_local_factor(tmp_path):
    market, service = corporate_fixture(tmp_path, action="SPLIT")
    # Source event is newly detected; stored history shows the old basis across
    # the ex-date while Kite returns the factor-adjusted pre-ex history.
    market.upsert_bars("share", [NormalizedBar("share", date(2026, 6, 15),
        Decimal(98), Decimal(98), Decimal(98), Decimal(98), 100)], "raw-ex-date")
    market.transition_corporate_action("event", "DETECTED")
    result = service.process_actionable(lambda *_: provider_rows())
    assert result["results"][0]["state"] == "VERIFIED"
    assert market.bars("share")[0]["close"] == "100"
    assert market.corporate_action_event("event")["applied_factor"] is None


def test_repeated_detection_resolves_missing_identity_without_resetting_state(tmp_path):
    market, _ = corporate_fixture(tmp_path)
    unresolved = {"event_id": "unresolved", "instrument_id": None, "isin": "OTHER",
        "symbol": "OTHER", "action_type": "RIGHTS", "ex_date": "2026-06-15",
        "raw_source_json": "{}", "state": "MONITORING"}
    market.upsert_corporate_action_event(unresolved)
    market.upsert_corporate_action_event({**unresolved, "instrument_id": "share", "state": "DETECTED"})
    event = market.corporate_action_event("unresolved")
    assert event["instrument_id"] == "share"
    assert event["state"] == "MONITORING"


def test_unknown_future_exit_session_remains_pending_until_benchmark_evidence(tmp_path):
    from src.application.universe_jobs import UniverseJobs
    market, jobs, planner = refresh_fixture(tmp_path)
    records = UniverseJobs(market)._record_exit_eligibility(
        [{"isin": "UNRELATED", "symbol": "UNRELATED"}], date(2026, 6, 5), "snapshot")
    assert records[0]["target_session"] is None
    assert records[0]["status"] == "missing_session"
    planned = planner.schedule({"start_date": "2026-06-05", "end_date": "2026-06-10"})
    assert planned["pending_exit_sessions"][0]["instrument_id"] == "unrelated"
    market.upsert_instruments([TrackedInstrument("benchmark", "INDEX:NIFTY 500", "NIFTY 500",
        "NSE", "500", date(2026, 6, 8))])
    market.upsert_bars("benchmark", [NormalizedBar("benchmark", date(2026, 6, 8),
        Decimal(100), Decimal(100), Decimal(100), Decimal(100), 0)], "benchmark-source")
    planned = planner.schedule({"start_date": "2026-06-05", "end_date": "2026-06-10"})
    assert planned["pending_exit_sessions"] == []
    exit_job = jobs.get(planned["exit_job_ids"][0])
    assert exit_job.payload["symbol"] == "UNRELATED"
    assert exit_job.payload["start_date"] == exit_job.payload["end_date"] == "2026-06-08"
    resolved = next(row for row in market.exit_eligible_instruments() if row["instrument_id"] == "unrelated")
    assert resolved["session_source"] == "observed_market"


def test_broker_receipt_recovery_uses_the_same_stable_tag_as_submission(tmp_path):
    from src.application.kite_auth import KiteCredentials
    from src.execution_gateway.broker import KiteExecutionGateway
    token = tmp_path / "token"
    token.write_text("fixture-token")
    class Client:
        def set_access_token(self, value):
            assert value == "fixture-token"
        def place_order(self, **payload):
            self.tag = payload["tag"]
            return "receipt"
        def orders(self):
            return [{"tag": self.tag, "order_id": "receipt"}]
    client = Client()
    gateway = KiteExecutionGateway(KiteCredentials("key", "secret"), token, enabled=True,
        client_factory=lambda **_: client, allowed_accounts=["account"], allowed_instruments=["share"])
    gateway.arm()
    order = {"account_id": "account", "instrument_id": "share", "idempotency_key": "retry",
        "exchange": "NSE", "symbol": "SHARE", "side": "BUY", "quantity": 1, "order_type": "MARKET"}
    assert gateway.submit_order(order) == gateway.find_order(order) == "receipt"
    assert gateway._order_tag({**order, "order_id": "existing-order-id"}) == "existingorderid"


def test_existing_exit_rows_survive_nullable_target_migration(tmp_path):
    from src.application.sqlite import sqlite_connection
    market, _, _ = refresh_fixture(tmp_path)
    before = market.exit_eligible_instruments()[0]
    with sqlite_connection(market.path) as connection:
        connection.execute("""CREATE TABLE legacy_exits (
            instrument_id TEXT NOT NULL, isin TEXT NOT NULL, symbol TEXT NOT NULL,
            decision_date TEXT NOT NULL, decision_snapshot_id TEXT NOT NULL,
            target_session_date TEXT NOT NULL, exit_only INTEGER NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(instrument_id,decision_snapshot_id))""")
        connection.execute("""INSERT INTO legacy_exits SELECT instrument_id, isin, symbol,
            decision_date, decision_snapshot_id, target_session_date, exit_only, created_at
            FROM universe_exit_eligibility""")
        connection.execute("DROP TABLE universe_exit_eligibility")
        connection.execute("ALTER TABLE legacy_exits RENAME TO universe_exit_eligibility")
        connection.execute("DELETE FROM system_schema_migrations WHERE namespace='market' AND version>=15")
    upgraded = MarketRepository(market.path)
    after = upgraded.exit_eligible_instruments()[0]
    assert all(after[key] == value for key, value in before.items())
    assert upgraded.record_exit_eligibility(instrument_id="unrelated", isin="UNRELATED",
        symbol="UNRELATED", decision_date=date(2026, 6, 5), decision_snapshot_id="snapshot",
        target_session_date=None)
    assert next(row for row in upgraded.exit_eligible_instruments() if row["instrument_id"] == "unrelated")["target_session_date"] is None
