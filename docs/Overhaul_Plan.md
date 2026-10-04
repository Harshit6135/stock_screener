# Stock Screener  — Master Overhaul Plan — Confirmed Scope

> This plan supersedes `detailed_plan.md` and `best_practices_gap_analysis.md`. This is the authoritative plan. Phase files must follow it. The user authorized implementation and completion of all seven phases on 2026-09-29. Current evidence and outstanding work are recorded in [repair-status.md](phases/repair-status.md).

---

## 1. Universe: NIFTY 500 Constituents

### Source
- **URL**: `https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv`
- **No cookies needed** — works directly
- **Format**: `Company Name, Industry, Symbol, Series, ISIN Code` (502 lines)
- **Accept ALL series** (EQ, BE, BZ — no series filter)

### New Tables

```sql
CREATE TABLE universe_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    index_name TEXT NOT NULL,         -- 'NIFTY 500'
    snapshot_date TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_hash TEXT NOT NULL,         -- SHA-256 of raw CSV bytes
    member_count INTEGER NOT NULL,
    raw_csv BLOB NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(index_name, snapshot_date)
);

CREATE TABLE universe_snapshot_members (
    snapshot_id TEXT NOT NULL,
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    company_name TEXT NOT NULL,
    industry TEXT,
    series TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, isin),
    FOREIGN KEY(snapshot_id) REFERENCES universe_snapshots(snapshot_id)
);
```

### New Job: `reference.download-nifty500-constituents`
1. Determine the collection day and check snapshot availability
2. Before downloading, check for an existing snapshot for the collection day. If present, reuse it, skip universe download/storage/diff and proceed to the next pipeline stage. The first successful snapshot is immutable for that day.
3. If no snapshot exists, download and hash the raw CSV bytes.
4. Parse CSV, extract all members
5. Insert into `universe_snapshots` + `universe_snapshot_members` atomically
6. Diff against previous snapshot → log additions and removals
7. For new ISINs not yet in `reference_instruments`: match against `kite.instruments("NSE")` by `tradingsymbol`, upsert instrument, schedule historical bar fetch

### History Tracking
- `universe_changes(from_date, to_date)` → returns `{added: [...], dropped: [...]}`
- Keep one snapshot per index/day; retain snapshots from previous days.
- Keep the first successful daily snapshot unchanged. Later runs reuse it and proceed; never overwrite it or create another snapshot for the day. Concurrent attempts must converge on the existing snapshot.
- Current downloads must record their actual collection date, not a historical as_of label.
- Build history **from today** — no historical constituent data available from NSE
- For backtesting dates before first snapshot: use earliest available snapshot (document assumption)

### Integration
- `PositionalTrendJobs._members()` reads from `universe_snapshot_members` of latest snapshot (replaces static CSV)
- Remove `ind_nifty500list.csv` from project root
- Replace runtime CSV reads with DB snapshots.
- No scheduling is in scope. Run manually through the pipeline: universe snapshot → instrument/token resolution → corporate-action detection/refresh → bars/quality → indicators/cache rebuild → strategy-specific percentiles/signals → scores/rankings for both momentum and positional_trend_following.

---

## 2. Market Data: Instrument Resolution & Index Benchmarks

### Instrument Resolution Flow (Simplified)
1. Download NIFTY 500 CSV → get `Symbol` list
2. Call `kite.instruments("NSE")` → get full instrument dump (daily, cache locally)
3. Match by `tradingsymbol` (no series filter — accept all)
4. Extract `instrument_token` for each matched stock
5. `instrument_id = uuid5(NAMESPACE_URL, f"NSE:{isin}")` — internal lineage key (unchanged)
6. Use `kite.historical_data(instrument_token, from, to, "day")` to fetch bars

### Remove BSE Entirely
- Delete `sync_bse_instruments()` method from [market_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/market_jobs.py)
- Delete `BSE_INDEX_SYMBOLS` constant
- Remove `bse_csv_path` parameter from [composition.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/composition.py) and all callers
- Remove `uuid5("BSE:...")` instrument_id generation
- Remove BSE fallback logic in [positional_trend_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/positional_trend_jobs.py)
- Delete `data/imports/BSE.csv` and `data/imports/NSE.csv` references (no longer needed — NIFTY 500 CSV is the sole source)
- Remove `reference.sync-bse-instruments` worker handler from [composition.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/composition.py)

### Series Continuity
- Remove the `SERIES == "EQ"` filter in `sync_instruments` ([market_jobs.py L79](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/market_jobs.py#L79))
- Accept all series from the instruments endpoint — universe membership (NIFTY 500 CSV) determines what's tracked
- Add `series` column to `reference_instruments` (new migration)
- When series changes (EQ → BE), ISIN stays stable → `instrument_id` stable → bar history preserved
- Log series transitions

### Index Benchmarks — Add Historical Bars
Update `NSE_INDEX_SYMBOLS` in [market_jobs.py L28-30](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/market_jobs.py#L28-L30):
```python
NSE_INDEX_SYMBOLS = frozenset({
    "NIFTY 50",
    "NIFTY 500",
    "NIFTY NEXT 50",
    "NIFTY MIDCAP 150",
    "NIFTY SMLCAP 250",   # verify exact tradingsymbol from kite.instruments("NSE")
    "INDIA VIX",
})
```
- Remove `NIFTY 100`, `NIFTY BANK`, `NIFTY MIDCAP 50` (not needed)
- Fetch **historical daily bars** for all indices via `kite.historical_data(index_token, "2021-01-01", today, "day")`
- Store in same `market_bars` table alongside equities
- Live quotes continue via websocket (existing flow unchanged)

### New Universe Member Bar Fetch
- After universe download detects new ISINs:
  1. Match against Kite instruments to get `instrument_token`
  2. Fetch bars from `2021-01-01` to today
  3. Store in `market_bars`

### Dropped Members Handling
- **Stop regular market data**: Excluded members are removed from regular refresh immediately. For a compulsory exit, retain explicit exit-only coverage through the next trading session so its opening price can be used; stop further refresh after that session. This exception does not restore membership or buy eligibility.
- **Auto-sell**: If portfolio holds a dropped stock → generate SELL action proposal for user approval
  - `ActionJobs.generate()` checks universe membership before building buy list
  - Additionally scans current holdings against latest snapshot → any holding NOT in latest snapshot → propose SELL
- **Retain history**: Keep dropped-member history and the single next-session exit-price record. Tag post-exclusion coverage as exit-only; it cannot feed new entries/rankings. Do not resume general refresh merely because a live sale remains open. Removed-strategy backtest cleanup remains separately scoped.
- Managed strategy holdings follow current NIFTY 500 membership; unrelated broker holdings are excluded.
- User-confirmed assumption: exit SELL proposals receive approval on the same day. Approval is still required; this does not authorize automatic submission.
- Backtests use as-of membership, generate compulsory exits on exclusion and execute the exit at the next trading session's actual open. Retain one extra session of exit-only data; do not use that future opening price in the exit decision, prior valuation, ranking or buy eligibility. Never substitute today's membership for stored historical snapshots. Preserve the documented earliest-snapshot fallback for pre-snapshot dates.
- Exit records carry decision date, target execution session, universe snapshot, reason, price source and fill status. Missing opening prices cannot be replaced by fabricated fills or the previous close. Saved runs remain immutable; newly requested runs use this exit policy.

---

## 3. Corporate Actions: Deterministic NSE Source + Kite Adjusted Prices

### Key Insight
**Kite returns adjusted prices in `historical_data()`**. So:
- Kite is authoritative. BONUS/SPLIT may be self-adjusted temporarily and must be re-fetched on later manual runs. RIGHTS/DEMERGER are monitored and re-fetched only; never locally adjusted.
- Corporate action handling = detect → re-fetch bars from Kite → overwrite `market_bars`
- NSE corporate actions API = deterministic detection source
- Close-gap heuristic = validation/catch-all backup

### NSE Corporate Actions API
- **URL**: `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`
- **Requires cookies**: Hit `https://www.nseindia.com` first to get session cookies
- **Returns JSON** with fields: `symbol`, `isin`, `series`, `exDate`, `subject`, `faceVal`, `comp`
- **Action types found**: BONUS, SPLIT, RIGHTS, DEMERGER, DIVIDEND, BUYBACK

### Actions That Affect Price (We Handle)
| Type | Subject Pattern | Regex |
|------|----------------|-------|
| **BONUS** | `Bonus 1:3` | `Bonus\s+(\d+):(\d+)` |
| **SPLIT** | `Face Value Split - From Rs 10/- To Rs 2/-` | `From Rs\s+(\d+).*To Rs\s+(\d+)` → ratio = old/new |
| **RIGHTS** | Rights issue | Detect/monitor price difference; Kite refresh only |
| **DEMERGER** | `Demerger` or `Scheme Of Arrangement` | Detect/monitor price difference; Kite refresh only |

### Actions We Ignore
- DIVIDEND (excluded from this plan's local price-adjustment processing)
- BUYBACK (no price adjustment)
- Interest Payment

### New Table
```sql
CREATE TABLE corporate_action_events (
    event_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    isin TEXT NOT NULL,
    instrument_id TEXT,             -- matched to our universe, NULL if not in universe
    ex_date TEXT NOT NULL,
    action_type TEXT NOT NULL,       -- 'BONUS', 'SPLIT', 'RIGHTS', 'DEMERGER'
    subject TEXT NOT NULL,           -- raw subject text from NSE
    parsed_ratio TEXT,               -- e.g., '1:3' for bonus, '10:2' for split
    adjustment_factor REAL,          -- computed from parsed ratio
    source TEXT NOT NULL,            -- 'NSE_API' or 'HEURISTIC'
    status TEXT NOT NULL,            -- 'DETECTED', 'SELF_ADJUSTED', 'MONITORING', 'VERIFIED'
    detected_at TEXT NOT NULL,
    refreshed_at TEXT,
    UNIQUE(isin, ex_date, action_type)
);
```

### Manual Pipeline Flow
1. Fetch NSE actions using a successful-detection watermark with overlap, independent of the latest bar date. Normalize dates and persist raw source data.
2. Resolve tracked instruments; unresolved references are NULL, never an empty-string foreign key.
3. Detect BONUS, SPLIT, RIGHTS and DEMERGER. Multiple actions for one stock/day are out of scope by user decision; rely on Kite rather than local combination logic.
4. Actually re-fetch Kite history and compare pre-action bars with a preserved baseline. Calendar age/weekends alone do not prove adjustment.
5. BONUS/SPLIT: store verified Kite history when available. Otherwise apply the parsed multiplier once to bars before ex-date and retain SELF_ADJUSTED as actionable work.
6. Every later manual pipeline run re-fetches SELF_ADJUSTED instruments. Keep the state until verified Kite history replaces local data. Temporary adjustment must never mark work completed.
7. RIGHTS/DEMERGER: monitor price differences and re-fetch Kite; never compute/apply local factors. Use Kite price-anomaly detection to drive refresh/monitoring state.
8. Apply bar/state updates atomically and idempotently. Preserve baseline/provenance to prevent repeated multiplication after retries/crashes and distinguish previously adjusted data.
9. Rebuild affected indicator cache histories before fresh computation. Preserve already published historical percentiles/rankings under the user policy in §5.
10. Emit quality events for unexplained gaps/mismatches. Adapt existing CorporateActions API, backtest consumers and adjusted-bar reader so they do not adjust refreshed history twice.

---

### Subject Text Parsing
```python
import re

def parse_corporate_action(subject: str) -> dict:
    subject_lower = subject.lower()
    
    # BONUS: "Bonus 1:3"
    m = re.search(r'bonus\s+(\d+)\s*:\s*(\d+)', subject_lower)
    if m:
        new, existing = int(m.group(1)), int(m.group(2))
        return {"type": "BONUS", "ratio": f"{new}:{existing}", 
                "factor": existing / (existing + new)}
    
    # SPLIT: "From Rs 10/- ... To Rs 2/-"
    m = re.search(r'from\s+rs\s*\.?\s*(\d+).*?to\s+rs?\s*\.?\s*(\d+)', subject_lower)
    if m:
        old_fv, new_fv = int(m.group(1)), int(m.group(2))
        return {"type": "SPLIT", "ratio": f"{old_fv}:{new_fv}", 
                "factor": new_fv / old_fv}
    
    # RIGHTS: "Rights 3:2 @ Premium Re. 0.63/-"
    m = re.search(r'rights\s+(\d+)\s*:\s*(\d+)\s*@\s*premium\s*rs?\.\?\s*([\d.]+)', subject_lower)
    if m:
        rights_shares, held_shares = int(m.group(1)), int(m.group(2))
        premium = float(m.group(3))
        return {"type": "RIGHTS", "ratio": f"{rights_shares}:{held_shares}",
                "premium": premium, "factor": None}  # monitoring only; never self-adjust rights
    
    # DEMERGER
    if "demerger" in subject_lower or "scheme of arrangement" in subject_lower:
        return {"type": "DEMERGER", "ratio": None, "factor": None}  # monitoring only; Kite refresh
    
    return None
```

### Kite Adjustment Verification
- Trust Kite data as authoritative, but verify adjustment against the baseline. Weekend timing is an expectation, not a completion condition.
- If ex-date was Friday and we fetch on Saturday: Kite may not have adjusted yet
- **Solution**: Compare our computed adjustment factor with the actual price change
  - If `prev_close × our_factor ≈ kite_adjusted_close` → Kite has adjusted
  - If `prev_close ≈ kite_close` (no change) → Kite hasn't adjusted yet → apply ourselves, mark for re-fetch

---

## 4. Indicators DAG: Bug Fixes

### Bugs to Fix

**4.1: 8 unimplemented operations** in `APPROVED_OPERATIONS` ([dag.py L36-42](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/domains/indicators/dag.py#L36-L42)):
- `percentile`, `rank`, `z_score`, `sector_z_score`, `modifier`, `all`, `any`, `not`
- Either implement or remove from `APPROVED_OPERATIONS`

**4.2: `_OPERATIONS` desync** between [strategy_definitions.py L29-36](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/gates/strategy_definitions.py#L29-L36) and [dag.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/domains/indicators/dag.py):
- Missing `abs`, `pct_change`, `ewm_mean` in `_OPERATIONS`
- **Fix**: Define `APPROVED_OPERATIONS` once in `dag.py`, import in `strategy_definitions.py`

**4.3: Private method access** ([dag.py L414](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/domains/indicators/dag.py#L414)):
- `self._adapter._validate_parameters` — expose as public method

**4.4: Content hash uses node IDs, not content hashes** ([dag.py L91-108](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/domains/indicators/dag.py#L91-L108)):
- Hash should recursively include input nodes' content hashes for true content-addressed deduplication
- Actual DagNode inputs are named reference tuples and the dataclass is frozen. Resolve dependencies in the validated graph, hash topologically, preserve argument roles/primitive identities and update cache consumers; do not treat input references as child objects or mutate the frozen hash property.

### Integration Status
- DAG is **already integrated** via `strategy_runtime._compute_dag_series()` and `from_yaml_sections()`
- `node_cache.py` wired in `composition.py`
- **Only bug fixes needed — no new integration work**

---

## 5. Rankings: Strategy Pattern Abstraction

### Retained Strategies and Retirement
- Delete [benchmark_relative_momentum.yml](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/strategies/benchmark_relative_momentum.yml)
- Delete [early_momentum.yml](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/strategies/early_momentum.yml)
- Remove references from: `_indicator_set()`, pipeline default strategies, worker handlers
- Retain **Momentum strategy** (factor_score) and **Positional trend following strategy** (event_signal), including runtime, action generation, replay and test coverage.
- Remove only benchmark-relative momentum and early momentum active definitions/wiring/code/tests after auditing shared dependencies; retire persisted revisions explicitly. Remove their historical backtesting data/results as well. Inventory database runs, artifacts/reports, strategy-specific output directories and UI/catalog references; delete only outputs attributable to these removed strategies. Retain shared market history and both retained strategies' outputs.
- Use descriptive retained-strategy names throughout UI, docs, configuration, APIs, jobs, tools, and tests. Use canonical IDs `momentum` and `positional_trend_following`; remove numbered aliases and outputs. Start from a fresh database and regenerate artifacts as needed. No previous strategy, database, or artifact identity must be preserved.

### Ranking Patterns (Derived from `kind`)
- `factor_score` → **FactorPercentileRanking**: indicators → percentiles → weighted score → rank
- `event_signal` → **DirectSignalRanking**: indicators → signal rules → rank by metrics

### Separate Percentile Storage

**New table:**
```sql
CREATE TABLE research_percentiles (
    percentile_snapshot_id TEXT NOT NULL,
    strategy_revision_id TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    raw_value REAL NOT NULL,
    percentile_value REAL NOT NULL,
    PRIMARY KEY(percentile_snapshot_id, instrument_id, factor_name)
);
```

**3-stage pipeline:**
- **Stage A: Indicators** → compute raw values (cached in `indicator_node_cache`)
- **Stage B: Percentiles** → cross-sectional ranking. Recalculated only when indicators or universe change
- **Stage C: Scores + Rankings** → apply weights, compute composite score, rank. Recalculated when weights change OR percentiles change

**Cache invalidation:**
- Weights-only change → skip A & B, rerun C
- Indicator definition/code change → rerun A, B, C
- Corporate-action history correction → rebuild affected indicator caches; preserve published historical percentiles/rankings by user decision. Fresh dates compute from refreshed indicators.
- Corporate-action corrections rebuild indicator history/cache, including ADX and other strategy indicators. Preserve historical percentile snapshots and higher-stage published factor scores/rankings even when recomputation would differ. Saved backtest results are immutable and never rewritten by refresh; newly requested runs use their declared input revisions.
- Cache validity includes market input revision and indicator implementation identity, not just node hash/instrument/date.

### Lineage Block on All Research Artifacts
Every ranking/research artifact includes:
```json
{
  "strategy_revision_id": "abc-123",
  "indicator_code_hash": "sha256 of indicator source files",
  "universe_snapshot_id": "snap-2026-09-28",
  "market_data_range": ["2024-01-01", "2026-09-27"],
  "computed_at": "2026-09-28T09:30:00Z"
}
```

### Strategy Versioning
- Already exists via `strategy_revisions` table — no changes needed
- Rankings reference `strategy_revision_id` — browseable by revision

---

## 6. Portfolio Management

### Kite Portfolio Data Reader (Read-Only)
```python
class KitePortfolioReader:
    """Read-only broker portfolio data. Uses portfolio API key."""
    def holdings(self) -> list[dict]: ...
    def positions(self) -> list[dict]: ...
    def orders(self) -> list[dict]: ...
    def order_trades(self, order_id: str) -> list[dict]: ...
    def margins(self) -> dict: ...
    def profile(self) -> dict: ...
```
- Each portfolio account uses its own Kite credentials/session; market-data credentials remain separate.
- Carry selected account through holdings, positions, orders, trades, margins, action approval, execution and reconciliation. No silent first-account fallback for writes.
- Keep broker session identity distinct from each managed strategy ledger identity. Link them through the strategy portfolio, creating parent and link rows atomically in valid foreign-key order; migrate existing accounts/credentials without deleting events. Store account API keys/secrets/tokens in local SQLite and redact them from responses/logs. Verify database files and WAL/SHM/journal sidecars are excluded from Git; do not commit credentials. Keep account-specific expired-session recovery.
- Portfolio sync explicitly carries the operated strategy ID. Each strategy has separate managed cash and accounting identity. Automatic switching/simultaneous operation is backlog scope.
- Day 0: fetch broker holdings and ask the user which stocks, if any, to import into the selected strategy. Import the entire broker quantity of each selected holding; unrelated holdings stay excluded. Choosing none establishes an empty starting holdings portfolio.
- Derive and persist starting stops for imported holdings using the selected strategy's existing stop model; proposals then act on those stops.
- The user supplies acquisition dates for selected holdings when unavailable from broker APIs. Kite holdings expose current quantity and average price but do not document original acquisition dates; never substitute the holdings authorisation date for purchase date.
- Preserve day-0 mappings; subsequent strategy-generated orders/fills establish their own ownership. Do not repeat the stock-selection prompt on ordinary later syncs. Unrelated broker holdings remain excluded.
- Read-only tools callable without approval
- Note: Kite updates holdings automatically on corporate actions (split/bonus adjusts quantity and avg price)

### RiskGuard (Pre-Trade Checks)
```python
class RiskGuard:
    def validate(self, order, portfolio_state, strategy_policy, portfolio_limits) -> None:
        """Enforce existing strategy policy and independent configured portfolio limits."""
```
- Checked in `KiteExecutionGateway.submit_order()` BEFORE Kite API call
- All violations logged with full context
- Risk limits stored in config, not hardcoded
- Approved next-session exits are submitted to Kite with variety=amo, through the selected account and normal approval/idempotency checks. Store broker order ID/variety and reconcile actual fills; AMO acceptance is not a completed fill.
- Backtest next-open prices are simulation inputs; live execution records broker-reported prices/times. Preserve strategy stop-trigger behavior during this integration.

### Approved Next-Session Exits and Existing Protective Stops
```
ActionJobs.generate() → proposal → UI display → user "Approve"
→ KiteExecutionGateway.submit_order() [RiskGuard checked here; AMO for approved next-session exits]
→ fill reconciliation → Ledger update
```

### New Job: `portfolio.reconcile-broker`
- Run reconciliation on every manual pipeline invocation with explicit portfolio account/strategy context. Reconcile only managed holdings and relevant orders; the ranking stages still compute both strategies.
- Automatically reconcile verified fills and recognized split/bonus quantity/cost adjustments idempotently. Unverified discrepancies require review before ledger correction; record source/before/after values and provenance.
- Import day-0 selected holdings as explicit opening/import events with user-supplied acquisition dates; do not invent historical fills. Use actual ledger projection objects.
- Idempotently record verified completed-order fills; preserve append-only accounting history. Define broker corporate-action quantity/cost reconciliation without treating adjustments as trades.

---

## 7. Capital Management
- **Live portfolio**: Ignore taxes and transaction costs entirely
- **Backtesting**: Keep existing 0.5% (`round_trip_cost_bps: 50`)
- Extend risk management while preserving those cost decisions.
- Enforce RiskGuard immediately before every broker submission, including manual orders, retries and stale approvals, using selected-account state.
- Preserve each strategy's existing risk calculation, sizing, initial stop and trailing-stop behavior. Independent portfolio-level safeguards apply globally and do not replace either strategy's formulas.
- Global configurable checks cover order value, daily loss, concentration/sector exposure, position count, holding period, cash reserve, portfolio heat and drawdown. Their exposure/loss/position scope is system-managed holdings and allocated strategy cash only; unrelated broker holdings are excluded. Broker buying-power validation still uses the selected broker account. Revalidate at proposal/submission boundaries.
- Stop-loss and compulsory universe-exit SELLs override the global minimum holding period. BUY restrictions must not suppress these protective/compulsory exits.
- Each strategy uses its separate configurable cash allocation. Initial cash is a setup input, not a fixed strategy default. Record initial funding and every subsequent deposit/withdrawal with strategy/account identity, amount, effective date/time, reason and idempotency.
- Returns include imported holdings using original acquisition cost and user-supplied purchase dates, alongside later real deposits/withdrawals. Preserve existing unrealized gains/losses; do not reset their return basis to setup-day price or count carried gains as today's profit.
- Keep setup market valuation as an audit/initial-balance snapshot. For lifetime return/XIRR inputs, imported purchase basis/dates supply historical performance provenance; do not also count setup market value as a second contribution for those same holdings, and do not manufacture broker fill records.
- Persist setup valuation, original cost/date, import identity and later dated capital flows distinctly. Repeated imports cannot duplicate cash or return inputs. Day P&L measures the day's market movement rather than assigning all carried returns to today. Portfolio return/XIRR includes the imported purchase history; a setup-only return view must not replace that requested primary view. Revalidate strategy allocation, broker buying power and global safeguards before submission.
- Use Decimal/Money and applicable existing limits consistently, validating prices, quantities, allocated cash and policy inputs. Never force a one-share order above the applicable budget.
- Buy restrictions must preserve required SELL proposals and existing strategy exit behavior.

---

## 8. UI: Material Design — Carbon Emerald Theme

### Design System: Carbon Emerald (Light + Dark Toggle)
| Token | Dark Mode | Light Mode |
|-------|-----------|------------|
| Background | `#111111` | `#F3F4F6` |
| Sidebar | `#1A1A1A` | `#FFFFFF` |
| Cards | `#1E1E1E` | `#FFFFFF` |
| Borders | `#2E2E2E` | `#E5E7EB` |
| Card shadow | `rgba(0,0,0,0.5)` | `0 1px 3px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04)` |
| Accent | `#10B981` emerald | `#059669` forest green |
| Positive P&L | `#10B981` | `#059669` |
| Negative P&L | `#EF4444` | `#DC2626` |
| Text primary | `#FAFAFA` | `#111827` |
| Text secondary | `#A1A1A1` | `#6B7280` |

- Font: **Inter** (Google Fonts)
- Icons: **Material Icons Round**
- Sidebar: 64px icon-only (compact)
- Cards float with elevation (light gray bg + white cards in light mode)
- Store theme preference in localStorage

### Feature Mapping: Old Dashboard → New UI

#### From `templates/dashboard.html` (Old Jinja2 Dashboard — DEAD CODE)
| Old Feature | New Location | Enhancement |
|-------------|-------------|-------------|
| **Index ticker bar** (scrolling marquee of NIFTY 50, VIX, etc.) | **Home `/`** — top of page | Material card carousel (not marquee), shows each index as a card with LTP, change%, mini sparkline |
| **Pipeline tab** (step toggles, sync instruments, run pipeline, console) | **`/pipeline`** page | Same toggles + progress bars, remove YFinance batch controls (dead), add SSE-based live console |
| **Portfolio tab** — Summary cards (10 metrics), Equity curve chart, Drawdown chart, Holdings table, Live P&L toggle, Trade journal, Rankings top 20, Portfolio distribution pie | **`/` (Home)** page | All moved to home. Summary cards enhanced with Material Design. Charts kept (Chart.js). Holdings table with sortable columns. Live streaming toggle preserved |
| **Actions tab** — Generate actions, approve/reject/process, cash projections, manual buy/sell/capital event modals | **`/actions`** page | Same functionality, enhanced modals with Material Design, keep cash projection panel |
| **Backtest tab** — Replay parameters, saved runs, fill report | **`/backtest`** page | Same, cleaner form layout |
| **Config tab** — Strategy YAML editor | **`/settings`** page | Merge with Kite auth settings |
| **Approve/Buy/Sell/Capital Event modals** | Keep all modals | Restyle with Material Design |

#### From `dashboard_web.py` ( Routes — ACTIVE)
| Old Feature | New Location | Enhancement |
|-------------|-------------|-------------|
| `/app` — Rankings table, Index quotes table, Job inspector, Worker control, Portfolio account lookup, Action proposals | Distribute: Rankings→`/rankings`, Quotes→home carousel, Worker→`/pipeline`, Portfolio→home | Remove as standalone page |
| `/actions` — Proposal review, manual intent builder | **`/actions`** page | Merge with old Actions tab functionality |
| `/backtest` — Replay form, saved runs | **`/backtest`** page | Merge with old Backtest tab |
| `/portfolio` — Holdings, equity curve, trade journal, live P&L | **`/` (Home)** page | Primary view |

### Index Carousel on Home Page
Replace the old scrolling ticker bar marquee with a **Material card carousel**:
```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ NIFTY 50 │ │NIFTY 500 │ │ NEXT 50  │ │MIDCAP 150│ │SMLCAP 250│
│ 24,150   │ │ 21,840   │ │ 68,320   │ │ 19,450   │ │ 16,280   │
│ ▲ +1.2%  │ │ ▲ +0.8%  │ │ ▼ -0.3%  │ │ ▲ +1.5%  │ │ ▲ +0.9%  │
│ ╱╲╱╲─╱╲  │ │ ╱──╲╱╲─  │ │ ╲╱╲──╱   │ │ ╱╱──╲╱   │ │ ╱──╱╲─   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
                        ◀  ● ● ○ ● ●  ▶
```
- Each card: Index name, LTP, change %, mini sparkline (last 30 days from historical bars)
- Auto-scroll with pause-on-hover
- Data: Live from websocket + historical from `market_bars` for sparkline

### Page Structure (Final)
| Route | Page | Content |
|-------|------|---------|
| `/` | **My Portfolio** (Home) | Index carousel, summary cards (value, invested, unrealized, realized, cash, abs return, XIRR, risk), equity curve + drawdown charts, holdings table (with live streaming toggle), trade journal, portfolio distribution pie, top 20 rankings |
| `/actions` | Actions | Generate/approve/reject/process proposals, manual buy/sell, capital events, cash projections |
| `/pipeline` | Pipeline | Step toggles, run pipeline, worker control, job inspector, SSE console |
| `/rankings` | Rankings | Momentum strategy / Positional trend following strategy select, week select, full rankings table, factor breakdown or event metrics |
| `/universe` | Universe | NIFTY 500 members, additions/removals history, snapshot diffs |
| `/backtest` | Backtesting | Replay parameters, saved runs, fill reports |
| `/settings` | Settings | Kite auth, strategy YAML editor, theme toggle, risk limits config |

### UI Integration Requirements
- Replace run.py's root redirect when serving `/`; define legacy `/app` and `/portfolio` redirects.
- Inventory actual APIs/payloads first. Existing portfolio endpoints use account paths and SSE; do not assume new routes or WebSocket contracts exist.
- Preserve both retained strategies' rankings/actions/replay under descriptive names.
- Complete universe history/diff/refresh, settings/YAML/risk/auth, logs/quality and index-history APIs/scripts.
- Carousel includes last-30-session sparklines, auto-scroll/pause-on-hover and freshness/empty/error states.
- Carry selected account through widgets, actions/modals and streams; clean up/reconnect SSE and handle failed responses.
- Include responsive/keyboard-accessible UI and functional route/API/browser checks.

### Architecture Change
- **DELETE** `templates/dashboard.html` — this old Jinja2 template is dead code (not served by any route)
- **DELETE** `static/css/dashboard.css` — old styling
- **DELETE** `static/js/index_ticker.js` — old ticker (replaced by carousel)
- **REWRITE** `dashboard_web.py` — currently has 1026 lines of inline HTML strings. Refactor to:
  - `templates/base.html` — shared layout (sidebar, theme toggle, head)
  - `templates/home.html` — portfolio + index carousel
  - `templates/actions.html` — actions page
  - `templates/pipeline.html` — pipeline page
  - `templates/rankings.html` — rankings page
  - `templates/universe.html` — universe page
  - `templates/backtest.html` — backtest page
  - `templates/settings.html` — settings page
  - `static/css/carbon-emerald.css` — theme CSS variables + Material Design tokens
  - `static/js/` — modular JS files per page

### Dead Code Cleanup (UI + General)
| File | Reason |
|------|--------|
| `templates/dashboard.html` (801 lines) | Old Jinja2 template, not served by any route, duplicates `dashboard_web.py` inline HTML |
| `static/css/dashboard.css` | Styles for dead `dashboard.html` |
| `static/js/index_ticker.js` | Old scrolling ticker, replaced by carousel |
| `static/codebase_flowcharts.html` | Development reference, not user-facing |
| `dashboard_web.py` inline HTML | Refactor to Jinja2 templates (move 1026 lines of f-strings to proper templates) |

---

## 9. Logging & Data Quality

### Structured Job Logging
```python
context.emit_progress("Processing RELIANCE", {
    "current": 42, "total": 500, "percent": 8.4
})
```

### Per-Module Loggers
```python
logger = logging.getLogger("screener.universe")
logger = logging.getLogger("screener.market_data")
logger = logging.getLogger("screener.indicators")
logger = logging.getLogger("screener.rankings")
logger = logging.getLogger("screener.portfolio")
logger = logging.getLogger("screener.corporate_actions")
```

### Data Quality Validation (Light)
Since Kite is a reliable source, keep validation lightweight:
```sql
CREATE TABLE data_quality_events (
    event_id INTEGER PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    check_type TEXT NOT NULL,     -- 'OHLC_INVALID', 'GAP', 'VOLUME_ZERO', 'CORP_ACTION_MISMATCH'
    severity TEXT NOT NULL,       -- 'WARNING', 'ERROR'
    detail TEXT NOT NULL,
    detected_at TEXT NOT NULL
);
```

Checks:
- H >= max(O,C) and L <= min(O,C)
- Absolute close-to-close gap > 15% without explanatory corporate-action data → flag, compare/refetch Kite history and retain diagnostics. Keep the stock included in rankings and permit BUY proposals subject to normal strategy/global checks. When refreshed Kite data resolves the relevant ex-date discrepancy under this configured criterion, complete monitoring automatically and retain the audit trail. Never complete monitoring merely because a later unrelated session has a normal gap.
- All universe stocks have bar for today (after market close)
- Volume == 0 for > 5 sessions → warning

### Structured Progress and Quality Completion
- Persist worker job events with job/stage/current/total/context and redacted failures; ordinary module loggers alone are insufficient.
- Complete OHLC, missing last-completed-session bars, prolonged zero-volume, unexplained-gap and corporate-action-mismatch checks. Use trading sessions/close state rather than calendar-today completeness.
- Emit persisted quality/anomaly events with affected instrument, source values, timestamps and refresh attempts.

### UI Log Viewer
- `/logs` page showing recent job events with filtering
- SSE-based real-time progress (existing pattern in `dashboard_web.py`)

---

## Files to Delete

| File/Directory | Reason |
|---------------|--------|
| `ind_nifty500list.csv` (project root) | Replaced by DB universe snapshots |
| `data/reference/nifty500/` | Runtime reads replaced by DB snapshots |
| `data/imports/NSE.csv` | Replaced by NIFTY 500 CSV + kite.instruments() |
| `data/imports/BSE.csv` | BSE removed entirely |
| `strategies/benchmark_relative_momentum.yml` | Strategy 2 dropped |
| `strategies/early_momentum.yml` | Strategy 3 dropped |
| `templates/dashboard.html` (801 lines) | Dead code — old Jinja2 template not served by any route |
| `static/css/dashboard.css` | Dead code — styles for dead `dashboard.html` |
| `static/js/index_ticker.js` | Dead code — old scrolling ticker, replaced by carousel |
| `static/codebase_flowcharts.html` | Dead code — dev reference, not user-facing |

---

## Code to Remove/Modify

| Location | Change |
|----------|--------|
| [market_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/market_jobs.py) `sync_bse_instruments()` | Delete entirely |
| [market_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/market_jobs.py) `BSE_INDEX_SYMBOLS` | Delete |
| [market_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/market_jobs.py) L79 `SERIES == "EQ"` filter | Remove filter |
| [market_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/market_jobs.py) `NSE_INDEX_SYMBOLS` | Update to new set |
| [composition.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/composition.py) `bse_csv_path` | Remove parameter |
| [composition.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/composition.py) `sync-bse-instruments` handler | Remove |
| [positional_trend_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/positional_trend_jobs.py) BSE fallback | Remove |
| [research.py](../src/gates/workflows/research.py) `_indicator_set()` | Remove retired benchmark-relative momentum wiring; preserve both retained strategies |
| [pipeline_jobs.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/pipeline_jobs.py) L85 default strategies | Use migrated names `momentum` and `positional_trend_following` throughout pipeline strategy selection |
| [run.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/run.py) L65 `bse_csv_path=` | Remove |
| [dag.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/domains/indicators/dag.py) `APPROVED_OPERATIONS` | Fix unimplemented ops |
| [strategy_definitions.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/gates/strategy_definitions.py) `_OPERATIONS` | Import from `dag.py` |
| [corporate_actions.py](file:///c:/Users/harsh/Documents/GitHub/stocks_screener/src/application/corporate_actions.py) | Rewrite: NSE API detect → Kite re-fetch flow |

---

## Execution Order

| Phase | Items | Dependencies |
|-------|-------|-------------|
| **Phase 1** | DAG bug fixes (§4), Logging (§9) | None — foundational |
| **Phase 2** | Universe (§1), Market Data (§2), BSE removal | None — data layer |
| **Phase 3** | Corporate Actions (§3), indicator cache rebuild | Phase 1, Phase 2 |
| **Phase 4** | Rankings refactor (§5) | Phase 1, Phase 2 |
| **Phase 5** | Mapped portfolio import, accounts and execution (§6) | Phase 2, Phase 4 |
| **Phase 6** | Submission RiskGuard (§6), capital/risk (§7) | Phase 5 |
| **Phase 7** | UI overhaul (§8) | All above |

## Confirmed Day-0 and Strategy Rules
- Retain Momentum strategy (`momentum`) and Positional trend following strategy (`positional_trend_following`); migrate existing numbered references.
- Portfolio sync explicitly identifies the operated strategy; rankings run for both. Separate managed cash is maintained for each strategy.
- Day-0 holdings selection is explicit and optional. No selected holdings means an empty starting holdings portfolio.
- User-supplied acquisition dates supplement broker holdings data; preserve each strategy's existing risk/sizing/stop/trailing rules.
- Same-day universe reruns reuse the first snapshot and continue to the next stage.
- Corporate-action history changes rebuild indicators only; historical percentiles and higher-stage scores/rankings remain stored as published.
- Remove benchmark-relative momentum and early momentum historical backtesting data during their planned retirement. No deletion is performed during this documentation review.

This document records confirmed scope. Implementation remains on hold during planning review.

## Backlog: Strategy Switching and Simultaneous Operation
Automatic strategy switching, cross-strategy portfolio transitions and simultaneous-strategy orchestration are outside this implementation scope. Portfolio sync receives the strategy explicitly; both ranking paths continue to run. Separate strategy cash and data identity are retained so future orchestration can build on them.

## Configuration Contract
Initial capital and operating-strategy selection are user inputs. No launch-specific cash amount is added as a strategy default. Strategy parameters and global portfolio safeguards remain configurable; configuration changes are validated and recorded with action/valuation lineage. Preserve each strategy's existing calculation model.


## Confirmed Exit, Risk and Import Accounting Rules
- Global portfolio safeguards apply only to system-managed holdings/cash. Stop-loss and universe-exit SELLs override minimum holding period.
- Anomaly flags do not remove stocks or block BUY proposals by themselves; resolved ex-date discrepancies complete monitoring automatically.
- Compulsory universe exits use next-trading-session open and one extra exit-only session of price data. Preserve decision/execution dates separately to avoid look-ahead.
- Imported holdings retain original cost/acquisition dates and contribute their existing returns to portfolio return/XIRR. Setup valuation is recorded separately, without double-counting an opening contribution or treating carried gains as today's profit. Later funding is an external capital event, not a return.


## Backlog: Missing Next-Session Opening Price
Special handling for a suspended stock or unavailable next-session opening price is deferred by user decision. The current supported replay path expects next-session exit data. Do not synthesize a fill/price or add a next-available-session fallback in this scope; record unavailable data as a validation failure. This deferral is separate from automatic strategy-switching backlog scope.

## AMO and Imported Performance Acceptance
Approved next-session exits submit as AMOs and reconcile actual broker fills idempotently. Preserve approval/account ownership and portfolio guards. Imported holdings contribute to portfolio returns/XIRR from original cost/acquisition dates, without treating setup import as a real trade or double-counting setup market value as fresh funding.


## Final Stop-Execution Decision: Choice A
- Preserve each retained strategy's existing protective/hard-stop execution during the trading session, including its current trigger, gap and fill rules. A protective stop is not delayed until tomorrow merely because AMO is supported.
- Exits decided after daily analysis and compulsory universe exclusions use approved AMO for the next trading session; replay uses that session's open.
- Stop-loss and universe-exit SELLs override minimum holding period. Preserve existing disabled midweek-next-open behavior rather than reintroducing it during the refactor.
- Separate decision/session/fill provenance and reconcile actual live executions. Keep configured prices/stops/strategy parameters editable without replacing calculation algorithms.

## Implementation Task Ownership
| Master requirement | Integrated phase tasks |
|--------------------|------------------------|
| DAG operations, graph hashing, cache identity | Phase 1 tasks 1.1–1.5 |
| Structured worker progress, logging, quality and readback | Phase 1 tasks 1.6–1.10; Phase 7 task 7.15 |
| Immutable daily universe and NSE/series/benchmark data | Phase 2 tasks 2.1–2.10 |
| Exclusion refresh exception, proposals and as-of replay | Phase 2 tasks 2.11–2.14; Phase 4 task 4.11 |
| Corporate detection, retry/verification, anomaly monitoring | Phase 3 tasks 3.1–3.6 |
| Indicator rebuild with frozen historical outputs | Phase 3 tasks 3.7–3.8; Phase 4 tasks 4.7–4.10 |
| Named migration and removed-strategy backtest cleanup | Phase 4 tasks 4.1–4.4 |
| Ranking patterns, percentile persistence/reuse, both branches | Phase 4 tasks 4.5–4.10 |
| Local SQLite auth, day-0 import, derived stops | Phase 5 tasks 5.1–5.6 |
| Verified reconciliation, review and explicit portfolio sync | Phase 5 tasks 5.7–5.10 |
| Account-aware AMO and actual normalized fills | Phase 5 tasks 5.11–5.13 |
| Separate cash, imported return history, capital events | Phase 5 task 5.14; Phase 6 tasks 6.7–6.9 |
| Existing strategy rules plus managed global guards and Choice A | Phase 6 tasks 6.1–6.6 |
| Carbon Emerald, all pages, APIs/streams and functional verification | Phase 7 tasks 7.1–7.19 |

Every phase file now contains integrated numbered steps, concrete existing/new file targets and task acceptance checks. Supplemental decision notes have been consolidated into those tasks. Strategy-switching/simultaneous operation and missing-next-open fallback remain explicitly deferred backlog scope. No product questions are embedded in these implementation tasks.

## Approval Gate
Planning is complete for the agreed scope. No application code, migration, data cleanup, broker submission or live arming is authorized by this document revision. Implementation starts only after the user explicitly approves it; follow the integrated phase sequence and record exit evidence at each phase.
