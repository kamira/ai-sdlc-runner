## Coordination file (strongly recommended for parallel work)

`docs/coordination.md` (or a board): list in-progress claims — owner, locked scope, CHG number, status, start time. Every agent updates it on entry and exit. This is the "lock table" for parallel work. For sequential handoff it can be omitted (CHG status is enough).

```markdown
# Coordination board
| Owner | Role | R/W permission | Locked scope | CHG | Status | Time |
|-------|------|----------------|--------------|-----|--------|------|
| agentA | implementer | RW: src/modules/billing | src/modules/billing | CHG-20260616-03 | in progress | ... |
| agentB | verifier | read-only | src/modules/report | CHG-20260616-04 | done | ... |
```

**One file per claim (atomicity)**: parallel agents editing a single `coordination.md` can race each other (both write "at the same time", one overwrites the other). Under real concurrency, prefer **one file per claim** — `docs/coordination/claims/<agent-id>.md` (file existence = the lock; a git conflict on it = collision detected) — and keep `coordination.md` as the human-readable summary. Note CHG numbers are unique **within a branch** only (see branch-isolation); claims on different branches don't reserve numbers for each other.

