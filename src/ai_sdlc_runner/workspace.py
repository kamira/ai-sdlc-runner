"""workspace.py — multi-project workspace with a designated authority (main) project.

A workspace registers one or more project locations. When there are several, one is the **authority**
(the main / entry project) that holds the shared cross-repo contract + Guideline; the others are
consumers that keep a local view and an authority pointer (see the skill's `cross-repo.md`).

The manifest is persisted at the authority as ``.sdlc-workspace.json`` so it travels with the source of
truth and can be reused across runs. A single-project workspace is just an authority with no consumers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

WORKSPACE_FILENAME = ".sdlc-workspace.json"


class WorkspaceError(Exception):
    """Raised for invalid workspace configuration."""


@dataclass
class Workspace:
    """A set of project paths with one designated authority (main) project.

    ``authority`` and ``consumers`` are absolute path strings. ``all_projects`` lists the authority
    first, then the consumers.
    """

    authority: str
    consumers: List[str] = field(default_factory=list)
    name: str = "workspace"

    # ---- mutation --------------------------------------------------------------------
    def add_project(self, path: str | Path) -> None:
        p = str(Path(path).resolve())
        if p == self.authority or p in self.consumers:
            return
        self.consumers.append(p)

    def set_authority(self, path: str | Path) -> None:
        """Promote ``path`` to authority; the previous authority becomes a consumer."""
        p = str(Path(path).resolve())
        if self.authority and self.authority != p and self.authority not in self.consumers:
            self.consumers.append(self.authority)
        self.consumers = [c for c in self.consumers if c != p]
        self.authority = p

    # ---- views -----------------------------------------------------------------------
    @property
    def all_projects(self) -> List[str]:
        return [self.authority, *self.consumers]

    @property
    def is_multi(self) -> bool:
        return len(self.consumers) > 0

    def manifest(self) -> dict:
        """Manifest compatible with cross_repo_check.py: authority + repos (as basenames)."""
        return {"authority": Path(self.authority).name,
                "repos": [Path(c).name for c in self.consumers]}

    # ---- validation ------------------------------------------------------------------
    def validate(self) -> None:
        if not self.authority:
            raise WorkspaceError("workspace has no authority (main) project")
        if not Path(self.authority).is_dir():
            raise WorkspaceError(f"authority path does not exist: {self.authority}")
        for c in self.consumers:
            if not Path(c).is_dir():
                raise WorkspaceError(f"consumer path does not exist: {c}")
        if self.authority in self.consumers:
            raise WorkspaceError("authority must not also be listed as a consumer")

    # ---- persistence -----------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"name": self.name, "authority": self.authority, "consumers": self.consumers}

    def save(self) -> str:
        """Write the manifest to ``<authority>/.sdlc-workspace.json`` and return its path."""
        self.validate()
        path = Path(self.authority) / WORKSPACE_FILENAME
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return str(path)


def load(project_dir: str | Path) -> Optional[Workspace]:
    """Load a workspace from ``<project_dir>/.sdlc-workspace.json`` (the authority), or None."""
    p = Path(project_dir) / WORKSPACE_FILENAME
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return Workspace(authority=data["authority"],
                     consumers=list(data.get("consumers", [])),
                     name=data.get("name", "workspace"))


def build(authority: str | Path, consumers: Optional[List[str]] = None, name: str = "workspace") -> Workspace:
    """Construct and validate a workspace from an authority path + optional consumer paths."""
    ws = Workspace(authority=str(Path(authority).resolve()), name=name)
    for c in consumers or []:
        ws.add_project(c)
    ws.validate()
    return ws
