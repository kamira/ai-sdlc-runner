"""tui.py — a tiny, zero-dependency interactive menu for the runner CLI.

Provides an arrow-key selectable list using the Python standard library's ``curses`` module. When
the session is not a TTY or ``curses`` is unavailable (pipes, CI, some Windows shells), it falls back
to a numbered text prompt. No third-party dependency — consistent with the runner's stdlib-only stance.

This is purely a UI helper: it only *collects a choice*. It contains no governance logic; the menu's
actions are dispatched by ``cli`` to the existing commands, so every halt gate and red-line stop still
applies.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, List, Optional, Sequence, Tuple

# An option is (label, description).
Option = Tuple[str, str]

# Set AI_SDLC_NO_CURSES=1 to force the numbered fallback (used by tests / non-interactive runs).
_FORCE_FALLBACK_ENV = "AI_SDLC_NO_CURSES"


def _parse_choice(raw: str, n: int) -> Optional[int]:
    """Parse a numbered-menu answer into a 0-based index, or ``None`` to cancel.

    Accepts ``1..n`` (1-based). ``q``/``quit``/``exit``/empty cancels. Anything else → ``None``.
    Pure function — unit-tested directly.
    """
    s = raw.strip().lower()
    if s in ("", "q", "quit", "exit"):
        return None
    if s.isdigit():
        i = int(s)
        if 1 <= i <= n:
            return i - 1
    return None


def _want_curses(stream_in, stream_out) -> bool:
    """True only if we should attempt the curses UI (interactive TTY, curses importable, not forced off)."""
    if os.environ.get(_FORCE_FALLBACK_ENV):
        return False
    try:
        if not (stream_in.isatty() and stream_out.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    try:
        import curses  # noqa: F401
    except Exception:
        return False
    return True


def _numbered_select(
    title: str,
    options: Sequence[Option],
    *,
    input_fn: Callable[[str], str] = input,
    out=None,
) -> Optional[int]:
    """Numbered-list fallback. Returns the chosen 0-based index, or ``None`` to cancel."""
    out = out or sys.stdout
    print(title, file=out)
    for i, (label, desc) in enumerate(options, 1):
        suffix = f"  — {desc}" if desc else ""
        print(f"  {i}. {label}{suffix}", file=out)
    try:
        raw = input_fn("Select [number, q to cancel]: ")
    except EOFError:
        return None
    return _parse_choice(raw, len(options))


def cycle_index(idx: int, n: int, key: int, *, key_up: Sequence[int] = (), key_down: Sequence[int] = ()) -> int:
    """Pure option-cycle core: given the current index, option count, and a curses key code, return
    the next index (wrapping). ``key_up``/``key_down`` are the extra key codes (e.g. ``curses.KEY_UP``,
    ``ord("k")``) recognized as "move up"/"move down" — kept out of this function so it needs no
    curses import and is directly unit-testable. Unrecognized keys leave ``idx`` unchanged."""
    if n <= 0:
        return idx
    if key in key_up:
        return (idx - 1) % n
    if key in key_down:
        return (idx + 1) % n
    return idx


def _curses_select_on(stdscr, title: str, options: Sequence[Option]) -> Optional[int]:
    """Arrow-key menu drawn on an **already-initialized** ``stdscr`` (no nested ``curses.wrapper``).

    ↑/↓ (or k/j) to move, Enter to choose, q/Esc to cancel.

    **One caller today**: ``_curses_select``, immediately below, which opens its own
    ``curses.wrapper``. This said it was *"the embeddable core reused by callers — such as the
    resident dashboard — that already own the curses screen"*, and `dashboard.py` no longer
    exists: `test_ledger_check.py` records it as part of an architecture that was removed. A
    split justified by a caller nobody can find is a split with no reason on the record
    (CHG-20260903-32, found by the defect seat).

    Kept rather than inlined, because the shape is still right — a menu that does not open a
    nested session is the reusable one, and merging it back would have to be undone by whoever
    next embeds a menu. What is removed is the claim that someone already did.
    """
    import curses

    idx = 0
    n = len(options)
    key_up = (curses.KEY_UP, ord("k"))
    key_down = (curses.KEY_DOWN, ord("j"))
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0, title)
        stdscr.addstr(1, 0, "↑/↓ move · Enter select · q cancel")
        for i, (label, desc) in enumerate(options):
            marker = "›" if i == idx else " "
            line = f"{marker} {label}"
            attr = curses.A_REVERSE if i == idx else curses.A_NORMAL
            try:
                stdscr.addstr(3 + i, 0, line, attr)
                if desc and i == idx:
                    stdscr.addstr(3 + n + 1, 0, desc[: max(0, curses.COLS - 1)], curses.A_DIM)
            except curses.error:
                pass
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13):
            return idx
        elif key in (27, ord("q")):  # Esc / q
            return None
        else:
            idx = cycle_index(idx, n, key, key_up=key_up, key_down=key_down)


def _curses_select(title: str, options: Sequence[Option]) -> Optional[int]:
    """Arrow-key menu via stdlib curses, in its own ``curses.wrapper`` session.

    ↑/↓ (or k/j) to move, Enter to choose, q/Esc to cancel.
    """
    import curses

    def _run(stdscr) -> Optional[int]:
        curses.curs_set(0)
        try:
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
        except Exception:
            pass
        return _curses_select_on(stdscr, title, options)

    return curses.wrapper(_run)


def select(
    title: str,
    options: Sequence[Option],
    *,
    input_fn: Callable[[str], str] = input,
    stream_in=None,
    stream_out=None,
) -> Optional[int]:
    """Show ``title`` and a list of ``options``; return the chosen 0-based index, or ``None`` to cancel.

    Uses the curses arrow-key menu when interactive; otherwise a numbered prompt. ``input_fn`` is
    injectable so the fallback can be tested without a real TTY.
    """
    if not options:
        return None
    si = stream_in or sys.stdin
    so = stream_out or sys.stdout
    if _want_curses(si, so):
        try:
            return _curses_select(title, options)
        except Exception:
            # Any curses failure (e.g. unusual terminal) degrades gracefully.
            return _numbered_select(title, options, input_fn=input_fn, out=so)
    return _numbered_select(title, options, input_fn=input_fn, out=so)


def confirm_high_risk(requested: int, floor: int, *, input_fn=input, stream_out=None) -> bool:
    """Ask the operator to turn on high-risk mode, which is the only way below the seat floor.

    Deliberately a question with the consequence written into the options rather than a silent
    config field: relaxing a gate is the user's call to make, and a call they cannot see themselves
    making is not one they made. Cancelling means no.
    """
    choice = select(
        f"Review is set to {requested} seat(s); the shipped floor is {floor}.",
        [
            ("Keep the floor", f"open {floor} seat(s) — the shipped default"),
            ("Enable high-risk mode",
             f"open {requested} seat(s), below the floor; the run records that it did"),
        ],
        input_fn=input_fn,
        stream_out=stream_out,
    )
    return choice == 1
