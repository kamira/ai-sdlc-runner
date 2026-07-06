---
name: modification-guide
description: >
  Govern ALL modifications and new features on an existing system: produce a modification guide,
  assess impact on existing structure, update structure documents in sync, and leave a change
  record. Whenever the user proposes any change in a session — "modify", "tweak this", "add a
  feature", "add a ...", "adjust", "refactor", "this needs to change" — it is mandatory to load
  and follow this skill; do not start changing code directly. It is mandatory to load this skill
  whenever a change is proposed. Covers impact analysis, modification guide, structure adjustment,
  change records. This is stage three of the ai-sdlc process; it is usually followed by
  acceptance-verification.
---

# modification-guide — change governance & change records

> 語言 / Language: [繁體中文](modification-guide.zh-tw.md) · **English**

## Purpose

Every modification or new feature on an existing system passes through here first: analyze what the change will touch, produce a clear modification guide, update structure docs in sync, and leave a change record. The goal is to avoid the architectural drift caused by "changing the code while docs and decisions fall behind".

## Mandatory-load rule (original requirement #5)

**This is a hard rule: whenever the user proposes a modification or new feature within a session, the AI must first load this skill and follow its process — it may not skip straight to changing code.**

Why mandatory: any change can touch existing structure and prior design decisions. If you skip governance and edit directly, you tend to get changes that conflict with the architecture, missed knock-on edits, and a "why was it changed this way" that nobody remembers. Running this process once is cheap, yet it preserves consistency and traceability.

How to tell it's triggered (any of these is a change and requires loading this skill):

- A request to adjust, fix, or extend an existing feature/file/table
- Adding a feature to an existing system
- Refactoring, renaming, moving, or deleting existing structure
- **Rolling back / reverting a previous change** (git revert included): a revert is itself a change — open a CHG linking the original CHG, and bring structure docs back in line with the reverted state
- Any change that would make the current structure documents inaccurate
- **Routed back from a failed acceptance**: when `acceptance-verification` reports fail/partial, return to this skill to produce a fix for the unmet items, then re-implement and re-verify

Exception: a brand-new project from scratch goes through `requirement-analysis` → `structure-design`, and this skill does not apply.

## Workflow

1. **Read the baseline**: read `docs/ai-guideline.md` and `docs/structure/*.md` to grasp the current state. If these don't exist, create them first (return to the matching skill) or note the gap in the record. **If you entered because acceptance failed, first read the relevant `docs/acceptance/ACC-*.md` and treat its unmet items as the target list for this fix.**
2. **Impact analysis**: determine which modules, components, data, and interfaces this change touches, plus knock-on effects (dependency direction, compatibility, data migration). **Also check assumptions**: scan the Decisions tables of prior CHGs touching this scope — if this change invalidates a recorded assumption, that decision must be re-evaluated (fold it into this CHG or open a follow-up), not silently left standing.
3. **Produce the modification guide**: use the template below to write concrete, executable steps so an implementer (human or AI) can just follow them. During implementation, **tick each step off the moment it's done** — if the session dies mid-implementation, the next session reconciles the unticked steps against the working tree (see handshake) instead of guessing how far you got.
4. **Adjust structure documents + revise the Guideline**: if the change alters the structure, **update** the corresponding files under `docs/structure/` — structure docs must always reflect the latest truth. If the change also touches requirements/scope/acceptance criteria, **revise `docs/ai-guideline.md` and bump it too** (a stale Guideline misleads later stages).
5. **Leave a change record**: add a record under `docs/changes/` (see template), stating motivation and trade-offs clearly. For a fix driven by failed acceptance, link back to that ACC report in the record's "Related" field.
6. **Confirm gate (before touching code)**: present the user a short summary — motivation, impact scope, the decisions **made on their behalf** (anything not derivable from the Guideline/docs/their instructions), and the risk grade — and get their confirmation before implementing. The user **reviews the risk grade here** (see grading: high-risk-list hits don't accept self-downgrades). **Pre-authorization**: the user may waive per-change confirmation for a class of changes ("this kind, just do it") — record it as a knowledge directive, written **narrow** (situation + boundary; a fuzzy boundary falls back to asking). Usage is counted in governance health; a class that misfires is **auto-revoked** (see CHG-lite). In solo sessions the AI should **proactively suggest** pre-authorization when it notices repeated confirmations of the same class. Autonomous runs use the halt contract (autonomy) instead of this interactive gate — same intent, two channels.
7. **Close acceptance in the same round (no handoff)**: once implemented, **immediately produce the matching `docs/acceptance/ACC-*.md` via `acceptance-verification` within the same round**, and update this CHG's status to "Accepted" with a link to the ACC. **Do not just mark it "pending acceptance" and stop** — in cross-session work the next session brings a new requirement, nobody comes back to do a deferred acceptance, so it hangs forever. **If items still fail, return to step 1, forming a "fix → re-implement → re-verify" loop until everything passes or the user explicitly accepts.** At close-out, also check whether this change's **motive/purpose repeats a prior CHG's** — a second occurrence triggers an autonomous **shallow knowledge record** (evidence + counters in the entry; see knowledge "autonomous triggering").

## Modification guide template

Write into the "modification guide" section of the change record, or split into a separate file as appropriate:

```markdown
## Modification Guide
### Goal
<what this achieves; which requirement/problem it maps to>

### Impact scope
| Affected item | Type (directory/logical/design/data) | Change | Knock-on effect |
|---------------|--------------------------------------|--------|-----------------|
| ... | design | ... | ... |

### Modification steps (tick each immediately when done — the ticks are the resume point after an interruption)
- [ ] 1. ...
- [ ] 2. ...

### Structure document updates
- [ ] docs/structure/<file> synced: <what changed>

### Risk & rollback
- Risk: ...
- Rollback: ...
```

## Change record template

One record per change; suggested filename `docs/changes/CHG-YYYYMMDD-NN.md`:

```markdown
# CHG-YYYYMMDD-NN — <change title>

- Project: <project id / name>   ← required across projects; when several projects are in play, prefix the change id (e.g. PROJ-CHG-…)
- Branch: <branch>   ← required with multiple branches; reference same-branch requirements/acceptance only (see branch-isolation)
- Date: YYYY-MM-DD (UTC+0)
- Type: new feature / fix / refactor / adjustment
- Proposed by: <user>
- Implemented by: <person / agent id>   ← used for the "verifier ≠ implementer" identity check
- Risk: high / medium / low (see grading below; drives acceptance rigor, CI gates, and autonomy halts)
- Autonomy: (optional) auto / halt   ← override the autonomous-run halt point (tighten only; see autonomy)
- Commit/PR: <hash / PR link>   ← filled at close-out; see "commit granularity" below
- Skill: ai-sdlc v<X.Y>   ← convention version this record was written under (new rules apply prospectively; see doc-integrity)
- Related: <requirement ID / prior change / acceptance report>

## Motivation
<why this change is needed>

## Decisions & trade-offs
| Decision | Options | Assumptions (premises this rests on) | Why this choice |
|----------|---------|--------------------------------------|-----------------|
| ... | A vs B | ... | ... |

## Modification guide
<see modification guide template above>

## Structure change summary
<which structure docs were updated, and the key points>

## Status
Draft / Implemented / Paused (reason + resume condition) / Accepted (link acceptance report)
```

**Commit granularity (commit anchoring)**: the code, this CHG, and its ACC land in the **same commit / PR**, and the **commit message carries the CHG id** (e.g. `CHG-20260702-02: …`). This is what makes history reconcilable — the handshake's commit scan flags any commit that references no CHG as ungoverned work. Fill the `Commit/PR:` header field at close-out.

**PR / squash / rebase workflows**: what survives history rewriting is the **message and the PR number**, not the hash — so the CHG id in the message is the primary anchor and the hash is best-effort. Squash merge: the squash commit **must carry the CHG id(s)** (put them in the PR title, or make sure they land in the squash message); the trunk is then scanned at squash-commit granularity, while per-commit scanning applies on the feature branch before the squash. Rebase / force-push: message-id matching survives the rewrite; at close-out backfill `Commit/PR:` with the **trunk commit / PR number** (stable), not a pre-rebase hash.

**Pausing a change (interleaved requirements)**: when a new requirement interrupts an in-progress CHG, don't leave it ambiguous — set its status to **Paused** with the reason and resume condition. Paused CHGs are listed at every session startup and consciously resumed or closed; a pause is legitimate WIP, unlike a hanging acceptance (implemented but never accepted), which must still be closed first.

## Risk grading and matching rigor

Grade each change's risk first so **governance rigor matches risk** (don't over-govern low risk, don't under-govern high risk):

| Level | Typical cases | Required rigor |
|-------|---------------|----------------|
| **High** | data model / migration, auth, payments, deletion / irreversible, cross-module interfaces, security | **full review panel** (see review-panel) + **independent acceptance** (verifier ≠ implementer) + **multi-scenario** + **regression run (affected scope)**; CI **identity check**; full pipeline; rollback plan required |
| **Medium** | behavior change to existing features, new non-breaking endpoint/field | **≥5-seat review** when spawnable (see review-panel); at least independent acceptance or full tests (≥3 verifiers when spawnable); **regression run (affected scope)**; structure sync; pipeline gate |
| **Low** | copy, comments, styling, pure internal refactor with test coverage | self-verify + tests green; pre-commit is enough |

When in doubt, grade up. Put the risk in the CHG header; it drives the acceptance and CI gates that follow.

**Grading is not solely self-assessed**: a hit on the high-risk list (data model/migration, auth/permissions, payments, deletion/irreversible, cross-module interfaces, security) is **high regardless of the AI's own grading** — no self-downgrade; and the user reviews the grade at the confirm gate. An unconsidered situation must not slip through every gate just because the AI graded itself "low".

## Lightweight record for low risk (CHG-lite)

Record-keeping cost must scale with risk too — demanding the full template for a typo fix is how people learn to bypass the flow. For **low-risk** changes a one-screen CHG suffices, same id and anchoring rules:

```markdown
# CHG-YYYYMMDD-NN — <title>
- Date: YYYY-MM-DD (UTC+0) | Branch: <branch> | Risk: low | Implemented by: <id>
- Motivation: <one sentence>
- Commit/PR: <hash / PR>
## Status
Accepted — self-verified (low risk): <one-line reproducible evidence, e.g. `pytest tests/x -q` green>
```

- **Eligibility is a whitelist, not a feeling**: copy/comments, styling, docs-only edits, pure internal refactors with test coverage. Anything touching structure, data, or interfaces is out; outside the whitelist → full template, no matter how small it feels.
- The inline self-acceptance line replaces a separate ACC **only at low risk** (the grading table already allows self-verify there) — it must contain the evidence, and the lint accepts it (a low-risk CHG marked self-verified is exempt from the ACC-file requirement).
- **Misfire = forced upgrade**: if a lite change is later caught breaking something (regression / acceptance), backfill a **full CHG** with the root cause into knowledge, and any pre-authorization covering that class is **auto-revoked** until the user re-grants it.
- Medium / high risk always use the full template + a separate ACC (+ review panel per risk, see review-panel).

## Expedited path (emergency)

When production is down or data is actively at risk, "governance first" would block the fix — that's when people abandon the whole flow. So there is a **legitimate emergency lane**:

- **Trigger**: a human explicitly declares an emergency (production incident, active data loss/security exposure). Not for "I'm in a hurry".
- **During**: fix first. Keep a minimal trace as you go — one worklog line ("emergency: what broke, what I'm changing").
- **After (within 24h)**: backfill a **retroactive CHG** (`Type: emergency / retroactive`, linking the incident and commits) + its ACC, and sync structure docs. The emergency lane defers the paperwork; it never waives it.
- **Audit**: retroactive CHGs are explicitly marked, so health metrics and reviews can see how often the lane is used — frequent use means the normal flow is too slow, which is its own finding.
- **Violation is defined as not backfilling**, not as using the lane.

Relation to autonomy: an explicit human emergency declaration counts as the human approval that halt gates await (see autonomy); always-halt actions are still executed by/with the human, never silently.

## Writing tips

- **Structure and records must keep up with code**: this skill's greatest value is keeping docs from lagging. Changing the structure without updating `docs/structure/` means the job isn't done.
- **Record the "why", not just the "what"**: decisions and trade-offs are the most valuable future information. Code shows what changed, not why it was chosen this way.
- **Look one layer outward in impact analysis**: not just the change point itself, but whether things depending on it might break.
- **Stay traceable**: link the change record back to requirement IDs and acceptance reports to form a complete chain.

## After delivery

Once the modification is implemented, move to `acceptance-verification`, using this change's "modification guide" and acceptance criteria as the baseline.
