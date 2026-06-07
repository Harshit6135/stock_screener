"""
Manual Trade Service

Handles operator-initiated trades outside the normal weekly cycle.
Delegates action building to ActionGenerator so all sizing / ATR logic
stays in one place.
"""

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from config import setup_logger
from repositories import ActionsRepository, ConfigRepository, InvestmentRepository, MarketDataRepository
from services.action_generator import ActionGenerator
from utils import get_previous_business_day

logger = setup_logger(name="ManualTradeService")


class ManualTradeService:
    """
    Create manual BUY / SELL actions for operator-initiated trades.

    These actions bypass the generate → approve cycle and are inserted
    directly with status=Pending so they still go through process_actions.
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
        # Delegate action building to ActionGenerator so sizing logic is shared
        self._generator = ActionGenerator(config_name, session, config_info)

    def create_manual_buy(self, stocks: List[Dict]) -> str:
        """
        Create manual BUY actions for a list of stocks.

        Each entry in stocks must have: symbol, date, units, price, reason.
        Capital is checked against the available remaining_capital;
        over-capital entries are reported but not inserted.

        Parameters:
            stocks: List of dicts with symbol, date, units, price, reason

        Returns:
            str: Summary message with created and skipped symbols
        """
        actions = []
        total_capital = self.investment_repo.get_total_capital(include_realized=True)
        summary = self.investment_repo.get_summary()
        remaining_capital = float(summary.remaining_capital) if summary else total_capital

        over_capital = []
        for stock in stocks:
            lookup_date = get_previous_business_day(stock["date"])
            md = self.marketdata_repo.get_marketdata_by_trading_symbol(stock["symbol"], lookup_date)
            if md is None:
                logger.warning(
                    f"create_manual_buy: no market data for {stock['symbol']} on {lookup_date} — skipping"
                )
                over_capital.append(stock)
                continue

            if remaining_capital < stock["units"] * stock["price"]:
                over_capital.append(stock)
                continue

            action, remaining_capital = self._generator.buy_action(
                symbol=stock["symbol"],
                action_date=stock["date"],
                prev_close=float(md.close),
                price=float(stock["price"]),
                reason=stock["reason"],
                total_capital=total_capital,
                remaining_capital=remaining_capital,
                units=stock["units"],
            )
            action.execution_price = float(stock["price"])
            actions.append(action)

        if actions:
            self.actions_repo.bulk_insert_actions(actions)

        created = [s["symbol"] for s in stocks if s not in over_capital]
        skipped = [s["symbol"] for s in over_capital]
        return (
            f"Manual BUY actions created for {created} "
            f"and over capital for {skipped}, before creating buy action infuse capital"
        )

    def create_manual_sell(self, stocks: List[Dict]) -> str:
        """
        Create manual SELL actions for a list of stocks.

        Each entry in stocks must have: symbol, date, units, price, reason.
        Symbols not found in current holdings are skipped.

        Parameters:
            stocks: List of dicts with symbol, date, units, price, reason

        Returns:
            str: Summary message with created and skipped symbols
        """
        actions = []
        not_in_holding = []
        current_holdings = self.investment_repo.get_holdings()
        holding_entry_prices = {h.symbol: float(h.entry_price) for h in (current_holdings or [])}

        for stock in stocks:
            if stock["symbol"] not in holding_entry_prices:
                not_in_holding.append(stock["symbol"])
                continue

            # Bug Q3 fix: use get_previous_business_day instead of naive timedelta(1)
            # so lookups on Mondays correctly land on the prior Friday, not Sunday.
            lookup_date = get_previous_business_day(stock["date"])
            md = self.marketdata_repo.get_marketdata_by_trading_symbol(
                stock["symbol"], lookup_date
            )
            prev_close = float(md.close) if md else float(stock["price"])

            action, _, _ = self._generator.sell_action(
                symbol=stock["symbol"],
                action_date=stock["date"],
                prev_close=prev_close,
                units=stock["units"],
                reason=stock["reason"],
                price=float(stock["price"]),
            )
            action.execution_price = float(stock["price"])
            actions.append(action)

        if actions:
            self.actions_repo.bulk_insert_actions(actions)

        created = [s["symbol"] for s in stocks if s["symbol"] not in not_in_holding]
        return (
            f"Manual SELL action created for {created} "
            f"and not in holding for {not_in_holding}"
        )
