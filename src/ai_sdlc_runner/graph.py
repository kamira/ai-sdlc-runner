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

#: The four kinds, closed. `MODES` has been closed since it was written; `kind` was not, and the
#: difference cost something measurable: a nonsense `kind` was accepted on 23 of the 31 shipped
#: nodes, and `done` — the one terminal that is not `permanent`, so the rule below does not see it
#: — reached `engine.walk`'s `node.kind == TERMINAL` test as a non-terminal. The run still said
#: `finished`; `halted_at` went from `'done'` to `None`. A run that forgets where it ended is the
#: same loss CHG-20260907-06 repaired for the other branch of that line.
#:
#: **A closed set refuses nonsense; it does not refuse the wrong member.** `LOOP` and `DECISION`
#: are indistinguishable to every rule in this file and to every reader of `.kind` in the
#: repository — `LOOP` appears in exactly one condition, shared with `DECISION`. Measured: both
#: `LOOP` nodes relabelled `DECISION` is accepted, and 5 of the 10 `DECISION` nodes accept being
#: relabelled `LOOP` (the other 5 are caught by the model-panel rule, which is not about loops).
#: No structural rule can tell them apart, for the same reason CHG-20260907-08 could not derive
#: where a refusal may go: 25 of 31 nodes are on a cycle, so "loops" is not a connectivity
#: property here. Which kind a node is, is a declaration — `test_which_nodes_are_loops_is_pinned`
#: is what protects it.
KINDS = (STEP, DECISION, LOOP, TERMINAL)

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
SURVEY = "survey"          #: every seat is asked and **all** answers are kept — see below

MODES = (RUNNER, SINGLE, SEAT_PANEL, MODEL_PANEL, POOL, FOLLOWS, SURVEY)

#: ``SURVEY`` is the one mode that does **not** adjudicate, and the difference is the point.
#:
#: A panel answers *"may this proceed?"* — one question, one answer, and counting is how you get it.
#: A survey answers *"what is wrong with this?"* — as many answers as there are things wrong, where
#: counting **destroys** the information. A problem three seats missed and one saw is still a
#: problem, and outvoting it would be the panel agreeing not to know something.
#:
#: So a survey takes the union and no verdict is reached. Nothing is vetoed, nothing ties.


@dataclass(frozen=True)
class Node:
    """One node: one kind of work.

    ``role`` names who does it — ``None`` means the runner does it itself and asks no model, which is
    what keeps "every asking node is its own session" a statement about the nodes that ask. ``gate``
    names the policy gate this node is answerable to, where the flow puts one.

    **When** it is consulted is ``gate_when``'s job, ten lines below, and the two disagreed.
    This said *consulted before the work* as if that were the rule; measured, **seven of the
    ten gated nodes are ``after``** — only ``engineer_selfverify``, ``pr`` and ``merge`` are
    ``before`` (CHG-20260903-37). Two sentences in one class body, and the one a reader meets
    first was false about most of what it described.
    """

    id: str
    kind: str
    label: str
    role: Optional[str] = None
    gate: Optional[str] = None
    #: When the gate is consulted, and **only meaningful with a gate**: ``None`` on a node that
    #: has none. ``before`` stops instead of doing the work; ``after`` does the work and then stops
    #: with its result in hand. Getting this backwards makes a gate unreachable: a review that
    #: halts *before* it runs is a review a high-risk change can never get, which is exactly what
    #: an independent verifier found here.
    #:
    #: **It used to default to** ``"before"`` — the *minority* value, since seven of the ten gated
    #: nodes are ``after``. So a gated node whose author forgot the phase silently got the shape
    #: the paragraph above calls a defect, and `validate` had no way to tell the omission from a
    #: decision. There is no default now: a gate without a phase is a `GraphError` before the walk
    #: starts, and so is a phase without a gate (CHG-20260907-11).
    gate_when: Optional[str] = None
    next: Optional[str] = None
    branches: Dict[str, str] = field(default_factory=dict)
    #: For a decision node with a role: the answer names the branch, and these are the branches the
    #: answer may name. A decision whose branches come from the plan while somebody is being asked
    #: is a question whose answer changes nothing.
    answer_decides: bool = False
    #: For a node a **panel** routes: which branch each panel outcome names.
    #:
    #: A panel answers in `pass` / `fail` / `undecided` — `policy.adjudicate`'s vocabulary, and the
    #: only thing `engine` has to route on, because reading one of several voices would make a panel
    #: into whichever model was asked first. A node answers in its own words.
    #:
    #: **Only a `MODEL_PANEL` routes through this table**, and `validate` refuses a declaration on
    #: a `SEAT_PANEL` — there and nowhere else. Every other mode may declare one, because `engine`
    #: reads this table a second time after the branch is taken, to name the word meaning
    #: *ratified*, and for a node whose branches are its own words that read is the only way to
    #: name it. `test_a_node_that_is_not_a_panel_may_declare_panel_branches` holds that. Six nodes are model
    #: panels and five of those carry branches — `lead_assess`
    #: is the sixth and carries none. Three of the five happen to name their branches `pass` and
    #: `fail` and so need nothing here. Two —
    #: `pm_confirm` and `pm_signoff` — ask a person-shaped question and offer `yes` and `no`, and
    #: **had no route at all**: the outcome named no branch of theirs, so any run with more than one
    #: model configured on either died there with `has no branch 'pass'`. Untested, because the
    #: panel tests only ever configured the `pass`/`fail` nodes (CHG-20260901-11).
    #:
    #: A fourth node names `pass`/`fail` too — `lead_review`, the one `SEAT_PANEL` — and is **not**
    #: counted above, because this table is not what routes it: `engine._adjudicate` returns the
    #: outcome as the branch name and never reads this. It therefore has no escape here and must
    #: name its branches in the panel's words, which `validate` refuses it for since
    #: CHG-20260908-03. Until then it was asked nothing at all, and the sentence above said
    #: *"three decision nodes"* without saying three of what.
    #:
    #: Declared, never inferred. Reading `yes` as the affirmative *because the string says yes* is a
    #: name standing in for a constraint, which is the defect this whole file is written against —
    #: and a third node offering `approve`/`reject` tomorrow would silently have no route again.
    #:
    #: `undecided` is deliberately unmappable: it is not a branch, it is the absence of one, and it
    #: has somewhere to go already — the ruling path, where a person decides and it is recorded as
    #: theirs. `validate` refuses it here.
    panel_branches: Dict[str, str] = field(default_factory=dict)
    #: How to read the models configured here — see ``MODES``. Declared, never inferred.
    #:
    #: **There is no default, and ``None`` is never a valid state.** The sentinel is there only
    #: so that an omission is a `GraphError` naming the node, instead of a `TypeError` raised
    #: from a constructor where nothing can say which node or what was missing.
    #:
    #: It used to default to ``SINGLE``, which is **4 of the 31 nodes**; ``RUNNER`` is 15. So
    #: the default was the minority value, and a node whose author never thought about its mode
    #: was read as one model in one session. Measured: `lead_task_review` rebuilt from its own
    #: fields minus `mode` came back ``single`` against a real ``model_panel``, and `validate`
    #: **accepted** the graph. The record that introduced this field named that hazard and
    #: shipped the default anyway (CHG-20260823-11, *"every unconsidered node would land there
    #: silently"*); CHG-20260907-11 had already taken the same decision one field up, where
    #: `gate_when` defaulted to the 3-of-10 value (CHG-20260907-26).
    mode: Optional[str] = None
    #: This terminal is a **give-up**, not an ending (CHG-20260827-22). `done` is where the flow was
    #: designed to arrive; `halt_second_fail` and `halt_unreconciled` are where it stopped because
    #: nothing it can do would help. Both used to report `state: finished`, which made "it worked"
    #: and "it gave up" the same shape — the very distinction the state vocabulary exists to draw.
    #:
    #: Declared rather than matched on an id prefix: `halt_` is a naming convention, and a
    #: convention is not a constraint. A terminal node added tomorrow and called `abandoned` would
    #: report success, and nothing would say so.
    permanent: bool = False
    #: This node's answers are **risk grades**, not branch labels (CHG-20260827-17). Declared here
    #: rather than matched on the node's id in the engine, for the reason this file exists: a node
    #: id in a condition is a name standing in for a constraint, and the constraint is *what kind of
    #: thing this node's voices are answering*.
    #:
    #: Until such a node's grade is signed off, every gate resolves at the **strictest** grade any
    #: voice proposed — see `engine._grade_in_force`. The grade under review cannot set the height
    #: of the gate reviewing it.
    grades_risk: bool = False
    #: Passing this node **settles** the grade a `grades_risk` node proposed (CHG-20260827-17).
    #: Separate from `grades_risk` because proposing and ratifying are two acts by two roles: the
    #: lead grades, the PM signs off. Until this node passes, gates resolve at the strictest
    #: candidate — which is what stops the assessment lowering the gate standing over its own
    #: review.
    settles_risk: bool = False
    #: ``POOL`` only: the **role** that dispatches. A role and not a node id, because no node
    #: represents "the lead handing out work" — the dispatching is part of the build node itself.
    main: Optional[str] = None
    #: ``FOLLOWS`` only: the **node id** whose model to reuse. A node id and not a role, because
    #: roles are not unique — several nodes are ``role="lead"`` — and "verify what *this*
    #: build produced" cannot be said by naming a role.
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
    Node("intake", STEP, "the user's instruction arrives", next="intake_review", mode=RUNNER,
         note="the runner reads it; nobody is asked anything yet"),
    Node("intake_review", STEP, "the seats read the requirement", role="seat",
         next="pm_plan", mode=SURVEY,
         note="before anything is planned. Every seat says what is wrong and what is missing, and "
              "ALL of it is kept — this is the one place several voices are collected rather than "
              "adjudicated, because 'what is wrong with this' has as many answers as there are "
              "things wrong and counting them would throw the information away. NO GATE: what "
              "stops a run here is the requirement being incomplete, not a risk grade — a gate "
              "that fires on a complete requirement would be asking a person to approve the "
              "absence of a problem, and one that never fires is decoration"),
    Node("pm_plan", STEP, "PM turns the instruction into a plan", role="pm", next="plan_scope",
         mode=SINGLE,
         note="a plan is work, not a verdict: several models would mean several candidate plans "
              "and no rule for choosing between them"),
    Node("pm_confirm", DECISION, "PM confirms the plan", role="pm", gate="plan_confirmed",
         gate_when="after", answer_decides=True, mode=MODEL_PANEL, rejects_to="pm_plan",
         branches={"yes": "lead_assess", "no": "pm_plan"},
         panel_branches={"pass": "yes", "fail": "no"},
         note="PM is asked, and the answer decides; the gate then stops with that answer in hand"),
    Node("plan_scope", LOOP, "one workstream or several", mode=RUNNER,
         branches={"split": "sub_plan", "single": "pm_confirm"},
         note="decided from the plan's own `workstreams`, the way `next_module` is decided from the "
              "run's record rather than from a list somebody wrote in advance. A programme with one "
              "workstream takes `single` and never enters the second tier — which is what keeps "
              "every plan written before CHG-20260827-22 behaving exactly as it did"),
    Node("sub_plan", STEP, "each workstream is planned at its own scope", role="planner",
         next="reconcile", mode=POOL, main="pm",
         note="the second planning tier, and the reason the tree is three deep. Dispatched by the "
              "PM; the planner dispatches nothing, which is the bound (`policy.MAX_DISPATCH_DEPTH`)"),
    Node("reconcile", DECISION, "the sub-plans are reconciled against each other", mode=RUNNER,
         branches={"agree": "pm_confirm", "conflict": "pm_plan",
                   "unresolved": "halt_unreconciled"},
         note="the node with no equivalent before this. `lead_review` reviews the CHANGE; nothing "
              "reviewed the PLANS against each other, so two planners could pick incompatible "
              "interfaces and the first thing to notice was a failing build several nodes later — "
              "or nothing, and the inconsistency shipped. **Nobody is asked**: two declarations "
              "naming the same interface differently is a fact about the plans, and a fact is not "
              "improved by voting on it. That is also why this node has no role"),
    Node("halt_unreconciled", TERMINAL, "the same interface conflict came back", mode=RUNNER,
         permanent=True,
         note="bounded: exactly one revision pass, the same bound `re_review` puts on a fix. "
              "`conflict` routes to `pm_plan`, whose answer cannot change the declarations — they "
              "come from the plan — so without this the run would cycle until `max_steps` and an "
              "operator would be told only that something looped"),
    Node("lead_assess", STEP, "the lead confirms feasibility and risk", role="lead",
         gate="feasibility_confirmed", gate_when="after", next="pm_signoff", mode=MODEL_PANEL,
         grades_risk=True, rejects_to="pm_plan",
         note="judged before anyone is dispatched, which is why the lead is asked first. The gate "
              "is consulted AFTER: the thing a person is being asked to confirm IS the lead's "
              "assessment, and stopping in front of it hands them an empty page. **A panel since "
              "CHG-20260827-17**: this was the one input deciding which row of the gate table every "
              "later node reads, and the only consequential decision in the flow no panel saw"),
    Node("pm_signoff", DECISION, "PM signs off on the lead's assessment", role="pm",
         gate="before_dispatch", gate_when="after", answer_decides=True, mode=MODEL_PANEL,
         rejects_to="pm_plan", settles_risk=True,
         branches={"yes": "next_module", "no": "pm_plan"},
         panel_branches={"pass": "yes", "fail": "no"},
         note="the grade becomes the run's grade here, not where it was proposed. Before "
              "CHG-20260827-17 this node's own gate was resolved from the grade it is reviewing — "
              "the reviewer stood at a height the reviewed thing chose"),
    Node("next_module", LOOP, "take the next unbuilt module", mode=RUNNER,
         branches={"module": "engineer_build", "none": "lead_review"},
         note="the frontier is the first module with no record — the loop and the resume are one"),
    Node("engineer_build", STEP, "an engineer builds one small module", role="engineer",
         next="engineer_selfverify", mode=POOL, main="lead",
         note="several models here is the pool the lead may dispatch to, and exactly one of them "
              "does the work. Calling that a vote would misdescribe what happened"),
    Node("engineer_selfverify", STEP, "the engineer verifies its own work", role="engineer",
         gate="self_verify", gate_when="before", next="lead_task_review", mode=FOLLOWS,
         follows="engineer_build",
         rejects_to="engineer_build",
         note="its own work — which is why it is never the last word"),
    Node("lead_task_review", DECISION, "the lead reviews that module", role="lead",
         gate="task_review", gate_when="after", answer_decides=True, mode=MODEL_PANEL,
         rejects_to="fix_pass",
         branches={"pass": "module_built", "fail": "fix_pass"},
         note="the lead reviews work it did not write, and the review's answer is what routes"),
    Node("module_built", DECISION, "did this lap build a module", mode=RUNNER,
         branches={"yes": "record_module", "no": "next_module"},
         note="the guard on the record (CHG-20260828-15). An engineer answering `{\"module\": \"\"}` "
              "is saying there is nothing left, and the lap still walked on to `record_module` — "
              "whose effects are 'tick, commit, update the worklog'. A worklog entry would claim a "
              "module that was never built, and `examples/weather-spa` declares those operations, "
              "so it was live rather than latent.\n\n"
              "Nobody is asked: what the engineer said is a fact in the run's record, and reading "
              "it is not a judgement. Both `pass` edges route through here, so a fix pass that "
              "built nothing is caught too"),
    Node("record_module", STEP, "record the module as done", next="next_module", mode=RUNNER,
         note="tick, commit, update the worklog — one kind of work, three ordered effects. Reached "
              "only through `module_built`, which is what keeps those three off an empty lap"),
    Node("fix_pass", STEP, "one fix pass", role="engineer", next="re_review",
         mode=FOLLOWS, follows="engineer_build",
         note="the fix goes back to whoever built it — handing a rework to a model that has not "
              "seen the module is a second first attempt"),
    Node("re_review", DECISION, "the lead re-reviews", role="lead", answer_decides=True,
         mode=MODEL_PANEL,
         branches={"pass": "module_built", "fail": "halt_second_fail"},
         note="bounded: exactly one fix pass, never repeat-until-green"),
    Node("halt_second_fail", TERMINAL, "a second failure halts", mode=RUNNER, permanent=True,
         note="two failures on one module is not something retrying fixes"),
    Node("lead_review", DECISION, "review seats cross-check the whole change", role="seat",
         gate="lead_review", gate_when="after", mode=SEAT_PANEL, rejects_to="review_failed",
         branches={"pass": "qa_verify", "fail": "review_failed"},
         note="one or many seats, each in its own session. The branch comes from adjudicating their "
              "verdicts — veto, then majority, and a tie does not pass"),
    Node("review_failed", STEP, "the panel did not pass it", next="change_retry", mode=RUNNER,
         note="back into the module loop; the panel's reasons travel with the run. Through "
              "`change_retry` since CHG-20260828-22, which is what counts the trip"),
    Node("qa_verify", STEP, "QA tests and verifies the whole change", role="qa", gate="qa_verify",
         gate_when="after", next="qa_accept", mode=SINGLE, rejects_to="next_module",
         note="run for real; a module's own tests are not this"),
    Node("qa_accept", DECISION, "acceptance", role="qa", gate="acceptance", gate_when="after",
         answer_decides=True, mode=MODEL_PANEL, rejects_to="acceptance_failed",
         branches={"pass": "pr", "fail": "acceptance_failed"}),
    Node("acceptance_failed", STEP, "back into the module loop", next="change_retry", mode=RUNNER),

    Node("change_retry", DECISION, "has the whole change been rejected before", mode=RUNNER,
         branches={"first": "next_module", "again": "halt_change_rejected"},
         note="the bound the whole-change loop did not have (CHG-20260828-22). `lead_review` and "
              "`qa_accept` both sent a rejected change back to `next_module` and nothing counted "
              "the trips, so a run that kept failing died on `walk exceeded 200 steps` — which "
              "tells an operator the runner gave up rather than that their change was rejected "
              "twice. "
              "ONE BUDGET FOR BOTH, because they are one fact: the assembled change was rejected. "
              "A bound per loop would let a change rejected once by the panel and once at "
              "acceptance spend neither, which is the run that most needs a person. "
              "Nobody is asked — it counts what is already in the run's record, the way "
              "`module_built` reads what the engineer said it built"),
    Node("halt_change_rejected", TERMINAL, "the whole change was rejected twice", mode=RUNNER,
         permanent=True,
         note="the same argument `halt_second_fail` makes one loop in: two rejections of the "
              "finished change is not something another lap fixes"),
    Node("pr", STEP, "open the pull request", role="lead", gate="pr", gate_when="before",
         next="merge", mode=SINGLE),
    Node("merge", STEP, "merge", role="lead", gate="merge", gate_when="before",
         next="close_out", mode=SINGLE,
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


def module_cycle(start: str = "engineer_build", end: str = "next_module") -> List[str]:
    """The asking nodes one module passes through, from `start` up to but not including `end`.

    Derived by walking the edges rather than listed, for the reason this file exists: a list of
    node ids is a **name list**, and a node added to the loop later would silently fall outside it.
    What callers actually want is the property — "this node is part of building one module" — and
    only a traversal answers that as the graph changes.

    `next_module` bounds it because that is where the loop turns over — a module stops being the one
    in hand at the moment the flow goes back to ask for another.

    It used to bound on `record_module`, which was the same boundary while every path out of the
    loop went through it. CHG-20260828-15 added `module_built --no--> next_module`, and the
    traversal escaped: it swept in `merge`, `pr` and `lead_review`, which would have put the whole
    change's review inside one module's worktree. The derivation is what made that visible — a
    hand-written list of five ids would have gone on looking correct.
    """
    seen, out, frontier = {start}, [], [start]
    while frontier:
        current = BY_ID[frontier.pop()]
        if current.role:
            out.append(current.id)
        for target in list(current.branches.values()) + ([current.next] if current.next else []):
            if target not in seen and target != end:
                seen.add(target)
                frontier.append(target)
    return sorted(out)


def dispatch_edges() -> Dict[str, List[str]]:
    """`{dispatching role: [roles it dispatches]}`, read off the pool nodes.

    A pool node is the only place one role opens work for another: `main` dispatches `role`. Derived
    rather than listed, so a fourth tier added to `NODES` shows up here without anyone remembering
    to update a second list — which is the failure this function exists to make impossible.
    """
    edges: Dict[str, List[str]] = {}
    for n in NODES:
        if n.mode == POOL and n.main and n.role:
            edges.setdefault(n.main, [])
            if n.role not in edges[n.main]:
                edges[n.main].append(n.role)
    return edges


def roles_asked_directly() -> List[str]:
    """Roles the runner asks itself, which are the roots of the dispatch tree at depth 1."""
    return sorted({n.role for n in NODES if n.role and n.mode != POOL})


def asking_nodes() -> List[str]:
    """The nodes that ask a model — the ones the one-session rule binds."""
    return [n.id for n in NODES if n.role]


def _reaches(start: str, target: str) -> bool:
    """Can the walk get from `start` to `target` along ordinary edges?

    Ordinary means branches and `next`. `rejects_to` is deliberately not one: a refusal is what a
    person does instead of letting the run continue, so counting it here would let two refusals
    justify each other.
    """
    seen: set = set()
    frontier = [start]
    while frontier:
        current = BY_ID[frontier.pop()]
        for edge in list(current.branches.values()) + ([current.next] if current.next else []):
            if edge == target:
                return True
            if edge not in seen:
                seen.add(edge)
                frontier.append(edge)
    return False


def validate() -> None:
    """Internal consistency, and agreement with the policy.

    Every edge lands somewhere, every node is reachable, and every gate and role a node names exists
    in `policy.py`. A node naming a gate nothing defines is the failure that would otherwise show up
    as a run halting on something nobody wrote down.
    """
    from . import policy

    if len(BY_ID) != len(NODES):
        raise GraphError("duplicate node id")
    # The line above is a **length** check, and equal lengths is not the same graph. Both names are
    # module attributes a caller may rebind — `policy.py` says the checks run "including one whose
    # graph a caller has altered in memory", so that is a supported surface rather than a test
    # artefact — and rebinding one of the two is enough. Measured: with `NODES` alone rebound so
    # that `merge` routes back to `intake`, `validate` **passes**, because the per-node rules read
    # the new `NODES` while the reachability walk reads the old `BY_ID`. `engine.walk` fetches the
    # node it executes from `BY_ID`. So the run that follows was certified against a graph it is
    # not the one running.
    #
    # A separate `if` rather than a longer condition on the line above: the two are different
    # faults and a reader sent to "duplicate node id" for a stale index goes looking for the wrong
    # repair. Refusing rather than repairing — rebuilding `BY_ID` here would leave `validate`
    # writing shared state on every call, and would certify the index it had just replaced.
    for node in NODES:
        if BY_ID.get(node.id) is not node:
            raise GraphError(
                f"node {node.id!r} in NODES is not the node BY_ID holds for that id — the two "
                f"views of the graph were rebound separately, and a run executes the second")
    ids = set(BY_ID)
    for node in NODES:
        targets = list(node.branches.values()) + ([node.next] if node.next else [])
        for target in targets:
            if target not in ids:
                raise GraphError(f"node {node.id!r} points at unknown node {target!r}")
        # First, so that the diagnostic a reader gets is about the mistake they made.
        #
        # I first wrote here that a typo'd kind is always still caught, by some other rule naming
        # some other node — a `step` with no successor coming back as a rejection-routing failure
        # at `engineer_selfverify`, a `decision` with one branch as a model-panel failure. A review
        # seat refuted it: **I had measured the four nodes that happen to have a neighbour to trip
        # over.** For all four kinds there is a shipped node where the kind's own rule is violated,
        # the kind is misspelled, and `validate` accepts it outright — `record_module` (a step with
        # no successor), `done` (a terminal with an edge), `plan_scope` and `module_built` (one
        # branch each).
        #
        # So both halves are true and neither is a defence: where a neighbouring rule fires it
        # sends the reader to the wrong node, and on four shipped nodes nothing fires at all.
        if node.kind not in KINDS:
            raise GraphError(
                f"node {node.id!r} has unknown kind {node.kind!r}, which is not one of {KINDS}")
        # `validate`'s reachability walk takes the union of `branches` and `next`; the engine takes
        # one **or** the other, `branches` first. So a node carrying both is a node where the two
        # disagree about what the graph is. Measured on the shipped flow: moving `reconcile`'s
        # `unresolved` branch onto its `next` leaves `halt_unreconciled` reachable according to
        # `validate` and reachable by no run at all — 30 of 31 nodes, and the guard said 31.
        #
        # The other direction is not silent but is still a build-time fact failing at run time: a
        # `STEP` given branches dies with `branches on [...] but the run supplied no choice for it`
        # partway through a run rather than being refused before one starts.
        if node.branches and node.next:
            raise GraphError(
                f"node {node.id!r} declares branches {sorted(node.branches)} and a successor "
                f"{node.next!r}. A run takes one or the other, so the other is an edge this "
                f"validator counts and no run can ever take")
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
        if node.gate_when is not None and node.gate_when not in ("before", "after"):
            raise GraphError(f"node {node.id!r} has an unknown gate phase {node.gate_when!r}")
        # **Both directions, which is what the old message claimed and the old condition did not.**
        # It refused an ungated node declaring `after` and accepted one declaring `before` — and
        # since `before` was the default, the sentence "has a gate phase but no gate" was true of
        # the twenty-one ungated nodes it let through. Round fourteen's conformance seat held a
        # veto on that, and the honest repair was the type rather than the wording: with no
        # default, "no phase" is a state the graph can be in, so the whole contract is sayable.
        #
        # The gain is not tidiness. Seven of the ten gated nodes are `after`, so the default was
        # the minority case: the next gated node whose author forgets the phase used to get the
        # behaviour the field's own comment calls a defect an independent verifier found. It gets
        # a build error instead.
        if (node.gate is None) != (node.gate_when is None):
            raise GraphError(
                f"node {node.id!r} names gate {node.gate!r} and phase {node.gate_when!r} — a "
                f"phase says when a gate is consulted, so neither means anything without the "
                f"other")
        if node.answer_decides and not node.role:
            raise GraphError(
                f"node {node.id!r} says its answer decides, but nobody is asked at it")
        # A panel node's branches must be reachable **by a panel**. `pm_confirm` and `pm_signoff`
        # offered `yes`/`no` while the only thing routing them was `pass`/`fail`, so both were dead
        # on any multi-model configuration and nothing said so — not `validate`, which never looked,
        # and not the panel tests, which only ever configured the `pass`/`fail` nodes. A node that
        # cannot be routed is worse than a node that routes wrongly: it takes the whole run with it,
        # and it does so at whichever node the operator happened to configure (CHG-20260901-11).
        if node.mode == MODEL_PANEL and node.branches:
            for outcome in (policy.PASS, policy.FAIL):
                landed = node.panel_branches.get(outcome, outcome)
                if landed not in node.branches:
                    raise GraphError(
                        f"node {node.id!r} is routed by a panel, whose {outcome!r} names no branch "
                        f"of its {sorted(node.branches)}. Declare `panel_branches` on it, or name "
                        f"its branches in the panel's own words")
        # The same question for the **other** panel mode, where the answer is stricter. The rule
        # above was written for `MODEL_PANEL` and guarded on it, and a seat panel was left with no
        # rule at all: measured by renaming `lead_review`'s branches to `approve`/`reject`, which
        # `validate` accepted and which would have died at `engine`'s branch lookup with the same
        # `has no branch 'pass'` CHG-20260901-11 was opened for.
        #
        # Stricter because **`panel_branches` is not an option here.** A model panel's outcome is
        # mapped through it (`engine`'s `node.panel_branches.get(outcome, outcome)`); a seat panel's
        # comes back from `_adjudicate`, which does not consult that mapping — though `engine`
        # reads it once more after the branch is taken, to name the word meaning ratified. So
        # the escape the message above offers — *declare `panel_branches` on it* — is not one, and
        # this message must not offer it.
        if node.mode == SEAT_PANEL and node.branches:
            for outcome in (policy.PASS, policy.FAIL):
                if outcome not in node.branches:
                    raise GraphError(
                        f"node {node.id!r} is routed by the review seats, whose {outcome!r} names "
                        f"no branch of its {sorted(node.branches)}. A seat panel must name its "
                        f"branches in the panel's own words: `panel_branches` routes a model "
                        f"panel's outcome and is never what routes this one")
        if node.mode == SEAT_PANEL and node.panel_branches:
            # On a **seat panel** the mapping can never help and can harm, which is why the
            # refusal is here and not on every mode that fails to route through it.
            #
            # `engine` reads this table twice. It routes a model panel's outcome through it, and
            # then — after the branch is taken, for every branching node — reads it again to name
            # the word that means *ratified*. The rule above requires a seat panel's branches to
            # **contain** `pass`, so that second read already resolves to a branch it offers.
            #
            # So a declaration here can never improve anything, and some of them break the
            # settling. The condition is exact and is not a count: **`ratified` moves iff the
            # mapping carries a `pass` key pointing somewhere other than `pass`.** Only that key is
            # read; every other declaration leaves `ratified` at `pass` and says nothing the
            # default did not.
            #
            # `ratified` **is** the settling condition — `engine` tests `choice == ratified`
            # against `_adjudicate`'s own word — so whichever word `pass` is pointed at becomes the
            # one that settles. Two outcomes follow, and this sentence has been written wrongly as
            # each of them alone:
            #
            #   `{pass: fail}`      `ratified` is `fail`, which the panel does return, so the
            #                       settling **swaps sides**: a rejection settles the grade and a
            #                       pass no longer does, recording the run as graded at what a
            #                       panel that refused it agreed.
            #   `{pass: <other>}`   `ratified` is a branch word no adjudication returns, so
            #                       **nothing settles** — the milder failure, and the one three
            #                       earlier versions named as though it were the only one.
            #
            # **No declaration helps**, and one that cannot help is a name standing in for a
            # constraint. Four earlier versions of this comment were counts and each was refused:
            # *can only misname*; *two of four*, counting `{}`, which a rule guarded on a non-empty
            # mapping never sees; *three of four*, enumerating only single-key mappings when both
            # shipped declarations are two-key; and *five of eight*, which counted the mappings
            # whose keys **and** values are drawn from `{pass, fail}` and called that the space
            # this rule sees. It is not. On a seat panel this `raise` fires before the loop below
            # ever runs, and that loop constrains the mapped *values* and refuses only an
            # `undecided` key — so `{"weird": "pass"}` is accepted, and so is `{"pass": "escalate"}`
            # on a seat panel carrying a third branch, since the rule above requires `pass` and
            # `fail` to be **among** the branches and not to be all of them.
            # A count of this set invites a fifth wrong number; the condition does not.
            #
            # **This rule was briefly widened to every mode but `MODEL_PANEL` and that was wrong.**
            # Elsewhere the branches are arbitrary and the second read is the *only* way to name
            # the ratified word: `pm_signoff` offers `yes`/`no` and settles precisely because it
            # declares `{pass: "yes"}` — without it, `ratified` is `pass`, which it does not offer,
            # and it could never settle. Refusing the declaration there would make a `settles_risk`
            # node with its own vocabulary inexpressible, and `engine` says that settling is "keyed
            # on the answer, never on the mode". A seat measured a `runner` node declaring the
            # mapping and passing, which is correct, not a gap.
            raise GraphError(
                f"node {node.id!r} is routed by the review seats and declares `panel_branches`, "
                f"which nothing routes through there and which cannot name the word meaning "
                f"ratified any better than the default already does — and which, if it maps `pass` "
                f"elsewhere, makes that word the one a node settles the grade on: a rejection if "
                f"it maps to `fail`, and nothing at all if it maps to a branch no panel returns. "
                f"Remove the declaration: a seat panel's branch comes back from `_adjudicate` "
                f"already in the panel's words, and needs no mapping")
        for outcome, landed in node.panel_branches.items():
            if landed not in node.branches:
                raise GraphError(
                    f"node {node.id!r} routes a panel's {outcome!r} to {landed!r}, which is not "
                    f"one of its branches {sorted(node.branches)}")
            if outcome == policy.UNDECIDED:
                # `undecided` is the absence of a verdict, and it already has somewhere to go: the
                # ruling path, where a person chooses and the run records the choice as *theirs*.
                # Mapping it to a branch would let a split panel look like a decision it never
                # reached, which is the distinction `undecided` exists to draw.
                raise GraphError(
                    f"node {node.id!r} maps {policy.UNDECIDED!r} to a branch. A split panel decided "
                    f"nothing; that goes to a person, not to an edge")

        # --- execution mode ------------------------------------------------------------------
        #
        # These rules **check** that two independently declared facts agree. They do not *derive*
        # one from the other, and the difference is the whole point: deriving the mode from the
        # role would mean a node's role silently decides how its models are read, which is a name
        # standing in for a constraint. Checking means both are written down and a disagreement is
        # a build error rather than a surprise at run time.
        #
        # No default, so "nobody wrote one down" is a state the graph can be in, and this is
        # where it stops. Its own rule, ahead of the closed-set one below, because "unknown
        # mode None" sends a reader after a typo when what happened is an omission — the same
        # repair CHG-20260907-11 made for `gate_when`, whose default was a minority value in
        # exactly this way (CHG-20260907-26).
        if node.mode is None:
            raise GraphError(
                f"node {node.id!r} declares no mode. How its models are read is declared and "
                f"never inferred, so a node that says nothing is a build error rather than a "
                f"{SINGLE!r}. It must name one of {MODES}")
        if node.mode not in MODES:
            raise GraphError(f"node {node.id!r} has unknown mode {node.mode!r}")
        if (node.role is None) != (node.mode == RUNNER):
            raise GraphError(
                f"node {node.id!r} is mode {node.mode!r} with role {node.role!r} — a node with no "
                f"role asks nobody and must be {RUNNER!r}, and only such a node may be")
        if (node.role == "seat") != (node.mode in (SEAT_PANEL, SURVEY)):
            raise GraphError(
                f"node {node.id!r} is mode {node.mode!r} with role {node.role!r} — only the review "
                f"seats are a {SEAT_PANEL!r} or a {SURVEY!r}, and they are always one of the two")
        if node.mode == MODEL_PANEL and node.kind != DECISION and not node.grades_risk:
            raise GraphError(
                f"node {node.id!r} is a {MODEL_PANEL!r} but a {node.kind!r} that grades nothing — "
                f"several models on one question are voices to adjudicate, and a node that reaches "
                f"no verdict has nothing to adjudicate. A panel must reach something: a "
                f"{DECISION!r} reaches a branch, and a node with `grades_risk` reaches a grade "
                f"(CHG-20260827-17). Work-producing nodes with several models are still refused — "
                f"that is what {POOL!r} is for, one model doing the work rather than several "
                f"voting on it.")
        if node.settles_risk and not any(n.grades_risk for n in NODES):
            raise GraphError(
                f"node {node.id!r} settles a risk grade and no node grades one. Ratifying a "
                f"proposal nothing makes would settle whatever the plan happened to say, which is "
                f"the single unadjudicated voice CHG-20260827-17 removed.")
        if node.grades_risk and node.mode != MODEL_PANEL:
            raise GraphError(
                f"node {node.id!r} grades risk but is mode {node.mode!r}. The grade indexes every "
                f"later gate, and one voice setting it alone is the circularity CHG-20260827-17 "
                f"exists to remove — so a grading node is a panel or it is nothing.")
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
            # **This one first.** A node following itself is a chain of follows, so the rule
            # below used to fire on it and the rule written for it never ran at all — and the
            # message a reader got said the node "follows something else", pointing at itself.
            # `test_a_node_cannot_follow_itself` matched `follows itself|follows something else`,
            # so it passed on the wrong rule's wrong sentence and its name was the only thing
            # claiming otherwise (CHG-20260907-07).
            if node.follows == node.id:
                raise GraphError(f"node {node.id!r} follows itself")
            if BY_ID[node.follows].mode == FOLLOWS:
                raise GraphError(
                    f"node {node.id!r} follows {node.follows!r}, which follows something else — a "
                    f"chain of follows has no model at the end of it")
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
            # **Necessary, and nowhere near sufficient — which is the point of the comment.**
            #
            # A refusal that lands where the walk can never come back from is a refusal that ends
            # the run, and `rejects_to` is not how a run ends. In this graph that means a terminal:
            # `qa_accept` rejecting to `done` or to `halt_change_rejected` is refused here.
            #
            # It refuses nothing else, and four candidate rules were measured before settling for
            # that (CHG-20260907-08):
            #
            #   the target reaches this node again          every shipped edge passes, and so does
            #                                               `qa_accept -> pr`: the flow is one
            #                                               cycle, so reachability says nothing
            #   this node is on every path to `merge`       refuses `lead_task_review -> fix_pass`,
            #                                               which ships — a fix pass is answered by
            #                                               `re_review`, a different review
            #   the target is not downstream                same cycle, same vacuity
            #   answerable without passing `merge`          accepts `qa_accept -> qa_verify`, which
            #                                               skips the `lead_review` gate entirely
            #
            # The last is the one that settles it: the normal return from an acceptance refusal
            # passes `lead_review` and `qa_verify`; the bypass passes only `qa_verify`. Which gates
            # a refusal must pass is **policy**, and connectivity cannot express it. What protects
            # it is `test_where_each_refusal_goes_is_pinned`, which names all eight edges.
            if not _reaches(node.rejects_to, node.id):
                raise GraphError(
                    f"node {node.id!r} rejects to {node.rejects_to!r}, which cannot reach it "
                    f"again — a refusal the run can never answer is not a refusal, it is a stop")

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
    for n in NODES:
        if n.permanent and n.kind != TERMINAL:
            raise GraphError(
                f"node {n.id!r} is marked permanent but is a {n.kind!r}. Only a terminal node ends "
                f"a run, so only a terminal node can end it badly.")

