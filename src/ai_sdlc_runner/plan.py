"""plan.py — the plan file, closed (CHG-20260823-28).

The plan is the outermost schema: every other shape rides inside it. It was the **only** entry point
with no validation at all — read key by key with `plan.get(...)`, unknown keys silently accepted and
doing nothing.

Six independent seat reviews named it, and one gave the case that decides it:

> a plan whose `ship` key is misspelled runs **with no side effects and reports `finished`** — a dry
> run wearing a shipped run's report, produced by one typo nothing refuses.

That is the repository's own doctrine failing at its front door. `settings.py` and `models.py`
enforce exactly this for files far less consequential, and both say why in the same words:

    a setting that looks configured and does nothing is worse than one that was rejected

## Closed at two levels

The top level, and the `ship` block inside it — because `ship` is where the silent-dry-run case
lives, and closing the outside while leaving that open would answer the complaint and not the
finding.

## Types, and the one dependency inside `ship`

`node_specs` must be an object; `operations` an object of **lists of objects**; `risk` one of the
grades; `decisions` and `ship` values strings. A key of the right name holding the wrong shape is the
same defect one step in: `"node_specs": []` reads as configured and supplies nothing, and
`"operations": {"x": "write stuff"}` makes the engine iterate a string character by character and
halt on `Got 'w'`.

**And `acc_id` needs `task`.** That is the finding the first version of this module missed: a `ship`
block with `acc_id` and `acc_body` and no `task` passed every check — the keys are known, the four
required ones are present — and `record_module` then carried **zero effects**. The acceptance record
was never written, nothing refused, and the run finished. The same silent dry run this module was
written to close, one conditional deeper than the misspelling it fixed. Closing the outer case and
leaving that one was answering the complaint rather than the finding.

**Not exhaustive, and it says so.** This refuses what it can name. Of a node spec's interior it
checks only that five required fields are not **blank** (CHG-20260823-34) — `workorder` still owns
the closed field set, at render time, and owns `instructions` alone because the engine may fill it
in between here and there. It does not check that a
node id exists, because a plan may legitimately name nodes for a graph it has not been run against
yet. **Nothing closes an operation's interior**, and that is stated rather than implied: an extra key
there is accepted and ignored.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, Tuple

from . import policy, workorder

#: Every key this runner reads from a plan. Anything else is refused.
#:
#: Derived from the code that reads them, not from memory: each of these appears as a `plan.get(...)`
#: in `cli.py`, and a test walks the source to prove the two lists have not drifted apart.
FIELDS: Tuple[str, ...] = (
    "risk",          # the change's grade — low | medium | high
    "autonomy",      # tighten-only override
    "node_specs",    # {node id: the closed 9-field spec}
    "operations",    # {node id: [{description, kind, targets}]}
    "decisions",     # {node id: branch}
    "node_models",   # {node id: [model id]}
    "seat_models",   # {seat: model id or argv}
    "ship",          # the side effects — see SHIP_FIELDS
    "workstreams",   # {name: grade} — CHG-20260827-18; the run's own `risk` still applies to
                     # anything outside them, at the strictest of them
    "node_workstream",  # {node id: workstream name}
    "interfaces",    # {workstream: {name: signature}} — CHG-20260827-22, reconciled before dispatch
)

#: The `ship` block's own closed set. `repo`, `chg_id`, `branch` and `message` are required by
#: `effects_provider`; the rest are optional there and listed so a typo in one is caught.
SHIP_FIELDS: Tuple[str, ...] = (
    "repo", "chg_id", "chg_body", "branch", "message", "remote",
    "task", "acc_id", "acc_body",
)

#: `ship` keys `effects_provider` indexes directly — a missing one is an unhandled `KeyError` deep
#: in a run rather than a refusal at the door.
SHIP_REQUIRED: Tuple[str, ...] = ("repo", "chg_id", "branch", "message")

#: The keys whose value must be an object keyed by something.
_MAPPINGS = ("node_specs", "operations", "decisions", "node_models", "seat_models", "ship",
             "workstreams", "node_workstream", "interfaces")


class PlanError(Exception):
    """Refused. A plan this runner accepted while not understanding is worse than one it refused."""


def check(payload: Mapping[str, object], where: str = "the plan") -> Dict[str, object]:
    """Refuse the plans this runner can recognise as ones it would not honour.

    **Not "a plan this runner would fully honour"** — the first version of this docstring said that
    and it was false, which a seat named as the module's own worst line: a name standing in for a
    constraint, in the module written against exactly that. What it refuses is listed above; what it
    leaves to another check, or to nobody, is listed there too.
    """
    if not isinstance(payload, Mapping):
        raise PlanError(f"{where} should be a JSON object with keys like {list(FIELDS[:3])}")

    unknown = sorted(set(payload) - set(FIELDS))
    if unknown:
        raise PlanError(
            f"{where} sets {unknown}, which this runner does not read. Ignoring them would let a "
            f"setting look configured and do nothing — and the case that decides it is `ship`: a "
            f"misspelt one makes a run perform no side effects and report `finished`. "
            f"This runner reads {list(FIELDS)}.")

    for key in _MAPPINGS:
        value = payload.get(key)
        if value is not None and not isinstance(value, Mapping):
            raise PlanError(
                f"{where} has {key!r} as {type(value).__name__}, and this runner reads it as an "
                f"object. A key of the right name holding the wrong shape reads as configured and "
                f"supplies nothing.")

    for key in ("node_models", "seat_models"):
        for owner, value in (payload.get(key) or {}).items():
            if key == "node_models" and not isinstance(value, (list, tuple)):
                raise PlanError(
                    f"{where} assigns {owner!r} a single {type(value).__name__}; `node_models` "
                    f"holds a **list** of model ids, and the order is load-bearing.")

    # A node spec whose fields are present but blank (CHG-20260823-34). Checked here as well as at
    # render time so it costs no asks: a blank `engineer_build` refused only at dispatch surfaces
    # after `intake_review` through `pm_signoff` have already spent seven of them.
    #
    # **Five fields, not six.** `instructions` is deliberately absent: `engine.py` joins any
    # `--instruction` text onto the node spec's own, and line 515 reads
    # `own = spec.get("instructions") or ()` — explicitly tolerating a blank. A plan that leaves
    # every node's `instructions` empty and supplies the text on the command line is coherent and
    # works today, so refusing it at the door would be this same defect inverted: a check answering
    # "malformed" about something it had not examined.
    at_load = tuple(f for f in workorder.CONTENTFUL_FIELDS if f != "instructions")
    for node_id, spec in (payload.get("node_specs") or {}).items():
        if isinstance(spec, Mapping):
            problem = workorder.content_problem(node_id, spec, where, at_load)
            if problem:
                raise PlanError(problem)

    risk = payload.get("risk")
    if risk is not None and risk not in policy.RISKS:
        raise PlanError(
            f"{where} grades this change {risk!r}; the grades are {list(policy.RISKS)}. Accepted "
            f"here, it reached the first gate as a crash or a halt about something the plan could "
            f"have been refused for at the door.")

    # ── workstreams (CHG-20260827-18) ────────────────────────────────────────────────────────
    #
    # Validated here for the reason `risk` is: a grade this runner does not recognise, accepted at
    # the door, reaches the first gate as a crash or as a halt about something the plan could have
    # been refused for.
    workstreams = payload.get("workstreams") or {}
    for name, grade in workstreams.items():
        if not str(name).strip():
            raise PlanError(
                f"{where} declares a workstream with no name. A workstream is what a node points "
                f"at, and a node pointing at an empty name points at nothing while looking "
                f"configured.")
        if grade not in policy.RISKS:
            raise PlanError(
                f"{where} grades workstream {name!r} as {grade!r}; the grades are "
                f"{list(policy.RISKS)}.")

    for node_id, name in (payload.get("node_workstream") or {}).items():
        if name not in workstreams:
            raise PlanError(
                f"{where} puts node {node_id!r} in workstream {name!r}, which it does not declare. "
                f"A node in an undeclared workstream would fall back to the strictest grade — safe, "
                f"and silently not what the plan meant. Declare it in `workstreams` or remove the "
                f"assignment.")

    # ── declared interfaces (CHG-20260827-22) ────────────────────────────────────────────────
    #
    # A workstream declaring an interface nobody declared is the same defect as a node in an
    # undeclared workstream: safe-looking, and reconciled against nothing.
    interfaces = payload.get("interfaces") or {}
    for name, signatures in interfaces.items():
        if name not in workstreams:
            raise PlanError(
                f"{where} declares interfaces for workstream {name!r}, which it does not declare. "
                f"Nothing would reconcile them, and the run would proceed as though they agreed.")
        if not isinstance(signatures, Mapping):
            raise PlanError(
                f"{where} gives workstream {name!r} interfaces as a "
                f"{type(signatures).__name__}; it must be an object of `{{name: signature}}` — a "
                f"list has no names to compare, and comparing is the whole point.")
        for label, signature in signatures.items():
            if not isinstance(signature, str) or not signature.strip():
                raise PlanError(
                    f"{where}: workstream {name!r} declares interface {label!r} as "
                    f"{signature!r}. A signature is the string two workstreams have to agree on; "
                    f"an empty one agrees with everything.")

    autonomy = payload.get("autonomy")
    if autonomy is not None and not isinstance(autonomy, str):
        raise PlanError(
            f"{where} sets `autonomy` to a {type(autonomy).__name__}; it is a verdict name, and a "
            f"non-string reached `policy.verdict` as an uncaught AttributeError.")

    for node_id, branch in (payload.get("decisions") or {}).items():
        # **Three forms**, and `_choose`'s own docstring names them: one label always, a sequence
        # consumed one per visit, or `"frontier"` — read the run rather than a list.
        #
        # The first version of this check accepted only a string, and refused the sequence form.
        # Twenty-five existing tests caught it. That is the other failure mode of a closed schema:
        # not accepting what it should refuse, but **refusing what it should accept**, which is
        # worse — a plan that was correct stops working and the message says it is malformed.
        if isinstance(branch, str):
            continue
        if isinstance(branch, (list, tuple)) and all(isinstance(b, str) for b in branch):
            continue
        raise PlanError(
            f"{where} decides {node_id!r} with {type(branch).__name__}; a decision is a branch "
            f"**name**, a list of names consumed one per visit, or \"frontier\". Anything else "
            f"reached the engine as a TypeError about lengths rather than a refusal about a plan.")

    for node_id, listed in (payload.get("operations") or {}).items():
        if not isinstance(listed, (list, tuple)):
            raise PlanError(
                f"{where} gives {node_id!r} operations as a {type(listed).__name__}; it is a "
                f"**list** of operations. A string here is iterated character by character and the "
                f"run halts on the first letter.")
        for operation in listed:
            if not isinstance(operation, Mapping):
                raise PlanError(
                    f"{where} gives {node_id!r} an operation that is a "
                    f"{type(operation).__name__}; each one is an object with `description`, `kind` "
                    f"and `targets`.")

    ship = payload.get("ship")
    if ship is not None:
        _check_ship(ship, where)
    return dict(payload)


def _check_ship(ship: Mapping[str, object], where: str) -> None:
    """The block whose typo produced a silent dry run. Closed, and its required keys named."""
    unknown = sorted(set(ship) - set(SHIP_FIELDS))
    if unknown:
        raise PlanError(
            f"{where}'s `ship` sets {unknown}, which nothing reads. This is the block a misspelt "
            f"key makes silent, so it refuses rather than skips. It reads {list(SHIP_FIELDS)}.")
    missing = [key for key in SHIP_REQUIRED if not ship.get(key)]
    if missing:
        raise PlanError(
            f"{where}'s `ship` is missing {missing}. Those are indexed directly, so leaving one out "
            f"is a KeyError partway through a run rather than a refusal before it starts.")

    wrong = sorted(k for k, v in ship.items() if not isinstance(v, str))
    if wrong:
        raise PlanError(
            f"{where}'s `ship` gives {wrong} a non-string value. Every one of them is written into "
            f"a file or a commit, and a number reached `ship.py` as an AttributeError about "
            f"`splitlines` before the run had started.")

    # **The dependency inside the block.** `record_effects` is called only `if task`, so `acc_id`
    # and `acc_body` without one are read by nothing: the acceptance record is never written and the
    # run reports `finished`. That is the silent dry run this module exists to close, one
    # conditional deeper than the misspelling — found by a seat, in the block the closure covered.
    orphaned = sorted(k for k in ("acc_id", "acc_body") if ship.get(k))
    if orphaned and not ship.get("task"):
        raise PlanError(
            f"{where}'s `ship` sets {orphaned} and no `task`. The acceptance effect runs only when "
            f"a task is named, so those would be read by nothing — the acceptance record silently "
            f"never written and the run reporting `finished`. Name the task, or remove them.")
    if ship.get("task") and not ship.get("acc_id"):
        raise PlanError(
            f"{where}'s `ship` names a task and no `acc_id`, so the acceptance record has no "
            f"identity to be written under.")


def load(path: str | Path) -> Dict[str, object]:
    """Read a plan file, and put it through `check`.

    The retracted claim lived here too. CHG-20260823-30 corrected `check`'s summary line and pinned
    it with a test that reads `check.__doc__` — so this line went on promising a plan "this runner
    would fully honour" for four more days, one function along, where the test did not look. Found
    by the acceptance round of 2026-08-27 and closed by CHG-20260827-10.

    What `check` refuses is listed in the module docstring; so is what it leaves to another check
    and what it leaves to nobody.
    """
    file = Path(path)
    if not file.is_file():
        raise PlanError(f"no plan at {file}")
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PlanError(f"{file} is not valid JSON: {exc}") from None
    return check(payload, where=str(file))
