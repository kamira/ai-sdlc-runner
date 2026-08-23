# Design review round 2 — CHG-20260823-11 (an operator console)

You are one of two independent reviewers. The other has the same brief and you will not see its
answer. Do not soften a verdict to look agreeable; do not manufacture disagreement to look
independent.

## What happened in round 1

Two seats reviewed this design against seven questions. They split — one said `not sound`, one said
`sound with changes` — so it **did not pass**. The record was then corrected: nine claims struck or
qualified, three done-whens tightened, eight tasks added (12–19).

**Those corrections have not been reviewed by anyone.** That is your job.

## The anchoring problem, stated plainly

The record now **contains round 1's findings**, written by the author who was corrected by them. You
will read a document that tells you what the last reviewers thought. That is a thumb on the scale and
there is no way to remove it — the findings had to go in the record.

So: **judge the corrections, do not defer to them.** A finding the record agrees with may still be
wrong. A correction the record presents as settled may not answer the finding it claims to answer.
Round 1's verdicts are evidence about round 1, not about the current document.

## Read, in this order

1. `docs/changes/CHG-20260823-11.md`     — the corrected record
2. `git show 26d1676 --stat` and the diff — what actually changed
3. `src/ai_sdlc_runner/engine.py`        — `walk`, `_gate`, `_adjudicate`, `_spoken_halt`, `_finish`
4. `src/ai_sdlc_runner/policy.py`        — `adjudicate`, `GATES`, `_TARGET_RULES`
5. `src/ai_sdlc_runner/graph.py`         — `Node` and the 23 nodes
6. `docs/design/console-mockup.html`     — skim; the interaction spec

## The questions

**R1 — Does each correction answer the finding it claims to answer?** Go through them one at a time:
the self-contradiction (`policy.py`/`graph.py` unchanged), the mock-up's node count, the "ends the
process" claim, the §3 seat exclusion, the collapsed design-only claims, and the three tightened
done-whens (tasks 1, 2, 4). For each: **answered / partly / not answered**, with the evidence. A
correction that restates the finding without changing what the design *does* is not an answer.

**R2 — Are the eight new tasks (12–19) each well-formed?** A task is well-formed when its done-when
is a thing you can watch someone demonstrate and see fail. Name any whose done-when could be
satisfied by code that does not do the job. Task 12 is the load-bearing one — if the execution mode
lands in `graph.Node` badly, tasks 4 and 5 inherit the flaw.

**R3 — What did the corrections break or newly assert?** Nine edits to a design record is a change
with its own risk. Does any correction contradict another part of the record, or assert something
about the code that is not true? Check the claims about `engine.py:572`, `engine.py:674-678`,
`engine.py:16`, `policy.py:219` and `_TARGET_FIELDS` **against the code**, not against the record's
description of the code.

**R4 — Is the round-1 verdict handling honest?** The record says a split means "does not pass" and
separates what both seats found from what one found. **Is that separation accurate**, and does the
record anywhere present a single-seat finding as if both had found it, or quietly drop a finding it
did not want? You do not have round 1's raw verdicts — say what you can check and mark the rest not
substantiated.

**R5 — Is the design now sound enough for task 1 to start?** Task 1 is the one that changes how a
gate stops. **Not "is the record good" — is the specific thing task 1 would build now specified
tightly enough to build safely?** If not, name what is still missing.

**R6 — What is still missing?** After 19 tasks and two rounds. Be specific — a missing task or a
missing constraint, not a topic.

## Answer format

Per question: a verdict word, the reasoning, then `file:line` evidence.
End with one line: `ROUND 2: pass` / `ROUND 2: pass with changes` / `ROUND 2: fail`, and if not a
clean pass, a numbered list of what must change before task 1 may start.

Cite `file:line`. If you cannot substantiate a claim from the repository, write "not substantiated"
rather than reasoning from how a system like this usually works.
