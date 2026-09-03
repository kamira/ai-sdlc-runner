"""The closed-schema renderer, pinned deliberately rather than incidentally (CHG-20260828-23).

`workorder.py` had no test file of its own. Its guarantees were asserted by tests written about
other things — `test_flow`, `test_plan`, `test_schemas` — and no mutation named any of them.

Measured before writing this, one mutation at a time against those files: **seven of nine
guarantees were already pinned.** No mutation coverage did *not* mean no coverage, which is worth
saying because the opposite is the easy assumption.

Two were not, and this file is mostly about those two:

* the **rendered order** is never compared against the closed schema — the source marks that guard
  `# pragma: no cover - structural guard`, which is an admission in the code itself;
* `to_json` promises *"sorted keys, LF, UTF-8"* and nothing checked the sorted part.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_sdlc_runner import graph, policy, workorder  # noqa: E402

#: One node spec that says something in every field that must.
SPEC = {
    "scope": "src/ai_sdlc_runner/",
    "objective": "build the module",
    "instructions": "do the thing described in the plan",
    "done_criteria": "the tests pass",
    "acceptance_predicate": "pytest exits 0",
    "input_artifacts": [],
    "expected_outputs": [],
    "idempotence_probes": [],
    "workdir": ".",
}

NODE = graph.BY_ID["engineer_build"]
VERDICT = policy.verdict("self_verify", "low")


def _spec(**over):
    return {**SPEC, **over}


# ── the schema is closed on the way in ─────────────────────────────────────────────────────────


def test_an_order_renders_from_a_complete_spec():
    order = workorder.render(NODE, SPEC, VERDICT)
    assert order["node_id"] == "engineer_build"


def test_a_field_outside_the_contract_is_refused():
    """The reason the schema is closed: a harness-specific field must not ride in through a caller.

    If a runner could add `"model_hint"` here, every consumer of an order would have to know which
    harness produced it, and the order would stop being the whole of what was asked.
    """
    with pytest.raises(workorder.WorkOrderError) as caught:
        workorder.render(NODE, _spec(harness_hint="use the fast model"), VERDICT)
    assert "outside the contract" in str(caught.value)


def test_a_partial_spec_is_refused_rather_than_filled_in():
    missing = {k: v for k, v in SPEC.items() if k != "objective"}
    with pytest.raises(workorder.WorkOrderError) as caught:
        workorder.render(NODE, missing, VERDICT)
    assert "missing required field" in str(caught.value)


def test_the_verdict_is_closed_too():
    with pytest.raises(workorder.WorkOrderError):
        workorder.render(NODE, SPEC, {**VERDICT, "relaxed": True})


# ── present is not the same as says something ──────────────────────────────────────────────────


def test_a_blank_field_is_refused_even_though_the_key_exists():
    """CHG-20260823-34's defect: `_check` tested `f not in supplied`, so `""` passed.

    Measured at the time: a plan with blank `scope` and `objective` ran the whole flow, 25 asks,
    exit 0, refused by nothing. A name standing in for a constraint, in the work-order builder.
    """
    with pytest.raises(workorder.WorkOrderError) as caught:
        workorder.render(NODE, _spec(scope=""), VERDICT)
    assert "says nothing" in str(caught.value)


def test_whitespace_is_blank():
    """The same defect one character deeper."""
    with pytest.raises(workorder.WorkOrderError):
        workorder.render(NODE, _spec(objective="   "), VERDICT)


def test_a_list_holding_only_blanks_is_blank():
    """`["", " "]` is a list that exists and constrains nothing."""
    assert workorder._blank(["", "  "])
    assert not workorder._blank(["a real one"])


def test_the_three_that_may_be_empty_stay_empty():
    """A blanket rule would refuse this repository's own example.

    `expected_outputs` is `[]` on fourteen of the fifteen nodes in `examples/minimal/plan.json` — review and
    gate nodes genuinely produce nothing — and a refusal that scolded there would invite padding
    `idempotence_probes` with a fake probe, manufacturing the defect the rule exists to stop.
    """
    order = workorder.render(NODE, _spec(input_artifacts=[], expected_outputs=[],
                                         idempotence_probes=[]), VERDICT)
    assert order["expected_outputs"] == []


def test_the_blank_rule_has_one_definition_shared_with_the_plan_loader():
    """`plan.py` raises `PlanError` and `render` raises `WorkOrderError` off **one** rule.

    Two copies drifting apart would give a plan that loads and will not dispatch.

    The first version of this asserted only that `content_problem` reports a blank field, and never
    imported `plan` at all — so the shared half, which is the whole claim in the name, was asserted
    by nothing. The review panel found it: a private copy in `plan.py` would have left it green
    (CHG-20260830-05). Both refusals are now driven, and compared.
    """
    from ai_sdlc_runner import plan as plan_mod

    blank = _spec(done_criteria="")

    with pytest.raises(workorder.WorkOrderError) as from_render:
        workorder.render(NODE, blank, VERDICT)
    with pytest.raises(plan_mod.PlanError) as from_plan:
        plan_mod.check({"risk": "low", "node_specs": {NODE.id: dict(blank)}})

    # Same rule, so the same sentence — the two differ only in the `where` each passes in.
    assert "done_criteria" in str(from_render.value)
    assert "done_criteria" in str(from_plan.value)
    assert "says nothing" in str(from_plan.value), (
        "the plan loader refused for some other reason; it is not going through content_problem")


# ── the seat shapes the instructions and nothing else ──────────────────────────────────────────


def test_an_unknown_seat_is_refused_by_name():
    with pytest.raises(workorder.WorkOrderError) as caught:
        workorder.render(NODE, SPEC, VERDICT, seat="not-a-seat")
    assert "no seat" in str(caught.value)
    assert sorted(policy.BY_SEAT)[0] in str(caught.value), "it must say what the seats are"


def test_two_seats_differ_in_their_instructions_and_in_nothing_else():
    """What makes several seats a cross-check rather than one opinion asked repeatedly."""
    names = sorted(policy.BY_SEAT)[:2]
    first = workorder.render(NODE, SPEC, VERDICT, seat=names[0])
    second = workorder.render(NODE, SPEC, VERDICT, seat=names[1])

    differ = {k for k in first if first[k] != second[k]}
    assert differ == {"instructions", "seat"}, f"seats differ in {differ}"


def test_a_seat_is_told_it_will_not_see_the_others():
    order = workorder.render(NODE, SPEC, VERDICT, seat=sorted(policy.BY_SEAT)[0])
    assert "will not see the other seats" in order["instructions"]


# ── every order carries every halt ─────────────────────────────────────────────────────────────


def test_the_permanent_halts_are_carried_in_full():
    """Never filtered to "the ones this node could hit".

    Filtering needs a judgement about what the work might touch, and every omission is a gate
    quietly disarmed.
    """
    order = workorder.render(NODE, SPEC, VERDICT)
    assert list(order["permanent_halts"]) == list(policy.PERMANENT_HALTS)
    assert order["permanent_halts"], "an order carrying no halts arms nothing"


# ── the two guarantees nothing pinned ──────────────────────────────────────────────────────────


def test_the_rendered_order_matches_the_closed_schema_exactly():
    """The structural guard the source marks `# pragma: no cover`, which is an admission.

    Nothing exercised it: removing the check entirely left the whole suite green. It is the only
    thing standing between a future edit to `render` and an order whose shape no longer matches the
    contract every consumer reads it by.
    """
    order = workorder.render(NODE, SPEC, VERDICT)
    assert tuple(sorted(order)) == tuple(sorted(workorder.WORK_ORDER_FIELDS))


def test_an_order_missing_a_contract_field_is_refused_rather_than_dispatched(monkeypatch):
    """And the guard is driven, not merely asserted around.

    A test that only checks a correct order's shape passes whether or not the guard exists. This
    one makes `render` produce a wrong order and requires it to refuse.
    """
    monkeypatch.setattr(workorder, "WORK_ORDER_FIELDS",
                        workorder.WORK_ORDER_FIELDS + ("a_field_render_does_not_produce",))
    with pytest.raises(workorder.WorkOrderError) as caught:
        workorder.render(NODE, SPEC, VERDICT)
    assert "closed schema" in str(caught.value)


def test_the_json_is_serialised_with_sorted_keys():
    """`to_json` promises *"sorted keys, LF, UTF-8"* and nothing checked the sorted part.

    It is the byte stream a dispatched agent reads. Two runs of the same order producing different
    bytes would make the record of what was asked depend on dict insertion order — and
    CHG-20260828-16 has just made the encoding of exactly these bytes something that matters.
    """
    order = workorder.render(NODE, SPEC, VERDICT)
    text = workorder.to_json(order)
    keys = [line.split('"')[1] for line in text.splitlines() if line.startswith('  "')]
    assert keys == sorted(keys), "the order's keys reached the agent unsorted"


def test_the_json_ends_with_one_newline_and_is_utf8_clean():
    text = workorder.to_json(workorder.render(NODE, SPEC, VERDICT))
    assert text.endswith("\n") and not text.endswith("\n\n")
    text.encode("utf-8")


def test_the_json_round_trips():
    order = workorder.render(NODE, SPEC, VERDICT)
    assert json.loads(workorder.to_json(order)) == order
