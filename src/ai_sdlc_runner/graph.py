"""graph.py — the node graph the runner walks: the skill's own flow, written down once.

CHG-20260822-04 task 6. The runner exists to be **an agent built on this flow** rather than a
dependency on somebody else's agent, so the flow is the specification and this module is it, stated
plainly. Nothing here is clever on purpose.

## Where the flow comes from

It is **shipped**, as a fenced block under `## State machine` in `references/autopilot-loop.md`
(lines 14–30), which task 1 already decomposed into the element
``references/autopilot-loop#state-machine``. `SKILL.md`'s `## The loop` carries a shortened variant
of the same flow.

That matters because CHG-20260822-04's D1 says the 99 flowchart nodes in the skill repo's
``design.md`` are not shipped and must not be reconstructed by hand — true of *that* diagram, and it
was read for two review rounds as "no flow is shipped anywhere", which is false. The flow below is
not a reconstruction of anything: it is the shipped block, written as data, with each node naming
the phrase it came from.

## Runner-authored fork point (D3): authored and pinned, not parsed

Writing the flow down rather than parsing the shipped block is a judgement, and D3 requires the
judgement to be named rather than left looking like it fell out of the data. It is fork point 8 in
`ai-guideline` §6's index. A different reader could parse the block — the reason not to is below.

## How it stays honest: one pin, no machinery

Each node carries ``source_phrase`` — a literal substring of the shipped block. A test asserts that
every phrase is present and that the nodes' order matches the phrases' order of first appearance.
If the skill changes its flow, the pin goes red.

The deliberate decision **not** to parse the block: it contains arrows that are not edges. Line 10 is
``→ operational verify (run it for real: operate → observe → pass; per policy)`` — the two arrows
inside the parentheses are prose, and a splitter would emit "observe" and "pass; per policy" as
nodes. Nineteen arrows in the block, at least two of them decoration. A parser could be taught to
skip parenthesised text, but that rule is hand-written against this block's typography, so parsing
buys no independence from human judgement — and it changes the **direction** of failure: a
misreading produces a wrong graph silently, and task 4's gate cannot catch it because the store did
not change. Writing the flow down and pinning it means a mistake shows up as a red test instead.

## What the graph must not lose

The shipped flow is not a line. Flattening it would quietly drop the parts that carry the most
meaning, so they are represented explicitly and tested:

* the **per-task loop** — "[ per unticked task T_i: … ]" — is a back edge, and it is the same
  mechanism as resume: an already-ticked task is simply not the frontier.
* the **review fail branch** — one fix pass, then re-review, and "second fail = halt" — is a bounded
  retry, not a repeat-until-green.
* the **CHG-not-confirmed branch** — "no → requirement/modification governance first" — loops back
  into requirement analysis and structure design, which the runner **drives itself**: it is the agent
  built on this flow, not a driver handing that stage to something else. (An earlier draft of this
  paragraph called it a halt-with-reason while the node table already drove it; the review panel
  caught the contradiction. The table was right.)

* the **plan-check failure** — "exit 2 on failure — a bad plan never starts" — is a stop, on the same
  footing as "second fail = halt". Both failure modes are stated inside the shipped block, so both
  get a node; representing one and leaving the other as a prose note was the inconsistency the panel
  found.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: The shipped element this graph is pinned to. Exactly one authority: `SKILL.md`'s `## The loop` is
#: a shortened variant (it omits the confirm gate and every branch), so pinning to both would fail
#: for a difference in detail rather than a difference in flow.
SOURCE_ELEMENT = "references/autopilot-loop#state-machine"
SOURCE_REL_PATH = "elements/references/autopilot-loop/001-state-machine.md"

STEP = "step"
DECISION = "decision"
LOOP = "loop"
TERMINAL = "terminal"


@dataclass(frozen=True)
class Node:
    """One node of the shipped flow.

    ``checkpoints`` are dispatch-element ids from task 2 — policy hanging on the node, never the
    source of its position. ``role`` is the role whose work order this node dispatches; ``None``
    means the runner does it itself (reading the ledger, checking a gate) and nothing is dispatched.
    """

    id: str
    kind: str
    source_phrase: str
    role: Optional[str] = None
    checkpoints: Tuple[str, ...] = ()
    next: Optional[str] = None
    #: decision/loop nodes only: label → target node id.
    branches: Dict[str, str] = field(default_factory=dict)
    note: str = ""


#: The flow, in the shipped order. Roles follow the skill's own least-privilege table: the lead
#: implementer is the only role with `can_spawn`, which is what makes "the lead dispatches the
#: engineers" a shipped fact rather than an arrangement invented here; the verifier is read-only on
#: what it verifies but may execute, which is what "QA runs the whole thing for real" needs.
NODES: Tuple[Node, ...] = (
    Node(id="handshake", kind=STEP, source_phrase="entry handshake", next="chg_confirmed",
         note="governance layer: knowledge INDEX + pending CHG scan"),
    Node(id="chg_confirmed", kind=DECISION, source_phrase="CHG exists & confirmed?",
         branches={"no": "requirement_analysis", "yes": "plan_check"},
         note="'no' leaves the runner's layer: governance first, then re-enter"),
    Node(id="requirement_analysis", kind=STEP, source_phrase="requirement/modification governance",
         role="analyst", checkpoints=("halt:requirement_confirmed",), next="structure_design",
         note="the user's requirement becomes a Guideline"),
    Node(id="structure_design", kind=STEP, source_phrase="requirement/modification governance",
         role="analyst", checkpoints=("halt:structure_confirmed",), next="chg_confirmed",
         note="governance produces the CHG, then the flow re-enters the decision"),
    Node(id="plan_check", kind=DECISION, source_phrase="plan-check gate", role="lead-implementer",
         branches={"pass": "confirm_gate", "fail": "halt_bad_plan"},
         note="the block states this gate's own failure mode; it gets a stop, like second-fail does"),
    Node(id="halt_bad_plan", kind=TERMINAL, source_phrase="exit 2 on failure",
         note="a bad plan never starts"),
    Node(id="confirm_gate", kind=STEP, source_phrase="confirm gate", role="lead-implementer",
         checkpoints=("autopilot:confirm_gate", "halt:before_implement"), next="next_task",
         note="feasibility and risk confirmed before any engineer is dispatched"),
    Node(id="next_task", kind=LOOP, source_phrase="per unticked task",
         branches={"task": "build", "none": "branch_review"},
         note="the frontier is the first unticked task — the loop and resume are one mechanism"),
    Node(id="build", kind=STEP, source_phrase="TDD build", role="sub-implementer", next="task_tests",
         note="one small module per dispatched engineer"),
    Node(id="task_tests", kind=STEP, source_phrase="task tests", role="sub-implementer",
         next="task_review", note="the engineer's own verification"),
    Node(id="task_review", kind=DECISION, source_phrase="read-only task review",
         role="lead-implementer", checkpoints=("autopilot:task_review",),
         branches={"pass": "tick_commit", "fail": "fix_pass"},
         note="the lead reviews work it did not write"),
    Node(id="tick_commit", kind=STEP, source_phrase="tick + commit", role="lead-implementer",
         next="next_task"),
    Node(id="fix_pass", kind=STEP, source_phrase="one fix pass", role="sub-implementer",
         next="re_review"),
    Node(id="re_review", kind=DECISION, source_phrase="re-review", role="lead-implementer",
         branches={"pass": "tick_commit", "fail": "halt_second_fail"},
         note="bounded retry: exactly one fix pass, never repeat-until-green"),
    Node(id="halt_second_fail", kind=TERMINAL, source_phrase="second fail = halt"),
    Node(id="branch_review", kind=STEP, source_phrase="whole-branch review", role="lead-implementer",
         next="operational_verify", note="no policy checkpoint: this is a code gate, not a risk gate"),
    Node(id="operational_verify", kind=STEP, source_phrase="operational verify", role="verifier",
         checkpoints=("autopilot:operational_verify",), next="acceptance",
         note="QA runs it for real; task tests are not acceptance"),
    Node(id="acceptance", kind=DECISION, source_phrase="acceptance", role="verifier",
         checkpoints=("autopilot:acceptance",),
         branches={"pass": "pr", "fail": "acceptance_failed"}),
    Node(id="acceptance_failed", kind=STEP, source_phrase="acceptance",
         checkpoints=("halt:acceptance_failed",), next="next_task",
         note="back into the fix loop, under the policy's own gate"),
    Node(id="pr", kind=STEP, source_phrase="PR", role="lead-implementer",
         checkpoints=("autopilot:pr",), next="merge"),
    Node(id="merge", kind=STEP, source_phrase="merge", role="lead-implementer",
         checkpoints=("autopilot:merge", "halt:before_merge_or_release"), next="close_out"),
    Node(id="close_out", kind=TERMINAL, source_phrase="close-out",
         note="CHG status + Commit/PR + recurrence check + knowledge"),
)

BY_ID: Dict[str, Node] = {node.id: node for node in NODES}


class GraphError(Exception):
    """Raised when the graph and the shipped flow, the elements, or itself disagree."""


def source_text(tree: str | Path) -> str:
    """The shipped state-machine element, read from an emitted element tree."""
    path = Path(tree) / SOURCE_REL_PATH
    if not path.is_file():
        raise GraphError(
            f"the shipped flow element is missing: {path} ({SOURCE_ELEMENT}). The graph is pinned "
            f"to it, so without it nothing here can be checked against its source.")
    return path.read_text(encoding="utf-8")


def checkpoint_ids() -> List[str]:
    """Every checkpoint attached anywhere on the graph, in graph order, with duplicates kept.

    Duplicates are kept on purpose: the coverage check wants to see a checkpoint attached **exactly
    once**, and silently de-duplicating here would hide the case it exists to catch.
    """
    return [cp for node in NODES for cp in node.checkpoints]


def dispatched_roles() -> List[str]:
    """Roles this graph actually dispatches work orders to, deduplicated and sorted."""
    return sorted({node.role for node in NODES if node.role})


def validate() -> None:
    """Internal consistency: every edge lands somewhere, every node is reachable, kinds are sane.

    Deliberately separate from the pin against the shipped text: this catches a graph that is
    malformed, the pin catches a graph that is well-formed but no longer the skill's flow.
    """
    ids = set(BY_ID)
    if len(BY_ID) != len(NODES):
        raise GraphError("duplicate node id in the graph")
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

    reachable = {"handshake"}
    frontier = ["handshake"]
    while frontier:
        current = BY_ID[frontier.pop()]
        for target in list(current.branches.values()) + ([current.next] if current.next else []):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
        reachable.add(current.id)
    unreachable = sorted(ids - reachable)
    if unreachable:
        raise GraphError(f"unreachable node(s): {unreachable}")
