"""
Action Processor

Converts approved actions into portfolio holdings and investment summary.

Responsibility boundary: reads approved actions, writes ONLY to the
investments / investment_summary / capital_events tables.
"""

from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from config import setup_logger
from models.action_models import HoldingResult
from repositories import ActionsRepository, ConfigRepository, InvestmentRepository, RankingRepository
from services.investment_service import InvestmentService
from services.trading_service import HoldingSnapshot
from utils import get_prev_friday

logger = setup_logger(name="ActionProcessor")


class ActionProcessor:
    """
    Process approved actions and update portfolio holdings.

    Three-phase pipeline:
        1. Sell  — realise PnL, record capital event, remove holding
        2. Buy   — create new holding or merge pyramid add
        3. Hold  — update SL and current price for unchanged positions
    """

    def __init__(
        self,
        config_name: str = None,
        session: Optional[Session] = None,
        config_info=None,
        strategy_id: str = "strategy1",
    ):
        config_repo = ConfigRepository()
        self.config = config_info or config_repo.get_config(config_name)
        self.strategy_id = strategy_id
        self.actions_repo = ActionsRepository(session)
        self.investment_repo = InvestmentRepository(session)
        self.investment_service = InvestmentService(session, strategy_id=strategy_id)
        self.ranking_repo = RankingRepository()

    # ------------------------------------------------------------------ #
    #  Phase 1 — Process sell actions                                      #
    # ------------------------------------------------------------------ #

    def _process_sell_actions(
        self, sell_symbols, buy_symbols, holdings_map, action_date
    ) -> tuple:
        """
        Process approved sell actions: compute PnL, record capital events,
        remove holdings.

        Returns:
            (sold_total, sold_symbols_set, updated_buy_symbols)
        """
        sold = 0
        sold_symbol_set = set()

        for symbol, action in sell_symbols.items():
            logger.info(
                f"SELL {symbol}: units={action.units}u@{action.execution_price}"
                f"={action.units * action.execution_price:.2f}"
            )
            if (symbol not in holdings_map) and symbol in buy_symbols:
                logger.info(f"Intraday sell of {symbol}")
                buy_action = buy_symbols.pop(symbol)
                holding = HoldingSnapshot(
                    symbol=symbol,
                    units=buy_action.units,
                    entry_price=float(buy_action.execution_price),
                    avg_price=float(buy_action.execution_price),
                    stop_loss=0,
                    score=0,
                )
            else:
                h = holdings_map.get(symbol)
                holding = HoldingSnapshot.from_holding(h) if h else None

            if not holding:
                logger.warning(
                    f"_process_sell_actions: no holding found for {symbol} on {action_date} — skipping"
                )
                continue

            pnl = (float(action.execution_price) - holding.avg_price) * action.units
            self.investment_repo.insert_capital_event({
                "date": action_date,
                "event_type": "realized_gain",
                "amount": pnl,
                "note": f"Sold {symbol}: {action.units}u @ {action.execution_price}",
            })
            self.investment_repo.delete_holding(symbol, action_date)
            sold_symbol_set.add(symbol)
            sold += float(action.execution_price) * action.units

        return sold, sold_symbol_set, buy_symbols

    # ------------------------------------------------------------------ #
    #  Phase 2 — Process buy actions                                       #
    # ------------------------------------------------------------------ #

    def _process_buy_actions(
        self, buy_symbols, sell_symbols, holdings_map, action_date, data_date
    ) -> tuple:
        """
        Process approved buy actions: create new holdings or merge pyramids.

        Returns:
            (week_holdings, bought_value, pyramid_symbols)
        """
        week_holdings: List[HoldingResult] = []
        bought_value = 0
        pyramid_symbols = set()

        for symbol, action in buy_symbols.items():
            if symbol in sell_symbols:
                continue

            # Pyramid add: merge into existing holding
            if action.reason == "pyramid_add" and symbol in holdings_map:
                old = holdings_map[symbol]
                old_avg = float(getattr(old, "avg_price", None) or old.entry_price)
                old_value = old_avg * old.units
                new_value = float(action.execution_price) * action.units
                bought_value += new_value
                total_units = old.units + action.units
                avg_price = round((old_value + new_value) / total_units, 2)

                rank_data = self.ranking_repo.get_rankings_by_date_and_symbol(
                    data_date, symbol, strategy_id=self.strategy_id
                )
                score = round(rank_data.composite_score, 2) if rank_data else 0

                old_sl = float(old.current_sl)
                old_entry_sl = float(getattr(old, "entry_sl", old_sl))

                logger.info(
                    f"PYRAMID_ADD {symbol}: {old.units}u@{old_avg:.2f} + {action.units}u@{action.execution_price} "
                    f"= {total_units}u avg_price={avg_price:.2f} (keeping SL={old_sl:.2f})"
                )

                week_holdings.append(HoldingResult(
                    symbol=symbol,
                    date=action_date,
                    entry_date=old.entry_date,
                    entry_price=old.entry_price,
                    avg_price=avg_price,
                    units=total_units,
                    atr=getattr(old, "atr", action.atr),
                    score=score,
                    entry_sl=old_entry_sl,
                    current_price=action.execution_price,
                    current_sl=old_sl,
                ))
                pyramid_symbols.add(symbol)
                continue

            # Normal buy — compute initial_sl from first principles
            atr_val = float(action.atr) if action.atr else 0.0
            risk_per_unit = round(atr_val * self.config.sl_multiplier, 2)
            if risk_per_unit <= 0 and atr_val > 0:
                risk_per_unit = round(atr_val, 2)
            initial_sl = round(float(action.execution_price) - risk_per_unit, 2)
            logger.info(
                f"BUY {symbol}: computed initial_sl={initial_sl:.2f} "
                f"(exec={action.execution_price} - risk={risk_per_unit:.2f}, "
                f"atr={atr_val}, sl_mult={self.config.sl_multiplier})"
            )

            rank_data = self.ranking_repo.get_rankings_by_date_and_symbol(
                data_date, symbol, strategy_id=self.strategy_id
            )
            score = round(rank_data.composite_score, 2) if rank_data else 0
            buy_value = float(action.execution_price) * action.units
            bought_value += buy_value
            logger.info(
                f"BUY {symbol}: units={action.units}u@{action.execution_price}={buy_value:.2f}"
            )

            week_holdings.append(HoldingResult(
                symbol=symbol,
                date=action_date,
                entry_date=action_date,
                entry_price=action.execution_price,
                avg_price=float(action.execution_price),
                units=action.units,
                atr=action.atr,
                score=score,
                entry_sl=initial_sl,
                current_price=action.execution_price,
                current_sl=initial_sl,
            ))

        return week_holdings, bought_value, pyramid_symbols

    # ------------------------------------------------------------------ #
    #  Phase 3 — Update unchanged positions                                #
    # ------------------------------------------------------------------ #

    def _update_held_positions(
        self, held_symbols, action_date, midweek, holdings_map
    ) -> List[Dict]:
        """Update unchanged held positions with current prices and trailing SL.

        Returns plain dicts (from InvestmentService.update_holding) rather than
        HoldingResult dataclasses because update_holding already serialises the
        ORM holding into a dict — converting twice would be wasteful.
        """
        updated = []
        config_name = self.config.name if hasattr(self.config, "name") else "momentum_config"
        for symbol in held_symbols:
            updated.append(
                self.investment_service.update_holding(
                    symbol,
                    action_date,
                    midweek,
                    holdings_map[symbol],
                    config_name=config_name,
                )
            )
        return updated

    # ------------------------------------------------------------------ #
    #  Main orchestrator                                                   #
    # ------------------------------------------------------------------ #

    def process_actions(self, action_date: date, midweek: bool = False) -> Optional[List[Dict]]:
        """
        Process approved actions and update holdings.

        Orchestrates sell processing, buy processing, and held position
        updates, then atomically upserts the resulting holdings and summary.

        Parameters:
            action_date: Date of actions to process
            midweek: Whether this is a mid-week processing run

        Returns:
            List of updated holding dicts, or None if aborted due to stale data
        """
        holdings = self.investment_repo.get_holdings()
        actions_list = self.actions_repo.get_actions(action_date)
        holdings_date = holdings[0].date if holdings else date(2000, 1, 1)

        if holdings_date > action_date:
            logger.warning(
                f"Holdings date {holdings_date} is ahead of action date {action_date} — aborting"
            )
            return None

        self.investment_repo.delete_capital_events(date=action_date, event_type="realized_gain")

        buy_symbols = {}
        sell_symbols = {}
        for item in actions_list:
            if item.status == "Approved":
                if item.type == "sell":
                    sell_symbols[item.symbol] = item
                elif item.type == "buy":
                    buy_symbols[item.symbol] = item

        holdings_map = {h.symbol: h for h in holdings}
        held_symbols = {h.symbol for h in holdings}

        # Phase 1: Process sells
        sold, sold_symbol_set, buy_symbols = self._process_sell_actions(
            sell_symbols, buy_symbols, holdings_map, action_date
        )
        held_symbols -= sold_symbol_set

        # Phase 2: Process buys — returns List[HoldingResult]
        data_date = get_prev_friday(action_date)
        week_holdings, bought_value, pyramid_symbols = self._process_buy_actions(
            buy_symbols, sell_symbols, holdings_map, action_date, data_date
        )
        held_symbols -= pyramid_symbols

        # Phase 3: Update unchanged held positions — returns plain dicts
        week_holdings.extend(
            self._update_held_positions(held_symbols, action_date, midweek, holdings_map)
        )

        # Normalise to plain dicts at the boundary so callers (upsert / summary)
        # work unchanged regardless of whether a holding came from Phase 2 or 3.
        week_holdings_dicts = [
            h.to_dict() if isinstance(h, HoldingResult) else h for h in week_holdings
        ]

        summary = self.investment_service.get_summary(
            week_holdings_dicts, sold, bought=bought_value, action_date=action_date
        )

        # Atomic upsert
        self.investment_repo.upsert_holdings(week_holdings_dicts, action_date)
        self.investment_repo.upsert_summary(summary)
        return week_holdings_dicts
