# Complete Audit: `_process_daily_stoploss` and Related Functions

Three bugs found. All previous changes have been reverted — this is against the ORIGINAL code.

---

## Bug 1 (CRITICAL): Ghost Holdings — Sold Stocks Re-Added

**Location**: [runner.py:337-359](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/runner.py#L337-L359)

**Scenario**: Stock X bought Monday open, hits SL on Monday afternoon.

| Step | Line | What happens |
|------|------|-------------|
| 1 | 240 | X's `daily_low <= current_sl` → SL triggered |
| 2 | 259-260 | X added to `sold_today` and `sold_this_week` |
| 3 | 301-303 | Building `updated` list: X is **skipped** (in `sold_this_week`) ✓ |
| 4 | 339 | `get_actions(day)` called — day is **Monday** |
| 5 | — | Returns **ALL** Monday actions (original buys + sells + fills) |
| 6 | 343 | Filter: `pf.type == 'buy' and pf.status == 'Approved'` → X's **original buy action matches** |
| 7 | 345 | `existing_symbols` does NOT contain X (skipped in step 3) |
| 8 | 346 | `pf.symbol not in existing_symbols` → **TRUE** |
| 9 | 348-359 | X is **re-added** to holdings with `entry_price = execution_price` |

**Result**: X was sold at SL but reappears in the portfolio. The portfolio now carries a phantom position that absorbs market losses with no SL protection (its SL may already be breached).

**Fix**: Add `sold_this_week` check on line 346:
```diff
- if pf.symbol not in existing_symbols:
+ if pf.symbol not in existing_symbols and pf.symbol not in sold_this_week:
```

---

## Bug 2 (HIGH): `bought` Miscounted by `get_summary()` on Daily Rewrites

**Location**: [actions_service.py:472-476](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/actions_service.py#L472-L476)

The `bought` calculation uses `entry_date == date`:
```python
bought_mask = df['entry_date'] == df['date']
```

On Monday: `date = Monday`, `entry_date = Monday` → **matches** → correct.

On Tuesday+: The daily loop writes holdings with `date = Tuesday` but `entry_date` stays as the **original buy date** (Monday). The mask fails → `bought = 0`.

When the summary is rewritten on Tuesday:
```
remaining = starting_capital + sold - 0 = starting_capital + sold
```

This **inflates** remaining_capital by the full bought amount. On the NEXT Monday, `starting_capital = previous remaining_capital` (inflated). More capital → bigger positions → bigger losses.

**Evidence**: Diagnostic shows 48 dates where `summary.bought < actual buy actions` (all negative diffs).

**Fix**: Don't recalculate `bought` from holdings on daily rewrites. Either:
- Pass explicit `bought` value (like `sold` is already passed), OR
- Only write summary on days when something actually changed (SL sell or fill)

---

## Bug 3 (MEDIUM): Summary Written Every Day Even When Nothing Changed

**Location**: [runner.py:361-383](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/runner.py#L361-L383)

The `if updated:` block on line 361 runs **every day** because there are almost always remaining holdings. This means:
- `bulk_insert_holdings` and `insert_summary` run 5x per week
- Each daily summary becomes the next day's `starting_capital` source
- Bug 2 corrupts the bought value on Tue-Fri, accumulating errors

On a quiet week (no SL sells), the flow is:
- Monday: `holdings updated, summary = correct` (from `process_actions`)
- Monday daily: `summary rewritten` — bought still correct (entry_date == Monday date)
- Tuesday: `summary rewritten` — **bought = 0** (Bug 2 fires) → remaining_capital inflated
- Wednesday: `starting_capital = inflated remaining` → remaining_capital stays inflated
- Thursday-Friday: same

The inflated remaining_capital becomes next Monday's starting_capital → more capital available → bigger positions → bigger losses when SL hits.

**Fix**: Only write and insert holdings/summary when something actually happened:
```diff
- if updated:
+ if updated and (sold_today or bought_today):
```
Or guard the summary write, not the holdings write (holdings update for current_price is fine for valuation).

---

## Proposed Fix Strategy

> [!IMPORTANT]
> Fix Bug 1 first (ghost holdings) — this is the most impactful. Then fix Bug 3 (only write summary when needed), which also eliminates Bug 2 (since the mask only fails on unnecessary daily rewrites).

### [MODIFY] [runner.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/backtesting/runner.py)

1. **Line 346**: Add `sold_this_week` guard to prevent ghost holdings
2. **Lines 361-383**: Only write summary when `sold_today` or pending buys were filled. Holdings can still be updated daily for valuation tracking, but the summary should only change when there's an actual transaction.

### [MODIFY] [actions_service.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/actions_service.py)

No changes needed if Bug 3 fix prevents unnecessary summary rewrites. The `entry_date == date` mask works correctly on Monday (when buys happen); it only fails on the unnecessary Tue-Fri rewrites that Bug 3 eliminates.

---

## Verification Plan

1. **Delete** `instance/backtest.db` and re-run the backtest
2. **Re-run** `python diagnose_returns.py`
3. **Check**:
   - `BOUGHT mismatch` should show **0 mismatches** (Bug 2 eliminated)
   - `Weeks with >1 summary record` — Monday-only transactions should show **1 per week** on quiet weeks
   - Final PV should be closer to the +100% the user saw with weekly-only execution
   - No ghost holdings — every sold stock should NOT reappear
