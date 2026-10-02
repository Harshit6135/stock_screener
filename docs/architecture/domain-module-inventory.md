# Source and domain ownership inventory

Read-only inventory for the proposed `src/domains/` and `src/gates/` architecture. No source modules are moved by this report.

## Proposed structural rules

- `src/platform_kernel/` remains the shared, domain-neutral foundation.
- Existing domain packages move as whole packages under `src/domains/`; no extra grouping level is added inside each domain.
- `src/gates/` owns HTTP/CLI entry adapters, dependency composition, durable job handlers, and workflows that coordinate multiple domains.
- A domain may depend on the platform kernel and its own modules. Cross-domain workflows must be expressed through gates or explicit contracts, not direct domain imports.
- Within each domain, use a consistent responsibility vocabulary where applicable: `api.py` for public domain contracts, `services.py` for domain operations, `repository.py` for persistence adapters, and `providers.py` for external data/broker adapters. Do not create empty files where a responsibility does not exist.

## Existing top-level packages and proposed destination

| Current package | Proposed destination | Initial responsibility |
| --- | --- | --- |
| `src/platform_kernel` | stays at `src/platform_kernel` | shared contracts, value types, artifact storage primitives; no domain behavior |
| `src/market_data` | `src/domains/market_data` | bars, providers, market history, calendars, universe/market snapshots |
| `src/reference_data` | `src/domains/reference_data` | instrument/reference snapshots, aliases, calendars, corporate-action reference types |
| `src/indicators` | `src/domains/indicators` | indicator contracts, registry, DAG, custom feature calculations |
| `src/strategies` | `src/domains/strategies` | strategy definitions, ranking, strategy runtime and signals |
| `src/backtesting` | `src/domains/backtesting` | replay models and backtest engine |
| `src/portfolio_engine` | `src/domains/portfolio_engine` | portfolio decision rules and policy |
| `src/portfolio_accounting` | `src/domains/portfolio_accounting` | fills, accounting events and projections |
| `src/execution_gateway` | `src/domains/execution` | broker gateway, order/ledger/account operations, execution risk |
| `src/application` | split between `src/gates` and domain packages | currently mixes routes, composition, persistence, job handlers and domain services |

## Gateways required by current cross-domain workflows

| Current code path | Current interaction | Proposed ownership |
| --- | --- | --- |
| `application/action_jobs.py` | combines market, positional strategy, research, ledger, portfolio decisions, accounting, SQLite and publication | split: action proposal / execution orchestration in `gates`; only stable calculations and policies move to their owning domain |
| `application/backtest_jobs.py` | combines backtesting API with market repository, research, corporate actions, persistence and publication | gate job handler coordinates domains; replay calculation stays in `domains/backtesting` |
| `application/corporate_actions.py` | market history, corporate-action lifecycle, ledger, indicator cache and publication | gate workflow coordinates market data, accounting and indicators; move pure corporate-action types/rules to `domains/reference_data` or market domain after function audit |
| `application/pipeline_jobs.py`, `pipeline_preparation.py` | coordinates strategies, market refresh, universe, corporate actions and research | gates job/workflow orchestration |
| `application/portfolio_sync.py` | coordinates broker account, ledger, market repository and portfolio inputs | gate workflow coordinates execution and portfolio domains |
| `execution_gateway/broker.py` | has a runtime import of `application.market_repository` for current membership checks | replace repository dependency with an injected membership contract supplied by a gate; execution domain must not import market domain |
| `indicators/custom/__init__.py` | imports positional trend feature logic from `application` | move the signal calculation into `domains/strategies`; indicator custom registry consumes a contract/callable without importing the strategy package |

## Current domain-to-application dependency violations

These edges must be resolved before moving whole packages. They are listed individually in the full inventory as well.

| Importing module | Current application dependency | Planned seam |
| --- | --- | --- |
| `execution_gateway/broker.py` | `kite_auth.KiteCredentials`, `sqlite`, and runtime `market_repository.MarketRepository` | move execution credential contract/auth to execution; make SQLite infrastructure neutral; inject a membership-check contract through gates |
| `execution_gateway/kite_accounts.py` | `sqlite` and `strategy_runtime.RETAINED_STRATEGIES` | neutralize SQLite dependency; move strategy ID contract to strategy domain or pass allowed IDs into account binding logic |
| `execution_gateway/ledger.py` | `sqlite` | move SQLite connection/migration primitives to a neutral storage boundary |
| `execution_gateway/risk_guard.py` | `sqlite` | same neutral storage seam |
| `indicators/custom/__init__.py` | `application.positional_trend.feature_series` | move signal feature ownership to strategies and make indicator registration consume an explicit callable/contract without importing a domain |

## Mixed-responsibility file review

| Current file | Responsibilities found in its symbols | Proposed treatment |
| --- | --- | --- |
| `application/market_repository.py` (1,524 lines) | instruments/universe snapshots, exit eligibility, market bars/coverage, indicators, index quotes, corporate-action event state | split by persistence aggregate into sibling repository modules under `domains/market_data`; keep transaction/schema helpers in platform storage boundary |
| `application/action_jobs.py` (1,331 lines) | proposal generation, policy comparison, risk projections, manual/amend flows, proposal/event reads, decision and execution processing | keep cross-domain use-case handlers in gates; extract only pure portfolio policy or execution rules after ownership review |
| `application/research_jobs.py` (1,425 lines) | research artifact builds, indicator/range rebuilds, ranking/revision workflows and persisted job handling | separate research domain calculations from gate job handlers and publication/persistence adapters |
| `application/market_jobs.py` (485 lines) | Kite client and market fetches, provider history, instrument sync, index quotes and stop-alert dispatch | provider adapter belongs to market-data/execution boundary; job dispatch and alert coordination belongs in gates |
| `application/corporate_actions.py` (618 lines) | provider date/ratio parsing, event classification/detection, adjustment math, ledger updates, publication, cache invalidation | split parsing/pure adjustment logic from cross-domain event processing; the latter is a gate workflow |
| `application/backtest_jobs.py` (804 lines) | request validation, replay dispatch, stress/walk-forward/attribution, persisted result listing/deletion | calculation stays in backtesting; persistence and job orchestration stay in gates |
| `application/market_web.py` (304 lines) | market routes plus corporate-action, quote, refresh and stream endpoints | split into gate route modules by external resource; routes remain adapters and call gate use cases |
| `application/strategy_runtime.py` | strategy catalog/legacy ID mapping, persistence-backed definitions, indicator DAG evaluation and ranking calculations | split pure strategy definitions/evaluation into `domains/strategies`; keep persistence orchestration at gate or strategy repository boundary |
| `application/positional_trend_backtest.py` | SQLite/CSV loading, universe selection, policy model, simulation and benchmark reading | move simulation to `domains/backtesting`; input loading becomes a repository/provider adapter; CLI entry belongs in gates/tools |
| `application/index_poller.py` | quote polling state, scheduling, exchange-open checks and background thread | market quote polling belongs to market-data service; generic thread lifecycle/job scheduling belongs in gates |
| `application/kite_auth.py` | credentials/config loading, Kite client protocol and token-file login lifecycle | move broker-specific auth to `domains/execution`; keep environment/config assembly at gates |
| `application/liquidity.py` | JSON validation/decoding plus mapping domain inputs to liquidity snapshot and publishing it | decoding/request boundary belongs in gates; universe calculation stays in `domains/reference_data` |
| `application/portfolio_web.py` | Flask request/response adapter and money/input validation around portfolio services | remain in gates; move reusable validation/calculation to portfolio domain contracts |
| `application/composition.py` | constructs every store/domain service and registers all durable job handlers | remain the gate composition root; later reduce it into small provider functions only if wiring becomes hard to trace |

## Application module-by-module ownership proposal

Destinations below are provisional. “Split” means assign functions/classes individually after reviewing call graphs; it is not an instruction to move the entire current file. Domain destinations are siblings directly under `src/domains/<domain>/`, following the existing package layout.

| Current module | Proposed owner | Notes / function-level split candidate |
| --- | --- | --- |
| `application/__init__.py` | gates public facade | Export only gate-facing API if needed; avoid exporting domain internals. |
| `application/action_jobs.py` | gates workflow | Cross-domain proposal, risk, ledger and execution orchestration. Extract only pure policy/decision functions to portfolio or execution after call-graph review. |
| `application/actions_web.py` | gates HTTP | Request/response adapter for action workflows. |
| `application/backtest_jobs.py` | gates workflow + backtesting | Job lifecycle, persistence and domain coordination in gates; replay/stress/walk-forward/attribution calculations in backtesting. |
| `application/backtest_web.py` | gates HTTP | Request/response adapter. |
| `application/broker_web.py` | gates HTTP | Request/response adapter for execution domain. |
| `application/catalog.py` | platform storage boundary | Artifact catalog persistence; check whether it belongs beside platform artifact storage rather than a domain. |
| `application/cli.py` | gates CLI | External command parsing and service invocation. |
| `application/composition.py` | gates composition | Sole cross-domain construction/wiring point; keep as traceable root. |
| `application/corporate_actions.py` | split: reference-data/market rules + gates workflow | Date/ratio parsing, classification and adjustment math are domain candidates; broker verification, ledger, cache invalidation and publication coordination stay in gates. |
| `application/dashboard_web.py` | gates HTTP | Dashboard route and template adapter. |
| `application/exchange_calendar.py` | reference data | Persisted trading-session calendar; reconcile with existing `reference_data.ExchangeCalendar` and keep one canonical contract. |
| `application/index_poller.py` | split: market data + gates | Quote/polling state and market-open semantics belong with market data; background thread lifecycle/job submission belongs in gates. |
| `application/indicators_web.py` | gates HTTP | Adapter for indicator catalogue/calculation API. |
| `application/ingestion.py` | market data | Provider-bar normalization/publication path; ensure no gate-only dependencies remain. |
| `application/intraday_alerts.py` | split: execution/market domain + gates | Pure stop/alert eligibility and state model may belong to execution; dispatch, job context, and artifact publication coordination stay in gates. |
| `application/intraday_stream.py` | split: market data + gates | Stream lease/state contract versus worker/process lifecycle. |
| `application/jobs.py` | gates job infrastructure | Durable job state/claim/cancel API used by gate handlers; move shared SQLite primitives out first. |
| `application/kite_accounts_web.py` | gates HTTP | Adapter for execution account workflows. |
| `application/kite_auth.py` | execution | Kite credential value object and broker authentication/token protocol; environment-specific credential loading remains in gates. |
| `application/kite_web.py` | gates HTTP | Login/session routes. |
| `application/liquidity.py` | split: reference data + gates | Payload decoding/validation and artifact publication at gates; mapping to `LiquidityUniversePolicy` and pure universe generation in reference data. |
| `application/live_quotes.py` | market data / execution contract | Quote store and stream adapter; separate generic quote state from Kite-specific stream/provider connection. |
| `application/managed_risk.py` | portfolio/execution | Risk calculations and guard policy; reconcile with `execution_gateway/risk_guard.py` and `portfolio_engine` before deciding canonical owner. |
| `application/market_jobs.py` | split: market data + gates | Provider calls and market normalization belong with market data; durable job handlers, alert dispatch and multi-service orchestration stay in gates. |
| `application/market_refresh.py` | split: market data + gates | Refresh planning policy versus JobStore scheduling/reconciliation orchestration. |
| `application/market_repository.py` | market data | Split instrument/universe, price/coverage/index, and corporate-action persistence into sibling repository modules; retain one migration/schema ownership strategy. |
| `application/market_web.py` | gates HTTP | Split routes by resource (market, corporate actions, quotes/stream, refresh) while keeping Flask concerns in gates. |
| `application/node_cache.py` | indicators | Persistent indicator-node cache; move persistence dependency to a neutral storage boundary. |
| `application/nse_client.py` | market data / reference data | NSE transport/download adapter; assign response parsing to the domain that owns each payload. |
| `application/operations.py` | platform storage boundary | SQLite backup/restore/readiness operations; keep operational command wiring in gates. |
| `application/payloads.py` | split by payload contract | Assign each payload class to its owning domain API; leave HTTP/job envelope parsing in gates. |
| `application/pipeline_jobs.py` | gates workflow | Job handler and pipeline lifecycle coordinating strategy and market services. |
| `application/pipeline_preparation.py` | gates workflow | Multi-domain preparation/synchronization coordinator. |
| `application/pipeline_web.py` | gates HTTP | Request/response adapter. |
| `application/portfolio_performance.py` | portfolio accounting | XIRR and portfolio performance calculations; verify against existing accounting projection semantics. |
| `application/portfolio_sync.py` | gates workflow | Coordinates broker accounts, ledger and market data; no domain-to-domain imports. |
| `application/portfolio_web.py` | gates HTTP | Request/response adapter; move reusable typed validation to portfolio contracts only if domain-owned. |
| `application/positional_trend_backtest.py` | split: backtesting + gates/tool entry | Simulation and benchmark calculations in backtesting; SQLite/CSV loading via adapters; CLI wiring in gates/tools. |
| `application/positional_trend_jobs.py` | gates workflow | Durable job handlers coordinating strategy and market-data services. |
| `application/positional_trend_web.py` | gates HTTP | Request/response adapter. |
| `application/positional_trend.py` | strategies | Signal/feature calculations; remove the current indicator-to-application import by exposing a strategy-owned public contract. |
| `application/providers.py` | split: market data + execution | Historical/instrument/quote providers belong with market data; streaming provider may be execution-specific. Keep provider implementations out of domain rules. |
| `application/publication.py` | platform storage boundary / gates | Artifact publication state coordination; separate generic store/catalog protocol from workflow-specific publish calls. |
| `application/ranking_patterns.py` | strategies | Ranking pattern implementations and selector. |
| `application/reference_web.py` | gates HTTP | Request/response adapter. |
| `application/release_gates.py` | gates/release tooling | Operational parity/restore checks; likely lives with release tooling, not a product domain. |
| `application/research_jobs.py` | gates workflow + indicators/strategies | Persisted job orchestration stays in gates; pure feature/ranking computations go to the owning existing domain APIs. |
| `application/research_web.py` | gates HTTP | Request/response adapter. |
| `application/runs.py` | split: backtesting + gates | Backtest result mapping belongs with backtesting; publication call remains a gate/storage operation. |
| `application/runtime.py` | gates configuration | Environment/config loading only; no domain policy. |
| `application/security.py` | gates/platform boundary | Request/log/error redaction utilities; place according to whether they are transport-specific or truly shared primitives. |
| `application/session_coverage.py` | market data | Completed-session coverage model/query. |
| `application/sqlite.py` | platform storage boundary | Shared SQLite connection/migration helpers; move before repositories and gateways to remove current imports back into application. |
| `application/strategies_web.py` | gates HTTP | Request/response adapter. |
| `application/strategy_definitions.py` | strategies | Persisted strategy definition/revision operations; keep repository dependency explicit. |
| `application/strategy_runtime.py` | split: strategies + indicators + gates | Strategy ID migration/catalog belongs with strategies; DAG/feature execution belongs with indicators; persistence-backed orchestration stays in gates. |
| `application/universe_jobs.py` | split: reference/market data + gates | CSV provider parsing and exit/universe domain policy versus durable job orchestration. |
| `application/universe_web.py` | gates HTTP | Request/response adapter. |
| `application/web.py` | gates HTTP | Generic durable-job HTTP/SSE adapter. |
| `application/wiki_web.py` | gates HTTP | Documentation page adapter. |
| `application/worker.py` | gates job infrastructure | Generic worker lifecycle and handler dispatch; should depend on job contracts, not domain code. |

The removed the removed application YFinance adapter was not included: repository-wide search found no callers, and the documented YFinance enrichment path had already been retired. The `yfinance` provenance strings in fixtures are data labels, not imports of the adapter.

## Full Python-file inventory

Imports include imports inside functions/classes as well as module-level imports. Symbols list module-level functions/classes/constants; class methods are listed under their class. This is an AST inventory, not a claim that every symbol should move with its file.

### `src/__init__.py` — 5 lines

**Imports**
- None

**Module-level symbols**
- None

### `src/application/__init__.py` — 33 lines

**Imports**
- L3: `from .catalog import ArtifactCatalog`
- L4: `from .jobs import JobExecutionContext, JobStatus, JobStore`
- L5: `from .liquidity import publish_liquidity_universe`
- L6: `from .operations import sqlite_backup, sqlite_ready, sqlite_restore`
- L7: `from .publication import ArtifactPublisher`
- L8: `from .release_gates import compare_execution_events, dashboard_visual_contract, next_tradable_session, restore_drill`
- L14: `from .runs import publish_backtest_result`
- L15: `from .worker import JobWorker`

**Module-level symbols**
- None

### `src/application/action_jobs.py` — 1331 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `import logging`
- L10: `from datetime import UTC, date, datetime, time, timedelta`
- L11: `from decimal import Decimal, InvalidOperation`
- L12: `from pathlib import Path`
- L13: `from typing import Any, cast`
- L14: `from uuid import NAMESPACE_URL, uuid5`
- L15: `from zoneinfo import ZoneInfo`
- L17: `from src.application.market_repository import MarketRepository`
- L18: `from src.application.positional_trend import valid_bar`
- L19: `from src.application.publication import ArtifactPublisher`
- L20: `from src.application.research_jobs import ResearchJobs`
- L21: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L22: `from src.execution_gateway import Ledger`
- L23: `from src.platform_kernel import DomainValidationError, Money, QualityStatus, Quantity`
- L24: `from src.portfolio_accounting import Fill, FillSide`
- L25: `from src.portfolio_engine import Candidate, DecisionType, Holding, MarketBar, PortfolioPolicy, PortfolioState, evaluate`
- L174: `from src.application.positional_trend import feature_series`
- L340: `from src.application.strategy_runtime import resolve_strategy_id`

**Module-level symbols**
- constant `_BUY_TYPES` (L35)
- constant `_EXECUTION_POLICY_VERSION` (L36)
- constant `_DEFAULT_PYRAMID_FRACTION` (L37)
- constant `_EXECUTION_POLICY` (L38)
- class `ActionJobs` (L51): `__init__` L52, `_current_buy_members` L92, `_generate_strategy4` L104, `generate` L332, `compare_execution_policy` L838, `risk_projection` L884, `update_risk_projection` L895, `create_manual` L928, `generate_midweek_stop` L1027, `amend` L1033, `_recover_projection` L1067, `_recover_manual_projection` L1104, `proposal` L1144, `_decode` L1154, `proposals` L1159, `action_dates` L1171, `events` L1179, `decide` L1196, `process` L1233

### `src/application/actions_web.py` — 165 lines

**Imports**
- L3: `from datetime import date`
- L5: `from flask import Blueprint, jsonify, request`
- L7: `from src.application.action_jobs import ActionJobs`
- L8: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_actions_blueprint` (L11)

### `src/application/backtest_jobs.py` — 804 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `import logging`
- L10: `from datetime import UTC, date, datetime, timedelta`
- L11: `from decimal import Decimal, InvalidOperation`
- L12: `from itertools import pairwise`
- L13: `from pathlib import Path`
- L14: `from typing import Any`
- L15: `from uuid import NAMESPACE_URL, UUID, uuid4, uuid5`
- L17: `from src.application.corporate_actions import CorporateActions`
- L18: `from src.application.market_repository import MarketRepository`
- L19: `from src.application.publication import ArtifactPublisher`
- L20: `from src.application.research_jobs import ResearchJobs`
- L21: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L22: `from src.backtesting import BacktestRunManifest, BacktestStep, FillModelRevision, run`
- L23: `from src.platform_kernel import DomainValidationError, Money, QualityStatus`
- L24: `from src.portfolio_engine import Candidate, MarketBar, PortfolioPolicy, PortfolioState`
- L499: `from src.application.positional_trend_backtest import Policy as Strategy4Policy`
- L500: `from src.application.positional_trend_backtest import benchmark_price_return, load_snapshot_universe, simulate`

**Module-level symbols**
- function `_decimal` (L27)
- class `BacktestJobs` (L39): `__init__` L40, `_code_revision` L72, `_momentum_membership_plan` L86, `_revision` L128, `execute` L139, `_execute_strategy4` L472, `stress` L610, `walk_forward` L633, `attribute` L684, `runs` L780, `run_artifact_id` L789, `delete_run` L798

### `src/application/backtest_web.py` — 57 lines

**Imports**
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.application.backtest_jobs import BacktestJobs`
- L6: `from src.platform_kernel import ArtifactStore, DomainValidationError`

**Module-level symbols**
- function `create_backtest_blueprint` (L9)

### `src/application/broker_web.py` — 80 lines

**Imports**
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.execution_gateway import BrokerOrderService`
- L6: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_broker_blueprint` (L9)

### `src/application/catalog.py` — 290 lines

**Imports**
- L3: `import json`
- L4: `import sqlite3`
- L5: `from pathlib import Path`
- L7: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L8: `from src.platform_kernel import ArtifactManifest, DomainValidationError`

**Module-level symbols**
- class `ArtifactCatalog` (L11): `__init__` L12, `_connect` L61, `register` L64, `set_publication_state` L119, `has` L133, `is_missing` L142, `summaries` L149, `mark_missing` L177, `set_status` L184, `artifacts` L197, `recovery_state` L211, `supersede` L225, `invalidation_plan` L263, `record_invalidation` L268, `_invalidation_plan` L278

### `src/application/cli.py` — 93 lines

**Imports**
- L3: `import argparse`
- L4: `import json`
- L5: `from pathlib import Path`
- L7: `from .composition import ApplicationServices`
- L8: `from .index_poller import IndexQuotePoller`
- L9: `from .intraday_stream import IntradayStreamLease`
- L10: `from .jobs import JobStore`
- L11: `from .kite_auth import load_kite_credentials`
- L12: `from .operations import sqlite_backup, sqlite_ready, sqlite_restore`
- L13: `from .pipeline_jobs import ResearchPipelineJobs`
- L14: `from .runtime import RuntimeConfig`

**Module-level symbols**
- function `main` (L17)

### `src/application/composition.py` — 221 lines

**Imports**
- L3: `import os`
- L4: `from dataclasses import dataclass`
- L5: `from pathlib import Path`
- L6: `from typing import Any`
- L8: `from src.application.action_jobs import ActionJobs`
- L9: `from src.application.backtest_jobs import BacktestJobs`
- L10: `from src.application.catalog import ArtifactCatalog`
- L11: `from src.application.corporate_actions import CorporateActions`
- L12: `from src.application.index_poller import IndexQuotePoller`
- L13: `from src.application.intraday_alerts import IntradayStopAlerts`
- L14: `from src.application.intraday_stream import IntradayStreamLease`
- L15: `from src.application.jobs import JobStore`
- L16: `from src.application.kite_auth import KiteCredentials`
- L17: `from src.application.liquidity import publish_liquidity_universe`
- L18: `from src.application.live_quotes import LiveQuotes, LiveQuoteStream`
- L19: `from src.application.managed_risk import ManagedRiskGuard`
- L20: `from src.application.market_jobs import KiteMarketJobs`
- L21: `from src.application.market_refresh import MarketRefreshPlanner`
- L22: `from src.application.market_repository import MarketRepository`
- L23: `from src.application.node_cache import IndicatorNodeCache`
- L24: `from src.application.pipeline_jobs import ResearchPipelineJobs`
- L25: `from src.application.pipeline_preparation import PipelinePreparation`
- L26: `from src.application.portfolio_sync import PortfolioSync`
- L27: `from src.application.positional_trend_jobs import PositionalTrendJobs`
- L28: `from src.application.publication import ArtifactPublisher`
- L29: `from src.application.research_jobs import ResearchJobs`
- L30: `from src.application.strategy_definitions import StrategyDefinitions`
- L31: `from src.application.strategy_runtime import StrategyRuntime`
- L32: `from src.application.universe_jobs import UniverseJobs`
- L33: `from src.application.worker import BackgroundWorker, JobWorker`
- L34: `from src.execution_gateway import BrokerOrderService, KiteExecutionGateway, Ledger`
- L35: `from src.execution_gateway.kite_accounts import KiteAccounts`
- L36: `from src.execution_gateway.risk_guard import PortfolioRiskConfig`
- L37: `from src.indicators.registry import PandasTaAdapter`
- L38: `from src.platform_kernel import ArtifactStore, SqliteArtifactStore`

**Module-level symbols**
- class `ApplicationServices` (L42): `create` L74

### `src/application/corporate_actions.py` — 618 lines

**Imports**
- L7: `import hashlib`
- L8: `import json`
- L9: `import logging`
- L10: `import re`
- L11: `from datetime import date, datetime, timedelta`
- L12: `from decimal import Decimal, InvalidOperation`
- L13: `from pathlib import Path`
- L14: `from typing import Any`
- L15: `from uuid import NAMESPACE_URL, uuid5`
- L16: `from zoneinfo import ZoneInfo`
- L18: `from src.application.market_repository import MarketRepository`
- L19: `from src.application.node_cache import IndicatorNodeCache`
- L20: `from src.application.publication import ArtifactPublisher`
- L21: `from src.application.sqlite import sqlite_connection`
- L22: `from src.execution_gateway import Ledger`
- L23: `from src.market_data import NormalizedBar`
- L24: `from src.platform_kernel import DomainValidationError`
- L313: `from src.application.nse_client import NseClient`

**Module-level symbols**
- constant `ANOMALY_THRESHOLD_PERCENT` (L29)
- constant `ADJUSTABLE_TYPES` (L32)
- constant `MONITORED_TYPES` (L34)
- constant `ALL_CA_TYPES` (L35)
- constant `_NSE_DATE_PATTERNS` (L38)
- constant `_MONTH_MAP` (L44)
- class `CorporateActions` (L50): `__init__` L51, `record` L66, `_qualify_dependents` L96, `adjusted_bars` L116, `liquidation_plan` L149, `normalize_nse_date` L178, `parse_ratio` L206, `classify_action_type` L234, `detect_events` L251, `detect_job` L311, `compute_adjustment_factor` L339, `apply_self_adjustment` L354, `verify_with_kite` L403, `_persist_provider_history` L561, `process_actionable` L575, `_fail_event` L600, `_check_anomaly` L607

### `src/application/dashboard_web.py` — 60 lines

**Imports**
- L7: `from datetime import datetime, timedelta`
- L8: `from zoneinfo import ZoneInfo`
- L10: `from flask import Blueprint, redirect, render_template`

**Module-level symbols**
- function `create_dashboard_blueprint` (L13)

### `src/application/exchange_calendar.py` — 88 lines

**Imports**
- L8: `from __future__ import annotations`
- L10: `from datetime import date`
- L11: `from pathlib import Path`
- L13: `from src.application.sqlite import sqlite_connection`

**Module-level symbols**
- class `TradingCalendar` (L16): `__init__` L19, `sessions` L22, `is_trading_day` L60, `last_session` L70

### `src/application/index_poller.py` — 128 lines

**Imports**
- L3: `import logging`
- L4: `import threading`
- L5: `from datetime import UTC, datetime, timedelta`
- L6: `from pathlib import Path`
- L7: `from zoneinfo import ZoneInfo`
- L9: `from src.application.jobs import JobStore`
- L10: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L11: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `IndexQuotePoller` (L16): `__init__` L17, `state` L30, `set_enabled` L35, `set_interval` L40, `tick` L47, `reconcile` L66, `record_error` L79
- function `market_is_open` (L89)
- class `BackgroundIndexPoller` (L95): `__init__` L98, `start` L104, `stop` L113, `_run` L116

### `src/application/indicators_web.py` — 23 lines

**Imports**
- L3: `from flask import Blueprint, jsonify`
- L5: `from src.indicators.registry import PandasTaAdapter`
- L6: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_indicators_blueprint` (L9)

### `src/application/ingestion.py` — 81 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `from collections.abc import Iterable`
- L6: `from dataclasses import asdict`
- L7: `from datetime import UTC, datetime`
- L9: `from src.application.publication import ArtifactPublisher`
- L10: `from src.application.security import sanitize_sensitive`
- L11: `from src.market_data import NormalizedBar`
- L12: `from src.platform_kernel import ArtifactManifest, DomainValidationError, QualityStatus`
- L35: `from uuid import uuid4`

**Module-level symbols**
- function `ingest_market_bars` (L15)

### `src/application/intraday_alerts.py` — 84 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `from datetime import UTC, datetime`
- L8: `from decimal import Decimal, InvalidOperation`
- L9: `from pathlib import Path`
- L10: `from uuid import NAMESPACE_URL, uuid5`
- L12: `from src.application.publication import ArtifactPublisher`
- L13: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L14: `from src.execution_gateway import Ledger`
- L15: `from src.platform_kernel import DomainValidationError, QualityStatus`

**Module-level symbols**
- class `IntradayStopAlerts` (L18): `__init__` L19, `ingest` L30, `read` L79

### `src/application/intraday_stream.py` — 102 lines

**Imports**
- L3: `from datetime import UTC, datetime`
- L4: `from pathlib import Path`
- L6: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L7: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `IntradayStreamLease` (L10): `__init__` L11, `state` L28, `start` L35, `stop` L48, `connected` L57, `mark_error` L80, `heartbeat` L91

### `src/application/jobs.py` — 647 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `import math`
- L6: `import sqlite3`
- L7: `from collections.abc import Collection`
- L8: `from dataclasses import dataclass`
- L9: `from datetime import UTC, datetime, timedelta`
- L10: `from enum import Enum`
- L11: `from pathlib import Path`
- L12: `from typing import Any`
- L13: `from uuid import uuid4`
- L15: `from src.application.security import sanitize_sensitive`
- L16: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L17: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `JobStatus` (L20)
- class `Job` (L29)
- class `JobExecutionContext` (L45): `__init__` L53, `checkpoint` L60, `heartbeat` L91, `cancelled` L94
- class `JobStore` (L98): `__init__` L99, `_connect` L103, `_initialize` L106, `_now` L136, `_payload` L140, `_row` L149, `submit` L166, `get` L234, `status_counts` L243, `active` L274, `queued_by_kind` L285, `cancel_kinds` L294, `claim_next` L346, `transition` L404, `complete` L410, `fail` L435, `request_cancel` L472, `requeue_expired_running` L495, `retry_failed` L531, `heartbeat` L556, `_require_claim` L579, `_cancel_claimed` L585, `emit` L610, `events_after` L620, `_append` L640

### `src/application/kite_accounts_web.py` — 71 lines

**Imports**
- L2: `from flask import Blueprint, jsonify, request`
- L3: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_kite_accounts_blueprint` (L6)

### `src/application/kite_auth.py` — 108 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import os`
- L6: `from collections.abc import Callable`
- L7: `from dataclasses import dataclass`
- L8: `from pathlib import Path`
- L9: `from tempfile import NamedTemporaryFile`
- L10: `from typing import Any, Protocol`
- L12: `from kiteconnect import KiteConnect`
- L47: `from local_secrets import KITE_API_KEY, KITE_API_SECRET`

**Module-level symbols**
- class `KiteClient` (L15): `login_url` L16, `generate_session` L18
- class `KiteCredentials` (L22)
- function `load_kite_credentials` (L27)
- class `KiteAuthService` (L61): `__init__` L64, `token_exists` L75, `login_url` L80, `exchange_request_token` L83, `_write_access_token` L94

### `src/application/kite_web.py` — 143 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import logging`
- L6: `import time`
- L7: `from html import escape`
- L9: `from flask import Blueprint, Response, jsonify, redirect, request, session, url_for`
- L10: `from flask.typing import ResponseReturnValue`
- L11: `from kiteconnect.exceptions import KiteException`
- L13: `from src.application.kite_auth import KiteAuthService`

**Module-level symbols**
- constant `_SESSION_STARTED_AT` (L15)
- constant `_SESSION_TTL_SECONDS` (L16)
- constant `_LOGGER` (L17)
- function `create_kite_auth_blueprint` (L20)

### `src/application/liquidity.py` — 155 lines

**Imports**
- L3: `from datetime import date`
- L4: `from decimal import Decimal, InvalidOperation`
- L5: `from typing import Any`
- L6: `from uuid import UUID`
- L8: `from src.application.publication import ArtifactPublisher`
- L9: `from src.market_data import NormalizedBar`
- L10: `from src.platform_kernel import ArtifactManifest, DomainValidationError`
- L11: `from src.reference_data import Instrument, LiquidityUniversePolicy, build_liquidity_universe`

**Module-level symbols**
- function `publish_liquidity_universe` (L14)
- function `_policy` (L33)
- function `_instrument` (L60)
- function `_bar` (L70)
- function `_mapping` (L99)
- function `_list` (L105)
- function `_only_keys` (L111)
- function `_string` (L116)
- function `_integer` (L122)
- function `_decimal` (L128)
- function `_date` (L140)
- function `_uuid` (L149)

### `src/application/live_quotes.py` — 186 lines

**Imports**
- L3: `from datetime import UTC, datetime`
- L4: `from decimal import Decimal, InvalidOperation`
- L5: `from pathlib import Path`
- L6: `from threading import RLock`
- L7: `from zoneinfo import ZoneInfo`
- L9: `from kiteconnect import KiteTicker`
- L11: `from src.application.providers import KiteStreamingProvider`
- L12: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L13: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `LiveQuotes` (L16): `__init__` L17, `ingest` L29, `read` L65, `execution_quote` L92
- class `LiveQuoteStream` (L99): `__init__` L102, `start` L108, `_ingest` L167, `stop` L180

### `src/application/managed_risk.py` — 191 lines

**Imports**
- L2: `from __future__ import annotations`
- L4: `import json`
- L5: `from datetime import datetime`
- L6: `from decimal import Decimal`
- L7: `from zoneinfo import ZoneInfo`
- L9: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L10: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `decimal` (L13)
- function `trading_date` (L23)
- class `ManagedRiskGuard` (L27): `__init__` L28, `release` L40, `validate` L44, `_sector` L166, `_performance_limits` L172

### `src/application/market_jobs.py` — 485 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import logging`
- L8: `from datetime import UTC, date, datetime, timedelta`
- L9: `from decimal import Decimal, InvalidOperation`
- L10: `from pathlib import Path`
- L11: `from typing import Any`
- L12: `from uuid import NAMESPACE_URL, uuid4, uuid5`
- L14: `from kiteconnect import KiteConnect`
- L15: `from kiteconnect.exceptions import KiteException`
- L16: `from requests.exceptions import RequestException`
- L18: `from src.application.ingestion import ingest_market_bars`
- L19: `from src.application.intraday_alerts import IntradayStopAlerts`
- L20: `from src.application.kite_auth import KiteCredentials`
- L21: `from src.application.market_repository import MarketRepository, TrackedInstrument`
- L22: `from src.application.providers import KiteHistoricalBarsProvider`
- L23: `from src.application.publication import ArtifactPublisher`
- L24: `from src.application.security import sanitize_error`
- L25: `from src.market_data import NormalizedBar`
- L26: `from src.platform_kernel import DomainValidationError`
- L378: `import concurrent.futures`

**Module-level symbols**
- constant `NSE_INDEX_SYMBOLS` (L28)
- constant `PHASE2_BENCHMARK_SYMBOLS` (L31)
- class `KiteMarketJobs` (L34): `__init__` L35, `_client` L50, `_cached_kite_nse_dump` L63, `corporate_history` L72, `sync_snapshot_instruments` L86, `fetch_index_quotes` L155, `fetch_intraday_stop_alerts` L214, `_current_history_isins` L248, `_history_context` L255, `fetch_bars` L276, `fetch_bulk_bars` L376

### `src/application/market_refresh.py` — 224 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `from collections.abc import Callable`
- L6: `from datetime import date, datetime`
- L7: `from pathlib import Path`
- L8: `from typing import Any`
- L9: `from zoneinfo import ZoneInfo`
- L11: `from src.application.jobs import JobStore`
- L12: `from src.application.market_repository import MarketRepository`
- L13: `from src.application.publication import ArtifactPublisher`
- L14: `from src.platform_kernel import DomainValidationError`
- L51: `from src.application.session_coverage import CompletedSessionCoverage`

**Module-level symbols**
- constant `PHASE2_BENCHMARK_SYMBOLS` (L17)
- class `MarketRefreshPlanner` (L22): `__init__` L23, `reconcile` L34, `schedule` L107

### `src/application/market_repository.py` — 1524 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `import math`
- L8: `from collections.abc import Iterable`
- L9: `from contextlib import nullcontext`
- L10: `from dataclasses import dataclass`
- L11: `from datetime import UTC, date, datetime, timedelta`
- L12: `from decimal import Decimal`
- L13: `from pathlib import Path`
- L14: `from uuid import uuid4`
- L16: `from src.application.security import sanitize_sensitive`
- L17: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L18: `from src.market_data import NormalizedBar`
- L19: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `TrackedInstrument` (L23)
- function `_ensure_market_column` (L33)
- class `MarketRepository` (L40): `__init__` L41, `upsert_instruments` L278, `universe_snapshot` L313, `latest_universe_snapshot` L321, `universe_snapshot_as_of` L329, `universe_snapshot_members` L349, `list_universe_snapshots` L360, `create_universe_snapshot` L370, `universe_snapshot_diff` L401, `record_exit_eligibility` L414, `resolve_pending_exit_sessions` L436, `exit_eligible_instruments` L461, `is_exit_only` L475, `instruments` L484, `tracked_instruments` L499, `instrument` L518, `instrument_by_id` L529, `universe_members` L536, `universe_build_state` L543, `active_universe_members` L550, `upsert_universe_members` L557, `replace_universe_members` L587, `delete_bars_after` L651, `latest_market_date` L670, `session_dates` L678, `nifty500_session_dates` L693, `token_assignments` L708, `token_history` L741, `upsert_bars` L766, `_validate_bars` L896, `record_quality_event` L907, `quality_events` L932, `market_history_revision` L957, `market_history_revisions` L965, `bump_market_history_revision` L978, `apply_price_factor` L992, `_capture_corporate_baseline` L1012, `preserve_corporate_action_baseline` L1038, `adjust_corporate_event` L1050, `indicators_for_date` L1108, `indicator_series` L1119, `upsert_indicators` L1137, `bars` L1162, `record_fetch_coverage` L1183, `has_coverage` L1215, `coverage` L1243, `histories` L1282, `upsert_index_quotes` L1332, `index_quotes` L1374, `index_quote_history` L1381, `upsert_corporate_action_event` L1405, `actionable_corporate_events` L1452, `corporate_action_event` L1463, `transition_corporate_action` L1471, `corporate_action_watermark` L1502, `advance_corporate_action_watermark` L1510

### `src/application/market_web.py` — 304 lines

**Imports**
- L3: `import json`
- L4: `from datetime import UTC, date, datetime, timedelta`
- L6: `from flask import Blueprint, Response, jsonify, request`
- L8: `from src.application.catalog import ArtifactCatalog`
- L9: `from src.application.corporate_actions import CorporateActions`
- L10: `from src.application.index_poller import IndexQuotePoller`
- L11: `from src.application.intraday_alerts import IntradayStopAlerts`
- L12: `from src.application.intraday_stream import IntradayStreamLease`
- L13: `from src.application.market_refresh import MarketRefreshPlanner`
- L14: `from src.application.market_repository import MarketRepository`
- L15: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_market_blueprint` (L18)

### `src/application/node_cache.py` — 339 lines

**Imports**
- L11: `from __future__ import annotations`
- L13: `import json`
- L14: `import math`
- L15: `from datetime import UTC, date, datetime`
- L16: `from pathlib import Path`
- L18: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L19: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `IndicatorNodeCache` (L22): `__init__` L31, `_require_revisions` L61, `get` L70, `put` L95, `get_series` L143, `get_bulk` L171, `put_bulk` L218, `has_coverage` L286, `cached_node_hashes` L309, `row_count` L317, `invalidate_instrument` L331

### `src/application/nse_client.py` — 87 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import csv`
- L6: `import io`
- L7: `import json`
- L9: `import requests`
- L11: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- constant `NIFTY_500_URL` (L13)
- constant `NSE_CA_URL` (L14)
- constant `NSE_BASE_URL` (L15)
- class `NseClient` (L18): `__init__` L19, `_ensure_nse_cookies` L24, `nifty_500_csv` L34, `corporate_actions` L55

### `src/application/operations.py` — 60 lines

**Imports**
- L3: `import sqlite3`
- L4: `from contextlib import closing`
- L5: `from pathlib import Path`
- L7: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `sqlite_backup` (L10)
- function `sqlite_restore` (L31)
- function `sqlite_ready` (L41)

### `src/application/payloads.py` — 202 lines

**Imports**
- L9: `from __future__ import annotations`
- L11: `from dataclasses import dataclass`
- L12: `from datetime import date`
- L13: `from typing import Any`
- L15: `from src.platform_kernel import DomainValidationError`
- L48: `from src.application.strategy_runtime import REMOVED_STRATEGIES`
- L193: `from src.application.strategy_runtime import REMOVED_STRATEGIES`

**Module-level symbols**
- class `RebuildRangePayload` (L19): `from_dict` L29, `validate` L46
- class `RebuildIndicatorsPayload` (L73): `from_dict` L81
- class `FetchBarsPayload` (L110): `from_dict` L118
- class `BacktestPayload` (L135): `from_dict` L145
- class `RebuildMultiYearPayload` (L164): `from_dict` L172, `validate` L189

### `src/application/pipeline_jobs.py` — 420 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `import logging`
- L10: `from datetime import UTC, date, datetime, timedelta`
- L11: `from pathlib import Path`
- L12: `from typing import Any`
- L13: `from uuid import NAMESPACE_URL, uuid5`
- L14: `from zoneinfo import ZoneInfo`
- L16: `from src.application.jobs import JobStatus, JobStore`
- L17: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L18: `from src.application.strategy_definitions import StrategyDefinitions`
- L19: `from src.application.strategy_runtime import StrategyRuntime`
- L20: `from src.indicators.registry import PandasTaAdapter`
- L21: `from src.platform_kernel import DomainValidationError`
- L117: `from src.application.exchange_calendar import TradingCalendar`

**Module-level symbols**
- constant `_CALCULATION_REVISION` (L23)
- class `ResearchPipelineJobs` (L26): `__init__` L27, `_request` L58, `_market_sessions` L115, `submit` L127, `_defer_advance` L215, `advance` L237, `retry_stage` L307, `cancel` L322, `status` L346, `_pipeline` L406, `_stages` L415

### `src/application/pipeline_preparation.py` — 51 lines

**Imports**
- L2: `from datetime import date, timedelta`
- L4: `from src.application.market_jobs import PHASE2_BENCHMARK_SYMBOLS`
- L5: `from src.application.session_coverage import CompletedSessionCoverage`
- L6: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `PipelinePreparation` (L9): `__init__` L10, `run` L14

### `src/application/pipeline_web.py` — 44 lines

**Imports**
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.application.pipeline_jobs import ResearchPipelineJobs`
- L6: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_pipeline_blueprint` (L9)

### `src/application/portfolio_performance.py` — 91 lines

**Imports**
- L3: `from datetime import date`
- L4: `from decimal import Decimal`
- L5: `from math import isfinite`
- L6: `from typing import Any`
- L8: `from src.execution_gateway import Ledger`
- L9: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `calculate_xirr` (L11)
- class `PortfolioPerformance` (L29): `__init__` L30, `calculate_xirr` L33, `calculate_drawdown` L79

### `src/application/portfolio_sync.py` — 130 lines

**Imports**
- L8: `from __future__ import annotations`
- L10: `import hashlib`
- L11: `import json`
- L12: `from datetime import UTC, date, datetime`
- L13: `from decimal import Decimal`
- L14: `from pathlib import Path`
- L15: `from typing import Any`
- L17: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L18: `from src.execution_gateway.kite_accounts import KiteAccounts`
- L19: `from src.execution_gateway.ledger import Ledger`
- L20: `from src.platform_kernel import DomainValidationError, Money, Quantity`
- L21: `from src.portfolio_accounting import Fill, FillSide, OpeningPosition`
- L46: `from src.application.strategy_runtime import RETAINED_STRATEGIES`

**Module-level symbols**
- class `PortfolioSync` (L24): `__init__` L25, `setup` L41, `reconcile` L113

### `src/application/portfolio_web.py` — 450 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import json`
- L6: `from datetime import date, datetime`
- L7: `from decimal import Decimal, InvalidOperation`
- L8: `from zoneinfo import ZoneInfo`
- L10: `from flask import Blueprint, Response, jsonify, request`
- L12: `from src.application.market_repository import MarketRepository`
- L13: `from src.execution_gateway import Ledger`
- L14: `from src.platform_kernel import DomainValidationError, Money, Quantity`
- L15: `from src.portfolio_accounting import Fill, FillSide`
- L27: `from src.application.portfolio_performance import PortfolioPerformance`
- L58: `from src.execution_gateway.risk_guard import RiskGuardLimits`
- L268: `from datetime import timedelta`
- L270: `from src.application.exchange_calendar import TradingCalendar`
- L308: `import hashlib`
- L309: `import json`

**Module-level symbols**
- function `_money` (L18)
- function `create_portfolio_blueprint` (L30)

### `src/application/positional_trend.py` — 166 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import math`
- L6: `from collections import deque`

**Module-level symbols**
- function `valid_bar` (L9)
- constant `_DEFAULT_RULES` (L17)
- function `_segment_features` (L25)
- function `feature_series` (L142)
- function `signal_series` (L165)

### `src/application/positional_trend_backtest.py` — 525 lines

**Imports**
- L2: `from __future__ import annotations`
- L4: `import csv`
- L5: `import hashlib`
- L6: `import json`
- L7: `import math`
- L8: `import sqlite3`
- L9: `from collections import Counter, defaultdict`
- L10: `from copy import deepcopy`
- L11: `from dataclasses import asdict, dataclass`
- L12: `from datetime import date, datetime`
- L13: `from pathlib import Path`
- L14: `from statistics import mean, median, stdev`
- L15: `from zoneinfo import ZoneInfo`
- L17: `from src.application.positional_trend import feature_series, valid_bar`

**Module-level symbols**
- function `load_data` (L20)
- function `load_market_cap_universe` (L95)
- function `load_snapshot_universe` (L148)
- class `Policy` (L227): `validate` L236
- function `_equity_at_open` (L250)
- function `simulate` (L261)
- function `benchmark_price_return` (L497)

### `src/application/positional_trend_jobs.py` — 187 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `from datetime import date, datetime`
- L8: `from pathlib import Path`
- L9: `from uuid import NAMESPACE_URL, uuid5`
- L10: `from zoneinfo import ZoneInfo`
- L12: `from src.application.positional_trend import feature_series`
- L13: `from src.application.sqlite import sqlite_connection`
- L14: `from src.platform_kernel import DomainValidationError, QualityStatus`
- L115: `from src.application.ranking_patterns import ranking_pattern_for`

**Module-level symbols**
- class `PositionalTrendJobs` (L17): `__init__` L23, `_members` L26, `_histories` L46, `_input_fingerprint` L50, `input_fingerprint` L63, `build_signals` L69, `build_range` L157, `read_signals` L168

### `src/application/positional_trend_web.py` — 52 lines

**Imports**
- L3: `from datetime import date`
- L5: `from flask import Blueprint, jsonify, request`
- L7: `from src.application.jobs import JobStore`
- L8: `from src.application.positional_trend_jobs import PositionalTrendJobs`
- L9: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_positional_trend_blueprint` (L12)

### `src/application/providers.py` — 226 lines

**Imports**
- L3: `from collections.abc import Callable, Mapping, Sequence`
- L4: `from datetime import UTC, date, datetime`
- L5: `from decimal import Decimal, InvalidOperation`
- L6: `from threading import Lock`
- L7: `from time import monotonic, sleep`
- L8: `from typing import Any`
- L10: `from src.market_data import NormalizedBar`
- L11: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `_ProviderThrottle` (L14): `__init__` L15, `wait` L23
- class `KiteHistoricalBarsProvider` (L31): `__init__` L32, `get_bars` L41
- class `KiteInstrumentProvider` (L84): `__init__` L85, `get_instruments` L96
- class `KiteQuoteProvider` (L103): `__init__` L104, `get_quote` L114
- class `KiteStreamingProvider` (L123): `__init__` L126, `start` L155, `stop` L167, `_on_connect` L178, `_on_close` L185, `_on_ticks` L188

### `src/application/publication.py` — 80 lines

**Imports**
- L3: `from typing import Any`
- L5: `from src.application.catalog import ArtifactCatalog`
- L6: `from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus`

**Module-level symbols**
- class `ArtifactPublisher` (L14): `__init__` L15, `publish_json` L19, `recover` L46

### `src/application/ranking_patterns.py` — 190 lines

**Imports**
- L7: `from __future__ import annotations`
- L9: `import hashlib`
- L10: `import json`
- L11: `import logging`
- L12: `from abc import ABC, abstractmethod`
- L13: `from collections import defaultdict`

**Module-level symbols**
- class `RankingPattern` (L18): `pattern_name` L23, `rank` L27
- class `FactorPercentileRanking` (L38): `pattern_name` L48, `rank` L51, `compute_percentiles` L84, `percentile_fingerprint` L119
- class `DirectSignalRanking` (L136): `pattern_name` L144, `rank` L147
- function `ranking_pattern_for` (L184)

### `src/application/reference_web.py` — 234 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `from datetime import UTC, date, datetime`
- L6: `from decimal import Decimal, InvalidOperation`
- L8: `from flask import Blueprint, jsonify, request`
- L10: `from src.application.market_repository import MarketRepository`
- L11: `from src.application.publication import ArtifactPublisher`
- L12: `from src.platform_kernel import ArtifactStore, DomainValidationError`

**Module-level symbols**
- function `create_reference_blueprint` (L15)

### `src/application/release_gates.py` — 94 lines

**Imports**
- L8: `from __future__ import annotations`
- L10: `import hashlib`
- L11: `from collections.abc import Iterable`
- L12: `from datetime import date`
- L13: `from pathlib import Path`
- L14: `from typing import Any`
- L16: `from src.application.operations import sqlite_backup, sqlite_ready, sqlite_restore`
- L17: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `next_tradable_session` (L20)
- function `compare_execution_events` (L28)
- function `restore_drill` (L61)
- function `dashboard_visual_contract` (L85)

### `src/application/research_jobs.py` — 1425 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `import logging`
- L10: `from collections import defaultdict`
- L11: `from datetime import UTC, date, datetime, timedelta`
- L12: `from importlib.metadata import version`
- L13: `from pathlib import Path`
- L14: `from statistics import mean, pstdev`
- L15: `from time import perf_counter`
- L16: `from typing import Any, cast`
- L17: `from uuid import NAMESPACE_URL, uuid4, uuid5`
- L19: `from src.application.jobs import JobExecutionContext`
- L20: `from src.application.market_repository import MarketRepository`
- L21: `from src.application.publication import ArtifactPublisher`
- L22: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L23: `from src.application.strategy_definitions import StrategyDefinitions`
- L24: `from src.application.strategy_runtime import StrategyRuntime`
- L25: `from src.indicators.custom import momentum_quality_from_indicators, momentum_quality_indicator_series, relative_strength_feature_series`
- L30: `from src.indicators.registry import PandasTaAdapter`
- L31: `from src.platform_kernel import DomainValidationError, QualityStatus`
- L127: `from src.application.strategy_runtime import resolve_strategy_id`
- L140: `from src.application.payloads import RebuildIndicatorsPayload`
- L166: `import pandas as pd`
- L168: `from src.indicators.dag import DagExecutor, DagGraph`
- L174: `import hashlib`
- L279: `from src.application.payloads import RebuildRangePayload`
- L440: `from src.application.ranking_patterns import ranking_pattern_for`
- L883: `from src.application.strategy_runtime import REMOVED_STRATEGIES, resolve_strategy_id`
- L1106: `from src.application.strategy_runtime import REMOVED_STRATEGIES, resolve_strategy_id`
- L1325: `from datetime import UTC, datetime`
- L1393: `from datetime import UTC, datetime`

**Module-level symbols**
- class `ResearchJobs` (L34): `__init__` L35, `_indicator_set` L125, `calculate_day` L133, `rebuild_indicators` L136, `rebuild_range` L276, `_factor_multiplier` L591, `sector_normalize` L608, `correlations` L711, `anomalies` L805, `_calculate_day` L882, `rank_week` L1105, `top_rankings` L1209, `all_rankings` L1222, `ranking_weeks` L1234, `read_snapshot` L1245, `upsert_percentile_snapshot` L1309, `read_percentile_snapshot` L1352, `record_lineage` L1379, `read_lineage` L1418

### `src/application/research_web.py` — 198 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `from datetime import date`
- L7: `from flask import Blueprint, jsonify, request`
- L9: `from src.application.jobs import JobStore`
- L10: `from src.application.research_jobs import ResearchJobs`
- L11: `from src.platform_kernel import ArtifactStore, DomainValidationError`

**Module-level symbols**
- function `create_research_blueprint` (L14)

### `src/application/runs.py` — 18 lines

**Imports**
- L3: `from src.application.publication import ArtifactPublisher`
- L4: `from src.backtesting import BacktestResult`
- L5: `from src.platform_kernel import ArtifactManifest`

**Module-level symbols**
- function `publish_backtest_result` (L8)

### `src/application/runtime.py` — 31 lines

**Imports**
- L3: `import os`
- L4: `from pathlib import Path`

**Module-level symbols**
- class `RuntimeConfig` (L7)

### `src/application/security.py` — 75 lines

**Imports**
- L3: `import logging`
- L4: `import re`
- L5: `import traceback`
- L6: `from collections.abc import Mapping, Sequence`
- L7: `from typing import Any`
- L9: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- constant `_SENSITIVE_KEYS` (L11)
- constant `_SENSITIVE_SUFFIXES` (L23)
- constant `_REDACTED` (L24)
- function `_is_sensitive_key` (L27)
- function `sanitize_sensitive` (L32)
- function `sanitize_error` (L44)
- constant `_SECRET_ASSIGNMENT` (L51)
- function `sanitize_text` (L59)
- class `RedactingLogFilter` (L64): `filter` L67

### `src/application/session_coverage.py` — 91 lines

**Imports**
- L3: `from bisect import bisect_right`
- L4: `from collections import defaultdict`
- L5: `from datetime import date, datetime, timedelta`
- L6: `from zoneinfo import ZoneInfo`
- L8: `from src.application.market_refresh import PHASE2_BENCHMARK_SYMBOLS`
- L9: `from src.application.sqlite import sqlite_connection`
- L10: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `CompletedSessionCoverage` (L13): `__init__` L14, `read` L18, `record` L85

### `src/application/sqlite.py` — 71 lines

**Imports**
- L3: `import sqlite3`
- L4: `from collections.abc import Callable, Iterator, Mapping, Sequence`
- L5: `from contextlib import contextmanager`
- L6: `from pathlib import Path`
- L8: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `sqlite_connection` (L14)
- function `migrate_sqlite` (L45)

### `src/application/strategies_web.py` — 44 lines

**Imports**
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.application.strategy_definitions import StrategyDefinitions`
- L6: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_strategies_blueprint` (L9)

### `src/application/strategy_definitions.py` — 260 lines

**Imports**
- L8: `from __future__ import annotations`
- L10: `import hashlib`
- L11: `import json`
- L12: `import math`
- L13: `import re`
- L14: `from datetime import UTC, datetime`
- L15: `from pathlib import Path`
- L16: `from typing import Any`
- L17: `from uuid import NAMESPACE_URL, uuid5`
- L19: `import yaml`
- L21: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L22: `from src.indicators.custom import CUSTOM_IMPLEMENTATIONS`
- L23: `from src.indicators.dag import APPROVED_OPERATIONS, DagGraph`
- L24: `from src.indicators.registry import PandasTaAdapter`
- L25: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- constant `_STATUSES` (L27)
- constant `_SEMVER` (L28)
- class `StrategyDefinitions` (L30): `__init__` L31, `create_from_yaml` L46, `get` L75, `revisions` L82, `active` L87, `active_revisions` L95, `activate` L102, `_decode` L116, `_validate` L121, `_validate_operations` L243

### `src/application/strategy_runtime.py` — 199 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `from collections.abc import Mapping, Sequence`
- L6: `from pathlib import Path`
- L7: `from typing import Any, cast`
- L9: `import pandas as pd`
- L11: `from src.application.strategy_definitions import StrategyDefinitions`
- L12: `from src.indicators.custom import CROSS_SECTION_IMPLEMENTATIONS, INSTRUMENT_IMPLEMENTATIONS, INSTRUMENT_SERIES_IMPLEMENTATIONS, BenchmarkImplementation, InstrumentImplementation`
- L19: `from src.indicators.dag import DagExecutor, DagGraph`
- L20: `from src.indicators.registry import PandasTaAdapter`
- L21: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- constant `LEGACY_STRATEGY_MAP` (L24)
- constant `NAMED_TO_LEGACY` (L28)
- constant `REMOVED_STRATEGIES` (L29)
- constant `RETAINED_STRATEGIES` (L30)
- function `resolve_strategy_id` (L33)
- class `StrategyRuntime` (L38): `__init__` L39, `seed` L43, `revision` L59, `strategy_ids` L69, `factor_weights` L75, `strategy_kind` L81, `signal_rules` L85, `benchmark` L92, `portfolio_policy` L97, `compute` L104, `compute_series` L119, `_compute_dag_series` L144, `cross_section` L177, `factor_multiplier` L184

### `src/application/universe_jobs.py` — 134 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import csv`
- L6: `import hashlib`
- L7: `import io`
- L8: `from datetime import date, datetime, timedelta`
- L9: `from typing import Any`
- L10: `from uuid import NAMESPACE_URL, uuid5`
- L11: `from zoneinfo import ZoneInfo`
- L13: `from src.application.exchange_calendar import TradingCalendar`
- L14: `from src.application.market_repository import MarketRepository`
- L15: `from src.application.nse_client import NseClient`
- L16: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `UniverseJobs` (L19): `__init__` L22, `download_nifty500_constituents` L27, `_record_exit_eligibility` L60, `detect_universe_exits` L93, `_parse` L121

### `src/application/universe_web.py` — 61 lines

**Imports**
- L3: `from datetime import UTC, date, datetime`
- L5: `from flask import Blueprint, jsonify, request`
- L7: `from src.application.jobs import JobStore`
- L8: `from src.application.market_repository import MarketRepository`
- L9: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `create_universe_blueprint` (L12)

### `src/application/web.py` — 163 lines

**Imports**
- L7: `import json`
- L8: `import time`
- L9: `from collections.abc import Collection`
- L10: `from pathlib import Path`
- L12: `from flask import Blueprint, Response, jsonify, request, stream_with_context`
- L14: `from src.application.jobs import Job, JobStore`
- L15: `from src.application.worker import BackgroundWorker, JobWorker`
- L16: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- function `_job_response` (L19)
- function `create_operations_blueprint` (L36)

### `src/application/wiki_web.py` — 43 lines

**Imports**
- L3: `from pathlib import Path`
- L5: `from flask import Blueprint, jsonify, render_template`

**Module-level symbols**
- constant `_WIKI_DIRECTORY` (L8)
- constant `_PAGES` (L9)
- function `create_wiki_blueprint` (L20)

### `src/application/worker.py` — 140 lines

**Imports**
- L3: `import inspect`
- L4: `import logging`
- L5: `import threading`
- L6: `from collections.abc import Callable, Mapping`
- L7: `from datetime import UTC, datetime`
- L8: `from typing import Any`
- L10: `from src.application.jobs import Job, JobExecutionContext, JobStore`
- L11: `from src.application.security import sanitize_error`
- L12: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `JobWorker` (L17): `__init__` L23, `run_once` L28
- class `BackgroundWorker` (L65): `__init__` L68, `start` L81, `stop` L97, `is_alive` L103, `status` L106, `_run_loop` L127

### `src/backtesting/__init__.py` — 19 lines

**Imports**
- L3: `from .api import BacktestResult, BacktestRunManifest, BacktestStep, FillModelRevision, SimulatedFill, run`

**Module-level symbols**
- None

### `src/backtesting/api.py` — 586 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `import re`
- L6: `from collections import defaultdict`
- L7: `from collections.abc import Mapping`
- L8: `from dataclasses import asdict, dataclass, field`
- L9: `from datetime import date`
- L10: `from decimal import Decimal`
- L11: `from uuid import UUID, uuid4`
- L13: `from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value`
- L19: `from src.portfolio_engine import Candidate, Decision, DecisionType, ExecutionAssumptions, MarketBar, PortfolioPolicy, PortfolioState, evaluate`

**Module-level symbols**
- constant `_SEMVER` (L30)
- class `FillModelRevision` (L34): `__post_init__` L43, `execution_assumptions` L66
- class `BacktestRunManifest` (L71): `__post_init__` L83, `fingerprint` L96
- class `BacktestStep` (L115)
- class `SimulatedFill` (L124)
- class `BacktestResult` (L140): `_xirr` L152, `metrics` L181, `period_fills` L269, `completed_trades` L276, `annual_returns` L314, `trade_counts` L328, `sanity_flags` L336, `publish` L349, `upstream_ids` L362, `to_payload` L371
- constant `_SELLS` (L419)
- function `run` (L429)

### `src/execution_gateway/__init__.py` — 6 lines

**Imports**
- L3: `from .broker import BrokerExecutionGateway, BrokerOrderService, KiteExecutionGateway`
- L4: `from .ledger import Ledger`

**Module-level symbols**
- None

### `src/execution_gateway/broker.py` — 473 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import json`
- L6: `from collections.abc import Iterable`
- L7: `from datetime import UTC, date, datetime`
- L8: `from decimal import Decimal`
- L9: `from pathlib import Path`
- L10: `from typing import Protocol`
- L11: `from uuid import NAMESPACE_URL, uuid4, uuid5`
- L13: `from kiteconnect import KiteConnect`
- L15: `from src.application.kite_auth import KiteCredentials`
- L16: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L17: `from src.platform_kernel import DomainValidationError, Money, Quantity`
- L18: `from src.portfolio_accounting import Fill, FillSide`
- L20: `from .ledger import Ledger`
- L334: `from src.application.market_repository import MarketRepository`

**Module-level symbols**
- class `BrokerExecutionGateway` (L23): `submit_order` L24, `order_status` L25
- class `KiteExecutionGateway` (L28): `__init__` L31, `arm` L50, `disarm` L54, `controls` L57, `_client` L65, `_order_tag` L86, `submit_order` L95, `order_status` L115, `find_order` L133
- class `BrokerOrderService` (L142): `__init__` L143, `execution_controls` L180, `create_basket` L189, `basket` L223, `submit_basket` L231, `create_intent` L241, `get` L288, `prepare_proposal` L295, `_assert_current_buy_membership` L331, `submit` L346, `reconcile` L390, `manual_fill` L431, `_post_fill_once` L450, `_event` L472

### `src/execution_gateway/kite_accounts.py` — 182 lines

**Imports**
- L3: `from datetime import UTC, datetime`
- L5: `from kiteconnect import KiteConnect`
- L7: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L8: `from src.platform_kernel import DomainValidationError`
- L105: `from src.application.strategy_runtime import RETAINED_STRATEGIES`

**Module-level symbols**
- class `KiteAccounts` (L11): `__init__` L14, `_initialize` L19, `register_account` L52, `list_accounts` L72, `get_credentials` L80, `update_session` L91, `link_portfolio` L104, `get_portfolio` L117, `binding` L128, `client` L135, `login_url` L143, `authenticate` L147, `validate` L161, `portfolio_inputs` L175

### `src/execution_gateway/ledger.py` — 566 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `import sqlite3`
- L6: `from collections.abc import Iterable`
- L7: `from contextlib import nullcontext`
- L8: `from datetime import UTC, date, datetime`
- L9: `from decimal import Decimal`
- L10: `from pathlib import Path`
- L12: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L13: `from src.platform_kernel import DomainValidationError, Money, Quantity`
- L14: `from src.portfolio_accounting import AccountingEvent, Fill, FillSide, OpeningPosition, project`
- L196: `import hashlib`
- L516: `from decimal import Decimal`
- L518: `from src.portfolio_accounting.api import Quantity`

**Module-level symbols**
- class `Ledger` (L17): `__init__` L18, `_connect` L22, `_initialize` L25, `open_account` L62, `record_fills` L74, `import_opening_positions` L178, `record_cash_transfer` L247, `projection` L322, `open_instrument_ids` L325, `projection_at` L333, `journal` L359, `save_valuation` L407, `valuations` L431, `accounts` L445, `events` L456, `_fill_event` L483, `_opening_position_event` L499, `_parse_accounting_event` L511, `_event_fill` L530, `_execution_time` L546, `_cash_balance` L552

### `src/execution_gateway/risk_guard.py` — 90 lines

**Imports**
- L3: `import json`
- L4: `from dataclasses import dataclass`
- L5: `from datetime import UTC, datetime`
- L6: `from math import isfinite`
- L7: `from typing import Any`
- L9: `from src.application.sqlite import migrate_sqlite, sqlite_connection`
- L10: `from src.platform_kernel import DomainValidationError`

**Module-level symbols**
- class `RiskGuardLimits` (L14): `__post_init__` L25
- class `PortfolioRiskConfig` (L42): `__init__` L43, `_initialize` L47, `get_limits` L64, `update_limits` L74

### `src/indicators/__init__.py` — 21 lines

**Imports**
- L3: `from .api import FeatureSnapshot, FeatureValue, IndicatorConfiguration, IndicatorRevision, compute_feature`
- L10: `from .dag import DagExecutor, DagGraph, DagNode`

**Module-level symbols**
- None

### `src/indicators/api.py` — 149 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `import re`
- L6: `from collections.abc import Mapping`
- L7: `from dataclasses import asdict, dataclass, field`
- L8: `from datetime import date`
- L9: `from decimal import Decimal`
- L10: `from uuid import UUID, uuid4`
- L12: `from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value`

**Module-level symbols**
- constant `_SEMVER` (L14)
- class `IndicatorRevision` (L18): `__post_init__` L27, `definition_hash` L41
- class `IndicatorConfiguration` (L58): `create` L65
- class `FeatureValue` (L81): `__post_init__` L85
- class `FeatureSnapshot` (L93): `publish` L100
- function `compute_feature` (L117)

### `src/indicators/custom/__init__.py` — 77 lines

**Imports**
- L3: `from collections.abc import Callable, Sequence`
- L4: `from typing import Any`
- L6: `from src.application.positional_trend import feature_series as positional_trend_feature_series`
- L8: `from .momentum_quality import momentum_quality_feature_series, momentum_quality_features, momentum_quality_from_indicators, momentum_quality_indicator_series`
- L14: `from .relative_strength import relative_strength_factor_series, relative_strength_factors, relative_strength_feature_series, relative_strength_features`

**Module-level symbols**
- function `positional_trend_features` (L22)
- function `positional_trend_series` (L28)
- constant `INSTRUMENT_IMPLEMENTATIONS` (L44)
- constant `INSTRUMENT_SERIES_IMPLEMENTATIONS` (L49)
- constant `CROSS_SECTION_IMPLEMENTATIONS` (L54)
- constant `CUSTOM_IMPLEMENTATIONS` (L57)

### `src/indicators/custom/momentum_quality.py` — 199 lines

**Imports**
- L8: `from __future__ import annotations`
- L10: `import math`
- L11: `from collections.abc import Sequence`
- L12: `from typing import Any`
- L14: `import pandas as pd`

**Module-level symbols**
- constant `_MOMENTUM_RSI_WEIGHT` (L16)
- constant `_MOMENTUM_PPO_WEIGHT` (L17)
- constant `_MOMENTUM_PPO_HISTOGRAM_WEIGHT` (L18)
- constant `_MOMENTUM_PURE_WEIGHT` (L19)
- function `_goldilocks` (L22)
- function `_rsi_regime` (L34)
- function `_percent_b_score` (L46)
- function `_value` (L56)
- function `momentum_quality_indicator_series` (L61)
- function `momentum_quality_from_indicators` (L151)
- function `momentum_quality_feature_series` (L191)
- function `momentum_quality_features` (L196)

### `src/indicators/custom/relative_strength.py` — 220 lines

**Imports**
- L8: `from __future__ import annotations`
- L10: `import math`
- L11: `from collections.abc import Sequence`
- L12: `from typing import Any, cast`
- L14: `import pandas as pd`

**Module-level symbols**
- function `_finite` (L17)
- function `_clip` (L25)
- function `relative_strength_feature_series` (L29)
- function `relative_strength_features` (L150)
- function `relative_strength_factors` (L160)
- function `relative_strength_factor_series` (L208)

### `src/indicators/dag.py` — 652 lines

**Imports**
- L13: `from __future__ import annotations`
- L15: `import hashlib`
- L16: `import json`
- L17: `import logging`
- L20: `import math`
- L21: `from collections import defaultdict, deque`
- L22: `from collections.abc import Mapping, Sequence`
- L23: `from dataclasses import dataclass`
- L24: `from typing import Any`
- L26: `import pandas as pd`
- L28: `from src.platform_kernel import DomainValidationError`
- L30: `from .registry import IndicatorSpec, PandasTaAdapter, provider_output_role, selected_indicator_output`
- L463: `import pandas_ta`

**Module-level symbols**
- constant `PRIMITIVE_FIELDS` (L40)
- constant `APPROVED_OPERATIONS` (L45)
- class `DagNode` (L59): `__post_init__` L88, `input_refs` L95, `content_hash` L100
- class `DagGraph` (L124): `__init__` L131, `nodes` L144, `_validate_references` L147, `_topological_sort` L161, `execution_order` L192, `max_warmup` L196, `unique_content_hashes` L225, `content_hash` L235, `_compute_content_hashes` L242, `to_dict` L270, `from_dict` L286, `from_yaml_sections` L303
- class `DagExecutor` (L371): `__init__` L378, `execute` L381, `_execute_node` L429, `_execute_pandas_ta` L441, `_execute_operation` L504
- function `_interpolate_piecewise` (L635)

### `src/indicators/registry.py` — 184 lines

**Imports**
- L7: `from __future__ import annotations`
- L9: `import importlib.metadata`
- L10: `import math`
- L11: `from collections.abc import Callable, Mapping`
- L12: `from dataclasses import dataclass`
- L13: `from enum import StrEnum`
- L14: `from typing import Any`
- L16: `import pandas as pd`
- L18: `from src.platform_kernel import DomainValidationError`
- L117: `import pandas_ta`

**Module-level symbols**
- class `IndicatorProvider` (L21)
- class `SupportStatus` (L27)
- class `IndicatorSpec` (L37): `catalogue_item` L49
- constant `_SPECS` (L70)
- constant `_PROVIDER_OUTPUT_PREFIXES` (L82)
- function `selected_indicator_output` (L89)
- function `provider_output_role` (L102)
- class `PandasTaAdapter` (L110): `__init__` L115, `catalogue` L124, `spec` L127, `calculate` L133, `_validate_series` L160, `validate_parameters` L169

### `src/market_data/__init__.py` — 17 lines

**Imports**
- L3: `from .api import AdjustmentBasis, MarketDataSnapshot, NormalizedBar, publish_raw_snapshot, publish_snapshot`

**Module-level symbols**
- None

### `src/market_data/api.py` — 126 lines

**Imports**
- L3: `from collections.abc import Iterable, Mapping`
- L4: `from dataclasses import asdict, dataclass`
- L5: `from datetime import date`
- L6: `from decimal import Decimal`
- L7: `from enum import Enum`
- L8: `from uuid import UUID, uuid4`
- L10: `from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus`

**Module-level symbols**
- class `AdjustmentBasis` (L18)
- class `NormalizedBar` (L25): `__post_init__` L35
- class `MarketDataSnapshot` (L59): `__post_init__` L66
- function `publish_raw_snapshot` (L78)
- function `publish_snapshot` (L100)

### `src/platform_kernel/__init__.py` — 41 lines

**Imports**
- L7: `from .api import ArtifactManifest, ArtifactStore, Broker, CommandMetadata, DomainValidationError, FrozenDict, HistoricalBarsProvider, InstrumentProvider, LiveQuoteProvider, Money, QualityStatus, Quantity, SqliteArtifactStore, VersionedReference, freeze_value`

**Module-level symbols**
- None

### `src/platform_kernel/api.py` — 31 lines

**Imports**
- L3: `from .artifacts import ArtifactManifest, ArtifactStore, QualityStatus, SqliteArtifactStore`
- L4: `from .contracts import CommandMetadata, FrozenDict, Money, Quantity, VersionedReference, freeze_value`
- L12: `from .errors import DomainValidationError`
- L13: `from .ports import Broker, HistoricalBarsProvider, InstrumentProvider, LiveQuoteProvider`

**Module-level symbols**
- None

### `src/platform_kernel/artifacts.py` — 338 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `import os`
- L6: `import shutil`
- L7: `import sqlite3`
- L8: `import zlib`
- L9: `from contextlib import closing`
- L10: `from dataclasses import asdict, dataclass`
- L11: `from datetime import UTC, datetime`
- L12: `from enum import Enum`
- L13: `from pathlib import Path`
- L14: `from tempfile import mkdtemp`
- L15: `from typing import Any`
- L17: `from .errors import DomainValidationError`

**Module-level symbols**
- class `QualityStatus` (L20)
- class `ArtifactManifest` (L30)
- class `ArtifactStore` (L40): `__init__` L43, `_parts` L49, `_encode` L56, `publish_json` L61, `read_json` L107, `recover_staging` L142, `manifests` L151, `artifact_locations` L159, `quarantine` L169, `is_published` L182
- class `SqliteArtifactStore` (L190): `__init__` L193, `_connect` L216, `publish_json` L223, `read_json` L266, `recover_staging` L301, `manifests` L304, `artifact_locations` L307, `has_payloads` L314, `quarantine` L322, `is_published` L333

### `src/platform_kernel/contracts.py` — 101 lines

**Imports**
- L7: `from dataclasses import dataclass`
- L8: `from decimal import Decimal, InvalidOperation`
- L9: `from typing import Any, NewType`
- L10: `from uuid import UUID`
- L12: `from .errors import DomainValidationError`

**Module-level symbols**
- class `FrozenDict` (L17): `_immutable` L20, `__copy__` L31, `__deepcopy__` L34
- function `freeze_value` (L38)
- function `_finite_decimal` (L49)
- class `Money` (L60): `__post_init__` L66
- class `Quantity` (L74): `__post_init__` L79
- class `VersionedReference` (L85)
- class `CommandMetadata` (L93): `__post_init__` L99

### `src/platform_kernel/errors.py` — 5 lines

**Imports**
- None

**Module-level symbols**
- class `DomainValidationError` (L4)

### `src/platform_kernel/ports.py` — 23 lines

**Imports**
- L3: `from collections.abc import Sequence`
- L4: `from datetime import date`
- L5: `from typing import Protocol`

**Module-level symbols**
- class `HistoricalBarsProvider` (L8): `get_bars` L9
- class `InstrumentProvider` (L14): `get_instruments` L15
- class `LiveQuoteProvider` (L18): `get_quote` L19
- class `Broker` (L22): `submit` L23

### `src/portfolio_accounting/__init__.py` — 5 lines

**Imports**
- L3: `from .api import Fill, FillSide, Lot, PortfolioProjection, project, OpeningPosition, AccountingEvent`

**Module-level symbols**
- None

### `src/portfolio_accounting/api.py` — 147 lines

**Imports**
- L3: `from collections.abc import Iterable`
- L4: `from dataclasses import dataclass, field`
- L5: `from datetime import UTC, date, datetime`
- L6: `from decimal import Decimal`
- L7: `from enum import Enum`
- L8: `from typing import Union`
- L10: `from src.platform_kernel import DomainValidationError, Money, Quantity`

**Module-level symbols**
- class `FillSide` (L13)
- class `Fill` (L19): `__post_init__` L30
- class `OpeningPosition` (L47): `__post_init__` L55
- class `Lot` (L64)
- class `PortfolioProjection` (L72)
- function `project` (L78)

### `src/portfolio_engine/__init__.py` — 25 lines

**Imports**
- L3: `from .api import Candidate, Decision, DecisionType, ExecutionAssumptions, Holding, MarketBar, PortfolioPolicy, PortfolioState, evaluate`

**Module-level symbols**
- None

### `src/portfolio_engine/api.py` — 542 lines

**Imports**
- L8: `from collections.abc import Mapping, Sequence`
- L9: `from dataclasses import dataclass, field, replace`
- L10: `from datetime import date`
- L11: `from decimal import ROUND_DOWN, Decimal`
- L12: `from enum import Enum`
- L14: `from src.platform_kernel import DomainValidationError, Money, Quantity`

**Module-level symbols**
- class `DecisionType` (L17)
- function `_amount` (L29)
- class `MarketBar` (L35): `__post_init__` L44
- class `Holding` (L56): `__post_init__` L64
- class `Candidate` (L71): `__post_init__` L78
- class `PortfolioPolicy` (L94): `__post_init__` L108
- class `ExecutionAssumptions` (L141): `__post_init__` L148
- class `PortfolioState` (L160): `__post_init__` L164
- class `Decision` (L173)
- function `_sell_decision` (L182)
- function `_with_costs` (L221)
- function `_execution_price` (L250)
- function `_volume_cap` (L256)
- function `evaluate` (L262)

### `src/reference_data/__init__.py` — 39 lines

**Imports**
- L3: `from .api import CorporateAction, CorporateActionSnapshot, ExchangeCalendar, FundamentalSnapshot, Instrument, InstrumentAlias, LiquidityUniverseMember, LiquidityUniversePolicy, LiquidityUniverseSnapshot, UniverseExclusionReason, UniverseSnapshot, build_liquidity_universe, publish_alias_snapshot, publish_calendar_snapshot, publish_instrument_snapshot, resolve_alias`

**Module-level symbols**
- None

### `src/reference_data/api.py` — 492 lines

**Imports**
- L3: `from collections.abc import Iterable, Mapping`
- L4: `from dataclasses import asdict, dataclass`
- L5: `from datetime import date`
- L6: `from decimal import Decimal`
- L7: `from enum import Enum`
- L8: `from typing import Protocol`
- L9: `from uuid import UUID, uuid4`
- L11: `from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus, freeze_value`

**Module-level symbols**
- class `Instrument` (L21): `__post_init__` L27
- class `InstrumentAlias` (L33): `__post_init__` L41
- class `UniverseSnapshot` (L54): `create` L61, `publish` L69
- class `UniverseExclusionReason` (L82)
- class `LiquidityBar` (L93): `instrument_id` L97, `as_of_date` L100, `open` L103, `high` L106, `low` L109, `close` L112, `volume` L115, `traded_value` L118
- class `LiquidityUniversePolicy` (L122): `__post_init__` L137
- class `LiquidityUniverseMember` (L156): `__post_init__` L165
- class `LiquidityUniverseSnapshot` (L187): `__post_init__` L194, `instrument_ids` L205, `to_payload` L208, `publish` L228
- function `build_liquidity_universe` (L236)
- function `_is_flat_ohlc` (L325)
- function `_median` (L330)
- class `CorporateAction` (L339): `__post_init__` L345
- class `ExchangeCalendar` (L351): `__post_init__` L356, `is_trading_day` L365, `next_trading_day` L368, `sessions_between` L371
- class `CorporateActionSnapshot` (L378): `publish` L383
- class `FundamentalSnapshot` (L398): `__post_init__` L404, `publish` L409
- function `publish_alias_snapshot` (L422)
- function `publish_calendar_snapshot` (L444)
- function `resolve_alias` (L453)
- function `publish_instrument_snapshot` (L472)

### `src/strategies/__init__.py` — 23 lines

**Imports**
- L3: `from .api import PercentileSnapshot, PortfolioPolicyRevision, RankingMember, RankingSnapshot, ScoreSnapshot, StrategyRevision, build_research_snapshots, rank_feature_values`

**Module-level symbols**
- None

### `src/strategies/api.py` — 363 lines

**Imports**
- L3: `import hashlib`
- L4: `import json`
- L5: `import re`
- L6: `from collections.abc import Mapping`
- L7: `from dataclasses import dataclass`
- L8: `from datetime import date`
- L9: `from decimal import Decimal`
- L10: `from enum import Enum`
- L11: `from uuid import UUID, uuid4`
- L13: `from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value`

**Module-level symbols**
- constant `_SEMVER` (L15)
- class `RevisionStatus` (L18)
- class `PortfolioPolicyRevision` (L28): `__post_init__` L35
- class `StrategyRevision` (L52): `__post_init__` L62, `definition_hash` L86
- class `RankingMember` (L102): `__post_init__` L111
- class `PercentileSnapshot` (L123): `__post_init__` L131, `publish` L136
- class `ScoreSnapshot` (L154): `__post_init__` L161, `publish` L166
- class `RankingSnapshot` (L182): `create` L191, `publish` L234
- function `build_research_snapshots` (L266)
- function `rank_feature_values` (L353)

