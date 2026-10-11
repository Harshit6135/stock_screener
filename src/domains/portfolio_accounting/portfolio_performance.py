"""Portfolio Performance and XIRR calculations."""

from datetime import date
from decimal import Decimal
from typing import Any, Protocol


class PortfolioLedger(Protocol):
    """Read-only accounting inputs required to calculate portfolio returns."""

    def events(self, account_id: str) -> list[dict[str, Any]]: ...

    def accounts(self) -> list[dict[str, Any]]: ...


def calculate_xirr(flows: list[tuple[date, Decimal]]) -> Decimal | None:
    """Solve dated cash flows, checking the NPV residual rather than rate movement.

    Same-day flows are netted first. There is no annualized rate when all
    capital and terminal value have the same date. Solve in log(1 + rate)
    so negative returns cannot step outside the valid rate domain.
    """
    daily: dict[date, Decimal] = {}
    for day, amount in flows:
        if not amount.is_finite():
            return None
        daily[day] = daily.get(day, Decimal(0)) + amount
    flows = sorted((day, amount) for day, amount in daily.items() if amount)
    if (
        len(flows) < 2
        or not any(value < 0 for _, value in flows)
        or not any(value > 0 for _, value in flows)
    ):
        return None
    origin = flows[0][0]
    timed = [(Decimal((day - origin).days) / Decimal(365), amount) for day, amount in flows]
    tolerance = sum(abs(amount) for _, amount in flows) * Decimal("1e-14")

    def npv(log_rate):
        return sum(amount * (-years * log_rate).exp() for years, amount in timed)

    if abs(npv(Decimal(0))) <= tolerance:
        return Decimal(0)
    checkpoints = [
        Decimal(n) for n in (-32, -16, -8, -4, -2, -1, 0, 1, 2, 4, 8, 16, 32, 64, 128, 256)
    ]
    brackets = []
    left = checkpoints[0]
    left_value = npv(left)
    for right in checkpoints[1:]:
        right_value = npv(right)
        if left_value * right_value <= 0:
            brackets.append((left, right))
        left, left_value = right, right_value
    if not brackets:
        return None
    # For non-conventional flows, prefer a root near the usual 10% guess.
    left, right = min(brackets, key=lambda pair: abs((pair[0] + pair[1]) / 2 - Decimal("1.1").ln()))
    left_value = npv(left)
    for _ in range(200):
        midpoint = (left + right) / 2
        value = npv(midpoint)
        if abs(value) <= tolerance:
            rate = midpoint.exp() - 1
            return rate if rate > -1 else None
        if left_value * value <= 0:
            right = midpoint
        else:
            left, left_value = midpoint, value
    return None


def calculate_open_holdings_xirr(
    holdings: list[dict[str, Any]], current_date: date
) -> Decimal | None:
    """Return on remaining buy lots only; excludes idle cash and closed trades."""
    if not holdings or any(
        item.get("purchase_date_known") is False or item.get("price") is None for item in holdings
    ):
        return None
    flows = []
    terminal = Decimal(0)
    for item in holdings:
        purchased = date.fromisoformat(item["acquisition_date"])
        if purchased > current_date:
            return None
        flows.append((purchased, -Decimal(item["cost"])))
        terminal += Decimal(item["market_value"])
    flows.append((current_date, terminal))
    return calculate_xirr(flows)


class PortfolioPerformance:
    def __init__(self, ledger: PortfolioLedger):
        self.ledger = ledger

    def calculate_xirr(
        self, account_id: str, current_equity: Decimal, current_date: date
    ) -> Decimal | None:
        """Calculate XIRR using only external deposits/withdrawals and imported origins."""
        events = self.ledger.events(account_id)
        funded_imports = {
            version
            for event in events
            if event["event_type"] == "IMPORTED_POSITION_FUNDED"
            and date.fromisoformat(event["occurred_at"][:10]) <= current_date
            for version in event["event"]["import_versions"]
        }
        flows = []

        # Include opening cash
        accounts = self.ledger.accounts()
        account = next((a for a in accounts if a["account_id"] == account_id), None)
        if account and Decimal(account["opening_cash"]) > 0:
            # Legacy fixtures may omit opening_date; durable accounts store it.
            earliest_date = None
            for event in events:
                if event.get("occurred_at"):
                    earliest_date = date.fromisoformat(event["occurred_at"][:10])
                    break
            opened_date = (
                date.fromisoformat(account["opening_date"])
                if account.get("opening_date")
                else earliest_date
                if earliest_date
                else current_date
            )
            if opened_date <= current_date:
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
                if event.get("version") in funded_imports:
                    continue
                # Imported holding cost basis
                units = Decimal(str(event["event"].get("units", 0)))
                unit_cost = Decimal(str(event["event"].get("unit_cost", 0)))
                opened_on_str = event["event"].get("acquisition_date")
                d = date.fromisoformat(opened_on_str[:10]) if opened_on_str else event_date
                flows.append((d, -(units * unit_cost)))

        if not flows:
            return None

        # A cost-funded import can carry gains earned before this account's
        # cash history starts. Annualizing those gains over the account's age
        # would attribute months of performance to a day or two of funding.
        # Recovered lot dates do not establish historical external deposits.
        capital_start = min(day for day, _ in flows)
        imported_dates = {}
        for event in events:
            if date.fromisoformat(event["occurred_at"][:10]) > current_date:
                continue
            payload = event["event"]
            if (
                event["event_type"] == "OPENING_POSITION_IMPORTED"
                and event.get("version") in funded_imports
            ):
                imported_dates[payload["instrument_id"]] = [
                    date.fromisoformat(payload["acquisition_date"][:10])
                ]
            elif (
                event["event_type"] == "OPEN_LOTS_RECONCILED"
                and payload["instrument_id"] in imported_dates
            ):
                imported_dates[payload["instrument_id"]] = [
                    date.fromisoformat(lot["date"]) for lot in payload["lots"]
                ]
        if any(day < capital_start for days in imported_dates.values() for day in days):
            return None

        flows.append((current_date, current_equity))
        return calculate_xirr(sorted(flows))

    def calculate_drawdown(self, equity_history: list[Decimal]) -> Decimal:
        """Calculate max drawdown from equity history."""
        if not equity_history:
            return Decimal(0)
        peak = equity_history[0]
        max_drawdown = Decimal(0)
        for equity in equity_history:
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak if peak > 0 else Decimal(0)
            max_drawdown = max(max_drawdown, drawdown)
        return max_drawdown
