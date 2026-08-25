# fable-seat — CHG-20260823-17 round 2 (the code)

Dispatched via the Agent tool on the fable model, against
[`conversation-store-round2-brief.md`](conversation-store-round2-brief.md), reviewing commit
`1212a91`. Committed whole and unedited below.

---

## 1. VERDICT: `not sound`

Two of the code's load-bearing safety claims are the repository's own two named defects, reproduced verbatim in the very functions that boast of having fixed them. Both are checkable, and I reproduced one by running the exact command the task gave me.

(Note: the working tree is being edited by a concurrent process — `conversations.py` currently has a Python **syntax error** at line 762 and there are untracked files `greet.py`, `conversation-store-round2-*.md`. I pinned every finding below to the committed code at `1212a91`, which is what this change actually is.)

---

## 2. The single worst thing

> `if query.get("directConnection", ["true"])[0].lower() == "false":` … and above it `if "replicaSet" in query:` — `conversations.py:188,192`, together with `socket_path = "%2f" in netloc.lower() or netloc.lower().endswith(".sock")` — `conversations.py:169`.

`local_mongo_uri` is the whole of design §4 — the function both seats demanded be *more* than a coarse check, because "a coarse check answering safe about something it had not examined" is this repo's second-most-frequent defect. It **is** that coarse check. Run against the committed code:

```
ACCEPTED: mongodb://remote.evil.sock            -> mongodb://remote.evil.sock?directConnection=true
ACCEPTED: mongodb://remote.evil.example%2f:27017 -> ...%2f:27017?directConnection=true
```

`remote.evil.sock` is a registrable DNS name. pymongo, given a host with no `/` or `%2F`, resolves it and connects over **TCP to a remote machine** — but the check classified it as a "genuinely local unix socket" on the strength of the string ending `.sock`, skipped the loopback test entirely, and returned it **without `--store-remote allow`**. `.sock`-as-suffix and `%2f`-as-substring are names standing in for the constraint "this netloc is only a local socket path." The design's §4 rule 3 ("the host is loopback, **or** a percent-encoded unix socket path — genuinely local, allowed") is implemented as a substring test that a remote host passes. This is a clean locality bypass and answers the task's Q3 directly.

The same class also weakens rules 4–5: MongoDB connection-string options are documented case-insensitive (pymongo lower-cases them), but the check matches the exact keys `replicaSet` and `directConnection`, so `?replicaset=rs0` and `?directconnection=false` slip past. `_hardened` then appends `directConnection=true` with a case-sensitive `"directConnection=" in uri` test (`:202`), so a URI carrying `directconnection=false` gets a *second, conflicting* `directConnection=true`. (Whether the driver then rejects, or true-wins by luck, I could not run — pymongo is not installed. Rules 1–2 bypasses via `.sock`/`%2f` do **not** depend on driver behaviour and are unambiguous.)

---

## 3. Round-1 findings

| # | Finding (seat) | Status | Evidence |
|---|---|---|---|
| 1 | "Derived from journal" is wrong; journal holds no operator turn (both) | **answered** | `RunConfig.conversation` is a first-class log written as turns happen; `_ask`→`ask/answer/unanswered`, gate sites→`decision`. Drove `examples/plan.json`: store held `opened, 17×ask, 17×answer, decision(merge), closed`. `test_an_operator_decision_is_a_turn` |
| 2 | Journal overwrites model turns; positional ids; 999 sort break (both/fable) | **answered** | `seq` is an int; `_assemble` sorts by `int(seq)` (`:503`). Drove 1100 turns → contiguous 0..n |
| 3 | Answering model not in any durable record (codex) | **answered** | `ask` turn carries `model` (`conversations.py:627`, `engine.py:588`); `test_the_answering_model_is_recorded` |
| 4 | Loopback host doesn't constrain `MongoClient`; topology discovery (both) | **partially** | `directConnection=true` forcing is real (`_hardened`) — good. But the URI-gate half is bypassable (§2 above). The "four rules constrain the URI" claim is false for `.sock`/`%2f`/case |
| 5 | `run_id` collision; Windows path not a filename (both) | **answered** | minted `conversation_id`, `.conversation` marker; re-attach vs new verified in `test_two_runs...` and a live 3-walk `serve` simulation |
| 6 | `--project` defaults to plan's parent dir (both) | **answered** | `--project` required, no default (`cli.py:_store_flags`), `project_id = sha256(name)[:32]` |
| 7 | Resume under a different project (both) | **answered** | refused by name (`resume_or_open:563`); reproduced |
| 8 | Journal-less run loses the conversation (fable/codex) | **answered** | `test_a_run_with_no_journal_still_gets_a_conversation` |
| 9 | CSV formula injection (fable) | **answered** | `_defuse` prefixes `'`; `test_a_csv_cell_cannot_execute_as_a_formula` (all 6 leaders) |
| 10 | Excel silent truncation at 32,767 (fable) | **answered** | `over_spreadsheet_cell_limit` column; data written whole; test |
| 11 | ``` in an answer breaks the markdown fence (fable) | **partially** | `_fence` fixes the JSON **body** block. But the header interpolates project name / run raw (§4 New-1) — markdown injection remains |
| 12 | Relaxation has nowhere to record at export (fable) | **answered** | recorded in the document at write (`relaxation` turn); export reads through the same locality gate (`_read_store`). Minor: an export that *reads* a remote store under `--store-remote allow` records nothing new (it's a read) |
| 13 | "Must not be silent" names no mechanism (fable/codex) | **prose only** | **The centre of the second finding.** Field exists; nothing surfaces it (§4 New-2) |
| 14 | Three backends guarantee nothing in common (codex) | **answered** | 5 guarantees stated and enforced: unique `(cid,seq)` refused (`_DocumentBackend.append`, Mongo unique index), append-only, `seq` ordering, partial line visible, no concurrent writers |
| 15 | "Owner-only permissions" overclaim (both) | **answered** | `_own` is `0700` best-effort, documented as *not* protection (§6) |
| 16 | `file` default is not a NoSQL DB (fable) | **answered** | said plainly in `FileBackend` docstring and README |
| 17 | CSV can't carry an in-band lossy note (fable) | **answered** | `_json` suffixes + flag column; `test_csv_carries_no_note_row` |
| 18 | Document schema absent (codex) | **answered** | `SCHEMA=1`, header line, `Turn.as_dict`, fixed `CSV_COLUMNS` |

---

## 4. New findings

**New-1 — "must not be silent" is silent on every operator-facing path.** `RunReport.store_errors`'s own docstring (`engine.py:330`) and design §6 say a failed write lands "on stderr" / "a non-zero-marked line on stderr." No code prints it. `grep store_errors` in `cli.py`/`server.py` → only the docstring. `cmd_run` prints relaxations, confirmations, panels, effects… never `store_errors` or `write_errors` (`cli.py:538-560`). `server.Runner.snapshot` omits it too (`server.py:186-205`). Reproduced with the **exact task command** (scratchpad store-root, path length 264 > Windows MAX_PATH 260):

```
state:         finished
(no mention of store/write/error in output)
(no conversation file written at all)   exit 0
```

Every turn failed to write, the whole conversation was lost, and the operator was told `finished` with no signal. "Every conversation stored" and "never silent" both fail together — the exact defect fable-seat named, reintroduced. The CHG's own Evidence block ("38 stored turns") must have been produced on a shorter root than the task's scratchpad; on this path it stores zero, silently. The guard test is misnamed (see §6).

**New-2 — markdown export header injection.** `_markdown` interpolates the project name raw: `f"- Project: **{project.get('name','?')}**"` (`conversations.py:724`). A name containing a newline emits a forged `# heading` and an unbalanced fence outside any code block. `_fence` only guards the JSON body; the header (project name, and `run` path values) is unprotected. Operator-controlled, so lower severity than the mongo bypass — but notable that the concurrent working-tree edit is *already* adding an `_inline()` helper to fix exactly this, i.e. it is a known live defect in the committed code.

**New-3 (minor) — a pre-existing journal with an empty store loses already-answered asks.** `_ask` returns a journalled answer *before* reaching the conversation (`engine.py:576-580`), by design. Correct across a resumed process (the first walk already wrote those turns). But if `--project` is added on a resume whose journal already has answers and whose store is empty, those asks/answers never enter the store. Narrow, but it is a turn that happens in a real (resume) run and is not recorded.

---

## 5. Answers to the driven checks

- **Q2 (any unrecorded turn):** All 6 `_ask` sites pass `conversation=` (`engine.py:1275,1316,1347,1374,1407,1440`); all 4 operator-decision sites (`report.rejections/confirmations/rulings.append`) are each paired with `cfg.conversation.decision(...)`. `serve`'s per-approval re-walks do **not** double-count: `instruction` dedupes by `nth`, `close` deliberately does not (verified: 3 walks → 3 `closed`, 1 `decision` per real approval). Gaps: send-back rework briefs are not a turn kind (their re-asks are recorded), plus New-3.
- **Q6 (behaviour without `--project`):** holds. `_open_conversation` returns `None` when no project (`cli.py:445`), `RunConfig.conversation` defaults `None`, every call is guarded. Full suite: **901 passed, 2 skipped**; the only pre-existing tests touched are two source-text asserts on the `_finish` signature.

---

## 6. Tests: behaviour vs. source text

Most tests drive real behaviour (good): the 1100-turn ordering test, the formula/truncation/fence exports, the round-trip, the resume/re-attach, the half-written-line reader.

**Weak / misnamed:**
- `test_a_failed_store_write_never_fails_a_run_and_is_never_silent` (`:176`) — asserts `write_errors` is populated and that `"store_errors" in RunReport().as_dict()`, i.e. that a **dict key exists**. It never checks the error reaches a human. "Is never silent" is asserted by the presence of a field that is in fact never printed (New-1). This is itself a coarse check answering "safe" about something it did not examine.
- `test_a_uri_that_could_leave_this_machine_is_refused` (`:196`) — the parametrized list omits exactly the bypasses that exist: no `.sock` remote host, no `%2f` remote netloc, no lowercase `replicaset`/`directconnection`. The suite proves the refusals the author already thought of and never probes the gaps.
- `test_direct_connection_is_forced...` (`:224`) — only checks `_hardened` string-appends; blind to the case-insensitivity conflict it creates.

**The two deliberate source-text tests:**
- `test_the_engine_records_the_decisions_the_report_records` (`inspect.getsource(engine)`, `:371`) — **justified.** The four decision sites are on four branches of one gate function; driving all four is awkward and a happy-path test would pass with three unwired. Scanning that each `report.*.append` is followed by a `decision(` call is a reasonable structural guard. It is brittle (proximity of text, not equivalence of condition), but the trade is defensible here.
- `test_the_answering_model_is_recorded` (`inspect.signature(AskJournal.record)`, `:114`) — **justified**, and it isn't purely textual: it also drives a real `ask` turn and asserts `model`/`seat` on the stored turn.

---

## 7. What I could not check, and what I'd need

- **pymongo runtime behaviour.** pymongo is not installed, so I could not observe whether `directConnection=true` actually stops discovery, nor how the driver resolves the `directconnection=false&directConnection=true` conflict `_hardened` produces, nor whether it TCP-dials `remote.evil.sock`. The `.sock`/`%2f` *acceptances* by `local_mongo_uri` are proven regardless of the driver; the downstream connection is asserted from the MongoDB URI spec. To close it: a mongod + a replica set with a remote member and `client.topology_description`.
- **The concurrent working-tree edit.** Something is mid-flight adding `_inline()` (fixing New-2) and left `conversations.py` with a syntax error. I reviewed the committed `1212a91`; if that in-progress work is meant to be part of this change, it needs its own pass — it did not exist when the full suite passed.
