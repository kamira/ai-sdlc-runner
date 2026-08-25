# fable-seat verdict — README.md and docs/defect-log.md at d93fcd2

Method note: I read both documents in full, all six listed source files, `workorder.py`, `models.py`, `settings.py` (in part), `tests/test_documented_numbers.py`, `tests/test_server.py`, `tests/test_nothing_is_unwired.py`, the CI workflow, `pyproject.toml`, and CHG-20260823-14/-15. I ran the suite and one probe script (from the scratchpad) read-only against the tree; `git status --porcelain` is clean before and after — no tracked file was touched. Measured at this commit: **849 passed, 2 skipped** (851 collected).

---

## R1 — Is every factual claim in the README true? Verdict: **mostly true, with two demonstrably false sentences and one unenforced guarantee**

Checked claim by claim:

**The risk table's "stops at" lists — TRUE.** `policy.py:100-124`: low stops only at `merge` (`"merge": {"low": CONFIRM, ...}`, policy.py:123); medium stops at `plan_confirmed`/`feasibility_confirmed`/`before_dispatch` (all CONFIRM) plus `merge` (HALT) = 4; high adds `lead_review` (HALT), `qa_verify` (HALT), `acceptance` (HALT_INDEPENDENT), `pr` (CONFIRM) = 8. Counts and placements match. Nit: the "Where" column mixes node ids (`pm_confirm`, `lead_assess`, `pm_signoff`) with gate ids (`acceptance` is the gate on node `qa_accept`), and the README never says which naming it is using — `--confirm` takes gate names, so a reader copying `--confirm pm_confirm` from the table gets an error (`engine.py` refuses unknown gates loudly, cli row at README.md:233 says "GATE").

**"A pool's choice is random on purpose and reproducible on purpose too, seeded by run and node" — TRUE in substance.** `engine.py:628`: `random.Random(f"{cfg.dispatch_seed}:{node.id}:{nth_ask}")` — deterministic given seed, node, and ask ordinal; every dispatch recorded (`engine.py:1366-1369`). Precision nit: nothing run-specific enters the seed from the CLI path (`cmd_run` never sets `dispatch_seed`, so it is always 0); "seeded by run" is a gloss, and two runs of the same plan dispatch identically — stronger than claimed, not weaker.

**"One ask, one session" — TRUE.** `engine.py:566-575`: open, ask once, close in `finally`; a factory returning a session it already returned is refused. Seat panels and model panels open one session per voice (`engine.py:1215-1225`, `1345-1357`); the CLI backend is one process per ask (`cli.py:88-156`).

**The three "local only" refusals — TWO TRUE, ONE OVERSTATED.** Host check: `server.py:385-388` (403 on non-loopback Host). Origin check: `server.py:390-394`. But the README says, at README.md:268-269:

> "**a token is required on every request** — minted at startup, written owner-only."

This is not what the code does: `server.py:381-384` exempts `/` and `/index.html` ("The shell only. … just not token-checked"), and `/run/events` accepts the token as a **query parameter** (`server.py:396-403`), which the code itself calls "a weaker place to carry a credential (it reaches access logs)". The exemptions are deliberate and defensible; the README's sentence is stronger than the code. Likewise "The token travels in the URL fragment, which browsers never send to a server" (README.md:274-275) is true of the openable link but silently untrue of the event stream. "Written owner-only" is `os.chmod(path, 0o600)` in a try/except (`server.py:100-104`) — best-effort on Windows.

**"Extra `input_artifacts` … on every node's work order" — TRUE.** `engine.py:406-409` (declared) and `engine.py:491` (done, appended never replacing); instructions numbered "instruction i of N" (`engine.py:492-498`). The task-17 hazard is closed: the red-line scan reads `cfg.node_specs`, not the merged order (`engine.py:755, 775-781`), so an attachment named `production/spec.pdf` no longer trips `policy.py:220`'s prod regex.

**Three unanswered intake asks — TRUE.** `intake.py:60` (`ASK_LIMIT = 3`), `intake.py:153-158` (`>=` — "the third unanswered ask is the one that has failed"), `intake.py:64/188-193` (fewer than three options refused), `engine.py:1303-1321` (options requested from a model, recorded as an ask, run suspends; nothing picks one).

**`decisions.next_module` may be `"frontier"` — TRUE.** `engine.py:645, 648-681, 686-692`: reads the latest `pm_plan` answer's `modules` and the `engineer_build` answers' `module` keys. (That the plan's *agent* must return a `modules` list for this to work is nowhere in the README — see R3.)

**FALSE №1 — README.md:383:**

> `pytest -q          # 847 passing`

Measured at this commit: **849 passed, 2 skipped**. CHG-20260823-15.md:184 — part of the same two-change sequence under review — itself says "849 passed, 2 skipped", and defect-log.md:3 says "849 tests". The README's own table (README.md:345) sells `test_documented_numbers` as refusing "a figure in the docs that disagrees with the code" — but the test count matches no pattern in `tests/test_documented_numbers.py` (no `\d+ passing` rule, DOCS list at lines 40-53), so this figure is exactly the hand-typed, unbound kind the file was written to eliminate, and it has already drifted.

**FALSE №2 — README.md:221-223:**

> "Without it every ask goes to a stub that answers nothing, and the run completes while having asked nobody."

The first half is true (`cli.py:159-206`: no `agent_command` → `_Stub`). The second half I tested: a full walk against the stub with complete node specs and `undeclared="allow"` raises at the first decision node — `EngineError: node 'pm_confirm' decides on its answer, but the answer named no branch. It must carry one of ['no', 'yes'] as 'branch', 'verdict' or 'outcome'` (`engine.py:882-901`). The silent-success failure mode this sentence warns about was real once, but `_answered_branch` now forecloses it: as shipped, the stub run halts loudly and early. It does not complete. The same false mechanism is enshrined in defect-log.md:352-353 ("the run completes having asked nobody, which looks like success") and CHG-15.md:136-137, and in the docstring of `test_the_readme_puts_global_flags_before_the_subcommand` (tests/test_documented_numbers.py:301-302). The error direction is cautionary, but it is a present-tense claim about what the code does, and the code refutes it.

**UNENFORCED — README.md:127:**

> "Acceptance on a high-risk change is `halt_independent`: the verifier must not be the builder."

`halt_independent` exists in exactly one live place: the policy table (`policy.py:115`). `STOPPING = (CONFIRM, HALT, HALT_INDEPENDENT)` (`policy.py:53`) flattens it, and `engine.py:21-22` says in as many words that "no ordering between `confirm`, `halt` and `halt_independent` is needed anywhere". Nothing anywhere checks who verifies: there is one operator token (`server.py:96-106`), no second identity, and `--confirm acceptance` from whoever holds it passes the gate identically to any `halt`. The defect log itself records (defect-log.md:87-91) that independence "enforced by a button caption" was a defect; the shipped enforcement is a verdict string's name. See R4.

Other spot-checks that came back TRUE: seat floor 3 with recorded bypass (`policy.py:568, 629-641`; `engine.py:1003-1007`); veto → majority → tie = `undecided`, undecided suspends and a person's ruling is "recorded as *theirs*" (`policy.py:651-709`; `engine.py:1415-1424`); the mode table matches `graph.py:60-68` and the engine's per-mode session behavior; closed node-spec schema refuses extras and omissions (`workorder.py:77-85, 99`); six never-automated kinds with target derivation overruling the declaration (`policy.py:132-140, 437-441, 466-471`); executors never vouchable (`policy.py:295-305`, `settings.py:168`); install/pyproject ("Standard library only", `dependencies = []`, `[test]` extra); CI matrix and ledger job as stated.

---

## R2 — Is the flow diagram right? Verdict: **correct**

Compared node by node against `graph.py:129-211`. All 24 nodes appear (I enumerated the tuple: 24; every id in the diagram matches). Every branch label is the graph's own: `yes/no` at `pm_confirm` and `pm_signoff` (graph.py:147, 158), `module/none` at `next_module` (graph.py:160), `pass/fail` at `lead_task_review`, `re_review`, `lead_review`, `qa_accept` (graph.py:173, 183, 189, 199), `more/done` at `feedback` (graph.py:208). All ten gates carry `◆` with the gate's policy name; both terminals (`halt_second_fail`, `done`) carry `■`. The three failure paths the mock-up omitted are drawn. CHG-15 task 1's done-when is satisfied.

One residual, which I flag because omission-of-recovery-paths is this project's recurring defect: the diagram draws `branches` but not `rejects_to`. Three rejection edges the engine actually honors (`engine.py:1138-1148`) have no coincident drawn branch and are invisible: `lead_assess` rejects to `pm_plan` (graph.py:151), `engineer_selfverify` rejects to `engineer_build` (graph.py:168), `qa_verify` rejects to `next_module` (graph.py:195). The README nowhere says rejection routing is omitted from the drawing. Not a false claim — the diagram never promises rejections — but the operator's "gate refused" paths are exactly the kind of edge this repo has twice been caught not drawing.

---

## R3 — What could somebody NOT do after reading this? Verdict: **they cannot get a real run past the first node**

Walking the path of a competent newcomer with the repo checked out:

1. **Install, `runner flow`, `runner policy`, `runner serve`** — all work as documented.
2. **Write a plan — stuck, twice over.** The page's only plan example (README.md:282-305) is fenced as `jsonc` and contains `//` comments; `cmd_run` parses it with `json.loads` (`cli.py:349`), so a copy-pasted `plan.json` fails with a JSONDecodeError. There is no runnable example plan anywhere in the repository (the only other `node_specs` mention is `docs/ARCHITECTURE.md`).
3. **Run it — stuck again.** Even de-commented, the example supplies `node_specs` for `engineer_build` only. Every asking node the walk reaches requires a spec or the engine raises — `engine.py:481-485`: *"node 'intake_review' has no work order: no node spec was supplied for it"* — and the first asking node is `intake_review`. There are 15 asking nodes (`graph.asking_nodes()`), each needing **all nine** fields, because the closed schema refuses omissions too (`workorder.py:80-81`). Nothing on the page says this.
4. **The agent contract is not on the page at all.** The README never states what the dispatched program must print: JSON on stdout (`cli.py:147-153`); a decision node's answer must carry `branch`/`verdict`/`outcome` naming a branch (`engine.py:893-897`); `pm_plan` must answer with a `modules` list or `"frontier"` raises (`engine.py:674-679`); `engineer_build` should return a `module` key for the frontier's "built" set (`engine.py:670-672`). Anyone wiring `["claude", "-p"]` per README.md:45 has no way to know their agent's required output shape without reading `engine.py`.
5. **`operations` is a required plan block the plan section never mentions.** Any working node that declares no operations is refused by default — `engine.py:846-853`: *"does work that could change the world and declares no operations"*. The plan-format section (README.md:281-314) shows no `operations` key and never gives the `{"description", "kind", "targets"}` shape (`policy.py:436-441`); the only hint is the `--undeclared` flag row. A first real run stops here with a good message, but the page claiming to show "How the plan is written" omits a block every real plan needs.
6. Minor: `--config` has a default, `config/runner.yaml`, shipped in the repo with `agent_command` commented out (`cli.py:30`; `config/runner.yaml:12`) — the README implies the flag is the only way. And the Layout section (README.md:358-376) omits `effects.py`, `probes.py`, `ship.py`, `settings.py`, `tui.py` — `ship.py` being the module that actually commits, pushes, and opens PRs, arguably the most consequence-bearing file not on the map.

Once *past* a stop, the answering loop is genuinely well-documented: the suspended report prints `continue with: --resume --confirm <gate>` (`cli.py:462-465`), matching the README's resume example.

---

## R4 — What does it overclaim? Verdict: **four sentences assert what nothing enforces**

1. README.md:127 — *"the verifier must not be the builder"* — detailed under R1. A stated guarantee whose entire implementation is the string `"halt_independent"` in a table.
2. README.md:268-269 — *"a token is required on every request"* — two routes exempt, one route takes the token in the query string (R1).
3. README.md:321 — *"**Every change gets a record** in `docs/changes/` before it is built"*. The records exist (39 of them), and `tools/ledger_check.py` enforces status/acceptance pairing — but nothing can or does enforce **"before it is built"**; that is the author's account of their own discipline, presented in the indicative. Same section, README.md:336-337: *"A split does not pass. The runner's own rule — a tie decides nothing — applies to its own design records, or it is not a rule."* — the runner enforces this for runs; nothing enforces it for design records. Both sentences are practice described as mechanism, in the section the brief predicted, by the person who did the governing.
4. README.md:350-351 — *"the nine that only running it found **had all been shipping**"*. The defect log it summarizes says **"several"**, twice: defect-log.md:151-152 ("Several had been shipping for several changes") and defect-log.md:381-382 ("several of which had been shipping for changes"). The README upgrades its own source's "several" to "all". Adjacent, the log's own "The pattern in **all nine**: a one-module … demo had the same bug and looked fine" (defect-log.md:383) is under-evidenced for at least the start-button entry (defect-log.md:229-235: it "threw on first click" — a one-server demo's first click is not obviously exempt).

Also worth naming: the README's tests table (README.md:344) lists `test_nothing_is_unwired` — that is a **file** name; the function is `test_nothing_public_in_src_is_unreachable_from_src` (tests/test_nothing_is_unwired.py:138). Runnable as written via the path, so a nit, not a defect.

---

## R5 — Is the defect log honest? Verdict: **substantially honest, arithmetically broken, and demonstrably incomplete in a checkable place**

The entries themselves check out where the code can confirm them: the quoted `policy.py` seat-raise exists (policy.py:698-700), the prod regex is at policy.py:220 exactly as cited, `_TARGET_FIELDS` exists (engine.py:755), `allow_reuse_address = False` with the two-runners story is in `server.py:625-641`, the journal-not-optional fix is in `cli.py:509-521`, and the `--seats` alias is really declared on the same line as `--review-seats` (`cli.py:620`). The self-incriminating entries (the primer, the dropped `role`, one-seat-reported-as-two) are the kind of material an author writes only when being honest. That said:

1. **The log contradicts its own table.** defect-log.md:22: *"**two of these thirty-two defects** were visible on a screen."* The table at defect-log.md:9-14 says 13 + 9 + 4 + 9 = **35**, and I counted the `###` headings: 13, 9, 4, 9 — 35 entries. The history is visible in CHG-14.md:22-27, whose table says 13/9/4/**6** = 32: three process failures were added later (the three CHG-15-born entries) and the "thirty-two" was never re-summed. This is the *same shape* as two defects the log itself records — "the record contradicted itself eleven lines apart" (defect-log.md:93) and "claimed 23 nodes and drew 18" (defect-log.md:103) — occurring in the ledger of those defects. `docs/defect-log.md` is not in `test_documented_numbers`' DOCS list (tests/test_documented_numbers.py:40-53), so nothing binds any of its numbers.
2. **One defect from the very change under review is missing.** CHG-20260823-15.md:140-142 records error №3: *"`feedback` branches on `more`/`done` — Not on the node names the diagram implied."* The log carries that change's other two errors (defect-log.md:337-344 and 346-353) and the meta-correction (355-360), but a grep of the log for "feedback" returns nothing. So "records **every** defect hit while building this" (README.md:348) is falsified by the author's own adjacent change record.
3. **"Four by the test suite" includes a non-defect.** The fourth entry says so itself — defect-log.md:283: *"Not a defect — the intended collision."* Counting it inflates the suite's column in a table whose whole point is the relative usefulness of the groups. (The downstream arithmetic "Three of the four … came from" the two class-catching tests, defect-log.md:386-388, stays internally consistent.)
4. **"Two … visible on a screen" is contestable beyond the count base.** The start button throwing (229), the stale-token bare 401 (237), the handler-less button (310), and "the console could not show where work was dispatched" (223) — an entry whose entire content is what the screen shows — make at least three or four screen-manifest defects. The claim as stated is unsupported by the entries below it.
5. **The screenshot explanation itself** — the quoted tool error ("the Browser pane is not displaying…") is not substantiable from the repository either way; I record it as *not substantiated* rather than as an excuse. The argument's second leg ("would not have helped much") rests on the miscounted "two of thirty-two", which weakens it. The general shape — most entries are tracebacks and assertions, for which captured text genuinely is the stronger evidence — is consistent with the entries.
6. "25 change records, 849 tests" (defect-log.md:3): 849 matches my measurement; `docs/changes/` holds 39 records in total, and a 25-record window (CHG-20260706-01 → CHG-20260823-15) matching "the operator console and its governance" exists — plausible scoping, not verifiable from the file itself, not flagged as false.
7. The section preamble "**Every one of these was found before the code existed**" (defect-log.md:32) is loose: the task-1 and task-2 entries quote then-existing engine code (`engine.py:572`, `engine.py:719`); what did not exist was the *change's* code. The intended meaning is recoverable, but the sentence as written is not literally true of its own entries.

---

## R6 — The single worst sentence

README.md:127:

> "Acceptance on a high-risk change is `halt_independent`: the verifier must not be the builder."

Weighted by reliance, this is the one. The README's central pitch is "the answer comes from a table you can read, not from a model's judgement" (README.md:28) — it teaches the reader that named policy values *are* enforced properties. A person choosing this runner for governed acceptance will read this sentence as "the system will not let the builder verify its own high-risk work". In the code, `halt_independent` is a string that behaves identically to `halt` (`policy.py:53`; `engine.py:21-22`), there is a single operator identity (`server.py:96-106`), and no mechanism records — let alone checks — that the confirmer of `acceptance` differs from anyone. The project's own defect log shows the author knows this failure class intimately: task 15's finding was independence "enforced by a button caption" (defect-log.md:87-91). The shipped enforcement is a caption one layer further down. Runners-up: "the run completes while having asked nobody" (README.md:222-223, false as shipped, demonstrated by execution) and "847 passing" (README.md:383, corrosive because it invites the reader to distrust every other number the moment they run the suite).

---

## On the brief itself

The brief steered fairly overall — the answers to its named R1 claims mostly came back *true* — but two of its framings deserve correction: it says the log "groups **32 defects**", inheriting the log's own wrong number (the log lists 35); and "the **counts** … are now checked by CI" overstates `test_documented_numbers`' coverage — it binds graph/policy/corpus counts, not the test total and nothing in `defect-log.md`, which is where the arithmetic defects actually sit.

---

## Verdict

**README: sound with changes**

What must change:

1. README.md:383 — replace "847 passing" with the measured figure (849 passed, 2 skipped at d93fcd2), and add a binding pattern (e.g. `\d+ passing`) or drop the number; as written it is the one figure in the file that `test_documented_numbers` cannot see, and it has already drifted.
2. README.md:222-223 — rewrite the stub sentence to what the code now does: the stub run does **not** complete; it halts at the first decision node with "the answer named no branch" (`engine.py:893-897`). Correct the same claim where it is replicated (defect-log.md:352-353 may stand as history if marked as the behavior *at the time*; the test docstring at tests/test_documented_numbers.py:301-302 should not assert a current mechanism that is false).
3. README.md:127 — either implement builder/verifier distinction for `halt_independent` (a second identity, or at minimum recording who confirmed `acceptance` distinctly) or rewrite the sentence to what is true: "acceptance on a high-risk change always halts for a person; independence of that person from the builder is asked for, not enforced."
4. README.md:268-269 — "a token is required on every request" → "on every request except the static shell page", and disclose the event stream's query-parameter token alongside the fragment claim (README.md:274-275).
5. defect-log.md:22 — fix "thirty-two" against the table's 35 (and re-verify "two … visible on a screen" against entries 223, 229, 237, 310); add `docs/defect-log.md` to `test_documented_numbers`' DOCS or give its header table a recomputed check, since it is now the only counted document nothing binds.
6. defect-log.md — add the missing CHG-15 §3 defect (the `feedback` `more`/`done` branch labels), or stop claiming the log records *every* defect (README.md:348).
7. README.md:350-351 — "had all been shipping" → the log's own "several", or produce per-entry evidence for "all".
8. README (plan section, README.md:281-314) — ship one complete, comment-free, runnable `plan.json` (all asking nodes' specs, an `operations` block, and the agent answer contract: `branch`/`verdict`/`outcome` on decision nodes, `modules` from `pm_plan`, `module` from `engineer_build`), or link to one; the current example cannot parse and cannot run past `intake_review`.
9. defect-log.md:245-248 — either drop the fourth "suite-caught" entry from the count or label the column so a non-defect ("the intended collision", line 283) is not counted as a defect.
10. Lower priority: note under the flow diagram that gate-rejection routing (`rejects_to`) is not drawn, with the three edges named (`lead_assess`→`pm_plan`, `engineer_selfverify`→`engineer_build`, `qa_verify`→`next_module`); soften README.md:321 and 336-337 from mechanism to practice; add the five omitted modules (`ship.py` above all) to the Layout section.
