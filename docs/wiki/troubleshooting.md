# Troubleshooting

## No rankings or signals

Check that a universe snapshot exists for the requested date, the relevant
market bars are stored, and the selected strategy revision is active. Then
inspect the pipeline/job events instead of rerunning blindly. An explicit
missing-data diagnostic is preferable to a fabricated ranking or fill.

## A valuation is zero or stale

Confirm the as-of date, account lots, stored bar coverage and `stale_prices`
field. The valuation endpoint uses the latest stored bar up to the date; it
does not fetch a quote or call a broker as a side effect.

## A proposal cannot be approved or processed

Read the proposal events and guard error. Verify account ID, proposal state,
ledger/config versions and timing. Do not create a manual fill to bypass a
rejection unless the real execution has been independently verified.

## A job appears stuck

Read `/api/operations/worker/status`, then inspect job events with the last
cursor. Check cancellation status and lease ownership before starting another
worker. A duplicate worker can create confusing contention rather than faster
completion.

## Credentials or tokens

Use the configured Kite access route. If a token is expired, re-authenticate
through the server-held credential flow. Do not add token text to a job payload,
browser local storage, log, wiki page, test fixture or support request.

## What to include in a safe support report

Include the page/action, account alias (not secret), job/pipeline/proposal ID,
timestamp, HTTP status, safe error message and relevant artifact/snapshot ID.
Exclude credentials, tokens, raw broker responses and personal holdings unless
the recipient is explicitly authorized.
