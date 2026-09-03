# Every schema in this design

One page, so that "what shape is this?" never needs a code read. Each entry names the file that
**defines** it — that file is authoritative, this page is a map.

**Five** schemas are **closed**: a field outside them is refused rather than ignored, because a
setting that looks configured and does nothing is worse than one that was rejected. Revision 1 of
this page said *"two"* in this sentence while its own table marked *three*, and the true number was
four — `settings.py` enforces closedness and was not credited. A catalogue of closedness that
miscounts its own subject is the thing it warns about, so the count is now checked by
[`tests/test_schemas.py`](../tests/test_schemas.py) rather than asserted here.

| # | Schema | Defined in | Status |
|---|---|---|---|
| 1 | Node | [`graph.py`](../src/ai_sdlc_runner/graph.py) | shipped |
| 2 | Plan file | [`plan.py`](../src/ai_sdlc_runner/plan.py) | shipped · **closed** |
| 3 | Node spec | [`workorder.py`](../src/ai_sdlc_runner/workorder.py) | shipped · **closed** |
| 4 | Operation | [`policy.py`](../src/ai_sdlc_runner/policy.py) | shipped |
| 5 | Work order | [`workorder.py`](../src/ai_sdlc_runner/workorder.py) | shipped · **closed** |
| 6 | Answer contract | [`examples/minimal/agent.py`](../examples/minimal/agent.py) | shipped |
| 7 | Ask journal entry | [`engine.py`](../src/ai_sdlc_runner/engine.py) | shipped |
| 8 | Conversation document + turn | [`conversations.py`](../src/ai_sdlc_runner/conversations.py) | shipped |
| 9 | Export formats — CSV columns, HTML stops | [`conversations.py`](../src/ai_sdlc_runner/conversations.py) | shipped |
| 10 | Model registry | [`models.py`](../src/ai_sdlc_runner/models.py) | shipped · **closed** |
| 11 | Settings | [`settings.py`](../src/ai_sdlc_runner/settings.py) | shipped · **closed** |
| 12 | Attachment manifest | [`attachments.py`](../src/ai_sdlc_runner/attachments.py) | shipped |
| 13 | Run report | [`engine.py`](../src/ai_sdlc_runner/engine.py) | shipped |
| 14 | **SQLite DDL** | [`DATABASE.md`](DATABASE.md) | 6 of 6 tables **built** |
| 15 | **Server HTTP API** | [`API.md`](API.md) | shipped |
| 16 | **Model management** — rules, reach, assignment | [`MODELS.md`](MODELS.md) | shipped |

---

## 1 · Node — the flow

31 of these, one kind of work each. `validate()` enforces cross-rules over them — the count is not
stated here because no partition of that function yields the number revision 1 claimed, which a seat
checked and could not reproduce. A decorative number is a small lie about a real mechanism.

```python
id: str                     # unique
kind: str                   # what sort of node
label: str
role: Optional[str]         # who is asked; None ⟺ mode == RUNNER
gate: Optional[str]         # which of the 10 gates fires here
gate_when: str              # "before" | "after"
next: Optional[str]         # the single successor
branches: Dict[str, str]    # branch label -> node id
answer_decides: bool        # the answer picks the branch
panel_branches: Dict[str, str]  # a PANEL's pass/fail -> this node's own branch words
permanent: bool            # this terminal is a give-up, not an ending
grades_risk: bool           # this node's voices answer with a risk grade, not a branch
settles_risk: bool          # passing this node makes the proposed grade the run's grade
mode: str                   # one of MODES — DECLARED, never inferred from the name
main: Optional[str]         # a ROLE, for pool dispatch
follows: Optional[str]      # a NODE ID, for FOLLOWS mode
rejects_to: Optional[str]   # where a refusal sends the run
note: str
```

**`MODES`** — `runner`, `single`, `seat_panel`, `model_panel`, `pool`, `follows`, `survey`.
`survey` is the only mode that reaches **no verdict**: it is a union of answers, not an adjudication.

Two biconditionals `validate()` checks rather than infers:
`role is None ⟺ mode == RUNNER`, and `role == "seat" ⟺ mode in (SEAT_PANEL, SURVEY)`.

## 2 · Plan file — **closed**

Closed at **two** levels: the top, and the `ship` block inside it. Unknown keys are refused, and so
is a key of the right name holding the wrong shape — `"node_specs": []` reads as configured and
supplies nothing.

It was the outermost schema and the only entry point with **no validation at all**, named by six
independent seat reviews. The case that decided it: *a plan whose `ship` key is misspelled runs with
no side effects and reports `finished`* — a dry run wearing a shipped run's report, produced by one
typo nothing refused.

`ship`'s four indexed keys — `repo`, `chg_id`, `branch`, `message` — are required, because leaving
one out was a `KeyError` partway through a run rather than a refusal before it started.

```jsonc
{
  "risk": "low|medium|high",
  "autonomy": "…",              // tighten-only
  "node_specs":  { "<node id>": { …schema 3… } },   // 15 needed; the walk stops at the first missing
  "operations":  { "<node id>": [ …schema 4… ] },   // every node that can act, seats included
  "decisions":   { "<node id>": "<branch>" },
  "node_models": { "<node id>": ["<model id>", …] },
  "seat_models": { "<seat>": ["<model id>", …] },
  "ship": {
    "repo": ".", "chg_id": "CHG-…", "branch": "…", "message": "…",   // required
    "chg_body": "…", "remote": "origin",
    "task": "…", "acc_id": "ACC-…", "acc_body": "…"                  // optional
  }
}
```

## 3 · Node spec — **closed by key set, open by type**

Per change, supplied by the caller. None of it can come from the governance definitions.

```
scope · objective · instructions · done_criteria · acceptance_predicate
input_artifacts · expected_outputs · idempotence_probes · workdir
```

`workorder._check` refuses a missing key **and** an extra one. It does not check **types**, and one
of them bites. `instructions` is legally a string in some plans and a list in others — both are in
use — and `render` calls `str()` on it, so a list reaches the model as a Python repr:

```
type sent to the model: str
value : '[\'step one\', "step two: don\'t"]'
```

Mixed quoting, not JSON and not prose, in the order's most important field. A value the schema
permits and the renderer cannot carry honestly. **Not yet fixed** — it needs a decision about which
type is canonical, and that changes every plan in use.

## 4 · Operation — what a node will actually do

```jsonc
{ "description": "write one module file",
  "kind": "ordinary",            // or one of the six permanent-halt kinds
  "targets": ["greet.py"] }      // commands, paths, URLs
```

**The six never-automated kinds**, each stopping at *every* risk grade:

| kind | |
|---|---|
| `deploy` | production deploy or release |
| `migration` | data migration or irreversible schema change |
| `delete` | deleting data, dropping a table, any hard delete |
| `money` | moving money |
| `access` | changing secrets, credentials, access control or permissions |
| `publish` | publishing public content |

A node declaring nothing is **refused**, not assumed safe — `--undeclared allow` overrides and
records itself as a relaxation.

## 5 · Work order — **closed**

What every ask receives on stdin. Identical for every voice on a panel; only the answerer differs.

```
node_id · node_label · role · role_label · seat
scope · objective · instructions · done_criteria · acceptance_predicate
input_artifacts · expected_outputs
policy_verdict · capabilities · permanent_halts · idempotence_probes · workdir
```

`policy_verdict` has its own fixed shape: `gate · risk · verdict · source · tightened`.

`source` carries **two facts concatenated into one string** — where the verdict came from, and any
refused loosening. A consumer cannot separate them mechanically. Acknowledged in `policy.py` and
recorded here rather than left to be rediscovered.

## 6 · Answer contract — what a dispatched agent prints

JSON on stdout. A non-zero exit is a failed attempt.

| The node | must answer |
|---|---|
| a decision node | `{"verdict": "<branch>"}` — one the node offers |
| `pm_plan` | `{"modules": [...]}` when `next_module` is `"frontier"` |
| `engineer_build` | `{"module": "<id>"}` |
| a seat on a panel | `{"verdict": "pass"\|"fail", "why": "…"}` |
| a seat at intake | `{"missing": [...], "problems": [...], "unsafe": [...]}` |
| anything else | any JSON object |

**Three names for one fact.** `_answered_branch` reads `answer.get("branch") or
answer.get("verdict") or answer.get("outcome")` — `branch` wins silently, so an answer carrying two
of them that disagree resolves to whichever is first, with nothing said. Seat verdicts accept
`verdict` or `outcome` the same way. `examples/minimal/agent.py` documents only `verdict`.

And `engineer_build`'s `{"module": ...}` is **not enforced**: an answer that omits it never shrinks
the frontier, so the run loops to `max_steps` and dies 200 steps from the cause.

## 7 · Ask journal entry

One file per ask, written **before** the ask. A resume index, keyed by position — **mutable by
design**, and it overwrites.

```jsonc
{ "ask_id": "000-pm_plan", "node_id": "pm_plan", "seat": null,
  "status": "pending|answered", "order": { …schema 5… }, "result": { … } }
```

**It carries no model and no operator turn.** That is why the conversation store is not derived
from it.

## 8 · Conversation document + turn

JSON Lines: a header line, then one line per turn. Append-only, never rewritten.

```jsonc
// header
{ "header": { "schema": 1, "conversation_id": "<32 hex>",
              "project": { "id": "<sha256(name)[:32]>", "name": "<as given>" },
              "run": { "journal": "…", "plan": "…" } } }

// every turn
{ "seq": 0, "kind": "<one of 9>", "at": "<ISO 8601 UTC>", …body… }
```

`seq` is an **integer**, never a zero-padded name — the journal sorts filenames and `'%03d' % 1000`
lands between the 100th and the 101st.

**A body may not name `seq`, `kind` or `at`.** It could until a seat read `Turn.as_dict`, which
spread the body *after* the envelope: `turn("note", seq=999, at="not-a-time")` stored a turn whose
identity disagreed with the number allocated and the time recorded. `kind` survived only because
Python raises `TypeError` on the keyword collision — luck, not schema. A log whose payload can
rewrite its envelope cannot be ordered, deduplicated or dated, which is all a log is for. The
collision is now refused **to the caller**, ahead of `_guarded`, because it is a bug in the caller
rather than an archival failure.

The per-kind bodies below are **convention, not schema**: nothing yet enforces required or typed
body fields per kind.

| kind | body |
|---|---|
| `opened` | `project`, `run` |
| `instruction` | `nth`, `text` |
| `ask` | `ask_id`, `node_id`, `role`, `seat`, `model`, `order` |
| `answer` | `ask_id`, `model`, **`backend`**, `result` |
| `unanswered` | `ask_id`, `why` |
| `decision` | `decision` (`approval`/`rejection`/`ruling`), `at_node`, `why`, `who` |
| `relaxation` | `text` |
| `note` | `text` |
| `closed` | `state` (`finished`/`suspended`/`stopped`), `at_node`, `why`, `risk`, `change_class` |
| `review` | `by`, `note` — an operator saying they looked at an `emergency` run afterwards |

`model` is what was **asked for**; `backend` is what **answered**. They come apart on a seat panel,
which routes by seat name and passes no model at all.

A reader may add `incomplete_lines` (a torn write) and `duplicate_seqs` (what `file` can report but
not refuse).

## 9 · Export formats — four, and only one of them lossless

```
seq · at · kind · node_id · ask_id · role · seat · model
text_or_state · body_json · over_spreadsheet_cell_limit
```

`_json` suffixes and the flag column **are** the "this is lossy" notice — CSV has no comments, and a
note row is a data row to every consumer. Every cell is defused against formula execution.

`FORMATS = ("json", "markdown", "csv", "html", "playback")`, and `--format` is **required**: a
default would decide for you which information you lose.

| | keeps | loses |
|---|---|---|
| `json` | everything | — |
| `markdown` | every turn, in order | the envelope, and the shape of the walk |
| `html` | every turn *and* the shape of the walk | nothing, but it is a page rather than data |
| `playback` | the shape *and* the duration | exact timings — the clock is compressed, and the page says so |
| `csv` | the columns above | nested bodies, past the cell limit |

The **HTML** export groups turns into *stops*: consecutive turns at one `node_id`. Consecutive, not
gathered — a node revisited later is a **second** stop, and merging the two would hide the loop
the format exists to show.

An `answer` carries `ask_id` and no `node_id`, so its node is read back out of the `NNN-node_id[-seat]`
form of the id. Without that, every ask/answer pair splits in two: 53 stops for 55 turns, a list
wearing a waterfall's markup.

Three voices, from `kind`: `runner` (`ask`, `opened`, `closed`, `relaxation`, `note`), `model`
(`answer`, `unanswered`), `operator` (`instruction`, `decision`, `review`). Model-written text is escaped on
the way in — the same reason CSV cells are defused against formulas.

## 10 · Model registry — **closed**, entry *and* envelope

Eight fields persist. `_model_from` refuses anything else by name — and so, now, does the envelope.
A seat found that `{"models": [], "modelz": [...]}` loaded as an **empty registry**: one typo and
every model you configured was gone with no message, which is the same defect `_model_from` refuses
one level down. Closed on every path in: file load, `Registry.add`, and the console's
`POST /models`.

```jsonc
{ "models": [ { "id": "…", "vendor": "…", "name": "claude-opus-5",
                "transport": "cli|api",
                "command": ["claude", "-p"],     // argv as a LIST, never re-split by a shell
                "endpoint": "https://…",         // api only
                "key_env": "ANTHROPIC_API_KEY",  // the NAME of an env var. Never a key.
                "note": "" } ] }
```

**`reach` and `leaves_this_machine` are computed, never stored** — `local` / `internal` / `external`,
derived from `(transport, endpoint)` on every load. `save()` strips them: *"storing them would let a
stale label outlive the truth."*

## 11 · Settings — **closed**

`settings.py` refuses unknown keys and wrong types with the same doctrine as the registry. It was
closed all along and revision 1 of this page did not say so.

```jsonc
{ "review_seats": null,          // null = the floor (3)
  "high_risk_mode": false,       // may the floor be crossed at all
  "ordinary_commands": [] }      // tools the operator vouches for — the TOOL, never a command line
```

## 12 · Attachment manifest

```jsonc
{ "id": "<sha256, all 64 chars>",   // identity
  "filename": "spec.pdf",           // data, NEVER a path
  "media_type": "application/pdf", "size": 12345, "instruction": 1 }
```

**The id is the full 64-character digest; the stored filename is `stored_name(id) = id[:32]`.**
They are not the same string:

```
id (full digest) len: 64
stored filename  len: 32
equal? False
```

Revision 1 of this page said the id *was* the filename. It was false about the field the entry
leads with, and anyone joining manifest ids to stored files off that line would have written a bug.
`attachments.py` says it plainly — *"The id stays the full digest, because identity is not the thing
under pressure here; only the filename is."*

## 13 · Run report

`visited · asks · state · suspended · halted_at · halt_reason · relaxations · verdicts · on_trust ·
confirmations · adjudications · single_model_panels · effects · resumed · dispatches · survey ·
options · panel_rounds · send_backs · rejections · rulings · store_errors · change_class ·
relaxations_by_class · risk_proposed · risk_settled · risk_agreed · halts ·
class_authorised_by ·
relaxation_authorisers`

`relaxation_authorisers` maps each note in `relaxations_by_class` to **who pre-authorised that
gate** (CHG-20260903-41). `class_authorised_by` beside it is one name for the whole run, read from
the run-level `--change-class` — which the CLI *refuses* over a split programme, so on the one
shape the per-workstream form exists for it is always empty. A gate belonging to no workstream
carries every authoriser, comma-separated, because it relaxed only if every workstream was
pre-authorised.

The last six were declared on `RunReport`, written during the walk, and emitted by nothing until
CHG-20260901-16 — so they reached no `--json`, no entry here, and no console, and lived only in
`cmd_run`'s stdout footer. The guard over this entry checked *emitted ⊆ documented*, which a field
passes for free by never being emitted;
`test_the_report_emits_every_field_it_declares` now checks the other direction.

Three states: `finished` (reached a terminal), `suspended` (a decision continues it), `stopped`
(nothing continues it).

The **dataclass** does not enforce membership — `RunReport(state="banana")` constructs and
`as_dict()` emits it. `_finish` refuses on every walk exit, so it is enforced at the boundary that
matters and not by the type.

## 14 · SQLite DDL — three of five tables built

The full schema, with every absent column and the finding that removed it, is
**[`DATABASE.md`](DATABASE.md)** — pinned by `tests/test_database_schema.py`, which executes the
page's SQL verbatim and tries to violate each constraint. Summary below.

Which pragmas persist, measured rather than assumed — set all five, close, reopen:

```
journal_mode     wal        <- the FILE's
user_version     7          <- the FILE's
foreign_keys     0          <- per connection: RESET
synchronous      2          <- per connection: RESET (to FULL)
busy_timeout     5000       <- per connection
```

**Three are per-connection, two are the file's.** Revision 1 of this page said *"two are
per-connection state, one is the file's"* — wrong on both counts, in the block whose subject is
pragmas that lie. `foreign_keys` and `synchronous` must be set on **every** connection or the
`REFERENCES` clause enforces nothing and the documented durability level is not the one running.

```sql
-- Per connection, every time: foreign_keys, synchronous, busy_timeout.
-- Written into the file once: journal_mode, user_version.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;      -- OFF by default, per connection. Without it REFERENCES is decorative.
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;   -- process crash: safe. Power loss: last transactions may roll back.
PRAGMA user_version = 1;       -- database schema version; ordered migrations

CREATE TABLE conversations (
  conversation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, project_name TEXT NOT NULL,
  schema INTEGER NOT NULL, run_json TEXT NOT NULL);

CREATE TABLE turns (
  conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
  seq INTEGER NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL,
  body_json TEXT NOT NULL,                    -- ONLY the body: never seq/kind/at
  PRIMARY KEY (conversation_id, seq));        -- a REAL refusal of a duplicate turn

CREATE TABLE models (
  id TEXT PRIMARY KEY, vendor TEXT NOT NULL, name TEXT NOT NULL, transport TEXT NOT NULL,
  command_json TEXT NOT NULL DEFAULT '[]', endpoint TEXT NOT NULL DEFAULT '',
  key_env TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '');
```

`models`, `node_assignments` and `seat_assignments` are live in
[`store.py`](../src/ai_sdlc_runner/store.py); `conversations` and `turns` are not created by any
code yet and arrive with the conversation-store migration.

No `reach` column, no `updated_at`, and **no `opened_at`** — the third one is this round's finding.
Both earlier seats called `opened_at` a guess and the correction deleted `updated_at` while keeping
it. Nothing in the code reads an open timestamp, so it is the same dead-column class; worse, it is a
**second copy of the OPENED turn's `at`** — the "two truths" the `turns` comment forbids eight lines
above it — minted at a different moment on the live path, and forced equal only on import. If a
listing ever needs an open time, it is the OPENED turn's `at`, one query away.

No `json_extract` anywhere — every query is by `conversation_id`, `project_id` or `seq`, so JSON1 is
never load-bearing and Python 3.9's bundled SQLite never has to be asked.

### Still open on the DDL

**A resumed run whose store read failed resets `_seq` to 0.** Against the file backend that produces
duplicate `seq` values the reader *reports*. Against a primary key, every turn of that run is
**refused** and swallowed into `write_errors` — the whole resumed conversation lost to stderr. The
duplicate-`seq` policy is written down for the importer and not for the live path.


---

## 15 · Server HTTP API

Seventeen routes, eight `GET` and nine `POST`, every one crossing a process boundary to a browser.
Written down in **[`API.md`](API.md)** and pinned by `tests/test_api_schema.py`.

The three-check guard that runs before every route — loopback `Host`, then `Origin`, then
`X-Operator-Token` — and the two deliberate token exemptions are documented there, in that order,
because the order is the property.

## 16 · Model management

Entry 10 is the model **shape**. [`MODELS.md`](MODELS.md) is the part that governs it — every
refusal `validate()` makes, how `reach` is computed from `(transport, endpoint)` and why an operator
must never label it themselves, and how a model gets from the registry to an actual ask through
`node_models`, `seat_models` and the factory's resolution order.

One thing it records that appears nowhere else: **an `api` model validates, lists, and cannot be
dispatched to.** The first ask routed to one raises, because this runner dispatches by running a
command. The refusal is right — the alternative is sending the work to the default and reporting it
as the named model — but `transport: "api"` is a declaration the runner cannot yet honour.

## What this catalogue does **not** cover

Named, because a map that silently omits territory is worse than one that marks it blank. Both seats
found these independently.

| Missing | Why it matters |
|---|---|
| ~~The server HTTP API~~ | **written down** — [`API.md`](API.md), seventeen routes, pinned by `tests/test_api_schema.py` |
| **`runner.yaml`** — `agent_command`, `agent_timeout` | durable config with a hand-rolled fallback parser that has already shipped one bug (the inline-list split) |
| **`RunConfig`** | the engine's real input contract, substantially wider than the plan file the catalogue shows |
| **`Approval` / `Rejection` / `Ruling`** | operator decisions crossing the server→engine boundary; the catalogue has their flattened conversation turns, not their input shapes |
| **The `.conversation` marker** and **`_project.json`** | durable, and the marker is load-bearing at resume — stale data there controls re-attachment |
| **`EffectOutcome`** — `frontier`, `already_met`, `applied`, `out_of_order` | durable report output with a fixed shape |
| **The intake `Survey` aggregate** | crosses the agent→operator boundary and lands in the run report; adds a computed `complete` absent from the answer contract |
| ~~The `ship` block's interior~~ | **closed** — nine fields, four of them required |

### Versioning

**Only the conversation document carries a version**, and even that is written rather than checked.
Plans, answer envelopes, ask journals, the registry, settings, attachment manifests and run reports
all persist or cross a process boundary, and none of them can say which shape they are.

### The one that produced all of the above

Nothing pinned this page. `tests/test_documented_numbers.py` pins the README's counts, flags and
examples; **the schema catalogue had no test at all**, and drifted in three checkable ways within a
day of being written — the attachment id, the closed count, and the pragma arithmetic.
[`tests/test_schemas.py`](../tests/test_schemas.py) now pins what is checkable. The rest is prose,
and prose is not run.

`playback` renders the same stops as `html` — they share `_stops()`, and a test asserts they agree,
because two renderings of one run that disagree about its shape make both untrustworthy.

Its clock is **legible rather than literal, and says which on the page**: a turn plays for at least
`MIN_BEAT` (0.35s) however fast it was, and a pause over `IDLE_CAP` (2s) plays as 2s with its real
length named. A turn whose `at` will not parse gets a beat, never an invented duration.

Model text is escaped for **script context** here, not markup: `<`, `>`, `U+2028`, `U+2029` at the
JSON level. A literal `</script>` inside an answer ends the block early and the rest of the payload
parses as page content — and a model writes that sequence the moment it is asked about HTML.
