"""Generic daily research and weekly ranking jobs over active strategy revisions."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev
from time import perf_counter
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.application.jobs import JobExecutionContext
from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.application.strategy_definitions import StrategyDefinitions
from src.application.strategy_runtime import StrategyRuntime
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError, QualityStatus


class ResearchJobs:
    def __init__(
        self,
        database: str | Path,
        market: MarketRepository,
        publisher: ArtifactPublisher,
        runtime: StrategyRuntime | None = None,
    ):
        self.database = Path(database)
        self.market = market
        self.publisher = publisher
        self.runtime = runtime or StrategyRuntime(StrategyDefinitions(database, PandasTaAdapter()))
        if runtime is None:
            self.runtime.seed(Path(__file__).resolve().parents[2] / "strategies")
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
                ),
                2: (
                    "DROP TABLE IF EXISTS research_daily_scores",
                    "DROP TABLE IF EXISTS research_weekly_rankings",
                    """CREATE TABLE research_daily_scores (
                        strategy_id TEXT NOT NULL, strategy_revision_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, instrument_id TEXT NOT NULL,
                        symbol TEXT NOT NULL, score REAL NOT NULL, penalty REAL NOT NULL,
                        artifact_id TEXT NOT NULL,
                        PRIMARY KEY(strategy_revision_id, as_of_date, instrument_id))""",
                    "CREATE INDEX research_daily_scores_date ON research_daily_scores(strategy_revision_id, as_of_date)",
                    """CREATE TABLE research_weekly_rankings (
                        strategy_id TEXT NOT NULL, strategy_revision_id TEXT NOT NULL,
                        week_end TEXT NOT NULL, instrument_id TEXT NOT NULL,
                        symbol TEXT NOT NULL, score REAL NOT NULL, rank INTEGER NOT NULL,
                        artifact_id TEXT NOT NULL,
                        PRIMARY KEY(strategy_revision_id, week_end, instrument_id))""",
                    "CREATE INDEX research_weekly_rankings_date ON research_weekly_rankings(strategy_revision_id, week_end, rank)",
                ),
            },
        )

    def calculate_day(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._calculate_day(payload)

    def rebuild_range(
        self, payload: dict[str, Any], context: JobExecutionContext
    ) -> dict[str, object]:
        """Rebuild a bounded range in four bulk stages without per-day history reloads."""
        allowed = {"start_date", "end_date", "strategies", "trading_dates"}
        if not isinstance(payload, dict) or set(payload) != allowed:
            raise DomainValidationError("research range rebuild payload is incomplete")
        try:
            start = date.fromisoformat(str(payload["start_date"]))
            end = date.fromisoformat(str(payload["end_date"]))
            sessions = tuple(date.fromisoformat(str(item)) for item in payload["trading_dates"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("research range dates must be ISO dates") from exc
        strategies = tuple(str(item) for item in payload["strategies"])
        if (
            start > end
            or (end - start).days > 365
            or not sessions
            or sessions != tuple(sorted(set(sessions)))
            or any(item < start or item > end for item in sessions)
            or not strategies
            or len(strategies) != len(set(strategies))
            or any(item not in self.runtime.strategy_ids() for item in strategies)
        ):
            raise DomainValidationError("research range or strategy selection is invalid")

        started = perf_counter()
        timings: dict[str, float] = {}
        context.checkpoint(
            progress={
                "stage": "loading_market_history",
                "stage_number": 1,
                "stage_count": 4,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "strategies": list(strategies),
                "sessions": len(sessions),
                "detail": "Loading the shared warm-up history once for this range.",
            }
        )
        stage_started = perf_counter()
        histories = self.market.histories(start - timedelta(days=900), end)
        timings["loading_market_history"] = perf_counter() - stage_started
        session_keys = {item.isoformat() for item in sessions}
        completed: dict[str, dict[str, int]] = {}

        for strategy_index, strategy_id in enumerate(strategies, start=1):
            revision = self.runtime.revision(strategy_id)
            revision_id = str(revision["revision_id"])
            factor_weights = self.runtime.factor_weights(strategy_id)
            benchmark: list[dict[str, object]] = []
            benchmark_name = self.runtime.benchmark(strategy_id)
            if benchmark_name:
                benchmark_id = str(self.market.instrument(benchmark_name)["instrument_id"])
                try:
                    benchmark = histories[benchmark_id][0]
                except KeyError as exc:
                    raise DomainValidationError(
                        f"{benchmark_name} benchmark history is required"
                    ) from exc

            stage_started = perf_counter()
            features_by_date: dict[str, dict[str, dict[str, object]]] = {
                item.isoformat(): {} for item in sessions
            }
            symbols: dict[str, str] = {}
            eligible_histories = [
                (instrument_id, bars, identity)
                for instrument_id, (bars, identity) in histories.items()
                if not str(identity["isin"]).startswith("INDEX:")
            ]
            for index, (instrument_id, bars, identity) in enumerate(eligible_histories, start=1):
                series = self.runtime.compute_series(strategy_id, bars, benchmark)
                symbols[instrument_id] = str(identity["symbol"])
                for day, values in series.items():
                    if day in session_keys:
                        features_by_date[day][instrument_id] = values
                if index % 25 == 0 or index == len(eligible_histories):
                    context.checkpoint(
                        progress={
                            "stage": "indicators",
                            "stage_number": 1,
                            "stage_count": 4,
                            "strategy": strategy_id,
                            "strategy_number": strategy_index,
                            "strategy_count": len(strategies),
                            "processed_instruments": index,
                            "total_instruments": len(eligible_histories),
                            "completed_percent": round(index / len(eligible_histories) * 100, 1),
                            "detail": "Computing every session's rolling indicators once per instrument.",
                        }
                    )
            timings[f"{strategy_id}:indicators"] = perf_counter() - stage_started

            stage_started = perf_counter()
            percentiles_by_date: dict[str, dict[str, dict[str, float]]] = {}
            for index, session in enumerate(sessions, start=1):
                day = session.isoformat()
                values = features_by_date[day]
                cross_section = self.runtime.cross_section(strategy_id, values)
                if cross_section is not None:
                    for instrument_id, factors in cross_section.items():
                        values[instrument_id]["factors"] = factors
                percentiles = {instrument_id: {} for instrument_id in values}
                for factor in factor_weights:
                    ordered = sorted(
                        values,
                        key=lambda key: (float(values[key]["factors"][factor]), key),
                    )
                    position = 0
                    while position < len(ordered):
                        tied_end = position + 1
                        while (
                            tied_end < len(ordered)
                            and values[ordered[tied_end]]["factors"][factor]
                            == values[ordered[position]]["factors"][factor]
                        ):
                            tied_end += 1
                        percentile = ((position + 1 + tied_end) / 2) / len(ordered) * 100
                        for instrument_id in ordered[position:tied_end]:
                            percentiles[instrument_id][factor] = percentile
                        position = tied_end
                percentiles_by_date[day] = percentiles
                if index % 10 == 0 or index == len(sessions):
                    context.checkpoint(
                        progress={
                            "stage": "percentiles",
                            "stage_number": 2,
                            "stage_count": 4,
                            "strategy": strategy_id,
                            "processed_sessions": index,
                            "total_sessions": len(sessions),
                            "completed_percent": round(index / len(sessions) * 100, 1),
                            "detail": "Normalizing each factor across the complete daily universe.",
                        }
                    )
            timings[f"{strategy_id}:percentiles"] = perf_counter() - stage_started

            stage_started = perf_counter()
            artifact_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"research-range:{revision_id}:{start.isoformat()}:{end.isoformat()}",
                )
            )
            total_scored = 0
            score_rows: list[tuple[object, ...]] = []
            for index, session in enumerate(sessions, start=1):
                day = session.isoformat()
                for instrument_id, values in features_by_date[day].items():
                    initial = sum(
                        percentiles_by_date[day][instrument_id][factor]
                        * weight
                        * self._factor_multiplier(revision, factor, values)
                        for factor, weight in factor_weights.items()
                    )
                    penalty = float(values["penalty"])
                    score_rows.append(
                        (
                            strategy_id,
                            revision_id,
                            day,
                            instrument_id,
                            symbols[instrument_id],
                            initial * penalty,
                            penalty,
                            artifact_id,
                        )
                    )
                total_scored = len(score_rows)
                if index % 10 == 0 or index == len(sessions):
                    context.checkpoint(
                        progress={
                            "stage": "scores",
                            "stage_number": 3,
                            "stage_count": 4,
                            "strategy": strategy_id,
                            "processed_sessions": index,
                            "total_sessions": len(sessions),
                            "scored_rows": total_scored,
                            "completed_percent": round(index / len(sessions) * 100, 1),
                            "detail": "Applying strategy weights and penalties, then batch-writing scores.",
                        }
                    )
            with sqlite_connection(self.database) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """DELETE FROM research_daily_scores
                       WHERE strategy_revision_id=? AND as_of_date BETWEEN ? AND ?""",
                    (revision_id, start.isoformat(), end.isoformat()),
                )
                connection.executemany(
                    """INSERT INTO research_daily_scores
                       (strategy_id, strategy_revision_id, as_of_date, instrument_id,
                        symbol, score, penalty, artifact_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    score_rows,
                )
            if not self.publisher.catalog.has(artifact_id):
                self.publisher.publish_json(
                    "research/range-scores",
                    artifact_id,
                    {
                        "strategy_id": strategy_id,
                        "strategy_revision_id": revision_id,
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                        "sessions": len(sessions),
                        "scored_rows": total_scored,
                    },
                    upstream_ids=(revision_id,),
                )
            timings[f"{strategy_id}:scores"] = perf_counter() - stage_started
            completed[strategy_id] = {
                "sessions": len(sessions),
                "scored_rows": total_scored,
                "instruments": len(eligible_histories),
            }

        stage_started = perf_counter()
        week_ends = tuple(
            max(item for item in sessions if item.isocalendar()[:2] == week)
            for week in sorted({item.isocalendar()[:2] for item in sessions})
        )
        ranked = 0
        ranking_total = len(week_ends) * len(strategies)
        for strategy_id in strategies:
            for week_end in week_ends:
                self.rank_week({"week_end": week_end.isoformat(), "strategy_id": strategy_id})
                ranked += 1
                if ranked % 5 == 0 or ranked == ranking_total:
                    context.checkpoint(
                        progress={
                            "stage": "rankings",
                            "stage_number": 4,
                            "stage_count": 4,
                            "processed_rankings": ranked,
                            "total_rankings": ranking_total,
                            "completed_percent": round(ranked / ranking_total * 100, 1),
                            "detail": "Aggregating completed daily scores into weekly rankings.",
                        }
                    )
        timings["rankings"] = perf_counter() - stage_started
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "strategies": completed,
            "weekly_rankings": ranked,
            "timings_seconds": {key: round(value, 3) for key, value in timings.items()},
            "total_seconds": round(perf_counter() - started, 3),
            "execution_model": "bulk-staged-vectorized",
        }

    @staticmethod
    def _factor_multiplier(
        revision: dict[str, object], factor: str, values: dict[str, object]
    ) -> float:
        definition = cast(dict[str, Any], revision["definition"])
        for modifier in definition.get("score", {}).get("factor_modifiers", []):
            if factor not in modifier["factors"]:
                continue
            observed = float(values[str(modifier["input"])])
            for rule in modifier["rules"]:
                threshold = float(rule["value"])
                if (rule["operator"] == "less_than" and observed < threshold) or (
                    rule["operator"] == "greater_than" and observed > threshold
                ):
                    return float(rule["multiplier"])
            return float(modifier["default"])
        return 1.0

    def sector_normalize(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {"as_of_date", "strategy_id", "feature_artifact_id", "sector_artifact_id"}
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or payload["strategy_id"] not in self.runtime.strategy_ids()
        ):
            raise DomainValidationError("sector ranking command is incomplete")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except ValueError as exc:
            raise DomainValidationError("sector ranking date must be ISO date") from exc
        try:
            _, features = self.publisher.store.read_json(
                f"features/{payload['strategy_id']}", str(payload["feature_artifact_id"])
            )
            _, sectors = self.publisher.store.read_json(
                "reference/sectors", str(payload["sector_artifact_id"])
            )
        except DomainValidationError as exc:
            raise DomainValidationError("feature or sector artifact was not found") from exc
        values = features.get("values")
        sector_values = sectors.get("values")
        if not isinstance(values, dict) or not isinstance(sector_values, dict):
            raise DomainValidationError("feature or sector artifact is malformed")
        instruments = [
            (str(instrument_id), item, str(sector_values[instrument_id]))
            for instrument_id, item in values.items()
            if isinstance(item, dict)
            and isinstance(item.get("factors"), dict)
            and instrument_id in sector_values
            and str(sector_values[instrument_id]).strip()
        ]
        if not instruments:
            raise DomainValidationError("no sector-classified factor values are available")
        weights = self.runtime.factor_weights(str(payload["strategy_id"]))
        factors = tuple(weights)
        by_sector: dict[str, list[dict[str, float]]] = defaultdict(list)
        for _, item, sector in instruments:
            by_sector[sector].append(
                {factor: float(item["factors"].get(factor, 0)) for factor in factors}
            )
        members = []
        for instrument_id, item, sector in instruments:
            factor_values = {factor: float(item["factors"].get(factor, 0)) for factor in factors}
            normalized: dict[str, float] = {}
            peers = by_sector[sector]
            for factor in factors:
                average = sum(peer[factor] for peer in peers) / len(peers)
                variance = sum((peer[factor] - average) ** 2 for peer in peers) / len(peers)
                deviation = variance**0.5
                normalized[factor] = (
                    (factor_values[factor] - average) / deviation if deviation else 0.0
                )
            members.append(
                {
                    "instrument_id": instrument_id,
                    "symbol": item.get("symbol"),
                    "sector": sector,
                    "factor_zscores": normalized,
                    "composite_score": sum(
                        normalized[factor] * weights[factor] for factor in factors
                    ),
                }
            )
        members.sort(key=lambda item: (-float(item["composite_score"]), str(item["instrument_id"])))
        for rank, item in enumerate(members, 1):
            item["rank"] = rank
        artifact_id = str(
            uuid5(
                NAMESPACE_URL,
                "sector-ranking:"
                + json.dumps(
                    {
                        "date": as_of.isoformat(),
                        "strategy": payload["strategy_id"],
                        "feature": payload["feature_artifact_id"],
                        "sector": payload["sector_artifact_id"],
                    },
                    sort_keys=True,
                ),
            )
        )
        report = {
            "snapshot_id": artifact_id,
            "as_of_date": as_of.isoformat(),
            "strategy_id": payload["strategy_id"],
            "normalization": "within_sector_zscore",
            "members": members,
        }
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "research/sector-rankings",
                artifact_id,
                report,
                upstream_ids=(
                    str(payload["feature_artifact_id"]),
                    str(payload["sector_artifact_id"]),
                ),
                quality=QualityStatus.PARTIAL,
            )
        return {"artifact_id": artifact_id, **report}

    def correlations(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {"as_of_date", "lookback_sessions", "correlation_threshold"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise DomainValidationError("correlation command is incomplete")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
            lookback = int(payload["lookback_sessions"])
            threshold = float(payload["correlation_threshold"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("correlation parameters are invalid") from exc
        if not 20 <= lookback <= 365 or not 0 < threshold <= 1 or as_of >= datetime.now(UTC).date():
            raise DomainValidationError("correlation parameters are outside supported bounds")
        histories = self.market.histories(as_of - timedelta(days=lookback * 3), as_of)
        closes: dict[str, dict[str, float]] = {}
        upstream_ids: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            if str(identity["isin"]).startswith("INDEX:"):
                continue
            ordered = bars[-lookback:]
            if len(ordered) < 20:
                continue
            closes[instrument_id] = {str(bar["as_of_date"]): float(bar["close"]) for bar in ordered}
            upstream_ids.update(str(bar["snapshot_id"]) for bar in ordered)
        if not 2 <= len(closes) <= 100:
            raise DomainValidationError(
                "correlation requires 2..100 instruments with sufficient bars"
            )
        instruments = sorted(closes)
        returns: dict[str, dict[str, float]] = {
            instrument_id: {
                day: closes[instrument_id][day] / closes[instrument_id][prior] - 1
                for prior, day in zip(
                    sorted(closes[instrument_id])[:-1],
                    sorted(closes[instrument_id])[1:],
                    strict=True,
                )
            }
            for instrument_id in instruments
        }
        matrix: dict[str, dict[str, float]] = {instrument_id: {} for instrument_id in instruments}
        for left in instruments:
            for right in instruments:
                common = sorted(set(returns[left]) & set(returns[right]))
                left_values = [returns[left][day] for day in common]
                right_values = [returns[right][day] for day in common]
                left_mean = sum(left_values) / len(left_values)
                right_mean = sum(right_values) / len(right_values)
                numerator = sum(
                    (a - left_mean) * (b - right_mean)
                    for a, b in zip(left_values, right_values, strict=True)
                )
                left_dev = sum((value - left_mean) ** 2 for value in left_values) ** 0.5
                right_dev = sum((value - right_mean) ** 2 for value in right_values) ** 0.5
                matrix[left][right] = (
                    numerator / (left_dev * right_dev) if left_dev and right_dev else 0.0
                )
        parent = {instrument_id: instrument_id for instrument_id in instruments}

        def find(item: str) -> str:
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        for left in instruments:
            for right in instruments:
                if left < right and abs(matrix[left][right]) >= threshold:
                    parent[find(left)] = find(right)
        clusters: dict[str, list[str]] = defaultdict(list)
        for instrument_id in instruments:
            clusters[find(instrument_id)].append(instrument_id)
        artifact_id = str(
            uuid5(NAMESPACE_URL, "correlations:" + json.dumps(payload, sort_keys=True))
        )
        report = {
            "snapshot_id": artifact_id,
            "as_of_date": as_of.isoformat(),
            "lookback_sessions": lookback,
            "correlation_threshold": threshold,
            "matrix": matrix,
            "clusters": sorted(
                (sorted(values) for values in clusters.values()), key=lambda values: values[0]
            ),
        }
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "research/correlations",
                artifact_id,
                report,
                upstream_ids=tuple(sorted(upstream_ids)),
                quality=QualityStatus.PARTIAL,
            )
        return {"artifact_id": artifact_id, **report}

    def anomalies(self, payload: dict[str, Any]) -> dict[str, object]:
        """Publish a bounded, deterministic return-anomaly report."""
        required = {"as_of_date", "lookback_sessions", "z_threshold", "min_sessions"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise DomainValidationError("anomaly command is incomplete")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
            lookback = int(payload["lookback_sessions"])
            threshold = float(payload["z_threshold"])
            minimum = int(payload["min_sessions"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("anomaly parameters are invalid") from exc
        if (
            not 20 <= lookback <= 365
            or not 2 <= threshold <= 10
            or not 20 <= minimum <= lookback
            or as_of >= datetime.now(UTC).date()
        ):
            raise DomainValidationError("anomaly parameters are outside supported bounds")
        histories = self.market.histories(as_of - timedelta(days=lookback * 3), as_of)
        rows: list[dict[str, object]] = []
        upstream_ids: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            if str(identity["isin"]).startswith("INDEX:"):
                continue
            ordered = sorted(bars, key=lambda item: str(item["as_of_date"]))[-(lookback + 2) :]
            if len(ordered) < minimum + 2:
                continue
            returns = [
                float(ordered[index]["close"]) / float(ordered[index - 1]["close"]) - 1
                for index in range(1, len(ordered))
            ]
            baseline, latest = returns[:-1], returns[-1]
            if len(baseline) < minimum:
                continue
            average = mean(baseline)
            deviation = pstdev(baseline)
            score = (latest - average) / deviation if deviation else 0.0
            upstream_ids.update(str(item["snapshot_id"]) for item in ordered)
            rows.append(
                {
                    "instrument_id": str(instrument_id),
                    "symbol": str(identity["symbol"]),
                    "latest_date": str(ordered[-1]["as_of_date"]),
                    "latest_return": latest,
                    "baseline_mean": average,
                    "baseline_stddev": deviation,
                    "z_score": score,
                    "anomaly": abs(score) >= threshold,
                }
            )
        if not rows:
            raise DomainValidationError("no instruments have sufficient return history")
        rows.sort(key=lambda item: (-abs(float(item["z_score"])), str(item["instrument_id"])))
        artifact_id = str(
            uuid5(NAMESPACE_URL, "research-anomalies:" + json.dumps(payload, sort_keys=True))
        )
        report = {
            "snapshot_id": artifact_id,
            "as_of_date": as_of.isoformat(),
            "lookback_sessions": lookback,
            "z_threshold": threshold,
            "min_sessions": minimum,
            "method": "latest-return-versus-prior-return-z-score",
            "rows": rows,
            "anomaly_count": sum(bool(row["anomaly"]) for row in rows),
        }
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "research/anomalies",
                artifact_id,
                report,
                upstream_ids=tuple(sorted(upstream_ids)),
                quality=QualityStatus.PARTIAL,
            )
        return {"artifact_id": artifact_id, **report}

    def _calculate_day(self, payload: dict[str, Any]) -> dict[str, object]:
        if (
            set(payload) - {"as_of_date", "strategy_id", "symbols"}
            or not {"as_of_date", "strategy_id"}.issubset(payload)
            or not isinstance(payload.get("as_of_date"), str)
            or payload.get("strategy_id") not in self.runtime.strategy_ids()
        ):
            raise DomainValidationError(
                "daily calculation requires as_of_date and an active strategy_id"
            )
        strategy_id = str(payload["strategy_id"])
        requested_symbols = payload.get("symbols")
        if requested_symbols is not None and (
            not isinstance(requested_symbols, list)
            or not requested_symbols
            or len(requested_symbols) > 500
            or len(set(requested_symbols)) != len(requested_symbols)
            or any(
                not isinstance(symbol, str) or not symbol.strip() for symbol in requested_symbols
            )
        ):
            raise DomainValidationError(
                "symbols must be a unique non-empty list of at most 500 values"
            )
        try:
            as_of_date = date.fromisoformat(payload["as_of_date"])
        except ValueError as exc:
            raise DomainValidationError("as_of_date must be an ISO date") from exc
        revision = self.runtime.revision(strategy_id)
        factor_weights = self.runtime.factor_weights(strategy_id)
        # EMA-200 needs a long seed. Use up to 900 calendar days, while still
        # allowing instruments with shorter histories to use all available data.
        histories = self.market.histories(as_of_date - timedelta(days=900), as_of_date)
        benchmark: list[dict[str, object]] = []
        benchmark_name = self.runtime.benchmark(strategy_id)
        if benchmark_name:
            try:
                benchmark_id = str(self.market.instrument(benchmark_name)["instrument_id"])
                benchmark = histories[benchmark_id][0]
            except (DomainValidationError, KeyError) as exc:
                raise DomainValidationError(
                    f"{benchmark_name} benchmark history is required"
                ) from exc
            if benchmark[-1]["as_of_date"] != as_of_date.isoformat():
                raise DomainValidationError(
                    f"{benchmark_name} benchmark is stale for requested date"
                )
        results: dict[str, dict[str, object]] = {}
        symbols: dict[str, str] = {}
        upstream_ids: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            if (
                requested_symbols is not None
                and instrument_id not in requested_symbols
                and identity["symbol"] not in requested_symbols
            ):
                continue
            if bars[-1]["as_of_date"] != as_of_date.isoformat() or str(identity["isin"]).startswith(
                "INDEX:"
            ):
                continue
            computed = self.runtime.compute(strategy_id, bars, benchmark)
            if computed is None:
                continue
            results[instrument_id] = computed
            symbols[instrument_id] = str(identity["symbol"])
            upstream_ids.update(str(bar["snapshot_id"]) for bar in bars)
        if not results:
            # A newly listed instrument only becomes scoreable after the
            # strategy warm-up. This is normal during a full historical
            # rebuild and must not make the pipeline fail.
            return {
                "as_of_date": as_of_date.isoformat(),
                "strategy_id": strategy_id,
                "scored_count": 0,
                "eligible_count": 0,
                "skipped": True,
                "reason": "no instruments have a completed bar and required warm-up",
            }
        cross_section = self.runtime.cross_section(strategy_id, results)
        if cross_section is not None:
            upstream_ids.update(str(bar["snapshot_id"]) for bar in benchmark)
            for instrument_id, values in results.items():
                values["factors"] = cross_section[instrument_id]
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
                "strategy_revision_id": revision["revision_id"],
                "factor_weights": factor_weights,
                "definition_hash": revision["definition_hash"],
                "values": {
                    instrument_id: {"symbol": symbols[instrument_id], **value}
                    for instrument_id, value in sorted(results.items())
                },
            },
            upstream_ids=tuple(sorted(upstream_ids | {str(revision["revision_id"])})),
            quality=QualityStatus.PARTIAL
            if len(results) < len(histories)
            else QualityStatus.COMPLETE,
        )
        percentiles: dict[str, dict[str, float]] = {key: {} for key in results}
        for factor in factor_weights:
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
                "strategy_revision_id": revision["revision_id"],
                "factor_weights": factor_weights,
                "feature_snapshot_id": feature_id,
                "values": percentiles,
            },
            upstream_ids=(feature_manifest.artifact_id,),
        )
        scores: dict[str, dict[str, object]] = {}
        for instrument_id, values in results.items():
            initial = sum(
                percentiles[instrument_id][factor]
                * weight
                * self.runtime.factor_multiplier(strategy_id, factor, values)
                for factor, weight in factor_weights.items()
            )
            penalty = float(cast(Any, values["penalty"]))
            scores[instrument_id] = {
                "symbol": symbols[instrument_id],
                "initial_composite_score": initial,
                "penalty": penalty,
                "penalty_reasons": values["penalty_reasons"],
                "composite_score": initial * penalty,
                "eligible": penalty > 0,
            }
        score_id = str(uuid4())
        self.publisher.publish_json(
            "research/scores",
            score_id,
            {
                "snapshot_id": score_id,
                "as_of_date": as_of_date.isoformat(),
                "strategy_id": strategy_id,
                "strategy_revision_id": revision["revision_id"],
                "factor_weights": factor_weights,
                "percentile_snapshot_id": percentile_id,
                "values": scores,
            },
            upstream_ids=(percentile_id, str(revision["revision_id"])),
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            # A recomputation can shrink the universe. Replace the complete
            # date projection so removed instruments cannot survive as stale
            # scores and later leak into weekly rankings.
            if requested_symbols is None:
                connection.execute(
                    "DELETE FROM research_daily_scores WHERE strategy_revision_id=? AND as_of_date=?",
                    (revision["revision_id"], as_of_date.isoformat()),
                )
            else:
                connection.executemany(
                    "DELETE FROM research_daily_scores WHERE strategy_revision_id=? AND as_of_date=? AND (instrument_id=? OR symbol=?)",
                    [
                        (revision["revision_id"], as_of_date.isoformat(), symbol, symbol)
                        for symbol in requested_symbols
                    ],
                )
            connection.executemany(
                """INSERT INTO research_daily_scores
                   (strategy_id, strategy_revision_id, as_of_date, instrument_id, symbol, score, penalty, artifact_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strategy_revision_id, as_of_date, instrument_id) DO UPDATE SET
                   score=excluded.score, penalty=excluded.penalty, artifact_id=excluded.artifact_id""",
                [
                    (
                        strategy_id,
                        revision["revision_id"],
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
        if (
            set(payload) != {"week_end", "strategy_id"}
            or not isinstance(payload.get("week_end"), str)
            or payload.get("strategy_id") not in self.runtime.strategy_ids()
        ):
            raise DomainValidationError(
                "weekly ranking requires week_end and an active strategy_id"
            )
        strategy_id = str(payload["strategy_id"])
        try:
            week_end = date.fromisoformat(payload["week_end"])
        except ValueError as exc:
            raise DomainValidationError("week_end must be an ISO date") from exc
        if week_end >= datetime.now(UTC).date():
            raise DomainValidationError("week_end must be a completed trading session")
        week_start = week_end - timedelta(days=4)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_daily_scores WHERE strategy_revision_id=?
                   AND as_of_date BETWEEN ? AND ? ORDER BY as_of_date""",
                (
                    self.runtime.revision(strategy_id)["revision_id"],
                    week_start.isoformat(),
                    week_end.isoformat(),
                ),
            ).fetchall()
        if not rows:
            return {
                "week_end": week_end.isoformat(),
                "strategy_id": strategy_id,
                "ranked_count": 0,
                "skipped": True,
                "reason": "no daily scores are available for this trading week",
            }
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
                "strategy_revision_id": self.runtime.revision(strategy_id)["revision_id"],
                "tie_policy": "composite_score_desc_symbol_asc",
                "members": members,
            },
            upstream_ids=tuple(sorted(upstream_ids)),
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM research_weekly_rankings WHERE strategy_revision_id=? AND week_end=?",
                (self.runtime.revision(strategy_id)["revision_id"], week_end.isoformat()),
            )
            connection.executemany(
                """INSERT INTO research_weekly_rankings
                   (strategy_id, strategy_revision_id, week_end, instrument_id, symbol, score, rank, artifact_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strategy_revision_id, week_end, instrument_id) DO UPDATE SET
                   score=excluded.score, rank=excluded.rank, artifact_id=excluded.artifact_id""",
                [
                    (
                        strategy_id,
                        self.runtime.revision(strategy_id)["revision_id"],
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

    def top_rankings(self, week_end: date, limit: int, strategy_id: str) -> list[dict[str, object]]:
        if not 1 <= limit <= 500:
            raise DomainValidationError("ranking limit must be between 1 and 500")
        if strategy_id not in self.runtime.strategy_ids():
            raise DomainValidationError("strategy_id is invalid")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_weekly_rankings WHERE strategy_revision_id=?
                   AND week_end=? ORDER BY rank LIMIT ?""",
                (self.runtime.revision(strategy_id)["revision_id"], week_end.isoformat(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_rankings(self, week_end: date, strategy_id: str) -> list[dict[str, object]]:
        """Return the complete published ranking for backtest universe construction."""
        if strategy_id not in self.runtime.strategy_ids():
            raise DomainValidationError("strategy_id is invalid")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_weekly_rankings WHERE strategy_revision_id=?
                   AND week_end=? ORDER BY rank""",
                (self.runtime.revision(strategy_id)["revision_id"], week_end.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def ranking_weeks(self, strategy_id: str) -> tuple[date, ...]:
        if strategy_id not in self.runtime.strategy_ids():
            raise DomainValidationError("strategy_id is invalid")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT DISTINCT week_end FROM research_weekly_rankings
                   WHERE strategy_revision_id=? ORDER BY week_end""",
                (self.runtime.revision(strategy_id)["revision_id"],),
            ).fetchall()
        return tuple(date.fromisoformat(row["week_end"]) for row in rows)

    def read_snapshot(
        self,
        kind: str,
        strategy_id: str,
        as_of_date: date | None = None,
        symbol: str | None = None,
    ) -> dict[str, object] | None:
        """Read the newest checksum-verified research snapshot matching a query.

        Research artifacts are immutable, so this read model can safely resolve
        a date or latest snapshot without exposing the artifact directory.
        """
        categories = {
            "features": f"features/{strategy_id}",
            "percentiles": "research/percentiles",
            "scores": "research/scores",
            "rankings": "research/rankings",
        }
        category = categories.get(kind)
        if category is None or strategy_id not in self.runtime.strategy_ids():
            raise DomainValidationError("research snapshot query is invalid")
        candidates: list[tuple[str, dict[str, object]]] = []
        for manifest in self.publisher.store.manifests():
            if manifest.category != category:
                continue
            try:
                _, payload = self.publisher.store.read_json(category, manifest.artifact_id)
            except DomainValidationError:
                continue
            if (
                payload.get("strategy_id") != strategy_id
                or payload.get("strategy_revision_id")
                != self.runtime.revision(strategy_id)["revision_id"]
            ):
                continue
            snapshot_date = payload.get("as_of_date", payload.get("week_end"))
            if as_of_date is not None and snapshot_date != as_of_date.isoformat():
                continue
            if symbol is not None:
                values = payload.get("values", payload.get("members", []))
                if isinstance(values, dict):
                    matches = any(
                        isinstance(value, dict) and value.get("symbol") == symbol
                        for value in values.values()
                    )
                else:
                    matches = (
                        any(
                            isinstance(value, dict) and value.get("symbol") == symbol
                            for value in values
                        )
                        if isinstance(values, list)
                        else False
                    )
                if not matches:
                    continue
            candidates.append((manifest.created_at, payload))
        if not candidates:
            return None
        _, payload = max(candidates, key=lambda item: item[0])
        return payload
