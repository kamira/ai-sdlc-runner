"""dashboard.py — multi-panel execution view (stdlib curses + text snapshot).

Panels (per CHG-20260617-03):
  • 狀態 / Status        — git branch + dirty flag, stage progress N/4, current stage + contract lock
  • 執行日誌 / Exec log    — stage transitions and gate decisions (AUTO/HALT + reason)
  • 檢驗結果 / Verify      — acceptance reports found + latest V1 conclusion / halt
  • agent 行為日誌 / Agent — per-agent dispatch & results; merged (default) or tabbed per agent

This is a **presentation layer only**: it consumes events emitted by the orchestrator and reads saved
``state.json`` / ``.sdlc-lock.json`` / ``docs/acceptance/`` / git. It holds no governance logic and
cannot change the run — launching a run from the dashboard still passes through every halt gate.
Zero third-party dependencies; the curses viewer degrades to a printed snapshot off-TTY.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import contract, state

AGENT_VIEW_MERGED = "merged"
AGENT_VIEW_TABBED = "tabbed"


def _git(project_dir: str | Path, *args: str) -> Optional[str]:
    """Run a git command in the project; return stripped stdout or None if not a repo / git missing."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_dir), *args],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


@dataclass
class DashboardModel:
    """Accumulates run events and exposes panel content. Also buildable from saved state alone."""

    project_dir: str
    events: List[dict] = field(default_factory=list)

    # ---- ingestion -------------------------------------------------------------------
    def add(self, event: dict) -> None:
        self.events.append(dict(event))

    @classmethod
    def from_saved(cls, project_dir: str | Path) -> "DashboardModel":
        """Build a model for a post-hoc view (no live events) — `runner dashboard <project>`."""
        return cls(project_dir=str(project_dir))

    # ---- panels ----------------------------------------------------------------------
    def status_panel(self) -> List[str]:
        """狀態: git branch + dirty, stage progress, current stage + contract lock (merged)."""
        lines: List[str] = []
        if _git(self.project_dir, "rev-parse", "--is-inside-work-tree") != "true":
            lines.append("branch:   (not a git repo)")
        else:
            branch = _git(self.project_dir, "branch", "--show-current") or "(detached/unborn)"
            porcelain = _git(self.project_dir, "status", "--porcelain")
            dirty = "dirty" if porcelain else "clean"
            lines.append(f"branch:   {branch} ({dirty})")

        st = state.load(self.project_dir)
        done = len(st.completed) if st else 0
        total = len(state.STAGES)
        bar = "█" * done + "░" * (total - done)
        cur = st.stage if st else "(not started)"
        lines.append(f"progress: [{bar}] {done}/{total} stages")
        lines.append(f"stage:    {cur}")

        lock = contract.read_lock(self.project_dir)
        if lock:
            lines.append(f"contract: locked {lock['contract_major']}.{lock['contract_minor']}.x "
                         f"(rec {lock['contract_version']})")
        else:
            lines.append("contract: (no lock yet)")
        return lines

    def exec_log_panel(self) -> List[str]:
        """執行日誌: stage transitions + gate decisions from the event stream."""
        lines: List[str] = []
        for e in self.events:
            t = e.get("type")
            if t == "stage":
                lines.append(f"▶ stage: {e.get('stage')}")
            elif t == "gate":
                mark = "■ HALT" if e.get("result") == "HALT" else "· AUTO"
                lines.append(f"  {mark}  {e.get('gate')} [{e.get('risk')}]")
            elif t == "checkpoint":
                lines.append(f"  ✓ checkpoint: {e.get('stage')} done")
            elif t == "halt":
                lines.append(f"  ✋ HALTED at {e.get('gate')} — awaiting approval")
            elif t == "done":
                lines.append("  ✓ run completed")
        return lines or ["(no execution events yet)"]

    def verify_panel(self) -> List[str]:
        """檢驗結果: acceptance reports on disk + latest V1 event outcome."""
        lines: List[str] = []
        acc_dir = Path(self.project_dir) / "docs" / "acceptance"
        reports = sorted(acc_dir.glob("ACC-*.md")) if acc_dir.is_dir() else []
        for r in reports:
            concl = "?"
            for line in r.read_text(encoding="utf-8", errors="replace").splitlines():
                low = line.lower()
                if "conclusion" in low or "結論" in line:
                    concl = line.split(":", 1)[-1].strip() or concl
                    break
            lines.append(f"{r.name}: {concl}")
        # Latest V1 acceptance event, if any.
        for e in reversed(self.events):
            if e.get("type") == "agent" and e.get("role") == "V1" and "passed" in e:
                lines.append(f"V1 run: {'PASS' if e['passed'] else 'FAIL'}")
            break
        return lines or ["(no acceptance reports yet)"]

    def agent_panel(self, view: str = AGENT_VIEW_MERGED) -> List[str]:
        """agent 行為日誌: merged chronological (default) or tabbed per agent."""
        agent_events = [e for e in self.events if e.get("type") == "agent"]
        if not agent_events:
            return ["(no agent activity yet)"]
        if view == AGENT_VIEW_TABBED:
            lines: List[str] = []
            roles: List[str] = []
            for e in agent_events:
                if e.get("role") not in roles:
                    roles.append(e.get("role"))
            for role in roles:
                lines.append(f"┌─ [{role}] ─")
                for e in agent_events:
                    if e.get("role") == role:
                        lines.append(f"│  {self._agent_line(e)}")
            return lines
        # merged
        return [f"[{e.get('role')}] {self._agent_line(e)}" for e in agent_events]

    @staticmethod
    def _agent_line(e: dict) -> str:
        verb = e.get("phase", "dispatch")
        detail = e.get("task") or e.get("scope") or ""
        if "passed" in e:
            detail = f"{detail} -> {'PASS' if e['passed'] else 'FAIL'}"
        return f"{verb}: {detail}".strip()


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------

def _dw(s: str) -> int:
    """Display width of a string, counting East-Asian wide/full chars as 2 columns."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _fit(s: str, n: int, fill: str = " ") -> str:
    """Truncate ``s`` to display width ``n`` (never splitting a wide char), then pad with ``fill``."""
    out, w = "", 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if w + cw > n:
            break
        out += c
        w += cw
    return out + fill * (n - w)


def _panel(title: str, body: List[str], width: int = 78) -> List[str]:
    """Box-draw one panel with a title and body lines (CJK display-width aware)."""
    inner = width - 2  # display columns between the corners
    out = ["┌" + _fit(f"─ {title} ", inner, "─") + "┐"]
    for line in body:
        out.append("│ " + _fit(line, inner - 2) + " │")
    out.append("└" + "─" * inner + "┘")
    return out


def render_snapshot(model: DashboardModel, agent_view: str = AGENT_VIEW_MERGED, width: int = 78) -> str:
    """Render all panels to a plain-text snapshot (used off-TTY, by tests, and by `dashboard`)."""
    blocks: List[str] = []
    blocks += _panel("狀態 / Status", model.status_panel(), width)
    blocks += _panel("執行日誌 / Execution log", model.exec_log_panel(), width)
    blocks += _panel("檢驗結果 / Verification", model.verify_panel(), width)
    label = "agent 行為日誌 / Agent log" + (f"  [{agent_view}]" if agent_view else "")
    blocks += _panel(label, model.agent_panel(agent_view), width)
    return "\n".join(blocks)


def _want_curses() -> bool:
    if os.environ.get("AI_SDLC_NO_CURSES"):
        return False
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        import curses  # noqa: F401
    except Exception:
        return False
    return True


def view(model: DashboardModel, agent_view: str = AGENT_VIEW_MERGED) -> None:
    """Show the dashboard. Interactive curses viewer on a TTY (t = toggle agent view, q = quit),
    otherwise print the text snapshot once."""
    if not _want_curses():
        print(render_snapshot(model, agent_view))
        return
    try:
        _curses_view(model, agent_view)
    except Exception:
        print(render_snapshot(model, agent_view))


def _curses_view(model: DashboardModel, agent_view: str) -> None:
    import curses

    def _run(stdscr):
        curses.curs_set(0)
        view_mode = agent_view
        while True:
            stdscr.erase()
            snap = render_snapshot(model, view_mode, width=min(100, curses.COLS - 1))
            for i, line in enumerate(snap.splitlines()):
                if i >= curses.LINES - 2:
                    break
                try:
                    stdscr.addstr(i, 0, line[: curses.COLS - 1])
                except curses.error:
                    pass
            try:
                stdscr.addstr(curses.LINES - 1, 0, "t = toggle agent view · q = quit", curses.A_DIM)
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), 27):
                return
            if key == ord("t"):
                view_mode = AGENT_VIEW_TABBED if view_mode == AGENT_VIEW_MERGED else AGENT_VIEW_MERGED

    curses.wrapper(_run)
