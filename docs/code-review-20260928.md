# Integration review — 28 September 2026

## Changes completed

- Moved the Strategy 4 portfolio replay and market loaders into `src/application/positional_trend_backtest.py`. The research CLIs and application backtest job use this implementation; production code no longer imports the Strategy 4 engine from the unpackaged `tools/` directory.
- Corrected the custom indicator series registry to expose a date-keyed series, while the single-row adapter returns the most recent row. Both accept chronologically unordered input.
- Made signal artifact and job identities depend on the active revision, universe, indicator/job code, exchange sessions and source histories. Readback rejects stale artifacts. A changed source snapshot produces fresh lineage even when prices are identical.
- Enforced the ₹500 crore threshold when reading the application universe and NSE-only membership for Nifty 500 signals. Total Market permits BSE fallback for BE identities, matching the research loader's convention.
- Aligned action sizing with replay by reducing equity for each preceding order's fee. Proposal identities now include the actual policy and source evidence. Actions reject invalid executable bars and allow the same 1–50 configurable position range as the backtest adapter.
- Rejected non-finite strategy settings, fractional indicator periods, truncated position counts and non-boolean backtest pyramid switches.
- Made the bulk fetch provider throttle safe across concurrent requests. Bulk jobs report individual successes, skips and errors and emit their final progress checkpoint even when the last instrument is skipped.
- Updated tests and documentation for missing stock bars: absent records preserve indicator history; malformed stored bars reset it. Strategy 3 uses Nifty 500; production Strategy 4 pyramiding remains deferred.
- Removed unused imports and fixed source lint errors.

## Verification

- Full suite: **262 passed**.
- Ruff: all `src/`, `run.py`, Strategy 4 CLIs and the new integration regression tests pass.
- Python compilation and both Strategy 4 CLI entry points pass.
- Added regressions for signal freshness after source/revision changes, the series adapter contract, invalid rule parameters, and fee-aware agreement between replay fills and action quantities.

Historical portfolio result files were not regenerated during this review. Their results reflect the indicator behavior in effect when they were produced; replay after the missing-bar change can differ.
