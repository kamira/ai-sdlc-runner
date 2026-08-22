## Operational verify — the last mile (task tests are not enough)

Per-task `test:` lines are **unit/build level** (RED-GREEN — the parts are correct). They do **not** prove the change actually runs and was actually exercised — the classic "all green, feature still broken" blind spot. Before acceptance the runner requires an **operational test**: run the app/change for real, operate it, observe the behavior.

- The plan declares the operational test in a **`### Acceptance operation`** section (`operate:` how to run/exercise / `observe:` what confirms it works / `pass:` pass criteria) — see execution-plan.
- Runner behavior at this stage:
  - `--verify-cmd C` given and stage is `auto` (low/medium): runs `C`; non-zero → halt (exit 3, "operational verify failed").
  - No `--verify-cmd` (and not dry-run): prints the `### Acceptance operation` brief and halts (exit 3) — **human-in-the-loop**: perform the operation, record evidence in the ACC, then continue to merge.
  - Stage is `halt` (high risk): **always human-performed** — a high-risk operational sign-off is not machine-self-certified, even with a passing `--verify-cmd`.
  - `--dry-run`: simulates operate/observe/pass.
- **Docs-only exemption**: a CHG that declares `Acceptance-operation: n/a (docs-only)` (and has no `### Acceptance operation`) skips this stage — no faked operation for pure-doc changes.
- **A code-bearing CHG with neither `### Acceptance operation` nor a docs-only marker halts here (exit 3)** — you cannot reach ACC on a code change without an operational test on record.

