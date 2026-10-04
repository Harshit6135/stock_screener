# Research and strategies

## Active strategies

The active strategy definitions are loaded from `strategies/` and versioned in
the strategy registry.

| Strategy ID | Name | Output |
|---|---|---|
| `momentum` | Momentum Quality | Weekly factor score and ranking. |
| `positional_trend_following` | Positional Trend Following | Daily breakout/exit signals and rank. |

Both appear in **Rankings**. Momentum needs a published week. Positional Trend
needs a completed NSE session; select the date directly and build signals if no
current signal artifact exists.

## Research flow

```text
dated universe snapshot + stored bars
                 ↓
       normalized history and checks
                 ↓
    strategy features / daily signals
                 ↓
     immutable ranking artifacts
                 ↓
   saved report or reviewed proposal
```

Research output is associated with a strategy revision and its input artifacts.
A ranking is a dated result, not a live recommendation or a promise of future
performance. Missing market history can prevent a ranking from being built.

## Universe and dates

Historical calculations use immutable membership snapshots so a current
constituent list is not silently substituted for historical membership. The
standard strategy universe is `SNAPSHOT_NIFTY500`. The snapshot used by a
calculation and its date are visible in the artifact lineage or job result.

Use completed exchange sessions. Calendar days and market sessions are not the
same: weekends, holidays, missing bars, and newly listed securities can all
affect coverage.

## Pipeline behavior

Pipeline submission is manual. It records the requested range and strategy set,
then creates durable data/research stages. A worker must be running to process
queued work. Inspect the stage/job result before retrying a failure.

## API entry points

- `GET /api/strategies/active` lists active revisions.
- `GET /api/research/ranking-weeks?strategy_id=momentum` lists published weekly
  ranking dates.
- `GET /api/research/rankings?strategy_id=momentum&week_end=YYYY-MM-DD` reads a
  weekly ranking.
- `POST /api/positional-trend/signals/build` queues daily signal generation.
- `GET /api/positional-trend/signals?as_of_date=YYYY-MM-DD` reads a built daily
  signal artifact.
- `POST /api/pipelines/research` submits a range pipeline.

The [API guide](api-and-data.md) and [operations guide](operations.md) describe
the durable job contracts.
