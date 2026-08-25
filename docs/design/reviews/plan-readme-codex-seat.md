# codex-seat — CHG-20260823-30 (the closed plan, and the README)

Dispatched via `codex exec --sandbox read-only` on
[`plan-readme-brief.md`](plan-readme-brief.md), against a frozen tree at `c123aa3`.
Committed whole and unedited below.

---

# VERDICT: not sound

## The single worst thing

> “Refuse a plan this runner would not fully honour” — [plan.py:75](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/plan.py:75)

That contract is false. `plan.check()` accepts malformed nested values and ignored fields. My direct probes showed it accepting:

```text
decisions_wrong   ACCEPT {'decisions': {'next_module': 7}}
risk_wrong        ACCEPT {'risk': 7}
risk_name_wrong   ACCEPT {'risk': 'banana'}
autonomy_loosen   ACCEPT {'autonomy': 'auto'}
node_unknown      ACCEPT {'node_specs': {'intake': {'bogus': 1}}}
op_extra          ACCEPT {... 'bogus': 1}
op_wrong          ACCEPT {'operations': {'engineer_build': ['x']}}
ship_acc_no_task  ACCEPT {... 'acc_id': 'ACC-X', 'acc_body': 'body'}
ship_no_body      ACCEPT {...}
```

This closes two key sets, not the plan schema. Some accepted inputs fail later; others are silently ignored.

## Findings on the closed plan

1. `operations` remains open and malformed operations pass the entry point.

   `check()` verifies only that `operations` is a mapping, at [plan.py:67](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/plan.py:67) and [plan.py:87](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/plan.py:87). It accepts both an operation string and an operation carrying `bogus`.

   Downstream `policy.classify()` refuses a non-mapping only when reached, but reads `kind`, `description`, and `targets` with `.get()` and never checks extra keys: [policy.py:455](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/policy.py:455), [policy.py:463](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/policy.py:463). Thus an extra operation key is accepted and permanently ignored.

2. `decisions` values are not validated.

   An integer value is accepted. `_choose()` treats every non-string, non-`None` value as a sequence and calls `len(value)` and indexing: [engine.py:752](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:752), [engine.py:759](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:759). An accepted integer therefore becomes an incidental `TypeError`, not a plan refusal.

3. `risk` has no entry validation.

   Both `7` and `"banana"` pass `plan.check()`. The former later crashes on `.lower()`; the latter raises `PolicyError` only when a gated node resolves it: [policy.py:594](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/policy.py:594). The accepted plan is not refused at the door as claimed.

4. `autonomy` has no entry validation.

   `"auto"`—a requested loosening—passes `plan.check()`. Policy later refuses loosening at [policy.py:600](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/policy.py:600), but only once a gate is consulted. Again, the plan validator has accepted a value it cannot honour.

5. Node-spec closure is deferred, so invalid plans are accepted.

   A node spec with `bogus` passes `plan.check()`. It is refused only if that node is rendered by `workorder._check()`: [workorder.py:77](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/workorder.py:77), [workorder.py:99](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/workorder.py:99). A spec for an unvisited or unknown node is therefore never checked at all.

6. The ship-required set is too small for a ship run that must complete.

   The four directly indexed names are correctly identified: `repo`, `chg_id`, `branch`, `message` at [cli.py:290](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:290) and [cli.py:303](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:303).

   But `chg_body` is operationally required unless the CHG record already exists. It is the first ship effect, and `_write_chg` raises when absent: [cli.py:294](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:294), [ship.py:60](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/ship.py:60). Calling it simply “optional” is materially misleading.

   `acc_body` is conditionally required when `task` and `acc_id` enable the acceptance effect: [cli.py:317](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:317), [ship.py:115](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/ship.py:115).

   Conversely, `acc_id` and `acc_body` without `task` are accepted and ignored because `record_effects` is called only under `if task`: [cli.py:326](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:326). That is an exact “accepted and not honoured” plan.

7. The top-level field list does not appear to refuse a legitimate key.

   All static `plan.get()` reads in `cli.py` are covered. The additional dynamic reads in `store.py` iterate `"node_models"` and `"seat_models"` at [store.py:406](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/store.py:406), and both are present. I found no missing correct top-level field.

   However, the drift test does not prove this repository-wide fact because it scans only literal `plan.get("...")` calls in `cli.py`.

## README and schema chart: false claims now

1. “The plan file is closed” at [README.md:378](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/README.md:378) overstates key-set closure as schema closure. Nested operations, decision values, risk, autonomy, model assignments, and conditional ship dependencies remain unchecked.

2. “Every schema page [is compared] against the code it maps” at [README.md:528](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/README.md:528) does not cover `schema-atlas.html`. No test references that file.

3. “Known gaps” is not current. It omits the accepted-but-ignored and accepted-then-crash plan cases above. The heading promises current gaps while [README.md:563](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/README.md:563) frames the list as what is enforced versus overstated.

4. “1084 passing” at [README.md:602](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/README.md:602) is not what its test establishes. It estimates run-time passes from collection-time output.

5. The chart contradicts itself about the plan:

   - [schema-atlas.html:212](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/schema-atlas.html:212) still says the plan is open and points to an open question.
   - [schema-atlas.html:235](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/schema-atlas.html:235) labels it closed.
   - [schema-atlas.html:437](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/schema-atlas.html:437) calls the open status history.

6. The chart says “Four are enforced in code” at [schema-atlas.html:406](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/schema-atlas.html:406), then lists five closed schemas at lines 413–422.

7. The chart’s statement that the plan refuses “a key of the right name holding the wrong shape” at [schema-atlas.html:413](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/schema-atlas.html:413) is too broad. It checks only six outer mapping values and node-model list values, not the shapes inside them.

## Tests: real and weak

Real behavioral tests in `test_plan.py`:

- Unknown top-level key refusal.
- Non-object plan refusal.
- Unknown ship key refusal.
- The four currently named required ship keys.
- Six top-level mapping-shape cases.
- Bare-string `node_models` refusal.
- Both CLI subprocess refusal tests.

Weak or vocabulary/source tests:

- `test_every_key_the_code_reads_is_one_the_plan_may_carry`, [test_plan.py:43](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_plan.py:43), regexes only literal `plan.get()` calls in `cli.py`. It misses dynamic reads and every other source module.
- `test_every_ship_key_the_code_reads_is_one_the_block_may_carry`, [test_plan.py:81](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_plan.py:81), asserts on source vocabulary. It cannot detect conditional dependencies or accepted-but-ignored combinations.
- `test_the_shipped_example_still_loads`, [test_plan.py:28](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_plan.py:28), merely loads and checks two values. It does not prove the example “still runs.”
- `test_a_complete_ship_block_is_accepted`, [test_plan.py:77](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_plan.py:77), calls a four-field block “complete” without executing an effect. It misses the absent `chg_body` failure.
- The schema chart has no test at all.
- The new count test is a coarse check. At [test_documented_numbers.py:345](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_documented_numbers.py:345) it collects, then at line 355 counts only collection-output `SKIPPED` lines or substitutes a hard-coded two. Run-time conditional skips, platform/plugin differences, collection errors, or output-format changes invalidate the subtraction. “Collected minus guessed skips” is not “passed.”
- The count test also silently returns when the README number disappears: [test_documented_numbers.py:340](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_documented_numbers.py:340). That is the same “nothing matched = fine” defect its own file condemns.

## Change-record claims that are not true

CHG-20260823-28:

- “The plan file, closed” is not true as a schema claim.
- “Every key the code reads” is checked is false; the test checks literal reads in `cli.py`, while `store.py` also reads plan assignments dynamically.
- “The shipped example still runs” and “visited 20 nodes, 17 asks, finished” are not demonstrated by `test_the_shipped_example_still_loads`.
- “`ship` … required keys named” names direct indexing, not the fields required for enabled effects to complete.
- Task 5 says the test walks both lists; it walks source vocabulary, not semantic dependencies.

CHG-20260823-29:

- “The test count is checkable” overstates a collection-time estimate as a run-time pass count.
- “The chart matches the code” is false due to the chart’s open-plan sentence, four-versus-five contradiction, and overbroad shape-refusal claim.
- “Known gaps complete” is false against the plan defects above.
- “1084 passed, 2 skipped” was not independently demonstrated by the new test’s method.

## What I could not check

- I could not run pytest in this managed read-only environment. Pytest failed before collection because Python could find no writable temporary directory. Therefore I did not independently observe the claimed `1084 passed, 2 skipped`.
- I did not execute destructive ship effects such as branch creation, commit, push, or PR creation. Their dependency findings above come from the actual effect construction and apply callbacks.
- The tracked commit was reviewed at `c123aa369c9bfb7a3937817c06f467319dd6bfa1`. The checkout also contained an unrelated untracked `docs/design/reviews/plan-readme-brief.md`; I did not use or modify it.
