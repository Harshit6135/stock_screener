# Getting started

## Start the application

From the repository root, install dependencies and run the local server:

```powershell
poetry install --with dev
poetry run python run.py
```

Open `http://127.0.0.1:5000/`. Local SQLite data and artifacts default to
`instance/`. Read-only research works without Kite credentials; broker
connections require separately configured server credentials.

## Main pages

| Page | What to do there |
|---|---|
| Home | Create and inspect a local portfolio account, holdings, valuation, cash flows, and journal. |
| Universe | Check immutable dated NIFTY 500 snapshots and their members. |
| Pipeline | Submit historical research dates and inspect job stages and worker state. |
| Rankings | Read weekly Momentum rankings or daily Positional Trend signals. |
| Backtest | Read saved immutable backtest reports. |
| Actions | Generate upcoming-session proposals and review existing proposals. |
| Settings | Read or update portfolio guard limits and strategy revisions. |
| Logs | Read stored market-data quality events. |

## First useful workflow

1. Confirm a NIFTY 500 snapshot and stored market bars exist for the dates you
   need.
2. Submit a research run from **Pipeline** and wait for all required stages.
3. Read the corresponding result in **Rankings** or **Backtest**.
4. Create a portfolio account on **Home** if you intend to generate actions.
5. In **Actions**, select the account, strategy, and target session, then
   generate and review proposals.

See the complete [user guide](../user/workflows.md) for details and important
limits around data freshness, proposal pricing, and execution.
