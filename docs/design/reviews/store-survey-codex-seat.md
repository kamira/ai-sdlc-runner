# codex-seat — CHG-20260823-18 deliberation (which database)

Dispatched via `codex exec --sandbox read-only` on
[`store-survey-brief.md`](store-survey-brief.md). Committed whole and unedited below.

---

# 1. VERDICT

`not sound`

The correct core decision is SQLite, but the proposition retains two storage backends without a requirement that justifies their continuing implementation and security burden. “Someone may already run MongoDB” is not a project requirement.

# 2. Recommended set

- **Default and sole writable backend: `sqlite`.**
- **JSONL: export/interchange format, not a second persistence backend.**
- **Remove TinyDB as a writer.** If already-created stores matter, provide a bounded one-shot TinyDB-to-SQLite importer or legacy read command.
- **Remove MongoDB from the core conversation store.** Reintroduce it only under a separate CHG backed by an actual multi-process, remote, or shared-store requirement.

Recommended SQLite shape:

- `conversations(conversation_id PRIMARY KEY, project_id, project_name, schema, run_json, ...)`
- `turns(conversation_id, seq, kind, at, body_json, PRIMARY KEY(conversation_id, seq))`
- foreign key from turns to conversations
- explicit transactions
- explicit `PRAGMA journal_mode=WAL`
- an explicitly chosen and documented `PRAGMA synchronous` level
- application-side JSON validation; JSON1 is optional unless an actual nested-field query is introduced
- a schema/version migration policy
- killed-process and reopening tests on Windows/Linux and Python 3.9/3.13

# 3. Single worst thing in the survey

> “**SQLite meets every requirement and costs nothing** — it is in the standard library.”

This is the repository’s recurring coarse-check defect.

`sqlite3` being importable proves neither the proposed schema nor the persistence guarantees. WAL is not automatically enabled, `synchronous` is not specified, no killed-process test exists, no migration policy exists, no maximum-value test exists, and the four-cell CI matrix has not exercised an implementation because there is no implementation. The survey converts a product name into evidence.

“Costs nothing” is also false in the relevant sense: SQLite removes a package and daemon burden, but still costs schema design, transactions, migrations, corruption handling, backup behavior, and tests.

# 4. Answers to the five questions

1. **Is the proposition right?**

   No. Its choice of SQLite and rejection of TinyDB are right; its recommended three-backend set is wrong.

   The code needs an ordered, locally durable event log with project lookup and export. Its backend interface is only five operations: open, append, read, list conversations, and list projects ([conversations.py:265](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:265)). SQLite satisfies these directly and gives a real `(conversation_id, seq)` constraint.

   JSONL’s human readability is an export requirement, not a reason to maintain a second consistency implementation. MongoDB’s nested queries, topology, and scale answer no stated need. Worse, keeping Mongo requires maintaining the substantial URI security boundary at [conversations.py:140](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:140), after prior versions repeatedly misclassified remote destinations as local.

2. **Remove TinyDB, or deprecate it?**

   Remove it from writable backend selection now. It shipped only hours ago and there is no established compatibility population.

   Preserve data honesty with a legacy importer/reader if any TinyDB file exists; do not retain a backend indefinitely merely to read it. Silent deletion of existing data would be wrong, but continued production use is not required for migration.

   TinyDB really does rewrite the complete database. Its `Table._update_table` reads the entire storage and calls `storage.write(tables)` after each insertion; `JSONStorage.write` seeks to zero, serializes the whole state, writes, fsyncs, and truncates. That verifies the survey’s central write-amplification claim from upstream source, not inference: [TinyDB table implementation](https://raw.githubusercontent.com/msiemens/tinydb/master/tinydb/table.py), [TinyDB JSON storage](https://raw.githubusercontent.com/msiemens/tinydb/master/tinydb/storages.py).

   An interruption during in-place replacement can leave the one JSON document unparsable. The `fsync` improves persistence after completion; it does not make the replacement atomic.

3. **Is SQLite an honest answer to “NoSQL DB”?**

   No, if advertised as a NoSQL database. Yes, as the correct conversation store.

   SQLite is a relational database storing JSON text. A `body_json` column makes it document-shaped at the application boundary; it does not turn SQLite into a NoSQL product. The honest wording is:

   > “Conversations are stored locally in SQLite; turn bodies are preserved as JSON documents.”

   The choice should be governed by constraints, not the category word “NoSQL.” The current file backend already acknowledges this distinction at [conversations.py:291](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:291). SQLite must receive the same honesty.

4. **Is Python 3.9 JSON1 availability a real risk? How should it be checked?**

   It is a real portability caveat only if the implementation actually depends on JSON1. It should not.

   The code never requires database-side nested JSON filtering. It queries by conversation, project, and sequence. Those should be ordinary indexed columns; `body_json` can be encoded and validated with Python’s `json` module. That works without `json_extract`.

   On this machine I ran:

   ```text
   Python 3.11.9
   SQLite 3.45.1
   select json_extract('{"a":2}', '$.a') => (2,)
   select json_valid('{"a":2}') => (1,)
   ```

   SQLite has built JSON functions in by default since 3.38.0; older builds made JSON1 compile-time optional. [SQLite documents that distinction](https://sqlite.org/json1.html).

   If a future requirement genuinely needs JSON1, do both:

   - execute the exact required SQL during backend initialization and refuse with a precise error if unavailable;
   - exercise that probe in all four CI cells.

   CI alone describes tested builds, not an arbitrary user’s interpreter. Import-time probing is also too broad: probe when opening the SQLite backend.

5. **What is a name standing in for a constraint? Which checks are unexamined?**

   Several scoring marks are unsupported:

   - **SQLite R6 “✓ WAL.”** WAL is a named mechanism, not proof of the promised crash semantics. No SQLite backend, transaction boundary, `synchronous` setting, real killed-process test, or reopen test exists.
   - **SQLite R2 “✓.”** This becomes true only with the proposed primary/unique keys and transactional append. “SQLite” alone does not create them.
   - **SQLite R5 “✓ JSON col.”** SQLite has no dedicated JSON type; it stores JSON as text. The application must define validity and encoding behavior.
   - **SQLite R8 “~ probe JSON1.”** No implementation has run on the matrix. Compatibility is unevaluated, not partly established.
   - **JSONL R2 “✓.”** The code assumes one writer but does not enforce it. `FileBackend.append` checks existence and opens append mode without a lock ([conversations.py:336](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:336)).
   - **JSONL R6 “~ line-level.”** Closing the handle addresses Python buffering, but there is no `fsync`, directory sync, or killed-process writer test. The prior review already identified this overclaim.
   - **TinyDB R2 “✓ full rewrite.”** This mixes two constraints. It is logically append-only through this wrapper, but physically rewrites the store. Rewrite behavior belongs under durability/write amplification, not “append-only.”
   - **Mongo R6 “✓.”** Durability depends on server configuration, write concern, journal settings, and topology. None is constrained by [MongoBackend._insert](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:498).
   - **Mongo R8 “✓.”** The round-two reviews explicitly say PyMongo and Mongo behavior were not executed. A driver’s declared compatibility is not this backend’s verified behavior.
   - **R10 generally.** “At rest” is not a binary mark. Best-effort `chmod(0700)` is explicitly not protection on Windows ([conversations.py:302](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:302)).

# 5. Further findings

## The requirements table contains classifications and preferences presented as requirements

- **R9** — “No licence or operations burden the user did not ask for” — has no source and no testable threshold. It needs separation into concrete constraints: no required service, no non-stdlib dependency for the default, supported licence policy, and bounded maintenance surface.
- **R10** is a sensitivity statement, not a storage requirement. The actual requirement should say what protection is demanded: OS-user confidentiality, encryption at rest, or merely an explicit disclosure that none is provided.
- **R2** combines two different matters: logical immutability and the single-writer operating assumption. The current code offers no writer ownership or locking mechanism.

## Material requirements are omitted

The backend choice also needs explicit requirements for:

- atomic conversation creation and atomic turn append;
- duplicate `(conversation_id, seq)` refusal;
- exact durability boundary: process crash versus OS/power loss;
- store failure visibility and the existing rule that archival failure must not stop the run;
- schema evolution and migrations;
- recovery behavior after corruption;
- backup/copy behavior while the store is open;
- maximum supported turn size;
- deterministic preservation of all JSON values accepted by the application.

These are already implicit in code and prior findings. For example, `Conversation._guarded` deliberately catches every write failure and reports it on stderr ([conversations.py:750](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:750)). A candidate database must fit that failure contract, yet the table never scores it.

## The TinyDB maintenance claim is wrong

> “Unmaintained-ish; effectively a toy at any size”

The write-path objection is valid, but this supporting claim is not. TinyDB describes itself as mature and in maintenance mode, supports Python 3.8–3.13, and has recent releases. [Its upstream project states that status directly](https://github.com/msiemens/tinydb). “Maintenance mode” is not “unmaintained.”

The survey should reject TinyDB because its persistence algorithm conflicts with this append log, not through a dismissive maintenance label.

## The MAX_PATH hazard is real, but stated too absolutely

This machine reports:

```text
HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 0
```

The working directory is already 92 characters long. The file backend then adds the store root, a 32-character project ID, a 32-character conversation ID, and `.jsonl`. The previous round reproduced complete write loss at a 264-character path.

Windows still imposes the 260-character limit unless both the OS policy and application opt-in conditions are satisfied. [Microsoft documents both conditions](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation?tabs=cmd).

However, “SQLite has no path-length hazard” is too strong. A SQLite filename can itself exceed the effective limit. SQLite materially reduces the risk from a deep per-project/per-conversation tree; it does not abolish Windows path rules.

## JSON1 is not needed by the stated workload

The survey lets the attractive phrase “document store” pull JSON query functions into the design. The current operations query metadata and return the complete turn body. Ordinary indexed columns plus opaque validated JSON text are simpler and compatible with older SQLite builds.

## No missed candidate is better than SQLite here

I found no omitted database that beats SQLite against the actual workload.

`dbm`, LMDB, RocksDB, and similar key/value engines push indexes, transactions across header/turn records, schema handling, and recovery into this project. DuckDB optimizes a different workload. SQLCipher would become relevant only if R10 were rewritten as an encryption-at-rest requirement; currently it is not.

The genuinely missed option is architectural: **one SQLite backend plus JSONL export**, instead of treating every useful representation as a separately writable store.

# 6. What I could not check

- TinyDB is not installed locally. I verified its rewrite behavior from current upstream source, not by tracing an installed package.
- PyMongo and a MongoDB server are unavailable, so I could not execute write-concern, journal, topology, or failure behavior.
- The sandbox provides no writable temporary directory. `pytest -q tests/test_conversations.py` failed before collection with `No usable temporary directory`; no test assertion ran.
- I could not implement or run a SQLite prototype, killed-process test, power-loss test, corruption recovery test, or concurrent backup test in this read-only seat.
- Only Python 3.11/SQLite 3.45.1 was available locally. I could not execute Python 3.9/3.13 or the Linux cells.

To close those gaps: a writable isolated directory, the four declared CI cells, a SQLite prototype with explicit pragmas and schema, forced-process termination/reopen tests, and documented expected behavior for OS/power loss and backups.
