"""`graph.validate()` is the only guard over the flow, and almost none of it could fail.

Round fourteen's defect seat removed each of seven rules in turn and ran the test files most likely
to notice. All seven stayed green:

    rejection-routing rules removed          test_sendback_retry_reject + test_execution_mode -> 43 passed
    panel-routability (CHG-20260901-11)      test_panel_and_pool + test_execution_mode + ...  -> 74 passed
    answer_decides-needs-role removed        test_flow + test_execution_mode                  -> 136 passed
    permanent-only-on-terminal removed       test_change_bound + test_execution_mode          -> 40 passed
    after-phase-needs-gate removed           test_flow + test_execution_mode                  -> 136 passed
    terminal-has-no-edges removed            test_flow + test_execution_mode                  -> 136 passed
    unreachable-node removed                 test_flow + test_execution_mode                  -> 136 passed

A complete inventory then found **32 rules** in the function and nineteen of them with no reverse
test at all — including the one `CHG-20260901-11` added to close a defect. The guard a repair
installs is itself a place the next defect can hide.

These are graph invariants rather than execution-mode rules, which is why they are here and not in
`test_execution_mode.py`: that file's scope is deliberately narrow and its name says so.

Each test below states the rule and then breaks it. A rule that cannot be broken does not get a
test here — `test_execution_mode` has one of those, and finding it was worth more than pinning it
would have been.
"""
import dataclasses

import pytest

from ai_sdlc_runner import graph, policy
from _graph_swap import validate_with


def _mutate(node_id, **changes):
    """The real graph with one node changed — the shape a wrong hand-edit would actually take."""
    return tuple(dataclasses.replace(n, **changes) if n.id == node_id else n for n in graph.NODES)


def _first(**predicate):
    """The first shipped node matching, so a test breaks a real node rather than an invented one."""
    for node in graph.NODES:
        if all(getattr(node, field) == value for field, value in predicate.items()):
            return node
    raise AssertionError(f"no shipped node matches {predicate}")


# ── the shape of the graph itself ────────────────────────────────────────────────────────────

def test_two_nodes_may_not_share_an_id():
    """`BY_ID` is a dict, so a duplicate id silently loses a node rather than colliding."""
    with pytest.raises(graph.GraphError, match="twice|duplicate|same id"):
        validate_with(_mutate("pm_plan", id="intake"))


def test_an_edge_may_not_name_a_node_that_does_not_exist():
    with pytest.raises(graph.GraphError, match="no node|unknown"):
        validate_with(_mutate("intake", next="nowhere_at_all"))


def test_a_terminal_may_not_have_an_outgoing_edge():
    """A terminal with an edge is not a terminal; the walk would leave through it."""
    terminal = _first(kind=graph.TERMINAL)
    with pytest.raises(graph.GraphError, match="terminal"):
        validate_with(_mutate(terminal.id, next="intake"))


def test_a_decision_may_not_offer_fewer_than_two_branches():
    """One branch is not a decision — it is a step with a question mark, which is the shape
    `read_options` refuses one module over for the same reason."""
    decision = _first(kind=graph.DECISION)
    one = {next(iter(decision.branches)): decision.branches[next(iter(decision.branches))]}
    # Not `match="branch"`: with this rule removed the panel-routability rule fires instead,
    # and its message — "whose 'fail' names no branch of its [...]" — contains the word too.
    with pytest.raises(graph.GraphError, match="needs at least two branches"):
        validate_with(_mutate(decision.id, branches=one))


def test_a_step_may_not_have_no_successor():
    step = _first(kind=graph.STEP)
    # Not `match="next|successor"`: with this rule removed, reachability fires and lists the
    # nodes it could not reach — one of which is `next_module`, so the pattern matched a node id
    # inside another rule's message.
    with pytest.raises(graph.GraphError, match="has no successor"):
        validate_with(_mutate(step.id, next=None))


def test_every_node_is_reachable_from_intake():
    """An unreachable node is a mechanism nobody can get to, and the walk would never say so."""
    orphan = dataclasses.replace(_first(kind=graph.TERMINAL), id="orphan")
    with pytest.raises(graph.GraphError, match="unreachable|reach"):
        validate_with(graph.NODES + (orphan,))


# ── what a node may claim about gates ────────────────────────────────────────────────────────

def test_a_node_may_not_name_a_gate_policy_does_not_have():
    gated = _first(gate="merge")
    with pytest.raises(graph.GraphError, match="names gate .*policy.py does not define"):
        validate_with(_mutate(gated.id, gate="no_such_gate"))


def test_a_node_may_not_name_a_role_policy_does_not_have():
    roled = next(n for n in graph.NODES if n.role and n.role in policy.BY_ROLE)
    with pytest.raises(graph.GraphError, match="names role .*policy.py does not define"):
        validate_with(_mutate(roled.id, role="no_such_role"))


def test_a_gate_phase_outside_the_two_words_is_refused():
    gated = _first(gate="merge")
    with pytest.raises(graph.GraphError, match="before|after|phase"):
        validate_with(_mutate(gated.id, gate_when="whenever"))


def test_a_phase_without_a_gate_is_refused():
    """Half of a contract that used to be stated whole and enforced half.

    The old message said *"has a gate phase but no gate"* while the condition refused only the
    `after` half — and since `before` was the **default**, that sentence was true of the
    twenty-one ungated nodes it accepted. Round fourteen's conformance seat vetoed it, and the
    repair was the type: with `gate_when` optional there is a "no phase" state, so both halves are
    sayable (CHG-20260907-11).
    """
    ungated = next(n for n in graph.NODES if not n.gate)
    for phase in ("after", "before"):
        with pytest.raises(graph.GraphError, match="neither means anything without the other"):
            validate_with(_mutate(ungated.id, gate_when=phase))


def test_a_gate_without_a_phase_is_refused():
    """The half that could not be said before, and the one that matters.

    Seven of the ten gated nodes are `after`, so the old default was the **minority** value: a
    gated node whose author forgot the phase silently got `before` — a gate consulted in front of
    the work it grades, which the field's own comment calls a defect an independent verifier
    found. Omission is a build error now.
    """
    gated = _first(gate="merge")
    with pytest.raises(graph.GraphError, match="neither means anything without the other"):
        validate_with(_mutate(gated.id, gate_when=None))


def test_which_gate_is_consulted_when_is_pinned():
    """A validator cannot choose between two valid values; only this can.

    Measured before it existed: `pm_signoff` moved to `before` and `engineer_selfverify` moved to
    `after` keeps `test_documented_numbers`' count at ten and three, and the **whole suite** stays
    green — 2292 passed, nothing failed. Three of the ten phases were held by a count and by
    nothing else.

    Written as one equality rather than ten assertions so that a *new* gated node fails it too and
    has to be entered here deliberately. `design.md` states the rule this table follows: before,
    where the work is the risk; after, where the point is to hold the result.
    """
    assert {n.id: n.gate_when for n in graph.NODES if n.gate} == {
        # after — the point is to hold the result and stop with it in hand
        "pm_confirm": "after",
        "lead_assess": "after",
        "pm_signoff": "after",
        "lead_task_review": "after",
        "lead_review": "after",
        "qa_verify": "after",
        "qa_accept": "after",
        # before — the work itself is the risk
        "engineer_selfverify": "before",
        "pr": "before",
        "merge": "before",
    }


def test_only_a_terminal_may_be_permanent():
    step = _first(kind=graph.STEP)
    with pytest.raises(graph.GraphError, match="permanent"):
        validate_with(_mutate(step.id, permanent=True))


# ── what a node may claim about answers ──────────────────────────────────────────────────────

def test_an_answer_may_not_decide_where_nobody_is_asked():
    """`answer_decides` on a node with no role is a field about an answer nobody gives."""
    roleless = next(n for n in graph.NODES if not n.role and not n.answer_decides)
    with pytest.raises(graph.GraphError, match="answer|role"):
        validate_with(_mutate(roleless.id, answer_decides=True))


# ── where a refusal goes ─────────────────────────────────────────────────────────────────────

def test_a_rejection_needs_a_gate_to_be_refused_at():
    """`rejects_to` says where a refusal goes; a node with no gate has nothing to refuse."""
    ungated = next(n for n in graph.NODES if not n.gate and not n.rejects_to)
    # `match="gate|reject"` matched nearly every message this function can raise.
    with pytest.raises(graph.GraphError, match="has no gate to reject"):
        validate_with(_mutate(ungated.id, rejects_to="intake"))


def test_a_rejection_may_not_land_where_the_run_can_never_come_back_from():
    """The weak half of the rule, and the record says plainly that it is the weak half.

    A refusal is not how a run ends, so a target the walk can never return from is refused. In
    this graph that means a terminal.
    """
    with pytest.raises(graph.GraphError, match="cannot reach it again"):
        validate_with(_mutate("qa_accept", rejects_to="done"))


def test_the_whole_change_bound_reads_the_graph_rather_than_a_written_list():
    """`_WHOLE_CHANGE_REJECTED` was the tuple `("review_failed", "acceptance_failed")` — exactly
    the nodes whose `.next` is `change_retry`, written out by hand beside the graph that says so.

    A written copy cannot be told from a derivation while the two agree, which is why this test
    adds a **third** such node and asks whether the bound sees it. Under the hand-written pair it
    does not.

    It is a function rather than a module constant for the reason `engine._MODULE_CYCLE` was a
    finding of this same round: that one snapshotted `graph.module_cycle()` at import while
    `plan.py` asked per call, and the two disagreed about a node added later. Deriving at import
    would have reproduced the shape this change removes. That snapshot is gone too
    (CHG-20260907-10) — this note keeps the reason, not the example.
    """
    import dataclasses

    from ai_sdlc_runner import engine

    assert set(engine._whole_change_rejected()) == {"review_failed", "acceptance_failed"}, (
        "the shipped graph's answer, unchanged by deriving it")

    extra = dataclasses.replace(graph.BY_ID["fix_pass"], id="another_failure",
                                next="change_retry", branches={})
    original = graph.NODES
    try:
        graph.NODES = graph.NODES + (extra,)
        assert "another_failure" in engine._whole_change_rejected(), (
            "a node routing into `change_retry` is a whole-change rejection, and the bound is "
            "reading a list that cannot know about it")
    finally:
        graph.NODES = original


def test_where_each_refusal_goes_is_pinned():
    """**This is what actually protects it**, and four structural rules were measured first.

    `validate` cannot express which gates a refusal must pass, because that is policy rather than
    connectivity. Measured against every candidate (CHG-20260907-08):

        the target reaches this node again    every shipped edge passes -- and so does
                                              `qa_accept -> pr`, because the flow is one cycle
        this node is on every path to merge   refuses `lead_task_review -> fix_pass`, which ships
        the target is not downstream          the same cycle, the same vacuity
        answerable without passing merge      accepts `qa_accept -> qa_verify`, which reaches
                                              `qa_accept` again while skipping `lead_review`

    The last is decisive: the normal return from an acceptance refusal passes `lead_review` and
    `qa_verify`; that bypass passes only `qa_verify`. So the eight edges are written down here.
    Changing one is not forbidden — it is a decision, and this test is where it has to be made.
    """
    assert {n.id: n.rejects_to for n in graph.NODES if n.rejects_to} == {
        "pm_confirm": "pm_plan",
        "lead_assess": "pm_plan",
        "pm_signoff": "pm_plan",
        "engineer_selfverify": "engineer_build",
        "lead_task_review": "fix_pass",
        "lead_review": "review_failed",
        # Deliberately outside the whole-change bound (CHG-20260828-22): a QA refusal goes round
        # the module loop rather than to `change_retry`.
        "qa_verify": "next_module",
        # Inside it. `acceptance_failed.next` is `change_retry`, which is what makes the second
        # refusal at this gate the last one.
        "qa_accept": "acceptance_failed",
    }


def test_a_rejection_may_not_name_a_node_that_does_not_exist():
    rejecting = next(n for n in graph.NODES if n.rejects_to)
    with pytest.raises(graph.GraphError, match="reject|no node|unknown"):
        validate_with(_mutate(rejecting.id, rejects_to="nowhere_at_all"))


def test_a_rejection_may_not_return_to_the_node_that_was_refused():
    """A refusal that lands where it was made is a loop with a person in it."""
    rejecting = next(n for n in graph.NODES if n.rejects_to)
    with pytest.raises(graph.GraphError, match="itself|same"):
        validate_with(_mutate(rejecting.id, rejects_to=rejecting.id))


# ── a node's kind, and what it promises about its edges ──────────────────────────────────────────


def test_an_unknown_kind_is_refused():
    """`MODES` has always been closed; `kind` was not, and 23 of 31 nodes accepted nonsense in it.

    The phrase is matched narrowly on purpose. Several other rules fire on a typo'd kind as
    collateral, naming a different node, and a loose `match=` here would go green on one of those
    — which is exactly how five reverse tests in this file were found hollow (CHG-20260907-07).
    """
    with pytest.raises(graph.GraphError, match="unknown kind"):
        validate_with(_mutate("engineer_build", kind="stpe"))


@pytest.mark.parametrize("node_id,changes", [
    # A step with no successor.
    ("record_module", dict(next=None)),
    # A terminal with an outgoing edge.
    ("done", dict(next="intake")),
    # A loop, and a decision, with one branch each.
    ("plan_scope", None),
    ("module_built", None),
])
def test_a_kinds_own_rule_does_not_cover_that_kind_misspelled(node_id, changes):
    """The four nodes that make the closed set necessary rather than tidy.

    My first measurement said a misspelled kind is always still caught, by some other rule naming
    some other node — bad, but bounded. A review seat refuted it: I had picked the four nodes that
    happen to have a neighbour to trip over. On these four the kind's own rule is violated, the
    kind is misspelled, and before this rule existed `validate` **accepted it outright**.

    Parametrised rather than written as one test with four cases, so that a repair covering three
    of them cannot pass.
    """
    node = graph.BY_ID[node_id]
    if changes is None:
        changes = dict(branches={list(node.branches)[0]: list(node.branches.values())[0]})
    with pytest.raises(graph.GraphError, match="unknown kind"):
        validate_with(_mutate(node_id, kind=node.kind + "_", **changes))


def test_the_one_terminal_a_typo_used_to_survive_on():
    """`done` is the only node where a nonsense kind both validated and reached the engine.

    The other three terminals are `permanent`, and the permanent-only-on-terminal rule refuses
    them. `done` is not, so it validated, and `engine.walk`'s `node.kind == TERMINAL` test read it
    as an ordinary node: the run still reported `finished` and `halted_at` came back `None`.
    """
    assert graph.BY_ID["done"].kind == graph.TERMINAL
    assert not graph.BY_ID["done"].permanent
    with pytest.raises(graph.GraphError, match="unknown kind"):
        validate_with(_mutate("done", kind="termnial"))


def test_a_node_may_not_declare_both_branches_and_a_successor():
    """The two edge shapes are exclusive, because a run only ever takes one of them.

    `validate`'s reachability walk unions `branches` and `next`; `engine.walk` takes `branches` if
    there are any and `next` otherwise. A node carrying both makes the guard and the run disagree
    about what the graph is.
    """
    step = _first(id="record_module")
    assert step.next and not step.branches
    with pytest.raises(graph.GraphError, match="no run can ever take"):
        validate_with(_mutate(step.id, branches={"again": "next_module", "stop": "done"}))


def test_the_reachability_walk_measures_the_graph_that_actually_runs():
    """The case the rule above exists for, stated as the harm rather than as the shape.

    Moving `reconcile`'s `unresolved` branch onto its `next` leaves every node reachable according
    to the union `validate` walks, while a run — which takes the branches and never looks at
    `next` — can reach 30 of the 31. The unreachable one is `halt_unreconciled`, a halt.
    """
    reconcile = graph.BY_ID["reconcile"]
    kept = {k: v for k, v in reconcile.branches.items() if v != "halt_unreconciled"}
    assert len(kept) == len(reconcile.branches) - 1, "the shipped branch this test moves is gone"
    with pytest.raises(graph.GraphError, match="no run can ever take"):
        validate_with(_mutate("reconcile", branches=kept, next="halt_unreconciled"))


def test_which_nodes_are_loops_is_pinned():
    """A closed set refuses nonsense. It does not refuse the wrong member of the set.

    `LOOP` appears in exactly one condition in `graph.py`, shared with `DECISION`, and nothing else
    in the repository reads it. Measured: both loops relabelled `DECISION` validates, and 5 of the
    10 decisions accept being relabelled `LOOP` — the 5 that do not are caught by the model-panel
    rule, which is not about loops. No structural rule separates them either: 25 of the 31 nodes
    are on a cycle, the same fact that defeated two of CHG-20260907-08's four candidate rules.

    So which kind a node is, is a declaration, and this is where changing one is a decision.
    """
    assert [n.id for n in graph.NODES if n.kind == graph.LOOP] == ["plan_scope", "next_module"]
    assert sorted(n.id for n in graph.NODES if n.kind == graph.TERMINAL) == [
        "done", "halt_change_rejected", "halt_second_fail", "halt_unreconciled"]
    # The membership too, not only that the shipped kinds are drawn from it: a set that
    # quietly gains a member is a set that is closed and does not refuse anything.
    assert graph.KINDS == (graph.STEP, graph.DECISION, graph.LOOP, graph.TERMINAL)
    assert set(n.kind for n in graph.NODES) == set(graph.KINDS)


# ── one graph, two views ─────────────────────────────────────────────────────────────────────────


def _validate_with_nodes_only(nodes):
    """Rebind `NODES` and leave `BY_ID` alone — the half-swap, on purpose.

    `_validate_with` above swaps both because that is how a test should ask the question. This one
    exists to be wrong, so that the rule refusing it has something to refuse.
    """
    original = graph.NODES
    graph.NODES = nodes
    try:
        graph.validate()
    finally:
        graph.NODES = original


def test_the_two_views_of_the_graph_must_be_the_same_graph():
    """`len(BY_ID) != len(NODES)` is a length check, and equal lengths is not the same graph.

    Both names are module attributes a caller may rebind, and `policy.py` says the checks run
    "including one whose graph a caller has altered in memory" — so this is a supported surface,
    not a test artefact. Rebinding one of the two is enough: the per-node rules then read the new
    `NODES` while reachability, `follows` and `_reaches` read the old `BY_ID`, and `engine.walk`
    executes the node it fetches from `BY_ID`.
    """
    with pytest.raises(graph.GraphError, match="rebound separately"):
        _validate_with_nodes_only(_mutate("merge", next="intake"))


def test_the_half_swap_used_to_certify_a_graph_that_does_not_run():
    """The measurement the rule above exists for, stated as the harm.

    With `merge -> intake` in `NODES` alone, `validate` passed: the shipped `merge` in `BY_ID` says
    the run finishes, the rebound one says it loops forever, and the walk follows `BY_ID`. Swapping
    both views instead refuses it, for a reason about the graph rather than about the rebinding —
    three nodes stop being reachable.
    """
    with pytest.raises(graph.GraphError, match="unreachable"):
        validate_with(_mutate("merge", next="intake"))


def test_the_shared_swap_puts_both_views_back_when_validate_raises():
    """One `finally` now serves 39 test functions, so it gets a test of its own.

    Until CHG-20260907-25 the swap was written three times and nothing asserted that any of them
    restored anything: measured with the `finally` body removed and one mutating test run alone,
    the result was `1 passed`. Run wider it fails 49 tests across the three files — every one of
    them a *later* test inheriting a graph the previous one left behind, which is collection
    order rather than a guarantee. `pytest-randomly` is not installed, so that order is stable,
    which makes the collateral reliable and no more meaningful.

    **By identity, not equality.** `graph.NODES == original` would also hold for a `finally` that
    rebuilt an equal tuple, and an equal tuple is the defect CHG-20260907-10 refuses: `validate`
    asks `BY_ID.get(node.id) is not node`, so a restored view holding equal-but-distinct nodes
    would fail the identity rule the next test to swap the graph relies on.
    """
    shipped_nodes, shipped_by_id = graph.NODES, graph.BY_ID
    with pytest.raises(graph.GraphError, match="unknown node"):
        validate_with(_mutate("intake", next="nowhere_at_all"))
    assert graph.NODES is shipped_nodes, "the shipped node tuple did not come back"
    assert graph.BY_ID is shipped_by_id, "the shipped index did not come back"
