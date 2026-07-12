"""
Action Lifecycle
================

Manages the status transitions of pending actions: Pending -> Approved | Rejected.

Responsibility boundary
-----------------------
Reads:  actions (Pending), holdings (entry price/date), market_data (Monday open)
Writes: actions table only (status, execution_price, units, capital, risk)

No holdings mutations happen here -- that is ActionProcessor's job.

Two-phase approval
------------------
Phase 1 -- Sells (always approved)
    Every pending SELL is approved at the Monday market open price.
    Sell proceeds are added back to ``remaining_capital`` and the PnL
    delta is added to ``sizing_base`` so subsequent buys are sized on
    the post-sell portfolio value.

Phase 2 -- Buys (capital-gated)
    Each pending BUY is re-sized at the actual Monday open price using
    ``calculate_position_size()``. If the position value would exceed
    ``remaining_capital`` the buy stays Pending (not rejected -- it may
    be retried later or expire at week-end via ``reject_pending_actions``).

Capital arithmetic
------------------
``remaining_capital`` starts from ``InvestmentRepository.get_summary()``
and is updated inline as sells are approved (proceeds added) and buys are
approved (cost deducted). This makes approval order deterministic:
sells always run before buys.

Injection pattern
-----------------
Accepts an optional ``session`` and ``config_info`` so the backtesting
engine can inject an isolated DB session and a pre-loaded config object
without hitting the production database.
"""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from config import PyramidConfig, setup_logger
from repositories import ActionsRepository, ConfigRepository, InvestmentRepository, MarketDataRepository
from utils.sizing_utils import calculate_position_size

logger = setup_logger(name="ActionLifecycle")


class ActionLifecycle:
    """
    Approve or reject pending actions with capital awareness.

    Phase 1 — Sells: always approved at Monday's open; sell proceeds
    update remaining_capital and sizing_base for the subsequent buy phase.

    Phase 2 — Buys: re-sized at the actual execution (Monday open) price.
    Actions that cannot be filled due to insufficient capital stay Pending.
    """

    def __init__(
        self,
        config_name: str = None,
        session: Optional[Session] = None,
        config_info=None,
    ):
        config_repo = ConfigRepository()
        self.config = config_info or config_repo.get_config(config_name)
        self.actions_repo = ActionsRepository(session)
        self.investment_repo = InvestmentRepository(session)
        self.marketdata_repo = MarketDataRepository()

    # ------------------------------------------------------------------ #
    #  Capital setup                                                       #
    # ------------------------------------------------------------------ #

    def _init_approval_capital(self, action_date) -> tuple[float, float]:
        """
        Return (remaining_capital, sizing_base) for the approval pass.

        remaining_capital — cash available for new buys.
        sizing_base       — total portfolio value used for ATR position sizing.
        """
        summary = self.investment_repo.get_summary()
        remaining_capital = (
            float(summary.remaining_capital)
            if summary
            else self.investment_repo.get_total_capital(action_date)
        )
        sizing_base = self.investment_repo.get_total_capital(action_date, include_realized=True)
        return remaining_capital, sizing_base

    # ------------------------------------------------------------------ #
    #  Phase 1 — Sells                                                     #
    # ------------------------------------------------------------------ #

    def _approve_sells(
        self, actions_list, action_date, remaining_capital: float, sizing_base: float
    ) -> tuple[float, float, int]:
        """
        Approve every pending SELL at Monday's open price.

        Returns updated (remaining_capital, sizing_base, count_approved).
        """
        approved_count = 0
        for item in actions_list:
            if item.type != "sell" or item.status != "Pending":
                continue

            entry_data = self.investment_repo.get_holdings_by_symbol(item.symbol)
            if entry_data is None:
                logger.warning(
                    f"_approve_sells: no holding for sell {item.symbol} on {action_date} — rejecting"
                )
                self.actions_repo.update_action(
                    {"action_id": item.action_id, "status": "Rejected"}
                )
                continue

            md_obj = self.marketdata_repo.get_marketdata_by_trading_symbol(
                item.symbol, action_date
            )
            execution_price = item.execution_price or (md_obj.open if md_obj else None)
            if execution_price is None:
                logger.warning(
                    f"_approve_sells: no market data for {item.symbol} on {action_date} — skipping"
                )
                continue

            self.actions_repo.update_action(
                {
                    "action_id": item.action_id,
                    "status": "Approved",
                    "execution_price": execution_price,
                }
            )

            sell_proceeds = float(item.units * execution_price)
            remaining_capital += sell_proceeds
            # BUG-14 fix: use avg_price as cost basis for pyramided positions
            avg_p = float(
                getattr(entry_data, "avg_price", None) or entry_data.entry_price
            )
            pnl = sell_proceeds - avg_p * float(entry_data.units)
            sizing_base += pnl
            approved_count += 1

        return remaining_capital, sizing_base, approved_count

    # ------------------------------------------------------------------ #
    #  Phase 2 — Buys                                                      #
    # ------------------------------------------------------------------ #

    def _approve_buys(
        self, actions_list, action_date, remaining_capital: float, sizing_base: float
    ) -> tuple[float, int]:
        """
        Approve pending BUYs that fit within the remaining capital budget.

        Re-sizes each buy at the actual execution (Monday open) price so that
        position sizing is consistent with the real fill.

        Returns updated (remaining_capital, count_approved).
        """
        approved_count = 0
        for item in actions_list:
            if item.type != "buy" or item.status != "Pending":
                continue

            md_obj = self.marketdata_repo.get_marketdata_by_trading_symbol(
                item.symbol, action_date
            )
            execution_price = item.execution_price or (md_obj.open if md_obj else None)
            if execution_price is None:
                logger.warning(
                    f"_approve_buys: no market data for {item.symbol} on {action_date} — skipping"
                )
                continue

            is_pyramid = item.reason == "pyramid_add"
            alloc_capital = (
                sizing_base * PyramidConfig().pyramid_fraction if is_pyramid else sizing_base
            )

            atr = float(item.atr) if item.atr else 0.0
            risk_per_unit = round(atr * self.config.sl_multiplier, 2)

            sizing = calculate_position_size(
                atr=atr,
                current_price=float(execution_price),
                total_capital=alloc_capital,
                remaining_capital=remaining_capital,
                config=self.config,
            )
            units = sizing["shares"]
            capital_needed = sizing["position_value"]
            if units == 0:
                logger.info(
                    f"Keeping BUY {item.symbol} as Pending (capital-constrained, units=0)"
                )
                continue

            self.actions_repo.update_action(
                {
                    "action_id": item.action_id,
                    "status": "Approved",
                    "execution_price": execution_price,
                    "units": units,
                    "capital": capital_needed,
                    "risk": risk_per_unit,
                }
            )
            remaining_capital -= capital_needed
            approved_count += 1

        return remaining_capital, approved_count

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def approve_all_actions(self, action_date) -> int:
        """
        Approve all pending actions for a given date.

        Phase 1 — Sells: always approved at Monday open.
        Phase 2 — Buys: re-sized at actual execution price within budget.

        Returns:
            int: Total number of actions approved.
        """
        actions_list = self.actions_repo.get_actions(action_date)
        remaining_capital, sizing_base = self._init_approval_capital(action_date)

        remaining_capital, sizing_base, sell_count = self._approve_sells(
            actions_list, action_date, remaining_capital, sizing_base
        )
        _, buy_count = self._approve_buys(
            actions_list, action_date, remaining_capital, sizing_base
        )
        return sell_count + buy_count

    def reject_pending_actions(self) -> int:
        """
        Reject all pending actions (unfilled buys at end of week).

        Returns:
            int: Number of actions rejected.
        """
        pending = self.actions_repo.get_pending_actions()
        for action in pending:
            self.actions_repo.update_action({"action_id": action.action_id, "status": "Rejected"})
        return len(pending)
