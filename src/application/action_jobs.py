"""Durable portfolio action proposals from prior rankings."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.execution_gateway import Ledger
from src.platform_kernel import DomainValidationError, Money, QualityStatus, Quantity
from src.portfolio_accounting import Fill, FillSide
from src.portfolio_engine import (
    Candidate,
    DecisionType,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)

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


class ActionJobs:
    def __init__(
        self,
        database: str | Path,
        market: MarketRepository,
        research: ResearchJobs,
        ledger: Ledger,
        publisher: ArtifactPublisher,
    ) -> None:
        self.database = Path(database)
        self.market = market
        self.research = research
        self.ledger = ledger
        self.publisher = publisher
        migrate_sqlite(
            self.database,
            "actions",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS action_proposals (
                        proposal_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL, action_date TEXT NOT NULL,
                        ranking_week_end TEXT NOT NULL, expected_ledger_version INTEGER NOT NULL,
                        status TEXT NOT NULL, artifact_id TEXT NOT NULL,
                        decision_json TEXT NOT NULL, resulting_ledger_version INTEGER,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
                    "CREATE INDEX IF NOT EXISTS action_proposals_account_date ON action_proposals(account_id, action_date)",
                    """CREATE TABLE IF NOT EXISTS action_proposal_events (
                        event_id INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL,
                        event_type TEXT NOT NULL, occurred_at TEXT NOT NULL,
                        detail_json TEXT NOT NULL,
                        FOREIGN KEY(proposal_id) REFERENCES action_proposals(proposal_id))""",
                )
            },
        )

    def generate(self, payload: dict[str, Any]) -> dict[str, object]:
        allowed_fields = {"account_id", "strategy_id", "action_date", "max_positions", "pyramid_enabled", "pyramid_fraction", "vacancy_from", "stale_buy_threshold", "correlation_artifact_id", "decorrelation_threshold", "ltcg_hold_days", "sector_artifact_id", "max_sector_fraction", "max_drawdown_pause", "macro_artifact_id", "max_vix", "market_cap_artifact_id", "market_cap_sizing", "swap_cost_bps", "fundamentals_artifact_id", "min_eps", "max_debt_equity"}
        if not isinstance(payload, dict) or not {"account_id", "strategy_id", "action_date"}.issubset(payload) or set(payload) - allowed_fields:
            raise DomainValidationError(
                "action generation requires account, strategy, date and limit"
            )
        account_id = payload["account_id"]
        strategy_id = payload["strategy_id"]
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
            max_debt_equity = None if "max_debt_equity" not in payload else Decimal(str(payload["max_debt_equity"]))
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
            or pyramid_enabled is not None and not isinstance(pyramid_enabled, bool)
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
            or (correlation_artifact_id is not None and (not isinstance(correlation_artifact_id, str) or not correlation_artifact_id.strip()))
            or (sector_artifact_id is not None and (not isinstance(sector_artifact_id, str) or not sector_artifact_id.strip()))
            or (macro_artifact_id is not None and (not isinstance(macro_artifact_id, str) or not macro_artifact_id.strip()))
            or (max_vix > 0 and macro_artifact_id is None)
            or (market_cap_artifact_id is not None and (not isinstance(market_cap_artifact_id, str) or not market_cap_artifact_id.strip()))
            or (market_cap_sizing != "NONE" and market_cap_artifact_id is None)
            or (fundamentals_artifact_id is not None and (not isinstance(fundamentals_artifact_id, str) or not fundamentals_artifact_id.strip()))
            or ((min_eps is not None or max_debt_equity is not None) and fundamentals_artifact_id is None)
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
        if action_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("portfolio action date must be completed")
        if vacancy_from is not None:
            try:
                vacancy_date = date.fromisoformat(vacancy_from)
            except ValueError as exc:
                raise DomainValidationError("vacancy_from must be an ISO date") from exc
            if vacancy_date >= action_date:
                raise DomainValidationError("vacancy_from must precede action_date")
        revision = self.research.runtime.revision(str(strategy_id))
        configured_settings = self.research.runtime.portfolio_policy(str(strategy_id))
        configured_positions = configured_settings["max_positions"]
        if not isinstance(configured_positions, int) or configured_positions > 20:
            raise DomainValidationError("strategy portfolio policy exceeds the action position limit")
        if positions is not None and positions != configured_positions:
            raise DomainValidationError("max_positions conflicts with the active strategy revision")
        positions = configured_positions
        if not isinstance(positions, int):
            raise DomainValidationError("max_positions is invalid")
        account = next(
            (item for item in self.ledger.accounts() if item["account_id"] == account_id), None
        )
        if account is None:
            raise DomainValidationError("portfolio account does not exist")
        projection = self.ledger.projection(account_id)
        weeks = [week for week in self.research.ranking_weeks(strategy_id) if week < action_date]
        if not weeks:
            raise DomainValidationError("no prior completed ranking is available")
        week_end = weeks[-1]
        ranked = self.research.top_rankings(week_end, 500, strategy_id)
        if not ranked:
            raise DomainValidationError("prior ranking is empty")
        histories = self.market.histories(action_date, action_date)
        bars: dict[str, MarketBar] = {}
        snapshot_ids: set[str] = {str(ranked[0]["artifact_id"])}
        snapshot_ids.add(str(revision["revision_id"]))
        for instrument_id, (values, identity) in histories.items():
            if str(identity["isin"]).startswith("INDEX:"):
                continue
            bar = values[0]
            bars[instrument_id] = MarketBar(
                instrument_id,
                action_date,
                Decimal(str(bar["open"])),
                Decimal(str(bar["high"])),
                Decimal(str(bar["low"])),
                Decimal(str(bar["close"])),
            )
            snapshot_ids.add(str(bar["snapshot_id"]))
        if not bars:
            raise DomainValidationError("action date has no market bars")
        eligible = [item for item in ranked if Decimal(str(item["score"])) > 0]
        if len(eligible) < positions or any(
            str(item["instrument_id"]) not in bars for item in eligible[:positions]
        ):
            raise DomainValidationError("top-ranked action candidate is missing a market bar")
        stale_buy_skipped: list[dict[str, object]] = []
        sector_skipped: list[dict[str, object]] = []
        drawdown_paused = False
        drawdown_value: Decimal | None = None
        macro_paused = False
        vix_value: Decimal | None = None
        if max_drawdown_pause > 0:
            snapshots = [
                item for item in self.ledger.valuations(account_id, 500)
                if str(item["as_of_date"]) <= action_date.isoformat()
            ]
            peak = Decimal(0)
            latest = None
            for snapshot in sorted(snapshots, key=lambda item: str(item["as_of_date"])):
                equity = Decimal(str(snapshot["payload"]["equity"]))
                peak = max(peak, equity)
                latest = (snapshot, (equity / peak - Decimal(1)) if peak else Decimal(0))
            if latest is not None:
                snapshot, drawdown_value = latest
                snapshot_ids.add(str(snapshot["snapshot_id"]))
                drawdown_paused = drawdown_value <= -max_drawdown_pause
        sector_by_instrument: dict[str, str] = {}
        if sector_artifact_id is not None:
            try:
                _, sector_payload = self.publisher.store.read_json("reference/sectors", sector_artifact_id)
                values = sector_payload["values"]
                if not isinstance(values, dict):
                    raise TypeError("values")
                sector_by_instrument = {str(key): str(value) for key, value in values.items()}
            except (DomainValidationError, KeyError, TypeError) as exc:
                raise DomainValidationError("sector artifact is missing or malformed") from exc
            snapshot_ids.add(str(sector_artifact_id))
        if macro_artifact_id is not None:
            try:
                _, macro_payload = self.publisher.store.read_json("reference/macro-indicators", macro_artifact_id)
                macro_date = date.fromisoformat(str(macro_payload["as_of_date"]))
                values = macro_payload["values"]
                if macro_date > action_date or not isinstance(values, dict):
                    raise ValueError("macro date or values")
                raw_vix = values.get("vix", values.get("VIX"))
                if raw_vix is not None:
                    vix_value = Decimal(str(raw_vix))
                    macro_paused = max_vix > 0 and vix_value >= max_vix
            except (DomainValidationError, KeyError, TypeError, ValueError) as exc:
                raise DomainValidationError("macro artifact is missing or malformed") from exc
            snapshot_ids.add(str(macro_artifact_id))
        cap_by_instrument: dict[str, Decimal] = {}
        if market_cap_artifact_id is not None:
            try:
                _, cap_payload = self.publisher.store.read_json("reference/market-capitalization", market_cap_artifact_id)
                cap_date = date.fromisoformat(str(cap_payload["as_of_date"]))
                values = cap_payload["values"]
                if cap_date > action_date or not isinstance(values, dict):
                    raise ValueError("capitalization date or values")
                if market_cap_sizing == "FREE_FLOAT" and any(not isinstance(value, dict) or set(value) != {"market_cap", "free_float"} for value in values.values()):
                    raise ValueError("free-float values")
                cap_by_instrument = {
                    str(key): Decimal(str(value["market_cap"])) * Decimal(str(value["free_float"]))
                    if market_cap_sizing == "FREE_FLOAT" and isinstance(value, dict) and set(value) == {"market_cap", "free_float"}
                    else Decimal(str(value["market_cap"])) if isinstance(value, dict) and "market_cap" in value
                    else Decimal(str(value))
                    for key, value in values.items()
                }
                if not cap_by_instrument or any(not value.is_finite() or value <= 0 for value in cap_by_instrument.values()):
                    raise ValueError("capitalization values")
            except (DomainValidationError, KeyError, TypeError, ValueError) as exc:
                raise DomainValidationError("market-cap artifact is missing or malformed") from exc
            snapshot_ids.add(str(market_cap_artifact_id))
        fundamentals_by_instrument: dict[str, dict[str, Decimal]] = {}
        if fundamentals_artifact_id is not None:
            try:
                _, fundamental_payload = self.publisher.store.read_json("reference/fundamentals", fundamentals_artifact_id)
                fundamental_date = date.fromisoformat(str(fundamental_payload["as_of_date"]))
                values = fundamental_payload["values"]
                if fundamental_date > action_date or not isinstance(values, dict):
                    raise ValueError("fundamentals date or values")
                for instrument_id, value in values.items():
                    if not isinstance(value, dict):
                        raise TypeError("fundamental row")
                    fundamentals_by_instrument[str(instrument_id)] = {field: Decimal(str(raw)) for field, raw in value.items()}
                if not fundamentals_by_instrument:
                    raise ValueError("empty fundamentals")
            except (DomainValidationError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise DomainValidationError("fundamentals artifact is missing or malformed") from exc
            snapshot_ids.add(str(fundamentals_artifact_id))
        cap_median = sorted(cap_by_instrument.values())[len(cap_by_instrument) // 2] if cap_by_instrument else Decimal(1)
        def size_multiplier(instrument_id: str) -> Decimal:
            if market_cap_sizing == "NONE" or instrument_id not in cap_by_instrument:
                return Decimal(1)
            ratio = cap_by_instrument[instrument_id] / cap_median
            if market_cap_sizing == "SQRT":
                ratio = ratio.sqrt()
            return min(Decimal(2), max(Decimal("0.5"), ratio))
        candidate_items = []
        for item in eligible:
            instrument_id = str(item["instrument_id"])
            if instrument_id not in bars:
                continue
            if market_cap_sizing != "NONE" and instrument_id not in cap_by_instrument:
                continue
            fundamental = fundamentals_by_instrument.get(instrument_id) if fundamentals_artifact_id is not None else None
            if fundamentals_artifact_id is not None and (
                fundamental is None
                or min_eps is not None and ("eps" not in fundamental or fundamental["eps"] < min_eps)
                or max_debt_equity is not None and ("debt_equity" not in fundamental or fundamental["debt_equity"] > max_debt_equity)
            ):
                continue
            if vacancy_from is not None:
                signal_bars = self.market.bars(instrument_id, vacancy_date, vacancy_date, limit=2)
                signal_close = Decimal(str(signal_bars[0]["close"])) if signal_bars else None
                if signal_close is None or bars[instrument_id].open > signal_close * (Decimal(1) + stale_buy_threshold):
                    stale_buy_skipped.append({"instrument_id": instrument_id, "reason": "stale_buy_above_signal_threshold"})
                    continue
            candidate_items.append(item)
        if sector_by_instrument and max_sector_fraction < 1:
            held_sector_counts: dict[str, int] = {}
            held_instrument_ids = {lot.instrument_id for lot in projection.open_lots}
            for instrument_id in held_instrument_ids:
                sector = sector_by_instrument.get(instrument_id)
                if sector:
                    held_sector_counts[sector] = held_sector_counts.get(sector, 0) + 1
            filtered_items = []
            for item in candidate_items:
                sector = sector_by_instrument.get(str(item["instrument_id"]))
                projected = held_sector_counts.get(sector, 0) + (0 if str(item["instrument_id"]) in held_instrument_ids else 1)
                if sector and Decimal(projected) / Decimal(positions) > max_sector_fraction:
                    sector_skipped.append({"instrument_id": str(item["instrument_id"]), "reason": "sector_concentration_limit", "sector": sector})
                else:
                    filtered_items.append(item)
            candidate_items = filtered_items
        if drawdown_paused or macro_paused:
            candidate_items = []
        candidates = tuple(Candidate(str(item["instrument_id"]), Decimal(str(item["score"])), size_multiplier(str(item["instrument_id"]))) for item in candidate_items)
        score_by_id = {str(item["instrument_id"]): Decimal(str(item["score"])) for item in ranked}
        lots_by_instrument: dict[str, tuple[int, Decimal]] = {}
        opened_by_instrument: dict[str, date] = {}
        for lot in projection.open_lots:
            units, cost = lots_by_instrument.get(lot.instrument_id, (0, Decimal(0)))
            lots_by_instrument[lot.instrument_id] = (
                units + lot.remaining_units.units,
                cost + lot.unit_cost.amount * lot.remaining_units.units,
            )
            opened_by_instrument[lot.instrument_id] = min(
                opened_by_instrument.get(lot.instrument_id, lot.opened_on), lot.opened_on
            )
        holdings = tuple(
            Holding(
                instrument_id,
                Quantity(units),
                Money(cost / units),
                Money(cost / units * Decimal("0.9")),
                score_by_id.get(instrument_id, Decimal(0)),
                opened_by_instrument[instrument_id],
            )
            for instrument_id, (units, cost) in lots_by_instrument.items()
        )
        if any(holding.instrument_id not in bars for holding in holdings):
            raise DomainValidationError("held stock is missing an action-date market bar")
        correlation_matrix: dict[str, dict[str, object]] = {}
        if correlation_artifact_id is not None:
            try:
                _, correlation_payload = self.publisher.store.read_json("research/correlations", correlation_artifact_id)
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
                    abs(float(correlation_matrix.get(instrument_id, {}).get(held_id, 0))) >= float(decorrelation_threshold)
                    for held_id in held_ids
                )
                if correlated:
                    decorrelation_skipped.append({"instrument_id": instrument_id, "reason": "correlated_with_existing_holding"})
                else:
                    filtered_items.append(item)
            candidate_items = filtered_items
            candidates = tuple(Candidate(str(item["instrument_id"]), Decimal(str(item["score"])), size_multiplier(str(item["instrument_id"]))) for item in candidate_items)
        settings = configured_settings
        policy = PortfolioPolicy(
            positions,
            Decimal(str(settings["exit_threshold"])),
            max_position_fraction=min(
                Decimal(1) / Decimal(positions),
                Decimal(str(settings["max_concentration_pct"])),
            ),
            swap_buffer=Decimal(str(settings["buffer_percent"])),
            pyramid_fraction=pyramid_fraction,
            ltcg_hold_days=ltcg_hold_days,
            swap_cost_bps=swap_cost_bps,
        )
        decisions, resulting_state = evaluate(PortfolioState(projection.cash, holdings), policy, candidates, bars)
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
            }
            for item in decisions
        ]
        version = int(str(account["version"]))
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "account_id": account_id,
                    "version": version,
                    "strategy_id": strategy_id,
                    "action_date": action_date.isoformat(),
                    "max_positions": positions,
                    "pyramid_enabled": pyramid_enabled,
                    "pyramid_fraction": str(pyramid_fraction),
                    "vacancy_from": vacancy_from,
                    "stale_buy_threshold": str(stale_buy_threshold),
                    "correlation_artifact_id": correlation_artifact_id,
                    "decorrelation_threshold": str(decorrelation_threshold),
                    "ltcg_hold_days": ltcg_hold_days,
                    "sector_artifact_id": sector_artifact_id,
                    "max_sector_fraction": str(max_sector_fraction),
                    "max_drawdown_pause": str(max_drawdown_pause),
                    "sector_skipped": sector_skipped,
                    "drawdown_paused": drawdown_paused,
                    "drawdown": str(drawdown_value) if drawdown_value is not None else None,
                    "macro_artifact_id": macro_artifact_id,
                    "max_vix": str(max_vix),
                    "vix": str(vix_value) if vix_value is not None else None,
                    "macro_paused": macro_paused,
                    "market_cap_artifact_id": market_cap_artifact_id,
                    "market_cap_sizing": market_cap_sizing,
                    "swap_cost_bps": str(swap_cost_bps),
                    "fundamentals_artifact_id": fundamentals_artifact_id,
                    "min_eps": str(min_eps) if min_eps is not None else None,
                    "max_debt_equity": str(max_debt_equity) if max_debt_equity is not None else None,
                    "strategy_revision_id": revision["revision_id"],
                    "sources": sorted(snapshot_ids),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        proposal_id = str(uuid5(NAMESPACE_URL, f"portfolio-action-proposal:{fingerprint}"))
        risk_artifact_id = str(uuid5(NAMESPACE_URL, f"portfolio-action-risk:{fingerprint}"))
        risk_projection = {
            "risk_projection_id": risk_artifact_id,
            "account_id": account_id,
            "action_date": action_date.isoformat(),
            "source_action_revision": proposal_id,
            "positions": [
                {
                    "instrument_id": holding.instrument_id,
                    "units": holding.units.units,
                    "entry_stop": str(holding.average_price.amount * (Decimal(1) - policy.initial_stop_fraction)),
                    "current_trailing_stop": str(holding.current_stop.amount),
                    "score": str(holding.score),
                }
                for holding in resulting_state.holdings
            ],
        }
        if not self.publisher.catalog.has(risk_artifact_id):
            self.publisher.publish_json(
                "actions/risk-projections", risk_artifact_id, risk_projection,
                upstream_ids=tuple(sorted(snapshot_ids)), quality=QualityStatus.PARTIAL,
            )
        if self.publisher.catalog.has(proposal_id):
            self._recover_projection(proposal_id)
            return self.proposal(proposal_id)
        self.publisher.publish_json(
            "actions/proposals",
            proposal_id,
            {
                "proposal_id": proposal_id,
                "account_id": account_id,
                "strategy_id": strategy_id,
                "ranking_week_end": week_end.isoformat(),
                "action_date": action_date.isoformat(),
                "expected_ledger_version": version,
                "policy": {
                    "execution_policy_version": _EXECUTION_POLICY_VERSION,
                    "sell_before_buy": True,
                    "entry_timing": "next_tradable_open",
                    "cash_resize": "actual_open_with_available_cash",
                    "zero_unit_buy": "remain_pending",
                    "pyramid_enabled": pyramid_enabled,
                    "max_positions": positions,
                    "exit_score": str(settings["exit_threshold"]),
                    "max_position_fraction": str(policy.max_position_fraction),
                    "swap_buffer": str(policy.swap_buffer),
                    "pyramid_fraction": str(policy.pyramid_fraction),
                    "vacancy_advance_from": vacancy_from,
                    "stale_buy_threshold": str(stale_buy_threshold),
                    "stale_buy_skipped": stale_buy_skipped,
                    "correlation_artifact_id": correlation_artifact_id,
                    "decorrelation_threshold": str(decorrelation_threshold),
                    "decorrelation_skipped": decorrelation_skipped,
                    "ltcg_hold_days": ltcg_hold_days,
                    "sector_artifact_id": sector_artifact_id,
                    "max_sector_fraction": str(max_sector_fraction),
                    "sector_skipped": sector_skipped,
                    "max_drawdown_pause": str(max_drawdown_pause),
                    "drawdown_paused": drawdown_paused,
                    "drawdown": str(drawdown_value) if drawdown_value is not None else None,
                    "market_cap_artifact_id": market_cap_artifact_id,
                    "market_cap_sizing": market_cap_sizing,
                    "macro_artifact_id": macro_artifact_id,
                    "max_vix": str(max_vix),
                    "vix": str(vix_value) if vix_value is not None else None,
                    "macro_paused": macro_paused,
                    "fundamentals_artifact_id": fundamentals_artifact_id,
                    "min_eps": str(min_eps) if min_eps is not None else None,
                    "max_debt_equity": str(max_debt_equity) if max_debt_equity is not None else None,
                },
                "strategy_revision_id": revision["revision_id"],
                "limitations": [
                    "portfolio execution against a completed historical bar",
                    "stop derived as 90% of FIFO unit cost; v3 trailing stops not imported",
                ],
                "decisions": encoded_decisions,
            },
            upstream_ids=tuple(sorted((*snapshot_ids, risk_artifact_id, *((correlation_artifact_id,) if correlation_artifact_id else ())))),
            quality=QualityStatus.PARTIAL,
        )
        self._recover_projection(proposal_id)
        return self.proposal(proposal_id) | {"risk_projection": risk_projection}

    def compare_execution_policy(self, payload: dict[str, object]) -> dict[str, object]:
        """Publish a deterministic review of a frozen v3 execution policy."""
        if not isinstance(payload, dict) or set(payload) != {"v3_policy"} or not isinstance(payload["v3_policy"], dict):
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

    def risk_projection(self, account_id: str, action_date: date | None = None) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for manifest in self.publisher.store.manifests():
            if manifest.category != "actions/risk-projections":
                continue
            _, payload = self.publisher.store.read_json(manifest.category, manifest.artifact_id)
            if payload.get("account_id") != account_id or (action_date and payload.get("action_date") != action_date.isoformat()):
                continue
            results.append({"artifact_id": manifest.artifact_id, "quality": manifest.quality.value, **payload})
        return sorted(results, key=lambda item: str(item["action_date"]), reverse=True)[:100]

    def update_risk_projection(self, payload: dict[str, object]) -> dict[str, object]:
        required = {"account_id", "as_of_date", "updates"}
        if not isinstance(payload, dict) or set(payload) != required or not isinstance(payload["updates"], list):
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
            if not isinstance(update, dict) or set(update) != {"instrument_id", "current_price", "stop_fraction"}:
                raise DomainValidationError("risk update entries are invalid")
            try:
                price = Decimal(str(update["current_price"]))
                fraction = Decimal(str(update["stop_fraction"]))
            except InvalidOperation as exc:
                raise DomainValidationError("risk update values are invalid") from exc
            instrument_id = str(update["instrument_id"])
            if instrument_id not in positions or price <= 0 or not 0 < fraction < 1:
                raise DomainValidationError("risk update values are invalid")
            proposed = price * (Decimal(1) - fraction)
            positions[instrument_id]["current_trailing_stop"] = str(max(Decimal(str(positions[instrument_id]["current_trailing_stop"])), proposed))
        body = {"account_id": str(payload["account_id"]), "action_date": as_of.isoformat(), "source_risk_projection": previous["artifact_id"], "positions": list(positions.values())}
        artifact_id = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json("actions/risk-projections", artifact_id, {"risk_projection_id": artifact_id, **body}, upstream_ids=(str(previous["artifact_id"]),), quality=QualityStatus.PARTIAL)
            self.publisher.catalog.supersede(str(previous["artifact_id"]), artifact_id)
        return {"artifact_id": artifact_id, "quality": "PARTIAL", "risk_projection_id": artifact_id, **body}

    def create_manual(
        self, payload: dict[str, Any], *, source: str = "manual"
    ) -> dict[str, object]:
        """Create a reviewable manual BUY/SELL proposal without trading."""
        if source not in {"manual", "midweek_stop"}:
            raise DomainValidationError("manual action source is invalid")
        if set(payload) != {"account_id", "action_date", "entries", "reason"}:
            raise DomainValidationError("manual action requires account, date, entries and reason")
        account_id, reason, entries = payload["account_id"], payload["reason"], payload["entries"]
        if not isinstance(account_id, str) or not account_id.strip() or not isinstance(reason, str) or not reason.strip():
            raise DomainValidationError("manual action account and reason are required")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise DomainValidationError("manual action entries must contain 1..100 items")
        try:
            action_date = date.fromisoformat(str(payload["action_date"]))
        except ValueError as exc:
            raise DomainValidationError("action_date must be an ISO date") from exc
        if action_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("manual action date must be completed")
        account = next((item for item in self.ledger.accounts() if item["account_id"] == account_id), None)
        if account is None:
            raise DomainValidationError("portfolio account does not exist")
        projection = self.ledger.projection(account_id)
        held: dict[str, int] = {}
        for lot in projection.open_lots:
            held[lot.instrument_id] = held.get(lot.instrument_id, 0) + lot.remaining_units.units
        decisions: list[dict[str, object]] = []
        buy_total = Decimal(0)
        sell_total = Decimal(0)
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {"symbol", "exchange", "side", "units", "price"}:
                raise DomainValidationError("manual action entry contains invalid fields")
            symbol, exchange, side = entry.get("symbol"), entry.get("exchange", "NSE"), entry.get("side")
            if not isinstance(symbol, str) or not isinstance(exchange, str) or side not in {"BUY", "SELL"}:
                raise DomainValidationError("manual action symbol, exchange or side is invalid")
            if isinstance(entry.get("units"), bool) or not isinstance(entry.get("units"), int) or entry["units"] < 1:
                raise DomainValidationError(f"manual {side} for {symbol} has invalid units")
            try:
                price = Decimal(str(entry["price"]))
            except (KeyError, ValueError):
                raise DomainValidationError(f"manual {side} for {symbol} has invalid price") from None
            if not price.is_finite() or price <= 0:
                raise DomainValidationError(f"manual {side} for {symbol} has invalid price")
            identity = self.market.instrument(symbol, exchange)
            instrument_id = str(identity["instrument_id"])
            if side == "BUY" and not self.market.bars(instrument_id, date.min, action_date - timedelta(days=1), limit=1000):
                raise DomainValidationError(f"manual BUY for {symbol} lacks a required prior bar")
            if side == "SELL" and entry["units"] > held.get(instrument_id, 0):
                raise DomainValidationError(f"manual SELL for {symbol} exceeds held units")
            value = price * entry["units"]
            buy_total += value if side == "BUY" else Decimal(0)
            sell_total += value if side == "SELL" else Decimal(0)
            decisions.append({
                "type": side, "instrument_id": instrument_id, "symbol": symbol,
                "units": entry["units"], "execution_price": str(price), "fee": "0", "reason": reason,
            })
        if buy_total > projection.cash.amount + sell_total:
            raise DomainValidationError("manual BUY batch exceeds available cash after sells")
        version = int(str(account["version"]))
        fingerprint = hashlib.sha256(json.dumps({
            "account_id": account_id, "action_date": action_date.isoformat(),
            "entries": decisions, "reason": reason, "version": version, "source": source,
        }, sort_keys=True).encode()).hexdigest()
        proposal_id = str(uuid5(NAMESPACE_URL, f"{source}-action-proposal:{fingerprint}"))
        if self.publisher.catalog.has(proposal_id):
            self._recover_projection(proposal_id)
            return self.proposal(proposal_id)
        self.publisher.publish_json(
            "actions/manual-intents", proposal_id,
            {"proposal_id": proposal_id, "account_id": account_id, "action_date": action_date.isoformat(),
             "reason": reason, "source": source,
             "expected_ledger_version": version, "decisions": decisions},
            quality=QualityStatus.PARTIAL,
        )
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO action_proposals
                   (proposal_id, account_id, strategy_id, action_date, ranking_week_end,
                    expected_ledger_version, status, artifact_id, decision_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
                (proposal_id, account_id, source, action_date.isoformat(), action_date.isoformat(), version,
                 proposal_id, json.dumps(decisions, sort_keys=True), timestamp, timestamp),
            )
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json) VALUES (?, 'GENERATED_MANUAL', ?, ?)""",
                (proposal_id, timestamp, json.dumps({"reason": reason}, sort_keys=True)),
            )
        return self.proposal(proposal_id)

    def generate_midweek_stop(self, payload: dict[str, object]) -> dict[str, object]:
        """Create a reviewable next-open SELL proposal for breached stops."""
        required = {"account_id", "signal_date", "action_date", "reason"}
        if not isinstance(payload, dict) or set(payload) != required or not isinstance(payload["reason"], str) or not str(payload["reason"]).strip():
            raise DomainValidationError("midweek stop requires account, signal date, action date and reason")
        try:
            signal_date = date.fromisoformat(str(payload["signal_date"]))
            action_date = date.fromisoformat(str(payload["action_date"]))
        except ValueError as exc:
            raise DomainValidationError("midweek stop dates must be ISO dates") from exc
        if signal_date >= action_date or action_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("midweek stop requires a later completed action date")
        account_id = str(payload["account_id"])
        projection = self.ledger.projection(account_id)
        entries: list[dict[str, object]] = []
        for lot in projection.open_lots:
            signal = self.market.bars(lot.instrument_id, signal_date, signal_date, limit=2)
            opening = self.market.bars(lot.instrument_id, action_date, action_date, limit=2)
            if not signal or not opening:
                continue
            stop = lot.unit_cost.amount * Decimal("0.9")
            if Decimal(str(signal[0]["low"])) > stop:
                continue
            identity = self.market.instrument_by_id(lot.instrument_id)
            if identity is not None:
                entries.append({"symbol": identity["symbol"], "exchange": identity["exchange"], "side": "SELL", "units": lot.remaining_units.units, "price": opening[0]["open"]})
        if not entries:
            raise DomainValidationError("no held position breached its stop on the signal date")
        return self.create_manual(
            {"account_id": account_id, "action_date": action_date.isoformat(),
             "entries": entries, "reason": str(payload["reason"])},
            source="midweek_stop",
        )

    def amend(self, proposal_id: str, decisions: object, reason: str) -> dict[str, object]:
        """Publish a replacement proposal; never mutate the approved artifact."""
        original = self.proposal(proposal_id)
        if original["status"] != "PENDING":
            raise DomainValidationError("only pending proposals can be amended")
        if not isinstance(decisions, list) or not decisions or not isinstance(reason, str) or not reason.strip():
            raise DomainValidationError("amendment requires decisions and operator reason")
        for item in decisions:
            if not isinstance(item, dict) or not item.get("type") or not item.get("instrument_id"):
                raise DomainValidationError("amended decision is incomplete")
        fingerprint = hashlib.sha256(json.dumps({
            "original": proposal_id, "decisions": decisions, "reason": reason,
        }, sort_keys=True).encode()).hexdigest()
        replacement_id = str(uuid5(NAMESPACE_URL, f"action-amendment:{fingerprint}"))
        if not self.publisher.catalog.has(replacement_id):
            self.publisher.publish_json(
                "actions/proposals", replacement_id,
                {"proposal_id": replacement_id, "replaces": proposal_id,
                 "account_id": original["account_id"], "strategy_id": original["strategy_id"],
                 "action_date": original["action_date"], "ranking_week_end": original["ranking_week_end"],
                 "expected_ledger_version": original["expected_ledger_version"],
                 "decisions": decisions, "amendment_reason": reason},
                upstream_ids=(str(original["artifact_id"]),), quality=QualityStatus.PARTIAL,
            )
        self._recover_projection(replacement_id)
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO action_proposal_events(proposal_id, event_type, occurred_at, detail_json) VALUES (?, 'AMENDED', ?, ?)",
                (proposal_id, timestamp, json.dumps({"replacement_id": replacement_id, "reason": reason}, sort_keys=True)),
            )
        return self.proposal(replacement_id)

    def _recover_projection(self, proposal_id: str) -> None:
        """Complete the SQL projection if publication finished before a crash."""
        manifest, payload = self.publisher.store.read_json("actions/proposals", proposal_id)
        if manifest.artifact_id != proposal_id:
            raise DomainValidationError("action proposal artifact identity is invalid")
        timestamp = manifest.created_at
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO action_proposals
                   (proposal_id, account_id, strategy_id, action_date, ranking_week_end,
                    expected_ledger_version, status, artifact_id, decision_json,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
                (
                    proposal_id,
                    payload["account_id"],
                    payload["strategy_id"],
                    payload["action_date"],
                    payload["ranking_week_end"],
                    payload["expected_ledger_version"],
                    manifest.artifact_id,
                    json.dumps(payload["decisions"], sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] == 1:
                connection.execute(
                    """INSERT INTO action_proposal_events
                       (proposal_id, event_type, occurred_at, detail_json)
                       VALUES (?, 'GENERATED', ?, '{}')""",
                    (proposal_id, timestamp),
                )

    def proposal(self, proposal_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("action proposal was not found")
        return self._decode(row)

    @staticmethod
    def _decode(row: Any) -> dict[str, object]:
        result = dict(row)
        result["decisions"] = json.loads(result.pop("decision_json"))
        return result

    def proposals(self, account_id: str, limit: int = 50, action_date: date | None = None) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise DomainValidationError("action proposal limit must be 1..100")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM action_proposals WHERE account_id=?
                   AND (? IS NULL OR action_date=?) ORDER BY action_date DESC, created_at DESC LIMIT ?""",
                (account_id, action_date.isoformat() if action_date else None,
                 action_date.isoformat() if action_date else None, limit),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def action_dates(self, account_id: str) -> list[date]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT DISTINCT action_date FROM action_proposals WHERE account_id=? ORDER BY action_date DESC",
                (account_id,),
            ).fetchall()
        return [date.fromisoformat(str(row["action_date"])) for row in rows]

    def events(self, proposal_id: str) -> list[dict[str, object]]:
        self.proposal(proposal_id)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT event_type, occurred_at, detail_json FROM action_proposal_events
                   WHERE proposal_id=? ORDER BY event_id""",
                (proposal_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"],
                "detail": json.loads(row["detail_json"]),
            }
            for row in rows
        ]

    def decide(self, proposal_id: str, action: str) -> dict[str, object]:
        if action not in {"APPROVED", "REJECTED"}:
            raise DomainValidationError("proposal decision is invalid")
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("action proposal was not found")
            if row["status"] != "PENDING":
                raise DomainValidationError("action proposal is not pending")
            connection.execute(
                "UPDATE action_proposals SET status=?, updated_at=? WHERE proposal_id=?",
                (action, timestamp, proposal_id),
            )
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json) VALUES (?, ?, ?, '{}')""",
                (proposal_id, action, timestamp),
            )
        return self.proposal(proposal_id)

    def process(self, proposal_id: str) -> dict[str, object]:
        proposal = self.proposal(proposal_id)
        if proposal["status"] == "PROCESSED":
            return proposal
        if proposal["status"] != "APPROVED":
            raise DomainValidationError("action proposal is not approved")
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
        decisions = cast(list[dict[str, object]], proposal["decisions"])
        ordered_decisions = sorted(decisions, key=lambda item: 0 if item["type"] not in {value.value for value in _BUY_TYPES} else 1)
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
                affordable = int((cash_available / (price + fee_per_unit)).to_integral_value()) if price + fee_per_unit > 0 else 0
                if affordable < units:
                    adjustments.append({"instrument_id": item["instrument_id"], "requested_units": units, "executed_units": affordable, "reason": "cash_constrained_at_approval"})
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
            changed = connection.execute(
                """UPDATE action_proposals SET status='PROCESSED',
                   resulting_ledger_version=?, updated_at=?
                   WHERE proposal_id=? AND status='APPROVED'""",
                (resulting_version, timestamp, proposal_id),
            )
            if changed.rowcount != 1:
                return self.proposal(proposal_id)
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json)
                   VALUES (?, 'PROCESSED', ?, ?)""",
                (
                    proposal_id,
                    timestamp,
                    json.dumps({"resulting_ledger_version": resulting_version, "adjustments": adjustments}),
                ),
            )
        return self.proposal(proposal_id)
