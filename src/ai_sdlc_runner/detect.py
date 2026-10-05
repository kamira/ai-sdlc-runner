"""detect.py — which model CLIs this machine has, for `runner setup` (CHG-20261005-01).

**Local facts only.** A program is looked for on the absolute entries of `PATH`, and the one thing
ever executed is `ollama list`, with a timeout. Nothing probes a port or a network address: a
detector that reaches outside the process unasked is a different tool from one that reads what is
installed.

**Never the working directory.** On Windows the current directory is searched before `PATH`, and an
empty or relative `PATH` entry means the current directory everywhere. A repository an operator has
just cloned must not be able to plant a `claude` that `setup` then offers to dispatch work to, so
those entries are skipped rather than resolved.

**A proposal is not a decision.** `propose` returns registry entries with a suggested tier and an
effort template; the runner holds no table of which model is "mid" beyond the one it suggests for a
CLI that ships exactly one default. The user accepts, edits or declines each one.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from . import models as models_mod, paths

#: What `setup` looks for. Fixed, not configurable: each has a proposal written for it below.
TOOLS = ("claude", "codex", "ollama")

#: How long `ollama list` may take. It reads a local manifest; ten seconds is a hung daemon.
OLLAMA_TIMEOUT = 10


def _same_place(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:                                    # pragma: no cover - exotic filesystems
        return False


def _extensions(environ) -> Tuple[str, ...]:
    if os.name != "nt":
        return ("",)
    raw = environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return ("",) + tuple(e for e in raw.split(";") if e)


def find_tool(name: str, path: Optional[str] = None, cwd: Optional[str] = None,
              environ=None) -> Optional[str]:
    """The absolute path of `name` on `path`, or `None`. Relative entries and `cwd` are skipped."""
    environ = os.environ if environ is None else environ
    search = environ.get("PATH", "") if path is None else path
    here = cwd if cwd is not None else os.getcwd()
    for entry in search.split(os.pathsep):
        if not entry or not os.path.isabs(entry) or _same_place(entry, here):
            continue
        for ext in _extensions(environ):
            candidate = Path(entry) / (name + ext)
            if candidate.is_file() and (os.name == "nt" or os.access(str(candidate), os.X_OK)):
                return str(candidate)
    return None


def ollama_models(executable: str, timeout: int = OLLAMA_TIMEOUT) -> Tuple[List[str], str]:
    """`(names, problem)` from `ollama list`. A failure is a problem string, never an exception."""
    try:
        done = subprocess.run([executable, "list"], capture_output=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return [], f"`ollama list` did not answer within {timeout}s"
    except OSError as exc:
        return [], f"`ollama list` could not run: {paths.plain_in(str(exc))}"
    if done.returncode != 0:
        return [], f"`ollama list` exited {done.returncode}"
    names: List[str] = []
    for line in done.stdout.decode("utf-8", errors="replace").splitlines():
        words = line.split()
        if words and words[0].upper() != "NAME":
            names.append(words[0])
    return names, ""


def plain_id(prefix: str, name: str) -> str:
    """A registry id for a vendor's own model name, which may carry `:` and `.`."""
    return prefix + "-" + re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")


def propose(environ=None, path: Optional[str] = None, cwd: Optional[str] = None
            ) -> Tuple[List[models_mod.Model], List[str]]:
    """`(proposals, notes)`: what is installed, as registry entries, and what could not be read."""
    found = {tool: find_tool(tool, path=path, cwd=cwd, environ=environ) for tool in TOOLS}
    proposals: List[models_mod.Model] = []
    notes: List[str] = []
    if found["claude"]:
        proposals.append(models_mod.Model(
            id="claude-sonnet-5-5", vendor="anthropic", name="claude-sonnet-5-5",
            transport=models_mod.CLI, tier="mid",
            command=("claude", "-p", "--model", "claude-sonnet-5-5"),
            effort_argv=("--effort", "{effort}"),
            note=f"found at {found['claude']}"))
    if found["codex"]:
        proposals.append(models_mod.Model(
            id="codex", vendor="openai", name="codex-default", transport=models_mod.CLI,
            command=("codex", "exec", "-"),
            effort_argv=("-c", "model_reasoning_effort={effort}"),
            note=f"found at {found['codex']}. No model is named: add `--model <name>` to the "
                 f"command and set a tier"))
    if found["ollama"]:
        names, problem = ollama_models(found["ollama"])
        if problem:
            notes.append(problem)
        for name in names:
            proposals.append(models_mod.Model(
                id=plain_id("ollama", name), vendor="ollama", name=name,
                transport=models_mod.CLI, command=("ollama", "run", name),
                note=f"local, from `ollama list` ({found['ollama']})"))
    for model in proposals:
        models_mod.validate(model)
    return proposals, notes
