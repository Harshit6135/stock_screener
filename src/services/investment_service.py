"""
Investment Service

Handles portfolio summary calculations, trade journal generation,
and manual trade creation. Centralizes business logic that was
previously scattered across route handlers.
"""
import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

from sqlalchemy.orm import Session
from datetime import datetime, date
from typing import Dict, List, Optional

from repositories import *
from config import setup_logger
from utils import calculate_xirr, get_prev_friday, calculate_effective_stop


logger = setup_logger(name="InvestmentService")


class InvestmentService:
    """Service layer for investment operations."""

    def __init__(self, session: Optional[Session] = None):
        self.inv_repo = InvestmentRepository(session)
        self.actions_repo = ActionsRepository(session)
        self.config_repo = ConfigRepository()

        self.indicators_repo = IndicatorsRepository()
        self.marketdata_repo = MarketDataRepository()
        self.ranking_repo = RankingRepository()

    def ensure_capital_events_seeded(self, seed_date = None) -> None:
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
        if not seed_date:
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

    def _calculate_xirr(
        self, portfolio_value
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

            events = self.inv_repo.get_all_capital_events()
            if not events:
                return None

            for ev in events:
                cashflows.append(
                    (-float(ev.amount), ev.date)
                )
            cashflows.append(
                (portfolio_value, datetime.now().date())
            )

            xirr_val = calculate_xirr(cashflows)
            return (
                round(xirr_val * 100, 2)
                if xirr_val else None
            )
        except Exception:
            return None

    def get_portfolio_summary(
        self, working_date: Optional[date] = None
    ) -> Optional[Dict]:

        summary_FROM_DB = self.inv_repo.get_summary(working_date)
        if not summary_FROM_DB:
            return None

        summary = summary_FROM_DB.to_dict()
        summary_date = summary['date']

        self.ensure_capital_events_seeded()
        total_capital = self.inv_repo.get_total_capital(summary_date, include_realized=True)
        total_invested_captial = self.inv_repo.get_total_capital(summary_date, include_realized=False)

        holdings = self.inv_repo.get_holdings(summary_date)
        entry_value = float(sum(h.entry_price * h.units for h in holdings))
        current_value = float(sum(h.current_price * h.units for h in holdings)) #TODO Handle split/bonus
        stoploss_value = float(sum(h.current_sl * h.units for h in holdings))
        portfolio_risk = current_value - stoploss_value
        capital_risk = entry_value - stoploss_value

        # current_invested = float(sum(a.execution_price or a.prev_close * a.units for a in holdings if a.type == 'buy'))

        remaining_cash = total_capital - entry_value
        portfolio_value = current_value + remaining_cash

        total_gain = portfolio_value - total_invested_captial
        unrealized_gain = current_value - entry_value

        realized_gain = total_capital - total_invested_captial

        absolute_return_pct = (
            (total_gain / total_invested_captial) * 100
            if total_invested_captial else 0
        )

        summary['portfolio_value'] = round(portfolio_value, 2)
        summary['gain'] = round(total_gain, 2)
        summary['gain_percentage'] = round(absolute_return_pct, 2)
        summary['invested_value'] = round(entry_value, 2)
        summary['unrealized_gain'] = round(unrealized_gain, 2)
        summary['realized_gain'] = round(realized_gain, 2)
        summary['remaining_capital'] = round(remaining_cash, 2)
        summary['xirr'] = self._calculate_xirr(portfolio_value)
        summary['portfolio_risk'] = round(portfolio_risk, 2)
        summary['capital_risk'] = round(capital_risk, 2)

        return summary

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
                    
                    if take >= available:
                        buys[symbol].pop(0)
                    else:
                        buy.units -= take
                else:
                    remaining = sell_units - matched_units
                    matched_units += remaining
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

    def update_holding(self, symbol: str, action_date: date, mid_week: bool = False, holding = None) -> Dict:
        """
        Update an existing holding with current prices.

        Uses shared calculate_effective_stop for consistency with backtesting.
        Uses weekly low price for stop-loss trigger check.

        Parameters:
            symbol (str): Trading symbol
            action_date (date): Current action date

        Returns:
            Dict: Updated holding data with new price/stop-loss
        """
        config = self.config_repo.get_config(
            'momentum_config'
        )
        if not holding:
            holding = self.inv_repo.get_holdings_by_symbol(symbol)
        data_date = get_prev_friday(action_date)
        raw_atr = self.indicators_repo.get_indicator_by_tradingsymbol('atrr_14', symbol, data_date)

        md_obj = self.marketdata_repo.get_marketdata_by_trading_symbol(symbol, data_date)
        if md_obj:
            current_price = md_obj.close
        else:
            logger.warning(f"Market data missing for {symbol} on {data_date}, using last known price")
            current_price = holding.current_price

        if not mid_week:
            atr = round(raw_atr, 2) if raw_atr is not None else 0.0
            stoploss = calculate_effective_stop(
                current_price=float(current_price),
                current_atr=atr,
                stop_multiplier=config.sl_multiplier,
                previous_stop=(
                    float(holding.current_sl)
                    if holding.current_sl
                    else float(holding.entry_sl)
                )
            )
            rank_data = self.ranking_repo.get_rankings_by_date_and_symbol(data_date, symbol)
            score = round(rank_data.composite_score, 2) if rank_data else 0
        else:
            stoploss = holding.current_sl
            score = holding.score
            atr = holding.atr

        holding_data = {
            'symbol': symbol,
            'date': action_date,
            'entry_date': holding.entry_date,
            'entry_price': holding.entry_price,
            'avg_price': getattr(holding, 'avg_price', None) or holding.entry_price,
            'units': holding.units,
            'atr': atr,
            'score': score,
            'entry_sl': holding.entry_sl,
            'current_price': current_price,
            'current_sl': stoploss
        }
        return holding_data

    def get_summary(self, week_holdings, sold, override_starting_capital=None, action_date=None, bought=None):
        """
        Build weekly portfolio summary from holdings data.

        Parameters:
            week_holdings (List[Dict]): Current week's holdings
            sold (float): Total value of sold positions
            override_starting_capital (float): Optional override to prevent double-counting
                                            when updating same-day summary

        Returns:
            Dict: Summary with capital, risk, and P&L metrics
        """
        if override_starting_capital is not None:
            total_cap = float(override_starting_capital)
        else:
            total_cap = float(self.inv_repo.get_total_capital(action_date, include_realized=True))

        if week_holdings:
            df = pd.DataFrame(week_holdings)
        else:
            df = pd.DataFrame(columns=[
                'entry_price', 'units', 'current_sl', 'current_price',
                'entry_date', 'date'
            ])

        for col in ['entry_price', 'units', 'current_sl', 'current_price']:
            if col in df.columns:
                df[col] = df[col].astype(float)
        
        new_capital_addition = 0
        prev_summary = self.inv_repo.get_summary()
        if not prev_summary:
            prev_remaining_capital = total_cap
        else:
            prev_remaining_capital = prev_summary.remaining_capital
            new_capital_addition = self.inv_repo.get_total_capital_by_date(prev_summary.date)

        if bought is None:
            bought_mask = df['entry_date'] == df['date']
            bought = float((df.loc[bought_mask, 'entry_price']* df.loc[bought_mask, 'units']).sum())
        starting_capital = float(prev_remaining_capital) + new_capital_addition

        capital_risk = float((df['units'] * (df['entry_price'] - df['current_sl'])).sum())
        holdings_value = float((df['units'] * df['current_price']).sum())
        remaining_capital = starting_capital - bought + sold
        portfolio_value = holdings_value + remaining_capital

        stop_value = float((df['units'] * df['current_sl']).sum())
        portfolio_risk = round(holdings_value - stop_value, 2)

        gain = round(portfolio_value - total_cap, 2)
        gain_pct = round(
            (gain) / total_cap * 100, 2
        ) if total_cap else 0.0

        summary = {
            'date': week_holdings[0]['date'] if week_holdings else action_date,
            'starting_capital': round(starting_capital, 2),
            'sold': round(sold, 2),
            'bought': round(bought, 2),
            'capital_risk': round(capital_risk, 2),
            'portfolio_value': round(portfolio_value, 2),
            'portfolio_risk': portfolio_risk,
            'gain': gain,
            'gain_percentage': gain_pct,
        }
        return summary

    def sync_prices(self) -> str:
        """
        Sync portfolio holdings with latest market prices.

        Returns:
            Confirmation message
        """
        holdings = self.inv_repo.get_holdings()
        if not holdings:
            return []
        
        for h in holdings:
            md = self.marketdata_repo.get_latest_marketdata(h.symbol)
            
            if not md:
                logger.warning(f"No market data found for {h.symbol}, skipping sync")
                continue
                
            current_price = float(md.close)
            h.current_price = current_price
            self.inv_repo.update_holding(h.symbol, h.date, {'current_price': current_price})
                    
        summary = self.inv_repo.get_summary()
        if summary:
            h_dicts = [h.to_dict() for h in holdings]
            
            new_summary = self.get_summary(
                h_dicts, 
                sold=float(summary.sold), 
                override_starting_capital=float(summary.starting_capital),
                action_date=summary.date,
                bought=float(summary.bought)
            )
            self.inv_repo.insert_summary(new_summary)
        return "Portfolio prices synced with latest market data"