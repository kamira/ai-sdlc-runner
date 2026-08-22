"""graph.py — the development flow this runner drives, as data.

CHG-20260823-01. The flow is the one the requirement describes, node by node:

    user instruction → PM plans → PM confirms → lead confirms feasibility and risk →
    PM signs off → [ per module: engineer builds → engineer verifies its own work →
    lead reviews → record | one fix pass → re-review → second failure halts ] →
    review seats cross-check the whole change → QA tests and verifies → acceptance →
    PR → merge → close-out → user feedback → back to PM

It was **designed from** the ai-sdlc-autopilot flowchart and is **not read from it**. The previous
version pinned every node to a literal phrase of a shipped block; there is no shipped block here any
more, and pinning to one would be exactly the runtime dependency this change removes. What replaces
the pin is `policy.py`: every gate a node names must exist there, every role must have capabilities,
and both are asserted — correctness is checked against our own definitions rather than against a file
we no longer hold.

## One node, one kind of work

The requirement says it plainly, and it is the rule that decides where the boundaries fall: *一個項目
只做單一類型的工作*. Building, verifying your own work, and having it reviewed are three kinds of
work, so they are three nodes. Opening a PR and merging are two. Planning and confirming the plan are
two — the second is where a human can still say no.

Sub-steps *inside* one node are **effects**, not nodes: ticking a box, committing, and updating the
worklog are one kind of work — recording that a module is done — carried out in order with a probe
each.

## What is not a line

Three shapes carry most of the meaning and would be lost by flattening, so each is explicit:

* the **per-module loop** — one engineer per small module, and the loop is also the resume mechanism:
  an already-recorded module is simply not the frontier.
* the **bounded retry** — one fix pass, one re-review, and a second failure halts. Not
  repeat-until-green.
* the **feedback loop** — user feedback returns to PM, so the flow closes rather than ends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

STEP = "step"
DECISION = "decision"
LOOP = "loop"
TERMINAL = "terminal"


@dataclass(frozen=True)
class Node:
    """One node: one kind of work.

    ``role`` names who does it — ``None`` means the runner does it itself and asks no model, which is
    what keeps "every asking node is its own session" a statement about the nodes that ask. ``gate``
    names the policy gate consulted before the work, where the flow puts one.
    """

    id: str
    kind: str
    label: str
    role: Optional[str] = None
    gate: Optional[str] = None
    #: When the gate is consulted. ``before`` stops instead of doing the work; ``after`` does the
    #: work and then stops with its result in hand. Getting this backwards makes a gate unreachable:
    #: a review that halts *before* it runs is a review a high-risk change can never get, which is
    #: exactly what an independent verifier found here.
    gate_when: str = "before"
    next: Optional[str] = None
    branches: Dict[str, str] = field(default_factory=dict)
    #: For a decision node with a role: the answer names the branch, and these are the branches the
    #: answer may name. A decision whose branches come from the plan while somebody is being asked
    #: is a question whose answer changes nothing.
    answer_decides: bool = False
    note: str = ""


NODES: Tuple[Node, ...] = (
    Node("intake", STEP, "the user's instruction arrives", next="pm_plan",
         note="the runner reads it; nobody is asked anything yet"),
    Node("pm_plan", STEP, "PM turns the instruction into a plan", role="pm", next="pm_confirm"),
    Node("pm_confirm", DECISION, "PM confirms the plan", role="pm", gate="plan_confirmed",
         gate_when="after", answer_decides=True,
         branches={"yes": "lead_assess", "no": "pm_plan"},
         note="PM is asked, and the answer decides; the gate then stops with that answer in hand"),
    Node("lead_assess", STEP, "the lead confirms feasibility and risk", role="lead",
         gate="feasibility_confirmed", next="pm_signoff",
         note="judged before anyone is dispatched, which is why the lead is asked first"),
    Node("pm_signoff", DECISION, "PM signs off on the lead's assessment", role="pm",
         gate="before_dispatch", gate_when="after", answer_decides=True,
         branches={"yes": "next_module", "no": "pm_plan"}),
    Node("next_module", LOOP, "take the next unbuilt module",
         branches={"module": "engineer_build", "none": "lead_review"},
         note="the frontier is the first module with no record — the loop and the resume are one"),
    Node("engineer_build", STEP, "an engineer builds one small module", role="engineer",
         next="engineer_selfverify"),
    Node("engineer_selfverify", STEP, "the engineer verifies its own work", role="engineer",
         gate="self_verify", next="lead_task_review",
         note="its own work — which is why it is never the last word"),
    Node("lead_task_review", DECISION, "the lead reviews that module", role="lead",
         gate="task_review", gate_when="after", answer_decides=True,
         branches={"pass": "record_module", "fail": "fix_pass"},
         note="the lead reviews work it did not write, and the review's answer is what routes"),
    Node("record_module", STEP, "record the module as done", next="next_module",
         note="tick, commit, update the worklog — one kind of work, three ordered effects"),
    Node("fix_pass", STEP, "one fix pass", role="engineer", next="re_review"),
    Node("re_review", DECISION, "the lead re-reviews", role="lead", answer_decides=True,
         branches={"pass": "record_module", "fail": "halt_second_fail"},
         note="bounded: exactly one fix pass, never repeat-until-green"),
    Node("halt_second_fail", TERMINAL, "a second failure halts",
         note="two failures on one module is not something retrying fixes"),
    Node("lead_review", DECISION, "review seats cross-check the whole change", role="seat",
         gate="lead_review", gate_when="after",
         branches={"pass": "qa_verify", "fail": "review_failed"},
         note="one or many seats, each in its own session. The branch comes from adjudicating their "
              "verdicts — veto, then majority, and a tie does not pass"),
    Node("review_failed", STEP, "the panel did not pass it", next="next_module",
         note="back into the module loop; the panel's reasons travel with the run"),
    Node("qa_verify", STEP, "QA tests and verifies the whole change", role="qa", gate="qa_verify",
         gate_when="after", next="qa_accept",
         note="run for real; a module's own tests are not this"),
    Node("qa_accept", DECISION, "acceptance", role="qa", gate="acceptance", gate_when="after",
         answer_decides=True, branches={"pass": "pr", "fail": "acceptance_failed"}),
    Node("acceptance_failed", STEP, "back into the module loop", next="next_module"),
    Node("pr", STEP, "open the pull request", role="lead", gate="pr", next="merge"),
    Node("merge", STEP, "merge", role="lead", gate="merge", next="close_out",
         note="a one-way door — its gate is consulted BEFORE, because the stop has to come before "
              "the door swings, not after"),
    Node("close_out", STEP, "close out: status, links, what was learned", next="feedback"),
    Node("feedback", DECISION, "user feedback returns to PM",
         branches={"more": "pm_plan", "done": "done"},
         note="the flow closes rather than ends — new feedback is a new plan"),
    Node("done", TERMINAL, "nothing further was asked for"),
)

BY_ID: Dict[str, Node] = {n.id: n for n in NODES}


class GraphError(Exception):
    """Raised when the graph disagrees with itself or with the policy."""


def gates_used() -> List[str]:
    """Every gate the flow consults, in flow order, duplicates kept so a test can see them."""
    return [n.gate for n in NODES if n.gate]


def roles_used() -> List[str]:
    return sorted({n.role for n in NODES if n.role})


def asking_nodes() -> List[str]:
    """The nodes that ask a model — the ones the one-session rule binds."""
    return [n.id for n in NODES if n.role]


def validate() -> None:
    """Internal consistency, and agreement with the policy.

    Every edge lands somewhere, every node is reachable, and every gate and role a node names exists
    in `policy.py`. A node naming a gate nothing defines is the failure that would otherwise show up
    as a run halting on something nobody wrote down.
    """
    from . import policy

    if len(BY_ID) != len(NODES):
        raise GraphError("duplicate node id")
    ids = set(BY_ID)
    for node in NODES:
        targets = list(node.branches.values()) + ([node.next] if node.next else [])
        for target in targets:
            if target not in ids:
                raise GraphError(f"node {node.id!r} points at unknown node {target!r}")
        if node.kind == TERMINAL and targets:
            raise GraphError(f"terminal node {node.id!r} has outgoing edges")
        if node.kind in (DECISION, LOOP) and len(node.branches) < 2:
            raise GraphError(f"{node.kind} node {node.id!r} needs at least two branches")
        if node.kind == STEP and not node.next:
            raise GraphError(f"step node {node.id!r} has no successor")
        if node.gate and node.gate not in policy.GATES:
            raise GraphError(
                f"node {node.id!r} names gate {node.gate!r}, which policy.py does not define")
        if node.role and node.role not in policy.BY_ROLE:
            raise GraphError(
                f"node {node.id!r} names role {node.role!r}, which policy.py does not define")
        if node.gate_when not in ("before", "after"):
            raise GraphError(f"node {node.id!r} has an unknown gate phase {node.gate_when!r}")
        if node.gate_when == "after" and not node.gate:
            raise GraphError(f"node {node.id!r} has a gate phase but no gate")
        if node.answer_decides and not node.role:
            raise GraphError(
                f"node {node.id!r} says its answer decides, but nobody is asked at it")

    reachable = {"intake"}
    frontier = ["intake"]
    while frontier:
        current = BY_ID[frontier.pop()]
        for target in list(current.branches.values()) + ([current.next] if current.next else []):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    unreachable = sorted(ids - reachable)
    if unreachable:
        raise GraphError(f"unreachable node(s): {unreachable}")
