"""Phase 3 behavioral tests: corporate action event detection, state machine,
date normalization, ratio parsing, self-adjustment, anomaly monitoring,
double-adjustment prevention, watermark management, and indicator cache invalidation."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from src.application.catalog import ArtifactCatalog
from src.application.corporate_actions import (
    ADJUSTABLE_TYPES,
    ANOMALY_THRESHOLD_PERCENT,
    CorporateActions,
)
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.node_cache import IndicatorNodeCache
from src.application.publication import ArtifactPublisher
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, DomainValidationError


# ── Task 3.1: Schema and event persistence ──

class TestEventPersistence:
    def test_corporate_action_event_upsert_and_query(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        event_id = str(uuid4())
        event = {
            "event_id": event_id, "isin": "INE000000001", "symbol": "TEST",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "ratio_numerator": 1.0, "ratio_denominator": 2.0,
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
            "event_id": str(uuid4()), "isin": "INE000000001", "symbol": "TEST",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "raw_source_json": '{"v": 1}',
        }
        market.upsert_corporate_action_event(event)
        # Same isin+type+date with different event_id
        event2 = {**event, "event_id": str(uuid4()), "raw_source_json": '{"v": 2}'}
        result = market.upsert_corporate_action_event(event2)
        # Conflict update doesn't count as new insert
        assert result is False

    def test_actionable_events_returns_correct_states(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        for state in ("DETECTED", "SELF_ADJUSTED", "MONITORING", "VERIFIED"):
            market.upsert_corporate_action_event({
                "event_id": str(uuid4()), "isin": f"IN{state[:8]}",
                "symbol": state[:4], "action_type": "SPLIT",
                "ex_date": "2026-06-15", "raw_source_json": "{}",
                "state": state,
            })
        actionable = market.actionable_corporate_events()
        states = {str(e["state"]) for e in actionable}
        assert states == {"DETECTED", "SELF_ADJUSTED", "MONITORING"}
        assert "VERIFIED" not in states

    def test_state_transition_increments_attempt_count(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "isin": "IN123", "symbol": "X",
            "action_type": "BONUS", "ex_date": "2026-07-01",
            "raw_source_json": "{}",
        })
        market.transition_corporate_action(eid, "SELF_ADJUSTED", attempt_outcome="ok", applied_factor=0.5)
        event = market.corporate_action_event(eid)
        assert event["state"] == "SELF_ADJUSTED"
        assert event["attempt_count"] == 1
        assert event["applied_factor"] == 0.5
        # Second transition
        market.transition_corporate_action(eid, "VERIFIED", attempt_outcome="verified")
        event = market.corporate_action_event(eid)
        assert event["state"] == "VERIFIED"
        assert event["attempt_count"] == 2
        assert event["verified_at"] is not None

    def test_invalid_state_transition_raises(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "isin": "IN456", "symbol": "Y",
            "action_type": "SPLIT", "ex_date": "2026-07-01",
            "raw_source_json": "{}",
        })
        with pytest.raises(DomainValidationError, match="invalid CA state"):
            market.transition_corporate_action(eid, "INVALID_STATE")


# ── Task 3.2: Date normalization and ratio parsing ──

class TestDateNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("2026-01-15", date(2026, 1, 15)),
        ("15-Jan-2026", date(2026, 1, 15)),
        ("15/01/2026", date(2026, 1, 15)),
        ("15-01-2026", date(2026, 1, 15)),
        ("", None),
        ("-", None),
        ("invalid", None),
        ("31-Feb-2026", None),
    ])
    def test_normalize_nse_date(self, raw, expected):
        result = CorporateActions.normalize_nse_date(raw)
        assert result == expected


class TestRatioParsing:
    @pytest.mark.parametrize("raw,action_type,expected", [
        ("1:2", "SPLIT", (1.0, 2.0)),
        ("5:1", "SPLIT", (5.0, 1.0)),
        ("1 : 10", "SPLIT", (1.0, 10.0)),
        ("1 For 2", "BONUS", (1.0, 2.0)),
        ("2", "SPLIT", (2.0, 1.0)),
        ("3", "BONUS", (1.0, 3.0)),
        ("-", "SPLIT", None),
        ("", "SPLIT", None),
        ("1:2", "RIGHTS", None),  # non-adjustable type
    ])
    def test_parse_ratio(self, raw, action_type, expected):
        result = CorporateActions.parse_ratio(raw, action_type)
        assert result == expected


class TestActionClassification:
    @pytest.mark.parametrize("raw,expected", [
        ("Bonus", "BONUS"),
        ("Stock Split", "SPLIT"),
        ("Rights Issue", "RIGHTS"),
        ("Demerger", "DEMERGER"),
        ("Scheme of Arrangement", "DEMERGER"),
        ("Dividend", "DIVIDEND"),
        ("Delisting", "DELISTING"),
    ])
    def test_classify_action_type(self, raw, expected):
        assert CorporateActions.classify_action_type(raw) == expected


# ── Task 3.2: Event detection from source records ──

class TestEventDetection:
    def test_detect_events_from_valid_records(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        market.upsert_instruments([
            TrackedInstrument("inst-1", "INE001", "RELIANCE", "NSE", "1", date(2026, 1, 1)),
        ])
        ca = CorporateActions(database, market, publisher)
        result = ca.detect_events([
            {"symbol": "RELIANCE", "isin": "INE001", "ex_date": "2026-06-15",
             "action_type": "Bonus", "ratio": "1:1"},
        ])
        assert result["detected"] == 1
        assert result["events"][0]["action_type"] == "BONUS"
        assert result["events"][0]["ratio_numerator"] == 1.0
        assert result["events"][0]["instrument_id"] == "inst-1"

    def test_detect_events_skips_invalid_dates(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        ca = CorporateActions(database, market, publisher)
        result = ca.detect_events([
            {"symbol": "X", "isin": "INE999", "ex_date": "invalid",
             "action_type": "Split", "ratio": "1:2"},
        ])
        assert result["detected"] == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "invalid_date"

    def test_detect_events_classifies_rights_as_monitoring(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        ca = CorporateActions(database, market, publisher)
        result = ca.detect_events([
            {"symbol": "X", "isin": "INE999", "ex_date": "2026-06-15",
             "action_type": "Rights Issue", "ratio": "-"},
        ])
        assert result["detected"] == 1
        assert result["events"][0]["state"] == "MONITORING"


# ── Task 3.1: Watermark management ──

class TestWatermark:
    def test_watermark_advances_monotonically(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        assert market.corporate_action_watermark() is None
        market.advance_corporate_action_watermark(date(2026, 6, 1))
        assert market.corporate_action_watermark() == date(2026, 6, 1)
        # Advance forward
        market.advance_corporate_action_watermark(date(2026, 6, 15))
        assert market.corporate_action_watermark() == date(2026, 6, 15)
        # Cannot go backward
        market.advance_corporate_action_watermark(date(2026, 6, 10))
        assert market.corporate_action_watermark() == date(2026, 6, 15)


# ── Task 3.4: Self-adjustment ──

class TestSelfAdjustment:
    def test_split_self_adjustment_scales_pre_ex_bars(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        node_cache = IndicatorNodeCache(database)
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        # Insert pre-ex bars
        market.upsert_bars(inst_id, [
            NormalizedBar(inst_id, date(2026, 5, 1), Decimal(200), Decimal(210), Decimal(190), Decimal(200), 100),
            NormalizedBar(inst_id, date(2026, 5, 2), Decimal(210), Decimal(220), Decimal(200), Decimal(210), 100),
        ], "snap-1")
        # Insert post-ex bar
        market.upsert_bars(inst_id, [
            NormalizedBar(inst_id, date(2026, 6, 16), Decimal(105), Decimal(110), Decimal(100), Decimal(105), 200),
        ], "snap-2")
        # Insert indicator cache entry
        node_cache.put("test_hash", inst_id, date(2026, 5, 1), 42.0, "snap-test")
        ca = CorporateActions(database, market, publisher, node_cache=node_cache)
        # Detect and persist the split event
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "instrument_id": inst_id,
            "isin": "INE001", "symbol": "ABC",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "ratio_numerator": 1.0, "ratio_denominator": 2.0,
            "raw_source_json": '{"test": true}', "state": "DETECTED",
        })
        result = ca.apply_self_adjustment(eid)
        assert result["state"] == "SELF_ADJUSTED"
        assert result["factor"] == 0.5  # 1:2 split = divide by 2
        assert result["adjusted_bars"] == 2  # two pre-ex bars
        # Verify bars were scaled
        bars = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        assert float(bars[0]["close"]) == pytest.approx(100.0, rel=0.01)  # 200 * 0.5
        # Verify post-ex bar unchanged
        bars_post = market.bars(inst_id, date(2026, 6, 16), date(2026, 6, 16))
        assert float(bars_post[0]["close"]) == pytest.approx(105.0, rel=0.01)
        # Verify indicator cache was invalidated
        assert node_cache.get("test_hash", inst_id, date(2026, 5, 1)) is None
        # Verify event state
        event = market.corporate_action_event(eid)
        assert event["state"] == "SELF_ADJUSTED"
        assert event["applied_factor"] == 0.5

    def test_self_adjustment_rejects_non_detected_state(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        ca = CorporateActions(database, market, publisher)
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "isin": "IN123", "symbol": "X",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "raw_source_json": "{}", "state": "VERIFIED",
        })
        with pytest.raises(DomainValidationError, match="not in DETECTED state"):
            ca.apply_self_adjustment(eid)


# ── Task 3.4: No double adjustment ──

class TestDoubleAdjustmentPrevention:
    def test_cannot_self_adjust_already_adjusted_event(self, tmp_path):
        """Phase 3 Task 3.8: Crash/retry cannot double-adjust."""
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        market.upsert_bars(inst_id, [
            NormalizedBar(inst_id, date(2026, 5, 1), Decimal(200), Decimal(210), Decimal(190), Decimal(200), 100),
        ], "snap-1")
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "instrument_id": inst_id,
            "isin": "INE001", "symbol": "ABC",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "ratio_numerator": 1.0, "ratio_denominator": 2.0,
            "raw_source_json": "{}", "state": "DETECTED",
        })
        ca = CorporateActions(database, market, publisher)
        # First adjustment succeeds
        ca.apply_self_adjustment(eid)
        bars = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        first_close = float(bars[0]["close"])
        # Second attempt rejects because state is now SELF_ADJUSTED
        with pytest.raises(DomainValidationError, match="not in DETECTED state"):
            ca.apply_self_adjustment(eid)
        # Price remains at single-adjusted level
        bars_after = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        assert float(bars_after[0]["close"]) == pytest.approx(first_close)


# ── Task 3.5: Verification with Kite ──

class TestKiteVerification:
    def test_verify_transitions_self_adjusted_to_verified(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "instrument_id": inst_id,
            "isin": "INE001", "symbol": "ABC",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "ratio_numerator": 1.0, "ratio_denominator": 2.0,
            "raw_source_json": "{}", "state": "SELF_ADJUSTED",
        })
        ca = CorporateActions(database, market, publisher)
        # Mock fetch_bars_fn that returns bars
        def mock_fetch(instrument_id, start, end):
            return [
                {"as_of_date": "2026-06-14", "open": "100", "high": "110", "low": "90", "close": "100"},
                {"as_of_date": "2026-06-15", "open": "100", "high": "110", "low": "95", "close": "105"},
            ]
        result = ca.verify_with_kite(eid, mock_fetch)
        assert result["state"] == "VERIFIED"
        event = market.corporate_action_event(eid)
        assert event["verified_at"] is not None

    def test_verify_without_provider_stays_actionable(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "instrument_id": inst_id,
            "isin": "INE001", "symbol": "ABC",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "raw_source_json": "{}", "state": "SELF_ADJUSTED",
        })
        ca = CorporateActions(database, market, publisher)
        result = ca.verify_with_kite(eid, fetch_bars_fn=None)
        assert result["outcome"] == "no_provider"
        event = market.corporate_action_event(eid)
        assert event["state"] == "SELF_ADJUSTED"  # remains actionable


# ── Task 3.6: Monitoring with anomaly detection ──

class TestAnomalyMonitoring:
    def test_rights_event_is_monitored_not_adjusted(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "instrument_id": inst_id,
            "isin": "INE001", "symbol": "ABC",
            "action_type": "RIGHTS", "ex_date": "2026-06-15",
            "raw_source_json": "{}", "state": "MONITORING",
        })
        ca = CorporateActions(database, market, publisher)
        # Bars with no anomaly (< 15% gap)
        def mock_fetch_no_anomaly(iid, start, end):
            return [
                {"as_of_date": "2026-06-14", "open": "100", "high": "110", "low": "90", "close": "100"},
                {"as_of_date": "2026-06-15", "open": "98", "high": "105", "low": "95", "close": "99"},
            ]
        result = ca.verify_with_kite(eid, mock_fetch_no_anomaly)
        assert result["state"] == "VERIFIED"
        assert result["outcome"] == "monitoring_resolved"

    def test_anomaly_keeps_monitoring_state(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "instrument_id": inst_id,
            "isin": "INE001", "symbol": "ABC",
            "action_type": "RIGHTS", "ex_date": "2026-06-15",
            "raw_source_json": "{}", "state": "MONITORING",
        })
        ca = CorporateActions(database, market, publisher)
        # Bars with >15% gap
        def mock_fetch_anomaly(iid, start, end):
            return [
                {"as_of_date": "2026-06-14", "open": "100", "high": "110", "low": "90", "close": "100"},
                {"as_of_date": "2026-06-15", "open": "80", "high": "85", "low": "75", "close": "82"},
            ]
        result = ca.verify_with_kite(eid, mock_fetch_anomaly)
        assert result["state"] == "MONITORING"
        assert result["outcome"] == "anomaly_present"
        assert result["discrepancy_pct"] > ANOMALY_THRESHOLD_PERCENT


# ── Task 3.7: Indicator cache invalidation ──

class TestIndicatorRebuild:
    def test_self_adjustment_invalidates_indicator_cache(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        node_cache = IndicatorNodeCache(database)
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        market.upsert_bars(inst_id, [
            NormalizedBar(inst_id, date(2026, 5, 1), Decimal(200), Decimal(210), Decimal(190), Decimal(200), 100),
        ], "snap-1")
        # Seed cache
        node_cache.put("ema50", inst_id, date(2026, 5, 1), 195.0, "snap-calc")
        node_cache.put("adx14", inst_id, date(2026, 5, 1), 30.0, "snap-calc")
        assert node_cache.get("ema50", inst_id, date(2026, 5, 1)) is not None
        eid = str(uuid4())
        market.upsert_corporate_action_event({
            "event_id": eid, "instrument_id": inst_id,
            "isin": "INE001", "symbol": "ABC",
            "action_type": "SPLIT", "ex_date": "2026-06-15",
            "ratio_numerator": 1.0, "ratio_denominator": 2.0,
            "raw_source_json": "{}", "state": "DETECTED",
        })
        ca = CorporateActions(database, market, publisher, node_cache=node_cache)
        ca.apply_self_adjustment(eid)
        # All cached indicators for this instrument should be gone
        assert node_cache.get("ema50", inst_id, date(2026, 5, 1)) is None
        assert node_cache.get("adx14", inst_id, date(2026, 5, 1)) is None


# ── Task 3.4: Price factor operations ──

class TestPriceFactorRepository:
    def test_apply_price_factor_scales_pre_ex_bars_only(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        market.upsert_bars(inst_id, [
            NormalizedBar(inst_id, date(2026, 5, 1), Decimal(100), Decimal(110), Decimal(90), Decimal(100), 50),
            NormalizedBar(inst_id, date(2026, 6, 15), Decimal(50), Decimal(55), Decimal(45), Decimal(50), 200),
        ], "snap-1")
        count = market.apply_price_factor(inst_id, date(2026, 6, 15), 0.5)
        assert count == 1  # only pre-ex bar
        bars = market.bars(inst_id, date(2026, 5, 1), date(2026, 5, 1))
        assert float(bars[0]["close"]) == pytest.approx(50.0, rel=0.01)
        # Post-ex bar untouched
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
        market.upsert_instruments([TrackedInstrument(inst_id, "INE001", "ABC", "NSE", "1", date(2026, 1, 1))])
        assert market.market_history_revision(inst_id) == "0"
        rev1 = market.bump_market_history_revision(inst_id)
        assert rev1 == "1"
        rev2 = market.bump_market_history_revision(inst_id)
        assert rev2 == "2"


# ── Task 3.4: Adjustment factor computation ──

class TestAdjustmentFactorComputation:
    def test_split_factor(self):
        ca = CorporateActions.__new__(CorporateActions)
        # 1:2 split = each old share becomes 2, pre-ex price * 0.5
        assert ca.compute_adjustment_factor("SPLIT", 1.0, 2.0) == pytest.approx(0.5)
        # 10:1 split (reverse split) = 10 old become 1, pre-ex price * 10
        assert ca.compute_adjustment_factor("SPLIT", 10.0, 1.0) == pytest.approx(10.0)

    def test_bonus_factor(self):
        ca = CorporateActions.__new__(CorporateActions)
        # 1:1 bonus = 1 free for each 1 held = total 2, pre-ex price * 1/2
        assert ca.compute_adjustment_factor("BONUS", 1.0, 1.0) == pytest.approx(0.5)
        # 1:2 bonus = 1 free for each 2 held = total 3, pre-ex price * 2/3
        assert ca.compute_adjustment_factor("BONUS", 1.0, 2.0) == pytest.approx(2.0/3.0)

    def test_non_adjustable_returns_none(self):
        ca = CorporateActions.__new__(CorporateActions)
        assert ca.compute_adjustment_factor("RIGHTS", 1.0, 1.0) is None
        assert ca.compute_adjustment_factor("DEMERGER", 1.0, 1.0) is None


# ── Legacy backward compat ──

class TestLegacyBackwardCompat:
    def test_legacy_record_still_works(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        inst_id = str(uuid4())
        market.upsert_instruments([TrackedInstrument(inst_id, "INE000000001", "ABC", "NSE", "1", date(2026, 1, 1))])
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
        market.upsert_bars(inst_id, [NormalizedBar(inst_id, date(2026, 1, 1), Decimal(100), Decimal(110), Decimal(90), Decimal(100), 10)], "raw-1")
        ca = CorporateActions(database, market, publisher)
        result = ca.record({"instrument_id": inst_id, "effective_date": "2026-01-02", "action_type": "SPLIT", "ratio": "2", "amount": "0"})
        assert "action_id" in result
        adjusted = ca.adjusted_bars(inst_id, date(2026, 1, 1), date(2026, 1, 1))
        assert Decimal(adjusted["bars"][0]["close"]) == Decimal(50)
