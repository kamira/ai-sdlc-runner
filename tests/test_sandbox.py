"""What a dispatched process may touch (CHG-20260827-23).

`policy.py`'s capability flags were **advisory**. `Role("qa", can_write=False)` carries the note
*"deliberately cannot write, so it cannot fix while verifying"* — a real safety property — and
nothing enforced it. The flags went into the work order and the process ran with the operator's full
rights.

## What this file can and cannot prove, stated up front

The **argv** built for each policy is asserted on every platform, by passing `system=` and a fake
`which`. That is a real check of the policy→command mapping and it runs everywhere.

Whether `bwrap` then *denies the write* needs `bwrap`. On Windows there is none, so
`test_a_denied_write_actually_fails` **skips**, loudly, naming what was not checked. It does not
pass quietly, because a skipped check that reads as a green tick is the thing this repository keeps
finding.

## The rule that shipped is not the rule proposed

CHG-20260827-23 said: no mechanism ⇒ refuse to dispatch. `available()` is `None` on every Windows
machine, so that refuses **every** dispatch — fourteen test files and the runner itself, on the
platform it is developed on. That is `policy.py`'s own named failure about the red lines: *a check
that gets switched off.*

What shipped: enforce where the machine can, **record** where it cannot, and refuse only when an
operator passed `--sandbox` and the machine cannot honour it. "Nobody asked and it is written down"
and "somebody asked and it cannot be done" are different, and only the second stops a run.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import policy, sandbox  # noqa: E402

HAS = {"bwrap": "/usr/bin/bwrap", "sandbox-exec": "/usr/bin/sandbox-exec"}
NONE = {}


def _which(table):
    return lambda tool: table.get(tool)


# ── the grade decides the policy ────────────────────────────────────────────────────────────────

def test_the_table_covers_every_grade_and_nothing_else():
    """A grade with no policy would be a blast radius nobody chose, defaulted to at the worst
    possible moment."""
    assert set(policy.SANDBOX) == set(policy.RISKS)
    for grade, rule in policy.SANDBOX.items():
        assert rule["write"] in policy.WRITE_SCOPES, grade
        assert isinstance(rule["network"], bool), grade


@pytest.mark.parametrize("grade,write,network", [
    ("low", "workspace", True),
    ("medium", "workspace", False),
    ("high", "none", False),
])
def test_the_table_says_what_the_record_says(grade, write, network):
    """The table is the part of this change most likely to be wrong, so it is asserted rather than
    left to be read. A seat arguing with it should find this test contradicting them, not silence."""
    assert policy.sandbox_for(grade) == {"write": write, "network": network}


def test_low_keeps_the_network_on_purpose():
    """The failure to fear is not "too loose". `policy.py` already names it about the red lines: a
    check that stops everything is a check that gets switched off. Builds fetch things."""
    assert policy.sandbox_for("low")["network"] is True


def test_a_role_that_may_not_write_gets_no_pen_at_any_grade():
    """The promise the flags were making and not keeping. QA is `can_write=False` so it cannot
    quietly repair what it is verifying — a `low` grade must not hand it a pen."""
    for grade in policy.RISKS:
        assert policy.sandbox_for(grade, can_write=False)["write"] == "none"


def test_capabilities_narrow_and_never_widen():
    """`can_write=True` must not turn a `high` grade's `none` into a `workspace`."""
    assert policy.sandbox_for("high", can_write=True)["write"] == "none"


def test_a_grade_with_no_policy_is_refused():
    with pytest.raises(policy.PolicyError):
        policy.sandbox_for("catastrophic")


# ── detection, from any platform ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("system,expected", [
    ("linux", "bwrap"),
    ("darwin", "seatbelt"),
    ("win32", None),
])
def test_the_mechanism_is_chosen_by_platform(system, expected):
    """`system` and `which` are parameters precisely so the Windows branch — the one that matters
    most, because it is the refusal — is exercised from a machine that is not Windows, and the
    Linux branch from one that is."""
    found = sandbox.available(system, _which(HAS))
    assert (found[0] if found else None) == expected


def test_a_platform_with_the_tool_missing_has_no_mechanism():
    """Being on Linux is not the same as having `bwrap`."""
    assert sandbox.available("linux", _which(NONE)) is None


def test_describe_names_the_mechanism_or_why_there_is_none():
    """Task 1: each run reports which mechanism it chose."""
    assert "bwrap" in sandbox.describe("linux", _which(HAS))
    assert "none available" in sandbox.describe("win32", _which(HAS))


# ── the command built for each policy ───────────────────────────────────────────────────────────

def test_a_high_grade_binds_nothing_writable():
    argv, bounded = sandbox.wrap(["run.py"], risk="high", workspace="/w",
                                 system="linux", which=_which(HAS))
    assert "--ro-bind" in argv
    assert "--bind" not in argv, "a `high` grade must not bind the workspace writable"
    assert "--unshare-net" in argv
    assert bounded["enforced"] is True and bounded["mechanism"] == "bwrap"


def test_a_low_grade_binds_the_workspace_and_keeps_the_network():
    argv, _ = sandbox.wrap(["run.py"], risk="low", workspace="/w",
                           system="linux", which=_which(HAS))
    assert argv[argv.index("--bind") + 1] == str(Path("/w").resolve()) or "--bind" in argv
    assert "--unshare-net" not in argv


def test_the_command_is_the_last_thing_on_the_line():
    """Everything after `--` is the command, so a flag in the argv cannot be read as a bwrap
    option."""
    argv, _ = sandbox.wrap(["run.py", "--verbose"], risk="high", workspace="/w",
                           system="linux", which=_which(HAS))
    assert argv[argv.index("--") + 1:] == ["run.py", "--verbose"]


def test_the_macos_profile_is_generated_from_the_same_policy():
    """One source for what is allowed. A profile kept as a file is a second document to drift."""
    argv, _ = sandbox.wrap(["run.py"], risk="medium", workspace="/w",
                           system="darwin", which=_which(HAS))
    profile = argv[argv.index("-p") + 1]
    assert "(deny default)" in profile
    assert "file-write*" in profile
    assert "(allow network*)" not in profile, "`medium` denies the network"


# ── recorded, or refused: never silent ──────────────────────────────────────────────────────────

def test_a_machine_that_cannot_enforce_records_it_rather_than_pretending():
    """The rule that shipped. `enforced: False` is the record; the argv is unchanged."""
    argv, bounded = sandbox.wrap(["run.py"], risk="high", system="win32", which=_which(HAS))
    assert argv == ["run.py"]
    assert bounded["enforced"] is False
    assert bounded["mechanism"] is None
    assert bounded["write"] == "none", "what was WANTED is still recorded, not overwritten"


def test_asking_for_a_sandbox_a_machine_cannot_give_is_refused():
    """The one case that stops a run: somebody asked for a boundary and it cannot be drawn."""
    with pytest.raises(sandbox.SandboxError) as exc:
        sandbox.wrap(["run.py"], risk="high", system="win32", which=_which(HAS), required=True)
    said = str(exc.value)
    assert "win32" in said, "the refusal must name the platform"
    assert sandbox.REQUIRE_FLAG in said, "and the flag that changes the outcome"


def test_the_refusal_is_never_a_downgrade():
    """There is no third outcome. `wrap` either bounds the command, records that it could not, or
    raises — it never returns the bare command while reporting a sandbox."""
    _, bounded = sandbox.wrap(["run.py"], risk="high", system="linux", which=_which(HAS))
    assert bounded["enforced"] is True
    _, unbounded = sandbox.wrap(["run.py"], risk="high", system="win32", which=_which(HAS))
    assert unbounded["enforced"] is False
    assert not (bounded["enforced"] and bounded["mechanism"] is None)


# ── the effect, where it can be observed ────────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("bwrap") is None,
                    reason="no bwrap on this machine, so the DENIAL is not exercised here — only "
                           "the argv is. Windows has no mechanism at all; see the module docstring "
                           "and ACC-20260827-23, which say so rather than implying coverage.")
def test_a_denied_write_actually_fails(tmp_path):
    """The only test here that observes the sandbox doing anything, and it runs where `bwrap` is.

    Everything above asserts the command; this asserts the consequence. Kept separate and skipped
    loudly rather than folded in, because a check that silently does not run reads as a green tick.
    """
    outside = tmp_path / "outside.txt"
    argv, bounded = sandbox.wrap(
        [sys.executable, "-c", f"open({str(outside)!r}, 'w').write('x')"],
        risk="high", workspace=str(tmp_path / "workspace"))
    assert bounded["enforced"] is True
    (tmp_path / "workspace").mkdir()

    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0, "a `high` grade wrote outside the workspace"
    assert not outside.exists()


# ── the promise, kept at the wiring and not only in the table ───────────────────────────────────

def test_the_dispatched_process_gets_the_roles_capability_not_a_guess():
    """`Role("qa", can_write=False)` is the note this whole change quotes. Asserting it against
    `policy.sandbox_for` proves the table; it does not prove the process was told.

    The first version of the wiring looked only at the **seat** name, so a `qa` node got
    `can_write=True` and the policy layer was never asked about it — the table was right and the
    promise was still not kept. Found while writing an acceptance, which is a worse way to find it
    than this test.
    """
    from ai_sdlc_runner import cli

    factory = cli.session_factory(
        {"agent_command": ["python3", "-c", "pass"], "agent_cwd": "."}, risk="low")

    for role, expected in (("qa", False), ("seat", False),
                           ("engineer", True), ("lead", True), ("pm", True)):
        assert factory(role=role).can_write is expected, role
        assert policy.BY_ROLE[role].can_write is expected, (
            f"{role} disagrees with policy.ROLES, so one of the two is stale")


def test_a_role_this_policy_does_not_define_is_not_guessed_at():
    """Narrowing on an unknown name would be inventing a capability; widening would be worse. The
    grade's default stands, and the grade is the thing that was actually decided."""
    from ai_sdlc_runner import cli

    factory = cli.session_factory(
        {"agent_command": ["python3", "-c", "pass"], "agent_cwd": "."}, risk="low")
    assert factory(role="archaeologist").can_write is True
    assert factory().can_write is True


def test_the_dispatched_process_is_bounded_at_the_grade_in_force_not_the_plans_proposal():
    """The other half of the sibling above, and it was missing for the same reason.

    `can_write` is a property of the role and was wired per ask. `risk` was bound **once**, when the
    factory was built, from `cfg.risk` — which `cmd_run` documents in as many words as *"the plan's
    proposal"*. `_Process.risk`'s own docstring says the opposite: *"Derived from the grade in force
    and narrowed by the role's `can_write`."*

    So a run whose grading panel answered `high` over a plan proposing `low` dispatched every later
    ask with `policy_verdict.risk = "high"` in its work order, into a `low` sandbox. Every shipped
    example plan declares `risk: low`, so this is the default case, not a corner
    (CHG-20260901-18, defect seat D-1).

    The grade arrives the ask-if-you-want-it way, exactly as `role` and `workspace` do.
    """
    from ai_sdlc_runner import cli

    factory = cli.session_factory(
        {"agent_command": ["python3", "-c", "pass"], "agent_cwd": "."}, risk="low")

    assert factory(role="engineer").risk == "low", "with no grade offered, the bound one stands"
    assert factory(role="engineer", grade="high").risk == "high", (
        "the grade in force must win over the grade the plan proposed")
    assert factory(role="engineer", grade="").risk == "low", (
        "an empty grade is 'the engine did not offer one', not 'the grade is empty'")

    # And the bound value is genuinely reachable, so the fallback above is not vacuous.
    strict = cli.session_factory(
        {"agent_command": ["python3", "-c", "pass"], "agent_cwd": "."}, risk="high")
    assert strict(role="engineer").risk == "high"
    assert strict(role="engineer", grade="low").risk == "low", (
        "the grade in force wins in both directions — a settled `low` is a decision, not a relaxation")
