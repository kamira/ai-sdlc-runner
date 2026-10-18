# Data Structure

Answers: FR-5, FR-7, FR-8, FR-15.

**CHG-20260823-01 replaced everything this file used to describe.** The per-project contract lock and
the stage checkpoint both existed to track a skill version and a four-stage pipeline; neither exists
now. What the runner persists today is one thing — the **ask journal** — and the rest is in-memory
structures whose shapes are load-bearing, so they are written down here.

The runner owns no database. It reads git and the forge through probes, and writes nothing a person
cannot open in a text editor.

## Persisted

### The ask journal — one file per ask

One JSON file per question, in the directory `--ask-journal` names. Written **before** the session
opens and rewritten after it answers, which is the whole point: a session that drops between those
two writes leaves the question on disk exactly as it was asked.

| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| `ask_id` | str | required, unique | `<sequence>-<node_id>[-<seat>[-m<N>]]` — sorts into flow order; `-m<N>` is added when a seat has several models, `N` the model's position |
| `node_id` | str | required | Which node asked |
| `status` | str (enum) | `pending` \| `answered` \| `refused` | `pending` is written first; `answered` replaces it, or `refused` when the ask's own check would not take the answer (the answer is kept) |
| `order` | object | required | The work order verbatim — the question itself, not a summary of it |
| `result` | object | present when answered or refused | Whatever the backend replied |
| `voice` | object | present on a seat ask; absent on any other | `{model, argv}`: the model id the seat session was put to (`null` for the default backend) and the argv the factory resolves for it. A resume reuses the answer only if this equals the voice about to be asked; an entry with no `voice` is asked again. When the user set a role or spec for the seat it adds `brief_sha256`, so a changed brief is asked again |
| `brief` | object | present on a seat ask; absent on any other | What the seat session was sent (CHG-20261016-01): `sha256` and `file` of the stored brief (`briefs/<ask_id>.json`, byte for byte what the process received; `file` is `null` when there is no journal), `role` (`text`, `level`) and `spec` (`kind`, `source` inline or file, `path`, `text` as copied when the walk started, `sha256`, `level`), each `null` when none applies. A spec file edited later does not change it |

A reconstructed approximation of a question is not the question. The order is stored whole so a
resumed run re-asks the same thing rather than something like it.

## In memory, and shaped on purpose

### The work order — a closed schema

Eighteen fields, listed in `workorder.WORK_ORDER_FIELDS`, and a field outside the list is refused
rather than passed through. What is **not** in it matters as much as what is: no tool list, no model
name, no allowlist, no session context, and nothing any previous answer touched. A harness detail in
the order is a harness the order cannot outlive.

| Field | Description |
|-------|-------------|
| `node_id`, `node_label` | which node this is |
| `role`, `role_label` | who is being asked |
| `seat` | which review seat, or `null` — adjudication counts verdicts by seat |
| `scope`, `objective`, `instructions`, `workdir` | the work |
| `done_criteria`, `acceptance_predicate`, `expected_outputs` | when it is finished |
| `input_artifacts`, `idempotence_probes` | what it starts from, and how to tell it already ran |
| `policy_verdict` | the gate's decision, already resolved — a node never re-derives it |
| `capabilities` | `can_spawn` / `can_write` / `can_execute` for this role |
| `permanent_halts` | all six, always, never filtered to "the ones this node might hit" |
| `reply` | how to answer: the keys the run acts on in this answer and what each accepts, for the path the ask was dispatched on, plus two fixed sentences — the answer's form, and that no person is attached (CHG-20260925-01) |

The order is what a backend receives, and it receives it through `workorder.to_json` — sorted keys,
LF, UTF-8 — so the same order is the same bytes on every machine.

### The run report

| Field | Type | Description |
|-------|------|-------------|
| `visited` | list[str] | Every node, in order |
| `asks` | list[Ask] | node id, role, seat, and the answer |
| `verdicts` | dict[str, object] | What the policy said at each node: gate, risk, verdict, source, tightened |
| `confirmations` | list[str] | Gates the operator had already approved — an approval with no trace is one nobody can audit |
| `adjudications` | list[object] | Each panel decision, with every seat's verdict that produced it |
| `relaxations` | list[str] | The seat floor bypassed, and at what count; a node run undeclared |
| `on_trust` | list[str] | Operations nothing could confirm — declared ordinary, with no targets *or* with targets this runner does not recognise. The planner's word is all that is behind them, and this is where that shows |
| `resumed` | list[str] | Ask ids answered from the journal rather than by opening a session |
| `seat_briefs` | list[object] | One per seat session (CHG-20261016-01): the role and spec it was sent and the level each came from, the brief's sha256 and stored file, or "no role, no spec" |
| `single_model_panels` | list[str] | Panels where every seat was answered by the same backend — independent sessions, one set of blind spots |
| `effects` | dict[str, object] | Per node, all four keys `EffectOutcome.as_dict()` writes: `frontier` (where the resume started), `already_met`, `applied`, `out_of_order`. An out-of-order effect is in **both** `already_met` and `out_of_order`, so the two lists do not partition the sequence |
| `halted_at`, `halt_reason` | str | Where the run stopped and why, in words that name the rule |

### The effect

An operation is admitted as an effect **only if it leaves a probeable postcondition**. That rule
is D6.2 and it is settled in **review**, not by the type: `__post_init__` refuses a missing
probe, a non-callable one, and one that cannot be called with no arguments, and it cannot tell
whether what a probe reads is the world or a receipt. `Effect(probe=lambda: True)` is admitted.

Every ordinary route to a probeless one is closed — the constructor, `dataclasses.replace`, and
assignment, since the class is frozen. Deliberate bypasses (`object.__setattr__`, a subclass
overriding `__post_init__`, unpickling an `object.__new__` instance) are not, and nothing in
`src/` uses any of them.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Required; it is what a resume log reports |
| `probe` | callable | Reads the postcondition from the world. Every probe in `probes.py` **raises** when it cannot answer, rather than returning False — see below; the type does not check it |
| `apply` | callable | Carries the effect out |
| `postcondition` | str | What the probe reads, in one line. An effect that cannot be said in a line usually cannot be probed either |

## Enums

- **risk**: `low | medium | high`
- **verdict**: `auto | confirm | halt | halt_independent`
- **gate**: `plan_confirmed | feasibility_confirmed | before_dispatch | self_verify | task_review |
  lead_review | qa_verify | acceptance | pr | merge`
- **operation kind** (what a plan declares each operation to be): `deploy | migration | delete |
  money | access | publish | ordinary`. **There is no default** — an operation declaring nothing is
  refused, because a red line whose default branch is "proceed" is not a red line

### The operation

What a node says it is about to do. `targets` is optional and is the strongest of the three signals,
because it is the only one that is a fact rather than a claim.

| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| `description` | str | required in practice | What this does, in the planner's words. Read only by the backstop |
| `kind` | str (enum) | **required** | One of the six red lines, or `ordinary`. Absent → refused |
| `targets` | list[str] | optional | The commands, paths and URLs it will act on. Each is **red**, **recognised-ordinary**, or **unrecognised**; a red one overrules a `kind` of `ordinary`, and an unrecognised one is not evidence of anything. A bare string is refused — joined into one blob, the boundary between two targets can hide a third |
- **role**: `pm | lead | engineer | qa | seat`
- **seat**: `conformance` (veto) `| defect | risk | idiom | security | ux | ci | modularity | privacy | performance | portability | docs`, and the opt-in `observability | supply_chain | i18n` (fifteen, `policy.SEATS`)
- **gate phase**: `before | after`
- **node kind**: `step | decision | loop | terminal`
- **ask status**: `pending | answered | refused`

### config/settings.json

What the user set, and the only file this runner writes on their behalf. **Seven fields, listed in
`settings.FIELDS` (the table below has all seven).** They cannot change what a gate verdict is,
which kinds are permanent halts, or the adjudication rule — `policy` owns those and takes nothing
from here. Two of them do change **whether a stop happens**: `review_seats=1` makes the `undecided`
outcome unreachable, and `ordinary_commands` decides whether the `unrecognised-target` halt trips
(CHG-20260903-47). `coder_model` and `coder_effort` choose a backend and touch no verdict
(CHG-20261005-01). `review_dimensions` names the review seats that open, in order, and replaces the
`review_seats` count while it is set; the floor applies to its length, and it must include the veto
seat `conformance` unless high-risk mode is on (CHG-20261005-02). `seat_specs` carries the user's
role and spec per seat and touches no verdict, veto or adjudication (CHG-20261016-01).

| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| `review_seats` | int \| null | 1 … `policy.MAX_SEAT_COUNT` (12), or absent | How many seats open. `null` means the floor, and a count above the twelve seats that are not opt-in is refused at load rather than raised when something renders it |
| `review_dimensions` | list[str] \| null | seat names from `policy.SEATS`, no repeats; the floor applies to its length; must include `conformance` unless `high_risk_mode` is on; absent → `null` | The review seats that open, in the order named. While set it replaces the `review_seats` count; the three opt-in seats open only here |
| `high_risk_mode` | bool | required-ish (defaults false) | Whether the floor may be crossed at all |
| `ordinary_commands` | list[str] | absent → none; one word each, never an executor | Commands whose **name** stops being unrecognised. The description is still read against the permanent halts — vouching clears `unrecognised-target` and nothing else, which is what the prose four lines above says |
| `coder_model` | str | absent → empty; not checked against a registry at save time | The registry model `engineer_build` uses when nothing is assigned. Empty means the registry's only `mid` model, if exactly one and no `agent_command` is configured; `none` means no default coder model (a No in `runner setup`), and a model so named is never picked. A set `coder_model` overrides a configured `agent_command`, with a notice. An id the registry lacks is an error when a run resolves it |
| `seat_specs` | list[object] \| null | each `{seat?, model?, role?, spec?}`; role ≤ 500 characters, spec text ≤ 8000, a spec `path` inside the repository (no `..`, no symlink out) and ≤ 32768 bytes; `kind` is `text` (reserved); one entry per level; absent → none | The user's text added to a seat's brief below its question: no `seat` is shared by every open seat, a `seat` is the whole seat, with a `model` that model on that seat. A more specific level replaces a less specific one, per text. Wins over the store's (console's) entry for the same level |
| `coder_effort` | str | `low` \| `medium` \| `high`; absent → `medium` | The effort for `engineer_build` and the nodes that follow it; delivered through the model's `effort_argv` |

This said *"Two fields, both about the seat floor"* over a table of two until CHG-20260902-20.
`settings.FIELDS` had three once `ordinary_commands` shipped, and it is not about the seat
floor — it is about what a permanent-halt check reads, which is a different subject in the same
file.

Missing → the defaults. **Empty or whitespace-only, or malformed → an error**, not the defaults: a typo must not be
indistinguishable from a deliberate choice when two of the three settings, taken together, are a safety bypass. An
unknown key is refused rather than ignored, because a setting nobody reads looks exactly like one
that works.

## Configuration

`config/runner.yaml` is dispatch settings only — `agent_command`, `agent_timeout`. There is no skill
path, no contract version and no lock, because there is nothing to lock against. Everything about
*this change* travels in the plan file `runner run --plan` names, and the **rules** of the
governance — gates, permanent halts, the adjudication rule, the class contract — are in
`policy.py` and take no input.

**One piece of governance is project data, and this paragraph used to deny it.** Halt routing —
who a stop is sent to — lives in a `halt_routing` table created and written in `store.py`, read
by `store.halt_routing(db)`, carried on `RunConfig`, and passed into
`policy.routed_to(kind, routing)` as an argument. `policy.py` owns the **shape** of that answer
and the fallback when a project names nobody; the project owns the names. Anything else that
later reaches `policy` from a project table belongs in this paragraph too
(CHG-20260903-33).
