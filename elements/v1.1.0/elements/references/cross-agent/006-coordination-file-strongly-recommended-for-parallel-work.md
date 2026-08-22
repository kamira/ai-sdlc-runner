## Coordination file (strongly recommended for parallel work)

`docs/coordination.md` (or a board): list in-progress claims — owner, locked scope, CHG number, status, start time. Every agent updates it on entry and exit. This is the "lock table" for parallel work. For sequential handoff it can be omitted (CHG status is enough).

```markdown
# Coordination board
| Owner | Role | R/W permission | Locked scope | CHG | Status | Time |
|-------|------|----------------|--------------|-----|--------|------|
| agentA | implementer | RW: src/modules/billing | src/modules/billing | CHG-20260616-03 | in progress | ... |
| agentB | verifier | read-only | src/modules/report | CHG-20260616-04 | done | ... |
```

