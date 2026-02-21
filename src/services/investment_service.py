"""
Investment Service

Handles portfolio summary calculations, trade journal generation,
and manual trade creation. Centralizes business logic that was
previously scattered across route handlers.
"""
from datetime import datetime, date
from typing import Dict, List, Optional

from config import setup_logger
from repositories import InvestmentRepository, ActionsRepository, ConfigRepository
from .actions_service import ActionsService
from utils import calculate_xirr

logger = setup_logger(name="InvestmentService")


class InvestmentService:
    """Service layer for investment operations."""

    def __init__(self):
        self.inv_repo = InvestmentRepository()
        self.actions_repo = ActionsRepository()
        self.config_repo = ConfigRepository()

    def get_portfolio_summary(
        self, working_date: Optional[date] = None
    ) -> Optional[Dict]:
        """
        Get portfolio summary with on-the-fly recalculation.

        Recalculates portfolio_value, gains, absolute return %,
        and XIRR from current holdings and cash, rather than
        relying on stale DB values.

        Parameters:
            working_date: Date to get summary for (None = latest)

        Returns:
            Dict with all summary fields, or None if no summary
        """
        summary_model = self.inv_repo.get_summary(working_date)
        if not summary_model:
            return None

        summary = summary_model.to_dict()
        summary_date = summary['date']

        # Total capital from capital_events up to this date
        self._ensure_capital_events_seeded()
        total_capital = self.inv_repo.get_total_capital(
            summary_date
        )

        # Fresh calculation from current holdings
        holdings = self.inv_repo.get_holdings(summary_date)
        entry_value = float(sum(
            float(h.entry_price) * h.units for h in holdings
        ))
        current_value = float(sum(
            float(h.current_price) * h.units for h in holdings
        ))

        # Remaining cash from actual actions
        all_actions = (
            self.actions_repo.get_all_approved_actions()
        )
        total_bought = sum(
            float(a.execution_price or a.prev_close) * a.units
            for a in all_actions if a.type == 'buy'
        )
        total_sold = sum(
            float(a.execution_price or a.prev_close) * a.units
            for a in all_actions if a.type == 'sell'
        )
        remaining_cash = (
            total_capital - total_bought + total_sold
        )

        portfolio_value = current_value + remaining_cash

        # Gains
        total_gain = portfolio_value - total_capital
        unrealized_gain = current_value - entry_value

        # Realized gain from trade journal (FIFO)
        trades = self.get_trade_journal()
        realized_gain = (
            sum(t['pnl'] for t in trades) if trades else 0.0
        )

        absolute_return_pct = (
            (total_gain / entry_value) * 100
            if entry_value else 0
        )

        summary['portfolio_value'] = round(portfolio_value, 2)
        summary['gain'] = round(total_gain, 2)
        summary['gain_percentage'] = round(
            absolute_return_pct, 2
        )
        summary['invested_value'] = round(entry_value, 2)
        summary['unrealized_gain'] = round(
            unrealized_gain, 2
        )
        summary['realized_gain'] = round(realized_gain, 2)
        summary['remaining_capital'] = round(
            remaining_cash, 2
        )

        # Calculate XIRR from cash flows
        summary['xirr'] = self._calculate_xirr(
            current_value
        )

        return summary

    def _calculate_xirr(
        self, current_value: float
    ) -> Optional[float]:
        """
        Calculate XIRR from capital events (infusions as
        negative cashflows) plus current portfolio value as
        terminal cashflow.

        Parameters:
            current_value: Current market value of holdings

        Returns:
            XIRR as percentage, or None if calculation fails
        """
        try:
            cashflows = []

            # Each capital event is a negative cashflow
            events = self.inv_repo.get_all_capital_events()
            if not events:
                return None

            for ev in events:
                cashflows.append(
                    (-float(ev.amount), ev.date)
                )

            # Remaining cash in the portfolio today
            remaining = self._remaining_cash()
            terminal = current_value + remaining
            cashflows.append(
                (terminal, datetime.now().date())
            )

            xirr_val = calculate_xirr(cashflows)
            return (
                round(xirr_val * 100, 2)
                if xirr_val else None
            )
        except Exception:
            return None

    def _remaining_cash(self) -> float:
        """
        Compute remaining cash = total_capital - bought + sold.

        Returns:
            float: Cash remaining in the portfolio
        """
        total_capital = self.inv_repo.get_total_capital()
        all_actions = (
            self.actions_repo.get_all_approved_actions()
        )
        total_bought = sum(
            float(a.execution_price or a.prev_close) * a.units
            for a in all_actions if a.type == 'buy'
        )
        total_sold = sum(
            float(a.execution_price or a.prev_close) * a.units
            for a in all_actions if a.type == 'sell'
        )
        return total_capital - total_bought + total_sold

    def get_summary_history(self) -> List[Dict]:
        """
        Get all historical summaries for equity curve and drawdown chart.

        Returns:
            List of summary dicts ordered by date ascending
        """
        summaries = self.inv_repo.get_all_summaries()
        return [s.to_dict() for s in summaries]

    def get_trade_journal(self) -> List[Dict]:
        """
        Build trade journal from matched buy/sell pairs using FIFO.

        Matches each sell action to the earliest unmatched buy for the
        same symbol, then calculates P&L, return %, and holding period.

        Returns:
            List of trade dicts sorted by exit_date descending

        Raises:
            Exception: If unable to build trade journal
        """
        all_actions = self.actions_repo.get_all_approved_actions()

        # Group by symbol
        buys = {}  # symbol -> list of buy actions (FIFO)
        sells = []

        for a in sorted(all_actions, key=lambda x: x.action_date):
            if a.type == 'buy':
                if a.symbol not in buys:
                    buys[a.symbol] = []
                buys[a.symbol].append(a)
            elif a.type == 'sell':
                sells.append(a)

        trades = []
        for sell in sells:
            symbol = sell.symbol
            sell_units = sell.units
            sell_price = float(sell.execution_price or sell.prev_close)
            total_sell_value = sell_units * sell_price
            
            total_buy_cost = 0.0
            buy_date = None
            
            # FIFO matching
            matched_units = 0
            while matched_units < sell_units:
                if symbol in buys and buys[symbol]:
                    buy = buys[symbol][0]
                    buy_price = float(buy.execution_price or buy.prev_close)
                    
                    available = buy.units
                    needed = sell_units - matched_units
                    take = min(available, needed)
                    
                    total_buy_cost += take * buy_price
                    matched_units += take
                    
                    if not buy_date:
                        buy_date = buy.action_date
                    
                    # Update buy units or remove if fully consumed
                    if take >= available:
                        buys[symbol].pop(0)
                    else:
                        buy.units -= take
                else:
                    # No more buys (split/bonus shares) -> 0 cost basis
                    # The remaining sell value is pure profit
                    remaining = sell_units - matched_units
                    matched_units += remaining
                    # total_buy_cost += 0
                    if not buy_date:
                         buy_date = sell.action_date # Fallback

            pnl = total_sell_value - total_buy_cost
            entry_price = total_buy_cost / sell_units if sell_units else 0
            
            return_pct = 0.0
            if total_buy_cost > 0:
                return_pct = (pnl / total_buy_cost) * 100

            days_held = (sell.action_date - buy_date).days if buy_date else 0

            trades.append({
                'entry_date': str(buy_date) if buy_date else str(sell.action_date),
                'exit_date': str(sell.action_date),
                'symbol': symbol,
                'units': sell.units,
                'entry_price': round(entry_price, 2),
                'exit_price': round(sell_price, 2),
                'pnl': round(pnl, 2),
                'return_pct': round(return_pct, 2),
                'days_held': days_held,
                'reason': sell.reason or ''
            })

        # Sort by exit date descending
        trades.sort(key=lambda x: x['exit_date'], reverse=True)
        return trades

    def create_manual_buy(self, stocks: List[Dict]) -> str:
        """
        Create manual BUY actions with position sizing.

        Parameters:
            stocks: List of dicts with symbol, date, price, units, reason, config_name

        Returns:
            Confirmation message

        Raises:
            ValueError: If validation fails
        """
        actions = []
        # Get portfolio value (Total Risk Capital) for sizing
        # For manual buy, we use the same base as generating actions (Net Worth)
        portfolio_value = self.inv_repo.get_total_capital(include_realized=True)
        
        for stock in stocks:
            service = ActionsService(stock['config_name'])
            action = service.buy_action(
                symbol=stock['symbol'],
                action_date=stock['date'],
                prev_close=float(stock['price']),
                reason=stock['reason'],
                portfolio_value=portfolio_value,
                remaining_capital=portfolio_value, # Manual buy might ignore checks, but param is needed
                units=stock['units']
            )
            action['execution_price'] = float(stock['price'])
            actions.append(action)

        self.actions_repo.delete_actions(stocks[0]['date'])
        self.actions_repo.bulk_insert_actions(actions)
        return f"Manual BUY actions created for {[s['symbol'] for s in stocks]}"

    def create_manual_sell(self, data: Dict) -> str:
        """
        Create a manual SELL action.

        Parameters:
            data: Dict with symbol, date, price, units, reason

        Returns:
            Confirmation message

        Raises:
            ValueError: If validation fails
        """
        # Validate units against current holding
        holding = self.inv_repo.get_holdings_by_symbol(data['symbol'])
        if not holding:
            raise ValueError(
                f"Cannot sell {data['symbol']}: not in current holdings"
            )
        if data['units'] > holding.units:
            raise ValueError(
                f"Cannot sell {data['units']} units of {data['symbol']}: "
                f"only {holding.units} held"
            )

        action = ActionsService.sell_action(
            data['symbol'], data['date'], float(data['price']), data['units'], data['reason']
        )
        action['execution_price'] = float(data['price'])
        self.actions_repo.delete_actions(data['date'])
        self.actions_repo.bulk_insert_actions([action])
        return f"Manual SELL action created for {data['symbol']}: {data['units']} units"

    def sync_prices(self) -> str:
        """
        Sync portfolio holdings with latest market prices.

        Returns:
            Confirmation message
        """
        today = datetime.now().date()
        service = ActionsService("momentum_config")
        service.sync_latest_prices(today)
        return "Portfolio prices synced with latest market data"

    def recalculate_summary(self) -> str:
        """
        Recalculate and fix all summary records in the DB.

        Uses cumulative capital from capital_events per
        summary date so infusions mid-stream are handled.

        Returns:
            Confirmation message with number of records fixed
        """
        self._ensure_capital_events_seeded()

        all_summaries = self.inv_repo.get_all_summaries()
        if not all_summaries:
            return "No summary records to recalculate"

        # Total capital from all events (for gain calc)
        total_capital = self.inv_repo.get_total_capital()

        # Group actions by date
        all_actions = (
            self.actions_repo.get_all_approved_actions()
        )
        actions_by_date: Dict = {}
        for a in all_actions:
            if a.action_date not in actions_by_date:
                actions_by_date[a.action_date] = []
            actions_by_date[a.action_date].append(a)

        first_date = all_summaries[0].date
        rolling_capital = self.inv_repo.get_total_capital(
            first_date
        )
        fixed_count = 0

        for summary_model in all_summaries:
            summary_date = summary_model.date

            # Check for infusions between last date
            # and this date
            cap_at_date = (
                self.inv_repo.get_total_capital(summary_date)
            )
            infusion_delta = cap_at_date - (
                rolling_capital
                + sum(
                    float(
                        a.execution_price or a.prev_close
                    ) * a.units
                    for a in all_actions
                    if a.type == 'sell'
                    and a.action_date <= summary_date
                )
                - sum(
                    float(
                        a.execution_price or a.prev_close
                    ) * a.units
                    for a in all_actions
                    if a.type == 'buy'
                    and a.action_date <= summary_date
                )
            ) if fixed_count > 0 else 0
            if infusion_delta > 0:
                rolling_capital += infusion_delta

            date_actions = actions_by_date.get(
                summary_date, []
            )
            bought = sum(
                float(
                    a.execution_price or a.prev_close
                ) * a.units
                for a in date_actions if a.type == 'buy'
            )
            sold = sum(
                float(
                    a.execution_price or a.prev_close
                ) * a.units
                for a in date_actions if a.type == 'sell'
            )

            holdings = self.inv_repo.get_holdings(
                summary_date
            )
            holdings_value = float(sum(
                float(h.current_price) * h.units
                for h in holdings
            )) if holdings else 0.0

            capital_risk = float(sum(
                h.units * (
                    float(h.entry_price)
                    - float(h.current_sl)
                )
                for h in holdings
            )) if holdings else 0.0

            remaining_capital = (
                rolling_capital + sold - bought
            )
            portfolio_value = (
                holdings_value + remaining_capital
            )

            gain = round(
                portfolio_value - total_capital, 2
            )
            gain_pct = round(
                (portfolio_value - total_capital)
                / total_capital * 100, 2
            ) if total_capital else 0

            stop_value = float(sum(
                float(h.current_sl) * h.units
                for h in holdings
            )) if holdings else 0.0
            portfolio_risk = round(
                holdings_value - stop_value, 2
            )

            corrected = {
                'date': summary_date,
                'starting_capital': round(
                    rolling_capital, 2
                ),
                'sold': round(sold, 2),
                'bought': round(bought, 2),
                'capital_risk': round(capital_risk, 2),
                'portfolio_value': round(
                    portfolio_value, 2
                ),
                'portfolio_risk': portfolio_risk,
                'gain': gain,
                'gain_percentage': gain_pct,
            }
            self.inv_repo.insert_summary(corrected)
            fixed_count += 1

            rolling_capital = remaining_capital

        return (
            f"Recalculated {fixed_count} summary records"
        )

    def add_capital_event(
        self,
        event_date: date,
        amount: float,
        event_type: str,
        note: str = "",
    ) -> str:
        """
        Record a capital infusion or withdrawal.

        Parameters:
            event_date: Date of the event
            amount: Positive for infusion, negative for
                    withdrawal
            event_type: 'initial' | 'infusion' | 'withdrawal'
            note: Optional description

        Returns:
            Confirmation message

        Raises:
            ValueError: If event_type is invalid
        """
        valid_types = ('initial', 'infusion', 'withdrawal')
        if event_type not in valid_types:
            raise ValueError(
                f"event_type must be one of {valid_types}"
            )
        self.inv_repo.insert_capital_event({
            'date': event_date,
            'amount': amount,
            'event_type': event_type,
            'note': note,
        })
        return (
            f"Capital event recorded: {event_type} "
            f"of {amount} on {event_date}"
        )

    def get_capital_events(self) -> List[Dict]:
        """
        Get all capital events.

        Returns:
            List of capital event dicts
        """
        events = self.inv_repo.get_all_capital_events()
        return [e.to_dict() for e in events]

    def _ensure_capital_events_seeded(self) -> None:
        """
        If capital_events table is empty, auto-seed
        with config.initial_capital at the earliest
        summary date for backward compatibility.
        """
        events = self.inv_repo.get_all_capital_events()
        if events:
            return

        config_data = self.config_repo.get_config(
            'momentum_config'
        )
        initial = float(config_data.initial_capital)

        # Use earliest summary date, or today
        summaries = self.inv_repo.get_all_summaries()
        seed_date = (
            summaries[0].date if summaries
            else datetime.now().date()
        )

        self.inv_repo.insert_capital_event({
            'date': seed_date,
            'amount': initial,
            'event_type': 'initial',
            'note': 'Auto-seeded from config',
        })
        logger.info(
            f"Auto-seeded capital event: {initial} "
            f"on {seed_date}"
        )

