"""Ordered effects and their probes (CHG-20260822-04 task 6, D6).

Two invariants carry the crash-safety, and each is tested by making the failure happen rather than
by asserting the happy path:

* **Admissibility** — an operation without a probe cannot become an effect at all (D6.2).
* **Frontier resume** — a sequence interrupted anywhere resumes at the first unmet postcondition,
  never at the start and never past a step that did not actually happen (D6.3).

Probes here are backed by a mutable ``world`` dict standing in for the ledger, git and the forge.
That is the right stand-in precisely because the tests can kill a run mid-sequence and leave the
world in the partial state a crash would.
"""
from __future__ import annotations

import pytest

from ai_sdlc_runner import effects


def _seq(world, order=("chg", "branch", "push", "pr"), fail_at=None):
    """A sequence whose effects set their own postconditions in ``world``."""
    def make(name):
        def apply():
            if fail_at == name:
                raise RuntimeError(f"killed during {name}")
            world[name] = True
        return effects.Effect(
            name=name,
            probe=lambda name=name: bool(world.get(name)),
            apply=apply,
            postcondition=f"world[{name!r}] is set",
        )
    return [make(name) for name in order]


# --------------------------------------------------------------------------------------
# D6.2 — probeability is the admission criterion
# --------------------------------------------------------------------------------------

def test_an_effect_without_a_probe_cannot_be_constructed():
    """The rule is enforced, not documented: an unprobeable step never reaches a sequence."""
    with pytest.raises(effects.EffectError) as exc:
        effects.Effect(name="deploy", probe=None, apply=lambda: None)
    assert "probeable postcondition" in str(exc.value)


def test_an_effect_without_an_apply_or_a_name_is_refused():
    with pytest.raises(effects.EffectError):
        effects.Effect(name="x", probe=lambda: True, apply=None)
    with pytest.raises(effects.EffectError) as exc:
        effects.Effect(name="", probe=lambda: True, apply=lambda: None)
    assert "named" in str(exc.value)


# --------------------------------------------------------------------------------------
# D6.3 — resume at the first unmet postcondition
# --------------------------------------------------------------------------------------

def test_a_cold_start_runs_everything_in_order():
    world = {}
    outcome = effects.run(_seq(world))
    assert outcome.frontier == "chg"
    assert outcome.applied == ["chg", "branch", "push", "pr"]
    assert outcome.already_met == []


def test_a_finished_sequence_applies_nothing():
    world = {"chg": True, "branch": True, "push": True, "pr": True}
    outcome = effects.run(_seq(world))
    assert outcome.frontier is None
    assert outcome.applied == []
    assert outcome.already_met == ["chg", "branch", "push", "pr"]


def test_the_push_pr_window_resumes_at_exactly_the_pr():
    """The worked example that decided the design: killed between `git push` and `gh pr create`.
    The branch exists on the remote, the PR does not, so the frontier is exactly "PR not created"
    and only that effect re-runs."""
    world = {"chg": True, "branch": True, "push": True}
    outcome = effects.run(_seq(world))
    assert outcome.frontier == "pr"
    assert outcome.applied == ["pr"]
    assert outcome.already_met == ["chg", "branch", "push"]


def test_a_partial_state_is_never_read_as_never_started():
    """The failure D6 exists to prevent. After a kill mid-sequence, a second run must not redo the
    effects that already left their postconditions behind."""
    world = {}
    with pytest.raises(RuntimeError):
        effects.run(_seq(world, fail_at="push"))
    assert world == {"chg": True, "branch": True}      # the crash left a partial world

    outcome = effects.run(_seq(world))                  # cold restart, same sequence
    assert outcome.frontier == "push"
    assert outcome.applied == ["push", "pr"]
    assert "chg" not in outcome.applied and "branch" not in outcome.applied


def test_a_later_met_postcondition_does_not_let_an_earlier_one_be_skipped():
    """Order is causal. A downstream postcondition that happens to be true — a stale branch from an
    abandoned attempt, say — must not make the engine think the upstream effect can be skipped."""
    world = {"pr": True}
    outcome = effects.run(_seq(world))
    assert outcome.frontier == "chg"
    assert outcome.applied == ["chg", "branch", "push", "pr"]


def test_find_frontier_short_circuits_at_the_first_unmet_probe():
    consulted = []

    def probe_for(name, value):
        def probe():
            consulted.append(name)
            return value
        return probe

    seq = [
        effects.Effect(name="a", probe=probe_for("a", True), apply=lambda: None),
        effects.Effect(name="b", probe=probe_for("b", False), apply=lambda: None),
        effects.Effect(name="c", probe=probe_for("c", True), apply=lambda: None),
    ]
    assert effects.find_frontier(seq) == 1
    assert consulted == ["a", "b"]                     # "c" is never consulted


# --------------------------------------------------------------------------------------
# an effect that runs without leaving evidence is a hard failure
# --------------------------------------------------------------------------------------

def test_an_effect_that_does_not_establish_its_postcondition_stops_the_run():
    """A step reporting success without evidence is the false-green this repo keeps catching; the
    engine must not march past it."""
    ran = []
    seq = [
        effects.Effect(name="noop", probe=lambda: False, apply=lambda: ran.append("noop"),
                       postcondition="something that never becomes true"),
        effects.Effect(name="after", probe=lambda: True, apply=lambda: ran.append("after")),
    ]
    with pytest.raises(effects.EffectError) as exc:
        effects.run(seq)
    assert "postcondition is still not true" in str(exc.value)
    assert ran == ["noop"]                             # the next effect never ran


# --------------------------------------------------------------------------------------
# inspection without acting
# --------------------------------------------------------------------------------------

def test_dry_run_reports_the_frontier_without_applying_anything():
    world = {"chg": True}
    outcome = effects.run(_seq(world), dry_run=True)
    assert outcome.frontier == "branch"
    assert outcome.applied == []
    assert world == {"chg": True}


def test_outcome_serialises_for_a_log():
    world = {"chg": True, "branch": True, "push": True}
    assert effects.run(_seq(world)).as_dict() == {
        "frontier": "pr",
        "already_met": ["chg", "branch", "push"],
        "applied": ["pr"],
    }
