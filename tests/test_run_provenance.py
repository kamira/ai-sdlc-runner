"""What a conversation records about the run that produced it.

CHG-20260823-49, from the survey ACC-20260823-48 reservation 2 asked for.

`--plan`, `--ask-journal`, `--store-root` and `--token-dir` are all CLI paths, and cwd-relative is
the *correct* meaning for a CLI path — you typed it where you were standing. The question worth
asking is different:

    does the path get RECORDED somewhere that outlives that shell,
    and if so, is what got recorded still meaningful there?

Surveyed by running each from two shells with identical relative arguments:

| flag | recorded? | verdict |
|---|---|---|
| `--ask-journal` | yes, `.resolve()`d | sound |
| `--store-root` | no — names a directory at use | sound |
| `--token-dir` | no — places the token, attachments, asks at use | sound |
| `--plan` | **yes, as typed** | **the finding** |

Two runs of two *different* plan files recorded the identical string `"ex/plan.json"`, while
`journal` in the same dict was absolute.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/minimal"


def _run(shell, *args):
    return subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli", *args],
        cwd=str(shell), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"}, timeout=600)


def _walk(shell):
    """One green run, every path argument given **relative**, and what it recorded."""
    shutil.copytree(EXAMPLE, shell / "ex",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "greet.py"))
    proc = _run(shell,
                "--config", "ex/runner.yaml",
                "run", "--plan", "ex/plan.json",
                "--risk", "low", "--confirm", "merge",
                "--ask-journal", "asks", "--project", "provenance",
                "--store", "sqlite", "--store-root", "store")
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "state:         finished" in out, out[-800:]

    import sqlite3
    con = sqlite3.connect(str(shell / "store" / "conversations.sqlite"))
    try:
        row = con.execute("SELECT run_json FROM conversations").fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row and row[0] else {}


def test_the_plan_a_run_walked_is_recorded_as_a_place_not_as_a_keystroke(tmp_path):
    """Two shells, two different plan files, the same relative string typed at both.

    Before this, both recorded `"ex/plan.json"` — so the store held two conversations whose
    provenance was identical and whose plans were not. Nothing reads the field back, which is why
    it went unnoticed and is the reason to fix it: its only reader is a person, later, asking which
    plan produced a conversation.
    """
    a, b = tmp_path / "shell-a", tmp_path / "shell-b"
    a.mkdir()
    b.mkdir()
    ran_a, ran_b = _walk(a), _walk(b)

    assert ran_a["plan"] != ran_b["plan"], (
        f"two different plan files recorded the same provenance: {ran_a['plan']!r}")
    assert Path(ran_a["plan"]).is_absolute(), (
        f"the plan was recorded as typed rather than as a place: {ran_a['plan']!r}")
    assert Path(ran_a["plan"]).name == "plan.json"
    assert str(a) in ran_a["plan"] and str(b) in ran_b["plan"]


def test_the_two_provenance_fields_agree_with_each_other(tmp_path):
    """`journal` was resolved and `plan` was not, in the same dict literal. Whatever the rule is,
    one dict should not hold two of them — that inconsistency is what made this findable."""
    shell = tmp_path / "shell"
    shell.mkdir()
    ran = _walk(shell)

    for field in ("journal", "plan"):
        assert ran.get(field), f"{field} was not recorded at all: {ran}"
        assert Path(ran[field]).is_absolute(), (
            f"run.{field} is recorded relative while the other field is absolute: {ran}")


def test_a_run_with_no_plan_records_no_plan():
    """`Path("").resolve()` is the working directory. Resolving an absent value would record a
    confident answer to a question nobody asked — the runner's own most-repeated defect class."""
    from ai_sdlc_runner import cli

    assert cli._where(None) == ""
    assert cli._where("") == ""


def test_a_plan_that_does_not_exist_is_still_recorded_as_a_place():
    """The case CI caught and this machine could not.

    Before Python 3.10, `Path.resolve()` on Windows returned a **non-existent** relative path
    unchanged (bpo-38671), and `requires-python` here is `>=3.9`. The first version of `_where`
    used `resolve()` alone and recorded `plan.json` verbatim on that combination — the defect the
    function exists to prevent, on a supported platform, green on four of the five CI jobs.

    The two tests above it walk a real run, so their plan file **exists** and resolves fine
    everywhere. A path that is not there is the only input that separates the two implementations,
    which is why this test names one.
    """
    from ai_sdlc_runner import cli

    for missing in ("plan.json", "no/such/plan.json", "./plan.json"):
        recorded = cli._where(missing)
        assert Path(recorded).is_absolute(), (
            f"_where({missing!r}) recorded {recorded!r}, which is not a place. On Python 3.9 for "
            f"Windows `Path.resolve()` alone leaves a non-existent relative path unchanged.")
        assert Path(recorded).name == "plan.json"
