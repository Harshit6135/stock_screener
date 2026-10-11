"""Global Risk Guard Configuration and Enforcement."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


@dataclass(frozen=True)
class RiskGuardLimits:
    max_order_value: int | None = None
    max_daily_loss: int | None = None
    max_concentration: float | None = None
    max_sector_exposure: float | None = None
    max_positions: int | None = None
    min_holding_period_days: int | None = None
    min_reserve_cash: int | None = None
    max_heat: float | None = None
    max_drawdown: float | None = None

    def __post_init__(self) -> None:
        non_negative = ("max_order_value", "max_daily_loss", "min_reserve_cash")
        fractions = ("max_concentration", "max_sector_exposure", "max_heat", "max_drawdown")
        for name in non_negative:
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise DomainValidationError(f"{name} must be a non-negative number")
        for name in fractions:
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= 1
            ):
                raise DomainValidationError(f"{name} must be between zero and one")
        if self.max_positions is not None and (
            isinstance(self.max_positions, bool)
            or not isinstance(self.max_positions, int)
            or self.max_positions < 1
        ):
            raise DomainValidationError("max_positions must be a positive integer")
        if self.min_holding_period_days is not None and (
            isinstance(self.min_holding_period_days, bool)
            or not isinstance(self.min_holding_period_days, int)
            or self.min_holding_period_days < 0
        ):
            raise DomainValidationError("min_holding_period_days must be a non-negative integer")


class PortfolioRiskConfig:
    def __init__(self, database_path: str):
        self.database = database_path
        self._initialize()

    def _initialize(self) -> None:
        migrate_sqlite(
            self.database,
            "portfolio_risk_config",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS portfolio_risk_config (
                        version INTEGER PRIMARY KEY AUTOINCREMENT,
                        config_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )""",
                    """INSERT OR IGNORE INTO portfolio_risk_config (version, config_json, updated_at)
                       VALUES (1, '{}', CURRENT_TIMESTAMP)""",
                )
            },
        )

    def get_limits(self) -> tuple[int, RiskGuardLimits]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT version, config_json FROM portfolio_risk_config ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if not row:
                return 0, RiskGuardLimits()
            data = json.loads(row["config_json"])
            return row["version"], RiskGuardLimits(**data)

    def update_limits(self, limits: RiskGuardLimits, expected_version: int | None = None) -> int:
        now = datetime.now(UTC).isoformat()
        data = {k: v for k, v in limits.__dict__.items() if v is not None}
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT MAX(version) FROM portfolio_risk_config"
            ).fetchone()[0]
            if expected_version is not None and current != expected_version:
                raise DomainValidationError("stale risk configuration version")
            connection.execute(
                "INSERT INTO portfolio_risk_config (config_json, updated_at) VALUES (?, ?)",
                (json.dumps(data), now),
            )
            row = connection.execute(
                "SELECT version FROM portfolio_risk_config ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return row[0]
