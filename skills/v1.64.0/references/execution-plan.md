---
name: execution-plan
description: >
  Executable plan format for autopilot runs: a Global Constraints block that binds every task,
  plus per-task Interfaces (consumes/produces) and a test line, tracked with checkboxes. The plan
  lives inside the target project's CHG (modification-guide section) — never in a separate file.
  Read this when writing or validating a plan, before the first task is built.
---

# execution-plan — the plan that a machine can drive

> 語言 / Language: [繁體中文](execution-plan.zh-tw.md) · **English**

## Why this format

A plan drives an autopilot only if every task is **independently executable and independently checkable**: an agent that sees nothing but the Global Constraints + one task entry must be able to build it, and a reviewer that sees nothing but the same brief + the diff must be able to judge it. Prose plans ("then improve the API") fail both tests.

## Format (inside the CHG's modification-guide section)

```markdown
### Global Constraints (every task must obey)
- <testable constraint — "always X", never "prefer X">

### Tasks (checkboxes = resume points)
- [ ] T1. <title>
  - interfaces: consumes <inputs/preconditions> / produces <outputs/deliverables>
  - test: <how to verify — a command or an assertable condition>
- [ ] T2. ...

### Acceptance operation (the end-stage operational test — required for code-bearing changes)
- operate: <how to run/exercise the change for real — a command or steps>
- observe: <what observable behavior confirms it works>
- pass: <pass criteria>
```

For a **pure-doc CHG** with nothing to run, replace the whole section with a one-line header field: `Acceptance-operation: n/a (docs-only)`.

## Rules (plan-check enforces these)

- A **Global Constraints** section must exist. Put version floors, naming rules, exact values here — anything that binds *every* task. Fold in the applicable knowledge globals and Guideline constraints so the task brief is self-contained.
- Every task carries an **`interfaces:` line** (what it consumes and produces — this is what makes tasks composable and reviewable) and a **`test:` line** (command or assertable condition; docs-only tasks state a reproducible check instead).
- Task ids **T1..Tn sequential**; each task sized so one agent run completes it (bite-sized; if a task needs its own plan, it is too big — split it).
- Ticks are written **the moment a task passes review** — they are the resume points after any interruption (crash-only discipline).
- **`### Acceptance operation`** declares the end-stage operational test (`operate`/`observe`/`pass`). This is **not** a per-task `test:` line — task tests are unit/build level, this runs the whole change for real. plan-check only *hints* if it is missing (non-blocking); the **run**-time operational-verify stage enforces it (a code CHG without it, and without a `docs-only` marker, halts before acceptance — see autopilot-loop).
<!-- claim: local-gate-before-merge-code-bearing -->
- **`### Local gate`** (or `## Local gate` / `本機閘`): a **code-bearing** change must pass a local self-check **before merge** (Skill >= v1.22, prospective). Format: `- cmd: <command>` / `- pass: <criteria>`. Without a declaration the runner looks for the project's conventional carrier in order (`.github/ci_local.sh`, `scripts/check.sh`, `make check`, `just check`); **if none of the four exist it halts** (exit 3) — merging is a one-way door, so not knowing means not merging. Docs-only (`Acceptance-operation: n/a`) and `Template: lite`/`classic` are exempt. **A declared `cmd` does not run by default**: it comes from repo content, not from the operator — pass `--trust-chg-commands`, or supply your own with `--local-gate-cmd` (see autopilot-loop "trust boundary").
- **`## Design diagrams`** (or `### Design diagrams` / `設計圖`): required for **medium/high-risk** changes, and **blocking** — without it plan-check exits 2 and the plan never starts. It holds an architecture diagram of the affected area plus a flow diagram of this change; Mermaid by default, ASCII is fine. The machine only checks that the section exists and contains at least one fenced block — it **does not judge whether the diagram is right**, because that is what the user judges at the confirm gate (see modification-guide step 6). If the user decides not to look, write `Diagrams: skipped — <reason>` in the header; **a blank reason counts as undeclared**. Low risk and `Template: lite`/`classic` are exempt. **Prospective**: it only applies to records declaring `Skill: ai-sdlc-autopilot v1.21` or later, so no existing CHG is affected.

## Optional pre-step: divergent ideation (adhd)

Before locking the plan (or during structure design), when the solution space is wide, run a **serial, inline** divergence→focus pass — adapted from the adhd method — to avoid premature convergence:

- **Diverge**: generate several candidate task-breakdowns / interface designs under distinct framings (invert the problem, remove a constraint, cross-domain transplant, push to extremes); suspend judgment.
- **Focus**: a critic pass scores candidates (viability / fit / trap), clusters, and keeps the survivor.
- **Inline only**: run it in the main thread, serially — this environment stalls parallel subagent fan-out; use no standing agents.
- **Backfill the ledger**: the chosen breakdown lands in the CHG tasks and the rationale in the decision table — **no separate ideation doc** (no parallel ledger).

This is an optional thinking aid for the plan / structure gate, not a runner stage.

## Relation to the ledger

The plan **is** the CHG's modification steps — one artifact, one truth. plan-check (`autopilot_runner.py plan-check`) is the machine gate; a plan that fails it never starts running (exit 2).
