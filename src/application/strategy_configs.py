"""Immutable, operator-approved strategy configuration revisions."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypedDict, cast
from uuid import NAMESPACE_URL, uuid5

from src.application.publication import ArtifactPublisher
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError, QualityStatus

_STRATEGIES = {"strategy1", "strategy2"}
_FIELDS = {
    "initial_capital",
    "risk_threshold",
    "max_positions",
    "min_position_percent",
    "exit_threshold",
    "buffer_percent",
    "sl_multiplier",
    "hard_sl_percent",
    "atr_fallback_percent",
    "max_concentration_pct",
}
_DEFAULTS = {
    "initial_capital": "100000",
    "risk_threshold": "1",
    "max_positions": 15,
    "min_position_percent": "0.05",
    "exit_threshold": "40",
    "buffer_percent": "0.25",
    "sl_multiplier": "2",
    "hard_sl_percent": "0.03",
    "atr_fallback_percent": "0.06",
    "max_concentration_pct": "0.25",
}


class StrategySettings(TypedDict):
    initial_capital: str
    risk_threshold: str
    max_positions: int
    min_position_percent: str
    exit_threshold: str
    buffer_percent: str
    sl_multiplier: str
    hard_sl_percent: str
    atr_fallback_percent: str
    max_concentration_pct: str


class ActiveStrategyConfig(TypedDict):
    revision_id: str
    artifact_id: str
    settings: StrategySettings


class StrategyConfigs:
    def __init__(self, database: str | Path, publisher: ArtifactPublisher) -> None:
        self.database, self.publisher = Path(database), publisher
        migrate_sqlite(
            self.database,
            "strategy_configs",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS strategy_config_revisions (
                        revision_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL,
                        settings_json TEXT NOT NULL, artifact_id TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL, effective_from TEXT, created_at TEXT NOT NULL,
                        approved_at TEXT, retired_at TEXT)""",
                    "CREATE INDEX IF NOT EXISTS strategy_config_effective ON strategy_config_revisions(strategy_id, status, effective_from)",
                )
            },
        )

    @staticmethod
    def _settings(value: object) -> dict[str, object]:
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise DomainValidationError(
                "strategy settings must contain the complete supported schema"
            )
        parsed: dict[str, object] = {}
        for field in _FIELDS - {"max_positions"}:
            raw = value[field]
            if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
                raise DomainValidationError(f"{field} must be numeric")
            try:
                decimal = Decimal(str(raw))
            except (InvalidOperation, ValueError) as exc:
                raise DomainValidationError(f"{field} must be numeric") from exc
            if not decimal.is_finite():
                raise DomainValidationError(f"{field} must be finite")
            parsed[field] = str(decimal)
        positions = value["max_positions"]
        if (
            isinstance(positions, bool)
            or not isinstance(positions, int)
            or not 1 <= positions <= 50
        ):
            raise DomainValidationError("max_positions must be an integer from 1 to 50")
        parsed["max_positions"] = positions
        positive = {"initial_capital", "risk_threshold", "sl_multiplier", "atr_fallback_percent"}
        fractions = {
            "min_position_percent",
            "hard_sl_percent",
            "max_concentration_pct",
        }
        if any(Decimal(str(parsed[field])) <= 0 for field in positive):
            raise DomainValidationError("capital, risk and sizing settings must be positive")
        if any(not Decimal(0) < Decimal(str(parsed[field])) <= Decimal(1) for field in fractions):
            raise DomainValidationError("percentage settings must be in (0, 1]")
        if Decimal(str(parsed["exit_threshold"])) < 0 or Decimal(str(parsed["buffer_percent"])) < 0:
            raise DomainValidationError("exit_threshold and buffer_percent must be non-negative")
        if Decimal(str(parsed["min_position_percent"])) > Decimal(
            str(parsed["max_concentration_pct"])
        ):
            raise DomainValidationError("minimum position cannot exceed maximum concentration")
        return {field: parsed[field] for field in sorted(parsed)}

    @staticmethod
    def defaults() -> dict[str, object]:
        return dict(_DEFAULTS)

    @staticmethod
    def _decode(row: Any) -> dict[str, object]:
        result = dict(row)
        result["settings"] = json.loads(result.pop("settings_json"))
        return result

    def create(self, strategy_id: str, settings: object) -> dict[str, object]:
        if strategy_id not in _STRATEGIES:
            raise DomainValidationError("strategy_id is invalid")
        normalized = self._settings(settings)
        revision_id = str(
            uuid5(
                NAMESPACE_URL,
                "strategy-config:"
                + json.dumps({"strategy_id": strategy_id, "settings": normalized}, sort_keys=True),
            )
        )
        artifact_id = revision_id
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "configurations/strategies",
                artifact_id,
                {"revision_id": revision_id, "strategy_id": strategy_id, "settings": normalized},
                quality=QualityStatus.COMPLETE,
            )
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO strategy_config_revisions
                   (revision_id, strategy_id, settings_json, artifact_id, status, created_at)
                   VALUES (?, ?, ?, ?, 'DRAFT', ?)""",
                (
                    revision_id,
                    strategy_id,
                    json.dumps(normalized, sort_keys=True),
                    artifact_id,
                    timestamp,
                ),
            )
        return self.get(revision_id)

    def get(self, revision_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM strategy_config_revisions WHERE revision_id=?", (revision_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("strategy configuration revision was not found")
        return self._decode(row)

    def revisions(self, strategy_id: str) -> list[dict[str, object]]:
        if strategy_id not in _STRATEGIES:
            raise DomainValidationError("strategy_id is invalid")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM strategy_config_revisions WHERE strategy_id=?
                   ORDER BY created_at DESC""",
                (strategy_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def approve(self, revision_id: str, effective_from: object) -> dict[str, object]:
        try:
            effective = date.fromisoformat(str(effective_from))
        except ValueError as exc:
            raise DomainValidationError("effective_from must be an ISO date") from exc
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM strategy_config_revisions WHERE revision_id=?", (revision_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("strategy configuration revision was not found")
            if row["status"] != "DRAFT":
                raise DomainValidationError("only a draft revision can be approved")
            conflict = connection.execute(
                """SELECT 1 FROM strategy_config_revisions
                   WHERE strategy_id=? AND status='APPROVED' AND effective_from=?""",
                (row["strategy_id"], effective.isoformat()),
            ).fetchone()
            if conflict is not None:
                raise DomainValidationError("an approved revision already has this effective date")
            connection.execute(
                """UPDATE strategy_config_revisions SET status='APPROVED', effective_from=?,
                   approved_at=? WHERE revision_id=?""",
                (effective.isoformat(), timestamp, revision_id),
            )
        return self.get(revision_id)

    def active(self, strategy_id: str, as_of_date: object) -> ActiveStrategyConfig | None:
        if strategy_id not in _STRATEGIES:
            raise DomainValidationError("strategy_id is invalid")
        try:
            requested = date.fromisoformat(str(as_of_date))
        except ValueError as exc:
            raise DomainValidationError("as_of_date must be an ISO date") from exc
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                """SELECT * FROM strategy_config_revisions
                   WHERE strategy_id=? AND status='APPROVED' AND effective_from<=?
                   ORDER BY effective_from DESC LIMIT 1""",
                (strategy_id, requested.isoformat()),
            ).fetchone()
        return cast(ActiveStrategyConfig, self._decode(row)) if row is not None else None
