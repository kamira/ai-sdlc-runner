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
* **A disagreement is escalated, never averaged (DIR-2).** Cross-read DISAGREE lines are collected
  and reported as they were said.
* **Seats are read-only and separate (KN-7).** Each cell is its own process, brief on stdin, run
  from the repo root; the argv in `config/panel.json` is what removes the seat's write tools.

Usage::

    python tools/panel.py list
    python tools/panel.py run --brief BRIEF.md --out DIR [--only-dimensions defect,risk] [--jobs 6]

Exit codes: 0 pass; 1 fail, or the tree is not frozen; 2 bad configuration or arguments; 3 the round
is incomplete (a seat unreached, or the tree moved) — never a pass.

**Interpreted:** `--out` must be outside the repo. Raw seat output written inside it would itself
dirty the tree the round is verifying, and the end-of-round freeze check would fail every round.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import frozen_tree  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "panel.json"
DEFAULT_TIMEOUT = 1800
DEFAULT_JOBS = 6

KINDS = ("claude", "codex")
_TOP_KEYS = {"models", "coder", "dimensions"}
_MODEL_KEYS = {"id", "argv", "kind"}
_CODER_KEYS = {"model", "effort"}
_DIMENSION_KEYS = {"id", "label", "question", "enabled"}

PASS, FAIL, UNREACHED = "pass", "fail", "unreached"
_VERDICT_LINE = re.compile(r"^VERDICT: (pass|fail)$")
_DISAGREE = re.compile(r"\bDISAGREE\b")
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


def load_config(path: Path) -> dict:
    """The panel's data, checked. Closed key sets: a misspelt key is an error, not a silent default —
    a dimension whose `enabled` was mistyped must not quietly stop being asked."""
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    _closed(config, _TOP_KEYS, "config")
    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise ConfigError("config: 'models' must be a list with at least one model")
    seen = set()
    for index, model in enumerate(models):
        where = f"models[{index}]"
        _closed(model, _MODEL_KEYS, where)
        mid = _text(model, "id", where)
        if mid in seen:
            raise ConfigError(f"{where}: duplicate model id {mid!r}")
        seen.add(mid)
        argv = model.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ConfigError(f"{where}: 'argv' must be a non-empty list of strings")
        if model.get("kind") not in KINDS:
            raise ConfigError(f"{where}: 'kind' must be one of {list(KINDS)}, not {model.get('kind')!r}")
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
        "contains that word, with your reason. This is read only — verify against the repository, "
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
    """`pass`/`fail` from the LAST exact `VERDICT: ...` line, else None. A seat that changed its mind
    mid-answer is held to the last thing it said; a line like `VERDICT: ok` is not a verdict."""
    found = None
    for line in (text or "").splitlines():
        hit = _VERDICT_LINE.match(line.strip())
        if hit:
            found = hit.group(1)
    return found


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
    is the last `item.completed` whose `item` is an `agent_message` (codex-cli 0.158.0); the event
    shape has moved between releases, so this also takes an `item`/`msg` of an agent-message type
    with a string `text` or `message`, and falls back to raw stdout when it finds none.
    """
    if kind == "claude":
        data = _claude_json(stdout)
        result = data.get("result") if data else None
        return result if isinstance(result, str) else None
    last = None
    for event in _events(stdout):
        if not isinstance(event, dict):
            continue
        for key in ("item", "msg"):
            inner = event.get(key)
            if isinstance(inner, dict) and inner.get("type") in _AGENT_MESSAGE_TYPES:
                for field in ("text", "message"):
                    if isinstance(inner.get(field), str):
                        last = inner[field]
                        break
    return last if last is not None else stdout


def codex_home(override: Optional[Path] = None) -> Path:
    """Where codex keeps its session logs: the argument, else `$CODEX_HOME`, else `~/.codex`."""
    if override is not None:
        return Path(override)
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _rollout_rate_limits(home: Path, thread_id: str) -> Optional[dict]:
    """The LAST `rate_limits` object in this thread's rollout file, else None.

    codex never prints rate limits on stdout; they are only in `sessions/YYYY/MM/DD/rollout-<ts>-
    <thread_id>.jsonl`. The file is matched by the id it ends with, so another thread's rollout —
    a concurrent seat's — is never read as this one's.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", thread_id):     # it goes into a glob; no metacharacters
        return None
    rate = None
    for path in sorted((home / "sessions").glob(f"**/*-{thread_id}.jsonl")):
        for event in _events(path.read_text(encoding="utf-8", errors="replace")):
            found = _last_key(event, "rate_limits")
            rate = found if isinstance(found, dict) else rate
    return rate


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
            rate = None
            if thread_id:
                try:
                    rate = _rollout_rate_limits(codex_home(home), thread_id)
                except OSError:
                    rate = None
            usage = {"rate_limits": rate, "token_usage": tokens}
        return usage if any(v is not None for v in usage.values()) else None
    except Exception:                                # noqa: BLE001 — best effort by contract
        return None


# ------------------------------------------------------------------------------------------ cells

def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def run_cell(model: dict, dim: dict, phase: str, brief: str, repo: Path, out: Path,
             timeout: float) -> dict:
    """One seat, one process. Whatever goes wrong is `unreached` with the reason, never a verdict."""
    repo_text = str(repo)
    argv = [a.replace("{repo}", repo_text) for a in model["argv"]]
    resolved = shutil.which(argv[0])                 # on Windows `claude` is claude.cmd
    if resolved:
        argv[0] = resolved
    stdout = stderr = ""
    exit_code: Optional[int] = None
    reason: Optional[str] = None
    started = time.monotonic()
    try:
        done = subprocess.run(argv, input=brief, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=repo_text, timeout=timeout)
        stdout, stderr, exit_code = done.stdout or "", done.stderr or "", done.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
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

    stem = f"{phase}__{_safe(dim['id'])}__{_safe(model['id'])}"
    cells = out / "cells"
    (cells / f"{stem}.stdout.txt").write_text(stdout, encoding="utf-8")
    (cells / f"{stem}.stderr.txt").write_text(stderr, encoding="utf-8")
    return {"model": model["id"], "dimension": dim["id"], "phase": phase,
            "verdict": verdict or UNREACHED, "reason": reason, "exit_code": exit_code,
            "seconds": seconds, "usage": extract_usage(model["kind"], stdout),
            "answer": answer}


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _run_phase(jobs: int, cells: List[Tuple[dict, dict, str, str]], repo: Path, out: Path,
               timeout: float) -> List[dict]:
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [pool.submit(run_cell, m, d, phase, brief, repo, out, timeout)
                   for m, d, phase, brief in cells]
        return [f.result() for f in futures]


# ---------------------------------------------------------------------------------------- round

def _freeze(repo: Path) -> Tuple[Optional[str], List[str], Optional[str]]:
    """(sha, dirty paths, why-it-could-not-be-answered)."""
    try:
        head, dirty = frozen_tree.state(repo)
    except frozen_tree.NotAnswerable as exc:
        return None, [], str(exc)
    return head, dirty, None


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def run_round(config_path: Path, repo: Path, brief_path: Path, out: Path,
              only: Optional[List[str]] = None, jobs: int = DEFAULT_JOBS, cross_read: bool = True,
              cell_timeout: float = DEFAULT_TIMEOUT) -> int:
    """One round. Returns the exit code; prints what it did."""
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

    try:
        config = load_config(config_path)
        dims, models = select_matrix(config, only)
        brief = Path(brief_path).read_text(encoding="utf-8")
        if _inside(out, repo):
            raise ConfigError(f"--out {out} is inside the repo; writing it would dirty the frozen "
                              "tree (KN-14) — choose a directory outside it")
    except OSError as exc:
        print(f"error: {exc}")
        return 2
    except ConfigError as exc:
        print(f"error: {exc}")
        return 2

    out.mkdir(parents=True, exist_ok=True)
    (out / "cells").mkdir(exist_ok=True)
    review_n, cross_n = session_count(dims, models, cross_read)
    print(f"round at {sha[:12]}: {len(dims)} dimension(s) x {len(models)} model(s) = "
          f"{review_n} review session(s), then {cross_n} cross-read; up to {jobs} at once")

    reasons: List[str] = []
    review = _run_phase(jobs, [(m, d, "review", review_header(m, d, sha) + brief)
                               for d in dims for m in models], repo, out, cell_timeout)
    cells = list(review)
    unreached = [c for c in review if c["verdict"] == UNREACHED]
    disagreements: List[dict] = []
    cross: List[dict] = []
    if unreached:
        reasons.append(f"{len(unreached)} review cell(s) unreached — cross-read skipped")
    elif cross_n:
        by_key = {(c["dimension"], c["model"]): c["answer"] for c in review}
        plan = []
        for d in dims:
            for m in models:
                others = [(o["id"], by_key[(d["id"], o["id"])]) for o in models if o["id"] != m["id"]]
                plan.append((m, d, "cross", cross_brief(m, d, sha, brief, others)))
        cross = _run_phase(jobs, plan, repo, out, cell_timeout)
        cells += cross
        unreached = [c for c in cross if c["verdict"] == UNREACHED]
        if unreached:
            reasons.append(f"{len(unreached)} cross-read cell(s) unreached")
        for c in cross:
            for line in (c["answer"] or "").splitlines():
                if _DISAGREE.search(line):
                    disagreements.append({"dimension": c["dimension"], "model": c["model"],
                                          "line": line.strip()})

    if any(c["verdict"] == UNREACHED for c in cells):
        result = "incomplete"
    elif all(c["verdict"] == PASS for c in cells):
        result = "pass"
    else:
        result = "fail"

    end_sha, end_dirty, end_unanswerable = _freeze(repo)
    if end_unanswerable or end_dirty or end_sha != sha:
        result = "incomplete"
        reasons.append("tree moved during the round (KN-14)" +
                       (f": {end_unanswerable}" if end_unanswerable else "") +
                       (f"; sha {sha[:12]} -> {(end_sha or '?')[:12]}" if end_sha != sha else "") +
                       (f"; differs: {', '.join(end_dirty)}" if end_dirty else ""))

    report = {"result": result, "sha": sha, "config": str(config_path), "reasons": reasons,
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
    print(f"result: {result} — report in {out / 'report.md'}")
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


def usage_summary(cells: List[dict]) -> dict:
    """Claude spend summed; codex quota as the latest cell reported it (a quota is a level, not a
    flow, so summing it would be wrong). remaining = 100 - used_percent."""
    claude = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cells": 0}
    codex: Dict[str, Any] = {"primary": None, "secondary": None, "cells": 0,
                             "input_tokens": 0, "output_tokens": 0}
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
            if isinstance(limits, dict):
                for which in ("primary", "secondary"):
                    window = limits.get(which)
                    if isinstance(window, dict) and isinstance(window.get("used_percent"), (int, float)):
                        codex[which] = {"used_percent": window["used_percent"],
                                        "remaining_percent": round(100 - window["used_percent"], 2),
                                        "window_minutes": window.get("window_minutes"),
                                        "resets": _reset_text(window)}
    claude["cost_usd"] = round(claude["cost_usd"], 6)
    return {"claude": claude, "codex": codex}


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
             f"- commit: `{report['sha']}`", f"- config: `{report['config']}`",
             f"- sessions: {report['matrix']['review_sessions']} review, "
             f"{report['matrix']['cross_sessions']} cross-read", ""]
    for why in report["reasons"]:
        lines.append(f"- **{why}**")
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
    run = sub.add_parser("run", help="run the review matrix")
    run.add_argument("--brief", required=True, metavar="BRIEF.md")
    run.add_argument("--out", required=True, metavar="DIR", help="outside the repo")
    run.add_argument("--config", default=str(DEFAULT_CONFIG), metavar="PATH")
    run.add_argument("--repo", default=".", metavar="PATH")
    run.add_argument("--only-dimensions", default=None, metavar="a,b",
                     help="run exactly these dimensions, disabled ones included")
    run.add_argument("--jobs", type=int, default=DEFAULT_JOBS, metavar="N")
    run.add_argument("--cross-read", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--cell-timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SECONDS")
    lst = sub.add_parser("list", help="print the matrix a round would run")
    lst.add_argument("--config", default=str(DEFAULT_CONFIG), metavar="PATH")
    args = parser.parse_args(argv)

    if args.command == "list":
        return _list(Path(args.config))
    only = None
    if args.only_dimensions is not None:
        only = [n.strip() for n in args.only_dimensions.split(",") if n.strip()]
    return run_round(Path(args.config), Path(args.repo), Path(args.brief), Path(args.out), only=only,
                     jobs=args.jobs, cross_read=args.cross_read, cell_timeout=args.cell_timeout)


if __name__ == "__main__":
    sys.exit(main())
