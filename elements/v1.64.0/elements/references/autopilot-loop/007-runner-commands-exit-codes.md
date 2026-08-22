## Runner commands & exit codes

```
plan-check --chg <CHG.md>                      # validate plan format only (operational-test hint is non-blocking)
run  --chg <CHG.md> --repo . [--agent-cmd T] [--test-cmd C] [--verify-cmd V] [--dry-run] [--no-commit] [--max-tasks N]
status --chg <CHG.md>                          # ticked/unticked, next task, current stage
```

`--test-cmd` runs each task's unit/build tests; `--verify-cmd` runs the end-stage operational test (operate the change for real). Exit codes: `0` done · `1` unexpected error · `2` invalid plan · `3` legitimate halt (reason printed). Wire cron/CI on 3 (notify a human with the reason) and 0 (pick up the next CHG). `--dry-run` simulates build/test/review **and operational verify** success to exercise the state machine and halt policy without an agent.

