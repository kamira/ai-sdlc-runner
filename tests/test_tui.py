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


def test_prompt_default_and_value():
    assert tui.prompt("Project", "x", input_fn=lambda _p: "") == "x"
    assert tui.prompt("Project", "x", input_fn=lambda _p: "abc") == "abc"
