"""What the auditor is given to read, and what it was not (CHG-20261028-01, task 2a).

`audit_read` reads "the change and what it touches": the diff, the modules it modifies, and their
direct callers and callees. That is a file list, assembled here by the runner, never by a model, and
bounded by `AUDIT_SCOPE_MAX_CHARS`. Every file in scope is recorded as `read` (inside the cap) or
`cut` (left out because the cap was reached), with the cap and the total, so an audit that passed
over code it never saw does not read as a full audit (Q3).

Callers and callees are resolved for Python only, from `import` statements (`ast`). A changed file
in another language is in scope as a changed file and nothing is followed from it; the scope says
so in `notes` rather than implying a reading it did not do.

Standard library only; `git` is asked for the change and its absence is a note, not a failure.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import paths

#: How many characters of source the auditor is sent to read. **Provisional** (CHG-20261028-01, Q3):
#: the value is a first estimate, set when task 2a was built and to be measured against run 4 of
#: CHG-20261019-01 -- a figure that the record, and not this comment, should change.
AUDIT_SCOPE_MAX_CHARS = 200_000

#: Why a file is in scope, in the order the cap is spent: the change first, then what it calls,
#: then what calls it.
REASONS = ("diff", "callee", "caller")

#: Directories never walked for callers: not the project's source, and often large.
_SKIPPED = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", "build", "dist",
            ".mypy_cache", ".pytest_cache"}

#: A repository with more Python files than this is not walked for callers (the scope says so).
_MAX_PY_FILES = 5000


def _git(workdir: str, *args: str) -> Optional[str]:
    """Stdout of a git command, or `None` when git is absent, fails, or this is not a repository."""
    if shutil.which("git") is None:
        return None
    try:
        done = subprocess.run(["git", *args], cwd=workdir or None, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):       # pragma: no cover - exotic environments
        return None
    return done.stdout if done.returncode == 0 else None


def capture_base(workdir: str = ".") -> Optional[str]:
    """The commit the change is measured from: `HEAD` now, or `None` without a repository.

    Taken before the first build so the diff is "what this run changed" and not "what differs from
    wherever the branch happens to be later".
    """
    out = _git(workdir, "rev-parse", "HEAD")
    return out.strip() or None if out is not None else None


def _changed(workdir: str, base: Optional[str]) -> Optional[List[str]]:
    """Changed and new files, repo-relative, sorted; `None` when git cannot say."""
    diff = _git(workdir, "diff", "--name-only", "-z", base or "HEAD", "--")
    if diff is None:
        return None
    new = _git(workdir, "ls-files", "--others", "--exclude-standard", "-z") or ""
    names = {n for n in (diff + "\0" + new).split("\0") if n}
    return sorted(names)


def _top(workdir: str) -> str:
    out = _git(workdir, "rev-parse", "--show-toplevel")
    return out.strip() if out and out.strip() else workdir


def _python_files(root: str) -> Optional[List[str]]:
    found: List[str] = []
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIPPED and not d.startswith("."))
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.relpath(os.path.join(here, name), root).replace(os.sep, "/"))
                if len(found) > _MAX_PY_FILES:
                    return None
    return found


def _dotted(rel: str) -> List[str]:
    """The module names a repo-relative `.py` path answers to (`src/` layouts included)."""
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    names = []
    if parts:
        names.append(".".join(parts))
        if parts[0] == "src" and len(parts) > 1:
            names.append(".".join(parts[1:]))
    return names


def _imports(root: str, rel: str, known: Dict[str, str]) -> Set[str]:
    """The repo-relative files `rel` imports, through names in `known`."""
    try:
        tree = ast.parse(paths.read_text(Path(root) / rel, encoding="utf-8"))
    except (OSError, ValueError, SyntaxError):
        return set()
    package = _dotted(rel)[-1].split(".") if _dotted(rel) else []
    if not rel.endswith("/__init__.py") and package:
        package = package[:-1]                  # a module's package is its parent
    wanted: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            wanted.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - (node.level - 1)] if node.level > 1 else package
                stem = ".".join(base + ([node.module] if node.module else []))
            else:
                stem = node.module or ""
            if stem:
                wanted.append(stem)
            for a in node.names:                # `from pkg import module` names a file
                wanted.append(f"{stem}.{a.name}" if stem else a.name)
    return {known[w] for w in wanted if w in known and known[w] != rel}


def _size(root: str, rel: str) -> Optional[int]:
    """Characters in a text file, or `None` when it cannot be read as text."""
    try:
        return len(paths.read_text(Path(root) / rel, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def assemble(workdir: str = ".", base: Optional[str] = None, *,
             max_chars: int = AUDIT_SCOPE_MAX_CHARS) -> Dict[str, object]:
    """The audit scope as a file list: each file with why it is there, its size, and `read`/`cut`.

    The cap is spent in `REASONS` order, file by file; a file that does not fit is `cut` and a
    smaller one after it may still be `read`, so the record says exactly which files the auditor
    was given. ``total_chars`` is the size of everything in scope and ``read_chars`` of what fit.
    """
    notes: List[str] = []
    root = _top(workdir)
    changed = _changed(workdir, base)
    if changed is None:
        notes.append("git could not say what changed (not a repository, or git is absent), "
                     "so the scope holds no files")
        changed = []
    py_files = _python_files(root)
    known: Dict[str, str] = {}
    if py_files is None:
        notes.append(f"more than {_MAX_PY_FILES} Python files: callers and callees were not followed")
        py_files = []
    for rel in py_files:
        for name in _dotted(rel):
            known.setdefault(name, rel)
    if any(not c.endswith(".py") for c in changed):
        notes.append("callers and callees are resolved for Python only; other changed files are "
                     "in scope as changed files")

    entries: List[Dict[str, object]] = []
    seen: Set[str] = set()

    def add(rel: str, why: str) -> None:
        if rel in seen:
            return
        seen.add(rel)
        entries.append({"path": rel, "why": why})

    for rel in changed:
        add(rel, "diff")
    changed_py = [c for c in changed if c.endswith(".py")]
    for rel in changed_py:
        for dep in sorted(_imports(root, rel, known)):
            add(dep, "callee")
    if changed_py:
        for rel in py_files:
            if rel in seen:
                continue
            if _imports(root, rel, known) & set(changed_py):
                add(rel, "caller")

    left = max_chars
    total = read_chars = 0
    for entry in entries:
        size = _size(root, str(entry["path"]))
        if size is None:
            # Deleted by the change, or binary: nothing there to read, and the record says so.
            entry["chars"] = 0
            entry["state"] = "read"
            entry["note"] = "not readable as text (deleted or binary)"
            continue
        entry["chars"] = size
        total += size
        if size <= left:
            entry["state"] = "read"
            left -= size
            read_chars += size
        else:
            entry["state"] = "cut"
    return {"base": base, "cap": max_chars, "total_chars": total, "read_chars": read_chars,
            "files": entries,
            "cut": [str(e["path"]) for e in entries if e["state"] == "cut"],
            "notes": notes}


def reading_list(scope: Dict[str, object]) -> List[str]:
    """The paths the auditor is told to read: the files the cap let in."""
    return [str(e["path"]) for e in scope.get("files", []) if e.get("state") == "read"
            and not e.get("note")]


def summary(scope: Dict[str, object]) -> List[str]:
    """Lines for the console and the report: the scope in one, then every file the cap cut."""
    files = list(scope.get("files") or [])
    if not files and not scope.get("notes"):
        return []
    cut = list(scope.get("cut") or [])
    lines = [f"audit scope: {len(files) - len(cut)} of {len(files)} file(s) read, "
             f"{scope.get('read_chars', 0)} of {scope.get('total_chars', 0)} characters "
             f"(cap {scope.get('cap')})"]
    if cut:
        lines.append("audit scope CUT, the auditor did not read: " + ", ".join(cut))
    for note in scope.get("notes") or []:
        lines.append(f"audit scope note: {note}")
    return lines


def save(directory: Path, scope: Dict[str, object]) -> str:
    """Write the scope under the audit directory; return the file name."""
    import json
    paths.makedirs(directory)
    paths.write_text(directory / "scope.json", json.dumps(scope, indent=2, sort_keys=True))
    return "scope.json"


def load_base(directory: Path) -> Tuple[bool, Optional[str]]:
    """The remembered base as `(found, sha)`. A saved `null` (no repository) is found, with no sha."""
    import json
    try:
        data = json.loads(paths.read_text(directory / "base.json", encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    return (True, data.get("base")) if isinstance(data, dict) else (False, None)


def save_base(directory: Path, sha: Optional[str]) -> None:
    import json
    paths.makedirs(directory)
    paths.write_text(directory / "base.json", json.dumps({"base": sha}))
