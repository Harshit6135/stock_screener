# Portfolio and actions

## Ledger model

An account is an event-sourced local ledger. Cash, fills and transfers create
versions; commands use the expected version to prevent an old browser view from
overwriting newer state. Account projections expose cash, realised P&L and
open lots; they are not broker authentication records.

## Account endpoints

| Operation | Endpoint |
|---|---|
| List accounts | `GET /api/portfolio/accounts` |
| Create local account | `POST /api/portfolio/accounts` |
| Account projection | `GET /api/portfolio/accounts/<account_id>` |
| Record verified fills | `POST /api/portfolio/accounts/<account_id>/fills` |
| Record capital transfer | `POST /api/portfolio/accounts/<account_id>/cash-transfers` |
| Dated valuation | `GET /api/portfolio/accounts/<account_id>/valuation?as_of_date=YYYY-MM-DD` |
| Valuation history | `GET /api/portfolio/accounts/<account_id>/valuation/history` |
| Journal/events | `GET /api/portfolio/accounts/<account_id>/journal` and `/events` |

Mutating commands require an idempotency key and expected ledger version.
Repeat a failed network request with the same key only when the original command
payload is unchanged.

## Valuation and returns

Valuation reads the ledger as of a date and the latest stored market bars up to
that date. It returns holding cost, price date/freshness, market value, cash,
equity, realised/unrealised P&L, trailing-stop readbacks and XIRR when there is
sufficient capital-flow history. Persist a valuation only when you need a
durable history point; Home will not fabricate one.

## Proposals

Actions are generated as reviewable proposals. Retrieve them with
`GET /api/actions/proposals?account_id=<id>`. A proposal carries its reason,
action date, decision state and event history. Approval/rejection/process routes
are scoped to the proposal ID; a guarded rejection must be shown to the
operator, not converted to success.

Daily/universe exits and protective-stop handling are different paths. An AMO
intent is not an actual fill. Only confirmed broker execution or a recorded
verified fill updates ledger history.

## Risk guard configuration

Use `GET /api/portfolio/risk-config` to read global managed-portfolio guard
limits and its version. Send `PUT /api/portfolio/risk-config` with
`expected_version` and a complete `limits` object. Guard limits are distinct
from strategy definitions and are not a license to modify strategy logic.
