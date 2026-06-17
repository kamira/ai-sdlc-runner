# ai-sdlc-runner

External Python orchestrator that drives the [`ai-sdlc`](https://github.com/kamira/ai-skills) skill's
semi-autonomous development loop. **The skill stays pure (markdown + zero-dependency gate scripts);
the runner is an external driver that references — never copies — the skill.** Dependency is one-way:
the runner depends on the skill; the skill never depends on the runner.

## Install

```bash
git clone https://github.com/kamira/ai-sdlc-runner.git
cd ai-sdlc-runner
git submodule update --init        # pulls ai-skills pinned at tag v1.0.0 (NOT main)
pip install -e .                   # optional: .[yaml] for PyYAML, .[test] for pytest
```

The `ai-skills` submodule is **pinned to tag `v1.0.0`** and must never track `main` (main drifts and
breaks the contract lock). The runner detects the *actual* contract version by reading the skill's
`SKILL.md` frontmatter, so a missing/incorrect tag surfaces as a contract-version mismatch rather
than silent drift.

## Usage

```bash
runner run <project>                      # drive the four-stage loop for a governed project
runner migrate <project> --to <version>   # validating contract upgrade (re-read all docs first)
runner status <project>                   # show the per-project lock + run state
```

Options for `run`: `--contract-version` (defaults to config), `--skill-path` (override, e.g. a local
skill cache for offline verification), `--risk {low,medium,high}`, `--resume`.

## How it works

- **Contract lock is per project, `major.minor`.** PATCH differences pass freely; a `minor`/`major`
  bump forces an explicit, *validating* `migrate` (re-read every doc; raise the lock only if all
  re-parse). The lock lives in the **governed project** as `.sdlc-lock.json` and travels with that
  project's git — not to be confused with the project's own product version.
- **No duplicated governance logic.** Halt-point decisions are obtained by `subprocess`-calling the
  skill's `scripts/halt_gate.py` (exit `0`=AUTO, `10`=HALT); role definitions are parsed from the
  skill's `references/agent-hierarchy.md`. The runner holds no risk matrix and no hardcoded role
  table of its own.
- **Stages run sequentially with shallow fan-out.** Four stages (requirement analysis → structure
  design → implement → acceptance), each passing a halt gate, with a checkpoint at every boundary
  (`--resume` continues from the last one). Fan-out is capped at depth ≤ 3 / concurrency ≤ 4 —
  deliberately conservative to save tokens (the platform supports more). These runtime limits live
  in `config/runner.yaml` and are probed at startup; the contract targets the skill's stable output,
  not Claude Code's current runtime behavior.
- **V1 verifier is locked down.** The independent acceptance agent is spawned with a tools allowlist
  that **excludes `Agent`** (it cannot spawn or fix while verifying) and is read-only on the code
  under review (but may run tests/CLI/GUI to verify).
- **Red lines always halt.** Deploy/release, data migration/irreversible schema, delete/drop, money,
  secrets/permissions, and publishing are never auto-run — they always surface for human approval.

> **The skill without the runner is still a pure skill.** Installing the runner adds an external
> driver; it does not modify or depend back on the skill.

## Governance

This repo is itself governed by ai-sdlc (dogfooding). See `docs/ai-guideline.md`,
`docs/structure/*.md`, `docs/changes/CHG-*.md`, and `docs/acceptance/ACC-*.md`.
