"""The default `agent_timeout`, and the wire from it to the process (CHG-20260925-01).

Nothing asserted the timeout before this: not the default, not that a configured value reaches
`subprocess.run`. Replacing the default with `None` — no timeout at all — passed the whole suite.
These tests capture the keyword the process is started with instead of waiting on a real one, so
they cost nothing and cannot flake on a slow runner.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_sdlc_runner import cli  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _timeout_used(monkeypatch, config):
    """The `timeout=` one ask's process is started with, under ``config``."""
    seen = {}

    def fake_run(argv, **kw):
        seen["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(argv, 0, '{"ok": true}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    session = cli.session_factory(config)()
    session.ask({"node_id": "engineer_build", "role": "engineer"})
    return seen["timeout"]


def test_with_no_timeout_configured_the_process_gets_the_default(monkeypatch):
    assert _timeout_used(monkeypatch, {"agent_command": ["agent"]}) == cli.DEFAULT_AGENT_TIMEOUT


def test_a_configured_timeout_still_wins_over_the_default(monkeypatch):
    """The default fills the unconfigured case; it never overrides a value somebody wrote."""
    assert _timeout_used(monkeypatch, {"agent_command": ["agent"], "agent_timeout": "30"}) == 30


def test_the_documented_timeout_is_the_one_the_code_uses():
    """README's example and the shipped `config/runner.yaml` both state the number.

    Changing the default and not the documents — or the reverse — is the drift nothing caught when
    the value was a bare literal: no guard read README's yaml block.
    """
    for path in (ROOT / "README.md", ROOT / "config" / "runner.yaml"):
        found = re.findall(r"^agent_timeout:\s*(\d+)", path.read_text(encoding="utf-8"), re.M)
        assert found == [str(cli.DEFAULT_AGENT_TIMEOUT)], (
            f"{path.relative_to(ROOT)} states agent_timeout {found}; the code's default is "
            f"{cli.DEFAULT_AGENT_TIMEOUT}")
