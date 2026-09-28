# Phase Execution Guide

> Status: Consolidated plan; waiting for explicit implementation approval.
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md). The master governs conflicts.
> Phases: 7. Integrated numbered tasks: 98.

## Phase Sequence

| Phase | File | Tasks | Dependencies |
|-------|------|-------|--------------|
| 1 | [phase1_dag_logging.md](phase1_dag_logging.md) | 12 | None; coordinate shared market migrations with Phase 2 |
| 2 | [phase2_universe_market_data.md](phase2_universe_market_data.md) | 18 | None for design; integrate Phase 1 shared migrations before Phase 2 schema additions |
| 3 | [phase3_corporate_actions.md](phase3_corporate_actions.md) | 10 | Phase 1 and Phase 2 |
| 4 | [phase4_strategy_cleanup.md](phase4_strategy_cleanup.md) | 12 | Phase 1 and Phase 2; integrate Phase 3 cache contracts for corporate-action tests |
| 5 | [phase5_portfolio_accounts.md](phase5_portfolio_accounts.md) | 16 | Phase 2 and Phase 4 |
| 6 | [phase6_risk_management.md](phase6_risk_management.md) | 11 | Phase 5 |
| 7 | [phase7_ui_overhaul.md](phase7_ui_overhaul.md) | 19 | All backend phases 1–6 |

Phase 1/2 design may proceed independently, but shared migration/file integration is coordinated. Corporate-action and ranking branches then follow their prerequisites; account/risk work follows ranking interfaces. UI requires all backend contracts.

## Manual Runtime Sequence

1. Reuse the first daily universe snapshot or download/store it if absent.
2. Resolve current NSE instruments, series/tokens and six benchmarks.
3. Detect/verify corporate actions and retry SELF_ADJUSTED work.
4. Fetch eligible bars plus explicit next-session exit-only data; run quality checks.
5. Rebuild affected indicators and compute both named ranking branches.
6. Reconcile the explicitly identified broker account/operated strategy; verified fills/split/bonus auto-adjust and unverified changes await review.
7. Generate proposals using existing strategy rules plus configured managed-portfolio guards; user approval precedes AMO submission.

Worker threads process manually submitted work; no calendar scheduler is introduced. Portfolio sync strategy does not restrict either ranking branch.

## Confirmed Decisions

| Decision | Final requirement |
|----------|-------------------|
| Strategies | momentum / Momentum strategy; positional_trend_following / Positional trend following strategy |
| Migration | Rename active IDs/config/jobs/APIs/tests and preserve retained history integrity |
| Retirement | Remove benchmark-relative/early momentum runtime and historical backtesting data; keep shared inputs and retained outputs |
| Universe | First snapshot per day immutable; rerun skips/reuses and advances |
| Corporate actions | Temporary BONUS/SPLIT adjustment retries until verified Kite replacement; RIGHTS/DEMERGER monitoring only |
| Historical output | Rebuild indicators; preserve published historical percentile/score/rankings and saved backtests |
| Anomalies | Configurable 15% criterion; no exclusion/standalone buy block; ex-date resolution auto-completes monitoring |
| Portfolio | Day-0 optional full-quantity selection, user purchase dates, derived strategy stops, separate cash |
| Reconciliation | Every operated-portfolio manual run; verified fills/split/bonus automatic, unverified differences reviewed |
| Protective stops | Choice A: existing protective/hard-stop execution retained |
| Daily/universe exits | Approval → AMO for next session; replay next-session open, one extra exit-only price session |
| Risk | Existing strategy models retained; configurable global limits cover system-managed holdings/cash only |
| Minimum hold | Protective stop/universe exits override minimum holding period |
| Returns | Include imported original cost/date history; no setup-day gain or duplicate contribution; actual capital events dated |
| Credentials | Local SQLite, database/sidecars excluded from Git, no browser/log exposure |
| Configuration | Cash/strategy/parameters/guards editable; no fixed launch ₹5 lakh default |
| Costs | Ignore live taxes/costs; retain 50-bps round-trip backtest convention |
| UI | Carbon Emerald dark/light, eight pages including logs, real APIs/SSE and complete functional coverage |

## Deferred Backlog

- Automatic strategy switching, portfolio transition and simultaneous-strategy orchestration.
- Suspended/missing-next-session-open fallback. Current scope reports missing input; it does not invent a fill or silently choose another session.

## Implementation and Approval

Each task specifies file targets, sequential low-level steps and acceptance evidence. Existing interfaces are distinguished from planned new modules; test placeholders and unsupported pseudocode were removed. Master-to-phase ownership is listed in the master plan.

Implementation is not started. Obtain explicit user approval before any code/schema/data cleanup. During implementation, use temporary/mocked broker data for checks, preserve existing live controls, run the relevant tests and full-suite baseline comparison, and record phase exit evidence. No permission to arm or submit live orders is implied by approving code work.
