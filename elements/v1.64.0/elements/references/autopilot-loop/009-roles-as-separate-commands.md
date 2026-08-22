## Roles as separate commands

Each stage of the loop is also callable on its own — review one diff, run just the operational verify, install just the sentinels — with `run` being the **composition** of the same units (one implementation, no drift). Splitting into commands is **not a governance bypass**: every role goes through the same halt policy and the same ledger, and a missing precondition halts (exit 3).

| role | precondition (else halt) |
|------|---------------------------|
| `plan` | CHG parses; task format complete (exit 2 if not) |
| `build` | valid plan · no permanent-halt marker · confirm gate passed (`--confirmed` for medium/high) |
| `review` | all tasks ticked (whole-branch review follows per-task review) |
| `verify` | all tasks ticked · `### Acceptance operation` present (or `docs-only`) |
| `accept` | all tasks ticked · operational verify passed (`verify` first, or `--verified` with evidence in the ACC) |
| `sentinels` | — (deterministic poll; see below) |

```
runner plan|build|review|verify|accept --chg <CHG.md> --repo .   # plan-check remains an alias of plan
```

