"""structure_scan.py — deterministic structure analysis across a workspace.

Runs *before* the AI-SDLC loop. For each project it produces a real, deterministic scan (directory
tree summary, detected languages, entry points) and scaffolds the four structure docs
(`docs/structure/{directory,logical,design,data}.md`); the `directory` doc is filled from the actual
tree, the other three are seeded with the scan facts for the A1 analysis stage to complete.

For a multi-project workspace it also wires up the skill's cross-repo model: the authority gets
`docs/contracts/VERSION` (the shared contract version) + a contract-surface note, and each consumer
gets a `docs/authority.md` pointer pinned to that version. `cross_repo_check.py` reads exactly these.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from . import workspace as ws_mod

# Directories we never descend into when scanning.
_SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".mypy_cache",
         ".pytest_cache", ".idea", ".vscode", "target", ".sdlc-runner"}

_LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".cpp": "C++", ".cs": "C#", ".kt": "Kotlin", ".swift": "Swift",
}
_ENTRY_HINTS = ("main.py", "__main__.py", "manage.py", "app.py", "cli.py", "index.js", "server.js",
                "main.go", "main.rs", "Cargo.toml", "pyproject.toml", "package.json", "go.mod")


@dataclass
class RepoScan:
    path: str
    tree: List[str] = field(default_factory=list)
    languages: Dict[str, int] = field(default_factory=dict)
    entrypoints: List[str] = field(default_factory=list)
    file_count: int = 0


def scan_repo(path: str | Path, max_entries: int = 400) -> RepoScan:
    """Walk a repo (skipping vendored/VCS dirs); collect a tree summary, languages, entry points."""
    base = Path(path)
    scan = RepoScan(path=str(base))
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP and not d.startswith(".git"))
        rel = os.path.relpath(root, base)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth <= 2 and len(scan.tree) < max_entries:
            label = "." if rel == "." else rel
            scan.tree.append(f"{'  ' * depth}{label}/")
        for f in sorted(files):
            scan.file_count += 1
            ext = Path(f).suffix.lower()
            if ext in _LANG_BY_EXT:
                lang = _LANG_BY_EXT[ext]
                scan.languages[lang] = scan.languages.get(lang, 0) + 1
            if f in _ENTRY_HINTS:
                scan.entrypoints.append(os.path.join(rel, f) if rel != "." else f)
    return scan


def _langs_line(scan: RepoScan) -> str:
    if not scan.languages:
        return "(none detected)"
    return ", ".join(f"{k} ({v})" for k, v in sorted(scan.languages.items(), key=lambda x: -x[1]))


def write_structure_baseline(repo: str | Path, scan: RepoScan) -> List[str]:
    """Scaffold `docs/structure/{directory,logical,design,data}.md` from the scan. Returns paths."""
    out_dir = Path(repo) / "docs" / "structure"
    out_dir.mkdir(parents=True, exist_ok=True)
    tree = "\n".join(scan.tree[:200]) or "(empty)"
    entry = ", ".join(scan.entrypoints) or "(none detected)"
    written: List[str] = []

    directory = (
        f"# Directory Structure — {Path(scan.path).name}\n\n"
        f"> Auto-scanned baseline (structure_scan). Review and refine in the structure-design stage.\n\n"
        f"## Tree (depth ≤ 2)\n```\n{tree}\n```\n\n"
        f"## Facts\n- Files scanned: {scan.file_count}\n- Languages: {_langs_line(scan)}\n"
        f"- Entry points: {entry}\n"
    )
    seed = (
        f"> Seeded by structure_scan from the repo scan; **A1 (analysis) completes this** in the\n"
        f"> structure-design stage. Languages: {_langs_line(scan)}; entry points: {entry}.\n"
    )
    docs = {
        "directory.md": directory,
        "logical.md": f"# Logical Structure — {Path(scan.path).name}\n\n{seed}\n## Layers / modules\n| Layer/Module | Responsibility | Depends on |\n|---|---|---|\n| _TBD_ | _from analysis_ | |\n",
        "design.md": f"# Design Structure — {Path(scan.path).name}\n\n{seed}\n## Key components\n| Component | Responsibility | Interface/contract |\n|---|---|---|\n| _TBD_ | | |\n",
        "data.md": f"# Data Structure — {Path(scan.path).name}\n\n{seed}\n## Entities\n| Entity | Fields | Notes |\n|---|---|---|\n| _TBD_ | | |\n",
    }
    for name, content in docs.items():
        p = out_dir / name
        p.write_text(content, encoding="utf-8")
        written.append(str(p))
    return written


def setup_authority_contract(authority: str | Path, version: str) -> str:
    """Create `<authority>/docs/contracts/VERSION` (+ a surface note). Returns the VERSION path."""
    cdir = Path(authority) / "docs" / "contracts"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "VERSION").write_text(f"{_v(version)}\n", encoding="utf-8")
    (cdir / "README.md").write_text(
        f"# Cross-repo contract — {Path(authority).name} (authority)\n\n"
        f"- Contract version: {_v(version)}\n"
        f"- This authority repo is the single source of truth for the shared contract + Guideline.\n"
        f"- Consumers pin this version in their `docs/authority.md`; `cross_repo_check.py` verifies it.\n",
        encoding="utf-8",
    )
    return str(cdir / "VERSION")


def setup_pointer(consumer: str | Path, authority: str | Path, version: str) -> str:
    """Create `<consumer>/docs/authority.md` pointing at the authority + pinned version."""
    ddir = Path(consumer) / "docs"
    ddir.mkdir(parents=True, exist_ok=True)
    p = ddir / "authority.md"
    # NOTE: the "Pinned version: vX" line format is what the skill's cross_repo_check.py parses
    # (regex `(釘住版本|pinned version): <ver>`) — keep it exactly.
    p.write_text(
        f"# Authority pointer\n\n"
        f"- Authority: {Path(authority).name} ({authority})\n"
        f"- Pinned version: {_v(version)}\n\n"
        f"This repo consumes the shared contract from the authority above. Keep this version in sync\n"
        f"with the authority's `docs/contracts/VERSION` (checked by `cross_repo_check.py`).\n",
        encoding="utf-8",
    )
    return str(p)


def _v(version: str) -> str:
    """Normalize a version to the `vX` / `vX.Y.Z` form cross_repo_check expects (it compares strings)."""
    return version if version.startswith("v") else f"v{version}"


@dataclass
class AnalyzeResult:
    scanned: List[str] = field(default_factory=list)
    scaffolded: List[str] = field(default_factory=list)
    authority_version: str = ""
    pointers: List[str] = field(default_factory=list)


def analyze_workspace(ws: "ws_mod.Workspace", contract_version: str) -> AnalyzeResult:
    """Run the structure analysis across the workspace.

    Scans + scaffolds four structures for every project; for a multi-project workspace, sets up the
    authority contract and each consumer's pointer (the skill's cross-repo model).
    """
    ws.validate()
    result = AnalyzeResult(authority_version=_v(contract_version))
    for proj in ws.all_projects:
        scan = scan_repo(proj)
        result.scanned.append(proj)
        result.scaffolded += write_structure_baseline(proj, scan)
    if ws.is_multi:
        setup_authority_contract(ws.authority, contract_version)
        for consumer in ws.consumers:
            result.pointers.append(setup_pointer(consumer, ws.authority, contract_version))
    return result
