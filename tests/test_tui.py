"""Tests for the interactive menu helper (CHG-20260617-02).

Covers the pure choice parser and the numbered-fallback selection with an injected input function,
so no real TTY is needed. The curses path is not unit-tested (it requires a terminal); the fallback
is what runs in pipes/CI.
"""
from __future__ import annotations

import io

import pytest

from ai_sdlc_runner import tui

OPTIONS = [("Run", "drive the loop"), ("Status", "show state"), ("Exit", "quit")]


@pytest.mark.parametrize("raw,expected", [
    ("1", 0),
    ("3", 2),
    ("  2 ", 1),
    ("", None),
    ("q", None),
    ("quit", None),
    ("EXIT", None),
    ("0", None),     # out of range (1-based)
    ("4", None),     # out of range
    ("abc", None),   # non-numeric
])
def test_parse_choice(raw, expected):
    assert tui._parse_choice(raw, n=3) == expected


def test_numbered_select_picks_index():
    out = io.StringIO()
    idx = tui._numbered_select("pick:", OPTIONS, input_fn=lambda _p: "2", out=out)
    assert idx == 1
    # The list was rendered with 1-based numbering.
    assert "1. Run" in out.getvalue()
    assert "3. Exit" in out.getvalue()


def test_numbered_select_cancel():
    out = io.StringIO()
    assert tui._numbered_select("pick:", OPTIONS, input_fn=lambda _p: "q", out=out) is None


def test_numbered_select_eof_cancels():
    def _raise(_p):
        raise EOFError

    out = io.StringIO()
    assert tui._numbered_select("pick:", OPTIONS, input_fn=_raise, out=out) is None


def test_select_empty_options_returns_none():
    assert tui.select("nothing", [], input_fn=lambda _p: "1") is None


def test_select_uses_fallback_when_forced(monkeypatch):
    monkeypatch.setenv(tui._FORCE_FALLBACK_ENV, "1")
    out = io.StringIO()
    idx = tui.select("pick:", OPTIONS, input_fn=lambda _p: "1", stream_out=out)
    assert idx == 0


# --------------------------------------------------------------------------------------
# Pure option-cycle core (CHG-20260703-03 step 1) — no curses import needed to test it.
# --------------------------------------------------------------------------------------

KEY_UP, KEY_K = 259, ord("k")     # stand-ins for curses.KEY_UP / ord("k")
KEY_DOWN, KEY_J = 258, ord("j")   # stand-ins for curses.KEY_DOWN / ord("j")


def test_cycle_index_down_wraps():
    assert tui.cycle_index(0, 3, KEY_DOWN, key_down=(KEY_DOWN, KEY_J)) == 1
    assert tui.cycle_index(2, 3, KEY_DOWN, key_down=(KEY_DOWN, KEY_J)) == 0  # wraps past the end


def test_cycle_index_up_wraps():
    assert tui.cycle_index(1, 3, KEY_UP, key_up=(KEY_UP, KEY_K)) == 0
    assert tui.cycle_index(0, 3, KEY_UP, key_up=(KEY_UP, KEY_K)) == 2  # wraps before the start


def test_cycle_index_vim_keys():
    assert tui.cycle_index(0, 3, KEY_J, key_down=(KEY_DOWN, KEY_J)) == 1
    assert tui.cycle_index(1, 3, KEY_K, key_up=(KEY_UP, KEY_K)) == 0


def test_cycle_index_unrecognized_key_is_noop():
    assert tui.cycle_index(1, 3, ord("z"), key_up=(KEY_UP,), key_down=(KEY_DOWN,)) == 1


def test_cycle_index_zero_options_is_noop():
    assert tui.cycle_index(0, 0, KEY_DOWN, key_down=(KEY_DOWN,)) == 0


class _FakeScreen:
    """A minimal stand-in for a curses `stdscr`, driven by a scripted key sequence."""

    def __init__(self, keys):
        self._keys = list(keys)

    def erase(self):
        pass

    def addstr(self, *a, **k):
        pass

    def refresh(self):
        pass

    def getch(self):
        return self._keys.pop(0)


def test_curses_select_on_uses_embeddable_core(monkeypatch):
    """`_curses_select_on` draws on a passed-in stdscr (no nested `curses.wrapper`) and drives
    selection via the same `cycle_index` core — simulated here with a fake stdscr. `curses.COLS` is
    normally set by `initscr()`/`wrapper()`; stub it since this test never starts a real session."""
    curses = pytest.importorskip("curses")
    monkeypatch.setattr(curses, "COLS", 80, raising=False)
    # down, down, enter -> index 2 (wraps within 3 options: 0 -> 1 -> 2)
    screen = _FakeScreen([curses.KEY_DOWN, curses.KEY_DOWN, 10])
    idx = tui._curses_select_on(screen, "pick:", OPTIONS)
    assert idx == 2


def test_curses_select_on_cancel_returns_none(monkeypatch):
    curses = pytest.importorskip("curses")
    monkeypatch.setattr(curses, "COLS", 80, raising=False)
    screen = _FakeScreen([ord("q")])
    assert tui._curses_select_on(screen, "pick:", OPTIONS) is None
