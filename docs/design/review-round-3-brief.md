# Design review round 3 — CHG-20260823-11

You are one of two independent reviewers. The other has the same brief and will not see your answer.
Do not soften a verdict to look agreeable; do not manufacture disagreement to look independent.

## Why this round exists, and the specific question it must answer

Round 1 reviewed the design: split, did not pass. The record was corrected — nine corrections.
Round 2 reviewed *those corrections*: split, did not pass, and found that **three of the nine were
defective, two of them reproducing the very defect they were fixing** (a contradiction introduced by
the fix for a contradiction; an overclaim inside the correction to an overclaim).

The record then wrote down a test for itself, and this round is that test:

> "If round 3 splits on defects introduced by round 2, the honest reading is that the record is being
> polished rather than fixed, and the next move is to build task 12 — the smallest load-bearing
> piece — and let running code settle what prose cannot."

**So the question is not only "is the record good now".** It is: **is prose review still producing
new information, or has it started producing new defects at roughly the rate it removes them?** Your
answer to Q4 decides whether anyone runs a round 4 or stops reviewing and starts building.

## The anchoring is now two layers deep

The record contains its own round-1 review **and** its own round-2 review, both written by the author
they corrected. Judge the corrections; do not defer to them. Round 2's verdicts are evidence about
round 2, not about the current document. A finding the record agrees with may still be wrong, and a
correction the record presents as closing a finding may not close it.

## Read

1. `docs/changes/CHG-20260823-11.md`   — the twice-corrected record
2. `git show bb9d83f`                  — round 2's corrections as a diff
3. `docs/design/reviews/`              — all four prior verdicts, verbatim, plus their provenance
4. `src/ai_sdlc_runner/{engine,policy,graph}.py`
5. `docs/design/console-mockup.html`   — skim

## The questions

**T1 — Did round 2's corrections introduce new defects?** This is the load-bearing question. Read
`git show bb9d83f` as a change with its own risk, not as a fix. Any new contradiction, any new claim
about the code that is not true, any correction that names a consequence and produces no task, any
done-when that a non-doing implementation would satisfy. **Name them or say there are none** — "none
found" is a real and useful answer here, and inventing one to seem thorough corrupts the T4 signal.

**T2 — Is task 12 buildable as written?** It is now the proposed next step, so it gets read the way a
builder would read it: `single`/`seat_panel`/`model_panel`/`pool`/`follows` on `graph.Node`, stated
referent types for `main`/`follows`, a mode for each of the 23 nodes, named cross-rules in
`graph.validate()`, inference from id or branch shape refused. **Could two competent builders read
this and produce incompatible graphs?** Where?

**T3 — Are the two questions task 1 must answer in writing actually answerable from the record?**
(The `confirmations`-vs-new-mechanism relation, and who mints the run id.) If not, say what a builder
would have to invent.

**T4 — Is prose review still converging?** Compare the three rounds using the verdicts in
`docs/design/reviews/`. Round 1 found N substantive defects, round 2 found M — of which 3 were
introduced by round 1's fixes. **Count what you found in T1 that round 2 created.** Then answer
directly: **is another review round the best next action, or is building task 12 the best next
action?** Give the reason, not a hedge. "Keep reviewing" is a legitimate answer if the round is still
paying for itself.

**T5 — What single thing, if wrong, would cost the most later?** One item. Not a list.

## Answer format

Per question: a verdict word, the reasoning, `file:line` evidence.
End with one line: `ROUND 3: pass` / `ROUND 3: pass with changes` / `ROUND 3: fail`, then one line:
`NEXT: review` or `NEXT: build task 12`, then — only if not a clean pass — a numbered list of what
must change.

Cite `file:line`. If you cannot substantiate a claim from the repository, write "not substantiated".
