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
