# Using the Stock Screener interface

This guide explains what each screen is for, how to use its main controls, and
what to check when a page is empty. Start at `/` and use the left sidebar to
move between pages. The top-right half-circle button switches between dark and
light themes; the choice is saved in this browser.

## Home: portfolio dashboard

Choose an account and an **As of date**, then select **Refresh values**. The
summary cards show portfolio value, invested cost, cash, realized and unrealized
gain, daily P&L, annualized return, stop-based risk, and stale price count. The
holdings table shows the price date used for each row; check it before relying
on a valuation. Equity and drawdown charts and the valuation history use saved
snapshots, so they may be empty until valuations have been recorded.

Use **Add account** to create a local ledger account. **Buy** and **Sell** record
completed transactions; they do not place broker orders. **Cash deposit /
withdrawal** records a completed capital transfer. These entries affect the
ledger, so enter actual transaction details. **Live ticker** is a separate,
optional quote display and does not change accounting values or fills.

## Universe: inspect coverage and membership

The **Snapshots** table lists dated universe versions. Select two snapshots and
choose **Compare** to inspect membership differences. **Current members** shows
the members of the selected active snapshot and their available coverage.
Choose **Refresh universe** to queue a refresh; if the worker is stopped, the
refresh will remain queued until a worker processes it. A refresh can reuse the
same-day snapshot.

## Pipeline: prepare research data and follow jobs

1. Select a completed **Start date** and **End date**.
2. Leave **Prepare market data first** selected when references or bars might
   be missing. This adds preparation stages and can take longer.
3. Choose **Start research run** and note the pipeline ID in the run summary.
4. Use **Run progress** to inspect stage status and job IDs. Retry a failed or
   cancelled stage after reviewing the reported error. Cancel only an active
   run.
5. Check **Background worker**. Use **Start worker** for ongoing processing,
   **Work one job** for controlled single-step processing, or **Refresh worker
   status** to reload its state.

The app returns a durable run ID. Save it if you need to reopen the run later:
paste it into **Pipeline ID** and choose **Load run**. Repeating identical
inputs may reopen an existing run instead of creating duplicate work. See
[Pipeline operation](../reference/operations.md) for job states and recovery.

## Rankings: view weekly and daily research

Select a strategy. Momentum uses a **Week ending** selector; choose a week to
load its published ranking. Use **Filter results** to narrow the rows by symbol
or signal.

Positional Trend uses a **Completed session date** instead. Choose a date and
load its saved signals. If none exist, choose **Build signals for date**. Signal
generation queues a job; the research worker must process it before results can
be displayed. The daily table includes the positional trend fields and whether
the row is a buy candidate. A research signal is an input for review, not an
order.

## Backtest: run or inspect a simulation

Choose a strategy and completed date range, then review the starting capital and
available strategy-specific assumptions. Expand **Execution assumptions and
strategy options** to see or adjust them. Some values, including maximum
holdings, come from the active strategy and are read-only. Choose **Run
simulation** and watch the status beside the button. On completion, the report
opens automatically.

Use **Saved runs** and **Refresh** to browse prior simulations; **Open report**
loads one into **Report detail**. The detail includes metrics, equity curve,
fills, open positions, and annual returns when available. Expand **Full report
data** for the saved payload. Simulations are isolated from the live portfolio.

## Actions: generate and review proposals

1. Select the local **Portfolio account**, **Strategy**, and **Target session**.
2. Choose **Generate proposals**. This queues proposal generation from the
   latest completed market session stored locally. If the page offers **Start
   job worker**, use it when no worker is running.
3. Once generation completes, choose **Load proposals** to refresh the review
   queue. Use the action-date filter to narrow it.
4. Review the stock table one row at a time. Each row shows the strategy, stock,
   action, units, estimated price, rationale, session, and review status. Use its
   **Approve** or **Reject** button to decide on that stock independently.
   Review risk projections for the selected account.
5. After every stock in a proposal is reviewed, prepare broker intents for the
   approved stocks if appropriate. This does not submit an order; submission is
   a separate step.

Upcoming share quantities use stored closing prices as estimates. The next
session’s opening prices are not known when proposals are generated. **Record a
manual trade** is for a completed, confirmed transaction, not a way to create a
proposal or place an order.

## Settings: review safeguards and strategy versions

The **Portfolio risk guard** shows the current version and limits. Edit its JSON
and choose **Save expected version** to save against the version displayed; if
another change has made that version stale, reload and review before saving.
The **Strategy revisions** panel lets you select a strategy and choose **Load
revisions** to inspect its history. Creating revisions uses the strategy API
with YAML; this screen does not accept credentials.

## Logs: inspect stored quality events

Choose a **Severity**, optionally enter a **Check type**, and select **Filter**.
The table shows stored events and their evidence. This is persisted application
evidence; browser developer-console messages are not included.

## Wiki: find a guide

Use **Filter guides** to search page titles. Select a page in the left column;
use **On this page** to jump to a section and **Previous guide** / **Next guide**
to browse. If a guide fails to load, refresh the page once; if it persists,
record the displayed error and see [Troubleshooting](../reference/troubleshooting.md).

## Kite access

The sidebar’s **Kite access** link opens the local authorization page for the
market-data profile. Authorization credentials and tokens stay on the server.
This page refreshes access; it does not create or submit an order. Broker account
setup and portfolio authorization are separately configured workflows.

For the full end-to-end sequence, see [Workflows](workflows.md). For
job terminology and recovery, see [Operations](../reference/operations.md).


---

# End-to-end workflows

This guide follows the normal local workflow. The app stores its data locally;
it does not require Kite credentials for read-only research or saved report
review.

## 1. Install and start

Use Python 3.13 and Poetry 2.x:

```powershell
poetry install --with dev
poetry run python run.py
```

Open `http://127.0.0.1:5000/`. The local database and artifact stores default
to `instance/`; set `SCREENER_DATA_DIRECTORY` to use a different directory.
See the [developer guide](../development/setup.md) for configuration and backups.

## 2. Prepare market data

1. Open **Universe** and check that a current NIFTY 500 snapshot is available.
   Refresh it if the required snapshot is missing.
2. Open **Pipeline** and submit a completed date range. Enable market-data
   orchestration when the run must first prepare its reference and bar data.
3. Review each stage and worker state. A queued job needs a running worker;
   retry a failed stage only after reviewing its error.
4. Open **Rankings** and choose the strategy and date. Momentum rankings are
   weekly. Positional Trend signals are daily; choose a completed session and
   build signals if no current artifact exists for it.

The pipeline is manually started. Re-submitting identical inputs can return an
existing durable pipeline. Market data availability determines which dates can
be calculated; the UI does not fabricate missing bars or signals.

## 3. Review backtests

Open **Backtest** to browse saved reports. The screen is a read-only report
viewer. A saved report retains the inputs, assumptions, fills, and diagnostics
from its original run. Missing next-session data is reported as a limitation;
it is not replaced with an invented fill.

## 4. Create and maintain a portfolio

On **Home**, create a local account with a unique account ID and opening cash.
Record verified fills and cash transfers with their actual dates. Refresh a
valuation only when you want to save a new history point. The valuation uses the
latest stored prices at or before its requested date, so check price dates and
staleness alongside value and return metrics.

Kite account authentication and importing broker holdings are separate from
creating a local ledger account. Reconciliation changes portfolio records only
after an explicit review/confirmation path.

## 5. Generate and review actions

1. Open **Actions**, select the local portfolio account, strategy, and target
   session date. The page uses the latest completed NSE session stored locally
   as the signal date.
2. Select **Generate proposals**. The request becomes a durable job. If the
   worker is stopped, start it from the page or **Pipeline**.
3. Read every decision, rationale, action date, and risk projection. Upcoming
   session sizes use the signal session’s closing prices as estimates; the
   target session’s opening prices are unknown until that session.
4. Approve or reject each proposal deliberately. Approval is a review decision,
   not an order submission or fill. Broker intents are a separate step.
5. Record an actual fill only after confirming it with broker execution or
   other execution evidence.

Manual trade entry follows the same review queue. It is intended for trades
that have already happened; it does not place orders.

## 6. Understand the main records

| Record | Meaning |
|---|---|
| Universe snapshot | Immutable dated membership used to scope research. |
| Ranking/signal artifact | Dated research output with source lineage; it is not a live recommendation. |
| Job | Durable unit of work with status, attempts, events, and result. |
| Pipeline | A date/strategy request composed of durable job stages. |
| Action proposal | Reviewable portfolio intent. It does not prove a broker fill. |
| Ledger event | Recorded account change such as a verified fill or cash transfer. |
| Backtest report | Immutable simulated result with explicit execution assumptions. |

For specific errors, see [Troubleshooting](../reference/troubleshooting.md). For
technical ownership and data flow, see the [system architecture](../development/architecture.md).
