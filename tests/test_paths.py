"""The long-path module, tested by the thing it claims — a deep path that actually round-trips.

Every earlier attempt at this defect was tested by asserting the *message* got louder. That is the
defect one layer down: a test that reads the words of a refusal proves the words, not the write. So
each test here either writes a file too long for the plain API and reads it back, or names a limit
no prefix lifts and shows it refused before anything is created.
"""
import io
import os
import sqlite3
from pathlib import Path

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


@pytest.mark.parametrize("name", [
    "n" * 200, "n" * 255, "n" * 300,
    "\u7bc0" * 85, "\u7bc0" * 100, "\u7bc0" * 255, "\u7bc0" * 300,
    "\U0001f600" * 100, "\U0001f600" * 200,
], ids=lambda n: f"{len(n)}x{ord(n[0]):04x}")
def test_the_check_agrees_with_what_the_filesystem_actually_does(tmp_path, name):
    """The test the previous one should have been.

    It asserted the limit was counted in **bytes** \u2014 which is what the code did, so it passed while
    the code was wrong. Windows counts UTF-16 code units, and a 100-character CJK name (300 bytes,
    100 units) is legal; `check` refused it with a message claiming no filesystem would take it.

    A Latin name reaches 255 bytes and 255 characters together, so nothing in the original test set
    could have caught this. The defect fell only on non-Latin names, which is why the cases below
    are mostly not Latin.

    So this asks the filesystem instead, in **both** directions \u2014 over-refusing is the real failure
    mode of a limit like this, and the one that shipped.
    """
    # Probed through the **extended** form. `check` is only ever about one component, and probing
    # with the plain path made `tmp_path`'s own depth the thing that failed — a 200-character name
    # under a deep pytest directory crosses MAX_PATH on the total, which is a different limit and
    # the one the prefix already lifts. That confound made four of these cases fail against correct
    # code, which is its own small lesson about isolating what a test is measuring.
    try:
        target = tmp_path / name
        io.open(paths.real(target), "w", encoding="utf-8").close()
        os.unlink(paths.real(target))
        accepted_by_os = True
    except OSError:
        accepted_by_os = False

    try:
        paths.check(tmp_path / name)
        accepted_by_check = True
    except paths.PathTooLong:
        accepted_by_check = False

    assert accepted_by_check == accepted_by_os, (
        f"{len(name)} chars / {len(name.encode('utf-8'))} utf-8 bytes / "
        f"{len(name.encode('utf-16-le')) // 2} utf-16 units: the filesystem "
        f"{'accepted' if accepted_by_os else 'refused'} it and check() "
        f"{'accepted' if accepted_by_check else 'refused'} it")


def test_a_cjk_name_is_judged_by_the_platform_that_will_store_it(tmp_path):
    """Named on its own because it is the regression, and because this repository is operated in
    Chinese: a project called \u4e00\u9031\u6c23\u8c61 nested a few directories deep hit a refusal that was untrue.

    **The first version of this test made the same mistake as the defect it was written for.** It
    asserted `check` accepts a 100-character CJK name \u2014 true on Windows, where that is 100 UTF-16
    units, and false on ext4, where it is 300 bytes and genuinely too long. CI caught it: Windows
    green, Ubuntu red. A platform truth written as a universal one, in the test fixing a platform
    truth written as a universal one.

    So it asserts the *rule* instead: the count uses the platform's unit, and `check` agrees with
    what the platform will actually store.
    """
    name = "\u7bc0" * 100
    size, unit = paths.measure(name)
    if os.name == "nt":
        assert (size, unit) == (100, "UTF-16 code units")
        paths.check(tmp_path / name)                     # legal on NTFS, and was being refused
    else:
        assert (size, unit) == (300, "bytes")
        with pytest.raises(paths.PathTooLong):
            paths.check(tmp_path / name)                 # genuinely too long on ext4


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


# ── the coverage claim, and the two holes under it (CHG-20260823-38) ──────────────────────────

#: Direct writes that are allowed, each with the reason it does not need the long-path module.
#:
#: The first version of the audit below was a **blanket ban**: no module may write directly, ever.
#: That replaced one over-broad claim ("every file write goes through it") with an over-broad rule,
#: which is the same defect wearing a test's clothes — the operator said so:
#:
#:     paths 是根據流程走的，不一定每個節點都會遇到
#:
#: Which writes can reach a deep path depends on the flow that runs, not on the module the call
#: sits in. So the audit is now an **allowlist with reasons**: a direct write is a decision somebody
#: made and wrote down, rather than something silently permitted or absolutely forbidden. Adding an
#: entry costs a sentence; that is the point.
ALLOWED_DIRECT_WRITES = {
    # (module, function called) : why it does not go through paths.py
    ("store.py", "sqlite3.connect"):
        "the database open itself; sqlite takes a path string rather than a handle, so it is given "
        "paths.real(file) and preceded by paths.check(file) two lines above — routed, just not "
        "through a paths.* call the scanner can see",
    ("conversations.py", "os.replace"):
        "the atomic rename that gives FileBackend.import_conversation its whole-or-nothing "
        "guarantee; both of its arguments are already paths.real() strings, so routing the rename "
        "itself through paths would prefix an already-prefixed path",
}


#: Fully-qualified calls that put bytes on disk. Matched on the whole dotted name, so there is no
#: ambiguity about what they are.
#:
#: Both seats found the previous list short: it missed the **builtin `open`**, the single most
#: ordinary way to write a file in Python, plus `os.replace`, `os.rename`, `Path.touch` and
#: everything in `shutil`. None existed in `src/` — the hole was latent, not live — but a write
#: audit blind to `open()` is not an audit.
WRITE_CALLS = {
    "io.open", "os.makedirs", "os.mkdir", "os.chmod", "os.unlink", "os.remove",
    "os.replace", "os.rename", "os.rmdir", "os.truncate", "os.link", "os.symlink",
    # fable-seat: these are fully dotted, statically identifiable, ordinary Python — and they were
    # missing while the honesty note below listed only *dynamic* gaps. A stated limit that omits
    # the things it could have caught is not honest, it is just written down.
    "os.open", "os.fdopen", "os.mkfifo", "os.makedev", "sqlite3.connect",
}

#: Any call into these modules counts. `tempfile` creates files; `shutil` moves them.
WRITE_MODULES = ("shutil.", "tempfile.")

#: Method names that mean a file operation **whatever the receiver is**. Deliberately short.
#:
#: The first widening of this set also included `open`, `unlink`, `replace` and `rename`, and it
#: matched `str.replace`, `dataclasses.replace` and `Conversation.open` — 30 false positives in
#: `src/`, which is the same over-broad rule the allowlist was introduced to stop, arriving from
#: the other direction. Telling `Path.replace` from `str.replace` needs type inference this does
#: not have, so those spellings are caught only as `os.replace`, and the gap is stated below rather
#: than papered over.
WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "touch"}

#: `Path(...).open("w")` is caught as a special case: an `open` attribute whose receiver is a call
#: to `Path`. Narrow on purpose — it is the realistic spelling, and it cannot match `conv.open()`.
#:
#: **Not caught, and said out loud**: `p.open("w")` where `p` was bound earlier, `f.write(...)` on
#: an already-open handle, a write through a helper this file has never seen, or anything reached
#: dynamically. The audit narrows the ways a bypass can be introduced silently; it does not close
#: them, and a test that claimed otherwise would be the defect it exists to catch.


def _writes_found_by_the_audit(module: Path):
    """Every direct-write call in one module, as `(line, dotted name)`.

    Extracted so the audit and the test guarding the audit run **the same code**. The previous
    guard re-scanned a file against its own hardcoded tuple and never invoked the audit — so
    gutting the audit's shape list left both tests green, which fable-seat demonstrated by doing
    exactly that.
    """
    import ast

    found = []
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = ast.unparse(func)
        if called.startswith("paths."):
            continue

        hit = called in WRITE_CALLS or called.startswith(WRITE_MODULES)
        if isinstance(func, ast.Name) and func.id == "open":
            hit = True                                   # the builtin
        if isinstance(func, ast.Attribute):
            if func.attr in WRITE_METHODS:
                hit = True
            elif func.attr == "open" and isinstance(func.value, ast.Call) \
                    and ast.unparse(func.value.func).rsplit(".", 1)[-1] == "Path":
                hit = True                               # Path(...).open(...)
        if hit:
            found.append((node.lineno, called))
    return found


def test_a_direct_write_is_either_routed_through_this_module_or_written_down():
    """CHG-20260823-32 said "every file write now goes through it" and wired three modules of eight.

    Both review seats named it the worst thing in that batch: a name standing in for a constraint,
    inside the change written to fix that class. `attachments.py` was the sharpest case — the module
    `paths.py`'s own docstring cites as the historical victim, still carrying its 32-character
    hash workaround and still writing directly.

    What this asserts is *not* that a direct write is forbidden. It is that a direct write is
    **accounted for** — either it goes through `paths`, or it is in `ALLOWED_DIRECT_WRITES` with a
    reason. A rule that simply banned them would be the same over-broad claim one level up, and
    would refuse a legitimate write to a temp directory on a path no flow can make deep.

    Read out of the syntax tree, not grepped, so a comment mentioning `write_text` cannot satisfy it.
    """
    offenders = []
    for module in sorted(Path(paths.__file__).parent.glob("*.py")):
        if module.name == "paths.py":
            continue
        for line, called in _writes_found_by_the_audit(module):
            if (module.name, called) in ALLOWED_DIRECT_WRITES:
                continue
            offenders.append(f"{module.name}:{line} {called}")
    assert not offenders, (
        "these writes neither go through paths.py nor appear in ALLOWED_DIRECT_WRITES with a "
        "reason: " + ", ".join(offenders))


def test_the_allowlist_gives_a_reason_for_every_entry():
    """An allowlist whose entries carry no reason is a blanket permission spelled out longhand."""
    for key, why in ALLOWED_DIRECT_WRITES.items():
        assert isinstance(why, str) and len(why.split()) >= 4, (
            f"{key} is exempted without a usable reason: {why!r}")


@pytest.mark.parametrize("shape", [
    "io.open(target, 'w')",
    "os.makedirs(target)",
    "os.chmod(target, 0o600)",
    "os.unlink(target)",
    "os.replace(a, b)",
    "shutil.copyfile(a, b)",
    "open(target, 'w')",
    "Path(target).open('w')",
    "Path(target).touch()",
    "Path(target).write_text('x')",
    "Path(target).write_bytes(b'x')",
    "Path(target).mkdir()",
])
def test_the_audit_actually_catches_each_shape(tmp_path, shape):
    """The guard, actually guarding.

    The previous version re-scanned this file against its **own hardcoded tuple** and asserted those
    calls existed. It never ran the audit. fable-seat gutted the audit's shape list down to
    `("write_text",)` — deleting `io.open`, `os.makedirs`, `os.chmod`, `os.unlink`, `os.remove`,
    `write_bytes` and `mkdir` — and **both tests passed**. The exact sabotage the docstring named
    went through silently: a test reading vocabulary instead of the claim, inside the change that
    relaxed the audit.

    This feeds a module containing one write to the audit's own scanner and requires it to be
    caught. Delete a shape from the list and the case for it fails.
    """
    module = tmp_path / "offender.py"
    module.write_text(
        "import io, os, shutil\nfrom pathlib import Path\n"
        f"def go(target, a, b):\n    {shape}\n", encoding="utf-8")
    assert _writes_found_by_the_audit(module), f"the audit does not recognise {shape}"


def test_the_audit_does_not_cry_wolf(tmp_path):
    """The other half: a module that writes nothing must come back clean, or the audit is a rule
    nobody can satisfy."""
    module = tmp_path / "innocent.py"
    module.write_text(
        "from pathlib import Path\n"
        "def go(p):\n"
        "    text = Path(p).read_text()\n"
        "    return text.upper()\n", encoding="utf-8")
    assert not _writes_found_by_the_audit(module)


def test_the_sqlite_database_name_is_checked_too(tmp_path):
    """`real()` is a spelling function and does not check — so `store.connect` passing `real(file)`
    to sqlite left the component limit unenforced on the database path, which CHG-32 claimed it
    enforced. A seat found the gap."""
    from ai_sdlc_runner import store

    with pytest.raises(paths.PathTooLong):
        store.connect(tmp_path / ("n" * 300) / "config.sqlite")
    with pytest.raises(paths.PathTooLong):
        store.connect(tmp_path / ("n" * 300 + ".sqlite"))


def test_a_prefixed_relative_path_is_resolved_not_returned_unchanged():
    """The prefix turns off the resolution that would have made a relative path absolute, so a
    prefixed relative path is one the OS cannot use. `real()` returned it unchanged."""
    once = paths.real(paths.PREFIX + "relative/thing" if os.name == "nt" else "relative/thing")
    assert os.path.isabs(paths.plain(once))


def test_the_limit_is_asked_of_the_filesystem_where_it_can_be_asked(tmp_path):
    """`NAME_MAX = 255` was a constant standing in for a queried constraint — this project's own
    defect class as a module-level assignment. POSIX can be asked; Windows cannot, and there the
    constant stands with that scope stated."""
    limit = paths.name_max(tmp_path)
    assert limit >= 255
    if os.name != "nt" and hasattr(os, "pathconf"):
        assert limit == os.pathconf(str(tmp_path), "PC_NAME_MAX")


def test_a_name_is_checked_before_its_directory_exists(tmp_path):
    """`check` runs before `makedirs`, so the directory whose filesystem sets the limit is often
    not there yet. The nearest existing ancestor is asked instead."""
    paths.name_max(tmp_path / "not" / "made" / "yet" / "file.txt")


def test_the_extended_prefix_is_not_measured_as_a_name(tmp_path):
    r"""`\\?\` arrives as parts[0] on Windows. Harmless at real lengths, but it is not a name and
    counting it as one is the sort of thing that becomes wrong later."""
    paths.check(paths.real(tmp_path / "ordinary.txt"))
