"""Durable planner for bounded all-symbol market refresh jobs."""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from src.application.jobs import JobStore
from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.platform_kernel import DomainValidationError


class MarketRefreshPlanner:
    def __init__(self, database: str | Path, repository: MarketRepository, jobs: JobStore, publisher: ArtifactPublisher | None = None):
        self.database, self.repository, self.jobs, self.publisher = Path(database), repository, jobs, publisher

    def reconcile(self, payload: dict[str, Any]) -> dict[str, object]:
        """Publish a deterministic daily reference/bar coverage reconciliation."""
        allowed = {"as_of_date", "source_instruments"}
        if not isinstance(payload, dict) or set(payload) - allowed or "as_of_date" not in payload:
            raise DomainValidationError("reconciliation requires as_of_date")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except ValueError as exc:
            raise DomainValidationError("reconciliation date must be ISO date") from exc
        if as_of >= datetime.now(UTC).date():
            raise DomainValidationError("reconciliation requires a completed date")
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
            "coverage": coverage,
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
        if exchange is not None and exchange not in {"NSE", "BSE"}:
            raise DomainValidationError("market refresh exchange is invalid")
        if start > end or (end - start).days > 365:
            raise DomainValidationError("market refresh range must be at most 365 days")
        instruments = []
        offset = 0
        while True:
            page = self.repository.instruments(limit=500, offset=offset)
            instruments.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
        jobs: list[int] = []
        excluded: list[dict[str, str]] = []
        for item in instruments:
            if exchange is not None and item["exchange"] != exchange:
                continue
            if str(item["isin"]).startswith("INDEX:"):
                excluded.append({"instrument_id": str(item["instrument_id"]), "reason": "index_identity"})
                continue
            if not str(item["provider_token"]).strip():
                excluded.append({"instrument_id": str(item["instrument_id"]), "reason": "missing_provider_token"})
                continue
            fingerprint = f"market-bars:{item['instrument_id']}:{start.isoformat()}:{end.isoformat()}"
            job = self.jobs.submit(
                fingerprint,
                "market.fetch-kite-bars",
                {"symbol": item["symbol"], "exchange": item["exchange"], "start_date": start.isoformat(), "end_date": end.isoformat()},
                max_attempts=3,
            )
            jobs.append(job.job_id)
        return {
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "scheduled_count": len(jobs), "job_ids": jobs, "excluded": excluded,
        }
