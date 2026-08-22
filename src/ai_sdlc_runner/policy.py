"""policy.py — this runner's own governance: roles, capabilities, gates, seats.

CHG-20260823-01 task 1. Until now every value here was read out of a vendored skill and the runner
was forbidden to hold any of it (`ai-guideline` §8, "read, don't re-implement"). That constraint
assumed a skill to read. There is none: **the flowchart is a design input, not a runtime
dependency**, and this module is the governance it describes, implemented here.

Two consequences worth stating, because they are the difference between this being a port and being
a re-implementation:

* **Correctness is judged against the requirement, not against a file.** There is no shipped table to
  diff against, so "matches the skill" is not available as an argument and was not used as one. What
  each value has instead is a reason, written next to it.
* **Completeness is structural.** The old design inherited a role table covering four of thirteen
  roles, which is why nine of them could not be dispatched at all. Here the roles *are* the ones the
  flow uses, so every role a node names has capabilities by construction — and a test asserts it
  rather than trusting the arithmetic.

## The roles, and why these

Straight from the requirement's own description of the flow: the user issues the instruction, PM
confirms the plan, the lead confirms feasibility and risk and dispatches, engineers build one small
module each and verify their own work, the lead reviews, QA tests and verifies the whole thing, and
user feedback returns to PM. Review seats sit alongside as the cross-checking mechanism.

The capability flags stay the three abstract ones — `can_spawn`, `can_write`, `can_execute` — because
they are what a work order can carry without naming any harness's tools.

## The gates

Same shape as the flow needs: risk × gate → `auto` / `confirm` / `halt` / `halt_independent`.
`confirm` and above stop the run; nothing continues on anything but `auto`, which is why no ordering
between the stopping values is needed.

The grades follow one rule, applied consistently: **a gate stops when getting it wrong is expensive
to undo.** Merging is a one-way door, so it stops earlier than a task review does. Acceptance on a
high-risk change wants someone other than the builder, so it is `halt_independent`. A task review is
cheap to redo and never stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

AUTO = "auto"
CONFIRM = "confirm"
HALT = "halt"
HALT_INDEPENDENT = "halt_independent"

#: Anything that is not `auto` stops the run. Stated once, so no caller has to rank the others.
STOPPING = (CONFIRM, HALT, HALT_INDEPENDENT)

RISKS = ("low", "medium", "high")


class PolicyError(Exception):
    """Raised when something is asked of the policy that it does not define. Never defaulted."""


@dataclass(frozen=True)
class Role:
    """One role in the flow, with the three capabilities a work order may carry.

    ``can_spawn`` is the one that carries real weight: the lead is the only role that dispatches, so
    an engineer cannot start further work of its own, and a reviewer cannot quietly become a builder.
    """

    name: str
    label: str
    can_spawn: bool
    can_write: bool
    can_execute: bool
    note: str = ""


ROLES: Tuple[Role, ...] = (
    Role("pm", "PM", can_spawn=False, can_write=True, can_execute=False,
         note="turns the user's instruction into a plan and confirms it; writes the plan, not the code"),
    Role("lead", "主管 / lead agent", can_spawn=True, can_write=True, can_execute=True,
         note="confirms feasibility and risk, dispatches the engineers, reviews what they produce — "
              "the only role that dispatches"),
    Role("engineer", "工程師 / sub-agent", can_spawn=False, can_write=True, can_execute=True,
         note="builds one small module and verifies its own work; cannot dispatch further, so the "
              "tree stays two deep"),
    Role("qa", "QA", can_spawn=False, can_write=False, can_execute=True,
         note="tests and verifies the whole change for real; deliberately cannot write, so it "
              "cannot fix while verifying"),
    Role("seat", "審議席 / review seat", can_spawn=False, can_write=False, can_execute=True,
         note="one review seat; several of them cross-check each other, which is the whole reason "
              "they exist"),
)

BY_ROLE: Dict[str, Role] = {r.name: r for r in ROLES}

#: The gates, and what each risk grade does at them. The rule behind the grades: a gate stops when
#: getting it wrong is expensive to undo.
GATES: Dict[str, Dict[str, str]] = {
    # The plan itself. Wrong plans are cheap to fix now and expensive to fix later.
    "plan_confirmed":        {"low": AUTO, "medium": CONFIRM, "high": HALT},
    # Feasibility and risk, judged by the lead before anyone is dispatched.
    "feasibility_confirmed": {"low": AUTO, "medium": CONFIRM, "high": HALT},
    # The last point before work starts. On a high-risk change a human sees it.
    "before_dispatch":       {"low": AUTO, "medium": CONFIRM, "high": HALT},
    # The engineer checking its own work. Never stops: catching nothing here costs one review.
    "self_verify":           {"low": AUTO, "medium": AUTO, "high": AUTO},
    # The lead reviewing one module. Cheap to redo, so it never stops the run either.
    "task_review":           {"low": AUTO, "medium": AUTO, "high": AUTO},
    # The whole change, reviewed by seats that cross-check. High risk wants eyes on it.
    "lead_review":           {"low": AUTO, "medium": AUTO, "high": HALT},
    # QA running it for real. Same.
    "qa_verify":             {"low": AUTO, "medium": AUTO, "high": HALT},
    # Acceptance. On a high-risk change the verifier must not be the builder.
    "acceptance":            {"low": AUTO, "medium": AUTO, "high": HALT_INDEPENDENT},
    # Opening a PR is reversible; closing one costs nothing.
    "pr":                    {"low": AUTO, "medium": AUTO, "high": AUTO},
    # Merging is a one-way door. It stops earliest of anything here.
    "merge":                 {"low": AUTO, "medium": HALT, "high": HALT},
}

#: Never automated, at any risk grade, and no configuration relaxes them. These are the actions whose
#: worst case is not "redo the work" but "the work cannot be undone".
PERMANENT_HALTS: Tuple[str, ...] = (
    "production deploy or release",
    "data migration or irreversible schema change",
    "deleting data, dropping a table, any hard delete",
    "moving money",
    "changing secrets, credentials, access control or permissions",
    "publishing public content",
)

#: The review seats, in opening order — least negotiable first, so opening fewer means taking a
#: prefix rather than picking favourites. A seat with `veto` cannot be outvoted: its subject is a
#: matter of fact, not of opinion.
@dataclass(frozen=True)
class Seat:
    name: str
    label: str
    question: str
    veto: bool


SEATS: Tuple[Seat, ...] = (
    Seat("conformance", "規格合規",
         "Is this the thing the task asked for? Line by line against what was written down — "
         "including work that was not asked for, which is equally out of scope.", veto=True),
    Seat("defect", "缺陷",
         "Where is this wrong? Concrete inputs and the wrong result they produce, not a feeling "
         "that something looks off.", veto=False),
    Seat("risk", "風險與可逆性",
         "What does this make hard to undo, and what happens if it is wrong in production?",
         veto=False),
    Seat("idiom", "慣例與簡潔",
         "Does this read like the code around it, and is any of it unnecessary?", veto=False),
)

BY_SEAT: Dict[str, Seat] = {s.name: s for s in SEATS}

#: The floor: how many seats open by default. Fewer than this needs the user's explicit high-risk
#: mode, because a single reviewer is exactly the single point of view the panel exists to avoid.
SEAT_FLOOR = 3


def role(name: str) -> Role:
    if name not in BY_ROLE:
        raise PolicyError(
            f"no role {name!r}; this runner defines {sorted(BY_ROLE)}. Roles are not defaulted — a "
            f"node naming one that does not exist is a mistake, not a case to guess at.")
    return BY_ROLE[name]


def capabilities(name: str) -> Dict[str, bool]:
    """The three flags a work order may carry for this role."""
    r = role(name)
    return {"can_spawn": r.can_spawn, "can_write": r.can_write, "can_execute": r.can_execute}


def verdict(gate: str, risk: str, autonomy: Optional[str] = None) -> Dict[str, object]:
    """What the policy says at this gate for this risk, tightened by ``autonomy`` if it is stricter.

    ``autonomy`` is the per-change override. It may **tighten only** — a change may declare itself
    more dangerous than its grade suggests, never less. Asking to loosen is not honoured and is
    reported, because a request to relax a gate is worth seeing rather than silently dropping.
    """
    if gate not in GATES:
        raise PolicyError(f"no gate {gate!r}; this runner defines {sorted(GATES)}")
    if risk.lower() not in RISKS:
        raise PolicyError(f"no risk grade {risk!r}; this runner defines {list(RISKS)}")

    graded = GATES[gate][risk.lower()]
    result = {"gate": gate, "risk": risk.lower(), "verdict": graded,
              "source": "policy.GATES", "tightened": False}
    if autonomy:
        want = autonomy.lower()
        if want not in (AUTO, *STOPPING):
            raise PolicyError(f"autonomy {autonomy!r} is not one of {[AUTO, *STOPPING]}")
        if graded == AUTO and want in STOPPING:
            result.update(verdict=want, tightened=True,
                          source="policy.GATES tightened by the change's Autonomy field")
        elif want == AUTO and graded in STOPPING:
            # Reported through `source` rather than as an extra key: the verdict's shape is fixed so
            # a work order's closed schema can carry it, and a refusal the node never sees is a
            # refusal that may as well not have happened.
            result["source"] += (
                f"; the change asked for {AUTO} here and was refused — tighten-only")
    return result


def stops(verdict_value: str) -> bool:
    """Does this verdict stop the run? Everything but ``auto`` does."""
    return verdict_value != AUTO


def seat_names(count: int) -> List[str]:
    if count < 1:
        raise PolicyError("a review needs at least one seat")
    if count > len(SEATS):
        raise PolicyError(f"{count} seats requested but this runner defines {len(SEATS)}")
    return [s.name for s in SEATS[:count]]


def resolve_seats(requested: Optional[int], high_risk_mode: bool) -> int:
    """How many seats a run opens, refusing to go below the floor on its own authority."""
    if requested is None:
        return SEAT_FLOOR
    if requested < SEAT_FLOOR and not high_risk_mode:
        raise PolicyError(
            f"{requested} seat(s) is below the floor of {SEAT_FLOOR}. Enable high-risk mode to go "
            f"below it — one reviewer is the single point of view the panel exists to avoid, so "
            f"this runner does not lower the floor by itself.")
    seat_names(requested)        # raises if the count is not one this runner can actually open
    return requested


def adjudicate(verdicts: Mapping[str, str]) -> Dict[str, object]:
    """Turn the seats' verdicts into one outcome: veto first, then majority.

    A veto seat's ``fail`` cannot be outvoted — its subject is a matter of fact, and counting votes
    on a fact is how a panel talks itself out of one. Everything else is a majority, and a tie does
    not pass: the panel exists to catch what one view would miss, so an even split has caught it.
    """
    unknown = [s for s in verdicts if s not in BY_SEAT]
    if unknown:
        raise PolicyError(f"unknown seat(s): {sorted(unknown)}")
    if not verdicts:
        raise PolicyError("no seat verdicts to adjudicate")

    vetoed = [s for s, v in verdicts.items() if BY_SEAT[s].veto and v != "pass"]
    if vetoed:
        return {"outcome": "fail", "reason": f"veto from {sorted(vetoed)}", "vetoed": sorted(vetoed)}

    passes = sum(1 for v in verdicts.values() if v == "pass")
    if passes * 2 > len(verdicts):
        return {"outcome": "pass", "reason": f"{passes}/{len(verdicts)} seats passed", "vetoed": []}
    return {"outcome": "fail",
            "reason": f"only {passes}/{len(verdicts)} seats passed; a tie does not pass",
            "vetoed": []}
