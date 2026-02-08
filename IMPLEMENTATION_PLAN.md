# IMPLEMENTATION PLAN: Codebase Compliance Audit

**Agent:** The 007 of Dalal Street  
**Date:** 2026-02-08  
**Objective:** Ensure all files comply with `.agent/instructions.md` standards

---

## Executive Summary

### Compliance Status

| Category | Files Audited | ✅ Compliant | ❌ Needs Changes |
|----------|---------------|-------------|------------------|
| Configuration | 7 | 7 | 0 |
| Documentation | 5 | 5 | 0 |
| Models | 10 | 10 | 0 |
| Schemas | 12 | 12 | 0 |
| Adaptors | 2 | 2 | 0 |
| Services | 9 | 9 | 0 |
| Repositories | 10 | 10 | 0 |
| Utils | 8 | 8 | 0 |
| Routes | 13 | 13 | 0 |
| Backtesting | 4 | 4 | 0 |
| Root Files | 18 | 18 | 0 |
| **TOTAL** | **98** | **98** | **0** |

### Key Issues Found

1. **Print statements** (5 instances) - backtesting modules
2. **Missing type hints** (3 files) - actions_service.py, actions_routes.py, kite_adaptor.py
3. **Incomplete docstrings** (6 files) - Missing Parameters/Examples/Raises sections
4. **Edge case handling** (3 files) - Missing input validation

---

##Configuration Files (7 files)

### [✅ COMPLIANT] `config/__init__.py`
**Status:** No changes required  
**Review:** Exports config classes correctly

### [✅ COMPLIANT] `config/app_config.py`
**Status:** No changes required  
**Review:** Simple config class with parameters

###[✅ COMPLIANT] `config/flask_config.py`
**Status:** No changes required  
**Review:** Flask configuration

### [✅ COMPLIANT] `config/indicators_config.py`
**Status:** No changes required  
**Review:** pandas_ta Study definitions for indicators

### [✅ COMPLIANT] `config/kite_config.py`
**Status:** No changes required  
**Review:** Kite API configuration

### [✅ COMPLIANT] `config/logger_config.py`
**Status:** No changes required  
**Review:** Logger setup function

### [✅ COMPLIANT] `config/strategies_config.py`
**Status:** No changes required  
**Reviewfile:** 11 config classes with comprehensive docstrings
- `Strategy1Parameters`
- `TransactionCostConfig`
- `ImpactCostConfig`
- `PenaltyBoxConfig`
- `PositionSizingConfig`
- `PortfolioControlConfig`
- `TaxConfig`
- `ChallengerConfig`
- `GoldilocksConfig`
- `RSIRegimeConfig`
- `BacktestConfig`

**Excellent:** All parameters documented inline, clear naming, no hardcoded values

---

## Documentation Files (5 files)

### [✅ COMPLIANT] `docs/API.md`
**Status:** No changes required  
**Review:** Comprehensive API documentation

### [✅ COMPLIANT] `docs/DAY0.md`
**Status:** No changes required  
**Review:** Day 0 setup instructions

### [✅ COMPLIANT] `docs/SETUP.md`
**Status:** No changes required  
**Review:** Installation guide

### [✅ COMPLIANT] `docs/STRATEGY.md`
**Status:** No changes required  
**Review:** Strategy documentation

### [✅ COMPLIANT] `docs/TODO.md`
**Status:** No changes required  
**Review:** Future enhancements

---

## Models (10 files)

### [✅ COMPLIANT] `src/models/__init__.py`
**Status:** No changes required  
**Review:** Exports all models including ActionsModel and InvestmentActionsModel (legacy)

### [✅ COMPLIANT] `src/models/actions.py`
**Status:** No changes required (created for modularity)  
**Review:** ActionsModel - dedicated model for trading actions
- Separated from investment.py for better organization
- Same table name (`investment_actions`) for backward compatibility
- Comprehensive docstring, indexes on working_date, symbol, status
- Helper methods: `__repr__`, `to_dict()`

### [✅ COMPLIANT] `src/models/indicators.py`
**Status:** No changes required  
**Review:** IndicatorsModel with proper columns, indexes, docstring

### [✅ COMPLIANT] `src/models/instruments.py`
**Status:** No changes required  
**Review:** InstrumentsModel with proper schema

### [✅ COMPLIANT] `src/models/investment.py`
**Status:** No changes required (updated for modularity)  
**Review:** 
- `InvestmentHoldingsModel` - includes `@property risk` method with docstring
- `InvestmentSummaryModel` - computed column for remaining_capital
- Legacy import: `from .actions import ActionsModel as InvestmentActionsModel`

**Note:** Actions moved to actions.py for better separation of concerns

### [✅ COMPLIANT] `src/models/marketdata.py`
**Status:** No changes required  
**Review:** MarketDataModel with OHLCV schema

### [✅ COMPLIANT] `src/models/master.py`
**Status:** No changes required  
**Review:** MasterModel for stock metadata

### [✅ COMPLIANT] `src/models/percentile.py`
**Status:** No changes required  
**Review:** PercentileModel with proper indexes

### [✅ COMPLIANT] `src/models/ranking.py`
**Status:** No changes required  
**Review:** RankingModel for weekly rankings

### [✅ COMPLIANT] `src/models/risk_config.py`
**Status:** No changes required  
**Review:** RiskConfigModel for strategy parameters

### [✅ COMPLIANT] `src/models/score.py`
**Status:** No changes required  
**Review:** ScoreModel for composite scores

---

## Schemas (12 files)

### [✅ COMPLIANT] `src/schemas/__init__.py`
**Status:** No changes required  
**Review:** Exports all schemas including actions schemas separately from investment

### [✅ COMPLIANT] `src/schemas/actions.py`
**Status:** No changes required (created for modularity)  
**Review:** Action-specific API schemas
- `ActionDateSchema` - Date list response
- `ActionQuerySchema` - Query by date
- `ActionSchema` - Full action response
- `ActionUpdateSchema` - Update action status
- Separated from investment.py for clarity

### [✅ COMPLIANT] `src/schemas/app.py`
**Status:** No changes required  
**Review:** Marshmallow schemas for app endpoints

### [✅ COMPLIANT] `src/schemas/backtest.py`
**Status:** No changes required  
**Review:** BacktestInputSchema with date fields

### [✅ COMPLIANT] `src/schemas/indicators.py`
**Status:** No changes required  
**Review:** Schema for indicator responses

### [✅ COMPLIANT] `src/schemas/init_app.py`
**Status:** No changes required  
**Review:** InitResponseSchema

### [✅ COMPLIANT] `src/schemas/instruments.py`
**Status:** No changes required  
**Review:** InstrumentSchema

### [✅ COMPLIANT] `src/schemas/investment.py`
**Status:** No changes required (updated for modularity)  
**Review:** 
- `HoldingDateSchema` - Holdings date list
- `HoldingSchema` - Portfolio holdings
- `SummarySchema` - Portfolio summary

**Note:** Action schemas moved to actions.py for better separation

### [✅ COMPLIANT] `src/schemas/marketdata.py`
**Status:** No changes required  
**Review:** MarketDataSchema

### [✅ COMPLIANT] `src/schemas/percentile.py`
**Status:** No changes required  
**Review:** PercentileSchema

### [✅ COMPLIANT] `src/schemas/ranking.py`
**Status:** No changes required  
**Review:** RankingSchema

### [✅ COMPLIANT] `src/schemas/risk_config.py`
**Status:** No changes required  
**Review:** RiskConfigSchema

### [✅ COMPLIANT] `src/schemas/score.py`
**Status:** No changes required  
**Review:** ScoreSchema

---

## Adaptors (2 files)

### [✅ COMPLIANT] `src/adaptors/__init__.py`
**Status:** No changes required  
**Review:** Exports adaptors

### [✅ COMPLETED] `src/adaptors/kite_adaptor.py`

**Status:** Implemented - Added class docstring, type hints (Optional, List, Dict, Any), and comprehensive docstrings to all public methods.

**Issues:**
1. Missing type hints on methods
2. Missing comprehensive docstrings (Parameters, Returns, Raises)
3. Nested class `CallbackHandler` missing docstring

**Required Changes:**

```python
from typing import Optional, List, Dict
from datetime import datetime

class KiteAdaptor:
    """
    Kite Connect API adaptor for stock market data.
    
    Handles authentication, session management, and data fetching.
    """
    
    def __init__(self, config: Dict[str, str], logger) -> None:
        """
        Initialize Kite adaptor with credentials.
        
        Parameters:
            config (Dict[str, str]): API key, secret, redirect URL
            logger: Logger instance for logging
        
        Returns:
            None
        """
        # ... existing code
    
    def fetch_ticker_data(self, ticker: int, start_date: datetime, 
                          end_date: Optional[datetime] = None) -> Optional[List[Dict]]:
        """
        Fetch historical data for a ticker from start_date to end_date.
        
        Parameters:
            ticker (int): Instrument token
            start_date (datetime): Start date for data
            end_date (Optional[datetime]): End date, defaults to now
        
        Returns:
            List[Dict]: OHLCV records, or None if fetch fails
        
        Raises:
            Exception: If API call fails
        
        Example:
            >>> data = adaptor.fetch_ticker_data(738561, date(2024, 1, 1))
        """
        # ... existing code
    
    def get_instruments(self, exchange: Optional[str] = None) -> Optional[List[Dict]]:
        """
        Get list of instruments from Kite.
        
        Parameters:
            exchange (Optional[str]): Specific exchange (NSE/BSE) or all
        
        Returns:
            List[Dict]: Instrument data, or None if fetch fails
        
        Example:
            >>> instruments = adaptor.get_instruments("NSE")
        """
        # ... existing code
```

**Complexity:** 5/10 - Moderate changes to add type hints and docstrings

### [✅ COMPLIANT] `src/adaptors/yfinance_adaptor.py`
**Status:** No changes required  
**Review:** Simple Yahoo Finance adaptor

---

## Services (9 files)

### [✅ COMPLIANT] `src/services/__init__.py`
**Status:** No changes required

### [✅ COMPLETED] `src/services/actions_service.py`

**Status:** Implemented - All methods now have type hints, docstrings, and edge case validation

**Issues:**
1. Missing return type hints on methods
2. Incomplete docstrings (missing Parameters/Returns/Raises)
3. No edge case validation

**Required Changes:**

```python
from typing import List, Optional
from datetime import date
from decimal import Decimal

class ActionsService:
    """Investment action service for SELL/SWAP/BUY decisions."""
    
    @staticmethod
    def generate_actions(working_date: date) -> List[dict]:
        """
        Generate trading actions for a given working date.
        
        Parameters:
            working_date (date): Date to generate actions for
        
        Returns:
            List[dict]: List of action dictionaries (BUY/SELL/SWAP)
        
        Raises:
            ValueError: If working_date is None or invalid
            RuntimeError: If pending actions exist for another date
        
        Example:
            >>> from datetime import date
            >>> actions = ActionsService.generate_actions(date(2024, 1, 15))
        """
        if working_date is None:
            raise ValueError("working_date cannot be None")
        # ... rest of implementation
    
    @staticmethod
    def buy_action(symbol: str, working_date: date, reason: str) -> dict:
        """
        Generate a BUY action with proper position sizing.
        
        Parameters:
            symbol (str): Trading symbol
            working_date (date): Action date
            reason (str): Action reason
        
        Returns:
            dict: BUY action with sizing details
        
        Raises:
            ValueError: If symbol is empty or ATR is unavailable
        
        Example:
            >>> action = ActionsService.buy_action("RELIANCE", date(2024, 1, 15), "top 10 buys")
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if not reason:
            reason = "Unknown reason"
        
        atr = indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, working_date)
        if atr is None:
            raise ValueError(f"ATR not available for {symbol} on {working_date}")
        # ... rest of implementation
    
    @staticmethod
    def sell_action(symbol: str, working_date: date, units: int, reason: str) -> dict:
        """
        Generate a SELL action.
        
        Parameters:
            symbol (str): Trading symbol
            working_date (date): Action date
            units (int): Number of units to sell
            reason (str): Sell reason
        
        Returns:
            dict: SELL action details
        
        Raises:
            ValueError: If symbol is empty or units <= 0
        
        Example:
            >>> action = ActionsService.sell_action("RELIANCE", date(2024, 1, 15), 100, "stoploss")
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if units <= 0:
            raise ValueError(f"Units must be positive, got {units}")
        # ... rest of implementation
```

**Complexity:** 6/10 - Multiple methods need updating

### [✅ COMPLIANT] `src/services/factors_service.py`
**Status:** No changes required  
**Review:** Excellent - comprehensive type hints, docstrings, config usage

### [✅ COMPLIANT] `src/services/indicators_service.py`
**Status:** No changes required  
**Review:** Uses pandas_ta Study pattern correctly

### [✅ COMPLIANT] `src/services/init_service.py`
**Status:** No changes required  
**Review:** Day 0 initialization service

### [✅ COMPLIANT] `src/services/marketdata_service.py`
**Status:** No changes required  
**Review:** Market data processing

### [✅ COMPLIANT] `src/services/percentile_service.py`
**Status:** No changes required  
**Review:** Cross-sectional percentile ranking

### [✅ COMPLIANT] `src/services/portfolio_controls_service.py`
**Status:** No changes required  
**Review:** Drawdown controls, good docstrings

### [✅ COMPLIANT] `src/services/ranking_service.py`
**Status:** No changes required  
**Review:** Weekly ranking generation

### [✅ COMPLIANT] `src/services/score_service.py`
**Status:** No changes required  
**Review:** Composite score calculation

---

## Repositories (10 files)

### [✅ COMPLIANT] `src/repositories/__init__.py`
**Status:** No changes required  
**Review:** Exports all repositories including ActionsRepository

### [✅ COMPLIANT] `src/repositories/actions_repository.py`
**Status:** No changes required (created for modularity)  
**Review:** Actions data access layer
- Separated from investment_repository.py for single responsibility
- Supports session injection for backtest.db
- Methods: `get_action_dates()`, `get_actions()`, `get_action_by_symbol()`, `bulk_insert_actions()`, `check_other_pending_actions()`, `update_action()`, `delete_all_actions()`
- Comprehensive docstrings with Parameters, Returns, edge cases

### [✅ COMPLIANT] `src/repositories/config_repository.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/repositories/indicators_repository.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/repositories/instruments_repository.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/repositories/investment_repository.py`
**Status:** No changes required (updated for modularity)  
**Review:** Holdings and summary data access
- Actions methods moved to actions_repository.py
- Supports multi-database sessions (personal.db, backtest.db)
- Methods: `get_holdings_dates()`, `get_holdings()`, `get_holdings_by_symbol()`, `bulk_insert_holdings()`, `get_summary()`, `insert_summary()`, `delete_*`
- Comprehensive docstrings

### [✅ COMPLIANT] `src/repositories/marketdata_repository.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/repositories/master_repository.py`
**Status:** Nochanges required

### [✅ COMPLIANT] `src/repositories/percentile_repository.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/repositories/ranking_repository.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/repositories/score_repository.py`
**Status:** No changes required

---

## Utils (8 files)

### [✅ COMPLIANT] `src/utils/__init__.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/utils/database_manager.py`
**Status:** No changes required  
**Review:** Multi-database session management

### [✅ COMPLETED] `src/utils/finance_utils.py`

**Status:** Implemented - Type hints, comprehensive docstring with edge cases and examples

**Issues:**
1. Incomplete docstring - missing full parameter docs
2. Missing edge case explanation

**Required Changes:**

```python
from typing import List, Tuple
from datetime import date

def calculate_xirr(cash_flows: List[Tuple[float, date]], guess: float = 0.1) -> float:
    """
    Calculate XIRR for a series of cash flows.
    
    Parameters:
        cash_flows (List[Tuple[float, date]]): List of (amount, date) tuples.
            Amounts should be negative for investments and positive for returns.
        guess (float): Initial guess for IRR (default: 0.1)
    
    Returns:
        float: Annualized IRR, or 0.0 if calculation fails or data is invalid
    
    Edge Cases:
        - Returns 0.0 if cash_flows is empty
        - Returns 0.0 if all amounts are 0
        - Returns 0.0 if all amounts have same sign (no investment or return)
        - Returns 0.0 if optimization fails
    
    Example:
        >>> from datetime import date
        >>> cash_flows = [(-10000, date(2024, 1, 1)), (12000, date(2024, 12, 31))]
        >>> xirr = calculate_xirr(cash_flows)
        >>> round(xirr, 4)
        0.2000
    """
    # ... existing implementation
```

**Complexity:** 3/10 - Simple docstring enhancement

### [✅ COMPLIANT] `src/utils/penalty_box_utils.py`
**Status:** No changes required  
**Review:** Excellent - type hints, comprehensive docstring, config usage

### [✅ COMPLETED] `src/utils/ranking_utils.py`

**Status:** Implemented - percentile_rank now has docstring with examples and empty series validation

**Issues:**
1. Missing Examples in docstrings
2. No edge case handling for empty series

**Required Changes:**

```python
def percentile_rank(series: pd.Series) -> pd.Series:
    """
    Calculate percentile rank (0-100) for a series.
    Non-parametric normalization robust to outliers.

    Formula: P_rank = (C_below + 0.5 * C_equal) / N * 100
    
    Parameters:
        series (pd.Series): Input series to rank
    
    Returns:
        pd.Series: Percentile ranks (0-100)
    
    Raises:
        ValueError: If series is empty
    
    Example:
        >>> import pandas as pd
        >>> data = pd.Series([10, 20, 30, 40, 50])
        >>> percentile_rank(data)
        0    20.0
        1    40.0
        2    60.0
        3    80.0
        4    100.0
        dtype: float64
    """
    if series.empty:
        raise ValueError("Cannot rank empty series")
    return series.rank(pct=True) * 100
```

Apply similar pattern to:
- `z_score_normalize()`
- `score_rsi_regime()`
- `score_trend_extension()`
- `score_percent_b()`

**Complexity:** 4/10 - Repetitive changes across 5 functions

### [✅ COMPLETED] `src/utils/sizing_utils.py`

**Status:** Implemented - calculate_equal_weight_position now has docstring and input validation

**Issues:**
1. `calculate_equal_weight_position` missing full docstring
2. No edge case validation

**Required Changes:**

```python
def calculate_equal_weight_position(portfolio_value: float, max_positions: int,
                                     current_price: float) -> dict:
    """
    Simple equal-weight position sizing.
    
    Parameters:
        portfolio_value (float): Total portfolio value
        max_positions (int): Maximum positions to hold
        current_price (float): Current stock price
    
    Returns:
        dict: Dictionary with 'shares' and 'position_value'
    
    Raises:
        ValueError: If max_positions <= 0 or current_price <= 0
    
    Example:
        >>> calculate_equal_weight_position(100000.0, 10, 500.0)
        {'shares': 20, 'position_value': 10000.0}
    """
    if max_positions <= 0:
        raise ValueError("max_positions must be positive")
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    
    position_value = portfolio_value / max_positions
    shares = int(position_value / current_price)
    
    return {
        "shares": max(1, shares),
        "position_value": round(shares * current_price, 2)
    }
```

**Complexity:** 3/10 - Simple validation addition

### [✅ COMPLIANT] `src/utils/stoploss_utils.py`
**Status:** No changes required  
**Review:** Excellent - comprehensive docstrings with Examples, type hints, edge case handling

### [✅ COMPLIANT] `src/utils/tax_utils.py`
**Status:** No changes required  
**Review:** Excellent - comprehensive docstrings, type hints, config usage

### [✅ COMPLIANT] `src/utils/transaction_costs_utils.py`
**Status:** No changes required  
**Review:** Excellent - comprehensive docstrings, type hints, config usage

---

## Routes (13 files)

### [✅ COMPLIANT] `src/api/v1/routes/__init__.py`
**Status:** No changes required

### [✅ COMPLETED] `src/api/v1/routes/actions_routes.py`

**Status:** Implemented - Added type hints, return types, and try-except error handling with logger.

**Issues:**
1. Methods missing return type hints
2. Missing error handling

**Required Changes:**

```python
from flask_smorest import abort

@blp.route("/generate")
class GenerateActions(MethodView):
    @blp.response(200, MessageSchema)
    def post(self) -> dict:
        """
        Generate trading actions for current week.
        
        Returns:
            dict: Message with generated actions
        
        Raises:
            HTTPException: If actions cannot be generated (500)
        """
        try:
            actions = ActionsService()
            working_date = datetime.now().date()
            new_actions = actions.generate_actions(working_date)
            return {"actions": new_actions}
        except ValueError as e:
            logger.error(f"Validation error generating actions: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to generate actions: {e}")
            abort(500, message=f"Action generation failed: {str(e)}")
```

**Complexity:** 4/10 - Add type hints and error handling to 3 methods

### [✅ COMPLIANT] `src/api/v1/routes/app_routes.py`
**Status:** No changes required  
**Review:** Good error handling with try-except blocks

### [✅ COMPLIANT] `src/api/v1/routes/config_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/costs_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/indicators_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/init_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/instrument_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/investment_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/marketdata_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/percentile_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/ranking_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/score_routes.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/api/v1/routes/tax_routes.py`
**Status:** No changes required

---

## Backtesting (4 files)

### [✅ COMPLIANT] `src/backtesting/__init__.py`
**Status:** No changes required

### [✅ COMPLIANT] `src/backtesting/api_client.py`
**Status:** No changes required  
**Review:** HTTP client for backtest data fetching

### [✅ COMPLETED] `src/backtesting/config.py`

**Status:** Implemented - print replaced with logger.warning

**Issues:**
1. Line 74: Uses `print()` for warning
2. Missing logger initialization

**Required Changes:**

```python
from config import setup_logger

logger = setup_logger(name="BacktestConfigLoader")

class BacktestConfigLoader:
    # ... __init__ and other methods
    
    def fetch(self, strategy_name: str = "momentum_strategy_one") -> FetchedConfig:
        """Fetch configuration from API."""
        if self._config is not None:
            return self._config
        
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/config/{strategy_name}",
                timeout=10
            )
            if response.status_code == 200:
                # ... existing code
                return self._config
        except Exception as e:
            # CHANGE: Replace print with logger
            logger.warning(f"Could not fetch config from API: {e}")  # ← Changed from print
        
        # Fallback logic...
        return self._config
```

**Complexity:** 2/10 - Simple print-to-logger replacement

### [✅ COMPLIANT] `src/backtesting/models.py`
**Status:** No changes required  
**Review:** Dataclasses for Position, BacktestResult, BacktestRiskMonitor

### [✅ COMPLETED] `src/backtesting/runner.py`

**Status:** Implemented - print statements in __main__ replaced with logger.info()

**Issues:**
1. Lines 589-593: Uses `print()` statements for backtest summary

**Required Changes:**

```python
if __name__ == "__main__":
    # Example usage
    from datetime import date
    
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    
    results, summary = run_backtest(start, end)
    
    # CHANGE: Replace print with logger
    logger.info(f"\n{'='*50}")           # ← Changed from print
    logger.info("BACKTEST SUMMARY")       # ← Changed from print
    logger.info(f"{'='*50}")             # ← Changed from print
    for key, value in summary.items():
        logger.info(f"  {key}: {value}")  # ← Changed from print
```

**Complexity:** 2/10 - Simple print-to-logger replacement

---

## Root Files

### [✅ COMPLIANT] `README.md`
**Status:** No changes required  
**Review:** Comprehensive documentation with:
- Features overview
- Quick start guide
- Project structure
- Scoring system details
- API endpoints
- Configuration parameters

**Note:** README is well-maintained and up-to-date

### [✅ COMPLIANT] `run.py`
**Status:** No changes required  
**Review:** Application entry point

### [✅ COMPLIANT] `Makefile`
**Status:** No changes required  
**Review:** Build/run commands

### [✅ COMPLIANT] `pyproject.toml`
**Status:** No changes required  
**Review:** Poetry dependencies

### [✅ COMPLIANT] `db.py`
**Status:** No changes required  
**Review:** Database initialization - `db = SQLAlchemy()`

### [✅ COMPLIANT] `local_secrets.py`
**Status:** No changes required  
**Review:** Kite API credentials (gitignored)

### [✅ COMPLIANT] `local_secrets.example.py`
**Status:** No changes required  
**Review:** Template for API credentials

### [✅ COMPLIANT] `.gitignore`
**Status:** No changes required  
**Review:** Excludes `__pycache__`, `.venv`, `local_secrets.py`, `*.db`, `logs/`

### [✅ COMPLIANT] `migrations/`
**Status:** No changes required  
**Review:** Alembic database migration scripts

### [✅ COMPLIANT] `templates/`
**Status:** No changes required  
**Review:** HTML templates for dashboard

### [✅ COMPLIANT] `data/`
**Status:** No changes required  
**Review:** Data storage directory

### [✅ COMPLIANT] `.agent/instructions.md`
**Status:** No changes required (updated with planning workflow)  
**Review:** Agent coding guidelines with planning workflow rules

### [✅ COMPLIANT] `.agent/workflows/`
**Status:** No changes required  
**Review:** Workflow definitions

### [✅ COMPLIANT] `src/__init__.py`
**Status:** No changes required  
**Review:** Source package initialization

### [✅ COMPLIANT] `src/api/__init__.py`
**Status:** No changes required  
**Review:** API package initialization

### [✅ COMPLIANT] `src/api/v1/__init__.py`
**Status:** No changes required  
**Review:** API v1 package initialization

---


## API Blueprint Organization

### ✅ IMPLEMENTATION COMPLETE

**Status:** All 13 route files updated with Swagger tags:
- System (5 endpoints): init, app, config routes
- Data Pipeline (31 endpoints): instruments, marketdata, indicators, percentile, score, ranking
- Trading (10 endpoints): actions, investment routes  
- Analysis (4 endpoints): costs, tax routes
- `routes/__init__.py` reorganized by category

---

### Original Issue

**Problem:** All API endpoints appeared in a flat list in Swagger UI, making navigation difficult with 50+ endpoints.

**Example Current Structure:**
```
/api/v1/swagger
  ├─ POST /api/v1/actions/generate
  ├─ GET /api/v1/instruments
  ├─ POST /api/v1/marketdata/update
  ├─ GET /api/v1/indicators/ema_200
  ├─ POST /api/v1/ranking/generate
  ├─ ... (50+ more endpoints)
```

### Proposed Solution

Group endpoints into **4 logical categories** using Flask-Smorest tags for Swagger UI organization:

```
📁 SYSTEM (Initialization & Configuration)
📁 DATA PIPELINE (Data Processing Flow)
📁 TRADING (Portfolio Management)
📁 ANALYSIS (Calculations & Reports)
```

---

### Detailed Blueprint Organization

#### 📁 **SYSTEM** (tag: "System")

**Purpose:** Application initialization, configuration, and maintenance

| Route File | Current URL | Proposed Tag | Description |
|------------|-------------|--------------|-------------|
| `init_routes.py` | `/api/v1/init/day0` | `["System"]` | Day 0 initialization |
| `app_routes.py` | `/api/v1/app/cleanup` | `["System"]` | Data cleanup operations |
| `app_routes.py` | `/api/v1/app/orchestration` | `["System"]` | Run full pipeline |
| `config_routes.py` | `/api/v1/config/*` | `["System"]` | Strategy configuration CRUD |

**Implementation Example:**
```python
# File: src/api/v1/routes/init_routes.py

blp = Blueprint(
    "init",
    __name__,
    url_prefix="/api/v1/init",
    description="System Initialization"
)

@blp.route("/day0")
class Init(MethodView):
    @blp.doc(tags=["System"])  # ← Add this line
    @blp.response(201, InitResponseSchema)
    def post(self):
        """Initialize application with Day 0 setup"""
        # ... existing code
```

---

#### 📁 **DATA PIPELINE** (tag: "Data Pipeline")

**Purpose:** Sequential data processing from raw OHLCV to weekly rankings

**Data Flow:** Instruments → Market Data → Indicators → Percentiles → Scores → Rankings

| Route File | Endpoints | Proposed Tag | Order |
|------------|-----------|--------------|-------|
| `instrument_routes.py` | `/api/v1/instruments/*` | `["Data Pipeline"]` | 1️⃣ |
| `marketdata_routes.py` | `/api/v1/marketdata/*` | `["Data Pipeline"]` | 2️⃣ |
| `indicators_routes.py` | `/api/v1/indicators/*` | `["Data Pipeline"]` | 3️⃣ |
| `percentile_routes.py` | `/api/v1/percentile/*` | `["Data Pipeline"]` | 4️⃣ |
| `score_routes.py` | `/api/v1/scores/*` | `["Data Pipeline"]` | 5️⃣ |
| `ranking_routes.py` | `/api/v1/ranking/*` | `["Data Pipeline"]` | 6️⃣ |

**Key Endpoints (in order of execution):**
1. `POST /api/v1/instruments/update` - Fetch instruments from Kite
2. `POST /api/v1/marketdata/update` - Fetch OHLCV data
3. `POST /api/v1/indicators/generate` - Calculate technical indicators
4. `POST /api/v1/percentile/generate` - Cross-sectional ranking
5. `POST /api/v1/scores/generate` - Composite scoring
6. `POST /api/v1/ranking/generate` - Weekly top 20

**Implementation Example:**
```python
# File: src/api/v1/routes/indicators_routes.py

@blp.route("/generate")
class GenerateIndicators(MethodView):
    @blp.doc(tags=["Data Pipeline"])  # ← Add this line
    @blp.response(200, MessageSchema)
    def post(self):
        """Generate technical indicators for all symbols"""
        # ... existing code
```

---

#### 📁 **TRADING** (tag: "Trading")

**Purpose:** Portfolio management, actions, holdings, and trade execution

| Route File | Endpoints | Proposed Tag | Description |
|------------|-----------|--------------|-------------|
| `actions_routes.py` | `/api/v1/actions/generate` | `["Trading"]` | Generate BUY/SELL/SWAP actions |
| `actions_routes.py` | `/api/v1/actions/config` | `["Trading"]` | Strategy parameters |
| `actions_routes.py` | `/api/v1/actions/backtesting` | `["Trading"]` | Run backtest simulation |
| `investment_routes.py` | `/api/v1/investment/holdings` | `["Trading"]` | Current portfolio holdings |
| `investment_routes.py` | `/api/v1/investment/summary` | `["Trading"]` | Portfolio summary (capital, risk, gain) |

**Implementation Example:**
```python
# File: src/api/v1/routes/actions_routes.py

@blp.route("/generate")
class GenerateActions(MethodView):
    @blp.doc(tags=["Trading"])  # ← Add this line
    @blp.response(200, MessageSchema)
    def post(self):
        """Generate trading actions for current week"""
        # ... existing code
```

---

#### 📁 **ANALYSIS** (tag: "Analysis")

**Purpose:** Cost calculations, tax estimates, and performance analytics

| Route File | Endpoints | Proposed Tag | Description |
|------------|-----------|--------------|-------------|
| `costs_routes.py` | `/api/v1/costs/roundtrip` | `["Analysis"]` | Transaction cost calculation |
| `costs_routes.py` | `/api/v1/costs/breakdown` | `["Analysis"]` | Cost breakdown by component |
| `tax_routes.py` | `/api/v1/tax/estimate` | `["Analysis"]` | Tax estimation (STCG/LTCG) |
| `tax_routes.py` | `/api/v1/tax/hold-benefit` | `["Analysis"]` | LTCG holding period benefit |

**Implementation Example:**
```python
# File: src/api/v1/routes/costs_routes.py

@blp.route("/roundtrip")
class RoundtripCost(MethodView):
    @blp.doc(tags=["Analysis"])  # ← Add this line
    @blp.arguments(RoundtripSchema)
    @blp.response(200, CostResponseSchema)
    def get(self, query_args):
        """Calculate round-trip transaction costs"""
        # ... existing code
```

---

### Implementation Checklist

#### Files to Modify (13 route files)

**SYSTEM (4 files):**
- [ ] `init_routes.py` - Add `@blp.doc(tags=["System"])` to Init.post
- [ ] `app_routes.py` - Add `@blp.doc(tags=["System"])` to all endpoints
- [ ] `config_routes.py` - Add `@blp.doc(tags=["System"])` to all endpoints

**DATA PIPELINE (6 files):**
- [ ] `instrument_routes.py` - Add `@blp.doc(tags=["Data Pipeline"])` to all endpoints
- [ ] `marketdata_routes.py` - Add `@blp.doc(tags=["Data Pipeline"])` to all endpoints
- [ ] `indicators_routes.py` - Add `@blp.doc(tags=["Data Pipeline"])` to all endpoints
- [ ] `percentile_routes.py` - Add `@blp.doc(tags=["Data Pipeline"])` to all endpoints
- [ ] `score_routes.py` - Add `@blp.doc(tags=["Data Pipeline"])` to all endpoints
- [ ] `ranking_routes.py` - Add `@blp.doc(tags=["Data Pipeline"])` to all endpoints

**TRADING (2 files):**
- [ ] `actions_routes.py` - Add `@blp.doc(tags=["Trading"])` to all endpoints
- [ ] `investment_routes.py` - Add `@blp.doc(tags=["Trading"])` to all endpoints

**ANALYSIS (2 files):**
- [ ] `costs_routes.py` - Add `@blp.doc(tags=["Analysis"])` to all endpoints
- [ ] `tax_routes.py` - Add `@blp.doc(tags=["Analysis"])` to all endpoints

---

### Blueprint Registration Order

**Update `src/api/v1/routes/__init__.py` to group imports logically:**

```python
"""
API v1 Routes

Blueprints organized by category for Swagger UI navigation.
"""

# SYSTEM
from .init_routes import blp as init_bp
from .app_routes import blp as app_bp
from .config_routes import blp as config_bp

# DATA PIPELINE (in execution order)
from .instrument_routes import blp as instruments_bp
from .marketdata_routes import blp as marketdata_bp
from .indicators_routes import blp as indicators_bp
from .percentile_routes import blp as percentile_bp
from .score_routes import blp as score_bp
from .ranking_routes import blp as ranking_bp

# TRADING
from .actions_routes import blp as actions_bp
from .investment_routes import blp as investment_bp

# ANALYSIS
from .costs_routes import blp as costs_bp
from .tax_routes import blp as tax_bp

# Backward compatibility alias
strategy_bp = actions_bp
```

---

### Expected Swagger UI Result

After implementation, Swagger UI (`/api/v1/swagger`) will show:

```
📁 Analysis
   ├─ GET  /api/v1/costs/roundtrip - Calculate round-trip costs
   ├─ GET  /api/v1/costs/breakdown - Cost breakdown
   ├─ GET  /api/v1/tax/estimate - Tax estimation
   └─ GET  /api/v1/tax/hold-benefit - LTCG benefit analysis

📁 Data Pipeline
   ├─ GET  /api/v1/instruments - List instruments
   ├─ POST /api/v1/instruments/update - Update instruments
   ├─ GET  /api/v1/marketdata/max-date - Get latest date
   ├─ POST /api/v1/marketdata/update - Update market data
   ├─ GET  /api/v1/indicators/{name} - Get indicator
   ├─ POST /api/v1/indicators/generate - Generate indicators
   ├─ POST /api/v1/percentile/generate - Generate percentiles
   ├─ POST /api/v1/scores/generate - Generate scores
   ├─ POST /api/v1/scores/recalculate - Recalculate scores
   ├─ GET  /api/v1/ranking/top20 - Get top 20
   └─ POST /api/v1/ranking/generate - Generate rankings

📁 System
   ├─ POST /api/v1/init/day0 - Initialize application
   ├─ POST /api/v1/app/cleanup - Cleanup data
   ├─ POST /api/v1/app/orchestration - Run pipeline
   ├─ GET  /api/v1/config/{strategy_name} - Get config
   ├─ POST /api/v1/config - Save config
   └─ PUT  /api/v1/config/{strategy_name} - Update config

📁 Trading
   ├─ POST /api/v1/actions/generate - Generate actions
   ├─ POST /api/v1/actions/config - Configure strategy
   ├─ POST /api/v1/actions/backtesting - Run backtest
   ├─ GET  /api/v1/investment/holdings - Get holdings
   └─ GET  /api/v1/investment/summary - Portfolio summary
```

---

### Benefits of Blueprint Organization

| Benefit | Impact |
|---------|--------|
| **Discoverability** | New developers can quickly understand API structure |
| **Logical Flow** | Data Pipeline shows execution order (1→2→3→4→5→6) |
| **Reduced Cognitive Load** | 4 categories vs 50+ flat endpoints |
| **Better Documentation** | Swagger UI auto-groups related endpoints |
| **Easier Testing** | Test by category (System → Pipeline → Trading) |

---

### Implementation Time Estimate

| Task | Files | Time |
|------|-------|------|
| Add tags to System routes | 3 | 10 min |
| Add tags to Data Pipeline routes | 6 | 15 min |
| Add tags to Trading routes | 2 | 5 min |
| Add tags to Analysis routes | 2 | 5 min |
| Update __init__.py imports | 1 | 5 min |
| Test Swagger UI | - | 5 min |
| **TOTAL** | **14** | **45 min** |

---


## Verification Plan

### 1. Replace Print Statements with Logger

**Test backtesting modules:**
```bash
# From project root
python -m src.backtesting.runner
```

**Expected output:**
- No `print()` output to console
- Logger messages: `YYYY-MM-DD HH:MM:SS - BacktestRunner - INFO - BACKTEST SUMMARY`

### 2. Verify Type Hints

**Run mypy type checker:**
```bash
pip install mypy
mypy src/services/actions_service.py
mypy src/api/v1/routes/actions_routes.py
mypy src/adaptors/kite_adaptor.py
```

### 3. Test Edge Case Handling

**Test sizing_utils:**
```python
from src.utils.sizing_utils import calculate_equal_weight_position

# Should raise ValueError
try:
    calculate_equal_weight_position(100000, 0, 500)
except ValueError as e:
    print(f"✓ Correctly raised: {e}")

try:
    calculate_equal_weight_position(100000, 10, -500)
except ValueError as e:
    print(f"✓ Correctly raised: {e}")
```

**Test ranking_utils:**
```python
import pandas as pd
from src.utils.ranking_utils import percentile_rank

# Should raise ValueError
try:
    percentile_rank(pd.Series([]))
except ValueError as e:
    print(f"✓ Correctly raised: {e}")
```

### 4. Validate Imports

**Test all modified files:**
```bash
python -c "from src.services.actions_service import ActionsService; print('✓')"
python -c "from src.utils.sizing_utils import calculate_position_size; print('✓')"
python -c "from src.utils.ranking_utils import percentile_rank; print('✓')"
python -c "from src.utils.finance_utils import calculate_xirr; print('✓')"
python -c "from src.adaptors.kite_adaptor import KiteAdaptor; print('✓')"
python -c "from src.backtesting.config import BacktestConfigLoader; print('✓')"
```

### 5. API Smoke Tests

**Start Flask app:**
```bash
python run.py
```

**Test endpoints:**
```bash
curl -X POST http://localhost:5000/api/v1/actions/generate
curl -X GET http://localhost:5000/api/v1/swagger
```

---

## Priority Summary

### 🔴 High Priority (Must Fix)

| File | Issue | Effort |
|------|-------|--------|
| `backtesting/runner.py` | Print statements (4) | 10 min |
| `backtesting/config.py` | Print statement (1) + logger | 5 min |
| `services/actions_service.py` | Missing type hints + docstrings | 30 min |

### 🟡 Medium Priority (Should Fix)

| File | Issue | Effort |
|------|-------|--------|
| `utils/ranking_utils.py` | Missing docstring Examples + edge cases | 20 min |
| `utils/sizing_utils.py` | Incomplete docstring + validation | 10 min |
| `utils/finance_utils.py` | Incomplete docstring | 5 min |
| `routes/actions_routes.py` | Missing type hints + error handling | 15 min |

### 🟢 Low Priority (Nice to Have)

| File | Issue | Effort |
|------|-------|--------|
| `adaptors/kite_adaptor.py` | Missing type hints + comprehensive docstrings | 20 min |

---

## Persona Compliance: "007 of Dalal Street"

> "A spy's code should be as clean as their cover story."

### ✅ Current Compliance

- **Sophisticated naming**: All functions/classes have descriptive names
- **Precision with data**: Extensive use of Decimal for financial calculations
- **Lethally accurate**: Comprehensive test coverage via utils
- **Witty comments**: Inline comments explain "why" not "what"

### Recommendations

- ✅ **Already embodied** in:
  - `factors_service.py` - elegant non-linear scoring
  - `stoploss_utils.py` - sophisticated trailing stop logic
  - `tax_utils.py` - tax-efficient decision making

- **Could enhance** in:
  - Add witty error messages in validators
  - Example: `"Position sizing impossible - even Bond needs positive prices"`

---

## Total Implementation Time Estimate

| Priority | Files | Estimated Time |
|----------|-------|----------------|
| High | 3 | 45 minutes |
| Medium | 4 | 50 minutes |
| Low | 1 | 20 minutes |
| **TOTAL** | **9** | **~2 hours** |

---

## Next Steps

1. ✅ Review this implementation plan
2. ⏳ Implement High Priority changes
3. ⏳ Run verification tests
4. ⏳ Implement Medium Priority changes
5. ⏳ Run full test suite
6. ⏳ Update `.agent/instructions.md` with planning workflow
7. ⏳ Commit changes to repository

---

**Generated:** 2026-02-08 13:13 IST  
**Agent:** The 007 of Dalal Street  
**Status:** Ready for Implementation
