# fable-seat — CHG-20260823-21 (the schema design)

Dispatched via the Agent tool on the fable model, against
[`schemas-brief.md`](schemas-brief.md). Committed whole and unedited below.

---

# Independent review — the schema design of ai-sdlc-runner

## 1 · VERDICT: `sound with changes`

The load-bearing decisions are right and are genuinely enforced: closedness is real code on every write path I could find, `reach` is computed and stripped on save, `seq` is an integer, the CSV is defused, attachments are content-addressed. The changes required are not cosmetic, though: the catalogue has already drifted from the code in a checkable way, the outermost schema (the plan file) violates the design's own first principle, and the closed schemas are closed by key-set only — a type the schema permits is mangled by the renderer, proved below.

## 2 · The single worst schema: **#2, the Plan file**

Every other schema rides inside it, and it is the only entry point with **no validation at all** — no unknown-key refusal, no version, no shape check. `cli.py:516-526` and `cli.py:665-679` consume it entirely through `plan.get(...)`. The repository's own doctrine, quoted on line 6-7 of SCHEMAS.md, is that *"a setting that looks configured and does nothing is worse than one that was rejected"* — and `settings.py:150` and `models._model_from` enforce exactly that for files far less consequential. The plan file gets the opposite treatment, and the worst case is not hypothetical: `effects_provider` (`cli.py:284`) does `settings = plan.get("ship")` and returns `None` when absent — so a plan whose `ship` key is misspelled runs **with no side effects and reports `finished`**. A dry run wearing a shipped run's report, produced by one typo nothing refuses. Misspelled keys under `seat_models`, `node_models`, or `decisions` are likewise silently absorbed. This is "a name standing in for a constraint" at the design's front door.

## 3 · Findings per schema

| # | Schema | Judgment | Evidence |
|---|---|---|---|
| 1 | Node | **sound** | All 14 fields match `graph.Node` exactly; 24 nodes, 15 asking nodes, 10 gate uses — verified by running `graph.validate()` and counting. Both claimed biconditionals are real checks (`graph.py:281-287`). Minor: "eight cross-rules" matches no natural partition — `validate()` has ~24 raise sites; the number is decorative. |
| 2 | Plan file | **broken** (as a shape; the code runs) | Fully open at the outermost boundary; see §2. The catalogue's own `"ship": { … }` is a shrug — the ship block's fields (`chg_id`, `chg_body`, `task`, `acc_id`, `acc_body`, `repo`…, per `ship.py`/`cli.py:275-324`) are written down nowhere. |
| 3 | Node spec | **needs change** | Closed by key set (`workorder._check` refuses extra and missing — I proved both) but **not by type**. `engine.py:~512` declares `instructions` legally "a string in some plans and a list in others, and both are in use"; `workorder.render` then does `str(node_spec["instructions"])`. Ran it: a list arrives at the model as the Python repr `'[\'step one\', "step two: don\'t"]'` — mixed quoting, not JSON. A value the schema permits and the renderer cannot handle honestly, in the order's most important field. |
| 4 | Operation | **sound** | `classify`/`derive`/`on_trust` (`policy.py:434-524`) are coherent; declaration required, targets overrule prose, prose only adds stops. Refusal of undeclared nodes and the effects-carve-out of `allow` verified at `engine.py:890-907`. |
| 5 | Work order | **needs change** | Closed for real (`workorder.py:141-144` asserts the exact key set on the only render path; extra/missing refused — proved). The instructions-mangling of #3 lands here. Also `policy_verdict.source` carries two facts — provenance *and* the refused-loosening report — concatenated into one string (`policy.py:~605`); acknowledged in a comment, but it is one field with two meanings that no consumer can separate mechanically. |
| 6 | Answer contract | **needs change** | The catalogue and `examples/agent.py` say a decision node answers `{"verdict": …}`; `engine.py:954` actually accepts `branch` or `verdict` or `outcome`, with `branch` silently winning — three aliases for one fact, two of which can disagree in one answer. Seat verdicts likewise accept `verdict` or `outcome` (`engine.py:997`). And `engineer_build` "must answer `{"module": …}`" is unenforced: a build that omits it never shrinks the frontier and dies at `max_steps=200`, far from the cause. |
| 7 | Ask journal entry | **sound** | Fields verified against `engine.py:120-131` (`ask_id, node_id, seat, status, order` + `result` on answer). Carries no model — and the catalogue says so, and says why the store isn't derived from it. Honest about being mutable. |
| 8 | Conversation doc + turn | **sound** | Nine kinds match `KINDS`; header matches `conversations.py:574-578`; the model/backend split is real (`conversations.py:706-714`); `decision` values `approval`/`rejection`/`ruling` confirmed at `engine.py:1230/1246/1518`. The only versioned schema in the design, correctly. |
| 9 | CSV export | **sound** | `CSV_COLUMNS` (`conversations.py:790-791`) matches the catalogue column-for-column; `_defuse` checks the first *non-blank* character; the over-limit flag is computed on both long cells. |
| 10 | Model registry | **sound** | Closed on **every** path in, which I checked one by one: file load (`_model_from` refuses unknown fields — proved), `Registry.add` → `validate`, and the console `POST /models` (`server.py:561`) goes through `_model_from` + `add`. Eight fields persist; `save()` strips `reach`/`leaves_this_machine`. This is what "closed" should mean everywhere. |
| 11 | Settings | **sound in code, mislabeled in catalogue** | `settings.py:150-155` refuses unknown keys with the same doctrine — Settings **is** a closed schema. The catalogue's header says "Two schemas are closed" while its own table marks **three**, and the true count of enforced-closed schemas is **four**. The doc contradicts itself and undercounts the code. |
| 12 | Attachment manifest | **catalogue entry is false** | SCHEMAS.md line 213: `"id": "<sha256[:32]>", // ALSO the stored filename`. Ran it: `id` is the **full 64-char digest** and is **not** the stored filename (`stored_name(id) = id[:32]` is). `attachments.py` says so explicitly: *"The id stays the full digest."* The code is right; the map is wrong, about the one field the entry leads with. Anyone joining manifest ids to stored files off this page writes a bug. |
| 13 | Run report | **sound** | All 22 fields at `engine.py:282-339` match the catalogue's list exactly; three states confirmed (`engine.py:195-197`). |
| 14 | SQLite DDL | **needs change — the residual defect is `opened_at`** | Three findings, first is the defect the brief said to assume: **(a)** Both prior seats called `opened_at` a guess (`reviews/sqlite-only-codex-seat.md:102`, `fable-seat.md:53`); the "corrected" doc deleted `updated_at` but kept `opened_at` with only a provenance note — yet **nothing in the code reads an open timestamp** (the header at `conversations.py:574-578` has none), making it exactly the dead-column class `updated_at` was deleted for; worse, it is a second copy of the OPENED turn's `at` — the "two truths" the `turns` comment forbids **eight lines below it** — minted at a different moment on the live path (they can disagree; the OPENED turn's guarded append can even fail, leaving `opened_at` with no OPENED turn) and forced equal on import, so live and imported rows carry different semantics in one column. **(b)** SCHEMAS.md's copy of the DDL drifts from `sqlite-only.md`: it moves `user_version` into the block and claims "two are per-connection state, one is the file's" over five pragmas — I ran it: per-connection = `foreign_keys`, `synchronous`, `busy_timeout` (three); file's = `journal_mode`, `user_version` (two). Wrong on both counts, in the entry whose subject is pragmas that lie. **(c)** The duplicate-`seq` policy is stated only for the importer. On the live path, `resume_or_open`'s failure branch (`conversations.py:632-634`) resets `_seq = 0`; against the PK, every turn of that resumed run is *refused* and swallowed by `_guarded` — the file backend degraded to "duplicates reported", SQLite degrades to "the whole resumed conversation lost to stderr". Unstated. |

## 4 · Schemas MISSING from the catalogue

1. **The server HTTP API** — the largest omission. ~8 GET and 7 POST endpoints (`server.py:474-580`: `/flow`, `/run`, `/run/events` (SSE), `/models`, `/attachments`, `/config/nodes`, `/whoami`, `/run/gate`, `/run/reject`, `/run/instruct`, `/run/decide`…), each with a JSON request/response shape, crossing a process boundary to a browser. Nobody wrote any of them down.
2. **`runner.yaml`** (`agent_command`, `agent_timeout`, `cli.py:36-60`) — durable config with its own hand-rolled fallback parser, which has already produced one shipped bug (the inline-list split, per its own docstring). Not catalogued, not closed.
3. **The `.conversation` marker** (`conversations.py` MARKER: `{"conversation_id", "project"}`) — durable, load-bearing at resume, refuses a project mismatch. Uncatalogued.
4. **`_project.json`** per-project marker in the file store (`conversations.py:328-334`) — durable; dies with the sqlite move but exists today.
5. **The ship block's interior** — present in entry 2 as literally `{ … }`.
6. **The intake Survey aggregate** (`intake.py`: `problems: {seat: […]}, missing, safety`) — the seat's answer is in entry 6, its union that lands in `RunReport.survey` is not.

## 5 · Delete or merge

- **The answer-contract aliases**: collapse `branch`/`verdict`/`outcome` to one key (`engine.py:954, 997`). Three names for one fact is redundancy that can *disagree*.
- **SCHEMAS.md line 6**: "Two schemas are closed" — make it four and add Settings to the closed set; a catalogue of closedness that miscounts its own subject undermines the page.
- **`opened_at`** in the DDL: delete it, for exactly the reasons `updated_at` was deleted. If a listing ever needs an open time, it is the OPENED turn's `at`, readable in one query.
- **Accepted, but name it**: the full work order is stored twice per ask — journal entry `order` and conversation `ask` turn `order`. The mutable-index/append-only-log rationale is sound; the byte-level duplication should be stated in the catalogue since both are durable.

## 6 · What I could not check, and what I would need

- **The 3.9 × Windows SQLite cell, the killed-process test, and the two-writer test** for the DDL — the design doc itself lists these as owed; nothing exists to run. I verified the pragma-persistence claims on this machine's Python/SQLite only.
- **Mongo and TinyDB behavior against real servers** — I read the backends and their tests but ran neither against a live instance; both are slated for removal anyway.
- **The server API under a real browser** (SSE stream shape, token fragment flow) — I read `server.py` and its tests; I did not drive the console.
- **What "eight cross-rules" was meant to enumerate** — I would need the author's list; no partition of `validate()` I can construct yields eight.
- One structural note: `tests/test_documented_numbers.py` pins other documented numbers, but **nothing pins SCHEMAS.md** — no test references it. The drift I found (entry 12, the closed-count, the pragma arithmetic) is the predictable result, and the fix is the mechanism this repo already owns: pin the catalogue's checkable claims, or expect this page to keep rotting under the sentence "that file is authoritative, this page is a map."

Full test suite: **915 passed, 2 skipped** — the shipped shapes do what their tests say; every finding above is in what the tests do not cover: the map, the types inside closed key-sets, and the unbuilt DDL.
