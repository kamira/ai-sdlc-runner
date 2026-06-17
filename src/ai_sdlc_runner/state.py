"""state.py — per-project checkpoint / resume (state.json).

One checkpoint is written at each stage boundary (build-guide §3, §4). ``--resume`` continues from
the last checkpoint without re-running completed stages. Each stage boundary is also a halt-point,
so "crash-resumable" and "human-gated at boundaries" fall out of the same structure.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATE_FILENAME = "state.json"

# Canonical stage order (mirrors the skill's four stages; build-guide §4).
STAGES = ("requirement_analysis", "structure_design", "implement", "acceptance")
DONE = "done"


@dataclass
class RunState:
    stage: str = STAGES[0]
    completed: "list[str]" = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)
    updated: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "completed": self.completed,
            "artifacts": self.artifacts,
            "updated": self.updated,
        }


def _state_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / STATE_FILENAME


def load(project_dir: str | Path) -> Optional[RunState]:
    """Return the saved RunState, or ``None`` if the project has none yet."""
    p = _state_path(project_dir)
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return RunState(
        stage=data.get("stage", STAGES[0]),
        completed=data.get("completed", []),
        artifacts=data.get("artifacts", {}),
        updated=data.get("updated", ""),
    )


def save(project_dir: str | Path, state: RunState) -> RunState:
    """Persist a checkpoint, stamping ``updated`` with the current UTC time."""
    state.updated = datetime.now(timezone.utc).isoformat()
    _state_path(project_dir).write_text(
        json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return state


def checkpoint(project_dir: str | Path, state: RunState, stage: str, artifacts: Optional[dict] = None) -> RunState:
    """Mark ``stage`` complete, advance to the next stage, and save.

    Appends ``stage`` to ``completed`` (idempotent) and sets ``stage`` to the next one in
    ``STAGES`` (or ``done`` after the last).
    """
    if stage not in state.completed:
        state.completed.append(stage)
    if artifacts:
        state.artifacts.update(artifacts)
    state.stage = _next_stage(stage)
    return save(project_dir, state)


def _next_stage(stage: str) -> str:
    if stage in STAGES:
        idx = STAGES.index(stage)
        return STAGES[idx + 1] if idx + 1 < len(STAGES) else DONE
    return DONE


def remaining_stages(state: Optional[RunState]) -> "list[str]":
    """Stages still to run, given a (possibly resumed) state. ``None`` → all stages."""
    if state is None:
        return list(STAGES)
    return [s for s in STAGES if s not in state.completed]
