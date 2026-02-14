# Intra-Week Daily Stop Loss Check in Backtesting

The current backtester checks SL using only the **Monday low price**. This misses intra-week SL triggers (Tue–Fri). The change iterates through each trading day of the prior week, and on the **first day** where `daily_low <= stop_loss`, sells the stock at the SL price on that day and frees the slot — before the weekly rebalance runs.

## Proposed Changes

### Data Provider

#### [MODIFY] [data_provider.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/data_provider.py)

Add a new method `get_daily_lows_in_range(tradingsymbol, start_date, end_date)` that uses the existing `MarketDataRepository.query()` (which supports date-range filters) to return a list of `(date, low)` tuples sorted by date ascending.

**Complexity: 3/10** — straightforward repository query wrapper.

---

### Backtest Runner

#### [MODIFY] [runner.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/runner.py)

**1. New method `_check_intraweek_stoploss(self, week_start, week_end)`**

- For each position in `self.positions`, fetch daily lows for the range `[week_start, week_end]`.
- Iterate day-by-day (sorted by date). On the **first day** where `daily_low <= pos.current_stop_loss`:
  - Sell the stock at `pos.current_stop_loss` (SL price, not the low).
  - Record the sell action with the **actual trigger date** (not Monday).
  - Free the slot by removing from `self.positions`.
  - Break out of the day loop for that symbol.
- Returns a list of sell action dicts.

**2. Update `run()` loop**

- Before the existing `rebalance_portfolio()` call, compute the prior week's date range (`prev_monday` to `prev_friday`).
- Call `_check_intraweek_stoploss(prev_monday, prev_friday)`.
- Prepend the resulting SL-sell actions to the week's actions list.
- The freed slots will naturally be picked up by `rebalance_portfolio()` since `self.positions` is already updated.

**Complexity: 6/10** — moderate; must handle date arithmetic and ensure SL sells feed into the weekly rebalance slot count correctly.

---

## Verification Plan

### Automated Tests

There are no existing unit tests in this project. A syntax verification will be performed:

```bash
cd src && python -c "from backtesting.runner import WeeklyBacktester; from backtesting.data_provider import BacktestDataProvider; print('OK')"
```

### Manual Verification

The user can run a backtest via the existing `/api/v1/backtest` endpoint and verify in the results that:
1. SL-triggered sells now show **intra-week dates** (e.g., Wednesday) instead of always Monday.
2. The sell price matches the SL price, not the daily low.
3. Freed slots are filled by new BUY actions in the same week's rebalance.
