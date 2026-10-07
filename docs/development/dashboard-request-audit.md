# Dashboard request audit — 7 October 2026

This checks the requests in the conversation against the actual dashboard, its accounting and import workflows, the archived dashboard, and automated checks. It does not certify every possible broker document layout or execute real orders/research jobs.

## Corrections found during this review

- The dashboard still displayed CAGR, the long whole-account XIRR label, and a separate open-holdings XIRR tile. The dashboard now shows **XIRR** and **Realised XIRR** as its two annualized return tiles. XIRR includes account cash and external capital flows; Realised XIRR uses sold FIFO lots and recorded charges. Legacy API calculation fields remain available for compatibility, but are not shown as extra tiles.
- The compact market band displayed five research benchmarks, while the archived dashboard used NIFTY 50, NIFTY 100, NIFTY BANK and SENSEX. The display now follows the archived set. Quote collection additionally supports the BSE SENSEX display identity; research benchmarks remain available to research jobs.
- The holdings total label was still abbreviated to Invested. It now says Invested capital.

## Request-by-request check

| Request | Result and evidence |
| --- | --- |
| Build a demo before changing the dashboard | Demo remains in `docs/ui-demo`; production templates and workspace scripts implement the approved layout. |
| Improve layout and guide for every tab | Nine main pages render successfully. The handbook explains each tab's purpose, steps, terminology and next action. |
| Keep import guidance within import flows | Source/preparation/review instructions are in the import dialogs or expanded Account & imports panel. Missing accounting data and risk warnings remain contextual to their metrics. |
| Trigger a specific research job with its parameters | Research runs loads all 26 registered job definitions, parameter forms or an advanced JSON editor, submission/status/retry/cancel controls and full-pipeline mode. This review did not launch resource-consuming research runs. |
| Explain each job and link to its definition | `/guide/jobs` and per-job pages provide definitions, prerequisites, parameters, sample inputs and results; Research runs links to the selected definition. |
| Small index carousel matching the old dashboard | Slim 40-pixel single-line strip, continuous scrolling, pause on hover/focus, quote freshness and five-second refresh; original four index names restored by this audit. |
| Real live prices in holdings | Kite WebSocket service supplies real account-scoped quotes; the browser receives SSE updates to price, value, day P&L and unrealised P&L. An existing actual stream was CONNECTED during the audit; UI behavior also checked with controlled tick fixtures. |
| Intraday and historical charts | Fresh ticks update day P&L; equity and drawdown reconstruct from dated ledger events and historical prices. The intraday trace starts when monitoring starts; it is not a persistent reconstruction of the full trading day after reload. |
| Shared market-data token without mandatory portfolio broker binding | Shared-token Go live is implemented and tested. Auto-login opens a separate tab for missing/expired credentials; popup blocking has a visible login fallback. The actual shared session was ACTIVE during this review. |
| Manual refresh of selected account credentials | Refresh account credentials authorizes the linked broker account in a separate tab. If no account is linked, the connection flow collects the missing binding. |
| Invested Capital, absolute return and capital risk | Labels and metrics are present. Capital risk retains signed values when stops protect gains. |
| Portfolio risk floored at zero | Uses the sum of each displayed holding's positive capital risk, not a signed total that could cancel another holding's risk. Stops at or above cost contribute zero. Stop breaches remain separately alerted. |
| Old holdings columns and red/green values | Original 13 columns plus Details, centered tile cells, signed risk colors, gain colors, quote metadata and per-row live updates. |
| XIRR and Realised XIRR separately; remove CAGR | Corrected by this audit. The actual dated valuation returns both XIRR values. |
| Buy-side and sell-side charges on individual closed trades | FIFO allocates buy charges to sold units; remaining charges stay in open cost. Journal groups contain aggregate charges and component/source/lot details. Hover and click interactions are checked. |
| Batch contract notes, encrypted PDFs and DP statements | Multi-file PDF/CSV/XLSX preview/apply is generic and account-scoped. Passwords are not saved. The supplied newer Zerodha sample reconciles quantities and the ₹12.47 cash charge total. Unsupported layouts are flagged rather than guessed. |
| Exclude stocks outside this portfolio and avoid duplicate charges | Exact transaction matching, outside-row exclusion, conflict checks, component replacement and idempotency are tested. Estimated daily allocations retain outside trades in the allocation denominator before excluding them from application. |
| Match stocks with series/group suffixes | Shared symbol normalization covers recognized NSE series and BSE group suffixes. Original execution exchange and verified execution IDs handle BSE trades and historical ISIN differences. Eight previously disabled rows matched on a read-only recheck; five unrelated HDFCBANK rows remained excluded. Existing previews require regeneration. |
| Current and previous financial-year tax, portfolio only, cess, same-year loss offsets | Exactly two tiles. April–March years; requested short/long rates and exemption, 4% cess, same-year loss offsets. Known itemized deductible charges reduce estimated gains; STT/unitemized fees do not. Estimates assume the portfolio has the stated exemption available and omit surcharge. |
| Persistent generic accounting, not hardcoded portfolio data | Charges use account/trade component records, source provenance and audit events. Original trade events remain unchanged. Cash, cost basis, realised P&L, valuation, returns and tax read effective amounts. No account-specific fee constants are used. |

## Verification and remaining limits

All main page routes, guide routes and the selected account's dated valuation responded successfully. The valuation exposed both return fields, absolute return, capital/portfolio risk, recorded charges and two tax estimates. Automated coverage includes accounting, charge reconciliation, reference identity, market quotes, shared authentication, streaming and HTTP routes. DOM checks cover the two requested annualized return tiles, four archived indices, 14 holding cells, live values/colors and the charge import/detail flows.

After the corrections, 140 relevant tests passed. The restarted dashboard was checked over HTTP: XIRR and Realised XIRR are present, and CAGR/whole-account/open-holdings labels are absent. The existing live feed reconnected successfully. A real Kite quote refresh populated all four archived display indices, including BSE SENSEX, with no poller error.

The intraday chart retains only observations received during the current monitoring session. Index prices refresh through polling, independently of holdings' WebSocket stream. Popup policy can prevent an automatic tab from opening, requiring the visible login link. Open-lot reconciliations without verifiable purchase history and unsupported/refund document rows are flagged for review. These are explicit limits; a complete all-day replay, all broker layouts and end-to-end real order execution have not been claimed as implemented or tested.

## Historical curve follow-up

Portfolio imports now queue `portfolio.backfill-price-history`, collecting daily Kite history for current and closed ledger instruments into `market_bars`, independent of NIFTY 500 membership. The dashboard monitors completion and refreshes both curves. Missing-price stocks are excluded consistently from chart-only projections and explicitly listed; no ledger events or other account metrics are removed. Imported-position funding is adjusted only in that filtered projection. Recorded cash transfers remain included and drawdown is cash-flow adjusted.
