# Phase 6: Existing Strategy Rules, Global Managed-Portfolio Guards and Returns

> Status: Plan only. Implementation requires explicit user approval.
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md).
> Dependencies: Phase 5.
> Numbered tasks: 11.

## Confirmed Scope

Choice A: preserve existing protective/hard-stop execution; after-daily-analysis/universe exits use approved next-session AMO. Preserve each strategy sizing/stop/trailing rules. Global configurable guards aggregate only system-managed holdings/cash, and stop/universe exits override minimum holding period. Include imported original purchase history in portfolio returns/XIRR.

New modules are identified at their introduction; phase-specific test files are planned additions. Other file names are existing integration targets. Numbered retained-strategy names appear only to identify migration sources; implemented runtime/config/UI uses momentum and positional_trend_following. Tests and migrations described here are future approved implementation work, not actions performed during plan review.

## Entry Checks

- [ ] Typed imported/fill/corporate-action/capital events and account/session ownership are available.
- [ ] Capture current strategy risk/stop regressions and valuation/risk projections.

## Exit Checks

- [ ] Both retained strategy algorithms remain unchanged through integration.
- [ ] Configured global guards work at proposal and final submission with actual reservations.
- [ ] Unrelated broker holdings do not enter risk scope; buying power is separately checked.
- [ ] Imported returns and deposits are not today profit or duplicated XIRR flows.
- [ ] Choice A protective execution and AMO daily exits remain separate.

## Task 6.1: Capture and preserve strategy risk contracts

**Files:** src/application/action_jobs.py; src/application/strategy_runtime.py; src/application/positional_trend.py; retained strategy YAML; existing stop/sizing tests.

1. Document existing Momentum and Positional sizing, initial stop, trailing/hard-stop, rounding, warmup and cash inputs.
2. Retain current strategy formula/rules; remove obsolete plan snippets proposing one universal formula.
3. Carry named strategy and separately allocated cash into each calculation; preserve configurable existing strategy values.

**Acceptance:** Before/after fixtures match quantities/stops/exits for unchanged strategy input.

## Task 6.2: Persist independent global portfolio configuration

**Files:** src/execution_gateway/risk_guard.py (new); src/execution_gateway/ledger.py; src/application/portfolio_web.py.

1. Store versioned enabled/limit settings for order value, daily loss, concentration, sector exposure, max positions, minimum holding period, reserve, heat and drawdown.
2. Values are user-editable configuration, not launch-specific capital or unapproved hardcoded example values.
3. Scope guard state to managed system holdings and allocated cash; exclude unrelated broker holdings but retain separate actual broker buying-power checks.
4. Expose validated read/update APIs with version/date and include config version in proposal/submission evidence.

**Acceptance:** Settings roundtrip, invalid values and ownership/version conflicts are tested.

## Task 6.3: Build managed risk state from real projections

**Files:** src/execution_gateway/risk_guard.py; src/execution_gateway/ledger.py; src/application/action_jobs.py; src/application/portfolio_web.py.

1. Read projection cash/open_lots, verified managed broker adjustments, current valuations and applicable strategy stop projections.
2. Reuse stop_based_risk convention max(0, mark_value - stop*units) for managed open risk; preserve strategy nominal risk calculations separately.
3. Use current sector artifact/metadata mapping and existing normalization; missing data for an enabled check is explicit validation failure, never assumed zero.
4. Include persisted pending/partial order quantities/reservations and remove reservations only on known cancel/fill/rejection.

**Acceptance:** Risk state excludes unmapped holdings and cannot omit pending quantities or unavailable enabled inputs.

## Task 6.4: Enforce proposal-batch and submission guards

**Files:** src/application/action_jobs.py; src/execution_gateway/risk_guard.py; src/execution_gateway/broker.py.

1. Project each accepted BUY and remaining reservations before reserve/heat/concentration/sector/positions/order-value checks.
2. Use Decimal/Money and existing strategy sizing; do not force one share above affordable/risk budget.
3. Revalidate current ledger/order/config revision immediately before every broker call, including manual orders/AMOs/retries/stale approvals.
4. Use persistent reservation/state transitions under the single-writer/transaction contract to prevent parallel orders both spending the same cash.
5. Emit redacted violation evidence; buy-only guards never delete required SELL proposals.

**Acceptance:** Fixtures cover aggregate overspend, concurrent intents, partial fills, config changes and stale approvals.

## Task 6.5: Implement exit precedence and preserve Choice A

**Files:** src/application/action_jobs.py; src/application/intraday_alerts.py; src/execution_gateway/risk_guard.py; src/application/backtest_jobs.py; src/application/positional_trend_backtest.py.

1. Classify protective stop/hard-stop separately from daily-analysis and universe_exit reasons.
2. Stop-loss and universe_exit override minimum holding period; buy-related caps never suppress protective/compulsory sells.
3. Keep existing regular/protective execution and backtest stop-fill/gap behavior; do not route an intraday stop breach to tomorrow AMO.
4. After-daily-analysis/universe exits use next trading session open in replay and AMO in live flow.
5. Keep the retired midweek next-open stop rule disabled; do not accidentally reintroduce it.

**Acceptance:** Explicit intraday breach fixture retains existing fill timing; daily/universe fixture uses next session.

## Task 6.6: Build daily-loss and drawdown guard inputs

**Files:** src/execution_gateway/risk_guard.py; src/execution_gateway/ledger.py; src/application/portfolio_web.py; src/application/portfolio_performance.py (new).

1. Persist valuation timestamps/managed scope and actual capital-flow dates; derive loss/drawdown from externally flow-adjusted managed equity rather than raw deposits/withdrawals.
2. Reuse applicable existing drawdown state/history and daily session boundaries; keep calculation evidence/peak/input revisions with guard results.
3. Do not reset an observed loss because cash was added or report a withdrawal as trading loss.
4. Unavailable/stale enabled guard inputs produce readable validation errors; no invented projection peak_value dictionary fields.

**Acceptance:** Deposit/withdrawal fixture changes cash but not falsely the measured trading loss/drawdown.

## Task 6.7: Implement portfolio return and XIRR cash-flow basis

**Files:** src/application/portfolio_performance.py; src/application/portfolio_web.py; src/execution_gateway/ledger.py.

1. Use imported quantity*original unit cost as dated historical investment input at supplied purchase dates, with explicit import provenance.
2. Use actual dated initial funding/deposits as investor outflows, actual withdrawals as inflows, and terminal managed equity as final inflow.
3. Do not count normal internal BUY/SELL fills as additional portfolio external flows; current valuation code does so and must be corrected.
4. Do not also count setup market value as a second contribution for imported holdings. Preserve cost-based realized/unrealized P&L and actual cash ledger.
5. Call shared _xirr/performance helper once per valuation and report basis/input dates; if required dates/values are invalid, return clear unavailable diagnostics rather than fabricated return.

**Acceptance:** Imported gain/loss, later sale, added cash and withdrawals calculate without double-counted flows.

## Task 6.8: Separate total P&L, day P&L and valuation history

**Files:** src/application/portfolio_performance.py; src/application/portfolio_web.py; src/execution_gateway/ledger.py.

1. Keep imported original cost/date and purchase-to-current total return; primary portfolio return/XIRR includes imported history.
2. Day P&L uses comparable previous-session value with external flows accounted for; accumulated imported gain is not day-zero profit.
3. Store setup market valuation as audit snapshot only; no invented daily equity curve before data exists.
4. Preserve checksum-verified historical valuation snapshots; new calculations declare basis/code revision.

**Acceptance:** A holding bought at 100 and imported at 120 retains total gain while today gain reflects only today movement.

## Task 6.9: Finalize configurable capital events

**Files:** src/execution_gateway/ledger.py; src/application/portfolio_web.py; src/application/portfolio_performance.py.

1. Use actual Ledger.record_cash_transfer and event API with version/idempotency, not fictional cash_transfer method.
2. Validate positive Money plus direction, effective date/time, reason and managed portfolio ownership.
3. Keep initial cash and later additions editable inputs, separate per strategy; no fixed ₹5 lakh default.
4. Expose event history and audit same-day/backdated input handling through validation, without rewriting existing fill chronology.

**Acceptance:** Duplicate transfer posts once and returned valuation/return inputs reflect correct effective date.

## Task 6.10: Preserve costs and backtest result immutability

**Files:** src/application/action_jobs.py; src/execution_gateway/broker.py; src/application/backtest_jobs.py; src/application/positional_trend_backtest.py.

1. Live accounting ignores taxes/transaction costs as master requires.
2. Keep 50-bps round-trip backtest cost convention; do not apply it twice to split buy/sell legs.
3. Old saved reports remain unchanged by new rules/price cache refresh; new run fingerprints include membership/exit/config/input revisions.

**Acceptance:** Cost and saved-run checksum regressions pass.

## Task 6.11: Verify risk, stops and return integration

**Files:** tests/test_phase6_risk.py; tests/test_atr_exit_rules.py; tests/test_intraday_alerts.py; tests/test_portfolio_web.py; tests/test_broker_execution.py.

1. Cover each configured guard, managed-only scope, minimum-period overrides, Choice A intraday timing, daily AMO, reservations and correct account/strategy.
2. Cover imported original-date XIRR, no internal trade double count, day P&L, flow-adjusted risk and transfer idempotency.
3. Run targeted/full tests; no live order submission and no new strategy formula.

**Acceptance:** All Phase 6 exit checks pass against baseline.
