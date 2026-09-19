"""Replay prior-week v4 rankings against later daily bars without broker writes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from src.application.corporate_actions import CorporateActions
from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.backtesting import BacktestRunManifest, BacktestStep, FillModelRevision, run
from src.platform_kernel import DomainValidationError, Money, QualityStatus
from src.portfolio_engine import Candidate, MarketBar, PortfolioPolicy, PortfolioState


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
        corporate_actions: CorporateActions | None = None,
    ) -> None:
        self.database = Path(database)
        self.market = market
        self.research = research
        self.publisher = publisher
        self.corporate_actions = corporate_actions
        migrate_sqlite(
            self.database,
            "backtest",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS backtest_runs (
                        run_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL, start_date TEXT NOT NULL,
                        end_date TEXT NOT NULL, fingerprint TEXT NOT NULL,
                        total_return TEXT NOT NULL, max_drawdown TEXT NOT NULL,
                        created_at TEXT NOT NULL)""",
                    "CREATE INDEX IF NOT EXISTS backtest_runs_dates ON backtest_runs(start_date, end_date)",
                )
            },
        )

    @staticmethod
    def _code_revision() -> str:
        source = Path(__file__).resolve().parents[1]
        digest = hashlib.sha256()
        for path in (
            source / "application" / "backtest_jobs.py",
            source / "backtesting" / "api.py",
            source / "portfolio_engine" / "api.py",
            source / "application" / "strategy_runtime.py",
            source / "indicators" / "custom" / "momentum_quality.py",
            source / "indicators" / "custom" / "relative_strength.py",
        ):
            digest.update(path.read_bytes())
        return digest.hexdigest()

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
        unsupported = set(payload) - {
            "strategy_id",
            "start_date",
            "end_date",
            "starting_cash",
            "max_positions",
            "slippage_bps",
            "fee_bps",
            "tax_bps",
            "data_basis",
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
        data_basis = payload.get("data_basis", "UNADJUSTED")
        if data_basis not in {"UNADJUSTED", "CORPORATE_ACTION_ADJUSTED"}:
            raise DomainValidationError("backtest data_basis is invalid")
        if data_basis == "CORPORATE_ACTION_ADJUSTED" and self.corporate_actions is None:
            raise DomainValidationError("corporate-action adjustment service is unavailable")
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
        if "pyramid_fraction" in payload:
            pyramid_fraction = _decimal(payload["pyramid_fraction"], "pyramid_fraction")
        else:
            pyramid_fraction = Decimal("0.5") if enable_pyramiding else Decimal(0)
        if not Decimal(0) <= pyramid_fraction <= Decimal(1):
            raise DomainValidationError("pyramid_fraction must be in [0, 1]")
        regime_schedule = payload.get("regime_schedule", [])
        if not isinstance(regime_schedule, list):
            raise DomainValidationError("regime_schedule must be a list")
        regime_by_date: dict[date, str] = {}
        for item in regime_schedule:
            if not isinstance(item, dict) or set(item) != {"date", "regime"} or item["regime"] not in {"RISK_ON", "RISK_OFF"}:
                raise DomainValidationError("regime schedule entries are invalid")
            try:
                regime_date = date.fromisoformat(str(item["date"]))
            except ValueError as exc:
                raise DomainValidationError("regime schedule date must be ISO date") from exc
            if not start <= regime_date <= end or regime_date in regime_by_date:
                raise DomainValidationError("regime schedule dates must be unique and in range")
            regime_by_date[regime_date] = str(item["regime"])
        raw_cash_flows = payload.get("cash_flows", [])
        volume_participation = _decimal(payload.get("max_volume_participation", "1"), "max_volume_participation")
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
        if (
            "max_positions" in payload
            and positions != settings["max_positions"]
        ):
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
        if slippage_bps < 0 or fee_bps < 0 or tax_bps < 0 or slippage_bps >= 10000 or fee_bps >= 10000 or tax_bps >= 10000:
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
            uuid5(NAMESPACE_URL, f"execution/fill_models:next-open:{slippage_bps}:{fee_bps}:{tax_bps}"),
            "1.0.0", slippage_bps=slippage_bps, fee_bps=fee_bps, tax_bps=tax_bps,
        )
        weeks = self.research.ranking_weeks(strategy_id)
        histories = self.market.histories(start, end)
        by_date: dict[date, dict[str, MarketBar]] = {}
        upstream_ids: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            if data_basis == "CORPORATE_ACTION_ADJUSTED":
                adjusted = self.corporate_actions.adjusted_bars(instrument_id, start, end)["bars"]
                bars = [{**raw, **value} for raw, value in zip(bars, adjusted, strict=True)]
            for bar in bars:
                day = date.fromisoformat(str(bar["as_of_date"]))
                by_date.setdefault(day, {})[instrument_id] = MarketBar(
                    instrument_id,
                    day,
                    _decimal(bar["open"], "open"),
                    _decimal(bar["high"], "high"),
                    _decimal(bar["low"], "low"),
                    _decimal(bar["close"], "close"),
                    int(str(bar["volume"])),
                )
                upstream_ids.add(str(bar["snapshot_id"]))
        if not by_date:
            raise DomainValidationError("backtest has no market sessions")
        steps: list[BacktestStep] = []
        for day in sorted(by_date):
            prior = [week for week in weeks if week < day]
            if not prior:
                raise DomainValidationError("backtest has no prior completed weekly ranking")
            week_end = prior[-1]
            ranking = self.research.all_rankings(week_end, strategy_id)
            if not ranking:
                raise DomainValidationError("backtest prior weekly ranking is empty")
            upstream_ids.add(str(ranking[0]["artifact_id"]))
            candidates = tuple(
                Candidate(str(item["instrument_id"]), _decimal(item["score"], "score"), Decimal(1))
                for item in ranking
                if str(item["instrument_id"]) in by_date[day]
            )
            if not candidates:
                raise DomainValidationError("backtest has no tradable ranked candidates")
            steps.append(BacktestStep(day, candidates, by_date[day], regime_by_date.get(day, "RISK_ON")))
        policy_payload = {
            "max_positions": max_positions,
            "exit_score": str(policy.exit_score),
            "max_position_fraction": str(policy.max_position_fraction),
            "swap_buffer": str(policy.swap_buffer),
            "strategy_revision_id": strategy_revision["revision_id"],
            "slippage_bps": str(slippage_bps),
            "fee_bps": str(fee_bps),
            "tax_bps": str(tax_bps),
            "rebalance_frequency": rebalance_frequency,
            "regime_schedule": json.dumps([{"date": day.isoformat(), "regime": regime} for day, regime in sorted(regime_by_date.items())], sort_keys=True),
            "swap_cost_bps": str(fee_bps + tax_bps),
            "check_daily_sl": check_daily_sl,
            "mid_week_buy": mid_week_buy,
            "enable_pyramiding": enable_pyramiding,
            "pyramid_fraction": str(pyramid_fraction),
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
            {"signal_timing": "close", "execution_timing": "next_tradable_open",
             "slippage_bps": str(slippage_bps), "fee_bps": str(fee_bps), "tax_bps": str(tax_bps)},
        )
        manifest = BacktestRunManifest(
            uuid4(),
            tuple(sorted(upstream_ids)),
            UUID(strategy_revision_id),
            UUID(policy_revision_id),
            fill_model.revision_id,
            "portfolio-engine-v4-1",
            steps[0].as_of_date,
            steps[-1].as_of_date,
            {
                "strategy_id": strategy_id,
                "strategy_definition_hash": self.research.runtime.revision(str(strategy_id))[
                    "definition_hash"
                ],
                "starting_cash": str(starting_cash),
                **{key: str(value) for key, value in policy_payload.items()},
                "data_basis": data_basis,
                "cash_flows": json.dumps([{"date": day.isoformat(), "amount": str(amount)} for day, amount in cash_flows], sort_keys=True),
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
        )
        artifact = self.publisher.publish_json(
            "runs/backtests",
            str(result.run_id),
            {
                **result.to_payload(),
                "limitations": [
                    f"market bars use {data_basis} basis",
                    "strategy outputs provisional; not live-trading evidence",
                ],
            },
            upstream_ids=result.upstream_ids,
            quality=QualityStatus.PARTIAL,
        )
        with sqlite_connection(self.database) as connection:
            connection.execute(
                """INSERT INTO backtest_runs
                   (run_id, artifact_id, strategy_id, start_date, end_date,
                    fingerprint, total_return, max_drawdown, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(result.run_id),
                    artifact.artifact_id,
                    strategy_id,
                    steps[0].as_of_date.isoformat(),
                    steps[-1].as_of_date.isoformat(),
                    manifest.fingerprint,
                    str(result.metrics["total_return"]),
                    str(result.metrics["max_drawdown"]),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return {
            "run_id": str(result.run_id),
            "artifact_id": artifact.artifact_id,
            "session_count": len(steps),
            "fill_count": len(result.fills),
            "metrics": {key: str(value) for key, value in result.metrics.items()},
        }

    def stress(self, payload: dict[str, Any]) -> dict[str, object]:
        """Run a bounded immutable scenario matrix for migration validation."""
        if not isinstance(payload, dict) or set(payload) != {"base", "scenarios"} or not isinstance(payload["base"], dict) or not isinstance(payload["scenarios"], list):
            raise DomainValidationError("stress command requires base and scenarios")
        scenarios = payload["scenarios"]
        if not 1 <= len(scenarios) <= 10 or any(not isinstance(item, dict) for item in scenarios):
            raise DomainValidationError("stress scenarios must contain 1..10 objects")
        names: set[str] = set()
        results: list[dict[str, object]] = []
        allowed_overrides = {
            "starting_cash", "max_positions", "slippage_bps", "fee_bps", "tax_bps", "data_basis",
            "cash_flows", "max_volume_participation", "rebalance_frequency", "regime_schedule", "check_daily_sl",
            "mid_week_buy", "enable_pyramiding", "pyramid_fraction",
        }
        for scenario in scenarios:
            if set(scenario) - ({"name"} | allowed_overrides) or not isinstance(scenario.get("name"), str) or not str(scenario["name"]).strip() or scenario["name"] in names:
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
            if not isinstance(item, dict) or set(item) != {"name", "train_start", "train_end", "test_start", "test_end"}:
                raise DomainValidationError("walk-forward windows require name and train/test dates")
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
                raise DomainValidationError("walk-forward windows must be completed and within 10 years")
            seen_names.add(name)
            windows.append({"name": name, "train_start": train_start.isoformat(), "train_end": train_end.isoformat(), "test_start": test_start.isoformat(), "test_end": test_end.isoformat()})
        definition = {"base": base, "windows": windows}
        artifact_id = str(uuid5(NAMESPACE_URL, "backtest-walk-forward:" + hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()))
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
        report = {"walk_forward_id": artifact_id, "base": base, "windows": results, "window_count": len(results), "read_only_comparison": True}
        self.publisher.publish_json("runs/backtest-walk-forward", artifact_id, report, upstream_ids=tuple(sorted(upstream_ids)), quality=QualityStatus.PARTIAL)
        return report

    def attribute(self, payload: dict[str, Any]) -> dict[str, object]:
        """Publish FIFO P&L attribution by instrument, sector, size, and factor."""
        allowed = {"run_id", "sector_artifact_id", "market_cap_artifact_id", "factor_artifact_id"}
        if not isinstance(payload, dict) or "run_id" not in payload or set(payload) - allowed:
            raise DomainValidationError("attribution requires run_id and supported classification artifacts")
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
        for field, category in (("sector_artifact_id", "reference/sectors"), ("market_cap_artifact_id", "reference/market-capitalization"), ("factor_artifact_id", f"features/{report.get('manifest', {}).get('parameters', {}).get('strategy_id', '')}")):
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
                lots.setdefault(instrument, []).append({"units": Decimal(units), "price": price, "fee_per_unit": fee / units})
                continue
            remaining = units
            for lot in lots.get(instrument, []):
                matched = min(remaining, int(lot["units"]))
                if matched < 1:
                    continue
                pnl = (price - lot["price"]) * matched - lot["fee_per_unit"] * matched - fee * Decimal(matched) / units
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
        cap_numbers = sorted(Decimal(str(value)) for value in cap_values.values()) if cap_values else []
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
        definition = {"run_id": run_id, **{key: payload.get(key) for key in sorted(allowed - {"run_id"})}}
        attribution_id = str(uuid5(NAMESPACE_URL, "backtest-attribution:" + hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()))
        result = {
            "attribution_id": attribution_id, "run_id": run_id, "basis": "FIFO closed-trade P&L; factor P&L split equally across available factors",
            "by_instrument": {key: str(value) for key, value in sorted(by_instrument.items())},
            "by_sector": {key: str(value) for key, value in sorted(by_sector.items())},
            "by_market_cap": {key: str(value) for key, value in sorted(by_market_cap.items())},
            "by_factor": {key: str(value) for key, value in sorted(by_factor.items())},
            "closed_trade_count": len(trades),
        }
        if not self.publisher.catalog.has(attribution_id):
            self.publisher.publish_json("runs/backtest-attribution", attribution_id, result, upstream_ids=tuple(sorted(upstream_ids)), quality=QualityStatus.PARTIAL)
        return result

    def runs(self, limit: int = 50) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise DomainValidationError("backtest limit must be 1..100")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def run_artifact_id(self, run_id: str) -> str:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT artifact_id FROM backtest_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("backtest run was not found")
        return str(row["artifact_id"])

    def delete_run(self, run_id: str) -> bool:
        """Remove a run from the operational index while retaining its immutable artifact."""
        with sqlite_connection(self.database) as connection:
            cursor = connection.execute("DELETE FROM backtest_runs WHERE run_id=?", (run_id,))
        if cursor.rowcount == 0:
            raise DomainValidationError("backtest run was not found")
        return True
