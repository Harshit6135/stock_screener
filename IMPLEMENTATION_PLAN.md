# Daily Stop-Loss Processing + Bug Fixes

## Overview

Change backtesting from weekly-only to daily stop-loss monitoring with capital-aware buy approval.

## Execution Rules

| Action | When | Price |
|--------|------|-------|
| **Monday vacancy buys** | Monday | Open |
| **Monday swap sell+buy** | Monday | Open |
| **Monday score degradation sell** | Monday | Open |
| **Mid-week SL sell** | Day it triggers | SL price |
| **Mid-week replacement buy** | Same day | Close |
| **Unfilled buys** | Rejected next Monday | — |

> [!NOTE]
> Monday = planned actions (from Friday analysis), execute at open.
> Mid-week = reactive actions (SL triggers), sell at SL, buy at close.
> Since SL is checked daily, `generate_actions` on Monday won't produce SL sells —
> they've already been caught during the previous week's daily loop.

## Flow

```
For each week:
  1. Monday: generate_actions → score sells + swaps + vacancy buys
  2. Monday: approve_all_actions (capital-aware)
     - Approve ALL sells → execution_price = Monday open
     - Approve buys IF capital allows → execution_price = Monday open
     - Unfilled buys stay Pending
  3. Monday: process_actions → execute approved actions, create holdings

  4. Mon → Fri daily loop:
     - For each held stock: get that day's low
     - If low ≤ current_sl → sell at SL price, record action
     - After sells: check pending buys → fill at day's close if capital available
     - Update all holdings: current_price = day's close, recalculate trailing SL

  5. End of week: reject remaining Pending buys
  6. Generate weekly summary (Friday)
```

## Proposed Changes

### [MODIFY] [runner.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/runner.py)

- Rewrite `run()` with daily inner loop
- New `_process_daily_stoploss(monday, friday)` method
- New `_get_business_days(monday, friday)` helper

### [MODIFY] [actions_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/actions_service.py)

- **`approve_all_actions`**: capital-aware — approve sells first (open price), buys within budget (open price)
- **New: `reject_pending_actions()`**
- **Bug 1**: `update_holding` — use `rank_date` for price/ATR
- **Bug 2**: `buy_action` — use `ranking_date` for ATR
- **Bug 4**: `generate_actions` — compute fresh trailing stop before SL check

### [MODIFY] [actions_repository.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/repositories/actions_repository.py)

- **New: `get_pending_actions()`**
- **New: `insert_action(action_dict)`** — single insert without deleting existing

### [MODIFY] [stoploss_utils.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/utils/stoploss_utils.py)

- **Bug 6**: `calculate_effective_stop` — add `max(..., previous_stop)` guard

## Verification

1. Re-run 1-year backtest
2. SL sells on actual trigger days, not just Mondays
3. Zero holdings where `current_price < current_sl`
4. `Rejected` status for unfilled buys
5. Daily holdings rows, weekly summary rows
