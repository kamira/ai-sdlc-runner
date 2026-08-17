"""Shared pytest fixtures."""
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def py_stub(tmp_path):
    """Write a throwaway stand-in for a local CLI agent and return the argv that runs it.

    The stub is Python invoked through ``sys.executable``, not a ``#!/bin/sh`` script: Windows has
    no shebang concept, so handing a bare ``.sh`` path to ``CreateProcess`` raises
    ``WinError 193`` (CHG-20260817-09). The interpreter running pytest is always present and always
    executable, so this needs no PATH probing and no shell in between — the executor still launches
    the stub directly, which is what the argv/env passthrough tests rely on.
    """
    def _make(body: str, name: str = "agent.py"):
        script = tmp_path / name
        script.write_text(body)
        return [sys.executable, str(script)]
    return _make


@pytest.fixture
def _skill_path():
    """Path to the ai-sdlc skill cache, from AI_SDLC_SKILL_PATH; skip the test if unavailable."""
    p = os.environ.get("AI_SDLC_SKILL_PATH")
    if not p or not Path(p).is_dir():
        pytest.skip("skill cache not provided via AI_SDLC_SKILL_PATH")
    return p
