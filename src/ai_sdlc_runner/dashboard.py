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

**Resident interactive console (CHG-20260703-03).** Alongside the read-only snapshot path above,
``ResidentApp`` is a persistent, always-on curses control console: bare ``runner`` (on a TTY) opens
it with no project loaded; ``/open <path>`` sets the *current project*; a plain-text line starts a run
on it (stub backend, offline); ``/quit`` is the only way out. At a HALT gate the app presents an
``[Approve / Reject]`` choice via the embeddable ``tui`` selector and blocks for a human decision —
red-line gates are never auto-approved. All of this is glue around the existing, unchanged
``orchestrator.run(approver=..., on_event=...)`` hooks; no governance logic lives here or is
duplicated. The curses loop itself is a thin shell around pure, headless-testable functions
(``parse_command``, ``render_layout``, ``approve_decision``) so the interactive behavior can be unit
tested without a real TTY.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import contract, orchestrator, state, tui

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
    skill_line: Optional[str] = None   # precomputed skill-update line (store-aware), set by the CLI

    # ---- caches (CHG-20260703-05) ------------------------------------------------------
    # `status_panel`/`verify_panel` are I/O-bound (git subprocesses, state/lock files, ACC-dir globs +
    # reads). The resident dashboard redraws on every keystroke, so these are memoized here and only
    # recomputed on real events (`refresh()`), not on every render. `exec_log_panel`/`agent_panel` stay
    # uncached — they just read `self.events` in memory, which is cheap and must stay live mid-run.
    _status_cache: Optional[List[str]] = field(default=None, repr=False, compare=False)
    _verify_cache: Optional[List[str]] = field(default=None, repr=False, compare=False)

    # ---- ingestion -------------------------------------------------------------------
    def add(self, event: dict) -> None:
        self.events.append(dict(event))

    @classmethod
    def from_saved(cls, project_dir: str | Path, skill_line: Optional[str] = None) -> "DashboardModel":
        """Build a model for a post-hoc view (no live events) — `runner dashboard <project>`."""
        return cls(project_dir=str(project_dir), skill_line=skill_line)

    # ---- cache control -----------------------------------------------------------------
    def refresh(self) -> None:
        """Invalidate the I/O-bound panel caches so the next `status_panel()`/`verify_panel()` call
        recomputes from git/disk. Call this on real events (app start, `/open`, after a run) — never
        per keystroke."""
        self._status_cache = None
        self._verify_cache = None

    # ---- panels ----------------------------------------------------------------------
    def status_panel(self) -> List[str]:
        """狀態: git branch + dirty, stage progress, current stage + contract lock (merged).
        Memoized (CHG-20260703-05): computed once per `refresh()`, not once per render."""
        if self._status_cache is None:
            self._status_cache = self._compute_status()
        return self._status_cache

    def _compute_status(self) -> List[str]:
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

        # Skill-update line, precomputed by the CLI (store-aware); shown when provided.
        if self.skill_line:
            lines.append(self.skill_line)
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
        """檢驗結果: acceptance reports on disk + latest V1 event outcome.
        Memoized (CHG-20260703-05): computed once per `refresh()`, not once per render."""
        if self._verify_cache is None:
            self._verify_cache = self._compute_verify()
        return self._verify_cache

    def _compute_verify(self) -> List[str]:
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


# --------------------------------------------------------------------------------------
# Resident interactive console (CHG-20260703-03)
# --------------------------------------------------------------------------------------
# Everything below is pure/headless-testable except `ResidentApp.run_curses`, which is a thin glue
# loop around it. No governance logic lives here: runs go through the unchanged `orchestrator.run`,
# gated by the unchanged `gates`/`halt_gate.py`; this module only supplies a human `approver` and an
# `on_event` sink.

COMMANDS = ("/open", "/run", "/status", "/check", "/menu", "/help", "/quit")


@dataclass
class Command:
    """A parsed input-box line. ``kind`` is one of:
    ``open`` | ``run`` | ``status`` | ``check`` | ``menu`` | ``help`` | ``quit`` | ``task`` | ``unknown``.
    ``arg`` carries the path (for ``open``) or the raw task/requirement text (for ``task``); ``error``
    carries a helpful message for ``unknown``.
    """

    kind: str
    arg: str = ""
    error: str = ""


def parse_command(raw: str) -> Command:
    """Parse one input-box line. Pure function — no I/O, no side effects.

    ``/open <path>``, ``/run``, ``/status``, ``/check``, ``/menu``, ``/help``, ``/quit`` are the
    recognized slash-commands (case-insensitive, extra whitespace tolerated). Any other ``/x`` is
    ``unknown`` with a helpful error line. Non-slash, non-empty text is a ``task`` (a requirement to
    run on the current project). An empty/whitespace-only line is a no-op.
    """
    text = raw.strip()
    if not text:
        return Command(kind="noop")
    if not text.startswith("/"):
        return Command(kind="task", arg=text)

    parts = text.split(None, 1)
    word = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if word == "/open":
        if not rest:
            return Command(kind="unknown", arg=text,
                            error="usage: /open <path>")
        return Command(kind="open", arg=rest)
    if word == "/run":
        return Command(kind="run", arg=rest)
    if word == "/status":
        return Command(kind="status")
    if word == "/check":
        return Command(kind="check")
    if word == "/menu":
        return Command(kind="menu")
    if word == "/help":
        return Command(kind="help")
    if word == "/quit":
        return Command(kind="quit")
    return Command(kind="unknown", arg=text,
                    error=f"unknown command: {word} (try /help)")


HELP_TEXT = [
    "Commands:",
    "  /open <path>   set the current project",
    "  /run [text]    start a run on the current project (optional inline requirement)",
    "  /status        show the current project's lock + run state",
    "  /check         check for a skill update against the current project",
    "  /menu          open the classic numbered/arrow menu",
    "  /help          show this help",
    "  /quit          leave the dashboard",
    "  <text>         (no leading /) — start a run, recording <text> as the requirement",
    "  F2             open the menu (same as /menu)  ·  ↑/↓ + Enter — select an offered answer",
]


# ---- 2-col bounded-height layout -------------------------------------------------------

def render_layout(
    model: DashboardModel,
    *,
    width: int,
    height: int,
    agent_view: str = AGENT_VIEW_MERGED,
    input_line: str = "",
    current_project: Optional[str] = None,
) -> List[str]:
    """Render the resident app's frame: Status | Verification (top row, full panels, never
    truncated), Execution log | Agent log (bottom row, 2 columns, each bounded to the last N lines
    where N derives from ``height`` so the top row always stays visible), and a bottom input line.

    Pure function of its inputs (no curses, no I/O) — this is what the curses loop calls every redraw,
    and what tests exercise directly with arbitrary small/large ``height``/``width`` to prove the top
    panels never get pushed off.
    """
    width = max(width, 20)
    col_w = max((width - 1) // 2, 10)

    status_body = model.status_panel()
    if current_project:
        status_body = [f"project:  {current_project}"] + status_body
    else:
        status_body = ["project:  (none — use /open <path>)"] + status_body
    verify_body = model.verify_panel()

    top_left = _panel("狀態 / Status", status_body, col_w)
    top_right = _panel("檢驗結果 / Verification", verify_body, col_w)
    top_rows = _side_by_side(top_left, top_right, col_w)

    # Header chrome (top row) + input line (1) + its help hint (1) are fixed; whatever remains goes
    # to the two bottom-row log panels (each panel adds 2 border lines to its body budget).
    reserved = len(top_rows) + 3
    avail = max(height - reserved, 5)
    log_body_budget = max((avail - 2) // 1, 1)  # body lines available inside each bottom panel

    exec_lines = model.exec_log_panel()
    agent_lines = model.agent_panel(agent_view)
    exec_tail = exec_lines[-log_body_budget:] if len(exec_lines) > log_body_budget else exec_lines
    agent_tail = agent_lines[-log_body_budget:] if len(agent_lines) > log_body_budget else agent_lines

    bottom_left = _panel("執行日誌 / Execution log", exec_tail, col_w)
    bottom_right = _panel(f"agent 行為日誌 / Agent log [{agent_view}]", agent_tail, col_w)
    bottom_rows = _side_by_side(bottom_left, bottom_right, col_w)

    lines: List[str] = []
    lines += top_rows
    lines += bottom_rows
    lines.append(_fit("", width, "─"))
    lines.append(("> " + input_line))
    return lines


def _side_by_side(left: List[str], right: List[str], col_w: int) -> List[str]:
    """Zip two equal-purpose panel blocks into side-by-side rows, padding the shorter block."""
    n = max(len(left), len(right))
    blank = _fit("", col_w)
    out = []
    for i in range(n):
        lft = left[i] if i < len(left) else blank
        rgt = right[i] if i < len(right) else blank
        out.append(f"{lft} {rgt}")
    return out


# ---- option-cycle / approver mapping ---------------------------------------------------

APPROVE_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("Approve", "continue past this halt gate"),
    ("Reject", "stop the run here (red lines are never auto-approved)"),
)


def approve_decision(selection) -> Optional[bool]:
    """Map a halt-gate answer to a boolean approval, or ``None`` if unresolved/cancelled.

    Accepts either an index into ``APPROVE_OPTIONS`` (0 = Approve, 1 = Reject — as returned by the
    arrow-key selector) or a raw y/n-style string (from a typed fallback answer). Anything else
    (``None``, empty, unrecognized text) returns ``None`` — callers should treat that as "no decision
    yet" and re-prompt, never as an implicit approval.
    """
    if selection is None:
        return None
    if isinstance(selection, bool):
        return selection
    if isinstance(selection, int):
        if selection == 0:
            return True
        if selection == 1:
            return False
        return None
    s = str(selection).strip().lower()
    if s in ("y", "yes", "approve", "a"):
        return True
    if s in ("n", "no", "reject", "r"):
        return False
    return None


# ---- key handling (CHG-20260703-04: any-language input) --------------------------------

def apply_key(buf: str, ch: str) -> Tuple[str, str]:
    """Classify one character from ``stdscr.get_wch()`` and apply it to the input buffer ``buf``.

    Pure function — no curses, no I/O — so it is unit-testable headlessly, including with
    multi-byte/CJK input (``get_wch`` hands back a full decoded ``str`` per keystroke, unlike
    ``getch``'s one-byte-at-a-time ``int``, which mangles anything outside Latin-1).

    Returns ``(new_buf, action)`` where ``action`` is one of:
      - ``"submit"``  — Enter (``"\\n"`` or ``"\\r"``); ``buf`` is returned unchanged, the caller
        dispatches it and resets the buffer.
      - ``"edit"``    — Backspace (``"\\x7f"``/``"\\b"``/``"\\x08"``, buffer shortened by one char,
        a no-op on an already-empty buffer) or a printable character, including any Unicode/CJK
        char, appended to ``buf``.
      - ``"noop"``    — any other non-printable control character; ``buf`` is returned unchanged.
    """
    if ch in ("\n", "\r"):
        return buf, "submit"
    if ch in ("\x7f", "\b", "\x08"):
        return buf[:-1], "edit"
    if ord(ch) < 32:
        return buf, "noop"
    return buf + ch, "edit"


# ---- resident app state + curses glue ---------------------------------------------------

@dataclass
class ResidentState:
    """Mutable state the resident app threads through: current project, input history, and the
    live ``DashboardModel`` for whichever project is currently open (rebuilt on ``/open``)."""

    current_project: Optional[str] = None
    model: Optional[DashboardModel] = None
    agent_view: str = AGENT_VIEW_MERGED
    history: List[str] = field(default_factory=list)
    status_line: str = "empty start — /open <path> or /help"

    def open_project(self, path: str) -> None:
        self.current_project = path
        self.model = DashboardModel.from_saved(path)
        # Fresh project: caches are already cold on a new model, but call `refresh()` explicitly so
        # the invalidation point is documented and holds even if construction ever changes (CHG-20260703-05).
        self.model.refresh()
        self.status_line = f"opened {path}"

    def ensure_model(self) -> DashboardModel:
        if self.model is None:
            self.model = DashboardModel(project_dir=self.current_project or ".")
        return self.model


# An "asker" answers one halt-gate decision: given the `gates.Decision`, return an answer understood
# by `approve_decision` (an index into APPROVE_OPTIONS, a bool, or a y/n-ish string). The default is a
# blocking `input()`-based y/n prompt (used headlessly by tests and as the non-curses fallback); the
# curses loop supplies one backed by `tui._curses_select_on` for real arrow-key selection.
Asker = Callable[[object], object]


def _input_asker(input_fn: Callable[[str], str] = input) -> Asker:
    """Build a plain-input asker: types y/n, blocking. Used by tests and as a non-curses fallback."""

    def _ask(decision) -> object:
        try:
            raw = input_fn(f"HALT at {getattr(decision, 'gate', '?')} — approve? [y/N]: ")
        except EOFError:
            raw = "n"
        return raw

    return _ask


def _curses_asker(stdscr) -> Asker:
    """Build an asker that presents [Approve / Reject] via the embeddable arrow-key selector, drawn
    on the resident app's own ``stdscr`` (never a nested ``curses.wrapper`` — that would be
    ``tui.select()``, which the resident loop must not call)."""

    def _ask(decision) -> object:
        gate = getattr(decision, "gate", "?")
        reason = getattr(decision, "reason", "") or ""
        title = f"HALT at '{gate}' — {reason}".strip()
        idx = tui._curses_select_on(stdscr, title, list(APPROVE_OPTIONS))
        return idx  # None (cancelled) safely maps to "no decision" via approve_decision

    return _ask


class ResidentApp:
    """The resident, interactive control console (curses). Only runs on a real TTY; construction and
    all state transitions are exercised headlessly via ``ResidentState``/``parse_command``/
    ``render_layout``/``approve_decision`` — this class is the thin glue loop that wires them to a
    real ``stdscr`` and to ``orchestrator.run``.
    """

    def __init__(self, project: Optional[str] = None, config: Optional[dict] = None):
        self.state = ResidentState()
        self.config = config or {}
        if project:
            self.state.open_project(project)

    # ---- command dispatch (no curses; used by both the loop and tests) ---------------
    def dispatch(self, raw: str, *, asker: Optional[Asker] = None) -> bool:
        """Handle one input-box line. Returns False to request quitting, True to keep looping.

        ``asker`` answers halt-gate approvals if a run reaches one; defaults to a blocking y/n
        ``input()`` prompt so this method — and thus the whole command layer — is testable without
        curses. The curses loop passes an arrow-key asker built with ``_curses_asker(stdscr)``.
        """
        cmd = parse_command(raw)
        st = self.state
        if cmd.kind == "noop":
            return True
        if cmd.kind == "quit":
            return False
        if cmd.kind == "open":
            st.open_project(cmd.arg)
            return True
        if cmd.kind == "help":
            st.status_line = " | ".join(HELP_TEXT[:3]) + " ..."
            return True
        if cmd.kind == "status":
            if not st.current_project:
                st.status_line = "no project; use /open <path>"
                return True
            lock = contract.read_lock(st.current_project)
            st.status_line = ("no contract lock (never run)" if lock is None else
                               f"locked {lock['contract_major']}.{lock['contract_minor']}.x")
            return True
        if cmd.kind == "check":
            st.status_line = "check: (use `runner check` from a shell for full output)"
            return True
        if cmd.kind == "menu":
            st.status_line = "(menu requested)"
            return True
        if cmd.kind == "unknown":
            st.status_line = cmd.error
            return True
        if cmd.kind in ("run", "task"):
            if not st.current_project:
                st.status_line = "no project; use /open <path>"
                return True
            self._start_run(cmd.arg, asker=asker or _input_asker())
            return True
        return True

    def _resolve_skill_path(self) -> str:
        """Resolve the concrete skill path for the current project the same way every other entry
        point does (CHG-20260617-05): explicit `skill_path` override in config → local offline store
        version matching the project's lock/config-expected → the fallback `skill_path`. Reuses
        `cli._resolve_skill_path` (lazy import — `cli` imports this module at load time, so importing
        it back at module scope would be circular) rather than re-implementing the precedence rules.
        """
        from . import cli as _cli  # local import: avoids a module-load cycle with cli -> dashboard

        return _cli._resolve_skill_path(self.config, None, self.state.current_project)

    def _start_run(self, requirement: str, *, asker: Asker) -> None:
        """Run the four-stage loop on the current project with the stub backend (offline, v1
        default), streaming events into the model and blocking for human approval at HALT gates.

        Single-thread by design (CHG-20260703-03): `on_event` updates the model in place and the
        caller redraws after this returns; `asker`/`approver` blocks synchronously. Fine for the stub
        backend; a slow real backend would block the UI too — a documented v1 limitation.
        """
        st = self.state
        model = st.ensure_model()
        if requirement:
            model.add({"type": "stage", "stage": f"(task) {requirement}"})

        def approver(decision) -> bool:
            # Red-line/HALT gates always require an explicit human Approve; an unresolved or
            # cancelled answer must map to reject (False), never to an implicit continue.
            return bool(approve_decision(asker(decision)))

        skill_path = self._resolve_skill_path()
        report = orchestrator.run(
            st.current_project,
            skill_path=skill_path,
            config=self.config or {"concurrency_max": 4, "nesting_depth_max": 3},
            requested_version=self.config.get("contract_version"),
            risk="medium",
            approver=approver,
            on_event=model.add,
        )
        # The run may have advanced state.json/.sdlc-lock.json and written new ACC-*.md reports;
        # invalidate the cached status/verify panels so the next redraw reflects them (CHG-20260703-05).
        model.refresh()
        st.status_line = f"run: {report.status}"


def _want_resident_curses() -> bool:
    """Resident app only ever runs on a real TTY (never off-TTY/CI/pipes)."""
    if os.environ.get("AI_SDLC_NO_CURSES"):
        return False
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        import curses  # noqa: F401
    except Exception:
        return False
    return True


def run_resident(project: Optional[str] = None, config: Optional[dict] = None) -> int:
    """Entry point for the resident dashboard. Off-TTY, this is a no-op the caller should not invoke
    (see `cli.main`, which only calls this when `_want_resident_curses()`); on a TTY it drives the
    curses loop until `/quit`, streaming run events live and asking [Approve/Reject] via the
    embeddable arrow-key selector at every HALT gate."""
    app = ResidentApp(project=project, config=config)
    if not _want_resident_curses():
        return 0
    import curses
    import locale

    # Make ncurses decode input as the user's locale encoding (typically UTF-8) so `get_wch()`
    # below returns whole characters — incl. multi-byte CJK — instead of raw bytes.
    locale.setlocale(locale.LC_ALL, "")

    def _run(stdscr) -> int:
        curses.curs_set(1)
        stdscr.keypad(True)
        buf = ""
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            model = app.state.ensure_model()
            frame = render_layout(
                model, width=min(w - 1, 120), height=max(h - 1, 8),
                agent_view=app.state.agent_view, input_line=buf,
                current_project=app.state.current_project,
            )
            for i, line in enumerate(frame):
                if i >= h - 1:
                    break
                try:
                    stdscr.addstr(i, 0, line[: w - 1])
                except curses.error:
                    pass
            try:
                stdscr.addstr(h - 1, 0, app.state.status_line[: w - 1], curses.A_DIM)
            except curses.error:
                pass
            stdscr.refresh()
            try:
                ch = stdscr.get_wch()
            except curses.error:
                continue
            if isinstance(ch, int):
                # Special keys (function/arrow/etc.) still arrive as ints even via get_wch().
                if ch == curses.KEY_F2:
                    cont = app.dispatch("/menu", asker=_curses_asker(stdscr))
                    buf = ""
                    if not cont:
                        return 0
                    continue
                if ch in (curses.KEY_ENTER, 10, 13):
                    cont = app.dispatch(buf, asker=_curses_asker(stdscr))
                    buf = ""
                    if not cont:
                        return 0
                    continue
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    buf = buf[:-1]
                    continue
                continue
            # str result: a decoded character (any language, incl. CJK) or Enter/Backspace as str.
            buf, action = apply_key(buf, ch)
            if action == "submit":
                cont = app.dispatch(buf, asker=_curses_asker(stdscr))
                buf = ""
                if not cont:
                    return 0

    return curses.wrapper(_run)
