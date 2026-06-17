"""gates.py — halt-point + cross-repo-drift queries by *calling the skill's scripts*.

The runner holds **no** risk matrix of its own (build-guide §1.3, §7). Every halt decision is
delegated to the skill's ``scripts/halt_gate.py`` via ``subprocess``; cross-repo drift is delegated
to ``scripts/cross_repo_check.py``. The runner only branches on the script's exit code.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Exit-code contract of halt_gate.py (build-guide §3 / the script's own docstring):
EXIT_AUTO = 0      # continue autonomously
EXIT_HALT = 10     # stop and await human approval
# any other code -> treated as an error (conservative; never silently continue)


class GateError(Exception):
    """Raised when a gate script is missing or returns an unexpected exit code."""


@dataclass
class Decision:
    result: str          # "AUTO" or "HALT"
    gate: str
    risk: str
    reason: str = ""

    @property
    def is_halt(self) -> bool:
        return self.result == "HALT"


def _script(skill_path: str | Path, name: str) -> Path:
    p = Path(skill_path) / "scripts" / name
    if not p.is_file():
        raise GateError(f"skill script not found: {p} (is the ai-skills submodule wired up?)")
    return p


def check_halt(
    skill_path: str | Path,
    gate: str,
    risk: str,
    action: Optional[str] = None,
    autonomy: Optional[str] = None,
) -> Decision:
    """Query the halt contract by calling the skill's ``halt_gate.py``.

    Builds ``python3 halt_gate.py --gate <gate> --risk <risk> [--action ...] [--autonomy ...]``,
    runs it, and maps the exit code: ``0 -> AUTO``, ``10 -> HALT``, anything else -> ``GateError``.
    The runner never re-derives the decision itself.
    """
    script = _script(skill_path, "halt_gate.py")
    cmd = [sys.executable, str(script), "--gate", gate, "--risk", risk, "--why"]
    if action:
        cmd += ["--action", action]
    if autonomy:
        cmd += ["--autonomy", autonomy]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    reason = (proc.stdout or "").strip() or (proc.stderr or "").strip()

    if proc.returncode == EXIT_AUTO:
        return Decision("AUTO", gate, risk, reason)
    if proc.returncode == EXIT_HALT:
        return Decision("HALT", gate, risk, reason)
    raise GateError(
        f"halt_gate.py returned unexpected exit code {proc.returncode} "
        f"for gate={gate} risk={risk}: {reason}"
    )


def check_cross_repo_drift(
    skill_path: str | Path,
    authority: str | Path,
    repos: "list[str]",
) -> Decision:
    """Query cross-repo drift by calling the skill's ``cross_repo_check.py``.

    Exit code ``0`` is treated as AUTO (consistent); any non-zero as HALT (drift/needs attention),
    surfacing the script's output as the reason. The runner does not interpret the drift itself.
    """
    script = _script(skill_path, "cross_repo_check.py")
    cmd = [sys.executable, str(script), "--authority", str(authority), "--repos", *map(str, repos)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    reason = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode == 0:
        return Decision("AUTO", "cross_repo", "n/a", reason)
    return Decision("HALT", "cross_repo", "n/a", reason)
