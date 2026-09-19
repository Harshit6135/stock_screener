"""Read-only preview of the configured v3 personal portfolio import."""

import json
from pathlib import Path

from src.application.legacy_portfolio import LegacyPortfolioImporter

from src.application.catalog import ArtifactCatalog
from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.execution_gateway import Ledger
from src.platform_kernel import ArtifactStore


def main() -> None:
    root = Path("instance")
    database = root / "system.db"
    importer = LegacyPortfolioImporter(
        database,
        MarketRepository(database),
        Ledger(database),
        ArtifactPublisher(ArtifactStore(root / "artifacts"), ArtifactCatalog(database)),
    )
    print(json.dumps(importer.preview({"legacy_path": str(root / "personal.db")}), indent=2))


if __name__ == "__main__":
    main()
