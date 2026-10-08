"""Durable portfolio action proposals from prior rankings."""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger("screener." + __name__)
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.domains.artifacts import ArtifactPublisher
from src.domains.portfolio_accounting import Fill, FillSide, Ledger, PortfolioProjection
from src.domains.portfolio_engine import (
    Candidate,
    DecisionType,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioProposalStore,
    PortfolioState,
    evaluate,
)
from src.domains.strategies import feature_series, valid_bar
from src.gates.repositories import MarketRepository
from src.gates.workflows.positional_trend import PositionalTrendJobs
from src.gates.workflows.research import ResearchJobs
from src.platform_kernel import DomainValidationError, Money, QualityStatus, Quantity
from src.platform_kernel.sqlite import sqlite_connection

_BUY_TYPES = {DecisionType.BUY, DecisionType.PYRAMID_ADD}
_EXECUTION_POLICY_VERSION = "v4-portfolio-execution-1"
_DEFAULT_PYRAMID_FRACTION = Decimal("0.5")
_EXECUTION_POLICY = {
    "signal_timing": "close",
    "execution_timing": "next_tradable_open",
    "sell_before_buy": True,
    "cash_resize": "actual_open_with_available_cash",
    "zero_unit_buy": "remain_pending",
    "vacancy_advance": "opt_in",
    "stale_buy_threshold": "0.05",
    "pyramid_enabled": "explicit_operator_switch",
    "pyramid_fraction": "0.5",
}


@dataclass(frozen=True)
class _GenerationRequest:
    account_id: str
    strategy_id: str
    positions: int
    ltcg_hold_days: int
    sector_artifact_id: str | None
    macro_artifact_id: str | None
    market_cap_artifact_id: str | None
    market_cap_sizing: str
    fundamentals_artifact_id: str | None
    pyramid_enabled: bool
    pyramid_fraction: Decimal
    stale_buy_threshold: Decimal
    decorrelation_threshold: Decimal
    max_sector_fraction: Decimal
    max_drawdown_pause: Decimal
    max_vix: Decimal
    swap_cost_bps: Decimal
    min_eps: Decimal | None
    max_debt_equity: Decimal | None
    vacancy_from: str | None
    correlation_artifact_id: str | None
    action_date: date
    forward: bool
    market_date: date
    vacancy_date: date | None
    revision: dict[str, Any]
    configured_settings: dict[str, Any]


@dataclass(frozen=True)
class _GenerationInputs:
    account: dict[str, Any]
    projection: PortfolioProjection
    week_end: date
    risk_inputs: dict[str, Any]
    ranked: list[dict[str, Any]]
    bars: dict[str, MarketBar]
    snapshot_ids: set[str]
    eligible: list[dict[str, Any]]


@dataclass(frozen=True)
class _GenerationSelection:
    stale_buy_skipped: list[dict[str, object]]
    sector_skipped: list[dict[str, object]]
    drawdown_paused: bool
    drawdown_value: Decimal | None
    macro_paused: bool
    vix_value: Decimal | None
    decorrelation_skipped: list[dict[str, object]]
    candidates: tuple[Candidate, ...]
    holdings: tuple[Holding, ...]
    score_by_id: dict[str, Decimal]
    rank_by_id: dict[str, int]


@dataclass(frozen=True)
class _GenerationEvaluation:
    policy: PortfolioPolicy
    resulting_state: PortfolioState
    encoded_decisions: list[dict[str, object]]


class ActionJobs:
    def __init__(
        self,
        database: str | Path,
        market: MarketRepository,
        research: ResearchJobs,
        ledger: Ledger,
        publisher: ArtifactPublisher,
        positional_trend=None,
        risk_config=None,
    ) -> None:
        self.database = Path(database)
        self.market = market
        self.research = research
        self.ledger = ledger
        self.publisher = publisher
        self.positional_trend = positional_trend
        self.risk_config = risk_config
        self.risk_guard = None
        self.proposals_store = PortfolioProposalStore(self.database)

    def _current_buy_members(self) -> tuple[str, set[str]]:
        """Use the latest immutable NSE snapshot for all live BUY proposals."""
        snapshot = self.market.latest_universe_snapshot("NIFTY 500")
        if snapshot is None:
            raise DomainValidationError("NIFTY 500 snapshot is unavailable for BUY eligibility")
        snapshot_id = str(snapshot["snapshot_id"])
        member_isins = {
            str(row["isin"])
            for row in self.market.universe_snapshot_members(snapshot_id, limit=1000)
        }
        eligible_ids = {
            str(row["instrument_id"])
            for row in self.market.tracked_instruments()
            if row["exchange"] == "NSE" and str(row["isin"]) in member_isins
        }
        return snapshot_id, eligible_ids

    def _generate_positional_trend(self, payload: dict[str, Any]) -> dict[str, object]:
        """Create a reviewable next-open proposal from the prior close's S4 signals."""
        if self.positional_trend is None:
            raise DomainValidationError("Positional trend daily signal service is unavailable")
        allowed = {
            "account_id",
            "strategy_id",
            "action_date",
            "as_of_date",
            "max_positions",
            "risk_pct",
            "max_order_pct",
            "adv_participation_pct",
            "round_trip_cost_bps",
            "universe",
        }
        if set(payload) - allowed:
            raise DomainValidationError("Positional trend action payload contains unsupported fields")
        account_id = payload.get("account_id")
        if not isinstance(account_id, str) or not account_id.strip():
            raise DomainValidationError("account_id is required")
        try:
            action_date = date.fromisoformat(str(payload.get("action_date")))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("action_date must be an ISO date") from exc
        forward = "as_of_date" in payload
        if forward:
            try:
                signal_date = date.fromisoformat(str(payload["as_of_date"]))
            except (TypeError, ValueError) as exc:
                raise DomainValidationError("as_of_date must be an ISO date") from exc
            if signal_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date() or action_date <= signal_date:
                raise DomainValidationError("forward actions require a completed signal date before the target date")
            sessions = self.market.session_dates(signal_date - timedelta(days=14), signal_date, exchange="NSE")
            if not sessions or sessions[-1] != signal_date.isoformat():
                raise DomainValidationError("as_of_date must be a completed stored NSE session")
        else:
            if action_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
                raise DomainValidationError("portfolio action date must be completed")
            sessions = sorted(
                self.market.session_dates(action_date - timedelta(days=14), action_date, exchange="NSE")
            )
            prior_sessions = [day for day in sessions if day < action_date.isoformat()]
            if not prior_sessions or not sessions or sessions[-1] != action_date.isoformat():
                raise DomainValidationError(
                    "Positional trend action date requires a prior and current stored session"
                )
            signal_date = date.fromisoformat(prior_sessions[-1])
        universe = payload.get("universe", "SNAPSHOT_NIFTY500")
        if universe != "SNAPSHOT_NIFTY500":
            raise DomainValidationError("Positional trend universe is invalid")
        signal_entry = self.positional_trend.read_signals(signal_date, str(universe))
        if signal_entry is None:
            self.positional_trend.build_signals(
                {"as_of_date": signal_date.isoformat(), "universe": universe}
            )
            signal_entry = self.positional_trend.read_signals(signal_date, str(universe))
        if signal_entry is None:
            raise DomainValidationError("prior Positional trend signal artifact could not be created")
        signal_artifact_id, signal_payload = signal_entry
        revision = self.research.runtime.revision("positional_trend_following")
        settings = self.research.runtime.portfolio_policy("positional_trend_following")
        positions = payload.get("max_positions", int(settings["max_positions"]))
        if (
            isinstance(positions, bool)
            or not isinstance(positions, int)
            or not 1 <= positions <= 50
        ):
            raise DomainValidationError("Positional trend max_positions must be between 1 and 50")
        try:
            risk_fraction = (
                Decimal(str(payload.get("risk_pct", float(settings["risk_fraction"]) * 100))) / 100
            )
            order_fraction = (
                Decimal(
                    str(payload.get("max_order_pct", float(settings["max_order_fraction"]) * 100))
                )
                / 100
            )
            adv_fraction = (
                Decimal(
                    str(
                        payload.get(
                            "adv_participation_pct",
                            float(settings["adv_participation_fraction"]) * 100,
                        )
                    )
                )
                / 100
            )
            round_trip_cost_bps = Decimal(str(payload.get("round_trip_cost_bps", 0)))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise DomainValidationError("Positional trend portfolio limits must be numeric") from exc
        if (
            not risk_fraction.is_finite()
            or not 0 < risk_fraction <= 1
            or not order_fraction.is_finite()
            or not 0 < order_fraction <= 1
            or not adv_fraction.is_finite()
            or not 0 < adv_fraction <= 1
            or not round_trip_cost_bps.is_finite()
            or not 0 <= round_trip_cost_bps < 10_000
        ):
            raise DomainValidationError("Positional trend portfolio limits are outside supported ranges")
        account = next(
            (item for item in self.ledger.accounts() if item["account_id"] == account_id), None
        )
        if account is None:
            raise DomainValidationError("portfolio account does not exist")
        projection = self.ledger.projection(account_id)
        if any(row["filtered"] for row in signal_payload["signals"]):
            universe_snapshot_id, buy_members = self._current_buy_members()
        else:
            universe_snapshot_id, buy_members = None, set()
        signal_rows = {str(item["instrument_id"]): item for item in signal_payload["signals"]}
        held: dict[str, int] = {}
        for lot in projection.open_lots:
            held[lot.instrument_id] = held.get(lot.instrument_id, 0) + lot.remaining_units.units
        held_source_ids: set[str] = set()
        held_last_closes: dict[str, Decimal] = {}
        opened = {}
        for lot in projection.open_lots:
            opened[lot.instrument_id] = min(
                opened.get(lot.instrument_id, lot.opened_on), lot.opened_on
            )
        if held:
            histories = self.market.histories(
                date(2021, 1, 1), signal_date, instrument_ids=set(held)
            )
            rules = self.research.runtime.signal_rules("positional_trend_following")
            for instrument_id, (history, identity) in histories.items():
                if instrument_id not in held:
                    continue
                held_source_ids.update(
                    str(bar["snapshot_id"]) for bar in history if bar.get("snapshot_id")
                )
                sessions_for_stock = self.market.session_dates(
                    date(2021, 1, 1), signal_date, exchange=str(identity["exchange"])
                )
                features = feature_series(
                    history, sessions_for_stock, str(identity["symbol"]), rules
                )
                features = [
                    row for row in features if row["signal_date"] <= signal_date.isoformat()
                ]
                valid_history = [bar for bar in history if valid_bar(bar)]
                if valid_history:
                    latest_bar = max(valid_history, key=lambda bar: str(bar["as_of_date"]))
                    held_last_closes[instrument_id] = Decimal(str(latest_bar["close"]))
                # Reconstruct any unexecuted exit since this position opened.
                # This survives a stock holiday, an unavailable open or a missed proposal run.
                triggered = next(
                    (
                        row
                        for row in features
                        if row["signal_date"] >= opened[instrument_id].isoformat()
                        and row["exit_signal"]
                    ),
                    None,
                )
                if features:
                    signal_rows[instrument_id] = {
                        **features[-1],
                        "instrument_id": instrument_id,
                        "exchange": identity["exchange"],
                        "exit_signal": triggered is not None,
                        "exit_signal_date": triggered["signal_date"] if triggered else None,
                    }
            if set(held) - set(held_last_closes):
                raise DomainValidationError(
                    "held Positional trend position lacks a valid valuation price"
                )
        requested_ids = set(held) | {
            str(row["instrument_id"]) for row in signal_payload["signals"] if row["filtered"]
        }
        bars = {}
        source_ids = {signal_artifact_id, str(revision["revision_id"])} | held_source_ids
        if universe_snapshot_id is not None:
            source_ids.add(universe_snapshot_id)
        for instrument_id in requested_ids:
            rows = self.market.bars(instrument_id, signal_date if forward else action_date, signal_date if forward else action_date, limit=1)
            if rows and valid_bar(rows[-1]):
                bars[instrument_id] = rows[-1]
                source_ids.add(str(rows[-1]["snapshot_id"]))
        equity = projection.cash.amount + sum(
            (
                Decimal(str(bars[instrument_id]["close"] if forward else bars[instrument_id]["open"]))
                if instrument_id in bars
                else held_last_closes[instrument_id]
            )
            * units
            for instrument_id, units in held.items()
        )
        if equity <= 0:
            raise DomainValidationError("Positional trend account equity must be positive")
        cash = projection.cash.amount
        fee_fraction = round_trip_cost_bps / Decimal(20_000)
        decisions: list[dict[str, object]] = []
        skipped: list[dict[str, object]] = []
        exited_ids: set[str] = set()
        # Sell exits first using the next-session open; buys use the remaining cash.
        for instrument_id, units in sorted(held.items()):
            feature = signal_rows.get(instrument_id)
            if feature and feature["exit_signal"]:
                if instrument_id not in bars:
                    skipped.append(
                        {
                            "instrument_id": instrument_id,
                            "reason": "exit_waiting_for_valid_open",
                            "signal_date": feature.get("exit_signal_date", signal_date.isoformat()),
                        }
                    )
                    continue
                price = Decimal(str(bars[instrument_id]["close"] if forward else bars[instrument_id]["open"]))
                fee = price * units * fee_fraction
                decisions.append(
                    {
                        "type": "SELL",
                        "instrument_id": instrument_id,
                        "symbol": feature["symbol"],
                        "units": units,
                        "execution_price": str(price),
                        "fee": str(fee),
                        "reason": "prior close below Supertrend or Donchian exit band",
                        "signal_date": feature.get("exit_signal_date", signal_date.isoformat()),
                    }
                )
                cash += price * units - fee
                equity -= fee
                del held[instrument_id]
                exited_ids.add(instrument_id)
        slots = positions - len(held)
        candidates = sorted(
            (row for row in signal_payload["signals"] if row["filtered"]),
            key=lambda row: (int(row.get("rank") or 10**9), str(row["symbol"])),
        )
        for row in candidates:
            instrument_id = str(row["instrument_id"])
            if instrument_id not in buy_members:
                skipped.append(
                    {"instrument_id": instrument_id, "reason": "outside_current_universe"}
                )
                continue
            bar = bars.get(instrument_id)
            if instrument_id in exited_ids:
                skipped.append({"instrument_id": instrument_id, "reason": "exited_this_session"})
                continue
            if instrument_id in held:
                skipped.append({"instrument_id": instrument_id, "reason": "pyramiding_deferred"})
                continue
            if slots <= 0:
                skipped.append({"instrument_id": instrument_id, "reason": "max_positions"})
                continue
            if bar is None:
                skipped.append({"instrument_id": instrument_id, "reason": "missing_action_open"})
                continue
            price = Decimal(str(bar["close"] if forward else bar["open"]))
            signal_close = Decimal(str(row["close"]))
            stop = Decimal(str(row["initial_stop_anchor"]))
            if price > signal_close * Decimal("1.03") or price <= stop:
                skipped.append({"instrument_id": instrument_id, "reason": "gap_or_anchor_check"})
                continue
            adtv = Decimal(str(row["adv30"] or 0))
            quantity = min(
                int(
                    (equity * risk_fraction / (price - stop)).to_integral_value(
                        rounding="ROUND_FLOOR"
                    )
                ),
                int((equity * order_fraction / price).to_integral_value(rounding="ROUND_FLOOR")),
                int((adtv * adv_fraction / price).to_integral_value(rounding="ROUND_FLOOR")),
                int(
                    (cash / (price * (1 + fee_fraction))).to_integral_value(rounding="ROUND_FLOOR")
                ),
            )
            if quantity <= 0:
                skipped.append({"instrument_id": instrument_id, "reason": "zero_size_or_cash"})
                continue
            gross, fee = price * quantity, price * quantity * fee_fraction
            decisions.append(
                {
                    "type": "BUY",
                    "instrument_id": instrument_id,
                    "symbol": row["symbol"],
                    "units": quantity,
                    "execution_price": str(price),
                    "fee": str(fee),
                    "reason": "ranked Positional trend breakout; next-open size estimated from prior close" if forward else "ranked Positional trend breakout; next-open risk-sized entry",
                    "signal_date": signal_date.isoformat(),
                    "signal_rank": row.get("rank"),
                    "adx": str(row["adx14"]) if row.get("adx14") is not None else None,
                    "adtv": str(row["adv30"]) if row.get("adv30") is not None else None,
                    "stop_anchor": str(stop),
                    "nominal_risk": str(quantity * (price - stop)),
                }
            )
            cash -= gross + fee
            equity -= fee
            held[instrument_id] = quantity
            slots -= 1
        if not decisions:
            decisions = [
                {
                    "type": "NO_ACTION",
                    "instrument_id": None,
                    "symbol": None,
                    "units": None,
                    "execution_price": None,
                    "fee": "0",
                    "reason": "no qualifying Positional trend action",
                }
            ]
        version = int(str(account["version"]))
        fingerprint_value = {
            "account_id": account_id,
            "version": version,
            "strategy_revision_id": revision["revision_id"],
            "universe": universe,
            "signal_artifact_id": signal_artifact_id,
            "signal_date": signal_date.isoformat(),
            "policy": {
                "max_positions": positions,
                "risk_fraction": str(risk_fraction),
                "max_order_fraction": str(order_fraction),
                "adv_participation_fraction": str(adv_fraction),
                "round_trip_cost_bps": str(round_trip_cost_bps),
            },
            "source_ids": sorted(source_ids),
            "action_date": action_date.isoformat(),
            "decisions": decisions,
            "skipped": skipped,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_value, sort_keys=True).encode()
        ).hexdigest()
        proposal_id = str(uuid5(NAMESPACE_URL, f"positional-trend-action-proposal:{fingerprint}"))
        if not self.publisher.catalog.has(proposal_id):
            self.publisher.publish_json(
                "actions/proposals",
                proposal_id,
                {
                    "proposal_id": proposal_id,
                    "account_id": account_id,
                    "strategy_id": "positional_trend_following",
                    "ranking_week_end": signal_date.isoformat(),
                    "signal_date": signal_date.isoformat(),
                    "action_date": action_date.isoformat(),
                    "as_of_date": signal_date.isoformat(),
                    "pricing_basis": "latest_completed_close_estimate" if forward else "historical_action_open",
                    "expected_ledger_version": version,
                    "strategy_revision_id": revision["revision_id"],
                    "signal_artifact_id": signal_artifact_id,
                    "universe": universe,
                    "execution_assumptions": {
                        "fill": "estimated from latest completed close; actual next-open price is unknown" if forward else "stored next-session opening price",
                        "upper_price_circuit": "not_observable_in_daily_OHLCV",
                        "live_order": "proposal generation does not submit an opening order",
                    },
                    "policy": {
                        "max_positions": positions,
                        "pyramiding": False,
                        "risk_fraction": str(risk_fraction),
                        "max_order_fraction": str(order_fraction),
                        "adv_participation_fraction": str(adv_fraction),
                        "round_trip_cost_bps": str(round_trip_cost_bps),
                    },
                    "skipped_candidates": skipped,
                    "decisions": decisions,
                },
                upstream_ids=tuple(sorted(source_ids)),
                quality=QualityStatus.PARTIAL,
            )
        self._recover_projection(proposal_id)
        return self.proposal(proposal_id)

    def _sector_reference(self, sector_artifact_id):
        sector_by_instrument: dict[str, str] = {}
        if sector_artifact_id is not None:
            try:
                _, sector_payload = self.publisher.store.read_json(
                    "reference/sectors", sector_artifact_id
                )
                values = sector_payload["values"]
                if not isinstance(values, dict):
                    raise TypeError("values")
                sector_by_instrument = {str(key): str(value) for key, value in values.items()}
            except (DomainValidationError, KeyError, TypeError) as exc:
                raise DomainValidationError("sector artifact is missing or malformed") from exc
        return sector_by_instrument

    def _capitalization_reference(self, market_cap_artifact_id, market_date, market_cap_sizing):
        cap_by_instrument: dict[str, Decimal] = {}
        if market_cap_artifact_id is not None:
            try:
                _, cap_payload = self.publisher.store.read_json(
                    "reference/market-capitalization", market_cap_artifact_id
                )
                cap_date = date.fromisoformat(str(cap_payload["as_of_date"]))
                values = cap_payload["values"]
                if cap_date > market_date or not isinstance(values, dict):
                    raise ValueError("capitalization date or values")
                if market_cap_sizing == "FREE_FLOAT" and any(
                    not isinstance(value, dict) or set(value) != {"market_cap", "free_float"}
                    for value in values.values()
                ):
                    raise ValueError("free-float values")
                cap_by_instrument = {
                    str(key): Decimal(str(value["market_cap"])) * Decimal(str(value["free_float"]))
                    if market_cap_sizing == "FREE_FLOAT"
                    and isinstance(value, dict)
                    and set(value) == {"market_cap", "free_float"}
                    else Decimal(str(value["market_cap"]))
                    if isinstance(value, dict) and "market_cap" in value
                    else Decimal(str(value))
                    for key, value in values.items()
                }
                if not cap_by_instrument or any(
                    not value.is_finite() or value <= 0 for value in cap_by_instrument.values()
                ):
                    raise ValueError("capitalization values")
            except (DomainValidationError, KeyError, TypeError, ValueError) as exc:
                raise DomainValidationError("market-cap artifact is missing or malformed") from exc
        return cap_by_instrument

    def _fundamentals_reference(self, fundamentals_artifact_id, market_date):
        fundamentals_by_instrument: dict[str, dict[str, Decimal]] = {}
        if fundamentals_artifact_id is not None:
            try:
                _, fundamental_payload = self.publisher.store.read_json(
                    "reference/fundamentals", fundamentals_artifact_id
                )
                fundamental_date = date.fromisoformat(str(fundamental_payload["as_of_date"]))
                values = fundamental_payload["values"]
                if fundamental_date > market_date or not isinstance(values, dict):
                    raise ValueError("fundamentals date or values")
                for instrument_id, value in values.items():
                    if not isinstance(value, dict):
                        raise TypeError("fundamental row")
                    fundamentals_by_instrument[str(instrument_id)] = {
                        field: Decimal(str(raw)) for field, raw in value.items()
                    }
                if not fundamentals_by_instrument:
                    raise ValueError("empty fundamentals")
            except (
                DomainValidationError,
                KeyError,
                TypeError,
                ValueError,
                InvalidOperation,
            ) as exc:
                raise DomainValidationError(
                    "fundamentals artifact is missing or malformed"
                ) from exc
        return fundamentals_by_instrument

    def generate(self, payload: dict[str, Any]) -> dict[str, object]:
        self._validate_generation_payload(payload)
        if payload["strategy_id"] == "positional_trend_following":
            return self._generate_positional_trend(payload)
        request = self._parse_generation_request(payload)
        inputs = self._load_generation_inputs(request)
        selection = self._select_generation_candidates(request, inputs)
        evaluation = self._evaluate_generation(request, inputs, selection)
        return self._publish_generation(request, inputs, selection, evaluation)

    @staticmethod
    def _validate_generation_payload(payload):
        allowed_fields = {
            "account_id",
            "strategy_id",
            "action_date",
            "as_of_date",
            "max_positions",
            "risk_pct",
            "max_order_pct",
            "adv_participation_pct",
            "round_trip_cost_bps",
            "universe",
            "pyramid_enabled",
            "pyramid_fraction",
            "vacancy_from",
            "stale_buy_threshold",
            "correlation_artifact_id",
            "decorrelation_threshold",
            "ltcg_hold_days",
            "sector_artifact_id",
            "max_sector_fraction",
            "max_drawdown_pause",
            "macro_artifact_id",
            "max_vix",
            "market_cap_artifact_id",
            "market_cap_sizing",
            "swap_cost_bps",
            "fundamentals_artifact_id",
            "min_eps",
            "max_debt_equity",
        }
        if (
            not isinstance(payload, dict)
            or not {"account_id", "strategy_id", "action_date"}.issubset(payload)
            or set(payload) - allowed_fields
        ):
            raise DomainValidationError(
                "action generation requires account, strategy, date and limit"
            )

    def _parse_generation_request(self, payload) -> _GenerationRequest:
        account_id = payload["account_id"]
        strategy_id = payload["strategy_id"]
        vacancy_date = None
        positions = payload.get("max_positions")
        ltcg_hold_days = payload.get("ltcg_hold_days", 365)
        sector_artifact_id = payload.get("sector_artifact_id")
        macro_artifact_id = payload.get("macro_artifact_id")
        market_cap_artifact_id = payload.get("market_cap_artifact_id")
        market_cap_sizing = payload.get("market_cap_sizing", "NONE")
        fundamentals_artifact_id = payload.get("fundamentals_artifact_id")
        pyramid_enabled = payload.get("pyramid_enabled")
        try:
            pyramid_fraction = Decimal(str(payload.get("pyramid_fraction", "0")))
            stale_buy_threshold = Decimal(str(payload.get("stale_buy_threshold", "0.05")))
            decorrelation_threshold = Decimal(str(payload.get("decorrelation_threshold", "0.8")))
            max_sector_fraction = Decimal(str(payload.get("max_sector_fraction", "1")))
            max_drawdown_pause = Decimal(str(payload.get("max_drawdown_pause", "0")))
            max_vix = Decimal(str(payload.get("max_vix", "0")))
            swap_cost_bps = Decimal(str(payload.get("swap_cost_bps", "0")))
            min_eps = None if "min_eps" not in payload else Decimal(str(payload["min_eps"]))
            max_debt_equity = (
                None
                if "max_debt_equity" not in payload
                else Decimal(str(payload["max_debt_equity"]))
            )
        except InvalidOperation as exc:
            raise DomainValidationError("action policy values must be numeric") from exc
        vacancy_from = payload.get("vacancy_from")
        correlation_artifact_id = payload.get("correlation_artifact_id")
        if (
            not isinstance(account_id, str)
            or not account_id.strip()
            or strategy_id not in self.research.runtime.strategy_ids()
            or positions is not None
            and (
                isinstance(positions, bool)
                or not isinstance(positions, int)
                or not 1 <= positions <= 20
            )
            or pyramid_enabled is not None
            and not isinstance(pyramid_enabled, bool)
            or pyramid_fraction < 0
            or pyramid_fraction > 1
            or stale_buy_threshold < 0
            or stale_buy_threshold > 1
            or decorrelation_threshold <= 0
            or decorrelation_threshold > 1
            or max_sector_fraction <= 0
            or max_sector_fraction > 1
            or max_drawdown_pause < 0
            or max_drawdown_pause > 1
            or max_vix < 0
            or max_vix > 1000
            or market_cap_sizing not in {"NONE", "LINEAR", "SQRT", "FREE_FLOAT"}
            or swap_cost_bps < 0
            or swap_cost_bps >= 10000
            or (min_eps is not None and not min_eps.is_finite())
            or (max_debt_equity is not None and not max_debt_equity.is_finite())
            or isinstance(ltcg_hold_days, bool)
            or not isinstance(ltcg_hold_days, int)
            or not 1 <= ltcg_hold_days <= 3650
            or (vacancy_from is not None and not isinstance(vacancy_from, str))
            or (
                correlation_artifact_id is not None
                and (
                    not isinstance(correlation_artifact_id, str)
                    or not correlation_artifact_id.strip()
                )
            )
            or (
                sector_artifact_id is not None
                and (not isinstance(sector_artifact_id, str) or not sector_artifact_id.strip())
            )
            or (
                macro_artifact_id is not None
                and (not isinstance(macro_artifact_id, str) or not macro_artifact_id.strip())
            )
            or (max_vix > 0 and macro_artifact_id is None)
            or (
                market_cap_artifact_id is not None
                and (
                    not isinstance(market_cap_artifact_id, str)
                    or not market_cap_artifact_id.strip()
                )
            )
            or (market_cap_sizing != "NONE" and market_cap_artifact_id is None)
            or (
                fundamentals_artifact_id is not None
                and (
                    not isinstance(fundamentals_artifact_id, str)
                    or not fundamentals_artifact_id.strip()
                )
            )
            or (
                (min_eps is not None or max_debt_equity is not None)
                and fundamentals_artifact_id is None
            )
            or (max_sector_fraction < 1 and sector_artifact_id is None)
        ):
            raise DomainValidationError("action generation parameters are invalid")
        if pyramid_enabled is None:
            pyramid_enabled = pyramid_fraction > 0
        elif pyramid_enabled and "pyramid_fraction" not in payload:
            pyramid_fraction = _DEFAULT_PYRAMID_FRACTION
        elif not pyramid_enabled and pyramid_fraction != 0:
            raise DomainValidationError("disabled pyramid policy cannot have a fraction")
        if not pyramid_enabled:
            pyramid_fraction = Decimal(0)
        try:
            action_date = date.fromisoformat(payload["action_date"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("action_date must be an ISO date") from exc
        forward = "as_of_date" in payload
        market_date = action_date
        if forward:
            try:
                market_date = date.fromisoformat(str(payload["as_of_date"]))
            except (TypeError, ValueError) as exc:
                raise DomainValidationError("as_of_date must be an ISO date") from exc
            if market_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date() or action_date <= market_date:
                raise DomainValidationError("forward actions require a completed signal date before the target date")
            sessions = self.market.session_dates(market_date - timedelta(days=14), market_date, exchange="NSE")
            if not sessions or sessions[-1] != market_date.isoformat():
                raise DomainValidationError("as_of_date must be a completed stored NSE session")
        elif action_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("portfolio action date must be completed")
        if vacancy_from is not None:
            try:
                vacancy_date = date.fromisoformat(vacancy_from)
            except ValueError as exc:
                raise DomainValidationError("vacancy_from must be an ISO date") from exc
            if vacancy_date >= market_date:
                raise DomainValidationError("vacancy_from must precede the signal date")
        revision = self.research.runtime.revision(str(strategy_id))
        configured_settings = self.research.runtime.portfolio_policy(str(strategy_id))
        configured_positions = configured_settings["max_positions"]
        if not isinstance(configured_positions, int) or configured_positions > 20:
            raise DomainValidationError(
                "strategy portfolio policy exceeds the action position limit"
            )
        if positions is not None and positions != configured_positions:
            raise DomainValidationError("max_positions conflicts with the active strategy revision")
        positions = configured_positions
        if not isinstance(positions, int):
            raise DomainValidationError("max_positions is invalid")
        return _GenerationRequest(
            account_id=account_id,
            strategy_id=strategy_id,
            positions=positions,
            ltcg_hold_days=ltcg_hold_days,
            sector_artifact_id=sector_artifact_id,
            macro_artifact_id=macro_artifact_id,
            market_cap_artifact_id=market_cap_artifact_id,
            market_cap_sizing=market_cap_sizing,
            fundamentals_artifact_id=fundamentals_artifact_id,
            pyramid_enabled=pyramid_enabled,
            pyramid_fraction=pyramid_fraction,
            stale_buy_threshold=stale_buy_threshold,
            decorrelation_threshold=decorrelation_threshold,
            max_sector_fraction=max_sector_fraction,
            max_drawdown_pause=max_drawdown_pause,
            max_vix=max_vix,
            swap_cost_bps=swap_cost_bps,
            min_eps=min_eps,
            max_debt_equity=max_debt_equity,
            vacancy_from=vacancy_from,
            correlation_artifact_id=correlation_artifact_id,
            action_date=action_date,
            forward=forward,
            market_date=market_date,
            vacancy_date=vacancy_date,
            revision=revision,
            configured_settings=configured_settings,
        )

    def _load_generation_inputs(self, request: _GenerationRequest) -> _GenerationInputs:
        account = next(
            (item for item in self.ledger.accounts() if item["account_id"] == request.account_id), None
        )
        if account is None:
            raise DomainValidationError("portfolio account does not exist")
        projection = self.ledger.projection(request.account_id)
        weeks = [week for week in self.research.ranking_weeks(request.strategy_id) if week <= request.market_date]
        if not weeks:
            raise DomainValidationError("no prior completed ranking is available")
        week_end = weeks[-1]
        risk_inputs = self.market.indicators_for_date(
            self.research._indicator_set("momentum", None), week_end
        )

        ranked = self.research.top_rankings(week_end, 500, request.strategy_id)
        if not ranked:
            raise DomainValidationError("prior ranking is empty")
        histories = self.market.histories(request.market_date, request.market_date)
        bars: dict[str, MarketBar] = {}
        snapshot_ids: set[str] = {str(ranked[0]["artifact_id"])}
        snapshot_ids.add(str(request.revision["revision_id"]))
        for instrument_id, (values, identity) in histories.items():
            if str(identity["isin"]).startswith("INDEX:"):
                continue
            bar = values[0]
            bars[instrument_id] = MarketBar(
                instrument_id,
                request.market_date,
                Decimal(str(bar["close"] if request.forward else bar["open"])),
                Decimal(str(bar["high"])),
                Decimal(str(bar["low"])),
                Decimal(str(bar["close"])),
            )
            snapshot_ids.add(str(bar["snapshot_id"]))
        if not bars:
            raise DomainValidationError("action date has no market bars")
        universe_snapshot_id, buy_members = self._current_buy_members()
        snapshot_ids.add(universe_snapshot_id)
        eligible = [
            item
            for item in ranked
            if Decimal(str(item["score"])) > 0 and str(item["instrument_id"]) in buy_members
        ]
        if any(str(item["instrument_id"]) not in bars for item in eligible[:request.positions]):
            raise DomainValidationError("top-ranked action candidate is missing a market bar")
        return _GenerationInputs(
            account=account,
            projection=projection,
            week_end=week_end,
            risk_inputs=risk_inputs,
            ranked=ranked,
            bars=bars,
            snapshot_ids=snapshot_ids,
            eligible=eligible,
        )

    @staticmethod
    def _risk_candidate(item, risk_inputs, multiplier=Decimal(1)):
        instrument_id = str(item["instrument_id"])
        risk = risk_inputs.get(instrument_id, {})
        atr = Decimal(str(risk.get("atrr_14", 0)))
        close = Decimal(str(risk.get("close", 0)))
        return Candidate(
            instrument_id,
            Decimal(str(item["score"])),
            multiplier,
            atr if atr > 0 else None,
            close if close > 0 else None,
        )

    @staticmethod
    def _filter_generation_sectors(request, inputs, sector_by_instrument, candidate_items):
        sector_skipped: list[dict[str, object]] = []
        if sector_by_instrument and request.max_sector_fraction < 1:
            held_sector_counts: dict[str, int] = {}
            held_instrument_ids = {lot.instrument_id for lot in inputs.projection.open_lots}
            for instrument_id in held_instrument_ids:
                sector = sector_by_instrument.get(instrument_id)
                if sector:
                    held_sector_counts[sector] = held_sector_counts.get(sector, 0) + 1
            filtered_items = []
            for item in candidate_items:
                sector = sector_by_instrument.get(str(item["instrument_id"]))
                projected = held_sector_counts.get(sector, 0) + (
                    0 if str(item["instrument_id"]) in held_instrument_ids else 1
                )
                if sector and Decimal(projected) / Decimal(request.positions) > request.max_sector_fraction:
                    sector_skipped.append(
                        {
                            "instrument_id": str(item["instrument_id"]),
                            "reason": "sector_concentration_limit",
                            "sector": sector,
                        }
                    )
                else:
                    filtered_items.append(item)
            candidate_items = filtered_items
        return candidate_items, sector_skipped

    def _generation_holdings(self, request, inputs):
        score_by_id = {str(item["instrument_id"]): Decimal(str(item["score"])) for item in inputs.ranked}
        rank_by_id = {
            str(item["instrument_id"]): int(item["rank"])
            for item in inputs.ranked
            if item.get("rank") is not None
        }
        lots_by_instrument: dict[str, tuple[int, Decimal]] = {}
        opened_by_instrument: dict[str, date] = {}
        for lot in inputs.projection.open_lots:
            units, cost = lots_by_instrument.get(lot.instrument_id, (0, Decimal(0)))
            lots_by_instrument[lot.instrument_id] = (
                units + lot.remaining_units.units,
                cost + lot.unit_cost.amount * lot.remaining_units.units,
            )
            opened_by_instrument[lot.instrument_id] = min(
                opened_by_instrument.get(lot.instrument_id, lot.opened_on), lot.opened_on
            )
        previous_risk = [
            item
            for item in self.risk_projection(request.account_id)
            if item.get("stop_model") == "ATR"
            and str(item["action_date"]) < request.action_date.isoformat()
        ]
        previous_stops = (
            {
                str(item["instrument_id"]): Decimal(str(item["current_trailing_stop"]))
                for item in previous_risk[0]["positions"]
            }
            if previous_risk
            else {}
        )
        for instrument_id in lots_by_instrument:
            if instrument_id not in previous_stops:
                raise DomainValidationError(
                    "held stock requires a persisted ATR stop before generating actions"
                )
        holdings = tuple(
            Holding(
                instrument_id,
                Quantity(units),
                Money(cost / units),
                Money(previous_stops[instrument_id]),
                score_by_id.get(instrument_id, Decimal(0)),
                opened_by_instrument[instrument_id],
            )
            for instrument_id, (units, cost) in lots_by_instrument.items()
        )
        if any(holding.instrument_id not in inputs.bars for holding in holdings):
            raise DomainValidationError("held stock is missing an action-date market bar")
        return holdings, score_by_id, rank_by_id

    def _generation_drawdown(self, request, inputs):
        drawdown_paused = False
        drawdown_value: Decimal | None = None
        if request.max_drawdown_pause > 0:
            snapshots = [
                item
                for item in self.ledger.valuations(request.account_id, 500)
                if str(item["as_of_date"]) <= request.market_date.isoformat()
            ]
            peak = Decimal(0)
            latest = None
            for snapshot in sorted(snapshots, key=lambda item: str(item["as_of_date"])):
                equity = Decimal(str(snapshot["payload"]["equity"]))
                peak = max(peak, equity)
                latest = (snapshot, (equity / peak - Decimal(1)) if peak else Decimal(0))
            if latest is not None:
                snapshot, drawdown_value = latest
                inputs.snapshot_ids.add(str(snapshot["snapshot_id"]))
                drawdown_paused = drawdown_value <= -request.max_drawdown_pause
        return drawdown_paused, drawdown_value

    def _generation_macro(self, request, inputs):
        macro_paused = False
        vix_value: Decimal | None = None
        if request.macro_artifact_id is not None:
            try:
                _, macro_payload = self.publisher.store.read_json(
                    "reference/macro-indicators", request.macro_artifact_id
                )
                macro_date = date.fromisoformat(str(macro_payload["as_of_date"]))
                values = macro_payload["values"]
                if macro_date > request.market_date or not isinstance(values, dict):
                    raise ValueError("macro date or values")
                raw_vix = values.get("vix", values.get("VIX"))
                if raw_vix is not None:
                    vix_value = Decimal(str(raw_vix))
                    macro_paused = request.max_vix > 0 and vix_value >= request.max_vix
            except (DomainValidationError, KeyError, TypeError, ValueError) as exc:
                raise DomainValidationError("macro artifact is missing or malformed") from exc
            inputs.snapshot_ids.add(str(request.macro_artifact_id))
        return macro_paused, vix_value

    def _select_generation_candidates(
        self, request: _GenerationRequest, inputs: _GenerationInputs
    ) -> _GenerationSelection:
        stale_buy_skipped: list[dict[str, object]] = []
        drawdown_paused, drawdown_value = self._generation_drawdown(request, inputs)
        sector_by_instrument = self._sector_reference(request.sector_artifact_id)
        if request.sector_artifact_id is not None:
            inputs.snapshot_ids.add(str(request.sector_artifact_id))
        macro_paused, vix_value = self._generation_macro(request, inputs)
        cap_by_instrument = self._capitalization_reference(request.market_cap_artifact_id, request.market_date, request.market_cap_sizing)
        if request.market_cap_artifact_id is not None:
            inputs.snapshot_ids.add(str(request.market_cap_artifact_id))
        fundamentals_by_instrument = self._fundamentals_reference(request.fundamentals_artifact_id, request.market_date)
        if request.fundamentals_artifact_id is not None:
            inputs.snapshot_ids.add(str(request.fundamentals_artifact_id))
        cap_median = (
            sorted(cap_by_instrument.values())[len(cap_by_instrument) // 2]
            if cap_by_instrument
            else Decimal(1)
        )

        def size_multiplier(instrument_id: str) -> Decimal:
            if request.market_cap_sizing == "NONE" or instrument_id not in cap_by_instrument:
                return Decimal(1)
            ratio = cap_by_instrument[instrument_id] / cap_median
            if request.market_cap_sizing == "SQRT":
                ratio = ratio.sqrt()
            return min(Decimal(2), max(Decimal("0.5"), ratio))

        candidate_items = []
        for item in inputs.eligible:
            instrument_id = str(item["instrument_id"])
            if instrument_id not in inputs.bars:
                continue
            if request.market_cap_sizing != "NONE" and instrument_id not in cap_by_instrument:
                continue
            fundamental = (
                fundamentals_by_instrument.get(instrument_id)
                if request.fundamentals_artifact_id is not None
                else None
            )
            if request.fundamentals_artifact_id is not None and (
                fundamental is None
                or request.min_eps is not None
                and ("eps" not in fundamental or fundamental["eps"] < request.min_eps)
                or request.max_debt_equity is not None
                and (
                    "debt_equity" not in fundamental or fundamental["debt_equity"] > request.max_debt_equity
                )
            ):
                continue
            if request.vacancy_from is not None:
                signal_bars = self.market.bars(instrument_id, request.vacancy_date, request.vacancy_date, limit=2)
                signal_close = Decimal(str(signal_bars[0]["close"])) if signal_bars else None
                if signal_close is None or inputs.bars[instrument_id].open > signal_close * (
                    Decimal(1) + request.stale_buy_threshold
                ):
                    stale_buy_skipped.append(
                        {
                            "instrument_id": instrument_id,
                            "reason": "stale_buy_above_signal_threshold",
                        }
                    )
                    continue
            candidate_items.append(item)
        candidate_items, sector_skipped = self._filter_generation_sectors(
            request, inputs, sector_by_instrument, candidate_items
        )
        if drawdown_paused or macro_paused:
            candidate_items = []
        candidates = tuple(
            self._risk_candidate(item, inputs.risk_inputs, size_multiplier(str(item["instrument_id"])))
            for item in candidate_items
        )
        holdings, score_by_id, rank_by_id = self._generation_holdings(request, inputs)
        correlation_matrix: dict[str, dict[str, object]] = {}
        if request.correlation_artifact_id is not None:
            try:
                _, correlation_payload = self.publisher.store.read_json(
                    "research/correlations", request.correlation_artifact_id
                )
                correlation_matrix = correlation_payload["matrix"]
            except (DomainValidationError, KeyError, TypeError) as exc:
                raise DomainValidationError("correlation artifact is missing or malformed") from exc
        decorrelation_skipped: list[dict[str, object]] = []
        if correlation_matrix:
            held_ids = {holding.instrument_id for holding in holdings}
            filtered_items = []
            for item in candidate_items:
                instrument_id = str(item["instrument_id"])
                correlated = any(
                    abs(float(correlation_matrix.get(instrument_id, {}).get(held_id, 0)))
                    >= float(request.decorrelation_threshold)
                    for held_id in held_ids
                )
                if correlated:
                    decorrelation_skipped.append(
                        {
                            "instrument_id": instrument_id,
                            "reason": "correlated_with_existing_holding",
                        }
                    )
                else:
                    filtered_items.append(item)
            candidate_items = filtered_items
            candidates = tuple(
                self._risk_candidate(item, inputs.risk_inputs, size_multiplier(str(item["instrument_id"])))
                for item in candidate_items
            )
        return _GenerationSelection(
            stale_buy_skipped=stale_buy_skipped,
            sector_skipped=sector_skipped,
            drawdown_paused=drawdown_paused,
            drawdown_value=drawdown_value,
            macro_paused=macro_paused,
            vix_value=vix_value,
            decorrelation_skipped=decorrelation_skipped,
            candidates=candidates,
            holdings=holdings,
            score_by_id=score_by_id,
            rank_by_id=rank_by_id,
        )

    def _evaluate_generation(
        self, request: _GenerationRequest, inputs: _GenerationInputs,
        selection: _GenerationSelection,
    ) -> _GenerationEvaluation:
        settings = request.configured_settings
        policy = PortfolioPolicy(
            request.positions,
            Decimal(str(settings["exit_threshold"])),
            max_position_fraction=min(
                Decimal(1) / Decimal(request.positions),
                Decimal(str(settings["max_concentration_pct"])),
            ),
            swap_buffer=Decimal(str(settings["buffer_percent"])),
            pyramid_fraction=request.pyramid_fraction,
            ltcg_hold_days=request.ltcg_hold_days,
            swap_cost_bps=request.swap_cost_bps,
        )
        decisions, resulting_state = evaluate(
            PortfolioState(inputs.projection.cash, selection.holdings),
            policy,
            selection.candidates,
            inputs.bars,
            score_candidates=tuple(self._risk_candidate(item, inputs.risk_inputs) for item in inputs.ranked),
        )
        identities = {
            item.instrument_id: self.market.instrument_by_id(item.instrument_id)
            for item in decisions
            if item.instrument_id is not None
        }
        resolved_symbols = {
            instrument_id: str(identity["symbol"])
            for instrument_id, identity in identities.items()
            if identity is not None
        }
        encoded_decisions = [
            {
                "type": item.type.value,
                "instrument_id": item.instrument_id,
                "symbol": resolved_symbols.get(item.instrument_id) if item.instrument_id else None,
                "units": item.units.units if item.units else None,
                "execution_price": str(item.execution_price.amount)
                if item.execution_price
                else None,
                "fee": str(item.fee.amount),
                "reason": item.reason,
                "score": str(selection.score_by_id[item.instrument_id])
                if item.instrument_id in selection.score_by_id
                else None,
                "rank": selection.rank_by_id.get(item.instrument_id),
            }
            for item in decisions
        ]
        return _GenerationEvaluation(
            policy=policy,
            resulting_state=resulting_state,
            encoded_decisions=encoded_decisions,
        )

    def _publish_generation(
        self, request: _GenerationRequest, inputs: _GenerationInputs,
        selection: _GenerationSelection, evaluation: _GenerationEvaluation,
    ) -> dict[str, object]:
        version = int(str(inputs.account["version"]))
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "account_id": request.account_id,
                    "version": version,
                    "strategy_id": request.strategy_id,
                    "action_date": request.action_date.isoformat(),
                    "as_of_date": request.market_date.isoformat(),
                    "pricing_basis": "latest_completed_close_estimate" if request.forward else "historical_action_open",
                    "max_positions": request.positions,
                    "pyramid_enabled": request.pyramid_enabled,
                    "pyramid_fraction": str(request.pyramid_fraction),
                    "vacancy_from": request.vacancy_from,
                    "stale_buy_threshold": str(request.stale_buy_threshold),
                    "correlation_artifact_id": request.correlation_artifact_id,
                    "decorrelation_threshold": str(request.decorrelation_threshold),
                    "ltcg_hold_days": request.ltcg_hold_days,
                    "sector_artifact_id": request.sector_artifact_id,
                    "max_sector_fraction": str(request.max_sector_fraction),
                    "max_drawdown_pause": str(request.max_drawdown_pause),
                    "sector_skipped": selection.sector_skipped,
                    "drawdown_paused": selection.drawdown_paused,
                    "drawdown": str(selection.drawdown_value) if selection.drawdown_value is not None else None,
                    "macro_artifact_id": request.macro_artifact_id,
                    "max_vix": str(request.max_vix),
                    "vix": str(selection.vix_value) if selection.vix_value is not None else None,
                    "macro_paused": selection.macro_paused,
                    "market_cap_artifact_id": request.market_cap_artifact_id,
                    "market_cap_sizing": request.market_cap_sizing,
                    "swap_cost_bps": str(request.swap_cost_bps),
                    "fundamentals_artifact_id": request.fundamentals_artifact_id,
                    "min_eps": str(request.min_eps) if request.min_eps is not None else None,
                    "max_debt_equity": str(request.max_debt_equity)
                    if request.max_debt_equity is not None
                    else None,
                    "strategy_revision_id": request.revision["revision_id"],
                    "sources": sorted(inputs.snapshot_ids),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        proposal_id = str(uuid5(NAMESPACE_URL, f"portfolio-action-proposal:{fingerprint}"))
        risk_artifact_id = str(uuid5(NAMESPACE_URL, f"portfolio-action-risk:{fingerprint}"))
        risk_projection = {
            "stop_model": "ATR",
            "risk_projection_id": risk_artifact_id,
            "account_id": request.account_id,
            "action_date": request.action_date.isoformat(),
            "source_action_revision": proposal_id,
            "positions": [
                {
                    "instrument_id": holding.instrument_id,
                    "units": holding.units.units,
                    "stop_model": "ATR",
                    "current_trailing_stop": str(holding.current_stop.amount),
                    "score": str(holding.score),
                }
                for holding in evaluation.resulting_state.holdings
            ],
        }
        if not self.publisher.catalog.has(risk_artifact_id):
            self.publisher.publish_json(
                "actions/risk-projections",
                risk_artifact_id,
                risk_projection,
                upstream_ids=tuple(sorted(inputs.snapshot_ids)),
                quality=QualityStatus.PARTIAL,
            )
        if self.publisher.catalog.has(proposal_id):
            self._recover_projection(proposal_id)
            return self.proposal(proposal_id)
        self.publisher.publish_json(
            "actions/proposals",
            proposal_id,
            {
                "proposal_id": proposal_id,
                "account_id": request.account_id,
                "strategy_id": request.strategy_id,
                "ranking_week_end": inputs.week_end.isoformat(),
                "action_date": request.action_date.isoformat(),
                "as_of_date": request.market_date.isoformat(),
                "pricing_basis": "latest_completed_close_estimate" if request.forward else "historical_action_open",
                "expected_ledger_version": version,
                "policy": {
                    "execution_policy_version": _EXECUTION_POLICY_VERSION,
                    "sell_before_buy": True,
                    "entry_timing": "next_tradable_open",
                    "cash_resize": "actual_open_with_available_cash",
                    "zero_unit_buy": "remain_pending",
                    "pyramid_enabled": request.pyramid_enabled,
                    "max_positions": request.positions,
                    "exit_score": str(request.configured_settings["exit_threshold"]),
                    "max_position_fraction": str(evaluation.policy.max_position_fraction),
                    "swap_buffer": str(evaluation.policy.swap_buffer),
                    "pyramid_fraction": str(evaluation.policy.pyramid_fraction),
                    "vacancy_advance_from": request.vacancy_from,
                    "stale_buy_threshold": str(request.stale_buy_threshold),
                    "stale_buy_skipped": selection.stale_buy_skipped,
                    "correlation_artifact_id": request.correlation_artifact_id,
                    "decorrelation_threshold": str(request.decorrelation_threshold),
                    "decorrelation_skipped": selection.decorrelation_skipped,
                    "ltcg_hold_days": request.ltcg_hold_days,
                    "sector_artifact_id": request.sector_artifact_id,
                    "max_sector_fraction": str(request.max_sector_fraction),
                    "sector_skipped": selection.sector_skipped,
                    "max_drawdown_pause": str(request.max_drawdown_pause),
                    "drawdown_paused": selection.drawdown_paused,
                    "drawdown": str(selection.drawdown_value) if selection.drawdown_value is not None else None,
                    "market_cap_artifact_id": request.market_cap_artifact_id,
                    "market_cap_sizing": request.market_cap_sizing,
                    "macro_artifact_id": request.macro_artifact_id,
                    "max_vix": str(request.max_vix),
                    "vix": str(selection.vix_value) if selection.vix_value is not None else None,
                    "macro_paused": selection.macro_paused,
                    "fundamentals_artifact_id": request.fundamentals_artifact_id,
                    "min_eps": str(request.min_eps) if request.min_eps is not None else None,
                    "max_debt_equity": str(request.max_debt_equity)
                    if request.max_debt_equity is not None
                    else None,
                },
                "strategy_revision_id": request.revision["revision_id"],
                "limitations": [
                    "portfolio execution against a completed historical bar",
                    "stop derived as 90% of FIFO unit cost; v3 trailing stops not imported",
                ],
                "decisions": evaluation.encoded_decisions,
            },
            upstream_ids=tuple(
                sorted(
                    (
                        *inputs.snapshot_ids,
                        risk_artifact_id,
                        *((request.correlation_artifact_id,) if request.correlation_artifact_id else ()),
                    )
                )
            ),
            quality=QualityStatus.PARTIAL,
        )
        self._recover_projection(proposal_id)
        return self.proposal(proposal_id) | {"risk_projection": risk_projection}

    def compare_execution_policy(self, payload: dict[str, object]) -> dict[str, object]:
        """Publish a deterministic review of a frozen v3 execution policy."""
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v3_policy"}
            or not isinstance(payload["v3_policy"], dict)
        ):
            raise DomainValidationError("execution policy parity requires a v3_policy object")
        baseline = payload["v3_policy"]
        required = set(_EXECUTION_POLICY)
        if set(baseline) != required:
            raise DomainValidationError("v3_policy must provide the complete execution policy")
        comparisons = [
            {
                "field": field,
                "v3": baseline[field],
                "v4": expected,
                "match": baseline[field] == expected,
            }
            for field, expected in _EXECUTION_POLICY.items()
        ]
        definition = json.dumps(
            {"version": _EXECUTION_POLICY_VERSION, "v3_policy": baseline},
            sort_keys=True,
            default=str,
        )
        artifact_id = str(
            uuid5(
                NAMESPACE_URL,
                "execution-policy-parity:" + hashlib.sha256(definition.encode()).hexdigest(),
            )
        )
        report = {
            "parity_artifact_id": artifact_id,
            "execution_policy_version": _EXECUTION_POLICY_VERSION,
            "v3_policy": baseline,
            "v4_policy": dict(_EXECUTION_POLICY),
            "comparisons": comparisons,
            "parity": all(bool(item["match"]) for item in comparisons),
            "read_only": True,
        }
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "actions/execution-policy-parity",
                artifact_id,
                report,
                quality=QualityStatus.PARTIAL,
            )
        return report

    def risk_projection(
        self, account_id: str, action_date: date | None = None
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        with sqlite_connection(self.database, read_only=True) as connection:
            ids = connection.execute(
                "SELECT artifact_id FROM catalog_artifacts WHERE category='actions/risk-projections' AND status='VALID'"
            ).fetchall()
        for (artifact_id,) in ids:
            manifest, payload = self.publisher.store.read_json(
                "actions/risk-projections", artifact_id
            )
            if payload.get("account_id") != account_id or (
                action_date and payload.get("action_date") != action_date.isoformat()
            ):
                continue
            results.append(
                {"artifact_id": manifest.artifact_id, "quality": manifest.quality.value, **payload}
            )
        return sorted(results, key=lambda item: str(item["action_date"]), reverse=True)[:100]

    def update_risk_projection(self, payload: dict[str, object]) -> dict[str, object]:
        required = {"account_id", "as_of_date", "updates"}
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or not isinstance(payload["updates"], list)
        ):
            raise DomainValidationError("risk update requires account, date and updates")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except ValueError as exc:
            raise DomainValidationError("risk update date must be an ISO date") from exc
        current = self.risk_projection(str(payload["account_id"]))
        if not current:
            raise DomainValidationError("no prior risk projection exists")
        previous = current[0]
        positions = {str(item["instrument_id"]): dict(item) for item in previous["positions"]}
        for update in payload["updates"]:
            if not isinstance(update, dict) or set(update) != {
                "instrument_id",
                "current_price",
                "atr",
            }:
                raise DomainValidationError("risk update entries are invalid")
            try:
                price = Decimal(str(update["current_price"]))
                atr = Decimal(str(update["atr"]))
            except InvalidOperation as exc:
                raise DomainValidationError("risk update values are invalid") from exc
            instrument_id = str(update["instrument_id"])
            if (
                instrument_id not in positions
                or not price.is_finite()
                or not atr.is_finite()
                or price <= 0
                or atr <= 0
            ):
                raise DomainValidationError("risk update values are invalid")
            proposed = price - Decimal(2) * atr
            positions[instrument_id]["current_trailing_stop"] = str(
                max(Decimal(str(positions[instrument_id]["current_trailing_stop"])), proposed)
            )
        body = {
            "stop_model": "ATR",
            "account_id": str(payload["account_id"]),
            "action_date": as_of.isoformat(),
            "source_risk_projection": previous["artifact_id"],
            "positions": list(positions.values()),
        }
        artifact_id = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()
        ).hexdigest()
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "actions/risk-projections",
                artifact_id,
                {"risk_projection_id": artifact_id, **body},
                upstream_ids=(str(previous["artifact_id"]),),
                quality=QualityStatus.PARTIAL,
            )
            self.publisher.catalog.supersede(str(previous["artifact_id"]), artifact_id)
        return {
            "artifact_id": artifact_id,
            "quality": "PARTIAL",
            "risk_projection_id": artifact_id,
            **body,
        }

    def create_manual(
        self, payload: dict[str, Any], *, source: str = "manual"
    ) -> dict[str, object]:
        """Create a reviewable manual BUY/SELL proposal without trading."""
        if source not in {"manual", "midweek_stop"}:
            raise DomainValidationError("manual action source is invalid")
        if set(payload) != {"account_id", "action_date", "entries", "reason"}:
            raise DomainValidationError("manual action requires account, date, entries and reason")
        account_id, reason, entries = payload["account_id"], payload["reason"], payload["entries"]
        if (
            not isinstance(account_id, str)
            or not account_id.strip()
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise DomainValidationError("manual action account and reason are required")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise DomainValidationError("manual action entries must contain 1..100 items")
        try:
            action_date = date.fromisoformat(str(payload["action_date"]))
        except ValueError as exc:
            raise DomainValidationError("action_date must be an ISO date") from exc
        if action_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("manual action date must be completed")
        account = next(
            (item for item in self.ledger.accounts() if item["account_id"] == account_id), None
        )
        if account is None:
            raise DomainValidationError("portfolio account does not exist")
        projection = self.ledger.projection(account_id)
        held: dict[str, int] = {}
        for lot in projection.open_lots:
            held[lot.instrument_id] = held.get(lot.instrument_id, 0) + lot.remaining_units.units
        buy_members = (
            self._current_buy_members()[1]
            if any(isinstance(entry, dict) and entry.get("side") == "BUY" for entry in entries)
            else set()
        )
        decisions: list[dict[str, object]] = []
        buy_total = Decimal(0)
        sell_total = Decimal(0)
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {
                "symbol",
                "exchange",
                "side",
                "units",
                "price",
            }:
                raise DomainValidationError("manual action entry contains invalid fields")
            symbol, exchange, side = (
                entry.get("symbol"),
                entry.get("exchange", "NSE"),
                entry.get("side"),
            )
            if (
                not isinstance(symbol, str)
                or not isinstance(exchange, str)
                or side not in {"BUY", "SELL"}
            ):
                raise DomainValidationError("manual action symbol, exchange or side is invalid")
            if (
                isinstance(entry.get("units"), bool)
                or not isinstance(entry.get("units"), int)
                or entry["units"] < 1
            ):
                raise DomainValidationError(f"manual {side} for {symbol} has invalid units")
            try:
                price = Decimal(str(entry["price"]))
            except (KeyError, ValueError):
                raise DomainValidationError(
                    f"manual {side} for {symbol} has invalid price"
                ) from None
            if not price.is_finite() or price <= 0:
                raise DomainValidationError(f"manual {side} for {symbol} has invalid price")
            identity = self.market.instrument(symbol, exchange)
            instrument_id = str(identity["instrument_id"])
            if side == "BUY" and instrument_id not in buy_members:
                raise DomainValidationError(
                    f"manual BUY for {symbol} is outside the current NSE snapshot"
                )
            if side == "BUY" and not self.market.bars(
                instrument_id, date.min, action_date - timedelta(days=1), limit=1000
            ):
                raise DomainValidationError(f"manual BUY for {symbol} lacks a required prior bar")
            if side == "SELL" and entry["units"] > held.get(instrument_id, 0):
                raise DomainValidationError(f"manual SELL for {symbol} exceeds held units")
            value = price * entry["units"]
            buy_total += value if side == "BUY" else Decimal(0)
            sell_total += value if side == "SELL" else Decimal(0)
            decisions.append(
                {
                    "type": side,
                    "instrument_id": instrument_id,
                    "symbol": symbol,
                    "units": entry["units"],
                    "execution_price": str(price),
                    "fee": "0",
                    "reason": reason,
                }
            )
        if buy_total > projection.cash.amount + sell_total:
            raise DomainValidationError("manual BUY batch exceeds available cash after sells")
        if self.risk_guard:
            self.risk_guard.validate(account_id, decisions, int(account["version"]))
        version = int(str(account["version"]))
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "account_id": account_id,
                    "action_date": action_date.isoformat(),
                    "entries": decisions,
                    "reason": reason,
                    "version": version,
                    "source": source,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        proposal_id = str(uuid5(NAMESPACE_URL, f"{source}-action-proposal:{fingerprint}"))
        if self.publisher.catalog.has(proposal_id):
            self._recover_manual_projection(proposal_id)
            return self.proposal(proposal_id)
        self.publisher.publish_json(
            "actions/manual-intents",
            proposal_id,
            {
                "proposal_id": proposal_id,
                "account_id": account_id,
                "action_date": action_date.isoformat(),
                "reason": reason,
                "source": source,
                "expected_ledger_version": version,
                "decisions": decisions,
            },
            quality=QualityStatus.PARTIAL,
        )
        timestamp = datetime.now(UTC).isoformat()
        self.proposals_store.insert_pending(
            proposal_id=proposal_id,
            account_id=account_id,
            strategy_id=source,
            action_date=action_date.isoformat(),
            ranking_week_end=action_date.isoformat(),
            expected_ledger_version=version,
            artifact_id=proposal_id,
            decisions=decisions,
            timestamp=timestamp,
            event_type="GENERATED_MANUAL",
            event_detail={"reason": reason},
        )
        return self.proposal(proposal_id)

    def generate_midweek_stop(self, payload: dict[str, object]) -> dict[str, object]:
        """The former next-open midweek stop is not a supported exit rule."""
        raise DomainValidationError(
            "Midweek next-open stop exits are disabled; use the daily hard stop 3% below the ATR stop"
        )

    def amend(self, proposal_id: str, decisions: object, reason: str) -> dict[str, object]:
        """Publish a replacement proposal; never mutate the approved artifact."""
        original = self.proposal(proposal_id)
        if original["status"] != "PENDING":
            raise DomainValidationError("only pending proposals can be amended")
        if (
            not isinstance(decisions, list)
            or not decisions
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise DomainValidationError("amendment requires decisions and operator reason")
        for item in decisions:
            if not isinstance(item, dict) or not item.get("type") or not item.get("instrument_id"):
                raise DomainValidationError("amended decision is incomplete")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "original": proposal_id,
                    "decisions": decisions,
                    "reason": reason,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        replacement_id = str(uuid5(NAMESPACE_URL, f"action-amendment:{fingerprint}"))
        if not self.publisher.catalog.has(replacement_id):
            self.publisher.publish_json(
                "actions/proposals",
                replacement_id,
                {
                    "proposal_id": replacement_id,
                    "replaces": proposal_id,
                    "account_id": original["account_id"],
                    "strategy_id": original["strategy_id"],
                    "action_date": original["action_date"],
                    "ranking_week_end": original["ranking_week_end"],
                    "expected_ledger_version": original["expected_ledger_version"],
                    "decisions": decisions,
                    "amendment_reason": reason,
                },
                upstream_ids=(str(original["artifact_id"]),),
                quality=QualityStatus.PARTIAL,
            )
        self._recover_projection(replacement_id)
        timestamp = datetime.now(UTC).isoformat()
        self.proposals_store.append_event(
            proposal_id,
            "AMENDED",
            timestamp,
            {"replacement_id": replacement_id, "reason": reason},
        )
        return self.proposal(replacement_id)

    def _recover_projection(self, proposal_id: str) -> None:
        """Complete the SQL projection if publication finished before a crash."""
        manifest, payload = self.publisher.store.read_json("actions/proposals", proposal_id)
        if manifest.artifact_id != proposal_id:
            raise DomainValidationError("action proposal artifact identity is invalid")
        timestamp = manifest.created_at
        if self.risk_guard:
            self.risk_guard.validate(
                payload["account_id"], payload["decisions"], payload["expected_ledger_version"]
            )
        self.proposals_store.recover_pending(
            proposal_id=proposal_id,
            account_id=str(payload["account_id"]),
            strategy_id=str(payload["strategy_id"]),
            action_date=str(payload["action_date"]),
            ranking_week_end=str(payload["ranking_week_end"]),
            expected_ledger_version=int(payload["expected_ledger_version"]),
            artifact_id=manifest.artifact_id,
            decisions=cast(list[dict[str, object]], payload["decisions"]),
            timestamp=timestamp,
            event_type="GENERATED",
        )

    def _recover_manual_projection(self, proposal_id: str) -> None:
        """Recover a confirmed-transaction projection after publication."""
        manifest, payload = self.publisher.store.read_json("actions/manual-intents", proposal_id)
        if manifest.artifact_id != proposal_id:
            raise DomainValidationError("manual action artifact identity is invalid")
        source = str(payload.get("source", "manual"))
        if source not in {"manual", "midweek_stop"}:
            raise DomainValidationError("manual action artifact source is invalid")
        timestamp = manifest.created_at
        self.proposals_store.recover_pending(
            proposal_id=proposal_id,
            account_id=str(payload["account_id"]),
            strategy_id=source,
            action_date=str(payload["action_date"]),
            ranking_week_end=str(payload["action_date"]),
            expected_ledger_version=int(payload["expected_ledger_version"]),
            artifact_id=manifest.artifact_id,
            decisions=cast(list[dict[str, object]], payload["decisions"]),
            timestamp=timestamp,
            event_type="GENERATED_MANUAL",
        )

    def proposal(self, proposal_id: str) -> dict[str, object]:
        return self._with_signal_scores(self.proposals_store.get(proposal_id))

    def _with_signal_scores(self, proposal: dict[str, object]) -> dict[str, object]:
        """Add ranking details to legacy proposals without mutating their artifacts."""
        strategy_id = str(proposal.get("strategy_id", ""))
        decisions = [dict(item) for item in proposal.get("decisions", [])]
        if strategy_id not in {"momentum", "positional_trend_following"} or not decisions:
            return proposal
        try:
            _, artifact = self.publisher.store.read_json(
                "actions/proposals", str(proposal["artifact_id"])
            )
            if strategy_id == "momentum":
                revision_id = str(artifact.get("strategy_revision_id", ""))
                week_end = str(proposal.get("ranking_week_end", ""))
                rows = self.research.research_store.all_rankings(revision_id, week_end)
                lookup = {
                    str(row["instrument_id"]): (row.get("score"), row.get("rank"))
                    for row in rows
                }
                for item in decisions:
                    values = lookup.get(str(item.get("instrument_id")))
                    if values is not None:
                        if item.get("score") is None and values[0] is not None:
                            item["score"] = str(values[0])
                        if item.get("rank") is None and values[1] is not None:
                            item["rank"] = values[1]
            elif artifact.get("signal_artifact_id") and self.positional_trend is not None:
                _, signals = self.publisher.store.read_json(
                    PositionalTrendJobs.CATEGORY, str(artifact["signal_artifact_id"])
                )
                lookup = {
                    str(row["instrument_id"]): row for row in signals.get("signals", [])
                }
                ranked_signal_ids = {
                    str(instrument_id): rank
                    for rank, instrument_id in enumerate(
                        signals.get("buy_candidates", []), start=1
                    )
                }
                for item in decisions:
                    row = lookup.get(str(item.get("instrument_id")))
                    if row is not None:
                        signal_rank = row.get("rank") or ranked_signal_ids.get(
                            str(item.get("instrument_id"))
                        )
                        for target, source in (
                            ("adx", "adx14"),
                            ("adtv", "adv30"),
                        ):
                            if item.get(target) is None and row.get(source) is not None:
                                item[target] = row[source]
                        if item.get("signal_rank") is None and signal_rank is not None:
                            item["signal_rank"] = signal_rank
        except (DomainValidationError, KeyError, TypeError, ValueError):
            # Old artifacts can predate stored ranks. Keep the proposal readable.
            pass
        return proposal | {"decisions": decisions}

    def proposals(
        self,
        account_id: str,
        limit: int = 50,
        action_date: date | None = None,
        strategy_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            self._with_signal_scores(proposal)
            for proposal in self.proposals_store.list_for_account(
                account_id, limit, action_date, strategy_id
            )
        ]

    def action_dates(self, account_id: str) -> list[date]:
        return self.proposals_store.action_dates(account_id)

    def events(self, proposal_id: str) -> list[dict[str, object]]:
        return self.proposals_store.events(proposal_id)

    def decide(self, proposal_id: str, action: str) -> dict[str, object]:
        if action not in {"APPROVED", "REJECTED"}:
            raise DomainValidationError("proposal decision is invalid")
        proposal = self.proposal(proposal_id)
        if proposal["status"] != "PENDING":
            raise DomainValidationError("action proposal is not pending")
        if action == "APPROVED":
            buy_ids = {
                str(item["instrument_id"])
                for item in proposal["decisions"]
                if item.get("type") in {"BUY", "PYRAMID_ADD"}
            }
            if buy_ids and not buy_ids <= self._current_buy_members()[1]:
                raise DomainValidationError(
                    "BUY proposal contains a stock outside the current NSE snapshot"
                )
        if action == "APPROVED" and self.risk_guard:
            self.risk_guard.validate(
                str(proposal["account_id"]),
                proposal["decisions"],
                int(proposal["expected_ledger_version"]),
                reservation_id=f"proposal:{proposal_id}",
                proposal_id=proposal_id,
            )
        timestamp = datetime.now(UTC).isoformat()
        self.proposals_store.transition_pending(proposal_id, action, timestamp)
        if action == "REJECTED" and self.risk_guard:
            self.risk_guard.release(f"proposal:{proposal_id}")
        return self.proposal(proposal_id)

    def decide_stock(self, proposal_id: str, decision_index: int, action: str) -> dict[str, object]:
        if action not in {"APPROVED", "REJECTED"}:
            raise DomainValidationError("proposal decision is invalid")
        proposal = self.proposal(proposal_id)
        if proposal["status"] != "PENDING":
            raise DomainValidationError("action proposal is not pending")
        decisions = cast(list[dict[str, object]], proposal["decisions"])
        statuses = cast(list[str], proposal["decision_statuses"])
        if not 0 <= decision_index < len(decisions) or statuses[decision_index] != "PENDING":
            raise DomainValidationError("proposal stock row is not pending")
        decision = decisions[decision_index]
        reservation_id = f"proposal:{proposal_id}:stock:{decision_index}"
        if action == "APPROVED":
            if decision.get("type") in {"BUY", "PYRAMID_ADD"}:
                _, eligible_ids = self._current_buy_members()
                if str(decision.get("instrument_id")) not in eligible_ids:
                    raise DomainValidationError("BUY proposal contains a stock outside the current NSE snapshot")
            if self.risk_guard and decision.get("type") != "NO_ACTION":
                self.risk_guard.validate(
                    str(proposal["account_id"]), [decision],
                    int(proposal["expected_ledger_version"]),
                    reservation_id=reservation_id, proposal_id=proposal_id,
                )
        timestamp = datetime.now(UTC).isoformat()
        updated = self.proposals_store.decide_stock(proposal_id, decision_index, action, timestamp)
        if action == "REJECTED" and self.risk_guard:
            self.risk_guard.release(reservation_id)
        return updated

    def process(self, proposal_id: str) -> dict[str, object]:
        proposal = self.proposal(proposal_id)
        if proposal["status"] == "PROCESSED":
            return proposal
        if proposal["status"] != "APPROVED":
            raise DomainValidationError("action proposal is not approved")
        if self.risk_guard:
            self.risk_guard.validate(
                str(proposal["account_id"]),
                proposal["decisions"],
                int(proposal["expected_ledger_version"]),
                reservation_id=f"proposal:{proposal_id}",
                proposal_id=proposal_id,
            )
        if proposal["strategy_id"] != "manual":
            raise DomainValidationError(
                "strategy and generated stop proposals require confirmed Kite or manual execution"
            )
        with sqlite_connection(self.database, read_only=True) as connection:
            artifact = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id=?",
                (proposal["artifact_id"],),
            ).fetchone()
        if artifact is None or artifact[0] != "VALID":
            raise DomainValidationError("action proposal artifact is not valid")
        action_date = date.fromisoformat(str(proposal["action_date"]))
        executed_at = datetime.combine(action_date, time(9, 15), tzinfo=ZoneInfo("Asia/Kolkata"))
        fills = []
        adjustments: list[dict[str, object]] = []
        cash_available = self.ledger.projection(str(proposal["account_id"])).cash.amount
        decisions = [decision for decision, state in zip(
            cast(list[dict[str, object]], proposal["decisions"]),
            cast(list[str], proposal["decision_statuses"]), strict=True,
        ) if state == "APPROVED"]
        if not decisions:
            raise DomainValidationError("proposal has no approved stock decisions")
        ordered_decisions = sorted(
            decisions,
            key=lambda item: 0 if item["type"] not in {value.value for value in _BUY_TYPES} else 1,
        )
        for item in ordered_decisions:
            decision_type = DecisionType(item["type"])
            if decision_type == DecisionType.NO_ACTION:
                continue
            if not item["instrument_id"] or item["units"] is None:
                raise DomainValidationError("priced action decision is incomplete")
            units = int(str(item["units"]))
            price = Decimal(str(item["execution_price"]))
            fee_per_unit = Decimal(str(item["fee"])) / units
            if decision_type in _BUY_TYPES:
                affordable = (
                    int((cash_available / (price + fee_per_unit)).to_integral_value())
                    if price + fee_per_unit > 0
                    else 0
                )
                if affordable < units:
                    adjustments.append(
                        {
                            "instrument_id": item["instrument_id"],
                            "requested_units": units,
                            "executed_units": affordable,
                            "reason": "cash_constrained_at_approval",
                        }
                    )
                    units = affordable
                if units < 1:
                    continue
                cash_available -= price * units + fee_per_unit * units
            else:
                cash_available += price * units - Decimal(str(item["fee"]))
            fills.append(
                Fill(
                    str(item["instrument_id"]),
                    action_date,
                    FillSide.BUY if decision_type in _BUY_TYPES else FillSide.SELL,
                    Quantity(units),
                    Money(price),
                    Money(fee_per_unit * units),
                    executed_at,
                    proposal_id,
                )
            )
        resulting_version = (
            self.ledger.record_fills(
                str(proposal["account_id"]),
                f"portfolio-proposal:{proposal_id}",
                int(str(proposal["expected_ledger_version"])),
                tuple(fills),
            )
            if fills
            else int(str(proposal["expected_ledger_version"]))
        )
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not fills:
                current = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM ledger_events WHERE account_id=?",
                    (proposal["account_id"],),
                ).fetchone()[0]
                if current != resulting_version:
                    raise DomainValidationError("stale ledger version")
            changed = self.proposals_store.mark_processed(
                connection, proposal_id, resulting_version, timestamp, adjustments
            )
            if not changed:
                return self.proposal(proposal_id)
        if self.risk_guard:
            self.risk_guard.release(f"proposal:{proposal_id}")
        return self.proposal(proposal_id)
