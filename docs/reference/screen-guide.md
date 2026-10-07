# Screen-by-screen guide

Choose a tab below to understand its purpose, main actions, and next step.

## Portfolio

Understand what you own, how it is performing, and which positions need attention.

### How to use it

1. Choose an account and valuation date. Review the index carousel and portfolio totals.
2. Use Go live with today’s date and an active shared market-data Kite session. Quote streaming does not require a portfolio broker binding; holdings imports and orders still use the portfolio account’s credentials. Fresh broker quotes update holding prices, market values, day P&L, unrealised P&L, and the intraday chart.
3. Use the holdings search. Scroll horizontally for stop thresholds and quote times; open Details for the risk basis.
4. Historical equity and drawdown use dated transactions and stored prices, separately from live ticks.
5. Use Account & imports to connect Kite or import holdings and tradebook history. Import instructions appear inside those flows.
6. Open Trade review for positions that breach stops.

### Terms

- **Portfolio value:** Market value of holdings plus available cash.
- **Unrealised gain:** Gain or loss on positions still held.
- **XIRR:** Annualised account return using opening capital, dated deposits and withdrawals, and portfolio value including cash. Buys and sells are internal account movements.
- **Realised XIRR:** Annualised return on sold FIFO lots, using buy costs and net sale proceeds including recorded charges. Open holdings and idle cash are excluded.
- **Portfolio risk:** Sum of positive capital risk across displayed holdings, floored at zero for each holding.
- **Capital risk:** Purchase cost minus value at trailing stops; negative when the stop locks in a gain.

[Open Portfolio](/)

### Portfolio table, risk and tax

Holdings use centered tile cells in the former dashboard order. Capital risk is purchase cost minus value at trailing stops and can be negative. Portfolio risk sums the positive capital risk of each displayed holding and floors each at zero. A stop breach remains an alert even when portfolio risk is zero. Quote timestamps, provenance and breach status are available through Details.

The two financial-year tax tiles use net realised gains from sold units in this portfolio only, with eligible losses offset within each financial year. Short-term losses can offset short- and long-term gains; long-term losses offset only long-term gains. Losses are not carried between years. Current holdings and unrealised gains are excluded; a partial sale taxes only the units sold. Changing current market prices does not change the tax estimate. Short-term holdings of 12 months or less use 20%; longer holdings use 12.5% on gains above the annual ₹1.25 lakh exemption. Both include 4% cess, assume the exemption is available and exclude surcharge. Known itemized brokerage, exchange, clearing, SEBI, GST, stamp duty and DP expenses reduce the gain estimate. STT and unitemized fees are excluded from deductions. Missing charges make estimates incomplete. The dashboard shows XIRR and Realised XIRR separately; CAGR and the additional open-holdings XIRR tile are omitted. Realised XIRR includes all recorded buy and sell fees. The exclusion of STT follows the [Income Tax Department's capital-gains computation rules](https://www.incometaxindia.gov.in/w/section-48-48).

On app open, a missing or expired shared session opens market-data Kite login in a separate tab; a visible login link is available if popups are blocked. Refresh account credentials beside Go live starts manual login for the selected portfolio account. The 40-pixel single-line market strip scrolls continuously and pauses on hover or keyboard focus. It follows the archived dashboard: NIFTY 50, NIFTY 100, NIFTY BANK and SENSEX. It polls stored real Kite index quotes every five seconds; the backend refreshes quotes every fifteen seconds during market hours and once on page initialization after login. Index identities initialize directly from Kite quotes without a research snapshot.

### Importing and reviewing charges

Zerodha’s current PDF format is read from its equity ISIN summary, cash-charge table and Annexure A. The importer checks summary quantities and reconciles charges to the net obligation; derivative charges and repeated NET TOTAL columns are excluded. Execution prices follow Zerodha’s net-rate convention, with brokerage recorded separately. See [Zerodha’s format guide](https://support.zerodha.com/category/console/reports/contract-note/articles/how-to-interpret-the-contract-note).

1. Select the portfolio account, expand Account & imports and choose Import contract notes or Import DP statements.
2. Select up to 50 PDF, CSV or XLSX files, totaling no more than 64 MB. Each file can be up to 8 MB. Encrypted PDFs in one batch must share a password; the password and original files are not saved.
3. Review document extraction results. Unsupported or scanned PDFs are flagged for a CSV/XLSX export or parser support rather than guessed. The downloadable CSV template accepts individual trade charge components. For DP statements, use date, description, ISIN or symbol, debit and credit columns; only DP debits are imported.
4. Check stock, trade date, side, quantity, price and trade ID matches. Trades outside the selected portfolio are ignored. Daily note totals are allocated across all recognized transactions before outside trades are excluded; such allocations are labeled estimates. Stamp duty is allocated to purchases. Resolve ambiguous DP postings by choosing their sale; same-day executions share the debit by units.
5. Apply selected rows. Contract-note charges replace the previous trading-fee basis; DP statements reconcile the DP component separately. Repeated files do not add charges twice. Overlapping sources with conflicting amounts require choosing one source. A changed ledger requires a new preview.
6. Hover over Charges in the closed-trade journal for a quick breakdown, or click for buy/sell components, source documents and FIFO allocations. Buy charges follow sold units; the rest remain in open holding cost. DP charges appear only after a matching DP import or itemized note.

Charges are stored per account and trade with source provenance and an audit event. Original trade events remain unchanged. Cash, cost basis, realised P&L, valuations, return calculations and tax estimates read the reconciled amounts. These workflows apply to every account and do not contain portfolio-specific hardcoded fees.

Recognized NSE series and BSE group suffixes are normalized when matching names, for example STOCK-SM, STOCK-A and STOCK-B. Imported executions use the exchange recorded in their original trade ID, rather than the exchange used for the instrument's current price listing. An older ISIN can match a current listing only when the normalized stock name and exact execution ID agree, along with the date, exchange, quantity and price. Re-upload documents to regenerate previews created before matching updates.

Purchases whose basis was later replaced by an open-lot reconciliation are flagged rather than assigned fees to an unverifiable lot. Recover complete trade history into a fresh portfolio before importing those buy charges.

## Trade review

Review proposed trades, the reasons for them, and their estimated account impact.

### How to use it

1. Choose the portfolio you want to review.
2. Check existing stop alerts before considering new entries.
3. Generate proposals for a strategy and target session when research is ready.
4. Open a proposal to review the stock, quantity, estimate, rationale, and risk.
5. In the real app, use the explicit execution controls only after reviewing their consequences.

### Terms

- **Proposal:** A suggested action awaiting review. Generating it does not itself place an order.
- **Stop alert:** A holding whose checked price has crossed its recorded stop.
- **Estimated impact:** Expected value or risk based on the prices available when the proposal was calculated.

[Open Trade review](/actions)

## Research runs

Launch the exact data or research operation you need and track it to completion.

### How to use it

1. Choose Specific job or Full pipeline.
2. Select the operation and enter its parameters. The job definition link explains each input and prerequisite.
3. Run the selected job. It remains queued until the worker is running.
4. Inspect Runs & jobs for progress, submitted parameters, failures, and retry/cancel controls.
5. Open the corresponding result page when processing completes.

### Terms

- **Pipeline:** A coordinated series of jobs with prerequisites.
- **Specific job:** One selected operation, such as rebuilding indicators or collecting a stock’s bars.
- **Queued:** Submitted but waiting for job processing.
- **Worker:** The process that claims and performs queued jobs.
- **Completed session:** A market session that has ended; research must not treat unfinished prices as final.

[Browse every job definition](/guide/jobs)

[Open Research runs](/pipeline)

## Stock rankings

Compare stocks that match a strategy for a published research session.

### How to use it

1. Choose a strategy and a completed published session.
2. Load the rankings and compare ranks, scores, and signals.
3. Inspect a stock to understand why it qualifies.
4. If results are missing, build the required research through Research runs.
5. Move to Trade review to assess proposals and account sizing.

### Terms

- **Rank:** Order within a strategy’s published result.
- **Score:** A strategy-specific measure; scores from different strategies are not automatically comparable.
- **Signal:** A strategy event for a particular session, rather than a guaranteed outcome.

[Open Stock rankings](/rankings)

## Stock universe

See which stocks are eligible for screening and how membership changes.

### How to use it

1. Review the latest snapshot date and eligible stock count.
2. Browse the current members and data-coverage status.
3. Refresh membership when a new collection is required.
4. Compare dated snapshots to see additions and removals.
5. Prepare data for new members through Research runs before relying on their rankings.

### Terms

- **Snapshot:** A saved membership list tied to a collection date.
- **Coverage:** Whether required instrument and market data is available.
- **Added / removed:** Membership differences between the selected snapshots.

[Open Stock universe](/universe)

## Backtests

Evaluate a strategy against historical data before using its results in portfolio decisions.

### How to use it

1. Choose the strategy, historical start and end dates, and initial capital.
2. Expand execution assumptions to inspect costs, stop behaviour, and position limits.
3. Run a simulation or open a saved report.
4. Read returns and drawdown together, then inspect the equity curve and trade log.
5. Use Research runs for stress tests, walk-forward windows, or return attribution.

### Terms

- **CAGR:** Annualised growth over the simulation period.
- **Max drawdown:** Largest decline from a prior portfolio peak.
- **Slippage:** Modelled difference between the reference price and a fill.
- **Walk-forward:** Evaluation over successive training and testing windows.

[Open Backtests](/backtest)

## Settings

Inspect active strategies and configure understandable portfolio risk limits.

### How to use it

1. Review the current limits before editing them.
2. Set portfolio and position limits with their units visible.
3. Save the configuration and inspect the resulting version.
4. Open active strategies to inspect rules and revision history.
5. Use advanced configuration only when the simple controls do not cover the required setting.

### Terms

- **Portfolio risk limit:** A guard on combined account exposure or stop risk, according to the underlying rule.
- **Strategy revision:** A versioned strategy definition.
- **Configuration version:** Used to detect concurrent edits and avoid overwriting newer settings.

[Open Settings](/settings)

## Activity & quality

Find data issues and failed checks, then decide what to fix.

### How to use it

1. Filter events by severity and check type.
2. Read the affected instrument, date, and evidence.
3. Use the event’s next action to prepare missing data or revisit a research run.
4. Retry the affected job after fixing its prerequisites.
5. Inspect the resulting job status and quality evidence to verify recovery.

### Terms

- **Warning:** A diagnostic that needs interpretation; it does not automatically exclude a stock.
- **Error:** A failure that may prevent a job or result from completing.
- **Evidence:** Recorded details used to investigate the check.

[Open Activity & quality](/logs)

## Guide

Understand each tab and follow a complete workflow without guessing what comes next.

### How to use it

1. Select a tab in the handbook navigation, or filter by title.
2. Read its purpose and numbered steps.
3. Use the term definitions to interpret its metrics and statuses.
4. Follow the next-action button to open the relevant screen.

### Terms

- **Handbook:** Tab-by-tab instructions, terminology, and follow-up actions.

[Open Guide](/wiki)

Portfolio imports automatically queue a daily-price backfill for all stocks in the account's recorded history, including closed positions outside the research universe. The worker stores daily bars in `market_bars`; the dashboard reconstructs equity and drawdown from dated ledger buys, sells, charges, splits, available cash and cash transfers. Drawdown adjusts for external cash transfers. The chart refreshes when backfill finishes; Activity shows progress and failures. Rebuild price history retries the collection after credentials are renewed.

Stocks without usable prices across their held dates are excluded consistently from both curves, including their curve cash flows and charges. Their capital remains idle in the reconstructed curve. Partial curves are labelled and list excluded symbols. These exclusions affect only chart reconstruction; all trades remain in the journal, holdings, account balance, returns, charges and tax calculations.
