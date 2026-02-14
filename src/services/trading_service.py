"""
Trading Service

Core trading decision logic shared between live and backtesting.
Implements the SELL → BUY → SWAP rebalancing algorithm.

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
    """
    symbol: str
    units: int
    stop_loss: float
    score: float


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
        action_type: 'SELL', 'BUY', or 'SWAP'
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

    Implements SELL → BUY → SWAP logic that is shared between
    live ActionsService and backtesting WeeklyBacktester.
    """

    @staticmethod
    def generate_decisions(
        holdings: List[HoldingSnapshot],
        candidates: List[CandidateInfo],
        prices: Dict[str, float],
        max_positions: int,
        swap_buffer: float = 1.25,
        exit_threshold: float = 40.0,
    ) -> List[TradingDecision]:
        """
        Generate trading decisions using SELL → BUY → SWAP logic.

        Parameters:
            holdings: Current portfolio positions as HoldingSnapshot list
            candidates: Top-N ranked stocks as CandidateInfo list
            prices: Price lookup dict (symbol → price).
                    Live passes weekly lows for stop-loss check;
                    backtest passes close prices.
            max_positions: Maximum number of portfolio positions
            swap_buffer: Score multiplier for swap decisions.
                         e.g. 1.25 means challenger must beat incumbent by 25%.
                         Derived from config: 1 + buffer_percent
            exit_threshold: Score below which a position is exited.
                            From config.exit_threshold (default 40.0)

        Returns:
            List[TradingDecision]: Ordered list of SELL, BUY, SWAP decisions
        """
        decisions: List[TradingDecision] = []
        candidate_symbols = {c.symbol for c in candidates}

        # Track which holdings remain after sells
        remaining_holdings: List[HoldingSnapshot] = []

        # ========== PHASE 1: SELL ==========
        # Check stop-loss and score degradation for each holding
        for h in holdings:
            price = prices.get(h.symbol, 0)

            # Stop-loss hit: price breached the stop level
            if h.stop_loss >= price:
                decisions.append(TradingDecision(
                    action_type='SELL',
                    symbol=h.symbol,
                    reason='stoploss hit',
                    units=h.units,
                ))
                logger.info(f"SELL {h.symbol}: stop-loss {h.stop_loss:.2f} >= price {price:.2f}")
                continue

            # Score degradation: score fell below exit threshold
            if h.score < exit_threshold:
                decisions.append(TradingDecision(
                    action_type='SELL',
                    symbol=h.symbol,
                    reason=f'score degraded to {h.score:.1f}',
                    units=h.units,
                ))
                logger.info(f"SELL {h.symbol}: score {h.score:.1f} < threshold {exit_threshold}")
                continue

            remaining_holdings.append(h)

        # ========== PHASE 2: BUY ==========
        # Count current holdings that survived phase 1
        current_count = len(remaining_holdings)
        vacancies = max_positions - current_count

        # Build set of symbols already held (surviving)
        held_symbols = {h.symbol for h in remaining_holdings}

        buy_count = 0
        buy_candidates = []
        for c in candidates:
            if buy_count >= vacancies:
                break
            if c.symbol not in held_symbols:
                decisions.append(TradingDecision(
                    action_type='BUY',
                    symbol=c.symbol,
                    reason='top N buys',
                ))
                held_symbols.add(c.symbol)
                buy_count += 1
                buy_candidates.append(c.symbol)
                logger.info(f"BUY {c.symbol}: vacancy fill (score {c.score:.1f})")

        # ========== PHASE 3: SWAP ==========
        # Remaining candidates not yet bought
        swap_candidates = [
            c for c in candidates
            if c.symbol not in held_symbols
        ]
        non_top_n_holdings = [c for c in candidates if c.symbol not in held_symbols]

        for challenger in swap_candidates:
            if not remaining_holdings:
                break

            # Find weakest incumbent among remaining holdings
            weakest = min(non_top_n_holdings, key=lambda h: h.score)

            if challenger.score > swap_buffer * weakest.score:
                decisions.append(TradingDecision(
                    action_type='SWAP',
                    symbol=weakest.symbol,
                    reason=f'swap: score {weakest.score:.1f} → {challenger.symbol} ({challenger.score:.1f})',
                    units=weakest.units,
                    swap_for=challenger.symbol,
                    swap_sell_units=weakest.units,
                ))
                non_top_n_holdings.remove(weakest)
                held_symbols.discard(weakest.symbol)
                held_symbols.add(challenger.symbol)
                logger.info(
                    f"SWAP {weakest.symbol} → {challenger.symbol}: "
                    f"{challenger.score:.1f} > {swap_buffer} × {weakest.score:.1f}"
                )
            else:
                break
        return decisions
