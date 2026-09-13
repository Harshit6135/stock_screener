"""Replay prior-week v4 rankings against later daily bars without broker writes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.research_strategy1 import FORMULA_REVISION as STRATEGY1_REVISION
from src.application.research_strategy2 import FORMULA_REVISION as STRATEGY2_REVISION
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.application.strategy_configs import StrategyConfigs
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
        configs: StrategyConfigs | None = None,
    ) -> None:
        self.database = Path(database)
        self.market = market
        self.research = research
        self.publisher = publisher
        self.configs = configs
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
            source / "application" / "research_strategy1.py",
            source / "application" / "research_strategy2.py",
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
        if not {"strategy_id", "start_date", "end_date"}.issubset(payload) or set(payload) - {
            "strategy_id",
            "start_date",
            "end_date",
            "starting_cash",
            "max_positions",
        }:
            raise DomainValidationError("backtest command has missing or unsupported fields")
        strategy_id = payload["strategy_id"]
        if strategy_id not in {"strategy1", "strategy2"}:
            raise DomainValidationError("backtest strategy_id is invalid")
        try:
            start = date.fromisoformat(payload["start_date"])
            end = date.fromisoformat(payload["end_date"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("backtest dates must be ISO dates") from exc
        if start > end or (end - start).days > 365 or end >= datetime.now(UTC).date():
            raise DomainValidationError("backtest requires completed dates within 365 days")
        active_config = (
            self.configs.active(strategy_id, start) if self.configs is not None else None
        )
        settings = active_config["settings"] if active_config is not None else None
        cash_value = payload.get("starting_cash", settings["initial_capital"] if settings else None)
        positions = payload.get("max_positions", settings["max_positions"] if settings else None)
        if (
            active_config is not None
            and "max_positions" in payload
            and positions != active_config["settings"]["max_positions"]
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
        policy = PortfolioPolicy(
            max_positions,
            Decimal(str(settings["exit_threshold"])) if settings else Decimal(40),
            max_position_fraction=min(
                Decimal(1) / Decimal(max_positions),
                Decimal(str(settings["max_concentration_pct"])) if settings else Decimal(1),
            ),
            swap_buffer=Decimal(str(settings["buffer_percent"])) if settings else Decimal("0.25"),
        )
        fill_model = FillModelRevision(
            uuid5(NAMESPACE_URL, "execution/fill_models:next-open-zero-costs-v1"), "1.0.0"
        )
        weeks = self.research.ranking_weeks(strategy_id)
        histories = self.market.histories(start, end)
        by_date: dict[date, dict[str, MarketBar]] = {}
        upstream_ids: set[str] = set()
        if active_config is not None:
            upstream_ids.add(str(active_config["artifact_id"]))
        for instrument_id, (bars, identity) in histories.items():
            if str(identity["isin"]).startswith("INDEX:"):
                continue
            for bar in bars:
                day = date.fromisoformat(str(bar["as_of_date"]))
                by_date.setdefault(day, {})[instrument_id] = MarketBar(
                    instrument_id,
                    day,
                    _decimal(bar["open"], "open"),
                    _decimal(bar["high"], "high"),
                    _decimal(bar["low"], "low"),
                    _decimal(bar["close"], "close"),
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
            ranking = self.research.top_rankings(week_end, 500, strategy_id)
            if not ranking:
                raise DomainValidationError("backtest prior weekly ranking is empty")
            upstream_ids.add(str(ranking[0]["artifact_id"]))
            top_candidates = [item for item in ranking if _decimal(item["score"], "score") > 0][
                :max_positions
            ]
            if len(top_candidates) < max_positions or any(
                str(item["instrument_id"]) not in by_date[day] for item in top_candidates
            ):
                raise DomainValidationError(
                    "backtest is missing a required top-ranked candidate bar"
                )
            candidates = tuple(
                Candidate(str(item["instrument_id"]), _decimal(item["score"], "score"))
                for item in ranking
                if _decimal(item["score"], "score") > 0
                and str(item["instrument_id"]) in by_date[day]
            )
            if not candidates:
                raise DomainValidationError("backtest has no tradable ranked candidates")
            steps.append(BacktestStep(day, candidates, by_date[day]))
        policy_payload = {
            "max_positions": max_positions,
            "exit_score": str(policy.exit_score),
            "max_position_fraction": str(policy.max_position_fraction),
            "swap_buffer": str(policy.swap_buffer),
            "config_revision_id": active_config["revision_id"] if active_config else None,
        }
        strategy_revision = STRATEGY1_REVISION if strategy_id == "strategy1" else STRATEGY2_REVISION
        strategy_revision_id = self._revision(
            "strategies/revisions",
            f"{strategy_id}:{strategy_revision}",
            {
                "strategy_id": strategy_id,
                "formula_revision": strategy_revision,
                "status": "PROVISIONAL",
            },
        )
        policy_revision_id = self._revision(
            "portfolio/policies",
            json.dumps(policy_payload, sort_keys=True),
            policy_payload,
        )
        fill_revision_id = self._revision(
            "execution/fill_models",
            "next-open-zero-costs-v1",
            {"signal_timing": "close", "execution_timing": "next_tradable_open"},
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
                "strategy_formula_revision": strategy_revision,
                "starting_cash": str(starting_cash),
                **{key: str(value) for key, value in policy_payload.items()},
                "data_basis": "UNADJUSTED",
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
        )
        artifact = self.publisher.publish_json(
            "runs/backtests",
            str(result.run_id),
            {
                **result.to_payload(),
                "limitations": [
                    "unadjusted bars; corporate-action reconciliation pending",
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
