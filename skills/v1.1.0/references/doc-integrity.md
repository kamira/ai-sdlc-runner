---
name: doc-integrity
description: >
  Document anti-drift and verification: ai-sdlc uses docs/ as the basis for later work, so the
  documents themselves must be continuously verified and must not drift from the code or from each
  other — solo development drifts too (you change code and forget to update the docs), and it's
  worse in a team / multi-agent setting. Read this to confirm existing docs are still trustworthy,
  when closing a change, or on takeover. Covers code↔doc bidirectional consistency, doc↔doc
  consistency, scriptable drift detection, and independent review. Applies to solo and teams.
---

# doc-integrity — document anti-drift & verification

> 語言 / Language: [繁體中文](doc-integrity.zh-tw.md) · **English**

## Purpose

ai-sdlc uses `docs/` as the basis for later work (**solo or team**) — so **once the docs drift from reality (the code) or from each other, later decisions rest on a wrong basis**. Drift is not a team-only problem: solo / single-agent work also "changes the code but forgets to update the docs"; it's just worse and harder to spot with a team / multiple agents. This file ensures docs are not merely "written" but **continuously verified and kept drift-free**.

## When to read

- To confirm whether existing `docs/` is still trustworthy (especially when taking over someone else's / another agent's project)
- When closing each change (verify doc consistency together with acceptance)
- During an agent's Session startup check

## Two kinds of consistency (both matter)

### 1. Code ↔ docs (vertical)
- If structural code changed (modules, data models, interfaces/APIs), `docs/structure/` must be synced; conversely, entities/modules/interfaces the docs describe must be findable in the code.
- Acceptance criteria (Guideline §7) must match actual behavior and tests.

### 2. Docs ↔ docs (horizontal)
- The four structures line up: logical modules ↔ directory folders ↔ design components ↔ data entities, with consistent names and boundaries.
- Every FR in the Guideline traces down to structure and some ACC; every CHG links back to an FR and forward to an ACC.

## Anti-drift trigger points

Not one-off, but embedded in the flow and checked repeatedly:
- **Change close-out**: when closing a CHG, also confirm structure docs are synced (per modification-guide's "documents are the truth").
- **On entry**: during the Session startup check, sweep doc consistency; fix drift before doing new work.
- **CI (optional)**: automate it as a PR gate via ci-cd's "structure-sync check".

## How to verify

- **Script what you can** (preferred — repeatable, unbiased):
  - This skill bundles **`scripts/doc_integrity_check.py`**: it checks "structural code changed but `docs/structure/` not synced" and "an implemented CHG has no matching ACC", exiting non-zero otherwise. Wire it into pre-commit / CI to turn "by discipline" into "by machine": `python3 scripts/doc_integrity_check.py --staged`.
  - An entity/module name mentioned in docs can't be grepped in the code → flag (docs may be stale or names drifted).
  - Every FR appears in structure/ACC.
- **Independent review for the rest**: whether the meaning is still correct and the rationale still holds — give it to a non-author agent (see independent-acceptance).

## Document verification checklist

Each document should satisfy:
- [ ] has a version and date (you can tell new from old)
- [ ] traceable: links to its FR / CHG / ACC numbers
- [ ] consistent with the latest code (vertical)
- [ ] consistent with the other structure docs (horizontal)

## When you find drift

**Don't silently edit the doc** — return to `modification-guide` and add a "doc sync" change (or note it in the current CHG), stating the drift and the fix, to keep the trail. Drift itself is a signal worth recording: it means some earlier change failed to bring the docs along.
