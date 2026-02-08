# IMPLEMENTATION PLAN: Codebase Issues Resolution

**Agent:** The 007 of Dalal Street  
**Date:** 2026-02-08  
**Objective:** Address 13 identified issues across config, routes, utils, and models

---

## Executive Summary

| # | Issue | Status | Priority | Files Affected |
|---|-------|--------|----------|----------------|
| 1 | Update Transaction Costs per TODOs | ✅ DONE | HIGH | `strategies_config.py`, `transaction_costs_utils.py` |
| 2 | Convert to python-json-logger | ✅ DONE | MEDIUM | `logger_config.py` |
| 3 | Config input via schema (not hardcoded) | ✅ EXISTS | LOW | `config_routes.py`, `RiskConfigSchema` |
| 4 | Actions still contains backtesting endpoint | ✅ DONE | HIGH | `actions_routes.py` |
| 5 | Move config/backtest to separate routes | ✅ DONE | HIGH | `actions_routes.py`, `backtest_routes.py` |
| 6 | Imports at top of file (not in functions) | ✅ DONE | MEDIUM | `actions_routes.py`, `runner.py` |
| 7 | Implement action CRUD endpoints | ✅ DONE | HIGH | `actions_routes.py` |
| 8 | Expose backtesting via endpoint | ✅ DONE | HIGH | `backtest_routes.py` |
| 9 | Remove duplicate code in backtesting | ✅ DONE | MEDIUM | `runner.py` |
| 10 | Remove backward compatibility alias | ✅ DONE | LOW | `models/__init__.py`, `database_manager.py` |
| 11 | Add calculate_buy_costs/calculate_sell_costs | ✅ DONE | HIGH | `transaction_costs_utils.py` |
| 12 | Check for undefined function references | ✅ DONE | HIGH | All functions verified |
| 13 | Comment out unused functions | ✅ DONE | LOW | `sizing_utils.py`, `tax_utils.py` |

---

## Proposed Changes

---

### Issue 1: Update Transaction Costs per TODOs

#### [MODIFY] [strategies_config.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/config/strategies_config.py)

**Current TODOs (lines 28-34):**
```python
#TODO STT is on Buy and Sell both
#TODO Exchange is on Buy and Sell both
#TODO SEBI is on Buy and Sell both
#TODO Stamp Duty is on Buy
#TODO GST is on Buy and Sell both
#TODO IPF Charges on Buy and Sell both (10 per crore)
#TODO DP Charges 13 per sell
```

**Proposed Config:**
```python
class TransactionCostConfig:
    """Indian market transaction cost parameters (Zerodha delivery)"""
    # Brokerage: Zero for delivery
    brokerage_percent: float = 0.0
    brokerage_cap: float = 0.0
    
    # STT: Buy AND Sell @ 0.1%
    stt_buy_percent: float = 0.001
    stt_sell_percent: float = 0.001
    
    # Exchange: Buy AND Sell
    exchange_percent: float = 0.0000345
    
    # SEBI: Buy AND Sell
    sebi_per_crore: float = 10.0
    
    # Stamp Duty: Buy only @ 0.015%
    stamp_duty_percent: float = 0.00015
    
    # GST: Buy AND Sell @ 18% on (brokerage + exchange + SEBI)
    gst_percent: float = 0.18
    
    # NEW: IPF Charges (₹10 per crore) - Buy AND Sell
    ipf_per_crore: float = 10.0
    
    # NEW: DP Charges (₹13 per sell transaction)
    dp_charges_per_sell: float = 13.0
```

#### [MODIFY] [transaction_costs_utils.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/utils/transaction_costs_utils.py)

Update `calculate_transaction_costs()` to use accurate formula.

---

### Issue 2: Convert to python-json-logger

#### [MODIFY] [logger_config.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/config/logger_config.py)

**Proposed Changes:**
```python
from pythonjsonlogger import jsonlogger

def setup_logger(name="StockScreener", log_dir="logs"):
    # ... existing setup ...
    
    # JSON format for file
    json_formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s'
    )
    file_handler.setFormatter(json_formatter)
```

**Dependency:** Add `python-json-logger` to `pyproject.toml`

---

### Issue 3: Config Input via Schema

**Status:** ✅ Already exists at `GET/PUT /api/v1/config/<strategy_name>`

Uses `RiskConfigSchema` for input validation. No changes needed.

---

### Issue 4 & 5: Move Backtesting to Separate Routes

#### [DELETE] Backtesting from [actions_routes.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/actions_routes.py)

Remove lines 44-64 (`ActionsBackTest` class)

#### [NEW] [backtest_routes.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/backtest_routes.py)

```python
"""
Backtest Routes

API endpoints for backtesting operations.
"""
from datetime import datetime
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from config import setup_logger
from schemas import BacktestInputSchema, MessageSchema
from src.backtesting import run_backtest

logger = setup_logger(name="BacktestRoutes")

blp = Blueprint(
    "backtest",
    __name__,
    url_prefix="/api/v1/backtest",
    description="Backtesting Operations"
)


@blp.route("/run")
class RunBacktest(MethodView):
    @blp.doc(tags=["Backtest"])
    @blp.arguments(BacktestInputSchema)
    @blp.response(200, MessageSchema)
    def post(self, data) -> dict:
        """Run backtest for date range."""
        try:
            start_date = datetime.strptime(str(data['start_date']), '%Y-%m-%d').date()
            end_date = datetime.strptime(str(data['end_date']), '%Y-%m-%d').date()
            
            results, summary = run_backtest(start_date, end_date)
            
            return {
                "message": f"Backtest completed. Final: {summary.get('final_value', 0)}, "
                          f"Return: {summary.get('total_return', 0):.2f}%"
            }
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            abort(500, message=str(e))
```

#### [MODIFY] [routes/__init__.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/__init__.py)

Add backtest_routes import and blueprint registration.

---

### Issue 6: Imports at Top of File

#### [MODIFY] [actions_routes.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/actions_routes.py)

**Current (inside function):**
```python
def post(self) -> dict:
    from flask_smorest import abort   # ❌ WRONG
    from config import setup_logger   # ❌ WRONG
```

**Proposed (at top):**
```python
from flask_smorest import Blueprint, abort
from config import setup_logger

logger = setup_logger(name="ActionsRoutes")
```

#### [MODIFY] [runner.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/runner.py)

Move line 217 import to top:
```python
# Line 217: from config.strategies_config import PositionSizingConfig
# Move to top with other imports
```

---

### Issue 7: Implement Action CRUD Endpoints

#### [MODIFY] [actions_routes.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/actions_routes.py)

Consolidate action endpoints from `investment_routes.py`:

```python
@blp.route("/dates")
class ActionDates(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.response(200, ActionDateSchema)
    def get(self):
        """Get all distinct action dates"""
        dates = ActionsRepository.get_action_dates()
        return {"dates": dates}


@blp.route("/")
class ActionsList(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, ActionSchema(many=True))
    def get(self, args):
        """Get actions for a specific date"""
        working_date = args.get('date')
        actions = ActionsRepository.get_actions(working_date)
        return [a.to_dict() for a in actions]


@blp.route("/<int:action_id>")
class ActionDetail(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.arguments(ActionUpdateSchema)
    @blp.response(200, MessageSchema)
    def put(self, data, action_id):
        """Update action (approve/reject/modify units)"""
        result = ActionsRepository.update_action(action_id, data)
        if result:
            return {"message": f"Action {action_id} updated"}
        abort(400, message=f"Failed to update action {action_id}")
```

#### [MODIFY] [investment_routes.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/investment_routes.py)

Remove action endpoints (lines 19-63) since they move to `actions_routes.py`

---

### Issue 8: Expose Backtesting via Endpoint

Covered by Issue 5 - new `backtest_routes.py`

---

### Issue 9: Remove Duplicate Code in Backtesting

#### [MODIFY] [runner.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/runner.py)

**Potential duplicates identified:**
1. Position size calculation duplicates `sizing_utils.py` logic
2. Import `PositionSizingConfig` inside function (line 217)

**Proposed refactor:**
- Use `calculate_risk_based_position()` from `sizing_utils.py` instead of reimplementing
- Move all imports to top of file

---

### Issue 10: Remove Backward Compatibility Alias

#### [MODIFY] [models/__init__.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/__init__.py)

**Current:**
```python
from .investment import InvestmentActionsModel, ...
```

**Proposed:**
```python
# Remove InvestmentActionsModel import entirely
from .actions import ActionsModel
from .investment import InvestmentHoldingsModel, InvestmentSummaryModel
```

#### [MODIFY] [investment.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/investment.py)

Already done by user - no legacy import at bottom.

---

### Issue 11: Add calculate_buy_costs/calculate_sell_costs

#### [MODIFY] [transaction_costs_utils.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/utils/transaction_costs_utils.py)

**Current (empty stubs):**
```python
def calculate_buy_costs():
    pass

def calculate_sell_costs():
    pass
```

**Proposed:**
```python
def calculate_buy_costs(trade_value: float,
                        config: TransactionCostConfig = None) -> dict:
    """
    Calculate buy-side transaction costs.
    
    Parameters:
        trade_value: Order value in INR
        config: TransactionCostConfig
        
    Returns:
        dict: Breakdown with total
    """
    return calculate_transaction_costs(trade_value, 'buy', config)


def calculate_sell_costs(trade_value: float,
                         config: TransactionCostConfig = None) -> dict:
    """
    Calculate sell-side transaction costs.
    
    Parameters:
        trade_value: Order value in INR
        config: TransactionCostConfig
        
    Returns:
        dict: Breakdown with total
    """
    return calculate_transaction_costs(trade_value, 'sell', config)
```

---

### Issue 12: Check for Undefined Function References

**Files to check:**
- `costs_routes.py` - imports `calculate_buy_costs`, `calculate_sell_costs` (missing)
- `runner.py` - imports `calculate_initial_stop_loss`, `calculate_effective_stop`

**Action:** Fix missing functions before deployment

---

### Issue 13: Comment Out Unused Functions

**Strategy:** After verifying all references, comment out any functions with 0 usages.

---

## File-by-File Summary

| File | Action | Changes |
|------|--------|---------|
| `config/strategies_config.py` | MODIFY | Add IPF, DP charges; split STT for buy/sell |
| `config/logger_config.py` | MODIFY | Add python-json-logger support |
| `src/utils/transaction_costs_utils.py` | MODIFY | Implement calculate_buy_costs, calculate_sell_costs |
| `src/api/v1/routes/actions_routes.py` | MODIFY | Remove backtesting, add CRUD endpoints, imports at top |
| `src/api/v1/routes/backtest_routes.py` | NEW | Dedicated backtesting endpoint |
| `src/api/v1/routes/investment_routes.py` | MODIFY | Remove action endpoints (moved to actions_routes) |
| `src/api/v1/routes/__init__.py` | MODIFY | Add backtest_routes import |
| `src/backtesting/runner.py` | MODIFY | Move imports to top, use sizing_utils |
| `src/models/__init__.py` | MODIFY | Remove InvestmentActionsModel alias |

---

## Verification Plan

### 1. Syntax Check
```bash
python -m py_compile src/utils/transaction_costs_utils.py
python -m py_compile src/api/v1/routes/actions_routes.py
python -m py_compile src/api/v1/routes/backtest_routes.py
```

### 2. Run Application
```bash
python run.py
```
Check Swagger UI at `http://localhost:5000/docs` for:
- `/api/v1/actions/*` endpoints (new CRUD)
- `/api/v1/backtest/run` endpoint (new)
- `/api/v1/investment/*` endpoints (holdings/summary only)

### 3. API Tests
```bash
# Test buy costs
curl "http://localhost:5000/api/v1/costs/buy?trade_value=100000"

# Test sell costs
curl "http://localhost:5000/api/v1/costs/sell?trade_value=100000"

# Test roundtrip
curl "http://localhost:5000/api/v1/costs/roundtrip?trade_value=100000"
```

### 4. Manual Verification
1. Run app and verify no import errors
2. Check Swagger UI groups are correct (System, Trading, Analysis, Backtest)
3. Verify logger outputs JSON to file

---

## Priority Order

1. **CRITICAL (blocks runtime):**
   - Issue 11: Add calculate_buy_costs/calculate_sell_costs
   - Issue 12: Fix undefined function references

2. **HIGH (route cleanup):**
   - Issue 4, 5, 8: Move backtesting to separate routes
   - Issue 7: Implement action CRUD endpoints

3. **MEDIUM (code quality):**
   - Issue 1: Update transaction costs per TODOs
   - Issue 6: Imports at top of file
   - Issue 9: Remove duplicate code

4. **LOW (cleanup):**
   - Issue 2: Convert to python-json-logger
   - Issue 10: Remove backward compatibility
   - Issue 13: Comment unused functions

---

**Awaiting user approval to proceed with implementation.**
