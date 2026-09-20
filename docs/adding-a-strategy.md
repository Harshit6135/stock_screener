# Adding a strategy

## What is supported today

A strategy is imported from YAML, validated, stored as an immutable revision,
activated, and referenced by research and backtest artifacts. Portfolio policy,
factor weights, benchmark dependency, score modifiers, and ranking policy are
configuration.

Complete calculation is not yet generic. Each strategy currently names a
registered Python instrument implementation, its matching vectorized series
implementation, and optionally a registered cross-sectional implementation.
Therefore:

- a revision that only changes weights, modifiers, portfolio policy, or other
  supported configuration needs only YAML;
- a materially new calculation needs a reusable Python implementation and a
  registry entry;
- declaring Pandas TA nodes in YAML validates them, but the runtime does not yet
  execute an arbitrary indicator/operation DAG.

The pending generic executor is documented in [pending items](pending-items.md).

## Existing strategies

| ID | YAML | Instrument implementation | Benchmark/cross-section |
|---|---|---|---|
| `strategy1` | `strategies/momentum_quality.yml` | `custom.momentum_quality_features` | none |
| `strategy2` | `strategies/benchmark_relative_momentum.yml` | `custom.relative_strength_features` | NIFTY 500 and `custom.relative_strength_factors` |

## YAML contract

Required top-level fields are `schema_version`, `strategy`, `calculation`,
`factors`, `ranking`, and `portfolio_policy`. Optional sections are `universe`,
`data_dependencies`, `indicators`, `eligibility`, and `score`. Unknown fields
are rejected.

```yaml
schema_version: 1

strategy:
  id: strategy3
  name: Example Strategy
  version: 1.0.0
  description: Short explanation of the investment hypothesis.

data_dependencies:
  benchmark: NIFTY 500       # optional

calculation:
  instrument_implementation: custom.example_features
  cross_section_implementation: custom.example_cross_section  # optional
  required_sessions: 253

factors:
  trend: 0.30
  momentum: 0.25
  efficiency: 0.20
  volume: 0.15
  structure: 0.10

score:
  factor_modifiers: []

portfolio_policy:
  initial_capital: 100000
  max_positions: 15
  exit_threshold: 40
  buffer_percent: 0.25
  max_concentration_pct: 0.25

ranking:
  frequency: weekly
  session: last_trading_session
  aggregation: weekly_mean
  tie_policy: score_desc_symbol_asc
```

Rules enforced by `StrategyDefinitions` include:

- `schema_version` must be `1`;
- strategy ID is alphanumeric with optional underscores;
- version is semantic version text;
- calculation implementations must exist in the approved custom registry;
- `required_sessions` is positive;
- indicator IDs are unique and Pandas TA functions are allowlisted;
- factor weights are non-negative and sum to `1`;
- position count is between `1` and `50`;
- policy numbers are within supported ranges; and
- ranking frequency/session values are approved.

## Approved Pandas TA indicators

The adapter currently exposes EMA, SMA, RSI, ROC, ATR, MACD, Bollinger Bands,
and ADX. Read the runtime catalogue at:

```text
GET /api/v2/indicators/catalog
GET /api/v2/indicators/catalog/pandas_ta/<indicator-key>
```

An installed Pandas TA function is not supported unless it appears in this
allowlist. Parameters, required inputs, outputs, warm-up, and support status
come from `src/indicators/registry.py`.

## Add a configuration-only revision

Use this path when the calculation functions do not change.

1. Copy the relevant YAML and keep the same `strategy.id`.
2. Increment `strategy.version`.
3. Change only validated configuration such as factor weights, modifier rules,
   or portfolio policy.
4. Submit `{"source_yaml": "..."}` through
   `POST /api/v2/strategies/revisions` or place the seed in `strategies/` for a
   clean database.
5. Inspect the returned revision and activate it with
   `POST /api/v2/strategies/revisions/<revision-id>/activate`.
6. Run research for the new active revision. Existing results remain attached
   to the previous revision and are not reused as if they were current.
7. Backtest and compare against the prior revision before relying on it.

Changing a seed file does not mutate an already active revision. The new
canonical definition creates a new deterministic revision ID.

## Add a genuinely new calculation

Use this path when no registered implementation produces the required
features.

1. Decide whether the calculation is instrument-local or cross-sectional.
2. Add a focused series implementation under `src/indicators/custom/`. It
   should accept normalized histories, calculate rolling values once, and
   return date-keyed finite, JSON-serializable values.
3. Keep a thin single-date wrapper that returns the final value from that same
   series implementation. Do not maintain a separate formula path.
4. Register the stable implementation key in both
   `INSTRUMENT_IMPLEMENTATIONS` and `INSTRUMENT_SERIES_IMPLEMENTATIONS`.
   Register cross-sectional behavior in `CROSS_SECTION_IMPLEMENTATIONS` when
   required, and include YAML-visible implementations in
   `CUSTOM_IMPLEMENTATIONS`.
5. Give it a stable name such as `custom.example_features` and reference that
   name in YAML.
6. Add a parity test proving the final bulk-series value equals the single-date
   wrapper result.
7. Add unit tests for warm-up, missing data, constant data, non-finite values,
   append/truncation behavior, and deterministic output.
8. Add no-look-ahead tests: calculating an earlier date with and without later
   bars must produce the same earlier output.
9. Add bulk research integration tests proving scores and rankings reference the
   correct strategy revision and upstream snapshots.
10. Add a representative performance test to detect accidental per-date history
    reloads or rolling-indicator recalculation.
11. Add a multi-year parity or acceptance backtest with pyramiding both off and
   on when the strategy uses it.

Do not create a complete new research job kind for each strategy. The generic
`research.rebuild-range` job accepts one or more active strategy IDs and runs
the ordered indicator, percentile, score, and ranking stages.

## Indicator node schema

The validator accepts indicator nodes in this form for the future DAG runtime:

```yaml
indicators:
  - id: ema_fast
    provider: pandas_ta
    function: ema
    inputs:
      close: close
    parameters:
      length: 20
    output: ema_20
```

Input names must exactly match the approved indicator specification. Operation
references may use declared indicator IDs or known fields `close`, `high`,
`low`, `volume`, and `benchmark.close`. Approved operations are allowlisted in
`strategy_definitions.py`.

Until the generic executor is complete, these nodes document and validate a
definition but do not replace `instrument_implementation`.

## Acceptance checklist

- The YAML imports and canonicalizes successfully.
- A duplicate import returns the same immutable revision.
- Activation retires only the prior revision of the same strategy.
- Required history and benchmark data are present.
- Feature output is deterministic and finite.
- No-look-ahead tests pass.
- Bulk score and weekly ranking artifacts include revision lineage.
- Bulk-series and single-date outputs have exact parity.
- Ranking ties are deterministic.
- Backtests report total return, CAGR, annual returns, fills, and risk metrics.
- Pyramiding-on and pyramiding-off behavior is explicitly tested.
- No strategy or backtest path writes the real ledger.
- The indicator catalogue and this guide are updated when support changes.
