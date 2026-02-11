# Pure Return Momentum Factors (3m/6m Skip-Week)

> **The 007 of Dalal Street** — *"In momentum trading, the last week is just noise, M. We skip it."*

## Problem

The spec defines **pure return momentum** as:
- **3-month**: `close[t-5] / close[t-65] - 1` (skip last week)
- **6-month**: `close[t-5] / close[t-130] - 1` (skip last week)

Currently, `ROC_60` and `ROC_125` are standard Rate of Change (`current / N_days_ago - 1`), which includes the last 5 trading days. The spec explicitly skips the last week to **avoid short-term mean-reversion noise** that would corrupt the momentum signal.

## Proposed Changes

### Indicators Layer

#### [MODIFY] [indicators_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/indicators_service.py)
- Add `momentum_3m` and `momentum_6m` calculation to `_calculate_derived_indicators()`
- Formula: `df['close'].shift(5) / df['close'].shift(65) - 1` and `df['close'].shift(5) / df['close'].shift(130) - 1`
- These use the `close` column already present in the DataFrame before it's dropped

#### [MODIFY] [indicators_model.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/indicators_model.py)
- Add two new columns: `momentum_3m = db.Column(db.Float, nullable=True)` and `momentum_6m = db.Column(db.Float, nullable=True)`

---

### Factors Layer

#### [MODIFY] [factors_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/factors_service.py)
- Update `calculate_momentum_factor()` to accept `momentum_3m` and `momentum_6m` instead of `roc_60` and `roc_125`
- Update `calculate_all_factors()` to pass the new columns

---

### Percentile Layer

#### [MODIFY] [percentile_model.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/percentile_model.py)
- Add `momentum_3m` and `momentum_6m` columns to store raw factor values
- Add `momentum_pure_rank` column for the skip-week momentum percentile rank

#### [MODIFY] [percentile_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/percentile_service.py)
- `_calculate_percentile_ranks`: Add `factor_momentum_pure` → `momentum_pure_rank` to the factor ranking map
- `calculate_composite_score`: Include `factor_momentum_pure`, `momentum_pure_rank` in `req_cols`

---

### Scoring Layer

#### [MODIFY] [strategies_config.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/config/strategies_config.py)
- Add `momentum_pure_weight` to `Strategy1Parameters`
- Re-distribute weights: Trend 0.25, Momentum 0.25, **Pure Momentum 0.10**, Risk 0.20, Volume 0.15, Structure 0.05

#### [MODIFY] [score_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/score_service.py)
- Add `momentum_pure_rank` to composite formula
- Update module docstring

#### [MODIFY] [score_model.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/score_model.py) *(if exists)*
- Add `momentum_pure_rank` column

---

## User Review Required

> [!IMPORTANT]
> **Weight Re-Distribution**: Adding a new factor (pure momentum) requires adjusting existing weights. My proposal:
> 
> | Factor | Current | Proposed |
> |---|---|---|
> | Trend | 0.30 | 0.25 |
> | Momentum (RSI+PPO+ROC) | 0.30 | 0.25 |
> | **Pure Momentum (3m/6m skip)** | — | **0.10** |
> | Risk Efficiency | 0.20 | 0.20 |
> | Volume | 0.15 | 0.15 |
> | Structure | 0.05 | 0.05 |
> 
> Alternative: Fold skip-week momentum INTO the existing momentum factor (replace `roc_60`/`roc_125` with `momentum_3m`/`momentum_6m`) — no weight change needed, simpler.

> [!WARNING]
> **DB Migration**: Adding columns to `indicators` and `percentile` tables means existing data won't have these values. Existing rows will have `NULL` for new columns. A backfill of indicators (`calculate_indicators`) would be needed to populate historical data.

## Verification Plan

1. `py_compile` all modified files
2. Verify new columns appear in DB models
3. Confirm factors_service correctly computes skip-week momentum
