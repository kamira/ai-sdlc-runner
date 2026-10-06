"""What an ask used and what quota the backend says remains (CHG-20261006-01).

Read from what the backend itself printed, never estimated. A backend that prints nothing usable is
recorded as ``unreported`` with ``None`` fields, never as zero: a zero reads afterwards as "this ask
was free", and the runner has no way to know that (KN-15: unknown is not safe).

Nothing here may affect an answer, a verdict or routing, so every function returns a record and none
raises on malformed input — a reply the parser cannot read is the ordinary case for a stub or an
``ollama run`` wrapper, not an error.

The one read outside the runner's own files is codex's local session log, and only for the thread id
the runner was just handed on stdout. Scanning for the newest log instead could read another
program's session, so the thread id is validated before it ever reaches a glob.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import paths

UNREPORTED_NOTE = "the backend did not report usage"
#: A real codex thread id is a UUID. Anything outside this set (`*`, `/`, `..`) would turn the glob
#: into a search of somebody else's sessions, so it is refused rather than escaped.
_THREAD_ID = re.compile(r"[0-9A-Za-z-]+")
_WINDOWS = ("primary", "secondary")
_TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")


def _unreported(note: str = UNREPORTED_NOTE) -> dict:
    return {"kind": "unreported", "cost_usd": None, "tokens": None, "remaining": [], "note": note}


def _number(value) -> Optional[float]:
    """A JSON number, or None. `bool` is an int in Python and is not a quantity."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _count(value) -> Optional[int]:
    number = _number(value)
    if number is None or number < 0 or number != int(number):
        return None
    return int(number)


def _parse_iso(text) -> Optional[datetime]:
    """An ISO-8601 stamp as an aware datetime, or None. 3.9's `fromisoformat` refuses a `Z`."""
    if not isinstance(text, str) or not text:
        return None
    try:
        when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def _epoch_iso(value) -> Optional[str]:
    seconds = _number(value)
    if seconds is None:
        return None
    try:
        return _iso(datetime.fromtimestamp(seconds, tz=timezone.utc))
    except (OverflowError, OSError, ValueError):
        return None


def _claude(parsed: dict) -> Optional[dict]:
    cost = _number(parsed.get("total_cost_usd"))
    used = parsed.get("usage")
    if cost is None and not isinstance(used, dict):
        return None
    tokens = None
    if isinstance(used, dict):
        given_in, given_out = _count(used.get("input_tokens")), _count(used.get("output_tokens"))
        if given_in is not None and given_out is not None:
            # The CLI leaves the cache keys out when nothing was cached, so absent means none here;
            # input and output are required, because without them the ask's size is unknown.
            tokens = {"input": given_in, "output": given_out,
                      "cache_read": _count(used.get("cache_read_input_tokens")) or 0,
                      "cache_write": _count(used.get("cache_creation_input_tokens")) or 0}
    return {"kind": "claude", "cost_usd": cost, "tokens": tokens, "remaining": [],
            "note": "cost is the API-equivalent figure the CLI prints, not a bill on a subscription; "
                    "this backend reports no remaining quota"}


def _codex_events(stdout: str) -> List[dict]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _windows(limits: dict, as_of: Optional[str], now: float) -> List[dict]:
    windows = []
    for name in _WINDOWS:
        entry = limits.get(name)
        if not isinstance(entry, dict):
            continue
        used = _number(entry.get("used_percent"))
        if used is None:
            continue
        resets = _epoch_iso(entry.get("resets_at"))
        reset_at = _number(entry.get("resets_at"))
        minutes = _count(entry.get("window_minutes"))
        windows.append({
            "window": name, "window_minutes": minutes, "used_percent": used,
            "remaining_percent": max(0.0, 100.0 - used), "resets_at": resets, "as_of": as_of,
            # A window past its reset says nothing about the new one: the old percentage must not
            # be shown as current. No `resets_at` means no claim either way, so it is not stale.
            "stale": bool(resets is not None and reset_at is not None and reset_at < now)})
    return windows


def _session_log(codex_home: Path, thread_id: str) -> Optional[Path]:
    if not _THREAD_ID.fullmatch(thread_id):
        return None
    try:
        found = sorted((codex_home / "sessions").glob(f"*/*/*/rollout-*-{thread_id}.jsonl"))
    except OSError:
        return None
    # Only a file ending in this exact id: `rollout-*-<id>` also matches `rollout-x-zz-<id>`, which
    # is still this thread's, but never a different id that merely ends the same way.
    found = [p for p in found if p.name.endswith("-" + thread_id + ".jsonl")]
    return found[-1] if found else None


def _remaining(codex_home: Path, thread_id: Optional[str], now: float):
    """The last non-null `rate_limits` in this thread's log, as (windows, why-not)."""
    if not thread_id:
        return [], "no thread id in the reply, so no session log to read"
    if not _THREAD_ID.fullmatch(thread_id):
        return [], "the thread id was not a plain id, so no session log was read"
    path = _session_log(codex_home, thread_id)
    if path is None:
        return [], "no session log found for this thread; remaining quota unknown"
    last, stamp = None, None
    try:
        with paths.open_(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "rate_limits" not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                payload = event.get("payload") if isinstance(event, dict) else None
                limits = payload.get("rate_limits") if isinstance(payload, dict) else None
                if isinstance(limits, dict):
                    last, stamp = limits, event.get("timestamp")
    except OSError:
        return [], "the session log could not be read; remaining quota unknown"
    if last is None:
        return [], "the session log carries no rate limits; remaining quota unknown"
    when = _parse_iso(stamp)
    windows = _windows(last, _iso(when) if when else None, now)
    if not windows:
        return [], "the session log's rate limits had no readable window; remaining quota unknown"
    return windows, ""


def _codex(events: List[dict], codex_home: Path, now: float) -> Optional[dict]:
    thread_id, usage = None, None
    seen = False
    for event in events:
        kind = event.get("type")
        if kind == "thread.started":
            seen = True
            if isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
        elif kind == "turn.completed":
            seen = True
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
    if not seen:
        return None
    tokens = None
    if usage is not None:
        given_in, given_out = _count(usage.get("input_tokens")), _count(usage.get("output_tokens"))
        if given_in is not None and given_out is not None:
            tokens = {"input": given_in, "output": given_out,
                      "cache_read": _count(usage.get("cached_input_tokens")) or 0,
                      "cache_write": 0}
    windows, why = _remaining(codex_home, thread_id, now)
    return {"kind": "codex", "cost_usd": None, "tokens": tokens, "remaining": windows,
            "note": why or "codex reports no cost; remaining quota is from its local session log"}


def from_reply(stdout: str, codex_home: Optional[Path] = None, now: Optional[float] = None) -> dict:
    """One ask's usage record from what the backend printed. Never raises."""
    try:
        text = stdout if isinstance(stdout, str) else ""
        stripped = text.strip()
        when = time.time() if now is None else now
        home = Path(codex_home) if codex_home is not None else Path.home() / ".codex"
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                record = _claude(parsed)
                if record is not None:
                    return record
        record = _codex(_codex_events(text), home, when) if stripped else None
        return record if record is not None else _unreported()
    except Exception:          # noqa: BLE001 - reporting must never touch the answer
        return _unreported()


def unwrap(stdout: str) -> Optional[Tuple[str, bool]]:
    """`(text, is_error)` when `stdout` is a claude or codex JSON envelope, else None.

    With the json output flags, which is what makes those CLIs print usage at all, the agent's own
    answer is no longer stdout: it is the string in claude's ``result`` or in codex's last
    ``agent_message``. Recognised narrowly: an agent's own JSON that is not exactly one of these
    shapes is its answer, and is left alone. Never raises.
    """
    try:
        text = stdout if isinstance(stdout, str) else ""
        stripped = text.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                parsed = None
            if (isinstance(parsed, dict) and parsed.get("type") == "result"
                    and isinstance(parsed.get("result"), str)):
                return parsed["result"], parsed.get("is_error") is True
        events = _codex_events(text)
        if any(e.get("type") == "thread.started" for e in events):
            said = [e["item"]["text"] for e in events
                    if e.get("type") == "item.completed" and isinstance(e.get("item"), dict)
                    and e["item"].get("type") == "agent_message"
                    and isinstance(e["item"].get("text"), str)]
            if said:
                return said[-1], False
    except Exception:          # noqa: BLE001 - recognising an envelope must never touch the answer
        pass
    return None


def _later(a: Optional[str], b: Optional[str]) -> bool:
    """Is reading `a` at least as recent as `b`? An undated reading loses to a dated one."""
    when_a, when_b = _parse_iso(a), _parse_iso(b)
    if when_b is None:
        return True
    return when_a is not None and when_a >= when_b


def summarize(records: list) -> dict:
    """Per model: asks, cost, tokens; and the latest reading of each remaining window.

    A sum is ``None`` when no ask of that model reported the figure, so "nobody said" never shows
    as a total of zero.
    """
    models: Dict[str, dict] = {}
    latest: Dict[str, dict] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        model = str(record.get("model") or "(default backend)")
        row = models.setdefault(model, {"asks": 0, "cost_usd": None, "tokens": None,
                                        "asks_unreported": 0})
        row["asks"] += 1
        if record.get("kind") == "unreported":
            row["asks_unreported"] += 1
        cost = _number(record.get("cost_usd"))
        if cost is not None:
            row["cost_usd"] = round((row["cost_usd"] or 0.0) + cost, 6)
        tokens = record.get("tokens")
        if isinstance(tokens, dict):
            if row["tokens"] is None:
                row["tokens"] = {key: 0 for key in _TOKEN_KEYS}
            for key in _TOKEN_KEYS:
                row["tokens"][key] += _count(tokens.get(key)) or 0
        for window in record.get("remaining") or []:
            if not isinstance(window, dict) or window.get("window") not in _WINDOWS:
                continue
            held = latest.get(window["window"])
            if held is None or _later(window.get("as_of"), held.get("as_of")):
                latest[window["window"]] = {"model": model, **window}
    return {"models": models, "remaining": [latest[n] for n in _WINDOWS if n in latest]}
