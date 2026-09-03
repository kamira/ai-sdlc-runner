"""What the conversation store must refuse, keep, and never lose (CHG-20260823-17).

Every test below is named for a finding one of the two review seats made **on the design, before
this code existed**. Both returned `not sound`; the verdicts are committed whole in
`docs/design/reviews/`. A test written for a finding is the only way the finding survives the change
that answered it.
"""
import csv
import io
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import conversations as conv  # noqa: E402
from ai_sdlc_runner import engine, graph  # noqa: E402


def _store(tmp_path):
    return conv.FileBackend(tmp_path / "conversations")


# ── identity ──────────────────────────────────────────────────────────────────────────────────

def test_a_project_name_is_required_because_a_directory_is_not_an_identity():
    """Both seats refused the first design's default of the plan file's parent directory."""
    for empty in ("", "   ", None):
        with pytest.raises(conv.ConversationError) as exc:
            conv.project_id(empty)
        assert "required" in str(exc.value)


def test_a_project_name_never_becomes_a_path(tmp_path):
    """`attachments.py`'s rule one layer out. A name an operator types can contain anything."""
    back = _store(tmp_path)
    hostile = "../../etc/passwd"
    c = conv.Conversation(back, hostile).open()
    c.close("finished")
    written = list((tmp_path / "conversations").rglob("*.jsonl"))
    assert len(written) == 1
    # Nothing above the root, and no separator survived into a path component.
    assert (tmp_path / "conversations") in written[0].parents
    assert written[0].parent.name == conv.project_id(hostile)
    assert ".." not in str(written[0].relative_to(tmp_path / "conversations"))
    # ...and the name itself is still readable, as data.
    assert c.document()["project"]["name"] == hostile


def test_two_runs_in_one_journal_directory_are_two_conversations(tmp_path):
    """The collision both seats found in `run_id`, which is the journal directory.

    Verified against the journal itself first: two fresh runs leave **one** entry, because ask ids
    are positional and `record` overwrites. That is the source the first design proposed to derive
    from, and it is why this store does not.
    """
    j = tmp_path / "asks"
    first = engine.AskJournal(j)
    first.record("000-pm_plan", "pm_plan", None, {"brief": "FIRST"})
    first.answered("000-pm_plan", {"modules": ["a"]})
    second = engine.AskJournal(j)
    second.record("000-pm_plan", "pm_plan", None, {"brief": "SECOND"})
    assert len(second.entries()) == 1
    assert second.entries()[0]["order"]["brief"] == "SECOND"
    assert first.dir.resolve() == second.dir.resolve()      # one run_id for two runs

    # The store does not inherit that. A fresh journal directory gets its own conversation, and a
    # re-attach to an existing one keeps the first.
    back = _store(tmp_path)
    a = conv.Conversation.resume_or_open(back, "P", j)
    a.instruction("first", 1)
    b = conv.Conversation.resume_or_open(back, "P", j)
    assert b.id == a.id                                      # re-attached, not duplicated
    c = conv.Conversation.resume_or_open(back, "P", tmp_path / "other-asks")
    assert c.id != a.id                                      # a different run is a different one


def test_a_resume_under_a_different_project_is_refused(tmp_path):
    back = _store(tmp_path)
    conv.Conversation.resume_or_open(back, "Login Page", tmp_path / "asks")
    with pytest.raises(conv.ConversationError) as exc:
        conv.Conversation.resume_or_open(back, "Something Else", tmp_path / "asks")
    assert "cannot be two projects" in str(exc.value)


def test_a_run_with_no_journal_still_gets_a_conversation(tmp_path):
    """The one case the first design admitted and then did not handle.

    `run_id` is `None` without a journal, so nothing derived could have existed. Being unresumable
    is a property of the run, not a reason to lose the record of it.
    """
    c = conv.Conversation(_store(tmp_path), "P", journal_dir=None).open()
    c.ask("000-x", "pm_plan", "pm", None, "m", {"brief": "b"})
    c.close("finished")
    assert [t["kind"] for t in c.document()["turns"]] == ["opened", "ask", "closed"]


# ── what a conversation contains ──────────────────────────────────────────────────────────────

def test_an_operator_decision_is_a_turn(tmp_path):
    """The keystone finding. The journal has never had a writer for any of these."""
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.decision("approval", "merge", "looks right")
    c.decision("rejection", "release", "not yet")
    c.decision("ruling", "lead_review", "a person chose 'pass'")
    kinds = [t["kind"] for t in c.document()["turns"]]
    assert kinds.count("decision") == 3
    assert {t.get("decision") for t in c.document()["turns"] if t["kind"] == "decision"} == {
        "approval", "rejection", "ruling"}


def test_the_answering_model_is_recorded(tmp_path):
    """`journal.record` takes no model, so the existing durable record cannot say who answered."""
    import inspect
    assert "model" not in inspect.signature(engine.AskJournal.record).parameters
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.ask("000-x", "engineer_build", "engineer", "defect", "codex-cli", {"brief": "b"})
    ask = [t for t in c.document()["turns"] if t["kind"] == "ask"][0]
    assert ask["model"] == "codex-cli" and ask["seat"] == "defect"


def test_an_ask_that_raised_is_a_turn_of_its_own(tmp_path):
    """"asked and it failed" and "never answered" are different, and a log must not merge them."""
    class Boom(engine.Session):
        def ask(self, order):
            raise RuntimeError("the backend died")

        def close(self):
            pass

    c = conv.Conversation(_store(tmp_path), "P").open()
    with pytest.raises(RuntimeError):
        engine._ask(lambda: Boom(), {"node_id": "x"}, [], ask_id="000-x", node_id="x",
                    conversation=c, role="engineer")
    kinds = [t["kind"] for t in c.document()["turns"]]
    assert kinds == ["opened", "ask", "unanswered"]
    assert "the backend died" in c.document()["turns"][-1]["why"]


def test_seq_is_an_integer_so_the_thousandth_turn_sorts_after_the_hundredth(tmp_path):
    """The journal sorts filenames, and `'%03d' % 1000` lands between the 100th and the 101st.

    Found by a seat reading `AskJournal.entries`; a store presenting "the ordered sequence of turns"
    would have inherited it silently, at a scale where a demo looks fine.
    """
    assert sorted("%03d" % n for n in (100, 101, 1000)) == ["100", "1000", "101"]
    c = conv.Conversation(_store(tmp_path), "P").open()
    for i in range(1100):
        c.note(f"turn {i}")
    seqs = [t["seq"] for t in c.document()["turns"]]
    assert seqs == sorted(seqs) and seqs == list(range(len(seqs)))


def test_a_re_walk_does_not_re_record_one_instruction(tmp_path):
    """`serve` re-walks the whole flow on every approval.

    A log that recorded the instruction each time would be counting walks while claiming to count
    turns — the operator asked once.
    """
    back = _store(tmp_path)
    c = conv.Conversation.resume_or_open(back, "P", tmp_path / "asks")
    for _ in range(4):
        c.instruction("build a login page", 1)
    c.instruction("and add remember-me", 2)
    said = [t for t in c.document()["turns"] if t["kind"] == "instruction"]
    assert [t["nth"] for t in said] == [1, 2]

    # ...and a resumed process knows it too, rather than starting the count again.
    again = conv.Conversation.resume_or_open(back, "P", tmp_path / "asks")
    again.instruction("build a login page", 1)
    assert len([t for t in again.document()["turns"] if t["kind"] == "instruction"]) == 2


def test_a_failed_store_write_never_fails_a_run_and_is_never_silent(tmp_path):
    """Both halves. Either alone is wrong."""
    class Broken(conv.Backend):
        def open_conversation(self, header):
            pass

        def append(self, header, turn):
            raise OSError("the disk is full")

        def read(self, pid, cid):
            return {"turns": []}

    c = conv.Conversation(Broken(), "P").open()
    c.note("something")                                     # does not raise
    assert c.write_errors and "disk is full" in c.write_errors[0]
    # ...and it reaches a person. The first version of this test asserted that a **dict key
    # existed** and called that "never silent" — a coarse check answering safe about something it
    # had not examined, in the test written to prove the opposite. A seat drove the real command on
    # a path over Windows' 260-character limit, lost every turn of a whole conversation, and was
    # told `finished` with no signal at all.
    assert "store_errors" in engine.RunReport().as_dict()


# ── backends ──────────────────────────────────────────────────────────────────────────────────

def test_an_unknown_backend_is_refused_by_name():
    with pytest.raises(conv.ConversationError) as exc:
        conv.backend("postgres")
    assert "unknown store" in str(exc.value)


def test_the_same_seq_is_never_written_twice(tmp_path):
    back = _store(tmp_path)
    c = conv.Conversation(back, "P").open()
    with pytest.raises(conv.ConversationError):
        back.open_conversation(c.header)                     # a conversation id is minted once


def test_a_half_written_line_is_reported_not_dropped(tmp_path):
    """A store that quietly discards its last turn is worse than one that says it is incomplete."""
    back = _store(tmp_path)
    c = conv.Conversation(back, "P").open()
    c.note("good")
    path = list((tmp_path / "conversations").rglob("*.jsonl"))[0]
    with io.open(path, "a", encoding="utf-8") as fh:
        fh.write('{"seq": 99, "kind": "no')                  # a crash mid-write
    doc = back.read(c.project["id"], c.id)
    assert doc["incomplete_lines"] == [4]
    assert [t["kind"] for t in doc["turns"]] == ["opened", "note"]


# ── export ────────────────────────────────────────────────────────────────────────────────────

def _sample(tmp_path, text="hello"):
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.instruction(text, 1)
    c.ask("000-x", "pm_plan", "pm", None, "m", {"brief": text})
    c.answer("000-x", {"modules": ["a"]}, "m")
    c.close("finished")
    return c.document()


def test_an_unknown_format_is_refused_rather_than_defaulted(tmp_path):
    with pytest.raises(conv.ConversationError):
        conv.export_conversation(_sample(tmp_path), "yaml")


def test_json_export_round_trips(tmp_path):
    doc = _sample(tmp_path)
    assert json.loads(conv.export_conversation(doc, "json")) == doc


def test_a_markdown_fence_survives_backticks_in_the_answer(tmp_path):
    """An answer containing ``` ends a three-backtick fence early, and "for reading" is this
    format's whole claim. Found by a seat on the design, before there was anything to break."""
    doc = _sample(tmp_path, text="run ```bash\\nls\\n``` and then ````x````")
    out = conv.export_conversation(doc, "markdown")
    fences = [line for line in out.splitlines() if line.startswith("`") and line.strip("`") in ("", "json")]
    assert any(len(f) - len(f.lstrip("`")) >= 5 for f in fences), fences
    # every fence opens and closes an even number of times
    assert len(fences) % 2 == 0


@pytest.mark.parametrize("leader", ["=", "+", "-", "@", "\t", "\r"])
def test_a_csv_cell_cannot_execute_as_a_formula(tmp_path, leader):
    """`=HYPERLINK(...)` is an exfiltration channel, and this text is model-produced.

    RFC-compliant quoting does not neutralise a formula; a leading apostrophe does. The export's
    stated purpose is to be opened in a spreadsheet, in a project whose standing constraint is
    local-only.
    """
    doc = _sample(tmp_path, text=leader + 'HYPERLINK("http://evil.example","click")')
    rows = list(csv.reader(io.StringIO(conv.export_conversation(doc, "csv"))))
    for row in rows[1:]:
        for cell in row:
            assert cell[:1] not in conv.FORMULA_LEADERS, cell[:40]
    assert any("HYPERLINK" in cell for row in rows for cell in row)   # still present, just defused


def test_csv_flags_the_rows_a_spreadsheet_will_silently_truncate(tmp_path):
    """Excel stops at 32,767 characters and says nothing. The data is written whole and flagged."""
    doc = _sample(tmp_path, text="x" * (conv.SPREADSHEET_CELL_LIMIT + 10))
    rows = list(csv.DictReader(io.StringIO(conv.export_conversation(doc, "csv"))))
    flagged = [r for r in rows if r["over_spreadsheet_cell_limit"] == "yes"]
    assert flagged, "a cell past the limit was not flagged"
    assert len(flagged[0]["body_json"]) > conv.SPREADSHEET_CELL_LIMIT   # whole, not truncated


def test_csv_carries_no_note_row_because_csv_has_no_comments(tmp_path):
    """A note row is a data row to every consumer. The notice lives in the column names."""
    rows = list(csv.reader(io.StringIO(conv.export_conversation(_sample(tmp_path), "csv"))))
    assert rows[0] == list(conv.CSV_COLUMNS)
    assert not any(row and row[0].startswith("#") for row in rows)
    assert any(col.endswith("_json") for col in conv.CSV_COLUMNS)


# ── the wiring ────────────────────────────────────────────────────────────────────────────────

def test_every_turn_kind_the_module_declares_can_actually_be_written(tmp_path):
    """A kind nothing writes is a name with no constraint behind it — the house defect, in a table.

    Driven rather than grepped: a text scan for each constant would pass on the declaration itself,
    which is the thing being doubted.

    `REVIEW` is written by `record_review` rather than by a `Conversation` method, deliberately —
    it is an operator act on a run that has already closed, and putting it on the conversation
    object would put it where a walk could reach it (CHG-20260828-21). It is still driven here,
    because a kind written by *nothing* is exactly what this test exists to refuse.
    """
    store = _store(tmp_path)
    c = conv.Conversation(store, "P").open()                 # opened
    c.instruction("do the thing", 1)
    c.ask("000-x", "pm_plan", "pm", None, "m", {"brief": "b"})
    c.answer("000-x", {"modules": []}, "m")
    c.unanswered("001-x", "the backend died")
    c.decision("approval", "merge", "fine")
    c.relaxation("--store-remote allow")
    c.note("a store write failed")
    c.close("finished",
            change_class="the 'emergency' class, authorised by ops-lead, due for review 2026-12-01")
    conv.record_review(store, c.id, by="ana")

    written = {t["kind"] for t in store.read(conv.project_id("P"), c.id)["turns"]}
    assert written == set(conv.KINDS)


def test_the_engine_records_the_decisions_the_report_records(tmp_path):
    """Every place the report gains an operator decision, the conversation gains a turn.

    Written as a source check rather than a walk because the four sites are on four different
    branches of one gate function, and a test that drove only one of them would have passed while
    three stayed unrecorded — which is exactly how the finding this answers came to exist.
    """
    import inspect
    source = inspect.getsource(engine)
    for appended in ("report.rejections.append", "report.confirmations.append",
                     "report.rulings.append"):
        for i in range(source.count(appended)):
            after = source[source.find(appended) if i == 0 else
                           source.find(appended, source.find(appended) + 1):][:900]
            assert "cfg.conversation.decision(" in after, f"{appended} #{i} records nothing"


# ── round 2: findings on the code ─────────────────────────────────────────────────────────────

def test_a_formula_behind_leading_whitespace_is_still_defused():
    """A cell whose formula sat after a newline was emitted unchanged by the first version."""
    for prefix in ("\n", " ", "\t ", "\r\n  "):
        assert conv._defuse(prefix + "=HYPERLINK(1)").startswith("'")
    assert conv._defuse("ordinary text") == "ordinary text"


def test_markdown_metadata_cannot_forge_document_structure(tmp_path):
    """A project name is operator text and was interpolated straight into the header line."""
    doc = conv.Conversation(_store(tmp_path), "ok\n# FORGED HEADING").open().document()
    out = conv.export_conversation(doc, "markdown")
    headings = [ln for ln in out.splitlines() if ln.startswith("# ")]
    assert headings == [ln for ln in headings if "FORGED" not in ln], headings


def test_a_session_that_fails_to_open_still_records_the_outcome(tmp_path):
    """Three of the four ways an ask can fail were unrecorded, while the README said "each"."""
    def broken_factory():
        raise RuntimeError("no backend")

    c = conv.Conversation(_store(tmp_path), "P").open()
    with pytest.raises(RuntimeError):
        engine._ask(broken_factory, {"node_id": "x"}, [], ask_id="000-x", node_id="x",
                    conversation=c, role="engineer")
    assert [t["kind"] for t in c.document()["turns"]] == ["opened", "ask", "unanswered"]


def test_a_session_handed_back_twice_still_records_the_outcome(tmp_path):
    class Once(engine.Session):
        def ask(self, order):
            return {"ok": True}

        def close(self):
            pass

    shared = Once()
    c = conv.Conversation(_store(tmp_path), "P").open()
    with pytest.raises(engine.EngineError):
        engine._ask(lambda: shared, {"node_id": "x"}, [shared], ask_id="000-x", node_id="x",
                    conversation=c, role="engineer")
    assert c.document()["turns"][-1]["kind"] == "unanswered"


def test_the_backend_that_answered_is_recorded_even_when_no_model_was_asked_for(tmp_path):
    """A seat panel routes by seat and passes no model, so `model` is None for every seat.

    A record that cannot name the answerer has kept the votes and thrown away the thing being voted
    on — which is the finding the `model` field exists for, one level further down.
    """
    class Named(engine.Session):
        def describe(self):
            return "python3 examples/agent.py"

        def ask(self, order):
            return {"verdict": "pass"}

        def close(self):
            pass

    c = conv.Conversation(_store(tmp_path), "P").open()
    engine._ask(lambda: Named(), {"node_id": "x"}, [], seat="defect", ask_id="000-x",
                node_id="x", conversation=c, role="seat")
    answer = [t for t in c.document()["turns"] if t["kind"] == "answer"][0]
    assert answer["model"] is None                    # nothing was routed by model
    assert answer["backend"] == "python3 examples/agent.py"


def test_a_failed_store_write_reaches_stderr_at_the_moment_it_fails(capsys, tmp_path):
    """The first version named three channels in its docstring and wrote to one."""
    class Broken(conv.Backend):
        def open_conversation(self, header):
            pass

        def append(self, header, turn):
            raise OSError("the disk is full")

        def read(self, pid, cid):
            return {"turns": []}

    conv.Conversation(Broken(), "P").open().note("something")
    assert "conversation store failed" in capsys.readouterr().err


def test_a_duplicate_seq_is_reported_where_it_cannot_be_refused(tmp_path):
    """`file` cannot refuse one without a read per append, so the reader says so.

    The design's first version claimed all three backends refused a duplicate — a guarantee two of
    them did not keep. Stating it where it is true beats stating it everywhere.
    """
    back = _store(tmp_path)
    c = conv.Conversation(back, "P").open()
    c.note("first")
    path = list((tmp_path / "conversations").rglob("*.jsonl"))[0]
    with io.open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"seq": 1, "kind": "note", "text": "a second first"}) + "\n")
    assert back.read(c.project["id"], c.id)["duplicate_seqs"] == [1]


def test_a_store_failure_reaches_the_operator_at_the_end_of_a_run_too():
    """Two channels: stderr at the moment of failure, and the report's summary at the end."""
    cli = Path(conv.__file__).with_name("cli.py").read_text(encoding="utf-8")
    assert "store failed:" in cli and "report.store_errors" in cli


def test_a_journal_that_already_had_answers_says_so_rather_than_pretending(tmp_path):
    """Adding --project to a resume stores none of what came before, by design.

    Backfilling would be deriving the conversation from the journal — the thing both round-1
    verdicts refused. So the gap is marked rather than filled or hidden.
    """
    j = tmp_path / "asks"
    older = engine.AskJournal(j)
    older.record("000-pm_plan", "pm_plan", None, {"brief": "before the store existed"})
    older.answered("000-pm_plan", {"modules": ["a"]})

    c = conv.Conversation.resume_or_open(_store(tmp_path), "P", j)
    notes = [t for t in c.document()["turns"] if t["kind"] == "note"]
    assert notes and "already answered" in notes[0]["text"]


def test_a_marker_whose_conversation_is_gone_is_reopened(tmp_path):
    """Found by driving a real project, not by a test.

    `resume_or_open` set `_opened = False` when the store read failed — meaning "so open it" — and
    then returned without opening. Every turn of that run failed with
    `no conversation at ….jsonl to append to`, once per turn, and the whole conversation went to
    stderr instead of to disk.

    No test reached it because every test either starts clean or resumes a store that still has the
    file. A journal that outlives its store is what a real machine produces.
    """
    back = _store(tmp_path)
    journal = tmp_path / "asks"
    first = conv.Conversation.resume_or_open(back, "P", journal)
    first.note("before")
    assert (journal / conv.MARKER).exists()

    for path in (tmp_path / "conversations").rglob("*.jsonl"):
        path.unlink()                                   # the store is gone; the journal is not

    again = conv.Conversation.resume_or_open(back, "P", journal)
    again.note("after")
    assert again.write_errors == [], again.write_errors
    assert [t["kind"] for t in again.document()["turns"]] == ["opened", "note"]
    assert again.id == first.id, "a resumed run must keep the identity its marker names"


# ── html: the waterfall ───────────────────────────────────────────────────────────────────────

def _walked(tmp_path):
    """A conversation shaped like a real run: a loop, three seats, an operator decision."""
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.instruction("build the thing", 1)
    for seat in ("conformance", "defect", "risk"):
        c.ask(f"00-lead_review-{seat}", "lead_review", "seat", seat, None, {"brief": "b"})
        c.answer(f"00-lead_review-{seat}", {"verdict": "pass"}, backend="python3 agent.py")
    for visit in range(2):
        # A review between the builds, because that is what the module loop does — and two builds
        # back to back are correctly **one** stop, which is what the first version of this fixture
        # accidentally tested.
        c.ask(f"1{visit}-engineer_build", "engineer_build", "engineer", None, "opus", {"b": 1})
        c.answer(f"1{visit}-engineer_build", {"module": f"m{visit}"}, "opus")
        c.ask(f"2{visit}-lead_task_review", "lead_task_review", "lead", None, "opus", {"b": 1})
        c.answer(f"2{visit}-lead_task_review", {"verdict": "pass"}, "opus")
    c.decision("approval", "merge", "confirmed")
    c.close("finished")
    return c.document()


def test_the_html_export_makes_one_stop_per_node_visit(tmp_path):
    """A transcript and a spreadsheet both lose the **shape** of a run.

    Grouping consecutive turns by node puts it back: a node revisited is a second stop, not a
    merged one, because collapsing them would hide the loop the waterfall exists to show.
    """
    page = conv.export_conversation(_walked(tmp_path), "html")
    assert page.lstrip().startswith("<!doctype html>")
    assert page.count('class="stop"') < page.count('class="turn')
    assert page.count(">engineer_build") == 2, "a revisited node must be two stops"
    assert "VISIT 2" in page.upper()


def test_an_answer_is_grouped_with_the_ask_it_answers(tmp_path):
    """An `answer` carries `ask_id` and no `node_id`.

    Reading it as its own stop split every pair in two — 53 stops for 55 turns, a list wearing a
    waterfall's markup.
    """
    page = conv.export_conversation(_walked(tmp_path), "html")
    stops = page.count('class="stop"')
    assert stops <= 8, f"{stops} stops for a run with four distinct nodes and one loop"


def test_the_two_voices_are_told_apart(tmp_path):
    """"the model answered" and "a person decided" is the distinction the store exists to keep."""
    page = conv.export_conversation(_walked(tmp_path), "html")
    for voice in ("turn model", "turn operator", "turn runner"):
        assert voice in page, f"{voice} is not marked on the page"
    assert page.count("turn operator") == 2, "the instruction and the decision are both a person's"


def test_the_html_export_escapes_what_a_model_wrote(tmp_path):
    """Answers are model-produced text going into a page. The CSV export defuses formulas for the
    same reason; this one escapes markup."""
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.answer("00-x", {"why": "<script>alert(1)</script> & \"quoted\""}, "m")
    page = conv.export_conversation(c.document(), "html")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_html_is_one_of_the_formats_the_cli_offers():
    assert "html" in conv.FORMATS
    cli_source = Path(conv.__file__).with_name("cli.py").read_text(encoding="utf-8")
    assert "a waterfall down the" in cli_source, "the flag's help must say what html is"


# ── playback: the run as something you press play on ──────────────────────────────────────────

def _at(second, micro=0):
    return f"2026-08-26T10:00:{second:02d}.{micro:06d}+00:00"


def _timed(tmp_path, stamps):
    """A document with the timestamps we want, built directly — the store stamps `at` itself, and
    a test that cannot choose the times cannot test what the times do."""
    turns = []
    for n, stamp in enumerate(stamps):
        turns.append({"seq": n, "kind": conv.ASK, "at": stamp, "node_id": f"n{n}",
                      "ask_id": f"{n:03d}-n{n}", "role": "engineer", "seat": None,
                      "model": "opus", "brief": {}})
    return {"conversation_id": "c1", "project": {"id": "p", "name": "P"}, "turns": turns}


def test_an_instant_run_still_plays_at_a_readable_pace(tmp_path):
    """A stand-in agent answers in milliseconds, and the first real export was **3 seconds for 55
    turns** — accurate, and unwatchable. Every turn gets a floor on the playback clock."""
    document = _timed(tmp_path, [_at(0, m) for m in (0, 1000, 2000, 3000, 4000)])
    page = conv.export_conversation(document, "playback")
    total = float(re.search(r'TOTAL = parseFloat\("([0-9.]+)"\)', page).group(1))
    assert total >= 4 * conv.MIN_BEAT - 0.01, f"{total}s for five turns is not watchable"


def test_a_long_wait_plays_short_and_says_what_it_really_took(tmp_path):
    """The other half of the same honesty: compressed, and named as compressed."""
    document = _timed(tmp_path, [_at(0), _at(40)])
    page = conv.export_conversation(document, "playback")
    total = float(re.search(r'TOTAL = parseFloat\("([0-9.]+)"\)', page).group(1))
    assert total <= conv.IDLE_CAP + 0.01, "forty seconds of waiting became forty of playback"
    assert '"waited": 40.0' in page, "the real duration must reach the page"


def test_relative_duration_survives_the_compression(tmp_path):
    """A slow turn must still read as slower than a fast one, or the replay has flattened the only
    thing it was showing."""
    document = _timed(tmp_path, [_at(0), _at(0, 1000), _at(30)])
    page = conv.export_conversation(document, "playback")
    times = [t["t"] for t in json.loads(re.search(r"const TURNS = (\[.*?\]), RAIL",
                                                  page, re.S).group(1))]
    quick, slow = times[1] - times[0], times[2] - times[1]
    assert slow > quick * 3, f"the slow turn ({slow}) does not read as slower than {quick}"


def test_the_replay_and_the_waterfall_agree_about_the_shape(tmp_path):
    """Two renderings of one run must not disagree about where a stop begins. They share `_stops`
    for exactly this reason; this is the test that keeps them sharing it."""
    document = _walked(tmp_path)
    stops, _ = conv._stops(document["turns"])
    waterfall = conv.export_conversation(document, "html")
    replay = conv.export_conversation(document, "playback")
    rail = json.loads(re.search(r"RAIL = (\[.*?\]), TOTAL", replay, re.S).group(1))
    assert len(rail) == len(stops) == waterfall.count('class="stop"')


def test_a_timestamp_that_will_not_parse_gets_a_beat_not_an_invented_duration(tmp_path):
    """`_seconds` returns None rather than 'now' or zero. A replay whose whole claim is that the
    timings are real must not manufacture one for a turn it cannot read."""
    assert conv._seconds("not a time") is None
    assert conv._seconds("") is None
    document = _timed(tmp_path, [_at(0), "not a time", _at(1)])
    page = conv.export_conversation(document, "playback")
    assert '"waited": null' in page or '"waited":null' in page or "waited" in page


def test_what_a_model_wrote_is_escaped_in_the_replay_too(tmp_path):
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.answer("00-x", {"why": "<img src=x onerror=alert(1)>"}, "m")
    page = conv.export_conversation(c.document(), "playback")
    assert "<img src=x" not in page
    assert "&lt;img" in page or "\u003c" in page


def test_playback_is_one_of_the_formats_the_cli_offers():
    assert conv.FORMATS == ("json", "markdown", "csv", "html", "playback")


def test_an_answer_containing_a_closing_script_tag_cannot_end_the_script_block(tmp_path):
    """The vector the escaping is actually for. `<img …>` inside a JS string is inert; a literal
    `</script>` is not — the HTML parser ends the block there and parses the rest as markup, so an
    answer becomes executable page content. `<!--` opens a comment that eats the rest of the page.

    A model writes these by accident the moment it is asked about HTML, which this project's own
    tide example does.
    """
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.answer("00-x", {"why": "</script><script>alert(1)</script> and <!-- a comment"}, "m")
    page = conv.export_conversation(c.document(), "playback")

    body = page.split("const TURNS =", 1)[1]
    assert "</script><script>" not in body
    assert "<!--" not in body
    assert body.count("</script>") == 1, "the only </script> must be the one that closes the player"
    assert "\u003c/script" in page, "the text is kept, escaped — not dropped"


def test_a_line_separator_in_an_answer_does_not_break_the_script():
    """U+2028 is legal inside a JSON string and a line terminator in JavaScript: unescaped, it ends
    the statement mid-string and the whole player fails to parse."""
    got = conv._script_json({"why": "a\u2028b\u2029c"})
    assert "\u2028" not in got and "\u2029" not in got, "the raw separator reached the page"
    assert "\\u2028" in got and "\\u2029" in got, "escaped, not dropped"


# ── the two backends that were removed (CHG-20260823-35) ──────────────────────────────────────

@pytest.mark.parametrize("kind", ["mongo", "tinydb"])
def test_a_removed_backend_is_refused_by_name_and_told_what_happened_to_it(kind):
    """`unknown store 'mongo'` reads as a typo to someone whose config worked last week.

    The ruling was 「只留 sqlite + file，移除 mongo 和 tinydb」. A backend that is gone must say it is
    gone — the alternative this repository has shipped twice is a setting that quietly stops meaning
    anything.
    """
    with pytest.raises(conv.ConversationError) as caught:
        conv.backend(kind)
    message = str(caught.value)
    assert kind in message
    assert "removed" in message and "CHG-20260823-35" in message
    assert "unknown store" not in message, "a retired kind is not an unknown one"


@pytest.mark.parametrize("kind", sorted(conv.RETIRED))
def test_the_person_who_types_a_removed_backend_is_the_one_who_sees_the_refusal(kind):
    """The test above passes with the CLI wire cut, because it never touches the CLI.

    It did pass with the wire cut, for four days. `--store` was declared `choices=BACKENDS`, and
    argparse checks `choices` before anything the program does, so `runner export --store mongo`
    printed `invalid choice: 'mongo'` — the typo-style message CHG-20260823-35 wrote its refusal to
    avoid — while the refusal itself sat in `backend()` with no CLI path reaching it. The comment
    above the flag said the opposite. Found by the acceptance round of 2026-08-27.

    So this test drives the **CLI**, in a subprocess, which is the only place the defect existed.
    Its sibling above checks the vocabulary; this one checks that a person can reach it.
    """
    import os
    import subprocess

    root = Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli", "export", "--store", kind,
         "--format", "json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root),
        env={**os.environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})

    said = done.stdout + done.stderr
    assert done.returncode != 0, said
    assert "removed" in said and "CHG-20260823-35" in said, said
    assert "invalid choice" not in said, (
        f"argparse refused {kind!r} before the store could say it was removed:{chr(10)}{said}")


def test_every_store_option_goes_through_the_one_checker():
    """One vocabulary, or the next `--store` added somewhere re-opens the same hole.

    Structural on purpose: the defect was a *declaration*, so what has to be pinned is how the
    argument is declared, not what one invocation of it does.
    """
    import ast

    source = (Path(__file__).resolve().parents[1] / "src" / "ai_sdlc_runner" / "cli.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))

    declarations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"):
            continue
        if not any(isinstance(a, ast.Constant) and a.value == "--store" for a in node.args):
            continue
        declarations.append({k.arg: k.value for k in node.keywords})

    assert declarations, "no `--store` argument found; has it been renamed?"
    for keywords in declarations:
        assert "choices" not in keywords, (
            "`--store` is back on `choices=`, which refuses a retired backend before the "
            "refusal that explains it can run")
        checker = keywords.get("type")
        assert isinstance(checker, ast.Name) and checker.id == "_store_kind", (
            "`--store` must resolve its kind through `_store_kind`")


def test_an_actually_unknown_store_is_still_refused_and_never_defaulted():
    """The oldest mistake in this repository is 'I asked for X and got a directory'. It stays
    refused now that there is only one backend to fall back to."""
    with pytest.raises(conv.ConversationError) as caught:
        conv.backend("postgres")
    assert "unknown store" in str(caught.value)


def test_nothing_reaches_for_the_removed_packages():
    """A removal that leaves the import behind is not a removal."""
    source = Path(conv.__file__).read_text(encoding="utf-8")
    for banned in ("import pymongo", "from tinydb", "import tinydb", "MongoClient"):
        assert banned not in source, f"{banned} survives the removal"


def test_the_locality_flags_went_with_the_backend_that_needed_them():
    """`--store-uri` and `--store-remote` existed only for Mongo. With no store that can be off this
    machine there is no locality to relax, and a flag that no longer changes anything is exactly the
    'looks configured and does nothing' this repository refuses everywhere else.

    Asked of the **parser**, not of the source: the first version grepped `cli.py` and failed on
    the comment explaining why the flags are gone. That is the third time this session a check has
    read vocabulary instead of the thing it claims.
    """
    from ai_sdlc_runner import cli

    parser = cli.build_parser()
    known = {action.dest for action in parser._actions}
    for subparser in [a for a in parser._actions if hasattr(a, "choices") and a.choices]:
        for sub in (subparser.choices or {}).values():
            if hasattr(sub, "_actions"):
                known |= {action.dest for action in sub._actions}

    assert "store_uri" not in known and "store_remote" not in known
    assert "store_root" in known, "the flag that still means something must still be there"


def test_a_duplicate_seq_is_reported_and_the_docstring_no_longer_claims_it_is_refused(tmp_path):
    """The one guarantee this removal genuinely weakened, tested as it now stands.

    Mongo's unique index and TinyDB's check did refuse a duplicate at write time. Both are gone, so
    detection is at read time and nothing prevents the write. The module says so; this asserts the
    behaviour rather than the sentence.
    """
    back = _store(tmp_path)
    c = conv.Conversation(back, "P").open()
    c.note("one")
    path = next((tmp_path / "conversations").rglob("*.jsonl"))
    with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"seq": 1, "kind": "note", "at": "2026-08-26T00:00:00+00:00",
                             "text": "a duplicate nobody refused"}) + "\n")

    document = conv.Conversation(back, "P", conversation_id=c.id).document()
    assert document.get("duplicate_seqs") == [1], "the reader must report what the writer allowed"


# ── the log must be readable without pressing play (CHG-20260823-39) ──────────────────────────

def test_every_turn_is_in_the_page_at_load_not_only_after_playing(tmp_path):
    """The replay rendered only the turns up to the clock, and the clock starts at zero — so opening
    it showed **one** turn while 305 sat in the payload, invisible. A reader concluded the responses
    had not been recorded, which is a fair reading of a page showing one line.

    A recording has to be a readable log first and a replay second.

    The cards are built by the page's own script at load, so they are not in the served markup and
    pytest has no engine to run it — the DOM count (306 of 306, against the demo fixture) was
    verified in a browser. What is checkable here is the two halves that were actually wrong: every
    turn reaches the payload, and the builder walks the **whole array** rather than a clock-bounded
    slice.
    """
    document = _walked(tmp_path)
    page = conv.export_conversation(document, "playback")

    payload = json.loads(re.search(r"const TURNS = (\[.*?\]), RAIL", page, re.S).group(1)
                         .replace("\\u003c", "<").replace("\\u003e", ">"))
    assert len(payload) == len(document["turns"]), "a turn never reached the page"

    builder = page.split("function build()", 1)[1].split("function draw()", 1)[0]
    assert "TURNS.forEach" in builder, "the builder must walk every turn"
    assert "<= n" not in builder, "the builder is bounded by the clock again"


def test_the_clock_dims_what_is_ahead_rather_than_hiding_it(tmp_path):
    page = conv.export_conversation(_walked(tmp_path), "playback")
    assert ".turn.ahead{opacity" in page, "turns ahead of the clock must be dimmed, not absent"
    assert "classList.toggle('ahead'" in page


def test_a_turn_can_be_clicked_to_move_the_clock_to_it(tmp_path):
    """Reading and replaying should be one surface, not two."""
    page = conv.export_conversation(_walked(tmp_path), "playback")
    assert "stage.addEventListener('click'" in page
    assert "data-i=" in page


# ── an answer's line has to say what came back ────────────────────────────────────────────────

def test_an_answer_that_found_nothing_says_so_rather_than_just_answered(tmp_path):
    """`{"missing": [], "problems": [], "unsafe": []}` means "nothing wrong" — the commonest review
    answer there is. It rendered as the bare word "answered", so a log of 150 lines said "answered"
    150 times and told a reader nothing."""
    turn = {"kind": conv.ANSWER, "result": {"missing": [], "problems": [], "unsafe": []}}
    assert conv._summary(turn) == "nothing missing, problems, unsafe"


def test_an_answer_that_found_something_names_it(tmp_path):
    turn = {"kind": conv.ANSWER, "result": {"missing": ["a done-criterion"], "problems": []}}
    assert "a done-criterion" in conv._summary(turn)


def test_a_verdict_carries_its_reason_where_there_is_one(tmp_path):
    turn = {"kind": conv.ANSWER, "result": {"verdict": "pass", "why": "read the brief"}}
    got = conv._summary(turn)
    assert "pass" in got and "read the brief" in got


def test_the_opened_turn_is_not_a_blank_line(tmp_path):
    """It has no `text` and no `why`, so it fell through to "" — and it is the first card anybody
    sees."""
    assert conv._summary({"kind": conv.OPENED, "project": "P"}).strip()
    assert conv._summary({"kind": conv.OPENED}).strip()


def test_no_turn_in_a_real_run_renders_a_blank_summary(tmp_path):
    """The general form. A card with an empty line is a card that says nothing happened."""
    for turn in _walked(tmp_path)["turns"]:
        assert conv._summary(turn).strip(), f"turn {turn['seq']} ({turn['kind']}) summarises to ''"


# --------------------------------------------------------------------------------------
# the clock (CHG-20260827-05)
# --------------------------------------------------------------------------------------

def test_a_turn_is_stamped_to_the_millisecond(tmp_path):
    """CHG-20260823-40 said the resolution was "asserted both ways". Nothing asserted it.

    That change's own commit touched only `tests/test_paths.py` under `tests/`, so no test for the
    clock was ever written — and reverting `_now()` to `timespec="seconds"` left 147 conversation,
    demo and recording tests green. An acceptance-round verifier did exactly that and reported it.

    The forward direction, which nothing guarded: a turn written now carries milliseconds. The
    reason it matters is the reason the change was made — two turns in the same second are
    indistinguishable at second resolution, and the committed fixture has stretches of them.
    """
    c = conv.Conversation(_store(tmp_path), "P", journal_dir=None).open()
    c.note("first")
    c.note("second")
    c.close("finished")

    stamps = [t["at"] for t in c.document()["turns"]]
    for at in stamps:
        seconds, _, fraction = at.partition("+")[0].rpartition(".")
        assert seconds, f"{at!r} carries no fractional second at all"
        assert len(fraction) == 3, f"{at!r} is not stamped to the millisecond"


def test_a_turn_stored_at_second_resolution_still_loads(tmp_path):
    """The backward direction, deliberately rather than by accident.

    It was covered only as a side effect of a test about duplicate `seq` that happened to use a
    second-resolution stamp. A compatibility path exercised by coincidence is one that disappears
    the day the unrelated test is rewritten.
    """
    from datetime import datetime

    back = _store(tmp_path)
    c = conv.Conversation(back, "P", journal_dir=None).open()
    c.note("written now")
    c.close("finished")

    document = c.document()
    old = "2026-08-26T00:00:00+00:00"
    document["turns"][0]["at"] = old

    # It must parse, and it must parse to the moment it spells — not merely fail to raise.
    assert datetime.fromisoformat(old).year == 2026
    rendered = conv.export_conversation(document, "markdown")
    assert old.split("T")[0] in rendered, "a second-resolution stamp vanished from the export"


def test_a_node_name_reaching_the_rail_cannot_end_the_script_block(tmp_path):
    """The replay writes **two** script payloads and only one of them was guarded.

    `_script_json` is called for `__TURNS__` and for `__RAIL__`. The test above covers the first.
    Removing the call from the second left all 81 conversation and recording tests green — found by
    an acceptance-round verifier who cut it and looked, and recorded as CHG-20260827-06.

    The rail carries node names rather than model prose, so the exposure is smaller than the one
    the sibling test guards. It is still the second emitter in the change whose whole subject was
    unguarded emitters, and "smaller" is not a reason for a payload to go unchecked.
    """
    hostile = "build</script><script>alert(1)</script>"
    c = conv.Conversation(_store(tmp_path), "P").open()
    c.ask("00-x", hostile, "engineer", None, "m", {"brief": "b"})
    page = conv.export_conversation(c.document(), "playback")

    # `const TURNS = …, RAIL = …` is one statement, so the rail is what follows `, RAIL = ` up to
    # the end of that line — not a block of its own.
    rail = page.split(", RAIL = ", 1)[1].split("\n", 1)[0]
    assert hostile not in rail, "the node name reached the rail payload unescaped"
    assert "</script><script>" not in rail
    # And the name is still *there*, escaped — a rail that solved this by dropping the node would
    # pass the assertions above and show the reader nothing.
    assert "alert(1)" in rail


def test_a_turn_body_cannot_rewrite_its_own_envelope(tmp_path):
    """CHG-20260823-21's headline refusal, which nothing tested until CHG-20260827-07.

    It fires — an acceptance-round verifier confirmed that by constructing the input and watching
    the error. That is evidence it works today and none at all that it will still be called
    tomorrow, which is the difference between a mechanism and a tested one.

    The check sits deliberately **outside** `_guarded`: a body colliding with the envelope is a bug
    in the caller, not a disk that filled up, and swallowing it into `write_errors` would let a run
    carry on having never stored the turn.
    """
    c = conv.Conversation(_store(tmp_path), "P").open()

    # `kind` is the signature's own positional parameter, so a body carrying it never reaches the
    # check -- Python refuses the call first. Worth asserting rather than assuming: it is the
    # reason this loop covers two of the three envelope names and not all three.
    with pytest.raises(TypeError):
        c.turn("note", kind="something else")

    reachable = [f for f in conv.Turn.ENVELOPE if f != "kind"]
    assert reachable, "the envelope has no field reachable through turn(); has the API changed?"
    for field in sorted(reachable):
        with pytest.raises(conv.ConversationError) as caught:
            c.turn("note", **{field: 999})
        message = str(caught.value)
        assert field in message, f"the refusal does not name {field!r}: {message}"
    # The conversation is still usable: a refused turn is refused, not a poisoned store.
    c.note("after the refusals")
    assert [t["kind"] for t in c.document()["turns"]] == ["opened", "note"]


# ── a refusal that points at a superseded store, and a count of one that is two ────────────────


def test_backends_is_not_described_as_a_tuple_of_one():
    """`BACKENDS = ("sqlite", "file")` has two, and the comment directly above it said one.

    A sentence that counts the line under it is worth reading against the line (CHG-20260903-32).
    """
    source = Path(conv.__file__).read_text(encoding="utf-8")

    assert "tuple of one" not in source or len(conv.BACKENDS) == 1


def test_the_retired_store_refusal_does_not_send_the_operator_to_a_superseded_store():
    """`RETIRED["mongo"]` told a stranded user that conversations live *"in the file store"*.

    `--store`'s own help says `sqlite` **is** the store since CHG-20260823-41 and `file` is *"the
    JSONL layout that came before it"*. The refusal exists so a config field that stops working
    gets better than `unknown store 'mongo'` — and it pointed at the store that was itself replaced.
    """
    said = conv.RETIRED["mongo"]

    assert "conversations in the file store" not in said
    assert "CHG-20260823-41" in said, "the message must name what actually replaced it"
