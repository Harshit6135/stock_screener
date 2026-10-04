# Portfolios and action proposals

## Portfolio ledger

A local account records cash, verified fills, transfers, and valuations as
versioned history. Creating an account is separate from signing in to Kite or
importing broker holdings. A broker snapshot is not automatically an executed
fill.

On **Home**, create an account, inspect holdings and cash, and refresh valuation
when a new dated valuation point is needed. Valuation uses the latest stored
market bar at or before its requested date; check each price date and freshness.

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

## API references

- `GET /api/portfolio/accounts` and `/api/portfolio/accounts/<account_id>`
- `POST /api/operations/jobs` with kind `actions.generate-portfolio-proposal`
- `GET /api/actions/proposals?account_id=<id>&action_date=YYYY-MM-DD`
- `GET /api/actions/proposals/<proposal_id>/events`
- `POST /api/actions/proposals/<proposal_id>/approve` or `/reject`
- `POST /api/portfolio/proposals/<proposal_id>/broker-intents`

Account fills, transfers, valuation, and guard configuration are documented in
the [API guide](api-and-data.md).
