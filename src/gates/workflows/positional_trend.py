"""Daily positional-trend signals, ranked and published with immutable lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.domains.strategies.api import feature_series, ranking_pattern_for
from src.platform_kernel import DomainValidationError, QualityStatus
from src.platform_kernel.sqlite import sqlite_connection

_FEATURE_SOURCE = (
    Path(__file__).resolve().parents[2] / "domains" / "strategies" / "positional_trend.py"
)


class PositionalTrendJobs:
    STRATEGY_ID = "positional_trend_following"
    CATEGORY = "research/positional-trend-signals"

    def __init__(self, market, publisher, runtime):
        self.market, self.publisher, self.runtime = market, publisher, runtime

    def _members(self, universe: str, as_of: date | None = None, snapshot_id: str | None = None) -> tuple[set[str], str, dict[str, object]]:
        # Phase 2 Task 2.8: snapshot-driven universe
        if universe == "SNAPSHOT_NIFTY500":
            snapshot = self.market.universe_snapshot_as_of("NIFTY 500", as_of or datetime.now(ZoneInfo("Asia/Kolkata")).date())
            if snapshot_id:
                snapshots = self.market.list_universe_snapshots("NIFTY 500", limit=500)
                snapshot = next((row for row in snapshots if row["snapshot_id"] == snapshot_id), None)
            if snapshot is None:
                raise DomainValidationError("Positional trend universe snapshot is not available; download NIFTY 500 first")
            snapshot_id = str(snapshot["snapshot_id"])
            rows = self.market.universe_snapshot_members(snapshot_id, limit=1000)
            if not rows:
                raise DomainValidationError("Positional trend universe snapshot has no members")
            members = {str(row["isin"]) for row in rows}
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
            return members, digest, {"source": universe, "snapshot_id": snapshot_id,
                                     "snapshot_date": str(snapshot["snapshot_date"]),
                                     "member_count": len(rows)}
        raise DomainValidationError("positional universe must be SNAPSHOT_NIFTY500")

    def _histories(self, as_of: date, members: set[str], metadata: dict[str, object]):
        histories = self.market.histories(date(2021, 1, 1), as_of, isins=members)
        return {key: value for key, value in histories.items() if value[1]["exchange"] == "NSE"}

    def _input_fingerprint(self, as_of: date, universe: str, universe_hash: str,
                           histories: dict) -> str:
        state = {
            "as_of_date": as_of.isoformat(), "universe": universe,
            "universe_hash": universe_hash,
            "revision_id": self.runtime.revision(self.STRATEGY_ID)["revision_id"],
            "feature_hash": hashlib.sha256(_FEATURE_SOURCE.read_bytes()).hexdigest(),
            "job_code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "histories": histories,
            "sessions": {"NSE": self.market.session_dates(date(2021, 1, 1), as_of, exchange="NSE")},
        }
        return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()

    def input_fingerprint(self, as_of: date, universe: str = "SNAPSHOT_NIFTY500") -> str:
        """Invalidate jobs and cached signals when their rules, code or market inputs change."""
        members, universe_hash, metadata = self._members(universe, as_of)
        histories = self._histories(as_of, members, metadata)
        return self._input_fingerprint(as_of, universe, universe_hash, histories)

    def build_signals(self, payload: dict[str, object]) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) - {"as_of_date", "universe", "universe_snapshot_id"} or "as_of_date" not in payload:
            raise DomainValidationError("Positional trend signal job requires as_of_date and optional universe")
        universe = str(payload.get("universe", "SNAPSHOT_NIFTY500"))
        if universe != "SNAPSHOT_NIFTY500":
            raise DomainValidationError("Positional trend universe is invalid")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("as_of_date must be an ISO date") from exc
        if as_of >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("Positional trend signals require a completed date")
        revision = self.runtime.revision(self.STRATEGY_ID)
        if self.runtime.strategy_kind(self.STRATEGY_ID) != "event_signal":
            raise DomainValidationError("Positional trend revision is not an event_signal definition")
        rules = self.runtime.signal_rules(self.STRATEGY_ID)
        members, universe_hash, universe_metadata = self._members(universe, as_of, payload.get("universe_snapshot_id"))
        histories = self._histories(as_of, members, universe_metadata)
        sessions_by_exchange = {"NSE": self.market.session_dates(
            date(2021, 1, 1), as_of, exchange="NSE")}
        if not any(as_of.isoformat() in sessions for sessions in sessions_by_exchange.values()):
            raise DomainValidationError("Positional trend date has no stored market session")
        rows = []
        used_snapshots: set[str] = {str(revision["revision_id"]), universe_hash}
        matched_isins: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            matched_isins.add(str(identity["isin"]))
            symbol = str(identity["symbol"])
            used_snapshots.update(str(bar["snapshot_id"]) for bar in bars if bar.get("snapshot_id"))
            sessions = sessions_by_exchange[str(identity["exchange"])]
            if as_of.isoformat() not in sessions:
                continue
            features = feature_series(bars, sessions, symbol, rules)
            feature = next((item for item in reversed(features)
                            if item["signal_date"] == as_of.isoformat()), None)
            if feature is None:
                continue
            feature["instrument_id"] = instrument_id
            feature["exchange"] = identity["exchange"]
            rows.append(feature)
            day_bar = next((bar for bar in reversed(bars)
                            if str(bar["as_of_date"]) == as_of.isoformat()), None)
            if day_bar:
                used_snapshots.add(str(day_bar["snapshot_id"]))
        rows.sort(key=lambda item: (-float(item["adx14"] or 0),
                                    -float(item["adv30"] or 0), str(item["symbol"])))
        ranked = ranking_pattern_for("event_signal").rank({row["instrument_id"]: {
            "signal": "BUY" if row["filtered"] else None, "adx": row["adx14"] or 0,
            "adtv": row["adv30"] or 0} for row in rows},
            signal_rules={"adx_minimum": 0, "minimum_adtv": 0},
            symbols={row["instrument_id"]: row["symbol"] for row in rows})
        ranks = {item["instrument_id"]: item["rank"] for item in ranked}
        for row in rows:
            row["rank"] = ranks.get(row["instrument_id"])
        for row in rows:
            row.setdefault("rank", None)
        payload_out = {
            "strategy_id": self.STRATEGY_ID,
            "input_fingerprint": self._input_fingerprint(as_of, universe, universe_hash, histories),
            "universe_id": universe,
            "strategy_revision_id": revision["revision_id"],
            "as_of_date": as_of.isoformat(),
            "universe": {**universe_metadata, "sha256": universe_hash,
                         "eligible_members": len(members), "matched_isins": len(matched_isins),
                         "missing_isins": sorted(members - matched_isins),
                         "historical_membership": "pinned_snapshot" if payload.get("universe_snapshot_id") else "as_of_decision_date"},
            "ranking": "filtered signals ordered by ADX descending, ADTV descending, symbol ascending",
            "feature_code_hash": hashlib.sha256(
                _FEATURE_SOURCE.read_bytes()
            ).hexdigest(),
            "signals": rows,
            "buy_candidates": [row["instrument_id"] for row in rows if row["filtered"]],
            "exit_candidates": [row["instrument_id"] for row in rows if row["exit_signal"]],
        }
        digest = hashlib.sha256(json.dumps(payload_out, sort_keys=True, allow_nan=False).encode()).hexdigest()
        artifact_id = str(uuid5(NAMESPACE_URL, f"positional-trend-signals:{digest}"))
        if self.publisher.catalog.has(artifact_id):
            return {"artifact_id": artifact_id, "as_of_date": as_of.isoformat(),
                    "signal_count": len(payload_out["buy_candidates"]),
                    "exit_count": len(payload_out["exit_candidates"]), "reused": True}
        artifact = self.publisher.publish_json(self.CATEGORY, artifact_id, payload_out,
                                               upstream_ids=tuple(sorted(used_snapshots)),
                                               quality=QualityStatus.PARTIAL)
        return {"artifact_id": artifact.artifact_id, "as_of_date": as_of.isoformat(),
                "signal_count": len(payload_out["buy_candidates"]),
                "exit_count": len(payload_out["exit_candidates"]), "reused": False}

    def build_range(self, payload: dict[str, object]) -> dict[str, object]:
        """Build the event-signal branch once per pinned market session."""
        if not isinstance(payload, dict) or set(payload) - {"trading_dates", "universe", "universe_snapshot_id"}:
            raise DomainValidationError("positional trend range payload is invalid")
        dates = payload.get("trading_dates")
        if not isinstance(dates, list) or not dates:
            raise DomainValidationError("positional trend range requires trading_dates")
        results = [self.build_signals({"as_of_date": day, "universe": payload.get("universe", "SNAPSHOT_NIFTY500"), **({"universe_snapshot_id": payload["universe_snapshot_id"]} if payload.get("universe_snapshot_id") else {})})
                   for day in dates]
        return {"strategy_id": self.STRATEGY_ID, "results": results}

    def read_signals(self, as_of_date: date, universe: str = "SNAPSHOT_NIFTY500") -> tuple[str, dict[str, object]] | None:
        with sqlite_connection(self.market.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT artifact_id, category FROM catalog_artifacts WHERE category=? AND status='VALID' ORDER BY created_at DESC",
                (self.CATEGORY,),
            ).fetchall()
        current_fingerprint = None
        for row in rows:
            artifact_id = str(row["artifact_id"])
            try:
                _, payload = self.publisher.store.read_json(str(row["category"]), artifact_id)
            except DomainValidationError:
                continue
            if (payload.get("as_of_date") == as_of_date.isoformat()
                    and payload.get("universe_id", "SNAPSHOT_NIFTY500") == universe):
                if current_fingerprint is None:
                    current_fingerprint = self.input_fingerprint(as_of_date, universe)
                if payload.get("input_fingerprint") == current_fingerprint:
                    return artifact_id, payload
        return None
