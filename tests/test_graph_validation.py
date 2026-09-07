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


def test_a_rejection_may_not_name_a_node_that_does_not_exist():
    rejecting = next(n for n in graph.NODES if n.rejects_to)
    with pytest.raises(graph.GraphError, match="reject|no node|unknown"):
        _validate_with(_mutate(rejecting.id, rejects_to="nowhere_at_all"))


def test_a_rejection_may_not_return_to_the_node_that_was_refused():
    """A refusal that lands where it was made is a loop with a person in it."""
    rejecting = next(n for n in graph.NODES if n.rejects_to)
    with pytest.raises(graph.GraphError, match="itself|same"):
        _validate_with(_mutate(rejecting.id, rejects_to=rejecting.id))
