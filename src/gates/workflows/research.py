"""Staged bulk research and ranking over active strategy revisions."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging

logger = logging.getLogger("screener." + __name__)
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.domains.artifacts import ArtifactPublisher
from src.domains.indicators import (
    DagExecutor,
    DagGraph,
    PandasTaAdapter,
    momentum_quality_indicator_series,
    relative_strength_feature_series,
)
from src.domains.operations import JobExecutionContext
from src.domains.research import (
    ResearchRepository,
    correlation_clusters,
    detect_return_anomalies,
    rank_sector_factors,
    weekly_ranking_members,
)
from src.domains.strategies import momentum_quality_from_indicators, ranking_pattern_for
from src.gates.repositories import MarketRepository
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.platform_kernel import DomainValidationError, QualityStatus


class ResearchJobs:
    def __init__(
        self,
        database: str | Path,
        market: MarketRepository,
        publisher: ArtifactPublisher,
        runtime: StrategyRuntime | None = None,
        node_cache: Any = None,  # IndicatorNodeCache
    ):
        self.database = Path(database)
        self.market = market
        self.publisher = publisher
        self.runtime = runtime or StrategyRuntime(StrategyDefinitions(database, PandasTaAdapter()))
        self.node_cache = node_cache
        if runtime is None:
            self.runtime.seed(Path(__file__).resolve().parents[3] / "strategies")
        self.research_store = ResearchRepository(self.database)

    @staticmethod
    def _indicator_set(strategy_id: str, benchmark_name: str | None) -> str:
        """Stable raw-input namespace; weights and score rules never belong here."""
        if strategy_id == "momentum":
            return "momentum:quality-v2"
        raise DomainValidationError(
            f"strategy '{strategy_id}' has no raw-indicator cache definition"
        )

    def calculate_day(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._calculate_day(payload)

    def rebuild_indicators(
        self, payload: dict[str, Any], context: JobExecutionContext
    ) -> dict[str, object]:
        """Build reusable raw strategy inputs independently of factors and scores."""
        from src.gates.payloads import RebuildIndicatorsPayload

        parsed = RebuildIndicatorsPayload.from_dict(
            payload,
            default_strategies=tuple(
                strategy_id
                for strategy_id in self.runtime.strategy_ids()
                if self.runtime.strategy_kind(strategy_id) != "event_signal"
            ),
        )
        start, end, requested = parsed.start_date, parsed.end_date, parsed.strategies
        histories = self.market.histories(start - timedelta(days=900), end)
        eligible = [
            item for item in histories.items() if not str(item[1][1]["isin"]).startswith("INDEX:")
        ]
        results: dict[str, dict[str, object]] = {}
        for strategy_id in requested:
            if self.runtime.strategy_kind(strategy_id) == "event_signal":
                raise DomainValidationError(
                    f"{strategy_id} is a daily event strategy; use its dedicated signal job"
                )
            revision = self.runtime.revision(strategy_id)
            compiled_dag = revision["definition"].get("_compiled_dag")

            benchmark: list[dict[str, object]] = []
            benchmark_name = self.runtime.benchmark(strategy_id)
            if benchmark_name:
                benchmark_id = str(self.market.instrument(benchmark_name)["instrument_id"])
                benchmark = histories[benchmark_id][0]

            if compiled_dag is not None and getattr(self, "node_cache", None) is not None:
                import pandas as pd

                graph = DagGraph.from_dict(compiled_dag)
                executor = DagExecutor(self.runtime._adapter)
                graph_hashes = graph.unique_content_hashes()
                node_hashes = set(graph_hashes.values())
                import hashlib

                code_root = Path(__file__).resolve().parents[2] / "indicators"
                identity = hashlib.sha256(
                    json.dumps(
                        {
                            "adapter": self.runtime._adapter.adapter_version,
                            "pandas_ta": self.runtime._adapter.package_version,
                            "pandas": pd.__version__,
                            "numpy": version("numpy"),
                        },
                        sort_keys=True,
                    ).encode()
                )
                for code_file in sorted(code_root.rglob("*.py")):
                    identity.update(code_file.relative_to(code_root).as_posix().encode())
                    identity.update(code_file.read_bytes())
                identity.update(Path(__file__).read_bytes())
                implementation_revision = identity.hexdigest()
                instrument_revisions = self.market.market_history_revisions(
                    str(instrument_id) for instrument_id, _ in eligible
                )
                # Pull existing cache across all instruments
                cached = self.node_cache.get_bulk(
                    node_hashes,
                    start,
                    end,
                    revisions=instrument_revisions,
                    implementation_revision=implementation_revision,
                )

                bench_df = pd.DataFrame(benchmark) if benchmark else None
                written = 0
                for index, (instrument_id, (bars, _identity)) in enumerate(eligible, start=1):
                    if not bars:
                        continue

                    ohlcv = pd.DataFrame(bars)
                    ohlcv["as_of_date"] = pd.to_datetime(ohlcv["as_of_date"]).dt.date
                    mask = (ohlcv["as_of_date"] >= start) & (ohlcv["as_of_date"] <= end)

                    # Fetch precomputed series from our cache
                    precomputed: dict[str, pd.Series] = {}
                    for node in graph.execution_order():
                        node_hash = graph_hashes[node.node_id]
                        if node_hash in cached and instrument_id in cached[node_hash]:
                            # Map date string to float values
                            date_vals = cached[node_hash][instrument_id]
                            # Create a Series aligned to the OHLCV index
                            series_idx = []
                            series_vals = []
                            for i, d in enumerate(ohlcv["as_of_date"]):
                                d_str = str(d)
                                if d_str in date_vals:
                                    series_idx.append(i)
                                    series_vals.append(date_vals[d_str])
                            if series_idx:
                                precomputed[node.node_id] = pd.Series(
                                    series_vals, index=series_idx
                                ).reindex(ohlcv.index)

                    node_results = executor.execute(graph, ohlcv, bench_df, precomputed=precomputed)

                    # Put back computed nodes into cache
                    for node in graph.execution_order():
                        if node.node_id in node_results and node.node_id not in precomputed:
                            res_series = node_results[node.node_id]
                            # Filter to requested date range
                            res_series = res_series[mask]
                            if not res_series.empty:
                                to_cache = {}
                                dates = ohlcv.loc[res_series.index, "as_of_date"]
                                for d, val in zip(dates, res_series):
                                    if pd.notna(val):
                                        to_cache[str(d)] = float(val)
                                if to_cache:
                                    written += self.node_cache.put_bulk(
                                        graph_hashes[node.node_id],
                                        {instrument_id: to_cache},
                                        f"job:rebuild-indicators:{strategy_id}",
                                        market_revisions={
                                            instrument_id: instrument_revisions[instrument_id]
                                        },
                                        implementation_revision=implementation_revision,
                                    )

                    if index % 25 == 0 or index == len(eligible):
                        context.checkpoint(
                            progress={
                                "stage": "indicator_cache (DAG)",
                                "strategy": strategy_id,
                                "processed_instruments": index,
                                "total_instruments": len(eligible),
                            }
                        )

                results[strategy_id] = {"indicator_set": "dag-cache", "rows": written}

            else:
                # Python implementation dispatch
                by_date: dict[date, dict[str, dict[str, object]]] = defaultdict(dict)
                for index, (instrument_id, (bars, _identity)) in enumerate(eligible, start=1):
                    series = (
                        momentum_quality_indicator_series(bars)
                        if strategy_id in ("momentum",)
                        else relative_strength_feature_series(bars, benchmark)
                    )
                    for day, values in series.items():
                        parsed_date = date.fromisoformat(day)
                        if start <= parsed_date <= end:
                            by_date[parsed_date][instrument_id] = values
                    if index % 25 == 0 or index == len(eligible):
                        context.checkpoint(
                            progress={
                                "stage": "indicator_cache",
                                "strategy": strategy_id,
                                "processed_instruments": index,
                                "total_instruments": len(eligible),
                            }
                        )
                indicator_set = self._indicator_set(strategy_id, benchmark_name)
                written = sum(
                    self.market.upsert_indicators(
                        indicator_set,
                        day,
                        values,
                        f"indicator-cache:{indicator_set}:{day.isoformat()}",
                    )
                    for day, values in sorted(by_date.items())
                )
                results[strategy_id] = {"indicator_set": indicator_set, "rows": written}
        return {"strategies": results, "start_date": start.isoformat(), "end_date": end.isoformat()}

    def rebuild_range(
        self, payload: dict[str, Any], context: JobExecutionContext
    ) -> dict[str, object]:
        from src.gates.payloads import RebuildRangePayload

        parsed = RebuildRangePayload.from_dict(payload)
        parsed.validate(tuple(self.runtime.strategy_ids()))
        start, end = parsed.start_date, parsed.end_date
        sessions, strategies = parsed.trading_dates, parsed.strategies

        started = perf_counter()
        timings: dict[str, float] = {}
        cache_only_momentum = (
            isinstance(self.runtime, StrategyRuntime)
            and strategies == ("momentum",)
        )
        context.checkpoint(
            progress={
                "stage": "loading_indicator_cache"
                if cache_only_momentum
                else "loading_market_history",
                "stage_number": 1,
                "stage_count": 4,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "strategies": list(strategies),
                "sessions": len(sessions),
                "detail": (
                    "Loading cached momentum inputs and instrument identities."
                    if cache_only_momentum
                    else "Loading the shared warm-up history once for this range."
                ),
            }
        )
        stage_started = perf_counter()
        histories = (
            {} if cache_only_momentum else self.market.histories(start - timedelta(days=900), end)
        )
        identities = (
            {
                str(item["instrument_id"]): item
                for item in self.market.tracked_instruments()
                if not str(item["isin"]).startswith("INDEX:")
            }
            if cache_only_momentum
            else {}
        )
        timings["loading_indicator_cache" if cache_only_momentum else "loading_market_history"] = (
            perf_counter() - stage_started
        )
        session_keys = {item.isoformat() for item in sessions}
        completed: dict[str, dict[str, int]] = {}

        for strategy_index, strategy_id in enumerate(strategies, start=1):
            if self.runtime.strategy_kind(strategy_id) == "event_signal":
                raise DomainValidationError(
                    f"{strategy_id} is a daily event strategy; use its dedicated signal job"
                )
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
            use_indicator_cache = strategy_id in {"momentum"} and isinstance(
                self.runtime, StrategyRuntime
            )
            cached_indicators = (
                self.market.indicator_series(
                    self._indicator_set(strategy_id, benchmark_name), start, end
                )
                if use_indicator_cache
                else {}
            )
            if use_indicator_cache and not cached_indicators:
                raise DomainValidationError(
                    f"{strategy_id} indicator cache is missing; run research.rebuild-indicators"
                )
            missing_sessions = session_keys - {
                day for series in cached_indicators.values() for day in series
            }
            if use_indicator_cache and missing_sessions:
                raise DomainValidationError(
                    f"{strategy_id} indicator cache is incomplete; rebuild missing sessions"
                )
            eligible_histories = (
                [
                    (instrument_id, (), identity)
                    for instrument_id, identity in identities.items()
                    if instrument_id in cached_indicators
                ]
                if cache_only_momentum
                else [
                    (instrument_id, bars, identity)
                    for instrument_id, (bars, identity) in histories.items()
                    if not str(identity["isin"]).startswith("INDEX:")
                ]
            )
            for index, (instrument_id, bars, identity) in enumerate(eligible_histories, start=1):
                if use_indicator_cache:
                    raw_series = cached_indicators.get(instrument_id, {})
                    series = (
                        {
                            day: momentum_quality_from_indicators(values)
                            for day, values in raw_series.items()
                        }
                        if strategy_id in ("momentum",)
                        else raw_series
                    )
                else:
                    series = self.runtime.compute_series(strategy_id, bars, benchmark)
                symbols[instrument_id] = str(identity["symbol"])
                for day, values in series.items():
                    if day in session_keys:
                        features_by_date[day][instrument_id] = values
                if index % 25 == 0 or index == len(eligible_histories):
                    context.checkpoint(
                        progress={
                            "stage": "factors" if use_indicator_cache else "indicators",
                            "stage_number": 1,
                            "stage_count": 4,
                            "strategy": strategy_id,
                            "strategy_number": strategy_index,
                            "strategy_count": len(strategies),
                            "processed_instruments": index,
                            "total_instruments": len(eligible_histories),
                            "completed_percent": round(index / len(eligible_histories) * 100, 1),
                            "detail": (
                                "Deriving strategy factors from cached indicators."
                                if use_indicator_cache
                                else "Computing every session's rolling indicators once per instrument."
                            ),
                        }
                    )
            timings[f"{strategy_id}:{'factors' if use_indicator_cache else 'indicators'}"] = (
                perf_counter() - stage_started
            )

            stage_started = perf_counter()
            percentiles_by_date: dict[str, dict[str, dict[str, float]]] = {}
            membership_lineage = {}
            for session in sessions:
                snapshot = self.market.universe_snapshot_as_of("NIFTY 500", session)
                snapshot_id = parsed.universe_snapshot_id or (
                    str(snapshot["snapshot_id"]) if snapshot else None
                )
                if not snapshot_id:
                    raise DomainValidationError("NIFTY 500 snapshot is required for research")
                member_isins = {
                    row["isin"]
                    for row in self.market.universe_snapshot_members(snapshot_id, limit=1000)
                }
                allowed_ids = {
                    row["instrument_id"]
                    for row in self.market.tracked_instruments()
                    if row["exchange"] == "NSE" and row["isin"] in member_isins
                }
                day = session.isoformat()
                features_by_date[day] = {
                    key: value for key, value in features_by_date[day].items() if key in allowed_ids
                }
                membership_lineage[day] = snapshot_id
            for index, session in enumerate(sessions, start=1):
                day = session.isoformat()
                values = features_by_date[day]
                percentiles = {instrument_id: {} for instrument_id in values}
                if values:
                    cross_section = self.runtime.cross_section(strategy_id, values)
                    if cross_section is not None:
                        for instrument_id, factors in cross_section.items():
                            values[instrument_id]["factors"] = factors

                    raw_factors = {key: value["factors"] for key, value in values.items()}
                    ranking_pattern_source = inspect.getsourcefile(ranking_pattern_for)
                    if ranking_pattern_source is None:
                        raise DomainValidationError("ranking implementation source is unavailable")
                    percentile_fingerprint = hashlib.sha256(
                        json.dumps(
                            {
                                "as_of_date": day,
                                "factors": raw_factors,
                                "factor_names": sorted(factor_weights),
                                "universe": membership_lineage[day],
                                "percentile_rule": "average-ties-v1",
                                "market_revisions": self.market.market_history_revisions(values),
                                "percentile_code": hashlib.sha256(
                                    Path(ranking_pattern_source).read_bytes()
                                ).hexdigest(),
                            },
                            sort_keys=True,
                            default=str,
                        ).encode()
                    ).hexdigest()
                    percentiles = self.read_percentile_snapshot(percentile_fingerprint, day)
                    if percentiles is None:
                        pattern = ranking_pattern_for(self.runtime.strategy_kind(strategy_id))
                        percentiles = pattern.compute_percentiles(raw_factors, factor_weights)
                        self.upsert_percentile_snapshot(
                            percentile_fingerprint,
                            revision_id,
                            day,
                            percentile_fingerprint,
                            {
                                key: {
                                    factor: (raw_factors[key][factor], value)
                                    for factor, value in factors.items()
                                }
                                for key, factors in percentiles.items()
                            },
                            symbols=symbols,
                            universe_snapshot_id=membership_lineage[day],
                            indicator_code_hash="average-ties-v1",
                        )
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
                    f"research-range:{revision_id}:{start.isoformat()}:{end.isoformat()}:"
                    + hashlib.sha256(
                        json.dumps(
                            {"features": features_by_date, "membership": membership_lineage},
                            sort_keys=True,
                            default=str,
                        ).encode()
                    ).hexdigest(),
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
                        * self.runtime.factor_multiplier(strategy_id, factor, values)
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
            self.research_store.replace_daily_score_range(
                revision_id, start.isoformat(), end.isoformat(), score_rows
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
                        "universe_snapshots": membership_lineage,
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
        weights = self.runtime.factor_weights(str(payload["strategy_id"]))
        members = rank_sector_factors(values, sector_values, weights)
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
        matrix, clusters = correlation_clusters(closes, threshold)
        artifact_id = str(
            uuid5(NAMESPACE_URL, "correlations:" + json.dumps(payload, sort_keys=True))
        )
        report = {
            "snapshot_id": artifact_id,
            "as_of_date": as_of.isoformat(),
            "lookback_sessions": lookback,
            "correlation_threshold": threshold,
            "matrix": matrix,
            "clusters": clusters,
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
        rows, upstream_ids = detect_return_anomalies(histories, lookback, threshold, minimum)
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
        score_rows = [
            (
                strategy_id,
                str(revision["revision_id"]),
                as_of_date.isoformat(),
                key,
                symbols[key],
                value["composite_score"],
                value["penalty"],
                score_id,
            )
            for key, value in scores.items()
        ]
        self.research_store.upsert_daily_scores_for_date(
            str(revision["revision_id"]),
            as_of_date.isoformat(),
            score_rows,
            tuple(requested_symbols) if requested_symbols is not None else None,
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
        rows = self.research_store.daily_scores(
            str(self.runtime.revision(strategy_id)["revision_id"]),
            week_start.isoformat(),
            week_end.isoformat(),
        )
        if not rows:
            return {
                "week_end": week_end.isoformat(),
                "strategy_id": strategy_id,
                "ranked_count": 0,
                "skipped": True,
                "reason": "no daily scores are available for this trading week",
            }
        members, upstream_ids = weekly_ranking_members(rows)
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
        self.research_store.replace_weekly_rankings(
            strategy_id,
            str(self.runtime.revision(strategy_id)["revision_id"]),
            week_end.isoformat(),
            artifact_id,
            members,
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
        return self.research_store.top_rankings(
            str(self.runtime.revision(strategy_id)["revision_id"]), week_end.isoformat(), limit
        )

    def all_rankings(self, week_end: date, strategy_id: str) -> list[dict[str, object]]:
        """Return the complete published ranking for backtest universe construction."""
        if strategy_id not in self.runtime.strategy_ids():
            raise DomainValidationError("strategy_id is invalid")
        return self.research_store.all_rankings(
            str(self.runtime.revision(strategy_id)["revision_id"]), week_end.isoformat()
        )

    def ranking_weeks(self, strategy_id: str) -> tuple[date, ...]:
        if strategy_id not in self.runtime.strategy_ids():
            raise DomainValidationError("strategy_id is invalid")
        return tuple(
            date.fromisoformat(value)
            for value in self.research_store.ranking_weeks(
                str(self.runtime.revision(strategy_id)["revision_id"])
            )
        )

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

    # Phase 4 Task 4.6: Percentile snapshot persistence

    def upsert_percentile_snapshot(
        self,
        snapshot_id: str,
        strategy_revision_id: str,
        as_of_date: str,
        input_fingerprint: str,
        percentiles: dict[str, dict[str, tuple[float | None, float]]],
        symbols: dict[str, str],
        *,
        universe_snapshot_id: str | None = None,
        indicator_code_hash: str | None = None,
    ) -> dict[str, object]:
        return self.research_store.upsert_percentile_snapshot(
            snapshot_id,
            strategy_revision_id,
            as_of_date,
            input_fingerprint,
            percentiles,
            symbols,
            universe_snapshot_id=universe_snapshot_id,
            indicator_code_hash=indicator_code_hash,
        )

    def read_percentile_snapshot(
        self, input_fingerprint: str, as_of_date: str
    ) -> dict[str, dict[str, float]] | None:
        return self.research_store.read_percentile_snapshot(input_fingerprint, as_of_date)

    # Phase 4 Task 4.10: Research artifact lineage

    def record_lineage(
        self,
        artifact_id: str,
        strategy_id: str,
        strategy_revision_id: str,
        *,
        indicator_code_hash: str | None = None,
        universe_snapshot_id: str | None = None,
        market_data_start: str | None = None,
        market_data_end: str | None = None,
        market_history_revision: str | None = None,
        percentile_snapshot_id: str | None = None,
    ) -> None:
        self.research_store.record_lineage(
            artifact_id,
            strategy_id,
            strategy_revision_id,
            indicator_code_hash=indicator_code_hash,
            universe_snapshot_id=universe_snapshot_id,
            market_data_start=market_data_start,
            market_data_end=market_data_end,
            market_history_revision=market_history_revision,
            percentile_snapshot_id=percentile_snapshot_id,
        )

    def read_lineage(self, artifact_id: str) -> dict[str, object] | None:
        return self.research_store.read_lineage(artifact_id)
