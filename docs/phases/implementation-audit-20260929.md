# Phase implementation audit — 2026-09-29

This is a preliminary audit of the current working tree, not phase completion
evidence. Scope and treatment of pre-existing staged/unstaged changes are pending
user clarification. Requirements examined: `Overhaul_Plan.md` and the seven
`docs/phases/phase*.md` plans. No live broker operations were performed.

## Reproducible baseline

Command (repository root, Windows PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .phase-audit-tests
```

Result: **308 passed, 15 failed**, 24.32 seconds. Temporary fixtures use isolated
databases. Existing application databases and credentials were not inspected.

## Phase findings

| Phase | Observed implementation | Open findings / required acceptance work |
| --- | --- | --- |
| 1: DAG and logging | Central operation validation, recursive hashes, revision-aware cache, persisted progress and quality events exist. Phase-specific tests pass in the baseline. | Phase documentation still has unchecked entry/exit checks and incomplete prior full-suite evidence. Confirm all acceptance items individually; a passing phase test file alone does not establish completion. |
| 2: Universe and market data | Daily snapshots, as-of lookup, NSE instrument resolution, six benchmarks and exit-eligibility storage exist. | `MarketRefreshPlanner.schedule` unions all held IDs into regular refresh; held exit-only instruments bypass its exclusion. This violates the single next-session exception. `PipelinePreparation.run` fetches one selected snapshot's members across the entire historical range rather than integrating historical membership and explicit exit-only coverage. Snapshot/re-entry lifecycle and every ingestion entry point need behavioral verification. Five baseline refresh tests fail; three still expect the retired fixed-universe contract. |
| 3: Corporate actions | Detection, temporary adjustment, actionable retry and provider replacement paths exist. | RIGHTS/DEMERGER verification can transition to VERIFIED without persisting fetched provider history. `_check_anomaly` uses a fixed constant rather than configurable threshold. Split/bonus verification should validate provider records at its boundary: the baseline fixture missing volume currently raises `KeyError`. Validate incomplete response and crash/retry paths without inventing missing market data. |
| 4: Strategies and replay | Two named YAML strategies, factor percentile storage and separate event jobs exist. | `load_snapshot_universe` selects the end-date snapshot, filters to EQ, and applies it backwards. `simulate` has no per-session universe membership contract and waits for a later valid open when an exit open is missing. Both contradict explicit requirements. Named runtime lookup does not itself migrate persisted legacy strategy/job/proposal ownership. `record_lineage` uses INSERT OR REPLACE and its test explicitly expects metadata to be overwritten. Audit frozen publications, stage reuse, both replay paths and ownership-scoped retirement cleanup. |
| 5: Portfolio and accounts | Broker accounts, linked ledgers, whole-quantity setup validation, imported opening lots, AMO intents and trade posting exist. | `PortfolioSync` creates discrepancy storage but implements no discrepancy detection/review commands or verified split/bonus reconciliation. Manual pipeline payloads have no operated broker-account/strategy sync context. Setup does not derive/persist imported strategy stops. One setup test lacks the broker/market fixtures now required by implementation. Gateway submission raises `KeyError` for an order without `order_id`; validate its input contract and stable receipt tag. |
| 6: Risk and returns | Versioned limits, durable reservations, managed ledger projection, external cash flows and imported-cost XIRR exist. | Review aggregate managed-account scope, pending/partial-fill reservation transitions, broker buying power, flow-adjusted guards and unavailable valuation inputs with behavior tests. Current valuation explicitly returns unavailable day-P&L for setup-day imports and leaves entry stops unset. Two baseline capital-flow tests omit the now-required reason. The positional action/replay sizing test expects fees in live sizing, contrary to the plan's live-cost exclusion; preserve separate live/backtest expectations. |
| 7: UI | Eight pages, theme assets and API/SSE scripts exist; route tests pass. | Home creates a generic empty ledger rather than providing account-scoped broker authentication and selected/all-quantity import. Reconciliation-review and capital-transfer controls are missing. Settings exposes risk JSON and revision readback but not the complete editable strategy/cash workflow. Route rendering is insufficient evidence for browser interaction, keyboard/mobile behavior, both themes and stream lifecycle. README links deleted documents and describes retired NSE/BSE/fixed-universe behavior. |

## Baseline failures

1. `test_broker_execution.py::test_kite_gateway_fails_closed_on_kill_switch_and_allowlists`
2. `test_market_coverage.py::test_refresh_schedules_only_fixed_universe_holdings_and_benchmark`
3. `test_market_coverage.py::test_refresh_refuses_to_download_before_fixed_universe_is_built`
4. `test_market_coverage.py::test_refresh_refuses_partial_universe_rows_without_completed_build`
5. `test_parity_assessment.py::test_pipeline_enforces_market_data_and_child_bar_jobs`
6. `test_phase2_behavioral.py::TestRefreshPlannerPhase2::test_refresh_includes_all_six_benchmarks`
7. `test_phase2_behavioral.py::TestRefreshPlannerPhase2::test_refresh_excludes_exit_only_instruments`
8. `test_phase3_corporate_actions.py::TestKiteVerification::test_verify_transitions_self_adjusted_to_verified`
9. `test_phase5_portfolio.py::test_account_scoped_setup_and_reconciliation`
10. `test_portfolio_performance.py::test_calculate_xirr`
11. `test_portfolio_web.py::test_manual_fill_lifecycle`
12. `test_research_bulk_rebuild.py::test_bulk_rebuild_calculates_each_stage_and_persists_range`
13. `test_research_bulk_rebuild.py::test_bulk_rebuild_accepts_a_range_before_strategy_warmup`
14. `test_strategy4_integration.py::test_signals_are_reused_only_for_identical_inputs`
15. `test_strategy4_integration.py::test_proposals_and_replay_size_competing_entries_after_fees`

Several failures reflect obsolete fixtures/interfaces. Update those only against
confirmed requirements while preserving their behavioral coverage; do not relax
implemented safety validation or restore retired runtime behavior to make tests
green. Existing tests also leave important phase gaps uncovered.

## Clarifications requested

1. Are the seven phase files and master plan the complete current scope?
2. Should implementation build on the extensive existing working-tree changes,
   or must any of those changes be excluded?

No existing source edits were made during this audit. Repairs and final
acceptance remain outstanding; none of the phases is newly certified complete.
