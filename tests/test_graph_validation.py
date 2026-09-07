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


def _mutate(node_id, **changes):
    """The real graph with one node changed — the shape a wrong hand-edit would actually take."""
    return tuple(dataclasses.replace(n, **changes) if n.id == node_id else n for n in graph.NODES)


def _validate_with(nodes):
    """Swap in a graph, validate it, and put the real one back whatever happens.

    Both `NODES` and `BY_ID` are replaced. `test_risk_adjudicated._validate_one` swaps only the
    first, which is enough for the field-only changes it makes and wrong for anything about ids,
    reachability or follows: `validate` compares the two lengths and then traverses `BY_ID`, so a
    replacement can be half-validated against the new node and half against the shipped one.
    """
    original_nodes, original_by_id = graph.NODES, graph.BY_ID
    graph.NODES = nodes
    graph.BY_ID = {n.id: n for n in nodes}
    try:
        graph.validate()
    finally:
        graph.NODES, graph.BY_ID = original_nodes, original_by_id


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
        _validate_with(_mutate("pm_plan", id="intake"))


def test_an_edge_may_not_name_a_node_that_does_not_exist():
    with pytest.raises(graph.GraphError, match="no node|unknown"):
        _validate_with(_mutate("intake", next="nowhere_at_all"))


def test_a_terminal_may_not_have_an_outgoing_edge():
    """A terminal with an edge is not a terminal; the walk would leave through it."""
    terminal = _first(kind=graph.TERMINAL)
    with pytest.raises(graph.GraphError, match="terminal"):
        _validate_with(_mutate(terminal.id, next="intake"))


def test_a_decision_may_not_offer_fewer_than_two_branches():
    """One branch is not a decision — it is a step with a question mark, which is the shape
    `read_options` refuses one module over for the same reason."""
    decision = _first(kind=graph.DECISION)
    one = {next(iter(decision.branches)): decision.branches[next(iter(decision.branches))]}
    # Not `match="branch"`: with this rule removed the panel-routability rule fires instead,
    # and its message — "whose 'fail' names no branch of its [...]" — contains the word too.
    with pytest.raises(graph.GraphError, match="needs at least two branches"):
        _validate_with(_mutate(decision.id, branches=one))


def test_a_step_may_not_have_no_successor():
    step = _first(kind=graph.STEP)
    # Not `match="next|successor"`: with this rule removed, reachability fires and lists the
    # nodes it could not reach — one of which is `next_module`, so the pattern matched a node id
    # inside another rule's message.
    with pytest.raises(graph.GraphError, match="has no successor"):
        _validate_with(_mutate(step.id, next=None))


def test_every_node_is_reachable_from_intake():
    """An unreachable node is a mechanism nobody can get to, and the walk would never say so."""
    orphan = dataclasses.replace(_first(kind=graph.TERMINAL), id="orphan")
    with pytest.raises(graph.GraphError, match="unreachable|reach"):
        _validate_with(graph.NODES + (orphan,))


# ── what a node may claim about gates ────────────────────────────────────────────────────────

def test_a_node_may_not_name_a_gate_policy_does_not_have():
    gated = _first(gate="merge")
    with pytest.raises(graph.GraphError, match="names gate .*policy.py does not define"):
        _validate_with(_mutate(gated.id, gate="no_such_gate"))


def test_a_node_may_not_name_a_role_policy_does_not_have():
    roled = next(n for n in graph.NODES if n.role and n.role in policy.BY_ROLE)
    with pytest.raises(graph.GraphError, match="names role .*policy.py does not define"):
        _validate_with(_mutate(roled.id, role="no_such_role"))


def test_a_gate_phase_outside_the_two_words_is_refused():
    gated = _first(gate="merge")
    with pytest.raises(graph.GraphError, match="before|after|phase"):
        _validate_with(_mutate(gated.id, gate_when="whenever"))


def test_an_after_phase_may_not_name_no_gate():
    """The half of the documented contract that is actually enforced. The other half — an ungated
    node carrying the default `before` — is not, and `CHG-20260907-07` does not change that: three
    gated nodes rely on the default, and the documentation is what is being narrowed to match."""
    ungated = next(n for n in graph.NODES if not n.gate)
    # The message is *"has a gate phase but no gate"* — the documented contract in full, while
    # the condition above it implements half: an ungated node carrying the default `before` also
    # has a phase and no gate, and is accepted. Round fourteen's conformance seat holds its veto
    # on that; this test pins the half that is enforced, and says which half that is.
    with pytest.raises(graph.GraphError, match="has a gate phase but no gate"):
        _validate_with(_mutate(ungated.id, gate_when="after"))


def test_only_a_terminal_may_be_permanent():
    step = _first(kind=graph.STEP)
    with pytest.raises(graph.GraphError, match="permanent"):
        _validate_with(_mutate(step.id, permanent=True))


# ── what a node may claim about answers ──────────────────────────────────────────────────────

def test_an_answer_may_not_decide_where_nobody_is_asked():
    """`answer_decides` on a node with no role is a field about an answer nobody gives."""
    roleless = next(n for n in graph.NODES if not n.role and not n.answer_decides)
    with pytest.raises(graph.GraphError, match="answer|role"):
        _validate_with(_mutate(roleless.id, answer_decides=True))


# ── where a refusal goes ─────────────────────────────────────────────────────────────────────

def test_a_rejection_needs_a_gate_to_be_refused_at():
    """`rejects_to` says where a refusal goes; a node with no gate has nothing to refuse."""
    ungated = next(n for n in graph.NODES if not n.gate and not n.rejects_to)
    # `match="gate|reject"` matched nearly every message this function can raise.
    with pytest.raises(graph.GraphError, match="has no gate to reject"):
        _validate_with(_mutate(ungated.id, rejects_to="intake"))


def test_a_rejection_may_not_land_where_the_run_can_never_come_back_from():
    """The weak half of the rule, and the record says plainly that it is the weak half.

    A refusal is not how a run ends, so a target the walk can never return from is refused. In
    this graph that means a terminal.
    """
    with pytest.raises(graph.GraphError, match="cannot reach it again"):
        _validate_with(_mutate("qa_accept", rejects_to="done"))


def test_the_whole_change_bound_reads_the_graph_rather_than_a_written_list():
    """`_WHOLE_CHANGE_REJECTED` was the tuple `("review_failed", "acceptance_failed")` — exactly
    the nodes whose `.next` is `change_retry`, written out by hand beside the graph that says so.

    A written copy cannot be told from a derivation while the two agree, which is why this test
    adds a **third** such node and asks whether the bound sees it. Under the hand-written pair it
    does not.

    It is a function rather than a module constant for the reason `engine._MODULE_CYCLE` is a
    finding of this same round: that one snapshots `graph.module_cycle()` at import while `plan.py`
    asks per call, and the two disagree about a node added later. Deriving at import would have
    reproduced the shape this change removes.
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
        _validate_with(_mutate(rejecting.id, rejects_to="nowhere_at_all"))


def test_a_rejection_may_not_return_to_the_node_that_was_refused():
    """A refusal that lands where it was made is a loop with a person in it."""
    rejecting = next(n for n in graph.NODES if n.rejects_to)
    with pytest.raises(graph.GraphError, match="itself|same"):
        _validate_with(_mutate(rejecting.id, rejects_to=rejecting.id))


# ── a node's kind, and what it promises about its edges ──────────────────────────────────────────


def test_an_unknown_kind_is_refused():
    """`MODES` has always been closed; `kind` was not, and 23 of 31 nodes accepted nonsense in it.

    The phrase is matched narrowly on purpose. Several other rules fire on a typo'd kind as
    collateral, naming a different node, and a loose `match=` here would go green on one of those
    — which is exactly how five reverse tests in this file were found hollow (CHG-20260907-07).
    """
    with pytest.raises(graph.GraphError, match="unknown kind"):
        _validate_with(_mutate("engineer_build", kind="stpe"))


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
        _validate_with(_mutate(node_id, kind=node.kind + "_", **changes))


def test_the_one_terminal_a_typo_used_to_survive_on():
    """`done` is the only node where a nonsense kind both validated and reached the engine.

    The other three terminals are `permanent`, and the permanent-only-on-terminal rule refuses
    them. `done` is not, so it validated, and `engine.walk`'s `node.kind == TERMINAL` test read it
    as an ordinary node: the run still reported `finished` and `halted_at` came back `None`.
    """
    assert graph.BY_ID["done"].kind == graph.TERMINAL
    assert not graph.BY_ID["done"].permanent
    with pytest.raises(graph.GraphError, match="unknown kind"):
        _validate_with(_mutate("done", kind="termnial"))


def test_a_node_may_not_declare_both_branches_and_a_successor():
    """The two edge shapes are exclusive, because a run only ever takes one of them.

    `validate`'s reachability walk unions `branches` and `next`; `engine.walk` takes `branches` if
    there are any and `next` otherwise. A node carrying both makes the guard and the run disagree
    about what the graph is.
    """
    step = _first(id="record_module")
    assert step.next and not step.branches
    with pytest.raises(graph.GraphError, match="no run can ever take"):
        _validate_with(_mutate(step.id, branches={"again": "next_module", "stop": "done"}))


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
        _validate_with(_mutate("reconcile", branches=kept, next="halt_unreconciled"))


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
