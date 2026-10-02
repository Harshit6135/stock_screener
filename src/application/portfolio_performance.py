"""Portfolio Performance and XIRR calculations."""

from datetime import date
from decimal import Decimal
from math import isfinite
from typing import Any

from src.execution_gateway import Ledger
from src.platform_kernel import DomainValidationError

def calculate_xirr(flows: list[tuple[date, Decimal]]) -> Decimal | None:
    if not flows or not any(value < 0 for _, value in flows) or not any(value > 0 for _, value in flows):
        return None
    origin = flows[0][0]
    rate = Decimal("0.1")
    for _ in range(50):
        value = sum(amount / (Decimal(1) + rate) ** (Decimal((day - origin).days) / Decimal(365)) for day, amount in flows)
        derivative = sum(-Decimal((day - origin).days) / Decimal(365) * amount / (Decimal(1) + rate) ** (Decimal((day - origin).days) / Decimal(365) + 1) for day, amount in flows)
        if not derivative:
            return None
        next_rate = rate - value / derivative
        if next_rate <= Decimal("-0.999999") or not isfinite(float(next_rate)):
            return None
        if abs(next_rate - rate) < Decimal("0.00000001"):
            return next_rate
        rate = next_rate
    return None

class PortfolioPerformance:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def calculate_xirr(self, account_id: str, current_equity: Decimal, current_date: date) -> Decimal | None:
        """Calculate XIRR using only external deposits/withdrawals and imported origins."""
        events = self.ledger.events(account_id)
        flows = []
        
        # Include opening cash
        accounts = self.ledger.accounts()
        account = next((a for a in accounts if a["account_id"] == account_id), None)
        if account and Decimal(account["opening_cash"]) > 0:
            # Derive account creation date from earliest ledger event since
            # the ledger_accounts schema has no created_at column.
            earliest_date = None
            for event in events:
                if event.get("occurred_at"):
                    earliest_date = date.fromisoformat(event["occurred_at"][:10])
                    break
            opened_date = earliest_date if earliest_date else current_date
            flows.append((opened_date, -Decimal(account["opening_cash"])))

        for event in events:
            event_date = date.fromisoformat(event["occurred_at"][:10])
            if event_date > current_date:
                continue
            if event["event_type"] == "CASH_TRANSFER":
                # Deposits are investor outflows; withdrawals are investor
                # inflows.  Trading fills are deliberately excluded.
                amount = Decimal(str(event["event"].get("amount", 0)))
                direction = event["event"].get("direction")
                if direction == "DEPOSIT":
                    flows.append((event_date, -amount))
                elif direction == "WITHDRAW":
                    flows.append((event_date, amount))
            elif event["event_type"] == "OPENING_POSITION_IMPORTED":
                # Imported holding cost basis
                units = Decimal(str(event["event"].get("units", 0)))
                unit_cost = Decimal(str(event["event"].get("unit_cost", 0)))
                opened_on_str = event["event"].get("acquisition_date")
                d = date.fromisoformat(opened_on_str[:10]) if opened_on_str else event_date
                flows.append((d, -(units * unit_cost)))
        
        if not flows:
            return None
            
        flows.append((current_date, current_equity))
        return calculate_xirr(sorted(flows))

    def calculate_drawdown(self, equity_history: list[Decimal]) -> Decimal:
        """Calculate max drawdown from equity history."""
        if not equity_history:
            return Decimal("0")
        peak = equity_history[0]
        max_drawdown = Decimal("0")
        for equity in equity_history:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak if peak > 0 else Decimal("0")
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        return max_drawdown
