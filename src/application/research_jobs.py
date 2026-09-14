"""Daily two-strategy research and weekly ranking jobs over persisted v4 bars."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.research_strategy1 import FACTOR_WEIGHTS, FORMULA_REVISION, strategy1_factors
from src.application.research_strategy2 import (
    FACTOR_WEIGHTS as STRATEGY2_FACTOR_WEIGHTS,
    FORMULA_REVISION as STRATEGY2_FORMULA_REVISION,
)
from src.application.research_strategy2 import strategy2_factors, strategy2_indicators
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.application.strategy_configs import StrategyConfigs
from src.application.yfinance_provider import download_daily_bars
from src.platform_kernel import DomainValidationError, QualityStatus


class ResearchJobs:
    def __init__(
        self, database: str | Path, market: MarketRepository, publisher: ArtifactPublisher,
        configs: StrategyConfigs | None = None,
    ):
        self.database = Path(database)
        self.market = market
        self.publisher = publisher
        self.configs = configs
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

    def sector_normalize(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {"as_of_date", "strategy_id", "feature_artifact_id", "sector_artifact_id"}
        if not isinstance(payload, dict) or set(payload) != required or payload["strategy_id"] not in {"strategy1", "strategy2"}:
            raise DomainValidationError("sector ranking command is incomplete")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except ValueError as exc:
            raise DomainValidationError("sector ranking date must be ISO date") from exc
        try:
            _, features = self.publisher.store.read_json(f"features/{payload['strategy_id']}", str(payload["feature_artifact_id"]))
            _, sectors = self.publisher.store.read_json("reference/sectors", str(payload["sector_artifact_id"]))
        except DomainValidationError as exc:
            raise DomainValidationError("feature or sector artifact was not found") from exc
        values = features.get("values")
        sector_values = sectors.get("values")
        if not isinstance(values, dict) or not isinstance(sector_values, dict):
            raise DomainValidationError("feature or sector artifact is malformed")
        instruments = [
            (str(instrument_id), item, str(sector_values[instrument_id]))
            for instrument_id, item in values.items()
            if isinstance(item, dict) and isinstance(item.get("factors"), dict) and instrument_id in sector_values and str(sector_values[instrument_id]).strip()
        ]
        if not instruments:
            raise DomainValidationError("no sector-classified factor values are available")
        factors = tuple(FACTOR_WEIGHTS)
        by_sector: dict[str, list[dict[str, float]]] = defaultdict(list)
        for _, item, sector in instruments:
            by_sector[sector].append({factor: float(item["factors"].get(factor, 0)) for factor in factors})
        members = []
        for instrument_id, item, sector in instruments:
            factor_values = {factor: float(item["factors"].get(factor, 0)) for factor in factors}
            normalized: dict[str, float] = {}
            peers = by_sector[sector]
            for factor in factors:
                average = sum(peer[factor] for peer in peers) / len(peers)
                variance = sum((peer[factor] - average) ** 2 for peer in peers) / len(peers)
                deviation = variance ** 0.5
                normalized[factor] = (factor_values[factor] - average) / deviation if deviation else 0.0
            members.append({"instrument_id": instrument_id, "symbol": item.get("symbol"), "sector": sector, "factor_zscores": normalized, "composite_score": sum(normalized[factor] * FACTOR_WEIGHTS[factor] for factor in factors)})
        members.sort(key=lambda item: (-float(item["composite_score"]), str(item["instrument_id"])))
        for rank, item in enumerate(members, 1):
            item["rank"] = rank
        artifact_id = str(uuid5(NAMESPACE_URL, "sector-ranking:" + json.dumps({"date": as_of.isoformat(), "strategy": payload["strategy_id"], "feature": payload["feature_artifact_id"], "sector": payload["sector_artifact_id"]}, sort_keys=True)))
        report = {"snapshot_id": artifact_id, "as_of_date": as_of.isoformat(), "strategy_id": payload["strategy_id"], "normalization": "within_sector_zscore", "members": members}
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json("research/sector-rankings", artifact_id, report, upstream_ids=(str(payload["feature_artifact_id"]), str(payload["sector_artifact_id"])), quality=QualityStatus.PARTIAL)
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
            raise DomainValidationError("correlation requires 2..100 instruments with sufficient bars")
        instruments = sorted(closes)
        returns: dict[str, dict[str, float]] = {
            instrument_id: {
                day: closes[instrument_id][day] / closes[instrument_id][prior] - 1
                for prior, day in zip(sorted(closes[instrument_id])[:-1], sorted(closes[instrument_id])[1:], strict=True)
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
                numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left_values, right_values, strict=True))
                left_dev = sum((value - left_mean) ** 2 for value in left_values) ** 0.5
                right_dev = sum((value - right_mean) ** 2 for value in right_values) ** 0.5
                matrix[left][right] = numerator / (left_dev * right_dev) if left_dev and right_dev else 0.0
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
        artifact_id = str(uuid5(NAMESPACE_URL, "correlations:" + json.dumps(payload, sort_keys=True)))
        report = {"snapshot_id": artifact_id, "as_of_date": as_of.isoformat(), "lookback_sessions": lookback, "correlation_threshold": threshold, "matrix": matrix, "clusters": sorted((sorted(values) for values in clusters.values()), key=lambda values: values[0])}
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json("research/correlations", artifact_id, report, upstream_ids=tuple(sorted(upstream_ids)), quality=QualityStatus.PARTIAL)
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
            ordered = sorted(bars, key=lambda item: str(item["as_of_date"]))[-(lookback + 2):]
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
            rows.append({
                "instrument_id": str(instrument_id),
                "symbol": str(identity["symbol"]),
                "latest_date": str(ordered[-1]["as_of_date"]),
                "latest_return": latest,
                "baseline_mean": average,
                "baseline_stddev": deviation,
                "z_score": score,
                "anomaly": abs(score) >= threshold,
            })
        if not rows:
            raise DomainValidationError("no instruments have sufficient return history")
        rows.sort(key=lambda item: (-abs(float(item["z_score"])), str(item["instrument_id"])))
        artifact_id = str(uuid5(NAMESPACE_URL, "research-anomalies:" + json.dumps(payload, sort_keys=True)))
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
                "research/anomalies", artifact_id, report,
                upstream_ids=tuple(sorted(upstream_ids)), quality=QualityStatus.PARTIAL,
            )
        return {"artifact_id": artifact_id, **report}

    @staticmethod
    def _configured_factor_weights(
        strategy_id: str, active_config: dict[str, object] | None
    ) -> dict[str, float]:
        """Resolve the approved revision's factor mix for one strategy."""
        defaults = FACTOR_WEIGHTS if strategy_id == "strategy1" else STRATEGY2_FACTOR_WEIGHTS
        raw = active_config["settings"].get("factor_weights") if active_config else None
        if raw is None:
            return dict(defaults)
        if not isinstance(raw, dict) or set(raw) != set(defaults):
            raise DomainValidationError("factor_weights must name every supported factor exactly once")
        try:
            parsed = {name: float(value) for name, value in raw.items()}
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("factor_weights must be numeric") from exc
        if any(not isfinite(value) or value < 0 for value in parsed.values()):
            raise DomainValidationError("factor_weights must be finite and non-negative")
        total = sum(parsed.values())
        if total <= 0:
            raise DomainValidationError("factor_weights must sum to a positive value")
        return {name: value / total for name, value in parsed.items()}

    def _calculate_day(self, payload: dict[str, Any], strategy_id: str) -> dict[str, object]:
        if set(payload) - {"as_of_date", "symbols"} or "as_of_date" not in payload or not isinstance(payload.get("as_of_date"), str):
            raise DomainValidationError("daily calculation requires as_of_date")
        requested_symbols = payload.get("symbols")
        if requested_symbols is not None and (
            not isinstance(requested_symbols, list)
            or not requested_symbols
            or len(requested_symbols) > 500
            or len(set(requested_symbols)) != len(requested_symbols)
            or any(not isinstance(symbol, str) or not symbol.strip() for symbol in requested_symbols)
        ):
            raise DomainValidationError("symbols must be a unique non-empty list of at most 500 values")
        try:
            as_of_date = date.fromisoformat(payload["as_of_date"])
        except ValueError as exc:
            raise DomainValidationError("as_of_date must be an ISO date") from exc
        active_config = self.configs.active(strategy_id, as_of_date) if self.configs else None
        config_artifact_id = str(active_config["artifact_id"]) if active_config else None
        factor_weights = self._configured_factor_weights(strategy_id, active_config)
        histories = self.market.histories(as_of_date - timedelta(days=420), as_of_date)
        benchmark: list[dict[str, object]] = []
        if strategy_id == "strategy2":
            try:
                benchmark_id = str(self.market.instrument("NIFTY 500")["instrument_id"])
                benchmark = histories[benchmark_id][0]
            except (DomainValidationError, KeyError) as exc:
                # Preserve the v3 Kite→YFinance fallback for migrations where
                # the benchmark has not yet been imported into the v4 store.
                try:
                    benchmark = download_daily_bars("^CNX500", as_of_date - timedelta(days=420), as_of_date)
                except DomainValidationError:
                    raise DomainValidationError("NIFTY 500 benchmark history is required") from exc
            if benchmark[-1]["as_of_date"] != as_of_date.isoformat():
                raise DomainValidationError("NIFTY 500 benchmark is stale for requested date")
        results: dict[str, dict[str, object]] = {}
        symbols: dict[str, str] = {}
        upstream_ids: set[str] = set()
        for instrument_id, (bars, identity) in histories.items():
            if requested_symbols is not None and instrument_id not in requested_symbols and identity["symbol"] not in requested_symbols:
                continue
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
                "config_revision_id": active_config["revision_id"] if active_config else None,
                "factor_weights": factor_weights,
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
            upstream_ids=tuple(sorted(upstream_ids | ({config_artifact_id} if config_artifact_id else set()))),
            quality=QualityStatus.PARTIAL
            if strategy_id == "strategy2" or len(results) < len(histories)
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
                "config_revision_id": active_config["revision_id"] if active_config else None,
                "factor_weights": factor_weights,
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
                "config_revision_id": active_config["revision_id"] if active_config else None,
                "factor_weights": factor_weights,
                "percentile_snapshot_id": percentile_id,
                "values": scores,
            },
            upstream_ids=tuple(
                item for item in (percentile_id, config_artifact_id) if item is not None
            ),
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            # A recomputation can shrink the universe. Replace the complete
            # date projection so removed instruments cannot survive as stale
            # scores and later leak into weekly rankings.
            if requested_symbols is None:
                connection.execute(
                    "DELETE FROM research_daily_scores WHERE strategy_id=? AND as_of_date=?",
                    (strategy_id, as_of_date.isoformat()),
                )
            else:
                connection.executemany(
                    "DELETE FROM research_daily_scores WHERE strategy_id=? AND as_of_date=? AND (instrument_id=? OR symbol=?)",
                    [(strategy_id, as_of_date.isoformat(), symbol, symbol) for symbol in requested_symbols],
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
                "formula_revision": FORMULA_REVISION if strategy_id == "strategy1" else STRATEGY2_FORMULA_REVISION,
                "tie_policy": "composite_score_desc_symbol_asc",
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
        if category is None or strategy_id not in {"strategy1", "strategy2"}:
            raise DomainValidationError("research snapshot query is invalid")
        candidates: list[tuple[str, dict[str, object]]] = []
        for manifest in self.publisher.store.manifests():
            if manifest.category != category:
                continue
            try:
                _, payload = self.publisher.store.read_json(category, manifest.artifact_id)
            except DomainValidationError:
                continue
            if payload.get("strategy_id") != strategy_id:
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
                    matches = any(
                        isinstance(value, dict) and value.get("symbol") == symbol
                        for value in values
                    ) if isinstance(values, list) else False
                if not matches:
                    continue
            candidates.append((manifest.created_at, payload))
        if not candidates:
            return None
        _, payload = max(candidates, key=lambda item: item[0])
        return payload

    def compare_strategy2_parity(self, payload: dict[str, Any]) -> dict[str, object]:
        """Publish a deterministic comparison against a frozen v3 factor baseline."""
        required = {"as_of_date", "strategy_id", "feature_artifact_id", "legacy_factors"}
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or payload["strategy_id"] != "strategy2"
        ):
            raise DomainValidationError("parity command is incomplete")
        try:
            as_of = date.fromisoformat(str(payload["as_of_date"]))
        except ValueError as exc:
            raise DomainValidationError("parity date must be ISO date") from exc
        legacy = payload["legacy_factors"]
        if not isinstance(legacy, dict) or not 1 <= len(legacy) <= 500:
            raise DomainValidationError("legacy_factors must contain 1..500 instruments")
        try:
            _, features = self.publisher.store.read_json(
                f"features/{payload['strategy_id']}", str(payload["feature_artifact_id"])
            )
        except DomainValidationError as exc:
            raise DomainValidationError("feature artifact was not found") from exc
        if features.get("as_of_date") != as_of.isoformat() or features.get("strategy_id") != payload["strategy_id"]:
            raise DomainValidationError("feature artifact does not match the parity request")
        values = features.get("values")
        if not isinstance(values, dict):
            raise DomainValidationError("feature artifact is malformed")
        factors = tuple(FACTOR_WEIGHTS)
        normalized_legacy: dict[str, dict[str, float]] = {}
        deltas: dict[str, dict[str, float]] = {}
        for instrument_id, baseline in legacy.items():
            current = values.get(str(instrument_id))
            if not isinstance(baseline, dict) or not isinstance(current, dict):
                raise DomainValidationError("parity instrument factors are malformed")
            current_factors = current.get("factors")
            if not isinstance(current_factors, dict):
                raise DomainValidationError("feature artifact has no factor values")
            normalized: dict[str, float] = {}
            difference: dict[str, float] = {}
            for factor in factors:
                raw = baseline.get(factor, baseline.get(f"factor_{factor}"))
                if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                    raise DomainValidationError("legacy factor values must be numeric")
                try:
                    legacy_value = float(raw)
                    current_value = float(current_factors[factor])
                except (KeyError, TypeError, ValueError) as exc:
                    raise DomainValidationError("legacy factor values must be numeric") from exc
                if not isfinite(legacy_value) or not isfinite(current_value):
                    raise DomainValidationError("legacy factor values must be finite")
                normalized[factor] = legacy_value
                difference[factor] = current_value - legacy_value
            normalized_legacy[str(instrument_id)] = normalized
            deltas[str(instrument_id)] = difference
        report = {
            "as_of_date": as_of.isoformat(),
            "strategy_id": payload["strategy_id"],
            "feature_artifact_id": str(payload["feature_artifact_id"]),
            "v4_formula_revision": features.get("formula_revision"),
            "v3_formula_revision": "v3-archived-factors-service-v2",
            "tie_policy": "score_desc_symbol_asc",
            "legacy_factors": normalized_legacy,
            "v4_feature_values": {
                key: values[key] for key in sorted(normalized_legacy)
            },
            "factor_deltas": deltas,
        }
        artifact_id = str(uuid5(NAMESPACE_URL, "research-parity:" + json.dumps(report, sort_keys=True)))
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "research/parity", artifact_id,
                {"snapshot_id": artifact_id, **report},
                upstream_ids=(str(payload["feature_artifact_id"]),),
            )
        return {"artifact_id": artifact_id, "as_of_date": as_of.isoformat(), "strategy_id": payload["strategy_id"], "compared_count": len(normalized_legacy)}

    def compare_strategy2_candidates(self, payload: dict[str, Any]) -> dict[str, object]:
        """Publish a deterministic v3/v4 candidate-set and rank comparison."""
        required = {"week_end", "ranking_artifact_id", "legacy_candidates"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise DomainValidationError("candidate parity command is incomplete")
        try:
            week_end = date.fromisoformat(str(payload["week_end"]))
        except ValueError as exc:
            raise DomainValidationError("candidate parity date must be ISO date") from exc
        legacy_rows = payload["legacy_candidates"]
        if not isinstance(legacy_rows, list) or not 1 <= len(legacy_rows) <= 500:
            raise DomainValidationError("legacy_candidates must contain 1..500 rows")
        try:
            _, ranking = self.publisher.store.read_json(
                "research/rankings", str(payload["ranking_artifact_id"])
            )
        except DomainValidationError as exc:
            raise DomainValidationError("ranking artifact was not found") from exc
        if ranking.get("strategy_id") != "strategy2" or ranking.get("week_end") != week_end.isoformat():
            raise DomainValidationError("ranking artifact does not match candidate parity")
        current_rows = ranking.get("members")
        if not isinstance(current_rows, list) or len(current_rows) > 500:
            raise DomainValidationError("ranking artifact members are malformed")

        def normalize(rows: list[object], label: str) -> dict[str, dict[str, object]]:
            result: dict[str, dict[str, object]] = {}
            for index, row in enumerate(rows, 1):
                if isinstance(row, str):
                    identity, symbol, rank = row, row, index
                elif isinstance(row, dict):
                    identity = row.get("instrument_id", row.get("symbol"))
                    symbol = row.get("symbol", identity)
                    rank = row.get("rank", index)
                else:
                    raise DomainValidationError(f"{label} rows are malformed")
                if not isinstance(identity, str) or not identity.strip() or not isinstance(symbol, str):
                    raise DomainValidationError(f"{label} rows are malformed")
                if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
                    raise DomainValidationError(f"{label} ranks are invalid")
                if identity in result:
                    raise DomainValidationError(f"{label} contains duplicate instruments")
                result[identity] = {"instrument_id": identity, "symbol": symbol, "rank": rank}
            return result

        legacy = normalize(legacy_rows, "legacy candidate")
        current = normalize(current_rows, "v4 candidate")
        all_ids = sorted(set(legacy) | set(current))
        comparisons = []
        for instrument_id in all_ids:
            old = legacy.get(instrument_id)
            new = current.get(instrument_id)
            comparisons.append({
                "instrument_id": instrument_id,
                "symbol": (new or old)["symbol"],
                "v3_rank": old["rank"] if old else None,
                "v4_rank": new["rank"] if new else None,
                "rank_delta": new["rank"] - old["rank"] if old and new else None,
                "status": "UNCHANGED" if old and new else "ADDED" if new else "REMOVED",
            })
        report = {
            "snapshot_id": "",
            "week_end": week_end.isoformat(),
            "strategy_id": "strategy2",
            "ranking_artifact_id": str(payload["ranking_artifact_id"]),
            "v3_formula_revision": "v3-archived-score-service",
            "v4_formula_revision": ranking.get("formula_revision"),
            "tie_policy": ranking.get("tie_policy"),
            "v3_candidates": legacy,
            "v4_candidates": current,
            "comparisons": comparisons,
            "added": sorted(set(current) - set(legacy)),
            "removed": sorted(set(legacy) - set(current)),
        }
        artifact_id = str(
            uuid5(NAMESPACE_URL, "research-candidate-parity:" + json.dumps(report, sort_keys=True))
        )
        report["snapshot_id"] = artifact_id
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "research/candidate-parity", artifact_id, report,
                upstream_ids=(str(payload["ranking_artifact_id"]),),
            )
        return {
            "artifact_id": artifact_id,
            "week_end": week_end.isoformat(),
            "strategy_id": "strategy2",
            "compared_count": len(comparisons),
            "added_count": len(report["added"]),
            "removed_count": len(report["removed"]),
        }
