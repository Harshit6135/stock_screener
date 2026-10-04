# Operations and observability

## Durable jobs

Jobs persist their kind, payload checksum, status, attempts, lease, result, and
events. A queued job does not run until a worker claims it. The **Pipeline**
page provides worker status, start/stop, and one-job processing controls.

| Operation | Endpoint |
|---|---|
| Submit supported job | `POST /api/operations/jobs` |
| Read status/result | `GET /api/operations/jobs/<job_id>` |
| Read event history | `GET /api/operations/jobs/<job_id>/events?after=<event_id>` |
| Request cancellation | `POST /api/operations/jobs/<job_id>/cancel` |
| Read worker state | `GET /api/operations/worker/status` |
| Start, stop, or work once | `POST /api/operations/worker/start`, `/stop`, or `/work-once` |

Job status and pipeline status are related but distinct. A pipeline consists of
stages, each referencing a job. Read the stage and job result before retrying.

## Research pipeline

Submit with `POST /api/pipelines/research`, inspect with
`GET /api/pipelines/research/<pipeline_id>`, retry one failed stage through its
stage route, or request cancellation. Identical requests may resolve to an
existing pipeline because runs are fingerprinted by their inputs.

## Market quality events

Ingestion checks normalized OHLCV and records configured quality warnings. A
warning is diagnostic and does not by itself remove a stock from research.
Read events from `GET /api/market/quality-events`; narrow results with the
supported filters and pagination fields.

## Backups and local state

Use `screener-ops backup-sqlite` and `restore-sqlite` for SQLite copies. Keep
backups outside Git and verify the source and destination paths before restore.
The application data directory may include account history, provider state,
market bars, and artifacts. Do not delete it as part of code cleanup.

## Logs and support evidence

Include the route/page, timestamp, safe error message, job/pipeline/proposal ID,
and relevant artifact or snapshot ID. Remove credentials, access tokens, raw
provider responses, and personal holdings from support material.
