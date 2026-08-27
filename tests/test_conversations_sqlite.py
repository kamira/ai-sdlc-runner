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


def test_a_good_conversation_after_a_dirty_legacy_store_still_imports(tmp_path):
    """It used to raise out of the loop, so every conversation after it in iteration order was
    silently not imported either.

    Renamed by CHG-20260827-03. This was `test_one_bad_conversation_does_not_stop_the_others`, and
    so is the parametrised test further down this file — CHG-45's, over the `DIRT` shapes. Python
    keeps the last definition of a name, so from the day CHG-45 landed **this test stopped being
    collected**, and nobody noticed because the replacement is stronger and the suite stayed green.
    Dead code that looks like coverage, found by the acceptance round of 2026-08-27.

    It is renamed rather than deleted: `_dirty_legacy` is not one of the `DIRT` shapes, so this case
    is real coverage the parametrised test does not have.
    """
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


# ── the importer, third round (CHG-20260823-45) ───────────────────────────────────────────────
#
# CHG-42's preflight knew exactly the two dirty shapes that had burned CHG-41. Both seats then
# broke it six more ways: five aborted the whole migration on the first bad file — four of them as
# raw tracebacks — and one vanished with a clean report.
#
# So these are the hostile stores, not a clean one. Each is built with a GOOD conversation after
# the bad one, because "one bad conversation does not stop the others" is the claim under test and
# a store with one conversation cannot test it.

def _store_with(tmp_path, damage):
    """A legacy store: one good conversation, one damaged, one good after it."""
    back = _file(tmp_path)
    first = conv.Conversation(back, "A").open()
    first.note("before")
    first.close("finished")

    bad = conv.Conversation(back, "B").open()
    bad.note("hello")
    bad_path = None
    for candidate in (tmp_path / "legacy").rglob("*.jsonl"):
        if candidate.stem == bad.id:
            bad_path = candidate
    damage(bad_path)

    last = conv.Conversation(back, "C").open()
    last.note("after")
    last.close("finished")
    return bad.id, last.id


def _append(path, line):
    with io.open(str(path), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


DIRT = {
    "a bare JSON scalar on a line": lambda p: _append(p, "42"),
    "a turn whose seq is not a number": lambda p: _append(
        p, json.dumps({"seq": "x", "kind": "note", "at": "2026-01-01T00:00:00.000+00:00"})),
    "a turn with no kind": lambda p: _append(
        p, json.dumps({"seq": 9, "at": "2026-01-01T00:00:00.000+00:00", "text": "x"})),
    "a header with no project": lambda p: p.write_text(
        json.dumps({"header": {"conversation_id": p.stem, "schema": 1}}) + "\n", encoding="utf-8"),
    "a filename that disagrees with the header": lambda p: p.rename(
        p.with_name("not-the-id.jsonl")),
    "a duplicate seq": lambda p: _append(
        p, json.dumps({"seq": 1, "kind": "note", "at": "2026-01-01T00:00:00.000+00:00",
                       "text": "twice"})),
}


@pytest.mark.parametrize("description", sorted(DIRT))
def test_one_bad_conversation_does_not_stop_the_others(tmp_path, description):
    """The claim CHG-42 made and could not keep.

    Its loop's `try` wrapped only `into.import_conversation` and caught only `ConversationError`;
    `source.read`, `_assemble`, the header lookups and every non-sqlite error inside the import
    fell outside it. Each of these shapes killed the migration and everything after it.
    """
    _bad, last = _store_with(tmp_path, DIRT[description])
    target = _sqlite(tmp_path)

    report = conv.import_file_store(tmp_path / "legacy", target)

    imported = report["imported"]
    assert last in imported, (
        f"{description!r} stopped the conversation after it from importing: {report}")
    assert report["refused"], f"{description!r} was not refused by name: {report}"
    for entry in report["refused"]:
        assert entry["conversation_id"], "a refusal with no name is not a refusal"
        assert entry["why"], "a refusal with no reason is not a refusal"


def test_a_directory_named_like_a_conversation_does_not_stop_the_import(tmp_path):
    """fable-seat's sixth: `PermissionError` out of `FileBackend.conversations`, before a single
    conversation was read."""
    back = _file(tmp_path)
    good = conv.Conversation(back, "A").open()
    good.note("fine")
    good.close("finished")
    (tmp_path / "legacy" / conv.project_id("A") / "fake.jsonl").mkdir()

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))

    # The assertion this replaces was `good.id in report["imported"] or report["refused"]`. The
    # `or` made it pass on the exact abort its own name forbids: when the directory stopped the
    # import, `imported` was empty and `refused` held one entry saying the *store* could not be
    # listed, so the second operand was truthy and the test went green. It shipped, and a seat
    # found it rather than the suite. Both halves are required now, separately.
    assert good.id in report["imported"], (
        f"the directory named *.jsonl stopped the good conversation importing: {report}")
    named = [e["conversation_id"] for e in report["refused"]]
    assert any("fake.jsonl" in n for n in named), (
        f"the directory was not refused by the name of the file it is: {named}")


def test_a_store_past_max_path_still_reports_what_it_could_not_read(tmp_path):
    """The only **silent** one, and the worst.

    `on_disk` used `Path(root).rglob("*.jsonl")`. Sixty lines above, `FileBackend.conversations`
    carries a comment saying glob must not be used here for exactly this reason: it goes through
    the OS with the plain path, so a store past MAX_PATH lists as **empty** rather than raising.

    Measured at a 322-character root: `rglob` found 0 files, `paths.listdir` found 2, and a file
    with an unreadable header vanished from the import with a clean report and exit 0 — the precise
    failure this scan exists to prevent, produced by the scan.
    """
    from ai_sdlc_runner import paths

    root = tmp_path
    while len(str(root)) < 300:
        root = root / "a-directory-with-an-ordinary-name"
    paths.makedirs(root)
    assert len(str(root)) > 260

    back = conv.FileBackend(root)
    good = conv.Conversation(back, "P").open()
    good.note("fine")
    good.close("finished")
    paths.write_text(root / conv.project_id("P") / "junk.jsonl", "NOT JSON AT ALL\n")

    report = conv.import_file_store(root, conv.backend("sqlite", root=tmp_path / "db"))
    assert good.id in report["imported"]
    named = [r["conversation_id"] for r in report["refused"]]
    # CHG-20260823-47: `["junk"]` is what this asserted, and the bare stem was the defect — it is
    # what let two projects' `shared.jsonl` collapse into one entry. A refusal names the file.
    assert named == [f"{conv.project_id('P')}/junk.jsonl"], (
        f"the unreadable file vanished from a deep store, or was named too vaguely to find: "
        f"{report}")


def test_a_staging_file_left_by_a_dead_import_is_named(tmp_path):
    """`.part` residue was never mentioned, while the record claimed "a failure writes nothing"."""
    back = _file(tmp_path)
    good = conv.Conversation(back, "P").open()
    good.note("fine")
    good.close("finished")
    (tmp_path / "legacy" / conv.project_id("P") / "half-written.jsonl.part").write_text(
        "{}\n", encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))
    assert good.id in report["imported"]
    named = [r for r in report["refused"] if "staging" in r["why"]]
    assert named, f"the .part residue was not reported: {report}"


def test_the_same_id_holding_a_different_conversation_is_refused_not_skipped(tmp_path):
    """codex-seat's finding. `_already_there` compared id and **count**, so a target holding the
    same id and the same number of unrelated turns was reported as "skipped, already here" while
    the source's content was never imported — a coarse check answering *safe* about content it had
    never examined."""
    source, cid = _legacy_with(tmp_path, turns=2)
    target = _sqlite(tmp_path)
    document = source.read(conv.project_id("P"), cid)
    target.import_conversation(
        {"conversation_id": cid, "project": document["project"],
         "schema": document["schema"], "run": {}},
        [dict(t, text=f"unrelated {i}") for i, t in enumerate(document["turns"])])

    report = conv.import_file_store(tmp_path / "legacy", target)
    assert report["skipped"] == [], "unrelated content of the same size was called 'already here'"
    why = report["refused"][0]["why"]
    assert "not these ones" in why and "will not choose" in why


def test_a_genuine_re_import_is_still_skipped(tmp_path):
    """The other direction: comparing content must not turn idempotence into a refusal."""
    _legacy_with(tmp_path, turns=3)
    target = _sqlite(tmp_path)
    conv.import_file_store(tmp_path / "legacy", target)
    second = conv.import_file_store(tmp_path / "legacy", target)
    assert len(second["skipped"]) == 1 and second["refused"] == []


def test_the_store_is_never_listed_with_glob():
    """Read out of the syntax tree. `glob`/`rglob` go through the OS with the plain path, so on a
    deep store they return nothing rather than raising — which is how the silent omission happened
    in the function written to stop silent omissions."""
    import ast

    source = Path(conv.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in (
                "glob", "rglob", "iterdir"):
            raise AssertionError(
                f"conversations.py:{node.lineno} lists the store with "
                f"{ast.unparse(node.func)} — see FileBackend.conversations on why it must not")


# ── the target is listed once (CHG-20260823-46) ───────────────────────────────────────────────

class _Counting:
    """A backend that records how often it is asked to list or read."""

    def __init__(self, inner):
        self.inner, self.listed, self.reads = inner, 0, []

    def conversations(self, pid=None):
        self.listed += 1
        return self.inner.conversations(pid)

    def read(self, pid, cid):
        self.reads.append(cid)
        return self.inner.read(pid, cid)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_the_target_is_listed_once_however_many_conversations_are_imported(tmp_path):
    """`_already_there` called `into.conversations()` for **every** source conversation.

    Counted rather than timed, because a timing test on a shared machine is a coin flip. The cost
    it stands for was measured with a file target:

    ```
    conversations   seconds   ms each        after
              100      3.86      38.6         9.3
              200     11.43      57.1         6.5
              400     43.40     108.5         7.0     (3.80x per doubling -> 2.17x)
    ```
    """
    back = _file(tmp_path)
    for n in range(12):
        c = conv.Conversation(back, f"P{n}").open()
        c.note("x")
        c.close("finished")

    target = _Counting(_sqlite(tmp_path))
    report = conv.import_file_store(tmp_path / "legacy", target)

    assert len(report["imported"]) == 12
    assert target.listed == 1, (
        f"the target was listed {target.listed} times for 12 conversations; it grows with the "
        f"source and the check is meant to be one call")


def test_the_target_is_read_only_where_an_id_actually_collides(tmp_path):
    """Comparing turns is what makes "already here" honest, and it is only needed on a collision.
    Reading every target conversation regardless would put the cost back in a different place."""
    back = _file(tmp_path)
    ids = []
    for n in range(6):
        c = conv.Conversation(back, f"P{n}").open()
        c.note("x")
        c.close("finished")
        ids.append(c.id)

    target = _Counting(_sqlite(tmp_path))
    conv.import_file_store(tmp_path / "legacy", target)
    assert target.reads == [], "nothing collided, so nothing in the target needed reading"

    # Now everything collides, and each one is read exactly once to compare.
    target.reads.clear()
    target.listed = 0
    second = conv.import_file_store(tmp_path / "legacy", target)
    assert len(second["skipped"]) == 6
    assert sorted(target.reads) == sorted(ids)
    assert target.listed == 1


# ── CHG-20260823-47: the importer, told what it is looking at ─────────────────────────────────────
#
# Every test below constructs a state one of the two seats produced against CHG-45/-46 and asserts
# the behaviour, not the vocabulary. Each was watched failing against the previous commit first.


class _Breaks:
    """A target whose writes fail the way a full disk fails. Nothing about the source is wrong."""

    def __init__(self, inner, error=None):
        self.inner, self.attempts = inner, 0
        self.error = error or OSError(28, "No space left on device")

    def import_conversation(self, header, turns):
        self.attempts += 1
        raise self.error

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _legacy(tmp_path, projects, turns=1):
    back = _file(tmp_path)
    ids = {}
    for name in projects:
        c = conv.Conversation(back, name).open()
        for _ in range(turns):
            c.note("x")
        c.close("finished")
        ids[name] = c.id
    return ids


def _refused(report):
    return [e["conversation_id"] for e in report["refused"]]


def test_a_broken_target_is_tried_once_and_named_as_the_target(tmp_path):
    """CHG-46 filed a full disk as damage to each source conversation, three times over.

    Both seats found it independently. The report said three of the operator's conversations were
    bad; none of them was. Worse than the wrong words: the loop kept writing to a target it had
    already been told was broken, which on four hundred conversations is four hundred attempts.
    """
    _legacy(tmp_path, ["A", "B", "C"])
    target = _Breaks(_sqlite(tmp_path))

    report = conv.import_file_store(tmp_path / "legacy", target)

    assert target.attempts == 1, (
        f"the target failed on the first write and was written to {target.attempts} times")
    assert _refused(report) == ["(the target)"], (
        f"a broken target was reported as broken source conversations: {_refused(report)}")


def test_source_dirt_is_still_refused_one_at_a_time(tmp_path):
    """The other half of the same claim: telling target failures apart must not turn a single dirty
    source conversation into an abort. Without this, `TargetError` could be made to pass the test
    above by stopping on everything."""
    ids = _legacy(tmp_path, ["A", "B"])
    (tmp_path / "legacy" / conv.project_id("A") / "junk.jsonl").write_text(
        "NOT JSON\n", encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))

    assert sorted(report["imported"]) == sorted(ids.values())
    assert any("junk.jsonl" in n for n in _refused(report)), _refused(report)


def test_two_projects_holding_the_same_filename_are_two_refusals(tmp_path):
    """`_walk_store` returned **bare filenames**, flattened across projects, so `A/shared.jsonl` and
    `B/shared.jsonl` collapsed to one entry in a set. Two unreadable files produced one refusal and
    the other vanished with a clean report — the same silent omission the scan exists to prevent,
    reintroduced by the fix for it.

    The shipped test for the scan used **one** project, so the flattening was never exercised. That
    is why this one uses two.
    """
    _legacy(tmp_path, ["A", "B"])
    for name in ("A", "B"):
        (tmp_path / "legacy" / conv.project_id(name) / "shared.jsonl").write_text(
            "NOT JSON\n", encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))

    shared = [n for n in _refused(report) if "shared.jsonl" in n]
    assert len(shared) == 2, f"two unreadable files, {len(shared)} refusal(s): {_refused(report)}"
    assert len(set(shared)) == 2, (
        f"both refusals name the same thing, so an operator cannot tell which file to remove: "
        f"{shared}")


def test_a_file_directly_under_the_store_root_does_not_stop_the_import(tmp_path):
    """It raised `NotADirectoryError` out of `FileBackend.conversations`, which the importer caught
    as "(the store) could not be listed" and then returned from. One stray file meant **not one**
    conversation imported, and the report did not say which file."""
    ids = _legacy(tmp_path, ["A", "B"])
    (tmp_path / "legacy" / "stray.jsonl").write_text("{}\n", encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))

    assert sorted(report["imported"]) == sorted(ids.values()), (
        f"one stray file stopped the whole store importing: {report}")
    assert any("stray.jsonl" in n for n in _refused(report)), _refused(report)


def test_a_third_level_is_reported_rather_than_skipped_in_silence(tmp_path):
    """The walk assumed exactly `<root>/<project>/<file>`. A subdirectory inside a project was
    skipped without a word, so a subtree of conversations could sit in the store and the report
    would call the import clean. This runner does not read it; it must not imply it did."""
    ids = _legacy(tmp_path, ["A"])
    buried = tmp_path / "legacy" / conv.project_id("A") / "archive"
    buried.mkdir()
    (buried / "buried.jsonl").write_text("{}\n", encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))

    assert list(report["imported"]) == [ids["A"]]
    assert any("archive" in n for n in _refused(report)), (
        f"a directory the import did not descend into went unmentioned: {_refused(report)}")


def test_a_copied_file_whose_header_names_another_project_is_refused(tmp_path):
    """`cp A/x.jsonl B/` leaves a file whose header still names project A.

    CHG-46 claimed "two files claiming one id is still caught". It was not: the collision read used
    the id from the *header*, so `source.read(pid_from_header, cid)` re-opened the **original**
    file and compared it with itself. The copy was reported "skipped, already here, whole" without
    ever being read, and the same id appeared in both `imported` and `skipped`.
    """
    ids = _legacy(tmp_path, ["A", "B"])
    pa, pb = conv.project_id("A"), conv.project_id("B")
    original = tmp_path / "legacy" / pa / f"{ids['A']}.jsonl"
    (tmp_path / "legacy" / pb / f"{ids['A']}.jsonl").write_text(
        original.read_text(encoding="utf-8"), encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))

    assert not (set(report["imported"]) & set(report["skipped"])), (
        f"one id was both imported and skipped: {report}")
    assert any(pb[:8] in n and ids["A"][:8] in n for n in _refused(report)), (
        f"the misfiled copy was not refused by where it actually is: {_refused(report)}")
    assert ids["A"] in report["imported"], "the original should still import"


@pytest.mark.parametrize("kind", ["sqlite", "file"])
def test_importing_twice_skips_rather_than_accusing_the_operator(tmp_path, kind):
    """`import_conversation` coerces `at` to a string and `seq` to an int. The collision check
    compared **raw** source turns against **normalised** stored ones, so a legacy turn with no `at`
    — or a `seq` of `"7"` — imported cleanly and was refused on every later run, with a message
    asserting *"Same id, different conversation"* about the operator's own data and advising them
    to delete the target copy. A false accusation is worse than a crash: it invites a deletion.
    """
    ids = _legacy(tmp_path, ["A"])
    cid = ids["A"]
    path = tmp_path / "legacy" / conv.project_id("A") / f"{cid}.jsonl"
    path.write_text(path.read_text(encoding="utf-8")
                    + json.dumps({"seq": "7", "kind": "note", "text": "legacy"}) + "\n",
                    encoding="utf-8")

    into = conv.backend(kind, root=tmp_path / f"db-{kind}")
    first = conv.import_file_store(tmp_path / "legacy", into)
    assert list(first["imported"]) == [cid], f"{first}"

    second = conv.import_file_store(tmp_path / "legacy", into)
    assert list(second["skipped"]) == [cid], (
        f"the same store imported twice accused the operator instead of skipping: {second}")
    assert not second["refused"], _refused(second)


def test_the_cli_does_not_send_a_conversations_own_bytes_to_the_terminal(tmp_path):
    """A store this runner did not write holds whatever it holds. A conversation id of
    `evil\x1b]0;pwned\x07` retitles the operator's terminal window when the import names it, and
    `\x1b[31m` recolours everything printed after. Verified reaching the terminal intact through
    `cli._import` before this."""
    from ai_sdlc_runner import cli

    out = cli._printable("evil\x1b]0;pwned\x07\x1b[31mRED\x1b[0m")
    assert "\x1b" not in out and "\x07" not in out, repr(out)
    assert "pwned" in out, "escaping must not delete the evidence, only defuse it"
    assert cli._printable("\u5c08\u6848\u7532") == "\u5c08\u6848\u7532", (
        "a CJK project name is printable and must be left exactly as it is")


def test_two_files_in_one_project_claiming_one_id_are_not_called_already_here(tmp_path):
    """Found by reading CHG-47's own fix, not by a seat.

    `source.read(pid, cid)` resolves to `<pid>/<cid>.jsonl`. The header-vs-directory check made
    `pid` provably right and left `cid` unchecked, so a file named anything else whose header
    claimed an id caused a **different file** to be read and reported under this one's name. Two
    files in one project claiming one id: the second was compared against the first, found equal,
    and called "already here" — the cross-project defect this change fixed, one axis over.
    """
    ids = _legacy(tmp_path, ["A"])
    cid = ids["A"]
    here = tmp_path / "legacy" / conv.project_id("A")
    (here / "a-second-copy.jsonl").write_text(
        (here / f"{cid}.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", _sqlite(tmp_path))

    assert cid in report["imported"], f"the real file should still import: {report}"
    assert cid not in report["skipped"], (
        f"one id was both imported and skipped, from two files: {report}")
    assert any("a-second-copy.jsonl" in n for n in _refused(report)), (
        f"the second file claiming the same id was not refused by name: {_refused(report)}")


def test_one_unreadable_conversation_in_the_target_does_not_stop_the_import(tmp_path):
    """CHG-20260823-47's own defect 4, mirrored onto the target side (CHG-20260823-51).

    `in_target` was a dict comprehension over `into.conversations()`, so a single conversation
    already in the target whose header lacked `project` raised `KeyError` out of the whole
    expression. The blanket `except` above it caught that as "(the target) could not be listed" and
    returned: **zero imported**, and the offending conversation unnamed.

    That is exactly the shape CHG-47 fixed on the source side — "one stray file, zero imports, file
    unnamed" — inside the change whose Risk section says "a stray file no longer aborts the store".
    One review seat called it a defect; the other saw the same mechanism and judged it consistent
    with the backend contract. The record was wrong either way.
    """
    ids = _legacy(tmp_path, ["A", "B"])

    target = _file(tmp_path / "target-store")
    # A conversation already in the target, written by hand without a project.
    pid_dir = (tmp_path / "target-store" / "legacy" / "no-project-here")
    pid_dir.mkdir(parents=True)
    (pid_dir / "_project.json").write_text('{"id": "no-project-here"}', encoding="utf-8")
    (pid_dir / "deadbeef.jsonl").write_text(
        json.dumps({"header": {"conversation_id": "deadbeef", "schema": 1}}) + "\n",
        encoding="utf-8")

    report = conv.import_file_store(tmp_path / "legacy", target)

    assert sorted(report["imported"]) == sorted(ids.values()), (
        f"one unreadable conversation in the target stopped the whole import: {report}")
    named = [e["conversation_id"] for e in report["refused"]]
    assert any("deadbeef" in n for n in named), (
        f"the unreadable target conversation was not named: {named}")
