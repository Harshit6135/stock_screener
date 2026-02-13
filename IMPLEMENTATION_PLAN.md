# Fix Backtest: Friday Rankings + Monday Open Execution

## Problem

Rankings are stored for **every Friday** (always calendar Friday, even if Friday is a market holiday — confirmed in `ranking_service.py` line 87). The backtest `run()` loop iterates over **Mondays** and passes the Monday date to `get_top_rankings()`. Since `RankingRepository.get_top_n_by_date()` uses **exact date match** (`ranking_date == date`), passing a Monday date returns **no results**, causing all weeks to be skipped.

Additionally, trade execution currently uses **closing prices** (`get_close_price`), but should use **Monday opening prices** to simulate real-world execution.

## Key Findings

1. **Rankings are always stored on calendar Fridays** — `ranking_service.py` line 87: `weekly_avg['ranking_date'] = current_friday`. The `get_friday()` function computes the calendar Friday regardless of holidays.
2. **`get_prev_friday()` already exists** in `ranking_routes.py` — normalizes any date to the previous Friday. We'll reuse this logic.
3. **Market data `open` column exists** — `MarketDataModel` has `open`, `high`, `low`, `close` fields.
4. **`get_marketdata_by_trading_symbol()` uses `>= date`** — If Monday is a holiday, it auto-finds the next available trading day's data. This already handles Monday holidays gracefully.

## Proposed Changes

### 1. `src/backtesting/data_provider.py` — Add Open Price Method

**Complexity: 2/10**

#### Add `get_open_price()` method
- Mirrors existing `get_close_price()` but returns `result.open` instead of `result.close`
- Since `get_marketdata_by_trading_symbol` uses `>= date`, if Monday is a holiday, it automatically returns the next trading day's open

---

### 2. `src/backtesting/runner.py` — Core Logic Fix

**Complexity: 5/10**

#### a. Add `_get_ranking_friday()` helper method
- Reuses the same logic from `ranking_routes.get_prev_friday()`: given a Monday (weekday=0), compute `monday - 3 days` = previous Friday
- This always yields the **calendar Friday**, which matches how rankings are stored (even if Friday was a market holiday)

#### b. Modify `run()` method (lines 362–426)
- Compute `ranking_friday = self._get_ranking_friday(week_date)` before fetching rankings
- Pass `ranking_friday` to `self.data.get_top_rankings()` 
- Add log: `"Using rankings from: {ranking_friday}"`
- Build **open price lookup** for trade execution (using `get_open_price` with Monday date)
- Keep close price lookup for portfolio valuation
- Pass open prices to `rebalance_portfolio()` for execution

#### c. Modify `rebalance_portfolio()` signature
- Add `execution_price_lookup` parameter (Monday opens) for buy/sell execution
- Keep existing `price_lookup` for stop-loss/ valuation
- Execute trades at open prices, evaluate portfolio at close prices

## Summary of Data Flow After Fix

```
Monday (week_date)
  ├── ranking_friday = get_prev_friday(week_date) → always calendar Friday
  │   └── get_top_rankings(ranking_friday) → Friday's rankings ✓
  │       (works even if Friday was a market holiday — rankings stored on calendar Friday)
  ├── open_price = get_open_price(symbol, week_date) → Monday open (or next trading day)
  │   └── Used for BUY/SELL execution prices ✓
  │       (auto-handles Monday holidays via >= date query)
  └── close_price = get_close_price(symbol, week_date) → Monday close
      └── Used for portfolio valuation & stop-loss checks ✓
```

## Verification Plan

### Manual Verification
- User to run the backtest endpoint and verify:
  1. Logs show `"Using rankings from: {friday_date}"` with correct Friday dates
  2. Rankings are no longer skipped (`"No rankings for..."` should not appear for valid weeks)
  3. Buy/sell action prices in the DB should reflect Monday opening prices
