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


def test_a_later_met_postcondition_does_not_move_the_frontier_and_is_not_redone():
    """Order is causal, so a downstream postcondition that happens to be true — the residue of an
    abandoned attempt — must not make the engine think the upstream effect can be skipped.

    It must equally **not** be applied again. Re-running an effect whose postcondition already holds
    is a duplicate side effect: `gh pr create` against an existing PR is not idempotent in the world,
    only in a test double. The review panel caught this — the first version of `run` applied
    everything past the frontier unconditionally, and this test asserted that behaviour, so the test
    was hiding the hazard rather than catching it. The state is reported as out of order instead:
    neither silently redone nor silently accepted."""
    world = {"pr": True}
    outcome = effects.run(_seq(world))
    assert outcome.frontier == "chg"
    assert outcome.applied == ["chg", "branch", "push"]
    assert "pr" not in outcome.applied
    assert outcome.out_of_order == ["pr"]


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
        "out_of_order": [],
    }


def test_an_effect_already_true_is_never_applied_even_far_past_the_frontier():
    """The general form of the defect: nothing already true is ever applied, at any position."""
    applied = []
    world = {"chg": True, "pr": True}
    seq = _seq(world)
    seq = [effects.Effect(name=e.name, probe=e.probe,
                          apply=(lambda e=e: (applied.append(e.name), e.apply())[1]),
                          postcondition=e.postcondition) for e in seq]
    outcome = effects.run(seq)
    assert applied == ["branch", "push"]
    assert outcome.out_of_order == ["pr"]


# --------------------------------------------------------------------------------------
# CHG-20260905-01 — what the module does on the path it exists for: a failing one
# --------------------------------------------------------------------------------------


class _Unanswerable(Exception):
    """Stands in for `probes.ProbeError`, which `probes.py` raises by design when a probe cannot
    answer. `effects.py` must not import `probes`, so the test uses a foreign exception class —
    which is also the sharper test: the translation must be by *behaviour*, not by a name."""


def _cannot_answer(name):
    def probe():
        raise _Unanswerable("could not reach origin")
    return effects.Effect(name=name, probe=probe, apply=lambda: None,
                          postcondition=f"{name} is on the remote")


def test_a_probe_that_cannot_answer_halts_the_run_instead_of_the_process():
    """`ProbeError` used to travel out of the process entirely.

    `engine._run_effects` catches `EffectError` only and `cli.cmd_run`'s handler tuple listed
    neither `ProbeError` nor `ShipError`, so an unreachable remote killed the run with a traceback,
    no report, and no halt — which leaks a `--worktree` run's tree, the damage `cli.py`'s own
    comment records as already found once for `IntakeError`.
    """
    world = {}
    sequence = _seq(world, order=("chg",)) + [_cannot_answer("push")]

    with pytest.raises(effects.EffectError) as caught:
        effects.run(sequence)

    assert isinstance(caught.value.__cause__, _Unanswerable), (
        "the original is dropped, so nobody can see what actually went wrong")


def test_the_halt_says_which_probe_could_not_answer():
    """A halt naming neither the effect nor its postcondition sends an operator to read the code."""
    with pytest.raises(effects.EffectError) as caught:
        effects.run([_cannot_answer("push")])

    said = str(caught.value)
    assert "push" in said, "the halt does not name the effect"
    assert "push is on the remote" in said, "the halt does not name what could not be read"
    assert "could not reach origin" in said, "the halt drops the probe's own reason"


def test_a_halted_sequence_reports_what_had_already_landed():
    """The outcome used to be a local in `run` and died with the raise.

    On the one path where *which effects are already done* is the entire question, the answer was
    thrown away — while `relaxations` and `on_trust` came through the same halt intact.
    """
    world = {}
    sequence = _seq(world, order=("chg", "branch")) + [_cannot_answer("push")]

    with pytest.raises(effects.EffectError) as caught:
        effects.run(sequence)

    assert world == {"chg": True, "branch": True}, "two effects really landed"
    assert caught.value.outcome is not None, "the record of what landed died with the raise"
    assert caught.value.outcome.applied == ["chg", "branch"]


def test_a_failure_to_establish_a_postcondition_also_reports_what_landed():
    """The other raise out of `run` — the false-green check — carries the outcome too."""
    world = {}
    sequence = _seq(world, order=("chg", "branch", "push"))
    silent = sequence[2]
    sequence[2] = effects.Effect(name=silent.name, probe=silent.probe, apply=lambda: None,
                                 postcondition=silent.postcondition)

    with pytest.raises(effects.EffectError) as caught:
        effects.run(sequence)

    assert caught.value.outcome is not None
    assert caught.value.outcome.applied == ["chg", "branch"]


def test_a_dry_run_sees_what_is_out_of_causal_order():
    """The mode for looking before acting could not see the thing most worth looking at.

    `run` returned at the frontier, so `out_of_order` came back empty for a world that was not in
    causal order — indistinguishable from a clean answer. FR-15 is P0, names `effects.run`, and
    carries no dry-run caveat.
    """
    world = {"chg": True, "push": True}          # `push` true while `branch` is not

    dry = effects.run(_seq(world), dry_run=True).as_dict()

    assert dry["frontier"] == "branch"
    assert dry["out_of_order"] == ["push"], (
        "a dry run reports a world out of causal order as if it were in order")
    assert dry["already_met"] == ["chg", "push"]


def test_a_dry_run_and_a_wet_run_read_the_same_world_the_same_way():
    """The property under the test above: looking and acting must not disagree about what is there.

    Asserting the dry list alone would stay green if the wet path stopped reporting it too.
    """
    dry = effects.run(_seq({"chg": True, "push": True}), dry_run=True).as_dict()
    wet = effects.run(_seq({"chg": True, "push": True})).as_dict()

    assert dry["frontier"] == wet["frontier"]
    assert dry["out_of_order"] == wet["out_of_order"]
    assert dry["already_met"] == wet["already_met"]


def test_a_dry_run_applies_nothing():
    """Reading the whole sequence must not have turned looking into acting."""
    world = {"chg": True, "push": True}

    outcome = effects.run(_seq(world), dry_run=True)

    assert outcome.applied == []
    assert world == {"chg": True, "push": True}, "a dry run changed the world"


def test_the_frontier_is_not_probed_twice():
    """`find_frontier` just read it as unmet; asking again is a second round trip for that answer.

    Probes are deliberately uncached and `probes.DEFAULT_TIMEOUT` is 60s, so the redundant read was
    a real one. Counted rather than described, because a comment saying "we do not re-probe" is
    exactly the kind of claim that stops being true without anything noticing.
    """
    world = {}
    asked = []

    def make(name):
        def probe():
            asked.append(name)
            return bool(world.get(name))
        return effects.Effect(name=name, probe=probe,
                              apply=lambda name=name: world.__setitem__(name, True),
                              postcondition=f"world[{name!r}] is set")

    effects.run([make("chg"), make("branch")])

    assert asked == ["chg", "chg", "branch", "branch"], (
        "the frontier was read once to find it, once again before applying, and once after")


def test_an_out_of_order_effect_does_not_stop_the_ones_after_it():
    """`continue`, not `break`. Replacing it skips every later effect and the PR is never created.

    The existing sequence tests have nothing out of causal order, so the swap left all of them
    green: the loop never reached the branch that would differ.
    """
    world = {"push": True}

    outcome = effects.run(_seq(world))

    assert outcome.out_of_order == ["push"]
    assert "pr" in outcome.applied, "the effect after the out-of-order one was skipped"
    assert world["pr"] is True


def test_a_probe_that_takes_arguments_is_refused_at_construction():
    """`Effect(probe=len)` was admitted and blew up inside `find_frontier` — at run time, which is
    after the effects before it have already been applied."""
    with pytest.raises(effects.EffectError) as caught:
        effects.Effect(name="x", probe=len, apply=lambda: None)

    assert "no arguments" in str(caught.value)

    with pytest.raises(effects.EffectError):
        effects.Effect(name="x", probe=lambda: True, apply=lambda a: None)


def test_a_callable_whose_signature_cannot_be_read_is_admitted():
    """The guard refuses what it can prove wrong, not what it cannot read.

    Refusing the unreadable would turn every valid-but-unintrospectable probe into a refusal in
    order to catch the invalid ones — a guard whose subject is *what it can see* rather than the
    property it is for.
    """
    admitted = effects.Effect(name="y", probe=dict, apply=lambda: None)

    assert admitted.probe() == {}
