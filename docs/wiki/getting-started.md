# Getting started

## Application pages

| Path | Purpose |
|---|---|
| `/` | portfolio home, index quotes, saved valuation and holdings |
| `/actions` | proposal review, decisions and risk readback |
| `/pipeline` | manually submitted research pipeline and worker control |
| `/rankings` | named strategy/week ranking readback |
| `/universe` | immutable universe snapshots, members, diff and refresh |
| `/backtest` | saved immutable backtest report readback |
| `/settings` | portfolio risk limits and strategy revision readback |
| `/logs` | persisted market quality-event viewer |

Legacy `/app` and `/portfolio` redirect to `/`.

## Local data boundaries

The app keeps local SQLite stores under its configured data directory. Market
bars, job events, artifacts, ledger events and strategy revisions have distinct
responsibilities even when local storage is colocated. Do not commit databases,
SQLite sidecars, access tokens, or generated test directories.

## Before you operate

1. Ensure reference instruments and the required universe snapshot exist.
2. Ensure market bars cover the dates you intend to research or value.
3. Verify strategy configuration/revision rather than assuming a visible name
   is sufficient.
4. Start a worker only when you intend to process the queued local jobs.

## Theme and accessibility

The browser shell persists dark/light choice in local storage. Keyboard users
can use the skip link and `Escape` to close the shared modal. Reduced-motion
preferences are respected by the Carbon Emerald theme.
