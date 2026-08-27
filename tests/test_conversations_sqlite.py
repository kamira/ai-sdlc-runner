"""The conversation store in the database (CHG-20260823-41).

`test_conversations.py` covers what a conversation must refuse, keep and never lose — against the
JSONL backend, which is where all of it was written. This covers what changes when the same
contract is served by SQLite, and the one guarantee that only the database can give.
"""
import io
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import conversations as conv  # noqa: E402
from ai_sdlc_runner import store as store_mod  # noqa: E402


def _sqlite(tmp_path):
    return conv.backend("sqlite", root=tmp_path / "store")


def _file(tmp_path):
    return conv.backend("file", root=tmp_path / "legacy")


# ── the guarantee the file store could not give ───────────────────────────────────────────────

def test_a_duplicate_turn_is_refused_at_the_write_not_reported_at_the_read(tmp_path):
    """CHG-20260823-35 had to record that a duplicate `seq` was "reported and refused nowhere" once
    Mongo and TinyDB were removed. `PRIMARY KEY (conversation_id, seq)` refuses it again — and this
    time the refusal is enforced by the database rather than by a convention.
    """
    back = _sqlite(tmp_path)
    c = conv.Conversation(back, "P").open()
    c.note("one")

    header = c.document()
    header = {k: v for k, v in header.items() if k != "turns"}
    with pytest.raises(conv.ConversationError) as caught:
        back.append(header, conv.Turn(seq=1, kind=conv.NOTE, at=conv._now(), body={"text": "again"}))
    assert "already exists" in str(caught.value)
    assert "refuses the write" in str(caught.value), "the message must say what changed"


def test_a_turn_cannot_belong_to_no_conversation(tmp_path):
    """The foreign key — which bites only because `store.connect` sets `PRAGMA foreign_keys = ON`.
    It is per-connection and OFF by default, so the declaration alone would enforce nothing."""
    back = _sqlite(tmp_path)
    ghost = {"conversation_id": "nope", "project": {"id": "p", "name": "P"}}
    with pytest.raises(conv.ConversationError) as caught:
        back.append(ghost, conv.Turn(seq=0, kind=conv.NOTE, at=conv._now(), body={"text": "x"}))
    assert "no conversation" in str(caught.value)


def test_foreign_keys_are_actually_on_for_this_connection(tmp_path):
    """Asserted directly, because the pragma being off is invisible: every insert succeeds and the
    orphan is only found much later, by a reader."""
    back = _sqlite(tmp_path)
    assert back.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reopening_a_conversation_id_is_refused(tmp_path):
    back = _sqlite(tmp_path)
    c = conv.Conversation(back, "P").open()
    header = {k: v for k, v in c.document().items() if k != "turns"}
    with pytest.raises(conv.ConversationError) as caught:
        back.open_conversation(header)
    assert "minted once" in str(caught.value)


# ── the same contract as the file store ───────────────────────────────────────────────────────

def test_the_document_is_the_same_shape_from_either_backend(tmp_path):
    """Two backends serving one contract must not disagree about the document, or every reader has
    to know which one produced it."""
    def walk(back):
        c = conv.Conversation(back, "一週氣象").open()
        c.instruction("做一個氣象頁", 1)
        c.ask("000-pm_plan", "pm_plan", "pm", None, "opus", {"brief": "b"})
        c.answer("000-pm_plan", {"modules": ["a"]}, "opus")
        c.decision("approval", "merge", "ok")
        c.close("finished")
        return c.document()

    from_db, from_files = walk(_sqlite(tmp_path)), walk(_file(tmp_path))
    for document in (from_db, from_files):
        document.pop("conversation_id")
        for turn in document["turns"]:
            turn.pop("at")
    assert from_db == from_files


def test_a_project_name_that_is_not_ascii_survives_the_round_trip(tmp_path):
    back = _sqlite(tmp_path)
    c = conv.Conversation(back, "一週氣象 Taipei").open()
    c.close("finished")
    listed = back.conversations()[0]
    assert listed["project"]["name"] == "一週氣象 Taipei"
    assert back.read(listed["project"]["id"], listed["conversation_id"])["project"]["name"] == \
        "一週氣象 Taipei"


def test_the_body_is_stored_without_the_envelope(tmp_path):
    """`body_json` holds **only** the body. The shipped code once had a body key overwrite `seq`
    and `at`, which is the two-truths problem in its sharpest form."""
    back = _sqlite(tmp_path)
    c = conv.Conversation(back, "P").open()
    c.note("hello")
    stored = back.db.execute(
        "SELECT body_json FROM turns WHERE kind = ? ", (conv.NOTE,)).fetchone()[0]
    body = json.loads(stored)
    for envelope in conv.Turn.ENVELOPE:
        assert envelope not in body, f"{envelope} is in body_json as well as its own column"
    assert body["text"] == "hello"


def test_reading_a_conversation_from_another_project_is_refused(tmp_path):
    back = _sqlite(tmp_path)
    c = conv.Conversation(back, "P").open()
    with pytest.raises(conv.ConversationError):
        back.read("some-other-project", c.id)


# ── the import ────────────────────────────────────────────────────────────────────────────────

def _legacy_with(tmp_path, name="P", turns=3):
    back = _file(tmp_path)
    c = conv.Conversation(back, name).open()
    for n in range(turns):
        c.note(f"turn {n}")
    c.close("finished")
    return back, c.id


def test_an_imported_conversation_is_identical_turn_for_turn(tmp_path):
    """A migration that changes what it moves is not a migration."""
    source, cid = _legacy_with(tmp_path)
    target = _sqlite(tmp_path)
    report = conv.import_file_store(tmp_path / "legacy", target)

    assert report["imported"] == [cid]
    pid = conv.project_id("P")
    assert target.read(pid, cid) == source.read(pid, cid)


def test_importing_twice_skips_rather_than_duplicating(tmp_path):
    _legacy_with(tmp_path)
    target = _sqlite(tmp_path)
    first = conv.import_file_store(tmp_path / "legacy", target)
    second = conv.import_file_store(tmp_path / "legacy", target)

    assert len(first["imported"]) == 1 and second["imported"] == []
    assert len(second["skipped"]) == 1
    assert len(target.conversations()) == 1, "the second import duplicated the conversation"


def test_the_import_leaves_the_source_where_it_is(tmp_path):
    """Nothing is deleted. A migration that removes its own source has no way back if it was
    wrong, and this one stays reversible for as long as the directory is there."""
    _legacy_with(tmp_path)
    before = sorted(p.name for p in (tmp_path / "legacy").rglob("*") if p.is_file())
    conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))
    after = sorted(p.name for p in (tmp_path / "legacy").rglob("*") if p.is_file())
    assert before == after and before, "the importer touched the store it read"


def test_importing_an_empty_directory_says_so_rather_than_failing(tmp_path):
    (tmp_path / "empty").mkdir()
    report = conv.import_file_store(tmp_path / "empty", _sqlite(tmp_path))
    assert report == {"imported": [], "skipped": [], "refused": [], "turns": 0}


# ── the store on disk ─────────────────────────────────────────────────────────────────────────

def test_the_database_lands_inside_the_store_root(tmp_path):
    back = _sqlite(tmp_path)
    assert back.path == tmp_path / "store" / conv.DB_NAME
    assert back.path.is_file()


def test_sqlite_is_the_default_and_file_is_still_reachable():
    from ai_sdlc_runner import cli

    parsed = cli.build_parser().parse_args(["conversations"])
    assert parsed.store == "sqlite", "the ruling was 「只留 sqlite + file」 with file for config"
    assert "file" in conv.BACKENDS, "an existing JSONL store must still be readable"


def test_a_store_from_a_newer_schema_is_refused_rather_than_guessed_at(tmp_path):
    """`store.py`'s rule, exercised through the conversation path: a database written by a later
    runner may hold columns this one would drop on write."""
    path = tmp_path / "store" / conv.DB_NAME
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(str(path))
    db.execute(f"PRAGMA user_version = {store_mod.SCHEMA_VERSION + 5}")
    db.commit()
    db.close()
    with pytest.raises(store_mod.StoreError) as caught:
        conv.backend("sqlite", root=tmp_path / "store")
    assert "upgrade the runner" in str(caught.value)


# ── what the panel found (CHG-20260823-42) ────────────────────────────────────────────────────

def _dirty_legacy(tmp_path, damage="duplicate"):
    """A legacy store in a state the file backend permits and reports."""
    back = _file(tmp_path)
    c = conv.Conversation(back, "P").open()
    for n in range(4):
        c.note(f"turn {n}")
    c.close("finished")
    path = next((tmp_path / "legacy").rglob("*.jsonl"))
    with io.open(str(path), "a", encoding="utf-8", newline="\n") as fh:
        if damage == "duplicate":
            fh.write(json.dumps({"seq": 2, "kind": "note", "at": conv._now(),
                                 "text": "a duplicate"}) + "\n")
        else:
            fh.write('{"seq": 9, "kind": "note", NOT JSON\n')
    return c.id


def test_a_conversation_with_a_duplicate_seq_is_refused_whole_and_left_on_disk(tmp_path):
    """`docs/DATABASE.md` §6 required this in bold and the first implementation did none of it.

    Measured before the fix: **3 of 7 turns imported**, the conversation left half-populated, and
    the retry reporting the stump as "skipped, already here" — a permanent, silent truncation of
    the operator's history, produced by the migration meant to preserve it. Both seats found it
    independently.
    """
    cid = _dirty_legacy(tmp_path)
    target = _sqlite(tmp_path)
    report = conv.import_file_store(tmp_path / "legacy", target)

    assert report["imported"] == [] and report["skipped"] == []
    refused = report["refused"]
    assert [r["conversation_id"] for r in refused] == [cid]
    assert "duplicate seq" in refused[0]["why"], "the refusal must name what is wrong"
    assert "left on disk" in refused[0]["why"]
    assert target.conversations() == [], "nothing of a refused conversation may be written"


def test_a_conversation_with_an_unreadable_line_is_refused_not_silently_shortened(tmp_path):
    cid = _dirty_legacy(tmp_path, damage="partial")
    target = _sqlite(tmp_path)
    report = conv.import_file_store(tmp_path / "legacy", target)
    assert [r["conversation_id"] for r in report["refused"]] == [cid]
    assert "incomplete line" in report["refused"][0]["why"]
    assert target.conversations() == []


def test_one_bad_conversation_does_not_stop_the_others(tmp_path):
    """It used to raise out of the loop, so every conversation after it in iteration order was
    silently not imported either."""
    _dirty_legacy(tmp_path)
    good = conv.Conversation(_file(tmp_path), "Q").open()
    good.note("fine")
    good.close("finished")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))
    assert good.id in report["imported"]
    assert len(report["refused"]) == 1


def test_a_half_imported_conversation_is_reported_not_skipped(tmp_path):
    """The shape a failed earlier run leaves. Skipping it is what made the truncation permanent."""
    source, cid = _legacy_with(tmp_path, turns=5)
    target = _sqlite(tmp_path)
    document = source.read(conv.project_id("P"), cid)
    header = {"conversation_id": cid, "project": document["project"],
              "schema": document["schema"], "run": document.get("run") or {}}
    target.import_conversation(header, document["turns"][:2])      # a stump

    report = conv.import_file_store(tmp_path / "legacy", target)
    assert report["skipped"] == [], "a short copy is not 'already here'"
    why = report["refused"][0]["why"]
    assert "2 of" in why and "did not finish" in why


def test_an_import_that_fails_writes_nothing_at_all(tmp_path):
    """Atomic per conversation: one transaction, so a turn violating the primary key rolls the
    header back with it."""
    target = _sqlite(tmp_path)
    header = {"conversation_id": "c1", "project": {"id": "p", "name": "P"},
              "schema": conv.SCHEMA, "run": {}}
    turns = [{"seq": 0, "kind": "note", "at": conv._now(), "text": "a"},
             {"seq": 0, "kind": "note", "at": conv._now(), "text": "collides"}]
    with pytest.raises(conv.ConversationError) as caught:
        target.import_conversation(header, turns)
    assert "Nothing of it was written" in str(caught.value)
    assert target.conversations() == []
    assert target.turn_count("c1") == 0


def test_the_computed_keys_of_a_read_do_not_become_stored_facts(tmp_path):
    """`_assemble` adds `duplicate_seqs` and `incomplete_lines`. The first importer carried them
    into the target header — dropped silently by SQLite, and written into a **file** target as a
    permanent fake fact that `_assemble` would then re-emit for ever."""
    _legacy_with(tmp_path, turns=2)
    target = conv.backend("file", root=tmp_path / "copy")
    conv.import_file_store(tmp_path / "legacy", target)

    stored = next((tmp_path / "copy").rglob("*.jsonl")).read_text(encoding="utf-8")
    first = json.loads(stored.splitlines()[0])["header"]
    for computed in ("duplicate_seqs", "incomplete_lines", "turns"):
        assert computed not in first, f"{computed} was written into the stored header"


def test_every_sqlite_entry_point_takes_the_connection_lock():
    """`store.Connection` carries `runner_lock` and `_locked`'s docstring says every entry point
    takes it. Every entry point in `store.py` did; `SqliteBackend` took it nowhere — a lock unused
    on the very object it protects.

    fable-seat ran two writers against one shared connection and **two turns vanished with no
    `write_errors` entry**: an append that returned success was rolled back by the other thread's
    transaction exit, breaking `_guarded`'s promise that a failed write is never silent.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(conv.SqliteBackend)))
    entry_points = [n for n in tree.body[0].body
                    if isinstance(n, ast.FunctionDef)
                    and not n.name.startswith("_")
                    and n.name != "close"]
    assert entry_points, "no entry points found; this test has stopped testing anything"
    for func in entry_points:
        locked = any("_locked" in ast.unparse(n) for n in ast.walk(func))
        assert locked, f"SqliteBackend.{func.name} does not take the connection lock"


def test_two_threads_cannot_be_handed_the_same_seq(tmp_path):
    """`server._advance()` runs the walk outside its own lock and `attach()` gates only on version,
    so a second walk can run over the same `Conversation`. Two threads then read `_seq` and both
    get N."""
    import threading

    c = conv.Conversation(_sqlite(tmp_path), "P").open()
    errors = []

    def hammer():
        try:
            for n in range(40):
                c.note(f"n{n}")
        except Exception as exc:          # pragma: no cover - reaching this IS the finding
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"a writer raised: {errors[:1]}"
    assert c.write_errors == [], f"a write failed: {c.write_errors[:2]}"
    seqs = [t["seq"] for t in c.document()["turns"]]
    assert len(seqs) == len(set(seqs)), "two turns were handed the same seq"
    assert seqs == sorted(seqs) and seqs == list(range(len(seqs)))
