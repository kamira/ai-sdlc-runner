---
name: autopilot-loop
description: >
  The drive contract: the state machine from requirement to merge, the halt decision order
  (permanent halts → CHG Autonomy → policy matrix → unknown = halt), resume semantics, ledger
  mapping, and the runner's commands and exit codes. Read this when running the whole flow,
  resuming an interrupted run, or wiring the runner into cron/CI.
---

# autopilot-loop — the drive contract

> 語言 / Language: [繁體中文](autopilot-loop.zh-tw.md) · **English**

## State machine

```
ai-sdlc entry handshake (governance layer — mandatory, includes knowledge INDEX + pending CHG scan)
  → CHG exists & confirmed?  no → requirement/modification governance first (ai-sdlc)
  → plan-check gate (exit 2 on failure — a bad plan never starts)
  → confirm gate            (per policy: auto / confirm / halt)
  → [ per unticked task T_i:
        TDD build → task tests → read-only task review
        → pass: tick + commit "CHG-<id>: T<i> <title>" + update live handshake
        → fail: one fix pass → re-review → second fail = halt ]
  → whole-branch review
  → operational verify (run it for real: operate → observe → pass; per policy)
  → acceptance (ACC; per policy self-verify / independent)
  → PR → merge (per policy) → close-out: CHG status + Commit/PR + recurrence check + knowledge
```

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

## Gates on agent-written code

`--test-cmd` going green proves only that *the agent's own tests did not catch the agent's own
mistakes*. The same model wrote both, so they share one set of blind spots — ai-sdlc
`independent-acceptance` already says as much about verification; it applies with equal force
when one agent writes the code and its tests in the same breath.

Four gates sit on the code the agent produces, in this order:

1. **Unit execution — mandatory.** No `--test-cmd` now halts (exit 3). Previously it was skipped
   silently, so a task could be ticked and committed with not one line ever executed.
   `--allow-untested` is the explicit escape hatch; it prints a warning and is written to the
   handshake file.
2. **Mutation.** `--mutation` seeds faults into the files *this task* changed and re-runs the
   task's own tests. Survivors are reported by line and operator: those are the lines that could
   be wrong without anything going red. Below `--min-kill-rate` (default 90) the task gets one
   repair attempt, then halts. Test files are excluded from mutation — mutating a test inflates
   the kill rate with a tautology. Python only; other languages are reported as **not covered**.
3. **Behaviour spec.** A code CHG at Skill >= v1.5.0 must declare `### Behaviour spec` with
   `- feature: <path>`. The verify stage runs each one. The CHG's user stories thereby become
   re-runnable assertions instead of prose someone reads.
4. **Whole-branch review.** No longer a no-op: it calls the review command against the branch
   diff and requires a verdict line. Absence of output is not a pass.

### Verifying the verifier

The gates are code, and an agent can write code. Deleting `require_test_command` from the
precondition tuple, or setting the kill-rate threshold to zero, leaves every existing test green.
Two things guard against that:

- `verifier_integrity.py` anchors the SHA-256 of the files that make up the checking apparatus.
  Re-anchoring requires naming the authorising CHG, so changing a verifier stops being a silent
  edit and becomes a signed ledger entry.
- `test_gates_wired.py` asserts by AST that each gate is still wired into the flow — the cheapest
  way to defeat a gate is to remove it, and a removed gate does not complain.

Escape hatches (`--allow-untested`, a below-floor `--min-kill-rate`, `--no-commit`) are printed
and written to the handshake; dropping the threshold below 60 additionally requires an
`Escape-hatch:` line in the CHG.

## Halt decision order (strict, tighten-only)

1. **Permanent halts** — task or CHG tagged `permanent-halt:<class>` (irreversible-delete / payments / prod-migration / security-boundary): unconditional halt; the runner refuses any config that relaxes these.
2. **CHG `Autonomy:` field** — may only tighten relative to policy.
3. **`assets/autopilot_policy.json`** — the risk × stage matrix.
4. **Unknown → halt.** A gate the contract doesn't recognize stops the run; guessing "auto" is how autopilots crash.

`confirm` stages may be pre-authorized via a knowledge directive (narrow class, auto-revoked on misfire) — ai-sdlc's pre-authorization rule, unchanged.

## Resume semantics

Ticked checkboxes = completed tasks; rerunning `run` skips them and continues from the first unticked task. The live handshake file (`docs/worklog/handshake-autopilot.md`) is rewritten at every task boundary — an interruption at any moment leaves it current. Working-tree reconciliation on re-entry belongs to the ai-sdlc handshake, not to the runner.

## Runner commands & exit codes

```
plan-check --chg <CHG.md>                      # validate plan format only (operational-test hint is non-blocking)
run  --chg <CHG.md> --repo . [--agent-cmd T] [--test-cmd C] [--verify-cmd V] [--dry-run] [--no-commit] [--max-tasks N]
status --chg <CHG.md>                          # ticked/unticked, next task, current stage
```

`--test-cmd` runs each task's unit/build tests; `--verify-cmd` runs the end-stage operational test (operate the change for real). Exit codes: `0` done · `1` unexpected error · `2` invalid plan · `3` legitimate halt (reason printed). Wire cron/CI on 3 (notify a human with the reason) and 0 (pick up the next CHG). `--dry-run` simulates build/test/review **and operational verify** success to exercise the state machine and halt policy without an agent.

## Degraded modes

- **No headless agent** (`--agent-cmd` unset, not dry-run): the runner prints each task brief and halts (exit 3) — human-in-the-loop mode; ticks still drive resume.
- **No `--verify-cmd`** (and not dry-run): the runner prints the `### Acceptance operation` brief and halts (exit 3) — human performs the operational test and records evidence in the ACC.
- **No gh CLI**: PR/merge stages print the exact commands to run and halt (exit 3) instead of merging.
- **No spawn for reviews**: the same agent builds and reviews serially — note the degradation in the ACC (same rule as ai-sdlc's degraded panel).

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

## Dispatching build and review to different models

`--review-cmd` points the per-task review at a **different command — and therefore a different model — from the builder**. Without it the review falls back to `--agent-cmd`, i.e. builder and reviewer run on the same model, which shares one set of training biases and blind spots (certain errors get missed *systematically, together*). The fallback is **announced, never silent**, so a round's independence is never overstated.

The runner stays no-LLM: it does not parse model names. Which model each command reaches is written into the command template by whoever runs it. Model choice per role follows ai-sdlc `agent-hierarchy` "Choosing a model per dispatch" — judgment density, independence need, cost.

```
runner build|run --chg <CHG.md> --repo . --agent-cmd '<builder>' --review-cmd '<reviewer>'
```

## Standing sentinels & scheduled re-entry

"Requirement-confirmation as standing polling" without stalling on parallel fan-out: a one-shot orchestrator installs deterministic sentinels + scheduled re-entry, then **exits** (dormant = exited, not a resident agent; a re-entry spawns a fresh one-shot run). Governance semantics are anchored in ai-sdlc `references/autonomy.md` — this layer only drives, never forks the taxonomy.

- **Sentinels** (`scripts/autopilot_sentinels.py poll`): deterministic, no-LLM checks over requirement / structure / change / acceptance (`assets/sentinel_policy.json`). Two-tier escape:
  - **Tier A — cannot evaluate** (check unavailable / crashes / unparseable): fail-open to the baseline linear flow (exit 0, logged) — degradation, never a silent swallow of a real halt.
  - **Tier B — real halt** (a check ran and flagged: always-halt action / risk×gate HALT / unknown=halt): exit 3, escalate to a human — never fall through.
- **Scheduled tail-recursion**: cron / scheduled-task re-invokes the poll each interval; ticked checkboxes are the state accumulator between fires. Base case (`plan complete / no progress / max_reentry`) stops re-entry.
<!-- claim: sentinel-install-always-halts -->
- **Install = halt** (`scripts/sentinel_install.py install`): creating cron/CI is a persistent-config action → **always halts for human authorization** (`--i-authorize-cron`); even authorized it emits a reviewable crontab line + CI snippet rather than mutating system cron.

```
runner sentinels --repo . [--chg CHG] [--reentry-count N]   # exit 0 = baseline / 3 = escalate
```
