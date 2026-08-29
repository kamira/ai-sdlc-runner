"""An emergency run was marked and then nothing chased it (CHG-20260828-21).

`CHG-20260827-20` guard 5: *"Emergency runs are marked and queued for review; nothing marks itself
emergency."* Marked was done. **Queued** was not, and that record named the gap rather than ticking
the task — `policy.ChangeClass` carries `reviewed_after=True` for `emergency` and nothing read it.

An emergency class relaxes a `confirm` to `auto`: a person who would have been asked was not, on the
promise that somebody looks afterwards. A promise nobody is reminded of is not a promise.

The queue is **derived** from the runs themselves rather than kept beside them, because a second
list of outstanding reviews would be a second source of truth about one fact — the shape
CHG-20260828-17 was spent on.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_sdlc_runner import conversations as conv  # noqa: E402

EMERGENCY = "the 'emergency' class, authorised by ops-lead, due for review on 2026-12-01"
STANDARD = "the 'standard' class, authorised by ops-lead, due for review on 2026-12-01"


@pytest.fixture
def store(tmp_path):
    return conv.backend("sqlite", root=str(tmp_path / "store"))


def _run(store, project="acme", change_class=EMERGENCY, state="finished"):
    """One finished run in the store, closed under the given class."""
    conversation = conv.Conversation(store, project)
    conversation.open()
    conversation.note("did some work")
    conversation.close(state, change_class=change_class)
    return conversation.id


def test_a_run_that_proceeded_under_emergency_is_in_the_queue(store):
    cid = _run(store)
    waiting = conv.outstanding(store)
    assert [run["conversation_id"] for run in waiting] == [cid]
    assert waiting[0]["change_class"] == EMERGENCY


def test_an_ordinary_run_is_not(store):
    _run(store, change_class="nothing was declared")
    assert conv.outstanding(store) == []


def test_a_standard_class_run_is_not(store):
    """`standard` relaxes too, and is explicitly `reviewed_after=False`.

    It is the class whose *type* a person assessed in advance; there is no after-the-fact obligation
    to chase, and putting one in the queue would ask for a review nobody promised.
    """
    _run(store, change_class=STANDARD)
    assert conv.outstanding(store) == []


def test_the_word_emergency_in_prose_does_not_queue_a_run(store):
    """`change_class` holds a sentence, so the match is on the quoted class name and nothing else.

    Matching the bare word anywhere would queue a run whose reason merely mentioned it — the
    name-standing-in-for-a-constraint mistake this repository keeps finding.
    """
    _run(store, change_class="nothing was declared; the emergency was averted before the run")
    assert conv.outstanding(store) == []


def test_recording_a_review_takes_the_run_out_of_the_queue(store):
    cid = _run(store)
    conv.record_review(store, cid, by="ana")

    assert conv.outstanding(store) == []
    everything = conv.emergency_runs(store)
    assert [run["reviewed_by"] for run in everything] == ["ana"]


def test_the_review_is_a_turn_in_the_run_it_reviews(store):
    """Not a separate file. The run and the record of somebody looking at it belong in one place."""
    cid = _run(store)
    conv.record_review(store, cid, by="ana", note="checked the diff; the relaxation was warranted")

    document = store.read(conv.project_id("acme"), cid)
    reviews = [t for t in document["turns"] if t["kind"] == conv.REVIEW]
    assert len(reviews) == 1
    assert reviews[0]["by"] == "ana"
    assert "warranted" in reviews[0]["note"]
    assert reviews[0]["seq"] > 1, "the review must come after the run it reviews"


def test_a_review_that_names_nobody_is_refused(store):
    """The rule `class_in_force` applies to `authorised_by`, applied to signing the thing off."""
    cid = _run(store)
    with pytest.raises(conv.ConversationError) as caught:
        conv.record_review(store, cid, by="   ")
    assert "name who did it" in str(caught.value)
    assert conv.outstanding(store), "a refused review must not empty the queue"


def test_reviewing_a_run_that_was_never_an_emergency_is_refused(store):
    """Otherwise the queue empties by reviewing anything at all."""
    cid = _run(store, change_class="nothing was declared")
    with pytest.raises(conv.ConversationError) as caught:
        conv.record_review(store, cid, by="ana")
    assert "no emergency run" in str(caught.value)


def test_reviewing_a_run_that_does_not_exist_is_refused(store):
    with pytest.raises(conv.ConversationError):
        conv.record_review(store, "no-such-conversation", by="ana")


def test_a_second_review_is_refused_and_names_the_first(store):
    """The useful question after "was this reviewed?" is "by whom", so the refusal answers it."""
    cid = _run(store)
    conv.record_review(store, cid, by="ana")
    with pytest.raises(conv.ConversationError) as caught:
        conv.record_review(store, cid, by="bo")

    said = str(caught.value)
    assert "already reviewed by ana" in said
    document = store.read(conv.project_id("acme"), cid)
    assert len([t for t in document["turns"] if t["kind"] == conv.REVIEW]) == 1


def test_the_queue_can_be_read_for_one_project(store):
    first = _run(store, project="acme")
    _run(store, project="other")
    for_acme = conv.outstanding(store, conv.project_id("acme"))
    assert [run["conversation_id"] for run in for_acme] == [first]


def test_a_halted_emergency_run_is_still_queued(store):
    """It relaxed a gate before it stopped. How the run ended does not undo what it skipped."""
    cid = _run(store, state="stopped")
    assert [run["conversation_id"] for run in conv.outstanding(store)] == [cid]


def test_review_is_a_known_turn_kind(store):
    """`turn` refuses a kind nobody declared, so a new one has to be added to `KINDS` as well."""
    assert conv.REVIEW in conv.KINDS


def test_nothing_in_a_work_order_can_reach_a_review():
    """The axiom that made `emergency` operator-only, applied to signing it off.

    An answer that could record its own review would be a model granting itself an exemption and
    then approving it. The check is that no work-order field carries the review vocabulary at all —
    `plan.check` refuses unknown keys, so a field that does not exist cannot be supplied.
    """
    from ai_sdlc_runner import workorder
    fields = set(getattr(workorder, "FIELDS", ()))
    assert not fields & {"review", "reviewed", "reviewed_by", "emergency_review"}, (
        "a work order carries a review field, so a dispatched agent could close its own emergency")


# ── through the real command line, because that is the only way in ────────────────────────────


def _cli(tmp_path, command, *argv):
    """The store flags belong to the subcommand, not to `runner` — `_store_flags` adds them there."""
    from ai_sdlc_runner import cli
    return cli.main([command, "--store", "sqlite", "--store-root", str(tmp_path / "store"), *argv])


def test_the_command_lists_what_is_outstanding(tmp_path, capsys):
    store = conv.backend("sqlite", root=str(tmp_path / "store"))
    cid = _run(store)

    assert _cli(tmp_path, "emergencies") == 0
    said = capsys.readouterr().out
    assert cid in said
    assert "OUTSTANDING" in said
    assert "authorised by ops-lead" in said, "the queue must say who authorised the class"


def test_the_command_says_so_when_the_queue_is_empty(tmp_path, capsys):
    conv.backend("sqlite", root=str(tmp_path / "store"))
    assert _cli(tmp_path, "emergencies") == 0
    assert "waiting for review" in capsys.readouterr().out


def test_a_review_recorded_through_the_command_closes_the_entry(tmp_path, capsys):
    store = conv.backend("sqlite", root=str(tmp_path / "store"))
    cid = _run(store)

    assert _cli(tmp_path, "emergencies", "--reviewed", cid, "--by", "ana") == 0
    assert "reviewed by ana" in capsys.readouterr().out

    assert _cli(tmp_path, "emergencies") == 0
    assert "no emergency runs are waiting" in capsys.readouterr().out


def test_reviewing_without_a_name_fails_the_command(tmp_path, capsys):
    """A refusal has to be an exit code, not only a sentence: this is scriptable."""
    store = conv.backend("sqlite", root=str(tmp_path / "store"))
    cid = _run(store)

    assert _cli(tmp_path, "emergencies", "--reviewed", cid) == 2
    assert "name who did it" in capsys.readouterr().out
    assert conv.outstanding(store), "a failed review must leave the entry in the queue"


def test_all_shows_the_reviewed_ones_and_who_reviewed_them(tmp_path, capsys):
    store = conv.backend("sqlite", root=str(tmp_path / "store"))
    cid = _run(store)
    conv.record_review(store, cid, by="ana")

    assert _cli(tmp_path, "emergencies", "--all") == 0
    said = capsys.readouterr().out
    assert cid in said and "reviewed by ana" in said


def test_a_finishing_run_says_what_is_outstanding(tmp_path, capsys):
    """The chasing. A queue nobody is shown is the original defect one step further in."""
    from ai_sdlc_runner import cli
    store = conv.backend("sqlite", root=str(tmp_path / "store"))
    cid = _run(store)

    args = argparse.Namespace(store="sqlite", store_root=str(tmp_path / "store"))
    cli._chase_emergencies(args)
    said = capsys.readouterr().out
    assert cid in said
    assert "waiting for review" in said
    assert "runner emergencies --reviewed" in said, "it must say how to clear it"


def test_the_chasing_says_nothing_when_there_is_nothing_to_chase(tmp_path, capsys):
    from ai_sdlc_runner import cli
    conv.backend("sqlite", root=str(tmp_path / "store"))
    cli._chase_emergencies(argparse.Namespace(store="sqlite", store_root=str(tmp_path / "store")))
    assert capsys.readouterr().out == ""


def test_a_store_that_will_not_open_does_not_fail_the_run_that_just_succeeded(tmp_path, capsys):
    """A reminder about a previous run is not a reason to fail this one."""
    from ai_sdlc_runner import cli
    cli._chase_emergencies(argparse.Namespace(store="not-a-store", store_root=str(tmp_path)))
    assert capsys.readouterr().out == ""


def test_a_real_run_says_what_is_outstanding_when_it_finishes(tmp_path, py_stub, capsys):
    """Through `cmd_run`, not by calling the helper.

    The mutation that removes the call from `cmd_run` is only caught by a test that goes through
    `cmd_run`. A test calling `_chase_emergencies` directly asserts the helper works and says
    nothing about whether anything invokes it — which is the defect a mutation found in this
    repository once already, on the dispatch-depth bound.
    """
    import json
    from ai_sdlc_runner import cli
    from test_cli import AGENT, _plan_file                # the established end-to-end stub

    root = tmp_path / "store"
    stranded = _run(conv.backend("sqlite", root=str(root)))

    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    capsys.readouterr()

    cli.main(["--config", str(config), "run", "--undeclared", "allow",
              "--plan", _plan_file(tmp_path), "--confirm", "merge",
              "--store", "sqlite", "--store-root", str(root)])

    said = capsys.readouterr().out
    assert "waiting for review" in said, "a finished run said nothing about the queue"
    assert stranded in said


def test_the_export_files_a_review_under_the_person_who_did_it(store):
    """Not under the runner. The defect CHG-20260828-03 fixed for relaxations, one kind over.

    `_VOICES` had no entry for `REVIEW`, so `_voice_of` fell through to its default and an export
    attributed somebody's sign-off to the machine — in a document whose whole purpose is keeping
    the model's side and the person's side apart. Found by writing the line in `docs/SCHEMAS.md`
    that says which voice it is, and then checking whether that was true.
    """
    cid = _run(store)
    conv.record_review(store, cid, by="ana", note="looked at the diff")

    document = store.read(conv.project_id("acme"), cid)
    review = next(t for t in document["turns"] if t["kind"] == conv.REVIEW)
    who, verb = conv._voice_of(review)
    assert who == "operator", "a person's review was filed under the runner"
    assert verb == "reviewed"

    markdown = conv.export_conversation(document, "markdown")
    assert "ana" in markdown, "the export must name who reviewed it"
