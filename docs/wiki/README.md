# Wiki index

| Page | Use it for |
|---|---|
| [Getting started](getting-started.md) | local runtime, pages and safe setup |
| [Research and strategies](research-and-strategies.md) | universe, data, DAGs, rankings and replay |
| [Portfolio and actions](portfolio-and-actions.md) | ledger, valuation, proposals, capital and risk |
| [Operations and observability](operations.md) | pipeline, jobs, workers, SSE and quality events |
| [API and data model](api-and-data.md) | owned HTTP contracts and persistent state |
| [Troubleshooting](troubleshooting.md) | common failures and evidence collection |
| [Historical positional-trend reference](historical-positional-trend-reference.md) | retained source material; not the current runtime contract |

## Terms

- **Snapshot**: immutable stored universe or published research input.
- **Artifact**: immutable payload plus manifest/lineage.
- **Ledger version**: optimistic-concurrency version of one portfolio account.
- **Proposal**: a reviewable action intent, not proof of a broker fill.
- **Quality event**: a persisted warning/error about data; it does not silently
  remove a stock from research.

The historical positional-trend reference predates the snapshot-based universe
contract. Use the operational pages and versioned strategy definition for
current behavior.
