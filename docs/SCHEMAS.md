# Every schema in this design

One page, so that "what shape is this?" never needs a code read. Each entry names the file that
**defines** it — that file is authoritative, this page is a map.

Two schemas are **closed**: a field outside them is refused rather than ignored, because a setting
that looks configured and does nothing is worse than one that was rejected.

| # | Schema | Defined in | Status |
|---|---|---|---|
| 1 | Node | [`graph.py`](../src/ai_sdlc_runner/graph.py) | shipped |
| 2 | Plan file | [`cli.py`](../src/ai_sdlc_runner/cli.py) | shipped |
| 3 | Node spec | [`workorder.py`](../src/ai_sdlc_runner/workorder.py) | shipped · **closed** |
| 4 | Operation | [`policy.py`](../src/ai_sdlc_runner/policy.py) | shipped |
| 5 | Work order | [`workorder.py`](../src/ai_sdlc_runner/workorder.py) | shipped · **closed** |
| 6 | Answer contract | [`examples/agent.py`](../examples/agent.py) | shipped |
| 7 | Ask journal entry | [`engine.py`](../src/ai_sdlc_runner/engine.py) | shipped |
| 8 | Conversation document + turn | [`conversations.py`](../src/ai_sdlc_runner/conversations.py) | shipped |
| 9 | CSV export columns | [`conversations.py`](../src/ai_sdlc_runner/conversations.py) | shipped |
| 10 | Model registry | [`models.py`](../src/ai_sdlc_runner/models.py) | shipped · **closed** |
| 11 | Settings | [`settings.py`](../src/ai_sdlc_runner/settings.py) | shipped |
| 12 | Attachment manifest | [`attachments.py`](../src/ai_sdlc_runner/attachments.py) | shipped |
| 13 | Run report | [`engine.py`](../src/ai_sdlc_runner/engine.py) | shipped |
| 14 | **SQLite DDL** | [`sqlite-only.md`](design/sqlite-only.md) | **proposed, not built** |

---

## 1 · Node — the flow

24 of these, one kind of work each. `validate()` enforces eight cross-rules over them.

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

## 2 · Plan file

```jsonc
{
  "risk": "low|medium|high",
  "autonomy": "…",              // tighten-only
  "node_specs":  { "<node id>": { …schema 3… } },   // 15 needed; the walk stops at the first missing
  "operations":  { "<node id>": [ …schema 4… ] },   // every node that can act, seats included
  "decisions":   { "<node id>": "<branch>" },
  "node_models": { "<node id>": ["<model id>", …] },
  "seat_models": { "<seat>": ["<model id>", …] },
  "ship": { … }
}
```

## 3 · Node spec — **closed**

Per change, supplied by the caller. None of it can come from the governance definitions.

```
scope · objective · instructions · done_criteria · acceptance_predicate
input_artifacts · expected_outputs · idempotence_probes · workdir
```

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
| `closed` | `state` (`finished`/`suspended`/`stopped`) |

`model` is what was **asked for**; `backend` is what **answered**. They come apart on a seat panel,
which routes by seat name and passes no model at all.

A reader may add `incomplete_lines` (a torn write) and `duplicate_seqs` (what `file` can report but
not refuse).

## 9 · CSV export columns — fixed

```
seq · at · kind · node_id · ask_id · role · seat · model
text_or_state · body_json · over_spreadsheet_cell_limit
```

`_json` suffixes and the flag column **are** the "this is lossy" notice — CSV has no comments, and a
note row is a data row to every consumer. Every cell is defused against formula execution.

## 10 · Model registry — **closed**

Eight fields persist. `_model_from` refuses anything else by name.

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

## 11 · Settings

```jsonc
{ "review_seats": null,          // null = the floor (3)
  "high_risk_mode": false,       // may the floor be crossed at all
  "ordinary_commands": [] }      // tools the operator vouches for — the TOOL, never a command line
```

## 12 · Attachment manifest

```jsonc
{ "id": "<sha256[:32]>",   // ALSO the stored filename — no extension, nothing a scanner reads
  "filename": "spec.pdf",  // data, NEVER a path
  "media_type": "application/pdf", "size": 12345, "instruction": 1 }
```

## 13 · Run report

`visited · asks · state · suspended · halted_at · halt_reason · relaxations · verdicts · on_trust ·
confirmations · adjudications · single_model_panels · effects · resumed · dispatches · survey ·
options · panel_rounds · send_backs · rejections · rulings · store_errors`

Three states: `finished` (reached a terminal), `suspended` (a decision continues it), `stopped`
(nothing continues it).

## 14 · SQLite DDL — **proposed, not built**

From [`sqlite-only.md`](design/sqlite-only.md). Nothing here exists in code.

```sql
-- Set on EVERY connection: two are per-connection state, one is the file's.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;      -- OFF by default, per connection. Without it REFERENCES is decorative.
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;   -- process crash: safe. Power loss: last transactions may roll back.
PRAGMA user_version = …;       -- database schema version; ordered migrations

CREATE TABLE conversations (
  conversation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, project_name TEXT NOT NULL,
  schema INTEGER NOT NULL, run_json TEXT NOT NULL, opened_at TEXT NOT NULL);

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

No `reach` column, no `updated_at`. No `json_extract` anywhere — every query is by
`conversation_id`, `project_id` or `seq`, so JSON1 is never load-bearing and Python 3.9's bundled
SQLite never has to be asked.
