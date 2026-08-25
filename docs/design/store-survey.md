# Which database should hold the conversations — a survey, then a deliberation

- Project: ai-sdlc-runner
- Change: CHG-20260823-18 (proposed)
- Proposed by: the user — *「先列表可用的資料庫系統與優劣評比，再來審議適合情況」*
- Related: [CHG-20260823-17](../changes/CHG-20260823-17.md) shipped three backends (`file`, `tinydb`,
  `mongo`) after two review rounds. This asks whether those three are the right three.

## 0 · What the choice is actually against

A survey scored on generic merits would be worthless here — "MongoDB scales horizontally" decides
nothing for a store that will never leave one laptop. So the criteria come from what
[`conversations.py`](../../src/ai_sdlc_runner/conversations.py) already does, and from the standing
constraint the user set for the whole project.

| | Requirement | Where it comes from |
|---|---|---|
| **R1** | **Local-only.** No egress by default; anything that can reach off-machine must be refused unless explicitly relaxed and recorded | the user: *「host 在 local 不提供對外連線」* |
| **R2** | **Append-only, exactly one writer** per conversation | design §1, §3 |
| **R3** | **Whole-document read** — export reads every turn of one conversation in `seq` order | `export_conversation` |
| **R4** | List conversations **by project**; list projects | `runner conversations` |
| **R5** | **Nested JSON of arbitrary shape**, individual values up to hundreds of KB (a work order carries the brief, instructions and attachment manifest) | `workorder.render` |
| **R6** | **Crash-safe** — turns written before a crash survive, and a half-written turn is reported rather than dropped | design §3 |
| **R7** | **Zero setup for the default.** `runner run --project X` must work with nothing installed and nothing running | the default backend cannot need a server |
| **R8** | **Python 3.9 → 3.13, Windows and Linux**, and testable in CI on all four cells | `.github/workflows` matrix |
| **R9** | No licence or operations burden the user did not ask for | — |
| **R11** | **Every option the user might want is offered** — *「提供所有選擇的可能性」* | the user, when the store was first specified |
| **R10** | The store holds **every work order verbatim**; at-rest exposure is the same class as the ask journal | design §6 |

Two non-requirements, stated so they stop being argued: **there is no throughput requirement** and
**there is no scale requirement.** One operator, conversations in the hundreds of turns. Any system
chosen for throughput is being chosen for a problem this project does not have.

**R11 was not in revision 1 of this table, and its absence is what the two seats split over.** One
seat read the survey's own criteria and concluded — correctly, from those criteria — that MongoDB
answers no stated need and should be removed. The other weighed the user's instruction and kept it.
A requirement omitted from the table is a requirement the deliberation cannot see, which is the
survey's own version of the defect it exists to hunt.

**Concurrency is narrower than "none", and revision 1 got that wrong too.** The design promises one
writer *per conversation*, not one runner per machine. The `file` backend supports two runners on
two conversations for free, because they are two files. Any single-file backend must face it —
SQLite with `busy_timeout` and retry, or every turn lands in `write_errors`.

---

## 1 · The survey

### Embedded — no server, no port, no daemon

| System | Package | What it is | For | Against |
|---|---|---|---|---|
| **JSON Lines files** *(shipped default)* | none — stdlib | one file per conversation, one JSON object per line | Zero deps. Append is `open("a")` — no read-modify-write to lose a turn. A crash costs the line being written and the reader **reports** it. Trivially inspectable with `cat`, `grep`, `tail -f`. Git-diffable | No query language: `--project` filtering is a directory walk and any other filter is a full scan. No uniqueness enforcement — a duplicate `seq` can only be *reported*, not refused. Windows `MAX_PATH` is a live hazard (it lost a whole conversation during review). Not what most people mean by "a database" |
| **SQLite** *(stdlib, not currently offered)* | none — `sqlite3` | the world's most-deployed embedded SQL engine; a competent document store when a turn is JSON text in a `TEXT` column | **Zero deps, like the file backend, but with real guarantees** *once written*: ACID transactions, a genuine `UNIQUE(conversation_id, seq)`, indexes, and WAL. One file at a short path, which **materially reduces** the `MAX_PATH` hazard rather than abolishing it — a long enough store path still breaks. `ORDER BY seq` instead of sorting in Python | Not "NoSQL" by name — the same substitution the `file` backend already had to admit to, and it must be admitted here too. **None of the guarantees above exist until the backend is built**: WAL is an opt-in pragma, and two runners on one store need `busy_timeout` or every turn lands in `write_errors`. JSON1 is a non-issue **if the schema never asks for it** — see below |
| **TinyDB** *(shipped)* | `tinydb` | a pure-Python document DB in one JSON file | Genuinely document-shaped with a real query API (`Query()`), pure Python so it installs anywhere with no wheels or toolchain, tiny surface. **Actively maintained** — 4.9.0 is `Development Status :: 5 - Production/Stable` | **Rewrites the whole database on every write.** Not inference — `Table._update_table`'s own docstring says *"The storage interface used by TinyDB only allows to read/write the complete database data, but not modifying only portions of it"*, and `JSONStorage.write` seeks to 0, serialises everything, writes in place and truncates: no temp file, no atomic rename, so a crash mid-write can corrupt **every conversation in the store**, not one line. And **4.9.0 declares `Requires-Python: <4,>=3.10` while this project's floor is 3.9** |
| **DuckDB** | `duckdb` | embedded analytical (OLAP) engine with first-class JSON and CSV | Reads and writes JSON/CSV/Parquet natively — the **export** side of this feature is almost free. Excellent columnar scans if conversations ever get analysed in aggregate | Optimised for bulk analytics, not for appending one row at a time — row-by-row inserts are its weakest path, and that is 100% of this workload. Large binary wheel. Solves a problem we do not have |
| **LMDB** | `lmdb` | memory-mapped B-tree key/value store | Extremely fast, fully ACID, crash-proof by design. `(conversation_id, seq)` is a natural sorted key | Bytes in, bytes out — every document shape, query and index would be hand-built above it. A pre-sized memory map is a footgun on a growing store. C extension to build |
| **RocksDB / LevelDB** | `plyvel`, `rocksdb` | log-structured key/value | Built for exactly this write pattern (append-heavy, ordered keys) | Same "we would write the database" objection as LMDB, plus a much heavier build. Windows support is the weak spot, and half our matrix is Windows |
| **UnQLite** | `unqlite` | embedded document store, "SQLite for JSON" | Genuinely embedded **and** genuinely document-shaped — the combination nothing else in this table has | Thin, sparsely maintained Python bindings; small community; a bug here would be ours to fix |
| **ZODB** | `ZODB` | transactional Python object database | Persists Python objects directly, with transactions and history | Pickle-based: the store stops being readable by anything that is not this Python program, which breaks the point of an exportable archive. Heavyweight |

### Server-backed — a process to install, run and secure

| System | Package | For | Against |
|---|---|---|---|
| **MongoDB** *(shipped)* | `pymongo` | The reference document database. Real indexes and queries over nested documents, a unique index that actually refuses a duplicate, mature Python driver, and what most people mean by "NoSQL DB" | **A network client** — the reason `local_mongo_uri` exists and needed five rules plus a forced `directConnection=true`, and still had three bypasses found in round 2. Needs a daemon installed and running. A default localhost `mongod` usually has **no authentication at all**, so R10 is worse than the file backend, not better. SSPL licence |
| **PostgreSQL + JSONB** | `psycopg` | JSONB is a *better* document store than most document stores — indexable, queryable, constrained, and fully transactional. Would satisfy every functional requirement outright | Heaviest possible operational burden for a single-user local tool. A server, a user, a database, a schema, a migration story. Same network-client exposure as Mongo |
| **CouchDB** | `httpx` | Append-only by design and HTTP-native; philosophically the closest match to a conversation log | An HTTP server — the exact shape R1 was written against. Erlang runtime. Its replication strength is a feature we must actively suppress |
| **Redis** | `redis` | Fast; streams are literally an append-only ordered log | In-memory first — durability is configuration, and a store whose persistence is a setting is the wrong default for an archive. Another daemon |
| **Elasticsearch / OpenSearch** | `elasticsearch` | Full-text search across every work order ever sent, which is a genuinely attractive thing to have | A JVM cluster for a single-user log. Enormous. R1 and R9 both refuse it |
| **Firestore / DynamoDB / Cosmos DB** | — | — | **Disqualified by R1.** They are cloud services; there is no local-only mode that is the real thing. Not evaluated further |

---

## 2 · Scoring against the requirements

`✓` meets it · `~` meets it with work or caveats · `✗` fails it · `?` **a claim about code that
does not exist yet, or a probe nobody ran**

The `?` column was added in revision 2. Every one of them was a `✓` before both seats pointed out
that the winner's row was scoring an unwritten backend as though it were already built.

| | R1 local | R2 append/1-writer | R3 whole read | R4 by project | R5 nested JSON | R6 crash-safe | R7 zero setup | R8 3.9–3.13 ×2 OS | R9 no burden | R10 at rest |
|---|---|---|---|---|---|---|---|---|---|---|
| **JSONL files** | ✓ | ✓ | ✓ | ~ scan | ✓ | ~ line-level | ✓ | ✓ | ✓ | ~ `0700` |
| **SQLite** | ✓ | ? unbuilt | ✓ | ? unbuilt | ✓ JSON as TEXT | ? unbuilt | ✓ | ? never run | ✓ | ~ file perms |
| **TinyDB** | ✓ | ✗ full rewrite | ✓ | ✓ | ✓ | ✗ | ✓ | **✗ needs ≥3.10** | ✓ | ~ |
| **DuckDB** | ✓ | ~ slow inserts | ✓ | ✓ | ✓ | ✓ | ~ big wheel | ~ | ~ | ~ |
| **LMDB** | ✓ | ✓ | ✓ | ~ hand-built | ✗ bytes | ✓ | ~ C ext | ~ | ✗ | ~ |
| **MongoDB** | ✗ network | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ daemon | ✓ | ✗ | ✗ usually no auth |
| **PostgreSQL** | ✗ network | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | ✓ if configured |
| **CouchDB** | ✗ HTTP | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | ~ |

### What the table says before anybody argues

1. **TinyDB fails R2, R6 and R8 outright**, and R8 is the one that needs no argument:

   ```
   tinydb-4.9.0  Requires-Python: <4,>=3.10
   .github/workflows/ci.yml  python-version: ["3.9", "3.13"]
   ```

   A 3.9 operator silently resolves an older 4.8.x — a different library from the one anybody
   tested. Revision 1 scored TinyDB `✓` on R8 without checking, and separately called it
   *"unmaintained-ish; effectively a toy"*, which its own metadata contradicts. **Both errors were
   mine and in the same row**: an unexamined tick beside an unexamined slur. The real objection —
   the whole-database rewrite, quoted above from TinyDB's own docstring — never needed either.
2. **SQLite would meet every requirement, and is not currently offered at all.** Revision 1 said
   *"meets every requirement and costs nothing — it is in the standard library"*, and **both seats
   named that sentence as the worst thing in the survey.** They were right. `import sqlite3`
   succeeding proves nothing about a backend nobody has written: WAL is an opt-in pragma no code
   sets, the `UNIQUE(conversation_id, seq)` is a schema that does not exist, and no implementation
   has ever run on the CI matrix. It costs nothing in *dependencies*; it costs a schema,
   transactions, pragmas, busy-timeout handling, migrations and tests — all of which the table
   scored as already true. A correct conclusion resting on an unexamined mark is precisely how this
   repository's defect log says its defects get made.
3. **MongoDB is the only shipped backend that fails R1**, which is why it needed five rules and a
   forced client flag, and still had three locality bypasses found by review.
4. The two axes people usually decide on — scale and throughput — are **explicitly not
   requirements here**, and they are the only axes on which Mongo and Postgres beat SQLite.

5. **JSON1 is not needed at all.** Both seats checked and the code agrees: `grep -c json_extract
   src/ai_sdlc_runner/conversations.py` → `0`. Every query this module makes is rows by
   `conversation_id` ordered by `seq`, and headers by `project_id` — plain indexed columns. Put the
   turn in a `TEXT` column and parse it in Python exactly as the `file` backend does, and the
   Python-3.9 JSON1 question never has to be answered. **A schema that does not ask the question
   beats both probing and testing for it**, which is the sharpest thing either seat said.

6. **One candidate revision 1 missed: MontyDB** — pure-Python, embedded, MongoDB-API-compatible,
   optionally backed by SQLite. It is the literal answer to *"an embedded NoSQL database with the
   API the user named"*. It still loses (small project, sparse maintenance — the UnQLite objection
   in full), but a survey claiming to be a survey should have carried the row.

---

## 3 · The proposition put to the seats

> **The shipped set of three is wrong. It should be `file`, `sqlite` and `mongo`, with `sqlite` as
> the default and TinyDB removed.**
>
> - `sqlite` — zero dependency, real constraints, real crash safety, no path-length hazard, and the
>   only option that meets every requirement.
> - `file` — kept, because a JSONL file a person can `cat`, `grep` and diff is worth something a
>   database cannot give, and it is the one format that survives this program being deleted.
> - `mongo` — kept, because the user asked for *「提供所有選擇的可能性」* and somebody who already
>   runs a mongod should be able to use it. It stays behind the locality rules.
> - `tinydb` — **removed**, because a document store that rewrites the whole file per append and can
>   lose the entire store to one interrupted write is not an option, it is a trap with a friendly
>   API.

### The questions

1. Is this proposition right? If not, which set is, and why?
2. Is **removing** a shipped backend correct, or is deprecating it with a loud warning the honest
   move? It shipped hours ago and has no users, but "we shipped it" is not an argument.
3. Is SQLite an acceptable answer to *「寫到 nosql 的 db 中」*? It is a document store in behaviour
   and a relational engine by name. Is offering it as the default honest, or is it the same
   substitution the `file` backend already had to admit to?
4. Is the JSON1 availability caveat on Python 3.9 a real risk, and what is the honest way to find
   out — probe at import and refuse by name, or test it on the matrix and let CI answer?
5. **What in this survey is a name standing in for a constraint?** Specifically: are any of the
   `✓` marks above claims that have not been examined?


---

## 4 · The deliberation — and it is a split

Both seats got the same survey, neither saw the other.

| Seat | Verdict | Recommended set |
|---|---|---|
| **codex-seat** | **`not sound`** | **`sqlite` only** as a writable store. JSONL demoted to an export format, **Mongo removed** from the core and reintroduced only under a change backed by a real remote or multi-process requirement |
| **fable-seat** | **`sound with changes`** | **`file` + `sqlite` + `mongo`**, `sqlite` default, TinyDB removed and `--store tinydb` refusing *by the removal's name* rather than falling into `unknown store` |

**A split does not pass**, which is this runner's own rule applied to a decision about the runner.
So this is not merged as a decision — it goes to a person, exactly as an `undecided` panel does.

### What they agree on, and it is most of it

- **SQLite should be the default.** Both. Unconditionally.
- **TinyDB must go**, and *removed* rather than deprecated — it shipped hours ago, has no users and
  no data, and a deprecation warning on a store that can lose everything to one interrupted write
  fires *after* the operator has already chosen the trap.
- **SQLite is an honest answer to 「nosql」 only if the substitution is named out loud**, in the same
  words the `file` backend already uses about itself. Both seats, independently, pointed at that
  docstring as the precedent.
- **The survey's worst sentence** was *"SQLite meets every requirement and costs nothing"*. Both.

### What they split on, and why

**Whether `mongo` and `file` stay as writable backends.**

codex-seat scored strictly against the requirements as written and concluded that Mongo answers
none of them: it is the only backend that fails R1, it carries the entire locality-rule surface that
produced five findings across two rounds, and *"someone may already run MongoDB"* is not a project
requirement. On the survey as revision 1 wrote it, **that reasoning is correct.**

fable-seat weighed 「提供所有選擇的可能性」 as a real constraint and kept both.

**The disagreement is downstream of my omission.** R11 was not in revision 1's table. One seat could
not see the requirement that decides the question, so the two seats were scoring different problems
— and a survey whose criteria are incomplete manufactures exactly this kind of split. R11 is in the
table now; the split stands as recorded, because a verdict is not re-run to get a nicer answer.

### The decision that is a person's

With R11 restored, the question is no longer *"does Mongo earn its place on the merits"* — it does
not, and both seats effectively say so. It is:

> **Is 「提供所有選擇的可能性」 still what you want, now that the cost is visible?**

The cost, stated plainly: keeping `mongo` means keeping `local_mongo_uri` and its five rules, the
option allowlist, the socket-path decoder and the forced `directConnection=true` — the surface that
produced a locality bypass in round 2 **and** a second one in this round's own re-reading. It is the
only backend that can send conversations off the machine, and the only one whose defects have been
security defects.

Three answers, and none is wrong:

1. **Keep all three** (fable-seat) — the option set you asked for, with `sqlite` as a default that
   nobody has to think about.
2. **`sqlite` + `file` only** — drop the one backend that fails the local-only constraint, keep the
   two that cannot leave the machine.
3. **`sqlite` only** (codex-seat) — one writable store, `file` demoted to an export format
   alongside `json`/`markdown`/`csv`, which is where its real virtue (`cat`, `grep`, git-diff)
   actually lives.

Nothing is implemented from this document until that is answered. What *is* settled by unanimity —
SQLite as the default, TinyDB out — can proceed either way.
