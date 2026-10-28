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
| 6 | Answer contract | [`engine.py`](../src/ai_sdlc_runner/engine.py) — carried in every order's `reply` | shipped |
| 7 | Ask journal entry | [`engine.py`](../src/ai_sdlc_runner/engine.py) | shipped |
| 8 | Conversation document + turn | [`conversations.py`](../src/ai_sdlc_runner/conversations.py) | shipped |
| 9 | Export formats — CSV columns, HTML stops | [`conversations.py`](../src/ai_sdlc_runner/conversations.py) | shipped |
| 10 | Model registry | [`models.py`](../src/ai_sdlc_runner/models.py) | shipped · **closed** |
| 11 | Settings | [`settings.py`](../src/ai_sdlc_runner/settings.py) | shipped · **closed** |
| 12 | Attachment manifest | [`attachments.py`](../src/ai_sdlc_runner/attachments.py) | shipped |
| 13 | Run report | [`engine.py`](../src/ai_sdlc_runner/engine.py) | shipped |
| 14 | **SQLite DDL** | [`DATABASE.md`](DATABASE.md) | 7 of 7 tables **built** |
| 15 | **Server HTTP API** | [`API.md`](API.md) | shipped |
| 16 | **Model management** — rules, reach, assignment | [`MODELS.md`](MODELS.md) | shipped |

---

## 1 · Node — the flow

34 of these, one kind of work each. `validate()` enforces cross-rules over them — the count is not
stated here because no partition of that function yields the number revision 1 claimed, which a seat
checked and could not reproduce. A decorative number is a small lie about a real mechanism.

```python
id: str                     # unique
kind: str                   # what sort of node
label: str
role: Optional[str]         # who is asked; None ⟺ mode == RUNNER
gate: Optional[str]         # which of the 10 gates fires here
gate_when: Optional[str]    # "before" | "after"; None ⟺ gate is None
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
audit: Optional[str]        # "read" | "dispose" | "decide": which step of the whole-change audit this is
note: str
```

**`MODES`** — `runner`, `single`, `seat_panel`, `model_panel`, `pool`, `follows`, `survey`.
`survey` is the only mode that reaches **no verdict**: it is a union of answers, not an adjudication.

Two biconditionals `validate()` checks rather than infers:
`role is None ⟺ mode == RUNNER`, and `role == "seat" ⟺ mode in (SEAT_PANEL, SURVEY)`. A node with an
`audit` step is one auditor session (`audit` is `read` or `dispose`: role `auditor`, mode `SINGLE`) or the
runner's decision (`decide`: mode `RUNNER`, a `DECISION` with `pass` and `fail` branches), and the
`auditor` role appears at no other node.

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

What every ask receives on stdin. Identical for every voice on a model panel; the seats of a seat
panel differ in `seat` and `instructions` only. The answerer is the rest of the difference.

```
node_id · node_label · role · role_label · seat
scope · objective · instructions · done_criteria · acceptance_predicate
input_artifacts · expected_outputs
policy_verdict · capabilities · permanent_halts · idempotence_probes · workdir
reply
```

`policy_verdict` has its own fixed shape: `gate · risk · verdict · source · tightened`.

`reply` has its own fixed shape too: `format · schema · unattended` (CHG-20260925-01). `format`
and `unattended` are two fixed sentences (`workorder.REPLY_FORMAT`, `workorder.REPLY_UNATTENDED`).
`schema` is the answer's **JSON Schema, in a closed subset**: exactly `type: "object"`,
`properties`, `required` and `additionalProperties: false`; each property is `type: "string"`
(with an optional `enum`) or `type: "array"` of strings (with optional `enum` items, `minItems`
and `uniqueItems: true`) **or of closed objects** (CHG-20261028-01: `type: "object"` with exactly
`properties`, `required` and `additionalProperties: false`, each field a string with an optional
`enum` and no `description`), and always has a `description`. Every schema offers `why` (text), which
no router reads. `workorder.reply` refuses anything outside the subset. `required: []` says
nothing in the answer is acted on.

`source` carries **two facts concatenated into one string** — where the verdict came from, and any
refused loosening. A consumer cannot separate them mechanically. Acknowledged in `policy.py` and
recorded here rather than left to be rediscovered.

## 6 · Answer contract — what a dispatched agent prints

One JSON object on stdout. A non-zero exit is a failed attempt.

**The order states it.** `reply.schema` (§5) is computed per ask by `engine._answer_schema`, from
the path the ask was dispatched on and from the readers' own constants, so the table below is what
an order says rather than a second copy of it to keep in step (`required` keys named; `why` is
always offered):

| The ask | `reply.schema` |
|---|---|
| a decision node, one voice | `verdict` ∈ the node's branches — read by `_answered_branch` |
| a decision node, a panel of models | `verdict` ∈ `pass`/`fail`/`undecided` — `policy.adjudicate` |
| a `grades_risk` node, a panel of models | `risk` ∈ `low`/`medium`/`high` — `policy.adjudicate_grade` |
| a seat on the review panel | `verdict` ∈ `pass`/`fail`/`undecided` — `policy.adjudicate`; and `findings`, a list of findings — `policy.read_findings` (below) |
| `audit_read`, the auditor reading blind | `findings`, in a finding's shape (below) — `policy.read_findings`; no verdict |
| `audit_dispose`, the auditor in a new session | `dispositions`, one row per finding id — `policy.read_dispositions` (below); no verdict on the change |
| a seat at intake | `missing` (aspect ids), `problems`, `unsafe` — the order requires all three; `intake.collect` still accepts **at least one**, for backends written before it |
| the intake option ask | `options`, at least 3 distinct — `intake.read_options` |
| `engineer_build` | `module`, and `error` for a build that failed — `_stop_on_failed_build`, `_module_built`, `_frontier` |
| `pm_plan`, with a `"frontier"` decision | `modules` — `_frontier` |
| every other ask | `required: []` — nothing acted on; `why` still offered |

**A finding** (CHG-20261028-01) is what a review seat saw, as an object of exactly
`{id, file, line, claim, trigger, severity, origin}`, all required, read by `policy.read_findings`:

| Key | Meaning |
|---|---|
| `id` | the seat's own label, unique within one answer; the run's id for it is `<seat>:<id>` |
| `file`, `line` | where the problem is. **Required and non-blank**; `line` is a positive integer written as digits (a reply schema has no number type). A finding without a location is refused and stops the run, because it can be neither passed on nor disposed |
| `claim` | what is wrong |
| `trigger` | the concrete input and the wrong result it produces. May be empty — but **a finding with no `trigger` can never be `important`**: it is recorded as a `nit` and `severity_said` keeps the word the seat used |
| `severity` | `important` or `nit` (`policy.SEVERITIES`) |
| `origin` | `introduced` (this change caused it) or `pre-existing` (`policy.ORIGINS`) |

**A disposition** (CHG-20261028-01) is the auditor's answer about one finding, read by
`policy.read_dispositions`: `{id, disposition, file, line, evidence, input, result}`, all required.
`id` is the finding's id exactly as the findings file gives it; `disposition` is `confirm`, `refute`
or `cannot-verify`; `file` and `line` are where the evidence is, on every row. For a `refute`, `input`
and `result` are the concrete input and the right result it produces — a `refute` without both is read
as `cannot-verify`, and `disposition_said` keeps the word the auditor used. The findings file the
auditor reads is `<run directory>/audit/lap-NNN/findings.json`, written by the runner and named in
the order's `input_artifacts` by path; its scope is `scope.json` beside it.

The seat keeps its verdict: `policy.adjudicate` counts it exactly as before. Findings are not votes.
An answer that omits `findings` is read as none found, for backends written before it; the order
asks for the key, and `[]` is how a seat says it found nothing.

**The intake row is enforced, and the row above it is why it had to be.** A seat at intake and a
seat on a panel are one line apart in this table and answer with different shapes, and an agent
that did not notice — answering `{"verdict": "pass"}` at both — was counted at intake as having
looked and found nothing. `intake.collect` refuses an answer carrying none of the three now
(CHG-20260907-01), for the reason it already refuses an aspect it does not recognise: a survey
that treats silence as agreement is agreeing with a voice that did not speak.

Three empty lists is how a seat says it looked and found nothing. The reader accepts one of the
three; the order asks for all three.

**And the value has to be readable.** Each of the three is text, or a list of text. A number, a boolean or an object in any of them is refused by name
(CHG-20260907-03): reading it as text invents a finding nobody made, and dropping it loses one somebody did.

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
  "status": "pending|answered|refused", "order": { …schema 5… }, "result": { … },
  "voice": { "model": "opus" | null, "argv": ["claude", "-p"] | null,
             "brief_sha256"?: "<sha256>" },            // seat asks only
  "brief": { "sha256": "<sha256 of the brief file>",
             "file": "briefs/000-lead_review-defect.json" | null,
             "role": { "text": "…", "level": "model|seat|shared" } | null,
             "spec": { "kind": "text", "source": "inline|file", "path": "docs/x.md" | null,
                       "text": "…", "sha256": "<sha256 of text>",
                       "level": "model|seat|shared" } | null }
}                                                      // seat asks only
```

**`brief` is what a seat session was sent** (CHG-20261016-01). The brief is the work order exactly
as the process receives it, `workorder.to_json(order)` as UTF-8, kept byte for byte in
`briefs/<ask_id>.json` beside the entries (a subdirectory, so it is never read as an ask) with its
sha256 in the entry. A run with no ask journal keeps the same file in its own directory instead
(`runner run`: `.runner/briefs/<UTC time>-<id>/<ask_id>.json`), but writes no entry. `role`
and `spec` are the user's text in that brief with the level each came from, or `null`; both `null`
is a seat asked its own question and nothing more. `spec.text` is the text **copied when the walk
started**, so a spec file edited later leaves this entry as it was; `spec.sha256` is that text's
hash and `spec.path` the repository path when it came from a file. When a role or spec applies,
`voice.brief_sha256` is the brief's hash and a resume compares it with the rest of the voice, so a
changed role or spec re-asks that session; when neither applies `voice` is what it always was, which
is what lets a journal from before this change be resumed.

**`voice` is who a seat ask was put to** (CHG-20261005-02). `model` is the seat's model id for that
session, `null` for a seat with no model, which runs the default backend; `argv` is the command the
session factory resolves for it (for the default backend, the `agent_command`, or `null` when there
is none). A seat with several models has one entry per model, the ask id taking `-m<N>` (`N` the
model's position) after the seat: `004-lead_review-defect-m1`; a seat with one model or none keeps
`NNN-node-seat`. A resume reuses a journaled seat answer only when its `voice` equals the voice
about to be asked; an entry that differs, or has no `voice` (written before this field existed), is
asked again. An ask that is not a seat ask has no `voice`.

**Two order shapes can sit in one journal.** An entry written before CHG-20260925-01 has no `reply`.
A resumed run compares such an entry with the new order minus its `reply`; an entry that has a
`reply` is compared with `reply` reduced to the structure of its schema — no fixed sentence, no
description — so rewording never re-asks (`engine._same_question`, `_comparable`). Either way the
answer is reused only if the ask's own reader would accept it (`engine._heard`): a journal records
`answered` before any reader runs, so an answer the walk refused is asked again rather than replayed.
A failed build is journaled `refused` at its ask (`_stop_on_failed_build`), and so is an empty plan
under a `"frontier"` decision (`_stop_on_empty_plan`). **Once an entry asks the same question but its
answer is not reused, nothing journaled after it is reused either** — by position, so a panel's
other voices go too — and the journal forgets those entries (`AskJournal.forget_after`), so no
later walk reuses them: what was said later was said about the refused answer, and a journal an
older runner wrote past a failed build holds the self-check and the review of that failed attempt.
An entry whose question changed does not cut the rest; the later entries are still reused where
they ask the same.

**It carries no operator turn, and a model only through a seat ask's `voice`.** That is why the
conversation store is not derived from it.

## 8 · Conversation document + turn

JSON Lines: a header line, then one line per turn. Append-only, never rewritten.

```jsonc
// header
{ "header": { "schema": 1, "conversation_id": "<32 hex>",
              "project": { "id": "<sha256(name)[:32]>", "name": "<as given>" },
              "run": { "journal": "…", "plan": "…" } } }

// every turn
{ "seq": 0, "kind": "<one of `conversations.KINDS`>", "at": "<ISO 8601 UTC>", …body… }
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

`model` is what was **asked for**; `backend` is what **answered**. They come apart where a seat has
no model assigned: the ask names none, and the default backend answers.

A reader may add `incomplete_lines` (a torn write) and `duplicate_seqs` (what `file` can report but
not refuse).

## 9 · Export formats — `conversations.FORMATS`, and only one of them lossless

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

An `answer` carries `ask_id` and no `node_id`, so its node is read back out of the `NNN-node_id[-seat[-mN]]`
form of the id. Without that, every ask/answer pair splits in two: 53 stops for 55 turns, a list
wearing a waterfall's markup.

Three voices, from `kind`: `runner` (`ask`, `opened`, `closed`, `relaxation`, `note`), `model`
(`answer`, `unanswered`), `operator` (`instruction`, `decision`, `review`). Model-written text is escaped on
the way in — the same reason CSV cells are defused against formulas.

## 10 · Model registry — **closed**, entry *and* envelope

Eleven fields, listed in `models.Model`, persist. `_model_from` refuses anything else by name — and so, now, does the envelope.
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
                "note": "",
                "tier": "",                      // "" | "high" | "mid" | "low" — a label, not inferred
                "effort_argv": [],               // cli only — argv template; "{effort}" is substituted
                "declared_reach": "" } ] }       // "" | "local" | "internal" | "external" — may only raise the derived reach
```

**Three fields, listed in `models.COMPUTED`, are computed and never stored** — `reach` is `local` /
`internal` / `external` derived from `(transport, endpoint)` on every load — raised to
`declared_reach` when that is set and higher, never lowered by it (CHG-20261005-01) —
`leaves_this_machine` follows from it, and `reach_guessed` says whether the derivation had
to guess. `save()` strips them, and `models.py` says why on `models.COMPUTED`'s own line:
*"Storing one would let a stale label outlive the truth."*

## 11 · Settings — **closed**

`settings.py` refuses unknown keys and wrong types with the same doctrine as the registry. It was
closed all along and revision 1 of this page did not say so.

```jsonc
{ "review_seats": null,          // null = 2 (conformance, defect); the floor is 3 counting an independent auditor
  "high_risk_mode": false,       // may the floor be crossed at all
  "ordinary_commands": [],       // tools the operator vouches for — the TOOL, never a command line
  "coder_model": "",             // registry id for engineer_build when nothing is assigned; "" = the only mid model (unless agent_command is set); "none" = no default
  "coder_effort": "medium",      // low | medium | high — for engineer_build and what follows it
  "review_dimensions": null,     // null = the first review_seats seats; or seat names, in order
  "seat_specs": [] }             // the user's role and spec per seat; [] = nobody's
```

`seat_specs` (CHG-20261016-01) is a list of `{"seat"?, "model"?, "role"?, "spec"?}`: no `seat` is
the level shared by every open seat, a `seat` alone is that whole seat, a `seat` and a `model` is
that model on that seat. `spec` is `{"kind": "text", "text": "…"}` or `{"kind": "text", "path":
"docs/ARCHITECTURE.md"}` (a file inside the directory the runner is started from). `kind` is
reserved: only `text` exists. Each level holds one entry, and an entry sets a role, a spec, or both.
Role at most 500 characters, spec at most 8000 (a file at most 32768 bytes). The same validator
(`seatspec.parse`) reads the file, the settings screen, the store and `POST /config/seat_specs`.

`review_dimensions` (CHG-20261005-02) is a list of names from `policy.SEATS` — fifteen, of which the
first two (`conformance`, `defect`) open by default, `review_seats` takes a prefix of the
twelve that are not opt-in, and `observability`, `supply_chain` and `i18n` open only when named. When
it is set it **replaces** the `review_seats` prefix and `review_seats` is ignored (`runner settings
--show` says so). An unknown name, a repeat, fewer names than the floor (3, counting an independent auditor, so at least 2 here), or a list that leaves out
`conformance` (the veto seat) is refused at load and at save; high-risk mode allows the last two, as
it does for a count, and a run without `conformance` records that in `relaxations`.
`intake_review` asks the same seats.

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
confirmations · adjudications · single_model_panels · seat_models · seat_briefs · effects · resumed
· intake_asked_somebody · dispatches · effort_not_applied · usage · usage_summary · survey · options
· panel_rounds · send_backs · rejections · rulings · store_errors · change_class ·
relaxations_by_class · risk_proposed · risk_settled · risk_agreed · halts · class_authorised_by ·
relaxation_authorisers · findings · audit_scope · dispositions`

`findings` (CHG-20261028-01) is one entry per finding the whole-change review raised, per lap: the
finding as `policy.read_findings` reads it (`id`, `source` — the seat or `auditor` — `file`, `line`,
`claim`, `trigger`, `severity`, `origin`, and `severity_said` where a missing trigger demoted it)
and the `lap` it belongs to.

`audit_scope` (CHG-20261028-01) is what the auditor was given to read: `auditscope.assemble`'s record,
`{base, cap, total_chars, read_chars, files: [{path, why, chars, state}], cut, notes}`. `why` is
`diff`, `callee` or `caller`; `state` is `read` (inside `AUDIT_SCOPE_MAX_CHARS`) or `cut` (left out
because the cap was reached). `{}` until `audit_read` runs. A scope with `cut` files is printed beside
the review's outcome. Callers and callees are resolved for Python only; `notes` says where they were not.

`dispositions` (CHG-20261028-01) is what the auditor said about each finding, one entry per finding
per lap: `{id, disposition, file, line, evidence, input, result, lap}` and, where a `refute` showed no
input and result, `disposition_said: "refute"` beside `disposition: "cannot-verify"`. `disposition` is
`confirm`, `refute` or `cannot-verify` (`policy.DISPOSITIONS`); `file` and `line` are where the
evidence is. `[]` when no finding was raised: the auditor is not asked to dispose of nothing.

A `send_backs` entry from `review_decide` (CHG-20261028-01) adds `findings` (only the confirmed
findings: `id`, `source`, `file`, `line`, `claim`, `trigger`, `evidence`) and `findings_file`, the path
of `confirmed.json` beside the lap's `findings.json`, which the rework's order lists in
`input_artifacts`. Refuted, cannot-verify, nit and pre-existing findings are in `findings` of the
report and in the adjudication's `kept`, and do not travel. The appendix stays *reference, not
instruction*.

The adjudication entry for `review_decide` (`policy.dispose`) adds `panel_view` (the seats' result),
`audit_result` (`pass`, `fail` or `null` when a veto was refuted), `confirmed` and `kept` (each a
finding with its source and, for `kept`, a `why`: `refuted`, `cannot-verify`, `nit` or `pre-existing`).

`usage` (CHG-20261006-01) is one entry per ask whose session reported usage — `{ask_id, node_id, seat,
model, kind, cost_usd, tokens, remaining, note}`, `kind` being `claude`, `codex` or `unreported`;
an unknown figure is `null`, never `0`. Sessions with no usage attribute (the stub) add nothing.
`usage_summary` is `usage.summarize` over it: `{models: {id: {asks, cost_usd, tokens,
asks_unreported}}, remaining: [latest reading of each window]}`. Both are served by `GET /usage`.

`seat_models` (CHG-20261005-02) is `{node_id: {seat: [model, …]}}` — which models answered which seat,
for `intake_review` and `lead_review`, one entry per session in the order they were asked. A model
is its registry id, or its argv joined by spaces for a command; a seat nobody routed reads
`"(default backend)"`. A seat with several models also adds `by_model` to its adjudication
(`{seat: [word, …]}`), because the seat's own word is their conjunction. A seat that said `fail`
while one of its models named no verdict adds `unreached` (`{seat: ["seat (model)", …]}`).

`seat_briefs` (CHG-20261016-01) is one entry per seat session, in the order asked, for
`intake_review` and `lead_review`: `{ask_id, node_id, seat, model, position, summary, sha256, file,
role, spec, reused}`. `summary` reads "no role, no spec" for a seat with neither, so an empty one is
visible and not missing, and otherwise names the level each text came from and, for a file, its path
(a spec file is sent to that seat's model, under the same `reach` the model has). `file` links the
stored brief (the absolute path, in the journal's `briefs/` or in the run's own brief directory;
`null` only for a caller of `engine.walk` that gave neither a journal nor a `brief_store`);
`sha256` is the brief's; `role` and
`spec` are the journal's records (the spec text as sent, with its kind, source and hash); `reused`
is true when a resume answered the session from the journal. The verdict was reasoned from the
spec's text, not measured on a device.

`intake_asked_somebody` answers one question — *did the intake survey open a session this lap?*
— measured over that node's seat asks alone and **before** the escalation dispatches its own option
ask. It is on the report because two callers need it after the walk: `cli.cmd_run` and
`server.Runner._walk_once` decide from it whether a run counts as an ask for
`intake.times_asked`, and each used to rebuild it from `len(resumed) < len(asks)`. That pair is the
same number only while `intake_review` is the only node that has asked anything *and* while the
option ask replays from the journal — and with the replay gone, the one order that left the process
was the escalation's own, and both callers' lines would record a stop for it. **The command line
does reach that lap**; on the server the append also requires the brief to have grown, which
re-asks every seat, so the shape is not known to arise there (CHG-20260914-01).

`relaxation_authorisers` maps each note in `relaxations_by_class` to **who pre-authorised that
gate** (CHG-20260903-41). `class_authorised_by` beside it is one name for the whole run, read from
the run-level `--change-class` — which the CLI *refuses* over a split programme, so on the one
shape the per-workstream form exists for it is always empty. A gate belonging to no workstream
carries every authoriser, comma-separated, because it relaxed only if every workstream was
pre-authorised.

The last six were declared on `RunReport`, written during the walk, and emitted by nothing until
CHG-20260901-16 — so they reached no entry here and no console, and lived only in
`cmd_run`'s stdout footer. The guard over this entry checked *emitted ⊆ documented*, which a field
passes for free by never being emitted;
`test_the_report_emits_every_field_it_declares` now checks the other direction.

Three states: `finished` (reached a terminal), `suspended` (a decision continues it), `stopped`
(nothing continues it).

The **dataclass** does not enforce membership — `RunReport(state="banana")` constructs and
`as_dict()` emits it. `_finish` refuses on every walk exit, so it is enforced at the boundary that
matters and not by the type.

## 14 · SQLite DDL — seven of seven tables built

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
  key_env TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  tier TEXT NOT NULL DEFAULT '', effort_argv TEXT NOT NULL DEFAULT '[]',
  declared_reach TEXT NOT NULL DEFAULT '');
```

All seven are live in [`store.py`](../src/ai_sdlc_runner/store.py): `models`,
`node_assignments` and `seat_assignments` at schema 1, `conversations` and `turns` at schema
2 with the conversation-store migration, and `halt_routing` after it. `seat_assignments` was rebuilt
at schema 5 as `(seat, position, model_id)`, and `seat_specs` arrived at schema 6 — see
[`DATABASE.md`](DATABASE.md).

> This paragraph said `conversations` and `turns` were *"not created by any code yet"* until
> CHG-20260907-13. `DATABASE.md` was corrected for the same sentence by CHG-20260903-37 and
> given a guard; this page carried the denial for four more days, because the guard reads
> one file and the sentence lived in two.

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

Twenty-three routes, ten `GET` and thirteen `POST`, every one crossing a process boundary to a
browser. Written down in **[`API.md`](API.md)** and pinned by `tests/test_api_schema.py`.

The three-check guard that runs before every route — loopback `Host`, then `Origin`, then
`X-Operator-Token` — and the two deliberate token exemptions are documented there, in that order,
because the order is the property.

## 16 · Model management

Entry 10 is the model **shape**. [`MODELS.md`](MODELS.md) is the part that governs it — every
refusal `validate()` makes, how `reach` is derived from `(transport, endpoint)` and raised to
`declared_reach` when that is higher (never lowered), and how a model gets from the registry to an actual ask through
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
| ~~The server HTTP API~~ | **written down** — [`API.md`](API.md), twenty-three routes, pinned by `tests/test_api_schema.py` |
| **`runner.yaml`** — `agent_command`, `agent_timeout` | durable config with a hand-rolled fallback parser that has already shipped one bug (the inline-list split) |
| **`RunConfig`** | the engine's real input contract, substantially wider than the plan file the catalogue shows |
| **`Approval` / `Rejection` / `Ruling`** | operator decisions crossing the server→engine boundary; the catalogue has their flattened conversation turns, not their input shapes |
| **The `.conversation` marker** and **`_project.json`** | durable, and the marker is load-bearing at resume — stale data there controls re-attachment |
| **`EffectOutcome`** — `frontier`, `already_met`, `applied`, `out_of_order` | durable report output with a fixed shape |
| **The intake `Survey` aggregate** | crosses the agent→operator boundary and lands in the run report; adds a computed `complete` absent from the answer contract |
| ~~The `ship` block's interior~~ | **closed** — nine fields, listed in `plan.SHIP_FIELDS`; four required, listed in `plan.SHIP_REQUIRED` |

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
