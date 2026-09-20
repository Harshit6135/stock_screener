"""Single-process composition for the local modular monolith."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.application.action_jobs import ActionJobs
from src.application.backtest_jobs import BacktestJobs
from src.application.catalog import ArtifactCatalog
from src.application.corporate_actions import CorporateActions
from src.application.index_poller import IndexQuotePoller
from src.application.intraday_alerts import IntradayStopAlerts
from src.application.intraday_stream import IntradayStreamLease
from src.application.jobs import JobStore
from src.application.kite_auth import KiteCredentials
from src.application.liquidity import publish_liquidity_universe
from src.application.market_jobs import KiteMarketJobs
from src.application.market_refresh import MarketRefreshPlanner
from src.application.market_repository import MarketRepository
from src.application.pipeline_jobs import ResearchPipelineJobs
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.strategy_definitions import StrategyDefinitions
from src.application.strategy_runtime import StrategyRuntime
from src.application.worker import BackgroundWorker, JobWorker
from src.execution_gateway import BrokerOrderService, KiteExecutionGateway, Ledger
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import ArtifactStore, SqliteArtifactStore


@dataclass(frozen=True)
class ApplicationServices:
    database: Path
    artifacts: ArtifactStore
    catalog: ArtifactCatalog
    jobs: JobStore
    market: MarketRepository
    research: ResearchJobs
    strategies: StrategyDefinitions
    strategy_runtime: StrategyRuntime
    backtests: BacktestJobs
    actions: ActionJobs
    pipelines: ResearchPipelineJobs
    publisher: ArtifactPublisher
    ledger: Ledger
    worker: JobWorker
    index_poller: IndexQuotePoller
    market_refresh: MarketRefreshPlanner
    corporate_actions: CorporateActions
    intraday_alerts: IntradayStopAlerts
    intraday_stream: IntradayStreamLease
    broker_orders: BrokerOrderService
    market_jobs: KiteMarketJobs
    background_worker: BackgroundWorker | None = None

    @classmethod

    def create(
        cls,
        data_directory: str | Path,
        *,
        market_data_kite_credentials: KiteCredentials | None = None,
        market_data_kite_token_path: str | Path = "access_token.txt",
        nse_csv_path: str | Path = "data/imports/NSE.csv",
        bse_csv_path: str | Path = "data/imports/BSE.csv",
        portfolio_kite_credentials: KiteCredentials | None = None,
        portfolio_kite_token_path: str | Path = "portfolio_access_token.txt",
        portfolio_live_execution: bool = False,
    ) -> "ApplicationServices":
        root = Path(data_directory)
        database = root / "system.db"
        artifacts = SqliteArtifactStore(database)
        catalog = ArtifactCatalog(database)
        jobs = JobStore(database)
        index_poller = IndexQuotePoller(database, jobs)
        market = MarketRepository(database)
        publisher = ArtifactPublisher(artifacts, catalog)
        ledger = Ledger(database)
        intraday_alerts = IntradayStopAlerts(database, ledger, publisher)
        intraday_stream = IntradayStreamLease(database)
        market_refresh = MarketRefreshPlanner(
            database, market, jobs, publisher, held_instrument_ids=ledger.open_instrument_ids
        )
        corporate_actions = CorporateActions(database, market, publisher, ledger)
        broker_orders = BrokerOrderService(
            database, ledger, KiteExecutionGateway(
                portfolio_kite_credentials, portfolio_kite_token_path, enabled=portfolio_live_execution
            ),
        )
        strategies = StrategyDefinitions(database, PandasTaAdapter())
        strategy_runtime = StrategyRuntime(strategies)
        strategy_runtime.seed(Path(__file__).resolve().parents[2] / "strategies")
        research = ResearchJobs(database, market, publisher, strategy_runtime)
        backtests = BacktestJobs(database, market, research, publisher, corporate_actions)
        # Full artifact verification is expensive with a large research history.
        # A populated catalog already represents validated immutable artifacts;
        # clean interrupted staging work at startup and reserve a full scan for
        # an explicit SCREENER_FULL_STARTUP_RECOVERY=true setting.
        catalog_entries = catalog.artifacts()
        legacy_catalog_without_payloads = (
            bool(catalog_entries)
            and not artifacts.artifact_locations()
            and any(item["status"] != "MISSING" for item in catalog_entries)
        )
        if (
            os.environ.get("SCREENER_FULL_STARTUP_RECOVERY", "false").lower() == "true"
            or not catalog_entries
            or legacy_catalog_without_payloads
        ):
            publisher.recover()
        else:
            publisher.store.recover_staging()
        actions = ActionJobs(database, market, research, ledger, publisher)
        pipelines = ResearchPipelineJobs(database, jobs, strategy_runtime)
        market_jobs = KiteMarketJobs(
            market,
            publisher,
            market_data_kite_credentials,
            market_data_kite_token_path,
            nse_csv_path,
            bse_csv_path,
            intraday_alerts,
        )

        def build_liquidity_universe_job(payload: dict[str, Any]) -> dict[str, object]:
            manifest = publish_liquidity_universe(publisher, payload)
            return {
                "artifact_id": manifest.artifact_id,
                "category": manifest.category,
                "quality": manifest.quality.value,
            }

        def generate_portfolio_proposal(payload: dict[str, Any]) -> dict[str, object]:
            """Generate a proposal only; a proposal is never an execution."""
            return actions.generate(payload)

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
                "market.fetch-intraday-stop-alerts": market_jobs.fetch_intraday_stop_alerts,
                "market.schedule-all-symbol-refresh": market_refresh.schedule,
                "reference.reconcile-market": market_refresh.reconcile,
                "research.rebuild-range": research.rebuild_range,
                "backtest.run": backtests.execute,
                "backtest.stress": backtests.stress,
                "backtest.walk-forward": backtests.walk_forward,
                "backtest.attribute": backtests.attribute,
                "actions.generate-portfolio-proposal": generate_portfolio_proposal,
                "research.pipeline-advance": pipelines.advance,
                "reference.enrich-day0-universe": market_jobs.enrich_and_sync_universe,
            },
        )
        return cls(
            database,
            artifacts,
            catalog,
            jobs,
            market,
            research,
            strategies,
            strategy_runtime,
            backtests,
            actions,
            pipelines,
            publisher,
            ledger,
            worker,
            index_poller,
            market_refresh,
            corporate_actions,
            intraday_alerts,
            intraday_stream,
            broker_orders,
            market_jobs,
            background_worker=BackgroundWorker(worker),
        )
