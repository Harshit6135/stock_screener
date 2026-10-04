# Research and strategies

## Retained strategies

The active runtime uses named strategies, currently `momentum` and
`positional_trend_following`. Retired Strategy 2/3 material is intentionally
absent from active runtime, configuration, tools and historical backtest
outputs.

## Research data flow

```text
Universe snapshot → dated instruments → normalized OHLCV → indicators/DAG
→ percentiles/scores or event signals → immutable ranking artifact
```

Every stage retains identifiers for its input snapshot/artifact where the
contract provides them. A ranking is therefore a dated research output, not a
live recommendation.

## Universe rules

`SNAPSHOT_NIFTY500` is the standard historical-safe universe. Its members are
read from the latest immutable NIFTY 500 snapshot at or before the requested
date. `APPLICATION_MCAP500` is a separately maintained market-cap universe.
The retired root CSV fallback and total-market/BE compatibility route are not
active execution paths.

Universe endpoints:

- `GET /api/universe/snapshots?index_name=NIFTY%20500&limit=100&offset=0`
- `GET /api/universe/members?snapshot_id=<id>`
- `GET /api/universe/diff?from_snapshot_id=<id>&to_snapshot_id=<id>`
- `POST /api/universe/refresh` with optional `snapshot_date`

## Indicator DAG and cache identity

Strategy definitions can compile indicators into an immutable DAG. The graph
validates references and cycles before calculation. Recursive node hashes
include provider, function, normalized parameters and role-preserving input
identities, so renaming equivalent nodes does not invalidate work while
changing an ancestor or swapping operands does.

Indicator cache reuse requires more than node/instrument/date: it also checks
market-history revision and implementation revision. A changed OHLCV history
invalidates stale cache values transactionally.

## Rankings

Use `GET /api/research/ranking-weeks?strategy_id=<id>` to discover weeks,
then `GET /api/research/rankings?strategy_id=<id>&week_end=YYYY-MM-DD`.
The response contains returned members only; consumers should retain source
artifact/lineage fields and render anomaly flags rather than silently removing
rows.

## Backtests

`GET /api/backtests/runs` lists saved reports and
`GET /api/backtests/runs/<run_id>` reads one immutable report. A UI refresh,
new market download, or later replay must not rewrite a saved report. If a
next-session opening bar is unavailable, show the reported diagnostic instead
of claiming a made-up exit.
