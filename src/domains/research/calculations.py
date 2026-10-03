"""Pure research ranking and market-statistics calculations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean, pstdev

from src.platform_kernel import DomainValidationError


def rank_sector_factors(
    values: Mapping[str, object],
    sector_values: Mapping[str, object],
    weights: Mapping[str, float],
) -> list[dict[str, object]]:
    """Z-score each factor within sector and rank by weighted composite score."""
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
            normalized[factor] = (factor_values[factor] - average) / deviation if deviation else 0.0
        members.append(
            {
                "instrument_id": instrument_id,
                "symbol": item.get("symbol"),
                "sector": sector,
                "factor_zscores": normalized,
                "composite_score": sum(normalized[factor] * weights[factor] for factor in factors),
            }
        )
    members.sort(key=lambda item: (-float(item["composite_score"]), str(item["instrument_id"])))
    for rank, item in enumerate(members, 1):
        item["rank"] = rank
    return members


def correlation_clusters(
    closes: Mapping[str, Mapping[str, float]], threshold: float
) -> tuple[dict[str, dict[str, float]], list[list[str]]]:
    """Calculate Pearson correlations of aligned returns and cluster by threshold."""
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
            if not left_values:
                matrix[left][right] = 0.0
                continue
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
    ordered_clusters = sorted(
        (sorted(values) for values in clusters.values()), key=lambda values: values[0]
    )
    return matrix, ordered_clusters


def detect_return_anomalies(
    histories: Mapping[str, tuple[Sequence[Mapping[str, object]], Mapping[str, object]]],
    lookback: int,
    threshold: float,
    minimum: int,
) -> tuple[list[dict[str, object]], set[str]]:
    """Compare each latest return with its preceding bounded return distribution."""
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
    rows.sort(key=lambda item: (-abs(float(item["z_score"])), str(item["instrument_id"])))
    return rows, upstream_ids


def weekly_ranking_members(
    rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], set[str]]:
    """Average daily scores per instrument and rank with the published tie policy."""
    grouped: dict[str, list[float]] = defaultdict(list)
    symbols: dict[str, str] = {}
    upstream_ids: set[str] = set()
    for row in rows:
        instrument_id = str(row["instrument_id"])
        grouped[instrument_id].append(float(row["score"]))
        symbols[instrument_id] = str(row["symbol"])
        upstream_ids.add(str(row["artifact_id"]))
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
    return members, upstream_ids


__all__ = [
    "correlation_clusters",
    "detect_return_anomalies",
    "rank_sector_factors",
    "weekly_ranking_members",
]
