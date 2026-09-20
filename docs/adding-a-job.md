# Adding a durable job

This is the handoff guide for an agent or contributor adding background work.
Jobs are for provider calls, backfills, large calculations, staged workflows,
and any operation that must survive an HTTP request or be safely retried.

## Model

```text
UI/API or service -> JobStore.submit -> ops_jobs / ops_job_events
                                      -> BackgroundWorker / JobWorker
                                      -> registered domain handler
                                      -> repository, provider, artifact, result
```

The request submits durable intent; it does not run the long operation. `202`
means accepted, not complete.

## Choose the owner

| Work | Owner |
|---|---|
| Instruments, universe, bars, quotes | `src/application/market_jobs.py` |
| Bulk scores, rankings, research reports | `src/application/research_jobs.py` |
| Backtests and analysis | `src/application/backtest_jobs.py` |
| Portfolio proposals/actions | `src/application/action_jobs.py` |
| Stage coordination | `src/application/pipeline_jobs.py` |

Do not run long work in a Flask blueprint. Do not put domain logic in
`worker.py`; it is the durable execution boundary only.

## 1. Define kind and payload

Use a lowercase dot-separated kind scoped to its owner:

```text
reference.enrich-day0-universe
market.fetch-kite-bars
research.rebuild-range
backtest.run
```

Payload must be a complete JSON object containing every input that changes the
result. Validate the exact allowed and required fields in the handler; reject
unknown fields.

```python
allowed = {"as_of_date", "strategy_id", "instrument_ids", "mode"}
required = {"as_of_date", "strategy_id"}
if set(payload) - allowed or not required.issubset(payload):
    raise DomainValidationError("example job payload is invalid")
```

Do not rely on browser state, mutable globals, or an implicit “latest” value
unless that behavior is explicitly part of the contract.

## 2. Implement the handler

Handlers take `payload` and may take `JobExecutionContext`; they return a small
JSON-serializable result.

```python
from typing import Any

from src.application.jobs import JobExecutionContext
from src.platform_kernel import DomainValidationError


def calculate_example(
    payload: dict[str, Any], context: JobExecutionContext | None = None
) -> dict[str, object]:
    work_items = load_work_items(payload)
    for index, item in enumerate(work_items):
        if context is not None and (index == 0 or index % 25 == 0):
            context.checkpoint(progress={"processed": index, "total": len(work_items)})
        if context is not None and context.cancelled():
            return {"processed": index, "cancelled": True}
        process_one(item)
    return {"processed": len(work_items)}
```

Use `DomainValidationError` for invalid input or a known non-retryable business
precondition. Let transient network/provider errors propagate so the worker can
apply its retry policy. Do not catch broad `Exception` and label a coding error
as an unresolved item.

## 3. Make retries safe

Jobs can be submitted twice, retried after an outage, or reclaimed after a
lease expiry. Use all relevant layers:

1. Create a deterministic fingerprint from normalized inputs.
2. Use database uniqueness or an idempotency key at every write boundary.
3. Use deterministic immutable artifact IDs for derived evidence.
4. Store successful provider coverage/ranges for fetch jobs.
5. Return existing completed output on repeat rather than creating duplicates.

```python
normalized = {
    "as_of_date": as_of.isoformat(),
    "strategy_id": strategy_id,
    "instrument_ids": sorted(instrument_ids),
}
fingerprint = "research:example:" + hashlib.sha256(
    json.dumps(normalized, sort_keys=True).encode()
).hexdigest()
job = services.jobs.submit(fingerprint, "research.example", normalized)
```

`ops_jobs.fingerprint` is unique. The same fingerprint returns its existing
durable job instead of scheduling duplicate work.

## 4. Publish artifacts and projections

Use `ArtifactPublisher.publish_json()` whenever output needs reproducibility,
lineage, checksum verification, or readback:

```python
manifest = publisher.publish_json(
    "research/example",
    artifact_id,
    report,
    upstream_ids=tuple(sorted(upstream_ids)),
    quality=QualityStatus.COMPLETE,
)
```

Query projections should reference `manifest.artifact_id`. If artifact and
projection are separate writes, add a recovery path that can recreate missing
rows from the published artifact. For mutable active state, use one SQLite
transaction; `replace_universe_members()` is the model for atomic activation.

## 5. Register the job

Only `ApplicationServices.create()` in `src/application/composition.py`
registers executable job kinds:

```python
worker = JobWorker(
    jobs,
    "local-writer",
    {
        "research.example": research.calculate_example,
    },
)
```

This map is the allowlist. An unregistered kind becomes a durable
`unsupported job kind` failure. Do not make a strategy-specific kind when an
existing generic job can take `strategy_id` in its payload.

## 6. Expose submission

The local Operations API is suitable for administrative jobs:

```text
POST /api/v2/operations/jobs
```

```json
{
  "fingerprint": "research:example:<input-hash>",
  "kind": "research.example",
  "payload": {"as_of_date": "2026-09-18", "strategy_id": "strategy1"}
}
```

For user-facing workflows, create an area-specific endpoint that validates the
request and builds its fingerprint internally. Never accept an arbitrary job
kind from the browser.

Observe jobs through:

```text
GET /api/v2/operations/jobs/<job-id>
GET /api/v2/operations/jobs/<job-id>/events
POST /api/v2/operations/jobs/<job-id>/cancel
```

## 7. Add data safely

If persistent state is required:

1. identify the owning repository;
2. add the next namespaced `migrate_sqlite()` version in that owner;
3. use a transaction for related state changes;
4. add lookup indexes;
5. add migration and repository tests; and
6. keep state in `system.db`, not a new runtime database.

## 8. Required tests

Add tests for success, malformed payload, duplicate fingerprint, transient
retry, long-loop checkpoints/cancellation, no duplicate side effects,
artifact/checksum/lineage/recovery when applicable, and registration in the
composition handler map. Use fake providers and isolated temporary databases;
do not add one-off smoke or backfill scripts to the repository.

## Review checklist

- One clear owner and stable job kind.
- Exact payload validation and deterministic fingerprint.
- Safe duplicate, retry, and lease-recovery behavior.
- Checkpoints and cancellation for long loops.
- Expected provider failures are distinct from programming failures.
- Artifacts carry upstream lineage; projections can recover.
- Schema is owned, migrated, indexed, and tested.
- Handler is registered in `ApplicationServices.create()`.
- API/UI exposes job ID and durable status/events.

## Examples in this codebase

| Pattern | Example |
|---|---|
| Bounded provider fetch with coverage | `KiteMarketJobs.fetch_bars` |
| Rate-limited checkpointed loop | `KiteMarketJobs.enrich_and_sync_universe` |
| Revision-aware staged research | `ResearchJobs.rebuild_range` |
| Data-before-research coordination | `ResearchPipelineJobs.advance` |
| Artifact-to-projection recovery | `ActionJobs._recover_projection` |
| Idempotent accounting write | `Ledger.record_fills` |

See [Implementation guide](implementation.md), [Data model](data-model.md),
and [System workflows](workflows.md) for surrounding architecture.
