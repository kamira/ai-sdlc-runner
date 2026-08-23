"""server.py — the back end for the operator console. **Local only, and it means it.**

CHG-20260823-11 tasks 10, 14, 15 and 16. One project, one runner, one machine.

## "Local only" is a threat model, not a bind address

Binding to `127.0.0.1` stops the network reaching this server. It does **not** stop a browser: any
page the operator visits can issue requests to `http://127.0.0.1:<port>`, and if the port is guessed
or scanned, a page they did not write gets to drive a runner that merges branches. Two more things
are therefore required, and neither is optional:

* **A token on every request.** Minted at startup, written to a file only the owner can read. A
  cross-origin page can *send* a request, but it cannot *read* a file on disk, so it cannot produce
  the header. This is what makes "whoever can read the file is the operator" a true statement rather
  than a hopeful one — and it is task 15's server-issued credential: the identity is **derived** from
  what the caller proves it can read, never taken from a name in the request body.
* **A `Host` check.** DNS rebinding turns an attacker's hostname into `127.0.0.1` after the page has
  loaded, so the socket is local while the origin is not. Requests whose `Host` is not a loopback
  name are refused before anything else happens.

`Origin` is checked too, but it is the weakest of the three and is treated that way: it is a header
the client chooses.

## Nothing waits inside the walk

The engine's guarantee from task 1 is that a stop is a **return**. This server keeps it: it runs a
walk to completion on a worker thread, and a walk that suspends comes *back* with a report saying so.
The waiting happens here, in a server that is designed to wait, and never inside the flow.

## One run, one version

Every state change bumps a version, and every mutating request must name the version it was answering
(task 16). Two browsers, a double-click, and a tab left open since yesterday all become the same
refusal: *you are answering a state this run has moved past*. Without it, the second click of a
double-click spends a second approval — which is the "advance twice" an independent seat named.
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from . import engine, graph, models as models_mod, policy

#: The only addresses this server will bind. Not a default — a rule. A runner that can merge
#: branches has no business listening where anything but this machine can reach it, and making that
#: configurable would turn a decision somebody argued about into a flag somebody flips.
LOOPBACK = ("127.0.0.1", "::1", "localhost")

#: `Host` values a loopback request can legitimately carry. Anything else is a rebinding attempt or
#: a proxy, and both are reasons to refuse rather than to guess.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

IDLE = "idle"


class ServerError(Exception):
    """Refused. Never softened into a partial success."""


def _loopback_host(header: Optional[str]) -> bool:
    """Is this ``Host`` header one of ours? Port stripped, IPv6 brackets kept."""
    if not header:
        return False
    host = header.strip()
    if host.startswith("["):                       # [::1]:8765
        host = host.split("]")[0] + "]"
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host.lower() in LOOPBACK_HOSTS


@dataclass
class Operator:
    """Who the server will accept answers from, and how it knows.

    Task 15 asked for a server-issued credential rather than a name in a request body, and gave the
    reason: a submitted name is the button captioned "Accept (as verifier)" moved one layer down and
    called enforcement. Here the identity is what the caller **proved** — it held the token — and
    the label is the OS user the server runs as, which the caller cannot choose.
    """

    token: str
    name: str
    token_path: Path

    @classmethod
    def mint(cls, directory: Path) -> "Operator":
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "operator.token"
        token = secrets.token_urlsafe(32)
        path.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:                            # pragma: no cover - filesystems without modes
            pass
        name = os.environ.get("USER") or os.environ.get("USERNAME") or "operator"
        return cls(token=token, name=name, token_path=path)

    def accepts(self, presented: Optional[str]) -> bool:
        # Constant-time: the token is short and local, but a comparison that leaks its prefix is
        # free to avoid and awkward to explain afterwards.
        return bool(presented) and secrets.compare_digest(presented, self.token)


@dataclass
class RunState:
    """Everything a reconnecting browser needs to rebuild the view (task 14).

    Task 10's done-when was "a reload mid-run rebuilds the view", and an independent seat pointed out
    the endpoint list had only an event stream behind it — a browser that missed the event announcing
    the stop had no way to ask. So the snapshot is the primary source and the stream is the
    optimisation, not the other way round.
    """

    state: str = IDLE
    version: int = 0
    instruction: str = ""
    report: Optional[engine.RunReport] = None
    #: Answers accumulated across suspensions. A resumed walk replays from `intake` carrying these,
    #: which is why they are kept rather than applied and forgotten.
    approvals: List[engine.Approval] = field(default_factory=list)
    rulings: List[engine.Ruling] = field(default_factory=list)
    log: List[Dict[str, object]] = field(default_factory=list)
    error: str = ""

    def snapshot(self) -> Dict[str, object]:
        report = self.report
        return {
            "state": self.state,
            "version": self.version,
            "instruction": self.instruction,
            "error": self.error,
            "at": report.halted_at if report else None,
            "reason": report.halt_reason if report else "",
            "visited": list(report.visited) if report else [],
            "suspended": dict(report.suspended) if report and report.suspended else None,
            "confirmations": list(report.confirmations) if report else [],
            "rulings": list(report.rulings) if report else [],
            "adjudications": [dict(a) for a in report.adjudications] if report else [],
            "log": list(self.log),
        }


class Runner:
    """Owns the one run. Every state change bumps the version and wakes the listeners."""

    def __init__(self, walk: Callable[..., engine.RunReport], make_config: Callable[[str], object]):
        self._walk = walk
        self._make_config = make_config
        self._lock = threading.RLock()
        self._listeners: List["queue.Queue[str]"] = []
        self.state = RunState()

    # --- listeners -------------------------------------------------------------------------
    def listen(self) -> "queue.Queue[str]":
        q: "queue.Queue[str]" = queue.Queue()
        with self._lock:
            self._listeners.append(q)
        return q

    def unlisten(self, q: "queue.Queue[str]") -> None:
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def _publish(self) -> None:
        payload = json.dumps(self.state.snapshot(), ensure_ascii=False)
        for q in list(self._listeners):
            q.put(payload)

    # --- the run ---------------------------------------------------------------------------
    def start(self, instruction: str, version: int) -> Dict[str, object]:
        with self._lock:
            self._require_version(version)
            if self.state.state not in (IDLE, engine.FINISHED, engine.STOPPED):
                raise ServerError(
                    f"a run is already {self.state.state}; one project, one runner, one run at a "
                    f"time. Answer or abandon the one in front of you first.")
            self.state = RunState(state="running", version=self.state.version + 1,
                                  instruction=instruction)
            self._publish()
        return self._advance()

    def approve(self, version: int, gate: str, node_id: Optional[str]) -> Dict[str, object]:
        with self._lock:
            self._require_version(version)
            self._require_suspension(undecided=False)
            self.state.approvals.append(
                engine.Approval(gate=gate, node_id=node_id))
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        return self._advance()

    def rule(self, version: int, node_id: str, branch: str) -> Dict[str, object]:
        with self._lock:
            self._require_version(version)
            self._require_suspension(undecided=True)
            self.state.rulings.append(engine.Ruling(node_id=node_id, branch=branch))
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        return self._advance()

    def _require_version(self, version: int) -> None:
        """Task 16. The refusal that turns a double-click into an error instead of two approvals."""
        if version != self.state.version:
            raise ServerError(
                f"this run is at version {self.state.version} and you answered version {version}. "
                f"Something moved — another tab, or a click that already landed. Reload and look at "
                f"what it is actually waiting for before answering again.")

    def _require_suspension(self, undecided: bool) -> None:
        report = self.state.report
        if self.state.state != engine.SUSPENDED or report is None or report.suspended is None:
            raise ServerError(
                f"this run is {self.state.state}; there is nothing waiting for an answer.")
        is_tie = bool(report.suspended.get("undecided"))
        if is_tie != undecided:
            # A gate asks whether the run may proceed; a tie asks which way. Accepting one for the
            # other would record an answer to a question nobody was asked.
            wanted = "a tie to break" if is_tie else "a gate to approve"
            raise ServerError(
                f"this run is waiting for {wanted}, and that is not what you sent.")

    def _advance(self) -> Dict[str, object]:
        """Run the walk to its next return. **Nothing blocks inside it** — task 1's guarantee."""
        try:
            report = self._walk(self._make_config(self.state.instruction,
                                                  tuple(self.state.approvals),
                                                  tuple(self.state.rulings)))
        except Exception as exc:                   # the run failed; say so rather than look idle
            with self._lock:
                self.state.state = engine.STOPPED
                self.state.error = f"{type(exc).__name__}: {exc}"
                self.state.version += 1
                self._publish()
                return self.state.snapshot()
        with self._lock:
            self.state.report = report
            self.state.state = report.state
            self.state.version += 1
            self.state.log = [{"node_id": a.node_id, "role": a.role, "seat": a.seat}
                              for a in report.asks]
            self._publish()
            return self.state.snapshot()


def make_handler(runner: Runner, operator: Operator,
                 registry: Optional["models_mod.Registry"] = None,
                 registry_path: Optional[Path] = None):
    """The HTTP surface. Refuses before it reads, in the order the threat model requires."""

    held = {"registry": registry if registry is not None else models_mod.Registry()}

    class Handler(BaseHTTPRequestHandler):
        server_version = "ai-sdlc-runner"
        protocol_version = "HTTP/1.1"

        # -- refusals ----------------------------------------------------------------------
        def _guard(self) -> bool:
            if not _loopback_host(self.headers.get("Host")):
                # First, and before anything is parsed: a non-loopback Host on a loopback socket is
                # DNS rebinding, and the request should not get as far as being understood.
                self._json(403, {"error": "this server answers only to a loopback host"})
                return False
            origin = self.headers.get("Origin")
            if origin and not any(origin.startswith(f"http://{h}") or
                                  origin.startswith(f"https://{h}") for h in LOOPBACK_HOSTS):
                self._json(403, {"error": f"cross-origin request from {origin} refused"})
                return False
            if not operator.accepts(self.headers.get("X-Operator-Token")):
                self._json(401, {"error": "no operator token. It is in "
                                          f"{operator.token_path}, readable by you alone."})
                return False
            return True

        # -- plumbing ----------------------------------------------------------------------
        def _json(self, code: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> Dict[str, object]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError as exc:
                raise ServerError(f"the request body is not JSON: {exc}")

        def log_message(self, fmt, *args):          # pragma: no cover - quiet by default
            pass

        # -- routes ------------------------------------------------------------------------
        def do_GET(self):                           # noqa: N802 - http.server's spelling
            if not self._guard():
                return
            if self.path == "/flow":
                self._json(200, {"nodes": [
                    {"id": n.id, "kind": n.kind, "label": n.label, "role": n.role,
                     "gate": n.gate, "gate_when": n.gate_when, "mode": n.mode,
                     "main": n.main, "follows": n.follows,
                     "branches": dict(n.branches), "next": n.next}
                    for n in graph.NODES],
                    "gates": {g: dict(v) for g, v in policy.GATES.items()},
                    "modes": list(graph.MODES)})
            elif self.path == "/run":
                self._json(200, runner.state.snapshot())
            elif self.path == "/run/events":
                self._stream()
            elif self.path == "/models":
                # The console is local only; the models need not be, and the operator should never
                # have to read a hostname to find that out. `leaving` is the answer to "what goes
                # out from here", stated rather than derivable.
                reg = held["registry"]
                self._json(200, {**reg.as_dict(),
                                 "leaving": [m.id for m in reg.leaving()]})
            elif self.path == "/whoami":
                self._json(200, {"operator": operator.name})
            else:
                self._json(404, {"error": f"no route {self.path}"})

        def do_POST(self):                          # noqa: N802
            if not self._guard():
                return
            try:
                body = self._body()
                version = body.get("version")
                if not isinstance(version, int):
                    raise ServerError(
                        "every answer must name the version it is answering — without it two tabs "
                        "cannot be told apart, and a double-click spends two approvals")
                if self.path == "/run":
                    out = runner.start(str(body.get("instruction") or ""), version)
                elif self.path == "/run/gate":
                    out = runner.approve(version, str(body.get("gate") or ""),
                                         body.get("node_id"))
                elif self.path == "/models":
                    try:
                        held["registry"] = held["registry"].add(
                            models_mod._model_from(dict(body.get("model") or {})))
                    except models_mod.ModelError as exc:
                        raise ServerError(str(exc))
                    if registry_path is not None:
                        models_mod.save(held["registry"], registry_path)
                    reg = held["registry"]
                    out = {**reg.as_dict(), "leaving": [m.id for m in reg.leaving()]}
                elif self.path == "/run/decide":
                    out = runner.rule(version, str(body.get("node_id") or ""),
                                      str(body.get("branch") or ""))
                else:
                    self._json(404, {"error": f"no route {self.path}"})
                    return
            except ServerError as exc:
                self._json(409, {"error": str(exc)})
                return
            self._json(200, out)

        def _stream(self):
            q = runner.listen()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                # The current state first, so a stream and a snapshot never disagree about what the
                # client is looking at.
                self.wfile.write(
                    f"data: {json.dumps(runner.state.snapshot(), ensure_ascii=False)}\n\n"
                    .encode("utf-8"))
                self.wfile.flush()
                while True:
                    payload = q.get()
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                runner.unlisten(q)

    return Handler


def serve(runner: Runner, operator: Operator, host: str = "127.0.0.1",
          port: int = 8765, registry: Optional["models_mod.Registry"] = None,
          registry_path: Optional[Path] = None) -> ThreadingHTTPServer:
    """Build the server, refusing any host that is not this machine.

    The refusal is here rather than in the caller because a bind address is exactly the kind of thing
    that gets "temporarily" widened and never narrowed again.
    """
    if host not in LOOPBACK:
        raise ServerError(
            f"refusing to bind {host!r}. This runner merges branches and answers gates; it listens "
            f"on {LOOPBACK[0]} and nowhere else. If another machine needs to see it, put something "
            f"in front of it that you have decided to trust — do not widen this.")
    return ThreadingHTTPServer(
        (host, port), make_handler(runner, operator, registry, registry_path))
