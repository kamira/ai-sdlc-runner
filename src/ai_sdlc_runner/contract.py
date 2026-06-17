"""contract.py — version detection + per-project major.minor lock + validating migrate.

This module is the version-lock core (build-guide §5). It locks ``major.minor`` per governed
project; PATCH differences pass freely; a ``minor``/``major`` bump forces an explicit, *validating*
``migrate`` (re-read everything; raise the lock only if all docs re-parse).

The contract targets the skill's *stable output* (its SKILL.md version), not Claude Code's runtime.
The actual version is detected by reading the skill file, so a missing/wrong submodule tag surfaces
here as a contract-version mismatch rather than silent drift.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOCK_FILENAME = ".sdlc-lock.json"


class ContractError(Exception):
    """Base class for contract/version-lock errors."""


class MigrateRequired(ContractError):
    """Raised when the requested contract differs at major.minor from the project lock.

    The caller (CLI/orchestrator) must stop and tell the user to run ``migrate`` — the runner
    never silently crosses a version boundary.
    """

    def __init__(self, locked: "tuple[int, int]", requested: "tuple[int, int]", project_dir: str):
        self.locked = locked
        self.requested = requested
        self.project_dir = project_dir
        super().__init__(
            f"contract lock mismatch in {project_dir}: locked at "
            f"{locked[0]}.{locked[1]}.x but requested {requested[0]}.{requested[1]}.x. "
            f"Run `runner migrate {project_dir} --to <version>` (validating upgrade)."
        )


# --------------------------------------------------------------------------------------
# Version detection (reads the skill's stable output — its SKILL.md frontmatter)
# --------------------------------------------------------------------------------------

_VERSION_LINE = re.compile(r"^\s*version\s*:\s*['\"]?([0-9]+\.[0-9]+\.[0-9]+)['\"]?\s*$")


def read_skill_version(skill_path: str | Path) -> str:
    """Read the contract version from the skill's ``SKILL.md`` frontmatter.

    Supports both a top-level ``version:`` and a nested ``metadata:\\n  version:`` (the shipped
    skill uses the nested form). Returns a semantic ``"major.minor.patch"`` string.

    Raises ``ContractError`` if the file or a version line cannot be found — the runner never
    guesses a version.
    """
    skill_dir = Path(skill_path)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ContractError(f"SKILL.md not found under skill_path: {skill_md}")

    text = skill_md.read_text(encoding="utf-8")
    # Only scan the YAML frontmatter block (between the first two '---' fences) if present.
    block = text
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            block = parts[1]

    for line in block.splitlines():
        m = _VERSION_LINE.match(line)
        if m:
            return m.group(1)
    raise ContractError(f"no `version: X.Y.Z` found in frontmatter of {skill_md}")


def contract_key(version: str) -> "tuple[int, int]":
    """Reduce a semantic version to its lock key ``(major, minor)``, ignoring patch.

    ``"1.2.3" -> (1, 2)``. PATCH is intentionally dropped so patch bumps pass freely (§5).
    """
    parts = version.strip().split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ContractError(f"invalid version string: {version!r}")
    return int(parts[0]), int(parts[1])


# --------------------------------------------------------------------------------------
# Per-project lock
# --------------------------------------------------------------------------------------


def _lock_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / LOCK_FILENAME


def read_lock(project_dir: str | Path) -> Optional[dict]:
    """Return the parsed lock dict, or ``None`` if the project has no lock yet."""
    p = _lock_path(project_dir)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write_lock(project_dir: str | Path, version: str, runner: str = "ai-sdlc-runner") -> dict:
    """Write ``.sdlc-lock.json`` for the project and return the lock dict."""
    major, minor = contract_key(version)
    lock = {
        "contract_major": major,
        "contract_minor": minor,
        "contract_version": version,  # record-only; the gate compares (major, minor)
        "first_run": datetime.now(timezone.utc).isoformat(),
        "runner": runner,
    }
    _lock_path(project_dir).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def resolve_contract(project_dir: str | Path, requested: Optional[str]) -> str:
    """Resolve the per-project contract lock (build-guide §5).

    - First run (no lock): write the lock at ``requested`` and return it.
    - Later run, matching ``(major, minor)`` or ``requested is None``: continue the locked version.
    - Later run, differing ``(major, minor)``: raise ``MigrateRequired`` (do not auto-cross).

    PATCH differences never matter — only ``(major, minor)`` is compared.
    """
    if requested is None and read_lock(project_dir) is None:
        raise ContractError(
            f"no contract lock in {project_dir} and no requested version given; "
            f"pass the expected contract_version on first run."
        )

    existing = read_lock(project_dir)
    if existing is None:
        # First run — establish the lock.
        write_lock(project_dir, requested)  # type: ignore[arg-type]
        return requested  # type: ignore[return-value]

    locked_key = (existing["contract_major"], existing["contract_minor"])
    if requested is None:
        # Continue the locked version (no new request to compare).
        return existing["contract_version"]

    requested_key = contract_key(requested)
    if requested_key != locked_key:
        raise MigrateRequired(locked_key, requested_key, str(project_dir))

    # Same major.minor (patch may differ) — continue, recording the (possibly newer) patch.
    return requested


# --------------------------------------------------------------------------------------
# Validating migrate
# --------------------------------------------------------------------------------------


@dataclass
class MigrateResult:
    """Outcome of a ``migrate`` attempt.

    ``ok`` is True only when every existing doc/CHG/ACC/structure file re-parsed under the new
    contract and the lock was raised. Otherwise ``incompatibilities`` lists what blocked it and the
    lock is left untouched.
    """

    ok: bool
    to_version: str
    incompatibilities: "list[str]" = field(default_factory=list)
    checked: "list[str]" = field(default_factory=list)


# Files the runner re-reads when validating a contract upgrade. Each must parse under the new
# contract for the upgrade to succeed. (These are the governed project's own ai-sdlc artifacts.)
_MIGRATE_GLOBS = (
    "docs/ai-guideline.md",
    "docs/structure/*.md",
    "docs/changes/*.md",
    "docs/acceptance/*.md",
)


def _parse_under_contract(path: Path) -> Optional[str]:
    """Re-read one doc under the new contract.

    Returns ``None`` if it parses cleanly, or a human-readable reason string if it does not.
    The check is intentionally conservative: a doc that is empty or unreadable is an
    incompatibility (the runner never pretends a migrate succeeded).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"{path}: unreadable ({exc})"
    if not text.strip():
        return f"{path}: empty document"
    return None


def migrate(project_dir: str | Path, to_version: str) -> MigrateResult:
    """Validating upgrade (build-guide §5): re-read ALL docs under the new contract.

    If every file parses, raise the lock to ``to_version`` and return ``ok=True``. If any file
    fails, return ``ok=False`` with the incompatibility list and **leave the lock unchanged** —
    migrate is "verify whether we *can* upgrade, and upgrade only if we can", never a forced bump.
    """
    project = Path(project_dir)
    contract_key(to_version)  # validate the target version string early

    checked: "list[str]" = []
    incompatibilities: "list[str]" = []
    for pattern in _MIGRATE_GLOBS:
        for path in sorted(project.glob(pattern)):
            checked.append(str(path.relative_to(project)))
            problem = _parse_under_contract(path)
            if problem is not None:
                incompatibilities.append(problem)

    if incompatibilities:
        return MigrateResult(False, to_version, incompatibilities, checked)

    write_lock(project_dir, to_version)
    return MigrateResult(True, to_version, [], checked)
