"""The default panel is the necessary seats, and the floor counts the auditor (CHG-20261028-01, 1a).

`SEAT_DEFAULT = 2` opens `conformance` and `defect`. `SEAT_FLOOR = 3` stays, and now counts the seats
plus the auditor, the auditor counting only when its backend differs from the builder's and from
every open seat's. Below the floor still needs high-risk mode, exactly as before.
"""
from __future__ import annotations

import json

import pytest

from ai_sdlc_runner import cli, engine, graph, policy
from test_flow import Recorder, _cfg


# ── the policy ────────────────────────────────────────────────────────────────────────────────


def test_the_default_is_the_necessary_seats_and_the_floor_is_unchanged():
    assert policy.SEAT_DEFAULT == 2 and policy.SEAT_FLOOR == 3
    assert policy.seat_names(policy.SEAT_DEFAULT) == ["conformance", "defect"]
    assert policy.seat_names(3)[2] == "risk", "`review_seats 3` opens the seat that used to be default"


@pytest.mark.parametrize("seats, independent, met", [
    (2, True, True), (2, False, False), (2, None, False),
    (1, True, False), (3, False, True), (3, None, True), (1, False, False),
])
def test_the_floor_counts_the_auditor_only_where_it_is_independent(seats, independent, met):
    assert policy.floor_met(seats, independent) is met


def test_two_seats_and_an_independent_auditor_need_no_high_risk_mode():
    assert policy.resolve_seats(2, False, True) == 2


def test_two_seats_beside_an_auditor_on_a_seats_backend_are_below_the_floor():
    for independent in (False, None):
        with pytest.raises(policy.PolicyError, match="below the floor of 3"):
            policy.resolve_seats(2, False, independent)
    assert policy.resolve_seats(2, True, False) == 2, "high-risk mode lowers it, as it always did"


def test_one_seat_without_high_risk_mode_is_refused_even_beside_an_independent_auditor():
    with pytest.raises(policy.PolicyError, match="below the floor of 3"):
        policy.resolve_seats(1, False, True)
    assert policy.resolve_seats(1, True, True) == 1


def test_a_named_list_is_held_to_the_same_floor():
    assert policy.resolve_dimensions(["conformance", "defect"], False, True) == \
        ["conformance", "defect"]
    with pytest.raises(policy.PolicyError, match="below the floor"):
        policy.resolve_dimensions(["conformance", "defect"], False, False)
    with pytest.raises(policy.PolicyError, match="below the floor"):
        policy.resolve_dimensions(["conformance"], False, True)


def test_the_default_panel_is_sized_so_the_floor_holds():
    assert policy.default_seats(True, False) == 2
    assert policy.default_seats(False, False) == 3, "no independent auditor: a third seat"
    assert policy.default_seats(None, False) == 3
    assert policy.default_seats(False, True) == 2, "high-risk mode keeps two, and says so"


def test_the_conformance_veto_is_still_required():
    """`vetoes_missing` is unchanged: a default panel is not allowed to drop `conformance`."""
    assert policy.vetoes_missing(policy.seat_names(policy.SEAT_DEFAULT)) == []
    assert policy.vetoes_missing(["defect", "risk"]) == ["conformance"]


# ── the engine ────────────────────────────────────────────────────────────────────────────────


def _seats_asked(report, node="lead_review"):
    return [a.seat for a in report.asks if a.node_id == node and a.seat]


def test_a_default_run_opens_exactly_conformance_and_defect():
    """The wire: cut `resolve_seats`' default back to the floor and a third seat opens."""
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    assert _seats_asked(report) == ["conformance", "defect"]


def test_review_seats_three_opens_risk():
    report = engine.walk(_cfg(review_seats=3), Recorder(), enabled=True)
    assert _seats_asked(report) == ["conformance", "defect", "risk"]


def test_an_explicit_two_seats_is_refused_unless_the_auditor_counts():
    with pytest.raises(policy.PolicyError, match="below the floor"):
        engine.walk(_cfg(review_seats=2), Recorder(), enabled=True)
    report = engine.walk(_cfg(review_seats=2, auditor_independent=True), Recorder(), enabled=True)
    assert not [r for r in report.relaxations if "below the floor" in r], \
        "an independent auditor meets the floor; nothing was relaxed"


def test_two_seats_under_high_risk_mode_beside_a_same_backend_auditor_record_the_relaxation():
    report = engine.walk(
        _cfg(review_seats=2, auditor_independent=False, high_risk_mode=True), Recorder(),
        enabled=True)
    [note] = [r for r in report.relaxations if "below the floor" in r]
    assert "2 seat(s) (conformance, defect)" in note and "1 not opened" in note


def test_an_implicit_panel_the_caller_says_cannot_meet_the_floor_is_refused_without_high_risk():
    with pytest.raises(policy.PolicyError, match="below the floor"):
        engine.walk(_cfg(auditor_independent=False), Recorder(), enabled=True)
    report = engine.walk(_cfg(auditor_independent=False, high_risk_mode=True), Recorder(),
                         enabled=True)
    assert any("below the floor" in r for r in report.relaxations)
    assert _seats_asked(report) == ["conformance", "defect"]


def test_an_implicit_panel_nobody_has_judged_is_not_refused():
    """A library caller that does not say anything about the auditor runs the default, as before."""
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    assert not [r for r in report.relaxations if "below the floor" in r]


# ── the routing: which auditor counts ─────────────────────────────────────────────────────────


def _independent(audit, seats=None, builder=None, default=("claude", "-p"), registry=None,
                 open_seats=("conformance", "defect")):
    return cli.auditor_independent(
        {"agent_command": list(default)} if default else {}, registry, audit_entry=audit,
        seat_models=seats or {}, open_seats=list(open_seats),
        node_models={"engineer_build": builder} if builder else {})


def test_an_auditor_on_the_default_backend_is_not_independent_of_default_seats():
    assert _independent(None) is False


def test_an_auditor_routed_elsewhere_is_independent_of_default_seats_and_builder():
    assert _independent(["codex", "exec"]) is True


def test_an_auditor_on_a_seats_backend_is_not_independent():
    assert _independent(["codex", "exec"], seats={"defect": ["codex", "exec"]}) is False


def test_an_auditor_on_a_seat_that_is_not_open_does_not_count_against_it():
    assert _independent(["codex", "exec"], seats={"ux": ["codex", "exec"]}) is True


def test_an_auditor_is_compared_by_the_command_it_would_run_not_by_its_name():
    from ai_sdlc_runner import models as models_mod
    registry = models_mod.Registry([models_mod.Model(
        id="alpha", vendor="v", name="n", transport="cli", command=("codex", "exec"))])
    # The model id and the argv it expands to are one backend.
    assert _independent("alpha", seats={"defect": ["codex", "exec"]}, registry=registry) is False
    assert _independent("alpha", registry=registry) is True


def test_an_auditor_on_the_builders_backend_is_not_independent():
    from ai_sdlc_runner import models as models_mod
    registry = models_mod.Registry([models_mod.Model(
        id="alpha", vendor="v", name="n", transport="cli", command=("codex", "exec"))])
    assert _independent(["codex", "exec"], builder=["alpha"], registry=registry) is False


# ── the command line sizes the default panel ──────────────────────────────────────────────────


def _run(tmp_path, py_stub, capsys, *flags, **saved):
    from test_settings import _shipped
    config, settings_file, plan = _shipped(tmp_path, py_stub, **saved)
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan, "--confirm", "merge", *flags])
    return code, capsys.readouterr().out


def test_a_default_run_on_one_backend_opens_a_third_seat_and_says_why(tmp_path, py_stub, capsys):
    code, out = _run(tmp_path, py_stub, capsys)
    assert code == 0, out
    assert "opening 3 seats" in out
    assert "risk=pass" in out, "the third seat opened"


def test_high_risk_mode_keeps_the_default_two_and_the_run_records_it(tmp_path, py_stub, capsys):
    code, out = _run(tmp_path, py_stub, capsys, "--high-risk-mode")
    assert code == 0, out
    assert "opening 3 seats" not in out
    assert "risk=pass" not in out and "defect=pass" in out
    assert "below the floor" in out
