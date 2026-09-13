"""Single-process composition for the local modular monolith."""

from dataclasses import dataclass
from pathlib import Path

from src.application.catalog import ArtifactCatalog
from src.application.jobs import JobStore
from src.application.publication import ArtifactPublisher
from src.platform_kernel import ArtifactStore


@dataclass(frozen=True)
class ApplicationServices:
    database: Path
    artifacts: ArtifactStore
    catalog: ArtifactCatalog
    jobs: JobStore
    publisher: ArtifactPublisher

    @classmethod
    def create(cls, data_directory: str | Path) -> "ApplicationServices":
        root = Path(data_directory)
        database = root / "system.db"
        artifacts = ArtifactStore(root / "artifacts")
        catalog = ArtifactCatalog(database)
        jobs = JobStore(database)
        publisher = ArtifactPublisher(artifacts, catalog)
        publisher.recover()
        return cls(database, artifacts, catalog, jobs, publisher)
