"""Daily Strategy 4 signals, ranked and published with immutable lineage."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.application.positional_trend import feature_series
from src.application.sqlite import sqlite_connection
from src.platform_kernel import DomainValidationError, QualityStatus


class PositionalTrendJobs:
    STRATEGY_ID = "positional_trend_following"
    LEGACY_STRATEGY_ID = "strategy4"
    CATEGORY = "research/strategy4-signals"  # Keep legacy category for historical reads

    def __init__(self, market, publisher, runtime, universe_csv_path: str | Path | None = None):
        self.market, self.publisher, self.runtime = market, publisher, runtime
        self.universe_csv_path = (Path(universe_csv_path) if universe_csv_path else
                                  Path(__file__).parents[2] / "ind_nifty500list.csv")

    def _members(self, universe: str) -> tuple[set[str], str, dict[str, object]]:
        if universe == "APPLICATION_MCAP500":
            rows = [row for row in self.market.active_universe_members()
                    if float(row["last_market_cap"]) >= 5_000_000_000]
            if not rows:
                raise DomainValidationError("Strategy 4 application market-cap universe is not ready")
            members = {str(row["isin"]) for row in rows}
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
            return members, digest, {"source": universe, "snapshot_date": rows[0]["snapshot_date"],
                                     "member_count": len(rows), "members_by_exchange": {
                                         exchange: sum(row["exchange"] == exchange for row in rows)
                                         for exchange in ("NSE", "BSE")}}
        # Phase 2 Task 2.8: snapshot-driven universe
        if universe == "SNAPSHOT_NIFTY500":
            snapshot = self.market.latest_universe_snapshot("NIFTY 500")
            if snapshot is None:
                raise DomainValidationError("Strategy 4 universe snapshot is not available; download NIFTY 500 first")
            snapshot_id = str(snapshot["snapshot_id"])
            rows = self.market.universe_snapshot_members(snapshot_id, limit=1000)
            if not rows:
                raise DomainValidationError("Strategy 4 universe snapshot has no members")
            members = {str(row["isin"]) for row in rows}
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
            return members, digest, {"source": universe, "snapshot_id": snapshot_id,
                                     "snapshot_date": str(snapshot["snapshot_date"]),
                                     "member_count": len(rows)}
        if universe not in {"NIFTY500", "NIFTY_TOTAL_MARKET"}:
            raise DomainValidationError("Strategy 4 universe is invalid")
        csv_path = self.universe_csv_path if universe == "NIFTY500" else self.universe_csv_path.with_name("ind_niftytotalmarket_list.csv")
        if not csv_path.is_file():
            raise DomainValidationError(f"Strategy 4 universe CSV is missing: {csv_path}")
        raw = csv_path.read_bytes()
        try:
            rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise DomainValidationError("Strategy 4 universe CSV is invalid") from exc
        if not rows or not {"ISIN Code", "Series"} <= set(rows[0]):
            raise DomainValidationError("Strategy 4 universe CSV requires ISIN Code and Series")
        accepted = {"EQ", "BE"} if universe == "NIFTY_TOTAL_MARKET" else {"EQ"}
        members = {str(row["ISIN Code"]).strip() for row in rows
                   if row.get("Series", "").strip() in accepted and row.get("ISIN Code", "").strip()}
        if not members:
            raise DomainValidationError("Strategy 4 universe has no eligible members")
        return members, hashlib.sha256(raw).hexdigest(), {
            "source": universe, "csv": csv_path.name, "member_count": len(members),
            "included_series": sorted(accepted),
            "bse_fallback_isins": sorted(str(row["ISIN Code"]).strip() for row in rows
                                         if row.get("Series", "").strip() == "BE" and "BE" in accepted),
        }

    def _histories(self, as_of: date, members: set[str], metadata: dict[str, object]):
        histories = self.market.histories(date(2021, 1, 1), as_of, isins=members)
        if metadata["source"] == "APPLICATION_MCAP500":
            return histories
        fallback = set(metadata.get("bse_fallback_isins", []))
        return {key: value for key, value in histories.items()
                if value[1]["exchange"] == "NSE" or value[1]["isin"] in fallback}

    def _input_fingerprint(self, as_of: date, universe: str, universe_hash: str,
                           histories: dict) -> str:
        state = {
            "as_of_date": as_of.isoformat(), "universe": universe,
            "universe_hash": universe_hash,
            "revision_id": self.runtime.revision(self.STRATEGY_ID)["revision_id"],
            "feature_hash": hashlib.sha256(Path(__file__).with_name("positional_trend.py").read_bytes()).hexdigest(),
            "job_code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "histories": histories,
            "sessions": {exchange: self.market.session_dates(date(2021, 1, 1), as_of, exchange=exchange)
                         for exchange in ("NSE", "BSE")},
        }
        return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()

    def input_fingerprint(self, as_of: date, universe: str = "SNAPSHOT_NIFTY500") -> str:
        """Invalidate jobs and cached signals when their rules, code or market inputs change."""
        members, universe_hash, metadata = self._members(universe)
        histories = self._histories(as_of, members, metadata)
        return self._input_fingerprint(as_of, universe, universe_hash, histories)

    def build_signals(self, payload: dict[str, object]) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) - {"as_of_date", "universe"} or "as_of_date" not in payload:
            raise DomainValidationError("Strategy 4 signal job requires as_of_date and optional universe")
        universe = str(payload.get("universe", "SNAPSHOT_NIFTY500"))
        if universe not in {"NIFTY500", "NIFTY_TOTAL_MARKET", "APPLICATION_MCAP500", "SNAPSHOT_NIFTY500"}:
            raise DomainValidationError("Strategy 4 universe is invalid")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("as_of_date must be an ISO date") from exc
        if as_of >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("Strategy 4 signals require a completed date")
        revision = self.runtime.revision(self.STRATEGY_ID)
        if self.runtime.strategy_kind(self.STRATEGY_ID) != "event_signal":
            raise DomainValidationError("Strategy 4 revision is not an event_signal definition")
        rules = self.runtime.signal_rules(self.STRATEGY_ID)
        members, universe_hash, universe_metadata = self._members(universe)
        histories = self._histories(as_of, members, universe_metadata)
        sessions_by_exchange = {
            exchange: self.market.session_dates(date(2021, 1, 1), as_of, exchange=exchange)
            for exchange in ("NSE", "BSE")
        }
        if not any(as_of.isoformat() in sessions for sessions in sessions_by_exchange.values()):
            raise DomainValidationError("Strategy 4 date has no stored market session")
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
        for rank, row in enumerate((item for item in rows if item["filtered"]), 1):
            row["rank"] = rank
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
                         "historical_membership": "current constituents applied retrospectively"},
            "ranking": "filtered signals ordered by ADX descending, ADTV descending, symbol ascending",
            "feature_code_hash": hashlib.sha256(
                Path(__file__).with_name("positional_trend.py").read_bytes()
            ).hexdigest(),
            "signals": rows,
            "buy_candidates": [row["instrument_id"] for row in rows if row["filtered"]],
            "exit_candidates": [row["instrument_id"] for row in rows if row["exit_signal"]],
        }
        digest = hashlib.sha256(json.dumps(payload_out, sort_keys=True, allow_nan=False).encode()).hexdigest()
        artifact_id = str(uuid5(NAMESPACE_URL, f"strategy4-signals:{digest}"))
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
        if not isinstance(payload, dict) or set(payload) - {"trading_dates", "universe"}:
            raise DomainValidationError("positional trend range payload is invalid")
        dates = payload.get("trading_dates")
        if not isinstance(dates, list) or not dates:
            raise DomainValidationError("positional trend range requires trading_dates")
        results = [self.build_signals({"as_of_date": day, "universe": payload.get("universe", "SNAPSHOT_NIFTY500")})
                   for day in dates]
        return {"strategy_id": self.STRATEGY_ID, "results": results}

    def read_signals(self, as_of_date: date, universe: str = "SNAPSHOT_NIFTY500") -> tuple[str, dict[str, object]] | None:
        with sqlite_connection(self.market.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT artifact_id FROM catalog_artifacts WHERE category=? AND status='VALID' ORDER BY created_at DESC",
                (self.CATEGORY,),
            ).fetchall()
        current_fingerprint = None
        for row in rows:
            artifact_id = str(row["artifact_id"])
            try:
                _, payload = self.publisher.store.read_json(self.CATEGORY, artifact_id)
            except DomainValidationError:
                continue
            if (payload.get("as_of_date") == as_of_date.isoformat()
                    and payload.get("universe_id", "SNAPSHOT_NIFTY500") == universe):
                if current_fingerprint is None:
                    current_fingerprint = self.input_fingerprint(as_of_date, universe)
                if payload.get("input_fingerprint") == current_fingerprint:
                    return artifact_id, payload
        return None
