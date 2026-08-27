"""Every shipped example runs through the real CLI, from a directory that is not its own.

This is the test that did not exist (CHG-20260823-48). `agent_command` was passed to
`subprocess.run` as argv, so a relative path in it resolved against **the operator's shell** — and
the three shipped examples disagreed about which directory they meant:

    examples/minimal      ["python3", "examples/minimal/agent.py"]   relative to the repo root
    examples/tide-spa     ["python3", "agent.py"]                    relative to itself
    examples/weather-spa  ["python3", "agent.py"]                    relative to itself

Two conventions, one field, neither documented. `README.md` line 458 runs `minimal` from the repo
root and works; the identical shape against `tide-spa` halts at the first ask.

## Why the existing example tests did not notice

`test_example_weather_spa.py` copies `agent.py` into `tmp_path` and runs it with `cwd=str(tmp_path)`
— and invokes the agent **directly**, `[sys.executable, str(tmp_path / "agent.py")]`, never through
`runner --config`. It performs the `cd` the documentation omits and never touches `agent_command`
resolution at all.

That is this project's most-recorded shape: a test that arranges the exact conditions under which
the defect cannot appear, and reports the thing as covered.

## What this test does instead

Copies an example somewhere else entirely, then drives it **through the real CLI** from two working
directories that are not the copy's own: the repo root, and an unrelated empty directory.

Two, because one was not enough — and finding that out is the reason this docstring says something
different from its first draft. That draft ran only from the repo root and claimed every case failed
against the unfixed code. `minimal` **passed**, and passed for a worse reason than failing would
have been: its `agent_command` said `examples/minimal/agent.py`, which from the repo root resolves
to the **original example still sitting in the repo**. The copy under test never ran its own agent
and nothing noticed. A test that cannot tell those apart is measuring the wrong thing.

From an unrelated directory that coincidence is gone, and all three fail against the unfixed code.
The repo-root case is kept because it is the one `README.md` line 458 actually documents.

These are subprocess tests that walk a whole flow, and they cost real seconds. That is the price of
the claim being true from more than one directory.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

#: Every directory under `examples/` that ships a runner.yaml and a plan. Discovered rather than
#: listed: an example added later gets this test for free, and one that is deleted does not leave a
#: name here pointing at nothing. A hand-written list is how `minimal` came to be the only one that
#: worked from the repo root without anybody noticing the other two did not.
SHIPPED = sorted(d.name for d in EXAMPLES.iterdir()
                 if (d / "runner.yaml").is_file() and (d / "plan.json").is_file())


def test_the_discovery_actually_found_the_examples():
    """A parametrised test over an empty list passes without running anything. This is the guard
    that stops a broken glob from reading as three green cases."""
    assert len(SHIPPED) >= 3, f"expected the shipped examples, found {SHIPPED}"
    for name in ("minimal", "tide-spa", "weather-spa"):
        assert name in SHIPPED, f"{name} is shipped but was not discovered: {SHIPPED}"


#: The two places to stand. `repo-root` is the one README.md line 458 documents; `elsewhere` is the
#: one that removes the coincidence keeping `minimal` alive — see this module's docstring.
WHERE = ["repo-root", "elsewhere"]


@pytest.mark.parametrize("example", SHIPPED)
@pytest.mark.parametrize("where", WHERE)
def test_a_shipped_example_runs_from_a_directory_that_is_not_its_own(example, where, tmp_path):
    """Copy it elsewhere, run it from somewhere that is not the copy, require it to finish.

    The copy matters as much as the cwd. Running `examples/tide-spa` from the repo root fails
    against the old code; running `examples/minimal` from there **passes**, because its path was
    written for that one directory and resolves to the original example still in the repo. So the
    run under test would quietly use somebody else's agent. `where="elsewhere"` is what tells those
    two apart.
    """
    here = tmp_path / example
    shutil.copytree(EXAMPLES / example, here,
                    ignore=shutil.ignore_patterns("__pycache__", "site", "*.pyc"))

    stand = ROOT if where == "repo-root" else tmp_path / "somewhere-unrelated"
    if where != "repo-root":
        stand.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(here / "runner.yaml"),
         "run", "--plan", str(here / "plan.json"),
         "--risk", "low", "--confirm", "merge",
         "--ask-journal", str(tmp_path / "asks")],
        cwd=str(stand),                     # <- deliberately NOT the example's directory
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**_env(), "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"},
        timeout=600)

    out = (proc.stdout or "") + (proc.stderr or "")
    assert "can't open file" not in out, (
        f"{example} could not find its own agent when run from {where}. Its `agent_command` path "
        f"is being resolved against the shell rather than against its runner.yaml:\n{out[-900:]}")
    assert "state:         finished" in out, (
        f"{example} did not finish when run from {where}:\n{out[-900:]}")


@pytest.mark.parametrize("example", SHIPPED)
def test_a_shipped_example_writes_only_inside_itself(example, tmp_path):
    """An example run from the repo root must not leave anything in the repo root.

    The other half of what `minimal` was doing wrong. Its agent was found at
    `<repo>/examples/minimal/agent.py` and run with the shell's directory, so anything it wrote
    relative to itself landed wherever the operator happened to be standing — the repository, in the
    documented case. The run appeared to work, which is why nobody looked.
    """
    here = tmp_path / example
    shutil.copytree(EXAMPLES / example, here,
                    ignore=shutil.ignore_patterns("__pycache__", "site", "*.pyc"))
    before = {p.name for p in ROOT.iterdir()}

    subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(here / "runner.yaml"),
         "run", "--plan", str(here / "plan.json"),
         "--risk", "low", "--confirm", "merge",
         "--ask-journal", str(tmp_path / "asks")],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**_env(), "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"}, timeout=600)

    new = {p.name for p in ROOT.iterdir()} - before
    assert not new, (
        f"running {example} from the repo root created {sorted(new)} in the repository. The agent "
        f"ran in the operator's directory instead of its own.")


def _env():
    import os
    return dict(os.environ)
