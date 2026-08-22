"""The node graph, pinned to the skill's shipped flow (CHG-20260822-04 task 6).

Three invariants, each protecting a different failure and none substituting for another:

* **the pin** — every node names a literal phrase from the shipped `## State machine` block, in the
  block's own order. If the skill changes its flow, this goes red.
* **checkpoint coverage** — each of the store's checkpoint elements hangs on the graph exactly once,
  and every checkpoint the graph names exists as an element. Policy attaches to nodes; it never
  decides where they sit.
* **role coverage** — every role the graph dispatches has shipped capability data, and a node with a
  role that does not must **stop**, not be skipped.

The granularity rule the requirement states — *one node, one type of work* — is checked directly:
build, test and review are separate nodes, as are PR and merge, and requirement analysis and
structure design.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sdlc_runner import graph, workorder

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "skills" / "v1.64.0"
TREE = REPO_ROOT / "elements" / "v1.64.0"

pytestmark = pytest.mark.skipif(
    not (STORE / "assets").is_dir() or not TREE.is_dir(),
    reason="vendored store or element tree not present in this checkout",
)


# --------------------------------------------------------------------------------------
# the pin: the graph is the shipped flow, not an invention
# --------------------------------------------------------------------------------------

def test_every_node_names_a_phrase_from_the_shipped_block():
    text = graph.source_text(TREE)
    missing = [n.id for n in graph.NODES if n.source_phrase not in text]
    assert missing == [], f"nodes whose phrase is not in {graph.SOURCE_ELEMENT}: {missing}"


def test_the_node_order_matches_the_shipped_order():
    """First appearance of each phrase, in the block, must be non-decreasing across the graph.

    Non-decreasing rather than strictly increasing because several nodes legitimately share a
    phrase — requirement analysis and structure design are both governance, acceptance and its
    failure branch are both acceptance — and the block writes each once.
    """
    text = graph.source_text(TREE)
    positions = [text.find(n.source_phrase) for n in graph.NODES]
    assert all(p >= 0 for p in positions)
    out_of_order = [
        (graph.NODES[i].id, graph.NODES[i + 1].id)
        for i in range(len(positions) - 1) if positions[i] > positions[i + 1]
    ]
    assert out_of_order == [], f"nodes out of the shipped order: {out_of_order}"


def test_the_pin_has_exactly_one_authority():
    """`SKILL.md`'s `## The loop` is a shortened variant — it omits the confirm gate and every
    branch — so pinning to it as well would fail over a difference in detail, not in flow."""
    assert graph.SOURCE_ELEMENT == "references/autopilot-loop#state-machine"
    skill_md = (STORE / "SKILL.md").read_text(encoding="utf-8")
    assert "confirm gate" not in skill_md.split("## The loop")[1].split("##")[0]


def test_a_missing_source_element_is_a_hard_error(tmp_path):
    with pytest.raises(graph.GraphError) as exc:
        graph.source_text(tmp_path)
    assert graph.SOURCE_ELEMENT in str(exc.value)


# --------------------------------------------------------------------------------------
# the graph is a graph: loops and branches survive
# --------------------------------------------------------------------------------------

def test_the_graph_is_internally_consistent():
    graph.validate()


def test_the_per_task_loop_has_a_back_edge():
    """"[ per unticked task T_i: … ]" is a loop, and the loop is the resume mechanism: an already
    ticked task is simply not the frontier. Flattening it would lose both at once."""
    assert graph.BY_ID["tick_commit"].next == "next_task"
    assert graph.BY_ID["next_task"].kind == graph.LOOP
    assert set(graph.BY_ID["next_task"].branches) == {"task", "none"}


def test_the_review_failure_path_is_a_bounded_retry_not_a_loop():
    """One fix pass, then re-review, and "second fail = halt" — never repeat-until-green."""
    assert graph.BY_ID["task_review"].branches["fail"] == "fix_pass"
    assert graph.BY_ID["fix_pass"].next == "re_review"
    assert graph.BY_ID["re_review"].branches["fail"] == "halt_second_fail"
    assert graph.BY_ID["halt_second_fail"].kind == graph.TERMINAL
    # the only way back into the happy path is a passing re-review
    assert graph.BY_ID["re_review"].branches["pass"] == "tick_commit"


def test_the_unconfirmed_chg_branch_leaves_the_runners_layer():
    node = graph.BY_ID["chg_confirmed"]
    assert node.kind == graph.DECISION
    assert node.branches["no"] == "requirement_analysis"
    assert node.branches["yes"] == "plan_check"


def test_a_failed_acceptance_returns_to_the_task_loop():
    assert graph.BY_ID["acceptance"].branches["fail"] == "acceptance_failed"
    assert graph.BY_ID["acceptance_failed"].next == "next_task"


def test_the_graph_is_not_a_straight_line():
    """Guard against a future simplification quietly flattening it."""
    assert sum(1 for n in graph.NODES if n.kind in (graph.DECISION, graph.LOOP)) >= 4
    assert sum(1 for n in graph.NODES if n.kind == graph.TERMINAL) >= 2


# --------------------------------------------------------------------------------------
# one node, one type of work
# --------------------------------------------------------------------------------------

def test_build_test_and_review_are_separate_nodes():
    """The requirement states it directly: an item does a single type of work. Build, the
    engineer's own verification, and the review of that work are three types."""
    for node_id in ("build", "task_tests", "task_review"):
        assert node_id in graph.BY_ID
    assert graph.BY_ID["build"].next == "task_tests"
    assert graph.BY_ID["task_tests"].next == "task_review"


def test_pr_and_merge_are_separate_nodes():
    assert graph.BY_ID["pr"].next == "merge"
    assert graph.BY_ID["pr"].checkpoints != graph.BY_ID["merge"].checkpoints


def test_requirement_analysis_and_structure_design_are_separate_nodes():
    assert graph.BY_ID["requirement_analysis"].next == "structure_design"
    assert graph.BY_ID["requirement_analysis"].checkpoints == ("halt:requirement_confirmed",)
    assert graph.BY_ID["structure_design"].checkpoints == ("halt:structure_confirmed",)


# --------------------------------------------------------------------------------------
# checkpoint coverage — both directions
# --------------------------------------------------------------------------------------

def _shipped_checkpoints():
    manifest = json.loads((TREE / "dispatch" / "manifest.json").read_text(encoding="utf-8"))
    return {r["element_id"] for r in manifest["elements"] if r["kind"] == "checkpoint"}


def test_every_shipped_checkpoint_hangs_on_the_graph_exactly_once():
    attached = graph.checkpoint_ids()
    assert sorted(attached) == sorted(_shipped_checkpoints())
    assert len(attached) == len(set(attached)), "a checkpoint is attached to more than one node"


def test_every_checkpoint_the_graph_names_exists_as_an_element():
    """The other direction. Together these two make a store that gains or loses a gate fail loudly
    instead of leaving the graph quietly out of date."""
    shipped = _shipped_checkpoints()
    unknown = sorted(set(graph.checkpoint_ids()) - shipped)
    assert unknown == []


def test_checkpoints_never_decide_where_a_node_sits():
    """Policy hangs on nodes; the flow's order comes from the shipped block. A node with no
    checkpoint at all must still be allowed — `whole-branch review` is a code gate, not a risk
    gate, and inventing a checkpoint for it would be authoring policy."""
    assert graph.BY_ID["branch_review"].checkpoints == ()


# --------------------------------------------------------------------------------------
# role coverage — hard stop, never skip
# --------------------------------------------------------------------------------------

def test_every_dispatched_role_has_shipped_capability_data():
    for role in graph.dispatched_roles():
        caps = workorder.capabilities_for(STORE, role)
        assert set(caps) == set(workorder.CAPABILITY_FIELDS)


def test_the_lead_is_the_only_dispatching_role():
    """"The lead dispatches the engineers" is a shipped fact, not an arrangement invented here:
    `can_spawn` is true for the lead implementer and false for everyone else on this graph."""
    spawners = [r for r in graph.dispatched_roles()
                if workorder.capabilities_for(STORE, r)["can_spawn"]]
    assert spawners == ["lead-implementer"]


def test_the_verifier_may_execute_but_not_write():
    """QA runs the whole thing for real, and mechanically cannot fix while verifying."""
    caps = workorder.capabilities_for(STORE, "verifier")
    assert caps == {"can_spawn": False, "writable": False, "can_execute": True}


def test_a_node_whose_role_has_no_capability_data_stops_rather_than_being_skipped():
    """The engine must not step over a node it cannot render — that is the silent downgrade the
    whole design refuses. Proven on a role the skill declares but supplies no capability row for."""
    node = graph.Node(id="panel", kind=graph.STEP, source_phrase="whole-branch review",
                      role="seat-risk", next="close_out")
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.capabilities_for(STORE, node.role)
    assert "seat-risk" in str(exc.value)
    assert "no shipped capability row" in str(exc.value)


def test_the_graph_dispatches_only_roles_that_can_actually_be_rendered():
    """Stated as an equality rather than a subset, so that adding a node for an undispatchable role
    fails here instead of at run time."""
    renderable = []
    for role in json.loads((STORE / "assets" / "role_refs.json").read_text(encoding="utf-8"))["roles"]:
        try:
            workorder.capabilities_for(STORE, role)
        except workorder.WorkOrderError:
            continue
        renderable.append(role)
    assert set(graph.dispatched_roles()) <= set(renderable)
    assert sorted(renderable) == ["analyst", "lead-implementer", "sub-implementer", "verifier"]
