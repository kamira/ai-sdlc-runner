#!/usr/bin/env python3
"""The review matrix: every model on every dimension, one session each. (CHG-20260929-01)

DIR-2 says a review panel is three seats, each in its own session, then cross-read. It was run by
hand. The user then asked that every review and decision be confirmed by **every model on every
dimension** — one session per (model x dimension), the set of dimensions theirs to configure. At
twelve dimensions and three models that is 36 sessions a round, and a round that costs 36 hand-run
sessions is a round that gets skipped. So the rule becomes this tool, and the tool is the rule's
mechanism: KN-8 says a rule nothing runs is a paragraph.

What it keeps, and why:

* **The tree is frozen first and last (KN-14).** A dirty tree runs nothing. The sha is recorded, and
  checked again after the last seat reports: a round whose subject moved has verified nothing.
* **Unreached is a third state (KN-15).** A seat that crashed, timed out, exited non-zero or did not
  end on a `VERDICT:` line has not said pass, and it has not said fail. It is `unreached`, and
  "unknown" is not the safe answer — so it can never round to pass.
* **An unreached seat stops the round and asks the user (DIR-2).** No fallback panel, no retry, no
  quorum: the round is `incomplete`, the report says which cells and why, and the exit code is 3.
  Sessions not yet started when a seat is unreached are not started, and every seat's executable
  must resolve before anything is dispatched.
* **A round without cross-read never passes (DIR-3).** `--no-cross-read`, or a one-model config,
  can report `fail` or `incomplete`, never `pass`.
* **A reduced panel never passes (DIR-3).** `--only-dimensions` is allowed, for a targeted re-check,
  but a round whose matrix is smaller than every enabled dimension x every configured model can
  report `fail` or `incomplete`, never `pass`. Completeness is judged against DIR-2's engines
  (REQUIRED_ENGINES), not against whatever the config lists: a config without one of them can run a
  round that never passes ("reduced panel: engine X missing").
* **Ctrl-C stops the round.** Queued cells are cancelled, the live seats' process trees are killed,
  and the report is still written — `incomplete`, "interrupted by the operator", exit 130.
* **A round can be resumed.** `--resume DIR` keeps every pass/fail cell of an earlier round at the
  same commit whose fingerprint (dimension, model, argv, phase) still matches, and re-runs the rest,
  so a round too big for one quota window is paid for once. A round whose closing freeze check was
  not `ok` (`closing_freeze` in report.json), or that was interrupted, is refused (exit 2, KN-14).
  `--out` may not be the `--resume` directory or inside it: the earlier report is never overwritten,
  and an `--out` that already holds a report is refused.
* **The reviewers' controls come from the base, not the tree under review.** `config/panel.json` is
  read with `git show REF:config/panel.json` (`--config-from`, default `origin/main`), so a change
  cannot weaken its own reviewers. `--config PATH` takes the file as it is, and the report says so
  ("config taken from the reviewed tree" when the file is inside the repo).
* **What is sent, and to whom, is printed before it is sent** and recorded in the report: each
  model's executable and `reach`, the brief's size, and what each engine can read — stated per engine
  (READ_SCOPE) and without claiming a confinement nobody enforces: the codex `-s read-only` sandbox
  and claude's Read/Grep/Glob are not limited to the repo. Git-ignored files under the repo
  (`.env`, `.runner/`) are listed, up to 50. The disclosure is flushed before the first seat starts.
* **Executables come from PATH, never from the tree.** The seats, `git` and Windows' `taskkill` are
  looked up only in absolute PATH entries outside the repo (never the cwd, which Windows searches
  first); one that resolves inside the repo, or is not found, is refused before anything is sent.
* **A disagreement is escalated, never averaged (DIR-2).** Cross-read DISAGREE lines are collected
  and reported as they were said.
* **Seats are read-only and separate (KN-7).** Each cell is its own process, brief on stdin (from a
  file, `cells/<stem>.brief.txt`, so a seat that never reads it cannot hang the round), run from
  the repo root; the argv in `config/panel.json` is what removes the seat's write tools and stops
  the reviewed tree's own settings (hooks) from loading.

Usage::

    python tools/panel.py list
    python tools/panel.py run --brief BRIEF.md --out DIR [--only-dimensions defect,risk] [--jobs 6]
    python tools/panel.py run --brief BRIEF.md --out NEW_DIR --resume EARLIER_DIR
    python tools/panel.py run --brief BRIEF.md --out DIR --config PATH      # not the base's config

Exit codes: 0 pass; 1 fail, or the tree is not frozen; 2 bad configuration or arguments; 3 the round
is incomplete (a seat unreached, a reduced panel, or the tree moved) — never a pass; 130 interrupted.

**Interpreted:** `--out` must be outside the repo. Raw seat output written inside it would itself
dirty the tree the round is verifying, and the end-of-round freeze check would fail every round.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import frozen_tree  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "panel.json"
CONFIG_IN_REPO = "config/panel.json"        # where the panel's config lives in the repo under review
DEFAULT_CONFIG_FROM = "origin/main"         # the base a change is measured against
REQUIRED_ENGINES = ("fable", "opus", "gpt-6-astra")   # DIR-2's three seats; DIR-3: each on every dimension
DEFAULT_TIMEOUT = 1800
DEFAULT_JOBS = 6

LOCK_NAME = ".round.lock"            # a directory made exclusively in --out for as long as a round runs in it
PROJECT_CODEX_CONFIG = (".codex",)   # what codex loads from the tree it is run in
# bare names a seat's launcher may fall back to, which Windows looks for in the current directory
LAUNCHER_NAMES = frozenset(("node", "node.exe", "node.cmd", "node.bat", "cmd.exe", "powershell.exe",
                            "pwsh.exe", "python.exe", "py.exe"))
KILL_GRACE = 10                     # seconds to keep reading after a timed-out seat's tree is killed
WAIT_POLL = 0.5                     # seconds one wait may block: Ctrl-C is only delivered between waits
IGNORED_CAP = 50                    # git-ignored paths listed in the disclosure; the rest are counted

KINDS = ("claude", "codex")
READ_SCOPE = {                      # what a seat can read, per engine; nothing here confines it to the repo
    "claude": "Read/Grep/Glob are not confined to the repo: this tool does not restrict them, so any "
              "file the user can read may be read (a refusal outside the start directory is claude's "
              "own permission behaviour, seen in DIR-2, and is not enforced here)",
    "codex": "`-s read-only` blocks writes, not reads: the sandbox allows reading the whole "
             "filesystem the user can read",
}
REACHES = ("local", "internal", "external")
DEFAULT_REACH = "external"          # a model nobody classified is assumed to leave the machine
_TOP_KEYS = {"models", "coder", "dimensions"}
_MODEL_KEYS = {"id", "argv", "kind", "reach"}
_CODER_KEYS = {"model", "effort"}
_DIMENSION_KEYS = {"id", "label", "question", "enabled"}

PASS, FAIL, UNREACHED = "pass", "fail", "unreached"
INTERRUPTED = "interrupted by the operator"
STOPPED = "not run: round stopped after an unreached seat"
_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")   # an id becomes a file stem: two ids must never share one
_VERDICT_LINE =re.compile(r"^VERDICT: (pass|fail)$")
_DISAGREE = re.compile(r"^\s*(?:(?:[-*+•]|\d+[.)])\s+)?[*_`]*DISAGREE\b", re.IGNORECASE)
_AGENT_MESSAGE_TYPES = ("agent_message", "assistant_message")


class ConfigError(Exception):
    """The panel's data is not usable. Exits 2 and nothing is run."""


# ---------------------------------------------------------------------------------------- config

def _closed(obj: Any, allowed: set, where: str) -> None:
    if not isinstance(obj, dict):
        raise ConfigError(f"{where} must be an object")
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key {unknown[0]!r} (allowed: {', '.join(sorted(allowed))})")


def _text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: {key!r} must be a non-empty string")
    return value


def _check_id(value: str, where: str) -> None:
    """Ids name cell files (`risk/a` and `risk?a` would both be `risk_a`), so the alphabet is closed."""
    if not _ID.fullmatch(value):
        raise ConfigError(f"{where}: id {value!r} must match [a-z0-9][a-z0-9_-]* — it names a file")


def load_config(path: Path) -> dict:
    """The panel's data from a file, checked (see `parse_config`)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    return parse_config(text, str(path))


def parse_config(text: str, where_from: str) -> dict:
    """The panel's data, checked. Closed key sets: a misspelt key is an error, not a silent default —
    a dimension whose `enabled` was mistyped must not quietly stop being asked."""
    try:
        config = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"cannot read {where_from}: {exc}") from None
    _closed(config, _TOP_KEYS, "config")
    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise ConfigError("config: 'models' must be a list with at least one model")
    seen = set()
    for index, model in enumerate(models):
        where = f"models[{index}]"
        _closed(model, _MODEL_KEYS, where)
        mid = _text(model, "id", where)
        _check_id(mid, where)
        if mid in seen:
            raise ConfigError(f"{where}: duplicate model id {mid!r}")
        seen.add(mid)
        argv = model.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ConfigError(f"{where}: 'argv' must be a non-empty list of strings")
        if model.get("kind") not in KINDS:
            raise ConfigError(f"{where}: 'kind' must be one of {list(KINDS)}, not {model.get('kind')!r}")
        if model.get("reach", DEFAULT_REACH) not in REACHES:
            raise ConfigError(f"{where}: 'reach' must be one of {list(REACHES)}, not {model.get('reach')!r}")
    if "coder" in config:
        _closed(config["coder"], _CODER_KEYS, "coder")
    dimensions = config.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ConfigError("config: 'dimensions' must be a non-empty list")
    seen = set()
    for index, dim in enumerate(dimensions):
        where = f"dimensions[{index}]"
        _closed(dim, _DIMENSION_KEYS, where)
        did = _text(dim, "id", where)
        _check_id(did, where)
        _text(dim, "label", where)
        _text(dim, "question", where)
        if not isinstance(dim.get("enabled"), bool):
            raise ConfigError(f"{where}: 'enabled' must be true or false")
        if did in seen:
            raise ConfigError(f"{where}: duplicate dimension id {did!r}")
        seen.add(did)
    return config


def select_matrix(config: dict, only: Optional[List[str]]) -> Tuple[List[dict], List[dict]]:
    """(dimensions, models) a round runs, in config order.

    `--only-dimensions` names known ids, disabled ones included: an explicit ask overrides `enabled`,
    which is only the default set. An id nobody defined is an error rather than a smaller round.
    """
    dims = config["dimensions"]
    if only is None:
        chosen = [d for d in dims if d["enabled"]]
    else:
        known = {d["id"] for d in dims}
        for name in only:
            if name not in known:
                raise ConfigError(f"--only-dimensions: unknown dimension {name!r} (known: {', '.join(sorted(known))})")
        chosen = [d for d in dims if d["id"] in only]
    if not chosen:
        raise ConfigError("no dimensions selected — every dimension is disabled")
    return chosen, config["models"]


def reduced_panel(config: dict, dims: List[dict], models: List[dict]) -> Optional[str]:
    """What this round leaves out of enabled dimensions x DIR-2's engines, else None. The engines are
    REQUIRED_ENGINES whatever the config lists: a panel judged only against its own config could drop
    an engine and still look complete."""
    ran_dims, ran_models = {d["id"] for d in dims}, {m["id"] for m in models}
    parts = []
    configured = {m["id"] for m in config["models"]}
    parts += [f"engine {e} missing" for e in REQUIRED_ENGINES if e not in configured]
    absent = [d["id"] for d in config["dimensions"] if d["enabled"] and d["id"] not in ran_dims]
    if absent:
        parts.append("dimensions not run: " + ", ".join(absent))
    absent = [m["id"] for m in config["models"] if m["id"] not in ran_models]
    if absent:
        parts.append("models not run: " + ", ".join(absent))
    return "; ".join(parts) or None


def session_count(dims: List[dict], models: List[dict], cross_read: bool) -> Tuple[int, int]:
    """(review sessions, cross-read sessions). A lone model has nobody to cross-read."""
    review = len(dims) * len(models)
    cross = review if cross_read and len(models) > 1 else 0
    return review, cross


# ----------------------------------------------------------------------------------------- briefs

_CONTRACT = ("End your answer with exactly one final line, and nothing after it: `VERDICT: pass` if "
             "you find nothing that should block this, or `VERDICT: fail` if you find anything that should.")


def review_header(model: dict, dim: dict, sha: str) -> str:
    return "\n".join([
        f"# Review seat — {model['id']} on {dim['id']} ({dim['label']})",
        "",
        f"Seat: {model['id']}",
        f"Dimension: {dim['id']} — {dim['label']}",
        f"Question: {dim['question']}",
        f"Commit under review: {sha}",
        "",
        "You are one seat of a review matrix: one model, one dimension, one session. You will not see "
        "the other seats. This is read only — do not modify the repository, and do not run anything "
        "that would.",
        "",
        _CONTRACT,
        "",
        "---",
        "",
    ])


def cross_header(model: dict, dim: dict, sha: str) -> str:
    return "\n".join([
        f"# CROSS-READ — {model['id']} on {dim['id']} ({dim['label']})",
        "",
        f"Seat: {model['id']}",
        f"Dimension: {dim['id']} — {dim['label']}",
        f"Question: {dim['question']}",
        f"Commit under review: {sha}",
        "",
        "This is a new session. Other seats reviewed the same brief on this dimension; their answers "
        "follow it. Mark each finding they raise as AGREE or DISAGREE, on a line of its own that "
        "starts with that word, with your reason. This is read only — verify against the repository, "
        "do not modify it.",
        "",
        _CONTRACT,
        "",
        "---",
        "",
    ])


def cross_brief(model: dict, dim: dict, sha: str, brief: str, others: List[Tuple[str, str]]) -> str:
    parts = [cross_header(model, dim, sha), "## The brief\n\n", brief, "\n\n## The other seats' answers\n"]
    for other_id, answer in others:
        parts.append(f"\n<<< answer of {other_id} on {dim['id']} >>>\n{answer}\n<<< end of {other_id} >>>\n")
    return "".join(parts)


# ---------------------------------------------------------------------------------- answer + usage

def verdict_of(text: Optional[str]) -> Optional[str]:
    """`pass`/`fail` when the FINAL non-empty line is exactly `VERDICT: pass` or `VERDICT: fail`
    (surrounding whitespace and markdown `*`/backticks aside), else None. The contract says the verdict
    is the last line, so an earlier verdict followed by anything else — `VERDICT: ok`, "I could not
    finish" — is an answer that did not end, not a pass."""
    lines = [line.strip(" \t\r*`") for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    hit = _VERDICT_LINE.match(lines[-1]) if lines else None
    return hit.group(1) if hit else None


def _events(stdout: str) -> List[Any]:
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def _last_key(obj: Any, key: str) -> Any:
    """The last value under `key` anywhere in a JSON value (depth first, in order), else None."""
    found = None
    if isinstance(obj, dict):
        for name, value in obj.items():
            if name == key and value is not None:
                found = value
            inner = _last_key(value, key)
            if inner is not None:
                found = inner
    elif isinstance(obj, list):
        for value in obj:
            inner = _last_key(value, key)
            if inner is not None:
                found = inner
    return found


def _claude_json(stdout: str) -> Optional[dict]:
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(data, list):                      # a stream of events: the result event is the answer
        data = next((e for e in reversed(data) if isinstance(e, dict) and e.get("type") == "result"), None)
    return data if isinstance(data, dict) else None


def extract_answer(kind: str, stdout: str) -> Optional[str]:
    """The seat's answer text, or None when stdout does not hold one.

    claude: stdout is one JSON object, the answer is `result` — no fallback, because scanning raw
    JSON for a verdict would let a malformed reply through. codex `--json`: JSONL events, the answer
    is every `agent_message` of the last turn, joined in order (codex-cli 0.158.0); the event
    shape has moved between releases, so this also takes an `item`/`msg` of an agent-message type
    with a string `text` or `message`, and falls back to raw stdout when it finds none.
    """
    if kind == "claude":
        data = _claude_json(stdout)
        result = data.get("result") if data else None
        return result if isinstance(result, str) else None
    turn: List[str] = []
    for event in _events(stdout):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "turn.started":
            turn = []
        for key in ("item", "msg"):
            inner = event.get(key)
            if isinstance(inner, dict) and inner.get("type") in _AGENT_MESSAGE_TYPES:
                for field in ("text", "message"):
                    if isinstance(inner.get(field), str):
                        turn.append(inner[field])
                        break
    return "\n".join(turn) if turn else stdout


def codex_home(override: Optional[Path] = None) -> Path:
    """Where codex keeps its session logs: the argument, else `$CODEX_HOME`, else `~/.codex`."""
    if override is not None:
        return Path(override)
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _rollout_rate_limits(home: Path, thread_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """(the LAST `rate_limits` object in this thread's rollout file, when it was observed), else
    (None, None).

    codex never prints rate limits on stdout; they are only in `sessions/YYYY/MM/DD/rollout-<ts>-
    <thread_id>.jsonl`. The file is matched by the id it ends with, so another thread's rollout —
    a concurrent seat's — is never read as this one's. The time is the top-level `timestamp` of the
    line that carried the limits, else the file's mtime: a quota is a level, and which cell's reading
    is the current one is decided by when it was taken, not by where the cell sits in a list.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", thread_id):     # it goes into a glob; no metacharacters
        return None, None
    rate = at = None
    for path in sorted((home / "sessions").glob(f"**/*-{thread_id}.jsonl")):
        for event in _events(path.read_text(encoding="utf-8", errors="replace")):
            found = _last_key(event, "rate_limits")
            if isinstance(found, dict):
                stamp = event.get("timestamp") if isinstance(event, dict) else None
                rate, at = found, stamp if isinstance(stamp, str) and stamp else _mtime_iso(path)
    return rate, at


def _mtime_iso(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _when(stamp: Any) -> datetime:
    """An ISO timestamp as an aware datetime; anything unreadable is the oldest possible."""
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    if not isinstance(stamp, str):
        return oldest
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return oldest
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def extract_usage(kind: str, stdout: str, home: Optional[Path] = None) -> Optional[dict]:
    """What the cell cost, best effort. Never raises: usage is a report, not a verdict.

    codex: tokens are the last `turn.completed.usage` on stdout; rate limits are not on stdout at all
    and come from the thread's rollout file under `codex_home(home)`. No file, or no rate limits in
    it, is `rate_limits: None` — the cell's tokens still count.
    """
    try:
        if kind == "claude":
            data = _claude_json(stdout) or {}
            raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            usage = {"total_cost_usd": data.get("total_cost_usd")}
            for name in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                         "cache_creation_input_tokens"):
                usage[name] = raw.get(name)
        else:
            tokens = thread_id = None
            for event in _events(stdout):
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                    thread_id = event["thread_id"]
                elif event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                    tokens = event["usage"]
            rate = at = None
            if thread_id:
                try:
                    rate, at = _rollout_rate_limits(codex_home(home), thread_id)
                except OSError:
                    rate = at = None
            usage = {"rate_limits": rate, "rate_limits_at": at, "token_usage": tokens}
        return usage if any(v is not None for v in usage.values()) else None
    except Exception:                                # noqa: BLE001 — best effort by contract
        return None


# ------------------------------------------------------------------------------------------ cells

def _on_windows() -> bool:
    return os.name == "nt"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def cell_stem(phase: str, dimension_id: str, model_id: str) -> str:
    """The file stem of a cell. Collision-free by construction: ids never contain `.` (`_ID`), so the
    `.` that joins the three parts can only be a separator — `a__b` x `c` and `a` x `b__c` are
    different stems, which a `__` join could not tell apart."""
    return f"{phase}.{_safe(dimension_id)}.{_safe(model_id)}"


def check_stems(dims: List[dict], models: List[dict]) -> None:
    """Every cell of the round has a stem of its own, asserted before anything is dispatched: two
    cells sharing one would share a brief and an output file, and a verdict could be filed under a
    dimension its seat never reviewed."""
    seen: Dict[str, Tuple[str, str, str]] = {}
    for phase in ("review", "cross"):
        for d in dims:
            for m in models:
                stem = cell_stem(phase, d["id"], m["id"])
                if stem in seen:
                    raise ConfigError(f"cells {seen[stem]} and {(phase, d['id'], m['id'])} share the file "
                                      f"stem {stem!r}; nothing was run")
                seen[stem] = (phase, d["id"], m["id"])


def _kill_tree(proc: "subprocess.Popen", repo: Path) -> None:
    """Kill the seat and everything it started. Killing only the launcher leaves a grandchild (a
    Windows `.cmd` shim's node process) holding the pipes, and the read then never ends. `taskkill`
    is found like the seats are (PATH entries outside the repo): a bare name is searched in the
    current directory first on Windows, and the operator may be standing in the reviewed tree. Not
    found, it is not run, and only the launcher is killed."""
    try:
        if _on_windows():
            exe, _why = locate_executable("taskkill", repo)
            if exe:
                subprocess.run([exe, "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                               timeout=KILL_GRACE)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


class _Fleet:
    """One phase's stop flag and its live seats, so an interrupt can reach them. `stop` only keeps
    queued cells from starting; `aborted` (the operator's Ctrl-C) also kills the running ones."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.stop = threading.Event()
        self.aborted = threading.Event()
        self._lock = threading.Lock()
        self._live: set = set()

    def add(self, proc: "subprocess.Popen") -> None:
        with self._lock:
            self._live.add(proc)
            if self.aborted.is_set():                # started in the gap between the check and the kill
                _kill_tree(proc, self.repo)

    def discard(self, proc: "subprocess.Popen") -> None:
        with self._lock:
            self._live.discard(proc)

    def abort(self) -> None:
        self.stop.set()
        with self._lock:
            self.aborted.set()
            for proc in list(self._live):
                _kill_tree(proc, self.repo)


def _drain(pipe: Any, sink: List[bytes]) -> None:
    """Append what `pipe` yields to `sink` until EOF. Run as a daemon thread, started at spawn."""
    try:
        while True:
            chunk = pipe.read1(65536)
            if not chunk:
                return
            sink.append(chunk)
    except (OSError, ValueError):
        pass


def _run_process(argv: List[str], brief_file: Path, cwd: str, timeout: float,
                 fleet: Optional[_Fleet] = None) -> Tuple[str, str, Optional[int], bool]:
    """(stdout, stderr, exit code, timed out). The brief is the seat's stdin as an open file, never
    fed through the pipe: on Windows `communicate(input=...)` writes it before the timeout is in
    force, so a seat that never reads it would hang the round. Output is read by our own daemon
    threads, not `communicate()`: on timeout the whole process tree is killed and the threads are
    joined for at most KILL_GRACE more seconds, then abandoned. The pipes are never closed from
    here, because closing one a reader is blocked on can itself block (CPython on Windows)."""
    fleet = fleet or _Fleet(Path(cwd))
    extra: Dict[str, Any] = {}
    if _on_windows():
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True            # its own process group, so killpg reaches every child
    with open(brief_file, "rb") as stdin:
        proc = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=cwd, env=dict(os.environ, PATH=os.pathsep.join(_safe_path(fleet.repo)),
                                                  NoDefaultCurrentDirectoryInExePath="1"),
                                **extra)
        fleet.add(proc)
        try:
            sinks: List[List[bytes]] = [[], []]
            readers = [threading.Thread(target=_drain, args=(pipe, sink), daemon=True)
                       for pipe, sink in zip((proc.stdout, proc.stderr), sinks)]
            for reader in readers:
                reader.start()

            def join(seconds: float) -> bool:
                """Wait for the readers; once the operator has aborted, for at most KILL_GRACE more."""
                end = time.monotonic() + seconds
                capped = False
                while any(reader.is_alive() for reader in readers) and time.monotonic() < end:
                    if fleet.aborted.is_set() and not capped:
                        end, capped = min(end, time.monotonic() + KILL_GRACE), True
                    readers[0].join(WAIT_POLL / 10)
                    readers[1].join(WAIT_POLL / 10)
                return not any(reader.is_alive() for reader in readers)

            def text(sink: List[bytes]) -> str:
                return b"".join(sink).decode("utf-8", errors="replace")

            start = time.monotonic()
            try:
                proc.wait(timeout=timeout)
                if join(max(0.0, timeout - (time.monotonic() - start))):
                    return text(sinks[0]), text(sinks[1]), proc.returncode, False
            except subprocess.TimeoutExpired:
                pass
            _kill_tree(proc, fleet.repo)
            if not fleet.aborted.is_set():           # an abort already spent its grace in the join above
                join(KILL_GRACE)                     # still alive after this: abandoned, daemon
            return text(sinks[0]), text(sinks[1]), None, True
        finally:
            fleet.discard(proc)


def _argv(model: dict, repo: Path) -> List[str]:
    return [a.replace("{repo}", str(repo)) for a in model["argv"]]


def cell_fingerprint(model: dict, dim: dict, phase: str, repo: Path) -> str:
    """What defined a cell: dimension id, label, question; model id, kind and the full argv once
    `{repo}` is filled in; the phase. An answer is only an answer to this exact definition."""
    material = [dim["id"], dim["label"], dim["question"], model["id"], model["kind"],
                _argv(model, repo), phase]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _names(name: str) -> List[str]:
    """The file names `name` can stand for: on Windows `claude` is `claude.cmd` by PATHEXT."""
    if not _on_windows():
        return [name]
    exts = [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    return ([name] if name.lower().endswith(tuple(e.lower() for e in exts)) else []) + [name + e for e in exts]


def _runnable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _real_name(path: str) -> str:
    """`path` spelt as it is on disk. Windows finds `tool.CMD` when the file is `tool.cmd` (PATHEXT is
    upper case, names are not), and what is reported — and later compared, logged, fingerprinted — is
    the file's own name, not the spelling that happened to match."""
    folder, name = os.path.split(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return path
    if name in names:
        return path
    return next((os.path.join(folder, n) for n in names if n.lower() == name.lower()), path)


def _on_disk(path: str) -> str:
    return _real_name(path) if _on_windows() else path


def _safe_path(repo: Path) -> List[str]:
    """The PATH entries that are absolute and outside the repo — the only ones a seat or its launcher
    (`#!/usr/bin/env node`) may resolve a program from."""
    entries = (e.strip('"') for e in os.environ.get("PATH", "").split(os.pathsep))
    return [e for e in entries if e and os.path.isabs(e) and not _inside(Path(e), repo)]


def resolve_executable(name: str, repo: Path) -> Optional[str]:
    """Where `name` is, looking only at absolute PATH entries outside the repo — never the current
    directory, which `shutil.which` searches first on Windows, so the reviewed tree could otherwise
    supply `claude.cmd`. A name with a separator is taken as a path, and only an absolute one."""
    if os.sep in name or (os.altsep and os.altsep in name):
        found = next((n for n in _names(name) if os.path.isabs(n) and _runnable(n)), None)
        return _on_disk(found) if found else None
    for entry in _safe_path(repo):
        for candidate in _names(name):
            path = os.path.join(entry, candidate)
            if _runnable(path):
                return _on_disk(path)
    return None


def locate_executable(name: str, repo: Path) -> Tuple[Optional[str], Optional[str]]:
    """(path, None) or (None, why not). One function for pre-flight and `run_cell`, so the check made
    before anything is sent is the check made when it is sent."""
    found = resolve_executable(name, repo)
    if found is None:
        return None, f"executable {name!r} not found on PATH (absolute entries outside the repo only)"
    if _inside(Path(found), repo):
        return None, f"executable {name!r} is {found}, inside the repo under review; refused"
    return found, None


def run_cell(model: dict, dim: dict, phase: str, brief: str, repo: Path, out: Path,
             timeout: float, fleet: Optional[_Fleet] = None) -> dict:
    """One seat, one process. Whatever goes wrong is `unreached` with the reason, never a verdict."""
    repo_text = str(repo)
    argv = _argv(model, repo)
    resolved, refusal = locate_executable(argv[0], repo)
    if resolved:
        argv[0] = resolved
    stem = cell_stem(phase, dim["id"], model["id"])
    cells = out / "cells"
    brief_file = cells / f"{stem}.brief.txt"         # the seat's stdin, and evidence of what it was sent
    brief_file.write_bytes(brief.encode("utf-8"))    # bytes: no newline translation on Windows
    stdout = stderr = ""
    exit_code: Optional[int] = None
    reason: Optional[str] = None
    started = time.monotonic()
    if refusal:                                      # never hand the bare name to Popen: it may search the cwd
        reason = f"could not start {argv[0]!r}: {refusal}"
    else:
        try:
            stdout, stderr, exit_code, timed_out = _run_process(argv, brief_file, repo_text, timeout, fleet)
            if timed_out:
                reason = f"timed out after {timeout:g}s"
        except OSError as exc:
            reason = f"could not start {argv[0]!r}: {exc}"
    seconds = round(time.monotonic() - started, 2)

    answer = None
    if reason is None and exit_code != 0:
        reason = f"exit code {exit_code}"
    if reason is None:
        answer = extract_answer(model["kind"], stdout)
        if answer is None:
            reason = "stdout held no answer text"
    verdict = verdict_of(answer) if reason is None else None
    if reason is None and verdict is None:
        reason = "answer has no `VERDICT: pass` or `VERDICT: fail` line"

    (cells / f"{stem}.stdout.txt").write_text(stdout, encoding="utf-8")
    (cells / f"{stem}.stderr.txt").write_text(stderr, encoding="utf-8")
    return {"model": model["id"], "dimension": dim["id"], "phase": phase,
            "verdict": verdict or UNREACHED, "reason": reason, "exit_code": exit_code,
            "seconds": seconds, "usage": extract_usage(model["kind"], stdout),
            "answer": answer, "fingerprint": cell_fingerprint(model, dim, phase, repo)}


def _not_run(model: dict, dim: dict, phase: str, repo: Path, reason: str = STOPPED) -> dict:
    return {"model": model["id"], "dimension": dim["id"], "phase": phase, "verdict": UNREACHED,
            "reason": reason, "exit_code": None, "seconds": 0.0, "usage": None, "answer": None,
            "fingerprint": cell_fingerprint(model, dim, phase, repo)}


def _run_phase(jobs: int, cells: List[Tuple[dict, dict, str, str]], repo: Path, out: Path,
               timeout: float) -> Tuple[List[dict], bool]:
    """(results, interrupted). Run the cells, at most `jobs` at once. The first unreached cell stops
    the round (DIR-2): cells not yet started are cancelled and reported unreached; cells already
    running finish. Ctrl-C is harder: queued cells are cancelled and the running seats' process trees
    are killed too, and the cells come back unreached, "interrupted by the operator"."""
    fleet = _Fleet(repo)

    def job(model: dict, dim: dict, phase: str, brief: str) -> dict:
        # the worker itself raises the flag: a worker that finished the unreached cell would
        # otherwise take the next queued one before the main thread got round to cancelling it
        if fleet.stop.is_set():
            return _not_run(model, dim, phase, repo, INTERRUPTED if fleet.aborted.is_set() else STOPPED)
        cell = run_cell(model, dim, phase, brief, repo, out, timeout, fleet)
        if cell["verdict"] == UNREACHED:
            fleet.stop.set()
        return cell

    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    futures = [pool.submit(job, m, d, phase, brief) for m, d, phase, brief in cells]
    running: set = set()
    interrupted = False
    try:
        waiting = set(futures)
        stopped = False
        while waiting:
            # a bounded wait: an unbounded one cannot be interrupted by Ctrl-C on Windows (bpo-29971)
            done, waiting = wait(waiting, timeout=WAIT_POLL, return_when=FIRST_COMPLETED)
            if not stopped and any(f.result()["verdict"] == UNREACHED for f in done):
                stopped = True
                for f in waiting:
                    f.cancel()
                waiting = {f for f in waiting if not f.cancelled()}
    except KeyboardInterrupt:
        interrupted = True
        running = {f for f in futures if f.running()}
        fleet.abort()                                # first: a worker must not start a seat after the cancel
        for f in futures:
            f.cancel()
    finally:
        while True:
            try:
                pool.shutdown(wait=True)
                break
            except KeyboardInterrupt:                # a second Ctrl-C: kill again, keep waiting for the workers
                interrupted = True
                fleet.abort()
    results = []
    for future, (model, dim, phase, _brief) in zip(futures, cells):
        if future.cancelled():
            results.append(_not_run(model, dim, phase, repo, INTERRUPTED if interrupted else STOPPED))
            continue
        cell = future.result()
        if future in running and cell["verdict"] == UNREACHED:
            cell["reason"] = INTERRUPTED             # killed by the operator, not a seat's own failure
        results.append(cell)
    return results, interrupted


# ---------------------------------------------------------------------------------------- round

def _run_git(repo: Path, *args: str, guard: Optional[Path] = None) -> str:
    """git's stdout. `git` is resolved like the seats are, never by bare name: on Windows a bare name
    is searched in the current directory first, and the operator may be standing in the reviewed tree
    (a committed `git.exe` would run before anything is checked). Refused when not found."""
    exe, why = locate_executable("git", guard or repo)
    if exe is None:
        raise frozen_tree.NotAnswerable(f"could not run git: {why}")
    try:
        done = subprocess.run([exe, *args], cwd=str(repo), capture_output=True)
    except OSError as exc:
        raise frozen_tree.NotAnswerable(f"could not run git: {exc}") from None
    if done.returncode != 0:
        said = (done.stderr or done.stdout).decode("utf-8", errors="replace").strip()
        raise frozen_tree.NotAnswerable(said or "git failed")
    return done.stdout.decode("utf-8", errors="replace")


def _require_toplevel(repo: Path) -> None:
    """Seats review a whole repository, and every guard keys on `repo`: refuse a subdirectory of one.
    git is found without trusting any ancestor that is itself a checkout, as it is not yet known
    which of them is the top level."""
    guard = next((p for p in reversed([repo, *repo.parents]) if os.path.lexists(p / ".git")), repo)
    top = Path(_run_git(repo, "rev-parse", "--show-toplevel", guard=guard).strip())
    try:
        same = os.path.samefile(top, repo)
    except OSError:
        same = False
    if not same:
        raise frozen_tree.NotAnswerable(f"--repo {repo} is not the repository's top level, {top}; "
                                        "seats must review a whole repository — pass the top level")


def _freeze(repo: Path) -> Tuple[Optional[str], List[str], Optional[str]]:
    """(sha, dirty paths, why-it-could-not-be-answered). What `frozen_tree.state` answers, asked
    through `_run_git`."""
    try:
        head = _run_git(repo, "rev-parse", "HEAD").strip()
        dirty = sorted(frozen_tree._porcelain_paths(_run_git(repo, "status", "--porcelain", "-z")))
    except frozen_tree.NotAnswerable as exc:
        return None, [], str(exc)
    return head, dirty, None


def load_base_config(repo: Path, ref: str, sha: str) -> Tuple[dict, dict]:
    """(config, source) read with `git show REF:config/panel.json`: the file as the base the change is
    measured against has it, so the commit under review cannot weaken its own reviewers' controls
    (argv, system prompt, dimensions, questions). When REF is the reviewed commit, or has the same
    file as it, the source says so instead of claiming a base."""
    if not ref or ref.startswith("-"):
        raise ConfigError(f"--config-from: {ref!r} is not a ref")
    try:
        commit = _run_git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}").strip()
        text = _run_git(repo, "show", f"{commit}:{CONFIG_IN_REPO}")
    except frozen_tree.NotAnswerable as exc:
        raise ConfigError(f"--config-from {ref}: cannot read {CONFIG_IN_REPO} there: {exc} "
                          "(give --config PATH to use a file as it is)") from None
    try:
        same = _run_git(repo, "rev-parse", f"{commit}:{CONFIG_IN_REPO}") == _run_git(
            repo, "rev-parse", f"{sha}:{CONFIG_IN_REPO}")
    except frozen_tree.NotAnswerable:
        same = False
    kind, note = "base", f"config read from {ref} ({commit[:12]}), not from the reviewed tree"
    if commit == sha:
        kind, note = "reviewed-tree", f"config taken from the reviewed tree ({ref} is the commit under review)"
    elif same:
        kind, note = "reviewed-tree", f"config identical to the reviewed tree's (read from {ref}, {commit[:12]})"
    source = {"kind": kind, "ref": ref, "commit": commit, "path": CONFIG_IN_REPO,
              "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "note": note}
    return parse_config(text, f"{ref}:{CONFIG_IN_REPO}"), source


def load_explicit_config(path: Path, repo: Path) -> Tuple[dict, dict]:
    """(config, source) for `--config PATH`: the file as it is, and the report says where it was from."""
    config = load_config(path)
    inside = _inside(Path(path), repo)
    note = (f"config taken from the reviewed tree: {path} (--config); the commit under review could "
            "have changed its own reviewers' controls" if inside else
            f"config taken from --config {path}, outside the repo; not compared with any base")
    return config, {"kind": "reviewed-tree" if inside else "explicit-path", "path": str(path),
                    "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "note": note}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _closing_freeze(sha: str, end_sha: Optional[str], end_dirty: List[str],
                    end_unanswerable: Optional[str]) -> str:
    """`ok`, `dirty` (same commit, files differ) or `moved` (another commit, or it could not be told)."""
    if end_unanswerable or end_sha != sha:
        return "moved"
    return "dirty" if end_dirty else "ok"


def _load_resume(path: Path, sha: str, dims: List[dict], models: List[dict], brief_sha: str,
                 repo: Path) -> Dict[Tuple[str, str, str], dict]:
    """The cells of an earlier round that may be kept, keyed (phase, dimension, model).
    Refused unless that round saw the same commit, the same matrix and the same brief, and unless its
    closing freeze check was `ok` and it was not interrupted: a round the freeze invalidated donates no
    cell, because restoring the tree afterwards does not make what the seats read the tree they were
    told about (KN-14). A cell is kept only if it was reached (pass/fail) and its fingerprint is the
    one the current config gives it; a cell defined otherwise is run again."""
    where = Path(path) / "report.json"
    try:
        old = json.loads(where.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"--resume: cannot read {where}: {exc}") from None
    if not isinstance(old, dict):
        raise ConfigError(f"--resume: {where} is not a panel report")
    closing = old.get("closing_freeze")
    if closing != "ok" or old.get("interrupted") is not False:
        raise ConfigError(
            f"resume refused (KN-14): {path} has closing_freeze={closing!r}, interrupted="
            f"{old.get('interrupted')!r}; a round whose tree moved, or that was interrupted, did not "
            "verify a frozen tree and none of its cells may be reused")
    if old.get("sha") != sha:
        raise ConfigError(f"resume needs the same commit (KN-14): {path} was run at "
                          f"{str(old.get('sha'))[:12]}, the tree is at {sha[:12]}")
    matrix = old.get("matrix") if isinstance(old.get("matrix"), dict) else {}
    if matrix.get("dimensions") != [d["id"] for d in dims] or matrix.get("models") != [m["id"] for m in models]:
        raise ConfigError(f"resume needs the same matrix: {path} ran dimensions "
                          f"{matrix.get('dimensions')} x models {matrix.get('models')}")
    if old.get("brief_sha256") != brief_sha:
        raise ConfigError(f"resume needs the same brief: {path} was run on a different one")
    current = {(ph, d["id"], m["id"]): cell_fingerprint(m, d, ph, repo)
               for ph in ("review", "cross") for d in dims for m in models}
    return {key: c for c in old.get("cells", [])
            if isinstance(c, dict) and c.get("verdict") in (PASS, FAIL)
            for key in [(c.get("phase"), c.get("dimension"), c.get("model"))]
            if key in current and c.get("fingerprint") == current[key]}


def ignored_paths(repo: Path) -> List[str]:
    """What git ignores under the repo (directories as one entry each). A seat reads these too."""
    try:
        listed = _run_git(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                          "--directory")
    except frozen_tree.NotAnswerable as exc:
        raise ConfigError(f"cannot list git-ignored files: {exc}") from None
    return sorted(p for p in listed.split("\0") if p)


def run_round(*args: Any, **kwargs: Any) -> int:
    """`_run_round`, with the claim on --out released however it ends, an interrupt included."""
    held: List[Path] = []
    try:
        return _run_round(held, *args, **kwargs)
    finally:
        for lock in held:
            try:
                lock.rmdir()
            except OSError:
                pass


def _claim(out: Path, held: List[Path]) -> None:
    """Take `out` for this round: `.round.lock` is made exclusively (a directory), so of two rounds started on
    one directory the second is refused instead of overwriting the first's briefs."""
    out.mkdir(parents=True, exist_ok=True)
    lock = out / LOCK_NAME
    try:
        lock.mkdir()                                 # atomic: exactly one of two callers creates it
    except FileExistsError:
        raise ConfigError(f"--out {out} is claimed by a round that is running ({lock} exists); "
                          "if none is, remove that directory") from None
    held.append(lock)
    if (out / "cells").exists():
        raise ConfigError(f"--out {out} already holds a round's cells/; choose a fresh directory")


def _run_round(held: List[Path], config_path: Optional[Path], repo: Path, brief_path: Path, out: Path,
               only: Optional[List[str]] = None, jobs: int = DEFAULT_JOBS, cross_read: bool = True,
               cell_timeout: float = DEFAULT_TIMEOUT, resume: Optional[Path] = None,
               config_from: str = DEFAULT_CONFIG_FROM, allow_project_codex_config: bool = False,
               allow_repo_executables: bool = False) -> int:
    """One round. Returns the exit code; prints what it did. The config is `config_path` as it is when
    one is given, else `config/panel.json` at `config_from` — never the reviewed tree's own copy."""
    repo = Path(repo).resolve()                      # once: `{repo}` in argv and the seat's cwd must agree
    try:
        _require_toplevel(repo)
    except frozen_tree.NotAnswerable as exc:
        print(f"error: {exc}")
        return 2
    sha, dirty, unanswerable = _freeze(repo)
    if unanswerable:
        print(f"cannot tell whether the tree is frozen: {unanswerable}")
        return 2
    if dirty:
        print(f"the tree is NOT frozen at {sha[:12]} — {len(dirty)} path(s) differ from it (KN-14):")
        for path in dirty:
            print(f"  {path}")
        print("commit or stash them; nothing was run.")
        return 1

    kept: Dict[Tuple[str, str, str], dict] = {}
    try:
        if config_path is not None:
            config, config_source = load_explicit_config(config_path, repo)
        else:
            config, config_source = load_base_config(repo, config_from, sha)
        dims, models = select_matrix(config, only)
        check_stems(dims, models)
        raw_brief = Path(brief_path).read_bytes()     # bytes: the size disclosed is the file's own
        brief = raw_brief.decode("utf-8")             # no newline translation, so what is sent is what was read
        brief_sha = hashlib.sha256(raw_brief).hexdigest()
        if _inside(out, repo):
            raise ConfigError(f"--out {out} is inside the repo; writing it would dirty the frozen "
                              "tree (KN-14) — choose a directory outside it")
        if resume is not None and _inside(out, resume):
            raise ConfigError(f"--out {out} is the --resume directory or inside it: the new report would "
                              "replace the earlier round's, and an interrupted or dirty resume would leave "
                              "nothing to resume from (KN-14) — choose a fresh directory")
        if (out / "report.json").exists() or (out / "report.md").exists():
            raise ConfigError(f"--out {out} already holds a round's report; choose a fresh directory")
        ignored = ignored_paths(repo)
        if resume is not None:
            kept = _load_resume(resume, sha, dims, models, brief_sha, repo)
    except (OSError, UnicodeError) as exc:
        print(f"error: {exc}")
        return 2
    except ConfigError as exc:
        print(f"error: {exc}")
        return 2

    # a re-run seat must be an answer to this round's tree, so a cell whose dimension has a review cell
    # run again is run again too: its cross-read read answers that are being replaced
    stale = {d["id"] for d in dims for m in models if ("review", d["id"], m["id"]) not in kept}
    kept = {k: v for k, v in kept.items() if not (k[0] == "cross" and k[1] in stale)}

    unusable = [(m, why) for m in models for why in [locate_executable(_argv(m, repo)[0], repo)[1]] if why]
    if unusable:
        for m, why in unusable:
            print(f"error: model {m['id']!r}: {why}; nothing was run")
        return 3

    project_codex = [n for n in PROJECT_CODEX_CONFIG if os.path.lexists(repo / n)
                     ] if any(m["kind"] == "codex" for m in models) else []
    if project_codex and not allow_project_codex_config:   # codex has no flag that turns project config off
        print(f"error: the reviewed tree has {', '.join(project_codex)}, which codex loads as project "
              "configuration and can use to instruct its reviewer; nothing was run. Remove it from the "
              "tree, or pass --allow-project-codex-config to accept that.")
        return 3

    planted = sorted(n for n in os.listdir(repo) if n.lower() in LAUNCHER_NAMES)
    if planted and not allow_repo_executables:       # a seat's launcher may pick these up by bare name
        print(f"error: the reviewed tree's top level has {', '.join(planted)}, which a seat's launcher "
              "could run by bare name; nothing was run. Remove them from the tree, or pass "
              "--allow-repo-executables to accept that.")
        return 3

    disclosure = {"models": [{"id": m["id"], "executable": _argv(m, repo)[0],
                              "reach": m.get("reach", DEFAULT_REACH), "reads": READ_SCOPE[m["kind"]]}
                             for m in models],
                  "brief_bytes": len(raw_brief), "repo": str(repo),
                  "project_codex_config": {"present": project_codex, "allowed": allow_project_codex_config},
                  "repo_executables": {"present": planted, "allowed": allow_repo_executables},
                  "ignored_paths": ignored[:IGNORED_CAP], "ignored_more": max(0, len(ignored) - IGNORED_CAP)}
    print(config_source["note"])
    print("sending, before anything is dispatched:")
    for m in disclosure["models"]:
        print(f"  {m['id']}: {m['executable']} (reach: {m['reach']})")
        print(f"    can read: {m['reads']}")
    print(f"  the brief, {disclosure['brief_bytes']} bytes, to every seat; a cross-read adds the other "
          "seats' answers")
    print(f"  {repo} is each seat's working directory, including files git ignores")
    for line in _ignored_lines(disclosure):
        print(f"    {line}")
    sys.stdout.flush()                                # piped, the disclosure must be out before the data is

    try:
        _claim(out, held)
        (out / "cells").mkdir()
    except (OSError, ConfigError) as exc:
        print(f"error: {exc}")
        return 2
    review_n, cross_n = session_count(dims, models, cross_read)
    print(f"round at {sha[:12]}: {len(dims)} dimension(s) x {len(models)} model(s) = "
          f"{review_n} review session(s), then {cross_n} cross-read; up to {jobs} at once")
    if resume is not None:
        print(f"resuming {resume}: keeping {len(kept)} reached cell(s), re-running the rest")

    def phase(plan: List[Tuple[dict, dict, str, str]]) -> Tuple[List[dict], bool]:
        """The plan's cells in plan order: the kept ones as they were, the others run now."""
        todo = [item for item in plan if (item[2], item[1]["id"], item[0]["id"]) not in kept]
        fresh = {}
        interrupted = False
        if todo:
            ran, interrupted = _run_phase(jobs, todo, repo, out, cell_timeout)
            fresh = {(c["phase"], c["dimension"], c["model"]): c for c in ran}
        return [kept.get((i[2], i[1]["id"], i[0]["id"])) or fresh[(i[2], i[1]["id"], i[0]["id"])]
                for i in plan], interrupted

    reasons: List[str] = []
    review, interrupted = phase([(m, d, "review", review_header(m, d, sha) + brief)
                                 for d in dims for m in models])
    cells = list(review)
    unreached = [c for c in review if c["verdict"] == UNREACHED]
    disagreements: List[dict] = []
    cross: List[dict] = []
    if interrupted:
        reasons.append(INTERRUPTED)
    elif unreached:
        reasons.append(f"{len(unreached)} review cell(s) unreached — cross-read skipped")
    elif cross_n:
        by_key = {(c["dimension"], c["model"]): c["answer"] for c in review}
        plan = []
        for d in dims:
            for m in models:
                others = [(o["id"], by_key[(d["id"], o["id"])]) for o in models if o["id"] != m["id"]]
                plan.append((m, d, "cross", cross_brief(m, d, sha, brief, others)))
        cross, interrupted = phase(plan)
        cells += cross
        unreached = [c for c in cross if c["verdict"] == UNREACHED]
        if interrupted:
            reasons.append(INTERRUPTED)
        elif unreached:
            reasons.append(f"{len(unreached)} cross-read cell(s) unreached")
        for c in cross:
            for line in (c["answer"] or "").splitlines():
                if _DISAGREE.search(line):
                    disagreements.append({"dimension": c["dimension"], "model": c["model"],
                                          "line": line.strip()})

    if interrupted or any(c["verdict"] == UNREACHED for c in cells):
        result = "incomplete"
    elif all(c["verdict"] == PASS for c in cells):
        result = "pass"
    else:
        result = "fail"
    if not cross_n:                                   # DIR-3: a review nobody cross-read is not a pass
        reasons.append("cross-read skipped (--no-cross-read); DIR-3 requires it" if not cross_read else
                       "single-model config: one engine, nobody to cross-read; DIR-3 requires it")
        if result == "pass":
            result = "incomplete"
    left_out = reduced_panel(config, dims, models)
    if left_out:                                      # DIR-3: a smaller matrix than the configured one is a re-check
        reasons.append(f"reduced panel: {left_out}")
        if result == "pass":
            result = "incomplete"

    end_sha, end_dirty, end_unanswerable = _freeze(repo)
    closing = _closing_freeze(sha, end_sha, end_dirty, end_unanswerable)
    if closing != "ok":
        result = "incomplete"
        reasons.append("tree moved during the round (KN-14)" +
                       (f": {end_unanswerable}" if end_unanswerable else "") +
                       (f"; sha {sha[:12]} -> {(end_sha or '?')[:12]}" if end_sha != sha else "") +
                       (f"; differs: {', '.join(end_dirty)}" if end_dirty else ""))

    report = {"result": result, "sha": sha, "config": config_source["note"],
              "config_source": config_source, "reasons": reasons,
              "disclosure": disclosure, "brief_sha256": brief_sha,
              "closing_freeze": closing, "interrupted": interrupted,
              "resumed_from": str(resume) if resume is not None else None,
              "matrix": {"dimensions": [d["id"] for d in dims], "models": [m["id"] for m in models],
                         "review_sessions": review_n, "cross_sessions": cross_n},
              "cells": cells, "disagreements": disagreements, "usage_summary": usage_summary(cells)}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report, dims, models), encoding="utf-8")

    for c in cells:
        if c["verdict"] == UNREACHED:
            print(f"  UNREACHED {c['phase']} {c['dimension']} x {c['model']}: {c['reason']}")
    for d in disagreements:
        print(f"  DISAGREE {d['dimension']} / {d['model']}: {d['line']}")
    for why in reasons:
        print(f"  {why}")
    decide = f" — {len(disagreements)} disagreement(s) to decide" if disagreements else ""
    print(f"result: {result}{decide} — report in {out / 'report.md'}")
    if interrupted:
        return 130
    return {"pass": 0, "fail": 1}.get(result, 3)


# ---------------------------------------------------------------------------------------- report

def _reset_text(window: dict) -> Optional[str]:
    at = window.get("resets_at")
    if isinstance(at, (int, float)):
        try:
            return datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except (OverflowError, OSError, ValueError):
            return str(at)
    if at is not None:
        return str(at)
    if isinstance(window.get("resets_in_seconds"), (int, float)):
        return f"in {int(window['resets_in_seconds'])}s"
    return None


def _window_ok(window: Any) -> bool:
    return isinstance(window, dict) and isinstance(window.get("used_percent"), (int, float))


def _windows(limits: Any) -> bool:
    """Whether a `rate_limits` object carries a reading at all: at least one window with a percentage."""
    return isinstance(limits, dict) and any(_window_ok(limits.get(w)) for w in ("primary", "secondary"))


def usage_summary(cells: List[dict]) -> dict:
    """Claude spend summed; codex quota as the snapshot with the latest observation time (a quota is
    a level, not a flow, so summing it would be wrong, and cells finish in any order, so list order
    says nothing about which is newest) AMONG the cells that have a reading: a cell whose codex turn
    failed has a thread and a rollout but no rate limits, and must not displace one that does.
    remaining = 100 - used_percent."""
    claude = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cells": 0}
    codex: Dict[str, Any] = {"primary": None, "secondary": None, "cells": 0,
                             "input_tokens": 0, "output_tokens": 0}
    observed: List[Tuple[datetime, dict]] = []
    for cell in cells:
        usage = cell.get("usage")
        if not isinstance(usage, dict):
            continue
        if "total_cost_usd" in usage:
            claude["cells"] += 1
            for name, key in (("cost_usd", "total_cost_usd"), ("input_tokens", "input_tokens"),
                              ("output_tokens", "output_tokens"),
                              ("cache_read_input_tokens", "cache_read_input_tokens"),
                              ("cache_creation_input_tokens", "cache_creation_input_tokens")):
                if isinstance(usage.get(key), (int, float)):
                    claude[name] += usage[key]
        else:
            tokens, limits = usage.get("token_usage"), usage.get("rate_limits")
            if isinstance(tokens, dict):
                for name in ("input_tokens", "output_tokens"):
                    if isinstance(tokens.get(name), (int, float)):
                        codex[name] += tokens[name]
            if isinstance(tokens, dict) or isinstance(limits, dict):
                codex["cells"] += 1
            if _windows(limits):                     # a cell whose turn failed has a rollout, not a reading
                observed.append((_when(usage.get("rate_limits_at")), limits))
    if observed:                                     # the newest reading; the later cell wins a tie
        _, limits = max(enumerate(observed), key=lambda item: (item[1][0], item[0]))[1]
        for which in ("primary", "secondary"):
            window = limits.get(which)
            if _window_ok(window):
                codex[which] = {"used_percent": window["used_percent"],
                                "remaining_percent": round(100 - window["used_percent"], 2),
                                "window_minutes": window.get("window_minutes"),
                                "resets": _reset_text(window)}
    claude["cost_usd"] = round(claude["cost_usd"], 6)
    return {"claude": claude, "codex": codex}


def _ignored_lines(sent: dict) -> List[str]:
    """The git-ignored paths a seat can read, as lines; empty when there are none."""
    paths, more = sent.get("ignored_paths", []), sent.get("ignored_more", 0)
    if not paths:
        return []
    return [*paths, *([f"... and {more} more"] if more else [])]


def _table(cells: List[dict], dims: List[dict], models: List[dict], phase: str) -> List[str]:
    verdicts = {(c["dimension"], c["model"]): c["verdict"] for c in cells if c["phase"] == phase}
    lines = ["| dimension | " + " | ".join(m["id"] for m in models) + " |",
             "|---|" + "---|" * len(models)]
    for d in dims:
        row = [verdicts.get((d["id"], m["id"]), "—") for m in models]
        lines.append(f"| {d['id']} ({d['label']}) | " + " | ".join(row) + " |")
    return lines


def render_markdown(report: dict, dims: List[dict], models: List[dict]) -> str:
    cells = report["cells"]
    lines = [f"# Panel round — {report['result']}", "",
             f"- commit: `{report['sha']}`", f"- config: {report['config']}",
             f"- sessions: {report['matrix']['review_sessions']} review, "
             f"{report['matrix']['cross_sessions']} cross-read",
             f"- closing freeze check: {report.get('closing_freeze', 'unknown')}", ""]
    for why in report["reasons"]:
        lines.append(f"- **{why}**")
    sent = report["disclosure"]
    if report.get("resumed_from"):
        lines.insert(4, f"- resumed from `{report['resumed_from']}`: its pass/fail cells were kept")
    lines += ["", "## What was sent, and to whom", ""]
    for m in sent["models"]:
        lines += [f"- {m['id']}: `{m['executable']}`, reach: {m['reach']}"]
        if m.get("reads"):
            lines.append(f"  - can read: {m['reads']}")
    lines += [f"- the brief, {sent['brief_bytes']} bytes, to every seat (a cross-read adds the other "
              "seats' answers)",
              f"- `{sent['repo']}` is each seat's working directory, including files git ignores"]
    lines += [f"  - `{p}`" if not p.startswith("...") else f"  - {p}" for p in _ignored_lines(sent)]
    lines += ["", "## Review", ""] + _table(cells, dims, models, "review")
    if any(c["phase"] == "cross" for c in cells):
        lines += ["", "## Cross-read", ""] + _table(cells, dims, models, "cross")
    lines += ["", "## Unreached", ""]
    unreached = [c for c in cells if c["verdict"] == UNREACHED]
    lines += [f"- {c['phase']} {c['dimension']} x {c['model']}: {c['reason']}" for c in unreached] or ["none"]
    lines += ["", "## Disagreements (escalated, not averaged)", ""]
    lines += [f"- {d['dimension']} / {d['model']}: {d['line']}" for d in report["disagreements"]] or ["none"]
    usage = report["usage_summary"]
    c, x = usage["claude"], usage["codex"]
    lines += ["", "## Usage", "",
              f"- claude ({c['cells']} cell(s)): ${c['cost_usd']}, {c['input_tokens']} in / "
              f"{c['output_tokens']} out, cache {c['cache_read_input_tokens']} read / "
              f"{c['cache_creation_input_tokens']} created"]
    lines.append(f"- codex ({x['cells']} cell(s)): {x['input_tokens']} in / {x['output_tokens']} out")
    for which in ("primary", "secondary"):
        w = x[which]
        if w:
            lines.append(f"- codex {which}: {w['used_percent']}% used, **{w['remaining_percent']}% remaining**, "
                         f"window {w['window_minutes']} min, resets {w['resets'] or 'unknown'}")
        else:
            lines.append(f"- codex {which}: not reported")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------------------------- CLI

RUN_EPILOG = """\
Ctrl-C stops the round: queued sessions are not started, running seats are killed, report.json and
report.md are still written (incomplete, "interrupted by the operator"), exit 130.

A round too big for one quota window: run it again with --resume DIR, DIR being the --out of the
earlier one, with a fresh --out (never DIR or inside it: the earlier report is kept). Cells that said pass or fail are kept if the config still defines them the same way;
the rest run again. A different commit is refused (KN-14), as is a different matrix or brief, and a
round that was interrupted or whose tree moved at the close.
"""


def _list(config_path: Path) -> int:
    try:
        config = load_config(config_path)
        dims, models = select_matrix(config, None)
    except ConfigError as exc:
        print(f"error: {exc}")
        return 2
    print(f"models: {', '.join(m['id'] for m in models)}")
    print("dimensions (enabled):")
    for d in dims:
        print(f"  {d['id']:<14} {d['label']}  — {d['question']}")
    off = [d["id"] for d in config["dimensions"] if not d["enabled"]]
    if off:
        print(f"disabled (ask with --only-dimensions): {', '.join(off)}")
    review, cross = session_count(dims, models, True)
    print(f"a round opens {review} review + {cross} cross-read = {review + cross} sessions")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):           # labels are Traditional Chinese; a cp1252 console must not crash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the review matrix", epilog=RUN_EPILOG,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    run.add_argument("--brief", required=True, metavar="BRIEF.md")
    run.add_argument("--out", required=True, metavar="DIR", help="outside the repo")
    run.add_argument("--config", default=None, metavar="PATH",
                     help="use this file as it is; the report says it was not taken from the base "
                          "(default: config/panel.json at --config-from)")
    run.add_argument("--config-from", default=None, metavar="REF",
                     help=f"read config/panel.json from this git ref, not the checked-out tree "
                          f"(default: {DEFAULT_CONFIG_FROM})")
    run.add_argument("--repo", default=".", metavar="PATH")
    run.add_argument("--only-dimensions", default=None, metavar="a,b",
                     help="run exactly these dimensions, disabled ones included; a reduced panel "
                          "can never pass (exit 3)")
    run.add_argument("--resume", default=None, metavar="DIR",
                     help="an earlier round's --out: keep its pass/fail cells, re-run only the "
                          "unreached ones (same commit, matrix and brief required)")
    run.add_argument("--allow-project-codex-config", action="store_true",
                     help="run codex seats although the reviewed tree has a .codex/ they would load "
                          "(the report records it)")
    run.add_argument("--allow-repo-executables", action="store_true",
                     help="run although the reviewed tree's top level has a program a seat could "
                          "pick up by bare name, e.g. node.exe (the report records it)")
    run.add_argument("--jobs", type=int, default=DEFAULT_JOBS, metavar="N")
    run.add_argument("--cross-read", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--cell-timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SECONDS")
    lst = sub.add_parser("list", help="print the matrix a round would run")
    lst.add_argument("--config", default=str(DEFAULT_CONFIG), metavar="PATH")
    args = parser.parse_args(argv)

    if args.command == "list":
        return _list(Path(args.config))
    if args.config is not None and args.config_from is not None:
        print("error: --config and --config-from are alternatives: one file, or one ref")
        return 2
    only = None
    if args.only_dimensions is not None:
        only = [n.strip() for n in args.only_dimensions.split(",") if n.strip()]
    return run_round(Path(args.config) if args.config is not None else None, Path(args.repo), Path(args.brief),
                     Path(args.out), only=only, jobs=args.jobs, cross_read=args.cross_read,
                     cell_timeout=args.cell_timeout, allow_project_codex_config=args.allow_project_codex_config,
                     allow_repo_executables=args.allow_repo_executables,
                     resume=Path(args.resume) if args.resume else None,
                     config_from=DEFAULT_CONFIG_FROM if args.config_from is None else args.config_from)


if __name__ == "__main__":
    sys.exit(main())
