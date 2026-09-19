"""Framework-free contracts shared by the target modular monolith.

The package is intentionally small.  It may not import Flask, SQLAlchemy,
provider SDKs, or application adapters.
"""

from .api import (
    ArtifactManifest,
    ArtifactStore,
    Broker,
    CommandMetadata,
    DomainValidationError,
    FrozenDict,
    HistoricalBarsProvider,
    InstrumentProvider,
    LiveQuoteProvider,
    Money,
    QualityStatus,
    Quantity,
    SqliteArtifactStore,
    VersionedReference,
    freeze_value,
)

__all__ = [
    "ArtifactManifest",
    "ArtifactStore",
    "Broker",
    "CommandMetadata",
    "DomainValidationError",
    "FrozenDict",
    "HistoricalBarsProvider",
    "InstrumentProvider",
    "LiveQuoteProvider",
    "Money",
    "QualityStatus",
    "Quantity",
    "SqliteArtifactStore",
    "VersionedReference",
    "freeze_value",
]
