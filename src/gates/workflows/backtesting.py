"""Replay prior-week v4 rankings against later daily bars without broker writes."""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger("screener." + __name__)
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from src.domains.artifacts import ArtifactPublisher
from src.domains.backtesting import (
    BacktestRunManifest,
    BacktestRunStore,
    BacktestStep,
    FillModelRevision,
    run,
)
from src.domains.portfolio_engine import Candidate, MarketBar, PortfolioPolicy, PortfolioState
from src.gates.backtesting_adapter import BacktestPortfolioEngineAdapter
from src.gates.repositories import MarketRepository
from src.gates.workflows.research import ResearchJobs
from src.platform_kernel import DomainValidationError, Money, QualityStatus


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DomainValidationError(f"{field} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainValidationError(f"{field} must be numeric") from exc
    if not parsed.is_finite():
        raise DomainValidationError(f"{field} must be finite")
    return parsed


class BacktestJobs:
    def __init__(
        self,
        database: str | Path,
        market: MarketRepository,
        research: ResearchJobs,
        publisher: ArtifactPublisher,
        positional_trend=None,
    ) -> None:
        self.database = Path(database)
        self.market = market
        self.research = research
        self.publisher = publisher
        self.positional_trend = positional_trend
        self.run_store = BacktestRunStore(self.database)

    @staticmethod
    def _code_revision() -> str:
        source = Path(__file__).resolve().parents[2]
        digest = hashlib.sha256()
        for path in (
            source / "gates" / "workflows" / "backtesting.py",
            source / "domains" / "backtesting" / "simulation.py",
            source / "domains" / "portfolio_engine" / "api.py",
            source / "gates" / "strategy_runtime.py",
            source / "domains" / "indicators" / "momentum_quality.py",
            source / "domains" / "strategies" / "momentum_quality.py",
            source / "domains" / "strategies" / "positional_trend_backtest.py",
            source / "gates" / "workflows" / "positional_trend_backtest_inputs.py",
            source / "gates" / "momentum_quality.py",
            source / "domains" / "indicators" / "relative_strength.py",
        ):
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _momentum_membership_plan(self, start: date, end: date):
        """Resolve dated membership and exact observed next opens for exclusions."""
        snapshots = []
        offset = 0
        while True:
            page = self.market.list_universe_snapshots("NIFTY 500", limit=500, offset=offset)
            snapshots.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
        snapshots.sort(key=lambda row: str(row["snapshot_date"]))
        if not snapshots:
            raise DomainValidationError("Momentum replay requires a NIFTY 500 snapshot")
        # Before the first stored snapshot, use the documented earliest fallback.
        usable = [row for row in snapshots if str(row["snapshot_date"]) <= end.isoformat()]
        if not usable:
            usable = [snapshots[0]]
        members = {
            str(row["snapshot_id"]): {
                str(member["isin"])
                for member in self.market.universe_snapshot_members(
                    str(row["snapshot_id"]), limit=1000
                )
            }
            for row in usable
        }
        transitions = []
        for older, newer in pairwise(usable):
            removed = members[str(older["snapshot_id"])] - members[str(newer["snapshot_id"])]
            if removed and start <= date.fromisoformat(str(newer["snapshot_date"])) <= end:
                transitions.append((newer, removed))
        targets = []
        if transitions:
            observed = [
                date.fromisoformat(value)
                for value in self.market.nifty500_session_dates(
                    date.fromisoformat(str(transitions[0][0]["snapshot_date"])),
                    end + timedelta(days=30),
                )
            ]
            for snapshot, removed in transitions:
                decision_day = date.fromisoformat(str(snapshot["snapshot_date"]))
                target = next((day for day in observed if day > decision_day), None)
                if target is None:
                    raise DomainValidationError(
                        f"next observed NIFTY 500 session is unavailable after {decision_day}"
                    )
                targets.append((target, decision_day, str(snapshot["snapshot_id"]), removed))
        extra_date = next((target for target, _, _, _ in targets if target > end), None)
        return usable, members, targets, extra_date

    def _revision(self, category: str, identifier: str, payload: dict[str, object]) -> str:
        revision_id = str(uuid5(NAMESPACE_URL, f"{category}:{identifier}"))
        complete_payload = {"revision_id": revision_id, **payload}
        if self.publisher.catalog.has(revision_id):
            _, existing = self.publisher.store.read_json(category, revision_id)
            if existing != complete_payload:
                raise DomainValidationError("published revision conflicts with current definition")
        else:
            self.publisher.publish_json(category, revision_id, complete_payload)
        return revision_id

    def execute(self, payload: dict[str, Any]) -> dict[str, object]:
        if isinstance(payload, dict) and payload.get("strategy_id") == "positional_trend_following":
            return self._execute_positional_trend(payload)
        unsupported = set(payload) - {
            "strategy_id",
            "start_date",
            "end_date",
            "starting_cash",
            "max_positions",
            "slippage_bps",
            "fee_bps",
            "tax_bps",
            "cash_flows",
            "max_volume_participation",
            "rebalance_frequency",
            "regime_schedule",
            "check_daily_sl",
            "mid_week_buy",
            "enable_pyramiding",
            "pyramid_fraction",
        }
        if not {"strategy_id", "start_date", "end_date"}.issubset(payload) or unsupported:
            if "universe_snapshot_id" in unsupported:
                raise DomainValidationError("universe snapshot filters are no longer supported")
            raise DomainValidationError("backtest command has missing or unsupported fields")
        strategy_id = payload["strategy_id"]
        if strategy_id not in self.research.runtime.strategy_ids():
            raise DomainValidationError("backtest strategy_id is invalid")
        try:
            start = date.fromisoformat(payload["start_date"])
            end = date.fromisoformat(payload["end_date"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("backtest dates must be ISO dates") from exc
        if start > end or (end - start).days > 3650 or end >= datetime.now(UTC).date():
            raise DomainValidationError("backtest requires completed dates within 10 years")
        check_daily_sl = payload.get("check_daily_sl", True)
        if not isinstance(check_daily_sl, bool):
            raise DomainValidationError("check_daily_sl must be boolean")
        mid_week_buy = payload.get("mid_week_buy", True)
        if not isinstance(mid_week_buy, bool):
            raise DomainValidationError("mid_week_buy must be boolean")
        enable_pyramiding = payload.get("enable_pyramiding", False)
        if not isinstance(enable_pyramiding, bool):
            raise DomainValidationError("enable_pyramiding must be boolean")
        requested_pyramid_fraction = _decimal(
            payload.get("pyramid_fraction", "0.5"), "pyramid_fraction"
        )
        if not Decimal(0) <= requested_pyramid_fraction <= Decimal(1):
            raise DomainValidationError("pyramid_fraction must be in [0, 1]")
        pyramid_fraction = requested_pyramid_fraction if enable_pyramiding else Decimal(0)
        regime_schedule = payload.get("regime_schedule", [])
        if not isinstance(regime_schedule, list):
            raise DomainValidationError("regime_schedule must be a list")
        regime_by_date: dict[date, str] = {}
        for item in regime_schedule:
            if (
                not isinstance(item, dict)
                or set(item) != {"date", "regime"}
                or item["regime"] not in {"RISK_ON", "RISK_OFF"}
            ):
                raise DomainValidationError("regime schedule entries are invalid")
            try:
                regime_date = date.fromisoformat(str(item["date"]))
            except ValueError as exc:
                raise DomainValidationError("regime schedule date must be ISO date") from exc
            if not start <= regime_date <= end or regime_date in regime_by_date:
                raise DomainValidationError("regime schedule dates must be unique and in range")
            regime_by_date[regime_date] = str(item["regime"])
        raw_cash_flows = payload.get("cash_flows", [])
        volume_participation = _decimal(
            payload.get("max_volume_participation", "1"), "max_volume_participation"
        )
        rebalance_frequency = payload.get("rebalance_frequency", "DAILY")
        if rebalance_frequency not in {"DAILY", "WEEKLY", "BIWEEKLY", "MONTHLY"}:
            raise DomainValidationError("rebalance_frequency is invalid")
        if not 0 < volume_participation <= 1:
            raise DomainValidationError("max_volume_participation must be in (0, 1]")
        if not isinstance(raw_cash_flows, list):
            raise DomainValidationError("cash_flows must be a list")
        cash_flows: list[tuple[date, Decimal]] = []
        for item in raw_cash_flows:
            if not isinstance(item, dict) or set(item) != {"date", "amount"}:
                raise DomainValidationError("cash flow entries require date and amount")
            try:
                flow_date = date.fromisoformat(str(item["date"]))
            except ValueError as exc:
                raise DomainValidationError("cash flow date must be ISO date") from exc
            cash_flows.append((flow_date, _decimal(item["amount"], "cash flow amount")))
        strategy_revision = self.research.runtime.revision(str(strategy_id))
        settings = self.research.runtime.portfolio_policy(str(strategy_id))
        cash_value = payload.get("starting_cash", settings["initial_capital"])
        positions = payload.get("max_positions", settings["max_positions"])
        if "max_positions" in payload and positions != settings["max_positions"]:
            raise DomainValidationError("max_positions conflicts with the active configuration")
        starting_cash = _decimal(cash_value, "starting_cash")
        max_positions = positions
        if (
            starting_cash <= 0
            or isinstance(max_positions, bool)
            or not isinstance(max_positions, int)
            or not 1 <= max_positions <= 50
        ):
            raise DomainValidationError("backtest cash or max_positions is invalid")
        slippage_bps = _decimal(payload.get("slippage_bps", "0"), "slippage_bps")
        fee_bps = _decimal(payload.get("fee_bps", "0"), "fee_bps")
        tax_bps = _decimal(payload.get("tax_bps", "0"), "tax_bps")
        if (
            slippage_bps < 0
            or fee_bps < 0
            or tax_bps < 0
            or slippage_bps >= 10000
            or fee_bps >= 10000
            or tax_bps >= 10000
        ):
            raise DomainValidationError("backtest execution costs are invalid")
        policy = PortfolioPolicy(
            max_positions,
            Decimal(str(settings["exit_threshold"])),
            max_position_fraction=min(
                Decimal(1) / Decimal(max_positions),
                Decimal(str(settings["max_concentration_pct"])),
            ),
            swap_buffer=Decimal(str(settings["buffer_percent"])),
            pyramid_fraction=pyramid_fraction,
            max_volume_participation=volume_participation,
            rebalance_frequency=rebalance_frequency,
            swap_cost_bps=fee_bps + tax_bps,
            check_daily_sl=check_daily_sl,
            mid_week_buy=mid_week_buy,
        )
        fill_model = FillModelRevision(
            uuid5(
                NAMESPACE_URL, f"execution/fill_models:next-open:{slippage_bps}:{fee_bps}:{tax_bps}"
            ),
            "1.0.0",
            slippage_bps=slippage_bps,
            fee_bps=fee_bps,
            tax_bps=tax_bps,
        )
        weeks = self.research.ranking_weeks(strategy_id)
        snapshots, snapshot_members, exit_targets, extra_date = self._momentum_membership_plan(
            start, end
        )
        histories = self.market.histories(start, extra_date or end)
        identity_by_id = {
            instrument_id: identity for instrument_id, (_, identity) in histories.items()
        }
        exit_events: dict[date, dict[str, dict[str, str]]] = {}
        for target, decision_day, snapshot_id, removed_isins in exit_targets:
            for instrument_id, identity in identity_by_id.items():
                if identity["exchange"] != "NSE" or str(identity["isin"]) not in removed_isins:
                    continue
                exit_events.setdefault(target, {})[instrument_id] = {
                    "decision_date": decision_day.isoformat(),
                    "universe_snapshot_id": snapshot_id,
                    "market_revision": self.market.market_history_revision(instrument_id),
                }
        membership_hash = hashlib.sha256(
            json.dumps(
                [
                    (
                        row["snapshot_id"],
                        row["snapshot_date"],
                        sorted(snapshot_members[str(row["snapshot_id"])]),
                    )
                    for row in snapshots
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        by_date: dict[date, dict[str, MarketBar]] = {}
        extra_bars: dict[str, MarketBar] = {}
        upstream_ids: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            if identity["exchange"] != "NSE":
                continue
            for bar in bars:
                day = date.fromisoformat(str(bar["as_of_date"]))
                market_bar = MarketBar(
                    instrument_id,
                    day,
                    _decimal(bar["open"], "open"),
                    _decimal(bar["high"], "high"),
                    _decimal(bar["low"], "low"),
                    _decimal(bar["close"], "close"),
                    int(str(bar["volume"])),
                )
                if day <= end:
                    by_date.setdefault(day, {})[instrument_id] = market_bar
                elif day == extra_date:
                    extra_bars[instrument_id] = market_bar
                if day <= end or day == extra_date:
                    upstream_ids.add(str(bar["snapshot_id"]))
                    if instrument_id in exit_events.get(day, {}):
                        exit_events[day][instrument_id]["price_snapshot_id"] = str(
                            bar["snapshot_id"]
                        )
        if not by_date:
            raise DomainValidationError("backtest has no market sessions")
        steps: list[BacktestStep] = []
        risk_cache: dict[date, dict[str, dict[str, object]]] = {}
        missing_atr_candidates = 0
        for day in sorted(by_date):
            prior_snapshots = [
                row for row in snapshots if str(row["snapshot_date"]) < day.isoformat()
            ]
            effective_snapshot = prior_snapshots[-1] if prior_snapshots else snapshots[0]
            active_isins = snapshot_members[str(effective_snapshot["snapshot_id"])]
            eligible_ids = {
                instrument_id
                for instrument_id, identity in identity_by_id.items()
                if identity["exchange"] == "NSE" and str(identity["isin"]) in active_isins
            }
            prior = [week for week in weeks if week < day]
            if not prior:
                raise DomainValidationError("backtest has no prior completed weekly ranking")
            week_end = prior[-1]
            if week_end not in risk_cache:
                risk_cache[week_end] = self.market.indicators_for_date(
                    self.research._indicator_set("momentum", None), week_end
                )
                if not risk_cache[week_end]:
                    raise DomainValidationError(f"ATR cache missing for completed week {week_end}")
            ranking = self.research.all_rankings(week_end, strategy_id)
            if not ranking:
                raise DomainValidationError("backtest prior weekly ranking is empty")
            upstream_ids.add(str(ranking[0]["artifact_id"]))
            candidates = tuple(
                Candidate(
                    str(item["instrument_id"]),
                    _decimal(item["score"], "score"),
                    Decimal(1),
                    _decimal(risk_cache[week_end][str(item["instrument_id"])]["atrr_14"], "ATR")
                    if float(
                        risk_cache[week_end].get(str(item["instrument_id"]), {}).get("atrr_14", 0)
                    )
                    > 0
                    else None,
                    _decimal(
                        risk_cache[week_end][str(item["instrument_id"])]["close"], "signal close"
                    )
                    if float(
                        risk_cache[week_end].get(str(item["instrument_id"]), {}).get("close", 0)
                    )
                    > 0
                    else None,
                )
                for item in ranking
                if str(item["instrument_id"]) in by_date[day]
                and str(item["instrument_id"]) in eligible_ids
            )
            if not candidates and any(
                str(item["instrument_id"]) in eligible_ids for item in ranking
            ):
                raise DomainValidationError("backtest has no tradable ranked candidates")
            missing_atr_candidates += sum(candidate.atr is None for candidate in candidates)
            steps.append(
                BacktestStep(
                    day,
                    candidates,
                    by_date[day],
                    regime_by_date.get(day, "RISK_ON"),
                    exit_events.get(day, {}),
                )
            )
        policy_payload = {
            "max_positions": max_positions,
            "exit_score": str(policy.exit_score),
            "max_position_fraction": str(policy.max_position_fraction),
            "swap_buffer": str(policy.swap_buffer),
            "strategy_revision_id": strategy_revision["revision_id"],
            "universe_membership_hash": membership_hash,
            "slippage_bps": str(slippage_bps),
            "fee_bps": str(fee_bps),
            "tax_bps": str(tax_bps),
            "rebalance_frequency": rebalance_frequency,
            "regime_schedule": json.dumps(
                [
                    {"date": day.isoformat(), "regime": regime}
                    for day, regime in sorted(regime_by_date.items())
                ],
                sort_keys=True,
            ),
            "swap_cost_bps": str(fee_bps + tax_bps),
            "check_daily_sl": check_daily_sl,
            "mid_week_buy": mid_week_buy,
            "enable_pyramiding": enable_pyramiding,
            "pyramid_fraction": str(pyramid_fraction),
            "stop_model": "weekly_friday_atr",
            "atr_multiplier": str(policy.atr_multiplier),
            "hard_stop_buffer": "0.03",
            "hard_stop_daily": True,
            "atr_inputs_hash": hashlib.sha256(
                json.dumps(
                    {
                        day.isoformat(): {
                            instrument_id: {key: row.get(key) for key in ("atrr_14", "close")}
                            for instrument_id, row in values.items()
                        }
                        for day, values in risk_cache.items()
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
        }
        strategy_revision_id = str(self.research.runtime.revision(str(strategy_id))["revision_id"])
        policy_revision_id = self._revision(
            "portfolio/policies",
            json.dumps(policy_payload, sort_keys=True),
            policy_payload,
        )
        fill_revision_id = self._revision(
            "execution/fill_models",
            f"next-open:{slippage_bps}:{fee_bps}:{tax_bps}",
            {
                "signal_timing": "close",
                "execution_timing": "next_tradable_open",
                "slippage_bps": str(slippage_bps),
                "fee_bps": str(fee_bps),
                "tax_bps": str(tax_bps),
            },
        )
        manifest = BacktestRunManifest(
            uuid4(),
            tuple(sorted(upstream_ids)),
            UUID(strategy_revision_id),
            UUID(policy_revision_id),
            fill_model.revision_id,
            "portfolio-engine-v4-2-atr",
            steps[0].as_of_date,
            steps[-1].as_of_date,
            {
                "strategy_id": strategy_id,
                "strategy_definition_hash": self.research.runtime.revision(str(strategy_id))[
                    "definition_hash"
                ],
                "starting_cash": str(starting_cash),
                **{key: str(value) for key, value in policy_payload.items()},
                "cash_flows": json.dumps(
                    [
                        {"date": day.isoformat(), "amount": str(amount)}
                        for day, amount in cash_flows
                    ],
                    sort_keys=True,
                ),
                "max_volume_participation": str(volume_participation),
            },
            self._code_revision(),
        )
        # Persist the fill-model revision under the same ID used by the replay.
        if fill_revision_id != str(fill_model.revision_id):
            raise DomainValidationError("fill-model revision identity is inconsistent")
        result = run(
            PortfolioState(Money(starting_cash)),
            policy,
            tuple(steps),
            manifest,
            fill_model,
            tuple(cash_flows),
            BacktestStep(extra_date, (), extra_bars, universe_exits=exit_events.get(extra_date, {}))
            if extra_date is not None and exit_events.get(extra_date)
            else None,
            portfolio_engine=BacktestPortfolioEngineAdapter(),
        )
        artifact = self.publisher.publish_json(
            "runs/backtests",
            str(result.run_id),
            {
                **result.to_payload(),
                "limitations": [
                    "strategy outputs provisional; not live-trading evidence",
                    f"candidate-session observations without ATR (ineligible for entry): {missing_atr_candidates}",
                ],
            },
            upstream_ids=result.upstream_ids,
            quality=QualityStatus.PARTIAL,
        )
        self.run_store.record_run(
            run_id=str(result.run_id),
            artifact_id=artifact.artifact_id,
            strategy_id=strategy_id,
            start_date=steps[0].as_of_date.isoformat(),
            end_date=steps[-1].as_of_date.isoformat(),
            fingerprint=manifest.fingerprint,
            total_return=str(result.metrics["total_return"]),
            max_drawdown=str(result.metrics["max_drawdown"]),
            created_at=datetime.now(UTC).isoformat(),
        )
        return {
            "run_id": str(result.run_id),
            "artifact_id": artifact.artifact_id,
            "session_count": len(steps),
            "fill_count": len(result.fills),
            "metrics": {key: str(value) for key, value in result.metrics.items()},
        }

    def _execute_positional_trend(self, payload: dict[str, Any]) -> dict[str, object]:
        """Replay the standalone Positional trend simulator as a normal run artifact."""
        allowed = {
            "strategy_id",
            "start_date",
            "end_date",
            "starting_cash",
            "max_positions",
            "risk_pct",
            "max_order_pct",
            "adv_participation_pct",
            "round_trip_cost_bps",
            "universe",
            "include_be",
            "enable_pyramiding",
        }
        if not {"strategy_id", "start_date", "end_date"} <= set(payload) or set(payload) - allowed:
            raise DomainValidationError("Positional trend backtest payload is incomplete or unsupported")
        if not isinstance(payload.get("enable_pyramiding", False), bool):
            raise DomainValidationError("enable_pyramiding must be boolean")
        if payload.get("enable_pyramiding", False):
            raise DomainValidationError(
                "Positional trend pyramiding is deferred; set enable_pyramiding to false"
            )
        if "include_be" in payload and not isinstance(payload["include_be"], bool):
            raise DomainValidationError("include_be must be boolean")
        universe = payload.get("universe", "SNAPSHOT_NIFTY500")
        if universe != "SNAPSHOT_NIFTY500":
            raise DomainValidationError("Positional trend universe is invalid")
        if payload.get("include_be", False):
            raise DomainValidationError("BE rows are unavailable for snapshot universe replay")
        try:
            start, end = (
                date.fromisoformat(str(payload["start_date"])),
                date.fromisoformat(str(payload["end_date"])),
            )
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("Positional trend backtest dates must be ISO dates") from exc
        if start > end or end >= datetime.now(UTC).date() or (end - start).days > 3650:
            raise DomainValidationError(
                "Positional trend backtest requires completed dates within 10 years"
            )
        if self.positional_trend is None:
            raise DomainValidationError("Positional trend service is unavailable")
        settings = self.research.runtime.portfolio_policy("positional_trend_following")
        from src.domains.strategies import (
            PositionalTrendBacktestPolicy as PositionalTrendPolicy,
        )
        from src.domains.strategies import (
            simulate_positional_trend_backtest as simulate,
        )
        from src.gates.workflows.positional_trend_backtest_inputs import (
            benchmark_price_return,
            load_snapshot_universe,
        )

        try:
            capital = float(payload.get("starting_cash", settings["initial_capital"]))
            positions = payload.get("max_positions", settings["max_positions"])
            risk = float(payload.get("risk_pct", float(settings["risk_fraction"]) * 100)) / 100
            order_cap = (
                float(payload.get("max_order_pct", float(settings["max_order_fraction"]) * 100))
                / 100
            )
            adv_cap = (
                float(
                    payload.get(
                        "adv_participation_pct", float(settings["adv_participation_fraction"]) * 100
                    )
                )
                / 100
            )
            costs = float(payload.get("round_trip_cost_bps", settings["round_trip_cost_bps"]))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("Positional trend portfolio limits must be numeric") from exc
        if (
            isinstance(positions, bool)
            or not isinstance(positions, int)
            or not 1 <= positions <= 50
        ):
            raise DomainValidationError("Positional trend max_positions must be between 1 and 50")
        policy = PositionalTrendPolicy(capital, positions, order_cap, risk, adv_cap, costs, False)
        try:
            policy.validate()
            histories, sessions, coverage = load_snapshot_universe(
                self.database, end_date=end.isoformat()
            )
            instrument_ids = tuple(histories)
            if not instrument_ids:
                raise DomainValidationError("Positional trend universe has no matched market history")
            fingerprint_end = date.fromisoformat(
                str(coverage.get("exit_only_session") or end.isoformat())
            )
            source_rows = self.market.history_snapshot_rows(
                instrument_ids, date(2021, 1, 1), fingerprint_end
            )
            market_snapshot_hash = hashlib.sha256(
                json.dumps([tuple(row) for row in source_rows], separators=(",", ":")).encode()
            ).hexdigest()
            signal_rules = self.research.runtime.signal_rules("positional_trend_following")
            result = simulate(
                histories,
                sessions,
                policy=policy,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                rules=signal_rules,
                membership_by_day=coverage.get("membership_by_day"),
            )
        except (ValueError, OSError) as exc:
            raise DomainValidationError(
                f"Positional trend backtest could not load or simulate: {exc}"
            ) from exc
        revision = self.research.runtime.revision("positional_trend_following")
        first, last = result["period"]["first_session"], result["period"]["last_session"]
        result.update(
            {
                "strategy_id": "positional_trend_following",
                "strategy_revision_id": revision["revision_id"],
                "strategy_definition_hash": revision["definition_hash"],
                "data": coverage,
                "benchmark": benchmark_price_return(self.database, first, last),
                "limitations": [
                    "earliest snapshot used only before recorded membership history",
                    "stored provider OHLCV adjustment basis",
                    "daily OHLCV cannot verify opening fill availability or upper circuits",
                    "exploratory replay; Phase 1 advancement gate is not enforced",
                    "open holdings marked to latest stored close; not forcibly sold",
                    "pyramiding disabled",
                ],
            }
        )
        performance = result["performance"]
        result["metrics"] = {
            "total_return": performance["total_return"],
            "cagr": performance["cagr"],
            "max_drawdown": performance["max_drawdown"],
            "sharpe": performance["sharpe_zero_risk_free"],
            "win_rate": performance["win_rate"],
            "profit_factor": performance["profit_factor"],
        }
        result["annual_returns"] = performance["annual_returns"]
        result["final_cash"] = result["equity_curve"][-1]["cash"]
        result["ending_equity"] = performance["final_equity"]
        result["open_position_value"] = performance["final_equity"] - result["final_cash"]
        result["open_positions"] = [
            {"symbol": symbol, "shares": holding["shares"]}
            for symbol, holding in result["open_holdings"].items()
        ]
        instrument_by_symbol = {
            symbol: instrument_id for instrument_id, (symbol, _) in histories.items()
        }
        result["fills"] = [
            {
                **fill,
                "as_of_date": fill["date"],
                "decision_type": fill["side"],
                "instrument_id": instrument_by_symbol[fill["symbol"]],
                "units": fill["shares"],
                "side": "BUY" if fill["side"] == "BUY" else "SELL",
            }
            for fill in result["fills"]
        ]
        result["trade_counts"] = {
            "buy": sum(fill["side"] == "BUY" for fill in result["fills"]),
            "sell": sum(fill["side"] == "SELL" for fill in result["fills"]),
            "pyramid": 0,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "payload": payload,
                    "revision": revision["definition_hash"],
                    "universe_sha256": coverage.get(
                        "universe_csv_sha256", coverage.get("membership_sha256")
                    ),
                    "market_snapshot_hash": market_snapshot_hash,
                    "code_hash": hashlib.sha256(
                        (
                            Path(__file__).resolve().parents[3]
                            / "src"
                            / "domains"
                            / "strategies"
                            / "positional_trend.py"
                        ).read_bytes()
                        + (
                            Path(__file__).resolve().parents[3]
                            / "src"
                            / "domains"
                            / "strategies"
                            / "positional_trend_backtest.py"
                        ).read_bytes()
                        + (
                            Path(__file__).resolve().parents[2]
                            / "gates"
                            / "workflows"
                            / "positional_trend_backtest_inputs.py"
                        ).read_bytes()
                    ).hexdigest(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        run_id = str(uuid5(NAMESPACE_URL, f"positional-trend-backtest:{fingerprint}"))
        if self.publisher.catalog.has(run_id):
            manifest, _ = self.publisher.store.read_json("runs/backtests", run_id)
            artifact_id = manifest.artifact_id
            reused = True
        else:
            artifact = self.publisher.publish_json(
                "runs/backtests",
                run_id,
                result,
                upstream_ids=(
                    str(revision["revision_id"]),
                    coverage.get("universe_csv_sha256", coverage.get("membership_sha256")),
                    market_snapshot_hash,
                ),
                quality=QualityStatus.PARTIAL,
            )
            artifact_id = artifact.artifact_id
            reused = False
        self.run_store.record_run_if_missing(
            run_id=run_id,
            artifact_id=artifact_id,
            strategy_id="positional_trend_following",
            start_date=first,
            end_date=last,
            fingerprint=fingerprint,
            total_return=str(result["performance"]["total_return"]),
            max_drawdown=str(result["performance"]["max_drawdown"]),
            created_at=datetime.now(UTC).isoformat(),
        )
        return {
            "run_id": run_id,
            "artifact_id": artifact_id,
            "strategy_id": "positional_trend_following",
            "period": result["period"],
            "performance": result["performance"],
            "data": coverage,
            "reused": reused,
        }

    def stress(self, payload: dict[str, Any]) -> dict[str, object]:
        """Run a bounded immutable scenario matrix for migration validation."""
        if (
            not isinstance(payload, dict)
            or set(payload) != {"base", "scenarios"}
            or not isinstance(payload["base"], dict)
            or not isinstance(payload["scenarios"], list)
        ):
            raise DomainValidationError("stress command requires base and scenarios")
        scenarios = payload["scenarios"]
        if not 1 <= len(scenarios) <= 10 or any(not isinstance(item, dict) for item in scenarios):
            raise DomainValidationError("stress scenarios must contain 1..10 objects")
        names: set[str] = set()
        results: list[dict[str, object]] = []
        allowed_overrides = {
            "starting_cash",
            "max_positions",
            "slippage_bps",
            "fee_bps",
            "tax_bps",
            "cash_flows",
            "max_volume_participation",
            "rebalance_frequency",
            "regime_schedule",
            "check_daily_sl",
            "mid_week_buy",
            "enable_pyramiding",
            "pyramid_fraction",
        }
        for scenario in scenarios:
            if (
                set(scenario) - ({"name"} | allowed_overrides)
                or not isinstance(scenario.get("name"), str)
                or not str(scenario["name"]).strip()
                or scenario["name"] in names
            ):
                raise DomainValidationError("stress scenario names or fields are invalid")
            names.add(str(scenario["name"]))
            command = dict(payload["base"])
            command.update({key: value for key, value in scenario.items() if key != "name"})
            results.append({"name": scenario["name"], "result": self.execute(command)})
        return {"scenario_count": len(results), "scenarios": results, "read_only_comparison": True}

    def walk_forward(self, payload: dict[str, Any]) -> dict[str, object]:
        """Run bounded rolling train/test windows as one immutable comparison."""
        if (
            not isinstance(payload, dict)
            or set(payload) != {"base", "windows"}
            or not isinstance(payload["base"], dict)
            or not isinstance(payload["windows"], list)
            or not 1 <= len(payload["windows"]) <= 20
        ):
            raise DomainValidationError("walk-forward requires base and 1..20 windows")
        base = payload["base"]
        if "strategy_id" not in base:
            raise DomainValidationError("walk-forward base requires strategy_id")
        windows: list[dict[str, object]] = []
        seen_names: set[str] = set()
        for item in payload["windows"]:
            if not isinstance(item, dict) or set(item) != {
                "name",
                "train_start",
                "train_end",
                "test_start",
                "test_end",
            }:
                raise DomainValidationError(
                    "walk-forward windows require name and train/test dates"
                )
            name = item["name"]
            if not isinstance(name, str) or not name.strip() or name in seen_names:
                raise DomainValidationError("walk-forward window names must be unique")
            try:
                train_start = date.fromisoformat(str(item["train_start"]))
                train_end = date.fromisoformat(str(item["train_end"]))
                test_start = date.fromisoformat(str(item["test_start"]))
                test_end = date.fromisoformat(str(item["test_end"]))
            except ValueError as exc:
                raise DomainValidationError("walk-forward dates must be ISO dates") from exc
            if not train_start <= train_end < test_start <= test_end:
                raise DomainValidationError("walk-forward windows must be chronological")
            if (test_end - train_start).days > 3650 or test_end >= datetime.now(UTC).date():
                raise DomainValidationError(
                    "walk-forward windows must be completed and within 10 years"
                )
            seen_names.add(name)
            windows.append(
                {
                    "name": name,
                    "train_start": train_start.isoformat(),
                    "train_end": train_end.isoformat(),
                    "test_start": test_start.isoformat(),
                    "test_end": test_end.isoformat(),
                }
            )
        definition = {"base": base, "windows": windows}
        artifact_id = str(
            uuid5(
                NAMESPACE_URL,
                "backtest-walk-forward:"
                + hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest(),
            )
        )
        if self.publisher.catalog.has(artifact_id):
            _, existing = self.publisher.store.read_json("runs/backtest-walk-forward", artifact_id)
            return existing
        results: list[dict[str, object]] = []
        upstream_ids: set[str] = set()
        for window in windows:
            command = dict(base)
            command.update({"start_date": window["test_start"], "end_date": window["test_end"]})
            result = self.execute(command)
            results.append({"window": window, "result": result})
            upstream_ids.add(str(result["artifact_id"]))
        report = {
            "walk_forward_id": artifact_id,
            "base": base,
            "windows": results,
            "window_count": len(results),
            "read_only_comparison": True,
        }
        self.publisher.publish_json(
            "runs/backtest-walk-forward",
            artifact_id,
            report,
            upstream_ids=tuple(sorted(upstream_ids)),
            quality=QualityStatus.PARTIAL,
        )
        return report

    def attribute(self, payload: dict[str, Any]) -> dict[str, object]:
        """Publish FIFO P&L attribution by instrument, sector, size, and factor."""
        allowed = {"run_id", "sector_artifact_id", "market_cap_artifact_id", "factor_artifact_id"}
        if not isinstance(payload, dict) or "run_id" not in payload or set(payload) - allowed:
            raise DomainValidationError(
                "attribution requires run_id and supported classification artifacts"
            )
        run_id = payload["run_id"]
        if not isinstance(run_id, str) or not run_id.strip():
            raise DomainValidationError("attribution run_id is invalid")
        artifact_id = self.run_artifact_id(run_id)
        _, report = self.publisher.store.read_json("runs/backtests", artifact_id)
        fills = report.get("fills", [])
        if not isinstance(fills, list):
            raise DomainValidationError("backtest fills are malformed")
        classifications: dict[str, dict[str, object]] = {}
        upstream_ids = {artifact_id}
        for field, category in (
            ("sector_artifact_id", "reference/sectors"),
            ("market_cap_artifact_id", "reference/market-capitalization"),
            (
                "factor_artifact_id",
                f"features/{report.get('manifest', {}).get('parameters', {}).get('strategy_id', '')}",
            ),
        ):
            identifier = payload.get(field)
            if identifier is None:
                continue
            if not isinstance(identifier, str) or not identifier.strip():
                raise DomainValidationError(f"{field} is invalid")
            try:
                _, snapshot = self.publisher.store.read_json(category, identifier)
                values = snapshot["values"]
                if not isinstance(values, dict):
                    raise TypeError("values")
                classifications[field] = values
                upstream_ids.add(identifier)
            except (DomainValidationError, KeyError, TypeError, ValueError) as exc:
                raise DomainValidationError(f"{field} was not found or is malformed") from exc
        if not classifications:
            raise DomainValidationError("attribution requires at least one classification artifact")
        lots: dict[str, list[dict[str, Decimal]]] = {}
        trades: list[dict[str, object]] = []
        for fill in fills:
            if not isinstance(fill, dict) or fill.get("side") not in {"BUY", "SELL"}:
                raise DomainValidationError("backtest fill is malformed")
            instrument = str(fill.get("instrument_id"))
            units = int(str(fill.get("units")))
            price = Decimal(str(fill.get("price")))
            fee = Decimal(str(fill.get("fee", "0")))
            if units < 1 or price <= 0:
                raise DomainValidationError("backtest fill values are invalid")
            if fill["side"] == "BUY":
                lots.setdefault(instrument, []).append(
                    {"units": Decimal(units), "price": price, "fee_per_unit": fee / units}
                )
                continue
            remaining = units
            for lot in lots.get(instrument, []):
                matched = min(remaining, int(lot["units"]))
                if matched < 1:
                    continue
                pnl = (
                    (price - lot["price"]) * matched
                    - lot["fee_per_unit"] * matched
                    - fee * Decimal(matched) / units
                )
                trades.append({"instrument_id": instrument, "pnl": pnl})
                lot["units"] -= matched
                remaining -= matched
                if remaining == 0:
                    break
            if remaining:
                raise DomainValidationError("sell fill exceeds FIFO buys")
        by_instrument: dict[str, Decimal] = {}
        by_sector: dict[str, Decimal] = {}
        by_market_cap: dict[str, Decimal] = {}
        by_factor: dict[str, Decimal] = {}
        cap_values = classifications.get("market_cap_artifact_id", {})
        cap_numbers = (
            sorted(Decimal(str(value)) for value in cap_values.values()) if cap_values else []
        )
        median_cap = cap_numbers[len(cap_numbers) // 2] if cap_numbers else Decimal(0)
        for trade in trades:
            instrument = str(trade["instrument_id"])
            pnl = Decimal(str(trade["pnl"]))
            by_instrument[instrument] = by_instrument.get(instrument, Decimal(0)) + pnl
            sector = classifications.get("sector_artifact_id", {}).get(instrument)
            if sector is not None:
                by_sector[str(sector)] = by_sector.get(str(sector), Decimal(0)) + pnl
            if instrument in cap_values:
                bucket = "SMALL" if Decimal(str(cap_values[instrument])) <= median_cap else "LARGE"
                by_market_cap[bucket] = by_market_cap.get(bucket, Decimal(0)) + pnl
            factor_row = classifications.get("factor_artifact_id", {}).get(instrument, {})
            factors = factor_row.get("factors", {}) if isinstance(factor_row, dict) else {}
            if isinstance(factors, dict) and factors:
                share = pnl / len(factors)
                for factor in factors:
                    by_factor[str(factor)] = by_factor.get(str(factor), Decimal(0)) + share
        definition = {
            "run_id": run_id,
            **{key: payload.get(key) for key in sorted(allowed - {"run_id"})},
        }
        attribution_id = str(
            uuid5(
                NAMESPACE_URL,
                "backtest-attribution:"
                + hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest(),
            )
        )
        result = {
            "attribution_id": attribution_id,
            "run_id": run_id,
            "basis": "FIFO closed-trade P&L; factor P&L split equally across available factors",
            "by_instrument": {key: str(value) for key, value in sorted(by_instrument.items())},
            "by_sector": {key: str(value) for key, value in sorted(by_sector.items())},
            "by_market_cap": {key: str(value) for key, value in sorted(by_market_cap.items())},
            "by_factor": {key: str(value) for key, value in sorted(by_factor.items())},
            "closed_trade_count": len(trades),
        }
        if not self.publisher.catalog.has(attribution_id):
            self.publisher.publish_json(
                "runs/backtest-attribution",
                attribution_id,
                result,
                upstream_ids=tuple(sorted(upstream_ids)),
                quality=QualityStatus.PARTIAL,
            )
        return result

    def runs(self, limit: int = 50) -> list[dict[str, object]]:
        return self.run_store.list_runs(limit)

    def run_artifact_id(self, run_id: str) -> str:
        return self.run_store.artifact_id(run_id)

    def delete_run(self, run_id: str) -> bool:
        """Remove a run from the operational index while retaining its immutable artifact."""
        return self.run_store.delete_run(run_id)
