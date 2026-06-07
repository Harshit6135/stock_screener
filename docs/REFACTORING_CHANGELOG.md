# Refactoring Changelog — May 2026

Complete restructuring of the service layer to reduce complexity, eliminate duplication, and fix latent bugs.

---

## Phase 1: Bug Fixes & Dead Code Removal

### `actions_service.py`
| Change | Rationale |
|---|---|
| Removed dead `pass` block in `process_actions()` | Fetched holdings with date, checked truthiness, did nothing — then re-fetched without date on the next line |
| Removed stale `# TODO Check for any investment on same or future date` | Never implemented; noise |
| Used returned `remaining_capital` from `buy_action()` at 3 call sites | Previously discarded the returned value (`_`) and manually re-subtracted. Both produce the same result but the manual path was redundant and inconsistent with Phase 2 pyramids which correctly used the return value |
| Removed `pd.set_option("future.no_silent_downcasting", True)` | Centralized in `src/__init__.py` |

### `backtesting_service.py`
| Change | Rationale |
|---|---|
| Removed `set(holding_map)` no-op (was line 144) | Created a set and immediately discarded it — vestige of deleted code |

### `investment_service.py`
| Change | Rationale |
|---|---|
| Deleted `_remaining_cash()` method | Dead code — zero callers. Used wrong capital definition (`exclude_realized`) which disagreed with the first-principles calc used everywhere else |
| Removed commented-out `# current_invested = float(sum(...))` | Dead code |
| Removed `pd.set_option` | Centralized |

### `marketdata_service.py`
| Change | Rationale |
|---|---|
| Removed 4 lines of commented-out time-of-day gating | Dead code in `_get_fetch_end_date()` |

### `score_service.py`
| Change | Rationale |
|---|---|
| Removed `pd.set_option` | Centralized |

### `src/__init__.py`
| Change | Rationale |
|---|---|
| Added `pd.set_option("future.no_silent_downcasting", True)` | Single source of truth — was duplicated in 4 service files |

---

## Phase 2: Deduplication

### NEW: `src/utils/fifo_matcher.py`
Extracted FIFO trade matching into a shared utility with three classes:
- `BuyLeg` — dataclass for a single buy lot consumed by a sell
- `MatchedTrade` — dataclass for a completed trade with weighted-average entry price, PnL, return %, days held, and buy legs for XIRR
- `FIFOTradeTracker` — engine with `add_buy()`, `match_sell()`, and `from_actions()` class method

**Previously duplicated in:**
- `backtesting_service.py` `_build_trades_from_db()` (~100 lines)
- `investment_service.py` `get_trade_journal()` (~90 lines)

Both now call `FIFOTradeTracker.from_actions()`. The old `investment_service` version used a `buy._remaining` shadow attribute hack that mutated ORM objects — eliminated.

### `backtesting_service.py`
- `_build_trades_from_db()` reduced from ~100 lines to ~40 lines using `FIFOTradeTracker`

### `investment_service.py`
- `get_trade_journal()` reduced from ~90 lines to ~20 lines using `FIFOTradeTracker`

### `utils/__init__.py`
- Added `FIFOTradeTracker`, `MatchedTrade`, `BuyLeg` to exports

---

## Phase 3: God Method Decomposition

### `actions_service.py` — `generate_actions()` (was 340 lines → now 65 lines)

Extracted 5 private methods:

| Method | Responsibility |
|---|---|
| `_load_market_context()` | Fetch prices, holdings snapshots, EMA values → returns a 4-tuple |
| `_execute_sells()` | Phase 1: process all SELL + SWAP sell-legs → returns sell actions, swap queue, capital |
| `_execute_pyramid_adds()` | Phase 2: process PYRAMID_ADD decisions → returns actions, capital |
| `_execute_buys()` | Phase 3: planned buys, swap buy legs, backfill → returns actions, capital |
| `_persist_actions()` | De-duplicate and bulk insert |

`generate_actions()` is now a clean orchestrator:
```
load context → get decisions → sells → pyramids → buys → persist → log
```

### `actions_service.py` — `process_actions()` (was 190 lines → now 45 lines)

Extracted 3 private methods:

| Method | Responsibility |
|---|---|
| `_process_sell_actions()` | Process sells, compute PnL, record capital events |
| `_process_buy_actions()` | Create new holdings or merge pyramid adds |
| `_update_held_positions()` | Update unchanged positions with current prices/trailing SL |

### `actions_service.py` — `SimpleNamespace` replaced
- Replaced `SimpleNamespace(entry_price=..., units=...)` duck-typed holding with proper `HoldingSnapshot` dataclass (already defined in `trading_service.py`)
- Removed `from types import SimpleNamespace` import

---

## Phase 4: Cleanup & Consistency

### `stoploss_utils.py`
- Merged `calculate_effective_stop()` (trivial wrapper) into `calculate_atr_trailing_stop()` by adding `round_digits` parameter
- Added backward-compatible alias: `calculate_effective_stop = calculate_atr_trailing_stop`

### `score_service.py`
- Moved module-level repo instantiation (`score_repo`, `percentile_repo`, `indicators_repo`) into `__init__()` as `self.score_repo` etc.
- These were dead code — no references found anywhere in the codebase

### `investment_repository.py`
- Removed `insert_summary()` redirect method — it just called `upsert_summary()`. No callers remained.

---

## Net Impact

| Metric | Before | After |
|---|---|---|
| `actions_service.py` total lines | 1,050 | 990 |
| `generate_actions()` body | 340 lines | 65 lines (orchestrator) |
| `process_actions()` body | 190 lines | 45 lines (orchestrator) |
| FIFO matching implementations | 2 (190 lines combined) | 1 shared (110 lines) |
| `pd.set_option` call sites | 4 files | 1 file |
| Dead methods/code blocks removed | 0 | 5 (`_remaining_cash`, `insert_summary`, `calculate_effective_stop` wrapper, `set(holding_map)`, dead `pass` block) |
| `SimpleNamespace` usage | 1 (fragile duck typing) | 0 (proper `HoldingSnapshot` dataclass) |
| Module-level repo instantiation | 3 repos in `score_service.py` | 0 (moved to `__init__`) |

## Files Changed

```
MODIFIED  src/__init__.py
MODIFIED  src/services/actions_service.py
MODIFIED  src/services/backtesting_service.py
MODIFIED  src/services/investment_service.py
MODIFIED  src/services/marketdata_service.py
MODIFIED  src/services/score_service.py
MODIFIED  src/repositories/investment_repository.py
MODIFIED  src/utils/__init__.py
MODIFIED  src/utils/stoploss_utils.py
NEW       src/utils/fifo_matcher.py
```
