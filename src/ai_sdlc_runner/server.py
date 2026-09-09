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

import dataclasses
import errno
import json
import os
import queue
import socket
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional

from . import attachments as attach_mod
from . import paths
from . import engine, graph, intake as intake_mod, models as models_mod, policy, store as store_mod

#: The only addresses this server will bind. Not a default — a rule. A runner that can merge
#: branches has no business listening where anything but this machine can reach it, and making that
#: configurable would turn a decision somebody argued about into a flag somebody flips.
#:
#: `"::1"` was here from this file's first commit and **never bound once**: the server class is
#: `ThreadingHTTPServer`, whose `address_family` is `AF_INET`, and `serve` has never changed it. A
#: raw `AF_INET` bind of `::1` raises `gaierror`, which is an `OSError`, which the one handler below
#: reported as a port conflict — so the list promised an address, the socket refused it, and the
#: refusal blamed something else (CHG-20260907-20). Serving IPv6 is a capability nobody has asked
#: for and it costs the guarantee `_OneRunner` exists for: `127.0.0.1:p` held, `[::1]:p` binds
#: anyway, measured. So the promise is narrowed to what the socket does, not widened to match it.
#:
#: `"localhost"` left in CHG-20260907-24, and the reason is `LOOPBACK_HOSTS` below rather than the
#: socket — it binds fine under `AF_INET`, resolving to `127.0.0.1`, which is what kept it here
#: through CHG-20260907-20. Once the header set is **derived**, a name that is both a bind spelling
#: and a name RFC 6761 fixes supplies itself twice, and measured, dropping `RESOLVER_FIXED` from the
#: derivation changed the resulting table by nothing at all: the standard's term would arrive in
#: `src/` already unfalsifiable. One address, one reason each. Binding `localhost` bought nothing
#: over binding what it resolves to, and `serve(host="localhost")` is refused now — by a refusal
#: that names what it does take.
LOOPBACK = ("127.0.0.1",)

#: Names whose loopback meaning is fixed by **RFC 6761 6.3** rather than by a bind argument or by
#: DNS. A browser at `http://localhost:8765` reaches a server bound to `127.0.0.1` because the
#: standard fixes what the name means, whether or not `localhost` is a spelling `serve` accepts.
#:
#: Fixed by the standard and not by "the platform", and the difference is measured: this machine's
#: resolver also answers `127.0.0.1` for `localhost.localdomain`, which no standard requires and a
#: rebinding guard must not accept — *"whatever resolves to loopback here"* is the attacker's
#: precondition, not a rule. `foo.localhost` goes the other way: 6.3 covers it and this OS answers
#: `gaierror`, so only a browser could send it and accepting it would be a widening with its own
#: record. That intersection of standard, resolver and browser leaves exactly one member.
#:
#: **What a member may be, for whoever adds the second one.** A bare, lowercase name: an address's
#: loopback meaning is IANA's and belongs in `LOOPBACK`, and lowercase because `_loopback_host`
#: lowercases the header and looks the result up in `LOOPBACK_HOSTS` **as written**, so an
#: uppercase member is unreachable at runtime. CHG-20260907-21 wrote those as three assertions
#: beside the set; CHG-20260907-24 measured that once the set is pinned against a literal on the
#: test side they cannot fail on their own -- every single-edit widening is refused by the pin or
#: by the live `Host` test first -- and moved the rule here, where it is addressed to the person
#: who edits this line rather than presented as a check.
#:
#: Written on the test side by CHG-20260907-21, which said the record deriving `LOOPBACK_HOSTS` is
#: what would lift it across the line. This is that record (CHG-20260907-24).
RESOLVER_FIXED = frozenset({"localhost"})


def _authority(addr: str) -> str:
    """The authority a client sends for a bind address: an IPv6 literal wears brackets.

    `[::1]` is the string `_loopback_host` looks up for a server on `::1`, because it keeps the
    brackets, while `_loopback_origin` gets the bare form out of `urlsplit` and strips them off the
    table. The bracketed form is therefore the one to store: CHG-20260907-20 removed the bare
    `"::1"` as unreachable by any compliant request, and CHG-20260907-19's sketch emitted **both**
    spellings, which is the side this does not take.

    **The bracket is dead by data and not by test.** `LOOPBACK` holds no IPv6 address and cannot
    hold one while `address_family` is `AF_INET`, so no request reaches this branch. What keeps it
    honest is that this is a function rather than a comprehension inside a constant: a test can ask
    it about an input the constant does not have, and removing the bracket is CAUGHT. The same move
    reaches the two normalisations CHG-20260907-20 left dead-by-data in `_loopback_host` and
    `_loopback_origin` — derive this table for a bind list that is not the shipped one and both
    become falsifiable, which they were not before (CHG-20260907-24).
    """
    return f"[{addr}]" if ":" in addr else addr


def _accepted_hosts(addresses: Iterable[str]) -> FrozenSet[str]:
    """The `Host` and `Origin` table a bind list implies, plus the names a standard fixes.

    One boundary, written once. It used to be written twice four lines apart and nothing required
    the two spellings to agree; CHG-20260907-19 found that, CHG-20260907-21 stated the relation as
    an equality a test asserted, and this makes the equality true by construction instead.

    Lowercased, because `_loopback_host` lowercases the header and looks the result up in this
    table **as written** — a member spelled `LocalHost` would be dead at runtime, so a bind
    address spelled that way has to arrive here folded.
    """
    return frozenset({_authority(addr).lower() for addr in addresses}) | RESOLVER_FIXED


#: `Host` values a loopback request can legitimately carry. Anything else is a rebinding attempt or
#: a proxy, and both are reasons to refuse rather than to guess.
#:
#: **Derived, not written down twice** (CHG-20260907-24). The two IPv6 spellings this held left with
#: `"::1"` above (CHG-20260907-20) and cannot come back by hand: a browser sends `Host: [::1]` only
#: from a URL that connects to `::1`, where this server is not, and the bare `"::1"` was reachable
#: only through an unbracketed authority RFC 7230 5.4 does not permit. Now they can only come back
#: with the address, which is the point — the surface follows the socket rather than tracking it.
LOOPBACK_HOSTS = _accepted_hosts(LOOPBACK)

IDLE = "idle"


#: The largest request body this server will read, derived from the attachment limit rather
#: than chosen beside it.
#:
#: base64 is 4 bytes out for every 3 in, so a **legal** attachment of `attachments.MAX_BYTES`
#: arrives as 33.33 MB on the wire — measured, 34,952,586 bytes for the envelope. A wire limit
#: set to `MAX_BYTES` would therefore refuse every attachment that uses the limit it was given,
#: which is the trap in bounding this at all. The megabyte on top is the JSON envelope and the
#: room to say so.
#:
#: Derived, not written down twice: raising `MAX_BYTES` without this would reintroduce the
#: refusal it exists to prevent (CHG-20260906-02).
MAX_BODY_BYTES = attach_mod.MAX_BYTES * 4 // 3 + 1024 * 1024


class ServerError(Exception):
    """Refused. Never softened into a partial success."""


class BodyTooLarge(ServerError):
    """A request body larger than this server will read.

    Its own class because it is the one refusal here that is **not** a 409: `docs/API.md` says
    409 is this server saying *"I understood you and I am not doing that"*, and a body it
    refused to read is one it did not understand. 413 says which, and the message says both
    numbers.
    """


def _loopback_host(header: Optional[str]) -> bool:
    """Is this ``Host`` header one of ours? Port stripped, IPv6 brackets kept."""
    if not header:
        return False
    host = header.strip()
    # `[::1]` is not a host this server accepts any more (CHG-20260907-20), so no request reaches
    # this branch. It was also unfalsifiable until CHG-20260907-24: removing it changed no test,
    # measured then and re-measured since. It is now caught, because `LOOPBACK_HOSTS` is derived
    # and a test can derive it for a bind list the constant does not have and ask this function the
    # same question a browser would. Kept because it is what an IPv6 build would need back, and
    # because `_loopback_origin` normalises the other way — the pair is the thing to read together,
    # not either half alone.
    if host.startswith("["):                       # [::1]:8765
        host = host.split("]")[0] + "]"
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host.lower() in LOOPBACK_HOSTS


def _loopback_origin(origin: str) -> bool:
    """Is this ``Origin`` one of ours? **Parsed, never prefix-matched.**

    The first version asked whether the origin *started with* ``http://localhost``. It does not take
    much to defeat that: ``http://localhost.evil.example`` starts with ``http://localhost``, and an
    attacker can register that name. Found by an independent seat reading the check; confirmed by
    running it — three lookalike origins were accepted.

    A prefix is not a host. `urlsplit` knows where a hostname ends and this function does not have
    to guess.
    """
    try:
        parts = urlsplit(origin)
        scheme, host_attr, port = parts.scheme, parts.hostname, parts.port
    except ValueError:
        # `urlsplit` raises "Invalid IPv6 URL" on a malformed origin -- and on which inputs it
        # raises differs by Python version: 3.11 on Windows returned a hostname for
        # `http://[::1].evil.example`, while 3.9 and 3.13 raise. CI caught the difference; my
        # machine could not have. Malformed is refused either way, which is the only answer that
        # does not depend on the interpreter.
        return False
    if scheme not in ("http", "https"):
        return False
    if parts.path or parts.query or parts.fragment or parts.username or parts.password:
        return False        # an origin is scheme://host[:port] and nothing else

    # Rebuilt and compared, because parsing alone is not enough: `urlsplit` reads
    # `http://[::1].evil.example` as host `::1` and silently drops the rest, so a hostname check
    # would accept it. A browser would not send that -- but "browsers only send well-formed
    # origins" is exactly the kind of assumption that turns into the next finding.
    host = (host_attr or "").lower()
    port_part = f":{port}" if port else ""
    # `_authority`, not a second copy of it. This line read `f"[{host}]" if ":" in host else host`
    # -- the same expression, ninety lines from the function that now owns it, in the same file
    # whose subject is one boundary written twice. Found by review of CHG-20260907-24, whose record
    # had claimed there was no second copy. This is also the call site where the bracket is
    # **reached**: `test_an_ipv6_origin_is_refused_because_nothing_serves_one` sends
    # `http://[::1]:8080` on every run.
    literal = _authority(host)
    if f"{scheme}://{literal}{port_part}" != origin.strip().lower():
        return False
    # `hostname` strips the port and the brackets from an IPv6 literal, so `[::1]` arrives as `::1`
    # while `_loopback_host` looks up `"[::1]"`. One address, two lookups — the half of the pair
    # `_loopback_host` describes, and caught from CHG-20260907-24 for the reason given there.
    return host in {h.strip("[]") for h in LOOPBACK_HOSTS}


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
        paths.makedirs(directory)
        path = directory / "operator.token"
        token = secrets.token_urlsafe(32)
        paths.write_text(path, token + "\n")
        try:
            paths.chmod(path, 0o600)
        except OSError:                            # pragma: no cover - filesystems without modes
            pass
        name = os.environ.get("USER") or os.environ.get("USERNAME") or "operator"
        return cls(token=token, name=name, token_path=path)

    def accepts(self, presented: Optional[str]) -> bool:
        # Constant-time: the token is short and local, but a comparison that leaks its prefix is
        # free to avoid and awkward to explain afterwards.
        return bool(presented) and secrets.compare_digest(presented, self.token)


def _adjudication_for(report: Optional[engine.RunReport]) -> Optional[Dict[str, object]]:
    """The adjudication belonging to the stop, or `None` when the stopping node has no panel.

    The *last* adjudication for that node, because a panel can take more than one lap
    (`panel_rounds`) and what a person is being shown is what it settled on.
    """
    if not report or not report.suspended:
        return None
    here = (report.suspended or {}).get("node_id")
    mine = [a for a in report.adjudications if a.get("node_id") == here]
    return dict(mine[-1]) if mine else None


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
    #: Every instruction, in the order they arrived. The blueprint is rarely finished when a run
    #: starts; a second instruction is an event, not an edit of the first, and a work order that can
    #: say *when* something was asked for is most of what makes a late change reviewable.
    instructions: List[str] = field(default_factory=list)
    report: Optional[engine.RunReport] = None
    #: Answers accumulated across suspensions. A resumed walk replays from `intake` carrying these,
    #: which is why they are kept rather than applied and forgotten.
    approvals: List[engine.Approval] = field(default_factory=list)
    rulings: List[engine.Ruling] = field(default_factory=list)
    rejections: List["engine.Rejection"] = field(default_factory=list)
    #: Every time this run has stopped for an incomplete requirement, and what was missing. The
    #: escalation to options depends on this being **counted** rather than remembered, and it has to
    #: survive the walks in between — a counter that resets each walk would ask forever.
    intake_history: List[Dict[str, object]] = field(default_factory=list)
    #: Approvals the brief outgrew. Retired rather than removed — `approvals` above is
    #: append-only and three docstrings rely on it — so a superseded decision stays in the
    #: ledger as history and is named here instead of being spent (CHG-20260906-03).
    retired_approvals: List[str] = field(default_factory=list)
    #: `(node_id, digest, brief)` once somebody has read what a seat called unsafe and said to
    #: continue. The digest is `intake.shown_digest` of the findings they were shown, so a decision
    #: cannot answer findings nobody put in front of them; the brief retires it the way
    #: `_live_approvals` retires an approval the brief outgrew (CHG-20260906-03).
    proceeded: Optional[tuple] = None
    #: How many instructions had been given at the last stop that found the requirement
    #: **incomplete** (CHG-20260904-05). The assignment below is under `stop["incomplete"]` and
    #: nothing else writes this, so that is the whole of what it records — and `told > mark` is
    #: *"has it grown since that stop?"*.
    #:
    #: **Two renames, and the second is why the first was not enough** (CHG-20260907-27). It was
    #: `instructions_when_last_asked` until the fourth round, which was false once the guard split:
    #: a replayed walk records no stop, asks nobody, and still moves this. The fourth round called
    #: it `instructions_when_last_read` and glossed the comparison *"has it grown since the answers
    #: in hand were given?"*, and the sixth round refuted the gloss with a walk that reads the
    #: requirement, finds nothing missing, gives an answer and does not move this. The name had the
    #: same reach as the gloss, so the seventh round took the name too: what is written here is not
    #: every read, it is every read that stopped short. Three earlier records name the old
    #: spellings, and they are history: CHG-20260904-05
    #: put `_instructions_when_last_asked` on the `Runner`, CHG-20260904-09 moved it here.
    #: **On the run, not on the runner** (CHG-20260904-09): `start` builds a fresh `RunState` with
    #: `instructions=[instruction]`, so a mark that outlived it made `told > mark` false for every
    #: run after the first in a process, and `intake_history` above stayed empty — the field whose
    #: own comment says the escalation depends on it being counted.
    #: -1, not 0, so that the **first** stop is always an ask — which is CHG-20260904-05's own
    #: task 3, and was false whenever the run began on nothing. `start("")` builds `instructions=[]`,
    #: so `told > mark` was `0 > 0` and the first stop went uncounted; every later count was one
    #: short for the life of the run. `or not self.intake_history` produces identical counts, and
    #: was rejected for a reason that is not about behaviour: under it CHG-20260904-09's mutation
    #: stays **green**, so the existing guard becomes a test that cannot fail.
    instructions_at_last_incomplete_stop: int = -1
    log: List[Dict[str, object]] = field(default_factory=list)
    #: What the operator handed over, and anything the store has since lost. A brief that has
    #: quietly lost a document is worse than one that says so.
    attachments: List["attach_mod.Attachment"] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    error: str = ""

    def snapshot(self) -> Dict[str, object]:
        report = self.report
        return {
            "state": self.state,
            "version": self.version,
            "instructions": list(self.instructions),
            "attachments": [a.as_dict() for a in self.attachments],
            "attachments_missing": list(self.missing),
            "retired_approvals": list(self.retired_approvals),
            "error": self.error,
            "at": report.halted_at if report else None,
            "reason": report.halt_reason if report else "",
            "visited": list(report.visited) if report else [],
            "suspended": dict(report.suspended) if report and report.suspended else None,
            "confirmations": list(report.confirmations) if report else [],
            "rulings": list(report.rulings) if report else [],
            "rejections": list(report.rejections) if report else [],
            "survey": dict(report.survey) if report and report.survey else None,
            # **Per aspect, like the sentence above it in the page** (CHG-20260904-03, defect
            # seat L-16). This sent `len(self.intake_history)` — every intake stop, whatever
            # was missing — while the `<p>` beside it renders `report.halt_reason`, which
            # `intake.stop_reason` writes **per aspect**. From the second aspect onward the
            # console showed two different answers to one question in one box:
            #
            #     missing        the <p> says     the counter said
            #     flow           asked once       1
            #     architecture   asked once       2
            #     architecture   asked twice      3
            #
            # CHG-20260903-42 gave the two engine-side readers one name and did not reach
            # here. **The tally, not `asks_including_this_one`**: this is read *after* the
            # walk has recorded the current stop, so the ask in flight is already counted —
            # the same question has two correct answers at two moments, which is exactly why
            # one shared function would give the wrong one here.
            #
            # **The table above was measured before `attach` could walk without counting**
            # (CHG-20260907-27). Its three rows are all `instruct` laps, where the stop is
            # always appended, so the two columns could only differ by *which* stops were
            # counted. The row it was missing is the one where they differ by the ask in
            # flight, and it survived this repair's own predecessor:
            #
            #     walk       the <p> said      the counter said   options?
            #     attach     asked 3 times     2                  YES     <- CHG-20260904-05
            #     attach     asked twice       2                  no      <- and now
            #
            # Nothing here changed to fix it. The `<p>` moved, because the walk now tells the
            # engine it was not an ask; this stayed the tally, which was right both times.
            #
            # **And a fourth kind of walk, from the second round.** A `start` on a brief a
            # persisted journal already answers opens no session, so it is not an ask either, and
            # the `RunState` it starts is fresh — so this map has no entry for the aspect at all.
            # An absent key is zero here, and the sentence beside it says *"not asked yet"*:
            #
            #     walk       the <p> said      the counter said   options?
            #     start      asked 0 times     1                  no      <- 28afbc2, two answers
            #     start      not asked yet     (no entry)         no      <- and now
            #
            # Still nothing here changed. The append guard below stopped recording a stop nobody
            # was asked for, which is what makes the two columns one number again.
            "intake_asks_by_aspect": {
                aspect: intake_mod.times_asked(self.intake_history, aspect)
                for stop in self.intake_history
                for aspect in (stop.get("missing") or ())},
            "send_backs": [dict(b) for b in report.send_backs] if report else [],
            # Where a pool sent the work, and which model a follows reused. The console has to be
            # able to show this or "chosen at random" is a claim nobody can check.
            "dispatches": list(report.dispatches) if report else [],
            "adjudications": [dict(a) for a in report.adjudications] if report else [],
            # **The adjudication for the node the run is stopping at, or `None`**
            # (CHG-20260904-11). `drawDecisions` renders every adjudication a run made, two
            # blocks below the box a person is actually reading when they decide — and that box
            # rendered none of them. CHG-20260903-24 proposed showing `adjudications[-1]` and was
            # withdrawn partly for it: `[-1]` is whichever adjudication happened *last*, and at
            # `merge` on a default install that is `lead_review`'s verdict on built work, shown
            # as the one-way door's pre-answer. Bound to the stopping node instead, so a node
            # with no panel shows nothing rather than somebody else's judgement.
            #
            # Derived here rather than in the browser because the browser cannot be tested in
            # this repository — every console guard is a text search over the page — and the
            # rule this replaces is exactly the kind that reads plausible and measures wrong.
            "adjudication_here": _adjudication_for(report),
            "log": list(self.log),
        }


class Runner:
    """Owns the one run. Every state change bumps the version and wakes the listeners."""

    #: ``make_config`` returns a **`RunConfig`**, and the annotation says so from CHG-20260907-27.
    #: It said `object`, and `_walk_once` has been calling `dataclasses.replace` on the result since
    #: CHG-20260906-07 — behind `if proceeded`, so the two test stubs that returned `None` and
    #: `object()` never reached it. Filling `intake_ask_in_flight` on every walk did, and both went
    #: red at once. A signature that permits what the body cannot take is where those stubs came
    #: from.
    def __init__(self, walk: Callable[..., engine.RunReport],
                 make_config: Callable[..., engine.RunConfig],
                 store: Optional["attach_mod.Store"] = None):
        self._walk = walk
        self._make_config = make_config
        self._store = store
        self._lock = threading.RLock()
        #: Whether a walk is in flight, and whether something arrived while it was. Both are read
        #: and written only under `_lock`; the walk itself runs outside it. See `_advance`.
        self._walking = False
        self._walk_again = False
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
            # Read the store **before** the state moves. This ran after, so a manifest that
            # could not be read left the runner permanently "running": the raise escaped
            # `start` with the state already mutated, every later POST answered 409, and
            # there was no route back to idle short of restarting the process. Meanwhile
            # `GET /attachments` answered from cached state and reported zero attachments
            # *and* zero missing while the store held one — inverting the guarantee that a
            # run which has lost a document says so (CHG-20260905-04).
            held, lost = self._read_attachments()
            self.state = RunState(state="running", version=self.state.version + 1,
                                  instructions=[instruction] if instruction else [])
            self.state.attachments, self.state.missing = held, lost
            self._publish()
        return self._advance()

    def instruct(self, version: int, instruction: str) -> Dict[str, object]:
        """Add an instruction to a run already under way.

        The blueprint gets finished while the work happens — that is the normal case, not a failure
        of planning. So a second instruction is **added**, never merged into the first: every work
        order from here on carries both, numbered, and a reviewer can see that something arrived
        late rather than being handed a brief that looks as though it was always complete.

        Only at a stop. Editing the brief underneath a walk that is mid-flight would mean two nodes
        in one run answering different questions with nothing recording which was which.
        """
        if not instruction.strip():
            raise ServerError("an empty instruction says nothing; there is nothing to add")
        with self._lock:
            self._require_version(version)
            if self.state.state not in (engine.SUSPENDED, IDLE, engine.FINISHED, engine.STOPPED):
                raise ServerError(
                    f"this run is {self.state.state}. An instruction can be added when it is "
                    f"waiting or finished — changing the brief under a walk in flight would have "
                    f"two nodes answering different questions with nothing saying which was which.")
            self.state.instructions.append(instruction.strip())
            self._refresh_attachments()
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        # Then walk again. Adding to the brief and NOT re-walking was a defect found live: the
        # instruction landed, the version moved, and nothing was re-asked — so the seats went on
        # reporting what the first instruction had not said, however much was added afterwards.
        #
        # Re-walking is safe because it is the same walk it always was: the journal reuses every
        # answer whose question is unchanged, and a changed brief changes every question, which is
        # precisely when re-asking is the correct thing to do.
        return self._advance()

    def attach(self, version: int, filename: str, data: bytes) -> Dict[str, object]:
        if self._store is None:
            raise ServerError("this runner has no attachment store")
        with self._lock:
            self._require_version(version)
            try:
                self._store.add(filename, data, instruction=len(self.state.instructions))
            except attach_mod.AttachmentError as exc:
                raise ServerError(str(exc))
            self._refresh_attachments()
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        # Same reason as `instruct`: an attachment reaches every work order, so every question has
        # changed and the run has to be walked again for anybody to see it.
        return self._advance()

    def _brief_now(self) -> tuple:
        """What the operator is looking at: the instructions, and the attachments in front of
        them.

        Attachments already carry this stamp — `Store.add(..., instruction=len(instructions))`
        — and approvals did not, which is the whole of the defect. The attachment ids and not
        merely a count, because a document replaced is a changed brief even when the number is
        the same.
        """
        return (len(self.state.instructions),
                tuple(sorted(a.id for a in self.state.attachments)))

    def _live_approvals(self):
        """The approvals that answer the brief in front of the run now, and the retired rest.

        **Retired, not removed.** `state.approvals` is append-only and three docstrings rely on
        that, so a superseded decision stays in the ledger as history and is filtered out of
        what the walk is handed. An approval with no brief — one given up-front on the command
        line — answers any brief, which is what every existing caller passes.
        """
        here = self._brief_now()
        live, retired = [], []
        for approval in self.state.approvals:
            (live if approval.brief in (None, here) else retired).append(approval)
        return live, retired

    def _read_attachments(self):
        """What the store holds and what it has lost, without touching `self.state`.

        Separate from the assignment so a caller can raise *before* the run state moves —
        `Store.all` raises `AttachmentError` on an unreadable manifest, and a half-applied
        state change is how that became unrecoverable.
        """
        if self._store is None:
            return [], []
        return self._store.all(), self._store.missing()

    def _refresh_attachments(self) -> None:
        self.state.attachments, self.state.missing = self._read_attachments()

    def _answering(self, *, gate: Optional[str] = None,
                   node_id: Optional[str] = None) -> Dict[str, object]:
        """The stop this decision answers — refusing one that names a different stop.

        **The answer must name the stop it is answering** (CHG-20260903-34, risk seat L-47).
        `_require_suspension` checks *that* the run is waiting, never *which* gate it is waiting at,
        so a client could approve `acceptance` while the run was suspended at `plan_confirmed`, and
        `state.approvals` is append-only with no removal route — that pre-authorisation waited
        indefinitely for a rung the person would never be shown. Driven end to end, it opened
        `halt_independent` at `qa_accept` on a high-risk run whose operator answered only the seven
        stops the console put in front of them.

        **One helper rather than the check copied into each caller** (CHG-20260903-44). It was
        written into `approve` alone, and `reject` and `rule` — three and five methods below, in
        this same class — never got it: a refusal naming a gate the run was not at was accepted and
        routed the run past that same `halt_independent` cell, recorded as the operator's act.
        CHG-20260903-36 was *"two fixes shipped into one module and never swept into their
        siblings"*; this is that, inside the module that record was about. A fourth decision method
        cannot now be written without asking the question.

        Returns the suspension, so the caller can stamp `node_id` and `run_id` from it —
        `Approval`'s docstring calls `None` *"the wrong one for an answer typed into a console after
        a stop"*, and it was the one `reject` and `rule` passed.

        **A missing value is refused, not skipped** (CHG-20260904-01, defect seat L-15). `do_POST`
        turns an absent field into `""` — `str(body.get("gate") or "")` — and the guards below were
        written `if gate and …`, so an empty one short-circuited both and **no check ran at all**.
        The decision then reached a ledger this class's own docstring calls append-only with no
        removal route, and `walk`'s up-front check refused it on every subsequent walk:

            Approval(gate="")    EngineError: approval for gate '' does not exist
            Rejection(gate="")   EngineError: rejection names gate '', which does not exist
            Ruling(node_id="")   EngineError: ruling names a node that is not in the flow

        The run was then unrecoverable short of `POST /run` — which is CHG-20260903-23's L-25
        defect arriving by the empty-string road, into the helper CHG-20260903-44 extracted to stop
        exactly this. The helper asked the question and the question answered nothing.
        """
        waiting = self.state.report.suspended or {} if self.state.report else {}
        for label, given in (("gate", gate), ("node", node_id)):
            if given is not None and not str(given).strip() and waiting.get(
                    "gate" if label == "gate" else "node_id"):
                raise ServerError(
                    f"this decision names no {label}, and the run is waiting at "
                    f"{waiting.get('gate')!r} / {waiting.get('node_id')!r}. An empty answer cannot "
                    f"be spent anywhere and cannot be withdrawn once recorded.")
        if gate and waiting.get("gate") and gate != waiting["gate"]:
            raise ServerError(
                f"this run is waiting at {waiting['gate']!r}, not {gate!r}. A decision names the "
                f"stop it answers — one that names a different gate would wait for a stop nobody "
                f"has been shown.")
        if node_id and waiting.get("node_id") and node_id != waiting["node_id"]:
            raise ServerError(
                f"this run is waiting at node {waiting['node_id']!r}, not {node_id!r}.")
        return waiting

    def approve(self, version: int, gate: str, node_id: Optional[str]) -> Dict[str, object]:
        with self._lock:
            self._require_version(version)
            self._require_suspension(undecided=False)
            # **The answer must name the stop it is answering** (CHG-20260903-34, risk seat
            # L-47). `_require_suspension` checks *that* the run is waiting, never *which*
            # gate it is waiting at — so a client could approve `acceptance` while the run was
            # suspended at `plan_confirmed`, and `state.approvals` is append-only with no
            # removal route, so that pre-authorisation waited indefinitely for a rung the
            # person would never be shown. Driven end to end: it opened `halt_independent` at
            # `qa_accept` on a high-risk run whose operator answered only the seven stops the
            # console put in front of them.
            #
            # `Approval`'s own docstring says why this matters: `node_id` and `run_id` are
            # *"what make refusing a stale or misdirected answer possible"*, and `None` is
            # *"the wrong one for an answer typed into a console after a stop"*. This is that
            # console, and it was passing the wrong one.
            waiting = self._answering(gate=gate, node_id=node_id)
            self.state.approvals.append(
                engine.Approval(gate=gate,
                                node_id=node_id or waiting.get("node_id"),
                                run_id=waiting.get("run_id"),
                                brief=self._brief_now()))
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        return self._advance()

    def proceed(self, version: int, node_id: Optional[str]) -> Dict[str, object]:
        """A person read what the seats called unsafe, and said to continue anyway.

        There is no journal marker here, unlike the command line's `--proceed-unsafe`. There does
        not need to be: this route is reachable only while the run is suspended *showing* those
        findings, so being shown them is the route's precondition rather than something to record
        and check afterwards. The digest is still taken, because what is being answered has to be
        pinned to what was displayed — a later walk whose seats say something new is a different
        list, and this decision does not cover it.
        """
        with self._lock:
            self._require_version(version)
            # Through the same gate every other answer uses, rather than a second state check
            # of its own: `test_only_attach_reaches_advance_without_a_state_gate` exists to catch
            # exactly the parallel mechanism the first version of this method wrote.
            self._require_suspension(undecided=False, unsafe=True)
            report = self.state.report
            waiting = self._answering(node_id=node_id)
            self.state.proceeded = (waiting.get("node_id"),
                                    intake_mod.shown_digest(report.suspended.get("safety") or {}),
                                    self._brief_now())
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        return self._advance()

    def reject(self, version: int, gate: str, node_id: Optional[str],
               reason: str) -> Dict[str, object]:
        """Refuse a gate. Where the run then goes is the graph's to say, never the refuser's."""
        with self._lock:
            self._require_version(version)
            self._require_suspension(undecided=False)
            target = graph.BY_ID.get(node_id or "")
            if target is None or target.rejects_to is None:
                raise ServerError(
                    f"{node_id!r} has nowhere to send a refusal. This gate can be approved or left "
                    f"waiting — leaving the run stopped IS the refusal.")
            # Named and stamped, like `approve` (CHG-20260903-44). This appended whatever it was
            # given: a refusal aimed at a stop nobody had been shown redirected the run past
            # `acceptance@high`, the only `halt_independent` cell in `GATES`, under the operator's
            # name — and `run_id=None` left the engine's staleness guard dead for console traffic.
            waiting = self._answering(gate=gate, node_id=node_id)
            self.state.rejections.append(
                engine.Rejection(gate=gate, node_id=node_id or waiting.get("node_id"),
                                 run_id=waiting.get("run_id"), reason=reason))
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        return self._advance()

    def rule(self, version: int, node_id: str, branch: str) -> Dict[str, object]:
        with self._lock:
            self._require_version(version)
            self._require_suspension(undecided=True)
            # A tie-break names the node it breaks (CHG-20260903-44). `_require_suspension`
            # confirms the run is undecided; it does not confirm it is undecided *here*.
            waiting = self._answering(node_id=node_id)
            self.state.rulings.append(
                engine.Ruling(node_id=node_id, branch=branch, run_id=waiting.get("run_id")))
            self.state.state = "running"
            self.state.version += 1
            self._publish()
        return self._advance()

    def require_version(self, version: int) -> None:
        """Public, because the configuration routes need the same check the run routes make."""
        with self._lock:
            self._require_version(version)

    def edit(self, version: int, write):
        """Check the version, run ``write``, and advance the version — **all under one lock.**

        Three separate critical sections is a check-then-act window: two threads validate the same
        version, both write, and the double-submit the version exists to refuse happens anyway.
        """
        with self._lock:
            self._require_version(version)
            out = write()
            self.state.version += 1
            self._publish()
            return out

    def publish_config_change(self) -> None:
        """A configuration edit advances the version and wakes every listener."""
        with self._lock:
            self.state.version += 1
            self._publish()

    def _require_version(self, version: int) -> None:
        """Task 16. The refusal that turns a double-click into an error instead of two approvals."""
        if version != self.state.version:
            raise ServerError(
                f"this run is at version {self.state.version} and you answered version {version}. "
                f"Something moved — another tab, or a click that already landed. Reload and look at "
                f"what it is actually waiting for before answering again.")

    def _require_suspension(self, undecided: bool, unsafe: bool = False) -> None:
        report = self.state.report
        if self.state.state != engine.SUSPENDED or report is None or report.suspended is None:
            raise ServerError(
                f"this run is {self.state.state}; there is nothing waiting for an answer.")
        # **Three shapes, not two** (CHG-20260903-23, defect seat L-25). The engine emits a gate
        # (`incomplete` and `undecided` both false), an **incomplete requirement**
        # (`incomplete: True`), and a tie (`undecided: True`). This read `undecided` alone, so an
        # incomplete stop was accepted on the approve path — and `intake_review` has no gate, so
        # `approve()` stored `Approval(gate=None, …)`, which `walk`'s up-front check then refuses on
        # **every** subsequent walk. `RunState.approvals` is only ever appended to and read; there
        # is no removal route, so the run was unrecoverable short of `POST /run`.
        #
        # The refusal text was wrong too: at an incomplete stop it said *"waiting for a gate to
        # approve"*. It is waiting for a requirement somebody has to finish.
        is_tie = bool(report.suspended.get("undecided"))
        is_incomplete = bool(report.suspended.get("incomplete"))
        # **A fourth shape** (CHG-20260906-07). Refused here for the reason the comment above
        # gives about the incomplete one: `intake_review` has no gate, so an answer that reached
        # `approve()` would store `Approval(gate=None, …)`, which `walk` refuses on every later
        # walk — and `state.approvals` is append-only, so `_live_approvals` retires it only when
        # the brief changes. The run would be stuck on a decision the person did make.
        is_unsafe = bool(report.suspended.get("unsafe"))
        if is_unsafe != unsafe:
            said = "; ".join(f"{seat}: {line}"
                             for seat, lines in sorted(
                                 (report.suspended.get("safety") or {}).items())
                             for line in lines)
            raise ServerError(
                f"this run is waiting for a person to read what a seat called unsafe"
                f"{' — ' + said if said else ''}, and that is not what you sent. "
                f"Answer it with POST /run/proceed.")
        if is_incomplete:
            missing = ", ".join(str(a) for a in report.suspended.get("missing") or ())
            raise ServerError(
                f"this run is waiting for a requirement that is not complete"
                f"{' — ' + missing if missing else ''}, and that is not what you sent. "
                f"Answer it with POST /run/instruct.")
        if is_tie != undecided:
            # A gate asks whether the run may proceed; a tie asks which way. Accepting one for the
            # other would record an answer to a question nobody was asked.
            wanted = "a tie to break" if is_tie else "a gate to approve"
            raise ServerError(
                f"this run is waiting for {wanted}, and that is not what you sent.")

    def _advance(self) -> Dict[str, object]:
        """Run the walk to its next return — **one at a time**, and never dropping what arrived.

        `_advance` deliberately does not hold `self._lock`: a walk dispatches models and can take
        minutes, and holding the lock across it would make the whole HTTP surface unresponsive.
        That is task 1's guarantee and it is right.

        What it did not do was stop a **second** walk starting. **`attach()`** mutates the state
        under the lock, releases it, and calls this — so an attachment posted while a walk was in
        flight began a second concurrent walk over the same `Conversation` object. Both review
        seats found it.

        `attach()` alone: `start()` and `instruct()` refuse unless the run is idle, finished,
        stopped or suspended, and `approve`, `reject` and `rule` go through `_require_suspension`.
        An earlier version of this docstring named `instruct()` too, which was already false when
        it was written and is corrected here. CHG-20260823-42 made the consequence survivable — the turn
        writes serialise and a collision is refused rather than silently rolled back — but two walks
        over one run is still two walks over one run.

        Three ways to close it, and the two rejected ones are worth recording:

        * **Hold a lock across the walk.** Correct and unacceptable: it reintroduces exactly the
          unresponsiveness `_advance` exists to avoid.
        * **Refuse the second caller** (`409, a walk is already running`). Honest, non-blocking —
          and it silently discards the effect of the operator's instruction, because the walk
          already in flight captured its config before that instruction existed. The action would be
          recorded in the state and never acted on, which is this project's own worst failure shape.
        * **Coalesce.** The second caller's change is already committed to the state; it returns
          immediately with the current snapshot, and the *running* walk is told to go round again
          when it finishes. One walk at a time, and nothing an operator did is dropped.

        Coalesce. A caller that arrives during a walk gets `running` back — which is true — and its
        instruction is walked by the loop below rather than by a second thread.
        """
        with self._lock:
            if self._walking:
                # Recorded, not walked twice. The running walk will pick this up when it returns.
                self._walk_again = True
                return self.state.snapshot()
            self._walking = True

        try:
            while True:
                snapshot = self._walk_once()
                with self._lock:
                    if not self._walk_again:
                        # `_walking` is cleared **here**, in the same critical section as the check
                        # that found nothing waiting. Clearing it in a `finally` instead left a
                        # window (CHG-20260823-44): between this `return` releasing the lock and
                        # the `finally` re-acquiring it, another caller could take the lock, see
                        # `_walking` still true, set `_walk_again` — and then have it cleared out
                        # from under them by a walk that had already decided to stop. Their
                        # attachment would wait for some unrelated future caller to walk it, and
                        # that caller would then walk twice.
                        #
                        # A lost wakeup, in the gate written to stop an action being dropped. Found
                        # by reading it before sending it to review rather than by review.
                        self._walking = False
                        return snapshot
                    # Something arrived mid-walk. Go round again, with the state as it is now.
                    self._walk_again = False
        except BaseException:
            # A walk that died with something `_walk_once` does not catch — a `KeyboardInterrupt`,
            # or an error in the post-walk bookkeeping rather than in the walk itself.
            #
            # **This drops a pending wakeup, and that is a real cost rather than a clean-up.** A
            # caller who arrived mid-walk was told `running` and had `_walk_again` set; clearing it
            # means their action is walked by nobody until some unrelated later caller. The
            # alternative — leaving it set with no walk behind it — strands it differently and
            # makes the next unrelated caller walk twice. Neither is good; this one at least leaves
            # the runner in a state whose flags describe reality.
            #
            # Their action is still committed in `self.state`, so nothing is lost, only deferred.
            with self._lock:
                self._walking = False
                self._walk_again = False
            raise

    def _walk_once(self) -> Dict[str, object]:
        """One walk, exactly as before. Called only by `_advance`, only one at a time."""
        try:
            live, retired = self._live_approvals()
            for approval in retired:
                # Reported rather than spent, and reported the way `_finish` already reports a
                # confirmation nobody spent: a fact about the run, not an act by the operator.
                note = (f"{approval.gate} was approved against an earlier brief "
                        f"({approval.brief[0]} instruction(s), {len(approval.brief[1])} "
                        f"attachment(s)); the brief has changed, so that approval is retired "
                        f"and this gate asks again")
                if note not in self.state.retired_approvals:
                    self.state.retired_approvals.append(note)
            # **The store is read under the lock, and this was the one reader that was not**
            # (CHG-20260908-05). `start`, `instruct` and `attach` all read it inside
            # `with self._lock`; this call did not, because a walk deliberately holds no lock
            # across itself. But `Store.all()` opens `manifest.json` to read it, and `Store.add`
            # — under the lock, from `attach` — finishes with `os.replace` onto that same file.
            # On Windows a replace onto a file another thread holds open fails `PermissionError`
            # [WinError 5], deterministically. So the lock serialised writers against writers and
            # left the walk's reader racing the writer, and the operator's attachment came back
            # 500 while the walk carried on.
            #
            # Measured before this change: eight ordinary runs of
            # `test_the_gate_never_rests_with_something_still_flagged`, one thread dead of exactly
            # that. The test reported `1 passed`, which is the other half of this record.
            #
            # Only the read is inside the lock. The walk itself stays outside it, which is the
            # property `_advance` is built on and which CHG-20260823-44 pinned.
            if self._store is not None:
                with self._lock:
                    order_paths = tuple(self._store.order_paths())
            else:
                order_paths = ()
            cfg = self._make_config(tuple(self.state.instructions),
                                    tuple(live),
                                    tuple(self.state.rulings),
                                    order_paths,
                                    tuple(self.state.rejections),
                                    tuple(self.state.intake_history))
            # Set on the config rather than passed through `_make_config`. Twenty callers build
            # that one, and several are `lambda *a, **k:` — which would accept a seventh argument
            # and drop it, leaving the server believing it had said "a person decided this" when
            # it had said nothing. A field that cannot be silently ignored, for a fact whose whole
            # job is to not be assumed.
            proceeded = self.state.proceeded
            if proceeded and proceeded[2] == self._brief_now():
                cfg = dataclasses.replace(cfg, unsafe_shown=(proceeded[1],),
                                          proceed_unsafe="POST /run/proceed")
            elif proceeded:
                note = ("what a seat called unsafe was read against an earlier brief "
                        f"({proceeded[2][0]} instruction(s), {len(proceeded[2][1])} "
                        "attachment(s)); the brief has changed, so that decision is retired and "
                        "the findings are shown again")
                if note not in self.state.retired_approvals:
                    self.state.retired_approvals.append(note)
            # **Whether this walk is an ask, said before the walk instead of only after it**
            # (CHG-20260907-27). This is the half the caller can answer — *"did the requirement
            # grow?"* — and it is the first conjunct of the append guard below, written out here
            # rather than shared, because the two live at two moments and `cli.cmd_run` decides
            # the same thing a third way, from the report. What matters is that the server's two
            # answers agree, and they do because they are one sentence read twice.
            #
            # It is **not** the whole question, and a first build of this record shipped as if it
            # were: the guard below took this half alone while `engine.walk` took this half AND
            # *"did this node open a session?"*, so on a `start` against a persisted journal the
            # counter said 1 and the sentence said 0. Both halves, in both places, from here on —
            # see the guard.
            #
            # CHG-20260904-05 stopped `attach` *counting* as an ask and left the engine still
            # adding one for the ask in flight, so two recorded asks and one attached file crossed
            # `intake.ASK_LIMIT`. Set on the config for the reason the comment above gives —
            # `_make_config` has twenty callers and several would silently drop an argument.
            #
            # **The two reads are separated by the walk and still cannot disagree**, and this is
            # the state machine's guarantee rather than luck. A draft of this comment described a
            # mid-walk `instruct` making them differ and called the divergence harmless; a review
            # seat measured that it is not reachable at all, which is worse than harmless in a
            # comment — a reader could take it as licence for a divergence that really would be.
            #
            # `start`, `instruct` and `attach` each set `state = "running"` under the lock before
            # calling `_advance`, and `instruct` refuses anything but `suspended`, `idle`,
            # `finished` or `stopped` — so no instruction can be added while a walk is in flight.
            # `attach` is the one method that can arrive mid-walk and it does not touch
            # `instructions`. `instructions_at_last_incomplete_stop` is written in one place, one
            # walk at a time. Both operands are therefore fixed for the whole walk.
            cfg = dataclasses.replace(
                cfg,
                intake_ask_in_flight=(len(self.state.instructions)
                                      > self.state.instructions_at_last_incomplete_stop))
            report = self._walk(cfg)
        except Exception as exc:                   # the run failed; say so rather than look idle
            with self._lock:
                self.state.state = engine.STOPPED
                self.state.error = f"{type(exc).__name__}: {exc}"
                self.state.version += 1
                self._publish()
                return self.state.snapshot()
        with self._lock:
            # **The walk succeeded, so the previous walk's failure is no longer true**
            # (CHG-20260903-34, conformance seat L-48). `state.error` was assigned at exactly
            # one site and cleared at none. `instruct` and `attach` reach `_advance` without
            # guarding on suspension, so an operator who added a line to the brief after a
            # failure got a **finished** run still carrying the error — and CHG-20260903-29,
            # which reported this defect as not reproducing, is what made the field reach the
            # page.
            #
            # Cleared on the success path only. Clearing it in `_advance` would erase the
            # message while the operator was still looking at it.
            self.state.error = ""
            # A stop for an incomplete requirement is counted here and nowhere else, so "asked three
            # times" is arithmetic over what happened rather than a feeling about it.
            #
            # **A walk is not an ask** (CHG-20260904-05, defect seat L-25). Measured, exactly
            # three methods can walk from an incomplete stop — `start`, `instruct` and `attach`;
            # `approve`, `reject` and `rule` are refused by `_require_suspension`, which
            # CHG-20260903-23 gave that shape. So the one wrong path is **`attach`**: attaching an
            # unrelated file read as *"asked twice"*, and a third crossed `intake.ASK_LIMIT` — at
            # which point `needs_options` leaves the ask-again path and the runner offers options
            # to somebody nobody asked again. A **behaviour** change, not a label.
            #
            # An ask is counted when the **requirement itself grew**, because that is what
            # `intake_review` reads and what "asked for and not supplied" is about. An attachment
            # reaches work orders as an artifact; it is not somebody supplying the aspect.
            #
            # *"`attach` never counts"* is a property of the **mark**, not of the method, and the
            # fourth round of this record is where that stopped being true: 100 of the sweep's
            # 2004 walks were an `attach` that recorded a stop, every one of them straight after a
            # same-brief restart that had left the mark behind. See the guard's own comment below.
            #
            # **And when a session was actually opened** (CHG-20260907-27, second round, codex
            # seat, blocking). "Did the requirement grow?" is half the question, and this guard
            # asked only that half while `engine.walk` asked both — so the two boxes on one page
            # answered differently on the path this record had declared unaffected. Measured,
            # `serve`'s journal lives at `token_dir/asks`, persists across processes, has no run
            # id and nothing clears it, so the same brief started again replays every seat — when
            # the journal's **last** intake walk was on exactly that brief, the clause the third
            # round adds because the journal keeps one order per ask id and the last walk
            # overwrote it. `start a, instruct b, restart, start a` compares a brief of `a`
            # against an order for `a + b` and re-asks everything; the row below is the case where
            # they match:
            #
            #     start, finish, start the same brief   resumed  asks  the tally  the <p>
            #     first start                                 0     3          1  asked once
            #     second start, before this line              3     3          1  asked 0 times
            #     second start, after it                      3     3          0  not asked yet
            #
            # `told > instructions_at_last_incomplete_stop` is **true** on that second start — the mark is
            # `-1` on a fresh `RunState` — so the stop was recorded and the counter said 1, while
            # the engine's conjunct said no session was opened and the sentence counted the ask
            # out. One box, two answers: the defect CHG-20260903-42 closed, reintroduced by this
            # record's own conjunct.
            #
            # So the **append** takes both halves — the mark below moves on the first alone, for
            # the reason written at the guard itself — and they are the same two numbers the engine
            # takes. `cli.cmd_run` already writes this half exactly this way; the engine measures
            # its own node's asks (`asks_before`/`resumed_before`), and at an incomplete intake
            # stop those start at zero because `intake_review` is the first asking node and
            # nothing routes a rejection back to it — the sentence `cmd_run`'s own comment carries.
            # `test_the_same_brief_started_twice_says_one_number` measures the agreement lap by
            # lap off the `in_flight` the engine actually walked with, rather than reading it out
            # of either of the two expressions that produce it.
            #
            # The rejected alternative was to put the resolved `in_flight` on `RunReport` and read
            # it here. It is the same behaviour — measured identical on the sequence above and on
            # `test_server`/`test_intake`/`test_cli`/`test_flow`/`test_schemas` — and it costs a
            # field on the report's **documented** shape: `docs/SCHEMAS.md` entry 13 and the
            # console's `NOT_ON_THE_CONSOLE` inventory both go red until a purely internal
            # engine-to-server handoff is entered in both. **Two catalogue lines, and no wire**
            # (CHG-20260907-27, third round, correcting this comment's own overstatement):
            # `RunReport.as_dict()` has no caller in `src/` — `cli.py` says so at its
            # `risk_settled` line — so the field would reach no client, and `NOT_ON_THE_CONSOLE`
            # already holds `resumed`, the field this guard reads. The reason to prefer the
            # conjunct is the shape, not the paperwork: a field whose only reader is two lines
            # downstream sits on a documented report for every later reader to account for.
            #
            # The escalation's own option ask cannot make this read true where it was false. The
            # reason this comment gave until CHG-20260907-27's third round — *"an option ask is
            # dispatched only where `in_flight` already held"* — is **not** that reason, because it
            # is false. `intake.needs_options` is `times_asked + (1 if in_flight else 0) >=
            # ASK_LIMIT`, and `recorded=3, in_flight=False` satisfies it. On the server it fires
            # that way: swept over every sequence of `instruct` / `attach` / same-brief restart up
            # to five operations, 2004 walks, 194 of them dispatching an option ask —
            #
            #     where the option ask fired  the engine's `in_flight`  this guard's `told > mark`
            #     `instruct`, 151 walks       True                      True
            #     `attach`, 43 walks          False                     False
            #
            # — so an option ask *is* dispatched with `in_flight` false, 43 times, and the guard
            # is still right. `in_flight` is a conjunction, so a false one is false in one of two
            # ways and each is closed on its own:
            #
            #   * the **caller's** half is false. Then `told > mark` above is the same falsehood,
            #     and the first conjunct has already refused the append — whatever the third says.
            #     This is the `attach` column.
            #   * the **node's** half is false: the survey was answered entirely out of the
            #     journal. Then the requirement cannot have grown, because a grown brief changes
            #     every work order and the journal keeps one order per ask id, so the orders
            #     mismatch and every seat is re-asked. The one walk where `told > mark` survives
            #     that is a replayed `start` — the mark is `-1` on a fresh `RunState` — and a fresh
            #     `RunState` has an empty `intake_history`, so `times_asked` is 0 and no option ask
            #     can be dispatched there at all. Measured: of the swept walks, 363 have
            #     `told > mark` with a fully resumed survey, every one of them a restart, every one
            #     with an empty history and no option ask.
            #
            # The conclusion survives; the sentence it was argued from did not. A reachability
            # claim the code does not support is the defect class this record exists to remove, and
            # ACC finding 5 blocked the same class here already — in the mirror direction, where a
            # comment described a race the state machine forbids. This direction is the worse of
            # the two: what it is offered to prove is true, so nothing downstream looks wrong.
            #
            # **This counts asks over the whole report; the engine counts them over one node.**
            # They are the same pair of integers only because `intake_review` is the first node
            # that asks anybody and nothing routes back to it — the sentence *"the engine
            # measures its own node's asks"* above rests on, carried again by `cmd_run`'s comment,
            # and pinned since the third round by
            # `test_nothing_asks_anybody_before_the_node_the_append_guard_counts_over`.
            #
            # **The mark moves on its own condition; only the append takes the third conjunct**
            # (CHG-20260907-27, fourth round, blocking on behaviour). The two shared one `if`
            # until here, and the conjunct the round above added therefore stopped the mark as
            # well as the append. Every walk in this sweep, on the axis the round above did not
            # tabulate — `op` x *declared an ask* x *recorded a stop*, rather than `op` x *an
            # option ask fired*:
            #
            #     op         declared  recorded  walks     shipped     after this line
            #     start      True      True        363     correct     unchanged
            #     instruct   True      True        547     correct     unchanged
            #     restart    True      False       363     correct     unchanged, mark now moves
            #     restart    True      True        184     correct     unchanged
            #     attach     False     False       447     correct     unchanged
            #     attach     True      True        100     **wrong**   declared False, no append
            #
            # The last row is the defect. A replayed `start` — a fresh `RunState`, so the mark is
            # `-1`, and a journal whose last intake walk was this brief, so every seat is answered
            # out of it — correctly records nothing, and left the mark at `-1`. The next `attach`
            # then read `1 > -1`, was declared an ask by the same expression at the top of this
            # method, and appended: the console said *"asked once"* after `POST /attachments`, and
            # `docs/API.md`'s *"`POST /attachments` moves neither once an incomplete stop has been
            # reached at this instruction count — recorded, or replayed out of the journal by a
            # same-brief restart"* was false on 100 of the 2004 walks. (That line
            # is qualified *per instruction count* because of the other narrowing, which is not
            # this record's. The mark is written only under `incomplete`, so a walk that completes
            # leaves it where it was, and the next attach at the same count appends — correctly,
            # nobody had been asked at that count and that walk asked. Measured in the sixth round:
            # `start` incomplete at 1, `instruct` completing at 2, `attach` at 2 appends; the
            # control, an attach at a count that already has an incomplete stop, does not. It is
            # CHG-20260904-05's residue — that record put the mark under a gate CHG-20260823-13
            # already had — and `3a8caf2` reads the same only because this record did not touch
            # it; `3a8caf2` is younger than CHG-20260904-05 and can attribute nothing.) That attach walk really does open
            # sessions — its artifact changes every order, so no seat is replayed and the third
            # conjunct is true — which is why guarding the append alone never caught it. What was
            # false is the **first** conjunct, read off a mark that had stopped moving.
            #
            # It is `CHG-20260904-05`'s defect, the tally moving on an attachment, on the path
            # this record opened. At `3a8caf2` and `28afbc2` the replayed `start` still set the
            # mark, so the attach after it read `1 > 1`: a regression the round above introduced
            # and its own sweep hid.
            #
            # So the mark records **what the seats last read**, which is why it is no longer
            # spelled `instructions_when_last_asked`: a replayed walk asks nobody and still leaves
            # every seat's answer standing against that brief, so the requirement has not grown
            # since. `told > mark` is *"has it grown since the last incomplete stop?"* — and that
            # question is unchanged by whether a session was opened. It was written *"since the
            # answers in hand were given"* here until the eighth round: the sixth round replaced
            # that gloss at the field and missed this copy, which straddles a line break and
            # survived the grep that found the other one. A phrase split across two lines is not
            # found by a search for the phrase.
            stop = report.suspended or {}
            told = len(self.state.instructions)
            if stop.get("incomplete") and told > self.state.instructions_at_last_incomplete_stop:
                self.state.instructions_at_last_incomplete_stop = told
                if len(report.resumed) < len(report.asks):
                    self.state.intake_history.append(
                        {"missing": list(stop.get("missing") or ())})
            self.state.report = report
            self.state.state = report.state
            self.state.version += 1
            self.state.log = [{"node_id": a.node_id, "role": a.role, "seat": a.seat,
                               "model": a.model} for a in report.asks]
            self._publish()
            return self.state.snapshot()


def make_handler(runner: Runner, operator: Operator,
                 registry: Optional["models_mod.Registry"] = None,
                 registry_path: Optional[Path] = None,
                 assignments: Optional[Mapping[str, object]] = None,
                 db=None, plan_assignments: Optional[Mapping[str, object]] = None,
                 assignment_source: Optional[Mapping[str, str]] = None):
    """The HTTP surface. Refuses before it reads, in the order the threat model requires."""

    held = {"registry": registry if registry is not None else models_mod.Registry(),
            "assignments": dict(assignments or {}),
            "plan": dict(plan_assignments or {}),
            # **Seeded, not empty** (CHG-20260903-39, defect seat L-51). `cmd_serve`
            # computes this map with `store.resolve` and dropped it, so `held["source"]`
            # stayed `{}` until the first config *write* — and `GET /config/nodes` on a
            # freshly started server answered `"source": {}` against `docs/API.md`'s own
            # *"an override nobody can see is worse than no override"*.
            "source": dict(assignment_source or {})}
    #: `held` is read-modify-written from request threads, and `ThreadingHTTPServer` gives each
    #: request its own. `held["registry"] = held["registry"].add(model)` is exactly the shape that
    #: loses a write: two concurrent `POST /models` both read the same base registry, both add, the
    #: last save wins, and **both callers are told 200**.
    #:
    #: A seat found it. The lock on the SQLite connection secured the database and left the
    #: in-memory half of the same state unguarded — half a concurrency story reads as a whole one.
    held_lock = threading.RLock()

    #: **The one order every path takes these locks in**, outermost first:
    #:
    #:     runner._lock  ->  held_lock  ->  the store connection's runner_lock
    #:
    #: Any path that takes two of them must take them in this order. Two orderings deadlock, and
    #: this file had two for exactly one round: `_config_edit` reached the store before `held`, and
    #: `POST /models` reached `held` before the store.
    LOCK_ORDER = ("runner._lock", "held_lock", "store.runner_lock")

    def _reassign():
        # Callers hold `held_lock`. Stated rather than assumed: a seat found this writing
        # `held["assignments"]` and `held["source"]` outside it while `held["registry"]` was
        # guarded — half a lock reads as a whole one.
        """Re-merge plan and store after an edit, and refresh the provenance.

        The plan wins where it says something; the store fills where it is silent. Recomputed after
        every write rather than cached, because a console showing a stale merge would be reporting
        an assignment that is not the one the next run will use.
        """
        stored = {"node_models": store_mod.node_models(db),
                  "seat_models": store_mod.seat_models(db)} if db is not None else {}
        merged, source = store_mod.resolve(held["plan"], stored)
        held["assignments"] = merged
        held["source"] = source
        return {**merged, "source": source}

    def _config_edit(body, write):
        """Check the version, write, and advance it — **without letting go in between.**

        The first correction did all three and released the lock between each, which is a
        check-then-act window a seat named precisely: two threads validate version N, both write,
        both bump, and the double-submit the version exists to refuse happens anyway. `edit()` holds
        the runner's lock across the whole sequence, so the check is worth making.

        A configuration edit **is** a state change: it advances the version and wakes every
        listener. That invalidates an answer another tab was about to send, and that is right — the
        configuration moved under them.
        """
        if db is None:
            raise ServerError("this runner has no assignment store; start `serve` with one")

        def under_lock():
            # `held_lock` **before** the store's lock, never after. See LOCK_ORDER.
            #
            # The first version of this function took the store's lock inside `write()` and only
            # then took `held_lock`, while `POST /models` took `held_lock` first and the store's
            # lock second. Two orderings is a deadlock waiting for two requests: one thread holding
            # `held_lock` and waiting for the store, another holding the store and waiting for
            # `held_lock`.
            #
            # Introduced by the fix for the check-then-act window one round earlier — the fix
            # having the defect is this repository's most-recorded shape, and it is why the order
            # is now a stated rule rather than whatever each call site happened to do.
            with held_lock:
                try:
                    write()
                except store_mod.StoreError as exc:
                    raise ServerError(str(exc))
                return _reassign()

        out = runner.edit(body.get("version"), under_lock)
        return {**out, "version": runner.state.version}

    def _assign_node(body):
        node_id = str(body.get("node_id") or "")
        raw = body.get("models")
        if not isinstance(raw, list):
            raise ServerError("`models` must be a list of model ids — an empty one clears the node")
        return _config_edit(
            body, lambda: store_mod.set_node_models(db, node_id, [str(m) for m in raw]))

    def _assign_seat(body):
        seat = str(body.get("seat") or "")
        model_id = body.get("model_id")
        return _config_edit(
            body, lambda: store_mod.set_seat_model(db, seat, str(model_id) if model_id else None))

    def _route_halt(body):
        """Who a permanent halt of one kind reaches first, for this project (CHG-20260827-19).

        A blank or missing `recipient` clears the row, returning that kind to `policy.HALT_ROUTING`
        and, failing that, to the operator. The **kind** is validated in the store and the recipient
        is not: an organisation names its own functions, and a table accepting only this runner's
        five would be unusable by the organisations it exists for.
        """
        kind = str(body.get("kind") or "")
        recipient = body.get("recipient")
        return _config_edit(
            body,
            lambda: store_mod.set_halt_recipient(
                db, kind, str(recipient) if recipient else None))

    if db is not None:
        # Read the registry back out of the store, where the store has one.
        #
        # Without this a caller that passes `db` and no registry gets an empty one -- and the
        # console then shows **no models** while the assignments reference them by id. Found by
        # driving the real server: the assignment survived a restart and the model list came back
        # `[]`, which is precisely the "assignable and invisible" split this module's own comment
        # on `POST /models` warns about, arriving from the other direction.
        try:
            stored_registry = store_mod.load_registry(db)
        except Exception as exc:                 # noqa: BLE001 - a bad row must not kill startup
            raise ServerError(f"the assignment store's registry could not be read: {exc}")
        if len(stored_registry):
            held["registry"] = stored_registry
        elif len(held["registry"]):
            store_mod.save_registry(db, held["registry"])
        _reassign()

    class Handler(BaseHTTPRequestHandler):
        #: How long a connection may hold a thread without saying anything.
        #:
        #: `ThreadingHTTPServer` gives every connection its own thread and, without this, that
        #: thread waits forever. Measured: 20 bare connections that sent **nothing at all** held
        #: 20 threads, and a request already refused with 401 kept its thread for as long as the
        #: socket stayed open. So this is not a property of `_body` — bounding the body alone
        #: would have left both of those exactly as they were.
        #:
        #: Closing the client socket released every one, and `shutdown()` took 0.00s, so what
        #: this bounds is "one thread per open connection" rather than a leak.
        #:
        #: 30 seconds, because a legal at-limit upload — 33.3 MB on the wire — was measured at
        #: 0.37s. Not a flag: the sentence that keeps the bind address off the command line
        #: applies here too, and a timeout somebody can lower is one that gets lowered until a
        #: slow disk fails a legal upload (CHG-20260906-02).
        timeout = 30
        server_version = "ai-sdlc-runner"
        protocol_version = "HTTP/1.1"

        # -- refusals ----------------------------------------------------------------------
        def _guard(self) -> bool:
            if urlsplit(self.path).path in ("/", "/index.html"):
                # The shell only. Still loopback-checked below; just not token-checked, because
                # nothing can present a token before it has loaded the page that stores one.
                return _loopback_host(self.headers.get("Host")) or self._refuse_host()
            if not _loopback_host(self.headers.get("Host")):
                # First, and before anything is parsed: a non-loopback Host on a loopback socket is
                # DNS rebinding, and the request should not get as far as being understood.
                self._json(403, {"error": "this server answers only to a loopback host"})
                return False
            origin = self.headers.get("Origin")
            if origin and not _loopback_origin(origin):
                self._json(403, {"error": f"cross-origin request from {origin} refused"})
                return False
            presented = self.headers.get("X-Operator-Token")
            if presented is None and urlsplit(self.path).path == "/run/events":
                # EventSource cannot set headers -- the browser API simply has no way to. So the
                # stream, and only the stream, accepts the token as a query parameter. It is a
                # weaker place to carry a credential (it reaches access logs), which is why it is
                # this one route and not a general fallback: the stream is read-only and the token
                # is per-process, so the blast radius of a logged one is a session somebody can end
                # by restarting the server.
                presented = (parse_qs(urlsplit(self.path).query).get("token") or [None])[0]
            if not operator.accepts(presented):
                self._json(401, {"error": "no operator token. It is in "
                                          f"{operator.token_path}, readable by you alone."})
                return False
            return True

        def _refuse_host(self) -> bool:
            self._json(403, {"error": "this server answers only to a loopback host"})
            return False

        # -- plumbing ----------------------------------------------------------------------
        def _json(self, code: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> Dict[str, object]:
            """The request body, bounded **before** it is read.

            Every POST comes through here ahead of route dispatch, so none of this is about
            attachments: a 500 MB body aimed at `/run/instruct` was read in full just as
            happily, and `/attachments` was the only route with any limit underneath it.
            """
            raw_length = self.headers.get("Content-Length") or "0"
            try:
                length = int(raw_length)
            except ValueError:
                # `int(...)` sat outside the try, so a header a client typed wrong left as a
                # 500 — the code `docs/API.md` reserves for *unforeseen* failures. A header this
                # server can read and reject is a 409, which is already the answer a body that
                # is not JSON gets.
                raise ServerError(
                    f"Content-Length is {raw_length!r}, which is not a number of bytes")
            if length < 0:
                # `int("-1")` parses, `not -1` is False, and `rfile.read(-1)` reads to EOF, so
                # a negative length was the stalled-body case wearing a different hat.
                raise ServerError(
                    f"Content-Length is {length}, and a request body cannot be shorter than "
                    f"nothing")
            if length > MAX_BODY_BYTES:
                # Refused **before** the read, and the connection closed rather than drained:
                # reading the thing in order to reject it is the defect itself, and whatever is
                # left on the wire would otherwise be parsed as the next request.
                self.close_connection = True
                raise BodyTooLarge(
                    f"the request body is {length} bytes; the limit is {MAX_BODY_BYTES}")
            if not length:
                return {}
            try:
                data = self.rfile.read(length)
            # Both spellings on purpose: `socket.timeout` only became an alias of
            # `TimeoutError` in Python 3.10, and CI runs 3.9. Naming only the modern one made
            # this fall through to the 500 handler on 3.9 while passing on 3.13 — a difference
            # the local suite could not show, because it runs one interpreter.
            except (TimeoutError, socket.timeout):
                self.close_connection = True
                raise ServerError(
                    f"Content-Length promised {length} bytes and they did not arrive")
            if len(data) < length:
                self.close_connection = True
                raise ServerError(
                    f"Content-Length promised {length} bytes and {len(data)} arrived")
            try:
                body = json.loads(data.decode("utf-8"))
            except ValueError as exc:
                raise ServerError(f"the request body is not JSON: {exc}")
            if not isinstance(body, dict):
                # Every caller reaches for `body.get(...)` on the next line, so a JSON array
                # parses here and fails there as an AttributeError — a 500 for something this
                # server understood perfectly well.
                raise ServerError(
                    f"the request body is a JSON {type(body).__name__}, and every route here "
                    f"reads named fields from an object")
            return body

        def log_message(self, fmt, *args):          # pragma: no cover - quiet by default
            pass

        # -- routes ------------------------------------------------------------------------
        def do_GET(self):                           # noqa: N802 - http.server's spelling
            if not self._guard():
                return
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                self._console()
            elif path == "/flow":
                self._json(200, {"nodes": [
                    {"id": n.id, "kind": n.kind, "label": n.label, "role": n.role,
                     "gate": n.gate, "gate_when": n.gate_when, "mode": n.mode,
                     "main": n.main, "follows": n.follows, "rejects_to": n.rejects_to,
                     "branches": dict(n.branches), "next": n.next,
                     "permanent": n.permanent}
                    for n in graph.NODES],
                    "gates": {g: dict(v) for g, v in policy.GATES.items()},
                    "modes": list(graph.MODES)})
            elif path == "/run":
                self._json(200, runner.state.snapshot())
            elif path == "/run/events":
                self._stream()
            elif path == "/models":
                # The console is local only; the models need not be, and the operator should never
                # have to read a hostname to find that out. `leaving` is the answer to "what goes
                # out from here", stated rather than derivable.
                reg = held["registry"]
                self._json(200, {**reg.as_dict(),
                                 "leaving": [m.id for m in reg.leaving()]})
            elif path == "/attachments":
                self._json(200, {"attachments": [a.as_dict() for a in runner.state.attachments],
                                 "missing": list(runner.state.missing)})
            elif path == "/config/nodes":
                # The question a registry cannot answer: where does this model get *used*? A model
                # listed and used nowhere looks configured, and a model on eight nodes looks the
                # same in a list as one on a single node.
                node_models = dict(held["assignments"].get("node_models") or {})
                seat_models = dict(held["assignments"].get("seat_models") or {})
                reg = held["registry"]
                known = {m.id: m for m in reg}
                by_model = {}
                for node_id, ids in node_models.items():
                    mode = graph.BY_ID[node_id].mode if node_id in graph.BY_ID else None
                    for model_id in ids:
                        entry = by_model.setdefault(
                            model_id, {"nodes": [], "seats": [], "known": model_id in known})
                        entry["nodes"].append({"node_id": node_id, "mode": mode})
                for seat, command in seat_models.items():
                    # A seat naming a registry model lands in that model's bucket rather than
                    # inventing a second entry for the same backend under its command line.
                    label = (command if isinstance(command, str) and command in known
                             else " ".join(command) if isinstance(command, (list, tuple))
                             else str(command))
                    entry = by_model.setdefault(
                        label, {"nodes": [], "seats": [], "known": label in known})
                    entry["seats"].append(seat)
                # Models the project has and nothing uses. Said out loud, because "configured" and
                # "used" look identical in a list and only one of them does anything.
                for model_id in known:
                    by_model.setdefault(model_id, {"nodes": [], "seats": [], "known": True})
                self._json(200, {
                    "node_models": node_models,
                    "seat_models": {k: (" ".join(v) if isinstance(v, (list, tuple)) else str(v))
                                    for k, v in seat_models.items()},
                    "by_model": by_model,
                    "models": [m.as_dict() for m in reg],
                    # Which source put each assignment there. An override nobody can see is worse
                    # than no override: the plan wins over the store, and a console that showed the
                    # merged result with no provenance could not say that it had. **The shipped
                    # console is that console** — it draws `by_model` and no provenance at all
                    # (CHG-20260907-28). Sent for a client that wants it, and for the view that
                    # nobody has built yet.
                    "source": dict(held.get("source") or {}),
                    # Which modes do anything with a list, for a client that wants to refuse a node
                    # before it posts; `POST /config/nodes` refuses the same node anyway. **No
                    # shipped console reads this.** This comment said the console greys out the rest
                    # from the day the key shipped, and the console has never had a per-node
                    # configure control to grey (CHG-20260907-28).
                    "assignable": list(store_mod.MODES_THAT_USE_MODELS),
                })
            elif path == "/whoami":
                self._json(200, {"operator": operator.name})
            else:
                self._json(404, {"error": f"no route {path}"})

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
                  # The same staleness check. A seat pointed out this route was still taking any
                  # integer while the two beside it had been fixed — the fix stopped one route
                  # short of the one that writes a file.
                  runner.require_version(version)
                  with held_lock:
                    try:
                        added = held["registry"].add(
                            models_mod._model_from(dict(body.get("model") or {})))
                    except models_mod.ModelError as exc:
                        raise ServerError(str(exc))
                    # The store first, because it is the one that can refuse. Writing the file and
                    # memory before it is what turned a foreign-key refusal into three copies
                    # disagreeing, with the console showing a model the store had never accepted.
                    if db is not None:
                        try:
                            store_mod.save_registry(db, added)
                        except store_mod.StoreError as exc:
                            raise ServerError(str(exc))
                    held["registry"] = added
                    if registry_path is not None:
                        models_mod.save(held["registry"], registry_path)
                    reg = held["registry"]
                    out = {**reg.as_dict(), "leaving": [m.id for m in reg.leaving()]}
                  runner.publish_config_change()
                  out = {**out, "version": runner.state.version}
                elif self.path == "/run/proceed":
                    out = runner.proceed(version, body.get("node_id"))
                elif self.path == "/run/reject":
                    out = runner.reject(version, str(body.get("gate") or ""),
                                        body.get("node_id"), str(body.get("reason") or ""))
                elif self.path == "/run/instruct":
                    out = runner.instruct(version, str(body.get("instruction") or ""))
                elif self.path == "/attachments":
                    import base64
                    try:
                        raw = base64.b64decode(str(body.get("data") or ""), validate=True)
                    except Exception as exc:
                        raise ServerError(f"the attachment body is not valid base64: {exc}")
                    out = runner.attach(version, str(body.get("filename") or ""), raw)
                elif self.path == "/config/nodes":
                    out = _assign_node(body)
                elif self.path == "/config/seats":
                    out = _assign_seat(body)
                elif self.path == "/config/halts":
                    out = _route_halt(body)
                elif self.path == "/run/decide":
                    out = runner.rule(version, str(body.get("node_id") or ""),
                                      str(body.get("branch") or ""))
                else:
                    self._json(404, {"error": f"no route {self.path}"})
                    return
            except BodyTooLarge as exc:
                self._json(413, {"error": str(exc)})
                return
            except ServerError as exc:
                self._json(409, {"error": str(exc)})
                return
            except Exception as exc:
                # Anything unforeseen still gets an answer. Without this the handler thread dies,
                # the socket closes, and the client sees `RemoteDisconnected` — a failure with no
                # message, which sends whoever is debugging it to the network rather than to the
                # traceback. Found live: a missing store directory took down the request instead of
                # reporting itself.
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            self._json(200, out)

        def _console(self):
            """The page itself. Served without a token, and it holds nothing that needs one.

            A browser cannot present a credential for the very first request -- it has no way to
            attach a header to a navigation -- so the shell is public and the API is not. The page
            carries no data, no state and no governance; it is markup that asks the server what is
            true. The token reaches it through the URL fragment, which browsers never send anywhere.
            """
            page = Path(__file__).parent / "console" / "index.html"
            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # It talks to itself and nothing else, and says so rather than relying on being asked.
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

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
          registry_path: Optional[Path] = None,
          assignments: Optional[Mapping[str, object]] = None,
          db=None, plan_assignments: Optional[Mapping[str, object]] = None,
          assignment_source: Optional[Mapping[str, str]] = None
          ) -> ThreadingHTTPServer:
    """Build the server, refusing any host that is not this machine.

    The refusal is here rather than in the caller because a bind address is exactly the kind of thing
    that gets "temporarily" widened and never narrowed again.
    """
    if host not in LOOPBACK:
        raise ServerError(
            f"refusing to bind {host!r}. This runner merges branches and answers gates; it listens "
            f"on {' or '.join(LOOPBACK)} and nowhere else. If another machine needs to see it, put "
            f"something in front of it that you have decided to trust — do not widen this.")
    class _OneRunner(ThreadingHTTPServer):
        """One project, one runner — and now something enforces it.

        ``ThreadingHTTPServer`` sets ``allow_reuse_address``, which on Windows lets a **second**
        process bind a port the first is already listening on. Both then answer, and which one
        receives a given connection is undefined. That was found by starting a second `serve` during
        a live test and watching the console get answers from the process that had been replaced —
        a stale build serving requests, with nothing anywhere saying so.

        "One project, one runner" was a sentence in a record that nothing checked. Now a second
        `serve` on a busy port fails to bind, loudly, which is the only version of that sentence
        worth having.
        """

        allow_reuse_address = False

        #: How many connections the OS holds for us between `accept` calls.
        #:
        #: `socketserver` defaults this to **5**, and a full backlog is not a queue that grows.
        #: The next connection is not answered at all: the SYN is dropped, the client retransmits,
        #: and the RST follows that -- so it surfaces as `WinError 10061` / `ECONNREFUSED`, the
        #: same error as a port with nothing listening, **after about two seconds** rather than
        #: at once. Measured on this class, acceptor not draining:
        #:
        #:     listen(5)                 5 held    the 6th refused after 2.03s
        #:     listen(128)             128 held    the 129th, 2.03s
        #:     listen(200)             200 held
        #:     listen(201)             200 held    <- Windows clamps here
        #:     listen(socket.SOMAXCONN) 200 held    the constant is 2147483647 and is truncated
        #:
        #: **128, bounded from both sides**, which is the argument the number needs: above the
        #: largest burst anything here makes (eight pool workers, twenty in the test that pins
        #: this), and below the 200 the platform will silently truncate to. `SOMAXCONN` was the
        #: other seat's proposal and would write a value Windows quietly rewrites; on Linux the
        #: cap is `net.core.somaxconn`, read and not measured here.
        #:
        #: An earlier draft said 128 **because `http.server.HTTPServer` uses it**. It does not --
        #: neither `HTTPServer` nor `ThreadingHTTPServer` overrides this attribute on any
        #: supported version, and both inherit the 5. The citation was invented; a seat checked
        #: what I had not.
        #:
        #: The acceptor is one Python thread and does not have to be absent to be starved: it
        #: competes for the GIL with every handler thread it has already spawned. Measured with
        #: `serve_forever` running and eight spinner threads beside it, a burst of twenty draws
        #: 51 refusals in 200 connects at 5 and none at 128. What the depth buys is that a refusal
        #: becomes a wait, not that a loaded server answers quickly (CHG-20260907-22).
        request_queue_size = 128

    try:
        return _OneRunner((host, port),
                          make_handler(runner, operator, registry, registry_path, assignments,
                                       db=db, plan_assignments=plan_assignments,
                                       assignment_source=assignment_source))
    except OSError as exc:
        # Only what the errno establishes. This branch used to say "something is already there"
        # for every failure a socket can have, and `socket.gaierror` is an `OSError` — so the
        # `::1` this list used to permit produced a resolver answer reported as a port conflict.
        #
        # Two branches and not four: `EADDRINUSE` is the one cause an errno establishes and the
        # one this repository has a test for. The rest carry the operating system's own sentence
        # and no diagnosis — and `EACCES` is the case that shows why. It is reported as a port
        # reserved by something else on Windows and as a port below 1024 on Linux, so any advice
        # this file wrote for it would be wrong on half the machines it runs on. Neither cause
        # was reproducible here: `netsh interface ipv4 show excludedportrange protocol=tcp`
        # lists nothing on the machine this was written on.
        #
        # `paths.plain_in(str(exc))` is the load-bearing half of that argument, not decoration:
        # remove it and the branch says only which address failed. `bind` mutation 5 is there
        # because removing it was caught by nothing when this shipped.
        if exc.errno == errno.EADDRINUSE:
            raise ServerError(
                f"cannot listen on {host}:{port} — {paths.plain_in(str(exc))}. Something is "
                f"already there. If it is another `runner serve`, stop it first: two runners on "
                f"one port answer at random, and you would be reading one while driving the "
                f"other.")
        raise ServerError(f"cannot listen on {host}:{port} — {paths.plain_in(str(exc))}.")
