"""
Investment Service
==================

Portfolio accounting, reporting, and price-sync layer.

Responsibilities
----------------
- **Portfolio summary** -- compute weekly/current portfolio value, unrealized PnL,
  XIRR, and risk metrics from first principles.
- **Trade journal** -- FIFO-match all approved BUY/SELL actions to produce
  completed trade records (entry/exit price, PnL, holding period).
- **Holdings refresh** -- update current price and recalculate ATR trailing
  stop per holding, individually or in bulk.
- **Capital events** -- record infusions and withdrawals so that total_capital
  and remaining_capital are always derived from actual cash movements.

Capital arithmetic (first principles)
--------------------------------------
All capital figures are computed from scratch each cycle::

    total_capital     = SUM(capital_events.amount)
    cost_basis        = SUM(avg_price * units)   # open positions
    remaining_capital = total_capital - cost_basis

This prevents drift: remaining_capital is never carried forward from a
stale summary column.

Depends on
----------
- InvestmentRepository  -- holdings, summary, capital events
- ActionsRepository     -- approved actions for trade journal
- MarketDataRepository  -- current/historical OHLCV
- IndicatorsRepository  -- ATR values for stop-loss refresh
- RankingRepository     -- composite scores for holdings display
- ConfigRepository      -- sl_multiplier for trailing stop calculation
- FIFOTradeTracker      -- shared FIFO matching (also used by backtesting)
"""

import pandas as pd

from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from config import setup_logger
from repositories import (
    ActionsRepository,
    ConfigRepository,
    IndicatorsRepository,
    InvestmentRepository,
    MarketDataRepository,
    RankingRepository,
)
from utils import FIFOTradeTracker, calculate_effective_stop, calculate_xirr, get_prev_friday

logger = setup_logger(name="InvestmentService")


class InvestmentService:
    """
    Portfolio accounting, reporting, and price-sync service.

    Accepts an optional SQLAlchemy ``session`` for backtest DB injection.
    When ``session`` is None the default Flask-SQLAlchemy session is used
    (production path).

    Parameters
    ----------
    session : Session, optional
        Injected SQLAlchemy session. Pass the backtest DB session when
        running simulations so reads/writes go to the isolated backtest
        database rather than production personal.db.
    strategy_id : str
        Strategy identifier used when querying rankings.
        Defaults to ``"strategy1"``.
    """

    def __init__(self, session: Optional[Session] = None, strategy_id: str = "strategy1"):
        self.inv_repo = InvestmentRepository(session)
        self.actions_repo = ActionsRepository(session)
        self.config_repo = ConfigRepository()
        self.strategy_id = strategy_id

        self.indicators_repo = IndicatorsRepository()
        self.marketdata_repo = MarketDataRepository()
        self.ranking_repo = RankingRepository()

    def ensure_capital_events_seeded(self, seed_date=None) -> None:
        """
        If capital_events table is empty, auto-seed
        with config.initial_capital at the earliest
        summary date for backward compatibility.
        """
        events = self.inv_repo.get_all_capital_events()
        if events:
            return

        config_data = self.config_repo.get_config("momentum_config")
        initial = float(config_data.initial_capital)

        # Use earliest summary date, or today
        summaries = self.inv_repo.get_all_summaries()
        if not seed_date:
            seed_date = summaries[0].date if summaries else datetime.now().date()

        self.inv_repo.insert_capital_event(
            {
                "date": seed_date,
                "amount": initial,
                "event_type": "initial",
                "note": "Auto-seeded from config",
            }
        )
        logger.info(f"Auto-seeded capital event: {initial} " f"on {seed_date}")



    def _calculate_xirr(self, portfolio_value, as_of_date=None) -> Optional[float]:
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
                cashflows.append((-float(ev.amount), ev.date))
            cashflows.append((portfolio_value, as_of_date or datetime.now().date()))

            xirr_val = calculate_xirr(cashflows)
            return round(xirr_val * 100, 2) if xirr_val else None
        except Exception:
            return None

    def get_portfolio_summary(self, working_date: Optional[date] = None) -> Optional[Dict]:
        """
        Build a rich portfolio summary for the given date (defaults to latest).

        Pulls the raw summary row from the DB then enriches it with metrics
        computed from first principles so the API caller gets a single
        self-consistent snapshot.

        Returns
        -------
        dict or None
            None if no summary exists yet (portfolio never initialized).

            Otherwise a dict with:

            ================== ========================================================
            portfolio_value    holdings market value + remaining cash
            gain               portfolio_value - total invested capital
            gain_percentage    gain / total_invested_capital * 100
            invested_value     SUM(avg_price * units) for open positions
            unrealized_gain    current_value - cost_basis
            realized_gain      total_capital - total_invested_capital
            remaining_capital  cash available for new buys
            xirr               IRR using all capital infusion events as cashflows
            portfolio_risk     SUM(units * (current_price - current_sl))
            capital_risk       SUM(units * (entry_price - current_sl))
            ================== ========================================================
        """
        summary_FROM_DB = self.inv_repo.get_summary(working_date)
        if not summary_FROM_DB:
            return None

        summary = summary_FROM_DB.to_dict()
        summary_date = summary["date"]

        self.ensure_capital_events_seeded()
        total_capital = self.inv_repo.get_total_capital(summary_date, include_realized=True)
        total_invested_captial = self.inv_repo.get_total_capital(
            summary_date, include_realized=False
        )

        holdings = self.inv_repo.get_holdings(summary_date)
        entry_value = float(
            sum((getattr(h, "avg_price", None) or h.entry_price) * h.units for h in holdings)
        )
        current_value = float(
            sum(h.current_price * h.units for h in holdings)
        )
        stoploss_value = float(sum(h.current_sl * h.units for h in holdings))
        portfolio_risk = current_value - stoploss_value
        capital_risk = entry_value - stoploss_value



        remaining_cash = total_capital - entry_value
        portfolio_value = current_value + remaining_cash

        total_gain = portfolio_value - total_invested_captial
        unrealized_gain = current_value - entry_value

        realized_gain = total_capital - total_invested_captial

        absolute_return_pct = (
            (total_gain / total_invested_captial) * 100 if total_invested_captial else 0
        )

        summary["portfolio_value"] = round(portfolio_value, 2)
        summary["gain"] = round(total_gain, 2)
        summary["gain_percentage"] = round(absolute_return_pct, 2)
        summary["invested_value"] = round(entry_value, 2)
        summary["unrealized_gain"] = round(unrealized_gain, 2)
        summary["realized_gain"] = round(realized_gain, 2)
        summary["remaining_capital"] = round(remaining_cash, 2)
        summary["xirr"] = self._calculate_xirr(portfolio_value, as_of_date=summary_date)
        summary["portfolio_risk"] = round(portfolio_risk, 2)
        summary["capital_risk"] = round(capital_risk, 2)

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

        Uses shared FIFOTradeTracker for consistent matching with backtesting.
        Matches each sell to earliest unmatched buy, calculates P&L, return %, holding period.

        Returns:
            List of trade dicts sorted by exit_date descending
        """
        all_actions = self.actions_repo.get_all_approved_actions()
        matched_trades, _ = FIFOTradeTracker.from_actions(
            all_actions, use_fallback_price=True
        )

        trades = [
            {
                "entry_date": str(mt.entry_date),
                "exit_date": str(mt.exit_date),
                "symbol": mt.symbol,
                "units": mt.units,
                "entry_price": mt.entry_price,
                "exit_price": mt.exit_price,
                "pnl": mt.pnl,
                "return_pct": mt.return_pct,
                "days_held": mt.days_held,
                "reason": mt.reason,
            }
            for mt in matched_trades
        ]

        trades.sort(key=lambda x: x["exit_date"], reverse=True)
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
        valid_types = ("initial", "infusion", "withdrawal")
        if event_type not in valid_types:
            raise ValueError(f"event_type must be one of {valid_types}")
        self.inv_repo.insert_capital_event(
            {
                "date": event_date,
                "amount": amount,
                "event_type": event_type,
                "note": note,
            }
        )
        return f"Capital event recorded: {event_type} " f"of {amount} on {event_date}"

    def get_capital_events(self) -> List[Dict]:
        """
        Get all capital events.

        Returns:
            List of capital event dicts
        """
        events = self.inv_repo.get_all_capital_events()
        return [e.to_dict() for e in events]

    def update_holding(
        self,
        symbol: str,
        action_date: date,
        mid_week: bool = False,
        holding=None,
        config_name: str = "momentum_config",
    ) -> Dict:
        """
        Update an existing holding with current prices.

        Uses shared calculate_effective_stop for consistency with backtesting.
        Uses weekly low price for stop-loss trigger check.

        Parameters:
            symbol (str): Trading symbol
            action_date (date): Current action date
            mid_week (bool): If True, carry forward existing SL/score without update
            holding: Optional pre-fetched holding object
            config_name (str): Config to use for sl_multiplier (pass active config name)

        Returns:
            Dict: Updated holding data with new price/stop-loss
        """
        # Bug 16: use the supplied config_name so the active backtest config's
        # sl_multiplier is applied, not always 'momentum_config'.
        config = self.config_repo.get_config(config_name)
        if not holding:
            holding = self.inv_repo.get_holdings_by_symbol(symbol)
        data_date = get_prev_friday(action_date)
        raw_atr = self.indicators_repo.get_indicator_by_tradingsymbol("atrr_14", symbol, data_date)

        md_obj = self.marketdata_repo.get_marketdata_by_trading_symbol(symbol, data_date)
        if md_obj:
            current_price = md_obj.close
        else:
            logger.warning(
                f"Market data missing for {symbol} on {data_date}, using last known price"
            )
            current_price = holding.current_price

        if not mid_week:
            atr = round(raw_atr, 2) if raw_atr is not None else 0.0
            stoploss = calculate_effective_stop(
                current_price=float(current_price),
                current_atr=atr,
                stop_multiplier=config.sl_multiplier,
                previous_stop=(
                    float(holding.current_sl) if holding.current_sl else float(holding.entry_sl)
                ),
            )
            rank_data = self.ranking_repo.get_rankings_by_date_and_symbol(
                data_date, symbol, strategy_id=self.strategy_id
            )
            score = round(rank_data.composite_score, 2) if rank_data else 0
        else:
            stoploss = holding.current_sl
            score = holding.score
            atr = holding.atr

        holding_data = {
            "symbol": symbol,
            "date": action_date,
            "entry_date": holding.entry_date,
            "entry_price": holding.entry_price,
            "avg_price": (
                getattr(holding, "avg_price")
                if hasattr(holding, "avg_price") and getattr(holding, "avg_price") is not None
                else holding.entry_price
            ),
            "units": holding.units,
            "atr": atr,
            "score": score,
            "entry_sl": holding.entry_sl,
            "current_price": current_price,
            "current_sl": stoploss,
        }
        return holding_data

    def get_summary(
        self, week_holdings, sold, override_starting_capital=None, action_date=None, bought=None
    ):
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
        # Single call for all capital arithmetic (P8: eliminates duplicate call)
        total_cap_with_realized = float(
            self.inv_repo.get_total_capital(action_date, include_realized=True)
        )
        if override_starting_capital is not None:
            total_cap = float(override_starting_capital)
        else:
            total_cap = float(self.inv_repo.get_total_capital(action_date, include_realized=False))

        if week_holdings:
            df = pd.DataFrame(week_holdings)
        else:
            df = pd.DataFrame(
                columns=[
                    "entry_price",
                    "units",
                    "current_sl",
                    "current_price",
                    "entry_date",
                    "date",
                ]
            )

        for col in ["entry_price", "units", "current_sl", "current_price"]:
            if col in df.columns:
                df[col] = df[col].astype(float)

        if bought is None:
            bought_mask = df["entry_date"] == df["date"]
            bought = float(
                (df.loc[bought_mask, "entry_price"] * df.loc[bought_mask, "units"]).sum()
            )


        # remaining_capital = total_cap_with_realized - cost_basis (first principles, single source of truth)
        if "avg_price" in df.columns:
            cost_basis = float(
                (df["avg_price"].fillna(df["entry_price"]).astype(float) * df["units"]).sum()
            )
        else:
            cost_basis = float((df["entry_price"] * df["units"]).sum())
        remaining_capital = round(total_cap_with_realized - cost_basis, 2)


        # starting_capital = previous remaining + any new capital events since last summary
        prev_summary = self.inv_repo.get_summary()
        if not prev_summary:
            starting_capital = total_cap
        else:
            prev_remaining = float(prev_summary.remaining_capital or 0)
            new_capital_addition = self.inv_repo.get_total_capital_by_date(action_date)
            starting_capital = prev_remaining + new_capital_addition

        capital_risk = float((df["units"] * (df["entry_price"] - df["current_sl"])).sum())
        holdings_value = float((df["units"] * df["current_price"]).sum())
        portfolio_value = holdings_value + remaining_capital

        stop_value = float((df["units"] * df["current_sl"]).sum())
        portfolio_risk = round(holdings_value - stop_value, 2)

        gain = round(portfolio_value - total_cap, 2)
        gain_pct = round(gain / total_cap * 100, 2) if total_cap else 0.0

        summary = {
            "date": week_holdings[0]["date"] if week_holdings else action_date,
            "starting_capital": round(starting_capital, 2),
            "sold": round(sold, 2),
            "bought": round(bought, 2),
            "capital_risk": round(capital_risk, 2),
            "portfolio_value": round(portfolio_value, 2),
            "portfolio_risk": portfolio_risk,
            "gain": gain,
            "gain_percentage": gain_pct,
            "remaining_capital": remaining_capital,
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
            return "No holdings to sync"

        for h in holdings:
            md = self.marketdata_repo.get_latest_marketdata(h.symbol)

            if not md:
                logger.warning(f"No market data found for {h.symbol}, skipping sync")
                continue

            current_price = float(md.close)
            h.current_price = current_price
            self.inv_repo.update_holding(h.symbol, h.date, {"current_price": current_price})

        summary = self.inv_repo.get_summary()
        if summary:
            h_dicts = [h.to_dict() for h in holdings]

            new_summary = self.get_summary(
                h_dicts,
                sold=float(summary.sold),
                override_starting_capital=float(summary.starting_capital),
                action_date=summary.date,
                bought=float(summary.bought),
            )
            self.inv_repo.insert_summary(new_summary)
        return "Portfolio prices synced with latest market data"
