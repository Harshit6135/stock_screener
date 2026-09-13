"""Durable, operator-reviewed paper action proposals from prior rankings."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.application.strategy_configs import StrategyConfigs
from src.execution_gateway import Ledger
from src.platform_kernel import DomainValidationError, Money, QualityStatus, Quantity
from src.portfolio_accounting import Fill, FillSide
from src.portfolio_engine import (
    Candidate,
    DecisionType,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)

_BUY_TYPES = {DecisionType.BUY, DecisionType.PYRAMID_ADD}


class ActionJobs:
    def __init__(
        self,
        database: str | Path,
        market: MarketRepository,
        research: ResearchJobs,
        ledger: Ledger,
        publisher: ArtifactPublisher,
        configs: StrategyConfigs | None = None,
    ) -> None:
        self.database = Path(database)
        self.market = market
        self.research = research
        self.ledger = ledger
        self.publisher = publisher
        self.configs = configs
        migrate_sqlite(
            self.database,
            "actions",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS action_proposals (
                        proposal_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL, action_date TEXT NOT NULL,
                        ranking_week_end TEXT NOT NULL, expected_ledger_version INTEGER NOT NULL,
                        status TEXT NOT NULL, artifact_id TEXT NOT NULL,
                        decision_json TEXT NOT NULL, resulting_ledger_version INTEGER,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
                    "CREATE INDEX IF NOT EXISTS action_proposals_account_date ON action_proposals(account_id, action_date)",
                    """CREATE TABLE IF NOT EXISTS action_proposal_events (
                        event_id INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL,
                        event_type TEXT NOT NULL, occurred_at TEXT NOT NULL,
                        detail_json TEXT NOT NULL,
                        FOREIGN KEY(proposal_id) REFERENCES action_proposals(proposal_id))""",
                )
            },
        )

    def generate(self, payload: dict[str, Any]) -> dict[str, object]:
        if set(payload) not in (
            {"account_id", "strategy_id", "action_date"},
            {"account_id", "strategy_id", "action_date", "max_positions"},
        ):
            raise DomainValidationError(
                "action generation requires account, strategy, date and limit"
            )
        account_id = payload["account_id"]
        strategy_id = payload["strategy_id"]
        positions = payload.get("max_positions")
        if (
            not isinstance(account_id, str)
            or not account_id.strip()
            or strategy_id not in {"strategy1", "strategy2"}
            or positions is not None
            and (
                isinstance(positions, bool)
                or not isinstance(positions, int)
                or not 1 <= positions <= 20
            )
        ):
            raise DomainValidationError("action generation parameters are invalid")
        try:
            action_date = date.fromisoformat(payload["action_date"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("action_date must be an ISO date") from exc
        if action_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("paper action date must be completed")
        active_config = (
            self.configs.active(strategy_id, action_date) if self.configs is not None else None
        )
        if active_config is not None:
            configured_settings = active_config["settings"]
            configured_positions = configured_settings["max_positions"]
            if configured_positions > 20:
                raise DomainValidationError(
                    "active configuration exceeds paper action position limit"
                )
            if positions is not None and positions != configured_positions:
                raise DomainValidationError("max_positions conflicts with the active configuration")
            positions = configured_positions
        elif positions is None:
            raise DomainValidationError("max_positions is required without an active configuration")
        if not isinstance(positions, int):
            raise DomainValidationError("max_positions is invalid")
        account = next(
            (item for item in self.ledger.accounts() if item["account_id"] == account_id), None
        )
        if account is None:
            raise DomainValidationError("paper account does not exist")
        projection = self.ledger.projection(account_id)
        weeks = [week for week in self.research.ranking_weeks(strategy_id) if week < action_date]
        if not weeks:
            raise DomainValidationError("no prior completed ranking is available")
        week_end = weeks[-1]
        ranked = self.research.top_rankings(week_end, 500, strategy_id)
        if not ranked:
            raise DomainValidationError("prior ranking is empty")
        histories = self.market.histories(action_date, action_date)
        bars: dict[str, MarketBar] = {}
        snapshot_ids: set[str] = {str(ranked[0]["artifact_id"])}
        if active_config is not None:
            snapshot_ids.add(str(active_config["artifact_id"]))
        for instrument_id, (values, identity) in histories.items():
            if str(identity["isin"]).startswith("INDEX:"):
                continue
            bar = values[0]
            bars[instrument_id] = MarketBar(
                instrument_id,
                action_date,
                Decimal(str(bar["open"])),
                Decimal(str(bar["high"])),
                Decimal(str(bar["low"])),
                Decimal(str(bar["close"])),
            )
            snapshot_ids.add(str(bar["snapshot_id"]))
        if not bars:
            raise DomainValidationError("action date has no market bars")
        eligible = [item for item in ranked if Decimal(str(item["score"])) > 0]
        if len(eligible) < positions or any(
            str(item["instrument_id"]) not in bars for item in eligible[:positions]
        ):
            raise DomainValidationError("top-ranked action candidate is missing a market bar")
        candidates = tuple(
            Candidate(str(item["instrument_id"]), Decimal(str(item["score"])))
            for item in eligible
            if str(item["instrument_id"]) in bars
        )
        score_by_id = {str(item["instrument_id"]): Decimal(str(item["score"])) for item in ranked}
        lots_by_instrument: dict[str, tuple[int, Decimal]] = {}
        for lot in projection.open_lots:
            units, cost = lots_by_instrument.get(lot.instrument_id, (0, Decimal(0)))
            lots_by_instrument[lot.instrument_id] = (
                units + lot.remaining_units.units,
                cost + lot.unit_cost.amount * lot.remaining_units.units,
            )
        holdings = tuple(
            Holding(
                instrument_id,
                Quantity(units),
                Money(cost / units),
                Money(cost / units * Decimal("0.9")),
                score_by_id.get(instrument_id, Decimal(0)),
            )
            for instrument_id, (units, cost) in lots_by_instrument.items()
        )
        if any(holding.instrument_id not in bars for holding in holdings):
            raise DomainValidationError("held stock is missing an action-date market bar")
        settings = active_config["settings"] if active_config is not None else None
        policy = PortfolioPolicy(
            positions,
            Decimal(str(settings["exit_threshold"])) if settings else Decimal(40),
            max_position_fraction=min(
                Decimal(1) / Decimal(positions),
                Decimal(str(settings["max_concentration_pct"])) if settings else Decimal(1),
            ),
            swap_buffer=Decimal(str(settings["buffer_percent"])) if settings else Decimal("0.25"),
        )
        decisions, _ = evaluate(PortfolioState(projection.cash, holdings), policy, candidates, bars)
        identities = {
            item.instrument_id: self.market.instrument_by_id(item.instrument_id)
            for item in decisions
            if item.instrument_id is not None
        }
        resolved_symbols = {
            instrument_id: str(identity["symbol"])
            for instrument_id, identity in identities.items()
            if identity is not None
        }
        encoded_decisions = [
            {
                "type": item.type.value,
                "instrument_id": item.instrument_id,
                "symbol": resolved_symbols.get(item.instrument_id) if item.instrument_id else None,
                "units": item.units.units if item.units else None,
                "execution_price": str(item.execution_price.amount)
                if item.execution_price
                else None,
                "fee": str(item.fee.amount),
                "reason": item.reason,
            }
            for item in decisions
        ]
        version = int(str(account["version"]))
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "account_id": account_id,
                    "version": version,
                    "strategy_id": strategy_id,
                    "action_date": action_date.isoformat(),
                    "max_positions": positions,
                    "config_revision_id": active_config["revision_id"] if active_config else None,
                    "sources": sorted(snapshot_ids),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        proposal_id = str(uuid5(NAMESPACE_URL, f"paper-action-proposal:{fingerprint}"))
        if self.publisher.catalog.has(proposal_id):
            self._recover_projection(proposal_id)
            return self.proposal(proposal_id)
        self.publisher.publish_json(
            "actions/proposals",
            proposal_id,
            {
                "proposal_id": proposal_id,
                "account_id": account_id,
                "strategy_id": strategy_id,
                "ranking_week_end": week_end.isoformat(),
                "action_date": action_date.isoformat(),
                "expected_ledger_version": version,
                "policy": {
                    "max_positions": positions,
                    "exit_score": str(settings["exit_threshold"]) if settings else "40",
                    "max_position_fraction": str(policy.max_position_fraction),
                    "swap_buffer": str(policy.swap_buffer),
                },
                "config_revision_id": active_config["revision_id"] if active_config else None,
                "limitations": [
                    "paper-only execution against a completed historical bar",
                    "stop derived as 90% of FIFO unit cost; v3 trailing stops not imported",
                ],
                "decisions": encoded_decisions,
            },
            upstream_ids=tuple(sorted(snapshot_ids)),
            quality=QualityStatus.PARTIAL,
        )
        self._recover_projection(proposal_id)
        return self.proposal(proposal_id)

    def _recover_projection(self, proposal_id: str) -> None:
        """Complete the SQL projection if publication finished before a crash."""
        manifest, payload = self.publisher.store.read_json("actions/proposals", proposal_id)
        if manifest.artifact_id != proposal_id:
            raise DomainValidationError("action proposal artifact identity is invalid")
        timestamp = manifest.created_at
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO action_proposals
                   (proposal_id, account_id, strategy_id, action_date, ranking_week_end,
                    expected_ledger_version, status, artifact_id, decision_json,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
                (
                    proposal_id,
                    payload["account_id"],
                    payload["strategy_id"],
                    payload["action_date"],
                    payload["ranking_week_end"],
                    payload["expected_ledger_version"],
                    manifest.artifact_id,
                    json.dumps(payload["decisions"], sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] == 1:
                connection.execute(
                    """INSERT INTO action_proposal_events
                       (proposal_id, event_type, occurred_at, detail_json)
                       VALUES (?, 'GENERATED', ?, '{}')""",
                    (proposal_id, timestamp),
                )

    def proposal(self, proposal_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("action proposal was not found")
        return self._decode(row)

    @staticmethod
    def _decode(row: Any) -> dict[str, object]:
        result = dict(row)
        result["decisions"] = json.loads(result.pop("decision_json"))
        return result

    def proposals(self, account_id: str, limit: int = 50) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise DomainValidationError("action proposal limit must be 1..100")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM action_proposals WHERE account_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (account_id, limit),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def events(self, proposal_id: str) -> list[dict[str, object]]:
        self.proposal(proposal_id)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT event_type, occurred_at, detail_json FROM action_proposal_events
                   WHERE proposal_id=? ORDER BY event_id""",
                (proposal_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"],
                "detail": json.loads(row["detail_json"]),
            }
            for row in rows
        ]

    def decide(self, proposal_id: str, action: str) -> dict[str, object]:
        if action not in {"APPROVED", "REJECTED"}:
            raise DomainValidationError("proposal decision is invalid")
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("action proposal was not found")
            if row["status"] != "PENDING":
                raise DomainValidationError("action proposal is not pending")
            connection.execute(
                "UPDATE action_proposals SET status=?, updated_at=? WHERE proposal_id=?",
                (action, timestamp, proposal_id),
            )
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json) VALUES (?, ?, ?, '{}')""",
                (proposal_id, action, timestamp),
            )
        return self.proposal(proposal_id)

    def process(self, proposal_id: str) -> dict[str, object]:
        proposal = self.proposal(proposal_id)
        if proposal["status"] == "PROCESSED":
            return proposal
        if proposal["status"] != "APPROVED":
            raise DomainValidationError("action proposal is not approved")
        with sqlite_connection(self.database, read_only=True) as connection:
            artifact = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id=?",
                (proposal["artifact_id"],),
            ).fetchone()
        if artifact is None or artifact[0] != "VALID":
            raise DomainValidationError("action proposal artifact is not valid")
        action_date = date.fromisoformat(str(proposal["action_date"]))
        executed_at = datetime.combine(action_date, time(9, 15), tzinfo=ZoneInfo("Asia/Kolkata"))
        fills = []
        for item in cast(list[dict[str, object]], proposal["decisions"]):
            decision_type = DecisionType(item["type"])
            if decision_type == DecisionType.NO_ACTION:
                continue
            if not item["instrument_id"] or item["units"] is None:
                raise DomainValidationError("priced action decision is incomplete")
            fills.append(
                Fill(
                    str(item["instrument_id"]),
                    action_date,
                    FillSide.BUY if decision_type in _BUY_TYPES else FillSide.SELL,
                    Quantity(int(str(item["units"]))),
                    Money(Decimal(str(item["execution_price"]))),
                    Money(Decimal(str(item["fee"]))),
                    executed_at,
                    proposal_id,
                )
            )
        resulting_version = (
            self.ledger.record_fills(
                str(proposal["account_id"]),
                f"paper-proposal:{proposal_id}",
                int(str(proposal["expected_ledger_version"])),
                tuple(fills),
            )
            if fills
            else int(str(proposal["expected_ledger_version"]))
        )
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not fills:
                current = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM ledger_events WHERE account_id=?",
                    (proposal["account_id"],),
                ).fetchone()[0]
                if current != resulting_version:
                    raise DomainValidationError("stale ledger version")
            changed = connection.execute(
                """UPDATE action_proposals SET status='PROCESSED',
                   resulting_ledger_version=?, updated_at=?
                   WHERE proposal_id=? AND status='APPROVED'""",
                (resulting_version, timestamp, proposal_id),
            )
            if changed.rowcount != 1:
                return self.proposal(proposal_id)
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json)
                   VALUES (?, 'PROCESSED', ?, ?)""",
                (
                    proposal_id,
                    timestamp,
                    json.dumps({"resulting_ledger_version": resulting_version}),
                ),
            )
        return self.proposal(proposal_id)
