# Portfolios and action proposals

## Portfolio ledger

A local account records cash, verified fills, transfers, and valuations as
versioned history. Creating an account is separate from signing in to Kite or
importing broker holdings. A broker snapshot is not automatically an executed
fill.

On **Home**, **Create portfolio account** asks for the account name, opening date,
initial balance, portfolio Kite API key and API secret in one form. The defaults
are **1 February 2026** and **₹300,000**. The opening date is persisted and used
as the first investment date for whole-account XIRR and CAGR. Creation starts
Kite authorization; login obtains the access token. No trades are imported by
creation or login.

Create an account, inspect holdings and cash, and refresh valuation
when a new dated valuation point is needed. Valuation uses the latest stored
market bar at or before its requested date; check each price date and freshness.

After **Connect portfolio Kite** and broker login, use **Import Kite holdings**.
Review the preview and check only the holdings you want to import. Unchecked
holdings are ignored on subsequent refreshes. Reopen the preview to add an
ignored holding later; already imported holdings retain their ledger history.
The import includes selected delivery balances, including T1 holdings and
today's CNC positions, at their broker average cost. Older purchase dates are
marked unknown; their ledger date is the import baseline date. ETF and bond
holdings are included. BSE holdings are matched to the NSE reference by ISIN.
Selected holdings' acquisition cost (units × average cost) is deducted from
available cash once. This is an internal allocation, not an external withdrawal.
The preview shows cost and cash after import; costs exceeding configured capital
produce a visible cash deficit. Ignored holdings do not reduce cash. Broker
margins are not imported. Legacy broker imports receive a single ledger funding
correction when refreshed, without rewriting their original import events.
For a connected account, **Refresh values** reads broker balances and prices;
repeat refreshes do not duplicate the imported holdings. Quantity differences
require trade reconciliation. Current-date valuations use the saved broker
portfolio price snapshot; earlier dates continue using stored market bars.

To record added capital, use **Cash deposit / withdrawal**, choose **Deposit**,
and enter the amount, note, and **Investment date**. The date defaults to today
and can be changed to the actual investment date. Withdrawals use a **Withdrawal
date**. Both are recorded at the start of the selected day in India time and
used for dated valuations and return calculations.

Use **Import tradebook history** to reconstruct the complete portfolio.
Export the **Equity** tradebook from Zerodha Console with the full relevant date
range, choose the CSV (up to 4 MB), and click **Preview trades**. Required
columns are symbol, trade date, trade type, quantity and price; ISIN, exchange,
trade ID and execution time are used when available. The upload is archived
locally for that account. Previewing does not change holdings or cash.

**Full history — buys and sells** is the default. All eligible symbols, including
closed positions, are selected initially. **Import selected trade history**
debits buys, credits sells, matches FIFO lots and records realized gains plus
remaining open lots on their original dates. Select all symbols for complete
portfolio performance. Optional `fee`, `fees`, `charges`, `total_charges` or
`transaction_charges` columns are included in acquisition cost and sale proceeds.
Without charges data, the preview and dashboard explain that brokerage and
taxes are excluded. A temporary historical cash deficit is retained and shown,
without inventing a deposit; record actual additional funding separately.

Full history requires a fresh account without imported opening balances. Trades
before its opening date are rejected. Repeated files and overlapping exports
skip identical existing trades; changed existing trades are rejected. New trades
must follow existing execution history. The full import is atomic. Kite refresh
then updates prices without adding opening positions or changing traded units.

The alternative **Recover open-lot dates only** mode supports existing opening
balance accounts. It replaces matched remaining lots without replaying closed
trades. Quantities must match and any cost difference adjusts cash once.

Verified tradebook splits bridge old and new ISINs at the effective date,
multiply held quantities and divide per-share cost while preserving total cost.
Preview refreshes NSE corporate actions over the uploaded date range through
today and also reads cached exchange events, including records already used for
market-price adjustment. Split and sub-division notices are recognized; repeated
ISIN changes are bridged through the dated events. The preview lists every applied
adjustment with its source. All stocks use the same exchange-record path;
there are no stock-specific corporate-action overrides.
Bonus shares enter a separate zero-cost FIFO lot; original purchase cost and dates
stay intact. The exchange ex-date is used for the bonus lot and disclosed as an
estimate requiring actual allotment-date verification for tax reporting.
Unavailable downloads display a cached-data warning. Missing/conflicting ratios,
fractional entitlements, rights and demergers require manual review rather than
invented shares or acquisition cost.
Unresolved sells are flagged per symbol; they cannot be applied, but do not block
unrelated matching holdings. Ratios are never inferred from a quantity mismatch.

Full history also reconstructs dated cash and holdings for past valuations;
historical market prices still require stored bars. Saved valuation snapshots
are not fabricated. Net gain is equity less investor capital; realized gain
and current unrealized gain are shown separately. CAGR uses initial balance
and opening date when there are no later cash transfers; use XIRR with dated
additional funding or withdrawals.

The equity and drawdown curves are reconstructed from the opening date, ledger
events and observed market prices without requiring saved snapshots. Drawdown
adjusts for external cash transfers. Dates with no usable price for an open
position are omitted and listed in the history notice; hover on a curve point
to see its date and value. The dated history endpoint uses `as_of_date`; requests
without that parameter continue to return saved snapshots.

**Import Kite holdings** also works after a tradebook import. Select missing
stocks, enter a purchase date for each on the next screen, and confirm the import.
Dates must fall between account opening and today. Current quantities and average
cost come from Kite; the supplied dates are saved on the imported lots. Cash is
debited once, existing trade history is preserved, and ignored stocks remain
unimported during refresh. Recorded holdings are refreshed without rewriting
their quantities; discrepancies require trade reconciliation.
Kite balances add no prior sells. Mixed accounts show a history-completeness note
and withhold whole-account XIRR/CAGR rather than present incomplete history as a
complete return. Current unrealized gains and recorded realized gains remain
available; open-holding XIRR can use the supplied purchase dates.

## Generate actions for an upcoming session

1. Open **Actions** and select the portfolio account.
2. Select a strategy and target session date. The page finds the latest
   completed NSE session stored locally before the target.
3. Choose **Generate proposals**. This queues a durable background job. A
   worker must process it.
4. When the job finishes, the target date is selected in the review filter and
   the resulting proposal is displayed.

Upcoming-session sizing uses the signal session's closing prices as reference
estimates. The target session's actual opening prices are unknown when the
proposal is generated; order size or eligibility may need review when prices
move. A generated proposal does not submit an order or write a ledger fill.

## Review and execution boundary

A proposal contains decisions, rationale, strategy, target date, and a ledger
version. Approve or reject only after reviewing it. Approval records a decision
and may reserve risk capacity; it is not a broker fill. Broker intent creation,
order submission, broker receipts, and verified fills are separate steps.

For a manual entry, use **Record a manual trade** only after the trade actually
executed. Enter the execution date, side, symbol, units, price, and evidence.
The entry enters the review queue first.

Do not use a manual fill to bypass a rejected approval or missing broker
confirmation.

## Annualized returns

**Open holdings annualized return (XIRR)** uses the acquisition cost and actual
purchase date of each remaining buy lot, with current market value as the
terminal inflow. It excludes available cash and closed trades. Unknown purchase
dates or missing prices prevent calculation; same-day buys are netted against
the terminal value. This is performance of today's remaining holdings, not the
entire trading history.

**Whole account annualized return (XIRR)** uses external deposits and withdrawals
and ends with holdings plus available cash. Tradebook reconciliation does not
invent historical deposits. When funded imported purchases precede recorded
capital history, this metric stays unavailable rather than treating older gains
as returns earned since recent funding.

XIRR uses a [365-day year](https://support.microsoft.com/en-us/excel/functions/xirr-function).
Flows on one date cannot establish an annualized return. The solver nets flows
by date and verifies that the discounted cash-flow residual is close to zero.

## Imported holding stop estimates

The holdings dashboard reconstructs ATR stops from completed daily OHLC bars,
including imported positions without a saved strategy risk projection. It uses
the existing 14-session ATR calculation and the portfolio policy's 2× ATR distance.
The initial estimate uses the weighted acquisition cost on the earliest remaining
lot date and the preceding session's ATR. Each subsequent completed weekly close
can raise the trailing stop to close minus 2× ATR; it never lowers the stop. Daily
ATR inputs remain daily, but midweek closes and live ticks do not ratchet stops. A saved
strategy stop takes priority and can only rise. The hard stop is 3% below the
trailing stop, matching the existing action rules.

The table includes the calculation date, ATR, stop status and rupee exposure from
the latest available price down to the trailing stop. A position already below
its stop is flagged explicitly even though that remaining distance is zero.
These are model estimates, not guaranteed loss limits or standing broker orders.
The current week's OHLC cannot ratchet stops before Friday's close at 15:30 IST.
Once the week has closed and its data is available, the last trading session's
close is used, including a Thursday close when Friday is a holiday. Missing history and stale calculation dates remain
visible. The earliest remaining lot date is an estimate of the position's entry,
and incomplete pre-entry ATR history is disclosed in the row tooltip.

## Portfolio stop sells

While the local app is running, its background monitor checks every 30 seconds
and reconciles submitted Kite fills. During market hours, only a fresh live price
at or below the hard stop (97% of the trailing stop) creates an intraday sell.
Crossing the normal trailing stop midweek does not create an immediate sell.
The WebSocket's per-tick alerts also check only the hard stop.

At a completed weekly close, a close below the normal trailing stop creates a
weekly sell review for the next week. This fixed decision survives Monday price
recovery and subsequent daily refreshes. Stops ratchet only at weekly closes.
Weekly orders can be approved and submitted from the next week's market open;
the monitor never approves them. Hard-stop reviews expire on a new day; weekly
reviews do not. Both become invalid if their portfolio baseline changes. Legacy
unsubmitted reviews from the previous daily-stop schedule are retired on checking
stops again. Submitted receipts remain available for reconciliation.

Refreshing Home or loading Actions checks live hard stops and completed weekly
normal-stop signals. A qualifying signal creates one independent `portfolio_stop`
SELL review action per stock, labelled as a hard stop or a weekly sell.
Actions displays these in **Current stop-loss actions**, independently of the
strategy and action-date filters. **Check stops now** refreshes them. Expand
**Prices and stop thresholds checked** to see each checked price, threshold,
source/date and result; an empty queue is explained instead of implying that
strategy generation is required. A failed stop check is shown separately and
does not prevent loading existing strategy proposals.
Intraday detection requires a fresh account-specific Kite quote. Stored prices
are labelled for display and cannot create a new intraday hard-stop review.
Weekly detection uses only the completed weekly close. Detection never submits an order.

If Kite refuses order permission, the app displays the broker's error and keeps
the order available for retry after correcting the portfolio Kite permissions.
An older permission refusal labelled `SUBMIT_UNKNOWN` can be cleared with
**Refresh Kite order**, which checks for a broker receipt before clearing it.
Timeouts with an uncertain receipt still require reconciliation before retry.

**Approve & sell on Kite** records approval and submits that exact quantity as a
regular CNC market sell with automatic market protection. This approval-scoped
gateway enables only the displayed stop sell; it does not arm general strategy
execution. Home-created accounts route to the broker account with the same ID;
managed strategy accounts retain their explicit broker mapping.

Before approval and again before placement, the workflow checks current market
hours, account session, ledger version, held units, completed stop history, a
fresh timestamped live quote, and broker shares
after outstanding sells. Existing managed risk reservations also apply. No sell is
placed when these checks fail. Unknown submission outcomes retain the order tag
and require reconciliation instead of automatic resubmission.
Hard-stop execution also rechecks that price remains at or below the hard stop.
Weekly sell execution does not cancel the reviewed weekly decision because the
live price recovered above either stop.

Confirmed trade rows, including Kite's per-trade `average_price`, reduce the
ledger holding quantity and credit sale proceeds. A broker `COMPLETE` response
does not finalize local reconciliation until all ordered units have trade rows
posted to the ledger. Missing trade rows are retried; older stop orders marked
filled without ledger fills are also recovered. Repeated reconciliation never
posts a trade twice. When the live feed sees a new ledger version, Home reloads
holdings, cash, realised P&L, and the closed trade journal. Fully sold positions
leave Current holdings and remain in the journal.

Delivery holdings shown under BSE are matched to the NSE instrument by ISIN.
Existing delivery sells on either exchange reduce available shares; same-day BSE
buys do not fund NSE sells. Kite's display exchange does not restrict settled
holdings to that exchange ([Zerodha explanation](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-holdings/articles/default-exchange-on-kite)).

**Refresh Kite order** reads Kite order status and actual trade rows. Partial fills
are posted once to the ledger and journal; complete fills mark the action recorded.
Submission alone never removes holdings or creates a realised gain. Kite describes
the distinction between [order placement and confirmed execution](https://kite.trade/docs/connect/v3/orders/).

- `POST /api/actions/stops/check` with `account_id` creates review actions only.
- `POST /api/actions/stops/<proposal_id>/approve-execute` approves and submits.
- `POST /api/actions/stops/<proposal_id>/reconcile` refreshes confirmed fills.

## Account edits and existing strategy execution

Home's **Edit account** changes the display name, opening date and initial balance.
The account ID and trade history stay intact. The opening date cannot move later
than the earliest recorded transaction. Performance and cash are recalculated
from the corrected starting capital. Separate metadata versions prevent one edit
from overwriting another, and outstanding broker orders block capital/date edits.
Replacement Kite keys are optional; changing them expires the account session and
requires a new Kite login. API summaries never return credential values.

Existing strategy rows now offer **Approve & execute on Kite**. Each approval
creates a durable execution request; only approved stocks are included after all
rows are reviewed. Future-session requests wait for the target session to open.
The monitor executes sells first and waits for their confirmed fills before buys.
It checks live quotes, available broker shares, portfolio cash, broker funds,
current NSE buy eligibility and the existing managed risk reservations. Buys with
quotes more than 5% away from the reviewed estimate require fresh review.
Only this proposal's confirmed fills may advance its execution ledger baseline.
Unrelated portfolio changes block execution. Unknown broker receipts are
reconciled by tag instead of resubmitted. Old approvals do not run automatically;
they require an explicit execution request through the new button.

Approval-and-execution endpoints require JSON `approved: true` and reject a
different browser origin. Blocked requests expose the reason in Actions and allow
an explicit retry. All live orders are scoped to the approved account and stocks;
these requests leave the general strategy gateway's global controls untouched.

- `PUT /api/portfolio/accounts/<account_id>` updates name, opening date and capital.
- `PUT /api/broker-accounts/<account_id>` updates name and optional Kite credentials.
- `POST /api/actions/proposals/<proposal_id>/approve-execute` accepts `approved`
  and an optional `decision_index` for stock-level approval.
- `POST /api/actions/proposals/<proposal_id>/execution-refresh` refreshes receipts
  and processes an already requested execution.

## API references

- `GET /api/portfolio/accounts` and `/api/portfolio/accounts/<account_id>`
- `POST /api/operations/jobs` with kind `actions.generate-portfolio-proposal`
- `GET /api/actions/proposals?account_id=<id>&action_date=YYYY-MM-DD`
- `GET /api/actions/proposals/<proposal_id>/events`
- `POST /api/actions/proposals/<proposal_id>/approve` or `/reject`
- `POST /api/portfolio/proposals/<proposal_id>/broker-intents`

Account fills, transfers, valuation, and guard configuration are documented in
the [API guide](api-and-data.md).

## Live portfolio dashboard

The portfolio dashboard puts value, unrealised gain, day P&L, and cash first. Account connection and import controls are under **Account & imports**; import instructions appear inside the import dialogs. Additional return and risk metrics can be expanded when needed.

With today’s valuation date selected, **Go live** starts a read-only Kite WebSocket using the shared market-data session. Quotes are still stored and delivered under the selected ledger account; portfolio broker credentials remain separate for imports and execution. The browser receives account-scoped read-only updates via continuous SSE. Fresh, exchange-timestamped quotes update each holding’s price, market value, unrealised return, day P&L, stop distance, and quote time. Missing or stale quotes use labelled stored-price fallbacks and never qualify as fresh observations for the intraday chart. The intraday chart begins when monitoring starts; it does not reconstruct earlier ticks.

Historical equity and drawdown continue to use dated transactions and historical prices. Live quotes do not record fills, change cash, or rewrite valuation history. Acquisition-day rows retain their own cost bases while sharing the instrument’s latest quote.
