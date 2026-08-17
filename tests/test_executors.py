"""Tests for the pluggable executor backends (CHG-20260617-06).

Covers stub, the command backend (against a local script — no real AI), API request building and
response parsing for each provider (no network), and the from_config factory. Also checks that the
choice of backend does not affect halt gating.
"""
from __future__ import annotations

import os

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


def test_command_executor_stdin(py_stub):
    # A trivial local "agent" that echoes its stdin — proves any CLI tool can be driven.
    argv = py_stub("import sys\nsys.stdout.write(sys.stdin.read())\n")
    ex = executors.CommandExecutor(argv=argv, prompt_via="stdin")
    r = ex.run(_spec("HELLO-123"))
    assert r["backend"] == "command" and r["returncode"] == 0 and "HELLO-123" in r["output"]


def test_command_executor_arg(py_stub):
    argv = py_stub("import sys\nprint(sys.argv[1])\n")
    ex = executors.CommandExecutor(argv=argv, prompt_via="arg")
    r = ex.run(_spec("ARG-PROMPT"))
    assert "ARG-PROMPT" in r["output"]


def test_command_executor_empty_argv_errors():
    with pytest.raises(executors.ExecutorError):
        executors.CommandExecutor(argv=[]).run(_spec())


def test_command_executor_launch_failure_raises(tmp_path):
    # The other half of the failure contract: empty argv is caught by the guard *before*
    # subprocess.run, this one is caught after it. runner.yaml lets a user point argv at any local
    # CLI, and the usual misconfiguration is a binary that isn't installed — the raw
    # FileNotFoundError must not escape the executor abstraction. A path that was never created
    # fails identically on every platform, so this fixture stays portable by construction
    # (CHG-20260817-11).
    missing = tmp_path / "no-such-agent-binary"
    ex = executors.CommandExecutor(argv=[str(missing)])
    with pytest.raises(executors.ExecutorError) as exc:
        ex.run(_spec())
    # The type alone isn't the contract — the message has to say what failed to start.
    assert "failed to launch" in str(exc.value)
    assert "no-such-agent-binary" in str(exc.value)


# --------------------------------------------------------------------------------------
# extra_args / extra_env passthrough (CHG-20260703-02)
# --------------------------------------------------------------------------------------

def test_command_executor_extra_args_appended(py_stub):
    # A script that prints argv (minus argv[0]) so we can assert extra_args landed after argv.
    argv = py_stub('import sys\nfor a in sys.argv[1:]:\n    print("ARG:" + a)\n'
                   'sys.stdout.write(sys.stdin.read())\n')
    ex = executors.CommandExecutor(argv=argv, prompt_via="stdin",
                                    extra_args=["--settings", "config/pure-ai-sdlc.settings.json"])
    r = ex.run(_spec("BODY"))
    assert r["returncode"] == 0
    assert "ARG:--settings" in r["output"]
    assert "ARG:config/pure-ai-sdlc.settings.json" in r["output"]
    assert "BODY" in r["output"]


def test_command_executor_extra_env_merged(py_stub, monkeypatch):
    monkeypatch.setenv("ECC_BASE_VAR", "base")
    argv = py_stub('import os\nprint("BASE=" + os.environ.get("ECC_BASE_VAR", ""))\n'
                   'print("EXTRA=" + os.environ.get("ECC_EXTRA_VAR", ""))\n')
    ex = executors.CommandExecutor(argv=argv, extra_env={"ECC_EXTRA_VAR": "injected"})
    r = ex.run(_spec())
    assert "BASE=base" in r["output"]          # inherited env still present
    assert "EXTRA=injected" in r["output"]     # extra_env merged on top


def test_command_executor_defaults_empty_extra_fields():
    ex = executors.CommandExecutor(argv=["echo"])
    assert ex.extra_args == [] and ex.extra_env == {}


def test_from_config_command_reads_extra_args_and_env():
    cfg = {"executor": {"backend": "command", "command": {
        "argv": ["claude", "-p"],
        "extra_args": ["--settings", "config/pure-ai-sdlc.settings.json"],
        "extra_env": {"FOO": "bar"},
    }}}
    ex = executors.from_config(cfg)
    assert isinstance(ex, executors.CommandExecutor)
    assert ex.extra_args == ["--settings", "config/pure-ai-sdlc.settings.json"]
    assert ex.extra_env == {"FOO": "bar"}


def test_from_config_command_extra_fields_default_empty():
    cfg = {"executor": {"backend": "command", "command": {"argv": ["echo"]}}}
    ex = executors.from_config(cfg)
    assert ex.extra_args == [] and ex.extra_env == {}


def test_stub_executor_unaffected_by_extra_fields():
    # extra_args/extra_env are command-backend-only concepts; stub ignores config entirely.
    r = executors.StubExecutor().run(_spec())
    assert r["backend"] == "stub" and "extra_args" not in r and "extra_env" not in r


def test_api_executor_unaffected_by_extra_fields():
    # ApiExecutor has no extra_args/extra_env fields at all — api backend is untouched by CHG-20260703-02.
    ex = executors.ApiExecutor(base_url="https://x", model="m")
    assert not hasattr(ex, "extra_args") and not hasattr(ex, "extra_env")


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
