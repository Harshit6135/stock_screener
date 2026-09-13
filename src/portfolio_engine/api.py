"""Storage- and framework-free portfolio decisions.

This module is intentionally independent of Flask, SQLAlchemy, providers, and
filesystem APIs.  It is the first callable seam that later paper/live adapters
and the in-memory backtester will share.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import Enum

from src.platform_kernel import DomainValidationError, Money, Quantity


class DecisionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    PYRAMID_ADD = "PYRAMID_ADD"
    SWAP_SELL = "SWAP_SELL"
    HARD_STOP_GAP_OPEN = "HARD_STOP_GAP_OPEN"
    HARD_STOP_INTRADAY = "HARD_STOP_INTRADAY"
    SCORE_EXIT = "SCORE_EXIT"
    NO_ACTION = "NO_ACTION"


def _amount(value: Decimal | float | str, field_name: str) -> Decimal:
    del field_name
    return Money(Decimal(str(value))).amount


@dataclass(frozen=True)
class MarketBar:
    instrument_id: str
    as_of_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("open", "high", "low", "close"):
            object.__setattr__(self, field_name, _amount(getattr(self, field_name), field_name))
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise DomainValidationError("market prices must be positive")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise DomainValidationError("market bar OHLC values are inconsistent")
        if self.volume is not None and (isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0):
            raise DomainValidationError("market bar volume is invalid")


@dataclass(frozen=True)
class Holding:
    instrument_id: str
    units: Quantity
    average_price: Money
    current_stop: Money
    score: Decimal
    opened_on: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _amount(self.score, "score"))
        if self.current_stop.amount < 0:
            raise DomainValidationError("current_stop must not be negative")


@dataclass(frozen=True)
class Candidate:
    instrument_id: str
    score: Decimal
    size_multiplier: Decimal = Decimal(1)

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _amount(self.score, "score"))
        multiplier = _amount(self.size_multiplier, "size_multiplier")
        if multiplier <= 0:
            raise DomainValidationError("size_multiplier must be positive")
        object.__setattr__(self, "size_multiplier", multiplier)


@dataclass(frozen=True)
class PortfolioPolicy:
    max_positions: int
    exit_score: Decimal
    max_position_fraction: Decimal = Decimal("0.25")
    swap_buffer: Decimal = Decimal("0.25")
    pyramid_fraction: Decimal = Decimal(0)
    initial_stop_fraction: Decimal = Decimal("0.10")
    max_volume_participation: Decimal | None = None
    ltcg_hold_days: int | None = None
    rebalance_frequency: str = "DAILY"
    swap_cost_bps: Decimal = Decimal(0)
    check_daily_sl: bool = True
    mid_week_buy: bool = True

    def __post_init__(self) -> None:
        if self.max_positions < 1:
            raise DomainValidationError("max_positions must be at least one")
        object.__setattr__(self, "exit_score", _amount(self.exit_score, "exit_score"))
        fraction = _amount(self.max_position_fraction, "max_position_fraction")
        if not Decimal(0) < fraction <= Decimal(1):
            raise DomainValidationError("max_position_fraction must be in (0, 1]")
        object.__setattr__(self, "max_position_fraction", fraction)
        swap_buffer = _amount(self.swap_buffer, "swap_buffer")
        pyramid_fraction = _amount(self.pyramid_fraction, "pyramid_fraction")
        initial_stop_fraction = _amount(self.initial_stop_fraction, "initial_stop_fraction")
        participation = None if self.max_volume_participation is None else _amount(self.max_volume_participation, "max_volume_participation")
        if (
            swap_buffer < 0
            or not Decimal(0) <= pyramid_fraction <= Decimal(1)
            or not Decimal(0) < initial_stop_fraction < Decimal(1)
            or participation is not None and not Decimal(0) < participation <= Decimal(1)
            or self.ltcg_hold_days is not None and (isinstance(self.ltcg_hold_days, bool) or not isinstance(self.ltcg_hold_days, int) or self.ltcg_hold_days < 1)
            or self.rebalance_frequency not in {"DAILY", "BIWEEKLY", "MONTHLY"}
            or _amount(self.swap_cost_bps, "swap_cost_bps") < 0
            or _amount(self.swap_cost_bps, "swap_cost_bps") >= 10_000
        ):
            raise DomainValidationError("swap and pyramid policy values are invalid")
        object.__setattr__(self, "swap_buffer", swap_buffer)
        object.__setattr__(self, "pyramid_fraction", pyramid_fraction)
        object.__setattr__(self, "initial_stop_fraction", initial_stop_fraction)
        object.__setattr__(self, "max_volume_participation", participation)
        object.__setattr__(self, "swap_cost_bps", _amount(self.swap_cost_bps, "swap_cost_bps"))
        object.__setattr__(self, "check_daily_sl", bool(self.check_daily_sl))
        object.__setattr__(self, "mid_week_buy", bool(self.mid_week_buy))


@dataclass(frozen=True)
class ExecutionAssumptions:
    """Costs applied by the shared paper/backtest execution path."""

    slippage_bps: Decimal = Decimal(0)
    fee_bps: Decimal = Decimal(0)
    tax_bps: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        slippage = _amount(self.slippage_bps, "slippage_bps")
        fee = _amount(self.fee_bps, "fee_bps")
        tax = _amount(self.tax_bps, "tax_bps")
        if slippage < 0 or fee < 0 or tax < 0 or slippage >= 10_000 or fee >= 10_000 or tax >= 10_000:
            raise DomainValidationError("execution costs must be in [0, 10000) bps")
        object.__setattr__(self, "slippage_bps", slippage)
        object.__setattr__(self, "fee_bps", fee)
        object.__setattr__(self, "tax_bps", tax)


@dataclass(frozen=True)
class PortfolioState:
    cash: Money
    holdings: tuple[Holding, ...] = ()

    def __post_init__(self) -> None:
        if self.cash.amount < 0:
            raise DomainValidationError("portfolio cash must not be negative")
        identifiers = [holding.instrument_id for holding in self.holdings]
        if len(identifiers) != len(set(identifiers)):
            raise DomainValidationError("portfolio cannot contain duplicate holdings")


@dataclass(frozen=True)
class Decision:
    type: DecisionType
    instrument_id: str | None
    units: Quantity | None
    execution_price: Money | None
    reason: str
    fee: Money = field(default_factory=lambda: Money(Decimal(0)))


def _sell_decision(
    holding: Holding,
    bar: MarketBar,
    policy: PortfolioPolicy,
    is_rebalance_day: bool = True,
) -> Decision | None:
    if policy.check_daily_sl or is_rebalance_day:
        if bar.open <= holding.current_stop.amount:
            return Decision(
                DecisionType.HARD_STOP_GAP_OPEN,
                holding.instrument_id,
                holding.units,
                Money(bar.open),
                "open breached stop",
            )
        if bar.low <= holding.current_stop.amount:
            return Decision(
                DecisionType.HARD_STOP_INTRADAY,
                holding.instrument_id,
                holding.units,
                holding.current_stop,
                "intraday low breached stop",
            )
    if is_rebalance_day and holding.score < policy.exit_score:
        return Decision(
            DecisionType.SCORE_EXIT,
            holding.instrument_id,
            holding.units,
            Money(bar.open),
            "prior signal score below exit threshold",
        )
    return None


def _with_costs(
    decision: Decision,
    assumptions: ExecutionAssumptions,
) -> Decision:
    if decision.execution_price is None or decision.units is None:
        return decision
    is_buy = decision.type in {DecisionType.BUY, DecisionType.PYRAMID_ADD}
    direction = Decimal(1) if is_buy else Decimal(-1)
    price = Money(
        decision.execution_price.amount
        * (Decimal(1) + direction * assumptions.slippage_bps / Decimal(10000)),
        decision.execution_price.currency,
    )
    fee = Money(
        price.amount * decision.units.units * (
            assumptions.fee_bps + (assumptions.tax_bps if not is_buy else Decimal(0))
        ) / Decimal(10000),
        price.currency,
    )
    return Decision(
        decision.type,
        decision.instrument_id,
        decision.units,
        price,
        decision.reason,
        fee,
    )


def _execution_price(decision: Decision) -> Money:
    if decision.execution_price is None:
        raise DomainValidationError("priced decision requires an execution price")
    return decision.execution_price


def _volume_cap(bar: MarketBar, policy: PortfolioPolicy) -> int | None:
    if policy.max_volume_participation is None or bar.volume is None:
        return None
    return int((Decimal(bar.volume) * policy.max_volume_participation).to_integral_value(rounding=ROUND_DOWN))


def evaluate(
    state: PortfolioState,
    policy: PortfolioPolicy,
    candidates: Sequence[Candidate],
    bars: Mapping[str, MarketBar],
    execution: ExecutionAssumptions | None = None,
    is_rebalance_day: bool = True,
) -> tuple[tuple[Decision, ...], PortfolioState]:
    """Return deterministic sell, pyramid, vacancy-buy, and swap decisions.

    Decisions are evaluated in the only permitted order: risk/score exits,
    pyramid adds, then candidate buys or swaps.  This makes released cash
    available before a purchase and keeps a single state machine for paper and
    backtest callers.
    """
    decisions: list[Decision] = []
    retained: list[Holding] = []
    cash = state.cash.amount
    released_cash = Decimal(0)
    deferred_cash = Decimal(0)
    intraday_event = False
    assumptions = execution or ExecutionAssumptions()

    for holding in sorted(state.holdings, key=lambda item: item.instrument_id):
        bar = bars.get(holding.instrument_id)
        if bar is None:
            raise DomainValidationError(f"missing required market bar for {holding.instrument_id}")
        sell = _sell_decision(holding, bar, policy, is_rebalance_day=is_rebalance_day)
        if sell is None:
            retained.append(holding)
            continue
        sell = _with_costs(sell, assumptions)
        decisions.append(sell)
        proceeds = _execution_price(sell).amount * holding.units.units - sell.fee.amount
        if sell.type == DecisionType.HARD_STOP_INTRADAY:
            deferred_cash += proceeds
            intraday_event = True
        else:
            released_cash += proceeds

    if not is_rebalance_day and not policy.mid_week_buy:
        candidates = ()

    candidate_by_id = {candidate.instrument_id: candidate for candidate in candidates}
    held = {holding.instrument_id for holding in retained}

    if policy.pyramid_fraction and not intraday_event:
        rewritten: list[Holding] = []
        for holding in retained:
            candidate = candidate_by_id.get(holding.instrument_id)
            bar = bars.get(holding.instrument_id)
            if (
                candidate is None
                or bar is None
                or holding.current_stop.amount < holding.average_price.amount
                or candidate.score <= holding.score
            ):
                rewritten.append(holding)
                continue
            allocation = cash * policy.max_position_fraction * policy.pyramid_fraction * candidate.size_multiplier
            units = int((allocation / bar.open).to_integral_value(rounding=ROUND_DOWN))
            cap = _volume_cap(bar, policy)
            if cap is not None:
                units = min(units, cap)
            if units < 1:
                rewritten.append(holding)
                continue
            quantity = Quantity(units)
            decision = _with_costs(
                Decision(
                    DecisionType.PYRAMID_ADD,
                    holding.instrument_id,
                    quantity,
                    Money(bar.open),
                    "winner pyramid",
                ),
                assumptions,
            )
            while units and _execution_price(decision).amount * units + decision.fee.amount > cash:
                units -= 1
                if units:
                    quantity = Quantity(units)
                    decision = _with_costs(
                        Decision(
                            DecisionType.PYRAMID_ADD,
                            holding.instrument_id,
                            quantity,
                            Money(bar.open),
                            "winner pyramid",
                        ),
                        assumptions,
                    )
            if units < 1:
                rewritten.append(holding)
                continue
            price = _execution_price(decision)
            old_value = holding.average_price.amount * holding.units.units
            total_units = holding.units.units + units
            average_price = Money((old_value + price.amount * units) / total_units)
            decisions.append(decision)
            cash -= price.amount * units + decision.fee.amount
            rewritten.append(
                Holding(
                    holding.instrument_id,
                    Quantity(total_units),
                    average_price,
                    holding.current_stop,
                    candidate.score,
                )
            )
        retained = rewritten

    if intraday_event:
        return tuple(decisions), PortfolioState(
            Money(cash + released_cash + deferred_cash), tuple(retained)
        )

    for candidate in sorted(candidates, key=lambda item: (-item.score, item.instrument_id)):
        if candidate.instrument_id in held:
            continue
        bar = bars.get(candidate.instrument_id)
        if bar is None:
            raise DomainValidationError(
                f"missing required candidate market bar for {candidate.instrument_id}"
            )
        if len(retained) >= policy.max_positions:
            weakest = min(retained, key=lambda holding: (holding.score, holding.instrument_id))
            effective_swap_buffer = policy.swap_buffer + policy.swap_cost_bps / Decimal(10_000)
            if candidate.score <= weakest.score * (Decimal(1) + effective_swap_buffer):
                continue
            if (
                policy.ltcg_hold_days is not None
                and weakest.opened_on is not None
                and (bar.as_of_date - weakest.opened_on).days < policy.ltcg_hold_days
            ):
                continue
            weakest_bar = bars.get(weakest.instrument_id)
            if weakest_bar is None:
                continue
            sell = _with_costs(
                Decision(
                    DecisionType.SWAP_SELL,
                    weakest.instrument_id,
                    weakest.units,
                    Money(weakest_bar.open),
                    "prior-close candidate beat weakest holding",
                ),
                assumptions,
            )
            decisions.append(sell)
            released_cash += _execution_price(sell).amount * weakest.units.units - sell.fee.amount
            retained.remove(weakest)
            held.remove(weakest.instrument_id)
            # Candidate and weakest scores are prior-close inputs; both legs
            # execute at this step's open under sell-first sequencing.
        allocation = min(cash * policy.max_position_fraction * candidate.size_multiplier, cash)
        units = int((allocation / bar.open).to_integral_value(rounding=ROUND_DOWN))
        cap = _volume_cap(bar, policy)
        if cap is not None:
            units = min(units, cap)
        if units < 1:
            continue
        quantity = Quantity(units)
        decision = _with_costs(
            Decision(
                DecisionType.BUY,
                candidate.instrument_id,
                quantity,
                Money(bar.open),
                "ranked vacancy",
            ),
            assumptions,
        )
        while units and _execution_price(decision).amount * units + decision.fee.amount > cash:
            units -= 1
            if units:
                quantity = Quantity(units)
                decision = _with_costs(
                    Decision(
                        DecisionType.BUY,
                        candidate.instrument_id,
                        quantity,
                        Money(bar.open),
                        "ranked vacancy",
                    ),
                    assumptions,
                )
        if units < 1:
            continue
        price = _execution_price(decision)
        decisions.append(decision)
        cash -= price.amount * units + decision.fee.amount
        retained.append(
            Holding(
                candidate.instrument_id,
                quantity,
                price,
                Money(price.amount * (Decimal(1) - policy.initial_stop_fraction)),
                candidate.score,
            )
        )
        held.add(candidate.instrument_id)

    if not decisions:
        decisions.append(Decision(DecisionType.NO_ACTION, None, None, None, "portfolio unchanged"))
    return tuple(decisions), PortfolioState(Money(cash + released_cash), tuple(retained))
