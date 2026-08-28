"""One planning tier cannot plan a programme, and nothing reviewed two plans against each other
(CHG-20260827-22).

`pm_plan` produced one list of modules at one scope. For a programme that is really several
workstreams that is the wrong shape twice over:

* the plan is written at one level of detail for parts that do not share one, and
* `lead_review` reviews the **change**. Nothing ever reviewed the **plans** against each other, so
  two workstreams could pick incompatible interfaces and the first thing to notice would be a
  failing build several nodes later — or nothing, and the inconsistency ships.

## The two facts these tests are for

**Scope is read, never supplied.** `plan_scope` branches on the plan's own `workstreams`. A run that
could answer this question could declare itself simple and skip the reconciliation that exists to
catch it. That is why `_scope` takes the config and there is no decision key for it.

**Reconciliation is not a vote.** Two declarations naming one interface differently is a fact about
the plans. `reconcile` has no role and no panel; it compares strings.

## The bound, which is the part I got wrong first

`conflict` routes to `pm_plan`, whose answer cannot change `cfg.interfaces` — those come from the
plan file. So the first version of this cycled until `max_steps`, where the operator is told the
flow is "cycling without progress": the generic catch, not an answer. One revision pass, then a
halt that names the interface. The same bound `re_review` puts on a fix.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import engine, graph, plan, policy  # noqa: E402


def _cfg(**kw):
    kw.setdefault("node_specs", {})
    kw.setdefault("decisions", {})
    return engine.RunConfig(**kw)


# ── scope is decided from the plan, not answered ────────────────────────────────────────────────

def test_one_workstream_takes_the_single_branch():
    """The compatibility path: every plan written before this change has one workstream or none."""
    assert engine._scope(_cfg(workstreams={"only": "low"})) == "single"
    assert engine._scope(_cfg()) == "single"


def test_several_workstreams_take_the_split_branch():
    assert engine._scope(_cfg(workstreams={"api": "high", "copy": "low"})) == "split"


def test_the_run_cannot_answer_the_scope_question_itself():
    """A supplied decision for `plan_scope` is ignored.

    This is the check that matters more than the two above. If a run could answer this, a plan with
    three workstreams could say `single`, never reach `reconcile`, and the interfaces would go
    unexamined — with `visited` showing a clean single-workstream run. The branch is derived, so
    saying otherwise changes nothing.
    """
    cfg = _cfg(workstreams={"api": "high", "copy": "low"}, decisions={"plan_scope": "single"})
    assert engine._choose(cfg, graph.BY_ID["plan_scope"], {}, engine.RunReport()) == "split"


def test_the_single_branch_returns_to_the_node_it_used_to_go_to():
    """`pm_plan → pm_confirm` is what every earlier plan did, and it still does it."""
    assert graph.BY_ID["pm_plan"].next == "plan_scope"
    assert graph.BY_ID["plan_scope"].branches["single"] == "pm_confirm"


# ── the reconciliation itself ───────────────────────────────────────────────────────────────────

def test_interfaces_that_agree_are_not_a_conflict():
    """Two workstreams declaring the *same* signature is agreement, not duplication."""
    assert engine.conflicts({"a": {"fetch": "(id) -> User"}, "b": {"fetch": "(id) -> User"}}) == []


def test_interfaces_that_do_not_overlap_are_not_a_conflict():
    assert engine.conflicts({"a": {"fetch": "(id) -> User"}, "b": {"save": "(u) -> None"}}) == []


def test_the_same_name_with_different_signatures_is_a_conflict():
    found = engine.conflicts({"a": {"fetch": "(id) -> User"}, "b": {"fetch": "(id) -> dict"}})
    assert len(found) == 1
    assert "fetch" in found[0]


def test_a_conflict_names_the_interface_and_both_workstreams():
    """A boolean would send an operator back to `pm_plan` to guess.

    The branch is the same either way; what makes the halt actionable is the string.
    """
    found = engine.conflicts({"api": {"fetch": "(id) -> User"}, "web": {"fetch": "(id) -> dict"}})
    assert "api" in found[0] and "web" in found[0]
    assert "(id) -> User" in found[0] and "(id) -> dict" in found[0]


def test_three_workstreams_disagreeing_report_all_three():
    found = engine.conflicts({"a": {"f": "1"}, "b": {"f": "2"}, "c": {"f": "3"}})
    assert len(found) == 1
    assert all(w in found[0] for w in ("a", "b", "c"))


def test_nobody_is_asked_to_reconcile():
    """A fact about two declarations is not improved by voting on it — so the node has no role, no
    panel, and no gate to wave it through."""
    node = graph.BY_ID["reconcile"]
    assert node.role is None
    assert node.mode == graph.RUNNER
    assert node.gate is None


# ── the bound ───────────────────────────────────────────────────────────────────────────────────

def test_a_conflict_goes_back_to_the_planner_once():
    cfg = _cfg(interfaces={"a": {"f": "1"}, "b": {"f": "2"}})
    report = engine.RunReport()
    assert engine._reconciled(cfg, report) == "conflict"
    assert graph.BY_ID["reconcile"].branches["conflict"] == "pm_plan"


def test_the_same_conflict_a_second_time_halts_rather_than_cycling():
    """The defect in my own first draft.

    `pm_plan` cannot change `cfg.interfaces`; they are read from the plan. So a conflict that
    survives one trip through `pm_plan` is unchanged **by definition**, and routing it back again
    spins the flow until `max_steps` — where the operator learns only that something looped.
    """
    cfg = _cfg(interfaces={"a": {"f": "1"}, "b": {"f": "2"}})
    report = engine.RunReport()
    assert engine._reconciled(cfg, report) == "conflict"
    assert engine._reconciled(cfg, report) == "unresolved"
    assert graph.BY_ID["reconcile"].branches["unresolved"] == "halt_unreconciled"
    assert graph.BY_ID["halt_unreconciled"].kind == graph.TERMINAL


def test_the_halt_carries_the_interface_that_could_not_be_reconciled():
    """A terminal node that says "unreconciled" and nothing else is a stop with no next step."""
    cfg = _cfg(interfaces={"api": {"fetch": "(id) -> User"}, "web": {"fetch": "(id) -> dict"}})
    report = engine.RunReport()
    engine._reconciled(cfg, report)
    engine._reconciled(cfg, report)
    recorded = [d for d in report.dispatches if d.startswith("reconcile:")]
    assert len(recorded) == 1, f"the disagreement was recorded {len(recorded)} times: {recorded}"
    assert "fetch" in recorded[0] and "api" in recorded[0] and "web" in recorded[0]


def test_a_different_conflict_after_a_revision_is_not_treated_as_the_same_one():
    """The bound is one pass at *this* conflict, not one pass at reconciliation.

    A plan revised into a genuinely different disagreement has not been round this loop before, and
    treating it as unresolved would refuse a revision nobody had seen yet.
    """
    report = engine.RunReport()
    assert engine._reconciled(_cfg(interfaces={"a": {"f": "1"}, "b": {"f": "2"}}), report) \
        == "conflict"
    assert engine._reconciled(_cfg(interfaces={"a": {"g": "1"}, "b": {"g": "9"}}), report) \
        == "conflict"


# ── the second tier's shape ─────────────────────────────────────────────────────────────────────

def test_the_sub_planner_plans_and_does_not_build_or_dispatch():
    """`can_spawn=False` is the bound, not a preference: this tier opens nothing below it."""
    caps = policy.capabilities("planner")
    assert caps["can_spawn"] is False
    assert caps["can_write"] is True     # a plan is a written thing
    assert caps["can_execute"] is False  # a planner that could run commands is an engineer


def test_sub_planning_is_a_pool_the_pm_dispatches():
    node = graph.BY_ID["sub_plan"]
    assert node.mode == graph.POOL
    assert node.main == "pm"
    assert node.role == "planner"


def test_the_reconciled_whole_is_panelled_once_not_per_workstream():
    """Both branches land on the same `pm_confirm`.

    Panelling each sub-plan would put the same change through the gate N times and call the last
    verdict the answer. The plans are reconciled first, then the whole is confirmed once.
    """
    assert graph.BY_ID["plan_scope"].branches["single"] == "pm_confirm"
    assert graph.BY_ID["reconcile"].branches["agree"] == "pm_confirm"


# ── the plan file's side ────────────────────────────────────────────────────────────────────────

def _plan(tmp_path, payload):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_interfaces_reach_the_run(tmp_path):
    """The seam a unit test of `conflicts` cannot cover: the plan's key reaching `cfg.interfaces`."""
    loaded = plan.load(_plan(tmp_path, {
        "workstreams": {"api": "low"},
        "interfaces": {"api": {"fetch": "(id) -> User"}},
    }))
    assert loaded["interfaces"] == {"api": {"fetch": "(id) -> User"}}


def test_interfaces_for_a_workstream_nobody_declared_are_refused(tmp_path):
    """Nothing would reconcile them, and the run would proceed as though they agreed."""
    with pytest.raises(plan.PlanError) as exc:
        plan.load(_plan(tmp_path, {
            "workstreams": {"api": "low"},
            "interfaces": {"web": {"fetch": "(id) -> User"}},
        }))
    assert "web" in str(exc.value)


def test_an_empty_signature_is_refused(tmp_path):
    """It agrees with everything, which is worse than declaring nothing: it looks reconciled."""
    with pytest.raises(plan.PlanError) as exc:
        plan.load(_plan(tmp_path, {
            "workstreams": {"api": "low"},
            "interfaces": {"api": {"fetch": "   "}},
        }))
    assert "fetch" in str(exc.value)


def test_a_list_of_interfaces_is_refused(tmp_path):
    """A list has no names to compare, and comparing by name is the whole mechanism."""
    with pytest.raises(plan.PlanError) as exc:
        plan.load(_plan(tmp_path, {
            "workstreams": {"api": "low"},
            "interfaces": {"api": ["fetch"]},
        }))
    assert "list" in str(exc.value)


# ── end to end, through the real CLI ────────────────────────────────────────────────────────────

AGENT = """
import json, sys
order = json.load(sys.stdin)
node, seat = order["node_id"], order.get("seat")


def say(obj):
    print(json.dumps(obj))
    raise SystemExit(0)


if seat:
    if node == "intake_review":
        say({"missing": [], "problems": [], "unsafe": []})
    say({"verdict": "pass", "why": "nothing found"})
if node == "pm_plan":
    say({"modules": ["alpha"]})
if node == "lead_assess":
    say({"risk": "low"})
if node == "engineer_build":
    say({"module": "alpha"})
branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
          "re_review": "pass", "qa_accept": "pass"}.get(node)
say({"verdict": branch} if branch else {"summary": (node or "?") + " done"})
"""


def _run(tmp_path, name, payload):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "agent.py").write_text(AGENT, encoding="utf-8")
    (tmp_path / "runner.yaml").write_text(
        'agent_command: ["python3", "agent.py"]\nagent_timeout: 60\n', encoding="utf-8")
    where = tmp_path / name
    where.mkdir()
    (where / "plan.json").write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(tmp_path / "runner.yaml"),
         "run", "--plan", str(where / "plan.json"),
         "--confirm", "merge", "--ask-journal", str(where / "asks")],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}, timeout=900)
    return (proc.stdout or "") + (proc.stderr or "")


def test_conflicting_interfaces_stop_the_run_and_name_the_interface(tmp_path):
    """The whole change, observed from outside.

    The control and the subject differ **only** in one signature string. Without the control this
    would prove nothing: a run that stops for any of a dozen other reasons would look like a pass.
    """
    base = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/minimal/plan.json").read_text("utf-8"))
    base["risk"] = "low"
    base["workstreams"] = {"api": "low", "web": "low"}
    # `sub_plan` does work, so it declares what it will do — the same rule every other node obeys.
    # A new node is not exempt from `--undeclared refuse`, and the first draft of this test found
    # that out by being stopped at it.
    base["node_specs"]["sub_plan"] = dict(base["node_specs"]["pm_plan"], scope="sub_plan")
    base["operations"]["sub_plan"] = [
        {"description": "sub_plan: plan one workstream", "kind": "ordinary", "targets": []}]

    agreed = dict(base, interfaces={"api": {"fetch": "(id) -> User"},
                                    "web": {"fetch": "(id) -> User"}})
    clashing = dict(base, interfaces={"api": {"fetch": "(id) -> User"},
                                      "web": {"fetch": "(id) -> dict"}})

    control = _run(tmp_path, "agreed", agreed)
    assert "state:         finished" in control, (
        f"the control did not finish, so the comparison below proves nothing:\n{control[-900:]}")

    subject = _run(tmp_path, "clashing", clashing)
    assert "state:         finished" not in subject, (
        f"two workstreams declared `fetch` differently and the run finished anyway — nothing "
        f"reconciled them:\n{subject[-900:]}")
    assert "fetch" in subject, (
        f"the run stopped, but never named the interface it stopped for, so an operator cannot "
        f"act on it:\n{subject[-900:]}")


def test_a_single_workstream_plan_still_finishes_untouched(tmp_path):
    """The rollback story, run rather than argued: the shipped example is unchanged by this."""
    base = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/minimal/plan.json").read_text("utf-8"))
    base["risk"] = "low"
    out = _run(tmp_path, "plain", base)
    assert "state:         finished" in out, out[-900:]
    assert "sub_plan" not in out, "a one-workstream plan entered the second tier"


def test_the_bound_is_enforced_on_a_run_not_only_available_as_a_function(monkeypatch):
    """A mutation found this one, and it is the same defect twice in one change.

    `test_a_deeper_tree_is_refused_and_says_which_chain` calls `policy.check_dispatch_depth`
    directly, so deleting the call from `engine.walk` left every test green. That is exactly what
    `MAX_DISPATCH_DEPTH` being defined-but-uncomputed was — a guarantee stated in one place and
    checked in another that never meets it.

    Driven through `walk`, so "enforced on every run" is a claim something exercises.
    """
    monkeypatch.setattr(graph, "dispatch_edges",
                        lambda: {"pm": ["planner"], "planner": ["lead"], "lead": ["engineer"]})
    with pytest.raises(policy.PolicyError) as exc:
        engine.walk(_cfg(), lambda order: {"ok": True}, enabled=True)
    assert "deep" in str(exc.value)
    assert "planner dispatches lead" in str(exc.value)


# ── a formatting difference is not a disagreement (CHG-20260828-11) ─────────────────────────────

@pytest.mark.parametrize("one,two,why", [
    ("(id) -> User", "(id)->User", "the case ACC-20260827-22 named"),
    ("(id) -> User", "( id )->User", "spaces inside the brackets too"),
    ("Dict[str, int]", "Dict[str,int]", "after a comma"),
    ("  (id)->User  ", "(id)->User", "leading and trailing"),
])
def test_two_planners_spacing_a_signature_differently_agree(one, two, why):
    """`ACC-20260827-22` #2: *"a formatting difference stops a run… it is a false stop."*

    The reservation also said normalising would mean parsing a type language this runner does not
    have. That is true of **semantic** normalising and not of whitespace, and the two were conflated.
    """
    assert engine.conflicts({"a": {"f": one}, "b": {"f": two}}) == [], why


def test_a_space_between_two_words_is_still_a_difference():
    """Why stripping all whitespace is the wrong rule, and it was the first one tried.

    `int x` and `intx` are not the same declaration in any notation, so the rule is narrower:
    whitespace **touching punctuation** is formatting; whitespace between two word characters is not.
    """
    assert engine.conflicts({"a": {"f": "int x"}, "b": {"f": "intx"}}) != []


def test_a_real_disagreement_is_still_a_conflict():
    """The property that must survive: `(a) -> b` against `(a) -> c` differ in a word, not a space."""
    found = engine.conflicts({"a": {"f": "(a) -> b"}, "b": {"f": "(a) -> c"}})
    assert len(found) == 1 and "b" in found[0] and "c" in found[0]


def test_the_reported_strings_are_what_each_planner_wrote():
    """Normalisation is for comparison only.

    When two planners genuinely disagree the operator has to see what each of them said — a halt
    quoting a normalised form would send them looking for text that is in neither plan.
    """
    found = engine.conflicts({"api": {"f": "int x"}, "web": {"f": "intx"}})
    assert "'int x'" in found[0] and "'intx'" in found[0]
