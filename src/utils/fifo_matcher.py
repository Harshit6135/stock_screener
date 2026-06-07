"""
FIFO Trade Matcher

Shared utility for matching sell actions to buy actions using FIFO order.
Used by both backtesting (trade reconstruction) and live (trade journal).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Tuple


@dataclass
class BuyLeg:
    """A single buy lot consumed by a sell."""

    date: date
    price: float
    units: int


@dataclass
class MatchedTrade:
    """A completed trade: one sell matched against one or more buy lots."""

    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float  # weighted average of matched buy lots
    exit_price: float
    units: int
    pnl: float
    return_pct: float
    days_held: int
    reason: str = ""
    buy_legs: List[BuyLeg] = field(default_factory=list)


class FIFOTradeTracker:
    """
    FIFO trade matching engine.

    Add buys chronologically, then match sells against them.
    Each sell consumes buy lots in FIFO order, tracking remaining units.
    """

    def __init__(self):
        # symbol -> list of [date, price, remaining_units]
        self._buy_pool: Dict[str, List[List]] = {}

    def add_buy(self, symbol: str, buy_date: date, price: float, units: int) -> None:
        """Register a buy lot in the FIFO pool."""
        self._buy_pool.setdefault(symbol, []).append([buy_date, price, units])

    def match_sell(
        self,
        symbol: str,
        sell_date: date,
        sell_price: float,
        sell_units: int,
        reason: str = "",
    ) -> MatchedTrade:
        """
        Match a sell against the oldest available buy lots (FIFO).

        Returns a MatchedTrade with weighted-average entry price and
        individual buy legs for XIRR/cash-flow reconstruction.
        """
        lots = self._buy_pool.get(symbol, [])
        units_remaining = sell_units
        matched_legs: List[BuyLeg] = []
        total_cost = 0.0

        for lot in lots:
            if units_remaining <= 0:
                break
            lot_date, lot_price, lot_remaining = lot
            # Don't match buys dated after the sell
            if lot_date > sell_date:
                break
            consume = min(lot_remaining, units_remaining)
            if consume <= 0:
                continue
            matched_legs.append(BuyLeg(date=lot_date, price=lot_price, units=consume))
            total_cost += lot_price * consume
            lot[2] -= consume
            units_remaining -= consume

        # Purge fully consumed lots
        while lots and lots[0][2] <= 0:
            lots.pop(0)

        # Compute weighted-average entry price
        total_matched = sum(leg.units for leg in matched_legs)
        if total_matched > 0:
            entry_price = total_cost / total_matched
            entry_date = matched_legs[0].date
        else:
            entry_price = sell_price
            entry_date = sell_date

        pnl = (sell_price - entry_price) * total_matched
        return_pct = (pnl / total_cost * 100) if total_cost > 0 else 0.0
        days_held = (sell_date - entry_date).days

        return MatchedTrade(
            symbol=symbol,
            entry_date=entry_date,
            exit_date=sell_date,
            entry_price=round(entry_price, 2),
            exit_price=round(sell_price, 2),
            units=sell_units,
            pnl=round(pnl, 2),
            return_pct=round(return_pct, 2),
            days_held=days_held,
            reason=reason,
            buy_legs=matched_legs,
        )

    @classmethod
    def from_actions(
        cls,
        actions,
        use_fallback_price: bool = False,
    ) -> Tuple[List[MatchedTrade], Dict]:
        """
        Build matched trades from a list of action objects.

        Actions must have: type, symbol, action_date, execution_price, units, reason.
        Optionally: prev_close (used as fallback when use_fallback_price=True).

        Parameters:
            actions: Iterable of action objects (sorted by date ascending)
            use_fallback_price: If True, use prev_close when execution_price is None

        Returns:
            Tuple of (matched_trades, stats_dict)
        """
        tracker = cls()
        sorted_actions = sorted(actions, key=lambda a: a.action_date)

        total_buys = 0
        pyramid_buys = 0

        for a in sorted_actions:
            if a.type == "buy":
                price = float(a.execution_price) if a.execution_price else 0
                if use_fallback_price and not price:
                    price = float(getattr(a, "prev_close", 0) or 0)
                tracker.add_buy(a.symbol, a.action_date, price, int(a.units))
                total_buys += 1
                if getattr(a, "reason", "") == "pyramid_add":
                    pyramid_buys += 1

        trades = []
        for a in sorted_actions:
            if a.type != "sell":
                continue
            price = float(a.execution_price) if a.execution_price else 0
            if use_fallback_price and not price:
                price = float(getattr(a, "prev_close", 0) or 0)

            trade = tracker.match_sell(
                symbol=a.symbol,
                sell_date=a.action_date,
                sell_price=price,
                sell_units=int(a.units),
                reason=getattr(a, "reason", "") or "",
            )
            trades.append(trade)

        stats = {
            "total_buys": total_buys,
            "pyramid_buys": pyramid_buys,
            "total_sells": len(trades),
        }
        return trades, stats
