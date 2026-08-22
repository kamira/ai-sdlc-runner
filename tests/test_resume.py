"""Resuming an interrupted run (CHG-20260823-07).

The requirement asked for this in one sentence: *在最糟的情況下也要能保留詢問的內容待下次恢復時再詢問*
— preserve the question so it can be re-asked on recovery.

Preserving was built. **Re-asking on recovery was not.** `AskJournal.pending()` was only ever
printed; a second run restarted from `intake` and asked everything again, overwriting the same
files. And a test called `test_what_was_already_answered_is_not_re_asked` sat in `test_flow.py`
asserting that statuses had been *written* — not that anything was skipped.

That is the sharpest example this repo has produced of a test named for a behaviour nobody built.
It passed for four rounds of review. A verifier found it by reading the caller, not the test.

So this file tests the thing the name claims:

* an interrupted run leaves answered work behind, and a resumed run **does not open a session for
  it** — counted, not asserted vaguely;
* the pending question is asked again, verbatim;
* resuming is a **decision**: without `resume=True`, a journal that happens to exist changes
  nothing, because a run silently continuing somebody else's is worse than one starting over.
"""
from __future__ import annotations

import pytest

from ai_sdlc_runner import engine, graph

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}


def _answer(order):
    if order.get("seat"):
        return {"verdict": "pass"}
    branch = ANSWERS.get(order["node_id"])
    return {"verdict": branch} if branch else {"ok": True}


class _Counting:
    """A factory that records every ask it is actually asked to open a session for."""

    def __init__(self, fail_at=None):
        self.asked, self.opened, self._fail_at = [], 0, fail_at

    def __call__(self, seat=None):
        outer = self
        outer.opened += 1

        class _S:
            def ask(self, order):
                if outer._fail_at is not None and len(outer.asked) == outer._fail_at:
                    raise RuntimeError("session lost")
                outer.asked.append(order["node_id"])
                return _answer(order)

            def close(self):
                pass

        return _S()


def _cfg(journal, **kw):
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions={"next_module": ["module", "none"], "feedback": "done"},
                risk="low", undeclared="allow", confirmed=("merge",), journal=journal)
    base.update(kw)
    return engine.RunConfig(**base)


def _interrupt(tmp_path, at=5):
    """Run until the session drops, and hand back the journal it left."""
    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(RuntimeError):
        engine.walk(_cfg(journal), _Counting(fail_at=at), enabled=True)
    return journal


# --------------------------------------------------------------------------------------
# the interrupted run leaves something to resume from
# --------------------------------------------------------------------------------------

def test_an_interrupted_run_leaves_its_answers_and_one_open_question(tmp_path):
    journal = _interrupt(tmp_path)
    assert len(journal.answers()) == 5
    assert len(journal.pending()) == 1


def test_the_open_question_is_kept_whole_not_summarised(tmp_path):
    """A reconstructed approximation of a question is a different question."""
    journal = _interrupt(tmp_path)
    order = journal.pending()[0]["order"]
    from ai_sdlc_runner import workorder

    assert sorted(order) == sorted(workorder.WORK_ORDER_FIELDS)


# --------------------------------------------------------------------------------------
# resuming actually skips
# --------------------------------------------------------------------------------------

def test_a_resumed_run_does_not_open_a_session_for_answered_work(tmp_path):
    """The whole point, counted. Before this existed the number below was 14."""
    journal = _interrupt(tmp_path)
    already = len(journal.answers())

    second = _Counting()
    report = engine.walk(_cfg(journal, resume=True), second, enabled=True)

    assert report.halted_at == "done"
    assert len(report.resumed) == already
    assert second.opened == len(report.asks) - already


def test_the_answers_reused_are_the_ones_that_were_recorded(tmp_path):
    journal = _interrupt(tmp_path)
    recorded = journal.answers()

    report = engine.walk(_cfg(journal, resume=True), _Counting(), enabled=True)
    for ask_id in report.resumed:
        assert ask_id in recorded


def test_the_pending_question_is_asked_again(tmp_path):
    journal = _interrupt(tmp_path)
    pending_node = journal.pending()[0]["node_id"]

    second = _Counting()
    engine.walk(_cfg(journal, resume=True), second, enabled=True)
    assert pending_node in second.asked


def test_a_resumed_run_finishes_the_flow(tmp_path):
    journal = _interrupt(tmp_path)
    assert engine.walk(_cfg(journal, resume=True), _Counting(), enabled=True).halted_at == "done"


def test_resuming_twice_is_a_no_op_the_second_time(tmp_path):
    """Idempotence: once a run has completed, resuming it re-asks nothing at all."""
    journal = _interrupt(tmp_path)
    engine.walk(_cfg(journal, resume=True), _Counting(), enabled=True)

    third = _Counting()
    report = engine.walk(_cfg(journal, resume=True), third, enabled=True)
    assert third.opened == 0
    assert len(report.resumed) == len(report.asks)


# --------------------------------------------------------------------------------------
# resuming is a decision, not a side effect of a directory existing
# --------------------------------------------------------------------------------------

def test_without_resume_a_journal_that_exists_changes_nothing(tmp_path):
    """A run that silently continues somebody else's because a directory happened to be there is
    worse than one that starts over: the second is merely wasteful, the first is a lie about what
    was asked."""
    journal = _interrupt(tmp_path)
    second = _Counting()
    report = engine.walk(_cfg(journal), second, enabled=True)

    assert report.resumed == []
    assert second.opened == len(report.asks)


def test_resume_without_a_journal_is_refused():
    """Nothing to resume from, and continuing would silently re-ask everything while claiming to
    have resumed."""
    cfg = engine.RunConfig(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                           decisions={}, resume=True)
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(cfg, _Counting(), enabled=True)
    assert "needs a journal" in str(exc.value)


def test_the_report_says_how_much_was_resumed(tmp_path):
    journal = _interrupt(tmp_path)
    report = engine.walk(_cfg(journal, resume=True), _Counting(), enabled=True)
    assert report.as_dict()["resumed"] == report.resumed
    assert report.resumed


# --------------------------------------------------------------------------------------
# a resumed ask is not a session
# --------------------------------------------------------------------------------------

def test_a_resumed_ask_never_touches_the_factory(tmp_path):
    """Not "opens and closes quickly" — never opens. The one-session rule is about sessions that
    exist, and a question answered from disk did not need one."""
    journal = _interrupt(tmp_path)

    class _Explode:
        def __call__(self, seat=None):
            raise AssertionError("a resumed ask opened a session")

    # Complete the run first so every ask is answered, then resume with a factory that refuses.
    engine.walk(_cfg(journal, resume=True), _Counting(), enabled=True)
    report = engine.walk(_cfg(journal, resume=True), _Explode(), enabled=True)
    assert report.halted_at == "done"
