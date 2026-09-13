"""Provider ingestion composition: raw evidence first, then normalized output."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Iterable

from src.application.publication import ArtifactPublisher
from src.application.security import sanitize_sensitive
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactManifest, DomainValidationError, QualityStatus


def ingest_market_bars(
    publisher: ArtifactPublisher,
    provider: str,
    bars: Iterable[NormalizedBar],
    *,
    source_request: dict[str, object],
    raw_payload: object | None = None,
    provider_version: str = "unknown",
    retrieved_at: datetime | None = None,
    quality: QualityStatus = QualityStatus.COMPLETE,
) -> tuple[ArtifactManifest, ArtifactManifest]:
    """Persist redacted request evidence before the normalized immutable snapshot."""
    if not provider.strip():
        raise DomainValidationError("provider must be non-empty")
    normalized = tuple(sorted(bars, key=lambda bar: (bar.instrument_id, bar.as_of_date)))
    keys = [(bar.instrument_id, bar.as_of_date) for bar in normalized]
    if not normalized or len(keys) != len(set(keys)):
        raise DomainValidationError("provider returned no market bars")
    # Publish through the recoverable application publisher rather than calling
    # domain helpers directly, preserving catalog/file reconciliation.
    from uuid import uuid4
    raw_id = uuid4()
    retrieved = retrieved_at or datetime.now(UTC)
    if retrieved.tzinfo is None or retrieved.utcoffset() is None:
        raise DomainValidationError("retrieved_at must be timezone-aware")
    evidence = raw_payload if raw_payload is not None else [asdict(bar) for bar in normalized]
    raw = publisher.publish_json(
        f"market/raw/{provider}",
        str(raw_id),
        {
            "snapshot_id": str(raw_id),
            "provider": provider,
            "provider_version": provider_version,
            "retrieved_at": retrieved,
            "request": sanitize_sensitive(source_request),
            "response": sanitize_sensitive(evidence),
            "capture": "provider_raw" if raw_payload is not None else "normalized_fallback",
            "record_count": len(normalized),
        },
        quality=quality,
    )
    normalized_id = uuid4()
    normalized_manifest = publisher.publish_json(
        f"market/normalized/{provider}",
        str(normalized_id),
        {
            "snapshot_id": str(normalized_id),
            "provider": provider,
            "raw_snapshot_id": str(raw_id),
            "bars": [asdict(bar) for bar in normalized],
            "record_count": len(normalized),
        },
        upstream_ids=(raw.artifact_id,),
        quality=quality,
    )
    return raw, normalized_manifest
