"""
Trading Service

Core trading decision logic shared between live and backtesting.
Implements the SELL → Unified Candidate Loop (BUY/PYRAMID/SWAP) algorithm.

Both ActionsService and WeeklyBacktester convert their data to
normalized dataclasses, call generate_decisions(), then execute
the returned decisions in their own way.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from config import setup_logger


logger = setup_logger(name="TradingEngine")


@dataclass
class HoldingSnapshot:
    """
    Normalized view of a portfolio position.

    Attributes:
        symbol: Trading symbol
        units: Number of shares held
        stop_loss: Current effective stop-loss price
        score: Current composite score for the position
        entry_price: Entry price (for pyramid risk check)
    """
    symbol: str
    units: int
    stop_loss: float
    score: float
    entry_price: float = 0.0


@dataclass
class CandidateInfo:
    """
    Normalized view of a ranked candidate stock.

    Attributes:
        symbol: Trading symbol
        score: Composite score from ranking
    """
    symbol: str
    score: float


@dataclass
class TradingDecision:
    """
    A single trading decision output.

    Attributes:
        action_type: 'SELL', 'BUY', 'SWAP', or 'PYRAMID_ADD'
        symbol: Primary symbol for the action
        reason: Human-readable reason for the decision
        units: Number of units (for SELL only)
        swap_for: Replacement symbol (for SWAP: the new buy)
        swap_sell_units: Units to sell in a swap
    """
    action_type: str
    symbol: str
    reason: str
    units: int = 0
    swap_for: Optional[str] = None
    swap_sell_units: int = 0


class TradingEngine:
    """
    Core trading decision engine.

    Implements SELL → Unified Candidate Loop (BUY/PYRAMID/SWAP) logic
    shared between live ActionsService and backtesting WeeklyBacktester.
    """

    @staticmethod
    def generate_decisions(
        holdings: List[HoldingSnapshot],
        candidates: List[CandidateInfo],
        prices: Dict[str, float],
        max_positions: int,
        swap_buffer: float = 1.25,
        exit_threshold: float = 40.0,
        ema_50_values: Dict[str, float] = None,
        enable_pyramiding: bool = False,
    ) -> List[TradingDecision]:
        """
        Generate trading decisions using SELL → Unified Candidate Loop.

        After sells, loops through candidates by score (highest first).
        For each candidate:
          1. Already held + pyramid conditions pass → PYRAMID_ADD
          2. Not held + vacancy available → BUY
          3. Not held + no vacancy + beats weakest → SWAP

        Parameters:
            holdings: Current portfolio positions as HoldingSnapshot list
            candidates: Top-N ranked stocks as CandidateInfo list (sorted by score desc)
            prices: Price lookup dict (symbol → price)
            max_positions: Maximum number of portfolio positions
            swap_buffer: Score multiplier for swap decisions
            exit_threshold: Score below which a position is exited
            ema_50_values: Dict of symbol → EMA 50 value (for pyramid check)
            enable_pyramiding: Whether to check for pyramid adds

        Returns:
            List[TradingDecision]: Ordered list of decisions
        """
        decisions: List[TradingDecision] = []
        remaining_holdings: List[HoldingSnapshot] = []
        candidate_symbols = {c.symbol for c in candidates}
        if ema_50_values is None:
            ema_50_values = {}

        # ========== PHASE 1: SELL ==========
        # Check stop-loss and score degradation for each holding
        sold_symbols = set()
        surviving_holdings = {}  # symbol -> HoldingSnapshot
        for h in holdings:
            price = prices.get(h.symbol, 0)
            if h.stop_loss >= price:
                decisions.append(TradingDecision(
                    action_type='SELL',
                    symbol=h.symbol,
                    reason='stoploss hit',
                    units=h.units,
                ))
                sold_symbols.add(h.symbol)
                logger.info(f"SELL {h.symbol}: stop-loss {h.stop_loss:.2f} >= price {price:.2f}")
            elif h.score < exit_threshold:
                decisions.append(TradingDecision(
                    action_type='SELL',
                    symbol=h.symbol,
                    reason=f'score degraded to {h.score:.1f}',
                    units=h.units,
                ))
                sold_symbols.add(h.symbol)
                logger.info(f"SELL {h.symbol}: score {h.score:.1f} < threshold {exit_threshold}")
            else:
                if h.symbol not in candidate_symbols:
                    remaining_holdings.append(h)
                surviving_holdings[h.symbol] = h

        # ========== PHASE 2: UNIFIED CANDIDATE LOOP ==========
        current_count = len(holdings) - len(sold_symbols)
        vacancies = max_positions - current_count

        for c in candidates:
            # --- Already held → check for pyramid ---
            if c.symbol in surviving_holdings:
                if not enable_pyramiding:
                    continue
                h = surviving_holdings[c.symbol]
                # Check 1: Capital risk must be zero (SL >= entry price)
                if float(h.stop_loss) < float(h.entry_price):
                    continue
                # Check 2: EMA 50 above entry price
                if ema_50_values.get(c.symbol, 0) < float(h.entry_price):
                    continue
                # Passed both → pyramid add
                decisions.append(TradingDecision(
                    action_type='PYRAMID_ADD',
                    symbol=c.symbol,
                    reason='pyramid add',
                ))
                logger.info(
                    f"PYRAMID {c.symbol}: SL {h.stop_loss:.2f} >= entry {h.entry_price:.2f}, "
                    f"EMA50 {ema_50_values.get(c.symbol, 0):.2f} > entry {h.entry_price:.2f}"
                )
                continue

            # --- Not held + vacancy → BUY ---
            if vacancies > 0:
                decisions.append(TradingDecision(
                    action_type='BUY',
                    symbol=c.symbol,
                    reason='top N buys',
                ))
                vacancies -= 1
                logger.info(f"BUY {c.symbol}: vacancy fill (score {c.score:.1f})")
                continue

            # --- Not held + no vacancy → SWAP (vs weakest) ---
            if remaining_holdings:
                weakest = min(remaining_holdings, key=lambda h: h.score)
                if c.score > swap_buffer * float(weakest.score):
                    decisions.append(TradingDecision(
                        action_type='SWAP',
                        symbol=weakest.symbol,
                        reason=f'swap: score {weakest.score:.1f} → {c.symbol} ({c.score:.1f})',
                        units=weakest.units,
                        swap_for=c.symbol,
                        swap_sell_units=weakest.units,
                    ))
                    remaining_holdings.remove(weakest)
                    logger.info(
                        f"SWAP {weakest.symbol} → {c.symbol}: "
                        f"{c.score:.1f} > {swap_buffer} × {weakest.score:.1f}"
                    )
                else:
                    break  # candidates are sorted by score, no more profitable swaps

        return decisions

