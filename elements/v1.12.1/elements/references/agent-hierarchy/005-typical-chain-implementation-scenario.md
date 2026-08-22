## Typical chain (implementation scenario)

```
A1 analysis ──► I1 lead implementer ──► V1 independent acceptance
                ├─ I1.1 sub-impl (module X)
                └─ I1.2 sub-impl (module Y)
```

1. **Analysis agent (A1)**: produces Guideline / structure / impact analysis from the requirement — **analysis only, no implementation**.
2. **Lead implementer (I1)**: from A1's analysis, splits implementation into sub-tasks and dispatches them to **implementation sub-agents (I1.1, I1.2…)**; each does only its assigned module and writes only that module's scope.
3. **I1 confirms and verifies** each sub-agent's output (integrate, run tests, check consistency); aggregates once all sub-tasks are done.
4. **Only after all implementation is complete**, hand off to an **independent verifier (V1)** — V1 ≠ any agent in the implementation chain, and **read-only** — for multi-scenario acceptance, producing the ACC (see independent-acceptance).
5. Iron rules: **I1 does not self-verify** (player can't be referee); **V1 does not edit code** (found a problem → back to modification-guide for the implementation chain to fix).

