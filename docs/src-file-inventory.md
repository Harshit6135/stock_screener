# Source file inventory

Static inventory of 127 Python files currently present under `src/`, regenerated from the current worktree on 2026-10-03. Imports and module-level declarations are collected from AST nodes. This maps ownership candidates; reachability and ownership still require call-graph review.

Migration state: implementation and test-tree work are tracked in [the restructure migration manifest](architecture/restructure-migration-manifest.md). The sole test tree mirrors `src/`; each focused test module is named `test_<source_module>.py` and covers that source module.

## Inventory

### `src/__init__.py` (5 lines)

Imports:
- None

Top-level declarations:
- None

### `src/domains/__init__.py` (1 lines)

Imports:
- None

Top-level declarations:
- None

### `src/domains/artifacts/__init__.py` (6 lines)

Imports:
- L3: `from .catalog import ArtifactCatalog`
- L4: `from .publication import ArtifactPublisher`

Top-level declarations:
- L6: `__all__` (module value)

### `src/domains/artifacts/catalog.py` (286 lines)

Imports:
- L3: `import json`
- L4: `import sqlite3`
- L5: `from pathlib import Path`
- L7: `from src.platform_kernel import ArtifactManifest, DomainValidationError`
- L8: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L11: `ArtifactCatalog` (ClassDef)

### `src/domains/artifacts/publication.py` (85 lines)

Imports:
- L3: `from typing import Any`
- L5: `from src.platform_kernel import ( ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus, )`
- L12: `from .catalog import ArtifactCatalog`

Top-level declarations:
- L15: `ArtifactPublisher` (ClassDef)

### `src/domains/backtesting/__init__.py` (25 lines)

Imports:
- L3: `from .api import ( BacktestExecutionAssumptions, BacktestResult, BacktestRunManifest, BacktestRunStore, BacktestStep, FillModelRevision, PortfolioEnginePort, SimulatedFill, run, )`

Top-level declarations:
- L15: `__all__` (module value)

### `src/domains/backtesting/api.py` (25 lines)

Imports:
- L3: `from .repository import BacktestRunStore`
- L4: `from .simulation import ( BacktestExecutionAssumptions, BacktestResult, BacktestRunManifest, BacktestStep, FillModelRevision, PortfolioEnginePort, SimulatedFill, run, )`

Top-level declarations:
- L15: `__all__` (module value)

### `src/domains/backtesting/event_study.py` (219 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import math`
- L6: `from collections import Counter, defaultdict`
- L7: `from statistics import mean`
- L9: `import numpy as np`

Top-level declarations:
- L11: `WINDOWS` (module value)
- L15: `HORIZONS` (module value)
- L16: `COST` (module value)
- L19: `_valid_bar` (FunctionDef)
- L33: `evaluate_signal` (FunctionDef)
- L78: `_summary` (FunctionDef)
- L92: `stationary_interval` (FunctionDef)
- L145: `window_report` (FunctionDef)
- L182: `validation_gate` (FunctionDef)

### `src/domains/backtesting/repository.py` (142 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from pathlib import Path`
- L7: `from src.platform_kernel import DomainValidationError`
- L8: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L11: `BacktestRunStore` (ClassDef)

### `src/domains/backtesting/simulation.py` (638 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `import re`
- L6: `from collections import defaultdict`
- L7: `from collections.abc import Mapping, Sequence`
- L8: `from dataclasses import asdict, dataclass, field`
- L9: `from datetime import date`
- L10: `from decimal import Decimal`
- L11: `from typing import Any, Protocol`
- L12: `from uuid import UUID, uuid4`
- L14: `from src.platform_kernel import ( ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value, )`

Top-level declarations:
- L21: `_SEMVER` (module value)
- L25: `BacktestExecutionAssumptions` (ClassDef)
- L33: `PortfolioEnginePort` (ClassDef)
- L53: `FillModelRevision` (ClassDef)
- L90: `BacktestRunManifest` (ClassDef)
- L134: `BacktestStep` (ClassDef)
- L143: `SimulatedFill` (ClassDef)
- L159: `BacktestResult` (ClassDef)
- L443: `_SELLS` (module value)
- L453: `_decision_name` (FunctionDef)
- L457: `run` (FunctionDef)

### `src/domains/execution/__init__.py` (19 lines)

Imports:
- L3: `from .accounts import KiteAccounts`
- L4: `from .api import KiteAuthService, KiteClient, KiteCredentials, load_kite_credentials`
- L5: `from .broker_adapter import BrokerExecutionGateway, KiteExecutionGateway`
- L6: `from .order_repository import BrokerOrderRepository`
- L7: `from .streaming_provider import KiteStreamingProvider`

Top-level declarations:
- L9: `__all__` (module value)

### `src/domains/execution/accounts.py` (199 lines)

Imports:
- L3: `from datetime import UTC, datetime`
- L5: `from kiteconnect import KiteConnect`
- L7: `from src.platform_kernel import DomainValidationError`
- L8: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L11: `KiteAccounts` (ClassDef)

### `src/domains/execution/api.py` (5 lines)

Imports:
- L3: `from .kite_auth import KiteAuthService, KiteClient, KiteCredentials, load_kite_credentials`

Top-level declarations:
- L5: `__all__` (module value)

### `src/domains/execution/broker_adapter.py` (146 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from collections.abc import Iterable`
- L6: `from pathlib import Path`
- L7: `from typing import Protocol`
- L8: `from uuid import NAMESPACE_URL, uuid5`
- L10: `from kiteconnect import KiteConnect  # type: ignore[import-untyped]`
- L12: `from src.platform_kernel import DomainValidationError`
- L14: `from .kite_auth import KiteCredentials`

Top-level declarations:
- L17: `BrokerExecutionGateway` (ClassDef)
- L22: `KiteExecutionGateway` (ClassDef)

### `src/domains/execution/kite_auth.py` (108 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import os`
- L6: `from collections.abc import Callable`
- L7: `from dataclasses import dataclass`
- L8: `from pathlib import Path`
- L9: `from tempfile import NamedTemporaryFile`
- L10: `from typing import Any, Protocol`
- L12: `from kiteconnect import KiteConnect  # type: ignore[import-untyped]`
- L47: `from local_secrets import KITE_API_KEY, KITE_API_SECRET`

Top-level declarations:
- L15: `KiteClient` (ClassDef)
- L22: `KiteCredentials` (ClassDef)
- L27: `load_kite_credentials` (FunctionDef)
- L61: `KiteAuthService` (ClassDef)

### `src/domains/execution/order_repository.py` (311 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import json`
- L6: `from pathlib import Path`
- L8: `from src.platform_kernel import DomainValidationError`
- L9: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L12: `BrokerOrderRepository` (ClassDef)
- L311: `__all__` (module value)

### `src/domains/execution/streaming_provider.py` (118 lines)

Imports:
- L3: `from collections.abc import Callable, Mapping, Sequence`
- L4: `from datetime import UTC, datetime`
- L5: `from decimal import Decimal, InvalidOperation`
- L6: `from typing import Any`
- L8: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L11: `KiteStreamingProvider` (ClassDef)

### `src/domains/indicators/__init__.py` (51 lines)

Imports:
- L3: `from .api import ( FeatureSnapshot, FeatureValue, IndicatorConfiguration, IndicatorRevision, compute_feature, )`
- L10: `from .dag import APPROVED_OPERATIONS, PRIMITIVE_FIELDS, DagExecutor, DagGraph, DagNode`
- L11: `from .momentum_quality import momentum_quality_indicator_series`
- L12: `from .node_cache import IndicatorNodeCache`
- L13: `from .relative_strength import ( relative_strength_factor_series, relative_strength_factors, relative_strength_feature_series, relative_strength_features, )`
- L19: `from .registry import ( IndicatorProvider, IndicatorSpec, PandasTaAdapter, SupportStatus, provider_output_role, selected_indicator_output, )`

Top-level declarations:
- L28: `__all__` (module value)

### `src/domains/indicators/api.py` (166 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `import re`
- L6: `from collections.abc import Mapping`
- L7: `from dataclasses import asdict, dataclass, field`
- L8: `from datetime import date`
- L9: `from decimal import Decimal`
- L10: `from uuid import UUID, uuid4`
- L12: `from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value`
- L15: `from .momentum_quality import momentum_quality_indicator_series`
- L16: `from .relative_strength import ( relative_strength_factor_series, relative_strength_factors, relative_strength_feature_series, relative_strength_features, )`

Top-level declarations:
- L23: `__all__` (module value)
- L31: `_SEMVER` (module value)
- L35: `IndicatorRevision` (ClassDef)
- L75: `IndicatorConfiguration` (ClassDef)
- L98: `FeatureValue` (ClassDef)
- L110: `FeatureSnapshot` (ClassDef)
- L134: `compute_feature` (FunctionDef)

### `src/domains/indicators/dag.py` (652 lines)

Imports:
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
- L30: `from .registry import ( IndicatorSpec, PandasTaAdapter, provider_output_role, selected_indicator_output, )`
- L463: `import pandas_ta  # type: ignore[import-untyped]`

Top-level declarations:
- L19: `logger` (module value)
- L40: `PRIMITIVE_FIELDS` (module value)
- L45: `APPROVED_OPERATIONS` (module value)
- L59: `DagNode` (ClassDef)
- L124: `DagGraph` (ClassDef)
- L371: `DagExecutor` (ClassDef)
- L635: `_interpolate_piecewise` (FunctionDef)

### `src/domains/indicators/momentum_quality.py` (103 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import math`
- L6: `from collections.abc import Sequence`
- L7: `from typing import Any`
- L9: `import pandas as pd`

Top-level declarations:
- L11: `_value` (FunctionDef)
- L16: `momentum_quality_indicator_series` (FunctionDef)

### `src/domains/indicators/node_cache.py` (337 lines)

Imports:
- L11: `from __future__ import annotations`
- L13: `import json`
- L14: `import math`
- L15: `from datetime import UTC, date, datetime`
- L16: `from pathlib import Path`
- L18: `from src.platform_kernel import DomainValidationError`
- L19: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L22: `IndicatorNodeCache` (ClassDef)

### `src/domains/indicators/registry.py` (184 lines)

Imports:
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

Top-level declarations:
- L21: `IndicatorProvider` (ClassDef)
- L27: `SupportStatus` (ClassDef)
- L37: `IndicatorSpec` (ClassDef)
- L70: `_SPECS` (module value)
- L82: `_PROVIDER_OUTPUT_PREFIXES` (module value)
- L89: `selected_indicator_output` (FunctionDef)
- L102: `provider_output_role` (FunctionDef)
- L110: `PandasTaAdapter` (ClassDef)

### `src/domains/indicators/relative_strength.py` (220 lines)

Imports:
- L8: `from __future__ import annotations`
- L10: `import math`
- L11: `from collections.abc import Sequence`
- L12: `from typing import Any, cast`
- L14: `import pandas as pd`

Top-level declarations:
- L17: `_finite` (FunctionDef)
- L25: `_clip` (FunctionDef)
- L29: `relative_strength_feature_series` (FunctionDef)
- L150: `relative_strength_features` (FunctionDef)
- L160: `relative_strength_factors` (FunctionDef)
- L208: `relative_strength_factor_series` (FunctionDef)

### `src/domains/market_data/__init__.py` (27 lines)

Imports:
- L3: `from .api import ( NSE_INDEX_SYMBOLS, AdjustmentBasis, MarketDataSnapshot, NormalizedBar, publish_raw_snapshot, publish_snapshot, )`
- L11: `from .live_quotes import LiveQuotes`
- L12: `from .providers import KiteHistoricalBarsProvider, KiteInstrumentProvider, KiteQuoteProvider`
- L13: `from .repository import MarketRepository`

Top-level declarations:
- L15: `__all__` (module value)

### `src/domains/market_data/api.py` (137 lines)

Imports:
- L3: `from collections.abc import Iterable, Mapping`
- L4: `from dataclasses import asdict, dataclass`
- L5: `from datetime import date`
- L6: `from decimal import Decimal`
- L7: `from enum import Enum`
- L8: `from uuid import UUID, uuid4`
- L10: `from src.platform_kernel import ( ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus, )`

Top-level declarations:
- L17: `NSE_INDEX_SYMBOLS` (module value)
- L29: `AdjustmentBasis` (ClassDef)
- L36: `NormalizedBar` (ClassDef)
- L70: `MarketDataSnapshot` (ClassDef)
- L89: `publish_raw_snapshot` (FunctionDef)
- L111: `publish_snapshot` (FunctionDef)

### `src/domains/market_data/history_repository.py` (564 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `import math`
- L6: `import sqlite3`
- L7: `from collections.abc import Iterable`
- L8: `from contextlib import nullcontext`
- L9: `from datetime import UTC, date, datetime, timedelta`
- L10: `from decimal import Decimal`
- L11: `from uuid import uuid4`
- L13: `from src.platform_kernel import DomainValidationError`
- L14: `from src.platform_kernel.security import sanitize_sensitive`
- L15: `from src.platform_kernel.sqlite import sqlite_connection`
- L17: `from .api import NormalizedBar`

Top-level declarations:
- L20: `MarketHistoryRepositoryMixin` (ClassDef)

### `src/domains/market_data/index_quotes.py` (85 lines)

Imports:
- L3: `from collections.abc import Iterable`
- L5: `from src.platform_kernel import DomainValidationError`
- L6: `from src.platform_kernel.sqlite import sqlite_connection`

Top-level declarations:
- L9: `IndexQuoteRepositoryMixin` (ClassDef)

### `src/domains/market_data/live_quotes.py` (94 lines)

Imports:
- L3: `from datetime import UTC, datetime`
- L4: `from decimal import Decimal, InvalidOperation`
- L5: `from pathlib import Path`
- L6: `from zoneinfo import ZoneInfo`
- L8: `from src.platform_kernel import DomainValidationError`
- L9: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L12: `LiveQuotes` (ClassDef)

### `src/domains/market_data/providers.py` (120 lines)

Imports:
- L3: `from collections.abc import Callable, Mapping, Sequence`
- L4: `from datetime import date, datetime`
- L5: `from decimal import Decimal, InvalidOperation`
- L6: `from threading import Lock`
- L7: `from time import monotonic, sleep`
- L8: `from typing import Any`
- L10: `from src.platform_kernel import DomainValidationError`
- L12: `from .api import NormalizedBar`

Top-level declarations:
- L15: `_ProviderThrottle` (ClassDef)
- L32: `KiteHistoricalBarsProvider` (ClassDef)
- L84: `KiteInstrumentProvider` (ClassDef)
- L103: `KiteQuoteProvider` (ClassDef)

### `src/domains/market_data/repository.py` (82 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import math`
- L6: `from pathlib import Path`
- L8: `from src.platform_kernel import DomainValidationError`
- L10: `from .history_repository import MarketHistoryRepositoryMixin`
- L11: `from .index_quotes import IndexQuoteRepositoryMixin`
- L12: `from .schema import migrate_market_data`

Top-level declarations:
- L15: `MarketRepository` (ClassDef)

### `src/domains/market_data/schema.py` (64 lines)

Imports:
- L3: `from pathlib import Path`
- L5: `from src.platform_kernel.sqlite import migrate_sqlite`

Top-level declarations:
- L8: `migrate_market_data` (FunctionDef)

### `src/domains/operations/__init__.py` (13 lines)

Imports:
- L3: `from .jobs import Job, JobExecutionContext, JobStatus, JobStore`
- L4: `from .worker import BackgroundWorker, JobWorker`

Top-level declarations:
- L6: `__all__` (module value)

### `src/domains/operations/jobs.py` (658 lines)

Imports:
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
- L15: `from src.platform_kernel import DomainValidationError`
- L16: `from src.platform_kernel.security import sanitize_sensitive`
- L17: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L20: `JobStatus` (ClassDef)
- L29: `Job` (ClassDef)
- L45: `JobExecutionContext` (ClassDef)
- L128: `JobStore` (ClassDef)

### `src/domains/operations/worker.py` (142 lines)

Imports:
- L3: `import inspect`
- L4: `import logging`
- L5: `import threading`
- L6: `from collections.abc import Callable, Mapping`
- L7: `from datetime import UTC, datetime`
- L8: `from typing import Any`
- L10: `from .jobs import Job, JobExecutionContext, JobStore`
- L11: `from src.platform_kernel import DomainValidationError`
- L12: `from src.platform_kernel.security import sanitize_error`

Top-level declarations:
- L14: `JobHandler` (module value)
- L17: `JobWorker` (ClassDef)
- L67: `BackgroundWorker` (ClassDef)

### `src/domains/portfolio_accounting/__init__.py` (19 lines)

Imports:
- L3: `from .api import AccountingEvent, Fill, FillSide, Lot, OpeningPosition, PortfolioProjection, project`
- L4: `from .intraday_alerts import IntradayStopAlerts`
- L5: `from .ledger import Ledger`
- L6: `from .portfolio_performance import PortfolioPerformance`

Top-level declarations:
- L8: `__all__` (module value)

### `src/domains/portfolio_accounting/api.py` (147 lines)

Imports:
- L3: `from collections.abc import Iterable`
- L4: `from dataclasses import dataclass, field`
- L5: `from datetime import UTC, date, datetime`
- L6: `from decimal import Decimal`
- L7: `from enum import Enum`
- L8: `from typing import Union`
- L10: `from src.platform_kernel import DomainValidationError, Money, Quantity`

Top-level declarations:
- L13: `FillSide` (ClassDef)
- L19: `Fill` (ClassDef)
- L47: `OpeningPosition` (ClassDef)
- L61: `AccountingEvent` (module value)
- L64: `Lot` (ClassDef)
- L72: `PortfolioProjection` (ClassDef)
- L78: `project` (FunctionDef)

### `src/domains/portfolio_accounting/intraday_alerts.py` (103 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `from datetime import UTC, datetime`
- L8: `from decimal import Decimal, InvalidOperation`
- L9: `from pathlib import Path`
- L10: `from typing import Protocol`
- L11: `from uuid import NAMESPACE_URL, uuid5`
- L13: `from src.platform_kernel import DomainValidationError, QualityStatus`
- L14: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L17: `_Lot` (ClassDef)
- L21: `_Projection` (ClassDef)
- L25: `_Ledger` (ClassDef)
- L29: `_RiskProjectionReader` (ClassDef)
- L33: `_AlertPublisher` (ClassDef)
- L39: `IntradayStopAlerts` (ClassDef)

### `src/domains/portfolio_accounting/ledger.py` (563 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `import sqlite3`
- L6: `from collections.abc import Iterable`
- L7: `from contextlib import nullcontext`
- L8: `from datetime import UTC, date, datetime`
- L9: `from decimal import Decimal`
- L10: `from pathlib import Path`
- L12: `from src.domains.portfolio_accounting import ( AccountingEvent, Fill, FillSide, OpeningPosition, project, )`
- L19: `from src.platform_kernel import DomainValidationError, Money, Quantity`
- L20: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`
- L193: `import hashlib`
- L513: `from decimal import Decimal`
- L515: `from src.domains.portfolio_accounting.api import Quantity`

Top-level declarations:
- L23: `Ledger` (ClassDef)

### `src/domains/portfolio_accounting/portfolio_performance.py` (96 lines)

Imports:
- L3: `from datetime import date`
- L4: `from decimal import Decimal`
- L5: `from math import isfinite`
- L6: `from typing import Any, Protocol`

Top-level declarations:
- L9: `PortfolioLedger` (ClassDef)
- L16: `calculate_xirr` (FunctionDef)
- L34: `PortfolioPerformance` (ClassDef)

### `src/domains/portfolio_engine/__init__.py` (32 lines)

Imports:
- L3: `from .api import ( Candidate, Decision, DecisionType, ExecutionAssumptions, Holding, MarketBar, PortfolioPolicy, PortfolioState, evaluate, )`
- L14: `from .proposal_store import PortfolioProposalStore`
- L15: `from .risk_config import PortfolioRiskConfig, RiskGuardLimits`
- L16: `from .risk_reservations import RiskReservationRepository`

Top-level declarations:
- L18: `__all__` (module value)

### `src/domains/portfolio_engine/api.py` (617 lines)

Imports:
- L8: `from collections.abc import Mapping, Sequence`
- L9: `from dataclasses import dataclass, field, replace`
- L10: `from datetime import date`
- L11: `from decimal import ROUND_DOWN, Decimal`
- L12: `from enum import Enum`
- L14: `from src.platform_kernel import DomainValidationError, Money, Quantity`

Top-level declarations:
- L17: `DecisionType` (ClassDef)
- L29: `_amount` (FunctionDef)
- L35: `MarketBar` (ClassDef)
- L58: `Holding` (ClassDef)
- L73: `Candidate` (ClassDef)
- L96: `PortfolioPolicy` (ClassDef)
- L153: `ExecutionAssumptions` (ClassDef)
- L179: `PortfolioState` (ClassDef)
- L192: `Decision` (ClassDef)
- L201: `_sell_decision` (FunctionDef)
- L261: `_with_costs` (FunctionDef)
- L291: `_execution_price` (FunctionDef)
- L297: `_volume_cap` (FunctionDef)
- L307: `evaluate` (FunctionDef)

### `src/domains/portfolio_engine/proposal_store.py` (261 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import json`
- L6: `import sqlite3`
- L7: `from datetime import date`
- L8: `from pathlib import Path`
- L9: `from typing import Any`
- L11: `from src.platform_kernel import DomainValidationError`
- L12: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L15: `PortfolioProposalStore` (ClassDef)

### `src/domains/portfolio_engine/risk_config.py` (107 lines)

Imports:
- L3: `import json`
- L4: `from dataclasses import dataclass`
- L5: `from datetime import UTC, datetime`
- L6: `from math import isfinite`
- L8: `from src.platform_kernel import DomainValidationError`
- L9: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L13: `RiskGuardLimits` (ClassDef)
- L58: `PortfolioRiskConfig` (ClassDef)

### `src/domains/portfolio_engine/risk_reservations.py` (78 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import sqlite3`
- L6: `from pathlib import Path`
- L8: `from src.platform_kernel.sqlite import migrate_sqlite`

Top-level declarations:
- L11: `RiskReservationRepository` (ClassDef)
- L78: `__all__` (module value)

### `src/domains/reference_data/__init__.py` (47 lines)

Imports:
- L3: `from .api import ( CorporateAction, CorporateActionSnapshot, ExchangeCalendar, FundamentalSnapshot, Instrument, InstrumentAlias, LiquidityUniverseMember, LiquidityUniversePolicy, LiquidityUniverseSnapshot, UniverseExclusionReason, UniverseSnapshot, build_liquidity_universe, publish_alias_snapshot, publish_calendar_snapshot, publish_instrument_snapshot, resolve_alias, )`
- L21: `from .nse_provider import NIFTY_500_URL, NSE_BASE_URL, NSE_CA_URL, NseClient`
- L22: `from .repository import ReferenceDataRepository, TrackedInstrument`

Top-level declarations:
- L24: `__all__` (module value)

### `src/domains/reference_data/api.py` (492 lines)

Imports:
- L3: `from collections.abc import Iterable, Mapping`
- L4: `from dataclasses import asdict, dataclass`
- L5: `from datetime import date`
- L6: `from decimal import Decimal`
- L7: `from enum import Enum`
- L8: `from typing import Protocol`
- L9: `from uuid import UUID, uuid4`
- L11: `from src.platform_kernel import ( ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus, freeze_value, )`

Top-level declarations:
- L21: `Instrument` (ClassDef)
- L33: `InstrumentAlias` (ClassDef)
- L54: `UniverseSnapshot` (ClassDef)
- L82: `UniverseExclusionReason` (ClassDef)
- L93: `LiquidityBar` (ClassDef)
- L122: `LiquidityUniversePolicy` (ClassDef)
- L156: `LiquidityUniverseMember` (ClassDef)
- L187: `LiquidityUniverseSnapshot` (ClassDef)
- L236: `build_liquidity_universe` (FunctionDef)
- L325: `_is_flat_ohlc` (FunctionDef)
- L330: `_median` (FunctionDef)
- L339: `CorporateAction` (ClassDef)
- L351: `ExchangeCalendar` (ClassDef)
- L378: `CorporateActionSnapshot` (ClassDef)
- L398: `FundamentalSnapshot` (ClassDef)
- L422: `publish_alias_snapshot` (FunctionDef)
- L444: `publish_calendar_snapshot` (FunctionDef)
- L453: `resolve_alias` (FunctionDef)
- L472: `publish_instrument_snapshot` (FunctionDef)

### `src/domains/reference_data/nse_provider.py` (87 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import csv`
- L6: `import io`
- L7: `import json`
- L9: `import requests`
- L11: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L13: `NIFTY_500_URL` (module value)
- L14: `NSE_CA_URL` (module value)
- L15: `NSE_BASE_URL` (module value)
- L18: `NseClient` (ClassDef)

### `src/domains/reference_data/repository.py` (663 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `from collections.abc import Iterable`
- L6: `from contextlib import nullcontext`
- L7: `from dataclasses import dataclass`
- L8: `from datetime import UTC, date, datetime`
- L9: `from pathlib import Path`
- L11: `from src.platform_kernel import DomainValidationError`
- L12: `from src.platform_kernel.sqlite import sqlite_connection`
- L14: `from .schema import migrate_reference_data`

Top-level declarations:
- L18: `TrackedInstrument` (ClassDef)
- L28: `ReferenceDataRepository` (ClassDef)

### `src/domains/reference_data/schema.py` (84 lines)

Imports:
- L3: `from pathlib import Path`
- L5: `from src.platform_kernel.sqlite import migrate_sqlite`

Top-level declarations:
- L8: `migrate_reference_data` (FunctionDef)

### `src/domains/research/__init__.py` (19 lines)

Imports:
- L3: `from .api import ( ResearchPipelineRepository, ResearchRepository, correlation_clusters, detect_return_anomalies, rank_sector_factors, weekly_ranking_members, )`

Top-level declarations:
- L12: `__all__` (module value)

### `src/domains/research/api.py` (19 lines)

Imports:
- L3: `from .calculations import ( correlation_clusters, detect_return_anomalies, rank_sector_factors, weekly_ranking_members, )`
- L9: `from .pipeline_repository import ResearchPipelineRepository`
- L10: `from .repository import ResearchRepository`

Top-level declarations:
- L12: `__all__` (module value)

### `src/domains/research/calculations.py` (189 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from collections import defaultdict`
- L6: `from collections.abc import Mapping, Sequence`
- L7: `from statistics import mean, pstdev`
- L9: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L12: `rank_sector_factors` (FunctionDef)
- L59: `correlation_clusters` (FunctionDef)
- L116: `detect_return_anomalies` (FunctionDef)
- L158: `weekly_ranking_members` (FunctionDef)
- L184: `__all__` (module value)

### `src/domains/research/pipeline_repository.py` (120 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from pathlib import Path`
- L7: `from src.platform_kernel import DomainValidationError`
- L8: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L11: `ResearchPipelineRepository` (ClassDef)
- L120: `__all__` (module value)

### `src/domains/research/repository.py` (332 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from datetime import UTC, datetime`
- L6: `from pathlib import Path`
- L8: `from src.platform_kernel import DomainValidationError`
- L9: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L12: `ResearchRepository` (ClassDef)

### `src/domains/strategies/__init__.py` (47 lines)

Imports:
- L3: `from .api import ( PercentileSnapshot, PortfolioPolicyRevision, PositionalTrendBacktestPolicy, RankingMember, RankingSnapshot, ScoreSnapshot, StrategyDefinitions, StrategyDefinitionValidator, StrategyRevision, build_research_snapshots, feature_series, rank_feature_values, simulate_positional_trend_backtest, valid_bar, )`
- L19: `from .momentum_quality import momentum_quality_from_indicators`
- L20: `from .ranking_patterns import ( DirectSignalRanking, FactorPercentileRanking, RankingPattern, ranking_pattern_for, )`

Top-level declarations:
- L27: `__all__` (module value)

### `src/domains/strategies/api.py` (386 lines)

Imports:
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
- L15: `from .definitions import StrategyDefinitions, StrategyDefinitionValidator`
- L18: `from .momentum_quality import momentum_quality_from_indicators`
- L19: `from .positional_trend import feature_series, valid_bar`
- L20: `from .positional_trend_backtest import Policy as PositionalTrendBacktestPolicy`
- L21: `from .positional_trend_backtest import simulate as simulate_positional_trend_backtest`
- L22: `from .ranking_patterns import ranking_pattern_for`

Top-level declarations:
- L24: `__all__` (module value)
- L36: `RETAINED_STRATEGIES` (module value)
- L38: `_SEMVER` (module value)
- L41: `RevisionStatus` (ClassDef)
- L51: `PortfolioPolicyRevision` (ClassDef)
- L75: `StrategyRevision` (ClassDef)
- L125: `RankingMember` (ClassDef)
- L146: `PercentileSnapshot` (ClassDef)
- L177: `ScoreSnapshot` (ClassDef)
- L205: `RankingSnapshot` (ClassDef)
- L289: `build_research_snapshots` (FunctionDef)
- L376: `rank_feature_values` (FunctionDef)

### `src/domains/strategies/definitions.py` (434 lines)

Imports:
- L8: `from __future__ import annotations`
- L10: `import hashlib`
- L11: `import json`
- L12: `import math`
- L13: `import re`
- L14: `from datetime import UTC, datetime`
- L15: `from pathlib import Path`
- L16: `from typing import Any, Protocol`
- L17: `from uuid import NAMESPACE_URL, uuid5`
- L19: `import yaml`
- L21: `from src.platform_kernel import DomainValidationError`
- L22: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L24: `_STATUSES` (module value)
- L25: `_SEMVER` (module value)
- L28: `StrategyDefinitionValidator` (ClassDef)
- L44: `StrategyDefinitions` (ClassDef)

### `src/domains/strategies/momentum_quality.py` (79 lines)

Imports:
- None

Top-level declarations:
- L3: `_MOMENTUM_RSI_WEIGHT` (module value)
- L4: `_MOMENTUM_PPO_WEIGHT` (module value)
- L5: `_MOMENTUM_PPO_HISTOGRAM_WEIGHT` (module value)
- L6: `_MOMENTUM_PURE_WEIGHT` (module value)
- L9: `_goldilocks` (FunctionDef)
- L21: `_rsi_regime` (FunctionDef)
- L33: `_percent_b_score` (FunctionDef)
- L42: `momentum_quality_from_indicators` (FunctionDef)

### `src/domains/strategies/positional_trend.py` (166 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import math`
- L6: `from collections import deque`

Top-level declarations:
- L9: `valid_bar` (FunctionDef)
- L17: `_DEFAULT_RULES` (module value)
- L25: `_segment_features` (FunctionDef)
- L142: `feature_series` (FunctionDef)
- L165: `signal_series` (FunctionDef)

### `src/domains/strategies/positional_trend_backtest.py` (374 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import math`
- L6: `from collections import Counter, defaultdict`
- L7: `from copy import deepcopy`
- L8: `from dataclasses import asdict, dataclass`
- L9: `from datetime import date, datetime`
- L10: `from statistics import mean, median, stdev`
- L11: `from zoneinfo import ZoneInfo`
- L13: `from .positional_trend import feature_series, valid_bar`

Top-level declarations:
- L17: `Policy` (ClassDef)
- L51: `_equity_at_open` (FunctionDef)
- L65: `simulate` (FunctionDef)

### `src/domains/strategies/positional_trend_comparison.py` (77 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import math`
- L6: `from importlib import import_module`
- L8: `import pandas as pd`
- L10: `from src.domains.strategies.positional_trend import _segment_features, valid_bar`

Top-level declarations:
- L13: `pandas_ta_features` (FunctionDef)

### `src/domains/strategies/ranking_patterns.py` (190 lines)

Imports:
- L7: `from __future__ import annotations`
- L9: `import hashlib`
- L10: `import json`
- L11: `import logging`
- L12: `from abc import ABC, abstractmethod`
- L13: `from collections import defaultdict`

Top-level declarations:
- L15: `logger` (module value)
- L18: `RankingPattern` (ClassDef)
- L38: `FactorPercentileRanking` (ClassDef)
- L136: `DirectSignalRanking` (ClassDef)
- L184: `ranking_pattern_for` (FunctionDef)

### `src/gates/__init__.py` (1 lines)

Imports:
- None

Top-level declarations:
- None

### `src/gates/app.py` (220 lines)

Imports:
- L1: `import logging`
- L2: `import os`
- L3: `from pathlib import Path`
- L5: `from flask import Flask, jsonify`
- L6: `from waitress import serve  # type: ignore[import-untyped]`
- L8: `from src.domains.execution import KiteAuthService, load_kite_credentials`
- L9: `from src.domains.indicators import PandasTaAdapter`
- L10: `from src.gates.composition import ApplicationServices`
- L11: `from src.gates.http.actions import create_actions_blueprint`
- L12: `from src.gates.http.backtest import create_backtest_blueprint`
- L13: `from src.gates.http.broker import create_broker_blueprint`
- L14: `from src.gates.http.dashboard import create_dashboard_blueprint`
- L15: `from src.gates.http.indicators import create_indicators_blueprint`
- L16: `from src.gates.http.kite_accounts import create_kite_accounts_blueprint`
- L17: `from src.gates.http.kite_auth import create_kite_auth_blueprint`
- L18: `from src.gates.http.market import create_market_blueprint`
- L19: `from src.gates.http.operations import create_operations_blueprint`
- L20: `from src.gates.http.pipeline import create_pipeline_blueprint`
- L21: `from src.gates.http.portfolio import create_portfolio_blueprint`
- L22: `from src.gates.http.positional_trend import create_positional_trend_blueprint`
- L23: `from src.gates.http.reference import create_reference_blueprint`
- L24: `from src.gates.http.research import create_research_blueprint`
- L25: `from src.gates.http.strategies import create_strategies_blueprint`
- L26: `from src.gates.http.universe import create_universe_blueprint`
- L27: `from src.gates.http.wiki import create_wiki_blueprint`
- L28: `from src.gates.operations import sqlite_ready`
- L29: `from src.gates.runtime import RuntimeConfig`
- L30: `from src.gates.security import RedactingLogFilter`
- L31: `from src.gates.workflows.index_poller import BackgroundIndexPoller`
- L175: `import logging`

Top-level declarations:
- L34: `configure_logging` (FunctionDef)
- L46: `create_app` (FunctionDef)
- L173: `main` (FunctionDef)

### `src/gates/backtesting_adapter.py` (40 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from collections.abc import Mapping, Sequence`
- L6: `from typing import Any`
- L8: `from src.domains.backtesting import BacktestExecutionAssumptions, FillModelRevision`
- L9: `from src.domains.portfolio_engine import ExecutionAssumptions, evaluate`

Top-level declarations:
- L12: `BacktestPortfolioEngineAdapter` (ClassDef)

### `src/gates/cli.py` (95 lines)

Imports:
- L3: `import argparse`
- L4: `import json`
- L5: `from pathlib import Path`
- L7: `from src.domains.execution import load_kite_credentials`
- L8: `from src.domains.operations import JobStore`
- L9: `from src.gates.composition import ApplicationServices`
- L10: `from src.gates.operations import sqlite_backup, sqlite_ready, sqlite_restore`
- L11: `from src.gates.runtime import RuntimeConfig`
- L12: `from src.gates.workflows.index_poller import IndexQuotePoller`
- L13: `from src.gates.workflows.intraday_stream import IntradayStreamLease`
- L14: `from src.gates.workflows.research_pipeline import ResearchPipelineJobs`

Top-level declarations:
- L17: `main` (FunctionDef)

### `src/gates/composition.py` (251 lines)

Imports:
- L3: `import os`
- L4: `from dataclasses import dataclass`
- L5: `from pathlib import Path`
- L6: `from typing import Any`
- L8: `from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher`
- L9: `from src.domains.execution import ( BrokerOrderRepository, KiteAccounts, KiteCredentials, KiteExecutionGateway, KiteStreamingProvider, )`
- L16: `from src.domains.indicators import IndicatorNodeCache, PandasTaAdapter`
- L17: `from src.domains.market_data import LiveQuotes`
- L18: `from src.domains.operations import BackgroundWorker, JobStore, JobWorker`
- L19: `from src.domains.portfolio_accounting import IntradayStopAlerts, Ledger`
- L20: `from src.domains.portfolio_engine import PortfolioRiskConfig`
- L21: `from src.domains.strategies.api import RETAINED_STRATEGIES`
- L22: `from src.gates.repositories import MarketRepository`
- L23: `from src.gates.strategy_definitions import StrategyDefinitions`
- L24: `from src.gates.strategy_runtime import StrategyRuntime`
- L25: `from src.gates.workflows.backtesting import BacktestJobs`
- L26: `from src.gates.workflows.broker_orders import BrokerOrderWorkflow`
- L27: `from src.gates.workflows.corporate_actions import CorporateActions`
- L28: `from src.gates.workflows.index_poller import IndexQuotePoller`
- L29: `from src.gates.workflows.intraday_stream import IntradayStreamLease`
- L30: `from src.gates.workflows.liquidity_universe import publish_liquidity_universe`
- L31: `from src.gates.workflows.live_quote_stream import LiveQuoteStream`
- L32: `from src.gates.workflows.managed_risk import ManagedRiskGuard`
- L33: `from src.gates.workflows.market_jobs import KiteMarketJobs`
- L34: `from src.gates.workflows.market_refresh import MarketRefreshPlanner`
- L35: `from src.gates.workflows.pipeline_preparation import PipelinePreparation`
- L36: `from src.gates.workflows.portfolio_actions import ActionJobs`
- L37: `from src.gates.workflows.portfolio_sync import PortfolioSync`
- L38: `from src.gates.workflows.positional_trend import PositionalTrendJobs`
- L39: `from src.gates.workflows.research import ResearchJobs`
- L40: `from src.gates.workflows.research_pipeline import ResearchPipelineJobs`
- L41: `from src.gates.workflows.universe import UniverseJobs`
- L42: `from src.platform_kernel import ArtifactStore, SqliteArtifactStore`

Top-level declarations:
- L46: `ApplicationServices` (ClassDef)

### `src/gates/http/__init__.py` (1 lines)

Imports:
- None

Top-level declarations:
- None

### `src/gates/http/actions.py` (165 lines)

Imports:
- L3: `from datetime import date`
- L5: `from flask import Blueprint, jsonify, request`
- L7: `from src.gates.workflows.portfolio_actions import ActionJobs`
- L8: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L11: `create_actions_blueprint` (FunctionDef)

### `src/gates/http/backtest.py` (57 lines)

Imports:
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.gates.workflows.backtesting import BacktestJobs`
- L6: `from src.platform_kernel import ArtifactStore, DomainValidationError`

Top-level declarations:
- L9: `create_backtest_blueprint` (FunctionDef)

### `src/gates/http/broker.py` (82 lines)

Imports:
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.gates.workflows.broker_orders import BrokerOrderWorkflow`
- L6: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L9: `create_broker_blueprint` (FunctionDef)

### `src/gates/http/dashboard.py` (52 lines)

Imports:
- L7: `from datetime import datetime, timedelta`
- L8: `from zoneinfo import ZoneInfo`
- L10: `from flask import Blueprint, render_template`

Top-level declarations:
- L13: `create_dashboard_blueprint` (FunctionDef)

### `src/gates/http/indicators.py` (23 lines)

Imports:
- L3: `from flask import Blueprint, jsonify`
- L5: `from src.domains.indicators import PandasTaAdapter`
- L6: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L9: `create_indicators_blueprint` (FunctionDef)

### `src/gates/http/kite_accounts.py` (71 lines)

Imports:
- L2: `from flask import Blueprint, jsonify, request`
- L3: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L6: `create_kite_accounts_blueprint` (FunctionDef)

### `src/gates/http/kite_auth.py` (133 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import logging`
- L6: `import time`
- L7: `from html import escape`
- L9: `from flask import Blueprint, Response, jsonify, redirect, request, session, url_for`
- L10: `from flask.typing import ResponseReturnValue`
- L11: `from kiteconnect.exceptions import KiteException  # type: ignore[import-untyped]`
- L13: `from src.domains.execution import KiteAuthService`

Top-level declarations:
- L15: `_SESSION_STARTED_AT` (module value)
- L16: `_SESSION_TTL_SECONDS` (module value)
- L17: `_LOGGER` (module value)
- L20: `create_kite_auth_blueprint` (FunctionDef)

### `src/gates/http/market.py` (300 lines)

Imports:
- L3: `import json`
- L4: `from datetime import UTC, date, datetime, timedelta`
- L6: `from flask import Blueprint, Response, jsonify, request`
- L8: `from src.domains.artifacts import ArtifactCatalog`
- L9: `from src.domains.market_data import LiveQuotes`
- L10: `from src.domains.portfolio_accounting import IntradayStopAlerts`
- L11: `from src.gates.repositories import MarketRepository`
- L12: `from src.gates.workflows.index_poller import IndexQuotePoller`
- L13: `from src.gates.workflows.intraday_stream import IntradayStreamLease`
- L14: `from src.gates.workflows.market_refresh import MarketRefreshPlanner`
- L15: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L18: `create_market_blueprint` (FunctionDef)

### `src/gates/http/operations.py` (163 lines)

Imports:
- L7: `import json`
- L8: `import time`
- L9: `from collections.abc import Collection`
- L10: `from pathlib import Path`
- L12: `from flask import Blueprint, Response, jsonify, request, stream_with_context`
- L14: `from src.domains.operations import Job, JobStore`
- L15: `from src.domains.operations import BackgroundWorker, JobWorker`
- L16: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L19: `_job_response` (FunctionDef)
- L36: `create_operations_blueprint` (FunctionDef)

### `src/gates/http/pipeline.py` (44 lines)

Imports:
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.gates.workflows.research_pipeline import ResearchPipelineJobs`
- L6: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L9: `create_pipeline_blueprint` (FunctionDef)

### `src/gates/http/portfolio.py` (554 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import json`
- L6: `from datetime import date, datetime`
- L7: `from decimal import Decimal, InvalidOperation`
- L8: `from zoneinfo import ZoneInfo`
- L10: `from flask import Blueprint, Response, jsonify, request`
- L12: `from src.domains.portfolio_accounting import Fill, FillSide, Ledger, PortfolioPerformance`
- L13: `from src.domains.portfolio_engine import RiskGuardLimits`
- L14: `from src.gates.repositories import MarketRepository`
- L15: `from src.platform_kernel import DomainValidationError, Money, Quantity`
- L334: `from datetime import timedelta`
- L336: `from src.gates.workflows.trading_calendar import TradingCalendar`
- L391: `import hashlib`
- L392: `import json`

Top-level declarations:
- L18: `_money` (FunctionDef)
- L27: `create_portfolio_blueprint` (FunctionDef)

### `src/gates/http/positional_trend.py` (51 lines)

Imports:
- L3: `from datetime import date`
- L5: `from flask import Blueprint, jsonify, request`
- L7: `from src.domains.operations import JobStore`
- L8: `from src.gates.workflows.positional_trend import PositionalTrendJobs`
- L9: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L12: `create_positional_trend_blueprint` (FunctionDef)

### `src/gates/http/reference.py` (234 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `from datetime import UTC, date, datetime`
- L6: `from decimal import Decimal, InvalidOperation`
- L8: `from flask import Blueprint, jsonify, request`
- L10: `from src.gates.repositories import MarketRepository`
- L11: `from src.domains.artifacts import ArtifactPublisher`
- L12: `from src.platform_kernel import ArtifactStore, DomainValidationError`

Top-level declarations:
- L15: `create_reference_blueprint` (FunctionDef)

### `src/gates/http/research.py` (198 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `from datetime import date`
- L7: `from flask import Blueprint, jsonify, request`
- L9: `from src.domains.operations import JobStore`
- L10: `from src.gates.workflows.research import ResearchJobs`
- L11: `from src.platform_kernel import ArtifactStore, DomainValidationError`

Top-level declarations:
- L14: `create_research_blueprint` (FunctionDef)

### `src/gates/http/strategies.py` (44 lines)

Imports:
- L3: `from flask import Blueprint, jsonify, request`
- L5: `from src.gates.strategy_definitions import StrategyDefinitions`
- L6: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L9: `create_strategies_blueprint` (FunctionDef)

### `src/gates/http/universe.py` (61 lines)

Imports:
- L3: `from datetime import UTC, date, datetime`
- L5: `from flask import Blueprint, jsonify, request`
- L7: `from src.domains.operations import JobStore`
- L8: `from src.gates.repositories import MarketRepository`
- L9: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L12: `create_universe_blueprint` (FunctionDef)

### `src/gates/http/wiki.py` (43 lines)

Imports:
- L3: `from pathlib import Path`
- L5: `from flask import Blueprint, jsonify, render_template`

Top-level declarations:
- L8: `_WIKI_DIRECTORY` (module value)
- L9: `_PAGES` (module value)
- L20: `create_wiki_blueprint` (FunctionDef)

### `src/gates/indicator_implementations.py` (80 lines)

Imports:
- L3: `from collections.abc import Callable, Sequence`
- L4: `from typing import Any`
- L6: `from src.domains.indicators.api import ( momentum_quality_indicator_series, relative_strength_factor_series, relative_strength_factors, relative_strength_feature_series, relative_strength_features, )`
- L13: `from src.domains.strategies.api import ( feature_series as positional_trend_feature_series, )`
- L16: `from src.domains.strategies.api import ( momentum_quality_from_indicators, )`
- L19: `from src.gates.momentum_quality import ( momentum_quality_feature_series, momentum_quality_features, )`

Top-level declarations:
- L25: `positional_trend_features` (FunctionDef)
- L31: `positional_trend_series` (FunctionDef)
- L41: `InstrumentImplementation` (module value)
- L42: `BenchmarkImplementation` (module value)
- L45: `CrossSectionImplementation` (module value)
- L47: `INSTRUMENT_IMPLEMENTATIONS` (module value)
- L52: `INSTRUMENT_SERIES_IMPLEMENTATIONS` (module value)
- L57: `CROSS_SECTION_IMPLEMENTATIONS` (module value)
- L60: `CUSTOM_IMPLEMENTATIONS` (module value)
- L62: `__all__` (module value)

### `src/gates/momentum_quality.py` (22 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from collections.abc import Sequence`
- L6: `from typing import Any`
- L8: `from src.domains.indicators import momentum_quality_indicator_series`
- L9: `from src.domains.strategies import momentum_quality_from_indicators`

Top-level declarations:
- L12: `momentum_quality_feature_series` (FunctionDef)
- L19: `momentum_quality_features` (FunctionDef)

### `src/gates/operations.py` (60 lines)

Imports:
- L3: `import sqlite3`
- L4: `from contextlib import closing`
- L5: `from pathlib import Path`
- L7: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L10: `sqlite_backup` (FunctionDef)
- L31: `sqlite_restore` (FunctionDef)
- L41: `sqlite_ready` (FunctionDef)

### `src/gates/payloads.py` (169 lines)

Imports:
- L9: `from __future__ import annotations`
- L11: `from dataclasses import dataclass`
- L12: `from datetime import date`
- L13: `from typing import Any`
- L15: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L19: `RebuildRangePayload` (ClassDef)
- L62: `RebuildIndicatorsPayload` (ClassDef)
- L93: `FetchBarsPayload` (ClassDef)
- L116: `BacktestPayload` (ClassDef)
- L143: `RebuildMultiYearPayload` (ClassDef)

### `src/gates/release_gates.py` (94 lines)

Imports:
- L8: `from __future__ import annotations`
- L10: `import hashlib`
- L11: `from collections.abc import Iterable`
- L12: `from datetime import date`
- L13: `from pathlib import Path`
- L14: `from typing import Any`
- L16: `from src.gates.operations import sqlite_backup, sqlite_ready, sqlite_restore`
- L17: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L20: `next_tradable_session` (FunctionDef)
- L28: `compare_execution_events` (FunctionDef)
- L61: `restore_drill` (FunctionDef)
- L85: `dashboard_visual_contract` (FunctionDef)

### `src/gates/repositories.py` (342 lines)

Imports:
- L3: `import json`
- L4: `import math`
- L5: `from collections.abc import Iterable`
- L6: `from datetime import UTC, date, datetime`
- L7: `from decimal import Decimal`
- L8: `from pathlib import Path`
- L10: `from src.domains.market_data import MarketRepository as MarketDataRepository`
- L11: `from src.domains.market_data import NormalizedBar`
- L12: `from src.domains.reference_data import ReferenceDataRepository, TrackedInstrument`
- L13: `from src.platform_kernel import DomainValidationError`
- L14: `from src.platform_kernel.sqlite import sqlite_connection`

Top-level declarations:
- L17: `MarketRepository` (ClassDef)
- L342: `__all__` (module value)

### `src/gates/runtime.py` (31 lines)

Imports:
- L3: `import os`
- L4: `from pathlib import Path`

Top-level declarations:
- L7: `RuntimeConfig` (ClassDef)

### `src/gates/security.py` (20 lines)

Imports:
- L3: `import logging`
- L4: `import traceback`
- L6: `from src.platform_kernel.security import sanitize_text`

Top-level declarations:
- L9: `RedactingLogFilter` (ClassDef)

### `src/gates/session_coverage.py` (91 lines)

Imports:
- L3: `from bisect import bisect_right`
- L4: `from collections import defaultdict`
- L5: `from datetime import date, datetime, timedelta`
- L6: `from zoneinfo import ZoneInfo`
- L8: `from src.platform_kernel.sqlite import sqlite_connection`
- L9: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L12: `CompletedSessionCoverage` (ClassDef)

### `src/gates/strategy_definitions.py` (15 lines)

Imports:
- L3: `from pathlib import Path`
- L5: `from src.domains.indicators import PandasTaAdapter`
- L6: `from src.domains.strategies.api import StrategyDefinitions as _StrategyDefinitions`
- L7: `from src.gates.strategy_validation import StrategyIndicatorValidator`

Top-level declarations:
- L10: `StrategyDefinitions` (ClassDef)
- L15: `__all__` (module value)

### `src/gates/strategy_runtime.py` (189 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from collections.abc import Mapping, Sequence`
- L6: `from pathlib import Path`
- L7: `from typing import Any, cast`
- L9: `import pandas as pd`
- L11: `from src.domains.indicators import DagExecutor, DagGraph, PandasTaAdapter`
- L12: `from src.gates.indicator_implementations import ( CROSS_SECTION_IMPLEMENTATIONS, INSTRUMENT_IMPLEMENTATIONS, INSTRUMENT_SERIES_IMPLEMENTATIONS, BenchmarkImplementation, InstrumentImplementation, )`
- L19: `from src.gates.strategy_definitions import StrategyDefinitions`
- L20: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L22: `__all__` (module value)
- L25: `StrategyRuntime` (ClassDef)

### `src/gates/strategy_validation.py` (35 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from src.domains.indicators import APPROVED_OPERATIONS, DagGraph, PandasTaAdapter`
- L6: `from src.gates.indicator_implementations import CUSTOM_IMPLEMENTATIONS`
- L7: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L10: `StrategyIndicatorValidator` (ClassDef)

### `src/gates/workflows/__init__.py` (1 lines)

Imports:
- None

Top-level declarations:
- None

### `src/gates/workflows/backtesting.py` (1048 lines)

Imports:
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
- L17: `from src.domains.artifacts import ArtifactPublisher`
- L18: `from src.domains.backtesting import ( BacktestRunManifest, BacktestRunStore, BacktestStep, FillModelRevision, run, )`
- L25: `from src.domains.portfolio_engine import Candidate, MarketBar, PortfolioPolicy, PortfolioState`
- L26: `from src.gates.backtesting_adapter import BacktestPortfolioEngineAdapter`
- L27: `from src.gates.repositories import MarketRepository`
- L28: `from src.gates.workflows.research import ResearchJobs`
- L29: `from src.platform_kernel import DomainValidationError, Money, QualityStatus`
- L582: `from src.domains.strategies import ( PositionalTrendBacktestPolicy as PositionalTrendPolicy, )`
- L585: `from src.domains.strategies import ( simulate_positional_trend_backtest as simulate, )`
- L588: `from src.gates.workflows.positional_trend_backtest_inputs import ( benchmark_price_return, load_snapshot_universe, )`

Top-level declarations:
- L9: `logger` (module value)
- L32: `_decimal` (FunctionDef)
- L44: `BacktestJobs` (ClassDef)

### `src/gates/workflows/broker_orders.py` (436 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `from datetime import UTC, date, datetime`
- L6: `from decimal import Decimal`
- L7: `from pathlib import Path`
- L8: `from uuid import NAMESPACE_URL, uuid4, uuid5`
- L10: `from src.domains.execution import ( BrokerExecutionGateway, BrokerOrderRepository, KiteExecutionGateway, )`
- L15: `from src.domains.portfolio_accounting import Fill, FillSide, Ledger`
- L16: `from src.domains.portfolio_engine import PortfolioProposalStore`
- L17: `from src.gates.repositories import MarketRepository`
- L18: `from src.platform_kernel import DomainValidationError, Money, Quantity`

Top-level declarations:
- L21: `BrokerOrderWorkflow` (ClassDef)

### `src/gates/workflows/corporate_actions.py` (502 lines)

Imports:
- L7: `import json`
- L8: `import logging`
- L9: `import re`
- L10: `from datetime import date, datetime, timedelta`
- L11: `from decimal import Decimal, InvalidOperation`
- L12: `from pathlib import Path`
- L13: `from typing import Any`
- L14: `from uuid import NAMESPACE_URL, uuid5`
- L15: `from zoneinfo import ZoneInfo`
- L17: `from src.domains.indicators import IndicatorNodeCache`
- L18: `from src.domains.market_data import NormalizedBar`
- L19: `from src.gates.repositories import MarketRepository`
- L20: `from src.platform_kernel import DomainValidationError`
- L21: `from src.platform_kernel.sqlite import sqlite_connection`
- L197: `from src.domains.reference_data import NseClient`

Top-level declarations:
- L23: `logger` (module value)
- L27: `ANOMALY_THRESHOLD_PERCENT` (module value)
- L30: `ADJUSTABLE_TYPES` (module value)
- L32: `MONITORED_TYPES` (module value)
- L33: `ALL_CA_TYPES` (module value)
- L36: `_NSE_DATE_PATTERNS` (module value)
- L42: `_MONTH_MAP` (module value)
- L48: `CorporateActions` (ClassDef)

### `src/gates/workflows/index_poller.py` (169 lines)

Imports:
- L3: `import logging`
- L4: `import threading`
- L5: `from datetime import UTC, datetime, timedelta`
- L6: `from pathlib import Path`
- L7: `from zoneinfo import ZoneInfo`
- L9: `from src.domains.operations import JobStore`
- L10: `from src.platform_kernel import DomainValidationError`
- L11: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L13: `logger` (module value)
- L16: `IndexQuotePoller` (ClassDef)
- L126: `market_is_open` (FunctionDef)
- L136: `BackgroundIndexPoller` (ClassDef)

### `src/gates/workflows/intraday_stream.py` (114 lines)

Imports:
- L3: `from datetime import UTC, datetime`
- L4: `from pathlib import Path`
- L6: `from src.platform_kernel import DomainValidationError`
- L7: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L10: `IntradayStreamLease` (ClassDef)

### `src/gates/workflows/liquidity_universe.py` (155 lines)

Imports:
- L3: `from datetime import date`
- L4: `from decimal import Decimal, InvalidOperation`
- L5: `from typing import Any`
- L6: `from uuid import UUID`
- L8: `from src.domains.artifacts import ArtifactPublisher`
- L9: `from src.domains.market_data import NormalizedBar`
- L10: `from src.domains.reference_data import Instrument, LiquidityUniversePolicy, build_liquidity_universe`
- L11: `from src.platform_kernel import ArtifactManifest, DomainValidationError`

Top-level declarations:
- L14: `publish_liquidity_universe` (FunctionDef)
- L33: `_policy` (FunctionDef)
- L60: `_instrument` (FunctionDef)
- L70: `_bar` (FunctionDef)
- L99: `_mapping` (FunctionDef)
- L105: `_list` (FunctionDef)
- L111: `_only_keys` (FunctionDef)
- L116: `_string` (FunctionDef)
- L122: `_integer` (FunctionDef)
- L128: `_decimal` (FunctionDef)
- L140: `_date` (FunctionDef)
- L149: `_uuid` (FunctionDef)

### `src/gates/workflows/live_quote_stream.py` (97 lines)

Imports:
- L3: `from threading import RLock`
- L5: `from kiteconnect import KiteTicker`
- L7: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L10: `LiveQuoteStream` (ClassDef)

### `src/gates/workflows/managed_risk.py` (247 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import json`
- L6: `from datetime import datetime`
- L7: `from decimal import Decimal`
- L8: `from zoneinfo import ZoneInfo`
- L10: `from src.domains.portfolio_engine import RiskReservationRepository`
- L11: `from src.platform_kernel import DomainValidationError`
- L12: `from src.platform_kernel.sqlite import sqlite_connection`

Top-level declarations:
- L15: `decimal` (FunctionDef)
- L25: `trading_date` (FunctionDef)
- L29: `ManagedRiskGuard` (ClassDef)

### `src/gates/workflows/market_ingestion.py` (85 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `from collections.abc import Iterable`
- L6: `from dataclasses import asdict`
- L7: `from datetime import UTC, datetime`
- L9: `from src.domains.artifacts import ArtifactPublisher`
- L10: `from src.domains.market_data import NormalizedBar`
- L11: `from src.platform_kernel import ArtifactManifest, DomainValidationError, QualityStatus`
- L12: `from src.platform_kernel.security import sanitize_sensitive`
- L35: `from uuid import uuid4`

Top-level declarations:
- L15: `ingest_market_bars` (FunctionDef)

### `src/gates/workflows/market_jobs.py` (616 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import logging`
- L8: `from datetime import UTC, date, datetime, timedelta`
- L9: `from decimal import Decimal, InvalidOperation`
- L10: `from pathlib import Path`
- L11: `from typing import Any`
- L12: `from uuid import NAMESPACE_URL, uuid4, uuid5`
- L14: `from kiteconnect import KiteConnect  # type: ignore[import-untyped]`
- L15: `from kiteconnect.exceptions import KiteException`
- L16: `from requests.exceptions import RequestException`
- L18: `from src.domains.artifacts import ArtifactPublisher`
- L19: `from src.domains.market_data import NSE_INDEX_SYMBOLS, KiteHistoricalBarsProvider, NormalizedBar`
- L20: `from src.domains.portfolio_accounting import IntradayStopAlerts`
- L21: `from src.gates.repositories import MarketRepository, TrackedInstrument`
- L22: `from src.gates.workflows.market_ingestion import ingest_market_bars`
- L23: `from src.platform_kernel import DomainValidationError`
- L24: `from src.platform_kernel.security import sanitize_error`
- L458: `import concurrent.futures`

Top-level declarations:
- L7: `logger` (module value)
- L26: `PHASE2_BENCHMARK_SYMBOLS` (module value)
- L29: `KiteMarketJobs` (ClassDef)

### `src/gates/workflows/market_refresh.py` (286 lines)

Imports:
- L3: `import hashlib`
- L4: `import json`
- L5: `from collections.abc import Callable`
- L6: `from datetime import date, datetime`
- L7: `from pathlib import Path`
- L8: `from typing import Any`
- L9: `from zoneinfo import ZoneInfo`
- L11: `from src.domains.artifacts import ArtifactPublisher`
- L12: `from src.domains.market_data import NSE_INDEX_SYMBOLS`
- L13: `from src.domains.operations import JobStore`
- L14: `from src.gates.repositories import MarketRepository`
- L15: `from src.platform_kernel import DomainValidationError`
- L52: `from src.gates.session_coverage import CompletedSessionCoverage`

Top-level declarations:
- L18: `MarketRefreshPlanner` (ClassDef)

### `src/gates/workflows/pipeline_preparation.py` (102 lines)

Imports:
- L3: `from datetime import date, timedelta`
- L5: `from src.domains.market_data import NSE_INDEX_SYMBOLS`
- L6: `from src.gates.session_coverage import CompletedSessionCoverage`
- L7: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L10: `PipelinePreparation` (ClassDef)

### `src/gates/workflows/portfolio_actions.py` (1673 lines)

Imports:
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
- L17: `from src.domains.artifacts import ArtifactPublisher`
- L18: `from src.domains.portfolio_accounting import Fill, FillSide, Ledger`
- L19: `from src.domains.portfolio_engine import ( Candidate, DecisionType, Holding, MarketBar, PortfolioPolicy, PortfolioProposalStore, PortfolioState, evaluate, )`
- L29: `from src.domains.strategies import feature_series, valid_bar`
- L30: `from src.gates.repositories import MarketRepository`
- L31: `from src.gates.workflows.research import ResearchJobs`
- L32: `from src.platform_kernel import DomainValidationError, Money, QualityStatus, Quantity`
- L33: `from src.platform_kernel.sqlite import sqlite_connection`

Top-level declarations:
- L9: `logger` (module value)
- L35: `_BUY_TYPES` (module value)
- L36: `_EXECUTION_POLICY_VERSION` (module value)
- L37: `_DEFAULT_PYRAMID_FRACTION` (module value)
- L38: `_EXECUTION_POLICY` (module value)
- L51: `ActionJobs` (ClassDef)

### `src/gates/workflows/portfolio_sync.py` (266 lines)

Imports:
- L8: `from __future__ import annotations`
- L10: `import hashlib`
- L11: `import json`
- L12: `from datetime import UTC, date, datetime`
- L13: `from decimal import Decimal`
- L14: `from pathlib import Path`
- L15: `from typing import Any, Protocol`
- L17: `from src.domains.portfolio_accounting import Fill, FillSide, OpeningPosition`
- L18: `from src.domains.strategies.api import RETAINED_STRATEGIES`
- L19: `from src.platform_kernel import DomainValidationError, Money, Quantity`
- L20: `from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection`

Top-level declarations:
- L23: `BrokerClient` (ClassDef)
- L27: `AccountGateway` (ClassDef)
- L34: `LedgerGateway` (ClassDef)
- L48: `InstrumentReader` (ClassDef)
- L52: `PortfolioSync` (ClassDef)

### `src/gates/workflows/positional_trend.py` (188 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `from datetime import date, datetime`
- L8: `from pathlib import Path`
- L9: `from uuid import NAMESPACE_URL, uuid5`
- L10: `from zoneinfo import ZoneInfo`
- L12: `from src.domains.strategies.api import feature_series, ranking_pattern_for`
- L13: `from src.platform_kernel import DomainValidationError, QualityStatus`
- L14: `from src.platform_kernel.sqlite import sqlite_connection`

Top-level declarations:
- L16: `_FEATURE_SOURCE` (module value)
- L21: `PositionalTrendJobs` (ClassDef)

### `src/gates/workflows/positional_trend_backtest_inputs.py` (318 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import csv`
- L6: `import hashlib`
- L7: `import json`
- L8: `import sqlite3`
- L9: `from collections import Counter`
- L10: `from datetime import date, datetime`
- L11: `from pathlib import Path`
- L12: `from zoneinfo import ZoneInfo`

Top-level declarations:
- L15: `load_data` (FunctionDef)
- L96: `load_market_cap_universe` (FunctionDef)
- L165: `load_snapshot_universe` (FunctionDef)
- L287: `benchmark_price_return` (FunctionDef)

### `src/gates/workflows/research.py` (1164 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import inspect`
- L7: `import json`
- L8: `import logging`
- L11: `from collections import defaultdict`
- L12: `from datetime import UTC, date, datetime, timedelta`
- L13: `from importlib.metadata import version`
- L14: `from pathlib import Path`
- L15: `from time import perf_counter`
- L16: `from typing import Any, cast`
- L17: `from uuid import NAMESPACE_URL, uuid4, uuid5`
- L19: `from src.domains.artifacts import ArtifactPublisher`
- L20: `from src.domains.indicators import ( DagExecutor, DagGraph, PandasTaAdapter, momentum_quality_indicator_series, relative_strength_feature_series, )`
- L27: `from src.domains.operations import JobExecutionContext`
- L28: `from src.domains.research import ( ResearchRepository, correlation_clusters, detect_return_anomalies, rank_sector_factors, weekly_ranking_members, )`
- L35: `from src.domains.strategies import momentum_quality_from_indicators, ranking_pattern_for`
- L36: `from src.gates.repositories import MarketRepository`
- L37: `from src.gates.strategy_definitions import StrategyDefinitions`
- L38: `from src.gates.strategy_runtime import StrategyRuntime`
- L39: `from src.platform_kernel import DomainValidationError, QualityStatus`
- L76: `from src.gates.payloads import RebuildIndicatorsPayload`
- L107: `import pandas as pd`
- L113: `import hashlib`
- L249: `from src.gates.payloads import RebuildRangePayload`

Top-level declarations:
- L10: `logger` (module value)
- L42: `ResearchJobs` (ClassDef)

### `src/gates/workflows/research_pipeline.py` (410 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import hashlib`
- L6: `import json`
- L7: `import logging`
- L10: `from datetime import UTC, date, datetime, timedelta`
- L11: `from pathlib import Path`
- L12: `from typing import Any`
- L13: `from uuid import NAMESPACE_URL, uuid5`
- L14: `from zoneinfo import ZoneInfo`
- L16: `from src.domains.indicators import PandasTaAdapter`
- L17: `from src.domains.operations import JobStatus, JobStore`
- L18: `from src.domains.research import ResearchPipelineRepository`
- L19: `from src.gates.strategy_definitions import StrategyDefinitions`
- L20: `from src.gates.strategy_runtime import StrategyRuntime`
- L21: `from src.platform_kernel import DomainValidationError`
- L22: `from src.platform_kernel.sqlite import sqlite_connection`
- L96: `from src.gates.workflows.trading_calendar import TradingCalendar`

Top-level declarations:
- L9: `logger` (module value)
- L24: `_CALCULATION_REVISION` (module value)
- L27: `ResearchPipelineJobs` (ClassDef)

### `src/gates/workflows/trading_calendar.py` (88 lines)

Imports:
- L8: `from __future__ import annotations`
- L10: `from datetime import date`
- L11: `from pathlib import Path`
- L13: `from src.platform_kernel.sqlite import sqlite_connection`

Top-level declarations:
- L16: `TradingCalendar` (ClassDef)

### `src/gates/workflows/universe.py` (210 lines)

Imports:
- L3: `from __future__ import annotations`
- L5: `import csv`
- L6: `import hashlib`
- L7: `import io`
- L8: `from datetime import date, datetime, timedelta`
- L9: `from typing import Any`
- L10: `from uuid import NAMESPACE_URL, uuid5`
- L11: `from zoneinfo import ZoneInfo`
- L13: `from src.domains.reference_data import NseClient`
- L14: `from src.gates.repositories import MarketRepository`
- L15: `from src.gates.workflows.trading_calendar import TradingCalendar`
- L16: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L19: `UniverseJobs` (ClassDef)

### `src/platform_kernel/__init__.py` (41 lines)

Imports:
- L7: `from .api import ( ArtifactManifest, ArtifactStore, Broker, CommandMetadata, DomainValidationError, FrozenDict, HistoricalBarsProvider, InstrumentProvider, LiveQuoteProvider, Money, QualityStatus, Quantity, SqliteArtifactStore, VersionedReference, freeze_value, )`

Top-level declarations:
- L25: `__all__` (module value)

### `src/platform_kernel/api.py` (31 lines)

Imports:
- L3: `from .artifacts import ArtifactManifest, ArtifactStore, QualityStatus, SqliteArtifactStore`
- L4: `from .contracts import ( CommandMetadata, FrozenDict, Money, Quantity, VersionedReference, freeze_value, )`
- L12: `from .errors import DomainValidationError`
- L13: `from .ports import Broker, HistoricalBarsProvider, InstrumentProvider, LiveQuoteProvider`

Top-level declarations:
- L15: `__all__` (module value)

### `src/platform_kernel/artifacts.py` (338 lines)

Imports:
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

Top-level declarations:
- L20: `QualityStatus` (ClassDef)
- L30: `ArtifactManifest` (ClassDef)
- L40: `ArtifactStore` (ClassDef)
- L190: `SqliteArtifactStore` (ClassDef)

### `src/platform_kernel/contracts.py` (101 lines)

Imports:
- L7: `from dataclasses import dataclass`
- L8: `from decimal import Decimal, InvalidOperation`
- L9: `from typing import Any, NewType`
- L10: `from uuid import UUID`
- L12: `from .errors import DomainValidationError`

Top-level declarations:
- L14: `AggregateVersion` (module value)
- L17: `FrozenDict` (ClassDef)
- L38: `freeze_value` (FunctionDef)
- L49: `_finite_decimal` (FunctionDef)
- L60: `Money` (ClassDef)
- L74: `Quantity` (ClassDef)
- L85: `VersionedReference` (ClassDef)
- L93: `CommandMetadata` (ClassDef)

### `src/platform_kernel/errors.py` (5 lines)

Imports:
- None

Top-level declarations:
- L4: `DomainValidationError` (ClassDef)

### `src/platform_kernel/ports.py` (23 lines)

Imports:
- L3: `from collections.abc import Sequence`
- L4: `from datetime import date`
- L5: `from typing import Protocol`

Top-level declarations:
- L8: `HistoricalBarsProvider` (ClassDef)
- L14: `InstrumentProvider` (ClassDef)
- L18: `LiveQuoteProvider` (ClassDef)
- L22: `Broker` (ClassDef)

### `src/platform_kernel/security.py` (57 lines)

Imports:
- L3: `import re`
- L4: `from collections.abc import Mapping, Sequence`
- L5: `from typing import Any`
- L7: `from .errors import DomainValidationError`

Top-level declarations:
- L9: `_SENSITIVE_KEYS` (module value)
- L21: `_SENSITIVE_SUFFIXES` (module value)
- L22: `_REDACTED` (module value)
- L23: `_SECRET_ASSIGNMENT` (module value)
- L31: `_is_sensitive_key` (FunctionDef)
- L36: `sanitize_sensitive` (FunctionDef)
- L48: `sanitize_error` (FunctionDef)
- L55: `sanitize_text` (FunctionDef)

### `src/platform_kernel/sqlite.py` (71 lines)

Imports:
- L3: `import sqlite3`
- L4: `from collections.abc import Callable, Iterator, Mapping, Sequence`
- L5: `from contextlib import contextmanager`
- L6: `from pathlib import Path`
- L8: `from src.platform_kernel import DomainValidationError`

Top-level declarations:
- L10: `Migration` (module value)
- L14: `sqlite_connection` (FunctionDef)
- L45: `migrate_sqlite` (FunctionDef)
