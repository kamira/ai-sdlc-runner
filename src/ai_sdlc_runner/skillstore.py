"""skillstore.py — resolve the skill from a local, offline, multi-version store.

Per CHG-20260617-05 the runner keeps a vendored skill store (e.g. ``skills/v1.0.0``, ``skills/v1.1.0``)
so it can run **fully offline** with several contract versions on hand. This module lists the versions
in a store and resolves the right one — by a project's lock major.minor when possible — returning a
concrete ``skill_path`` for the rest of the runner to read/call.

The store holds verbatim skill snapshots (SKILL.md + references/ + scripts/ + assets/), extracted
offline from the ai-skills git tags. The runner still reads governance from those files / calls those
scripts — it never duplicates the logic.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from . import contract

# A version directory is named like "v1.2.3" (or "1.2.3") and contains a SKILL.md.
_VERSION_DIR = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _semver(version: str) -> Tuple[int, int, int]:
    m = _VERSION_DIR.match(version.strip())
    if not m:
        raise ValueError(f"not a version dir name: {version!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def store_versions(store_dir: str | Path) -> List[str]:
    """List version strings present in the store (newest first); only dirs that contain a SKILL.md."""
    base = Path(store_dir)
    if not base.is_dir():
        return []
    found: List[Tuple[int, int, int]] = []
    for child in base.iterdir():
        if child.is_dir() and _VERSION_DIR.match(child.name) and (child / "SKILL.md").is_file():
            found.append(_semver(child.name))
    found.sort(reverse=True)
    return [f"{a}.{b}.{c}" for a, b, c in found]


def _dir_for(store_dir: str | Path, version: str) -> Path:
    """Return the on-disk dir for a version, accepting both ``v1.2.3`` and ``1.2.3`` directory names."""
    base = Path(store_dir)
    for name in (f"v{version}", version):
        if (base / name / "SKILL.md").is_file():
            return base / name
    raise FileNotFoundError(f"version {version} not found in store {store_dir}")


def latest_version(store_dir: str | Path) -> Optional[str]:
    versions = store_versions(store_dir)
    return versions[0] if versions else None


def resolve_path(
    store_dir: str | Path,
    *,
    version: Optional[str] = None,
    major: Optional[int] = None,
    minor: Optional[int] = None,
) -> Optional[str]:
    """Resolve a concrete skill path from the store.

    Precedence: an exact ``version`` → the highest patch matching ``major.minor`` → ``None``.
    Returns a path string (so callers can pass it straight to the rest of the runner) or ``None`` if
    the store has no suitable version.
    """
    versions = store_versions(store_dir)
    if not versions:
        return None
    if version is not None:
        try:
            return str(_dir_for(store_dir, version))
        except FileNotFoundError:
            return None
    if major is not None and minor is not None:
        candidates = [v for v in versions if _semver(v)[:2] == (major, minor)]
        if candidates:
            return str(_dir_for(store_dir, candidates[0]))  # highest patch (versions is sorted desc)
        return None
    return str(_dir_for(store_dir, versions[0]))  # latest


def detect(
    store_dir: str | Path,
    project_dir: Optional[str | Path] = None,
    expected: Optional[str] = None,
) -> Optional["contract.UpdateInfo"]:
    """Compare the **newest version in the store** to the project lock / expected baseline.

    Answers "does my local store hold an update for this project?" Reuses ``contract.detect_update``
    on the latest store version's path, so the patch/minor/major classification is identical. Returns
    ``None`` if the store is empty.
    """
    latest = latest_version(store_dir)
    if latest is None:
        return None
    latest_path = resolve_path(store_dir, version=latest)
    info = contract.detect_update(latest_path, expected=expected, project_dir=project_dir)
    # latest_tag here means "newest version available in the store".
    info.latest_tag = latest
    return info
