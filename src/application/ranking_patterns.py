"""Phase 4 Task 4.5: Ranking pattern dispatch for factor_score and event_signal strategies.

FactorPercentileRanking: Weekly cross-sectional percentile scoring (momentum strategy).
DirectSignalRanking: Daily event-based ADX/ADTV ordering (positional trend strategy).
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections import defaultdict

logger = logging.getLogger("screener")


class RankingPattern(ABC):
    """Base interface for ranking pattern dispatch."""

    @property
    @abstractmethod
    def pattern_name(self) -> str:
        """Identifier for this ranking pattern."""

    @abstractmethod
    def rank(
        self,
        features: dict[str, dict[str, object]],
        *,
        factor_weights: dict[str, float] | None = None,
        signal_rules: dict[str, object] | None = None,
        symbols: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        """Rank instruments and return ordered list with rank, score, and eligibility."""


class FactorPercentileRanking(RankingPattern):
    """Phase 4 Task 4.5: Cross-sectional percentile scoring for factor_score strategies.

    Stages:
      A: Raw indicator values (per-instrument, cached)
      B: Cross-sectional percentiles (across universe)
      C: Weighted composite score and ranking
    """

    @property
    def pattern_name(self) -> str:
        return "factor_percentile"

    def rank(
        self,
        features: dict[str, dict[str, object]],
        *,
        factor_weights: dict[str, float] | None = None,
        signal_rules: dict[str, object] | None = None,
        symbols: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        if not factor_weights:
            return []
        symbols = symbols or {}
        # Stage B: Compute cross-sectional percentiles per factor
        percentiles = self.compute_percentiles(features, factor_weights)
        # Stage C: Apply weights and rank
        scored: list[dict[str, object]] = []
        for instrument_id, pcts in percentiles.items():
            composite = sum(
                pcts.get(factor, 0.0) * weight
                for factor, weight in factor_weights.items()
            )
            scored.append({
                "instrument_id": instrument_id,
                "symbol": symbols.get(instrument_id, ""),
                "composite_score": round(composite, 6),
                "percentiles": pcts,
                "eligible": composite > 0,
            })
        scored.sort(key=lambda x: (-x["composite_score"], x["symbol"]))
        for rank_idx, item in enumerate(scored, start=1):
            item["rank"] = rank_idx
        return scored

    @staticmethod
    def compute_percentiles(
        features: dict[str, dict[str, object]],
        factor_weights: dict[str, float],
    ) -> dict[str, dict[str, float]]:
        """Compute cross-sectional percentile for each factor across all instruments."""
        factors = list(factor_weights.keys())
        # Collect values per factor
        factor_values: dict[str, list[tuple[str, float]]] = {f: [] for f in factors}
        for instrument_id, values in features.items():
            for factor in factors:
                val = values.get(factor)
                if val is not None:
                    try:
                        factor_values[factor].append((instrument_id, float(val)))
                    except (TypeError, ValueError):
                        pass
        # Compute percentile ranks
        result: dict[str, dict[str, float]] = defaultdict(dict)
        for factor, pairs in factor_values.items():
            if not pairs:
                continue
            sorted_pairs = sorted(pairs, key=lambda x: x[1])
            n = len(sorted_pairs)
            position = 0
            while position < n:
                tied_end = position + 1
                while tied_end < n and sorted_pairs[tied_end][1] == sorted_pairs[position][1]:
                    tied_end += 1
                percentile = ((position + 1 + tied_end) / 2) / n * 100
                for inst_id, _ in sorted_pairs[position:tied_end]:
                    result[inst_id][factor] = percentile
                position = tied_end
        return dict(result)

    @staticmethod
    def percentile_fingerprint(
        factor_weights: dict[str, float],
        universe_snapshot_id: str | None,
        indicator_code_hash: str | None,
    ) -> str:
        """Phase 4 Task 4.6: Identity fingerprint for percentile snapshot reuse.

        Weights-only changes produce a different fingerprint from indicator/universe changes.
        """
        identity = json.dumps({
            "factors": sorted(factor_weights.keys()),
            "universe": universe_snapshot_id or "",
            "indicator_code": indicator_code_hash or "",
        }, sort_keys=True)
        return hashlib.sha256(identity.encode()).hexdigest()[:16]


class DirectSignalRanking(RankingPattern):
    """Phase 4 Task 4.5/4.8: Daily event signal ranking for positional_trend_following.

    Uses ADX and ADTV for ordering among instruments with active buy signals.
    No factor percentile dependency — snapshot-scoped membership only.
    """

    @property
    def pattern_name(self) -> str:
        return "direct_signal"

    def rank(
        self,
        features: dict[str, dict[str, object]],
        *,
        factor_weights: dict[str, float] | None = None,
        signal_rules: dict[str, object] | None = None,
        symbols: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        symbols = symbols or {}
        rules = signal_rules or {}
        adx_minimum = float(rules.get("adx_minimum", 25))
        minimum_adtv = float(rules.get("minimum_adtv", 100_000_000))

        eligible: list[dict[str, object]] = []
        for instrument_id, values in features.items():
            signal = values.get("signal")
            if signal != "BUY":
                continue
            adx = float(values.get("adx", 0))
            adtv = float(values.get("adtv", 0))
            if adx < adx_minimum or adtv < minimum_adtv:
                continue
            eligible.append({
                "instrument_id": instrument_id,
                "symbol": symbols.get(instrument_id, ""),
                "adx": adx,
                "adtv": adtv,
                "signal": "BUY",
                "eligible": True,
            })
        # Sort by ADX descending, then ADTV descending, then symbol ascending
        eligible.sort(key=lambda x: (-x["adx"], -x["adtv"], x["symbol"]))
        for rank_idx, item in enumerate(eligible, start=1):
            item["rank"] = rank_idx
        return eligible


def ranking_pattern_for(kind: str) -> RankingPattern:
    """Factory: resolve ranking pattern from strategy kind."""
    if kind == "factor_score":
        return FactorPercentileRanking()
    if kind == "event_signal":
        return DirectSignalRanking()
    raise ValueError(f"unknown strategy kind: {kind}")
