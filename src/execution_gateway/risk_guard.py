"""Global Risk Guard Configuration and Enforcement."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError


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
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                raise DomainValidationError(f"{name} must be a non-negative number")
        for name in fractions:
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1):
                raise DomainValidationError(f"{name} must be between zero and one")
        if self.max_positions is not None and (isinstance(self.max_positions, bool) or not isinstance(self.max_positions, int) or self.max_positions < 1):
            raise DomainValidationError("max_positions must be a positive integer")
        if self.min_holding_period_days is not None and (isinstance(self.min_holding_period_days, bool) or not isinstance(self.min_holding_period_days, int) or self.min_holding_period_days < 0):
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
                       VALUES (1, '{}', CURRENT_TIMESTAMP)"""
                )
            }
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

    def update_limits(self, limits: RiskGuardLimits) -> int:
        now = datetime.now(UTC).isoformat()
        data = {k: v for k, v in limits.__dict__.items() if v is not None}
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO portfolio_risk_config (config_json, updated_at) VALUES (?, ?)",
                (json.dumps(data), now)
            )
            row = connection.execute(
                "SELECT version FROM portfolio_risk_config ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return row[0]

@dataclass
class ProposedOrder:
    instrument_id: str
    side: str
    units: int
    price: float
    is_protective_stop: bool = False
    stop_price: float | None = None

class RiskGuardValidator:
    def __init__(
        self,
        limits: RiskGuardLimits,
        cash: float,
        holdings: dict[str, dict[str, Any]], # dict of instrument_id -> {'units': X, 'value': Y, 'sector': Z, 'stop': S}
        pending_reservations: list[ProposedOrder]
    ):
        self.limits = limits
        self.cash = cash
        self.holdings = holdings
        self.pending = pending_reservations

    def validate_orders(self, orders: list[ProposedOrder]) -> list[str]:
        violations = []
        all_orders = self.pending + orders
        
        # 1. Simulate portfolio state after all orders (for buying only, assuming protective stops are always allowed)
        projected_cash = self.cash
        projected_positions = len(self.holdings)
        projected_holdings = {k: v.copy() for k, v in self.holdings.items()}

        for o in all_orders:
            if o.side == "BUY":
                order_val = o.units * o.price
                if self.limits.max_order_value is not None and order_val > self.limits.max_order_value:
                    violations.append(f"Order for {o.instrument_id} value {order_val} exceeds max {self.limits.max_order_value}")
                
                projected_cash -= order_val
                if o.instrument_id not in projected_holdings:
                    projected_positions += 1
                    projected_holdings[o.instrument_id] = {"units": o.units, "value": order_val, "stop": o.stop_price or 0}
                else:
                    projected_holdings[o.instrument_id]["units"] += o.units
                    projected_holdings[o.instrument_id]["value"] += order_val
                    if o.stop_price:
                        projected_holdings[o.instrument_id]["stop"] = o.stop_price
            elif o.side == "SELL":
                # Sell rules
                pass

        if self.limits.min_reserve_cash is not None and projected_cash < self.limits.min_reserve_cash:
            violations.append(f"Projected cash {projected_cash} below minimum reserve {self.limits.min_reserve_cash}")
        
        if self.limits.max_positions is not None and projected_positions > self.limits.max_positions:
            violations.append(f"Projected positions {projected_positions} exceeds max {self.limits.max_positions}")
        
        # Calculate total equity for concentration/heat
        total_equity = projected_cash + sum(h["value"] for h in projected_holdings.values())
        
        if total_equity > 0:
            for inst, h in projected_holdings.items():
                concentration = h["value"] / total_equity
                if self.limits.max_concentration is not None and concentration > self.limits.max_concentration:
                    violations.append(f"Concentration for {inst} ({concentration:.2%}) exceeds max {self.limits.max_concentration:.2%}")
                
                # Check Heat
                stop = h.get("stop", 0)
                if stop > 0:
                    risk = max(0, h["value"] - (stop * h["units"]))
                    heat = risk / total_equity
                    if self.limits.max_heat is not None and heat > self.limits.max_heat:
                        violations.append(f"Heat for {inst} ({heat:.2%}) exceeds max {self.limits.max_heat:.2%}")
        
        return violations
