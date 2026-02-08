# IMPLEMENTATION PLAN: Cleanup Instructions.md

## Goal
Remove redundant project documentation from `.agent/instructions.md` that is already maintained in `README.md` and `docs/STRATEGY.md`. The `instructions.md` file should focus strictly on **Agent Persona**, **Workflow Compliance**, and **Coding Standards**.

## Proposed Changes

### [MODIFY] .agent/instructions.md

**Remove Sections:**
- `Project Overview` (Redundant with README)
- `Architecture` (Redundant with README)
- `Services` table (Redundant with README)
- `Utils` table (Redundant with README)
- `Config Classes` table (Redundant with README)
- `Factor Weights` (Redundant with README & STRATEGY.md)
- `Penalty Box` (Redundant with STRATEGY.md)

**Retain Sections:**
- `MANDATORY FIRST STEP`
- `Persona`
- `Compliance Checklist`
- `File Naming Conventions`
- `Python Coding Conventions`
- `Documentation Update Rules`
- `Planning Workflow`

**Refactoring:**
- Update `Project Overview` to a single sentence pointing to `README.md`.
- Update `Architecture` to a single sentence pointing to `README.md`.
