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
  - This skill bundles **`scripts/doc_integrity_check.py`**: it checks "structural code changed but `docs/structure/` not synced" and "an implemented CHG has no matching ACC" (Paused CHGs are legitimate WIP and skipped), plus **template field lint** (required CHG/ACC header fields), a **secrets scan** over docs/, and `--commits-since <anchor>` (a commit whose message references no CHG id = ungoverned work). Exits non-zero on any hit. Wire it into pre-commit / CI to turn "by discipline" into "by machine": `python3 scripts/doc_integrity_check.py --staged`.
  - **Trend, not just point checks**: `scripts/governance_health.py` reports the governance health of a repo — CHG status distribution, hanging acceptances, paused/stale items, emergency-retroactive and doc-sync counts, ACC pass rates. Run it periodically (or in CI, non-blocking); retrospective findings go into knowledge.
  - An entity/module name mentioned in docs can't be grepped in the code → flag (docs may be stale or names drifted).
  - Every FR appears in structure/ACC.
- **Independent review for the rest**: whether the meaning is still correct and the rationale still holds — give it to a non-author agent (see independent-acceptance).

## Document verification checklist

Each document should satisfy:
- [ ] has a version and date (you can tell new from old)
- [ ] traceable: links to its FR / CHG / ACC numbers
- [ ] consistent with the latest code (vertical)
- [ ] consistent with the other structure docs (horizontal)
- [ ] carries **no secrets** (tokens, passwords, keys, connection strings — reference by name/location, never by value; docs are long-lived and shared)
- [ ] **protected docs** (knowledge directives, halt policy, the Guideline): changes to them are user-visible — called out in the entry ack / covered by a CHG, never edited silently

## Convention versioning (prospective enforcement)

Records carry `Skill: ai-sdlc vX.Y` — the convention version they were written under. **Newer rules apply prospectively**: don't retro-fail records produced under an older convention (the machine lint hard-requires only fields that have existed since v1.0; stricter checks are opt-in flags like `--require-commit`). On entry, compare the running skill version with the versions in recent records: records **newer** than the installed skill → the skill is outdated, upgrade before working (see handshake).

## When you find drift

**Don't silently edit the doc** — return to `modification-guide` and add a "doc sync" change (or note it in the current CHG), stating the drift and the fix, to keep the trail. Drift itself is a signal worth recording: it means some earlier change failed to bring the docs along.

**Adjudication — which side is right**: docs record **intent**, code is **current reality**; "docs win" applies to *memory vs docs*, not to *reality vs docs*. Trace the CHG trail to decide the fix direction:
- The code state is explained by an accepted CHG whose doc sync was missed → **update the docs** to match (doc-sync change).
- No CHG explains the code state → an **ungoverned change**: reconstruct a CHG for it (if the change should stand) or revert it (a revert is also a CHG); when the intent is unclear, **ask the user** — don't pick a side silently.

## Growth & archiving

`docs/changes/` and `docs/acceptance/` grow without bound; past a threshold (suggest ~50 closed records, or quarterly) entry scans get slow and noisy:
- Move **fully closed** records (CHG Accepted + its ACC) into `docs/changes/archive/` / `docs/acceptance/archive/`; never archive open ones.
- Keep one index line per archived record in `docs/changes/INDEX.md` (id / title / status / links) so traceability survives archiving.
- Entry checks (handshake, `doc_integrity_check.py`) scan only non-archived records.
