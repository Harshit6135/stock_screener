"""Single-process composition for the local modular monolith."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.application.action_jobs import ActionJobs
from src.application.backtest_jobs import BacktestJobs
from src.application.catalog import ArtifactCatalog
from src.application.jobs import JobStore
from src.application.kite_auth import KiteCredentials
from src.application.legacy_portfolio import LegacyPortfolioImporter
from src.application.liquidity import publish_liquidity_universe
from src.application.market_jobs import KiteMarketJobs
from src.application.market_repository import MarketRepository
from src.application.pipeline_jobs import ResearchPipelineJobs
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.strategy_configs import StrategyConfigs
from src.application.worker import JobWorker
from src.execution_gateway import Ledger
from src.platform_kernel import ArtifactStore


@dataclass(frozen=True)
class ApplicationServices:
    database: Path
    artifacts: ArtifactStore
    catalog: ArtifactCatalog
    jobs: JobStore
    market: MarketRepository
    research: ResearchJobs
    configs: StrategyConfigs
    backtests: BacktestJobs
    actions: ActionJobs
    legacy_portfolio: LegacyPortfolioImporter
    pipelines: ResearchPipelineJobs
    publisher: ArtifactPublisher
    ledger: Ledger
    worker: JobWorker

    @classmethod
    def create(
        cls,
        data_directory: str | Path,
        *,
        market_data_kite_credentials: KiteCredentials | None = None,
        market_data_kite_token_path: str | Path = "access_token.txt",
        nse_csv_path: str | Path = "data/imports/NSE.csv",
        bse_csv_path: str | Path = "data/imports/BSE.csv",
        legacy_market_path: str | Path | None = None,
    ) -> "ApplicationServices":
        root = Path(data_directory)
        database = root / "system.db"
        artifacts = ArtifactStore(root / "artifacts")
        catalog = ArtifactCatalog(database)
        jobs = JobStore(database)
        market = MarketRepository(database)
        publisher = ArtifactPublisher(artifacts, catalog)
        research = ResearchJobs(database, market, publisher)
        configs = StrategyConfigs(database, publisher)
        backtests = BacktestJobs(database, market, research, publisher, configs)
        publisher.recover()
        ledger = Ledger(database)
        actions = ActionJobs(database, market, research, ledger, publisher, configs)
        legacy_portfolio = LegacyPortfolioImporter(database, market, ledger, publisher)
        pipelines = ResearchPipelineJobs(database, jobs)
        market_jobs = KiteMarketJobs(
            market,
            publisher,
            market_data_kite_credentials,
            market_data_kite_token_path,
            nse_csv_path,
            bse_csv_path,
            legacy_market_path,
        )

        def build_liquidity_universe_job(payload: dict[str, Any]) -> dict[str, object]:
            manifest = publish_liquidity_universe(publisher, payload)
            return {
                "artifact_id": manifest.artifact_id,
                "category": manifest.category,
                "quality": manifest.quality.value,
            }

        worker = JobWorker(
            jobs,
            "local-writer",
            {
                "system.echo": lambda payload: {"echo": payload},
                "artifacts.recover": lambda payload: publisher.recover(),
                "research.build-liquidity-universe": build_liquidity_universe_job,
                "reference.sync-kite-instruments": market_jobs.sync_instruments,
                "reference.sync-bse-instruments": market_jobs.sync_bse_instruments,
                "market.fetch-kite-bars": market_jobs.fetch_bars,
                "market.fetch-kite-index-quotes": market_jobs.fetch_index_quotes,
                "market.import-v3-bars": market_jobs.import_v3_bars,
                "research.calculate-strategy1-day": research.calculate_strategy1_day,
                "research.rank-strategy1-week": research.rank_week,
                "research.calculate-strategy2-day": research.calculate_strategy2_day,
                "research.rank-strategy2-week": research.rank_strategy2_week,
                "backtest.run": backtests.execute,
                "actions.generate-paper-proposal": actions.generate,
                "research.pipeline-advance": pipelines.advance,
            },
        )
        return cls(
            database,
            artifacts,
            catalog,
            jobs,
            market,
            research,
            configs,
            backtests,
            actions,
            legacy_portfolio,
            pipelines,
            publisher,
            ledger,
            worker,
        )
