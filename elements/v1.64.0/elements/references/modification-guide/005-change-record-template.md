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
- Recurrence check: <no repeat / repeats CHG-… → KN-… created or updated>   ← filled at close-out; see knowledge "autonomous triggering"
- Diagrams: <see the "## Design diagrams" section / skipped — why the user chose not to look>   ← required at medium/high risk; a skip needs a signature, a blank reason counts as undeclared
- Skill: ai-sdlc v<X.Y>   ← convention version this record was written under (new rules apply prospectively; see doc-integrity)
- Related: <requirement ID / prior change / acceptance report>

## Motivation
<why this change is needed>

## User stories   ← required for medium/high-risk records at Skill >= v1.19; not required for CHG-lite
1. As a <role>, I want <capability>, so that <benefit>
2. ...
<cover each user-facing aspect of this change; **this is the first-choice source of acceptance criteria** — the ACC checks each story off, rather than reverse-engineering behavior from the modification steps>

## Decisions & trade-offs
| Decision | Options | Assumptions (premises this rests on) | Why this choice |
|----------|---------|--------------------------------------|-----------------|
| ... | A vs B | ... | ... |

## Design diagrams   ← required for medium/high-risk records at Skill >= v1.21; not required for CHG-lite or low risk
<Two of them: (1) a system architecture diagram of the affected area — how the modules
connect, which way the dependencies point; (2) a flow diagram of this change — which
components the edit passes through, and in what order.
Mermaid by default (GitHub and most viewers render it directly); ASCII diagrams are fine too.
**Show them to the user for review and correction before touching code, and only proceed
once confirmed** — see workflow step 6>

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

