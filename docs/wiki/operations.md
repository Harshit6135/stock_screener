# Operations and observability

## Jobs and workers

The app uses durable jobs and a cooperative local worker. There is no hidden
calendar scheduler in the browser flow. Submit a pipeline deliberately, then
inspect, retry or cancel it by its durable ID.

Useful operations endpoints:

- `POST /api/v2/operations/jobs`
- `GET /api/v2/operations/jobs/<job_id>`
- `GET /api/v2/operations/jobs/<job_id>/events?after=<cursor>`
- `POST /api/v2/operations/jobs/<job_id>/cancel`
- `GET /api/v2/operations/worker/status`
- `POST /api/v2/operations/worker/start`, `/work-once`, or `/stop`

Progress events are persisted. A consumer reconnects using the last event
cursor; it should not infer progress from a client-side timer.

## Research pipeline

Create with `POST /api/v2/pipelines/research`, read with
`GET /api/v2/pipelines/research/<pipeline_id>`, retry a failed stage using its
stage-name route, or cancel the pipeline. Pipeline stages describe durable state
rather than an optimistic visual checklist.

## Quality events

Market ingestion validates finite positive prices and OHLC bounds. It stores
warning events for close-to-close gaps above the configured 15% threshold and
six-session zero-volume streaks. These flags are diagnostic: a flagged stock is
retained for research unless a separate data-sufficiency rule applies.

Read events with `GET /api/v2/market/quality-events`, optionally filtering by
`instrument_id`, `check_type`, `severity`, `limit` and `offset`.

## Redaction

Job payloads/events and persisted provider evidence pass through sensitive-key
redaction. Never add raw credentials to custom logging. Operational errors
should preserve a safe domain message or error class, not provider payloads.
