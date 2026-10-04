"""Corporate-action event detection, processing, and verified Kite refresh.

Supports BONUS/SPLIT with temporary self-adjustment and verified Kite replacement.
RIGHTS/DEMERGER are monitored without local factor adjustment.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.domains.indicators import IndicatorNodeCache
from src.domains.market_data import NormalizedBar
from src.gates.repositories import MarketRepository
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection

logger = logging.getLogger(__name__)


# Phase 3 Task 3.6: anomaly threshold
ANOMALY_THRESHOLD_PERCENT = 15.0

# Action types that receive local price adjustment
ADJUSTABLE_TYPES = frozenset({"BONUS", "SPLIT"})
# Action types that are monitored without local adjustment
MONITORED_TYPES = frozenset({"RIGHTS", "DEMERGER", "SCHEME_OF_ARRANGEMENT"})
ALL_CA_TYPES = ADJUSTABLE_TYPES | MONITORED_TYPES | frozenset({"DIVIDEND", "DELISTING"})

# NSE date formats commonly seen in corporate action feeds
_NSE_DATE_PATTERNS = [
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"),           # ISO: 2026-01-15
    re.compile(r"^(\d{2})-(\w{3})-(\d{4})$"),             # 15-Jan-2026
    re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"),             # 15/01/2026
    re.compile(r"^(\d{2})-(\d{2})-(\d{4})$"),             # 15-01-2026
]
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class CorporateActions:
    def __init__(
        self, database: str | Path, market: MarketRepository,
        node_cache: IndicatorNodeCache | None = None,
    ):
        self.database = Path(database)
        self.market = market
        self.node_cache = node_cache

    # ------------------------------------------------------------------
    # Phase 3: Event-driven corporate action processing
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_nse_date(raw_date: str) -> date | None:
        """Phase 3 Task 3.2: Normalize accepted NSE date formats to ISO."""
        text = raw_date.strip()
        if not text or text == "-":
            return None
        # Try ISO first
        for pattern in _NSE_DATE_PATTERNS:
            match = pattern.match(text)
            if match is None:
                continue
            groups = match.groups()
            try:
                if len(groups[0]) == 4:
                    # YYYY-MM-DD
                    return date(int(groups[0]), int(groups[1]), int(groups[2]))
                if groups[1].isalpha():
                    # DD-Mon-YYYY
                    month = _MONTH_MAP.get(groups[1].lower())
                    if month is not None:
                        return date(int(groups[2]), month, int(groups[0]))
                else:
                    # DD/MM/YYYY or DD-MM-YYYY
                    return date(int(groups[2]), int(groups[1]), int(groups[0]))
            except ValueError:
                continue
        return None

    @staticmethod
    def parse_ratio(raw: str, action_type: str) -> tuple[float, float] | None:
        """Phase 3 Task 3.2: Parse positive BONUS/SPLIT ratios from NSE text."""
        if action_type not in ADJUSTABLE_TYPES:
            return None
        text = raw.strip()
        if not text or text == "-":
            return None
        # Common patterns: "1:2", "1 : 2", "5:1", "1 For 2"
        cleaned = text.replace(" ", "").upper()
        for sep in (":", "FOR"):
            if sep in cleaned:
                parts = cleaned.split(sep, maxsplit=1)
                try:
                    num, den = float(parts[0]), float(parts[1])
                    if num > 0 and den > 0:
                        return (num, den)
                except (ValueError, IndexError):
                    continue
        # Single number (e.g., ratio=2 for a 1:2 split)
        try:
            val = float(cleaned)
            if val > 0:
                return (1.0, val) if action_type == "BONUS" else (val, 1.0)
        except ValueError:
            pass
        return None

    @staticmethod
    def classify_action_type(raw_type: str) -> str:
        """Phase 3 Task 3.2: Classify NSE corporate action type."""
        text = raw_type.strip().upper()
        if "BONUS" in text:
            return "BONUS"
        if "SPLIT" in text:
            return "SPLIT"
        if "RIGHT" in text:
            return "RIGHTS"
        if "DEMERGER" in text or "SCHEME" in text or "ARRANGEMENT" in text:
            return "DEMERGER"
        if "DIVIDEND" in text:
            return "DIVIDEND"
        if "DELIST" in text:
            return "DELISTING"
        return text

    def detect_events(self, source_records: list[dict[str, str]], context: Any = None) -> dict[str, object]:
        """Phase 3 Task 3.2: Detect corporate actions from NSE source records.

        Each source_record should have: symbol, isin, ex_date, action_type, ratio (optional), raw_json.
        """
        detected: list[dict[str, object]] = []
        skipped: list[dict[str, str]] = []
        for record in source_records:
            raw_date = str(record.get("ex_date", ""))
            ex = self.normalize_nse_date(raw_date)
            if ex is None:
                skipped.append({"symbol": record.get("symbol", ""), "reason": "invalid_date", "raw_date": raw_date})
                continue
            raw_type = str(record.get("action_type", ""))
            action_type = self.classify_action_type(raw_type)
            if action_type not in ALL_CA_TYPES:
                skipped.append({"symbol": record.get("symbol", ""), "reason": f"unsupported_type:{action_type}"})
                continue
            isin = str(record.get("isin", "")).strip()
            symbol = str(record.get("symbol", "")).strip()
            if not isin or not symbol:
                skipped.append({"symbol": symbol, "reason": "missing_identity"})
                continue
            # Parse ratio for adjustable types
            ratio = self.parse_ratio(str(record.get("ratio", "")), action_type)
            # Resolve instrument_id
            instruments = [item for item in self.market.tracked_instruments() if item["isin"] == isin and item["exchange"] == "NSE"]
            instrument_id = str(instruments[0]["instrument_id"]) if instruments else None
            event_id = str(uuid5(NAMESPACE_URL, f"ca-event:{isin}:{action_type}:{ex.isoformat()}"))
            raw_json = record.get("raw_json", json.dumps(record, default=str))
            # Determine initial state
            if action_type in MONITORED_TYPES:
                initial_state = "MONITORING"
            else:
                initial_state = "DETECTED"
            event = {
                "event_id": event_id,
                "instrument_id": instrument_id,
                "isin": isin,
                "symbol": symbol,
                "action_type": action_type,
                "ex_date": ex.isoformat(),
                "ratio_numerator": ratio[0] if ratio else None,
                "ratio_denominator": ratio[1] if ratio else None,
                "raw_source_json": raw_json,
                "state": initial_state,
            }
            was_new = self.market.upsert_corporate_action_event(event)
            if was_new:
                detected.append(event)
        # Advance watermark
        if source_records:
            dates = [self.normalize_nse_date(str(r.get("ex_date", ""))) for r in source_records]
            max_date = max((d for d in dates if d is not None), default=None)
            if max_date is not None:
                self.market.advance_corporate_action_watermark(max_date)
        if context is not None:
            context.checkpoint(progress={"stage": "detect_events", "detected": len(detected), "skipped": len(skipped)})
        return {"detected": len(detected), "skipped": skipped, "events": detected}

    def detect_job(self, payload: dict[str, object], context=None) -> dict[str, object]:
        """Adapt durable job payloads to normalized NSE source records."""
        from src.domains.reference_data import NseClient
        if set(payload) - {"as_of_date", "start_date"}:
            raise DomainValidationError("corporate action detection payload is invalid")
        end = date.fromisoformat(str(payload.get("as_of_date") or datetime.now(ZoneInfo("Asia/Kolkata")).date()))
        try:
            start = (
                date.fromisoformat(str(payload["start_date"]))
                if payload.get("start_date")
                else (self.market.corporate_action_watermark() or end - timedelta(days=365)) - timedelta(days=7)
            )
        except ValueError as exc:
            raise DomainValidationError("corporate action detection dates must be ISO dates") from exc
        if start > end:
            raise DomainValidationError("corporate action detection start_date must not follow end_date")
        raw = NseClient().corporate_actions(from_date=start.strftime("%d-%m-%Y"), to_date=end.strftime("%d-%m-%Y"))
        records = []
        for row in raw:
            subject = str(row.get("subject", ""))
            ratio = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", subject)
            face_values = re.search(r"FROM\s+(?:RS\.?\s*)?(\d+(?:\.\d+)?).*?TO\s+(?:RS\.?\s*)?(\d+(?:\.\d+)?)", subject.upper())
            ratio_text = ratio.group(0) if ratio else ""
            if "SPLIT" in subject.upper() and face_values:
                ratio_text = face_values.group(2) + ":" + face_values.group(1)
            records.append({"symbol": row.get("symbol", ""), "isin": row.get("isin", ""),
                "ex_date": row.get("exDate", ""), "action_type": subject,
                "ratio": ratio_text, "raw_json": json.dumps(row)})
        result = self.detect_events(records, context)
        # Advance the source query window even when it contained no events.
        self.market.advance_corporate_action_watermark(end)
        return result

    # ------------------------------------------------------------------
    # Phase 3 Task 3.3Ã¢â‚¬â€œ3.5: Fetch, temporary adjustment, and retry
    # ------------------------------------------------------------------

    def compute_adjustment_factor(self, action_type: str, numerator: float, denominator: float) -> float | None:
        """Compute the OHLC scaling factor for pre-ex-date bars.

        Returns the multiplier to apply to pre-ex-date prices.
        """
        if action_type == "SPLIT":
            # Split N:D means N old face value splits into D new face value
            # E.g., 1:2 split means 1 old share = 2 new, pre-ex prices * (1/2)
            return numerator / denominator if denominator > 0 else None
        if action_type == "BONUS":
            # Bonus N:D means N new shares for every D held
            # Pre-ex prices * D/(N+D)
            return denominator / (numerator + denominator) if (numerator + denominator) > 0 else None
        return None

    def apply_self_adjustment(self, event_id: str, context: Any = None) -> dict[str, object]:
        """Phase 3 Task 3.4: Apply temporary BONUS/SPLIT self-adjustment."""
        event = self.market.corporate_action_event(event_id)
        if event is None:
            raise DomainValidationError("corporate action event not found")
        if str(event["state"]) not in ("DETECTED",):
            raise DomainValidationError("event is not in DETECTED state for self-adjustment")
        if str(event["action_type"]) not in ADJUSTABLE_TYPES:
            raise DomainValidationError("only BONUS/SPLIT events can be self-adjusted")
        numerator = event.get("ratio_numerator")
        denominator = event.get("ratio_denominator")
        if numerator is None or denominator is None:
            return self._fail_event(event_id, "missing_ratio")
        factor = self.compute_adjustment_factor(str(event["action_type"]), float(numerator), float(denominator))
        if factor is None or factor <= 0:
            return self._fail_event(event_id, "invalid_factor")
        instrument_id = event.get("instrument_id")
        if instrument_id is None:
            return self._fail_event(event_id, "unresolved_instrument")
        ex_date = date.fromisoformat(str(event["ex_date"]))
        if ex_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            return self._fail_event(event_id, "ex_date_not_completed")
        # Load pre-ex-date bars; the repository captures their provenance atomically.
        bars = self.market.bars(str(instrument_id), None, ex_date - timedelta(days=1), limit=1000)
        if not bars:
            return self._fail_event(event_id, "no_pre_ex_bars")
        # Apply factor to pre-ex-date OHLC atomically
        adjusted_count = self.market.adjust_corporate_event(event_id, factor)
        if not adjusted_count:
            pending = self.market.corporate_action_event(event_id)
            outcome = str(pending["last_attempt_outcome"])
            if outcome in {"stored_history_appears_adjusted", "adjustment_basis_not_confirmed",
                           "incomplete_ex_date_window"}:
                evidence = json.loads(str(pending["verification_evidence_json"] or "{}"))
                self.market.record_quality_event(str(instrument_id), ex_date,
                    "corporate_action_mismatch",
                    "INFO" if outcome == "stored_history_appears_adjusted" else "WARNING",
                    {"event_id": event_id, "action_type": str(event["action_type"]),
                     "state": str(pending["state"]), "outcome": outcome, **evidence})
            return {"event_id": event_id, "state": str(pending["state"]),
                    "outcome": outcome, "adjusted_bars": 0,
                    "instrument_id": str(instrument_id)}
        # Invalidate indicator cache for this instrument
        if self.node_cache is not None:
            self.node_cache.invalidate_instrument(str(instrument_id))
        if context is not None:
            context.checkpoint(progress={"stage": "self_adjust", "event_id": event_id, "adjusted_bars": adjusted_count})
        return {"event_id": event_id, "state": "SELF_ADJUSTED", "factor": factor, "adjusted_bars": adjusted_count, "instrument_id": str(instrument_id)}

    def verify_with_kite(self, event_id: str, fetch_bars_fn: Any = None, context: Any = None) -> dict[str, object]:
        """Phase 3 Task 3.5: Re-fetch and verify SELF_ADJUSTED history against Kite."""
        event = self.market.corporate_action_event(event_id)
        if event is None:
            raise DomainValidationError("corporate action event not found")
        if str(event["state"]) not in ("DETECTED", "SELF_ADJUSTED", "MONITORING"):
            raise DomainValidationError("event is not in an actionable state for verification")
        instrument_id = event.get("instrument_id")
        if instrument_id is None:
            return self._fail_event(event_id, "unresolved_instrument")
        if fetch_bars_fn is None:
            # No provider available; record attempt but remain actionable
            self.market.transition_corporate_action(
                event_id, str(event["state"]),
                attempt_outcome="no_provider_available",
            )
            return {"event_id": event_id, "state": str(event["state"]), "outcome": "no_provider"}
        ex_date = date.fromisoformat(str(event["ex_date"]))
        if ex_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            self.market.transition_corporate_action(event_id, str(event["state"]),
                                                   attempt_outcome="ex_date_not_completed")
            return {"event_id": event_id, "state": str(event["state"]),
                    "outcome": "ex_date_not_completed"}
        if str(event["action_type"]) in ADJUSTABLE_TYPES:
            event = self.market.preserve_corporate_action_baseline(event_id)
        # Fetch fresh bars covering the ex-date window
        try:
            fresh_bars = fetch_bars_fn(str(instrument_id), date(2021, 1, 1), datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1))
        except Exception as exc:  # noqa: BLE001 - sanitize provider failures at this boundary
            self.market.transition_corporate_action(
                event_id, str(event["state"]),
                attempt_outcome=f"fetch_failed:{type(exc).__name__}",
            )
            return {"event_id": event_id, "state": str(event["state"]), "outcome": "fetch_failed", "error": type(exc).__name__}
        if not fresh_bars:
            self.market.transition_corporate_action(
                event_id, str(event["state"]),
                attempt_outcome="empty_fetch",
            )
            return {"event_id": event_id, "state": str(event["state"]), "outcome": "empty_fetch"}
        # Validate the entire provider response before replacing bars or changing state.
        try:
            normalized = tuple(sorted((NormalizedBar(
                str(instrument_id), date.fromisoformat(str(row["as_of_date"])),
                Decimal(str(row["open"])), Decimal(str(row["high"])),
                Decimal(str(row["low"])), Decimal(str(row["close"])), row["volume"],
            ) for row in fresh_bars), key=lambda bar: bar.as_of_date))
            if len({bar.as_of_date for bar in normalized}) != len(normalized):
                raise DomainValidationError("duplicate provider dates")
            if any(bar.as_of_date < date(2021, 1, 1) or bar.as_of_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date()
                   for bar in normalized):
                raise DomainValidationError("provider dates outside completed history")
        except (KeyError, TypeError, ValueError, InvalidOperation, DomainValidationError):
            self.market.transition_corporate_action(
                event_id, str(event["state"]), attempt_outcome="invalid_provider_history",
            )
            return {"event_id": event_id, "state": str(event["state"]),
                    "outcome": "invalid_provider_history"}
        fresh_bars = [{"as_of_date": bar.as_of_date.isoformat(), "open": str(bar.open),
                      "high": str(bar.high), "low": str(bar.low), "close": str(bar.close),
                      "volume": bar.volume} for bar in normalized]
        if not any(row["as_of_date"] == ex_date.isoformat() for row in fresh_bars):
            self.market.transition_corporate_action(event_id, str(event["state"]),
                                                   attempt_outcome="incomplete_ex_date_window")
            return {"event_id": event_id, "state": str(event["state"]),
                    "outcome": "incomplete_ex_date_window"}
        # Compare the relevant ex-date, never a later unrelated normal gap.
        action_type = str(event["action_type"])
        if action_type in MONITORED_TYPES:
            if not any(str(b["as_of_date"]) < ex_date.isoformat() for b in fresh_bars) or not any(str(b["as_of_date"]) >= ex_date.isoformat() for b in fresh_bars):
                self.market.transition_corporate_action(event_id, str(event["state"]),
                                                       attempt_outcome="incomplete_ex_date_window")
                return {"event_id": event_id, "state": str(event["state"]), "outcome": "incomplete_ex_date_window"}
            anomaly = self._check_anomaly(fresh_bars, ex_date)
            state = "VERIFIED" if anomaly is None else "MONITORING"
            outcome = "monitoring_resolved" if anomaly is None else "anomaly_present"
            self._persist_provider_history(event_id, str(instrument_id), normalized, state,
                outcome if anomaly is None else f"anomaly_present:{anomaly:.1f}%")
            self.market.record_quality_event(
                str(instrument_id), ex_date, "corporate_action_mismatch",
                "INFO" if anomaly is None else "WARNING",
                {"event_id": event_id, "action_type": action_type,
                 "ex_date": ex_date.isoformat(), "source": "kite",
                 "state": state, "discrepancy_pct": anomaly,
                 "threshold_pct": self.market.price_gap_threshold * 100,
                 "market_revision": self.market.market_history_revision(str(instrument_id))},
            )
            result = {"event_id": event_id, "state": state, "outcome": outcome,
                      "instrument_id": str(instrument_id)}
            if anomaly is not None:
                result["discrepancy_pct"] = anomaly
            return result
        # For BONUS/SPLIT: verify that Kite has adjusted the pre-ex bars
        if action_type in ADJUSTABLE_TYPES:
            pre = [b for b in fresh_bars if str(b["as_of_date"]) < ex_date.isoformat()]
            post = [b for b in fresh_bars if str(b["as_of_date"]) >= ex_date.isoformat()]
            if not pre or not post or self._check_anomaly(fresh_bars, ex_date) is not None:
                self.market.transition_corporate_action(event_id, str(event["state"]),
                                                       attempt_outcome="provider_history_not_verified")
                return {"event_id": event_id, "state": str(event["state"]), "outcome": "provider_history_not_verified"}
            stored = self.market.histories(date(2021, 1, 1), ex_date - timedelta(days=1)).get(str(instrument_id), ([], {}))[0]
            fetched_dates = {str(row["as_of_date"]) for row in fresh_bars}
            if any(str(row["as_of_date"]) not in fetched_dates for row in stored):
                self.market.transition_corporate_action(event_id, str(event["state"]),
                                                       attempt_outcome="incomplete_provider_history")
                return {"event_id": event_id, "state": str(event["state"]), "outcome": "incomplete_provider_history"}
            baseline = json.loads(str(event["baseline_prices_json"])) if event.get("baseline_prices_json") else None
            if baseline is None:
                self.market.transition_corporate_action(event_id, str(event["state"]),
                                                       attempt_outcome="missing_verification_baseline")
                return {"event_id": event_id, "state": str(event["state"]),
                        "outcome": "missing_verification_baseline"}
            reference = {str(row["as_of_date"]): Decimal(str(row["close"])) for row in pre}
            selected = baseline["pre"]
            selected_close = Decimal(str(selected["close"]))
            fetched_close = reference.get(str(selected["as_of_date"]))
            expected_close = selected_close
            factor = None
            if baseline["captured_state"] == "DETECTED":
                numerator, denominator = event.get("ratio_numerator"), event.get("ratio_denominator")
                if numerator is None or denominator is None:
                    return self._fail_event(event_id, "missing_ratio")
                factor = self.compute_adjustment_factor(action_type, float(numerator), float(denominator))
                if factor is None or not 0 < factor < 100:
                    return self._fail_event(event_id, "invalid_factor")
                expected_close *= Decimal(str(factor))
            comparison = "provider_matches_expected_factor"
            matches = fetched_close is not None and abs(fetched_close / expected_close - 1) <= Decimal("0.02")
            # Previously smooth stored history is eligible for authoritative verification,
            # never for another local multiplication. Record the observed unchanged basis.
            if not matches and baseline["captured_state"] == "DETECTED" and baseline["post"] is not None:
                stored_post = Decimal(str(baseline["post"]["close"]))
                if (abs(stored_post / selected_close - 1) <= Decimal(str(self.market.price_gap_threshold))
                        and fetched_close is not None
                        and abs(fetched_close / selected_close - 1) <= Decimal("0.02")):
                    expected_close, matches = selected_close, True
                    comparison = "provider_matches_existing_smooth_basis"
            evidence = {"source": "kite", "comparison": comparison,
                        "baseline_revision": event["baseline_revision"],
                        "pre_date": selected["as_of_date"], "baseline_close": str(selected_close),
                        "expected_close": str(expected_close),
                        "provider_close": str(fetched_close) if fetched_close is not None else None,
                        "provider_ex_date_close": str(post[0]["close"]),
                        "factor": str(factor) if factor is not None else None,
                        "tolerance_pct": 2, "matched": matches}
            if not matches:
                self.market.transition_corporate_action(event_id, str(event["state"]),
                    attempt_outcome="provider_adjustment_not_confirmed", verification_evidence=evidence)
                self.market.record_quality_event(str(instrument_id), ex_date,
                    "corporate_action_mismatch", "WARNING", {"event_id": event_id,
                    "action_type": action_type, "state": str(event["state"]), **evidence})
                return {"event_id": event_id, "state": str(event["state"]),
                        "outcome": "provider_adjustment_not_confirmed"}
            self._persist_provider_history(event_id, str(instrument_id), normalized,
                                           "VERIFIED", "verified_with_kite", evidence=evidence)
            return {"event_id": event_id, "state": "VERIFIED", "outcome": "verified_with_kite", "instrument_id": str(instrument_id)}
        return {"event_id": event_id, "state": str(event["state"]), "outcome": "no_action_needed"}

    def _persist_provider_history(self, event_id, instrument_id, bars, state, outcome, *, evidence=None):
        """Commit provider replacement, revisions and event state together."""
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.market.upsert_bars(instrument_id, bars, f"corporate-action:{event_id}",
                                    transaction_connection=connection)
            if not self.market.transition_corporate_action(
                event_id, state, attempt_outcome=outcome, verification_evidence=evidence,
                transaction_connection=connection,
            ):
                raise DomainValidationError("corporate action event disappeared during verification")
        if self.node_cache is not None:
            self.node_cache.invalidate_instrument(instrument_id)

    def process_actionable(
        self,
        fetch_bars_fn: Any = None,
        context: Any = None,
        event_ids: set[str] | None = None,
    ) -> dict[str, object]:
        """Process actionable corporate actions, optionally from one fresh batch only."""
        events = self.market.actionable_corporate_events()
        if event_ids is not None:
            events = [event for event in events if str(event["event_id"]) in event_ids]
        results: list[dict[str, object]] = []
        for index, event in enumerate(events, start=1):
            if context is not None and (index == 1 or index % 25 == 0 or index == len(events)):
                context.checkpoint(
                    progress={
                        "stage": "corporate_action_process",
                        "current": index - 1,
                        "total": len(events),
                        "message": "Processing detected corporate actions",
                    }
                )
            event_id = str(event["event_id"])
            state = str(event["state"])
            action_type = str(event["action_type"])
            try:
                if state == "DETECTED" and action_type in ADJUSTABLE_TYPES:
                    result = (self.verify_with_kite(event_id, fetch_bars_fn, context=context)
                              if fetch_bars_fn is not None else None)
                    if result is None or (result["state"] == "DETECTED"
                            and result["outcome"] in {"fetch_failed", "empty_fetch",
                                "provider_history_not_verified", "incomplete_provider_history"}):
                        result = self.apply_self_adjustment(event_id, context=context)
                elif state in ("DETECTED", "SELF_ADJUSTED", "MONITORING"):
                    result = self.verify_with_kite(event_id, fetch_bars_fn, context=context)
                else:
                    result = {"event_id": event_id, "state": state, "outcome": "skipped"}
            except DomainValidationError as exc:
                result = {"event_id": event_id, "state": state, "outcome": f"error:{exc}"}
            results.append(result)
        return {"processed": len(results), "results": results}

    def _fail_event(self, event_id: str, reason: str) -> dict[str, object]:
        """Transition an event to DETECTED with failure diagnostics (stays actionable)."""
        self.market.transition_corporate_action(
            event_id, "DETECTED", attempt_outcome=f"failed:{reason}",
        )
        return {"event_id": event_id, "state": "DETECTED", "outcome": reason}

    def _check_anomaly(self, bars: list[dict[str, object]], ex_date: date) -> float | None:
        """Phase 3 Task 3.6: Check for >15% gap around ex-date."""
        pre_ex = [b for b in bars if date.fromisoformat(str(b["as_of_date"])) < ex_date]
        post_ex = [b for b in bars if date.fromisoformat(str(b["as_of_date"])) >= ex_date]
        if not pre_ex or not post_ex:
            return None
        pre_close = float(pre_ex[-1]["close"])
        post_open = float(post_ex[0]["open"])
        if pre_close <= 0:
            return None
        change_pct = abs((post_open - pre_close) / pre_close) * 100
        return change_pct if change_pct > self.market.price_gap_threshold * 100 else None
