# Phase 5: Broker Accounts, Day-0 Imports, Reconciliation and AMO Integration

> Status: Plan only. Implementation requires explicit user approval.
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md).
> Dependencies: Phase 2 and Phase 4.
> Numbered tasks: 16.

## Confirmed Scope

Portfolio sync explicitly names the operated strategy; rankings still run for both. Maintain separate managed cash per broker-account/strategy portfolio. Day-0 import is optional, imports entire selected quantities, uses supplied acquisition dates and derives stops. Verified fills/split/bonus changes auto-reconcile; unverified differences require review. Credentials stay in local Git-ignored SQLite.

New modules are identified at their introduction; phase-specific test files are planned additions. Other file names are existing integration targets. Numbered retained-strategy names appear only to identify migration sources; implemented runtime/config/UI uses momentum and positional_trend_following. Tests and migrations described here are future approved implementation work, not actions performed during plan review.

## Entry Checks

- [ ] Named strategies/universe instruments and current ledger/projection interfaces are available.
- [ ] Inventory existing broker controls, account routes, auth sessions and fill reconciliation.

## Exit Checks

- [ ] Broker session identity and managed strategy ledger identity are explicitly linked, not silently conflated.
- [ ] Day-0 none-selected setup creates empty holdings with configurable cash.
- [ ] Selected imports preserve quantity/cost/date/return history without reducing cash as a fictitious BUY.
- [ ] AMO receipt is not a fill; normalized broker trades post idempotently.
- [ ] Automatic/review reconciliation paths preserve append-only events and audit provenance.

## Task 5.1: Separate broker account and strategy portfolio identity

**Files:** src/execution_gateway/ledger.py; src/execution_gateway/kite_accounts.py (new); src/application/portfolio_sync.py (new).

1. Add kite_accounts for broker account name/API credentials/token/broker user/validation/setup timestamps.
2. Add strategy_portfolios linking broker_account_id, strategy_id and ledger_account_id; enforce unique broker-account/strategy ownership and retained named IDs.
3. Keep API account_id ledger identity where existing /portfolio/accounts contracts already use it; new sync/auth payloads explicitly identify broker account plus strategy.
4. Create relevant ledger parent and link rows atomically in valid FK order. Migrate existing account references without deleting ledger events.

**Acceptance:** Fresh/upgrade tests prove separate strategy cash and correct broker-session routing.

## Task 5.2: Persist local credentials and verify Git exclusion

**Files:** src/execution_gateway/kite_accounts.py; src/application/sqlite.py; .gitignore; src/application/security.py.

1. Store API key/secret/access token only in local SQLite using parameterized statements.
2. Verify *.db/*.sqlite/*.sqlite3 and journal/WAL/SHM paths are excluded; check whether credential-bearing files are already tracked before introducing records.
3. List/status responses omit secrets and tokens; redaction covers requests/errors/job events.
4. Keep market-data credential profile independent and preserve existing live-execution disabled/kill-switch controls.

**Acceptance:** Ignore/redaction tests pass; no credential enters a tracked file or public response.

## Task 5.3: Implement account-specific authentication lifecycle

**Files:** src/execution_gateway/kite_accounts.py; src/application/kite_auth.py; src/application/kite_web.py; src/application/composition.py.

1. Create/list account, obtain login URL, associate callback/request token with explicit account and validate broker profile/user.
2. Generate/store session on server; persist validated/session-expired state and re-login route.
3. Select client by broker_account_id for reads and writes; no first-account fallback for mutation.
4. Failed validation never reports ACTIVE; duplicate requests/retries preserve valid existing account relationships.

**Acceptance:** Mock successful/failed/expired identity flows and account isolation.

## Task 5.4: Expose day-0 broker holdings selection

**Files:** src/application/portfolio_sync.py; src/application/portfolio_web.py; src/application/kite_accounts_web.py (new).

1. GET eligible broker holdings through the selected session and stable ISIN instrument resolver.
2. POST setup accepts broker_account_id, named strategy_id, selected instruments, user purchase dates and configured opening cash.
3. Import entire reported quantity of selected holdings at reported average cost; user dates supplement missing broker acquisition history.
4. Allow an empty selection and persist setup completion, so ordinary later sync cannot repeat the import prompt.
5. Unselected holdings remain outside managed holdings, universe exits and risk aggregates.

**Acceptance:** API fixtures cover selected/all-quantity/none-selected/invalid-date/repeated setup.

## Task 5.5: Add explicit opening-position accounting event

**Files:** src/execution_gateway/ledger.py; src/portfolio_accounting/api.py.

1. Add idempotent OPENING_POSITION_IMPORTED event with managed ledger/strategy/instrument, quantity, unit cost, acquisition date, import effective time and broker provenance.
2. Extend pure projection/replay to seed imported lots without creating FILL_RECORDED or spending opening cash.
3. Preserve original date for holding period/trade journal and total cost for P&L; current setup valuation is distinct audit metadata.
4. Repeated import key must return prior version only for identical payload; conflicting replay of same key rejects.

**Acceptance:** Imported existing gain/loss, later FIFO sell and unchanged configured cash project correctly.

## Task 5.6: Derive day-0 strategy stops

**Files:** src/application/action_jobs.py; src/application/portfolio_sync.py; src/application/strategy_runtime.py; src/application/positional_trend.py.

1. Call each strategy existing initial stop/risk model with its required bars/inputs for selected holdings.
2. Persist entry/current trailing/hard-stop metadata through existing risk projection contract extended for named strategy identity.
3. Do not import arbitrary user stop overrides or replace ATR/Supertrend/strategy-specific formulas with a common percentage.
4. Expose derived stops and resulting proposals; retain Choice A protective-stop execution thereafter.

**Acceptance:** Regression fixtures derive valid Momentum and Positional stops without changing later trailing behavior.

## Task 5.7: Read complete broker portfolio/reconciliation inputs

**Files:** src/application/portfolio_sync.py; src/execution_gateway/kite_accounts.py.

1. Implement read-only holdings, positions, orders, order trades, margins and profile readers per selected account.
2. Reconcile only managed mappings and relevant strategy order IDs; reconcile settlement holdings/positions without double-counting the same stock.
3. Use real PortfolioProjection.cash/open_lots/realised_pnl object fields, never assumed dict positions.
4. Persist raw source evidence, account/strategy identity and comparison result for review.

**Acceptance:** Quantity/cost comparisons are stable across renamed symbols and settlement fixture variants.

## Task 5.8: Automatically reconcile verified fills and split/bonus changes

**Files:** src/application/portfolio_sync.py; src/execution_gateway/ledger.py; src/portfolio_accounting/api.py; src/application/corporate_actions.py.

1. Identify completed trades by broker trade/order ID and managed ownership; post actual partial/final fills once.
2. For a recognized verified split/bonus, append a CORPORATE_ACTION_APPLIED accounting event that adjusts managed quantities/unit cost and relevant stop price basis while preserving aggregate cost/purchase-date provenance.
3. Do not model share adjustments as BUY/SELL or external funding; update projection from typed events.
4. Deduplicate event/source identity and compare expected adjusted holdings before automatic correction.

**Acceptance:** Repeat sync cannot duplicate fills/shares or alter original investment cost/returns.

## Task 5.9: Persist unverified discrepancy review

**Files:** src/application/portfolio_sync.py; src/execution_gateway/ledger.py; src/application/portfolio_web.py.

1. Add reconciliation discrepancy records with type, before/observed state, source snapshot, explanation and review status.
2. Unverified external trades/unknown quantity/cost differences remain flagged without overwriting managed accounting.
3. Provide explicit review/accept/reject APIs; accepted corrections append a typed event with reviewer/reason/provenance, not direct ledger row edits.
4. Recheck ledger/source version before applying review to avoid stale/double correction.

**Acceptance:** Unverified changes await review and repeated/obsolete decisions cannot mutate accounting twice.

## Task 5.10: Add explicit portfolio sync to manual pipeline

**Files:** src/application/pipeline_jobs.py; src/application/composition.py; src/application/pipeline_web.py.

1. Register portfolio.reconcile-broker and require explicit account/strategy context for the operated portfolio.
2. Orchestrate sync after relevant corporate-action/market updates and before actions/risk readback; both ranking branches still run independently.
3. Persist sync job/result IDs in pipeline status and report discrepancies without silently converting them to fills.
4. Automatic switching/simultaneous operation remains backlog; no guessed active strategy mapping.

**Acceptance:** Every operated-portfolio manual run has one idempotent sync and both rankings.

## Task 5.11: Route broker operations by account and strategy

**Files:** src/execution_gateway/broker.py; src/application/broker_web.py; src/application/action_jobs.py; src/application/composition.py.

1. Persist broker_account_id/managed ledger ID/named strategy ownership on order intents and execution events.
2. Resolve gateway session from the linked account for submission/status/trades/cancel; validate proposal-account-strategy ownership.
3. Preserve enabled/kill-switch/allowlist controls and submission-unknown reconciliation-before-retry behavior.
4. Pass existing strategy state plus global managed-portfolio guards to Phase 6 validation.

**Acceptance:** Wrong account/strategy rejects before broker call; correct account fills update only its ledger.

## Task 5.12: Implement AMO intent and broker lifecycle

**Files:** src/execution_gateway/broker.py; src/application/action_jobs.py; src/application/broker_web.py.

1. Add intent/schema fields variety, exit_reason, decision_time and target_session; require amo for approved next-session/daily-analysis exits.
2. Stop hardcoding variety=regular in place_order; preserve regular/protective execution for Choice A.
3. Include variety/ownership/policy in idempotent command identity and cancellation/status API calls.
4. Use AMO submission after approval/guard validation; record actual broker fill time/price rather than promised exact backtest opening price.
5. Report broker rejection/unknown submission/partial fill; AMO receipt never spends cash or closes holdings.

**Acceptance:** Mocked next-session exits use amo; protective path remains unchanged; submit retry cannot duplicate order.

## Task 5.13: Normalize Kite status and trade fills

**Files:** src/execution_gateway/broker.py; src/application/portfolio_sync.py.

1. KiteExecutionGateway.order_status currently returns order_history, whereas BrokerOrderService.reconcile expects fills; fetch actual order_trades and construct the expected normalized fills collection.
2. Map trade ID, actual quantity/price/date/time and broker statuses, keeping AMO received/open distinct from COMPLETE.
3. Reconcile actual trade IDs idempotently, including partial fills; do not mark order filled when completed trade details are absent.
4. Preserve live zero cost/tax convention.

**Acceptance:** Adapter/service contract test catches missing-fill normalization and duplicate partial-fill posting.

## Task 5.14: Integrate capital/performance inputs

**Files:** src/execution_gateway/ledger.py; src/application/portfolio_web.py; src/application/portfolio_sync.py.

1. Record configurable initial cash funding at actual effective date and later cash transfers with reason/account/strategy/version/idempotency.
2. Retain imported original-cost/date inputs for primary portfolio return/XIRR; no extra setup market-value contribution for those holdings.
3. Separate actual cash transfer events, imported historical performance provenance and internal trading cash movements.
4. Phase 6 implements shared performance calculation and global guards; API fields distinguish total holding P&L, day P&L and portfolio return basis.

**Acceptance:** Imported profitable/loss-making holdings and added cash produce auditable nonduplicated return inputs.

## Task 5.15: Expose account/setup/sync/review API contracts

**Files:** src/application/portfolio_web.py; src/application/kite_accounts_web.py; src/application/broker_web.py; run.py.

1. Preserve existing /api/v2/portfolio/accounts/{account_id}/valuation, /summary, /valuation/history, /journal, /events, /cash-transfers and ticker/stream interfaces.
2. Add broker-account login/list/status and day-0 setup/sync/discrepancy-review routes in owning blueprints.
3. Use POST for imports/sync/review mutations; validate explicit account/strategy and return structured errors.
4. Wire factories/services and document real payloads for Phase 7 scripts; no secrets in browser payloads.

**Acceptance:** Route/API fixtures cover valid/invalid ownership, empty setup, re-login and discrepancy decisions.

## Task 5.16: Verify account, import, reconciliation and AMO flows

**Files:** tests/test_phase5_portfolio.py; tests/test_portfolio_accounting.py; tests/test_jobs_ledger_backtesting.py; tests/test_kite_profiles.py; tests/test_broker_execution.py.

1. Cover fresh/upgraded account links, local credential ignore/redaction, empty/full import, dates/cost/cash, derived stops and imported FIFO sale.
2. Cover verified/unknown reconciliation, split/bonus accounting, AMO variety, normalized actual fills, partial/duplicate/unknown submissions and account isolation.
3. Run targeted and full suite with broker/network mocks and disabled live execution.

**Acceptance:** All Phase 5 exit checks and zero-new-failure tests pass.
