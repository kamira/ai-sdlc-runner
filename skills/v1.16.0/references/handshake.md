---
name: handshake
description: >
  Entry handshake protocol: every agent / session / handoff does a "handshake" before acting — read
  existing docs in a fixed order, extract the key points, and echo back its understanding, so it can
  take over safely. Read this when you just entered, are taking over an existing project, or handing
  off across sessions/agents. Defines what to read, the order, the key points, and the entry
  acknowledgement (ack) format. It is the executable form of the Session startup check.
---

# handshake — entry handshake protocol

> 語言 / Language: [繁體中文](handshake.zh-tw.md) · **English**

## Purpose

Any agent, on entry (new session, takeover, handoff), first does a "handshake": **read existing docs in a fixed order → extract key points → echo back understanding**, then start work. The goal is auditable handoff and avoiding the drift/misunderstanding caused by "acting without reading". This is the executable form of the Session startup check.

## What to read (fixed order)

1. **Current branch & working tree**: confirm which branch you're on (see branch-isolation) and run `git status` — note any uncommitted changes for step 5's reconciliation; afterwards only reference that branch's requirements/acceptance. **Switching branches mid-session counts as a new entry: redo this handshake.** **No git?** Commit anchoring, the commit scan and `--commits-since` don't apply — state the degraded mode in your ack; CHG step ticks + the worklog become the only interruption markers, reconciliation is manual (files vs CHG steps). Recommend `git init` before anything else.
2. **`docs/ai-guideline.md`**: the current Guideline — goals, scope, current **version**, open items. **Skill version self-check**: compare the `Skill:` version in recent CHG/ACC against your running skill version — records newer than your skill mean **you are outdated: upgrade before working** (an old skill silently misses newer rules); records older than your skill are fine (new rules apply prospectively, see doc-integrity).
3. **`docs/knowledge/` — via its INDEX, not the whole file**: read the index, then load only **global entries + entries whose tags intersect your current scope** (directives, deep/shallow pattern records, known errors — see knowledge). Deep records you'll be applying belong in your ack.
4. **`docs/coordination.md`**: org/claims — your role, locked scope, read/write permission, others' in-progress work.
5. **`docs/changes/` + `docs/acceptance/`**: any unclosed stage (CHG not accepted / missing ACC); close first, then start new. **Reconcile the working tree**: every uncommitted change noted in step 1 must map to some CHG's modification steps (or a worklog entry); an unmatched change means an interrupted or ungoverned edit — treat it as drift (see doc-integrity) and resolve it before new work. **Scan commit history too**: from the last governed anchor (the newest ACC's Commit field, or the last commit referencing a CHG) to HEAD, every commit message should reference a CHG id (see modification-guide "commit granularity"); a commit referencing none is ungoverned work — same drift handling (in squash-merge workflows the trunk is scanned at squash-commit granularity — see modification-guide "PR / squash / rebase"). Machine aid: `scripts/doc_integrity_check.py --commits-since <anchor>`.
6. **`docs/structure/`**: current structure, check for drift vs code (see doc-integrity).

## Key points (must capture)

- **Current branch** and its scope (don't reference other branches' requirements).
- **Current Guideline version** and open items.
- **Your role / read-write permission** (role_refs, tools allowlist).
- **Known errors and correction directives** (knowledge, high priority).
- **Unclosed stages** (hanging acceptance).
- **Working-tree state** (uncommitted changes mapped to a CHG, or flagged as drift).
- **In-progress claims** (avoid collisions; stale claims → see cross-agent takeover).

## Echo acknowledgement (handshake ack — required before acting)

After reading, **echo your understanding in a few lines before acting**:

```
[handshake] branch: <branch> | role: <role> (RW: <scope>)
worktree: <clean / uncommitted → mapped to CHG-… / unmatched → drift>; commits since <anchor>: <all governed / N ungoverned>
current Guideline: v<x>; unclosed: <CHG-… pending acceptance / none>
must follow (knowledge): <key entries / none>
next I will: <one line>; halt: <per autonomy, this gate auto/halt>
```

The echo lets a human/parent intercept misunderstanding before you act; across agents it's proof of "I took over correctly".

## Tiered handshake: full vs scoped (subagents)

Reading everything doesn't scale, and a dispatched subagent doesn't need the whole picture. Two tiers:

**Full handshake** — solo entry, the orchestrator / main agent, taking over a whole project, and **peer parallel agents with no dispatching parent** (no one composes a briefing for you → you carry the full duty yourself): read the full list above.

**Scoped handshake** — a **dispatched subagent**. Its context is keyed by four things: **branch + structural location (module) + requirement (its task's FR/CHG slice) + location (locked file scope)**.

- **Reads**: the **dispatch briefing** its parent composed from the full view (task, locked scope, R/W permission, relevant contract/interface excerpts, relevant structure-doc sections, knowledge entries that are global or tagged for its scope) + its own scope's structure docs and worklog.
- **Does not read**: other branches; other modules' claims / worklogs / handshakes. The branch is inherited from the dispatch — never reference another branch's sources.
- **Global knowledge pierces scope**: directives tagged "all branches / global" are mandatory for every tier — the one thing that crosses scope boundaries.
- **Scoped ack goes to the parent** (not broadcast): `[handshake:scoped] branch | structure | requirement | locked location | next: <one line>`.
- **The parent audits**: it alone has the full view — it composes the briefing before dispatch, and on receiving the ack checks the **four keys match the dispatch**; a mismatch is intercepted before the subagent acts. Cross-scope consistency stays the parent's job (impact analysis, integration acceptance). A subagent that discovers an out-of-scope dependency **reports up** — it does not read sideways or self-expand (see agent-hierarchy).

**The cost, stated plainly**: a scoped subagent cannot catch what the briefing missed. Compensating controls: the parent's impact analysis (CHG), integration acceptance for parallel work, and V1's wider-view acceptance. The trade is deliberate — cheap, parallel, bounded workers + one accountable full-view reviewer.

## Mid-session re-sync (mini-handshake)

The full handshake happens at entry — but long sessions lose context to compaction, and "the docs are the truth" only holds if you actually re-read them. Re-read the Guideline + the active CHG (+ knowledge when directives are in play) and emit a 2-line mini-ack:

```
[re-sync] CHG-…: step <n>/<m> done; branch <b>; next: <one line>
constraints re-confirmed: <key knowledge / guideline points / none>
```

Triggers: **every autonomy gate**; **before starting acceptance**; **on signs of compaction** (you can't precisely recall an earlier decision — don't guess from memory, re-read); and periodically in long sessions (suggest every ~20 turns).

## Live handshake (always written, always current)

The ack is not just spoken into the conversation — **it is a file, and it stays current**. On entry, write the ack to `docs/worklog/handshake-<agent-id>.md`; **update it at every step boundary** (the moment a step completes, together with that step's durable write):

```
branch/role/scope: <…>
doing: CHG-… step <n>/<m>
next: <one line>
last-updated: YYYY-MM-DD HH:MM (UTC+0)
```

This is the last-act discipline applied to the handshake itself: an interruption at **any** moment finds the file current, and the next session's entry handshake reads it as the exact resume point — no reconstruction, no guessing. Solo sequential work keeps one file; parallel agents keep one each (same worklog conventions: archive on close).

## Last-act discipline (crash-only)

Conduct **every action as if the session dies right after it**. The entry handshake above assumes the previous session got no warning — this discipline is what makes that assumption permanently safe:

- **One step, one durable write**: intent lands on disk *before* acting (the CHG step, a worklog line); the outcome lands *immediately after* (tick the box, bump the counter, flip the status). Never batch record-keeping for "when I'm done" — "done" may never come.
- **Nothing lives only in the conversation**: a decision made but not written is, to the next session, a decision never made.
- **A graceful exit is just a crash that happened to be convenient**: when the invariant holds, planned handoffs and sudden deaths leave identical states — the exit checklist (cross-agent) *verifies* the invariant rather than rescuing the state.

## Relation to the rest of the flow

- Concretizes the Session startup check; the read list maps to knowledge / branch-isolation / doc-integrity / coordination / autonomy.
- Machine aids: use `scripts/role_loadout.py` for the role's references to load; `scripts/doc_integrity_check.py` to scan for unclosed items and drift.
- If you find unclosed items / drift / conflict → handle it per the matching reference before starting new work.
