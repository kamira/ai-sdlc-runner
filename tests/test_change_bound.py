"""The module loop is bounded and the whole-change loop was not (CHG-20260828-22).

README *Known gaps* named one of the two:

> **A seat panel that keeps failing has no bound.** `lead_review` → `review_failed` →
> `next_module` → `lead_review` cycles until `max_steps`.

Reading the graph to fix it found the same loop one node over, unnamed —
`qa_accept` → `acceptance_failed` → `next_module` → `lead_review` → `qa_verify` → `qa_accept`.
Both are the assembled change being rejected and sent back with nothing counting, and a run that
kept failing died on *"walk exceeded 200 steps"*: a message that tells an operator the runner gave
up rather than that **their change was rejected twice**.

The module loop has said the right thing since the beginning — `halt_second_fail`, *"two failures on
one module is not something retrying fixes"*.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_sdlc_runner import engine, graph, policy  # noqa: E402

SPEC = {"objective": "o", "instructions": "i", "done_when": "d"}


def _report(*rejected_at):
    """A run that has already routed through these rejection nodes, in this order."""
    report = engine.RunReport()
    report.visited.extend(rejected_at)
    return report


# ── the bound itself ───────────────────────────────────────────────────────────────────────────


def test_the_first_rejection_goes_round_again():
    assert engine._change_retry(_report("review_failed")) == "first"


def test_the_second_rejection_halts():
    assert engine._change_retry(_report("review_failed", "review_failed")) == "again"


def test_a_change_never_rejected_is_not_at_the_bound():
    """`change_retry` is only reached after a rejection, but the count must still be honest."""
    assert engine._change_retry(engine.RunReport()) == "first"


def test_the_two_loops_share_one_budget():
    """The design decision, and the reason there are two new nodes rather than four.

    A bound per loop would let a change rejected once by the panel and once at acceptance spend
    neither — which is precisely the run that most needs a person.
    """
    mixed = _report("review_failed", "acceptance_failed")
    assert engine._change_retry(mixed) == "again"


def test_acceptance_twice_halts_too():
    """The half of the gap the README did not name."""
    assert engine._change_retry(_report("acceptance_failed", "acceptance_failed")) == "again"


def test_a_pass_is_not_a_rejection():
    passed = _report("lead_review", "qa_verify", "qa_accept", "review_failed")
    assert engine._change_retry(passed) == "first"


def test_a_module_review_is_not_a_whole_change_review():
    """`lead_task_review` and `re_review` judge one module and have their own bound.

    Counting them here would halt a change for module failures that `halt_second_fail` already
    handles, and would do it after one module rather than after the change was rejected.
    """
    modules = _report("fix_pass", "re_review", "fix_pass", "halt_second_fail")
    assert engine._change_retry(modules) == "first"


def test_one_panel_rejection_counts_once_however_many_seats_voted():
    """The defect the first implementation had, kept so it cannot come back.

    That version counted `lead_review` asks answering `fail`, and `lead_review` is a **seat panel**:
    three seats, three asks, **one** rejection. It counted a single panel failure as three and would
    have halted on the first — a bound of one wearing the label of two.

    Counting the node a rejected change routes *through* counts the rejection itself, whatever the
    panel's shape. Its own end-to-end test is what caught it.
    """
    report = engine.RunReport()
    report.visited.extend(["lead_review", "review_failed"])
    for seat in ("conformance", "defect", "risk"):
        report.asks.append(engine.Ask(node_id="lead_review", role="seat", seat=seat,
                                      result={"verdict": "fail"}))
    assert engine._change_retry(report) == "first", "three seats are one rejection"


# ── the shape of the flow ──────────────────────────────────────────────────────────────────────


def test_both_rejection_paths_route_through_the_bound():
    """Either one alone would leave the other loop unbounded, which is how the gap survived."""
    assert graph.BY_ID["review_failed"].next == "change_retry"
    assert graph.BY_ID["acceptance_failed"].next == "change_retry"


def test_the_bound_is_the_only_way_back_into_the_loop_from_a_rejection():
    """Otherwise it is decoration: a path around it is a path that never counts."""
    reaching = [n.id for n in graph.NODES
                if n.next == "next_module" or "next_module" in (n.branches or {}).values()]
    assert "review_failed" not in reaching
    assert "acceptance_failed" not in reaching
    assert "change_retry" in reaching


def test_nobody_is_asked():
    node = graph.BY_ID["change_retry"]
    assert node.role is None, "counting what already happened is not somebody's judgement"
    assert node.gate is None
    assert node.mode == graph.RUNNER
    assert set(node.branches) == {"first", "again"}


def test_the_halt_is_permanent():
    """Declared, not matched on the id — the same rule `validate` enforces for the other two."""
    halt = graph.BY_ID["halt_change_rejected"]
    assert halt.kind == graph.TERMINAL
    assert halt.permanent is True


def test_the_module_bound_is_untouched():
    """This change is about the loop outside the module loop, and must not move that one."""
    assert graph.BY_ID["re_review"].branches["fail"] == "halt_second_fail"
    assert graph.BY_ID["halt_second_fail"].permanent is True


def test_the_module_cycle_did_not_escape_through_the_new_edge():
    """CHG-20260828-15 added one edge and `module_cycle()` silently began returning `merge`, `pr`
    and `lead_review` — the set that decides which nodes run inside a module's worktree.

    The traversal is derived, so a new edge can change it without anybody writing a list down. That
    is the point of deriving it, and the reason this check exists rather than being assumed.
    """
    assert graph.module_cycle() == [
        "engineer_build", "engineer_selfverify", "fix_pass", "lead_task_review", "re_review"]


def test_the_graph_still_validates():
    graph.validate()


# ── driven through a real walk, because the routing is what the bound is ───────────────────────


#: Enough trips round for a rejected change to come back and be rejected again. The engine refuses
#: to guess how a loop ends, so a test about going round twice has to say so.
ROUND_TWICE = {"next_module": ["module", "none", "none", "none", "none", "none"],
               "feedback": "done"}


class Rejecting:
    """A dispatcher that rejects the whole change every time it is asked to judge it.

    `test_flow`'s `Recorder` deliberately cannot do this. It fails `lead_review` on the **first**
    panel only, and says why:

        A panel that fails every time loops forever - `lead_review` routes to `review_failed`,
        which returns to the module loop, which comes straight back - and a test that hits
        `max_steps` proves nothing about the branch it was written for.

    That comment is a workaround for the defect this change fixes, written into a fixture. With the
    bound in place a panel that fails every time **halts**, so rejecting every time is now a thing a
    test can do - and this is the test that had to be able to do it.

    `Recorder` is left alone: other tests depend on its one-failure behaviour, and rewriting a
    shared fixture to suit one new file is how a fixture stops meaning what its users think.
    """

    def __init__(self, reject=("lead_review",), times=None):
        self.reject = set(reject)
        #: How many rejections to give before passing. `None` is "every time", which is the case
        #: that used to loop forever.
        self.times = times
        self.given = 0

    def _rejecting(self) -> bool:
        if self.times is not None and self.given >= self.times:
            return False
        self.given += 1
        return True

    def __call__(self, order):
        node_id = order["node_id"]
        if order.get("seat"):
            if node_id == "intake_review":
                return {"problems": [], "missing": [], "unsafe": []}
            if node_id in self.reject and self._rejecting():
                return {"verdict": "fail"}
            return {"verdict": "pass"}
        if node_id == "engineer_build":
            return {"module": "alpha"}
        if node_id in self.reject and self._rejecting():
            return {"verdict": "fail"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "plan_scope": "single",
                  "lead_task_review": "pass", "re_review": "pass", "qa_accept": "pass"}.get(node_id)
        return {"verdict": branch} if branch else {"ok": True}


def _walk(reject=("lead_review",), times=None, decisions=None):
    """A dry run whose whole-change reviews reject, driven through `engine.walk`."""
    from test_flow import SPEC as FLOW_SPEC

    cfg = engine.RunConfig(
        node_specs={n.id: dict(FLOW_SPEC) for n in graph.NODES if n.role},
        decisions={**ROUND_TWICE, **(decisions or {})}, risk="low", undeclared="allow")
    return engine.walk(cfg, Rejecting(reject, times), enabled=True)


def test_one_panel_rejection_goes_back_into_the_module_loop():
    """Unchanged behaviour: the first trip round is what the flow always did."""
    report = _walk(times=3)     # three seats, one panel
    assert "change_retry" in report.visited
    assert report.halted_at != "halt_change_rejected"


def test_a_panel_that_keeps_failing_halts_instead_of_cycling_to_the_step_cap():
    """The gap, closed. Before this the walk cycled until `walk exceeded 200 steps`."""
    report = _walk()
    assert report.halted_at == "halt_change_rejected"
    assert report.state == engine.STOPPED


def test_an_acceptance_that_keeps_failing_halts_too():
    """The half the README did not name."""
    report = _walk(reject=("qa_accept",))
    assert report.halted_at == "halt_change_rejected"


def test_the_message_says_the_change_was_rejected_not_that_the_runner_gave_up():
    """What the operator reads is the whole point of bounding it rather than letting it cycle."""
    report = _walk()
    said = graph.BY_ID[report.halted_at].label
    assert "rejected" in said.lower(), (
        f"the terminal says {said!r}, which does not tell an operator what happened")


def test_a_run_that_is_never_rejected_still_reaches_the_pull_request():
    """The bound must not stop a change nobody rejected — the failure that would matter most."""
    report = _walk(reject=())
    assert report.halted_at != "halt_change_rejected"
    assert "change_retry" not in report.visited
