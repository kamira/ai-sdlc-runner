"""Tests for the pluggable executor backends (CHG-20260617-06).

Covers stub, the command backend (against a local script — no real AI), API request building and
response parsing for each provider (no network), and the from_config factory. Also checks that the
choice of backend does not affect halt gating.
"""
from __future__ import annotations

import os
import stat

import pytest

from ai_sdlc_runner import agents, executors


def _spec(prompt="PROMPT-BODY"):
    return agents.AgentSpec("A1", ["Read"], False, False, "docs", prompt)


# --------------------------------------------------------------------------------------
# Stub + command
# --------------------------------------------------------------------------------------

def test_stub_executor():
    r = executors.StubExecutor().run(_spec())
    assert r["backend"] == "stub" and r["role"] == "A1" and r["stub"] is True


def test_command_executor_stdin(tmp_path):
    # A trivial local "agent" that echoes its stdin — proves any CLI tool can be driven.
    script = tmp_path / "agent.sh"
    script.write_text("#!/bin/sh\ncat\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    ex = executors.CommandExecutor(argv=[str(script)], prompt_via="stdin")
    r = ex.run(_spec("HELLO-123"))
    assert r["backend"] == "command" and r["returncode"] == 0 and "HELLO-123" in r["output"]


def test_command_executor_arg(tmp_path):
    script = tmp_path / "agent.sh"
    script.write_text('#!/bin/sh\necho "$1"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    ex = executors.CommandExecutor(argv=[str(script)], prompt_via="arg")
    r = ex.run(_spec("ARG-PROMPT"))
    assert "ARG-PROMPT" in r["output"]


def test_command_executor_empty_argv_errors():
    with pytest.raises(executors.ExecutorError):
        executors.CommandExecutor(argv=[]).run(_spec())


# --------------------------------------------------------------------------------------
# API request building + response parsing (no network)
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("provider,header_key", [
    ("anthropic", "x-api-key"),
    ("openai", "authorization"),
    ("generic", "authorization"),
])
def test_build_request_headers_and_body(provider, header_key):
    url, headers, body = executors.build_request(provider, "https://host/api", "mdl", "KEY", "hi")
    assert url == "https://host/api"
    assert header_key in {k.lower() for k in headers}
    assert b'"model"' in body and b"mdl" in body
    if provider == "anthropic":
        assert headers["x-api-key"] == "KEY"
    else:
        assert "Bearer KEY" in headers["authorization"]


@pytest.mark.parametrize("provider,raw,expected", [
    ("anthropic", '{"content":[{"text":"A"}]}', "A"),
    ("openai", '{"choices":[{"message":{"content":"B"}}]}', "B"),
    ("generic", '{"output":"C"}', "C"),
    ("generic", '{"text":"D"}', "D"),
])
def test_parse_response(provider, raw, expected):
    assert executors.parse_response(provider, raw) == expected


def test_parse_response_non_json_returns_raw():
    assert executors.parse_response("generic", "plain text") == "plain text"


def test_api_executor_missing_key_errors(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    ex = executors.ApiExecutor(base_url="https://x", model="m", provider="anthropic", api_key_env="NOPE_KEY")
    with pytest.raises(executors.ExecutorError) as exc:
        ex.run(_spec())
    assert "NOPE_KEY" in str(exc.value)


# --------------------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------------------

def test_from_config_defaults_to_stub():
    assert isinstance(executors.from_config({}), executors.StubExecutor)


def test_from_config_override_wins():
    # Config says stub, but the override selects command (and supplies argv) -> CommandExecutor.
    cfg = {"executor": {"backend": "stub", "command": {"argv": ["echo"]}}}
    ex = executors.from_config(cfg, override_backend="command")
    assert isinstance(ex, executors.CommandExecutor) and ex.argv == ["echo"]


def test_from_config_api_requires_base_url_and_model():
    with pytest.raises(executors.ExecutorError):
        executors.from_config({"executor": {"backend": "api", "api": {"model": "m"}}})


def test_from_config_api_ok():
    cfg = {"executor": {"backend": "api", "api": {"base_url": "https://x", "model": "m", "provider": "openai"}}}
    ex = executors.from_config(cfg)
    assert isinstance(ex, executors.ApiExecutor) and ex.provider == "openai"


def test_from_config_unknown_backend_errors():
    with pytest.raises(executors.ExecutorError):
        executors.from_config({"executor": {"backend": "telepathy"}})
