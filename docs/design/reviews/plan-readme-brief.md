You are an INDEPENDENT REVIEW SEAT on the repository at:
C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df

Another seat is reviewing the same thing at the same time. You will not see their verdict and they
will not see yours. A split does not pass. Do not soften.

THE SUBJECT: two changes, reviewed together because the second documents the first.

  CHG-20260823-28 — the plan file, closed. The outermost schema, and the only entry point that
                    had no validation at all. Six prior reviews named it.
  CHG-20260823-29 — the README brought up to what shipped, plus a test that pins the test count,
                    plus the schema chart committed to the repo.

The tree is frozen at the commit above and will not be touched while you read it. Last round a seat
found the worktree being edited mid-review; that was a process failure and it is not repeating.

READ FIRST (open them):
- src/ai_sdlc_runner/plan.py             <- THE NEW MODULE
- tests/test_plan.py                     <- what it claims to have tested
- src/ai_sdlc_runner/cli.py              <- both load paths, effects_provider (the ship block)
- docs/changes/CHG-20260823-28.md        <- what the closing claims
- docs/changes/CHG-20260823-29.md        <- what the README pass claims
- README.md                              <- the whole thing, against the code
- docs/SCHEMAS.md, docs/schema-atlas.html
- tests/test_documented_numbers.py       <- the new test-count check
- docs/defect-log.md

WHAT TO JUDGE:

1. IS THE PLAN ACTUALLY CLOSED? Find a plan this runner would accept and not fully honour. Try:
   nested keys, `ship` sub-blocks, a node spec with an unknown field, an operation with an extra
   key, a `decisions` value of the wrong type, `risk` set to something that is not a grade,
   `autonomy` set to a loosening. Which of those are refused and which merely have not been tried?
2. DOES IT REFUSE ANYTHING IT SHOULD ACCEPT? A closed schema built from memory fails the other
   way — a key the code reads that FIELDS lacks would refuse a correct plan. Check both lists
   against every read in src/, not just cli.py.
3. THE SHIP BLOCK. SHIP_REQUIRED names four. Read effects_provider and say whether that is the
   right four, and whether any optional key is in fact required somewhere else.
4. THE README. Go through it against the code. Which claims are false NOW? Pay attention to:
   the seven Known gaps, the model-configuration section, the Layout block, the numbers, and any
   sentence that describes behaviour rather than intent.
5. THE TEST-COUNT TEST. It runs pytest --collect-only in a subprocess. Is that sound? What does it
   do on a machine where collection differs, or where a test is skipped for a different reason?
   Does the README's number mean what the test checks?
6. THE SCHEMA CHART (docs/schema-atlas.html). Is every claim on it true of the code today?
7. THE TESTS. Real, or asserting on source text? Name the weak ones. The last two rounds each found
   a test that checked vocabulary rather than the claim — find the next one.

Check by running things (python3, PYTHONPATH=src, PYTHONUTF8=1, pytest; the CLI runs). Prove claims.
Assume a defect remains; find it.

The house standard: checkable findings quoting file and line. "A name standing in for a constraint"
and "a coarse check answering safe about something it had not examined" are this repository's two
most frequent defects. Do NOT average or split a difference.

OUTPUT, in markdown:
1. VERDICT: exactly one of `sound`, `sound with changes`, `not sound`
2. The single worst thing, quoted, and why
3. Findings on the closed plan, each with evidence
4. Findings on the README and the chart — every claim that is false now
5. The tests: which are real, which are weak
6. What the two change records claim that is not true
7. What you could not check
