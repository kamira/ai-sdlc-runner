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
- Any change that would make the current structure documents inaccurate
- **Routed back from a failed acceptance**: when `acceptance-verification` reports fail/partial, return to this skill to produce a fix for the unmet items, then re-implement and re-verify

Exception: a brand-new project from scratch goes through `requirement-analysis` → `structure-design`, and this skill does not apply.

## Workflow

1. **Read the baseline**: read `docs/ai-guideline.md` and `docs/structure/*.md` to grasp the current state. If these don't exist, create them first (return to the matching skill) or note the gap in the record. **If you entered because acceptance failed, first read the relevant `docs/acceptance/ACC-*.md` and treat its unmet items as the target list for this fix.**
2. **Impact analysis**: determine which modules, components, data, and interfaces this change touches, plus knock-on effects (dependency direction, compatibility, data migration).
3. **Produce the modification guide**: use the template below to write concrete, executable steps so an implementer (human or AI) can just follow them.
4. **Adjust structure documents**: if the change alters the structure, **update** the corresponding files under `docs/structure/` — structure docs must always reflect the latest truth.
5. **Leave a change record**: add a record under `docs/changes/` (see template), stating motivation and trade-offs clearly. For a fix driven by failed acceptance, link back to that ACC report in the record's "Related" field.
6. **Close acceptance in the same round (no handoff)**: once implemented, **immediately produce the matching `docs/acceptance/ACC-*.md` via `acceptance-verification` within the same round**, and update this CHG's status to "Accepted" with a link to the ACC. **Do not just mark it "pending acceptance" and stop** — in cross-session work the next session brings a new requirement, nobody comes back to do a deferred acceptance, so it hangs forever. **If items still fail, return to step 1, forming a "fix → re-implement → re-verify" loop until everything passes or the user explicitly accepts.**

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

### Modification steps
1. ...
2. ...

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
- Date: YYYY-MM-DD
- Type: new feature / fix / refactor / adjustment
- Proposed by: <user>
- Implemented by: <person / agent id>   ← used for the "verifier ≠ implementer" identity check
- Risk: high / medium / low (see grading below; drives acceptance rigor, CI gates, and autonomy halts)
- Autonomy: (optional) auto / halt   ← override the autonomous-run halt point (tighten only; see autonomy)
- Related: <requirement ID / prior change / acceptance report>

## Motivation
<why this change is needed>

## Decisions & trade-offs
| Decision | Options | Why this choice |
|----------|---------|-----------------|
| ... | A vs B | ... |

## Modification guide
<see modification guide template above>

## Structure change summary
<which structure docs were updated, and the key points>

## Status
Draft / Implemented / Accepted (link acceptance report)
```

## Risk grading and matching rigor

Grade each change's risk first so **governance rigor matches risk** (don't over-govern low risk, don't under-govern high risk):

| Level | Typical cases | Required rigor |
|-------|---------------|----------------|
| **High** | data model / migration, auth, payments, deletion / irreversible, cross-module interfaces, security | **independent acceptance** (verifier ≠ implementer) + **multi-scenario**; CI **identity check**; full pipeline; rollback plan required |
| **Medium** | behavior change to existing features, new non-breaking endpoint/field | at least independent acceptance or full tests; structure sync; pipeline gate |
| **Low** | copy, comments, styling, pure internal refactor with test coverage | self-verify + tests green; pre-commit is enough |

When in doubt, grade up. Put the risk in the CHG header; it drives the acceptance and CI gates that follow.

## Writing tips

- **Structure and records must keep up with code**: this skill's greatest value is keeping docs from lagging. Changing the structure without updating `docs/structure/` means the job isn't done.
- **Record the "why", not just the "what"**: decisions and trade-offs are the most valuable future information. Code shows what changed, not why it was chosen this way.
- **Look one layer outward in impact analysis**: not just the change point itself, but whether things depending on it might break.
- **Stay traceable**: link the change record back to requirement IDs and acceptance reports to form a complete chain.

## After delivery

Once the modification is implemented, move to `acceptance-verification`, using this change's "modification guide" and acceptance criteria as the baseline.
