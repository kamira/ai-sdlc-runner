---
name: ci-cd
description: >
  Optional: wire ai-sdlc's document governance into automated checks so "documents are the truth" is
  enforced by machine, not just by discipline. Opt in per solo or team need — it can run in a
  pipeline (authoritative PR/merge gates) or as pre-commit (local preliminary checks), and the two
  can be combined. Read this to turn acceptance and structure-consistency into gates. Covers
  governance-artifact-to-gate mapping, recommended gates, and platform-neutral pre-commit and
  pipeline examples.
---

# ci-cd (optional) — wire governance into CI/CD

> 語言 / Language: [繁體中文](ci-cd.zh-tw.md) · **English**

## Purpose (optional)

**Opt in per solo or team need.** If a project has CI/CD, turn ai-sdlc's document governance into **automated gates** so "documents are the truth", "trace every change", and "acceptance aligns to source" are enforced by machine rather than by discipline. **Projects without a pipeline can skip this** and rely on the ai-sdlc flow. Solo projects are often simpler; teams need it more; either may opt in.

## When to read

- A team project has or is adopting CI/CD
- You want acceptance and structure-consistency to become merge / PR gates
- Multi-person / multi-agent collaboration that needs machine enforcement so nobody skips governance

## Governance artifact → gate mapping

| ai-sdlc artifact | CI/CD counterpart |
|------------------|-------------------|
| Acceptance criteria (Guideline §7 / ACC) | automated tests; CI runs them as a gate |
| Change record CHG | required PR template field; PR must link the CHG |
| Structure docs `docs/structure/` | structure-drift check (below) |
| Acceptance report ACC | merge gate: no matching, passing ACC → no merge |

## Recommended gates (loose → strict; pick per team needs)

1. **Tests must be green**: maps to acceptance criteria; the baseline.
2. **PR must link a CHG**: PR description must contain a `CHG-` reference (maps to "trace every change").
3. **Structure-sync check**: if this PR changed structural code (e.g. `src/models/**`, schema) but didn't update `docs/structure/`, warn or block (maps to "documents are the truth").
4. **Acceptance gate**: an ACC for this change exists and concludes "pass" before merge (maps to "close acceptance in the same round").
5. **Identity check (verifier ≠ implementer)**: compare the ACC's "Verifier" with the CHG's "Implemented by" (or commit author / agent id); **they must differ** — turning "player can't be referee" into a machine-enforceable gate. **Mandatory for high-risk changes**; low-risk may be exempt (self-verification allowed).

Adopt **loose → strict**: start with "tests green + PR links CHG", and once the team is used to it add structure-sync, the ACC gate, and the identity check, so you don't stall the flow by being too strict at once.

### Apply gates by risk level

Read the CHG's "Risk" to decide which gates apply: **high** → all of them (identity check, full pipeline, multi-scenario); **medium** → tests + structure-sync + ACC; **low** → tests green is enough, pre-commit is fine. Match rigor to risk rather than treating everything the same.

## Two checkpoints: pre-commit (preliminary) and pipeline (full)

Gates can live at two levels; use either or both:

- **pre-commit (local, fast, preliminary)**: before a commit, run "cheap, sub-second" checks to stop obvious problems before they enter version control — e.g. lint/format, quick unit tests, a `CHG-` reference check, a "changed structural files but didn't touch docs/structure" reminder. Use the `pre-commit` framework or a git hook (`.git/hooks/pre-commit`). **Preliminary and bypassable (`--no-verify`), so not the final line of defense.**
- **pipeline (CI, full, authoritative)**: on PR / merge, run the full tests, structure-sync, and ACC gates — **not bypassable, the final line of defense**.

Suggested split: **put the fast and cheap in pre-commit for instant feedback; put the slow and authoritative (full tests, ACC gate) in the pipeline.** The same check can live in both (pre-commit warns early, pipeline enforces). A solo project may use pre-commit only; a team should have at least the pipeline.

### pre-commit example (platform-neutral pseudo)

```yaml
# concept: .pre-commit-config.yaml or .git/hooks/pre-commit
pre-commit:
  - run: <lint / format>
  - run: <quick unit tests>
  - run: python3 scripts/doc_integrity_check.py --staged   # structure drift + CHG↔ACC link; blocks the commit
  - check: commit message or staged diff contains a "CHG-" reference
```

> **Turn "by discipline" into "by machine"**: `scripts/doc_integrity_check.py --staged` checks, before commit, "structural code changed but docs/structure not synced" and "an implemented CHG has no matching ACC (acceptance hanging)", failing the commit otherwise. Semantic content still needs a human/agent, but *whether it's synced* is machine-enforced — no longer discipline-only.

## Platform-neutral example (pipeline, pseudo)

Conceptual sketch; translate to any CI platform (GitHub Actions / GitLab CI / Jenkins...):

```yaml
on: pull_request
jobs:
  governance:
    steps:
      - run: <run tests>                    # gate 1: tests green
      - check: PR body contains "CHG-"      # gate 2: traceability
      - check: if changed_files match structural paths (src/models|schema),
               then docs/structure/ must also have changes        # gate 3: structure sync
      - check: docs/acceptance has an ACC for this CHG concluding "pass"  # gate 4: acceptance gate
      - check: if CHG risk=high, the ACC's "Verifier" ≠ the CHG's "Implemented by"  # gate 5: identity check
```

GitHub Actions example: trigger on `on: pull_request`; `gate 1` runs the test step; `gate 2/3/4` use a script that reads the PR body and `git diff --name-only`, compares paths, and greps `docs/acceptance/` for the matching file — any failing check exits non-zero to block the merge. Other platforms (GitLab CI `rules`, Jenkins stages) work the same way.

## Relation to the base flow

CI/CD **does not replace governance; it enforces that governance is followed**. ai-sdlc defines "what documents to produce and how to verify"; this file turns those into machine-checkable gates. The team edition especially needs it — with more people, discipline alone is unreliable. Optional: without a pipeline, rely on the ai-sdlc and cross-agent flows.
