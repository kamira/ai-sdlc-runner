# Design — every conversation stored, categorised by project, and exportable

- Project: ai-sdlc-runner
- Change: CHG-20260823-17
- Proposed by: the user — *「每次對話都要寫到 nosql 的 db 中，依據專案分類」* and *「並提供匯出對話功能」*
- Answers already given: store — *「提供所有選擇的可能性」*; export — *「JSON, Markdown, CSV 都支援，但用戶可選哪種形式匯出」*
- Standing constraint: **the whole operating flow is local-only.** The host offers no external
  connection. The server may reach models, in or out.

## Revision 2 — the first design did not pass

The brief went to both seats **before any code existed**, which is the first time that has actually
happened in this repository, and the last review round struck a README sentence out for claiming it.
Both verdicts are committed whole:
[codex-seat](reviews/conversation-store-codex-seat.md) · [fable-seat](reviews/conversation-store-fable-seat.md).

**Both returned `not sound`, and both named the same keystone sentence:**

> *"The store is therefore **derived**, not a second source of truth."*

Fourteen lines above it the brief had defined a conversation as asks **and operator decisions** —
*"a person answering is as much a turn as a model answering"* — and then chose a source that has
never held a single operator turn. `journal.record` and `journal.answered` are the only two writers
(`engine.py:564`, `576`); confirmations, rejections and rulings reach only the in-memory
`RunReport`. The design's own architecture could not produce the document the design defined.

Two further facts I confirmed by running them rather than reading them:

```
two fresh runs, one journal directory  ->  entries: 1
what survives                          ->  {"brief": "SECOND RUN"}
run_id 1 == run_id 2                   ->  True
```

The journal is keyed by **position**, and `record` overwrites unconditionally. The first
conversation is not stale in the store — it is gone from the source. And:

```
sorted(['%03d-x' % n for n in (99, 100, 101, 999, 1000)])
['099-x', '100-x', '1000-x', '101-x', '999-x']
```

`entries()` orders by filename sort, so the 1000th ask sorts between the 100th and the 101st. A
store presenting "the ordered sequence of turns" would have inherited that.

Everything below is the design after both verdicts. Each section says which finding it answers.

## 1 · The store is a first-class append-only log, written as turns happen

Not derived. Both seats said so and they are right, for different halves of the same reason: the
journal lacks the operator turns, and it destroys the model turns it does have.

The two are **not** duplicate writers of one fact, which was the original objection to having both:

| | records |
|---|---|
| `AskJournal` | *"what is the current question at position N"* — a resume index, mutable by design |
| the conversation store | *"what happened, in order"* — append-only, never rewritten |

A turn is written **when it happens**. A crashed run has everything up to the crash.

### The turn kinds

| kind | carries |
|---|---|
| `opened` | project, run, schema version, when |
| `instruction` | what the operator asked for, and which instruction number it is |
| `ask` | node, role, seat, **model**, and the work order sent |
| `answer` | the ask it answers, and the JSON that came back |
| `unanswered` | an ask that raised, and what raised |
| `decision` | `approval` / `rejection` / `ruling`, the gate or node, and why |
| `relaxation` | anything the run was granted, including `--store-remote allow` |
| `note` | a store write that failed, and anything else the store must say out loud |
| `closed` | the run's final state |

**The answering model is recorded.** `_ask` already receives `model` and did not pass it to the
journal (`engine.py:541`, `564`) — codex-seat found that, and it means the existing durable record
cannot say which model said what. The store's `ask` turn carries it.

### `seq` is an explicit integer

Not a zero-padded filename. The 999 break above is exactly the class of defect this repository keeps
recording, and inheriting it would have been avoidable by not reusing the mechanism that has it.

## 2 · Identity — what a conversation *is*

`run_id` (the journal directory) identifies **storage**, not one execution. Both seats said so.

- **`conversation_id`** is minted when a conversation opens, 32 hex characters, and written into the
  document at once. Durable before the first turn, not reconstructed afterwards.
- Where a journal exists, the id is **also** written beside it as `<journal>/.conversation`. A
  resumed walk re-attaches to the same conversation; a fresh journal directory has no marker and
  gets a new one. **That marker file is the "run instance" fable-seat asked for** — it exists
  already as a durable place, so nothing new has to be invented to hold it.
- A run with **no journal** still gets a conversation. It cannot be resumed, and that is a property
  of the run, not a reason to lose the record of it. This closes the one case the first brief
  admitted and then did not handle.

### The project is required, and is never a directory name

The first brief defaulted `--project` to the plan file's parent directory. Both seats named it: that
files every `examples/plan.json` run under a project called **"examples"**, and `serve` may have no
plan at all. A location is not an identity.

**`--project NAME` is required** by any command that stores. There is no default, because there is
no fact available to default from.

- `project.id = sha256(name)[:32]` — what the file backend uses as a directory.
- `project.name` — the name as given, stored as **data**, never as a path.

That is `attachments.py`'s rule applied one layer out (`attachments.py:131`, `150`): an
operator-chosen string never becomes a path component. It also fixes the second half of what
codex-seat found — a resolved Windows path contains a colon and separators and is not a filename on
any platform.

**A resume that names a different project is refused by name.** The document records the project at
first write; changing it would silently rewrite categorisation history.

## 3 · Three backends, and what they have in common

| Backend | Needs | Shape |
|---|---|---|
| `file` | nothing — stdlib | **JSON Lines**: `<root>/<project_id>/<conversation_id>.jsonl`, header line then one line per turn |
| `tinydb` | `tinydb` | one document per turn, plus a header document |
| `mongo` | `pymongo` | one document per turn, plus a header document |

A backend whose package is missing **refuses by name**. No fallback to `file`. Neither `tinydb` nor
`pymongo` is installed here, so the refusal is the path that is actually tested; the backends
themselves are tested where the package exists and skipped where it does not, and the skip is
visible rather than counted as a pass.

Codex-seat asked what the three actually guarantee in common. They guarantee this and no more:

| Guarantee | How |
|---|---|
| append-only | no backend has an update path; `file` opens `"a"`, the others insert |
| `(conversation_id, seq)` is unique | **refused** where a backend can (Mongo's unique index, TinyDB's check) and **reported** by the reader everywhere. `file` cannot refuse one without a read per append, and one writer per conversation is already the rule — so the guarantee is stated where it is true rather than everywhere. The first version claimed all three refused |
| ordering | by the integer `seq`, never by insertion order or filename |
| a partial write is visible | the last line of a JSONL file may be short; the reader reports it rather than dropping it |
| concurrent writers | **not supported** — one runner per conversation. Said here rather than implied |

`file` is the default, and it is a directory of files. The user asked for a NoSQL DB and the default
is not one — fable-seat is right that this should be named rather than argued around. It is a
document store with the filesystem as its index; `--store tinydb` or `--store mongo` is a real
document database and is one flag away.

## 4 · Mongo is a network client, and loopback does not constrain it

The first brief proposed a loopback host check by analogy with `_loopback_origin`. **Both seats
refused the analogy**, and fable-seat gave the mechanism: `MongoClient` performs topology discovery.
Given a loopback seed that turns out to be a replica-set member or a `mongos`, the driver reads the
topology **from the server** and connects to every member it learns of, including remote ones,
without consulting the URI again. A host check would answer "local" about a URI while the driver
went off-machine — this project's second-most-frequent defect, exactly.

So the rule is not one check. Without `--store-remote allow`, all of these hold:

1. scheme is `mongodb` — **`mongodb+srv://` is refused**, it is a DNS seedlist lookup by construction
2. exactly **one** host — a comma in the netloc is refused
3. the host **round-trips**, and is loopback or a percent-encoded unix socket path
4. every query option is on an **allowlist**, matched case-insensitively
5. `directConnection=true` is **forced on the client**, so discovery cannot widen the connection

Points 1–4 constrain the URI; **point 5 is the one that constrains the driver**, and without it the
first four are decoration.

**Rules 3 and 4 are round-2 findings on the code that answered round 1.** The first version checked
the parsed hostname, which reads `mongodb://[::1].evil.example` as `::1` and drops the rest — the
same hole CI had caught in `server.py` two changes earlier. And it *refused two option names*, which
a seat broke twice over: `?proxyHost=attacker.example&proxyPort=1080` keeps the seed loopback and
sends the whole connection through somebody else's SOCKS proxy, and `?replicaset=rs0` walked past a
check that refused `replicaSet=rs0`. A denylist answers "safe" about every option nobody thought of,
which is the same defect as the host check one field over.

`--store-remote allow` skips all five and records a `relaxation` turn **in the document itself**.
Fable-seat found why that matters: `export` runs outside any walk, so `RunReport.relaxations` does
not exist at the moment the relaxation is used, and a mechanism whose name outlives its availability
records nothing.

**Out of scope, said plainly:** an SSH tunnel to a remote mongod is loopback at the socket and
remote at the destination, and nothing in a URI can tell. The server's own loopback bind cannot stop
a tunnel either. The threat model is config-borne exfiltration — a URI somebody pasted — not a
determined operator.

## 5 · Export

`export_conversation(document, fmt)` for `json`, `markdown`, `csv`. The operator picks; there is no
default that quietly loses information.

- **json** — the document as stored. The only lossless form.
- **markdown** — for reading. The fence is **as long as the longest run of backticks in the content
  plus one**, minimum three: fable-seat found that an answer containing ``` ends the fence early,
  and "for reading" is this format's whole claim.
- **csv** — one row per turn, a fixed column set, nested values as JSON text in cells whose column
  names end `_json`. Three things the first brief had wrong or missing:
  - **Formula injection.** Cell text is model-produced. A cell beginning `=`, `+`, `-`, `@`, tab or
    CR executes when opened in a spreadsheet, and `=HYPERLINK(...)` is an exfiltration channel — in
    a local-only project, reached through the export whose stated purpose is to be opened in a
    spreadsheet. Every cell is defused with a leading apostrophe.
  - **Excel truncates at 32,767 characters, silently.** A work order in one cell passes that
    routinely. The data is written whole; an `over_spreadsheet_cell_limit` column flags every row
    where a reader's spreadsheet will lose the end of it.
  - **CSV has no comments.** "Say in the export that it is lossy" has no in-band mechanism — a note
    row is a data row. The `_json` suffixes and that flag column are the notice.

## 6 · What is deliberately not done

- **No redaction.** A work order carries whatever the operator put in it. Scrubbing patterns would
  be a coarse check answering "safe" about content it had not examined.
- **No claim about permissions.** The first brief said "owner-only where the platform offers them",
  which fable-seat correctly called one sentence doing safety work for three backends and holding
  for at most one: `chmod 0600` does little on Windows, and for `mongo` the runner sets nothing at
  all — the protection is the mongod's auth, typically none on localhost. So: the `file` backend is
  created `0700` best-effort, and the documentation says the store is **as sensitive as the journal
  already sitting beside it** and no better protected.
- **A failed store write never fails a run** — and is never silent. Two channels, both real:
  a line on **stderr at the moment of failure**, which is the one that survives a crash, and
  **`RunReport.store_errors`** printed at the end of the run. A `note` turn is *not* attempted: the
  store that would hold it is the one that just failed, and writing the record of a failure into
  the thing that failed is not a channel.

  Round 2 found the first code had none of them — the failures went into a list, the docstring named
  three channels, and nothing wrote to stderr or printed the field. That is "must not be silent"
  naming no mechanism, which is exactly the round-1 finding this bullet was written to answer,
  reappearing one layer down.
- **No concurrent writers.** One runner per conversation, stated in §3.
