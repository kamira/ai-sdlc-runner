"""The work-order format and renderer (CHG-20260822-04 task 5).

Two done-when clauses, checked from opposite sides:

* **no harness-specific field** — proven by enumerating what the order *contains* against a closed
  whitelist, plus a sentinel that would have to appear if a tool name ever leaked. Never by
  substring-searching for banned words: that scores 21 false positives on this repo's own corpus and
  already failed the guard test written for task 2.
* **renders without any sibling element** — proven by showing every source in a rendered order
  carries the path and anchor it resolves to, so the receiving node needs only the order and the
  store.

The capability-flag group pins the deliberate hard error: nine of thirteen roles have no shipped
capability data, and rendering one is refused rather than defaulted.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from ai_sdlc_runner import agents, dispatch, workorder

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "skills" / "v1.64.0"
TREE = REPO_ROOT / "elements" / "v1.64.0"

pytestmark = pytest.mark.skipif(
    not (STORE / "assets").is_dir() or not TREE.is_dir(),
    reason="vendored store or element tree not present in this checkout",
)

NODE_SPEC = {
    "scope": "src/ai_sdlc_runner/",
    "objective": "implement the thing the CHG task describes",
    "done_criteria": ["suite green", "doc-integrity exit 0"],
    "input_artifacts": ["docs/changes/CHG-20260822-04.md"],
    "expected_outputs": ["src/ai_sdlc_runner/thing.py"],
    "acceptance_predicate": "pytest tests/ exits 0",
    "idempotence_probes": [{"effect": "push", "probe": "git ls-remote origin <branch>"}],
    "workdir": ".",
}
VERDICT = {
    "checkpoint": "halt:before_implement",
    "risk": "medium",
    "verdict": "auto",
    "source": "assets/halt_policy.json",
}

COVERED = ("analyst", "lead-implementer", "sub-implementer", "verifier")
UNCOVERED = ("orchestrator", "integrator", "reviewer",
             "seat-risk", "seat-impact", "seat-drift",
             "seat-compliance", "seat-security", "seat-consistency")


def _render(role="verifier", **kwargs):
    return workorder.render(STORE, TREE, role, "halt:before_implement",
                            NODE_SPEC, VERDICT, **kwargs)


# --------------------------------------------------------------------------------------
# done-when — no harness-specific field
# --------------------------------------------------------------------------------------

def test_rendered_order_has_exactly_the_closed_schema():
    """Absence is proven by enumerating presence: any harness-specific field would have to show up
    as a key outside the D5 whitelist."""
    assert sorted(_render()) == sorted(workorder.WORK_ORDER_FIELDS)


def test_no_tool_name_can_escape_into_an_order(monkeypatch):
    """The sentinel check. `agents` synthesises a tools list of Claude Code names; if the renderer
    ever read it — directly, or by deriving flags back from it — this unique string would surface."""
    sentinel = "SENTINEL-4f3a9c-TOOLNAME"
    real = agents.parse_role_table(STORE)
    patched = {
        code: dataclasses.replace(spec, tools=[sentinel, *spec.tools])
        for code, spec in real.items()
    }
    monkeypatch.setattr(agents, "parse_role_table", lambda _p: patched)

    # Guard against a vacuous pass: the sentinel must really be in what the renderer reads from,
    # otherwise this test would go green by patching nothing.
    assert sentinel in agents.parse_role_table(STORE)["V1"].tools

    rendered = workorder.to_json(_render())
    assert sentinel not in rendered
    assert "SENTINEL" not in rendered


def test_writes_docs_never_reaches_an_order():
    """`RoleSpec.writes_docs` is guessed from prose in the Notes column and is not one of D5's three
    flags. It is excluded on the same grounds as the tool names."""
    order = _render()
    assert sorted(order["capabilities"]) == sorted(workorder.CAPABILITY_FIELDS)
    assert "writes_docs" not in workorder.to_json(order)


def test_capabilities_are_exactly_the_three_shipped_booleans():
    order = _render()
    assert set(order["capabilities"]) == set(workorder.CAPABILITY_FIELDS)
    assert all(isinstance(v, bool) for v in order["capabilities"].values())


def test_no_body_is_inlined():
    """D5: paths and anchors only. Inlining bodies would re-import the cost the decomposition removed."""
    order = _render()
    for source in order["sources"]:
        assert set(source) == {"element_id", "source_path", "anchor", "anchor_slug"}
    assert "body" not in workorder.to_json(order)


def test_a_field_outside_the_contract_cannot_ride_in_through_the_caller():
    """The closed node spec is what stops a harness-specific field entering by the back door."""
    spec = dict(NODE_SPEC, model="claude-opus-5", tools=["Read", "Bash"])
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.render(STORE, TREE, "verifier", "halt:before_implement", spec, VERDICT)
    assert "outside the contract" in str(exc.value)


# --------------------------------------------------------------------------------------
# done-when — renders without any sibling element
# --------------------------------------------------------------------------------------

def test_every_source_carries_the_path_and_anchor_it_resolves_to():
    """The operational form of self-sufficiency: a content element id must never appear without the
    path and anchor it dereferences to, or the node would need the manifest to find its material."""
    order = _render()
    assert order["sources"]
    for source in order["sources"]:
        assert source["source_path"].startswith("references/")
        assert source["anchor"] and source["anchor_slug"]


def test_the_order_plus_the_store_is_enough():
    """Everything the order points at exists in the store, so nothing else has to travel with it."""
    order = _render()
    for source in order["sources"]:
        assert (STORE / source["source_path"]).is_file()


def test_the_order_names_no_path_inside_the_element_tree():
    """A path into `elements/` would make the order depend on the derived tree rather than on the
    store — the sibling-element dependency the clause forbids."""
    rendered = workorder.to_json(_render())
    assert "elements/" not in rendered
    assert "dispatch/" not in rendered


# --------------------------------------------------------------------------------------
# capability flags — the deliberate hard error
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("role", COVERED)
def test_roles_with_a_shipped_row_render(role):
    order = _render(role=role)
    assert order["role"] == role
    assert order["node_id"] == f"{role}@halt:before_implement"


@pytest.mark.parametrize("role", UNCOVERED)
def test_roles_without_a_shipped_row_are_a_hard_error_naming_the_role(role):
    """Nine of thirteen. Defaulting the flags in either direction would be this runner authoring an
    authorization policy — over-tight silently fails legitimate work, over-loose silently permits
    what the skill never granted."""
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.capabilities_for(STORE, role)
    message = str(exc.value)
    assert role in message
    assert "no shipped capability row" in message
    for covered in COVERED:
        assert covered in message          # the error shows the shape of the gap, not just its edge


def test_the_covered_and_uncovered_sets_are_the_whole_role_table():
    """Pins the count: if the skill ever ships more capability rows, this fails and the gap record
    in CHG-20260822-04 gets revisited instead of quietly going stale."""
    declared = set(json.loads((STORE / "assets" / "role_refs.json").read_text(encoding="utf-8"))["roles"])
    assert declared == set(COVERED) | set(UNCOVERED)
    assert len(COVERED) == 4 and len(UNCOVERED) == 9


def test_an_undeclared_role_is_rejected_before_anything_else():
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.capabilities_for(STORE, "not-a-role")
    assert "not declared" in str(exc.value)


# --------------------------------------------------------------------------------------
# runtime selection: the elements hold everything, dispatch picks
# --------------------------------------------------------------------------------------

def test_language_is_selected_at_dispatch_not_baked_in():
    both = _render()
    english = _render(languages=["en"])
    assert len(english["sources"]) * 2 == len(both["sources"])
    assert all(".zh-tw." not in s["source_path"] for s in english["sources"])


def test_situational_flags_add_their_own_elements():
    base = _render(languages=["en"])
    with_flag = _render(languages=["en"], situational_flags=["cicd"])
    assert len(with_flag["sources"]) > len(base["sources"])
    assert any("ci-cd" in s["source_path"] for s in with_flag["sources"])


def test_an_unknown_language_is_an_error_not_an_empty_order():
    with pytest.raises(workorder.WorkOrderError) as exc:
        _render(languages=["fr"])
    assert "fr" in str(exc.value)


def test_an_unknown_situational_flag_is_an_error():
    with pytest.raises(workorder.WorkOrderError):
        _render(situational_flags=["nope"])


# --------------------------------------------------------------------------------------
# validation of the runtime inputs
# --------------------------------------------------------------------------------------

def test_a_missing_node_spec_field_is_refused_rather_than_rendered_partial():
    spec = {k: v for k, v in NODE_SPEC.items() if k != "acceptance_predicate"}
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.render(STORE, TREE, "verifier", "halt:before_implement", spec, VERDICT)
    assert "acceptance_predicate" in str(exc.value)


def test_a_malformed_verdict_is_refused():
    with pytest.raises(workorder.WorkOrderError):
        workorder.render(STORE, TREE, "verifier", "halt:before_implement", NODE_SPEC,
                         {"verdict": "auto"})


def test_an_unknown_checkpoint_is_a_hard_error_naming_it():
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.render(STORE, TREE, "verifier", "halt:no_such_gate", NODE_SPEC, VERDICT)
    assert "halt:no_such_gate" in str(exc.value)


def test_a_malformed_checkpoint_id_is_rejected():
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.render(STORE, TREE, "verifier", "before_implement", NODE_SPEC, VERDICT)
    assert "namespace" in str(exc.value)


def test_the_resolved_verdict_travels_verbatim():
    """D5 wants the verdict already resolved — the renderer must not re-derive or reinterpret it."""
    assert _render()["policy_verdict"] == VERDICT


def test_serialisation_is_deterministic_and_lf_only():
    a, b = workorder.to_json(_render()), workorder.to_json(_render())
    assert a == b
    assert "\r" not in a
    assert a.endswith("\n")
