"""Cataloged publication of completed research runs."""

from src.application.publication import ArtifactPublisher
from src.backtesting import BacktestResult
from src.platform_kernel import ArtifactManifest


def publish_backtest_result(
    publisher: ArtifactPublisher,
    result: BacktestResult,
) -> ArtifactManifest:
    """Publish a complete backtest through the recoverable catalog protocol."""
    return publisher.publish_json(
        "runs/backtests",
        str(result.run_id),
        result.to_payload(),
        upstream_ids=result.upstream_ids,
    )
