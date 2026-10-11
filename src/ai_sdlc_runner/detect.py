"""detect.py — which model CLIs this machine has, for `runner setup` (CHG-20261005-01).

**Local facts only.** A program is looked for on the absolute entries of `PATH`, and the one thing
ever executed is `ollama list`, with a timeout. Nothing probes a port or a network address: a
detector that reaches outside the process unasked is a different tool from one that reads what is
installed.

**Never the working directory.** On Windows the current directory is searched before `PATH`, and an
empty or relative `PATH` entry means the current directory everywhere. A repository an operator has
just cloned must not be able to plant a `claude` that `setup` then offers to dispatch work to, so
those entries are skipped rather than resolved.

**The path found is the path dispatched.** `command[0]` is the absolute path `find_tool` returned,
not the bare name: dispatch would otherwise look the name up again with the operating system's own
search, which may include the working directory, and run a different program than the one `setup`
showed.

**A proposal is not a decision.** `propose` returns registry entries (claude with a tier and an effort
template, codex with an effort template only, ollama with neither); the runner holds no table of which
model is "mid" beyond the one it suggests for a CLI that ships exactly one default. The user accepts,
edits or declines each one.

**Where the work goes is said, not inferred.** `claude` and `codex` are thin clients: the prompt, which
carries the work order and the repository's content, goes to the vendor's hosted API. Their entries
declare reach `external`, so every surface that reports whether work leaves the machine says it does.
`ollama` stays `local`, which assumes the daemon is local: `OLLAMA_HOST` can point it elsewhere.
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


def _on_windows() -> bool:
    """Its own function so a test can answer yes on Linux; `os.name` itself cannot be patched
    without breaking `pathlib`, which picks its flavour from it."""
    return os.name == "nt"


def _extensions(environ, name: str = "") -> Tuple[str, ...]:
    """The suffixes to try after `name`. On Windows only PATHEXT ones, as `cmd.exe` does.

    The bare name is not tried there unless it already ends in one: npm installs `claude` and
    `codex` as three files, an extensionless POSIX shell shim beside `.cmd` and `.ps1`, and
    Windows cannot run the shim (`WinError 193`). Since the path found is the path dispatched,
    picking it would freeze a command that never starts into the registry.
    """
    if not _on_windows():
        return ("",)
    raw = environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    exts = tuple(e for e in raw.split(";") if e)
    return ("",) if name.lower().endswith(tuple(e.lower() for e in exts)) else exts


def find_tool(name: str, path: Optional[str] = None, cwd: Optional[str] = None,
              environ=None) -> Optional[str]:
    """The absolute path of `name` on `path`, or `None`. Relative entries and `cwd` are skipped."""
    environ = os.environ if environ is None else environ
    search = environ.get("PATH", "") if path is None else path
    here = cwd if cwd is not None else os.getcwd()
    for entry in search.split(os.pathsep):
        if not entry or not os.path.isabs(entry) or _same_place(entry, here):
            continue
        for ext in _extensions(environ, name):
            candidate = Path(entry) / (name + ext)
            if candidate.is_file() and (_on_windows() or os.access(str(candidate), os.X_OK)):
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
            command=(found["claude"], "-p", "--model", "claude-sonnet-5-5"),
            effort_argv=("--effort", "{effort}"), declared_reach=models_mod.EXTERNAL,
            note="the claude CLI sends the work order and the repository's content to Anthropic"))
    if found["codex"]:
        proposals.append(models_mod.Model(
            id="codex", vendor="openai", name="codex-default", transport=models_mod.CLI,
            command=(found["codex"], "exec", "-"),
            effort_argv=("-c", "model_reasoning_effort={effort}"),
            declared_reach=models_mod.EXTERNAL,
            note="the codex CLI sends the work order and the repository's content to OpenAI. No "
                 "model is named. Once the store has entries `run` and `serve` no longer read "
                 "models.json, so editing it changes nothing: in the console's model editor "
                 "(POST /models) add a second entry under a new id, with `--model <name>` in "
                 "its command and a tier. That route only adds; it does not change this one"))
    if found["ollama"]:
        names, problem = ollama_models(found["ollama"])
        if problem:
            notes.append(problem)
        for name in names:
            proposals.append(models_mod.Model(
                id=plain_id("ollama", name), vendor="ollama", name=name,
                transport=models_mod.CLI, command=(found["ollama"], "run", name),
                note=f"local, from `ollama list` ({found['ollama']})"))
    for model in proposals:
        models_mod.validate(model)
    return proposals, notes
