"""agents.py — parse the skill's role table and spawn role-scoped agents.

Role definitions are **read from the skill** (``references/agent-hierarchy.md`` → the "Role startup
spec" table), never hardcoded in the runner (build-guide §1.3, §7). The role chain is
``A1`` (analysis) → ``I1`` (lead implementer, may spawn ``I1.x``) → ``V1`` (independent verifier).

Hard invariant (build-guide §1.6, §6): a spawned ``V1`` must receive a tools allowlist that
**excludes ``Agent``** — mechanically preventing it from spawning sub-agents or fixing while verifying.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


class RoleError(Exception):
    """Raised when the role table cannot be parsed or a role is unknown."""


@dataclass
class RoleSpec:
    role: str
    can_spawn: bool          # holds the `Agent` tool?
    writable: bool           # may write CODE/STRUCTURE (not just docs)?
    can_execute: bool        # may run tests/CLI/scripts/GUI?
    writes_docs: bool        # may write its own docs (A1 guideline / V1 ACC)?
    scope: str = ""
    tools: "list[str]" = field(default_factory=list)


@dataclass
class AgentSpec:
    role: str
    tools: "list[str]"
    can_spawn: bool
    writable: bool
    scope: str
    prompt: str
    workdir: "Optional[str]" = None   # the project/repo dir the agent operates in (CLI cwd)


_TICK = "✓"
_CROSS = "✗"


def _cell_bool(cell: str) -> bool:
    """A table cell counts as True if it contains a check mark and no cross mark."""
    return _TICK in cell and _CROSS not in cell


def _role_token(first_cell: str) -> str:
    """Extract the role code from a first cell like ``**V1 verifier**`` → ``V1``."""
    cleaned = first_cell.replace("*", "").strip()
    return cleaned.split()[0] if cleaned else ""


def _compose_tools(can_spawn: bool, writable: bool, can_execute: bool, writes_docs: bool) -> "list[str]":
    """Compose a least-privilege tools allowlist from the role's capability flags.

    - ``Read``  : always.
    - ``Bash``  : if the role may execute (run tests/CLI).
    - ``Edit``  : only if the role may write code/structure (so read-only roles cannot edit code).
    - ``Write`` : if the role may write code/structure OR its own docs (A1 guideline, V1 ACC).
    - ``Agent`` : only if the role may spawn — **never for V1**.
    """
    tools = ["Read"]
    if can_execute:
        tools.append("Bash")
    if writable:
        tools.append("Edit")
    if writable or writes_docs:
        tools.append("Write")
    if can_spawn:
        tools.append("Agent")
    return tools


def parse_role_table(skill_path: str | Path) -> Dict[str, RoleSpec]:
    """Parse the "Role startup spec" table in ``references/agent-hierarchy.md``.

    Returns ``{role_code: RoleSpec}``. The table columns are
    ``Role | Can spawn | Can write code/structure | Can execute | Notes``.
    """
    ref = Path(skill_path) / "references" / "agent-hierarchy.md"
    if not ref.is_file():
        raise RoleError(f"agent-hierarchy.md not found: {ref} (is the ai-skills submodule wired up?)")

    lines = ref.read_text(encoding="utf-8").splitlines()

    # Locate the startup-spec table header: a row mentioning Role + Can spawn.
    header_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|") and "Role" in line and re.search(r"spawn", line, re.I):
            header_idx = i
            break
    if header_idx is None:
        raise RoleError(f"could not find the 'Role startup spec' table in {ref}")

    specs: Dict[str, RoleSpec] = {}
    # Data rows start two lines after the header (header, separator, then rows).
    for line in lines[header_idx + 2:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break  # table ended
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        role = _role_token(cells[0])
        if not role:
            continue
        can_spawn = _cell_bool(cells[1])
        writable = _cell_bool(cells[2])
        can_execute = _cell_bool(cells[3])
        notes = " ".join(cells[1:]).lower()
        writes_docs = ("doc" in notes) or ("acc" in notes) or ("acceptance" in notes)
        tools = _compose_tools(can_spawn, writable, can_execute, writes_docs)
        specs[role] = RoleSpec(
            role=role,
            can_spawn=can_spawn,
            writable=writable,
            can_execute=can_execute,
            writes_docs=writes_docs,
            scope=cells[2],
            tools=tools,
        )
    if not specs:
        raise RoleError(f"no role rows parsed from the spec table in {ref}")
    return specs


def _resolve_role(role: str, table: Dict[str, RoleSpec]) -> RoleSpec:
    """Resolve a concrete role id to its spec, mapping ``I1.1``/``I1.2`` → the ``I1.x`` template."""
    if role in table:
        return table[role]
    if re.fullmatch(r"I1\.\d+", role) and "I1.x" in table:
        return table["I1.x"]
    raise RoleError(f"unknown role {role!r}; known: {sorted(table)}")


def spawn(skill_path: str | Path, role: str, scope: str, task: str,
          workdir: Optional[str] = None) -> AgentSpec:
    """Build the launch spec for an agent of ``role`` with its role-scoped tools allowlist.

    The prompt always carries "load the ai-sdlc skill + your role & scope"; when ``workdir`` is set
    (the target project/repo), it is named in the prompt and carried on the spec so the executor runs
    the agent there. Enforces the §1.6 invariant: a ``V1`` spec must never include the ``Agent`` tool.
    """
    table = parse_role_table(skill_path)
    spec = _resolve_role(role, table)

    # Concrete agents (e.g. I1.1) inherit the I1.x template tools.
    tools = list(spec.tools)

    if role == "V1" and "Agent" in tools:
        raise RoleError("invariant violated: V1 must not receive the `Agent` tool")

    workdir_line = f"Project (working dir): {workdir}\n" if workdir else ""
    prompt = (
        f"Load the ai-sdlc skill. You are agent {role}.\n"
        f"{workdir_line}"
        f"Role scope: {scope or spec.scope}\n"
        f"Task: {task}\n"
        f"Stay within your remit; do not exceed your granted scope."
    )
    return AgentSpec(
        role=role,
        tools=tools,
        can_spawn=spec.can_spawn,
        writable=spec.writable,
        scope=scope or spec.scope,
        prompt=prompt,
        workdir=workdir,
    )
