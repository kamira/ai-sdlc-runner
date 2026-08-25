# Proposition — SQLite only, files for server config, and the model registry moves in

- Project: ai-sdlc-runner
- Change: CHG-20260823-19 (proposed)
- Decided by: the user, ruling on the split in
  [CHG-20260823-18](store-survey.md) —
  *「只留 sqlite + file，移除 mongo 和 tinydb / file 只作為 server 的 config 才處理 /
  sqlite 內容不僅限於紀錄，也包含 model 模型配置的紀錄儲存」*
- Sent back for deliberation by the user: *「以上敘述交由審議席再審議並提供判斷」*

## 0 · What was ruled, and what that retires

The [previous deliberation](store-survey.md) split: codex-seat said `sqlite` only, fable-seat said
`file` + `sqlite` + `mongo`. A split does not pass, so it went to a person. It has been answered:

1. **`mongo` and `tinydb` are removed.**
2. **`file` is handled only as server config**, not as a conversation store.
3. **SQLite holds more than the conversation log** — the **model configuration records** go in too.

**This retires R11.** The user set 「提供所有選擇的可能性」 when the store was first specified, and
has now, with the costs visible, withdrawn it. That is recorded rather than quietly dropped: R11 was
the requirement whose absence caused the split, and it is being removed by the person who set it,
which is the only authority that can.

That also settles what the seats disagreed about. **codex-seat's recommendation is the one the
person chose**, and this proposition should say so plainly rather than presenting the outcome as a
fresh idea.

## 1 · Where the two instructions appear to collide

> *「file 只作為 server 的 config 才處理」* — files are handled only as server config
>
> *「sqlite 內容不僅限於紀錄，也包含 model 模型配置的紀錄儲存」* — SQLite holds the model
> configuration records too

**The model registry is server configuration.** Read literally, the first sentence keeps it in a
file and the second moves it into SQLite.

Revision 1 resolved that by inventing a principle — *hand-written vs machine-maintained* — and
**both seats refused it**, for the same reason and with the same evidence: `settings.json` is
machine-written too (`cli.py:270` calls `settings_mod.save`, which writes at `settings.py:188`), so
the line does not distinguish the registry from settings at all. Revision 1's own footnote calling
settings.json *"the awkward one"* was the tell that the principle was not carrying the decision.

fable-seat put the correction most sharply: **the collision does not need a principle, because the
ruling resolves it itself.** The second sentence names the model registry explicitly, and a specific
instruction carves out of a general one. Inventing a rule creates exactly the hazard this document
warns about — a rule that gets applied later to files nobody ruled on.

So the line is the ruling's own:

- **server config stays a file** — including `settings.json`, because it is config and is read
  before any store exists, not because of who types it;
- **the model registry moves**, because the ruling says so by name;
- **records live in SQLite.**

If a general principle is ever needed for a file the ruling did not name, fable-seat's is the
accurate one: *written by the running server while it serves* (`server.py:565` writes `models.json`
on a console POST) versus *written outside any run* (`settings.json`, by a short human-driven
command). It is offered as a tie-breaker for future cases, not as the reason for this one.

The table below is therefore an outcome, not a derivation:

| Stays a file | Moves into SQLite |
|---|---|
| `runner.yaml` — `agent_command`, how an ask is dispatched | `models.json` — the model registry |
| `settings.json` — review seats, high-risk bypass, vouched commands | the conversation log (already) |

The evidence that *is* load-bearing, and which both seats verified independently: **nothing in
`src/` ever writes `runner.yaml`** — `load_config` at `cli.py:36` only reads it — and
`server.py:565` is the sole production writer of `models.json`.

## 2 · What is proposed

### The store

- **`sqlite` is the only conversation store.** `--store` keeps one value.
- **`mongo` removed**, and with it `local_mongo_uri`, the option allowlist, `_unix_socket`,
  `_hardened`, `MONGO_OPTIONS`, `LOOPBACK_HOSTS` and `--store-uri` / `--store-remote`. That is the
  entire surface that produced a locality bypass in round 2 and a second one on re-reading.
- **`tinydb` removed** — `Requires-Python: <4,>=3.10` against a 3.9 floor, and a write path that
  rewrites the whole database per turn.
- All three — including **`file`** — refuse **by name**, with the change id, rather than falling
  into `unknown store`. Revision 1 listed only mongo and tinydb, and fable-seat pointed out that
  `file` is the one operators actually used, **because it was the default** (`cli.py`:
  `default="file"`).
- **And the operator who typed nothing is the sharper case.** Their store silently changes, and any
  existing `.jsonl` tree at the default root stops appearing in `runner conversations` — old data
  made invisible with no message. That is the same "must not be silent" class as the round-2 finding
  where a whole conversation was lost under a `finished` run. So the sqlite backend **notices an
  existing file-store tree at the default root and says so**, pointing at `runner import`.

### The schema

```sql
-- Set on EVERY connection, not once at create time. Two of the three are per-connection state,
-- and the third is the file's. A pragma named in a design and not executed on the connection that
-- needs it is a name standing in for a constraint -- which is what happened to the foreign key in
-- revision 1 of this block.
PRAGMA journal_mode = WAL;        -- the file's; survives reopen
PRAGMA foreign_keys = ON;         -- per connection, OFF by default -- see below
PRAGMA busy_timeout = 5000;       -- ms; the server writes the registry while a run appends turns
PRAGMA synchronous = NORMAL;      -- chosen, not deferred -- see the boundary it buys, below

CREATE TABLE conversations (
  conversation_id TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL,
  project_name    TEXT NOT NULL,
  schema          INTEGER NOT NULL,
  run_json        TEXT NOT NULL,
  opened_at       TEXT NOT NULL);   -- minted at open; on import, taken from the OPENED turn's `at`

CREATE TABLE turns (
  conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
  seq             INTEGER NOT NULL,
  kind            TEXT NOT NULL,
  at              TEXT NOT NULL,
  body_json       TEXT NOT NULL,    -- ONLY the body: never seq/kind/at, or there are two truths
  PRIMARY KEY (conversation_id, seq));

CREATE TABLE models (
  id        TEXT PRIMARY KEY,
  vendor    TEXT NOT NULL,
  name      TEXT NOT NULL,
  transport TEXT NOT NULL,
  command_json TEXT NOT NULL DEFAULT '[]',   -- argv as a list; never re-split by a shell
  endpoint  TEXT NOT NULL DEFAULT '',
  key_env   TEXT NOT NULL DEFAULT '',        -- the NAME of an env var. Never a key.
  note      TEXT NOT NULL DEFAULT '');
```

**`reach` is not a column, and revision 1 proposing one was the worst thing in this document.** Both
seats named it. `models.py` says *"Computed, never declared"*, and `save()` strips `reach` and
`leaves_this_machine` with the comment *"both are computed; storing them would let a stale label
outlive the truth."* `reach` is what the console shows to say **whether a model leaves this
machine** — persisting it means an endpoint edit that forgets to recompute leaves the console
showing "local" about something external. Two lines away, revision 1 said the `key_env` property
"must survive the move intact" while killing the module's other safety property.

Round-tripping the registry shows exactly what is persisted, and it is these eight fields:

```
persisted keys: ['command', 'endpoint', 'id', 'key_env', 'name', 'note', 'transport', 'vendor']
stripped      : ['leaves_this_machine', 'reach']
reach recomputed on load: ['local', 'external']
```

And a `reach` column would not merely be dead — it would be a **refusal trigger**, because
`_model_from` rejects unknown fields with this repository's own doctrine in the message:

```
model 'x' has field(s) this runner does not know: ['reach'].
Ignoring them would let a setting look configured and do nothing.
```

`updated_at` is also gone. Nothing in `models.py` produces or reads one; revision 1 invented it.

**The foreign key was decorative, and that is checkable in three lines.** `PRAGMA foreign_keys` is
OFF by default, **per connection**:

```
foreign_keys default -> 0
orphan turn accepted -> [('ghost', 0)]
```

A `REFERENCES` clause with the pragma unset enforces nothing. Revision 1 named WAL, `busy_timeout`
and `synchronous`, and not `foreign_keys` — putting a name standing in for a constraint inside the
schema block of a document whose closing question asks the reader to find one. fable-seat found it.

**`PRAGMA synchronous = NORMAL`, and here is the boundary it buys**, because codex-seat is right
that "durable" is a word until somebody names it: under WAL, `NORMAL` is safe against **process
crash** — a killed runner loses nothing already committed — and under **power loss** the most recent
transactions may roll back. `FULL` would close that at a per-turn fsync. `NORMAL` is chosen because
the store is an archive whose failure is explicitly non-fatal to a run, and the run's own journal is
the thing a resume reads.

**`PRAGMA user_version` carries the database schema version**, and migrations are ordered and
explicit. The per-conversation `schema` column says what shape a *document* is; it is not a
substitute for versioning the database, which codex-seat correctly separated.

- `PRIMARY KEY (conversation_id, seq)` — a **real** refusal of a duplicate turn, which neither
  `file` nor `tinydb` could give. Verified, not asserted:

  ```
  journal_mode -> wal
  duplicate refused -> UNIQUE constraint failed: t.a
  side files -> ['s.sqlite', 's.sqlite-shm', 's.sqlite-wal']
  ```

  (Revision 1 said this made `enforces_unique_seq` "true rather than aspirational". That flag lives
  on `_DocumentBackend`, which dies with the two backends being removed — the property becomes real,
  the flag it named will not exist.)

  **That third line is a finding.** WAL means three files hold the data. Any statement about the
  store's permissions has to cover `-wal` and `-shm`, or it covers a third of it.
- `body_json` is **`TEXT`, parsed in Python**. No `json_extract`, no `json_valid`, nothing from
  JSON1 — because nothing needs it: `grep -c json_extract src/ai_sdlc_runner/conversations.py` is
  `0` today, and every query is by `conversation_id`, `project_id` or `seq`. Both seats said a
  schema that never asks the question beats probing for it, and Python 3.9's bundled SQLite on
  Windows predates JSON1 being on by default.
- **One file, not two.** Both seats agree, and fable-seat reads the ruling's singular
  「sqlite 內容…也包含」 as saying so outright. The registry is a handful of rows an operator can
  re-enter; the history is the irreplaceable part and it is in the file either way. But the two
  need **separate failure contracts**, which codex-seat is right that one "store write" abstraction
  would hide: a conversation write is deliberately non-fatal and reported, while **a registry edit
  must not return success unless its transaction committed.**

### Migration

Revision 1 said *"an existing `models.json` and existing `.jsonl` conversations both exist on this
machine right now."* **That is false, and fable-seat could not find either.** I checked: there is no
`.runner` directory in the repo, and no `models.json` or `.jsonl` anywhere under it. The JSONL
stores I produced while testing CHG-20260823-17 were in temporary directories that no longer matter.
The migration section was propping itself on a fiction — an unexamined present-tense claim, which is
the same defect shape as everything else this document has had to correct.

The importer is still right to build, for **users who do have such files** — but it is written for a
hypothetical, and saying so changes how it should be scoped.

Proposed: a one-shot `runner import --from <path>` that reads a `models.json` or a `file`-store tree
and writes into SQLite. It must:

- **preserve the old reader's semantics exactly.** The JSONL reader *reports* partial lines and
  duplicate `seq` values rather than refusing them (`incomplete_lines`, `duplicate_seqs`). SQLite's
  primary key will **refuse** a duplicate the old reader merely noted. So the policy has to be
  stated, not discovered: a conversation carrying duplicate `seq` values is **refused whole**, named,
  and left on disk — never partially imported;
- be **atomic per conversation** — a failed import leaves no half-populated conversation;
- be **idempotent** — re-running it does not double anything;
- **refuse rather than guess** on a `models.json` entry that `validate` now rejects;
- **delete nothing.**

## 3 · What this costs, said before the seats have to find it

- **The plain-text archive goes.** Both seats valued `file` for `cat`, `grep`, `tail -f` and
  git-diff. A `.sqlite` file is readable by the `sqlite3` CLI everywhere and the format is
  archivally stable, but it is not greppable and not diffable. The mitigation is that
  `runner export` already writes `json`, `markdown` and `csv` — but export is a step somebody has
  to take, and `tail -f` on a live run is not one of the three.
- **The bootstrap is sound, and revision 1 explained it with a claim that is not true today.** It
  said `--store-root` *"and the config file"* locate the store. `config/runner.yaml` carries no
  store key — only `agent_timeout` and a commented `agent_command` — and `load_config`'s output
  feeds `session_factory` alone. **Flags locate the store, and only flags.** There is no
  circularity, because `serve` already has the store flags and can find a SQLite registry without
  reading anything out of a store. If `runner.yaml` later grows a store path that is fine — a file
  locating the store is config. What may never happen is the store's location being read from the
  store. The sentence *"'files are only server config' is doing real work and must not erode"* was
  right; its supporting evidence was the invented part.
- **`serve` will now touch the store even with no `--project`.** Today it can run with no
  conversation store at all — it reads the registry from `<token-dir>/models.json`, independent of
  the store flags. After this, listing your models **creates a database file**. `models.load`'s rule
  — *"a missing file is an empty one; a malformed file is an error"* — must survive the move, which
  in SQLite means: a missing store is an empty registry, and a **corrupt** store is an error by
  name, never an empty registry.
- **`--models` has no disposition in revision 1.** It must die or repoint, and `serve` and `run`
  must resolve the same store file by default, or "one file" is fiction across two commands.
- **A single file is a single point of failure** in a way a directory of per-conversation files is
  not. One corrupt SQLite file is every conversation; one corrupt `.jsonl` was one conversation.
  WAL and transactions make corruption much less likely, not impossible.
- **The registry's own protection changes shape.** `models.json` was a file an operator could read,
  audit and `chmod`. It is proposed to keep storing **the name of an environment variable and never
  a key** — that property is in `models.py` and must survive the move intact.

## 4 · The questions for the seats

1. Is the **hand-written vs machine-maintained** line in §1 the right reading of
   *「file 只作為 server 的 config 才處理」* and *「sqlite 也包含 model 配置」*, or does the user
   mean something else? If it is right, is `settings.json` on the correct side of it?
2. **Does the model registry belong in the same SQLite file as the conversations, or its own?**
   One file is simpler; one file also means a corrupt store loses the registry *and* the history,
   and means registry writes contend with turn writes.
3. Is removing `file` as a conversation store **right**, given both seats independently argued for
   keeping it one round ago? What is actually lost, and is `runner export` a real replacement or a
   consolation?
4. Is the schema in §2 correct for what `conversations.py` and `models.py` actually do? Name any
   column that is a guess, and anything the code needs that is missing.
5. What in this proposition is **a name standing in for a constraint**, and which of its claims are
   asserted about code that does not exist yet? Round 1 and round 2 both caught one of those in the
   document that proposed the fix; assume there is one here.


---

## 5 · The deliberation

| Seat | Verdict |
|---|---|
| **codex-seat** | **`not sound`** |
| **fable-seat** | **`sound with changes`** |

**A split, so it does not pass** — and this one is a split on *severity*, not on direction. Both
verdicts are committed whole: [codex-seat](reviews/sqlite-only-codex-seat.md) ·
[fable-seat](reviews/sqlite-only-fable-seat.md).

**On substance the two seats agree completely**, which is worth stating precisely because the
verdicts differ:

- The **direction is right** — sqlite only, mongo and tinydb removed, files for server config, the
  registry moved in. Neither seat re-argued the ruling; both said explicitly it should stand.
- **The same worst thing**, named by both: the stored `reach` column, which reverses a documented
  invariant of the module being moved.
- **The same objection to §1's principle**, with the same evidence: `settings.json` is machine-written,
  so *hand-written vs machine-maintained* does not divide anything.
- **The same guessed columns**: `opened_at` and `updated_at`.
- **The same demand** that `synchronous` be chosen rather than deferred.

They differ on what the remaining gaps mean. codex-seat calls a design whose schema contradicts the
code's safety invariants `not sound` — an error of kind. fable-seat calls the same set `sound with
changes` — the direction survives every correction, so the document is fixable rather than wrong.
**Both readings are defensible and this document does not pick between them**, because averaging two
verdicts is the one thing this project's rules forbid outright.

Every finding above is now applied, and every one was verified by running it rather than by reading
the seat's summary of it.

### What that leaves

The proposition is **corrected but still unreviewed in its corrected form** — the third consecutive
change where that sentence is true, and the third where the corrections themselves turned out to
contain a defect of the same class as the one they fixed. Round 1 of the store found a design that
could not produce its own document; round 2 found the fix to its locality check was the coarse check
it replaced; this round found a schema that stored a safety label the code deliberately strips.

**The honest expectation is that a fourth round finds something too.** Implementation should not
start on the assumption it will not.

### Not claimed

**That the SQLite backend will behave as described.** None of it exists. WAL, the unique refusal and
the side files are verified on this machine at Python 3.11.9 / SQLite 3.45.1 — the 3.9 × Windows
cell, the killed-process test and the two-writer test are all still owed, and both seats said so.

**That the importer's refusal cases are complete.** They are where the next seat should look.
