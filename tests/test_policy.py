"""The governance this runner owns (CHG-20260823-01).

Every value here used to be read out of a vendored skill, and the runner was forbidden to hold any of
it. There is no skill: these are ours, and what they are checked against is the requirement rather
than a file. Two properties carry most of the weight:

* **Completeness is structural.** The old design inherited a table covering four of thirteen roles,
  which is why nine could not be dispatched. Here the roles are the ones the flow uses, and that is
  asserted rather than assumed.
* **Nothing is defaulted.** An unknown gate, risk or role raises. A governance value that appears out
  of nowhere when asked for something undefined is the silent fallback everything here refuses.
"""
from __future__ import annotations

import pytest

from ai_sdlc_runner import graph, policy


# --------------------------------------------------------------------------------------
# completeness
# --------------------------------------------------------------------------------------

def test_every_role_the_flow_uses_is_defined_with_capabilities():
    """The failure that cannot recur: a node naming a role nothing describes."""
    for role in graph.roles_used():
        caps = policy.capabilities(role)
        assert set(caps) == {"can_spawn", "can_write", "can_execute"}
        assert all(isinstance(v, bool) for v in caps.values())


def test_every_gate_the_flow_consults_is_defined_for_every_risk():
    for gate in set(graph.gates_used()):
        for risk in policy.RISKS:
            assert policy.GATES[gate][risk] in (policy.AUTO, *policy.STOPPING)


def test_nothing_is_defined_that_the_flow_never_uses():
    """An unused gate or role is a governance value nobody can point at a decision for."""
    assert set(graph.gates_used()) == set(policy.GATES)
    assert set(graph.roles_used()) == set(policy.BY_ROLE)


# --------------------------------------------------------------------------------------
# the capability that carries weight
# --------------------------------------------------------------------------------------

def test_the_dispatch_tree_is_two_deep():
    """The property the old name-list stood for.

    This assertion used to read `spawners == ["lead"]`, and it guarded the wrong thing: a **list of
    names**, when what the requirement cares about is how many layers sit between the operator and
    the work. CHG-20260827-22 let the PM dispatch a planner, which breaks the name list and leaves
    the depth exactly where it was — `pm → planner` and `lead → engineer` are siblings, not nested.

    Derived from the graph, so a fourth tier fails here whether or not anyone updates a list.
    """
    depth = policy.dispatch_depth(graph.dispatch_edges(), graph.roles_asked_directly())
    assert depth == 2, f"the dispatch tree is {depth} deep: {graph.dispatch_edges()}"
    assert depth <= policy.MAX_DISPATCH_DEPTH


def test_a_deeper_tree_is_refused_and_says_which_chain():
    """The bound is enforced, not merely stated — the whole reason the constant exists."""
    deep = {"pm": ["planner"], "planner": ["lead"], "lead": ["engineer"]}
    with pytest.raises(policy.PolicyError) as exc:
        policy.check_dispatch_depth(deep, ["pm"])
    assert "4 deep" in str(exc.value)
    assert "planner dispatches lead" in str(exc.value)


def test_a_dispatch_cycle_is_refused_rather_than_hung():
    """A role reachable from itself has no depth; the caller hears that instead of waiting."""
    with pytest.raises(policy.PolicyError) as exc:
        policy.dispatch_depth({"lead": ["engineer"], "engineer": ["lead"]}, ["lead"])
    assert "loops" in str(exc.value)


def test_every_spawner_actually_dispatches_somebody_in_the_graph():
    """`can_spawn=True` on a role no pool node names is a capability granted for nothing.

    This is the guard the old name-list could not give: it checked *who* was allowed to dispatch,
    never whether the permission corresponded to anything the flow does.
    """
    spawners = {r.name for r in policy.ROLES if r.can_spawn}
    dispatching = set(graph.dispatch_edges())
    assert spawners == dispatching, (
        f"roles permitted to dispatch: {sorted(spawners)}; roles that actually dispatch in the "
        f"graph: {sorted(dispatching)}. A permission nothing uses is not a permission.")


def test_qa_and_the_seats_cannot_write_what_they_judge():
    """They may run things — that is how verification works — but not fix while verifying."""
    for name in ("qa", "seat"):
        caps = policy.capabilities(name)
        assert caps["can_execute"] is True
        assert caps["can_write"] is False
        assert caps["can_spawn"] is False


# --------------------------------------------------------------------------------------
# the gates
# --------------------------------------------------------------------------------------

def test_merge_stops_earliest_because_it_is_a_one_way_door():
    """The rule behind the grades, checked where it bites: merging stops at medium risk, while a
    task review — cheap to redo — never stops at all."""
    assert policy.GATES["merge"]["medium"] in policy.STOPPING
    assert policy.GATES["task_review"]["high"] == policy.AUTO


def test_high_risk_acceptance_wants_someone_other_than_the_builder():
    assert policy.GATES["acceptance"]["high"] == policy.HALT_INDEPENDENT


def test_anything_that_is_not_auto_stops():
    assert policy.stops(policy.AUTO) is False
    for value in policy.STOPPING:
        assert policy.stops(value) is True


def test_autonomy_may_tighten():
    v = policy.verdict("task_review", "low", autonomy="halt")
    assert v["verdict"] == "halt" and v["tightened"] is True


def test_autonomy_may_not_loosen_and_the_attempt_is_reported():
    """A request to relax a gate is worth seeing rather than silently dropping."""
    v = policy.verdict("merge", "high", autonomy="auto")
    assert v["verdict"] == policy.HALT
    assert "refused" in v["source"]


def test_an_unknown_gate_risk_or_role_raises_rather_than_defaulting():
    with pytest.raises(policy.PolicyError):
        policy.verdict("no_such_gate", "low")
    with pytest.raises(policy.PolicyError):
        policy.verdict("merge", "catastrophic")
    with pytest.raises(policy.PolicyError):
        policy.role("nobody")


def test_the_verdict_shape_is_fixed():
    """Fixed so a work order's closed schema can carry it without special cases."""
    for autonomy in (None, "halt", "auto"):
        v = policy.verdict("merge", "high", autonomy=autonomy)
        assert set(v) == {"gate", "risk", "verdict", "source", "tightened"}


# --------------------------------------------------------------------------------------
# seats
# --------------------------------------------------------------------------------------

def test_seats_open_least_negotiable_first():
    assert policy.seat_names(1) == ["conformance"]
    assert policy.SEATS[0].veto is True


def test_the_floor_holds_without_high_risk_mode():
    with pytest.raises(policy.PolicyError) as exc:
        policy.resolve_seats(1, high_risk_mode=False)
    assert "high-risk mode" in str(exc.value)
    assert policy.resolve_seats(1, high_risk_mode=True) == 1
    assert policy.resolve_seats(None, high_risk_mode=False) == policy.SEAT_FLOOR


def test_more_seats_than_exist_is_refused():
    with pytest.raises(policy.PolicyError):
        policy.seat_names(len(policy.SEATS) + 1)


# --------------------------------------------------------------------------------------
# adjudication — the reason the panel exists
# --------------------------------------------------------------------------------------

def test_a_veto_cannot_be_outvoted():
    """Its subject is a matter of fact, and counting votes on a fact is how a panel talks itself out
    of one."""
    outcome = policy.adjudicate({"conformance": "fail", "defect": "pass", "risk": "pass"})
    assert outcome["outcome"] == "fail"
    assert outcome["vetoed"] == ["conformance"]


def test_a_majority_passes():
    assert policy.adjudicate(
        {"conformance": "pass", "defect": "pass", "risk": "fail"})["outcome"] == "pass"


def test_a_tie_does_not_pass_and_does_not_fail_either():
    """A tie decides nothing, and *nothing* is a third answer.

    **This test changed deliberately in CHG-20260823-11 task 2.** It used to assert a tie returns
    ``fail``, and it was not wrong — the rule it asserted was the rule. The rule changed, and the
    reason is worth more than the diff: ``fail`` sends the work back, and sending work back is a
    judgement. An even split has made no judgement. Calling it a failure meant the runner deciding
    on the panel's behalf while reporting that the panel had decided.

    What is preserved is the property the old name was protecting — **a tie still does not pass**.
    That was never the part in question.
    """
    outcome = policy.adjudicate({"conformance": "pass", "defect": "fail"})
    assert outcome["outcome"] == policy.UNDECIDED
    assert outcome["outcome"] != policy.PASS
    assert "decides nothing" in str(outcome["reason"])


def test_an_unknown_seat_is_refused():
    with pytest.raises(policy.PolicyError):
        policy.adjudicate({"nobody": "pass"})


def test_no_verdicts_is_not_a_pass():
    with pytest.raises(policy.PolicyError):
        policy.adjudicate({})
