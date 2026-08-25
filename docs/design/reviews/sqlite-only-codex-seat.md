# codex-seat — CHG-20260823-19 deliberation (SQLite only)

Dispatched via `codex exec --sandbox read-only` on
[`sqlite-only-brief.md`](sqlite-only-brief.md). Committed whole and unedited below.

---

# VERDICT: `not sound`

The ruling is clear and should stand: remove MongoDB and TinyDB, retain files only for server configuration, and store both conversations and model configuration records in SQLite. The proposition reaches that broad destination, but its interpretation and schema contradict the current code’s safety invariants. Those are design errors, not implementation details.

## 2. Reading of the new requirements

My reading is:

1. `file` remains a representation for server configuration, not a selectable conversation backend.
2. Model registry records move from `models.json` into SQLite even though they are configuration records; that is an explicit exception/specialization supplied by the third ruling.
3. Files required to locate or initialize SQLite may remain server configuration, because the database cannot supply its own location before it is opened.

Section 1’s **hand-written versus machine-maintained** distinction is not supported as the governing rule.

- `runner.yaml` is read but never written by `src/`; [cli.py:34](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:34) supports the proposition on that file.
- `models.json` is read during server startup at [cli.py:687](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:687) and written after a console `/models` request at [server.py:558](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:558).
- `settings.json` is also machine-written: `runner settings` calls `settings_mod.save` at [cli.py:264](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:264), and the actual write is [settings.py:188](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/settings.py:188).

Therefore “machine-maintained” does not distinguish `models.json` from `settings.json`. `settings.json` may remain a file, but because it is server configuration and needed during bootstrap—not because it is hand-written.

## 3. Single worst thing

> “`reach` is a **stored column**, not recomputed on read.”

This directly reverses the model registry’s existing safety rule.

[models.py:77](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:77) says reach is “Computed, never declared.” `Model.reach` recomputes it from `transport` and `endpoint` at [models.py:124](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:124). Most decisively, `save()` deliberately removes both `reach` and `leaves_this_machine` because storing them would “let a stale label outlive the truth” at [models.py:279](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:279).

The proposition asserts the opposite without identifying any transaction constraint that guarantees `endpoint` and `reach` can never disagree. `reach` must remain derived during validation/read, or be database-generated from an equivalently exact and maintained rule. A normal writable column is unsafe.

## 4. Answers to the five questions

### 1. Is §1’s distinction right, and is `settings.json` on the correct side?

No. The correct line is not hand-written versus machine-maintained. It is:

- server bootstrap/configuration files remain files;
- conversation records and model registry records live in SQLite.

`settings.json` is on the correct storage side, but for the wrong stated reason. It is programmatically edited and saved, just like the model registry. It remains a file because it is server configuration loaded independently of the conversation/model store and may participate in locating or governing that store.

The proposition should state explicitly whether “server config” includes `settings.json`, `runner.yaml`, the SQLite path, and any migration/version settings. It should not infer a new authorship taxonomy from the ruling.

### 2. Same SQLite file or separate files?

Use the same SQLite file unless a concrete recovery, retention, or permissions requirement demands separation.

A second database adds:

- a second bootstrap location;
- separate migrations and backups;
- the possibility that conversations and the model configuration used for them are captured at inconsistent points.

Registry writes and turn writes are short transactions. WAL plus bounded busy handling should be enough for this workload. Merely saying “contention” does not establish that a second file is safer.

However, the shared file needs separate transactional APIs and failure contracts. Conversation writes are deliberately non-fatal but reported at [conversations.py:750](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:750). A registry edit must not receive a success response unless its database transaction committed. Those two policies cannot be hidden behind one coarse “store write” abstraction.

### 3. Is removing `file` as a conversation store right?

Yes. The person settled this, and the implementation should remove it as a selectable backend.

What is lost:

- direct `cat`, `grep`, `tail -f`, and git diff;
- isolation of corruption to one conversation file;
- tolerance of separate conversations naturally writing separate files.

Export replaces archival inspection and interchange, but it does not replace live `tail -f`, filesystem diffing, or per-conversation failure isolation. It is a mitigation, not an equivalent replacement.

Current dependencies that must be changed include:

- `BACKENDS = ("file", "tinydb", "mongo")` at [conversations.py:68](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:68).
- `file` is the CLI default at [cli.py:432](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:432).
- `backend()` constructs `FileBackend` at [conversations.py:522](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:522).
- Conversation tests instantiate `FileBackend` directly; `rg -n "FileBackend|--store|backend\\(" src tests` exposes these call sites.

The removal is intentional, but it is not localized to deleting one class. CLI compatibility, tests, documentation, defaults, export behavior, and explicit refusal messages all need migration.

### 4. Is the proposed schema correct?

No.

Conversation facts actually stored are:

- header: `schema`, `conversation_id`, `project: {id, name}`, and arbitrary `run`, at [conversations.py:568](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:568);
- turn: `seq`, `kind`, `at`, plus arbitrary flattened body fields, at [conversations.py:248](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:248).

Model facts actually persisted are:

- `id`, `vendor`, `name`, `transport`, `command`, `endpoint`, `key_env`, and `note`, from [models.py:107](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:107);
- not `reach` or `leaves_this_machine`, per [models.py:279](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:279).

Columns that are guesses or insufficiently specified:

- `conversations.opened_at`: no header field supplies it. An `opened` turn has an `at`, but the proposition does not say it is derived from that turn.
- `models.updated_at`: no such value exists in the current registry or save path.
- `models.reach`: not merely a guess; it contradicts the current invariant.
- `models.body_json`: its exact contents are unspecified. If it contains the saved model, the separately stored `transport`, `endpoint`, and `key_env` create two sources of truth.
- `turns.body_json`: must be defined as only the arbitrary body, excluding `seq`, `kind`, and `at`; otherwise it also creates duplicate sources of truth.
- `run_json`: appropriate in shape, but canonical encoding and round-trip behavior are unspecified.

Missing explicit model representation:

- `vendor`;
- vendor model `name`;
- CLI `command` as an ordered argument list;
- `note`.

Those can live in one canonical `body_json`, but the schema must say so and must validate through `_model_from()`/`validate()` on every read and import. Do not duplicate selected fields unless a query requirement justifies them and consistency is enforced.

### 5. Names standing in for constraints and claims about nonexistent code

Names standing in for constraints:

- `reach` as a stored column: the name does not guarantee agreement with `endpoint`.
- `WAL`: does not specify connection setup, checkpoint behavior, or whether the returned pragma was checked.
- `busy_timeout`: does not define its value, the tolerated blocking interval, retry behavior, or what the operator sees after exhaustion.
- `synchronous`: the proposition says it will be “chosen and documented” but does not choose it.
- “one-shot import”: does not define atomicity, idempotence, collision handling, partial failure, merge versus replace, or whether a path is one JSONL file or an existing store directory.
- “refuses rather than guesses when shapes do not match”: no accepted shapes or validation boundary are specified.

Claims about code that does not exist:

- SQLite uniqueness enforcement.
- WAL concurrency behavior.
- busy-timeout handling.
- the selected durability boundary.
- SQLite model storage.
- `runner import`.
- automatic handling of both `models.json` and JSONL conversations.
- explicit CHG-based refusals for removed backends.

These are acceptable as proposed work only when converted into testable acceptance criteria. They cannot yet be cited as guarantees.

## 5. Further findings

### Bootstrap is acknowledged but not actually designed

The proposition correctly notices the circularity, but “`--store-root` and the config file answer that” is incomplete.

Today `load_config()` reads `runner.yaml` at [cli.py:34](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:34), while conversation flags are parsed directly and `_open_conversation()` consumes `args.store_root` at [cli.py:447](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:447). The proposition does not identify a current config key that supplies the SQLite path or precedence among CLI, `runner.yaml`, defaults, and server token directory.

Required ordering should be explicit:

1. Parse CLI.
2. Read file-based bootstrap configuration.
3. Resolve one absolute SQLite path using documented precedence.
4. Open and migrate SQLite.
5. Load the model registry.
6. Build dispatch/session objects.

The `serve` path currently opens the conversation at [cli.py:654](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:654), then loads `models.json` at line 687 and calls `load_config()` at line 694. Moving models into SQLite requires deliberately reordering this sequence.

### Registry update semantics are incomplete

`Registry` supports both `add` and `remove` at [models.py:224](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:224), while the shown server route only adds and then rewrites the whole registry at [server.py:558](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:558). The SQLite design must say whether edits are insert-only, upsert, replace-all, or support deletion. `model_id PRIMARY KEY` alone does not answer that.

### Schema versioning is missing

The existing conversation header carries `SCHEMA = 1` specifically to avoid guessing stored shapes at [conversations.py:51](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:51). A SQLite database also needs a database schema/version mechanism and ordered migrations. A per-conversation `schema` column is not a substitute for database schema versioning.

### Import must preserve existing semantics exactly

JSONL reads:

- report malformed/partial lines;
- sort turns numerically;
- report duplicate sequences.

See [conversations.py:343](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:343) and [conversations.py:534](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:534).

Import cannot simply pass the assembled document into SQLite: SQLite’s unique key would refuse duplicates that the old reader merely reports. The migration policy must say whether the entire conversation is refused, partial lines are refused, or anomalies are imported into explicit diagnostic records. “Nothing is deleted” does not answer whether a failed import leaves a partially populated database.

### File permissions remain unnamed

The old file backend attempts `0700`, while admitting that this is not meaningful protection on Windows at [conversations.py:302](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:302). The proposition discusses registry protection but provides no acceptance criterion for the SQLite file, `-wal`, and `-shm` files. All three may contain sensitive conversation/model data.

## 6. What I could not check

- No SQLite backend, migration command, or revised tests exist, so their runtime behavior cannot be checked.
- `pytest -q` could not start because the read-only environment has no usable temporary directory; failure occurred before collection. A writable temporary directory is required.
- I could not run concurrency, killed-process, power-loss, WAL recovery, checkpoint, backup, corruption, or import-interruption tests.
- I could not verify behavior across the declared Python/OS matrix from this seat.

To close these gaps, I would need a writable isolated temporary directory and an implementation with tests covering schema migration, exact JSON round trips, concurrent registry/turn writes, duplicate imports, partial JSONL input, commit failure visibility, WAL reopen/recovery, and the supported Python/Windows/Linux cells.
