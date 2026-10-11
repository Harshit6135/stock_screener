"""Gate workflow for durable immutable daily universe snapshots."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.domains.reference_data import NseClient
from src.gates.repositories import MarketRepository
from src.gates.workflows.trading_calendar import TradingCalendar
from src.platform_kernel import DomainValidationError


class UniverseJobs:
    INDEX_NAME = "NIFTY 500"

    def __init__(
        self, repository: MarketRepository, client: NseClient | None = None, *, collection_date=None
    ) -> None:
        self.repository, self.client = repository, client or NseClient()
        self.collection_date = collection_date or (
            lambda: datetime.now(ZoneInfo("Asia/Kolkata")).date()
        )

    def download_nifty500_constituents(
        self, payload: dict[str, Any], context: Any = None
    ) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) - {"snapshot_date"}:
            raise DomainValidationError("universe download payload is invalid")
        actual_day = self.collection_date()
        try:
            collection_day = date.fromisoformat(str(payload.get("snapshot_date") or actual_day))
        except ValueError as exc:
            raise DomainValidationError("snapshot_date must be ISO formatted") from exc
        existing = self.repository.universe_snapshot(self.INDEX_NAME, collection_day)
        if existing is not None:
            if context is not None:
                context.checkpoint(
                    progress={
                        "stage": "universe_snapshot",
                        "status": "reused",
                        "snapshot_id": existing["snapshot_id"],
                    }
                )
            return {
                "status": "reused",
                "snapshot_id": existing["snapshot_id"],
                "snapshot_date": str(existing.get("snapshot_date") or collection_day.isoformat()),
                "member_count": existing["member_count"],
            }
        if collection_day != actual_day:
            raise DomainValidationError(
                "current NSE downloads must use their actual collection date"
            )
        source_url, raw = self.client.nifty_500_csv()
        members = self._parse(raw)
        snapshot_id = str(
            uuid5(
                NAMESPACE_URL,
                f"nifty500:{collection_day.isoformat()}:{hashlib.sha256(raw).hexdigest()}",
            )
        )
        prior = self.repository.latest_universe_snapshot(self.INDEX_NAME)
        stored = self.repository.create_universe_snapshot(
            snapshot_id=snapshot_id,
            index_name=self.INDEX_NAME,
            snapshot_date=collection_day,
            source_url=source_url,
            raw_csv=raw,
            members=members,
        )
        # A concurrent collector may have stored a different first snapshot.
        # All downstream work must use the identity that actually committed.
        snapshot_id = str(stored["snapshot_id"])
        diff = (
            self.repository.universe_snapshot_diff(str(prior["snapshot_id"]), snapshot_id)
            if prior and prior["snapshot_id"] != snapshot_id
            else {"additions": [], "removals": [], "series_transitions": []}
        )
        # Phase 2 Task 2.11: record exit eligibility for removed members
        exit_records = self._record_exit_eligibility(
            diff.get("removals", []), collection_day, snapshot_id
        )
        if context is not None:
            context.checkpoint(
                progress={
                    "stage": "universe_snapshot",
                    "status": "stored",
                    "snapshot_id": snapshot_id,
                    "member_count": stored["member_count"],
                }
            )
        return {
            "status": "stored",
            "snapshot_id": stored["snapshot_id"],
            "snapshot_date": str(stored.get("snapshot_date") or collection_day.isoformat()),
            "member_count": stored["member_count"],
            "source_hash": stored["source_hash"],
            "diff": diff,
            "exit_eligibility": exit_records,
        }

    def _record_exit_eligibility(
        self,
        removals: list[dict[str, object]],
        decision_date: date,
        snapshot_id: str,
    ) -> list[dict[str, str]]:
        """Phase 2 Task 2.11: persist exit eligibility for removed members with held positions."""
        if not removals:
            return []
        # Future sessions require calendar evidence. Preserve a pending record
        # rather than inventing tomorrow when no observed session is available.
        calendar = TradingCalendar(self.repository.path)
        target_window = calendar.sessions(
            decision_date + timedelta(days=1), decision_date + timedelta(days=10)
        )
        target_session = target_window[0] if target_window else None
        recorded: list[dict[str, str]] = []
        for removed in removals:
            isin = str(removed["isin"])
            symbol = str(removed["symbol"])
            # Look up the instrument_id from reference_instruments
            instruments = [
                row
                for row in self.repository.tracked_instruments()
                if row["isin"] == isin and row["exchange"] == "NSE"
            ]
            if not instruments:
                continue
            instrument_id = str(instruments[0]["instrument_id"])
            was_new = self.repository.record_exit_eligibility(
                instrument_id=instrument_id,
                isin=isin,
                symbol=symbol,
                decision_date=decision_date,
                decision_snapshot_id=snapshot_id,
                target_session_date=target_session,
                session_source="observed_market" if target_session else "pending",
            )
            if was_new:
                recorded.append(
                    {
                        "instrument_id": instrument_id,
                        "symbol": symbol,
                        "target_session": target_session.isoformat() if target_session else None,
                        "status": "ready" if target_session else "missing_session",
                    }
                )
        return recorded

    def detect_universe_exits(
        self,
        payload: dict[str, Any],
        context: Any = None,
    ) -> dict[str, object]:
        """Phase 2 Task 2.13: detect managed holdings absent from current snapshot and generate exit records."""
        snapshot_id = payload.get("snapshot_id")
        held_instrument_ids = payload.get("held_instrument_ids", [])
        if not isinstance(snapshot_id, str) or not isinstance(held_instrument_ids, list):
            raise DomainValidationError(
                "exit detection requires snapshot_id and held_instrument_ids"
            )
        members = self.repository.universe_snapshot_members(snapshot_id, limit=1000)
        member_isins = {str(m["isin"]) for m in members}
        exits: list[dict[str, object]] = []
        for instrument_id in held_instrument_ids:
            instrument = self.repository.instrument_by_id(str(instrument_id))
            if instrument is None:
                continue
            isin = str(instrument["isin"])
            if isin.startswith("INDEX:"):
                continue
            if isin not in member_isins:
                exits.append(
                    {
                        "instrument_id": str(instrument_id),
                        "isin": isin,
                        "symbol": str(instrument["symbol"]),
                        "reason": "universe_exit",
                    }
                )
        return {"snapshot_id": snapshot_id, "exits": exits, "exit_count": len(exits)}

    @staticmethod
    def _parse(raw: bytes) -> list[dict[str, object]]:
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            result = [
                {
                    "isin": str(row["ISIN Code"]).strip(),
                    "symbol": str(row["Symbol"]).strip(),
                    "company_name": str(row["Company Name"]).strip(),
                    "industry": str(row["Industry"]).strip(),
                    "series": str(row["Series"]).strip(),
                }
                for row in reader
            ]
        except (UnicodeDecodeError, KeyError) as exc:
            raise DomainValidationError("NSE constituent CSV is invalid") from exc
        if not result or any(
            not all(str(value).strip() for value in row.values()) for row in result
        ):
            raise DomainValidationError("NSE constituent CSV has incomplete members")
        if len({str(row["isin"]).upper() for row in result}) != len(result):
            raise DomainValidationError("NSE constituent CSV has duplicate ISINs")
        return result
