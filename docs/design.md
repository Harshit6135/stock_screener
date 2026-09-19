# Design principles

## Real portfolio means real transactions

There is no paper-trading portfolio type. Every ledger account represents a
real accounting record. A transaction can enter the ledger only when its
execution facts are supplied manually or reconciled from Kite.

Strategy actions are proposals. Approval records human review but does not
prove execution. `ActionJobs.process()` therefore rejects generated strategy
and generated stop proposals. Backtest fills exist only inside a backtest
report.

## Point-in-time correctness

Research and backtests must use data that was knowable on the evaluated date.
The implementation preserves this by storing dated bars, revision IDs,
artifact lineage, and dated daily scores. Benchmark-relative strategies read
the benchmark history for the same window. Future values must never influence
an earlier score, rank, or fill.

Market-cap screening is intentionally a day-zero survivor-biased choice for
this application: the initial current universe is frozen, later runs retain
all members, and newly eligible listings may be added. This is a product
decision and must be stated when interpreting historical results.

## Instrument identity

ISIN is the cross-exchange equity identity. When both NSE and BSE listings are
available, NSE is preferred. Provider tokens are observations that can change;
they are not permanent instrument identities. Every token observation is
retained so changes can be reconciled.

## Universe publication is atomic

`universe_membership` is usable only when it matches a completed
`universe_build_state`. A successful build replaces membership and writes its
completion metadata in one transaction. Interrupted or failed scans cannot
silently activate a partial list.

Later builds retain existing members regardless of current market cap. An
unresolved existing member is carried forward. A new stock is added only after
its observed market cap is strictly greater than ₹500 crore, unless the job is
explicitly run with another positive threshold.

## Coverage is a provider fact

Bar boundaries do not prove complete historical coverage because internal
sessions may be missing. Completed Kite requests are stored as coverage
windows, including zero-row pre-listing windows. A requested range is covered
only when the union of recorded windows spans it.

An empty successful range is not the same as a provider failure. This matters
when rebuilding from 2015 for companies that listed later.

## Immutable definitions and artifacts

YAML is the human import/export format for a strategy. The runtime source of
truth is canonical JSON stored in an immutable strategy revision. Activation
retires the previous active revision for the same strategy but does not mutate
it.

Research reports, rankings, risk projections, backtests, and reference
snapshots use content-addressed or deterministic artifact identities. Artifact
lineage identifies every upstream snapshot. Corrections create replacements
or invalidations rather than editing historical evidence in place.

## Idempotency and recovery

Any command that can be retried must have a stable fingerprint or idempotency
key. Jobs, ledger commands, action proposals, broker fills, strategy revisions,
and artifact publications apply this rule.

Publication and relational projection may span more than one write. Recovery
paths complete the missing projection from the already-published immutable
artifact. Retrying the same command must not duplicate a fill, event, score,
or artifact.

## One database, explicit ownership

The application uses one shareable SQLite database rather than a tree of
generated files. Tables are grouped by store ownership, and every owner
applies namespaced migrations. Compressed artifact payloads live in SQLite as
well, keeping backup and transfer operationally simple.

The single database does not mean arbitrary cross-module writes. Each service
writes its own tables and uses public methods to read another module's state.

## Fail closed at financial boundaries

The system rejects stale ledger versions, missing prior bars for manual buys,
oversells, malformed prices, invalid artifact state, incomplete proposal
decisions, and disabled broker execution. Unexpected universe code failures
abort publication. Silent exception swallowing is not acceptable for an
operational background process.

## Small web handlers, durable application services

Blueprint functions validate transport details and delegate. Long work is a
job. Domain calculations should remain independent from Flask and provider
SDKs. This keeps core logic testable and avoids tying correctness to a browser
request lifetime.

## Explicit current limitations

The strategy schema validates indicator and operation nodes, but the runtime
still dispatches each complete strategy through a registered custom Python
implementation. The generic DAG executor described in pending work is not yet
implemented. Documentation must not imply that arbitrary YAML strategies run
without Python changes today.
