# Documentation index

This directory separates the current modular implementation from the preserved
v3 documentation. Use the current section for development and operations.
Archived documents describe the retired Flask-Smorest, SQLAlchemy, dashboard,
and v1 API implementation; they are historical references only.

## Current implementation

- [Current state](current/Current%20state.md) — source-of-truth description of
  the current implementation and the v3 comparison.
- [Modular monorepo design](current/Modular%20monorepo%20design.md) — target
  architecture and package-boundary decisions.
- [Implementation plan](current/Implementation%20plan.md) — phased delivery
  plan and release gates.
- [Design and implementation gap review](current/Design%20and%20implementation%20gap%20review.md)
  — verified fixes, remaining risks, and validation evidence.
- [Pending migration implementation design](current/Pending%20migration%20implementation%20design.md)
  — v3 behavior, v4 design and acceptance criteria for every open migration row.
- [Pending items](current/Pending%20items.md) — checklist of remaining v3
  migration gaps and the separately carried-forward v3 future backlog.
- [V3 code audit and V4 comparison](current/V3%20code%20audit%20and%20V4%20comparison.md)
  — source-code-only route, service and frontend comparison.

The repository [README](../README.md) is the shortest start/run reference.

## Historical v3 documentation

The [v3 archive](archive/v3) retains the previous application’s API,
architecture, strategy, setup, deep dives, and changelog without presenting
them as current behavior. The original quantitative research is in
[archive/research](archive/research). An exact duplicate of the v3 ranking
deep dive is retained separately in [archive/duplicates](archive/duplicates)
for traceability.

## Naming convention

Documentation file names use sentence case. Active material belongs in
`current/`; immutable historical reference belongs in `archive/` rather than
being copied into new implementation guidance.
