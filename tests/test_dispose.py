"""`policy.dispose`: the review's decision, in code (CHG-20261028-01, task 3).

Rules 5.1 to 5.6, one test each, and the named tests that fail when 5.1 or 5.2 is cut (KN-8). The
last tests drive the engine, because a rule that `review_decide` does not call is not built.
"""
from __future__ import annotations

import pytest

from ai_sdlc_runner import engine, policy
from test_audit_nodes import Audit, FINDING, OWN, _row, _walk
from test_flow import TWO_PASSES

PASS_ALL = {"outcome": "pass", "verdicts": {"conformance": "pass", "defect": "pass", "risk": "pass"}}
FAIL_VIEW = {"outcome": "fail", "verdicts": {"conformance": "pass", "defect": "fail", "risk": "fail"}}
VETO_VIEW = {"outcome": "fail", "verdicts": {"conformance": "fail", "defect": "pass", "risk": "pass"}}


def finding(source="defect", local="F1", severity="important", origin="introduced",
            trigger="a=1 gives 2, should be 3"):
    return policy.read_findings([{
        "id": local, "file": "pkg/a.py", "line": "7", "claim": f"{source} claim", "trigger": trigger,
        "severity": severity, "origin": origin}], source=source)[0]


def row(f, disposition="confirm", **kw):
    base = {"id": f["id"], "disposition": disposition, "file": "pkg/a.py", "line": 7,
            "evidence": "read it", "input": "", "result": ""}
    base.update(kw)
    return base


# ── 5.1 every finding has exactly one disposition ───────────────────────────────────────────────


def test_rule_5_1_a_finding_with_no_disposition_is_unreached_not_refuted():
    """Cut rule 5.1 (the id check in `dispose`) and a dropped finding reads as a quiet `pass`."""
    f = finding()
    with pytest.raises(policy.PolicyError, match=r"unreached.*no disposition for \['defect:F1'\]"):
        policy.dispose([f], [], PASS_ALL)


def test_rule_5_1_a_duplicate_row_is_unreached():
    f = finding()
    with pytest.raises(policy.PolicyError, match=r"more than one disposition for \['defect:F1'\]"):
        policy.dispose([f], [row(f), row(f, "refute", input="x", result="y")], PASS_ALL)


def test_rule_5_1_a_row_for_an_id_nobody_raised_is_unreached():
    f = finding()
    with pytest.raises(policy.PolicyError, match=r"\['defect:nope'\], which nobody raised"):
        policy.dispose([f], [row(f), dict(row(f), id="defect:nope")], PASS_ALL)


def test_rule_5_1_a_row_with_no_findings_at_all_is_unreached():
    with pytest.raises(policy.PolicyError, match="which nobody raised"):
        policy.dispose([], [{"id": "x:1", "disposition": "confirm", "file": "a", "line": 1,
                             "evidence": "", "input": "", "result": ""}], PASS_ALL)


def test_rule_5_1_no_findings_and_no_rows_is_complete():
    assert policy.dispose([], [], PASS_ALL)["outcome"] == "pass"


def test_rule_5_1_stops_the_run_with_the_ids_named_in_the_engine():
    """Wired: `review_decide` turns the refusal into an `EngineError`, the way a seat that names no
    verdict is. Cut the call to `policy.dispose` in `_decide_review` and this passes silently."""
    dispatch = Audit(seat_findings={"defect": [FINDING]}, auditor_findings=[OWN],
                     dispositions=[_row("defect:F1")])
    with pytest.raises(engine.EngineError, match=r"review_decide.*no disposition for \['auditor:A1'\]"):
        _walk(dispatch)


# ── 5.2 the veto cannot be refuted away ─────────────────────────────────────────────────────────


def test_rule_5_2_a_refuted_conformance_fail_is_undecided_never_pass():
    """Cut rule 5.2 and the audit result (`pass`, nothing confirmed) is compared with a failing
    panel by 5.6 -- which still says `undecided`. The case that separates them is the next one."""
    f = finding("conformance")
    out = policy.dispose([f], [row(f, "refute", input="a", result="b")], VETO_VIEW)
    assert out["outcome"] == "undecided"
    assert "a veto is not audited away" in out["reason"]


def test_rule_5_2_holds_even_when_another_seat_has_a_confirmed_finding():
    """The named test for 5.2 (KN-8). Without the rule the audit result is `fail`, it agrees with the
    failing panel, and the run goes back for rework on a defect finding while the conformance seat's
    veto was refuted by nobody who showed a reason -- the veto audited away."""
    veto = finding("conformance")
    other = finding("defect", severity="important")
    out = policy.dispose([veto, other],
                         [row(veto, "refute", input="a", result="b"), row(other, "confirm")],
                         {"outcome": "fail", "verdicts": {"conformance": "fail", "defect": "fail",
                                                          "risk": "pass"}})
    assert out["outcome"] == "undecided" and out["audit_result"] is None


def test_rule_5_2_a_veto_with_a_finding_left_standing_is_not_refuted():
    a, b = finding("conformance", "F1"), finding("conformance", "F2")
    out = policy.dispose([a, b], [row(a, "refute", input="x", result="y"), row(b, "confirm")],
                         VETO_VIEW)
    assert out["outcome"] == "fail" and [c["id"] for c in out["confirmed"]] == ["conformance:F2"]


def test_rule_5_2_a_refute_that_shows_no_work_is_not_a_refutation():
    """`read_dispositions` reads it as `cannot-verify`, so the veto stands."""
    f = finding("conformance")
    rows = policy.read_dispositions([{"id": f["id"], "disposition": "refute", "file": "a",
                                      "line": "1", "evidence": "", "input": "", "result": ""}])
    out = policy.dispose([f], rows, VETO_VIEW)
    assert out["outcome"] == "undecided"           # 5.6: the audit found nothing, the panel failed
    assert "veto is not audited away" not in out["reason"]


def test_rule_5_2_does_not_fire_for_a_veto_that_passed():
    f = finding("conformance")
    out = policy.dispose([f], [row(f, "refute", input="a", result="b")], PASS_ALL)
    assert out["outcome"] == "pass"


def test_rule_5_2_in_the_engine_a_refuted_veto_suspends_the_run_for_a_person():
    seats = {"conformance": [dict(FINDING, id="C1")], "defect": [dict(FINDING, id="D1")]}
    dispatch = Audit(seat_findings=seats,
                     verdicts={"conformance": "fail", "defect": "fail"},
                     dispositions=lambda found: [
                         _row(f["id"], "refute", input="a", result="b") if f["source"] ==
                         "conformance" else _row(f["id"], "confirm") for f in found])
    report = _walk(dispatch)
    assert report.state == engine.SUSPENDED and report.halted_at == "review_decide"
    assert "a veto is not audited away" in report.halt_reason
    assert "qa_verify" not in report.visited and "review_failed" not in report.visited


# ── 5.3 confirmed important + introduced findings fail the review ───────────────────────────────


def test_rule_5_3_a_confirmed_important_introduced_finding_fails_the_review():
    f = finding("defect")
    out = policy.dispose([f], [row(f)], FAIL_VIEW)
    assert out["outcome"] == "fail"
    [kept] = out["confirmed"]
    assert (kept["id"], kept["claim"], kept["trigger"], kept["source"]) == (
        "defect:F1", "defect claim", "a=1 gives 2, should be 3", "defect")
    assert kept["evidence"] == "read it" and kept["evidence_file"] == "pkg/a.py"


def test_rule_5_3_needs_both_important_and_introduced():
    nit = finding("defect", "N", severity="nit")
    old = finding("defect", "O", origin="pre-existing")
    out = policy.dispose([nit, old], [row(nit), row(old)], PASS_ALL)
    assert out["outcome"] == "pass" and out["confirmed"] == []


# ── 5.4 the auditor's own findings count directly ───────────────────────────────────────────────


def test_rule_5_4_the_auditors_own_triggered_important_finding_counts_without_a_second_voice():
    own = finding(policy.AUDITOR_SOURCE, "A1")
    out = policy.dispose([own], [row(own, "cannot-verify")], FAIL_VIEW)
    assert out["outcome"] == "fail" and out["confirmed"][0]["why"] == "raised by the auditor itself"


def test_rule_5_4_without_a_trigger_it_is_recorded_and_does_not_fail_the_change():
    own = finding(policy.AUDITOR_SOURCE, "A1", trigger="")          # demoted to a nit by the reader
    assert own["severity"] == "nit"
    out = policy.dispose([own], [row(own)], PASS_ALL)
    assert out["outcome"] == "pass" and out["kept"][0]["why"] == "nit"


def test_rule_5_4_does_not_extend_to_a_seats_finding():
    seat = finding("defect")
    out = policy.dispose([seat], [row(seat, "cannot-verify")], PASS_ALL)
    assert out["outcome"] == "pass" and out["confirmed"] == []


# ── 5.5 what does not fail the change is still kept ─────────────────────────────────────────────


@pytest.mark.parametrize("make, disposition, why", [
    (lambda: finding("defect"), "refute", "refuted"),
    (lambda: finding("defect"), "cannot-verify", "cannot-verify"),
    (lambda: finding("defect", severity="nit"), "confirm", "nit"),
    (lambda: finding("defect", origin="pre-existing"), "confirm", "pre-existing"),
])
def test_rule_5_5_each_kind_is_kept_with_its_reason_and_fails_nothing(make, disposition, why):
    f = make()
    extra = {"input": "a", "result": "b"} if disposition == "refute" else {}
    out = policy.dispose([f], [row(f, disposition, **extra)], PASS_ALL)
    assert out["outcome"] == "pass" and out["confirmed"] == []
    assert [(k["id"], k["why"]) for k in out["kept"]] == [(f["id"], why)]


def test_rule_5_5_in_the_engine_the_kept_findings_reach_the_record_and_not_the_rework():
    seats = {"defect": [FINDING, dict(FINDING, id="F2", severity="nit")]}
    dispatch = Audit(seat_findings=seats, verdicts={"defect": "fail", "risk": "fail"},
                     dispositions=lambda found: [_row(f["id"], "confirm") for f in found])
    report = _walk(dispatch, decisions=dict(TWO_PASSES))
    first = [a for a in report.adjudications if a["node_id"] == "review_decide"][0]
    assert [c["id"] for c in first["confirmed"]] == ["defect:F1"]
    assert [(k["id"], k["why"]) for k in first["kept"]] == [("defect:F2", "nit")]
    assert {f["id"] for f in report.findings} >= {"defect:F1", "defect:F2"}, "all of it is recorded"


# ── 5.6 the panel's view and the audit disagree ─────────────────────────────────────────────────


def test_rule_5_6_seats_that_fail_with_every_finding_refuted_are_undecided():
    f = finding("defect")
    out = policy.dispose([f], [row(f, "refute", input="a", result="b")], FAIL_VIEW)
    assert out["outcome"] == "undecided"
    assert (out["panel_view"], out["audit_result"]) == ("fail", "pass")
    assert "nothing is waived" in out["reason"]


def test_rule_5_6_seats_that_pass_beside_a_confirmed_finding_are_undecided():
    f = finding(policy.AUDITOR_SOURCE, "A1")
    out = policy.dispose([f], [row(f)], PASS_ALL)
    assert out["outcome"] == "undecided" and (out["panel_view"], out["audit_result"]) == (
        "pass", "fail")


def test_rule_5_6_seats_that_fail_with_no_finding_behind_them_are_undecided():
    assert policy.dispose([], [], FAIL_VIEW)["outcome"] == "undecided"


def test_rule_5_6_a_tied_panel_stays_undecided():
    tie = {"outcome": "undecided", "verdicts": {"conformance": "pass", "defect": "fail"}}
    assert policy.dispose([], [], tie)["outcome"] == "undecided"


def test_rule_5_6_when_they_agree_the_outcome_is_theirs():
    f = finding("defect")
    assert policy.dispose([f], [row(f)], FAIL_VIEW)["outcome"] == "fail"
    assert policy.dispose([], [], PASS_ALL)["outcome"] == "pass"


def test_an_unknown_panel_view_is_refused():
    with pytest.raises(policy.PolicyError, match="panel's view"):
        policy.dispose([], [], {"outcome": "maybe", "verdicts": {}})


# ── the engine routes on it ─────────────────────────────────────────────────────────────────────


def test_a_confirmed_finding_beside_failing_seats_sends_the_change_back():
    seats = {"defect": [FINDING]}
    dispatch = Audit(seat_findings=seats, verdicts={"defect": "fail", "risk": "fail"})
    report = _walk(dispatch, decisions=dict(TWO_PASSES))
    assert "review_failed" in report.visited
    assert [a["outcome"] for a in report.adjudications if a["node_id"] == "review_decide"][0] == \
        "fail"


def test_review_decide_routes_on_dispose_and_not_on_the_panels_view():
    """Cut `policy.dispose` out of `_decide_review` (return the panel's view) and seats that fail
    with nothing behind them go back for rework instead of to a person."""
    report = _walk(Audit(verdicts={"defect": "fail", "risk": "fail"}))
    assert report.state == engine.SUSPENDED and report.halted_at == "review_decide"
    assert "nothing is waived" in report.halt_reason
    assert "review_failed" not in report.visited


def test_a_person_can_rule_on_the_undecided_review_and_both_views_are_in_the_record():
    report = _walk(Audit(verdicts={"defect": "fail", "risk": "fail"}),
                   rulings=[engine.Ruling(node_id="review_decide", branch="pass")])
    assert report.rulings and "qa_verify" in report.visited
    decided = [a for a in report.adjudications if a["node_id"] == "review_decide"][0]
    assert (decided["panel_view"], decided["audit_result"]) == ("fail", "pass")
