"""Shared pytest fixtures."""
import os
import pathlib
import shutil
import sys
import warnings

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


@pytest.fixture
def remove_deep_chains(tmp_path):
    """Remove a `tmp_path` holding a path past `MAX_PATH`, and **say so when it cannot**.

    **What actually fails** (CHG-20260908-04). pytest keeps the last three basetemps and removes the
    older ones with `shutil.rmtree` on a plain path. Measured: a 353-character chain survives that
    call with `WinError 3`; `paths.real` + `rmtree` removes it. So a module that builds one leaves a
    `pytest-N` directory **pytest** cannot remove. The first draft of this record said *nothing*
    could — a seat ran `cmd /c rmdir /s /q` on one and it returned exit 0 with the directory gone.
    What is true is narrower and is the whole reason this exists: pytest's own cleanup is the thing
    that fails, so the directories accumulate until somebody notices.

    **Why it warns rather than ignoring the error.** The first build was
    `shutil.rmtree(..., ignore_errors=True)` and both seats refused it: a removal that silently does
    nothing keeps every test green while the directories go on accumulating — a guard that cannot
    fail, which is the class this ledger keeps finding, written into the repair for another one. And
    the case is not hypothetical: a seat measured `test_sqlite_opens_at_that_depth` **failing**
    before `db.close()`, where the open handle keeps `models.db` alive and the removal leaves the
    chain in place.

    A raise would be wrong there — it replaces the real failure with a teardown error and sends the
    operator to debug the cleanup. A warning names the path, survives a red test, and cannot be
    mistaken for success.

    **What it warns about is narrower than what it failed to remove**, and the first build of the
    warning got that wrong: it fired whenever the directory survived, which on
    `test_conversations_sqlite` was 41 of 48 tests — ordinary shallow directories that pytest
    removes without trouble, kept alive by open handles that have nothing to do with path length.
    Those are not this fixture's business. What matters is a survivor that still holds a path past
    `MAX_PATH`, because that is the one pytest's own unprefixed `rmtree` will also fail on.

    The message says the directory survived and how deep it is. It does not say **why**: an open
    handle is the case a seat measured, but this fixture does not know that, and a teardown that
    guesses at a cause is the kind of sentence this ledger spends its rounds removing.

    Named rather than autouse so that a module which builds a chain has to opt in. The second module
    doing this was found by a sweep, not by a fixture quietly covering it, and a third will have to
    say so too.
    """
    from ai_sdlc_runner import paths

    yield
    shutil.rmtree(paths.real(tmp_path), ignore_errors=True)
    if not os.path.isdir(tmp_path):
        return
    deepest = len(str(tmp_path))
    for root, _dirs, files in os.walk(paths.real(tmp_path)):
        deepest = max([deepest, len(root)] + [len(os.path.join(root, f)) for f in files])
    if deepest > 259:
        warnings.warn(
            f"deep-chain teardown could not remove {tmp_path}, and what survives reaches "
            f"{deepest} characters — past the limit pytest's own unprefixed rmtree fails at, so "
            f"this directory will outlive the run (CHG-20260908-04).",
            RuntimeWarning, stacklevel=1)
