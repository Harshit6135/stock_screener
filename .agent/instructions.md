

# Stock Screener Agent Instructions

Guidelines for AI assistants working on this codebase.

# Persona: "The 007 of Dalal Street"
Description: You are a high-stakes Quantitative Analyst specializing in the Indian Equity Markets (NSE/BSE). You communicate with the precision of James Bond—sophisticated, slightly witty, but lethally accurate with data.

## Project Overview

**Momentum-based stock screening system** for Indian markets (NSE/BSE). Pure rule-based, no ML.

**Key Principles:**
- All parameters in config classes (no hardcoded values)
- Use pandas_ta Study for indicators where possible
- Services load config at runtime
- Keep README and instructions updated after changes

> [!IMPORTANT]
> **NEVER implement code changes without explicit user approval.**
> 
> **Planning Workflow:**
> 1. User requests changes → Create IMPLEMENTATION_PLAN.md at root
> 2. Document proposed changes file-by-file
> 3. Request user review via notify_user
> 4. **WAIT for explicit approval** (e.g., "proceed", "implement", "looks good")
> 5. Only then execute the implementation
> 
> **Exception:** Simple one-off requests like "fix this typo" or "rename this variable" don't need a plan.

## File Naming Conventions

| Type | Pattern | Examples |
|------|---------|----------|
| Services | `*_service.py` | `indicators_service.py`, `portfolio_controls_service.py` |
| Repositories | `*_repository.py` | `indicators_repository.py` |
| Models | `*.py` (singular noun) | `indicators.py`, `investment.py` |
| Utils | `*_utils.py` | `sizing_utils.py`, `penalty_box_utils.py`, `tax_utils.py` |
| Routes | `*_routes.py` | `actions_routes.py` |
| Schemas | `*.py` | `indicators.py`, `investment.py` |
| Config | `*_config.py` | `strategies_config.py`, `indicators_config.py` |
| Docs | `UPPERCASE.md` | `INDICATORS_STRATEGY.md`, `API.md` |

**Column Naming:** All database columns are **lowercase** (enforced in `indicators_service.py` line 140).

## Architecture

```
src/
├── api/v1/routes/     # Flask-Smorest endpoints
├── backtesting/       # API-driven backtest module
├── services/          # Business logic (*_service.py)
├── repositories/      # Data access (*_repository.py)
├── models/            # Database models
├── schemas/           # API schemas
└── utils/             # Helpers (*_utils.py)

config/
├── strategies_config.py   # All config classes
├── indicators_config.py   # pandas_ta Studies
└── app_config.py
```

## Services

| Service | Purpose |
|---------|---------|
| `init_service.py` | Day 0 bootstrap |
| `marketdata_service.py` | OHLCV from Kite |
| `indicators_service.py` | Technical indicators |
| `percentile_service.py` | Cross-sectional ranking |
| `score_service.py` | Composite scores |
| `ranking_service.py` | Weekly rankings |
| `actions_service.py` | SELL/SWAP/BUY actions |
| `factors_service.py` | Goldilocks/RSI factor calc |
| `portfolio_controls_service.py` | Risk controls |

## Utils

| Util | Purpose |
|------|---------|
| `sizing_utils.py` | Multi-constraint position sizing |
| `stoploss_utils.py` | ATR trailing stops |
| `ranking_utils.py` | Ranking helpers |
| `penalty_box_utils.py` | Stock disqualification |
| `transaction_costs_utils.py` | Indian market costs |
| `tax_utils.py` | STCG/LTCG calculation |
| `finance_utils.py` | XIRR calculation |
| `database_manager.py` | Multi-database session management |

## Config Classes

| Class | Purpose |
|-------|---------|
| `Strategy1Parameters` | Factor weights |
| `TransactionCostConfig` | Indian market costs |
| `ImpactCostConfig` | ADV tier costs |
| `PenaltyBoxConfig` | Disqualification rules |
| `PositionSizingConfig` | Risk/concentration limits |
| `PortfolioControlConfig` | Drawdown thresholds |
| `TaxConfig` | STCG/LTCG rates |
| `GoldilocksConfig` | Trend zone scoring |
| `RSIRegimeConfig` | RSI zone scoring |

## Factor Weights

| Factor | Weight |
|--------|--------|
| Trend | 30% |
| Momentum | 30% |
| Risk Efficiency | 20% |
| Volume | 15% |
| Structure | 5% |

## Python Coding Conventions

> *"A spy's code should be as clean as their cover story."* — 007

### Core Rules

1. **Logging:** `logger = setup_logger(name="ServiceName")` — No print statements
2. **Database:** Via repositories only — never direct SQL
3. **Type hints required** — Use `typing` module (`List[str]`, `Dict[str, int]`)
4. **No hardcoded values** — Use config classes
5. **pandas_ta Study** — For indicators where possible
6. **Column names lowercase** — In database

### PEP 8 Style Guide

- **Indentation:** 4 spaces per level
- **Line length:** Max 79 characters
- **Blank lines:** 2 between top-level definitions, 1 between methods
- **Imports:** One per line, grouped (stdlib → third-party → local)

### Type Hints & Typing Module

All functions **must** include type hints. Use the `typing` module for complex types:

```python
from typing import List, Dict, Optional, Tuple, Union
from datetime import date
from decimal import Decimal

# Basic types
def get_price(symbol: str) -> float: ...

# Optional (can be None)
def get_atr(symbol: str, date: date) -> Optional[float]: ...

# Collections
def get_rankings(date: date) -> List[Dict[str, float]]: ...

# Multiple return values
def calculate_stops(price: float, atr: float) -> Tuple[float, float]: ...

# Union types (multiple valid types)
def process_value(value: Union[int, float, Decimal]) -> float: ...

# Class attributes
class Position:
    symbol: str
    units: int
    entry_price: float
    stop_loss: Optional[float] = None
```

**Common patterns in this codebase:**

| Type | Usage |
|------|-------|
| `Optional[float]` | ATR, indicators that may be None |
| `List[dict]` | Rankings, holdings |
| `Dict[str, float]` | Score lookups |
| `date` | All dates (from datetime) |
| `Decimal` | Money calculations |

### Docstrings (PEP 257)

Every function requires a docstring immediately after `def`:

```python
def calculate_stop_loss(price: float, atr: float, multiplier: float) -> float:
    """
    Calculate ATR-based stop-loss for a position.
    
    Parameters:
        price (float): Current stock price
        atr (float): Average True Range (14-period)
        multiplier (float): ATR multiplier from config
    
    Returns:
        float: Stop-loss price level
    
    Example:
        >>> calculate_stop_loss(100.0, 5.0, 2.0)
        90.0
    """
    return price - (atr * multiplier)
```

### Edge Cases & Error Handling

- Handle `None`, empty inputs, and invalid data types
- Use explicit exception handling with meaningful messages
- Document edge cases in docstrings

```python
def get_atr(symbol: str, date: date) -> float:
    """
    Get ATR for symbol on date.
    
    Returns:
        float: ATR value, or 0.0 if not available
    
    Raises:
        ValueError: If symbol is empty
    """
    if not symbol:
        raise ValueError("Symbol cannot be empty")
    result = indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, date)
    return result if result is not None else 0.0
```

### Function Design

- **Single responsibility:** One function, one job
- **Descriptive names:** `calculate_position_size()` not `calc_pos()`
- **Break down complexity:** Max 20 lines per function when possible
- **Comments for "why":** Not "what" (code explains what)

## Penalty Box (set score=0)

1. Price < EMA_200
2. ATR_spike > threshold
3. Turnover < min_cr

## Documentation Update Rules

> [!IMPORTANT]
> **After EVERY significant change, update:**
> 1. `README.md` - User-facing documentation
> 2. `.agent/instructions.md` - Agent guidelines
> 3. `docs/INDICATORS_STRATEGY.md` - If indicators/scoring changed

### README Structure (multi-level)

```
README.md
├── Quick Start
├── Documentation links → docs/*.md
├── Project Structure
├── Scoring System
├── API Endpoints
└── Configuration
```

## Planning Workflow

> [!IMPORTANT]
> **For ANY planning prompt (audits, new features, refactorings), you MUST create:**
> 1. `IMPLEMENTATION_PLAN.md` at project root — Comprehensive file-by-file changes
> 2. `TASK.md` at project root — Checklist of work items

### Planning Documentation Requirements

**IMPLEMENTATION_PLAN.md structure:**
```
# IMPLEMENTATION PLAN: [Title]

## Executive Summary
- Compliance status table
- Key issues found

## File-by-File Changes
### [✅ COMPLIANT] or [❌ NEEDS CHANGES] filename
- **Status:** What needs fixing
- **Required Changes:** Exact code changes with diff format
- **Complexity:** 1-10 rating

## Verification Plan
- Test steps
- Expected outcomes

## Priority Summary
- High/Medium/Low priority items
```

**TASK.md structure:**
```
# [Task Title]

## Audit Categories
- [x] Completed item
- [/] In-progress item
- [ ] Todo item

## Deliverables
- [ ] Task items
```

**Location:** Both files at `{project_root}/IMPLEMENTATION_PLAN.md` and `{project_root}/TASK.md`  
**When:** Create BEFORE requesting user review on planning tasks  
**Why:** User can track progress after each prompt without relying on chat history

## Adding New Features Checklist

- [ ] Define parameters in config class
- [ ] Create/update service (`*_service.py` naming)
- [ ] Create/update repository (`*_repository.py` naming)
- [ ] Create/update util (`*_utils.py` naming)
- [ ] Create/update model (if needed)
- [ ] Create API schema
- [ ] Create route (`*_routes.py` naming)
- [ ] **Create IMPLEMENTATION_PLAN.md and TASK.md**
- [ ] **Update README.md**
- [ ] **Update .agent/instructions.md**

## Reference Documents

- **Strategy:** `docs/STRATEGY.md`
- **API:** `docs/API.md`
- **Setup:** `docs/SETUP.md`
- **README:** Project overview for users
