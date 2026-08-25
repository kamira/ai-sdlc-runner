# fable-seat — CHG-20260823-30 (the closed plan, and the README)

Dispatched via the Agent tool on the fable model, against
[`plan-readme-brief.md`](plan-readme-brief.md), on a frozen tree at `c123aa3`.
Committed whole and unedited below.

---

# VERDICT: `not sound`

Suite state verified: `1084 passed, 2 skipped` on this machine, frozen at c123aa3. Everything below was run, not inferred.

## 2. The single worst thing

**The silent dry run — the exact case six reviews named and CHG-28 claims closed — is still producible with keys the closed schema accepts.**

`src/ai_sdlc_runner/cli.py:326-327`:

```python
record = ship.record_effects(repo, chg_id, task, acc_id, tick=_tick,
                             write_acc=_write_acc) if task else []
```

A plan whose `ship` block carries `acc_id` and `acc_body` but no `task` passes `plan.check` — every key is in `SHIP_FIELDS`, all four required keys are present — and `record_module` then carries **zero effects**. Proven:

```
plan.check({... "ship": {"repo":".", "chg_id":"CHG-X", "branch":"b", "message":"m",
                         "acc_id":"ACC-9", "acc_body":"evidence"}})   # accepted
cli.effects_provider(p)("record_module")  ->  []
```

The acceptance record is never written, nothing refuses, nothing reports, and the run finishes. That is "a setting that looks configured and does nothing" — the doctrine quoted in `plan.py`'s own docstring — inside the very block the change closed, one conditional deeper than the misspelling it fixed. The closure answered the complaint (a misspelt key) and not the finding (ship configuration that silently does nothing).

## 3. Findings on the closed plan (CHG-20260823-28)

What holds, first: unknown top-level keys, unknown `ship` keys, missing required `ship` keys, the six mapping shapes, and `node_models` bare strings are all genuinely refused, at the CLI door, exit 2 — reproduced. The example plan loads and finishes (`visited: 20, asks: 17, state: finished`). `SHIP_REQUIRED` is the right four: `effects_provider` indexes exactly `repo`, `chg_id`, `branch`, `message` (cli.py:290-304) and `.get()`s the rest. I found no key the code reads that `FIELDS` lacks — no correct plan is refused (checked every `plan.get(` across `src/`, all eight in `FIELDS`).

What does not hold:

1. **The `acc_id`-without-`task` silent no-op** (above). The interior dependency `acc_id ⇒ task` is validated nowhere.
2. **"Types, not only keys" is true for six keys and false for the rest — accepted plans crash the runner with raw tracebacks, exit 1, not refusals.** All three proven by running the CLI:
   - `"autonomy": 42` → `AttributeError: 'int' object has no attribute 'lower'` at `policy.py:601`, uncaught (engine catches only `EngineError/PolicyError/CliError`).
   - `"decisions": {"feedback": 123}` → `TypeError: object of type 'int' has no len()` at `engine.py:759` — the brief's exact probe, a `decisions` value of the wrong type.
   - `"ship": {"message": 123, ...}` → `AttributeError: 'int' object has no attribute 'splitlines'` at `ship.py:54`, at config-build time. `_check_ship` checks presence-and-truthiness (`not ship.get(key)`), never type.
3. **`plan.py`'s docstring claims a check the code does not make.** "`operations` an object of lists" — the code checks only that `operations` is a Mapping. `"operations": {"engineer_build": "write stuff"}` passes `plan.check`, and the engine then iterates the string character-wise and halts with the nonsense message `Got 'w'`. A name standing in for a constraint, in the closing module's own documentation.
4. **An operation with an extra key runs to `finished` silently.** Proven: `{"description": ..., "kind": "ordinary", "kinds": "deploy", "targets": [...]}` — return code 0, state finished, stray key ignored. The plan's "deliberately does not check" list names node-spec interiors and node ids; it does not name operation interiors, which are closed by nobody.
5. `"risk": "banana"` is accepted at the door and halts (governed, exit 10) only when the first gate is resolved — a refusal, but not at the door the change advertises. `"autonomy": "auto"` (a loosening) is accepted and correctly handled tighten-only by `policy.verdict` — that one is by design.

## 4. The README and the chart — every claim false now

**README:**

- **"That drives all 24 nodes, asks 17 questions"**. False. The run visits **20** nodes — reproduced (`visited: 20 node(s)`), and CHG-28's own record says "visited 20 nodes, 17 asks". Five failure-path nodes are never visited on the green path. Worse: `test_documented_numbers`'s node-count check *passes* this sentence, because its regex validates that "24" equals `len(graph.NODES)` — it checks the figure against the wrong referent. The claim is about a run; the check is about the graph.
- **"pytest -q # 1084 passing"** is true only on a machine without `curses`. Both skips are `curses` importorskips; on CI's Ubuntu they execute and `pytest -q` prints 1086. The test that claims to pin this number cannot see it — see §5.
- **"All four pages are pinned by tests"**. Overstated: `docs/SCHEMAS.md` §15 says **"Fifteen routes, eight `GET` and seven `POST`"** and again "fifteen routes" later, while the code has **17 routes, 8 GET and 9 POST**. `test_api_schema.py` pins API.md's count, not SCHEMAS.md's — the drift the pinning claim says cannot happen is standing on the pinned page's own catalogue entry.

**The chart (`docs/schema-atlas.html`) — CHG-29 ticks "The chart matches the code" and it does not:**

- *"Five shapes in sequence. **Two of them are closed**, and they are the two that cross the boundary into a model."* — three of the five stages are now chipped closed, and the plan file does not cross into a model. Both halves stale.
- The "open" legend: *"Unknown keys are silently accepted and do nothing. **The plan file is the one that matters — see the open question below.**"* — the plan is closed; the callout it points at says so itself. The page contradicts itself.
- Constraints header: *"**Four** are enforced in code on every path in."* — five; the page's own legend says five. Internal contradiction on the count that is the chart's subject.
- Footer: *"Counts pinned by `tests/test_schemas.py`, `test_api_schema.py`…"* — **no test in the repository reads `schema-atlas.html` at all** (grep over `tests/`: zero hits). The chart is entirely unpinned while claiming to be pinned.

## 5. The tests

**Real:** the top-level-typo parametrisation, the ship-typo and missing-required-key tests, the six wrong-shape parametrisations, the bare-string `node_models` test, and both CLI subprocess tests — the typo test even fixed the previous round's vocabulary trap correctly (checking for the `state:` line, not the word "finished"). `test_schemas.py`'s closed-count test genuinely exercises each refusal.

**Weak:**

1. **`test_the_test_count_the_readme_states_is_the_real_one` — the next "coarse check answering safe about something it had not examined."** Its comment says the skips are "Counted, not guessed". They are always guessed: `pytest --collect-only -q` never emits `SKIPPED` lines (verified), so the fallback constant runs on every machine. On Ubuntu CI the skips are 0, `pytest -q` prints 1086 passed, the README's 1084 is false there — and this test passes, because it computes 1086 − 2 = 1084 everywhere. There is a third, package-conditional skip site that would silently break the arithmetic in the other direction.
2. **The node-count check validated a false sentence.** "drives all 24 nodes" matches `(\d+)\s+nodes` and passes because 24 == `len(graph.NODES)` — vocabulary checked against the wrong claim.
3. **`test_every_ship_key_the_code_reads_...`** — the regex is character-soup that happens to work today; the `("origin",)` exclusion is dead; and nothing machine-checks that `SHIP_REQUIRED` is exactly the direct-indexed subset.
4. **`test_every_key_the_code_reads_is_one_the_plan_may_carry`** guards one direction only: reads ⊆ FIELDS. A FIELDS key nothing reads would pass it.

## 6. What the two change records claim that is not true

**CHG-20260823-28:**
- "Closing the outside while leaving that open would answer the complaint and not the finding" — and that is what happened: the ship block still contains a silently-inert configuration.
- "Types, not only keys" — holds for six mapping keys and `node_models`; `autonomy`, `decisions` values, and every `ship` value type produce uncaught tracebacks from accepted plans.
- The Not-claimed section names node-spec interiors and node ids, not the operation interior or the value-type crashes — the reader is told the residue is checked elsewhere when part of it is checked nowhere.

**CHG-20260823-29:**
- Task 5 "The chart matches the code" is ticked and false three ways, plus the footer's false pinning claim.
- "Five kinds of claim are machine-checked" — SCHEMAS.md's route count is checked by nothing and wrong; the atlas is checked by nothing.
- "compares collected-minus-skipped, which is the number a run actually prints" — it compares collected minus a **constant**; the number a run prints differs by platform and the check cannot tell.

## 7. What I could not check

- That "six prior reviews" named the plan — I did not audit `docs/design/reviews/` for the count.
- The ship sequence end-to-end against a real git remote and `gh`.
- The console/server behavioural claims beyond reading `server.py`.
- The two-process store gap and the Windows-path defects — claims of absence, taken as stated.
- Whether any plan in the wild carries keys the closure now refuses.

---

**Why `not sound` and not softer:** CHG-29's task table ticks a done-when that a reader of the chart can disprove in three places, while the chart's footer claims a pinning that does not exist — a ticked task that is false is this repository's own definition of a false green. And CHG-28's headline — the silent dry run is closed — is refuted by a five-line reproduction inside the block it closed. The work is substantial and most of it holds; the claims made for it are larger than the work, and this house's rule is that the claim, not the effort, is what is under review.
