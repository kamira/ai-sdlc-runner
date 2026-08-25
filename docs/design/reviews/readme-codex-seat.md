# README review — codex-seat

## R1 — FAIL

Several important prose claims are false or materially incomplete.

- The risk table is accurate. `low` stops only at `merge`; `medium` adds `pm_confirm`, `lead_assess`, and `pm_signoff`; `high` additionally stops at `lead_review`, `qa_verify`, `qa_accept`, and `pr`. The table agrees with `policy.GATES`. `README.md:117-126`; `src/ai_sdlc_runner/policy.py:99-124`.

- “A pool’s choice is … reproducible … seeded by run and node” is only partly true. The choice is deterministic for `dispatch_seed`, node id, and global ask ordinal:
  ```python
  random.Random(f"{cfg.dispatch_seed}:{node.id}:{nth_ask}")
  ```
  It is not seeded by the run identity. The default seed is always `0`, and inserting an earlier ask changes `nth_ask`; therefore the same logical module is not guaranteed the same dispatch across a changed/resumed walk. `README.md:179-182`; `src/ai_sdlc_runner/engine.py:418-422,609-628`.

- “One ask, one session” agrees with the engine: it opens one session, calls `ask` once, closes it in `finally`, and rejects a reused session object. Backend retries can still launch multiple backend attempts inside that one session, so this guarantees session isolation, not necessarily one backend process or one model invocation. `README.md:184-187`; `src/ai_sdlc_runner/engine.py:540-575`; `src/ai_sdlc_runner/cli.py:112-136`.

- “A cross-origin `Origin` is refused” is false as a guarantee. The check uses `startswith("http://localhost")`-style matching, so an origin such as `http://localhost.evil.example` passes. `README.md:263-269`; `src/ai_sdlc_runner/server.py:390-394`.

- “A token is required on every request” is explicitly false. `/` and `/index.html` bypass token checking. `/run/events` also permits the token in the query string rather than the stated every-request mechanism. The accurate claim would be “every data/API request requires a token, with a query-token exception for the event stream.” `README.md:268-269`; `src/ai_sdlc_runner/server.py:380-408,436-454`.

- “A cross-origin page can send a request but cannot read a file on disk, which is what makes local-only hold” does not describe the implemented boundary. The server checks a presented token; browser inability to read an arbitrary disk file is not itself an enforcement performed by this code. Moreover the defective origin-prefix check weakens the preceding refusal. `README.md:268-269`; `src/ai_sdlc_runner/server.py:390-407`.

- The URL-fragment statement is true for normal browser HTTP behavior, but it omits that JavaScript must subsequently transmit the token to the API and that the event stream places it in a query parameter that can reach access logs. The code candidly documents this exception. `README.md:271-272`; `src/ai_sdlc_runner/server.py:395-403`.

- The late-artifact claim is narrower than the brief suggests. Attachments are appended to `input_artifacts` for every generated work order, and instructions are appended to every generated work order. Runner-only nodes receive no work order at all. Thus “Every work order … carries all of it” is true; “`input_artifacts` reaches every node” would be false. `README.md:259-261`; `src/ai_sdlc_runner/engine.py:405-413,476-513`; `src/ai_sdlc_runner/graph.py:130-210`.

- The intake escalation description is inaccurate:
  > “after the third unanswered ask for one aspect, the runner stops asking and puts at least three options on the table”

  `needs_options` becomes true only when the prior history already contains three misses. On the next walk, the runner still conducts `intake_review` before requesting options. In effect, the option request occurs during a fourth intake pass, not immediately after the third ask, and the seats are not prevented from being asked again. `README.md:205-208`; `src/ai_sdlc_runner/intake.py:148-176`; `src/ai_sdlc_runner/engine.py:1281-1321`.

- “`decisions.next_module` may be `"frontier"`” is true. It reads the most recent `pm_plan.modules`, subtracts modules reported by `engineer_build`, and selects `module` or `none`. What the README omits is that `pm_plan` must return a non-empty `modules` list or the run errors. `README.md:311-313`; `src/ai_sdlc_runner/engine.py:648-700`.

## R2 — PASS, with a material omission

The diagram contains all 24 nodes in `graph.NODES`; its declared branch labels agree:

- `pm_confirm`: `yes` / `no`
- `pm_signoff`: `yes` / `no`
- `next_module`: `module` / `none`
- `lead_task_review` and `re_review`: `pass` / `fail`
- `lead_review` and `qa_accept`: `pass` / `fail`
- `feedback`: `more` / `done`

Both terminals, `halt_second_fail` and `done`, are marked. All ten gated nodes are marked. `README.md:58-89`; `src/ai_sdlc_runner/graph.py:129-210`.

However, it does not show gate-rejection transitions, although those are real runtime routes and part of the node data:

- `lead_assess → pm_plan`
- `engineer_selfverify → engineer_build`
- `lead_task_review → fix_pass`
- `lead_review → review_failed`
- `qa_verify → next_module`
- `qa_accept → acceptance_failed`

It also does not distinguish before-work from after-work gates, despite that distinction controlling whether work happens before suspension. Calling this merely “the flow” is defensible, but CHG-15’s stronger claim that it depicts the graph completely is not. `src/ai_sdlc_runner/graph.py:94-125,145-204`; `docs/changes/CHG-20260823-15.md:25-26,72`.

## R3 — FAIL

A competent newcomer cannot construct a runnable plan from this README.

The only `node_specs` example is for `engineer_build`, but every asking node reached by the walk requires its own work order. The example will fail first at `intake_review` or `pm_plan` with:

> “node … has no work order: no node spec was supplied for it”

`README.md:280-305`; `src/ai_sdlc_runner/engine.py:476-484`.

Missing operational information includes:

1. A complete minimal `plan.json`, including specs for every asking node that the sample path reaches.
2. The required answer shape for each node: for example `pm_plan.modules`, decision branch fields, model-panel verdicts, seat survey responses, and intake option responses.
3. An `operations` example and explanation of which working nodes require declarations. The README exposes `--undeclared` but does not show how to write the declaration it defaults to requiring. `README.md:231-239`; `src/ai_sdlc_runner/cli.py:654-658`.
4. How a backend reads the work order and returns its JSON answer. “The work order arrives on stdin” is insufficient to implement a compatible backend. `README.md:42-49`.
5. How to answer an incomplete-intake stop. The resume example only demonstrates confirming a gate; `--confirm` cannot supply a missing requirement or a model answer. `README.md:224-229`.
6. The `"frontier"` prerequisite that PM must answer with `{"modules": [...]}`. `src/ai_sdlc_runner/engine.py:663-677`.

Installation is shown; the first meaningful run is not reproducible from the page.

## R4 — FAIL

The practice section presents aspirations as enforced facts.

The worst overclaim is:

> “Changes are reviewed by two independent seats before they land, each with the same brief, neither seeing the other, against a frozen tree.”

At the reviewed commit, CHG-14 and CHG-15 have already landed in `d93fcd2`, while both records say nobody independent has read them. This directly disproves “before they land.” `README.md:331-334`; `docs/changes/CHG-20260823-14.md:89-99`; `docs/changes/CHG-20260823-15.md:82-90`.

Other overclaims:

- “Every change gets a record … before it is built” — not substantiated. A present record does not establish its creation preceded implementation, and the ledger checker does not enforce chronology. `README.md:322-325`.

- “Nothing is ticked until it is demonstrated” — not enforced by the cited ledger check. The check relates finished statuses to acceptance records; it cannot prove when or whether each task’s demonstration occurred. The sentence should be identified as practice, not guarantee. `README.md:327-329`; `tests/test_documented_numbers.py:244-263`.

- “A split does not pass … applies to its own design records” — not substantiated. No cited mechanism binds repository merges to two-seat adjudication, and the already-landed unreviewed changes show repository process is not controlled by runner policy. `README.md:336-337`.

- “every defect …” is an absolute completeness claim contradicted by CHG-14’s own “Not claimed” section. `README.md:348`; `docs/changes/CHG-20260823-14.md:93-96`.

## R5 — FAIL

The log is not internally honest enough to support its conclusions.

- Its group counts sum to 35, not 32: `13 + 9 + 4 + 9`. Yet it says “these thirty-two defects.” `docs/defect-log.md:9-14,22`.

- The test-suite group claims four defects, but its fourth entry explicitly says:
  > “Not a defect — the intended collision.”

  Therefore “four suite-caught defects” and “three of the four” are misleading. `docs/defect-log.md:245-285,386-388`.

- “Every one of these was found before the code existed” is false literally. Several entries quote and diagnose existing `engine.py` and `policy.py` behavior. At most, they were found before the proposed replacement code existed. `docs/defect-log.md:31-33,35-66`.

- The broad conclusion:
  > “a one-module, one-instruction, one-server demo had the same bug and looked fine”

  is not supported for all nine live-run defects. A first-click null dereference, a missing dispatch display, and a stale-token 401 are observable without scale or multiple modules/instructions/servers. `docs/defect-log.md:223-241,381-384`.

- A known defect is missing: CHG-15 records that the original README mislabeled `feedback`’s branches, but the defect log’s README-process entries do not record it. `docs/changes/CHG-20260823-15.md:40-42`; `docs/defect-log.md:337-360`.

- The screenshot explanation begins candidly by stating the tooling failure, but “would not have helped much” becomes an excuse. More than two listed defects had visible UI consequences: the ineffective “add to the brief,” absent dispatch information, first-click exception, and stale-token 401. Screenshots would not prove the underlying cause, but they could document the operator-visible failure. `docs/defect-log.md:16-25,179-189,223-241`.

- “What is quoted below is the output captured at the moment each was found” is also too broad: several entries contain retrospective prose or source excerpts, not captured runtime output. `docs/defect-log.md:24-25,68-145`.

## R6 — FAIL

The single worst sentence is:

> “Changes are reviewed by two independent seats before they land, each with the same brief, neither seeing the other, against a frozen tree.”

It is a front-door assurance about the reliability of everything else, and the target commit itself disproves it: the two README changes landed while their records still say nobody independent had reviewed them. `README.md:331-334`; `docs/changes/CHG-20260823-14.md:89-99`; `docs/changes/CHG-20260823-15.md:82-90`.

README: not sound

1. Replace the false repository-review guarantee with the actual process and disclose that CHG-14/-15 landed before independent review.
2. Fix the local-only section: exact origin validation, shell/event-stream exceptions, and narrower token wording.
3. Describe pool reproducibility using the real seed inputs and its stability limits.
4. Correct the intake timing: options are requested on a subsequent walk after three recorded misses, after another survey.
5. Add a genuinely runnable minimal plan, all required node specs, operation declarations, backend answer schemas, and instructions for resolving incomplete intake.
6. Clarify that attachments reach every generated work order, not every graph node.
7. Either draw gate-rejection routes and gate phases or explicitly state that the diagram omits them.
