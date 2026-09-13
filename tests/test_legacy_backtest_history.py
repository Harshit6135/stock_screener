import json
from datetime import UTC, datetime

from src.application.backtest_jobs import BacktestJobs
from src.application.catalog import ArtifactCatalog
from src.application.publication import ArtifactPublisher
from src.application.sqlite import sqlite_connection
from src.platform_kernel import ArtifactStore


def test_legacy_history_readback_is_digest_checked_and_read_only(tmp_path):
    folder = tmp_path / "history" / "20260101_1"
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps({"return": 1}), encoding="utf-8")
    (folder / "equity_curve.json").write_text("[]", encoding="utf-8")
    (folder / "trades.json").write_text("[]", encoding="utf-8")
    (folder / "report.txt").write_text("legacy", encoding="utf-8")
    jobs = object.__new__(BacktestJobs)
    listing = jobs.legacy_runs(tmp_path / "history")
    assert listing[0]["legacy_id"] == "20260101_1"
    detail = jobs.legacy_run("20260101_1", tmp_path / "history")
    assert detail["read_only"] is True
    assert detail["report"] == "legacy"


def test_legacy_trade_comparison_is_read_only_and_canonical(tmp_path):
    folder = tmp_path / "history" / "20260101_2"
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text("{}", encoding="utf-8")
    (folder / "equity_curve.json").write_text("[]", encoding="utf-8")
    (folder / "trades.json").write_text(json.dumps([{"symbol": "ABC", "side": "BUY", "date": "2026-01-02", "units": 2}]), encoding="utf-8")
    (folder / "report.txt").write_text("legacy", encoding="utf-8")
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    publisher.publish_json("runs/backtests", "v4-artifact", {"fills": [{"instrument_id": "ABC", "side": "BUY", "as_of_date": "2026-01-02", "units": 2}]})
    jobs = BacktestJobs(database, None, None, publisher)
    with sqlite_connection(database) as connection:
        connection.execute("INSERT INTO backtest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("v4-run", "v4-artifact", "strategy1", "2026-01-02", "2026-01-02", "fp", "0", "0", datetime.now(UTC).isoformat()))
    comparison = jobs.compare_legacy("20260101_2", "v4-run", tmp_path / "history")
    assert comparison["matched_trade_count"] == 1
    assert comparison["read_only"] is True
    published = jobs.publish_legacy_comparison("20260101_2", "v4-run", tmp_path / "history")
    manifest, readback = publisher.store.read_json("runs/backtest-parity", published["parity_artifact_id"])
    assert manifest.upstream_ids == ("v4-artifact",)
    assert readback["matched_trade_count"] == 1
    assert jobs.publish_legacy_comparison("20260101_2", "v4-run", tmp_path / "history")["parity_artifact_id"] == published["parity_artifact_id"]


def test_backtest_rejects_unknown_historical_universe_snapshot(tmp_path):
    from pytest import raises

    from src.application.market_repository import MarketRepository
    from src.application.research_jobs import ResearchJobs
    from src.platform_kernel import DomainValidationError

    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    jobs = BacktestJobs(database, MarketRepository(database), ResearchJobs(database, MarketRepository(database), publisher), publisher)
    with raises(DomainValidationError, match="universe snapshot"):
        jobs.execute({"strategy_id": "strategy1", "start_date": "2026-09-10", "end_date": "2026-09-11", "starting_cash": "1000", "max_positions": 1, "universe_snapshot_id": "missing"})


def test_backtest_stress_command_bounds_scenarios(tmp_path):
    from pytest import raises

    from src.platform_kernel import DomainValidationError

    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    jobs = BacktestJobs(database, None, None, publisher)
    with raises(DomainValidationError, match="stress scenarios"):
        jobs.stress({"base": {}, "scenarios": []})


def test_walk_forward_validates_rolling_windows(tmp_path):
    from pytest import raises

    from src.platform_kernel import DomainValidationError

    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    jobs = BacktestJobs(database, None, None, publisher)
    with raises(DomainValidationError, match="chronological"):
        jobs.walk_forward({
            "base": {"strategy_id": "strategy1"},
            "windows": [{
                "name": "bad",
                "train_start": "2026-01-02",
                "train_end": "2026-02-01",
                "test_start": "2026-01-15",
                "test_end": "2026-02-15",
            }],
        })


def test_walk_forward_publishes_and_replays_immutable_report(tmp_path, monkeypatch):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    jobs = BacktestJobs(database, None, None, publisher)
    monkeypatch.setattr(jobs, "execute", lambda payload: {"run_id": payload["start_date"], "artifact_id": "run-" + payload["start_date"]})
    payload = {
        "base": {"strategy_id": "strategy1"},
        "windows": [{
            "name": "fold-1",
            "train_start": "2026-01-02",
            "train_end": "2026-02-01",
            "test_start": "2026-02-02",
            "test_end": "2026-03-02",
        }],
    }
    first = jobs.walk_forward(payload)
    second = jobs.walk_forward(payload)
    assert first == second
    assert first["window_count"] == 1
    assert publisher.store.read_json("runs/backtest-walk-forward", first["walk_forward_id"])[1] == first


def test_backtest_attribution_is_fifo_and_lineaged(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    jobs = BacktestJobs(database, None, None, publisher)
    publisher.publish_json("runs/backtests", "run-artifact", {
        "manifest": {"parameters": {"strategy_id": "strategy1"}},
        "fills": [
            {"instrument_id": "ABC", "side": "BUY", "units": 2, "price": "10", "fee": "0"},
            {"instrument_id": "ABC", "side": "SELL", "units": 1, "price": "12", "fee": "0"},
        ],
    })
    sector = publisher.publish_json("reference/sectors", "sector-artifact", {"as_of_date": "2026-01-01", "values": {"ABC": "TECH"}})
    cap = publisher.publish_json("reference/market-capitalization", "cap-artifact", {"as_of_date": "2026-01-01", "values": {"ABC": "100"}})
    features = publisher.publish_json("features/strategy1", "feature-artifact", {"as_of_date": "2026-01-01", "values": {"ABC": {"factors": {"trend": "1", "momentum": "2"}}}})
    with sqlite_connection(database) as connection:
        connection.execute("INSERT INTO backtest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("run-1", "run-artifact", "strategy1", "2026-01-01", "2026-01-02", "fp", "0", "0", datetime.now(UTC).isoformat()))
    result = jobs.attribute({"run_id": "run-1", "sector_artifact_id": sector.artifact_id, "market_cap_artifact_id": cap.artifact_id, "factor_artifact_id": features.artifact_id})
    assert result["by_sector"]["TECH"] == "2"
    assert set(result["by_factor"]) == {"momentum", "trend"}
    assert set(publisher.store.read_json("runs/backtest-attribution", result["attribution_id"])[0].upstream_ids) == {"run-artifact", "sector-artifact", "cap-artifact", "feature-artifact"}
