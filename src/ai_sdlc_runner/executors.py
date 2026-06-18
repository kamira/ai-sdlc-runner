"""executors.py — pluggable, platform-agnostic agent-execution backends.

The backend that actually runs an agent is a **runtime concern**, not part of the contract
(build-guide §1.7). This module lets the runner drive agents through any AI platform:

  • ``stub``     — no-op (offline / dry-run; the default).
  • ``command``  — run any local CLI agent (a **subscription**-based tool, e.g. a logged-in CLI), passing
                   the agent prompt via stdin or as an argument; captures its output.
  • ``api``      — call an HTTP **API**; generic by config (``base_url``/``model``/``api_key_env``) with
                   ``anthropic`` / ``openai`` / ``generic`` request+parse adapters. Uses stdlib ``urllib``.

Secrets (API keys) are read from an environment variable named in config — never stored in config/repo.
The executor only performs *agent work*; halt gates and red-line stops are independent and unchanged.
Zero third-party dependencies.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import agents

BACKEND_STUB = "stub"
BACKEND_COMMAND = "command"
BACKEND_API = "api"


class ExecutorError(Exception):
    """Raised when a backend is misconfigured or a call fails."""


# --------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------

class StubExecutor:
    """No-op backend: records the spec without launching anything (offline / dry-run)."""

    backend = BACKEND_STUB

    def run(self, spec: agents.AgentSpec) -> dict:
        return {"role": spec.role, "tools": spec.tools, "scope": spec.scope,
                "backend": self.backend, "stub": True}


@dataclass
class CommandExecutor:
    """Run any local CLI agent (subscription-based or otherwise).

    ``argv`` is the base command (e.g. ``["claude", "-p"]`` or ``["my-agent"]``). The agent prompt is
    delivered via stdin (``prompt_via="stdin"``) or appended as a final argument (``"arg"``). This is
    deliberately platform-agnostic — it works with any tool that reads a prompt and writes a reply.
    """

    argv: List[str]
    prompt_via: str = "stdin"          # "stdin" | "arg"
    timeout: int = 600
    env: Dict[str, str] = field(default_factory=dict)
    backend: str = BACKEND_COMMAND

    def run(self, spec: agents.AgentSpec) -> dict:
        if not self.argv:
            raise ExecutorError("command backend requires a non-empty `argv`")
        cmd = list(self.argv)
        stdin_data: Optional[str] = None
        if self.prompt_via == "arg":
            cmd.append(spec.prompt)
        else:
            stdin_data = spec.prompt
        run_env = {**os.environ, **self.env}
        try:
            proc = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True,
                                  timeout=self.timeout, env=run_env)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ExecutorError(f"command backend failed to launch {cmd!r}: {exc}") from exc
        return {"role": spec.role, "backend": self.backend, "returncode": proc.returncode,
                "output": (proc.stdout or "").strip(), "error": (proc.stderr or "").strip()}


@dataclass
class ApiExecutor:
    """Call an HTTP API. Platform-agnostic via config; key read from ``api_key_env``."""

    base_url: str
    model: str
    provider: str = "generic"          # "anthropic" | "openai" | "generic"
    api_key_env: str = "AI_SDLC_API_KEY"
    timeout: int = 120
    max_tokens: int = 4096
    backend: str = BACKEND_API

    def run(self, spec: agents.AgentSpec) -> dict:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ExecutorError(
                f"api backend: environment variable {self.api_key_env} is not set "
                f"(API keys are read from the environment, never from config)."
            )
        url, headers, body = build_request(self.provider, self.base_url, self.model, key,
                                            spec.prompt, self.max_tokens)
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (user-configured URL)
                raw = resp.read().decode("utf-8")
        except Exception as exc:  # urllib.error.URLError, timeouts, etc.
            raise ExecutorError(f"api backend request to {url} failed: {exc}") from exc
        text = parse_response(self.provider, raw)
        return {"role": spec.role, "backend": self.backend, "provider": self.provider,
                "model": self.model, "output": text}


# --------------------------------------------------------------------------------------
# Request building / response parsing (pure, unit-tested without network)
# --------------------------------------------------------------------------------------

def build_request(provider: str, base_url: str, model: str, api_key: str, prompt: str,
                  max_tokens: int = 4096) -> Tuple[str, Dict[str, str], bytes]:
    """Build ``(url, headers, body_bytes)`` for the given provider. No network I/O."""
    p = (provider or "generic").lower()
    if p == "anthropic":
        headers = {
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {"model": model, "max_tokens": max_tokens,
                   "messages": [{"role": "user", "content": prompt}]}
    elif p == "openai":
        headers = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    else:  # generic
        headers = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}
        payload = {"model": model, "prompt": prompt, "max_tokens": max_tokens}
    return base_url, headers, json.dumps(payload).encode("utf-8")


def parse_response(provider: str, raw: str) -> str:
    """Extract the assistant text from a raw JSON response for the given provider."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()
    p = (provider or "generic").lower()
    try:
        if p == "anthropic":
            return data["content"][0]["text"]
        if p == "openai":
            return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        pass
    # generic / fallback
    for key in ("output", "text", "completion", "response"):
        if isinstance(data, dict) and key in data:
            return str(data[key])
    return raw.strip()


# --------------------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------------------

def from_config(config: dict, override_backend: Optional[str] = None) -> object:
    """Build an executor from the ``executor`` block of runner.yaml (or an override backend).

    Defaults to the stub backend (offline/dry-run) when nothing is configured.
    """
    spec = config.get("executor", {}) if isinstance(config.get("executor"), dict) else {}
    backend = (override_backend or spec.get("backend") or BACKEND_STUB).lower()

    if backend == BACKEND_STUB:
        return StubExecutor()
    if backend == BACKEND_COMMAND:
        cmd = spec.get("command", {}) if isinstance(spec.get("command"), dict) else {}
        argv = cmd.get("argv")
        if isinstance(argv, str):
            argv = argv.split()
        if not argv:
            raise ExecutorError("executor.command.argv is required for the `command` backend")
        return CommandExecutor(
            argv=list(argv),
            prompt_via=cmd.get("prompt_via", "stdin"),
            timeout=int(cmd.get("timeout", 600)),
            env=cmd.get("env", {}) if isinstance(cmd.get("env"), dict) else {},
        )
    if backend == BACKEND_API:
        api = spec.get("api", {}) if isinstance(spec.get("api"), dict) else {}
        if not api.get("base_url") or not api.get("model"):
            raise ExecutorError("executor.api requires `base_url` and `model`")
        return ApiExecutor(
            base_url=api["base_url"],
            model=api["model"],
            provider=api.get("provider", "generic"),
            api_key_env=api.get("api_key_env", "AI_SDLC_API_KEY"),
            timeout=int(api.get("timeout", 120)),
            max_tokens=int(api.get("max_tokens", 4096)),
        )
    raise ExecutorError(f"unknown executor backend: {backend!r} (use stub|command|api)")
