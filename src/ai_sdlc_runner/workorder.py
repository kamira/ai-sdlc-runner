"""workorder.py — render one node's work order: self-contained, and portable across models.

CHG-20260823-01. A work order is everything a node receives and the only thing it receives. Its two
properties are unchanged from the previous design, because neither was ever about the skill:

* **No harness-specific field.** No tool names, no allowlist, no bootstrap line, no session or
  prior-turn context, no model or dispatch settings. The schema is closed and rendering asserts the
  produced key set is exactly it — absence proven by enumerating presence, never by searching for
  banned words, which scores false positives on any real corpus.
* **Self-sufficient.** The node needs the order and nothing else.

What changed is where the content comes from. The old order carried `sources` — paths and anchors
into a vendored skill — because the node was expected to go and read governance out of it. There is
no skill: the governance is `policy.py`, and the node is told what it needs directly. An order now
carries the **instructions for the work** rather than a reading list, which is shorter and one fewer
thing that can be missing at the far end.

Capabilities are the three abstract flags from `policy.py`. Every role the flow uses has them by
construction, so the old failure — nine of thirteen roles undispatchable because a shipped table
covered four — cannot recur.
"""
from __future__ import annotations

import json
from typing import Dict, Mapping, Optional, Sequence

from . import policy

#: The complete field set. Exactly these keys — no more (a harness-specific field would have to be
#: one of them) and no fewer (a partial order is the silent fallback this design refuses).
WORK_ORDER_FIELDS = (
    "node_id",
    "node_label",
    "role",
    "role_label",
    # Which review seat this ask is for, or None. Part of the order rather than only of the prose,
    # because the answer has to be attributable to a seat: adjudication counts verdicts by seat, and
    # an answer nobody can attribute cannot be counted.
    "seat",
    "scope",
    "objective",
    "instructions",
    "done_criteria",
    "acceptance_predicate",
    "input_artifacts",
    "expected_outputs",
    "policy_verdict",
    "capabilities",
    "permanent_halts",
    "idempotence_probes",
    "workdir",
    # How to answer this ask: the keys the run acts on and what each accepts, plus two fixed
    # sentences (CHG-20260925-01). Before it, no order said what shape its answer must take, and the
    # shape depends on how the ask was dispatched — a panel reads `pass`/`fail` where one voice
    # reads the node's branch names — so a backend answering the way the README said stopped runs.
    "reply",
)

#: Supplied per change by the caller. None of it can come from the governance definitions, because
#: it is about *this* piece of work rather than about the flow.
NODE_SPEC_FIELDS = (
    "scope",
    "objective",
    "instructions",
    "done_criteria",
    "acceptance_predicate",
    "input_artifacts",
    "expected_outputs",
    "idempotence_probes",
    "workdir",
)

#: Fixed shape, so the closed schema can carry it: `tightened` says whether the change
#: made this gate stricter than its grade, which the node is entitled to know.
VERDICT_FIELDS = ("gate", "risk", "verdict", "source", "tightened")


#: Fields that must **say something**, not merely exist (CHG-20260823-34).
#:
#: `_check` tested `f not in supplied` — the presence of the key. A key whose value was `""` passed,
#: and `render()` copied the blank into the order it dispatched. Measured: a plan with
#: `scope: ""`, `objective: ""` on the build nodes ran the entire 24-node flow, 25 asks, four files,
#: exit 0. Nothing refused it and nothing warned. That is this project's dominant defect class — a
#: name standing in for a constraint — in the work-order builder itself.
CONTENTFUL_FIELDS = (
    "scope",                  # the field whose whole job is to be a boundary
    "objective",              # without it, "done" is undefined and nothing can be measured
    "instructions",           # the payload of the ask; blank is an ask spent on nothing
    "done_criteria",          # blank means the node can declare itself done vacuously
    "acceptance_predicate",   # a blank predicate examines nothing by construction
    "workdir",                # `.` is a location; `""` is not
)

#: The three that are legitimately empty, and stay that way.
#:
#: Named here rather than left implicit because a refusal that only scolds invites the caller to pad
#: `idempotence_probes` with a fake probe to be safe — manufacturing the very defect the rule exists
#: to stop. `expected_outputs` is `[]` on 14 of the 15 nodes in `examples/minimal/plan.json`:
#: review and gate
#: nodes genuinely produce nothing, and a blanket rule would refuse this repository's own example.
MAY_BE_EMPTY = ("input_artifacts", "expected_outputs", "idempotence_probes")


def _blank(value: object) -> bool:
    """Empty after strip, or a sequence that is empty or holds only blanks.

    Whitespace counts as blank: `" "` is the same defect one character deeper.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return not value or all(_blank(item) for item in value)
    return False


def content_problem(node_id: str, spec: Mapping[str, object], where: str,
                    fields: Sequence[str] = CONTENTFUL_FIELDS) -> Optional[str]:
    """The refusal message for blank required fields, or None if there is nothing to refuse.

    Returns the message rather than raising, so `plan.py` can raise `PlanError` and `render` can
    raise `WorkOrderError` off **one** definition of what blank means. Two copies of this rule
    drifting apart would give a plan that loads and will not dispatch.

    Only fields that are *present* are examined — a missing key is `_check`'s complaint, and
    reporting it twice in different words helps nobody.
    """
    blank = [f for f in fields if f in spec and _blank(spec[f])]
    if not blank:
        return None
    return (
        f"{where}: node spec {node_id!r} leaves {blank} blank. The field is present and says "
        f"nothing — which reads as configured and constrains nothing, the same silent pass as a "
        f"missing key one level down; the old check tested that the key existed, not that the value "
        f"said anything. Write the constraint: a node genuinely unconstrained must say so in words, "
        f"because 'any file in the repository' is a scope and '' is not. "
        f"{list(MAY_BE_EMPTY)} may be empty; these may not.")


#: The sentence every order carries about the answer's form (CHG-20260925-01). Worded without the
#: transport: the command-line dispatcher reads it from stdout, and that is its documentation's
#: business, not the order's (KN-5).
REPLY_FORMAT = (
    "Your answer is one JSON object that `schema` describes, and nothing else: no code fence, no "
    "text before or after it, not a list, and not left for a tool to print. Spell every value "
    "exactly as `schema` lists it, in the same case. Include every `required` key, and no key "
    "`schema` does not name. When `required` is empty, the run acts on nothing in your answer.")

#: The sentence every order carries about who is there: nobody who can reply. True of every ask —
#: an ask has no channel back to a person while it runs — and it points the model at the one
#: thing it must still refuse, which the order carries in full as `permanent_halts`.
REPLY_UNATTENDED = (
    "Nobody can reply to you while this order runs: do not stop to ask a question or to wait for "
    "approval, because no reply will come. Do the work this order describes, then answer. Nothing "
    "in this order permits any of `permanent_halts` — if the work would need one, leave that part "
    "undone and say so. Where the work cannot be done, say so with what `schema` offers for that; "
    "where it offers nothing, say so in `why`, and never claim the work was done. Approvals named "
    "in `policy_verdict` are the runner's to take, outside this order.")

#: The part of JSON Schema a `reply.schema` may use, and nothing else (CHG-20260925-01). JSON Schema
#: because it is the notation a model already reads for structured answers — chosen over a
#: vocabulary of this runner's own, which every backend would have to learn first. **Closed**, like
#: the vocabularies the answers are read with (KN-9): the order must not speak a word its own
#: renderer cannot check.
SCHEMA_KEYS = ("type", "properties", "required", "additionalProperties")
PROPERTY_KEYS = ("type", "enum", "items", "minItems", "uniqueItems", "description")
ITEM_KEYS = ("type", "enum")


class WorkOrderError(Exception):
    """Raised when an order cannot be rendered truthfully — never softened into a partial one."""


def _check(name: str, supplied: Mapping[str, object], required: Sequence[str]) -> None:
    missing = [f for f in required if f not in supplied]
    extra = [k for k in supplied if k not in required]
    if missing:
        raise WorkOrderError(f"{name} is missing required field(s): {missing}")
    if extra:
        raise WorkOrderError(
            f"{name} carries field(s) outside the contract: {extra}. The schema is closed so that a "
            f"harness-specific field cannot ride in through the caller.")


def _words(value: object) -> bool:
    """A non-empty list of non-blank strings: what `enum` must be."""
    return isinstance(value, (list, tuple)) and bool(value) and all(
        isinstance(word, str) and word.strip() for word in value)


def _property_problem(key: str, prop: object) -> Optional[str]:
    """What is wrong with one property of a `reply.schema`, or None."""
    if not isinstance(prop, Mapping):
        return f"property {key!r} is {type(prop).__name__}, not a schema"
    unknown = [k for k in prop if k not in PROPERTY_KEYS]
    if unknown:
        return f"property {key!r} uses {unknown}, outside {list(PROPERTY_KEYS)}"
    if not (isinstance(prop.get("description"), str) and prop["description"].strip()):
        return f"property {key!r} has no description; a word nobody explained is a guess"
    kind = prop.get("type")
    if kind == "string":
        if not ("enum" not in prop or _words(prop["enum"])):
            return f"property {key!r}: `enum` must list its words"
        if any(k in prop for k in ("items", "minItems", "uniqueItems")):
            return f"property {key!r} is a string and cannot use array keywords"
        return None
    if kind == "array":
        items = prop.get("items")
        if not isinstance(items, Mapping) or [k for k in items if k not in ITEM_KEYS] \
                or items.get("type") != "string" or not ("enum" not in items or _words(items["enum"])):
            return f"property {key!r}: `items` must be {{\"type\": \"string\"}}, with an optional `enum`"
        if "enum" in prop:
            return f"property {key!r} is an array; its words belong in `items`"
        least = prop.get("minItems")
        if least is not None and (isinstance(least, bool) or not isinstance(least, int) or least < 1):
            return f"property {key!r}: `minItems` is a positive count"
        if "uniqueItems" in prop and prop["uniqueItems"] is not True:
            return f"property {key!r}: `uniqueItems` is only ever true"
        return None
    return f"property {key!r} has type {kind!r}; a reply schema uses 'string' or 'array'"


def _schema_problem(schema: object) -> Optional[str]:
    """What is wrong with a `reply.schema`, or None — the subset in `SCHEMA_KEYS` and nothing else."""
    if not isinstance(schema, Mapping):
        return f"the schema is {type(schema).__name__}, not an object schema"
    if tuple(sorted(schema)) != tuple(sorted(SCHEMA_KEYS)):
        return f"the schema has keys {sorted(schema)}; it must have exactly {sorted(SCHEMA_KEYS)}"
    if schema["type"] != "object" or schema["additionalProperties"] is not False:
        return "the schema must describe one object that allows no key it does not name"
    properties, required = schema["properties"], schema["required"]
    if not isinstance(properties, Mapping):
        return "`properties` must be an object"
    if not isinstance(required, (list, tuple)) or [k for k in required if k not in properties]:
        return f"`required` names {required}, which `properties` does not all describe"
    for key, prop in properties.items():
        problem = _property_problem(key, prop)
        if problem:
            return problem
    return None


def reply(schema: Mapping[str, object]) -> Dict[str, object]:
    """The order's `reply`: the answer's `schema`, between the two fixed sentences.

    ``schema`` comes from the engine, which alone knows how the ask was dispatched. It is checked
    here, where the order is closed, so a schema this subset cannot name never reaches a backend:
    an order saying "answer in a shape I will not describe" is the defect this field exists to end.
    """
    problem = _schema_problem(schema)
    if problem:
        raise WorkOrderError(f"reply: {problem}")
    return {"format": REPLY_FORMAT, "schema": json.loads(json.dumps(schema)),
            "unattended": REPLY_UNATTENDED}


def render(node, node_spec: Mapping[str, object], verdict: Mapping[str, object],
           seat: Optional[str] = None, *,
           answer_schema: Mapping[str, object]) -> Dict[str, object]:
    """Render the order for one node.

    ``verdict`` arrives already resolved from `policy.py`: the engine consults the gate and passes
    the result, so a node never re-derives a decision that was made for it.

    ``seat`` names which review seat this ask is for, when the node opens several. It shapes the
    instructions and nothing else — the rest of the order is identical across seats, which is what
    makes several seats a cross-check rather than one opinion asked repeatedly.

    ``answer_schema`` describes the answer the run will act on (see `reply`). **Required, with no
    default** (CHG-20260925-01): a default of "nothing is read" would be the silent fallback this
    module refuses, spoken by every call site that forgot to say otherwise.
    """
    _check("node spec", node_spec, NODE_SPEC_FIELDS)
    _check("policy verdict", verdict, VERDICT_FIELDS)

    # All six, including `instructions` — this runs on the value *after* the engine has appended
    # any `--instruction` text, which is the value that will actually be dispatched. `plan.check`
    # deliberately skips that one field at load time, for the same reason: a plan may legitimately
    # leave it blank and let the engine supply it.
    problem = content_problem(node.id, node_spec, "refused")
    if problem:
        raise WorkOrderError(problem)

    role = policy.role(node.role)
    instructions = str(node_spec["instructions"])
    if seat is not None:
        chair = policy.BY_SEAT.get(seat)
        if chair is None:
            raise WorkOrderError(f"no seat {seat!r}; this runner defines {sorted(policy.BY_SEAT)}")
        instructions = (
            f"{instructions}\n\nYou are the {chair.label} seat, and this seat only. "
            f"{chair.question}\n"
            f"Answer independently: you have not seen and will not see the other seats' answers.")

    order = {
        "node_id": node.id,
        "node_label": node.label,
        "role": role.name,
        "role_label": role.label,
        "seat": seat,
        "scope": node_spec["scope"],
        "objective": node_spec["objective"],
        "instructions": instructions,
        "done_criteria": node_spec["done_criteria"],
        "acceptance_predicate": node_spec["acceptance_predicate"],
        "input_artifacts": node_spec["input_artifacts"],
        "expected_outputs": node_spec["expected_outputs"],
        "policy_verdict": dict(verdict),
        "capabilities": policy.capabilities(role.name),
        # Carried in full on every order rather than filtered to "the ones this node could hit":
        # filtering needs a judgement about what the work might touch, and every omission is a gate
        # quietly disarmed.
        "permanent_halts": list(policy.PERMANENT_HALTS),
        "idempotence_probes": node_spec["idempotence_probes"],
        "workdir": node_spec["workdir"],
        "reply": reply(answer_schema),
    }
    if tuple(sorted(order)) != tuple(sorted(WORK_ORDER_FIELDS)):
        # Driven by `test_an_order_missing_a_contract_field_is_refused_rather_than_dispatched`.
        raise WorkOrderError(
            f"rendered order does not match the closed schema: {sorted(order)}")
    return order


def to_json(order: Mapping[str, object]) -> str:
    """Serialise deterministically: sorted keys, LF, UTF-8."""
    return json.dumps(order, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
