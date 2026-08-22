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
| `ask_id` | str | required, unique | `<sequence>-<node_id>[-<seat>]` — sorts into flow order |
| `node_id` | str | required | Which node asked |
| `status` | str (enum) | `pending` \| `answered` | `pending` is written first; `answered` replaces it |
| `order` | object | required | The work order verbatim — the question itself, not a summary of it |
| `result` | object | present when answered | Whatever the backend replied |

A reconstructed approximation of a question is not the question. The order is stored whole so a
resumed run re-asks the same thing rather than something like it.

## In memory, and shaped on purpose

### The work order — a closed schema

Seventeen fields, listed in `workorder.WORK_ORDER_FIELDS`, and a field outside the list is refused
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
| `on_trust` | list[str] | Operations nothing could check — declared ordinary, no targets. The planner's word is all that is behind them, and this is where that shows |
| `effects` | dict[str, object] | Per node: applied, already met, and anything found true out of causal order |
| `halted_at`, `halt_reason` | str | Where the run stopped and why, in words that name the rule |

### The effect

An operation is admitted as an effect **only if it leaves a probeable postcondition** — there is
deliberately no way to construct one without a probe.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Required; it is what a resume log reports |
| `probe` | callable | Reads the postcondition from the world. Unanswerable raises rather than returning False |
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
| `targets` | list[str] | optional | The commands, paths and URLs it will act on. A red-line target **overrules** a `kind` of `ordinary`. A bare string is refused — joined into one blob, the boundary between two targets can hide a third |
- **role**: `pm | lead | engineer | qa | seat`
- **seat**: `conformance` (veto) `| defect | risk | idiom`
- **gate phase**: `before | after`
- **node kind**: `step | decision | loop | terminal`
- **ask status**: `pending | answered`

## Configuration

`config/runner.yaml` is dispatch settings only — `agent_command`, `agent_timeout`. There is no skill
path, no contract version and no lock, because there is nothing to lock against. Everything about
*this change* travels in the plan file `runner run --plan` names, and everything about the governance
is in `policy.py`.
