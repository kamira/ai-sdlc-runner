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

#: **How to read the models configured on a node.** A node may have several models attached, and
#: several models mean two entirely different things depending on the node: at a verdict they are
#: voices to be adjudicated, at a build they are a pool one of which does the work. That difference
#: is not derivable — ``engineer_build`` (a pool) and ``engineer_selfverify`` (follows the builder)
#: are both ``role="engineer"``, both ``STEP``, both branchless — so it is **declared here** and
#: nowhere else. A runner that worked it out from a node's id would be reading a name as evidence,
#: which this repository has already had to stop itself doing once.
#:
#: The mode says how to *read* the model list. It does not claim how long the list is. A
#: ``MODEL_PANEL`` with one model configured is one voice, adjudicated trivially; a ``SINGLE`` with
#: three configured is a configuration error, not a panel.
RUNNER = "runner"          #: nobody is asked; the runner does the work itself
SINGLE = "single"          #: exactly one model, one session
SEAT_PANEL = "seat_panel"  #: the review seats — each its own question, independence not configurable
MODEL_PANEL = "model_panel"  #: N models on *one* question, adjudicated
POOL = "pool"              #: N models a main may dispatch to; one of them does the work
FOLLOWS = "follows"        #: whichever model answered the node named in ``follows``

MODES = (RUNNER, SINGLE, SEAT_PANEL, MODEL_PANEL, POOL, FOLLOWS)


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
    #: How to read the models configured here — see ``MODES``. Declared, never inferred.
    mode: str = SINGLE
    #: ``POOL`` only: the **role** that dispatches. A role and not a node id, because no node
    #: represents "the lead handing out work" — the dispatching is part of the build node itself.
    main: Optional[str] = None
    #: ``FOLLOWS`` only: the **node id** whose model to reuse. A node id and not a role, because
    #: roles are not unique — three nodes are ``role="lead"`` — and "verify what *this* build
    #: produced" cannot be said by naming a role.
    follows: Optional[str] = None
    #: Where a **rejected** gate sends the run. ``None`` means this gate cannot be rejected — it can
    #: be approved or left waiting, and nothing else.
    #:
    #: Declared per node rather than defaulting to one place. The mock-up sent every rejection to
    #: `pm_plan`, which is right for a plan nobody agreed with and wrong for a QA run that failed:
    #: that belongs back in the module loop, not back at the drawing board. A universal target is a
    #: guess wearing the shape of a rule.
    #:
    #: Some gates genuinely have nowhere to go. Rejecting `merge` means *do not merge* — there is no
    #: node for that, and inventing one would be pretending a refusal is a step. Those gates carry
    #: ``None``, and a console must not offer a control the graph cannot honour.
    rejects_to: Optional[str] = None
    note: str = ""


NODES: Tuple[Node, ...] = (
    Node("intake", STEP, "the user's instruction arrives", next="pm_plan", mode=RUNNER,
         note="the runner reads it; nobody is asked anything yet"),
    Node("pm_plan", STEP, "PM turns the instruction into a plan", role="pm", next="pm_confirm",
         mode=SINGLE,
         note="a plan is work, not a verdict: several models would mean several candidate plans "
              "and no rule for choosing between them"),
    Node("pm_confirm", DECISION, "PM confirms the plan", role="pm", gate="plan_confirmed",
         gate_when="after", answer_decides=True, mode=MODEL_PANEL, rejects_to="pm_plan",
         branches={"yes": "lead_assess", "no": "pm_plan"},
         note="PM is asked, and the answer decides; the gate then stops with that answer in hand"),
    Node("lead_assess", STEP, "the lead confirms feasibility and risk", role="lead",
         gate="feasibility_confirmed", gate_when="after", next="pm_signoff", mode=SINGLE,
         rejects_to="pm_plan",
         note="judged before anyone is dispatched, which is why the lead is asked first. The gate "
              "is consulted AFTER: the thing a person is being asked to confirm IS the lead's "
              "assessment, and stopping in front of it hands them an empty page"),
    Node("pm_signoff", DECISION, "PM signs off on the lead's assessment", role="pm",
         gate="before_dispatch", gate_when="after", answer_decides=True, mode=MODEL_PANEL,
         rejects_to="pm_plan",
         branches={"yes": "next_module", "no": "pm_plan"}),
    Node("next_module", LOOP, "take the next unbuilt module", mode=RUNNER,
         branches={"module": "engineer_build", "none": "lead_review"},
         note="the frontier is the first module with no record — the loop and the resume are one"),
    Node("engineer_build", STEP, "an engineer builds one small module", role="engineer",
         next="engineer_selfverify", mode=POOL, main="lead",
         note="several models here is the pool the lead may dispatch to, and exactly one of them "
              "does the work. Calling that a vote would misdescribe what happened"),
    Node("engineer_selfverify", STEP, "the engineer verifies its own work", role="engineer",
         gate="self_verify", next="lead_task_review", mode=FOLLOWS, follows="engineer_build",
         rejects_to="engineer_build",
         note="its own work — which is why it is never the last word"),
    Node("lead_task_review", DECISION, "the lead reviews that module", role="lead",
         gate="task_review", gate_when="after", answer_decides=True, mode=MODEL_PANEL,
         rejects_to="fix_pass",
         branches={"pass": "record_module", "fail": "fix_pass"},
         note="the lead reviews work it did not write, and the review's answer is what routes"),
    Node("record_module", STEP, "record the module as done", next="next_module", mode=RUNNER,
         note="tick, commit, update the worklog — one kind of work, three ordered effects"),
    Node("fix_pass", STEP, "one fix pass", role="engineer", next="re_review",
         mode=FOLLOWS, follows="engineer_build",
         note="the fix goes back to whoever built it — handing a rework to a model that has not "
              "seen the module is a second first attempt"),
    Node("re_review", DECISION, "the lead re-reviews", role="lead", answer_decides=True,
         mode=MODEL_PANEL,
         branches={"pass": "record_module", "fail": "halt_second_fail"},
         note="bounded: exactly one fix pass, never repeat-until-green"),
    Node("halt_second_fail", TERMINAL, "a second failure halts", mode=RUNNER,
         note="two failures on one module is not something retrying fixes"),
    Node("lead_review", DECISION, "review seats cross-check the whole change", role="seat",
         gate="lead_review", gate_when="after", mode=SEAT_PANEL, rejects_to="review_failed",
         branches={"pass": "qa_verify", "fail": "review_failed"},
         note="one or many seats, each in its own session. The branch comes from adjudicating their "
              "verdicts — veto, then majority, and a tie does not pass"),
    Node("review_failed", STEP, "the panel did not pass it", next="next_module", mode=RUNNER,
         note="back into the module loop; the panel's reasons travel with the run"),
    Node("qa_verify", STEP, "QA tests and verifies the whole change", role="qa", gate="qa_verify",
         gate_when="after", next="qa_accept", mode=SINGLE, rejects_to="next_module",
         note="run for real; a module's own tests are not this"),
    Node("qa_accept", DECISION, "acceptance", role="qa", gate="acceptance", gate_when="after",
         answer_decides=True, mode=MODEL_PANEL, rejects_to="acceptance_failed",
         branches={"pass": "pr", "fail": "acceptance_failed"}),
    Node("acceptance_failed", STEP, "back into the module loop", next="next_module", mode=RUNNER),
    Node("pr", STEP, "open the pull request", role="lead", gate="pr", next="merge", mode=SINGLE),
    Node("merge", STEP, "merge", role="lead", gate="merge", next="close_out", mode=SINGLE,
         note="a one-way door — its gate is consulted BEFORE, because the stop has to come before "
              "the door swings, not after"),
    Node("close_out", STEP, "close out: status, links, what was learned", next="feedback",
         mode=RUNNER),
    Node("feedback", DECISION, "user feedback returns to PM", mode=RUNNER,
         branches={"more": "pm_plan", "done": "done"},
         note="the flow closes rather than ends — new feedback is a new plan"),
    Node("done", TERMINAL, "nothing further was asked for", mode=RUNNER),
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

        # --- execution mode ------------------------------------------------------------------
        #
        # These rules **check** that two independently declared facts agree. They do not *derive*
        # one from the other, and the difference is the whole point: deriving the mode from the
        # role would mean a node's role silently decides how its models are read, which is a name
        # standing in for a constraint. Checking means both are written down and a disagreement is
        # a build error rather than a surprise at run time.
        if node.mode not in MODES:
            raise GraphError(f"node {node.id!r} has unknown mode {node.mode!r}")
        if (node.role is None) != (node.mode == RUNNER):
            raise GraphError(
                f"node {node.id!r} is mode {node.mode!r} with role {node.role!r} — a node with no "
                f"role asks nobody and must be {RUNNER!r}, and only such a node may be")
        if (node.role == "seat") != (node.mode == SEAT_PANEL):
            raise GraphError(
                f"node {node.id!r} is mode {node.mode!r} with role {node.role!r} — the review "
                f"seats are the only {SEAT_PANEL!r}, and they are always one")
        if node.mode == MODEL_PANEL and node.kind != DECISION:
            raise GraphError(
                f"node {node.id!r} is a {MODEL_PANEL!r} but a {node.kind!r} — several models on one "
                f"question are voices to adjudicate, and a node that reaches no verdict has nothing "
                f"to adjudicate. Work-producing nodes with several models are not settled")
        if node.mode == POOL:
            if not node.main:
                raise GraphError(f"pool node {node.id!r} names no main to dispatch from")
            if node.main not in policy.BY_ROLE:
                raise GraphError(
                    f"pool node {node.id!r} names main {node.main!r}, which is not a role policy.py "
                    f"defines — `main` is a role, not a node id")
        elif node.main:
            raise GraphError(f"node {node.id!r} is mode {node.mode!r} and has no use for a main")
        if node.mode == FOLLOWS:
            if not node.follows:
                raise GraphError(f"follows node {node.id!r} names no node to follow")
            if node.follows not in ids:
                raise GraphError(
                    f"node {node.id!r} follows unknown node {node.follows!r} — `follows` is a node "
                    f"id, not a role, because a role names no single answer to follow")
            if BY_ID[node.follows].mode == FOLLOWS:
                raise GraphError(
                    f"node {node.id!r} follows {node.follows!r}, which follows something else — a "
                    f"chain of follows has no model at the end of it")
            if node.follows == node.id:
                raise GraphError(f"node {node.id!r} follows itself")
        elif node.follows:
            raise GraphError(f"node {node.id!r} is mode {node.mode!r} and has no use for a follows")

        # --- rejection routing -----------------------------------------------------------------
        if node.rejects_to is not None:
            if not node.gate:
                raise GraphError(
                    f"node {node.id!r} says where a rejection goes but has no gate to reject. Only "
                    f"a gate can be rejected, because rejecting is what a person does instead of "
                    f"approving")
            if node.rejects_to not in ids:
                raise GraphError(
                    f"node {node.id!r} rejects to unknown node {node.rejects_to!r}")
            if node.rejects_to == node.id:
                raise GraphError(
                    f"node {node.id!r} rejects to itself, which is a refusal that changes nothing")

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
