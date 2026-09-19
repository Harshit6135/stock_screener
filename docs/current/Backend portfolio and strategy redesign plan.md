# Backend Portfolio and Strategy Redesign Plan

## Document status

- Status: planning only
- Primary priority: backend correctness, extensibility, reproducibility, and clean boundaries
- UI redesign: intentionally deferred until the backend contracts are stable
- Existing documentation: must not be modified as part of creating this plan
- Current implementation: remains unchanged until an implementation phase is explicitly approved

## 1. Purpose

This plan consolidates the requested backend changes:

1. Remove the paper-versus-real portfolio distinction. There is one real portfolio.
2. Treat both manually recorded transactions and Kite-confirmed transactions as real portfolio activity.
3. Disable the local operator-token authentication layer while retaining Kite authentication.
4. Preserve appropriate execution-safety mechanisms even though they are not authentication.
5. Replace hardcoded Python strategy implementations with versioned, declarative strategy definitions.
6. Allow a new strategy using existing capabilities to be added without changing Python code.
7. Use Pandas TA for supported standard indicators.
8. Require manual Python implementation only when an indicator or operation is not available through the approved Pandas TA adapter or existing custom registry.
9. Generate historical features, scores, and rankings automatically for a new strategy revision.
10. Publish a future UI page showing which indicators Pandas TA can handle and which ones require manual work.
11. Keep the dashboard refresh and index-chart aesthetic improvements as a separate pending UI item.

## 2. Confirmed product decisions

### 2.1 Portfolio semantics

- There is no paper-trading portfolio.
- The default authoritative account will be called `portfolio` unless a different stable identifier is selected before migration.
- A manually entered transaction represents an actual transaction supplied by the user.
- A Kite fill represents an actual broker-confirmed transaction.
- Manual and Kite transactions feed the same ledger and portfolio projection.
- Backtesting remains simulated and isolated. It must never write to the real portfolio ledger.
- Transaction source is provenance, not portfolio mode. Suggested values are `MANUAL`, `KITE`, `LEGACY_IMPORT`, `CORPORATE_ACTION`, and `ADJUSTMENT`.

### 2.2 Authentication and safety

- The application is local-only for now.
- No application-level operator authentication is required.
- Kite login and access-token exchange remain active.
- The existing operator-token implementation should initially be retained but made inactive, as requested.
- Loopback-only binding remains mandatory by default.
- Idempotency, ledger-version checks, broker reconciliation, execution controls, credential redaction, and transaction validation remain. These are safety and correctness mechanisms, not authentication.

### 2.3 Strategy authoring

- A strategy is data, not a Python module.
- YAML is the human-readable import/export and seed format.
- The database is the authoritative runtime store for immutable strategy revisions.
- The backend stores both original YAML and canonical normalized JSON.
- A strategy may use:
  - Approved Pandas TA indicators.
  - Registered custom indicators.
  - Approved declarative transformations and scoring operations.
- Arbitrary Python, imports, scripts, or `eval` expressions must never be accepted from YAML.

## 3. Current-state problems that must be addressed

### 3.1 Two strategy systems exist but only one is used in production

The repository already has generic domain types under `src/indicators` and `src/strategies`, but the production research flow still directly imports and branches between `research_strategy1.py` and `research_strategy2.py`.

Consequences:

- A new strategy requires code changes.
- Worker handlers and job names must be added manually.
- Backtests, actions, APIs, and UI selectors all contain hardcoded strategy IDs.
- The generic strategy abstractions are not the actual production execution path.

### 3.2 Current strategy Python files mix multiple responsibilities

The current strategy files combine:

- Raw technical indicators.
- Rolling-window calculations.
- Benchmark alignment.
- Derived indicators.
- Piecewise transformations.
- Cross-sectional normalization.
- Eligibility rules.
- Penalties.
- Factor construction.
- Strategy-specific output formatting.

Simply moving factor weights into YAML would leave most of the strategy hardcoded in Python.

### 3.3 Existing indicator cache can collide

The current market-indicator cache is keyed primarily by instrument and date, while the stored value can depend on strategy-specific formulas. Different strategies or revisions can therefore overwrite or incorrectly reuse each other's values.

### 3.4 Research projections are not revision-safe

Daily scores and weekly rankings are keyed by strategy ID and date. Recalculating a strategy after changing its definition can replace the current projection for that strategy/date and obscure which definition produced a result.

### 3.5 Pipeline orchestration is hardcoded

Current jobs include strategy-specific names such as:

- `research.calculate-strategy1-day`
- `research.calculate-strategy2-day`
- `research.rank-strategy1-week`
- `research.rank-strategy2-week`

The pipeline also assumes weekdays and Friday rankings in places. This does not correctly model exchange holidays or the final trading session of a shortened week.

### 3.6 Research calculations can fetch external data

Benchmark fallback can occur during strategy calculation. This weakens reproducibility because the same strategy calculation can observe different external data on a later run.

All provider access must occur in the market-data stage. Research must consume frozen, identified input snapshots.

### 3.7 Converting paper processing directly into real processing is unsafe

The current action flow can process a paper proposal against a completed historical bar and write fills into the ledger. Renaming that behavior to real portfolio processing would create fictional real transactions.

A real portfolio fill must be based on:

- A confirmed Kite trade/fill, or
- Complete manually supplied execution facts.

A strategy proposal is not a fill.

### 3.8 Commenting operator-token checks everywhere conflicts with clean-code goals

Operator-token checks and headers are spread through many blueprints, tests, scripts, and dashboard functions. Leaving large commented blocks in every file would make the code harder to maintain.

The transition should preserve the old implementation in one clearly marked inactive location and disable enforcement centrally. Repeated route and UI plumbing can then be retired in a controlled cleanup after the local-only behavior is verified.

## 4. Target backend architecture

```text
Future Strategy UI / YAML Import
               |
               v
      Strategy Definition API
               |
      validate + canonicalize
               |
               v
    Immutable Strategy Revision
               |
               v
       Strategy DAG Compiler
               |
       dependency resolution
               |
       +-------+--------+
       |                |
       v                v
 Indicator Registry   Data Planner
       |                |
       |        market/benchmark snapshots
       +-------+--------+
               |
               v
      Generic Research Pipeline
               |
     features -> scores -> rankings
               |
       +-------+--------+
       |                |
       v                v
   Backtesting     Portfolio proposals
                           |
                 manual execution or Kite
                           |
                           v
                  Real portfolio ledger
```

## 5. Strategy definition and storage

### 5.1 YAML versus database

Use a hybrid model:

- YAML is the readable strategy format presented to users and suitable for import, export, review, seed files, and Git.
- The database stores immutable strategy identities, revisions, lifecycle state, effective dates, and relationships to pipeline runs.
- Canonical JSON generated from parsed YAML is used for hashing and execution.
- The artifact store retains immutable published copies and lineage.

The database is the runtime source of truth because the UI needs revision queries, activation history, status, comparison, and pipeline relationships. YAML files alone do not provide these safely.

### 5.2 Proposed strategy persistence

`strategy_definitions`

- `strategy_id`
- `name`
- `description`
- `created_at`

`strategy_revisions`

- `revision_id`
- `strategy_id`
- `schema_version`
- `semantic_version`
- `source_yaml`
- `canonical_json`
- `definition_hash`
- `compiler_version`
- `status`
- `created_at`
- `validated_at`
- `activated_at`
- `retired_at`

`strategy_activation_schedule`

- `strategy_id`
- `revision_id`
- `effective_from`
- `effective_to`

`strategy_dependencies`

- `revision_id`
- `node_id`
- `provider`
- `implementation_key`
- `implementation_version`
- `configuration_hash`

### 5.3 Revision lifecycle

Recommended lifecycle:

```text
DRAFT -> VALIDATED -> READY -> ACTIVE -> RETIRED
```

- `DRAFT`: may be incomplete and may reference unavailable indicators.
- `VALIDATED`: schema, references, parameters, and graph are valid.
- `READY`: required validation/backfill checks have completed successfully.
- `ACTIVE`: eligible for scheduled rankings and portfolio proposals.
- `RETIRED`: retained for history but not used for new scheduled work.

The `PAPER` strategy status should be removed. Backtest results and readiness are recorded separately rather than encoded as a trading mode.

### 5.4 Strategy YAML scope

A definition must support:

- Identity and version.
- Universe and exchange selection.
- Market-data dependencies.
- Benchmark dependencies.
- Indicator nodes.
- Derived transformations.
- Cross-sectional calculations.
- Factor construction.
- Eligibility and exclusion rules.
- Penalties and score modifiers.
- Ranking frequency and aggregation.
- Tie policy.
- Missing-data behavior.
- Portfolio-policy reference.

Example:

```yaml
schema_version: 1

strategy:
  id: momentum_quality
  name: Momentum Quality
  version: 1.0.0

universe:
  source: nifty_500
  exchanges: [NSE]

data_dependencies:
  benchmark: NIFTY 500

indicators:
  - id: ema_50
    provider: pandas_ta
    function: ema
    inputs:
      close: close
    parameters:
      length: 50
    output: EMA_50

  - id: rsi_14
    provider: pandas_ta
    function: rsi
    inputs:
      close: close
    parameters:
      length: 14
    output: RSI_14

  - id: relative_strength
    provider: custom
    function: mansfield_relative_strength
    inputs:
      close: close
      benchmark_close: benchmark.close
    parameters:
      lookback: 200

factors:
  momentum:
    operation: weighted_sum
    terms:
      - weight: 0.6
        value:
          operation: percentile
          input: relative_strength
          direction: high
      - weight: 0.4
        value:
          operation: scale
          input: rsi_14
          minimum: 40
          maximum: 80
          output_minimum: 0
          output_maximum: 100

eligibility:
  operation: all
  conditions:
    - operation: greater_than
      left: close
      right: ema_50
    - operation: greater_than
      left: avg_turnover_20
      right: 500000000

score:
  operation: weighted_sum
  terms:
    - factor: momentum
      weight: 1.0

ranking:
  frequency: weekly
  session: last_trading_session
  aggregation: weekly_mean
  tie_policy: score_desc_symbol_asc

portfolio_policy:
  max_positions: 15
  max_concentration: 0.25
  stop_loss_multiplier: 2
```

### 5.5 Safe expression model

YAML must contain a structured operation tree, never an executable expression string.

Approved operations should initially include:

- Arithmetic: add, subtract, multiply, divide, ratio, logarithm.
- Series operations: shift, rolling mean, rolling standard deviation, rolling correlation.
- Transformations: clip, scale, piecewise linear, default, conditional.
- Boolean operations: all, any, not, comparisons.
- Cross-sectional operations: percentile, rank, z-score, sector z-score.
- Composition: weighted sum and modifier.

Unknown operations fail validation with a structured error.

## 6. Unified indicator system

### 6.1 Indicator provider types

All indicators use one execution contract regardless of implementation source:

```text
PANDAS_TA -> approved Pandas TA adapter
CUSTOM    -> registered project-owned Python function
BUILT_IN  -> small foundational operation maintained by the engine
```

Each indicator registration must describe:

- Stable implementation key.
- Provider.
- Implementation and package version.
- Category.
- Required input series.
- Parameter schema, defaults, bounds, and types.
- Output columns and types.
- Warm-up bars.
- Calculation scope.
- Look-ahead characteristics.
- Missing-value behavior.
- Support and test status.

### 6.2 Pandas TA adapter

Pandas TA should be the primary implementation for standard technical indicators that it supports.

The adapter must:

1. Map canonical OHLCV names to the function's expected arguments.
2. Validate parameters before invocation.
3. Support both Series and DataFrame results.
4. Require explicit output selection for multi-output indicators.
5. Normalize output names and numerical types.
6. Reject infinite results.
7. Preserve expected warm-up nulls rather than silently converting them.
8. Disable or reject look-ahead modes for research and backtesting.
9. Record the Pandas TA package version and adapter version in lineage.
10. Produce deterministic configuration hashes.
11. Return structured errors instead of leaking library exceptions into job state.

Standard candidates include EMA, SMA, RSI, ROC, ATR, PPO/MACD, Bollinger Bands, ADX, and other catalogued studies. Support is not assumed merely because a function exists; each function receives an explicit support status after testing.

### 6.3 Custom indicators

A custom implementation is required when:

- Pandas TA does not provide the calculation.
- The required formula intentionally differs from Pandas TA.
- Benchmark-relative or cross-sectional behavior is project-specific.
- The Pandas TA implementation cannot meet no-look-ahead or reproducibility requirements.
- Output parity with the accepted strategy cannot be achieved through parameters or a small compatibility adapter.

Custom indicators must use the same registry contract and must include:

- Parameter validation.
- Warm-up declaration.
- Unit tests.
- Golden-data tests.
- Version identifier.
- Output schema.
- Documentation explaining why Pandas TA was insufficient.

Examples likely to remain custom include strategy-specific piecewise factor scores, selected benchmark-relative calculations, cross-sectional composites, and eligibility/penalty rules.

## 7. Pandas TA evaluation and testing plan

Pandas TA must not be introduced directly into production without a compatibility and parity gate.

### 7.1 Environment compatibility spike

Test in an isolated branch/environment against the project's supported runtime:

- Current Python requirement.
- Current pandas requirement.
- Windows development environment.
- CI environment.
- Dependency resolver and lockfile generation.
- Import and startup time.

Record:

- Candidate package/version.
- Installation source.
- Supported Python versions observed in the resolved package.
- pandas compatibility.
- Transitive dependencies.
- Installation or runtime failures.

If the preferred package is incompatible with the supported runtime, evaluate a maintained compatible distribution or retain a minimal custom implementation for affected indicators. The decision must be documented rather than silently changing formulas.

### 7.2 V3 inventory and recovery

Recover the exact V3 Pandas TA usage from Git history:

- Function names.
- Parameters.
- Moving-average modes.
- Adjust settings.
- Column-name expectations.
- Fill/null behavior.
- Strategy batching behavior.
- Any monkey patches or compatibility helpers.

Create a V3 indicator manifest before changing production code.

### 7.3 Indicator conformance tests

For every catalogued Pandas TA indicator, test:

- Required and optional inputs.
- Default parameters.
- Parameter boundaries.
- Minimum input length.
- Output shape.
- Output column names.
- Single-output and multi-output behavior.
- Index alignment.
- Null warm-up region.
- Constant series.
- Zero-volume series.
- Gapped sessions.
- Missing OHLCV fields.
- Non-finite input rejection.
- Deterministic repeated execution.

### 7.4 Numerical parity tests

Use the same frozen OHLCV histories for:

1. V3 Pandas TA implementation.
2. Current handwritten V4 implementation.
3. Proposed Pandas TA adapter.

Compare:

- Full indicator series where available.
- Final-session values.
- Warm-up boundaries.
- Derived factors.
- Eligibility and penalty results.
- Composite scores.
- Final rank ordering.

Define tolerances explicitly:

- Exact equality for booleans, exclusions, IDs, and ordering rules.
- Tight absolute/relative tolerance for floating-point indicator values.
- Zero tolerance for unexplained rank changes at decision boundaries.

Every accepted difference must have a written reason and a new calculation revision.

### 7.5 Look-ahead tests

For each indicator and strategy:

1. Calculate results using data through session `T`.
2. Append future sessions.
3. Recalculate the value for `T`.
4. Confirm the value at `T` has not changed.

Indicators or modes that change historical values after future data is appended must be rejected for ranking/backtesting or explicitly wrapped in a no-look-ahead configuration.

### 7.6 Performance tests

Benchmark:

- One indicator across the full universe.
- A representative multi-indicator strategy.
- One session calculation.
- One year of historical backfill.
- Cold-cache and warm-cache runs.
- Memory use for long warm-up windows.

The adapter must avoid recalculating the same indicator separately for every strategy when the definition and inputs are identical.

### 7.7 Upgrade policy

Pandas TA must be version-pinned after compatibility testing.

The implementation identity must include:

```text
provider + function + normalized parameters + package version + adapter version
```

Upgrading Pandas TA creates new indicator revisions. Existing historical artifacts remain linked to the old implementation. Recalculation is explicit and never silently overwrites prior results.

### 7.8 Pandas TA acceptance gate

Pandas TA is approved for production use only when:

- It installs reproducibly in development and CI.
- Required functions pass input/output conformance tests.
- No-look-ahead tests pass.
- Strategy 1 and Strategy 2 parity is accepted.
- Multi-output mapping is deterministic.
- Performance is acceptable for historical backfills.
- Package and adapter versions are recorded in artifacts.

## 8. Supported-indicators catalogue and future UI page

### 8.1 Backend catalogue first

The UI page must not contain a manually maintained hardcoded list. The backend indicator registry is the source of truth.

Proposed endpoint:

```text
GET /api/v2/indicators/catalog
```

Optional detail endpoint:

```text
GET /api/v2/indicators/catalog/{provider}/{indicator_key}
```

Each catalogue item should return:

- Provider: `pandas_ta`, `custom`, or `built_in`.
- Indicator key and display name.
- Category.
- Description.
- Required inputs.
- Supported parameters, defaults, types, and bounds.
- Outputs and whether output selection is required.
- Warm-up bars.
- Scope: instrument, benchmark-relative, or cross-sectional.
- Package/implementation version.
- Support status.
- Test status.
- Look-ahead status.
- Parity status.
- Manual-effort requirement and reason.

Suggested support statuses:

```text
AVAILABLE_UNTESTED
SUPPORTED
SUPPORTED_WITH_RESTRICTIONS
CUSTOM_IMPLEMENTATION
MANUAL_IMPLEMENTATION_REQUIRED
UNSUPPORTED
```

### 8.2 Catalogue generation

The build/development process may inspect the installed Pandas TA package to discover candidate functions, but the production runtime should expose a persisted approved catalogue rather than blindly exposing every callable.

Catalogue refresh process:

1. Discover candidate Pandas TA functions.
2. Extract signatures and categories where available.
3. Apply project metadata overrides.
4. Run conformance tests.
5. Mark tested functions as supported or restricted.
6. Persist the catalogue revision.
7. Publish a catalogue artifact with package and adapter versions.

### 8.3 Future UI page

The future UI should provide an `Indicators` page with:

- Search by name.
- Filters for provider and category.
- Filters for support/test status.
- `Handled automatically` section.
- `Custom implementation available` section.
- `Manual effort required` section.
- Parameter and output details.
- Warm-up requirement.
- Compatibility and parity badges.
- Explanation for unsupported/restricted indicators.
- Direct use in the future strategy builder.

The page answers two practical questions:

1. Can this indicator be selected in a YAML strategy immediately?
2. If not, what manual backend work is required?

This indicator-catalogue page belongs to the later UI redesign, but its backend API and metadata model belong to the backend implementation phase.

## 9. Feature cache and lineage redesign

Per-instrument feature cache keys must include:

- Indicator implementation identity.
- Normalized parameter hash.
- Instrument ID.
- As-of trading session.
- Input market snapshot digest.
- Benchmark snapshot digest when applicable.

Cross-sectional results must additionally include:

- Universe snapshot ID.
- Complete ordered input-feature snapshot IDs.

Research artifacts must include:

- Strategy revision ID.
- Compiled-plan hash.
- Indicator implementation versions.
- Market and benchmark snapshot IDs.
- Universe snapshot ID.
- Calculation-engine version.
- Missing-data policy.
- Quality status.

Content-derived or deterministic IDs should be preferred so an identical rerun can safely reuse prior results.

## 10. Generic historical pipeline

### 10.1 Generic job types

Replace strategy-specific job handlers with generic jobs:

- `strategy.validate-revision`
- `strategy.compile-revision`
- `research.plan-history`
- `research.ensure-data`
- `research.compute-feature-batch`
- `research.compute-cross-section`
- `research.score-session`
- `research.build-ranking`
- `research.verify-history`

Each job carries a `strategy_revision_id` and deterministic fingerprint.

### 10.2 Backfill planner

When a strategy revision is validated or the user requests history generation:

1. Compile the dependency graph.
2. Resolve all indicator implementations.
3. Calculate the maximum warm-up requirement using trading sessions, not calendar days.
4. Resolve the dated universe.
5. Resolve benchmark dependencies.
6. Inspect existing market-data coverage.
7. Inspect feature-cache coverage.
8. Schedule missing provider data first.
9. Calculate only missing features.
10. Calculate cross-sectional factors after all per-instrument dependencies complete.
11. Generate scores and rankings on configured sessions.
12. Verify artifact completeness and lineage.

Long histories should run in bounded, restartable chunks. The existing one-year request limit should not prevent multi-year history; the planner should create multiple bounded child jobs.

### 10.3 Exchange calendar

- Use actual exchange sessions.
- A weekly strategy ranks on the final completed trading session of the week, not necessarily Friday.
- Holidays and exceptional closures must not create failed phantom jobs.
- Strategy calculations must reject incomplete current-session data unless the strategy explicitly supports intraday operation.

### 10.4 Missing indicator behavior

If a YAML strategy references an unavailable indicator:

- Save it as `DRAFT` if the rest of the schema is valid.
- Return a structured dependency report.
- Mark the indicator `MANUAL_IMPLEMENTATION_REQUIRED` in the catalogue.
- Do not schedule partial rankings.
- After the implementation is registered, revalidate and generate history without changing the strategy's intended logic.

## 11. Migrating Strategy 1 and Strategy 2

### 11.1 Freeze current behavior

Before replacing production calculations, create golden fixtures covering:

- Normal price history.
- Short warm-up history.
- Flat prices.
- Zero volume.
- Missing sessions.
- Corporate-action boundaries.
- Benchmark gaps.
- Ties and near-ties.
- Eligibility thresholds.

### 11.2 Extract reusable calculations

Classify each current calculation as:

- Standard Pandas TA indicator.
- Small Pandas TA compatibility wrapper.
- Generic declarative transform.
- Reusable custom indicator.
- Strategy-specific configuration.

Standard calculations should move to the Pandas TA provider. Strategy-specific constants, weights, thresholds, and composition should move to YAML.

### 11.3 Shadow execution

For representative historical periods, run:

```text
legacy/current Python strategy
             versus
new compiled YAML strategy
```

Compare indicators, factors, eligibility, scores, percentiles, rankings, and downstream actions. Production remains on the old path until the accepted parity threshold is met.

### 11.4 Cutover

After parity acceptance:

- Register Strategy 1 and Strategy 2 as immutable YAML-backed revisions.
- Switch production jobs to the generic handler.
- Switch backtests and actions to explicit revision IDs.
- Remove production imports of `research_strategy1.py` and `research_strategy2.py`.
- Keep the old files temporarily as parity references, then retire them after the migration is signed off.

## 12. Real portfolio and execution redesign

### 12.1 Single authoritative portfolio

Migrate the default account identity from `paper` to `portfolio` without rewriting historical audit records in place.

Possible compatibility approach:

- Add a one-time account alias/migration record.
- Preserve original historical event payloads.
- Use `portfolio` for all new API defaults, jobs, UI values, and records.
- Mark old `paper` labels as legacy data only.

### 12.2 Transaction model

Every real transaction should contain:

- Portfolio/account ID.
- Instrument ID.
- Side.
- Quantity.
- Actual execution price.
- Fees and taxes where known.
- Execution timestamp.
- Settlement/trade date where relevant.
- Source/provenance.
- External broker order/trade IDs when applicable.
- Correlation and idempotency IDs.
- Optional note/evidence reference for manual entries.

### 12.3 Proposal versus fill

Required state flow:

```text
strategy ranking
      -> proposal
      -> approved execution intent
      -> Kite submission or manual execution confirmation
      -> confirmed fill
      -> portfolio ledger
```

- Approving a proposal does not alter holdings.
- Processing a proposal must not synthesize a historical-price fill.
- A manual transaction endpoint may directly record a fill only when the user supplies actual transaction facts.
- Kite writes ledger fills only from confirmed/reconciled broker state.

### 12.4 Kite synchronization and deduplication

Connecting Kite should support importing/reconciling actual broker holdings, orders, and trades.

Deduplication keys should prioritize:

- Broker trade ID.
- Broker order ID plus execution sequence.
- Account/profile identity.

Manual records that correspond to later Kite imports need a reconciliation workflow rather than duplicate posting.

## 13. Operator-token deactivation plan

### 13.1 Active behavior

- Operator-token validation becomes inactive.
- No API request requires `X-Operator-Token`.
- `SCREENER_OPERATOR_TOKEN` is not required.
- Dashboard requests stop prompting for or sending the token.
- Kite authorization start no longer checks the operator token.
- Kite's own login/token exchange remains unchanged.

### 13.2 Preserving the code temporarily

To satisfy the request to retain the existing implementation while keeping the code as clean as possible:

1. Disable the validation centrally first.
2. Preserve one clearly labelled commented reference implementation in the shared web/auth module.
3. Comment or bypass route-level calls during the transition.
4. Comment the operator-token UI helper/header plumbing as grouped sections rather than leaving scattered partial statements.
5. Mark the retained code with one consistent removal ticket/reference.
6. Update tests to prove mutations work without the token.

Long-term, Git history is the cleaner preservation mechanism. The retained comments should be removed only after a separate approval, because the current requirement is to keep the code in place.

### 13.3 Explicit local-only consequence

Without application authentication, any process or browser context capable of reaching the localhost service may attempt API calls. The loopback binding must therefore remain enforced, and network binding must continue to require an explicit separate configuration.

## 14. Downstream migration

### 14.1 Backtesting

- Backtests consume an explicit immutable strategy revision.
- A run records strategy revision, indicator versions, data snapshots, universe snapshot, portfolio policy, costs, and engine version.
- Backtests must not resolve “whatever is active now” during a historical replay.
- Walk-forward tests may use a dated revision schedule only when explicitly configured.
- Simulated fills remain confined to backtest state/artifacts.

### 14.2 Portfolio actions

- Action generation consumes an explicit ranking artifact and strategy revision.
- Portfolio policy is versioned separately from research logic.
- Action approval creates an intent, not a fill.
- Manual/Kite execution determines actual fills.
- Paper-specific policy names, IDs, methods, messages, and event origins are retired from active behavior.

### 14.3 APIs

Remove hardcoded strategy allowlists and expose registry-backed APIs for:

- Listing strategies.
- Creating a draft revision.
- Importing/exporting YAML.
- Validating and compiling a revision.
- Comparing revisions.
- Planning historical generation.
- Starting and monitoring a backfill.
- Activating and retiring revisions.
- Listing ranking history by revision.
- Reading the indicator catalogue.

## 15. Future UI contracts

Backend work should provide contracts for the later UI, but full visual redesign is not part of the initial backend implementation.

Future strategy UI capabilities:

- Strategy list and revision history.
- Visual strategy builder.
- YAML preview and import/export.
- Indicator selection from the backend catalogue.
- Parameter editors generated from registry metadata.
- Dependency and warm-up preview.
- Validation errors mapped to fields.
- Historical backfill estimate and progress.
- Ranking preview.
- Revision comparison.
- Activation controls.

## 16. Deferred dashboard aesthetic work

Keep the following as a separate pending UI workstream:

- Stop refreshing the whole dashboard when index values update.
- Update index components incrementally.
- Restore the prior animated/running index line.
- Use positive/negative colors for upward and downward movement.
- Preserve user inputs, scroll position, selections, and open panels during refresh.
- Use smooth transitions without coupling UI refresh behavior to backend research jobs.

The backend may expose an efficient polling or streaming contract, but visual implementation should wait for the UI redesign.

## 17. Implementation phases and gates

### Phase 0: Baseline and inventory

- Back up the local database and artifacts.
- Record the existing schema versions.
- Freeze Strategy 1 and Strategy 2 fixtures.
- Recover V3 Pandas TA configuration from Git.
- Inventory existing `paper` account data and operator-token references.
- Record current test results before changing behavior.

Gate: repeatable baseline exists and no migration work has started without recoverable data.

### Phase 1: Pandas TA feasibility and catalogue prototype

- Test installation/runtime compatibility.
- Build the initial adapter contract.
- Discover candidate indicators.
- Test required Strategy 1/2 indicators.
- Produce a support matrix and parity report.

Gate: approve the package/version and identify all required custom calculations.

### Phase 2: Strategy revision foundation

- Add YAML parsing and canonicalization.
- Add immutable strategy revision persistence.
- Add schema validation and lifecycle.
- Add strategy and indicator catalogue APIs.

Gate: a draft strategy can be imported, exported, hashed, validated, and read back identically.

### Phase 3: Indicator registry and cache correction

- Add Pandas TA, custom, and built-in providers.
- Add versioned metadata.
- Replace the collision-prone cache identity.
- Add per-indicator conformance, look-ahead, and determinism tests.

Gate: identical indicators are reused across strategies; different definitions cannot collide.

### Phase 4: Generic compiler and executor

- Implement safe operation-tree validation.
- Compile a strategy into a dependency DAG.
- Execute per-instrument, benchmark-relative, and cross-sectional nodes.
- Publish complete lineage.

Gate: generic fixtures run without strategy-specific Python dispatch.

### Phase 5: Strategy 1/2 shadow migration

- Create YAML seed definitions.
- Run old and new paths side by side.
- Resolve parity differences.
- Publish comparison reports.

Gate: accepted parity for indicators, eligibility, scores, rankings, and actions.

### Phase 6: Generic pipeline and historical generation

- Replace hardcoded strategy job kinds.
- Add dependency-aware history planning.
- Add exchange-calendar scheduling.
- Add chunking, resume, retry, cancellation, and idempotency.

Gate: a newly created strategy using existing indicators generates its complete available ranking history without Python changes.

### Phase 7: Revision-safe downstream migration

- Migrate scores/rankings to revision-aware keys.
- Update research APIs.
- Update backtests.
- Update action generation.
- Preserve legacy readback.

Gate: multiple revisions coexist without overwriting or mixing results.

### Phase 8: Real portfolio migration

- Introduce transaction provenance.
- Migrate default account semantics.
- Separate proposals/intents from fills.
- Add Kite import/reconciliation and deduplication.
- Remove active paper behavior.

Gate: only actual manual or Kite-confirmed transactions alter the real portfolio.

### Phase 9: Operator-token deactivation

- Disable checks centrally.
- Disable dashboard token prompts/headers.
- Retain requested commented reference code.
- Update tests, scripts, and active documentation in a later explicitly approved documentation pass.

Gate: all local workflows function without an operator token; Kite authentication still works.

### Phase 10: Production cutover and cleanup

- Switch all production research to generic jobs.
- Remove production imports of strategy-specific files.
- Verify migrations and startup recovery.
- Run the full regression suite.
- Keep compatibility reads until explicitly retired.

Gate: no production code path requires a hardcoded strategy ID or paper mode.

### Phase 11: Separate UI redesign

- Build strategy editor.
- Build supported-indicators page.
- Redesign portfolio pages.
- Address dashboard streaming and aesthetics.

## 18. Testing strategy

### Unit tests

- YAML parser and canonicalizer.
- Schema and operation-tree validation.
- Definition hashing.
- Indicator parameter validation.
- Pandas TA result normalization.
- Custom indicator contract.
- DAG cycle and missing-reference detection.
- Cache-key construction.
- Exchange-session calculation.
- Transaction provenance and deduplication.

### Integration tests

- YAML revision to historical ranking.
- Multiple strategies sharing one indicator cache.
- Multiple revisions of one strategy.
- Missing-data scheduling.
- Benchmark dependency scheduling.
- Pipeline restart/retry/cancel.
- Backtest isolation.
- Manual transaction posting.
- Kite reconciliation posting.
- Operator-token-free local API flow.
- Kite authorization flow.

### Regression and parity tests

- V3 Pandas TA versus approved adapter.
- Current V4 strategy Python versus YAML engine.
- Existing rankings and ties.
- Existing action decisions.
- Existing backtest outcomes.
- Existing portfolio projection after migrated events.

### Failure tests

- Unsupported Pandas TA function.
- Invalid parameter type/range.
- Unexpected output columns.
- Missing benchmark.
- Insufficient warm-up.
- Stale market snapshot.
- Duplicate Kite trade.
- Manual/Kite reconciliation conflict.
- Strategy DAG cycle.
- Worker interruption during a backfill.

## 19. Principal risks and mitigations

### Numerical drift

Risk: Pandas TA and handwritten formulas may use different smoothing defaults.

Mitigation: recover exact V3 parameters, pin versions, compare full series, and use compatibility wrappers only where required.

### Hidden look-ahead

Risk: an indicator or data-alignment mode may revise past values using future data.

Mitigation: automated truncation/append look-ahead tests for every supported indicator.

### YAML becoming executable code

Risk: an overly flexible expression syntax creates security and maintenance problems.

Mitigation: typed, allowlisted operation trees with no eval/import capability.

### Cache contamination

Risk: results from one definition are reused by another.

Mitigation: full implementation/parameter/input hashes and revision-aware storage.

### Historical overwrite

Risk: activating a new revision replaces old results.

Mitigation: immutable revision IDs in all primary keys and artifacts.

### Fictional real trades

Risk: old paper processing behavior writes synthetic fills into the real ledger.

Mitigation: proposals produce intents only; actual execution facts are mandatory for fills.

### Duplicate manual and Kite trades

Risk: the same transaction is recorded manually and imported later.

Mitigation: broker identifiers, reconciliation status, and explicit conflict resolution.

### Dead commented authentication code

Risk: temporary preserved code becomes permanent clutter.

Mitigation: centralize the retained block, label it consistently, and require explicit approval before final removal.

## 20. Definition of done

The redesign is complete when:

- There is one real portfolio model and no active paper-trading behavior.
- Manual and Kite transactions update the same authoritative ledger.
- Strategy proposals cannot directly create synthetic real fills.
- Backtests are isolated from the real portfolio.
- No active API requires an operator token.
- Kite is the only active authentication flow.
- A new strategy using supported indicators requires only a YAML/database definition.
- A new custom calculation requires one reusable registered implementation, not a strategy-specific module.
- Pandas TA compatibility, parity, no-look-ahead, determinism, and performance tests pass.
- The indicator catalogue clearly identifies automatic versus manual implementation requirements.
- Strategy 1 and Strategy 2 run through the generic YAML engine with accepted parity.
- No production job, API, backtest, or action path hardcodes Strategy 1 or Strategy 2.
- Features, scores, rankings, backtests, and actions carry immutable strategy revision lineage.
- Historical generation is exchange-calendar-aware, resumable, idempotent, and revision-safe.
- Cache entries cannot collide across indicator definitions or strategy revisions.
- Existing audit history remains readable after migration.
- The backend indicator-catalogue API is ready for the later supported-indicators UI page.
- Dashboard refresh and animated index-line improvements remain tracked as a separate UI redesign item.

