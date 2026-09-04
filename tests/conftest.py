"""Shared pytest fixtures."""
import pathlib
import sys

import pytest


def pytest_configure(config):
    """**Refuse to measure a different checkout** (CHG-20260904-15, conformance seat).

    The package is installed editable, and `site-packages/__editable__.ai_sdlc_runner-*.pth`
    points at whichever checkout was installed from — in practice the main one. So a bare
    `pytest` inside a worktree imports `ai_sdlc_runner` from **somewhere else**, and a seat
    measuring a `src/` mutation this way got `98 passed` where the same mutation with
    `PYTHONPATH=src` gave `3 failed`. A green that measured another tree is worse than a red.

    The repo's own harness sets `PYTHONPATH=src` itself and was never exposed. Everything
    else — a person, CI, a review seat — is, so the suite says so before it runs rather than
    after somebody has trusted the answer.
    """
    del config
    import ai_sdlc_runner

    here = pathlib.Path(__file__).resolve().parents[1]
    imported = pathlib.Path(ai_sdlc_runner.__file__).resolve().parents[1]
    if imported != (here / "src").resolve():
        raise pytest.UsageError(
            "this suite is in %s and `import ai_sdlc_runner` resolves to %s. An editable\n"
            "install points at whichever checkout it was made from, so a bare `pytest` in a\n"
            "worktree measures that one. Run with PYTHONPATH=src." % (here, imported))


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
