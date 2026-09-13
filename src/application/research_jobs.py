"""Daily two-strategy research and weekly ranking jobs over persisted v4 bars."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, cast
from uuid import uuid4

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.research_strategy1 import FACTOR_WEIGHTS, FORMULA_REVISION, strategy1_factors
from src.application.research_strategy2 import (
    FORMULA_REVISION as STRATEGY2_FORMULA_REVISION,
)
from src.application.research_strategy2 import strategy2_factors, strategy2_indicators
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError, QualityStatus


class ResearchJobs:
    def __init__(
        self, database: str | Path, market: MarketRepository, publisher: ArtifactPublisher
    ):
        self.database = Path(database)
        self.market = market
        self.publisher = publisher
        migrate_sqlite(
            self.database,
            "research",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS research_daily_scores (
                        strategy_id TEXT NOT NULL, as_of_date TEXT NOT NULL,
                        instrument_id TEXT NOT NULL, symbol TEXT NOT NULL,
                        score REAL NOT NULL, penalty REAL NOT NULL,
                        artifact_id TEXT NOT NULL,
                        PRIMARY KEY(strategy_id, as_of_date, instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS research_daily_scores_date ON research_daily_scores(strategy_id, as_of_date)",
                    """CREATE TABLE IF NOT EXISTS research_weekly_rankings (
                        strategy_id TEXT NOT NULL, week_end TEXT NOT NULL,
                        instrument_id TEXT NOT NULL, symbol TEXT NOT NULL,
                        score REAL NOT NULL, rank INTEGER NOT NULL,
                        artifact_id TEXT NOT NULL,
                        PRIMARY KEY(strategy_id, week_end, instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS research_weekly_rankings_date ON research_weekly_rankings(strategy_id, week_end, rank)",
                )
            },
        )

    def calculate_strategy1_day(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._calculate_day(payload, "strategy1")

    def calculate_strategy2_day(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._calculate_day(payload, "strategy2")

    def _calculate_day(self, payload: dict[str, Any], strategy_id: str) -> dict[str, object]:
        if set(payload) != {"as_of_date"} or not isinstance(payload.get("as_of_date"), str):
            raise DomainValidationError("daily calculation requires as_of_date")
        try:
            as_of_date = date.fromisoformat(payload["as_of_date"])
        except ValueError as exc:
            raise DomainValidationError("as_of_date must be an ISO date") from exc
        histories = self.market.histories(as_of_date - timedelta(days=420), as_of_date)
        benchmark: list[dict[str, object]] = []
        if strategy_id == "strategy2":
            try:
                benchmark_id = str(self.market.instrument("NIFTY 500")["instrument_id"])
                benchmark = histories[benchmark_id][0]
            except (DomainValidationError, KeyError) as exc:
                raise DomainValidationError("NIFTY 500 benchmark history is required") from exc
            if benchmark[-1]["as_of_date"] != as_of_date.isoformat():
                raise DomainValidationError("NIFTY 500 benchmark is stale for requested date")
        results: dict[str, dict[str, object]] = {}
        symbols: dict[str, str] = {}
        upstream_ids: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            if bars[-1]["as_of_date"] != as_of_date.isoformat() or str(identity["isin"]).startswith(
                "INDEX:"
            ):
                continue
            computed = (
                strategy1_factors(bars)
                if strategy_id == "strategy1"
                else strategy2_indicators(bars, benchmark)
            )
            if computed is None:
                continue
            results[instrument_id] = computed
            symbols[instrument_id] = str(identity["symbol"])
            upstream_ids.update(str(bar["snapshot_id"]) for bar in bars)
        if not results:
            raise DomainValidationError(
                "no instruments have a completed bar and 200-session warm-up"
            )
        if strategy_id == "strategy2":
            upstream_ids.update(str(bar["snapshot_id"]) for bar in benchmark)
            factors = strategy2_factors(results)
            for instrument_id, values in results.items():
                values["factors"] = factors[instrument_id]
        factor_values = {
            instrument_id: cast(dict[str, float], values["factors"])
            for instrument_id, values in results.items()
        }
        feature_id = str(uuid4())
        feature_manifest = self.publisher.publish_json(
            f"features/{strategy_id}",
            feature_id,
            {
                "snapshot_id": feature_id,
                "as_of_date": as_of_date.isoformat(),
                "strategy_id": strategy_id,
                "formula_revision": FORMULA_REVISION
                if strategy_id == "strategy1"
                else STRATEGY2_FORMULA_REVISION,
                "inherited_limitations": [
                    "quality_z_score is an unpopulated constant-zero placeholder",
                    "scaled_turnover is relative volume, not float turnover",
                ]
                if strategy_id == "strategy2"
                else [],
                "values": {
                    instrument_id: {"symbol": symbols[instrument_id], **value}
                    for instrument_id, value in sorted(results.items())
                },
            },
            upstream_ids=tuple(sorted(upstream_ids)),
            quality=QualityStatus.PARTIAL
            if strategy_id == "strategy2" or len(results) < len(histories)
            else QualityStatus.COMPLETE,
        )
        percentiles: dict[str, dict[str, float]] = {key: {} for key in results}
        for factor in FACTOR_WEIGHTS:
            ordered = sorted(results, key=lambda key: (factor_values[key][factor], key))
            start = 0
            while start < len(ordered):
                end = start + 1
                while (
                    end < len(ordered)
                    and factor_values[ordered[end]][factor] == factor_values[ordered[start]][factor]
                ):
                    end += 1
                value = ((start + 1 + end) / 2) / len(ordered) * 100
                for instrument_id in ordered[start:end]:
                    percentiles[instrument_id][factor] = value
                start = end
        percentile_id = str(uuid4())
        self.publisher.publish_json(
            "research/percentiles",
            percentile_id,
            {
                "snapshot_id": percentile_id,
                "as_of_date": as_of_date.isoformat(),
                "strategy_id": strategy_id,
                "feature_snapshot_id": feature_id,
                "values": percentiles,
            },
            upstream_ids=(feature_manifest.artifact_id,),
        )
        scores: dict[str, dict[str, object]] = {}
        for instrument_id, values in results.items():
            adx_multiplier = 1.0
            if strategy_id == "strategy2":
                adx = float(cast(Any, values["adx_14"]))
                adx_multiplier = 0.5 if adx < 20 else 0.9 if adx > 30 else 1.0
            initial = sum(
                percentiles[instrument_id][factor]
                * weight
                * (adx_multiplier if factor in {"trend", "momentum"} else 1)
                for factor, weight in FACTOR_WEIGHTS.items()
            )
            penalty = float(cast(Any, values["penalty"]))
            scores[instrument_id] = {
                "symbol": symbols[instrument_id],
                "initial_composite_score": initial,
                "penalty": penalty,
                "penalty_reasons": values["penalty_reasons"],
                "composite_score": initial * penalty,
                "eligible": penalty > 0,
                "adx_multiplier": adx_multiplier if strategy_id == "strategy2" else None,
            }
        score_id = str(uuid4())
        self.publisher.publish_json(
            "research/scores",
            score_id,
            {
                "snapshot_id": score_id,
                "as_of_date": as_of_date.isoformat(),
                "strategy_id": strategy_id,
                "percentile_snapshot_id": percentile_id,
                "values": scores,
            },
            upstream_ids=(percentile_id,),
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            # A recomputation can shrink the universe. Replace the complete
            # date projection so removed instruments cannot survive as stale
            # scores and later leak into weekly rankings.
            connection.execute(
                "DELETE FROM research_daily_scores WHERE strategy_id=? AND as_of_date=?",
                (strategy_id, as_of_date.isoformat()),
            )
            connection.executemany(
                """INSERT INTO research_daily_scores
                   (strategy_id, as_of_date, instrument_id, symbol, score, penalty, artifact_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strategy_id, as_of_date, instrument_id) DO UPDATE SET
                   score=excluded.score, penalty=excluded.penalty, artifact_id=excluded.artifact_id""",
                [
                    (
                        strategy_id,
                        as_of_date.isoformat(),
                        key,
                        symbols[key],
                        value["composite_score"],
                        value["penalty"],
                        score_id,
                    )
                    for key, value in scores.items()
                ],
            )
        return {
            "feature_artifact_id": feature_id,
            "percentile_artifact_id": percentile_id,
            "score_artifact_id": score_id,
            "as_of_date": as_of_date.isoformat(),
            "strategy_id": strategy_id,
            "scored_count": len(scores),
            "eligible_count": sum(bool(value["eligible"]) for value in scores.values()),
        }

    def rank_week(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._rank_week(payload, "strategy1")

    def rank_strategy2_week(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._rank_week(payload, "strategy2")

    def _rank_week(self, payload: dict[str, Any], strategy_id: str) -> dict[str, object]:
        if set(payload) != {"week_end"} or not isinstance(payload.get("week_end"), str):
            raise DomainValidationError("weekly ranking requires week_end")
        try:
            week_end = date.fromisoformat(payload["week_end"])
        except ValueError as exc:
            raise DomainValidationError("week_end must be an ISO date") from exc
        if week_end.weekday() != 4 or week_end >= datetime.now(UTC).date():
            raise DomainValidationError("week_end must be a completed Friday")
        week_start = week_end - timedelta(days=4)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_daily_scores WHERE strategy_id=?
                   AND as_of_date BETWEEN ? AND ? ORDER BY as_of_date""",
                (strategy_id, week_start.isoformat(), week_end.isoformat()),
            ).fetchall()
        if not rows:
            raise DomainValidationError("weekly ranking has no daily scores")
        grouped: dict[str, list[float]] = defaultdict(list)
        symbols: dict[str, str] = {}
        upstream_ids: set[str] = set()
        for row in rows:
            grouped[row["instrument_id"]].append(row["score"])
            symbols[row["instrument_id"]] = row["symbol"]
            upstream_ids.add(row["artifact_id"])
        ranked = sorted(grouped, key=lambda key: (-mean(grouped[key]), symbols[key]))
        members = [
            {
                "instrument_id": key,
                "symbol": symbols[key],
                "composite_score": mean(grouped[key]),
                "rank": index,
                "sampled_sessions": len(grouped[key]),
            }
            for index, key in enumerate(ranked, start=1)
        ]
        artifact_id = str(uuid4())
        self.publisher.publish_json(
            "research/rankings",
            artifact_id,
            {
                "snapshot_id": artifact_id,
                "strategy_id": strategy_id,
                "week_end": week_end.isoformat(),
                "members": members,
            },
            upstream_ids=tuple(sorted(upstream_ids)),
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM research_weekly_rankings WHERE strategy_id=? AND week_end=?",
                (strategy_id, week_end.isoformat()),
            )
            connection.executemany(
                """INSERT INTO research_weekly_rankings
                   (strategy_id, week_end, instrument_id, symbol, score, rank, artifact_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strategy_id, week_end, instrument_id) DO UPDATE SET
                   score=excluded.score, rank=excluded.rank, artifact_id=excluded.artifact_id""",
                [
                    (
                        strategy_id,
                        week_end.isoformat(),
                        item["instrument_id"],
                        item["symbol"],
                        item["composite_score"],
                        item["rank"],
                        artifact_id,
                    )
                    for item in members
                ],
            )
        return {
            "artifact_id": artifact_id,
            "week_end": week_end.isoformat(),
            "strategy_id": strategy_id,
            "ranked_count": len(members),
        }

    def top_rankings(
        self, week_end: date, limit: int = 20, strategy_id: str = "strategy1"
    ) -> list[dict[str, object]]:
        if not 1 <= limit <= 500:
            raise DomainValidationError("ranking limit must be between 1 and 500")
        if strategy_id not in {"strategy1", "strategy2"}:
            raise DomainValidationError("strategy_id is invalid")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_weekly_rankings WHERE strategy_id=?
                   AND week_end=? ORDER BY rank LIMIT ?""",
                (strategy_id, week_end.isoformat(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def ranking_weeks(self, strategy_id: str) -> tuple[date, ...]:
        if strategy_id not in {"strategy1", "strategy2"}:
            raise DomainValidationError("strategy_id is invalid")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT DISTINCT week_end FROM research_weekly_rankings
                   WHERE strategy_id=? ORDER BY week_end""",
                (strategy_id,),
            ).fetchall()
        return tuple(date.fromisoformat(row["week_end"]) for row in rows)
