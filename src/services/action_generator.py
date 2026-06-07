"""
Action Generator

Converts TradingDecision objects and raw market data into typed action results
(BuyActionResult / SellActionResult) and persists them.

Responsibility boundary: reads from DB, writes ONLY to the actions table.
No holdings mutations happen here.
"""

from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from config import PyramidConfig, setup_logger
from models.action_models import BuyActionResult, SellActionResult
from repositories import (
    ActionsRepository,
    ConfigRepository,
    IndicatorsRepository,
    InvestmentRepository,
    MarketDataRepository,
    RankingRepository,
)
from services.trading_service import CandidateInfo, HoldingSnapshot, TradingEngine
from utils import get_next_business_day, get_prev_friday
from utils.sizing_utils import calculate_position_size

logger = setup_logger(name="ActionGenerator")


class ActionGenerator:
    """
    Generate pending BUY / SELL / SWAP actions for a given date.

    All public methods return typed dataclasses (BuyActionResult /
    SellActionResult) or lists of them. The only DB write is the final
    bulk_insert via _persist_actions().
    """

    def __init__(
        self,
        config_name: str = None,
        session: Optional[Session] = None,
        config_info=None,
    ):
        config_repo = ConfigRepository()
        self.config = config_info or config_repo.get_config(config_name)
        self.ranking_repo = RankingRepository()
        self.indicators_repo = IndicatorsRepository()
        self.marketdata_repo = MarketDataRepository()
        self.actions_repo = ActionsRepository(session)
        self.investment_repo = InvestmentRepository(session)

    # ------------------------------------------------------------------ #
    #  Primitive action builders                                           #
    # ------------------------------------------------------------------ #

    def buy_action(
        self,
        symbol: str,
        action_date: date,
        prev_close: float,
        reason: str,
        total_capital: float,
        remaining_capital: float = None,
        units: int = 0,
        price: float = 0,
        **kwargs,
    ) -> tuple[BuyActionResult, float]:
        """
        Build a BuyActionResult with ATR-based position sizing.

        Parameters:
            symbol: Trading symbol
            action_date: Date the action is for
            prev_close: Friday close price used for sizing
            reason: Narrative reason (e.g. 'top N buys')
            total_capital: Total portfolio value — drives risk % sizing
            remaining_capital: Available cash — affordability check
            units: Explicit override; 0 = auto-calculate
            price: Required when units > 0 (override fill price)

        Returns:
            (BuyActionResult, updated_remaining_capital)
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if not reason:
            reason = "Unknown reason"

        data_date = get_prev_friday(action_date)
        atr = self.indicators_repo.get_indicator_by_tradingsymbol("atrr_14", symbol, data_date)
        if atr is None:
            logger.warning(f"ATR not available for {symbol} on {data_date} — skipping buy.")
            return BuyActionResult(
                action_date=action_date,
                symbol=symbol,
                reason=reason,
                prev_close=prev_close,
                units=0,
                capital=0.0,
            ), remaining_capital

        atr = round(atr, 2)

        if units > 0:
            capital_needed = units * float(price)
            risk_per_unit = round(atr * self.config.sl_multiplier, 2)
        else:
            sizing = calculate_position_size(
                atr=atr,
                current_price=float(prev_close),
                total_capital=total_capital,
                remaining_capital=remaining_capital,
                config=self.config,
                existing_position_value=kwargs.get("existing_position_value", 0.0),
            )
            units = sizing["shares"]
            capital_needed = sizing["position_value"]
            risk_per_unit = sizing["stop_distance"]

        hard_sl_pct = getattr(self.config, "hard_sl_percent", 0.03)
        stop_loss = round(float(prev_close) - risk_per_unit, 2)
        hard_sl_price = round(stop_loss * (1 - hard_sl_pct), 2)

        result = BuyActionResult(
            action_date=action_date,
            symbol=symbol,
            reason=reason,
            prev_close=prev_close,
            units=units,
            capital=capital_needed,
            risk=risk_per_unit,
            atr=atr,
            stop_loss=stop_loss,
            hard_sl_price=hard_sl_price,
        )
        if remaining_capital is not None:
            remaining_capital -= capital_needed
        return result, remaining_capital

    def sell_action(
        self,
        symbol: str,
        action_date: date,
        prev_close: float,
        units: int,
        reason: str,
        price: float = 0,
        remaining_capital: float = 0,
        entry_price: float = 0,
    ) -> tuple[SellActionResult, float, float]:
        """
        Build a SellActionResult.

        Returns:
            (SellActionResult, updated_remaining_capital, realized_gain)
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if units <= 0:
            raise ValueError(f"Units must be positive, got {units}")
        if not reason:
            reason = "Unknown reason"

        price = price if price else prev_close
        capital_released = units * price

        result = SellActionResult(
            action_date=action_date,
            symbol=symbol,
            reason=reason,
            units=units,
            prev_close=prev_close,
            capital=capital_released,
        )
        remaining_capital += capital_released
        realized_gain = (float(price) - entry_price) * units
        return result, remaining_capital, realized_gain

    # ------------------------------------------------------------------ #
    #  Mid-week daily stoploss check                                       #
    # ------------------------------------------------------------------ #

    def check_daily_stoploss(self, day: date, mid_week_buy: bool = False) -> List[dict]:
        """
        Close-based SL check for a single day (live mid-week use).

        For each current holding, if today's close < current_sl, generate a
        Pending SELL action (to be executed at next day's open).
        Optionally advance stale pending BUY actions to fill any new vacancies.

        Parameters:
            day: The date to check (must have market data)
            mid_week_buy: If True, advance pending buys when vacancies open

        Returns:
            List of generated sell action dicts (may be empty)
        """
        md_prices = self.marketdata_repo.get_prices_for_all_stocks(
            {"start_date": day, "end_date": day}
        )
        if len(md_prices) < 500:
            logger.info(f"check_daily_stoploss: {day} appears to be a market holiday — skipping")
            return []

        current_holdings = self.investment_repo.get_holdings()
        if not current_holdings:
            logger.info(f"check_daily_stoploss: no holdings on {day}")
            return []

        holding_map = {h.symbol: h for h in current_holdings}
        sold_count = 0
        sell_actions = []

        for h in current_holdings:
            md = self.marketdata_repo.get_marketdata_by_trading_symbol(h.symbol, day)
            if md is None or md.close is None:
                logger.warning(
                    f"check_daily_stoploss: no market data for {h.symbol} on {day} — skipping"
                )
                continue

            current_sl = float(h.current_sl)
            daily_close = float(md.close)

            if daily_close < current_sl:
                next_day = get_next_business_day(day)
                logger.info(
                    f"CLOSE-BASED SL: {h.symbol} close {daily_close:.2f} < SL {current_sl:.2f} on {day} "
                    f"→ generating SELL for next open ({next_day})"
                )
                # Note: daily SL sell is a raw dict so we can set status=Pending explicitly
                sell_action = {
                    "action_date": next_day,
                    "type": "sell",
                    "reason": f"close-based stoploss on {day} (close={daily_close:.2f} < SL={current_sl:.2f})",
                    "symbol": h.symbol,
                    "units": h.units,
                    "prev_close": daily_close,
                    "capital": float(h.units) * daily_close,
                    "status": "Pending",
                }
                self.actions_repo.insert_action(sell_action)
                sell_actions.append(sell_action)
                del holding_map[h.symbol]
                sold_count += 1

        if mid_week_buy and sold_count:
            vacancies = self.config.max_positions - len(holding_map)
            if vacancies > 0:
                next_day = get_next_business_day(day)
                pending_buys = self.actions_repo.get_pending_buy_actions()
                for pending in pending_buys or []:
                    md_pb = self.marketdata_repo.get_marketdata_by_trading_symbol(
                        pending.symbol, day
                    )
                    if md_pb is None:
                        continue
                    close_price = float(md_pb.close)
                    signal_price = float(pending.prev_close)
                    if signal_price > 0 and close_price > signal_price * 1.05:
                        logger.info(
                            f"STALE BUY SKIP: {pending.symbol} close {close_price:.2f} > "
                            f"signal {signal_price:.2f} × 1.05 on {day}"
                        )
                        continue
                    self.actions_repo.update_action(
                        {"action_id": pending.action_id, "action_date": next_day}
                    )
                    logger.info(
                        f"MID-WEEK BUY: advanced {pending.symbol} buy to {next_day} "
                        f"(vacancy opens after close-SL on {day})"
                    )

        if sell_actions:
            logger.info(
                f"check_daily_stoploss: {len(sell_actions)} close-based SL sell(s) generated for {day}"
            )
        return sell_actions

    # ------------------------------------------------------------------ #
    #  Market context loader                                               #
    # ------------------------------------------------------------------ #

    def _load_market_context(
        self,
        action_date: date,
        current_holdings,
        top_n,
        enable_pyramiding: bool,
    ) -> tuple:
        """
        Load HoldingSnapshot list, entry prices, current prices, and EMA50 values.

        Returns:
            (holdings_snap, holdings_entry_prices, prices, ema_50_values)
        """
        data_date = get_prev_friday(action_date)
        holdings_snap = []
        holdings_entry_prices = {}
        prices = {}
        ema_50_values = {}

        candidate_symbols = {item.tradingsymbol for item in top_n}

        for h in current_holdings:
            holdings_entry_prices[h.symbol] = float(h.entry_price)
            md_h = self.marketdata_repo.get_marketdata_by_trading_symbol(h.symbol, data_date)
            if md_h:
                prices[h.symbol] = float(md_h.close)
            else:
                prices[h.symbol] = float(h.current_price)

            holdings_snap.append(HoldingSnapshot.from_holding(h))

            if enable_pyramiding:
                ema_50 = self.indicators_repo.get_indicator_by_tradingsymbol(
                    "ema_50", h.symbol, data_date
                )
                ema_50_values[h.symbol] = float(ema_50) if ema_50 else 0.0

        for item in top_n:
            if item.tradingsymbol not in prices:
                md_c = self.marketdata_repo.get_marketdata_by_trading_symbol(
                    item.tradingsymbol, data_date
                )
                if md_c:
                    prices[item.tradingsymbol] = float(md_c.close)

        return holdings_snap, holdings_entry_prices, prices, ema_50_values

    # ------------------------------------------------------------------ #
    #  Execution phases (sell → pyramid → buy)                             #
    # ------------------------------------------------------------------ #

    def _execute_sells(
        self, decisions, action_date, data_date, holdings_entry_prices, remaining_capital, sizing_base
    ) -> tuple:
        """
        Phase 1: Process all SELL and SWAP sell-legs.

        Returns:
            (sell_actions, swap_buy_queue, remaining_capital, sizing_base)
        """
        sell_actions = []
        swap_buy_queue = []

        for d in decisions:
            if d.action_type not in ("SELL", "SWAP"):
                continue

            md = self.marketdata_repo.get_marketdata_by_trading_symbol(d.symbol, data_date)
            if md is None:
                logger.warning(
                    f"generate_actions: no market data for {d.symbol} on {data_date}, skipping SELL"
                )
                continue

            action, remaining_capital, realized_gain = self.sell_action(
                d.symbol,
                action_date,
                md.close,
                d.units if d.action_type == "SELL" else d.swap_sell_units,
                d.reason,
                remaining_capital=remaining_capital,
                entry_price=holdings_entry_prices.get(d.symbol, 0),
            )
            sell_actions.append(action)
            sizing_base += realized_gain

            if d.action_type == "SWAP":
                swap_buy_queue.append((d.swap_for, d.reason))

        logger.info(
            f"generate_actions Phase 1 complete: remaining_capital=₹{remaining_capital:,.0f} "
            f"after {len(sell_actions)} sell(s)"
        )
        return sell_actions, swap_buy_queue, remaining_capital, sizing_base

    def _execute_pyramid_adds(
        self, decisions, action_date, data_date, sizing_base, remaining_capital
    ) -> tuple:
        """
        Phase 2: Process PYRAMID_ADD decisions.

        Returns:
            (pyramid_actions, remaining_capital)
        """
        pyramid_actions = []
        for d in decisions:
            if d.action_type != "PYRAMID_ADD":
                continue
            md = self.marketdata_repo.get_marketdata_by_trading_symbol(d.symbol, data_date)
            if md is None:
                logger.warning(
                    f"generate_actions: no market data for {d.symbol} on {data_date}, skipping PYRAMID_ADD"
                )
                continue
            pyramid_cfg = PyramidConfig()
            existing_holding = self.investment_repo.get_holdings_by_symbol(d.symbol)
            existing_value = (
                float(existing_holding.avg_price or existing_holding.entry_price)
                * existing_holding.units
                if existing_holding
                else 0.0
            )
            action, remaining_capital = self.buy_action(
                d.symbol,
                action_date,
                md.close,
                "pyramid_add",
                total_capital=sizing_base * pyramid_cfg.pyramid_fraction,
                remaining_capital=remaining_capital,
                existing_position_value=existing_value,
            )
            pyramid_actions.append(action)
            logger.info(
                f"PYRAMID_ADD {d.symbol}: adding {pyramid_cfg.pyramid_fraction:.0%} position, "
                f"existing_value={existing_value:.0f}"
            )
        return pyramid_actions, remaining_capital

    def _execute_buys(
        self,
        decisions,
        action_date,
        data_date,
        top_n,
        swap_buy_queue,
        current_holdings,
        sell_actions,
        sizing_base,
        remaining_capital,
    ) -> tuple:
        """
        Phase 3: Process all BUY decisions, swap buy legs, and backfill.

        Returns:
            (buy_actions, remaining_capital)
        """
        buy_decision_symbols = {d.symbol for d in decisions if d.action_type == "BUY"}
        swap_buy_map = {sym: reason for sym, reason in swap_buy_queue}

        already_bought: set = set()
        sold_this_week = {a.symbol for a in sell_actions}
        held_after = {h.symbol for h in current_holdings if h.symbol not in sold_this_week}
        open_slots = self.config.max_positions - len(held_after)

        logger.info(
            f"generate_actions Phase 3: {open_slots} open slot(s), "
            f"remaining_capital=₹{remaining_capital:,.0f}"
        )

        buy_actions = []

        for item in top_n:
            sym = item.tradingsymbol
            if sym in already_bought or sym in held_after:
                continue

            is_buy_decision = sym in buy_decision_symbols
            is_swap_buy = sym in swap_buy_map

            if not is_buy_decision and not is_swap_buy:
                continue
            if open_slots <= 0 and not is_swap_buy:
                continue

            md = self.marketdata_repo.get_marketdata_by_trading_symbol(sym, data_date)
            if md is None:
                logger.warning(
                    f"generate_actions: no market data for {sym} on {data_date}, skipping BUY"
                )
                continue

            reason = swap_buy_map.get(sym, "top N buys")
            action, remaining_capital = self.buy_action(
                sym, action_date, md.close, reason,
                total_capital=sizing_base, remaining_capital=remaining_capital,
            )
            buy_actions.append(action)
            already_bought.add(sym)

            if action.units == 0:
                logger.info(
                    f"generate_actions: BUY {sym} is capital-constrained — queued as pending vacancy"
                )
            else:
                held_after.add(sym)
                if is_buy_decision:
                    open_slots -= 1

        # Handle swap buy legs whose target was NOT in top_n
        for sym, reason in swap_buy_queue:
            if sym in already_bought:
                continue
            md = self.marketdata_repo.get_marketdata_by_trading_symbol(sym, data_date)
            if md is None:
                logger.warning(
                    f"generate_actions: no market data for swap-buy {sym} on {data_date}, skipping"
                )
                continue
            action, remaining_capital = self.buy_action(
                sym, action_date, md.close, reason,
                total_capital=sizing_base, remaining_capital=remaining_capital,
            )
            buy_actions.append(action)
            already_bought.add(sym)
            if action.units > 0:
                held_after.add(sym)

        # Backfill remaining open slots
        if open_slots > 0 and remaining_capital > 0:
            logger.info(
                f"generate_actions: {open_slots} open slot(s) remain — "
                f"backfilling from top-{self.config.max_positions} ranked list"
            )
            for item in top_n:
                if open_slots <= 0 or remaining_capital <= 0:
                    break
                sym = item.tradingsymbol
                if sym in already_bought or sym in held_after:
                    continue
                md = self.marketdata_repo.get_marketdata_by_trading_symbol(sym, data_date)
                if md is None:
                    continue
                action, remaining_capital = self.buy_action(
                    sym, action_date, md.close, reason="vacancy backfill",
                    total_capital=sizing_base, remaining_capital=remaining_capital,
                )
                if action.units > 0:
                    buy_actions.append(action)
                    already_bought.add(sym)
                    held_after.add(sym)
                    open_slots -= 1
                    logger.info(
                        f"BACKFILL BUY {sym}: {action.units} units @ "
                        f"₹{md.close:.2f} = ₹{action.capital:,.0f}"
                    )

        return buy_actions, remaining_capital

    def _persist_actions(self, new_actions: list) -> None:
        """De-duplicate and bulk insert generated actions."""
        new_actions = [a for a in new_actions if a is not None]
        if new_actions:
            action_date = new_actions[0].action_date
            new_symbols = {a.symbol for a in new_actions}
            self.actions_repo.delete_actions_by_symbols(action_date, new_symbols)
            self.actions_repo.bulk_insert_actions(new_actions)

            pending_buys = [a for a in new_actions if isinstance(a, BuyActionResult) and a.units == 0]
            if pending_buys:
                logger.info(
                    f"Saved {len(pending_buys)} capital-constrained buys as Pending: "
                    f"{[a.symbol for a in pending_buys]}"
                )

    # ------------------------------------------------------------------ #
    #  Main orchestrator                                                   #
    # ------------------------------------------------------------------ #

    def generate_actions(
        self,
        action_date: date,
        skip_pending_check: bool = False,
        enable_pyramiding: bool = False,
        check_daily_sl: bool = False,
        mid_week_buy: bool = False,
    ) -> list:
        """
        Generate trading actions (BUY/SELL/SWAP) for a given date.

        Delegates core decision logic to TradingEngine.generate_decisions(),
        then executes sells → pyramids → buys in order.

        Parameters:
            action_date: Date to generate actions for
            skip_pending_check: Skip pending actions guard (for backtesting)
            enable_pyramiding: Allow pyramid adds on existing positions
            check_daily_sl: Run close-based SL check only (mid-week)
            mid_week_buy: Advance pending buys when SL vacancies open

        Returns:
            List of BuyActionResult / SellActionResult instances (may be empty)

        Raises:
            ValueError: If pending actions from another date exist (not skipped)
        """
        if not skip_pending_check:
            pending_actions = self.actions_repo.check_other_pending_actions(action_date)
            if pending_actions:
                raise ValueError(
                    "Actions pending from another date — approve or reject them before generating new actions."
                )

        if check_daily_sl:
            return self.check_daily_stoploss(action_date, mid_week_buy=mid_week_buy)

        data_date = get_prev_friday(action_date)
        top_n = self.ranking_repo.get_top_n_by_date(self.config.max_positions, data_date)
        candidates = [
            CandidateInfo(symbol=item.tradingsymbol, score=item.composite_score) for item in top_n
        ]

        current_holdings = self.investment_repo.get_holdings()
        total_capital = self.investment_repo.get_total_capital(action_date, include_realized=True)
        remaining_capital = self.investment_repo.get_remaining_capital(target_date=action_date)

        holdings_snap, holdings_entry_prices, prices, ema_50_values = self._load_market_context(
            action_date, current_holdings, top_n, enable_pyramiding
        )

        decisions = TradingEngine.generate_decisions(
            holdings=holdings_snap,
            candidates=candidates,
            prices=prices,
            max_positions=self.config.max_positions,
            swap_buffer=1 + self.config.buffer_percent,
            exit_threshold=self.config.exit_threshold,
            ema_50_values=ema_50_values if current_holdings else None,
            enable_pyramiding=enable_pyramiding,
        )

        sizing_base = total_capital
        if sizing_base <= 0:
            logger.warning(
                f"sizing_base is {sizing_base} — no capital events found before {action_date}. "
                f"Position sizes will be 0."
            )

        sell_actions, swap_buy_queue, remaining_capital, sizing_base = self._execute_sells(
            decisions, action_date, data_date, holdings_entry_prices, remaining_capital, sizing_base
        )
        pyramid_actions, remaining_capital = self._execute_pyramid_adds(
            decisions, action_date, data_date, sizing_base, remaining_capital
        )
        buy_actions, remaining_capital = self._execute_buys(
            decisions, action_date, data_date, top_n, swap_buy_queue,
            current_holdings, sell_actions, sizing_base, remaining_capital,
        )

        new_actions = sell_actions + pyramid_actions + buy_actions
        self._persist_actions(new_actions)

        buy_count = len([a for a in new_actions if isinstance(a, BuyActionResult) and a.units > 0])
        sell_count = len([a for a in new_actions if isinstance(a, SellActionResult)])
        logger.info(
            f"generate_actions: complete — {buy_count} buys, {sell_count} sells, "
            f"remaining_capital=₹{remaining_capital:,.0f}"
        )
        return new_actions
