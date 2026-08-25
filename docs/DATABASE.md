# The database schema

**Status: proposed, not built.** No SQLite code exists in `src/` — this is the shape to review before
it does.

It follows the ruling on [CHG-20260823-19](design/sqlite-only.md): *「只留 sqlite + file，移除 mongo
和 tinydb / file 只作為 server 的 config 才處理 / sqlite 內容不僅限於紀錄，也包含 model 模型配置的紀錄
儲存」* — SQLite is the only store, files are server config, and the model registry moves in.

Four review rounds preceded this page. Every design decision below carries the finding that produced
it, because a schema without its reasons gets "simplified" back into the defect it was avoiding.

---

## 0 · What is in the file, and what is not

| In the database | Stays a file | Why |
|---|---|---|
| conversation history — every ask, answer, decision, instruction | `runner.yaml` — `agent_command`, `agent_timeout` | nothing in `src/` ever writes it; a person authors it |
| the **model registry** — *which models exist* | `settings.json` — seats, high-risk bypass, vouched commands | server config, read before any store exists |
| — | the ask journal (`.runner/asks/*.json`) | a **resume index**, mutable by design; see §5 |
| **not stored at all** | the **model assignment** — `node_models`, `seat_models` in the plan | it is an **input**, never an output — see §0.1 |

### 0.1 · Model configuration is two halves, and only one is persisted here

This is the question the schema does not answer on its own, so it is answered here.

| | What it is | Where it lives | Who writes it |
|---|---|---|---|
| **Registry** | *which models exist* — `opus` is a `cli` model running `claude -p` | `models.json` today, the `models` table proposed | the operator, through `POST /models`, **and it persists** |
| **Assignment** | *which node and which seat gets which model* | the plan file's `node_models` / `seat_models`, and `--seat-model` | **nobody.** It is read once at startup and never written |

`assignments` is built at `cli.py:704` from `plan.get("node_models")` and `plan.get("seat_models")`,
held in memory, and exposed **read-only** by `GET /config/nodes`. No POST route touches it. There is
no writer anywhere in `src/`.

**That is defensible, and it is also a half-feature.** Defensible because `Registry`'s own docstring
draws the line — *"the models this project may use, and nothing about which node uses which"* — and
an assignment is a property of **this change**, not of the project: the plan file is its durable
home, and it is the file a person version-controls. A half-feature because through the console you
can **add a model and cannot assign it to anything**: it appears in `by_model` with empty `nodes`
and `seats` until somebody hand-edits the plan.

### 0.2 · A decision that is not mine to make

The ruling this schema implements says:

> 「sqlite 內容不僅限於紀錄，也包含 **model 模型配置**的紀錄儲存」

**「模型配置」 can be read two ways**, and this page took the narrow one:

1. **the registry only** — which models exist. That is what the `models` table holds, and what is
   built here.
2. **the registry *and* the assignment** — which would mean `node_models` and `seat_models` become
   tables too, the console gets routes to edit them, and the plan file stops being their home.

Reading (1) was chosen because `Registry` draws that line itself and because an assignment belongs to
a change rather than to a project. **It was not confirmed**, and a previous round of this same design
was refused for exactly that move — deciding an ambiguity silently instead of naming it. So it is
named:

**If 「模型配置」 was meant to include the assignment, this schema is missing two tables and the API is
missing the routes to fill them.** Say so and it gets built.

**The database's own location is never in the database.** It comes from `--store-root` and nothing
else. That is not a limitation to work around later — it is the one rule that keeps the bootstrap
from being circular, and a seat checked that `runner.yaml` carries no store key today.

---

## 1 · Connection setup

**Every connection, every time.** Three of these are per-connection state and reset on reconnect;
two are written into the file. Getting that backwards is how a `REFERENCES` clause enforces nothing.

```sql
PRAGMA journal_mode = WAL;      -- FILE-level: survives reopen
PRAGMA user_version = 1;        -- FILE-level: survives reopen
PRAGMA foreign_keys = ON;       -- PER CONNECTION: OFF by default
PRAGMA busy_timeout = 5000;     -- PER CONNECTION: ms
PRAGMA synchronous = NORMAL;    -- PER CONNECTION: resets to FULL
```

Measured on this machine — set all five, close, reopen:

```
journal_mode     wal        <- survived
user_version     7          <- survived
foreign_keys     0          <- RESET
synchronous      2          <- RESET (to FULL)
busy_timeout     5000       <- per connection
```

### Why each one

| Pragma | Buys | Costs |
|---|---|---|
| `journal_mode=WAL` | a reader never blocks a writer; crash recovery | **two extra files**, `-wal` and `-shm`, which also hold data — any permissions statement must cover all three |
| `foreign_keys=ON` | `REFERENCES` actually refuses an orphan turn | nothing. It is off by default and a seat proved an orphan row inserts fine without it |
| `busy_timeout=5000` | the server can write the registry while a run appends turns | up to 5s of blocking before `SQLITE_BUSY` |
| `synchronous=NORMAL` | **process crash: nothing committed is lost** | **power loss: the last transactions may roll back.** Chosen, not defaulted — the store is an archive whose failure is explicitly non-fatal to a run, and the run's own journal is what a resume reads. `FULL` would close the gap at an fsync per turn |
| `user_version` | ordered migrations | it must actually be read and compared at open, or it is a number nobody consults |

---

## 2 · The tables

```sql
CREATE TABLE conversations (
  conversation_id TEXT PRIMARY KEY,      -- 32 hex, minted at open
  project_id      TEXT NOT NULL,         -- sha256(project_name)[:32]
  project_name    TEXT NOT NULL,         -- as the operator typed it
  schema          INTEGER NOT NULL,      -- the DOCUMENT's version, not the database's
  run_json        TEXT NOT NULL          -- {"journal": …, "plan": …}
);
CREATE INDEX conversations_by_project ON conversations(project_id);

CREATE TABLE turns (
  conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
  seq             INTEGER NOT NULL,
  kind            TEXT NOT NULL,         -- one of the nine
  at              TEXT NOT NULL,         -- ISO 8601 UTC, seconds
  body_json       TEXT NOT NULL,         -- ONLY the body
  PRIMARY KEY (conversation_id, seq)
);

CREATE TABLE models (
  id           TEXT PRIMARY KEY,
  vendor       TEXT NOT NULL,
  name         TEXT NOT NULL,            -- the vendor's own identifier
  transport    TEXT NOT NULL,            -- 'cli' | 'api'
  command_json TEXT NOT NULL DEFAULT '[]',   -- argv as a LIST
  endpoint     TEXT NOT NULL DEFAULT '',     -- api only
  key_env      TEXT NOT NULL DEFAULT '',     -- the NAME of an env var. Never a key.
  note         TEXT NOT NULL DEFAULT ''
);
```

That is the whole schema. Three tables, one index.

---

## 3 · Every column that is **not** here, and why

This section is longer than the schema, and that is deliberate — each absence is a finding.

### `models.reach` — the worst thing in an earlier draft

Both seats named it. `models.py` says **"Computed, never declared"**, and `save()` strips it:

```python
{k: v for k, v in m.as_dict().items()
 if k not in ("reach", "leaves_this_machine")}     # both are computed; storing them would
                                                    # let a stale label outlive the truth
```

`reach` is what the console shows to say **whether a model leaves this machine**. Persisted, one
endpoint edit that forgets to recompute leaves the console showing `local` about something external.
It is derived from `(transport, endpoint)` on every read, and `_model_from` would **refuse** a
payload containing it anyway, with this project's doctrine in the message:

```
model 'x' has field(s) this runner does not know: ['reach'].
Ignoring them would let a setting look configured and do nothing.
```

### `conversations.opened_at`

Two seats called it a guess and a third round removed it. Nothing in the code reads an open
timestamp, and it would be a **second copy of the OPENED turn's `at`** — the two-truths problem the
`turns` table exists to avoid. If a listing ever needs one:

```sql
SELECT at FROM turns WHERE conversation_id = ? AND seq = 0;
```

### `models.updated_at`

Invented. Nothing in `models.py` produces or reads an update time.

### `turns.seq/kind/at` inside `body_json`

`body_json` holds **only** the body. Putting the envelope in it too creates two sources for one fact
— and the shipped code had exactly that bug: `Turn.as_dict` spread the body last, so a body key
overwrote `seq` and `at`. Now refused.

---

## 4 · What each constraint actually enforces

| Constraint | Refuses | Verified |
|---|---|---|
| `PRIMARY KEY (conversation_id, seq)` | a duplicate turn — **a real refusal**, which neither the JSONL nor the TinyDB backend could give | `UNIQUE constraint failed` |
| `REFERENCES conversations(...)` | a turn with no conversation — **only with `foreign_keys=ON`** | an orphan inserts fine without it |
| `conversations.conversation_id PRIMARY KEY` | reopening a conversation id | — |
| `models.id PRIMARY KEY` | two models with one id | — |
| `NOT NULL` throughout | a missing field | — |

**No `CHECK` constraint on `transport`, `kind` or `project_id`.** Deliberate: a lone
`CHECK (transport IN ('cli','api'))` is coarser than `models.validate`, which enforces the real
biconditionals (a `cli` model needs `command`; an `api` model needs `endpoint`; an `external` model
needs `key_env`). Two validators that disagree is worse than one that is authoritative, so **every
row is validated through `models.validate` and `_model_from` on read and on write**, and the
database enforces identity and referential integrity only.

---

## 5 · Why the ask journal stays a file

They record different facts and cannot drift:

| | Records | Mutable |
|---|---|---|
| ask journal | *"what is the current question at position N"* | **yes, by design** — `record` overwrites |
| this database | *"what happened, in order"* | **no** — append-only, `INSERT` only |

Proved by running it:

```
two fresh runs, one journal directory  ->  entries: 1
what survives                          ->  {"brief": "SECOND RUN"}
```

The journal is keyed by position and overwrites. The conversation store must not be derived from it —
that was the finding that failed the first design outright, in both seats' words.

---

## 6 · Migration from what exists

`runner import --from <path>` reads a `models.json` or a JSONL store tree. It must:

- **preserve the old reader's semantics or refuse.** The JSONL reader *reports* duplicate `seq`
  values (`duplicate_seqs`); a primary key **refuses** them. So the policy is stated rather than
  discovered: **a conversation carrying duplicate `seq` values is refused whole, named, and left on
  disk** — never partially imported;
- be **atomic per conversation** — a failure leaves no half-populated conversation;
- be **idempotent** — re-running doubles nothing;
- **refuse rather than guess** on a `models.json` entry `validate` now rejects;
- **delete nothing.**

An earlier draft claimed such files "both exist on this machine right now". They do not — there is no
`.runner` directory anywhere in this repo. The importer is for operators who have them.

---

## 7 · Still open — please read before approving

These are known and unresolved. None is a reason not to build; all are reasons not to claim more
than is true.

1. **A resumed run whose store read fails resets `seq` to 0.** Against the JSONL backend that
   produced duplicates the reader *reported*. Against a primary key, **every turn of that run is
   refused and swallowed into `write_errors`** — the whole resumed conversation lost to stderr. The
   duplicate policy above is written for the importer and not for this path.
2. **Nothing is verified on Python 3.9 × Windows.** All measurements here are 3.11.9 / SQLite
   3.45.1. WAL under 3.9's bundled DLL, a killed-process test, and a two-writer test are all owed —
   every previous seat said so and this page does not discharge it.
3. **`busy_timeout=5000` is a guess.** No measurement says 5s is the right ceiling, and what an
   operator sees when it is exhausted is unspecified.
4. **The store is as sensitive as the ask journal beside it and no better protected.** `0700` is
   best-effort and does little on Windows, and WAL means **three** files carry the data.
5. **A single file is a single point of failure** where a directory of per-conversation files was
   not. One corrupt database is every conversation; one corrupt `.jsonl` was one conversation.

---

## 8 · The queries this schema has to serve, in full

There are five, and none needs JSON1 — which is why `body_json` is `TEXT` and Python parses it, and
why Python 3.9's bundled SQLite never has to be asked whether it has `json_extract`.

```sql
-- 1. every turn of one conversation, in order
SELECT seq, kind, at, body_json FROM turns
 WHERE conversation_id = ? ORDER BY seq;

-- 2. one conversation's header
SELECT * FROM conversations WHERE conversation_id = ?;

-- 3. conversations in a project
SELECT * FROM conversations WHERE project_id = ?;

-- 4. every project
SELECT DISTINCT project_id, project_name FROM conversations;

-- 5. the registry
SELECT * FROM models ORDER BY id;
```

Appending is one `INSERT` per turn. There is no `UPDATE` and no `DELETE` on `turns` — not as a
convention, but because no code path exists to issue one.
