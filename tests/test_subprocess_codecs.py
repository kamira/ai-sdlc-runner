"""Every subprocess that reads text names the codec it reads (CHG-20260828-16).

`subprocess.run(..., text=True)` decodes the child's output with **the caller's locale codec**. On a
machine whose locale is not UTF-8 — cp950 here, cp932 in Japan — UTF-8 bytes raise
`UnicodeDecodeError` *inside the reader thread*, which is not the calling thread. `subprocess.run`
does not fail. It returns `returncode=0` and `stdout=None`: a successful call with no output.

Two guards in this repository read that `None` and concluded there was nothing to check.

Eleven call sites were fixed by hand, which is eleven reasons to believe a twelfth will be written
without the keyword. So the rule is checked on the syntax tree rather than trusted to memory — the
same argument `graph.module_cycle()` makes about deriving a traversal instead of listing it: a
hand-maintained list stays correct-looking while the thing it describes moves.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parents[1]

#: Where the rule applies. Tests are excluded on purpose: a test may want to reproduce the broken
#: behaviour, and a rule that forbids writing down the bug cannot be tested.
ROOTS = (REPO / "src", REPO / "tools")

#: Asking for text mode. `universal_newlines` is the old spelling of the same switch and decodes the
#: same way, so leaving it out would be a rule with a hole in it.
TEXT_SWITCHES = {"text", "universal_newlines"}

#: Keywords that say the call really is starting a process.
#:
#: A text switch alone is not enough, and the first draft of this file proved it by flagging
#: `self.turn(INSTRUCTION, nth=nth, text=text)` in `conversations.py` — a keyword that happens to be
#: spelled `text` on a method with no child process anywhere near it. Matching a name and calling it
#: a constraint is the defect this repository keeps finding; writing it into the guard against that
#: same defect was not the place for it.
#:
#: Callee-based matching does not work either: `worktree.py` calls `self._run(...)` and `run(...)`,
#: where `run` is a parameter whose default is `subprocess.run`. What every real site does have is a
#: keyword only a process launcher accepts.
PROCESS_KEYWORDS = {"capture_output", "stdout", "stderr", "stdin", "bufsize", "check", "input"}


def _text_mode_calls(path: Path) -> List[Tuple[int, set]]:
    """Every call in one file that starts a process in text mode, with the keywords it passed.

    Read from the tree, not from the line: `text=True` and the `encoding=` that should sit beside it
    are routinely on different physical lines, and a line-based check reported a call as unfixed
    while it was fixed — and would equally have reported a fixed call as broken.
    """
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keywords = {kw.arg for kw in node.keywords if kw.arg}
        if keywords & TEXT_SWITCHES and keywords & PROCESS_KEYWORDS:
            found.append((node.lineno, keywords))
    return found


def _sources() -> List[Path]:
    return sorted(p for root in ROOTS for p in root.rglob("*.py"))


def test_every_text_mode_subprocess_names_its_codec():
    unnamed = [
        f"{path.relative_to(REPO).as_posix()}:{line}"
        for path in _sources()
        for line, keywords in _text_mode_calls(path)
        if "encoding" not in keywords
    ]
    assert not unnamed, (
        "these calls decode the child's output with the caller's locale, so on a non-UTF-8 machine "
        "they return returncode=0 and stdout=None — a successful call with no output: "
        + ", ".join(unnamed))


def test_every_text_mode_subprocess_survives_a_byte_it_cannot_read():
    """`encoding` alone still raises; it just raises about a different codec.

    The reader thread dying is what turns a failed read into a silent success, so the point is that
    it must not be able to die — not that it should die about UTF-8 instead of about cp950.
    """
    strict = [
        f"{path.relative_to(REPO).as_posix()}:{line}"
        for path in _sources()
        for line, keywords in _text_mode_calls(path)
        if "encoding" in keywords and "errors" not in keywords
    ]
    assert not strict, (
        "these name a codec but decode strictly, so a stray byte still kills the reader thread and "
        "the call still comes back successful and empty: " + ", ".join(strict))


def test_the_rule_finds_the_calls_it_claims_to_find():
    """A check that examined nothing would pass both tests above.

    This repository's own recurring defect is a coarse check answering safe about something it never
    looked at, and this file would be an ironic place to ship one.
    """
    counted = sum(len(_text_mode_calls(path)) for path in _sources())
    assert counted >= 12, f"only {counted} text-mode calls found; the walk is not reaching them"


def test_a_call_without_a_codec_is_caught(tmp_path):
    """And the rule is exercised against a file that breaks it, not only against files that pass."""
    bad = tmp_path / "bad.py"
    bad.write_text("import subprocess\n"
                   "subprocess.run(['git', 'log'], capture_output=True, text=True)\n",
                   encoding="utf-8")
    calls = _text_mode_calls(bad)
    assert calls, "the walk did not see the call at all"
    assert "encoding" not in calls[0][1]


def test_a_call_split_across_lines_is_read_as_one_call(tmp_path):
    """The failure that made this an AST walk instead of a grep."""
    good = tmp_path / "good.py"
    good.write_text("import subprocess\n"
                    "subprocess.run(['git', 'log'], capture_output=True, text=True,\n"
                    "               encoding='utf-8', errors='replace')\n",
                    encoding="utf-8")
    (line, keywords), = _text_mode_calls(good)
    assert {"encoding", "errors"} <= keywords, "a grep on the `text=True` line would have missed it"


def test_a_keyword_merely_spelled_text_is_not_a_subprocess(tmp_path):
    """The first draft's false positive, kept so it cannot come back.

    `conversations.py` has `self.turn(INSTRUCTION, nth=nth, text=text)`. Nothing there launches
    anything; the parameter is just called `text`. A rule that flags it is matching a name and
    calling it a constraint.
    """
    innocent = tmp_path / "innocent.py"
    innocent.write_text("def turn(kind, nth=0, text=''): pass\n"
                        "turn('instruction', nth=1, text='hello')\n", encoding="utf-8")
    assert _text_mode_calls(innocent) == []


def test_a_launcher_reached_through_a_variable_is_still_caught(tmp_path):
    """`worktree.py` calls `run(...)` and `self._run(...)`, where `run` defaults to `subprocess.run`.

    So the rule cannot key on the callee's name either. It keys on the keywords, which is what both
    spellings of a launch have in common.
    """
    indirect = tmp_path / "indirect.py"
    indirect.write_text("import subprocess\n"
                        "def go(run=subprocess.run):\n"
                        "    return run(['git'], capture_output=True, text=True)\n",
                        encoding="utf-8")
    (line, keywords), = _text_mode_calls(indirect)
    assert "encoding" not in keywords


# ── the same question one layer over: files, not pipes (CHG-20260828-19) ───────────────────────
#
# ACC-20260828-16 reserved this and marked it checked-by-reading: "File I/O in this repository
# passes encoding="utf-8" explicitly, which is why nothing else surfaced. Nothing exercises that
# claim." It was true. It is now exercised.
#
# `Path.read_text()` and a bare `open()` in text mode decode with the caller's locale, exactly as
# `subprocess` does. The difference is that they raise in the calling thread, so the failure is
# loud rather than a silent empty read — which makes this the cheaper half of the same defect, not
# a different one.

#: Reading or writing text. `read_bytes`/`write_bytes` and any `"b"` mode are excluded: no codec is
#: involved, so there is nothing to name.
FILE_CALLS = {"open", "open_", "read_text", "write_text"}

#: `paths.read_text` and `paths.write_text` take `encoding: str = "utf-8"`, so a call that omits it
#: has still named it. Going through `paths` is the house style — it also enforces the sandbox — and
#: a rule that flagged it would push people back to bare `open()`.
CODEC_BY_DEFAULT = "paths"


def _file_calls(path: Path) -> List[Tuple[int, str, set]]:
    """Text-mode file opens in one file, as (line, name, keywords)."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name, receiver = func.attr, getattr(func.value, "id", None)
        elif isinstance(func, ast.Name):
            name, receiver = func.id, None
        else:
            continue
        if name not in FILE_CALLS:
            continue
        if receiver == CODEC_BY_DEFAULT and name in {"read_text", "write_text"}:
            continue
        # `open` is only a file open when nothing or a module this project opens files through is
        # in front of it. `conversations.py` has `conv.open()`, which opens a conversation record;
        # the first draft flagged it, which is the name-for-a-constraint mistake again. See
        # `test_a_method_merely_called_open_is_not_a_file` for the gap this leaves.
        if name == "open" and receiver not in (None, "io"):
            continue
        mode = "".join(a.value for a in node.args
                       if isinstance(a, ast.Constant) and isinstance(a.value, str))
        if "b" in mode:
            continue
        found.append((node.lineno, f"{receiver + '.' if receiver else ''}{name}", 
                      {kw.arg for kw in node.keywords if kw.arg}))
    return found


#: `paths.open_` forwards `**kwargs` to `io.open`, so the codec it uses is whichever its caller
#: named. It is the one place that cannot name one itself, and every caller is checked below.
FORWARDS_ITS_CALLERS_CODEC = ("src/ai_sdlc_runner/paths.py", "io.open")


def test_every_text_file_open_names_its_codec():
    unnamed = [
        f"{path.relative_to(REPO).as_posix()}:{line} {name}(" 
        for path in _sources()
        for line, name, keywords in _file_calls(path)
        if "encoding" not in keywords
        and (path.relative_to(REPO).as_posix(), name) != FORWARDS_ITS_CALLERS_CODEC
    ]
    assert not unnamed, (
        "these decode with the caller's locale, so a UTF-8 file fails to read on a machine whose "
        "locale is not UTF-8: " + ", ".join(unnamed))


def test_the_one_call_that_cannot_name_a_codec_has_no_caller_that_forgets():
    """`paths.open_` uses its caller's codec, so the guarantee lives at the call sites."""
    callers = [
        f"{path.relative_to(REPO).as_posix()}:{line}"
        for path in _sources()
        for line, name, keywords in _file_calls(path)
        if name.endswith("open_") and "encoding" not in keywords
    ]
    assert not callers, f"these reach io.open with no codec through paths.open_: {callers}"


def test_going_through_paths_counts_as_naming_it(tmp_path):
    """`paths.read_text(p)` has named UTF-8 — by its signature's default, not at the call."""
    through = tmp_path / "through.py"
    through.write_text("from ai_sdlc_runner import paths\n"
                       "text = paths.read_text('a.json')\n", encoding="utf-8")
    assert _file_calls(through) == []


def test_a_bare_open_in_text_mode_is_caught(tmp_path):
    bare = tmp_path / "bare.py"
    bare.write_text("data = open('a.json').read()\n", encoding="utf-8")
    (line, name, keywords), = _file_calls(bare)
    assert name == "open" and "encoding" not in keywords


def test_a_binary_open_is_not_asked_to_name_a_codec(tmp_path):
    """There is no codec in play, so requiring one would be cargo cult."""
    binary = tmp_path / "binary.py"
    binary.write_text("blob = open('a.png', 'rb').read()\n"
                      "more = __import__('pathlib').Path('b.png').read_bytes()\n", encoding="utf-8")
    assert _file_calls(binary) == []


def test_a_method_merely_called_open_is_not_a_file(tmp_path):
    """`conversations.py` has `conv.open()`, which opens a conversation record, not a file.

    The first draft of this survey flagged it — and flagged `paths.read_text` too — which is the
    same name-for-a-constraint mistake `test_a_keyword_merely_spelled_text_is_not_a_subprocess`
    exists for, made twice more while investigating the change that was about it.

    **The gap this leaves, stated rather than hidden:** an AST walk cannot tell `conv.open()` from
    `some_path.open()`, so the attribute form is out of scope and a `Path.open()` in text mode
    would slip past. Nothing in `src/` or `tools/` uses one — checked, not assumed — and the two
    forms this project does use, bare `open()` and `paths.open_()`, are both covered.
    """
    innocent = tmp_path / "innocent.py"
    innocent.write_text("class Conversation:\n"
                        "    def open(self): pass\n"
                        "conv = Conversation()\n"
                        "conv.open()\n", encoding="utf-8")
    assert [c for c in _file_calls(innocent) if c[1] == "conv.open"] == []


def test_no_path_open_has_appeared_since(tmp_path):
    """The gap above is only acceptable while nothing uses the form it cannot see.

    So the claim is checked rather than asserted: `.open(` on anything but `io` or `paths` must be
    a method, and today the only one is `Conversation.open`. If a `Path.open()` is added, this goes
    red and whoever added it has to decide whether to widen the rule or route through `paths`.
    """
    import re
    calls = []
    for path in _sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for found in re.finditer(r"\b(\w+)\.open\(", line):
                if found.group(1) not in ("io", "paths"):
                    calls.append(f"{path.relative_to(REPO).as_posix()}:{number} {found.group(0)}")
    assert calls == [
        "src/ai_sdlc_runner/conversations.py:916 conv.open(",
        "src/ai_sdlc_runner/conversations.py:919 conv.open(",
    ], (
        "the set of `.open(` calls the AST survey cannot classify has changed. If one of these is a "
        f"Path, it opens a file with the caller's locale and needs an encoding: {calls}")


def test_the_file_survey_finds_the_calls_it_claims_to_find():
    """A survey that examined nothing passes `test_every_text_file_open_names_its_codec` trivially.

    That is not a hypothetical here: disabling the filter made the mutation come back NOT CAUGHT
    with fourteen tests green, because an empty list satisfies `assert not unnamed`. The subprocess
    half of this file already had this floor; the file half shipped without it for one run.
    """
    counted = sum(len(_file_calls(path)) for path in _sources())
    assert counted >= 20, f"only {counted} text file opens found; the walk is not reaching them"


def test_the_helpers_this_survey_trusts_really_do_default_to_utf8():
    """`_file_calls` exempts `paths.read_text`/`write_text` because their signatures name UTF-8.

    Nothing checked that. A survey that exempts a helper on the strength of a default it never reads
    is trusting a name again — and the exemption is load-bearing, since most file I/O here goes
    through those two. Found by a mutation that had nowhere to land.
    """
    import inspect
    sys.path.insert(0, str(REPO / "src"))
    from ai_sdlc_runner import paths

    for name in ("read_text", "write_text"):
        parameter = inspect.signature(getattr(paths, name)).parameters["encoding"]
        assert parameter.default == "utf-8", (
            f"paths.{name} defaults to {parameter.default!r}, so every call that omits `encoding` "
            f"— which this survey exempts — decodes with the caller's locale")
