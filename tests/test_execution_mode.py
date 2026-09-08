"""Task 12 — the execution mode is node data, and it constrains something.

Three review rounds turned on one question: **how does the runner know that several models on
`engineer_build` is a pool and several on `lead_task_review` is a panel?** Every answer that read a
node's *name* was rejected, because this repository merged "a name is evidence only if it constrains
what happens" (CHG-20260823-10) and then immediately proposed keying dispatch off `id ==
"engineer_build"`.

So the mode is declared, and these tests are what stop it being decoration:

* **Every node has one**, from the closed set. A default that quietly applies to a node nobody
  thought about is how `SINGLE` would end up meaning "unclassified".
* **`validate()` refuses the disagreements**, each with its own test. A validator that only checks
  the field exists satisfies the prose and catches nothing — an independent seat named that exact
  hollow implementation, so each rule gets a case that fails without it.
* **The engine reads the mode**, not the role. Under the biconditional below the two always agree
  today, which is precisely why this test matters: it is the one that fails if someone "simplifies"
  the dispatch back to `role == "seat"` and leaves `mode` as a comment with a syntax.

## On the biconditionals

`role is None ⟺ mode == RUNNER` and `role == "seat" ⟺ mode == SEAT_PANEL` look like the inference
the design forbids, and are its opposite. Inference *derives* mode from role — one fact, silently
doing two jobs. These **check** two independently written facts against each other, so a node whose
role and mode disagree is a build error instead of a run-time surprise. The distinction is the
reason `role` could go back into the design's inference-refusal clause after round 3 found it had
been dropped without a reason.
"""
import dataclasses

import pytest

from ai_sdlc_runner import graph
from _graph_swap import validate_with


def _mutate(node_id, **changes):
    """The real graph with one node changed — the shape a wrong hand-edit would actually take."""
    nodes = tuple(dataclasses.replace(n, **changes) if n.id == node_id else n for n in graph.NODES)
    return nodes


def test_every_node_declares_a_mode_from_the_closed_set():
    for node in graph.NODES:
        assert node.mode in graph.MODES, f"{node.id} has mode {node.mode!r}"


def test_the_real_graph_validates():
    graph.validate()


def test_the_modes_partition_every_node():
    counted = sum(1 for n in graph.NODES if n.mode in graph.MODES)
    assert counted == len(graph.NODES), "every node has a mode from the closed set"


def test_a_node_that_asks_nobody_is_runner_and_only_such_a_node_is():
    for node in graph.NODES:
        assert (node.role is None) == (node.mode == graph.RUNNER), node.id


def test_the_seats_are_the_only_seat_panel():
    seat_panels = [n.id for n in graph.NODES if n.mode == graph.SEAT_PANEL]
    assert seat_panels == ["lead_review"]


def test_a_role_bearing_node_declared_runner_is_refused():
    with pytest.raises(graph.GraphError, match="asks nobody"):
        validate_with(_mutate("pm_plan", mode=graph.RUNNER))


def test_a_runner_node_declared_single_is_refused():
    # This used to be justified by the dataclass default — `SINGLE` was where a node added
    # without thinking about its mode landed. CHG-20260907-26 removed that default, so the
    # omission is refused on its own now (the test below) and this one holds what is left: a
    # node that asks nobody and has `SINGLE` written on it deliberately.
    with pytest.raises(graph.GraphError, match="asks nobody|must be"):
        validate_with(_mutate("intake", mode=graph.SINGLE))


def test_a_non_seat_node_declared_seat_panel_is_refused():
    with pytest.raises(graph.GraphError, match="only the review seats"):
        validate_with(_mutate("lead_task_review", mode=graph.SEAT_PANEL))


def test_the_seat_node_declared_model_panel_is_refused():
    with pytest.raises(graph.GraphError, match="only the review seats"):
        validate_with(_mutate("lead_review", mode=graph.MODEL_PANEL))


def test_an_unknown_mode_is_refused():
    with pytest.raises(graph.GraphError, match="unknown mode"):
        validate_with(_mutate("pm_plan", mode="committee"))


def test_a_work_producing_node_cannot_be_a_model_panel():
    # `qa_verify` produces work, not a verdict. Several models there would be several candidate
    # outputs and no rule for choosing — which the design lists as unsettled rather than inventing.
    with pytest.raises(graph.GraphError, match="nothing\nto adjudicate|nothing to adjudicate"):
        validate_with(_mutate("qa_verify", mode=graph.MODEL_PANEL))


def test_a_pool_must_name_a_main():
    with pytest.raises(graph.GraphError, match="names no main"):
        validate_with(_mutate("engineer_build", main=None))


def test_a_pools_main_is_a_role_not_a_node_id():
    # The mock-up used a role here and a node id for `follows`, and the design record deferred the
    # question. Deferring it was the finding: two builders would have produced incompatible graphs.
    with pytest.raises(graph.GraphError, match="not a role|is a role, not a node id"):
        validate_with(_mutate("engineer_build", main="lead_assess"))


def test_only_a_pool_carries_a_main():
    with pytest.raises(graph.GraphError, match="no use for a main"):
        validate_with(_mutate("pm_plan", main="lead"))


def test_a_follows_must_name_a_node():
    with pytest.raises(graph.GraphError, match="names no node to follow"):
        validate_with(_mutate("engineer_selfverify", follows=None))


def test_a_follows_target_is_a_node_id_not_a_role():
    with pytest.raises(graph.GraphError, match="unknown node|is a node\nid|is a node id"):
        validate_with(_mutate("engineer_selfverify", follows="engineer"))


def test_a_follows_chain_is_refused():
    # `fix_pass` follows `engineer_build`. Pointing it at `engineer_selfverify` — itself a follows —
    # would leave nothing at the end of the chain that actually chose a model.
    with pytest.raises(graph.GraphError, match="follows something else"):
        validate_with(_mutate("fix_pass", follows="engineer_selfverify"))


def test_a_node_cannot_follow_itself():
    # The alternation this used to carry — `follows itself|follows something else` — let the test
    # pass on the chain rule, which fired first and said the node followed "something else" while
    # pointing at itself. The rule this test is named for could not run. Narrowed, so the name and
    # the assertion agree (CHG-20260907-07).
    with pytest.raises(graph.GraphError, match="follows itself"):
        validate_with(_mutate("engineer_selfverify", follows="engineer_selfverify"))


def test_only_a_follows_carries_a_follows():
    with pytest.raises(graph.GraphError, match="no use for a follows"):
        validate_with(_mutate("pm_plan", follows="pm_confirm"))


def test_the_engine_decides_a_panel_from_the_mode_not_the_role():
    """The test that fails if `mode` is ever quietly demoted back to decoration.

    `role == "seat"` and `mode == SEAT_PANEL` agree on every node in the real graph, so reading
    either one behaves identically today. That is what makes this worth pinning: the only way to
    tell whether the engine consults the declared mode is to read the engine.
    """
    import inspect

    from ai_sdlc_runner import engine
    # `_walk` is the body; `walk` is the wrapper that closes the durable record when the
    # body does not return (CHG-20260907-15). The property below is the body's.

    source = inspect.getsource(engine._walk)
    assert 'node.role == "seat"' not in source, (
        "the walk is keying its panel decision off the role again — the mode is then a field "
        "nothing reads, which is the decorative-data failure task 12 exists to prevent")
    assert "graph.SEAT_PANEL" in source, "the walk should decide a panel from the declared mode"

def test_a_node_whose_author_never_declared_a_mode_is_refused():
    """The state that had no name until CHG-20260907-26: `mode` defaulted, so an omission was
    `SINGLE` — 4 of the 31 nodes, where `RUNNER` is 15. The default was the minority value, the
    same shape CHG-20260907-11 removed from `gate_when`, whose `before` was 3 of 10.

    **Through the constructor, not through `_mutate`.** `_mutate("pm_plan", mode=None)` would
    pass with the default restored, because what it trips is the `is None` clause and that
    clause survives the mutation. A default can only act where a value is not supplied, so the
    node has to be built without one — which is also the shape of the real mistake: somebody
    adds a node and does not think about its mode.

    Measured before the default went: `lead_task_review` rebuilt from its own fields minus
    `mode` came back `single` against a real `model_panel`, and `validate()` **accepted** it.
    """
    import dataclasses

    shipped = graph.BY_ID["lead_task_review"]
    fields = {f.name: getattr(shipped, f.name) for f in dataclasses.fields(shipped)}
    del fields["mode"]
    forgotten = graph.Node(**fields)
    assert forgotten.mode is None, "a mode nobody wrote down must not come back as a mode"
    with pytest.raises(graph.GraphError, match="declares no mode"):
        validate_with(tuple(forgotten if n.id == shipped.id else n for n in graph.NODES))
