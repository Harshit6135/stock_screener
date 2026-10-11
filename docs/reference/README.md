# In-app handbook

| Page | Use it for |
|---|---|
| [Getting started](getting-started.md) | local runtime, pages and safe setup |
| [Research and strategies](research-and-strategies.md) | universe, data, DAGs, rankings and replay |
| [Portfolio and actions](portfolio-and-actions.md) | ledger, valuation, proposals, capital and risk |
| [Operations and observability](operations.md) | pipeline, jobs, workers, SSE and quality events |
| [API and data model](api-and-data.md) | owned HTTP contracts and persistent state |
| [Troubleshooting](troubleshooting.md) | common failures and evidence collection |

## Terms

For screen-by-screen instructions, see the [user guide](../user/workflows.md).

- **Snapshot**: immutable stored universe or published research input.
- **Artifact**: immutable payload plus manifest/lineage.
- **Ledger version**: optimistic-concurrency version of one portfolio account.
- **Proposal**: a reviewable action intent, not proof of a broker fill.
- **Quality event**: a persisted warning/error about data; it does not silently
  remove a stock from research.

The in-app pages are concise reference topics. For screen-by-screen instructions
and workflows, see the [user guide](../user/workflows.md).
