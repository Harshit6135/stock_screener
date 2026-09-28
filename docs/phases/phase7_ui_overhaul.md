# Phase 7: Carbon Emerald UI, Complete API Wiring and Functional Acceptance

> Status: Plan only. Implementation requires explicit user approval.
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md).
> Dependencies: All backend phases 1–6.
> Numbered tasks: 19.

## Confirmed Scope

Port active views into Jinja templates without losing either strategy. Include account/day-0/sync/review/capital/AMO/guard flows, both ranking patterns, universe history, index sparklines and structured logs. Preserve actual account-path APIs and existing SSE transport. No demo-only placeholders or line-count acceptance gates.

New modules are identified at their introduction; phase-specific test files are planned additions. Other file names are existing integration targets. Numbered retained-strategy names appear only to identify migration sources; implemented runtime/config/UI uses momentum and positional_trend_following. Tests and migrations described here are future approved implementation work, not actions performed during plan review.

## Entry Checks

- [ ] Backend account/universe/ranking/risk/AMO/readback contracts pass tests.
- [ ] Inventory actual dashboard routes, portfolio/account endpoints and template/static setup.

## Exit Checks

- [ ] All pages render and complete intended actions using actual APIs.
- [ ] Both rankings, day-0 empty/imported setup, account/strategy context and immutable backtest reports work.
- [ ] Theme/keyboard/mobile/stream lifecycle and error states are verified.
- [ ] Old assets are removed only after replacement behavior passes.

## Task 7.1: Inventory routes, payloads and assets

**Files:** run.py; src/application/dashboard_web.py; src/application/portfolio_web.py; src/application/broker_web.py; src/application/pipeline_web.py; templates/; static/.

1. Map every active widget/action to owning endpoint/request/response; compare old dashboard feature mapping in master.
2. Record current /api/v2/portfolio/accounts/{account_id}/valuation, /summary, /valuation/history, /journal, /ticker and /ticker/stream contracts.
3. Identify old inline HTML/scripts and dependencies; do not assume /holdings, /equity-curve or browser WebSocket endpoints exist.

**Acceptance:** Per-page API matrix includes actual auth/role requirements and all features.

## Task 7.2: Implement Carbon Emerald CSS tokens

**Files:** static/css/carbon-emerald.css (new).

1. Use master dark/light colors, Inter, Material Icons Round, card elevations, 64px sidebar and localStorage preference.
2. Style tables/forms/buttons/cards/modals/chips/status/error/loading states and responsive breakpoints.
3. Add focus-visible/keyboard labels, contrast and reduced-motion handling; no arbitrary required CSS line count.

**Acceptance:** Dark/light styles cover every page and interactive state.

## Task 7.3: Create shared Jinja layout and common client helpers

**Files:** templates/base.html (new); static/js/common.js (new).

1. Render sidebar/topbar/theme toggle, navigation including /logs and per-page head/script blocks.
2. Restore theme before first paint; persist across page navigation.
3. Create fetch/error/status helpers and modal accessibility/lifecycle utilities; use textContent for provider/user labels.
4. Provide explicit account/strategy context shared by relevant pages, never secret data.

**Acceptance:** Base renders through Flask; theme/focus/error helpers pass browser smoke checks.

## Task 7.4: Replace root and legacy page routing

**Files:** src/application/dashboard_web.py; run.py.

1. Serve / as home template instead of retaining run.py root redirect.
2. Render /actions, /pipeline, /rankings, /universe, /backtest, /settings and /logs templates.
3. Redirect legacy /app and /portfolio to their new destinations without duplicate Flask route conflicts.
4. Use Flask template/static resolution from real app root and preserve API owning blueprints.

**Acceptance:** Route tests verify home/new pages/legacy redirects and no inline HTML rendering remains.

## Task 7.5: Build home portfolio and returns

**Files:** templates/home.html (new); static/js/portfolio.js (new); src/application/portfolio_web.py.

1. Render index carousel, account/strategy context, summary metrics, equity/drawdown, holdings, journal, distribution and top rankings.
2. Map real valuation/history/summary payloads and expose derived stops plus existing protective timing.
3. Show original costs/dates, carried gains, day P&L and primary portfolio return/XIRR including imported history.
4. Show allocated cash and capital-event linkage; avoid presenting setup value as today gain or fabricating prior equity history.

**Acceptance:** Empty/imported profitable/loss-making portfolio fixtures render all metrics accurately.

## Task 7.6: Implement day-0 account/setup modal flow

**Files:** templates/modals/add_account_modal.html; templates/modals/import_holdings_modal.html; static/js/accounts.js (new); templates/home.html; templates/settings.html.

1. Create/validate/re-login account using owning account auth routes with server-held secrets.
2. Fetch holdings, explicitly select stocks, capture purchase dates and configured cash; entire selected quantities import.
3. Allow none-selected completion; display derived strategy stops and resulting setup status.
4. Do not reopen selection during ordinary sync; failed create/validate/import must show actual error instead of success.

**Acceptance:** Browser checks cover both selected and empty setup, failed auth and repeated refresh.

## Task 7.7: Build full index carousel

**Files:** static/js/index_carousel.js (new); src/application/market_web.py; templates/home.html.

1. Read /api/v2/market/indices/quotes and add bounded historical index readback for last 30 trading sessions.
2. Render six cards with LTP/change/freshness plus sparklines, auto-scroll and pause-on-hover/focus.
3. Quote polling reads existing live cache; use stable identity and preserve empty/error/stale states.
4. Clean up timers/listeners on navigation; do not invent a browser WebSocket payload.

**Acceptance:** All six fixture indices show quotes/history and carousel controls work.

## Task 7.8: Build proposal, AMO and protective-action views

**Files:** templates/actions.html; templates/modals/buy_modal.html; templates/modals/sell_modal.html; templates/modals/approve_modal.html; static/js/actions.js.

1. Keep generation, review/approve/reject/process, manual intents, cash projections and both strategy options.
2. Show reason/decision date/next session, AMO variety/status and actual fill time/price for approved daily/universe exits.
3. Show existing protective-stop execution separately; Choice A is not replaced by delayed AMO.
4. Preserve account/strategy/ledger/config version in approval/process payloads and show guard rejection errors.

**Acceptance:** End-to-end mocked proposal approval submits proper AMO or existing protective path without wrong-account dispatch.

## Task 7.9: Build reconciliation and capital-event review

**Files:** templates/home.html; templates/actions.html; templates/modals/capital_event_modal.html; static/js/portfolio.js; static/js/actions.js.

1. Trigger sync with explicit account/strategy and display auto-verified fills/split/bonus audit history.
2. Show unverified discrepancies with review/accept/reject and source/version evidence.
3. Provide dated deposit/withdrawal input with reason/configurable amounts and event history.
4. Refresh valuations/returns on confirmed mutation; never treat broker receipt as fill or added cash as profit.

**Acceptance:** Review/capital browser checks validate errors, idempotency and metric updates.

## Task 7.10: Build pipeline worker/progress page

**Files:** templates/pipeline.html; static/js/pipeline.js.

1. Port step controls and worker start/stop/status/work-once plus job inspector.
2. Show pinned universe/reused snapshot, prerequisite stages, both strategy branches and explicit portfolio sync context.
3. Consume existing structured SSE/job events with cursor reconnect, cancellation/retry and stage error reporting.
4. No automatic scheduler/hidden timed pipeline launch is introduced.

**Acceptance:** Manual run trace and reconnect/retry UI match actual backend stage state.

## Task 7.11: Build both ranking pattern views

**Files:** templates/rankings.html; static/js/rankings.js.

1. Use named strategy selector; factor strategy shows factors/percentiles/composite score and event strategy shows event/ADX/ADTV metrics.
2. Use actual date/week/revision selection and pagination; both pipeline results remain accessible regardless of synced strategy.
3. Show source snapshot/market/code lineage and anomalous stock flags without excluding rows.

**Acceptance:** Factor and event fixtures render different appropriate columns and revision history.

## Task 7.12: Build universe history/diff/refresh page

**Files:** templates/universe.html; static/js/universe.js (new).

1. Load current members/series/industry/last refresh and paginated snapshot history.
2. Select two snapshot IDs for additions/removals diff; render source date/hash and member count.
3. POST manual refresh job and show same-day reused identity rather than a fake changed snapshot.
4. Show excluded-member exit-only coverage distinctly from current membership.

**Acceptance:** History/diff/refresh and error paths use real universe endpoints.

## Task 7.13: Build backtest replay and immutable report page

**Files:** templates/backtest.html; static/js/backtest.js.

1. Port both strategy parameter/revision selection, saved-run list and report/fill readback.
2. Show as-of membership assumptions, next-open compulsory exit timing and existing protective fill behavior.
3. Saved results remain unchanged when new replay/market refresh runs; removed-strategy results no longer appear.
4. Missing-opening fallback is backlog; display validation diagnostic instead of a made-up completed fill.

**Acceptance:** Saved fixture checksums and fill dates/reasons remain consistent through UI refresh.

## Task 7.14: Build settings and configurable guard editing

**Files:** templates/settings.html; static/js/settings.js (new); src/application/strategies_web.py.

1. Wire account-specific auth/re-login/status, strategy YAML/revision editor and theme selection.
2. Expose existing strategy parameters separately from global managed-portfolio guard settings.
3. Validate settings and display revision/config identity; starting cash and launch strategy are user inputs, never fixed ₹5 lakh.
4. Keep secrets out of rendered state/read APIs and show expired session/rejected edit responses.

**Acceptance:** Settings changes preserve algorithms and update versioned configuration through real APIs.

## Task 7.15: Build structured log and quality viewer

**Files:** templates/logs.html; static/js/logs.js (new); src/application/web.py; src/application/market_web.py.

1. Filter persisted events by job/stage/account/strategy/severity and display quality/anomaly/refresh evidence.
2. Use reconnectable SSE progress and paginated history; redact secret fields.
3. Show automatically resolved ex-date monitoring alongside kept historical diagnostics.

**Acceptance:** Filter/cursor/live/error tests prove logs are persisted and not merely browser console text.

## Task 7.16: Preserve portfolio SSE lifecycle

**Files:** static/js/portfolio.js; static/js/common.js; src/application/portfolio_web.py.

1. Reuse current ticker/stream SSE transport; live toggle connects/disconnects explicitly.
2. Cancel old streams/requests when account/strategy changes and ignore stale responses from previous context.
3. Update live valuations without confusing quote price with broker fill or persisted backtest data.

**Acceptance:** Account-switch/reconnect/toggle browser checks show no duplicate stream or wrong-account update.

## Task 7.17: Remove replaced UI assets after verification

**Files:** templates/dashboard.html; static/css/dashboard.css; static/js/index_ticker.js; static/codebase_flowcharts.html; src/application/dashboard_web.py.

1. Verify all replacement features and routes first, then delete master-listed obsolete assets.
2. Remove inline page HTML/embedded page JS now represented by templates/modules.
3. Audit references/imports and keep API contracts; do not use a <300-line limit as correctness gate.

**Acceptance:** No served page depends on deleted assets; templates/static requests resolve.

## Task 7.18: Write functional route/API/browser coverage

**Files:** tests/test_phase7_ui.py; tests/test_dashboard_web.py; tests/test_portfolio_web.py; browser validation.

1. Test every page/legacy redirect and required API payload/ownership/error contract with mocked backend data.
2. Cover dark/light persistence, keyboard/modal flow, mobile layout, charts, both ranking patterns, day-0 none/import, sync review and AMO status.
3. Cover capital/returns, stream account switching, pipeline progress, universe reuse, logs and immutable backtest views.
4. No pass-only assertions or manual visuals substituted for functional behavior.

**Acceptance:** All intended workflows verified in both themes without console errors.

## Task 7.19: Run final integrated acceptance

**Files:** tests/; run.py; docs/phases/README.md.

1. Run relevant UI/API/integration tests and full suite; compare recorded baseline.
2. Perform browser functional/visual inspection of all eight pages using non-live fixtures.
3. Trace fresh setup → manual universe/data/both rankings/sync → proposals → approval → mocked AMO/actual fills → capital events/returns.
4. Record phase exit evidence; live deployment/arming remains separately gated.

**Acceptance:** All backend/UI exit checks and zero-new-failure evidence are complete.
