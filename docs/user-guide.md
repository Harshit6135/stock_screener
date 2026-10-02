# User guide

## What this application does

Stock Screener is a local-first research and portfolio-operations application.
It stores market/reference data, calculates named strategy research, maintains
an event-sourced portfolio ledger, and prepares reviewable action proposals.
It is not an unattended trading system: portfolio mutations and broker actions
remain explicit, guarded operations.

## First-time setup

1. Create and activate the project environment, then start the application as
   described by the repository's runtime instructions.
2. Open `/` in a browser. The Home page is the portfolio read model; it does
   not invent valuation history when no saved valuation exists.
3. Use **Kite access** only to authenticate an explicitly configured account.
   Secrets and access tokens remain server-side and must never be pasted into
   a browser form, log, issue, or wiki page.
4. On Home, create a local ledger account with an account ID and opening cash.
   Importing broker holdings and account authentication are separate guarded
   workflows; a broker receipt is not treated as an executed fill.

## Daily operating sequence

1. On **Universe**, check the current NIFTY 500 snapshot. A same-day refresh
   can correctly reuse an immutable snapshot rather than manufacture a change.
2. On **Pipeline**, submit a date range manually. Monitor durable stages and
   worker state; retry only a failed stage and cancel only a selected pipeline.
3. On **Rankings**, choose a named strategy and ranking week. Both retained
   strategy branches are available independently of the portfolio context.
4. On **Actions**, inspect proposals for the intended account and action date.
   Read the rationale, decision/next-session data, and guard error before an
   approval. Daily/universe exits use the approved next-session AMO path;
   protective-stop handling remains distinct.
5. Record verified fills and dated capital transfers through their owning
   account APIs. Re-open Home to refresh valuation, holdings, XIRR and journal
   evidence.

## Reading returns and risk

- **Equity** is cash plus priced open holdings at the requested as-of date.
- **XIRR** uses investor cash flows and the current valuation. It may be absent
  when there is not enough cash-flow basis; absence is not a zero return.
- **Stale prices** mean the latest stored bar is older than the requested date.
- **Trailing/hard stops** are derived risk read models. They are not evidence
  that a broker order filled.
- **Capital transfers** change invested capital, not trading profit.

## Safety checklist

- Confirm account ID, strategy/revision, ledger version and action date before
  approving or processing an action.
- Treat a rejected guard response as an operational stop, not a UI glitch.
- Keep API keys, secrets, access tokens and browser session material private.
- Use saved reports for replay review; do not infer a completed fill from a
  missing next-session opening price.

For detail, continue with the [wiki](wiki/README.md).
