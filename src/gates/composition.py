"""Single-process composition for the local modular monolith."""

import os
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.execution import (
    BrokerOrderRepository,
    KiteAccounts,
    KiteCredentials,
    KiteExecutionGateway,
    KiteStreamingProvider,
)
from src.domains.indicators import IndicatorNodeCache, PandasTaAdapter
from src.domains.market_data import LiveQuotes
from src.domains.operations import BackgroundWorker, JobStore, JobWorker
from src.domains.portfolio_accounting import IntradayStopAlerts, Ledger
from src.domains.portfolio_engine import PortfolioRiskConfig
from src.domains.strategies.api import RETAINED_STRATEGIES
from src.gates.repositories import MarketRepository
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.gates.workflows.backtesting import BacktestJobs
from src.gates.workflows.broker_orders import BrokerOrderWorkflow
from src.gates.workflows.corporate_actions import CorporateActions
from src.gates.workflows.index_poller import IndexQuotePoller
from src.gates.workflows.intraday_stream import IntradayStreamLease
from src.gates.workflows.liquidity_universe import publish_liquidity_universe
from src.gates.workflows.live_quote_stream import LiveQuoteStream
from src.gates.workflows.managed_risk import ManagedRiskGuard
from src.gates.workflows.market_jobs import KiteMarketJobs
from src.gates.workflows.market_refresh import MarketRefreshPlanner
from src.gates.workflows.pipeline_preparation import PipelinePreparation
from src.gates.workflows.portfolio_actions import ActionJobs
from src.gates.workflows.portfolio_sync import PortfolioSync
from src.gates.workflows.portfolio_history_backfill import backfill_portfolio_history
from src.gates.workflows.positional_trend import PositionalTrendJobs
from src.gates.workflows.research import ResearchJobs
from src.gates.workflows.research_pipeline import ResearchPipelineJobs
from src.gates.workflows.universe import UniverseJobs
from src.platform_kernel import ArtifactStore, SqliteArtifactStore


@dataclass(frozen=True)
class ApplicationServices:
    database: Path
    artifacts: ArtifactStore
    catalog: ArtifactCatalog
    jobs: JobStore
    market: MarketRepository
    research: ResearchJobs
    positional_trend: PositionalTrendJobs
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
    broker_orders: BrokerOrderWorkflow
    market_jobs: KiteMarketJobs
    universe: UniverseJobs
    kite_accounts: KiteAccounts
    portfolio_sync: PortfolioSync
    live_quotes: LiveQuotes
    live_stream: LiveQuoteStream
    background_worker: BackgroundWorker | None = None

    @classmethod
    def create(
        cls,
        data_directory: str | Path,
        *,
        market_data_kite_credentials: KiteCredentials | None = None,
        market_data_kite_token_path: str | Path = "access_token.txt",
        portfolio_kite_credentials: KiteCredentials | None = None,
        portfolio_kite_token_path: str | Path = "portfolio_access_token.txt",
        portfolio_live_execution: bool = False,
    ) -> "ApplicationServices":
        root = Path(data_directory)
        database = root / "stock_screener.db"
        artifacts = SqliteArtifactStore(database)
        catalog = ArtifactCatalog(database)
        jobs = JobStore(database)
        index_poller = IndexQuotePoller(database, jobs)
        market = MarketRepository(database)
        universe = UniverseJobs(market)
        publisher = ArtifactPublisher(artifacts, catalog)
        ledger = Ledger(database)
        kite_accounts = KiteAccounts(str(database), allowed_strategy_ids=RETAINED_STRATEGIES)
        portfolio_sync = PortfolioSync(database, kite_accounts, ledger, market)
        intraday_stream = IntradayStreamLease(database)
        live_quotes = LiveQuotes(database)
        market_refresh = MarketRefreshPlanner(
            database, market, jobs, publisher, held_instrument_ids=ledger.open_instrument_ids
        )
        node_cache = IndicatorNodeCache(database)
        corporate_actions = CorporateActions(database, market, node_cache)
        risk_config = PortfolioRiskConfig(str(database))
        broker_orders = BrokerOrderWorkflow(
            database,
            ledger,
            KiteExecutionGateway(
                portfolio_kite_credentials,
                portfolio_kite_token_path,
                enabled=portfolio_live_execution,
                accounts=kite_accounts,
            ),
            risk_config,
            repository=BrokerOrderRepository(database),
            market=market,
        )
        strategies = StrategyDefinitions(database, PandasTaAdapter())
        strategy_runtime = StrategyRuntime(strategies)
        strategy_runtime.seed(Path(__file__).resolve().parents[2] / "strategies")
        research = ResearchJobs(database, market, publisher, strategy_runtime, node_cache)
        positional_trend = PositionalTrendJobs(market, publisher, strategy_runtime)
        backtests = BacktestJobs(
            database, market, research, publisher, positional_trend
        )
        # Full artifact verification is expensive with a large research history.
        # A populated catalog already represents validated immutable artifacts;
        # clean interrupted staging work at startup and reserve a full scan for
        # an explicit SCREENER_FULL_STARTUP_RECOVERY=true setting.
        catalog_populated, _catalog_has_live_entries = catalog.recovery_state()
        if (
            os.environ.get("SCREENER_FULL_STARTUP_RECOVERY", "false").lower() == "true"
            or not catalog_populated
        ):
            publisher.recover()
        else:
            publisher.store.recover_staging()
        actions = ActionJobs(
            database, market, research, ledger, publisher, positional_trend, risk_config
        )
        intraday_alerts = IntradayStopAlerts(database, ledger, actions, publisher)
        live_stream = LiveQuoteStream(
            kite_accounts,
            market,
            live_quotes,
            intraday_stream,
            intraday_alerts,
            KiteStreamingProvider,
        )
        risk_guard = ManagedRiskGuard(
            database, ledger, market, risk_config, actions.risk_projection
        )
        actions.risk_guard = risk_guard
        broker_orders.risk_guard = risk_guard
        pipelines = ResearchPipelineJobs(database, jobs, strategy_runtime)
        market_jobs = KiteMarketJobs(
            market,
            publisher,
            market_data_kite_credentials,
            market_data_kite_token_path,
            intraday_alerts=intraday_alerts,
            ledger=ledger,
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
                "reference.sync-snapshot-instruments": market_jobs.sync_snapshot_instruments,
                "market.fetch-kite-bars": market_jobs.fetch_bars,
                "market.fetch-bulk-kite-bars": market_jobs.fetch_bulk_bars,
                "market.fetch-kite-index-quotes": market_jobs.fetch_index_quotes,
                "market.fetch-intraday-stop-alerts": market_jobs.fetch_intraday_stop_alerts,
                "portfolio.backfill-price-history": lambda payload, context: backfill_portfolio_history(
                    ledger, market_jobs, payload['account_id'], date.fromisoformat(payload['as_of_date']), context
                ),
                "market.schedule-all-symbol-refresh": market_refresh.schedule,
                "reference.reconcile-market": market_refresh.reconcile,
                "research.rebuild-range": research.rebuild_range,
                "research.rebuild-indicators": research.rebuild_indicators,
                "research.positional-trend-build-signals": positional_trend.build_signals,
                "research.positional-trend-build-range": positional_trend.build_range,
                "backtest.run": backtests.execute,
                "backtest.stress": backtests.stress,
                "backtest.walk-forward": backtests.walk_forward,
                "backtest.attribute": backtests.attribute,
                "actions.generate-portfolio-proposal": generate_portfolio_proposal,
                "research.pipeline-advance": pipelines.advance,
                "research.pipeline-prepare": PipelinePreparation(
                    universe,
                    market,
                    market_jobs,
                    corporate_actions,
                    research,
                    market_refresh,
                    kite_accounts,
                ).run,
                "reference.download-nifty500-constituents": universe.download_nifty500_constituents,
                "universe.detect-exits": universe.detect_universe_exits,
                "reference.detect-corporate-actions": corporate_actions.detect_job,
                "reference.process-corporate-actions": lambda payload, context=None: (
                    corporate_actions.process_actionable(
                        market_jobs.corporate_history, context=context
                    )
                ),
            },
        )
        return cls(
            database,
            artifacts,
            catalog,
            jobs,
            market,
            research,
            positional_trend,
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
            universe,
            kite_accounts,
            portfolio_sync,
            live_quotes,
            live_stream,
            background_worker=BackgroundWorker(worker),
        )
