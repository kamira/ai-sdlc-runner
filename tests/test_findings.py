"""Seats report findings as well as a verdict (CHG-20261028-01, task 1).

A finding is `{id, file, line, claim, trigger, severity, origin}`. `file` and `line` are required;
a finding with no `trigger` can never be `important`. The seat keeps its verdict, and
`policy.adjudicate` still counts it — findings are what a seat saw, not a vote.

The walks here are the wire being cut (KN-8): remove the reader from the seat block, or the
demotion from the reader, and a named test below fails.
"""
from __future__ import annotations

import pytest

from ai_sdlc_runner import engine, graph, policy, workorder
from test_flow import NOTHING_READ, SPEC, Recorder, _cfg


def finding(**kw):
    base = {"id": "F1", "file": "src/a.py", "line": "12", "claim": "drops the last row",
            "trigger": "an empty list returns None instead of []", "severity": "important",
            "origin": "introduced"}
    base.update(kw)
    return base


# ── the reader ────────────────────────────────────────────────────────────────────────────────


def test_a_finding_is_read_with_its_source_and_a_line_number():
    [one] = policy.read_findings([finding()], source="defect")
    assert one["id"] == "defect:F1" and one["source"] == "defect"
    assert one["line"] == 12 and one["severity"] == "important"


def test_absent_findings_is_none_found():
    assert policy.read_findings(None, source="defect") == []
    assert policy.read_findings([], source="defect") == []


def test_a_trigger_less_important_finding_is_never_important():
    """The named test for rule 1. Cut the demotion in `read_findings` and this fails."""
    for blank in ("", "   "):
        [one] = policy.read_findings([finding(trigger=blank)], source="defect")
        assert one["severity"] == "nit", "a finding with no trigger was accepted as important"
        assert one["severity_said"] == "important", "the demotion must leave what the seat said"


def test_a_trigger_less_nit_is_left_alone():
    [one] = policy.read_findings([finding(trigger="", severity="nit")], source="idiom")
    assert one["severity"] == "nit" and "severity_said" not in one


@pytest.mark.parametrize("key", ["file", "line"])
def test_a_finding_without_a_location_is_refused(key):
    broken = finding()
    del broken[key]
    with pytest.raises(policy.PolicyError, match="missing"):
        policy.read_findings([broken], source="defect")


@pytest.mark.parametrize("key, value", [("file", ""), ("file", "  "), ("line", ""), ("line", "0"),
                                        ("line", "-3"), ("line", "twelve"), ("line", True)])
def test_a_blank_or_unreadable_location_is_refused(key, value):
    with pytest.raises(policy.PolicyError, match="location|line"):
        policy.read_findings([finding(**{key: value})], source="defect")


def test_a_line_may_be_an_integer_or_digits():
    assert policy.read_findings([finding(line=7)], source="s")[0]["line"] == 7
    assert policy.read_findings([finding(line=" 7 ")], source="s")[0]["line"] == 7


@pytest.mark.parametrize("raw, says", [
    ("nope", "not a list"),
    (["nope"], "not an object"),
    ([finding(severity="critical")], "severity"),
    ([finding(origin="inherited")], "origin"),
    ([finding(id="  ")], "blank `id`"),
    ([finding(claim="")], "blank `claim`"),
    ([dict(finding(), extra="x")], "not part of a finding"),
    ([finding(), finding()], "appears twice"),
])
def test_what_a_finding_may_not_be(raw, says):
    with pytest.raises(policy.PolicyError, match=says):
        policy.read_findings(raw, source="defect")


def test_two_seats_numbering_from_f1_do_not_collide():
    a = policy.read_findings([finding()], source="defect")[0]["id"]
    b = policy.read_findings([finding()], source="risk")[0]["id"]
    assert a != b


# ── the schema a seat is told ─────────────────────────────────────────────────────────────────


def _asked_seat_orders(raw_by_seat):
    orders = []
    base = Recorder()

    def dispatch(order):
        orders.append(order)
        if order["node_id"] == "lead_review" and order.get("seat"):
            return {"verdict": "pass", "findings": raw_by_seat.get(order["seat"], [])}
        return base(order)
    return dispatch, orders


def test_a_seat_is_told_the_words_policy_reads():
    """The order cannot promise a word the reader refuses: the enums are `policy`'s own."""
    dispatch, orders = _asked_seat_orders({})
    engine.walk(_cfg(), dispatch, enabled=True)
    seat_order = next(o for o in orders if o["node_id"] == "lead_review" and o["seat"])
    schema = seat_order["reply"]["schema"]
    item = schema["properties"]["findings"]["items"]
    assert list(item["required"]) == list(policy.FINDING_FIELDS)
    assert item["properties"]["severity"]["enum"] == list(policy.SEVERITIES)
    assert item["properties"]["origin"]["enum"] == list(policy.ORIGINS)
    assert "findings" in schema["required"]


def test_the_closed_object_item_is_checked_like_the_rest_of_the_subset():
    good = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
            "additionalProperties": False}
    schema = dict(NOTHING_READ, properties={"xs": {"type": "array", "items": good,
                                                   "description": "d"}})
    workorder.render(graph.BY_ID["pr"], SPEC, policy.verdict("pr", "low"), answer_schema=schema)
    for broken, says in [
        (dict(good, additionalProperties=True), "allow no key"),
        (dict(good, required=["b"]), "does\\s+not all describe|does not all describe"),
        (dict(good, properties={"a": {"type": "string", "description": "d"}}), "field 'a'"),
        (dict(good, properties={"a": {"type": "array"}}), "field 'a'"),
        ({"type": "object"}, "exactly"),
    ]:
        bad = dict(NOTHING_READ, properties={"xs": {"type": "array", "items": broken,
                                                    "description": "d"}})
        with pytest.raises(workorder.WorkOrderError, match=says):
            workorder.render(graph.BY_ID["pr"], SPEC, policy.verdict("pr", "low"),
                             answer_schema=bad)


# ── the wire: the walk reads what a seat found ────────────────────────────────────────────────


def test_a_seats_findings_reach_the_report_attributed_and_lap_numbered():
    dispatch, _ = _asked_seat_orders({"defect": [finding()]})
    report = engine.walk(_cfg(), dispatch, enabled=True)
    mine = [f for f in report.findings if f["source"] == "defect"]
    assert [f["id"] for f in mine] == ["defect:F1"]
    assert mine[0]["lap"] == 1 and mine[0]["line"] == 12


def test_a_trigger_less_important_finding_is_recorded_as_a_nit_by_the_walk():
    """The wire for rule 1: a seat says `important` with no trigger and the record says `nit`."""
    dispatch, _ = _asked_seat_orders({"defect": [finding(trigger="")]})
    report = engine.walk(_cfg(), dispatch, enabled=True)
    [one] = [f for f in report.findings if f["source"] == "defect"]
    assert one["severity"] == "nit" and one["severity_said"] == "important"


def test_a_finding_with_no_location_stops_the_run_naming_the_seat():
    broken = finding()
    del broken["line"]
    dispatch, _ = _asked_seat_orders({"defect": [broken]})
    with pytest.raises(engine.EngineError, match="defect.*missing"):
        engine.walk(_cfg(), dispatch, enabled=True)


def test_the_report_emits_its_findings():
    assert "findings" in engine.RunReport().as_dict()
