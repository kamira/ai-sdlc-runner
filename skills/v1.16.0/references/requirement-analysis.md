---
name: requirement-analysis
description: >
  Analyze requirements and produce a standardized "AI Guideline" document that serves as the
  single source of truth for subsequent AI development, design, and acceptance. Whenever the
  user describes a new project, a new requirement, wants to build some system/feature, or says
  "analyze the requirements", "help me clarify what I need", "how should this be done", or
  "plan this out", be sure to use this skill to first turn the requirements into a Guideline
  before any design or implementation. Covers goal clarification, scope definition, constraints
  and assumptions, stakeholders, functional and non-functional requirements, acceptance criteria.
  This is stage one of the ai-sdlc process.
---

# requirement-analysis — produce an AI Guideline from requirements

> 語言 / Language: [繁體中文](requirement-analysis.zh-tw.md) · **English**

## Purpose

Turn the user's requirements (often scattered, colloquial, full of hidden assumptions) into a structured **AI Guideline**. This document is the single basis for all later stages (structure design, modification, acceptance), so the AI never has to re-guess what the user wants.

## When to use

- A new project or a major new feature arrives
- Requirements are vague, colloquial, or mix multiple goals and need clarifying first
- The user asks "how should I plan / build this"
- Before entering `structure-design`

If the request is a modification or new feature on an *existing* system, use `modification-guide` instead (it will reference this stage's Guideline when needed).

## Workflow

1. **Read existing context**: if the project already has `docs/ai-guideline.md`, read it first to avoid duplication or conflict.
2. **Clarify, don't assume**: proactively ask about key unknowns — goals, users, scale, constraints, deadlines, tech preferences, acceptance criteria. Ask the important things; don't drown the user in a wall of questions at once.
3. **Consolidate**: split the conversation into functional and non-functional requirements; flag assumptions and open items.
4. **Produce the Guideline**: write `docs/ai-guideline.md` using the template below.
5. **Hand back for confirmation**: ask the user to confirm the Guideline before entering structure design.

**Elicitation by proxy (when subagents can be dispatched)**: the **decision agent does not conduct the user Q&A**. The elicitor (A1) owns the whole conversation — asks, iterates until the requirement is **fully understood** (open items resolved or explicitly deferred) — then hands up a **proposal (企劃)**: the draft Guideline + resolved clarifications + an impact sketch. The decision agent reads **the proposal, not the transcript** (transcripts replicate anchoring — the same reason verifiers never get the implementer's narrative), and convenes the review panel on it (decision quota ≥5, see review-panel). This separates *information gathering* from *adjudication*; the **confirm gate still goes to the user directly** — approval authority is never proxied. No spawn available → the same agent asks and decides, and notes that limitation in the record.

**Knowledge bootstrap (founded before work, not lazily)**: creating `docs/` includes creating `docs/knowledge/` **at this stage** — an empty INDEX (+ a vocabulary stub) is a valid knowledge base. Don't wait for the first correction: interaction-style observations count from the very first exchange — even "how the user prefers to deliver instructions needs adjusting" is a knowledge entry (tag `interaction`; see knowledge).

## Clarification checklist

Cover these when asking (without robotically reciting them):

- **Goal**: what problem to solve? What does success look like?
- **Users / stakeholders**: who uses it? Who decides?
- **Scope**: what's in this round, and what's explicitly out (to prevent scope creep).
- **Constraints & assumptions**: deadline, budget, existing systems, compliance, tech preferences.
- **Non-functional needs**: performance, security, maintainability, compatibility, scale.
- **Acceptance criteria**: what counts as done? Measurable standards.

## AI Guideline template

Produce `docs/ai-guideline.md` using this fixed structure:

```markdown
# AI Guideline — <project/feature name>

- Project: <project id / name>   ← required across projects, so this doc is clearly attributable
- Branch: <branch>   ← required with multiple branches; use same-branch sources only (see branch-isolation)
- Version: v1.0   ← after a structure change or requirement update, revise this doc and bump (see below)
- Date: YYYY-MM-DD
- Status: Draft / Confirmed

## 1. Background & Goals
<why we're doing this, the problem to solve, definition of success>

## 2. Scope
### In scope
- ...
### Out of scope (explicitly excluded)
- ...

## 3. Stakeholders
| Role | Concern |
|------|---------|
| ... | ... |

## 4. Functional Requirements
| ID | Requirement | Priority (P0/P1/P2) | Notes |
|----|-------------|---------------------|-------|
| FR-1 | ... | P0 | ... |

## 5. Non-Functional Requirements
| Category | Requirement |
|----------|-------------|
| Performance | ... |
| Security | ... |
| Maintainability | ... |
| Compatibility/Scale | ... |

## 6. Constraints & Assumptions
- Constraints: ...
- Assumptions: ...
- Open items: ...

## 7. Acceptance Criteria
- [ ] <measurable criterion tied to a specific requirement>

## 8. AI Development Conventions
<principles later AI work must follow: naming, tech-direction, where docs live,
which skills to pair with, etc.>
```

## Writing tips

- **Acceptance criteria must be measurable**: "fast" won't do; "list page p95 < 500ms" will. Tie each to a functional requirement where possible.
- **State "out of scope" explicitly**: the boundary of scope prevents disputes better than the scope itself.
- **Mark open items**: don't hard-fill uncertainties — put them under "open items" for the user to fill.
- **Section 8 is for the future AI**: spell out conventions specific to this project so later stages have a basis.

## Guideline maintenance (revise after any change)

The Guideline is a living document, not one-off: **whenever the structure is adjusted or requirements change, the existing Guideline must be revised in sync and bumped** (update the affected FR/scope/acceptance criteria, version +1, note it in the change history). The modification flow (modification-guide) checks at close-out that the Guideline kept up; doc verification (doc-integrity) treats "Guideline lagging behind the agreed structure/requirements" as drift. A stale Guideline misleads every later stage.

**Major revision (pivot)**: when the requirement fundamentally changes direction, don't rewrite history — bump the Guideline a **major** version; mark dropped FRs **deprecated (date + superseded-by)** instead of deleting them; **never reuse FR ids**. Old CHG/ACC remain valid **against the Guideline version they cite** (records carry dates and versions, so the old trail still reads correctly); only new work aligns to the new version. The pivot itself goes through modification-guide — it is a change, usually high-risk.

## After delivery

Once the user confirms the Guideline, move on to `structure-design` to produce the system structure from it.
