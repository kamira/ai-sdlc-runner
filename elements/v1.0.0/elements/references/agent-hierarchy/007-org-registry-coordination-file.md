## Org registry (coordination file)

Maintain the org table in `docs/coordination.md` so anyone/any agent can see who does what, who manages whom, and what tools were granted:

```markdown
# Agent org
| ID   | Role | Parent | Task / scope | R/W permission | Tools | Status |
|------|------|--------|--------------|----------------|-------|--------|
| A1   | analysis | —  | requirement/structure/impact | read code; write docs/ only | no Agent; can execute analysis | done |
| I1   | lead impl | — | coordinate impl, integrate | RW src/ | Agent (can dispatch); can execute | in progress |
| I1.1 | sub-impl | I1 | module X | RW src/x | no Agent; can execute | in progress |
| I1.2 | sub-impl | I1 | module Y | RW src/y | no Agent; can execute | done |
| V1   | verifier | — | multi-scenario acceptance | read-only on code; write docs/acceptance | **no Agent; can execute (tests/CLI/GUI)** | standby |
```

