---
name: cross-agent
description: >
  Cross-agent / multi-session collaboration and handoff mechanism: how multiple AI agents, or one
  agent across many sessions, keep the same project consistent, conflict-free, and handoff-ready
  via docs/. Read this when work changes hands, accumulates across sessions, or multiple agents
  touch the same project at once. Covers the sequential handoff protocol and parallel multi-agent
  claim/lock/merge.
---

# cross-agent — cross-agent collaboration & handoff

> 語言 / Language: [繁體中文](cross-agent.zh-tw.md) · **English**

## Purpose

Keep one project consistent, conflict-free, and handoff-ready when it's developed by multiple AI agents, or by one agent across multiple sessions (sequentially or in parallel). The core move: promote `docs/` from "memory" to "the collaboration medium between agents".

## When to read

- Work will be continued by a different session / different agent (cross-session incremental development)
- Multiple agents may touch the same project at the same time
- Any handoff situation (to someone else, or to your future self)

## Core principle: docs/ is the single source of truth between agents

Don't pass state between agents through conversation memory — it can't cross agents and gets compacted. Every agent **reads `docs/` on entry** (echoing this skill's "Session startup check" and the principle "don't rely on memory, rely on the docs"). The precondition for the next agent to continue is that the previous agent wrote the full state into the docs.

## Mode A: sequential handoff (one agent at a time)

The validated common case (matches the cross-session scenario in the loop test).

- **On entry**: run the Session startup check — scan `docs/changes/` for any status ≠ Accepted and `docs/acceptance/` for missing ACC; close those acceptances first, then start new work.
- **On exit (before handoff)**: close acceptance in the same round, set CHG status to Accepted, sync the structure docs — leave a clean, continuable state for the next agent.
- **Handoff checklist** — before leaving, confirm:
  - [ ] docs and code are consistent (structure docs reflect the latest truth)
  - [ ] no dangling stage (every CHG has a matching ACC)
  - [ ] latest decisions and open items are written into CHG / Guideline
  - [ ] the next step is stated in the record (the next agent can pick up just by reading docs)

## Mode B: parallel multi-agent (touching the same project at once)

Risks: overwriting each other, conflicting structure docs, duplicate/conflicting changes, CHG number clashes. Mechanism:

- **Claim**: before starting, declare in the coordination file (below) "my **role**, I'm doing X, locking scope Y, my **read/write permission**", with owner + time + status (in progress). Claim first, then work.
- **Role and read/write permission**: every agent has an explicit role (implementer / verifier / integrator / reviewer…) and a **readable/writable scope**. Least privilege: grant only the write scope that role needs. E.g. the verifier is **read-only** (must not edit the code under review); the implementer may write only its claimed scope; structure docs are written by whoever owns that module. This both prevents accidental edits in parallel and is the precondition for independent acceptance.
- **Scope boundary**: claim **non-overlapping** module/file scopes. On overlap, the later agent waits or coordinates — never barges in.
- **Single-writer rule**: the same structure doc / same module is written by only one agent at a time, to avoid races.
- **Reserve CHG numbers**: CHG uses date+sequence; reserve the number at claim time (e.g. CHG-YYYYMMDD-03) so two agents don't collide.
- **Release on completion**: after finishing your CHG + ACC, update the coordination file to mark the claim done and release the scope.
- **Integration acceptance**: if two parallel changes touch the same structure or depend on each other, run one "integration acceptance" to confirm mutual compatibility (by one of the agents or a dedicated integration session) — two independent green lights aren't enough.
- **Conflict handling**: if your assumption conflicts with someone's already-committed CHG → **stop**, read their CHG's decisions/trade-offs, reconcile; return to `modification-guide` for a fresh impact analysis if needed.

## Coordination file (strongly recommended for parallel work)

`docs/coordination.md` (or a board): list in-progress claims — owner, locked scope, CHG number, status, start time. Every agent updates it on entry and exit. This is the "lock table" for parallel work. For sequential handoff it can be omitted (CHG status is enough).

```markdown
# Coordination board
| Owner | Role | R/W permission | Locked scope | CHG | Status | Time |
|-------|------|----------------|--------------|-----|--------|------|
| agentA | implementer | RW: src/modules/billing | src/modules/billing | CHG-20260616-03 | in progress | ... |
| agentB | verifier | read-only | src/modules/report | CHG-20260616-04 | done | ... |
```

## Relation to the base flow

- **Sequential handoff** = a direct application of this skill's "Session startup check" + "close acceptance in the same round".
- **Parallel** = the above plus claim / single-writer / integration acceptance.
- Both rest on "documents are the truth / don't rely on memory" — without reliable shared docs, cross-agent collaboration inevitably drifts.
