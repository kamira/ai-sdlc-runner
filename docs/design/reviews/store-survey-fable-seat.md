# fable-seat — CHG-20260823-18 deliberation (which database)

Dispatched via the Agent tool on the fable model, against
[`store-survey-brief.md`](store-survey-brief.md). Committed whole and unedited below.

---

# VERDICT: `sound with changes`

The proposition — `file`, `sqlite`, `mongo`, with `sqlite` as the default and TinyDB removed — is the right answer. The survey that carries it, however, contains the repository's own named defect: several check-marks on its recommended winner describe code that has not been written and probes that were never run, and one factual claim about TinyDB is contradicted by TinyDB's own metadata. The proposition survives those corrections; the survey needs them before it is a record anyone should trust.

---

## Recommended set

**`file`, `sqlite`, `mongo` — `sqlite` as the default. TinyDB removed, and `--store tinydb` refuses by the removal's name.**

- **`sqlite` (default)** — stdlib, zero setup, one file at a short path (kills the MAX_PATH hazard that demonstrably lost a whole conversation — reproduced below), a real `UNIQUE(conversation_id, seq)` so it joins Mongo on `enforces_unique_seq = True`, and transactional writes. Conditions, because none of this is free: the backend must actually set `PRAGMA journal_mode=WAL` and a `busy_timeout`, must implement the unique index and the refusal message, and should be **schema-designed so JSON1 is not load-bearing at all** (see Q4). WAL is not SQLite's default; a `✓ WAL` for an unbuilt backend is a name standing in for a constraint.
- **`file` (kept)** — the one format that survives this program being deleted, `cat`/`grep`/diff-able, and the crash-granularity story (`read` reports partial lines, `conversations.py:350-365`) is real and tested. It stops being the default because it has a **reproduced silent-total-loss mode on Windows** (below), and "every conversation stored" cannot default to the backend with that property on a matrix that is half Windows.
- **`mongo` (kept)** — the user said 「提供所有選擇的可能性」, and the locality rules in the current worktree (`local_mongo_uri`, the option allowlist at `conversations.py:100-104`, `_unix_socket` at `:222-237`, forced `directConnection=true`) now answer both round-2 bypasses. pymongo 4.17.0 declares `Requires-Python: >=3.9` (verified from the wheel's METADATA), so R8 holds on paper — though CI still never executes it.
- **`tinydb` (removed)** — see Q1/Q2. The removal should not degrade to `unknown store 'tinydb'` in `backend()` (`conversations.py:527`); it should refuse with the reason and the CHG number, consistent with the module's own doctrine that a missing backend "refuses by name."

---

## The single worst thing in the survey

> **"SQLite meets every requirement and costs nothing — it is in the standard library."** (§2, point 2)

Two of the ten marks behind that sentence are claims nobody examined. The R6 cell says `✓ WAL` — but WAL is an opt-in pragma, and there is no SQLite backend in `conversations.py` to have opted in; the mark scores an unbuilt configuration as already true. The R8 cell honestly says `~ probe JSON1`, and the prose two lines later silently upgrades the whole row to "meets every requirement." The survey's own closing question asks "are any of the `✓` marks claims that have not been examined?" — and the answer is yes, on the winner, in the sentence doing the most persuading. It "costs nothing" in dependencies; it costs a backend with pragmas, a unique index, busy-timeout handling and tests, all of which the table scored as pre-existing. The conclusion is still right — which is exactly why the overclaim matters: a correct verdict resting on an unexamined mark is how this repository's defect log says its defects get made.

---

## Answers to the five questions

**1. Is the proposition right?** Yes: `file` + `sqlite` + `mongo`, `sqlite` default, TinyDB out. I verified the load-bearing claims independently:

- **TinyDB rewrites the entire database per insert — confirmed from its source, not its reputation.** I downloaded the current wheel (tinydb 4.9.0) and read it. `Table._update_table` says so in its own docstring: *"The storage interface used by TinyDB only allows to read/write the complete database data"* — every `insert` is `storage.read()` → mutate → `storage.write(whole_db)`. And `JSONStorage.write` is `seek(0)`, serialize everything, write **in place**, truncate — no temp file, no atomic rename. A crash mid-write corrupts the entire store, every conversation in it, not one line. The survey's `✗ R2 / ✗ R6` are true and now examined.
- **The MAX_PATH hazard is real — reproduced on this machine.** `FileBackend` on a ~240-character root dies with `FileNotFoundError: [WinError 3] 系統找不到指定的路徑` at `conversations.py:299` (`self.root.mkdir`), exactly the misleading-error shape `ID_CHARS`'s comment (`conversations.py:77`) and defect-log line 544 record. Round 2's worst finding — a `finished` run with zero turns stored — came from this path.
- **SQLite json_extract works here**: Python 3.11.9 / SQLite 3.45.1, `json_extract('{"a": 5}', '$.a') -> 5`. But see Q4 — it shouldn't matter.

**2. Remove or deprecate?** **Remove.** It shipped hours ago with zero users and zero data — deprecation is a cost with no beneficiary. More to the point, this repository's own doctrine decides it: a deprecation warning on a store that can lose every conversation to one interrupted write is "must not be silent" naming a mechanism that fires *after* you chose the trap. The design's backend rule is "refuses by name"; apply it: `--store tinydb` should refuse with the reason and the change id, not vanish into `unknown store`. "We shipped it" is not an argument, and neither is its mirror, "removal looks bad."

**3. Is SQLite an honest answer to 「寫到 nosql 的 db 中」?** Yes, **with the same admission the file backend already makes.** `FileBackend`'s docstring (`conversations.py:293-295`) names its own substitution: "The user asked for a NoSQL DB and this is not one… the honest thing is to name that." SQLite gets the identical treatment: a relational engine by name, a document store in the behaviour this code needs — one JSON document per turn, keyed by `(conversation_id, seq)`, whole-document reads. "NoSQL" here is a name; the constraint behind it is nested-JSON document storage with no schema migration burden, and SQLite meets the constraint. The user's current request — survey, then deliberate on what *fits* — supersedes the literal word. What would be dishonest is silence; what the file backend proved is that naming the substitution passes review.

**4. Is the JSON1 caveat real, and how to find out?** It is real but **it should be made irrelevant, which is better than either probing or testing.** Every query this module performs — rows by `conversation_id` ordered by `seq` (`_rows`), headers by `project_id` (`conversations`), header rows (`seq = -1`) — needs only plain columns. Store the turn as serialized JSON in a `TEXT` column and put `conversation_id`, `project_id`, `seq` in real columns, and no `json_*` function is ever load-bearing; JSON parsing happens in Python exactly as it does for the file backend today. Then: if any `json_*` call is nonetheless used, probe at connect and refuse by name (the module's existing doctrine), **and** put a probe test on the CI matrix so the four cells answer empirically — Python 3.9's bundled Windows SQLite predates 3.38, where JSON functions became default-on, so 3.9×Windows is precisely the cell that cannot be answered from a 3.11 machine. Do both; but a schema that doesn't ask the question beats both.

**5. Which marks were never examined?** Four, plus one requirement written in the incumbent's image:

- **TinyDB R8 `✓` is false for the current release.** tinydb 4.9.0's METADATA: `Requires-Python: <4,>=3.10`. The project's CI matrix includes 3.9 (`.github/workflows/ci.yml:31`). A 3.9 user silently resolves an older 4.8.x. Nobody probed this — tinydb isn't even installed here.
- **"Unmaintained-ish; effectively a toy" — the first half is contradicted by evidence.** 4.9.0's metadata: `Development Status :: 5 - Production/Stable`, classifiers through Python 3.14, current packaging (Metadata-Version 2.4). Actively released. The *right* objection — whole-file rewrite, verified above — needed no slur, and an unexamined slur beside a verified defect teaches readers to discount both.
- **SQLite R6 `✓ WAL`** — scores a pragma no code sets. See "worst thing."
- **Mongo R8 `✓`** — pymongo is not installed here and CI's backend tests skip it (design §3 admits this); the version claim now checks out (4.17.0 allows ≥3.9), but "runs on the matrix" has never once been observed.
- **R6's wording is the file backend describing itself.** "A half-written turn is *reported* rather than dropped" is JSONL's crash behaviour promoted to a requirement. Under SQLite a torn write **cannot be observed** — the transaction rolls back and the unacknowledged turn atomically vanishes, which is *stronger*, yet fails R6 as literally worded. The real requirement is "no acknowledged turn is lost and no torn state is silently readable." As written, R6 is a coarse ruler that would mark the better backend wrong.

---

## Further findings

1. **A requirement the table omits: two runners, two conversations, one store.** The design promises one writer *per conversation* (§3), not one runner per machine. `FileBackend` tolerates concurrent runners on different conversations for free (separate files). Any single-file backend must face it: TinyDB loses data outright (read-modify-write over the whole file); SQLite needs `busy_timeout` plus retry or it throws `SQLITE_BUSY` into `_guarded`, landing every turn in `write_errors`. Not a blocker — but the SQLite backend's spec must name it, or the survey's "no concurrency requirement" line quietly deletes a scenario the shipped default supports today.
2. **The survey never mentions the in-place fix for MAX_PATH** — Windows extended-length paths (`\\?\` prefix on an absolute path) or shortening the layout. It treats the hazard as intrinsic to `file` when it is a fixable implementation defect. This doesn't change the default recommendation (SQLite wins on constraints, not just paths), but a survey that uses a fixable bug as a structural argument is leaning on it. If `file` is kept — and it should be — the hazard should be fixed or made a loud refusal regardless, because "kept for inspectability" cannot mean "kept with a known silent-loss mode." (Codex round-2 finding 4 also stands for `file`: no `fsync`, so power-loss durability is weaker than the module's "durable at the moment the turn occurs.")
3. **One candidate the survey missed: MontyDB** (`montydb` — pure-Python, MongoDB-API-compatible, embedded, can even back onto SQLite). It is the literal answer to "an embedded NoSQL database with the API the user named." It loses anyway — small project, sparse maintenance, the UnQLite objection ("a bug here would be ours to fix") applies in full — but a survey claiming completeness should have had the row, because it is the one candidate a "NoSQL by name" advocate would reach for. Nothing else missing beats SQLite: `shelve`/`dbm` are pickle-bound (ZODB's objection), `sqlitedict` is a dependency wrapping what the stdlib already gives.
4. **The archival argument for `file` half-applies to SQLite too, and the survey doesn't say so.** §3 credits `file` as "the one format that survives this program being deleted." An `.sqlite` file is readable by the `sqlite3` CLI on every platform and the format is famously stable (the Library of Congress lists it as a recommended archival format). The genuine `file`-only virtues are `grep`/`tail -f`/git-diffability — real, and sufficient to keep it — but the survey's strongest pro-file sentence is broader than the truth.
5. **Requirements R1–R5, R7, R10 trace correctly to the code.** I checked each against `conversations.py` rather than the survey's summary: R3 = `read` + `export_conversation` (`:791`), R4 = `conversations`/`projects` + `cmd_conversations` (`cli.py:360`), R5 = work-order bodies through `ask` (`:695`), R7 = `backend()` default `file` with stdlib only, R10 = design §6's "as sensitive as the journal." No invented requirement found; the omissions are finding 1 and the R6 wording above. The current worktree's tests pass: `tests/test_conversations.py` — 58 passed.

---

## What I could not check, and what I would need

- **TinyDB and pymongo behaviour at runtime** — neither is installed; I read TinyDB 4.9.0's source from its wheel (conclusive for the rewrite claim) and only pymongo's METADATA. Actual topology-discovery and `directConnection` behaviour still needs a live mongod fixture, as both round-2 seats already said.
- **JSON1 on the other three CI cells** — verified only on this machine (3.11.9 / SQLite 3.45.1). The 3.9×Windows cell is the one in doubt and only CI can answer it; my Q4 recommendation makes the answer non-load-bearing.
- **TinyDB's maintenance cadence beyond metadata** — no network access to the repository's commit history; the "actively released" counter-evidence is from the current wheel alone.
- **Whether `pip install tinydb` on Python 3.9 resolves 4.8.x cleanly** — inferred from `Requires-Python`, not executed on a 3.9 interpreter.
- **Power-loss durability for any backend** — needs the killed-process/forced-exit harness codex-seat requested in round 2; nothing here changes that debt.
