"""The long-path module, tested by the thing it claims — a deep path that actually round-trips.

Every earlier attempt at this defect was tested by asserting the *message* got louder. That is the
defect one layer down: a test that reads the words of a refusal proves the words, not the write. So
each test here either writes a file too long for the plain API and reads it back, or names a limit
no prefix lifts and shows it refused before anything is created.
"""
import io
import os
import sqlite3

import pytest

from ai_sdlc_runner import paths


def _deep(root, depth_chars=320):
    """A path past MAX_PATH, built out of ordinary components."""
    d = root
    while len(str(d)) < depth_chars:
        d = d / "segment-of-an-ordinary-directory-name"
    return d


# ── the claim: it works at a depth the plain API cannot reach ─────────────────────────────────

def test_a_file_deeper_than_max_path_writes_and_reads_back(tmp_path):
    target = _deep(tmp_path) / "conversation.jsonl"
    assert len(str(target)) > 260, "the fixture must actually be past the limit"

    paths.makedirs(target.parent)
    paths.write_text(target, '{"seq": 1}\n')

    assert paths.read_text(target) == '{"seq": 1}\n'
    assert paths.exists(target)
    assert "conversation.jsonl" in paths.listdir(target.parent)


def test_the_plain_api_is_what_could_not_do_that(tmp_path):
    """The contrast the module exists for — skipped where the OS has already lifted the limit."""
    target = _deep(tmp_path) / "conversation.jsonl"
    try:
        os.makedirs(str(target.parent), exist_ok=True)
        io.open(str(target), "w", encoding="utf-8").close()
    except OSError:
        return                                        # the limit is real here; the point stands
    pytest.skip("long paths are enabled on this machine, so the contrast cannot be shown")


def test_sqlite_opens_at_that_depth(tmp_path):
    """`store.py` puts a **database** at whatever depth the operator chose, and sqlite3 reported
    `unable to open database file` on the plain path — a message that reads like corruption."""
    db_path = _deep(tmp_path) / "models.db"
    paths.makedirs(db_path.parent)
    db = sqlite3.connect(paths.real(db_path))
    db.execute("create table t (x integer)")
    db.execute("insert into t values (1)")
    db.commit()
    assert db.execute("select x from t").fetchone() == (1,)
    db.close()


# ── what no prefix lifts: one component over 255 ──────────────────────────────────────────────

def test_an_over_long_component_is_refused_before_anything_is_created(tmp_path):
    target = tmp_path / ("n" * 300) / "file.txt"
    with pytest.raises(paths.PathTooLong) as caught:
        paths.makedirs(target.parent)
    assert "300" in str(caught.value), "the refusal must say how long it actually was"
    assert os.listdir(str(tmp_path)) == [], "refused means nothing was created"


def test_the_boundary_is_not_over_refused(tmp_path):
    """255 is accepted. A check that refused at 200 to be safe would be the same defect inverted —
    a coarse limit answering 'no' about something it had not measured."""
    paths.check(tmp_path / ("n" * 255) / "file.txt")


def test_the_limit_is_counted_in_bytes_not_characters(tmp_path):
    """`NAME_MAX` is 255 **bytes**. 200 CJK characters are 600 bytes and do not fit, and counting
    them as 200 would let the write through to fail as errno 22."""
    with pytest.raises(paths.PathTooLong):
        paths.check(tmp_path / ("\u7bc0" * 200))


# ── the prefix's own conditions, each one a way to get it wrong ────────────────────────────────

def test_real_is_idempotent():
    r"""Prefixing an already-prefixed path yields a literal `\\?\` *component*, which no filesystem
    has, so the second call must be a no-op rather than a doubling."""
    once = paths.real(os.path.abspath("x"))
    assert paths.real(once) == once


def test_real_is_absolute_because_the_prefix_turns_off_resolution():
    """A relative path carrying the prefix is not resolved — it is refused. So `real` must make it
    absolute before prefixing, not after."""
    assert os.path.isabs(paths.plain(paths.real("relative/thing")))


@pytest.mark.skipif(os.name != "nt", reason="the prefix is a Windows thing")
def test_a_unc_path_takes_the_other_form():
    r"""`\\?\\\server\share` is not a path. The UNC form is `\\?\UNC\server\share`, and getting
    this wrong turns a network store into a refusal that reads like a permissions problem."""
    got = paths.real(r"\\fileserver\share\project\conv.jsonl")
    assert got == r"\\?\UNC\fileserver\share\project\conv.jsonl"
    assert paths.plain(got) == r"\\fileserver\share\project\conv.jsonl"


@pytest.mark.skipif(os.name == "nt", reason="POSIX has no prefix to add")
def test_posix_gets_no_invented_wrapper():
    """POSIX needs nothing for total length, so `real` returns a plain absolute path — a no-op
    wrapper would only make every traceback less readable."""
    assert paths.real("/tmp/x") == "/tmp/x"
    assert not paths.real("/tmp/x").startswith("\\")


def test_plain_inverts_real_so_messages_stay_readable():
    r"""A traceback carrying `\\?\C:\…` sends the reader looking for a network share."""
    original = os.path.abspath("some/file.txt")
    assert paths.plain(paths.real(original)) == original


def test_a_root_and_a_drive_are_not_mistaken_for_a_long_name(tmp_path):
    paths.check(tmp_path)
    paths.check(os.path.abspath(os.sep))


# ── the handle that was never closed ───────────────────────────────────────────────────────────

def test_write_text_closes_so_the_file_is_not_empty(tmp_path):
    """`_project.json` came out **empty** from `open_(...).write(...)` with no context manager, and
    `runner conversations` then died on `Expecting value: line 1 column 1`. Read back with plain
    `io.open`, not through this module, so a mutual bug cannot make the test pass."""
    target = tmp_path / "marker.json"
    paths.write_text(target, '{"id": "x"}\n')
    assert io.open(str(target), encoding="utf-8").read() == '{"id": "x"}\n'


def test_write_bytes_closes_too(tmp_path):
    target = tmp_path / "payload.json"
    paths.write_bytes(target, b'{"a": 1}\n')
    assert io.open(str(target), "rb").read() == b'{"a": 1}\n'


def test_write_text_does_not_translate_newlines(tmp_path):
    """The stores are JSONL and a CRLF would put a stray byte in every record."""
    target = tmp_path / "lines.jsonl"
    paths.write_text(target, "a\nb\n")
    assert io.open(str(target), "rb").read() == b"a\nb\n"


def test_listdir_of_a_missing_directory_is_empty_not_an_error(tmp_path):
    assert paths.listdir(tmp_path / "never-made") == []


def test_unlink_removes_a_deep_file(tmp_path):
    target = _deep(tmp_path) / "gone.txt"
    paths.makedirs(target.parent)
    paths.write_text(target, "x")
    paths.unlink(target)
    assert not paths.exists(target)
