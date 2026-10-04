import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domains.indicators import IndicatorNodeCache
from src.domains.market_data import NormalizedBar
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.corporate_actions import ANOMALY_THRESHOLD_PERCENT, CorporateActions
from src.platform_kernel import DomainValidationError


class TestEventPersistence:
    def test_corporate_action_event_upsert_and_query(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        event_id = str(uuid4())
        event = {
            "event_id": event_id,
            "isin": "INE000000001",
            "symbol": "TEST",
            "action_type": "SPLIT",
            "ex_date": "2026-06-15",
            "ratio_numerator": 1.0,
            "ratio_denominator": 2.0,
            "raw_source_json": '{"raw": "data"}',
        }
        assert market.upsert_corporate_action_event(event) is True
        stored = market.corporate_action_event(event_id)
        assert stored is not None
        assert stored["isin"] == "INE000000001"
        assert stored["state"] == "DETECTED"
        assert stored["attempt_count"] == 0

    def test_duplicate_event_updates_raw_json_only(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        event = {
            "event_id": str(uuid4()),
            "isin": "INE000000001",
            "symbol": "TEST",
            "action_type": "SPLIT",
            "ex_date": "2026-06-15",
            "raw_source_json": '{"v": 1}',
        }
        market.upsert_corporate_action_event(event)
        event2 = {**event, "event_id": str(uuid4()), "raw_source_json": '{"v": 2}'}
        result = market.upsert_corporate_action_event(event2)
        assert result is False

    def test_actionable_events_returns_correct_states(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        for state in ("DETECTED", "SELF_ADJUSTED", "MONITORING", "VERIFIED"):
            market.upsert_corporate_action_event(
                {
                    "event_id": str(uuid4()),
                    "isin": f"IN{state[:8]}",
                    "symbol": state[:4],
                    "action_type": "SPLIT",
                    "ex_date": "2026-06-15",
                    "raw_source_json": "{}",
                    "state": state,
                }
            )
        actionable = market.actionable_corporate_events()
        states = {str(e["state"]) for e in actionable}
        assert states == {"DETECTED", "SELF_ADJUSTED", "MONITORING"}
        assert "VERIFIED" not in states

    def test_state_transition_increments_attempt_count(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "isin": "IN123",
                "symbol": "X",
                "action_type": "BONUS",
                "ex_date": "2026-07-01",
                "raw_source_json": "{}",
            }
        )
        market.transition_corporate_action(
            eid, "SELF_ADJUSTED", attempt_outcome="ok", applied_factor=0.5
        )
        event = market.corporate_action_event(eid)
        assert event["state"] == "SELF_ADJUSTED"
        assert event["attempt_count"] == 1
        assert event["applied_factor"] == 0.5
        market.transition_corporate_action(eid, "VERIFIED", attempt_outcome="verified")
        event = market.corporate_action_event(eid)
        assert event["state"] == "VERIFIED"
        assert event["attempt_count"] == 2
        assert event["verified_at"] is not None

    def test_invalid_state_transition_raises(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "isin": "IN456",
                "symbol": "Y",
                "action_type": "SPLIT",
                "ex_date": "2026-07-01",
                "raw_source_json": "{}",
            }
        )
        with pytest.raises(DomainValidationError, match="invalid CA state"):
            market.transition_corporate_action(eid, "INVALID_STATE")


class TestDateNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-01-15", date(2026, 1, 15)),
            ("15-Jan-2026", date(2026, 1, 15)),
            ("15/01/2026", date(2026, 1, 15)),
            ("15-01-2026", date(2026, 1, 15)),
            ("", None),
            ("-", None),
            ("invalid", None),
            ("31-Feb-2026", None),
        ],
    )
    def test_normalize_nse_date(self, raw, expected):
        result = CorporateActions.normalize_nse_date(raw)
        assert result == expected


class TestRatioParsing:
    @pytest.mark.parametrize(
        "raw,action_type,expected",
        [
            ("1:2", "SPLIT", (1.0, 2.0)),
            ("5:1", "SPLIT", (5.0, 1.0)),
            ("1 : 10", "SPLIT", (1.0, 10.0)),
            ("1 For 2", "BONUS", (1.0, 2.0)),
            ("2", "SPLIT", (2.0, 1.0)),
            ("3", "BONUS", (1.0, 3.0)),
            ("-", "SPLIT", None),
            ("", "SPLIT", None),
            ("1:2", "RIGHTS", None),
        ],
    )
    def test_parse_ratio(self, raw, action_type, expected):
        result = CorporateActions.parse_ratio(raw, action_type)
        assert result == expected


class TestActionClassification:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Bonus", "BONUS"),
            ("Stock Split", "SPLIT"),
            ("Rights Issue", "RIGHTS"),
            ("Demerger", "DEMERGER"),
            ("Scheme of Arrangement", "DEMERGER"),
            ("Dividend", "DIVIDEND"),
            ("Delisting", "DELISTING"),
        ],
    )
    def test_classify_action_type(self, raw, expected):
        assert CorporateActions.classify_action_type(raw) == expected


class TestEventDetection:
    def test_detect_events_from_valid_records(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        market.upsert_instruments(
            [TrackedInstrument("inst-1", "INE001", "RELIANCE", "NSE", "1", date(2026, 1, 1))]
        )
        ca = CorporateActions(database, market)
        result = ca.detect_events(
            [
                {
                    "symbol": "RELIANCE",
                    "isin": "INE001",
                    "ex_date": "2026-06-15",
                    "action_type": "Bonus",
                    "ratio": "1:1",
                }
            ]
        )
        assert result["detected"] == 1
        assert result["events"][0]["action_type"] == "BONUS"
        assert result["events"][0]["ratio_numerator"] == 1.0
        assert result["events"][0]["instrument_id"] == "inst-1"

    def test_detect_events_skips_invalid_dates(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        ca = CorporateActions(database, market)
        result = ca.detect_events(
            [
                {
                    "symbol": "X",
                    "isin": "INE999",
                    "ex_date": "invalid",
                    "action_type": "Split",
                    "ratio": "1:2",
                }
            ]
        )
        assert result["detected"] == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "invalid_date"

    def test_detect_events_classifies_rights_as_monitoring(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        ca = CorporateActions(database, market)
        result = ca.detect_events(
            [
                {
                    "symbol": "X",
                    "isin": "INE999",
                    "ex_date": "2026-06-15",
                    "action_type": "Rights Issue",
                    "ratio": "-",
                }
            ]
        )
        assert result["detected"] == 1
        assert result["events"][0]["state"] == "MONITORING"


class TestWatermark:
    def test_watermark_advances_monotonically(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        assert market.corporate_action_watermark() is None
        market.advance_corporate_action_watermark(date(2026, 6, 1))
        assert market.corporate_action_watermark() == date(2026, 6, 1)
        market.advance_corporate_action_watermark(date(2026, 6, 15))
        assert market.corporate_action_watermark() == date(2026, 6, 15)
        market.advance_corporate_action_watermark(date(2026, 6, 10))
        assert market.corporate_action_watermark() == date(2026, 6, 15)


class TestSelfAdjustment:
    def test_split_self_adjustment_scales_pre_ex_bars(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        node_cache = IndicatorNodeCache(database)
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        market.upsert_bars(
            inst_id,
            [
                NormalizedBar(
                    inst_id,
                    date(2026, 5, 1),
                    Decimal(200),
                    Decimal(210),
                    Decimal(190),
                    Decimal(200),
                    100,
                ),
                NormalizedBar(
                    inst_id,
                    date(2026, 5, 2),
                    Decimal(210),
                    Decimal(220),
                    Decimal(200),
                    Decimal(210),
                    100,
                ),
            ],
            "snap-1",
        )
        market.upsert_bars(
            inst_id,
            [
                NormalizedBar(
                    inst_id,
                    date(2026, 6, 15),
                    Decimal(105),
                    Decimal(110),
                    Decimal(100),
                    Decimal(105),
                    200,
                ),
                NormalizedBar(
                    inst_id,
                    date(2026, 6, 16),
                    Decimal(105),
                    Decimal(110),
                    Decimal(100),
                    Decimal(105),
                    200,
                ),
            ],
            "snap-2",
        )
        node_cache.put(
            "test_hash",
            inst_id,
            date(2026, 5, 1),
            42.0,
            "snap-test",
            market_revision="1",
            implementation_revision="test",
        )
        ca = CorporateActions(database, market, node_cache=node_cache)
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "instrument_id": inst_id,
                "isin": "INE001",
                "symbol": "ABC",
                "action_type": "SPLIT",
                "ex_date": "2026-06-15",
                "ratio_numerator": 1.0,
                "ratio_denominator": 2.0,
                "raw_source_json": '{"test": true}',
                "state": "DETECTED",
            }
        )
        result = ca.apply_self_adjustment(eid)
        assert result["state"] == "SELF_ADJUSTED"
        assert result["factor"] == 0.5
        assert result["adjusted_bars"] == 2
        bars = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        assert float(bars[0]["close"]) == pytest.approx(100.0, rel=0.01)
        bars_post = market.bars(inst_id, date(2026, 6, 16), date(2026, 6, 16))
        assert float(bars_post[0]["close"]) == pytest.approx(105.0, rel=0.01)
        assert (
            node_cache.get(
                "test_hash",
                inst_id,
                date(2026, 5, 1),
                market_revision="1",
                implementation_revision="test",
            )
            is None
        )
        event = market.corporate_action_event(eid)
        assert event["state"] == "SELF_ADJUSTED"
        assert event["applied_factor"] == 0.5

    def test_self_adjustment_rejects_non_detected_state(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        ca = CorporateActions(database, market)
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "isin": "IN123",
                "symbol": "X",
                "action_type": "SPLIT",
                "ex_date": "2026-06-15",
                "raw_source_json": "{}",
                "state": "VERIFIED",
            }
        )
        with pytest.raises(DomainValidationError, match="not in DETECTED state"):
            ca.apply_self_adjustment(eid)


class TestDoubleAdjustmentPrevention:
    def test_cannot_self_adjust_already_adjusted_event(self, tmp_path):
        """Phase 3 Task 3.8: Crash/retry cannot double-adjust."""
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        market.upsert_bars(
            inst_id,
            [
                NormalizedBar(
                    inst_id,
                    date(2026, 5, 1),
                    Decimal(200),
                    Decimal(210),
                    Decimal(190),
                    Decimal(200),
                    100,
                ),
                NormalizedBar(
                    inst_id,
                    date(2026, 6, 15),
                    Decimal(100),
                    Decimal(105),
                    Decimal(95),
                    Decimal(100),
                    200,
                ),
            ],
            "snap-1",
        )
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "instrument_id": inst_id,
                "isin": "INE001",
                "symbol": "ABC",
                "action_type": "SPLIT",
                "ex_date": "2026-06-15",
                "ratio_numerator": 1.0,
                "ratio_denominator": 2.0,
                "raw_source_json": "{}",
                "state": "DETECTED",
            }
        )
        ca = CorporateActions(database, market)
        ca.apply_self_adjustment(eid)
        bars = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        first_close = float(bars[0]["close"])
        with pytest.raises(DomainValidationError, match="not in DETECTED state"):
            ca.apply_self_adjustment(eid)
        bars_after = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        assert float(bars_after[0]["close"]) == pytest.approx(first_close)


class TestKiteVerification:
    def test_verify_transitions_self_adjusted_to_verified(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        market.upsert_bars(
            inst_id,
            [
                NormalizedBar(
                    inst_id,
                    date(2026, 6, 14),
                    Decimal(100),
                    Decimal(110),
                    Decimal(90),
                    Decimal(100),
                    100,
                )
            ],
            "self-adjusted-baseline",
        )
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "instrument_id": inst_id,
                "isin": "INE001",
                "symbol": "ABC",
                "action_type": "SPLIT",
                "ex_date": "2026-06-15",
                "ratio_numerator": 1.0,
                "ratio_denominator": 2.0,
                "raw_source_json": "{}",
                "state": "SELF_ADJUSTED",
            }
        )
        ca = CorporateActions(database, market)

        def mock_fetch(instrument_id, start, end):
            return [
                {
                    "as_of_date": "2026-06-14",
                    "open": "100",
                    "high": "110",
                    "low": "90",
                    "close": "100",
                    "volume": 100,
                },
                {
                    "as_of_date": "2026-06-15",
                    "open": "100",
                    "high": "110",
                    "low": "95",
                    "close": "105",
                    "volume": 100,
                },
            ]

        result = ca.verify_with_kite(eid, mock_fetch)
        assert result["state"] == "VERIFIED"
        event = market.corporate_action_event(eid)
        assert event["verified_at"] is not None

    def test_verify_without_provider_stays_actionable(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "instrument_id": inst_id,
                "isin": "INE001",
                "symbol": "ABC",
                "action_type": "SPLIT",
                "ex_date": "2026-06-15",
                "raw_source_json": "{}",
                "state": "SELF_ADJUSTED",
            }
        )
        ca = CorporateActions(database, market)
        result = ca.verify_with_kite(eid, fetch_bars_fn=None)
        assert result["outcome"] == "no_provider"
        event = market.corporate_action_event(eid)
        assert event["state"] == "SELF_ADJUSTED"


class TestAnomalyMonitoring:
    def test_rights_event_is_monitored_not_adjusted(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "instrument_id": inst_id,
                "isin": "INE001",
                "symbol": "ABC",
                "action_type": "RIGHTS",
                "ex_date": "2026-06-15",
                "raw_source_json": "{}",
                "state": "MONITORING",
            }
        )
        ca = CorporateActions(database, market)

        def mock_fetch_no_anomaly(iid, start, end):
            return [
                {
                    "as_of_date": "2026-06-14",
                    "open": "100",
                    "high": "110",
                    "low": "90",
                    "close": "100",
                    "volume": 100,
                },
                {
                    "as_of_date": "2026-06-15",
                    "open": "98",
                    "high": "105",
                    "low": "95",
                    "close": "99",
                    "volume": 100,
                },
            ]

        result = ca.verify_with_kite(eid, mock_fetch_no_anomaly)
        assert result["state"] == "VERIFIED"
        assert result["outcome"] == "monitoring_resolved"

    def test_anomaly_keeps_monitoring_state(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "instrument_id": inst_id,
                "isin": "INE001",
                "symbol": "ABC",
                "action_type": "RIGHTS",
                "ex_date": "2026-06-15",
                "raw_source_json": "{}",
                "state": "MONITORING",
            }
        )
        ca = CorporateActions(database, market)

        def mock_fetch_anomaly(iid, start, end):
            return [
                {
                    "as_of_date": "2026-06-14",
                    "open": "100",
                    "high": "110",
                    "low": "90",
                    "close": "100",
                    "volume": 100,
                },
                {
                    "as_of_date": "2026-06-15",
                    "open": "80",
                    "high": "85",
                    "low": "75",
                    "close": "82",
                    "volume": 100,
                },
            ]

        result = ca.verify_with_kite(eid, mock_fetch_anomaly)
        assert result["state"] == "MONITORING"
        assert result["outcome"] == "anomaly_present"
        assert result["discrepancy_pct"] > ANOMALY_THRESHOLD_PERCENT
        warnings = market.quality_events(
            instrument_id=inst_id, check_type="corporate_action_mismatch", severity="WARNING"
        )
        assert len(warnings) == 1
        assert warnings[0]["detail"]["event_id"] == eid
        assert warnings[0]["detail"]["ex_date"] == "2026-06-15"
        assert ca.verify_with_kite(eid, mock_fetch_anomaly)["state"] == "MONITORING"
        assert (
            len(
                market.quality_events(
                    instrument_id=inst_id,
                    check_type="corporate_action_mismatch",
                    severity="WARNING",
                )
            )
            == 1
        )

        def resolved_history(iid, start, end):
            return [
                {
                    "as_of_date": "2026-06-14",
                    "open": "100",
                    "high": "110",
                    "low": "90",
                    "close": "100",
                    "volume": 100,
                },
                {
                    "as_of_date": "2026-06-15",
                    "open": "98",
                    "high": "105",
                    "low": "95",
                    "close": "99",
                    "volume": 100,
                },
            ]

        assert ca.verify_with_kite(eid, resolved_history)["state"] == "VERIFIED"
        resolved = market.quality_events(
            instrument_id=inst_id, check_type="corporate_action_mismatch", severity="INFO"
        )
        assert len(resolved) == 1
        assert resolved[0]["detail"]["state"] == "VERIFIED"


def test_self_adjustment_skips_already_smooth_prices_and_records_evidence(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
    )
    market.upsert_bars(
        instrument_id,
        [
            NormalizedBar(instrument_id, date(2026, 6, 14), 200, 205, 195, 200, 100),
            NormalizedBar(instrument_id, date(2026, 6, 15), 190, 195, 185, 190, 200),
        ],
        "already-adjusted",
    )
    market.upsert_corporate_action_event(
        {
            "event_id": "event",
            "instrument_id": instrument_id,
            "isin": "INE001",
            "symbol": "ABC",
            "action_type": "SPLIT",
            "ex_date": "2026-06-15",
            "ratio_numerator": 1,
            "ratio_denominator": 2,
            "raw_source_json": "{}",
            "state": "DETECTED",
        }
    )
    service = CorporateActions(database, market)
    before = market.bars(instrument_id)
    result = service.apply_self_adjustment("event")
    assert result["outcome"] == "stored_history_appears_adjusted"
    assert market.corporate_action_event("event")["state"] == "DETECTED"
    assert market.bars(instrument_id) == before
    warnings = market.quality_events(
        instrument_id=instrument_id, check_type="corporate_action_mismatch", severity="INFO"
    )
    assert len(warnings) == 1
    assert warnings[0]["detail"]["pre_close"] == "200"
    assert warnings[0]["detail"]["post_close"] == "190"


def test_self_adjustment_waits_for_exact_ex_date_price(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
    )
    market.upsert_bars(
        instrument_id,
        [
            NormalizedBar(instrument_id, date(2026, 6, 14), 200, 205, 195, 200, 100),
            NormalizedBar(instrument_id, date(2026, 6, 16), 100, 105, 95, 100, 200),
        ],
        "missing-ex-date",
    )
    market.upsert_corporate_action_event(
        {
            "event_id": "event",
            "instrument_id": instrument_id,
            "isin": "INE001",
            "symbol": "ABC",
            "action_type": "SPLIT",
            "ex_date": "2026-06-15",
            "ratio_numerator": 1,
            "ratio_denominator": 2,
            "raw_source_json": "{}",
            "state": "DETECTED",
        }
    )
    service = CorporateActions(database, market)
    before = market.bars(instrument_id)
    result = service.apply_self_adjustment("event")
    assert result["outcome"] == "incomplete_ex_date_window"
    event = market.corporate_action_event("event")
    assert event["state"] == "DETECTED"
    assert json.loads(event["baseline_prices_json"])["post"] is None
    assert market.bars(instrument_id) == before
    warnings = market.quality_events(
        instrument_id=instrument_id, check_type="corporate_action_mismatch", severity="WARNING"
    )
    assert len(warnings) == 1


class TestIndicatorRebuild:
    def test_self_adjustment_invalidates_indicator_cache(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        node_cache = IndicatorNodeCache(database)
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        market.upsert_bars(
            inst_id,
            [
                NormalizedBar(
                    inst_id,
                    date(2026, 5, 1),
                    Decimal(200),
                    Decimal(210),
                    Decimal(190),
                    Decimal(200),
                    100,
                ),
                NormalizedBar(
                    inst_id,
                    date(2026, 6, 15),
                    Decimal(100),
                    Decimal(105),
                    Decimal(95),
                    Decimal(100),
                    200,
                ),
            ],
            "snap-1",
        )
        node_cache.put(
            "ema50",
            inst_id,
            date(2026, 5, 1),
            195.0,
            "snap-calc",
            market_revision="1",
            implementation_revision="test",
        )
        node_cache.put(
            "adx14",
            inst_id,
            date(2026, 5, 1),
            30.0,
            "snap-calc",
            market_revision="1",
            implementation_revision="test",
        )
        assert (
            node_cache.get(
                "ema50",
                inst_id,
                date(2026, 5, 1),
                market_revision="1",
                implementation_revision="test",
            )
            is not None
        )
        eid = str(uuid4())
        market.upsert_corporate_action_event(
            {
                "event_id": eid,
                "instrument_id": inst_id,
                "isin": "INE001",
                "symbol": "ABC",
                "action_type": "SPLIT",
                "ex_date": "2026-06-15",
                "ratio_numerator": 1.0,
                "ratio_denominator": 2.0,
                "raw_source_json": "{}",
                "state": "DETECTED",
            }
        )
        ca = CorporateActions(database, market, node_cache=node_cache)
        ca.apply_self_adjustment(eid)
        assert (
            node_cache.get(
                "ema50",
                inst_id,
                date(2026, 5, 1),
                market_revision="1",
                implementation_revision="test",
            )
            is None
        )
        assert (
            node_cache.get(
                "adx14",
                inst_id,
                date(2026, 5, 1),
                market_revision="1",
                implementation_revision="test",
            )
            is None
        )


class TestPriceFactorRepository:
    def test_apply_price_factor_scales_pre_ex_bars_only(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        market.upsert_bars(
            inst_id,
            [
                NormalizedBar(
                    inst_id,
                    date(2026, 5, 1),
                    Decimal(100),
                    Decimal(110),
                    Decimal(90),
                    Decimal(100),
                    50,
                ),
                NormalizedBar(
                    inst_id,
                    date(2026, 6, 15),
                    Decimal(50),
                    Decimal(55),
                    Decimal(45),
                    Decimal(50),
                    200,
                ),
            ],
            "snap-1",
        )
        count = market.apply_price_factor(inst_id, date(2026, 6, 15), 0.5)
        assert count == 1
        bars = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        assert float(bars[0]["close"]) == pytest.approx(50.0, rel=0.01)
        bars_post = market.bars(inst_id, date(2026, 6, 15), date(2026, 6, 15))
        assert float(bars_post[0]["close"]) == pytest.approx(50.0, rel=0.01)

    def test_apply_price_factor_rejects_invalid_factor(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        with pytest.raises(DomainValidationError, match="positive and reasonable"):
            market.apply_price_factor("x", date(2026, 1, 1), 0)
        with pytest.raises(DomainValidationError, match="positive and reasonable"):
            market.apply_price_factor("x", date(2026, 1, 1), 200)

    def test_bump_revision_increments(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        inst_id = str(uuid4())
        market.upsert_instruments(
            [TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
        )
        assert market.market_history_revision(inst_id) == "0"
        rev1 = market.bump_market_history_revision(inst_id)
        assert rev1 == "1"
        second_revision = market.bump_market_history_revision(inst_id)
        assert second_revision == "2"


class TestAdjustmentFactorComputation:
    def test_split_factor(self):
        ca = CorporateActions.__new__(CorporateActions)
        assert ca.compute_adjustment_factor("SPLIT", 1.0, 2.0) == pytest.approx(0.5)
        assert ca.compute_adjustment_factor("SPLIT", 10.0, 1.0) == pytest.approx(10.0)

    def test_bonus_factor(self):
        ca = CorporateActions.__new__(CorporateActions)
        assert ca.compute_adjustment_factor("BONUS", 1.0, 1.0) == pytest.approx(0.5)
        assert ca.compute_adjustment_factor("BONUS", 1.0, 2.0) == pytest.approx(2.0 / 3.0)

    def test_non_adjustable_returns_none(self):
        ca = CorporateActions.__new__(CorporateActions)
        assert ca.compute_adjustment_factor("RIGHTS", 1.0, 1.0) is None
        assert ca.compute_adjustment_factor("DEMERGER", 1.0, 1.0) is None


def test_unverified_corporate_provider_retries_persist_outcome_and_stay_actionable(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))]
    )
    event_id = str(uuid4())
    market.upsert_corporate_action_event(
        {
            "event_id": event_id,
            "instrument_id": instrument_id,
            "isin": "INE001",
            "symbol": "ABC",
            "action_type": "SPLIT",
            "ex_date": "2026-06-15",
            "ratio_numerator": 1.0,
            "ratio_denominator": 2.0,
            "raw_source_json": "{}",
            "state": "SELF_ADJUSTED",
        }
    )
    actions = CorporateActions(database, market)
    provider_rows = [
        {
            "as_of_date": "2026-06-14",
            "open": "200",
            "high": "201",
            "low": "199",
            "close": "200",
            "volume": 100,
        },
        {
            "as_of_date": "2026-06-15",
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": 100,
        },
    ]
    for attempt in (1, 2):
        result = actions.verify_with_kite(event_id, lambda *_: provider_rows)
        event = market.corporate_action_event(event_id)
        assert result["outcome"] == "provider_history_not_verified"
        assert event["state"] == "SELF_ADJUSTED"
        assert event["attempt_count"] == attempt
        assert event["last_attempt_outcome"] == "provider_history_not_verified"
        assert any(row["event_id"] == event_id for row in market.actionable_corporate_events())
    assert market.bars(instrument_id, date(2026, 6, 14), date(2026, 6, 15)) == []
    market.upsert_bars(
        instrument_id,
        [NormalizedBar(instrument_id, date(2026, 6, 14), 100, 101, 99, 100, 100)],
        "self-adjusted-baseline",
    )
    different_pre_ex = [
        {
            "as_of_date": "2026-06-14",
            "open": "120",
            "high": "121",
            "low": "119",
            "close": "120",
            "volume": 100,
        },
        {
            "as_of_date": "2026-06-15",
            "open": "120",
            "high": "121",
            "low": "119",
            "close": "120",
            "volume": 100,
        },
    ]
    result = actions.verify_with_kite(event_id, lambda *_: different_pre_ex)
    event = market.corporate_action_event(event_id)
    assert result["outcome"] == "provider_adjustment_not_confirmed"
    assert event["state"] == "SELF_ADJUSTED" and event["attempt_count"] == 3
    assert event["last_attempt_outcome"] == "provider_adjustment_not_confirmed"


def provider_rows(post=98):
    return [
        {
            "as_of_date": day,
            "open": str(price),
            "high": str(price),
            "low": str(price),
            "close": str(price),
            "volume": 100,
        }
        for day, price in [("2026-05-01", 100), ("2026-06-15", post)]
    ]


def corporate_fixture(tmp_path, *, action="RIGHTS", threshold=0.15):
    db = tmp_path / "system.db"
    market = MarketRepository(db, price_gap_threshold=threshold)
    market.upsert_instruments(
        [TrackedInstrument("share", "ISIN", "SHARE", "NSE", "1", date(2026, 1, 1))]
    )
    market.upsert_bars(
        "share",
        [
            NormalizedBar(
                "share",
                date(2026, 5, 1),
                Decimal(200),
                Decimal(200),
                Decimal(200),
                Decimal(200),
                100,
            )
        ],
        "original",
    )
    market.upsert_corporate_action_event(
        {
            "event_id": "event",
            "isin": "ISIN",
            "symbol": "SHARE",
            "instrument_id": "share",
            "action_type": action,
            "ex_date": "2026-06-15",
            "raw_source_json": "{}",
            "state": "MONITORING",
            "ratio_numerator": 1.0 if action == "SPLIT" else None,
            "ratio_denominator": 2.0 if action == "SPLIT" else None,
        }
    )
    return market, CorporateActions(db, market)


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
    market.upsert_bars(
        "share",
        [
            NormalizedBar(
                "share", date(2026, 6, 15), Decimal(98), Decimal(98), Decimal(98), Decimal(98), 100
            )
        ],
        "raw-ex-date",
    )
    market.transition_corporate_action("event", "DETECTED")
    result = service.process_actionable(lambda *_: provider_rows())
    assert result["results"][0]["state"] == "VERIFIED"
    assert market.bars("share")[0]["close"] == "100"
    assert market.corporate_action_event("event")["applied_factor"] is None


def test_repeated_detection_resolves_missing_identity_without_resetting_state(tmp_path):
    market, _ = corporate_fixture(tmp_path)
    unresolved = {
        "event_id": "unresolved",
        "instrument_id": None,
        "isin": "OTHER",
        "symbol": "OTHER",
        "action_type": "RIGHTS",
        "ex_date": "2026-06-15",
        "raw_source_json": "{}",
        "state": "MONITORING",
    }
    market.upsert_corporate_action_event(unresolved)
    market.upsert_corporate_action_event(
        {**unresolved, "instrument_id": "share", "state": "DETECTED"}
    )
    event = market.corporate_action_event("unresolved")
    assert event["instrument_id"] == "share"
    assert event["state"] == "MONITORING"
