# Acceptance round 2026-08-27 — closing forty-seven open changes

Every ACC written on 2026-08-27 references this file for the machine evidence they share. Nothing
here replaces a per-change record; it exists so that one set of commands is run once and quoted
once, rather than forty-seven times with forty-seven chances to mistype a number.

## Why this round happened

A ledger reconciliation found **47 of 71 changes unclosed** — eleven at `草稿 / draft` and thirty-six
at `Under review`. `tools/ledger_check.py` passed throughout, and correctly: it requires an ACC only
from a change whose status says it is finished, and none of these said so. The lint was not wrong.
The ledger was simply never closed, change after change, for forty-seven consecutive rounds.

That is the finding this round exists to answer, and it is worth naming as a pattern rather than an
accident: **a status vocabulary that makes "unfinished" the safe word will accumulate unfinished
work indefinitely, and no lint will object.** `Under review` is true of a change nobody has reviewed.

## Who verified

Two engines, neither of them the implementer of anything under review:

- `codex-cli 0.147.0` (OpenAI), run headless with `codex exec --sandbox read-only`, eleven batches.
- Claude `fable` subagents, eleven batches, one session each, able to run tests and to mutate-and-revert.

Each engine received the same written brief and no sight of the other's findings. Where the two
disagreed, the adjudicating session reproduced the disputed fact itself and the stricter verdict
won. Where an engine could not check something, that is recorded as unconfirmed rather than passed.

**A limit of the codex half, recorded rather than glossed:** its read-only sandbox had no writable
temporary directory, so from batch 6 onward it could not execute the tests it cites. Its findings
there are from reading, and the Claude half is what carries the executed evidence for those batches.

## Machine evidence

| Command | Result |
|---|---|
| `PYTHONUTF8=1 PYTHONPATH=src python -m pytest tests/ -q -rs` | **1316 passed, 3 skipped** (305.74s) |
| `PYTHONUTF8=1 PYTHONPATH=src python tools/mutation_check.py` | **12 of 12 caught** |
| `PYTHONUTF8=1 python tools/ledger_check.py --repo .` | **passed, 71 changes** |
| `PYTHONUTF8=1 PYTHONPATH=src python -m ai_sdlc_runner.cli flow` | 24 nodes, 15 of them ask someone, 10 gates |
| `PYTHONUTF8=1 PYTHONPATH=src python -m ai_sdlc_runner.cli settings --show` | `review seats: 3 (the floor; nothing set) \| high-risk mode: off` |
| targeted: `test_policy` `test_targets` `test_settings` `test_cli` `test_nothing_is_unwired` `test_false_stops` `test_ledger_check` | **397 passed** (20 / 184 / 46 / 54 / 11 / 53 / 29) |

## What this round is, and what it is not

It is **retrospective**. Every change under review is already merged; the earliest merged four days
before this record. What each ACC verifies is that the change's mechanisms are present and reachable
from a caller in the code as it stands today, plus what `git show` says about the change's own commit
where a claim is about the past.

It is **not** a fresh acceptance round against each change in isolation, and no ACC in this round
claims to be one. Two consequences follow and are stated in each record rather than left implied:

1. **Drift is not failure.** Counts stated in a 2026-08-23 record that later governed changes moved
   are drift. Where a claim was never true, that is said instead, with the commit that proves it.
2. **Supersession is not failure.** Several changes had their mechanism deliberately removed or
   replaced by a higher-numbered change. Those are recorded as superseded, naming the change that
   did it — not as a change that failed.

## Findings this round produced

Recorded here as the round's own yield, and each carried into the ACC of the change it belongs to.
None was fixed in this round: each is a modification and needs its own CHG.

### Mechanisms that are not reachable, or not there

| # | Finding | Where | ACC |
|---|---|---|---|
| 1 | The retired-backend refusal is **unreachable from the CLI**: argparse's `choices=BACKENDS` rejects `mongo` first, so a user sees `invalid choice: 'mongo'`, never `the mongo store was removed in CHG-20260823-35`. Present at the change's own commit `52017b4`, so never true. Reproduced three ways -- both engines and the adjudicating session. | `conversations.py:764` vs `cli.py:556` | ACC-35 |
| 2 | Six endpoints listed in CHG-11's design section have no route in `server.py`, and the six-phase screen strip it describes exists nowhere. Neither appears in any task's done-when, so the State column is not false -- a reader of the design section is misled. | `docs/changes/CHG-20260823-11.md` | ACC-11 |

### Tests that do not bite -- green that means nothing

The largest category, and the one the repo's own §8 warns about: *a test that asserts the current
behaviour proves nothing.* Each of these was established by **breaking the mechanism and watching the
suite stay green**, not by reading.

| # | Finding | Where | ACC |
|---|---|---|---|
| 3 | The every-exit unspent-confirmation report: regressed to success-only, the suite passes. The one behavioural test ends at `done` -- the single exit that always worked. | `engine.py:1064` | ACC-05 |
| 4 | Nothing on the console front end has a biting test. Deleting the whole `drawFlow` / `drawModels` chain leaves the suite green. | `console/index.html` | ACC-12 |
| 5 | Millisecond timestamp precision is asserted by nothing. Reverting `_now()` to seconds leaves 147 tests green; the change's commit touched only `test_paths.py` under `tests/`. | `conversations.py:1063` | ACC-40 |
| 6 | CHG-44's forced-arrival **behavioural** test does not catch the window it was written for. Reintroduce the race and only the **structural** test fails. | `server.py:446-460` | ACC-44 |
| 7 | `test_one_bad_conversation_does_not_stop_the_others` at `test_conversations_sqlite.py:254` is **shadowed** by a same-named parametrised redefinition at `:417` and has never been collected since. Dead code that looks like coverage. | `tests/test_conversations_sqlite.py` | ACC-42 |
| 8 | The replay's `__RAIL__` script payload is escaped but unguarded -- removing the call fails nothing. Low exposure; an unguarded emitter in the change whose whole subject is unguarded emitters. | `conversations.py:1367` | ACC-38 |
| 9 | Neither of CHG-21's two refusals has an automated test. Both fire when driven by hand. | `conversations.py:951`, `models.py:276` | ACC-21 |
| 10 | The README diagram's **completeness** is unchecked: a node dropped from the drawing while the count sentence stayed correct would pass CI. | `README.md:53-92` | ACC-15 |

### Records that do not match the facts

| # | Finding | Where | ACC |
|---|---|---|---|
| 11 | KN-3's body was never marked superseded -- only its INDEX row -- and still describes the deleted `DashboardModel` / `render_snapshot` in the present tense. True since commit `3059308`. | `docs/knowledge/knowledge.md:72-84` | ACC-01 |
| 12 | `plan.load`'s docstring still carries the phrasing CHG-30 retracted; the fix reached `check`'s summary line only. | `plan.py:225` | ACC-30 |
| 13 | `docs/defect-log.md` is not in the DOCS tuple, so its own counts are never machine-checked -- against a record claiming every figure is recomputed. | `tests/test_documented_numbers.py:40` | ACC-14 |
| 14 | ACC-47's reproduction command names `mutation_check.py --only importer` for a seven-row table; that group holds six, the seventh has lived in group `cli` since `2932e38`. | `docs/acceptance/ACC-20260823-47.md` | ACC-47 |

### A rule with no mechanism

| # | Finding | Where | ACC |
|---|---|---|---|
| 15 | KN-14 -- *freeze the tree before verification* -- lives in `README.md:524` and `docs/defect-log.md:49` and **nothing enforces it**. No hook, no script, no test checks that a reviewed tree is committed or pinned. CHG-30's statement that it did not happen again is a statement, not a check. | `README.md:524` | ACC-27 |

## The pattern underneath most of these

Fourteen of the forty-seven records claim a closure that only the **next** change actually delivers.
CHG-25's version-checked routes arrived with CHG-26. CHG-26's one-transaction schema write arrived
with CHG-27. CHG-28's closed plan arrived with CHG-30. CHG-29's counted test figure arrived with
CHG-30. CHG-32's every-writer path module and CHG-33's closed injection arrived with CHG-38. CHG-41's
lossless importer took CHG-42, -45, -46 and -47.

In every case the following change **found it and said so**, which is the ledger working. What the
ledger did not do is stop the claim being written in the present tense the first time. The
distinction this round drew throughout -- *what the change did at its own commit* versus *what is true
today* -- is not bookkeeping pedantry; it is the only way to read a record like this without being
misled by it.

## This round broke KN-14 itself

Recorded because the alternative is the failure this repo keeps naming.

Eleven `fable` verifiers ran in parallel **against one shared worktree**, and several of them
mutated `src/` to prove a test bites. One reported finding another's uncommitted cut mid-audit. The
adjudicating session later found `cli.py` and `engine.py` still modified -- line endings only, no
content change, confirmed by `git diff --numstat` returning nothing.

One consequence is visible in the evidence: a verifier saw an order-dependent flake in
`test_the_cli_does_not_send_a_conversations_own_bytes_to_the_terminal`, which passes alone and on
rerun, and attributed it to a sibling's mutation.

The tree was restored, verified clean, and the full suite re-run: **1316 passed, 3 skipped** --
identical to the baseline taken before any verifier started. The evidence stands. The method was
still wrong, and a future round of this shape should give each verifier its own worktree.

That is finding 15 demonstrating itself: a rule nothing enforces is a rule that gets broken by the
people who wrote it down.


## The rule this round did not follow, and why

`docs/ai-guideline.md` §8 says every change leaves a CHG. Writing an acceptance record is the closing
half of a change that already has one — it is the prescribed process, not a new change — so no CHG
was opened for the act of writing these forty-seven records. Flipping each `## Status` section is
part of the same act.

The three findings above are different: each is a modification, and each needs a CHG of its own
before anybody touches the file. None was fixed in this round.

## The round broke a test, and the test caught it

Worth recording next to fifteen findings about tests that do not bite: one that does.

Flipping forty-seven `## Status` sections was done by a script that replaced the whole first
paragraph of each section. On CHG-20260823-11 that paragraph carried the sentence
`**20 of 20 tasks built**`, and `tests/test_documented_numbers.py:244` --
`test_the_change_records_task_count_matches_its_own_task_table` -- exists precisely to keep that
sentence agreeing with the twenty `**[x]**` ticks in the table below it.

The full suite came back **1 failed, 1315 passed**. The Status line was rewritten to carry the count
again, and nothing was committed in between.

That test was written after CHG-20260822-04 claimed "all nine tasks built" while `src/` was empty.
It was written to catch a person being careless in one direction, and it caught a script being
careless in the other. A test aimed at a failure mode rather than at a line of code keeps working
when the thing doing the damage changes shape.

