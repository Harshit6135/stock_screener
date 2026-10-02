"""Durable planner for bounded all-symbol market refresh jobs."""

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.application.jobs import JobStore
from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.platform_kernel import DomainValidationError

# Phase 2 Task 2.9: six NSE benchmarks
PHASE2_BENCHMARK_SYMBOLS = frozenset(
    {"NIFTY 50", "NIFTY 500", "NIFTY NEXT 50", "NIFTY MIDCAP 150", "NIFTY SMLCAP 250", "INDIA VIX"}
)


class MarketRefreshPlanner:
    def __init__(
        self,
        database: str | Path,
        repository: MarketRepository,
        jobs: JobStore,
        publisher: ArtifactPublisher | None = None,
        held_instrument_ids: Callable[[], set[str]] | None = None,
    ):
        self.database, self.repository, self.jobs, self.publisher = Path(database), repository, jobs, publisher
        self.held_instrument_ids = held_instrument_ids

    def reconcile(self, payload: dict[str, Any]) -> dict[str, object]:
        """Publish a deterministic daily reference/bar coverage reconciliation."""
        allowed = {"as_of_date", "start_date", "source_instruments"}
        if not isinstance(payload, dict) or set(payload) - allowed or "as_of_date" not in payload:
            raise DomainValidationError("reconciliation requires as_of_date")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except ValueError as exc:
            raise DomainValidationError("reconciliation date must be ISO date") from exc
        if as_of >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("reconciliation requires a completed date")
        try:
            start = date.fromisoformat(str(payload.get("start_date", as_of.isoformat())))
        except ValueError as exc:
            raise DomainValidationError("reconciliation start date must be ISO date") from exc
        if start > as_of:
            raise DomainValidationError("reconciliation date range is invalid")
        from src.application.session_coverage import CompletedSessionCoverage

        session_coverage = CompletedSessionCoverage(self.repository).read(start, as_of)
        current: list[dict[str, object]] = []
        offset = 0
        while True:
            page = self.repository.instruments(limit=500, offset=offset)
            current.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
        expected = payload.get("source_instruments", [])
        if not isinstance(expected, list) or any(not isinstance(item, dict) for item in expected):
            raise DomainValidationError("source_instruments must be a list of objects")
        expected_isins = {str(item.get("isin")) for item in expected if item.get("isin")}
        expected_symbols = {str(item.get("symbol")) for item in expected if item.get("symbol")}
        current_isins = {str(item["isin"]) for item in current}
        current_symbols = {str(item["symbol"]) for item in current}
        duplicate_symbols = sorted({str(item["symbol"]) for item in current if sum(x["symbol"] == item["symbol"] for x in current) > 1})
        excluded: list[dict[str, object]] = []
        for item in current:
            reason = None
            if str(item["isin"]).startswith("INDEX:"):
                reason = "index_identity"
            elif not str(item["provider_token"]).strip():
                reason = "missing_provider_token"
            if reason is not None:
                excluded.append({
                    "instrument_id": str(item["instrument_id"]),
                    "symbol": str(item["symbol"]),
                    "exchange": str(item["exchange"]),
                    "reason": reason,
                })
        coverage = []
        offset = 0
        while True:
            page = self.repository.coverage(limit=500, offset=offset)
            coverage.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
        report = {
            "as_of_date": as_of.isoformat(), "source_count": len(expected),
            "tracked_count": len(current), "matched_isins": sorted(expected_isins & current_isins),
            "unmatched_source_isins": sorted(expected_isins - current_isins),
            "unmatched_source_symbols": sorted(expected_symbols - current_symbols),
            "tracked_not_in_source": sorted(current_isins - expected_isins) if expected else [],
            "duplicate_symbols": duplicate_symbols,
            "excluded_identities": excluded,
            "coverage": coverage, "session_coverage": session_coverage,
        }
        artifact_id = hashlib.sha256(json.dumps(report, sort_keys=True, default=str).encode()).hexdigest()
        if self.publisher is not None and not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json("reference/reconciliations", artifact_id, report)
        return {"artifact_id": artifact_id, **report}

    def schedule(self, payload: dict[str, Any]) -> dict[str, object]:
        if set(payload) not in ({"start_date", "end_date"}, {"start_date", "end_date", "exchange"}):
            raise DomainValidationError("market refresh requires start_date and end_date")
        try:
            start, end = date.fromisoformat(str(payload["start_date"])), date.fromisoformat(str(payload["end_date"]))
        except ValueError as exc:
            raise DomainValidationError("market refresh dates must be ISO dates") from exc
        exchange = payload.get("exchange")
        if exchange is not None and exchange != "NSE":
            raise DomainValidationError("market refresh exchange is invalid")
        if start > end or (end - start).days > 365:
            raise DomainValidationError("market refresh range must be at most 365 days")

        # Phase 2 Task 2.12: intersect refresh with snapshot members + benchmark set
        catalog = self.repository.tracked_instruments()
        reference_by_id = {str(item["instrument_id"]): item for item in catalog}

        # Use either active universe members OR snapshot members
        snapshot = self.repository.latest_universe_snapshot("NIFTY 500")
        if snapshot is None:
            raise DomainValidationError("NIFTY 500 snapshot is unavailable")
        members = self.repository.universe_snapshot_members(str(snapshot["snapshot_id"]), limit=1000)
        member_isins = {str(item["isin"]) for item in members}
        universe = [item for item in catalog if str(item["isin"]) in member_isins and item["exchange"] == "NSE"]

        held_ids = set(self.held_instrument_ids() if self.held_instrument_ids else ())
        selected_ids = {str(item["instrument_id"]) for item in universe}

        # Phase 2 Task 2.9/2.12: include all six benchmark instruments
        for item in catalog:
            if str(item["symbol"]) in PHASE2_BENCHMARK_SYMBOLS and str(item["exchange"]) == "NSE":
                selected_ids.add(str(item["instrument_id"]))

        # Phase 2 Task 2.12: include exit-only instruments separately
        self.repository.resolve_pending_exit_sessions()
        exit_eligible = self.repository.exit_eligible_instruments()
        exit_ids = {str(item["instrument_id"]) for item in exit_eligible}

        instruments = [reference_by_id[item] for item in sorted(selected_ids | exit_ids | held_ids) if item in reference_by_id]
        jobs: list[int] = []
        excluded: list[dict[str, str]] = []
        blocked: list[dict[str, str]] = []
        known_ids = set(reference_by_id)
        blocked.extend(
            {"instrument_id": instrument_id, "reason": "held_position_not_in_reference_catalog"}
            for instrument_id in sorted(held_ids - known_ids)
        )
        valid_items = []
        for item in instruments:
            if exchange is not None and item["exchange"] != exchange:
                continue
            instrument_id = str(item["instrument_id"])
            is_held = instrument_id in held_ids
            is_benchmark = str(item["symbol"]) in PHASE2_BENCHMARK_SYMBOLS
            is_exit = instrument_id in exit_ids

            # Phase 2 Task 2.12: exclude non-benchmark indices from regular refresh
            if str(item["isin"]).startswith("INDEX:") and not is_benchmark and not is_held:
                excluded.append({"instrument_id": instrument_id, "reason": "index_identity"})
                continue
            if not str(item["provider_token"]).strip():
                row = {"instrument_id": instrument_id, "reason": "missing_provider_token"}
                (blocked if is_held else excluded).append(row)
                continue
            if instrument_id not in selected_ids:
                excluded.append({"instrument_id": instrument_id,
                                 "reason": "exit_only" if is_exit else "outside_snapshot"})
                continue
            valid_items.append(item)
            
        if valid_items:
            identity = hashlib.sha256(json.dumps([(item["instrument_id"], item["provider_token"]) for item in valid_items], sort_keys=True).encode()).hexdigest()
            fingerprint = f"market-bars-bulk:{snapshot['snapshot_id']}:{identity}:{start.isoformat()}:{end.isoformat()}"
            payload_items = [{"symbol": item["symbol"], "exchange": item["exchange"]} for item in valid_items]
            job = self.jobs.submit(
                fingerprint,
                "market.fetch-bulk-kite-bars",
                {"start_date": start.isoformat(), "end_date": end.isoformat(), "items": payload_items},
                max_attempts=3,
            )
            jobs.append(job.job_id)
            scheduled_count = len(payload_items)
        else:
            scheduled_count = 0
            
        # Excluded holdings receive exactly their declared exit session, never
        # the regular request range. An old exit record cannot suppress re-entry.
        exit_job_ids = []
        pending_exit_sessions = []
        for record in exit_eligible:
            instrument_id = str(record["instrument_id"])
            if record["target_session_date"] is None:
                if instrument_id not in selected_ids:
                    pending_exit_sessions.append({"instrument_id": instrument_id,
                        "decision_date": record["decision_date"], "status": "missing_session"})
                continue
            target = date.fromisoformat(str(record["target_session_date"]))
            item = reference_by_id.get(instrument_id)
            if (instrument_id in selected_ids or not start <= target <= end or item is None
                    or item["exchange"] != "NSE" or not str(item["provider_token"]).strip()):
                continue
            job = self.jobs.submit(
                f"exit-bars:{record['decision_snapshot_id']}:{instrument_id}:{target.isoformat()}",
                "market.fetch-kite-bars",
                {"symbol": item["symbol"], "exchange": "NSE",
                 "start_date": target.isoformat(), "end_date": target.isoformat(),
                 "exit_only": True},
                max_attempts=3,
            )
            jobs.append(job.job_id)
            exit_job_ids.append(job.job_id)
        return {
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "snapshot_id": snapshot["snapshot_id"], "exit_job_ids": exit_job_ids,
            "pending_exit_sessions": pending_exit_sessions,
            "scheduled_count": scheduled_count, "job_ids": jobs, "excluded": excluded,
            "blocked_held_positions": sorted(blocked, key=lambda item: item["instrument_id"]),
        }
