# Troubleshooting

## A page looks unchanged after a code update

Confirm the browser is on `http://127.0.0.1:5000/` and the expected server
process is running from this repository. Restart that process after backend or
template changes. Asset URLs include version keys; reload the page after the
server serves the new template.

## No rankings or Positional Trend signals

Check the selected strategy and date. Momentum uses weekly published ranking
dates. Positional Trend uses a completed NSE session and a separately built
daily signal artifact. In **Rankings**, choose a session and use **Build signals
for date** if the artifact is absent. Confirm the worker is processing the job
and inspect its result. Missing universe membership or bars can stop a build.

## The proposal list is empty

**Load proposals** only reads existing proposals. Select the account and date;
to create new proposals, use **Generate proposals** above the queue. The page
uses the latest completed NSE session stored locally, which may be older than
the previous calendar day. Check the generation job and its result if nothing
appears.

## A generated proposal uses an older price date

The proposal uses the latest completed session stored in the local database.
Check market-data coverage and refresh missing history before generating again.
Upcoming-session prices are estimates based on that session's close; they are
not the target session's actual open.

## A valuation is stale or incomplete

Check account lots, valuation as-of date, stored bar coverage, and displayed
price dates. Valuation does not fetch a broker quote as a side effect.

## A job is queued or running for a long time

Check `GET /api/operations/worker/status`, then read the job by ID and inspect
its events and `last_error`. A stopped worker leaves jobs queued. Review the
active lease before starting another worker or retrying.

## Approval or broker step is rejected

Read the proposal state, proposal events, and guard error. Verify account,
strategy, date, and ledger/config version. Do not turn a rejected decision into
a manual fill unless the underlying trade actually executed and is verified.

## Report an issue safely

Include the route/page, timestamp, non-secret account alias, job/proposal ID,
HTTP status, and safe error text. Exclude access tokens, API secrets, raw broker
responses, and personal holdings.
