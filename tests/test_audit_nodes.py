"""The audit stage that follows the seats: `audit_read`, `audit_dispose`, `review_decide` (CHG-20261028-01, task 2).

`lead_review` keeps its seats and its verdicts, records the panel's view, and leads into the audit.
The `lead_review` gate stands at `review_decide`, after the work, unchanged. The tally is the
runner's and nobody is asked there.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sdlc_runner import engine, graph, policy
from test_flow import ALL_GATES, THROUGH, TWO_PASSES, _answer, _cfg

FINDING = {"id": "F1", "file": "pkg/a.py", "line": "7", "claim": "SEAT-CLAIM-XYZ",
           "trigger": "a=1 gives 2, should be 3", "severity": "important", "origin": "introduced"}
OWN = {"id": "A1", "file": "pkg/b.py", "line": "3", "claim": "AUDITOR-CLAIM-QQQ",
       "trigger": "b=0 raises", "severity": "important", "origin": "introduced"}


class Audit:
    """A dispatcher for the whole flow with a say in what the seats and the auditor answer."""

    def __init__(self, seat_findings=None, auditor_findings=None, dispositions=None,
                 verdicts=None):
        self.orders = []
        self.seat_findings = seat_findings or {}
        self.auditor_findings = auditor_findings or []
        self.dispositions = dispositions
        self.verdicts = verdicts or {}
        self.file_seen = None
        self.file_name = None

    def __call__(self, order):
        self.orders.append(order)
        node = order["node_id"]
        if order.get("seat"):
            if node == "intake_review":
                return {"problems": [], "missing": [], "unsafe": []}
            return {"verdict": self.verdicts.get(order["seat"], "pass"),
                    "findings": self.seat_findings.get(order["seat"], [])}
        if node == "audit_read":
            return {"findings": self.auditor_findings}
        if node == "audit_dispose":
            named = Path(order["input_artifacts"][0])
            found = json.loads(named.read_text("utf-8"))["findings"]
            self.file_seen, self.file_name = found, named.name
            if callable(self.dispositions):
                return {"dispositions": self.dispositions(found)}
            return {"dispositions": self.dispositions if self.dispositions is not None else [
                _row(f["id"], "confirm") for f in found]}
        return _answer(order)

    def of(self, node_id):
        return [o for o in self.orders if o["node_id"] == node_id]


def _row(finding_id, disposition="confirm", **kw):
    row = {"id": finding_id, "disposition": disposition, "file": "pkg/a.py", "line": "7",
           "evidence": "read it", "input": "", "result": ""}
    row.update(kw)
    return row


def _walk(dispatch, **kw):
    kw.setdefault("review_seats", 3)
    return engine.walk(_cfg(confirmed=THROUGH, **kw), dispatch, enabled=True)


# ── the graph ─────────────────────────────────────────────────────────────────────────────────


def test_the_graph_with_the_audit_stage_validates():
    graph.validate()
    for node_id in ("audit_read", "audit_dispose", "review_decide"):
        assert node_id in graph.BY_ID


def test_the_auditor_has_the_seats_flags():
    role = policy.BY_ROLE["auditor"]
    assert (role.can_spawn, role.can_write, role.can_execute) == (False, False, True)


def test_lead_review_leads_into_the_audit_and_routes_nothing():
    lead = graph.BY_ID["lead_review"]
    assert (lead.kind, lead.mode, lead.role) == (graph.STEP, graph.SEAT_PANEL, "seat")
    assert lead.next == "audit_read" and lead.branches == {} and lead.gate is None
    assert graph.BY_ID["audit_read"].next == "audit_dispose"
    assert graph.BY_ID["audit_dispose"].next == "review_decide"
    for node_id in ("audit_read", "audit_dispose"):
        node = graph.BY_ID[node_id]
        assert (node.role, node.mode) == ("auditor", graph.SINGLE)
    assert graph.BY_ID["audit_read"].audit == graph.AUDIT_READ
    assert graph.BY_ID["audit_dispose"].audit == graph.AUDIT_DISPOSE


def test_review_decide_is_the_runners_and_carries_the_gate_lead_review_had():
    node = graph.BY_ID["review_decide"]
    assert (node.kind, node.mode, node.role) == (graph.DECISION, graph.RUNNER, None)
    assert (node.gate, node.gate_when, node.rejects_to) == ("lead_review", "after", "review_failed")
    assert node.branches == {"pass": "qa_verify", "fail": "review_failed"}
    assert node.audit == graph.AUDIT_DECIDE
    assert policy.GATES["lead_review"] == {"low": policy.AUTO, "medium": policy.AUTO,
                                           "high": policy.HALT}


def test_the_lead_review_gate_is_consulted_at_review_decide_and_nowhere_else():
    assert [n.id for n in graph.NODES if n.gate == "lead_review"] == ["review_decide"]
    # Driven: a high-risk run with every other gate confirmed stops at the node that carries it,
    # after the seats and the auditor have been asked, and not at any of the three before it.
    gates = tuple(g for g in ALL_GATES if g != "lead_review")
    dispatch = Audit()
    report = engine.walk(_cfg(risk="high", confirmed=gates, review_seats=3), dispatch,
                         enabled=True)
    assert report.halted_at == "review_decide"
    assert "lead_review" in report.halt_reason
    assert [n for n in report.visited if n in ("lead_review", "audit_read", "audit_dispose")] == \
        ["lead_review", "audit_read", "audit_dispose"]
    assert dispatch.of("audit_read"), "the work was done before the gate stopped (`after`)"
    assert report.verdicts["review_decide"]["gate"] == "lead_review"


def test_a_confirmed_lead_review_gate_lets_the_review_through_to_qa():
    report = engine.walk(_cfg(risk="high", confirmed=ALL_GATES, review_seats=3), Audit(),
                         enabled=True)
    assert "qa_verify" in report.visited
    assert report.visited.index("review_decide") < report.visited.index("qa_verify")


# ── who is asked ──────────────────────────────────────────────────────────────────────────────


def test_review_decide_asks_nobody():
    dispatch = Audit()
    report = _walk(dispatch)
    assert "review_decide" in report.visited
    assert dispatch.of("review_decide") == []
    assert not [a for a in report.asks if a.node_id == "review_decide"]


def test_the_seats_are_still_asked_and_their_view_is_recorded_not_routed():
    seats = {"defect": [dict(FINDING, id="D1")], "risk": [dict(FINDING, id="R1")]}
    report = _walk(Audit(seat_findings=seats, verdicts={"defect": "fail", "risk": "fail"}),
                   decisions=dict(TWO_PASSES))
    view = [a for a in report.adjudications if a["node_id"] == "lead_review"][0]
    assert view["outcome"] != "pass" and view["verdicts"]["defect"] == "fail"
    decided = [a for a in report.adjudications if a["node_id"] == "review_decide"]
    assert decided and decided[0]["panel_view"] == view["outcome"]
    # Nothing was sent back from the seats' node; the decision did it.
    assert {s["node_id"] for s in report.send_backs} == {"review_decide"}


def test_the_auditor_reads_blind_and_the_seats_findings_never_reach_it():
    dispatch = Audit(seat_findings={"defect": [FINDING]})
    report = _walk(dispatch)
    [order] = dispatch.of("audit_read")
    assert "SEAT-CLAIM-XYZ" not in json.dumps(order), "a reader handed a list reads the list"
    assert order["role"] == "auditor" and order["seat"] is None
    assert order["capabilities"] == policy.capabilities("auditor")
    assert Path(order["input_artifacts"][0]).name == "scope.json"
    assert report.audit_scope and report.audit_scope["cap"] > 0


def test_the_auditor_disposes_in_a_second_session_from_one_file_by_path():
    dispatch = Audit(seat_findings={"defect": [FINDING]}, auditor_findings=[OWN])
    report = _walk(dispatch)
    [read] = dispatch.of("audit_read")
    [dispose] = dispatch.of("audit_dispose")
    assert dispose is not read
    ids = [a.node_id for a in report.asks if a.node_id in ("audit_read", "audit_dispose")]
    assert ids == ["audit_read", "audit_dispose"], "two asks, two sessions (FR-3, FR-6)"
    assert dispatch.file_name == "findings.json", "the file was there to be read, by its path"
    assert {f["id"] for f in dispatch.file_seen} == {"defect:F1", "auditor:A1"}
    assert {f["source"] for f in dispatch.file_seen} == {"defect", "auditor"}
    for f in dispatch.file_seen:
        assert f["file"] and isinstance(f["line"], int) and f["trigger"]


def test_with_no_findings_there_is_nothing_to_dispose_of_and_no_session_is_spent():
    dispatch = Audit()
    report = _walk(dispatch)
    assert dispatch.of("audit_read") and dispatch.of("audit_dispose") == []
    assert "audit_dispose" in report.visited
    assert report.dispositions == []


def test_what_the_auditor_said_about_each_finding_is_recorded_per_lap():
    rows = lambda found: [_row(found[0]["id"], "confirm"),                     # noqa: E731
                          _row(found[1]["id"], "refute", input="b=0", result="returns 0")]
    dispatch = Audit(seat_findings={"defect": [FINDING]}, auditor_findings=[OWN],
                     dispositions=rows)
    report = _walk(dispatch)
    got = {d["id"]: d for d in report.dispositions}
    assert got["defect:F1"]["disposition"] == "confirm" and got["defect:F1"]["lap"] == 1
    assert got["auditor:A1"]["disposition"] == "refute"
    assert report.as_dict()["dispositions"] == report.dispositions


def test_the_findings_the_walk_gathers_include_the_auditors_own():
    report = _walk(Audit(seat_findings={"defect": [FINDING]}, auditor_findings=[OWN]))
    assert {f["id"] for f in report.findings} == {"defect:F1", "auditor:A1"}


# ── the replies ───────────────────────────────────────────────────────────────────────────────


def test_each_auditor_node_asks_for_what_its_reader_reads():
    dispatch = Audit(seat_findings={"defect": [FINDING]})
    _walk(dispatch)
    read = dispatch.of("audit_read")[0]["reply"]["schema"]
    dispose = dispatch.of("audit_dispose")[0]["reply"]["schema"]
    assert "findings" in read["required"] and "verdict" not in read["properties"]
    assert "dispositions" in dispose["required"] and "verdict" not in dispose["properties"]
    row = dispose["properties"]["dispositions"]["items"]
    assert row["properties"]["disposition"]["enum"] == list(policy.DISPOSITIONS)
    assert sorted(row["required"]) == sorted(policy.DISPOSITION_FIELDS)


def test_a_refute_that_does_not_show_its_work_reads_as_cannot_verify():
    rows = policy.read_dispositions([_row("x:1", "refute", input="a", result="")])
    assert rows[0]["disposition"] == "cannot-verify" and rows[0]["disposition_said"] == "refute"
    rows = policy.read_dispositions([_row("x:1", "refute", input="a", result="b")])
    assert rows[0]["disposition"] == "refute" and "disposition_said" not in rows[0]


@pytest.mark.parametrize("broken, says", [
    ({"file": ""}, "file"), ({"line": "0"}, "line"), ({"line": "x"}, "line"),
    ({"disposition": "maybe"}, "maybe"), ({"id": " "}, "id")])
def test_a_disposition_without_its_location_or_word_is_refused(broken, says):
    with pytest.raises(policy.PolicyError, match=says):
        policy.read_dispositions([_row("x:1", **broken)])


def test_an_unreadable_disposition_stops_the_run_by_name():
    dispatch = Audit(seat_findings={"defect": [FINDING]},
                     dispositions=[_row("defect:defect:F1", file="")])
    with pytest.raises(engine.EngineError, match="file"):
        _walk(dispatch)


# ── the cut wire ──────────────────────────────────────────────────────────────────────────────


def test_a_walk_whose_graph_lacks_the_audit_still_reaches_qa_through_the_decision():
    """The routing is the decision's: cut `review_decide`'s branch lookup and the run dies here."""
    report = _walk(Audit())
    assert report.visited[report.visited.index("lead_review"):][:5] == [
        "lead_review", "audit_read", "audit_dispose", "review_decide", "qa_verify"]


# ── validate() holds the audit stage to its shape ──────────────────────────────────────────────


def _refused(monkeypatch, node_id, match, **changes):
    """Rebuild the graph with one node changed, in memory, and require `validate` to refuse it.

    Done here and not through `_graph_swap`: that helper's caller count is stated in three places
    and pinned (`test_the_number_of_callers_the_swap_states_is_the_real_one`), and a test file
    that only needs a monkeypatch should not move it.
    """
    import dataclasses
    nodes = tuple(dataclasses.replace(n, **changes) if n.id == node_id else n
                  for n in graph.NODES)
    monkeypatch.setattr(graph, "NODES", nodes)
    monkeypatch.setattr(graph, "BY_ID", {n.id: n for n in nodes})
    with pytest.raises(graph.GraphError, match=match):
        graph.validate()


def test_an_unknown_audit_step_is_refused(monkeypatch):
    _refused(monkeypatch, "audit_read", "audit step 'peek'", audit="peek")


def test_the_auditor_is_asked_only_at_a_node_that_names_its_step(monkeypatch):
    _refused(monkeypatch, "audit_read", "names no audit step", audit=None)


def test_the_decision_is_the_runners_and_no_models(monkeypatch):
    _refused(monkeypatch, "audit_dispose", "the decision is the runner's",
             audit=graph.AUDIT_DECIDE)


def test_a_model_node_cannot_be_the_decision(monkeypatch):
    _refused(monkeypatch, "review_decide", "the decision is the runner's", audit=graph.AUDIT_READ)


def test_a_decision_that_cannot_route_pass_and_fail_is_refused(monkeypatch):
    _refused(monkeypatch, "review_decide", "'pass' and 'fail' branches",
             branches={"yes": "qa_verify", "no": "review_failed"}, rejects_to=None, gate=None,
             gate_when=None)


def test_an_audit_read_that_is_not_one_auditor_session_is_refused(monkeypatch):
    _refused(monkeypatch, "audit_read", "one auditor session", mode=graph.MODEL_PANEL)


# ── a refused answer is refused at its own ask ─────────────────────────────────────────────────


@pytest.mark.parametrize("node_id, answer", [
    ("audit_read", {"findings": [dict(OWN, file="")]}),
    ("audit_dispose", {"dispositions": [_row("defect:F1", line="0")]}),
])
def test_an_unreadable_auditor_answer_is_journaled_refused_so_a_resume_asks_again(
        tmp_path, node_id, answer):
    """Cut `_accept_for`'s auditor readers and the answer is journaled `answered`, then replayed and
    refused again on every resume."""
    class Bad(Audit):
        def __call__(self, order):
            if order["node_id"] == node_id:
                self.orders.append(order)
                return answer
            return super().__call__(order)

    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(engine.EngineError):
        _walk(Bad(seat_findings={"defect": [FINDING]}), journal=journal)
    status = {e["node_id"]: e["status"] for e in journal.entries()}
    assert status[node_id] == "refused"


# ── the scope is the runner's, recorded, and the base survives a resume ───────────────────────


def _scope(cut=()):
    return {"root": "/repo", "base": None, "cap": 10, "total_chars": 30, "read_chars": 5,
            "files": [{"path": "a.py", "why": "diff", "chars": 5, "state": "read"}]
                     + [{"path": c, "why": "caller", "chars": 25, "state": "cut"} for c in cut],
            "cut": list(cut), "notes": []}


def test_the_scope_is_assembled_by_the_runner_recorded_and_handed_over_by_path(monkeypatch):
    """Cut the call to `auditscope.assemble` in `_audit_read_brief` and no scope reaches the order."""
    seen = []

    def assemble(workdir, base):
        seen.append((workdir, base))
        return _scope(cut=["big.py"])

    monkeypatch.setattr(engine.auditscope, "assemble", assemble)
    dispatch = Audit()
    report = _walk(dispatch)
    assert seen and seen[0][0] == "."
    assert report.audit_scope["cut"] == ["big.py"]
    [order] = dispatch.of("audit_read")
    assert Path(order["input_artifacts"][0]).name == "scope.json"
    assert order["input_artifacts"][1] == str(Path("/repo") / "a.py"), "only what fit is listed"
    assert "big.py" in order["instructions"], "what was cut is said, so it is not mistaken for read"


def test_the_commit_the_change_is_measured_from_is_taken_at_the_first_build_and_remembered(
        tmp_path, monkeypatch):
    bases = iter(["first", "second"])
    monkeypatch.setattr(engine.auditscope, "capture_base", lambda workdir: next(bases))
    got = []
    monkeypatch.setattr(engine.auditscope, "assemble",
                        lambda workdir, base: got.append(base) or _scope())
    journal = engine.AskJournal(tmp_path / "asks")
    _walk(Audit(), journal=journal)
    _walk(Audit(), journal=journal, resume=True)
    assert got == ["first", "first"], "a resume does not move the line the diff is measured from"
    assert (tmp_path / "asks" / "audit" / "base.json").is_file()
