"""conversations.py — every conversation stored, categorised by project (CHG-20260823-17).

The design brief is [`docs/design/conversation-store.md`](../../docs/design/conversation-store.md);
both seats' verdicts on it are in `docs/design/reviews/`. **Both returned `not sound` on the first
version, and both named the same sentence** — that the store could be *derived* from the
`AskJournal`. It cannot, for two reasons that between them define this module:

1. The journal has never held an **operator turn**. `journal.record` and `journal.answered` are its
   only two writers; confirmations, rejections and rulings reach only the in-memory `RunReport`. A
   store derived from it would have been the model-side-only store the brief itself said would have
   thrown away half of what a reader comes for.
2. The journal **destroys** the model turns it does have. Its ids are positional and `record`
   overwrites unconditionally, so two runs in one journal directory leave one entry:

   ```
   two fresh runs, one journal directory  ->  entries: 1
   what survives                          ->  {"brief": "SECOND RUN"}
   ```

So the journal and this module are not two writers of one fact. The journal records *"what is the
current question at position N"* — a resume index, mutable by design. This records *"what happened,
in order"* — append-only, never rewritten. A crashed run has everything up to the crash.

## seq is an integer

Not a zero-padded filename. The journal sorts by name and `'%03d' % 1000` sorts between the 100th
and the 101st ask, which fable-seat found and which a store presenting "the ordered sequence of
turns" would have inherited for free.

## Nothing an operator types becomes a path

`attachments.py`'s rule, one layer out: the project **name** is data and the project **id** is a
hash. A resolved journal path contains a colon and separators on Windows and is not a filename on
any platform; an operator-chosen project name can contain anything at all.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

#: Bumped when the shape of a stored turn changes in a way a reader must know about. Written into
#: every header, because a document that cannot say which shape it is has to be guessed at.
SCHEMA = 1

#: Every kind of turn. A conversation is asks **and** decisions — a person answering is as much a
#: turn as a model answering, and the first design chose a source that had never held one.
OPENED = "opened"
INSTRUCTION = "instruction"
ASK = "ask"
ANSWER = "answer"
UNANSWERED = "unanswered"
DECISION = "decision"
RELAXATION = "relaxation"
NOTE = "note"
CLOSED = "closed"
KINDS = (OPENED, INSTRUCTION, ASK, ANSWER, UNANSWERED, DECISION, RELAXATION, NOTE, CLOSED)

#: The three backends the user asked for — *「提供所有選擇的可能性」*. A backend whose package is
#: missing **refuses by name**; it never falls back to ``file``. "I asked for Mongo and got a
#: directory" is this repository's oldest mistake wearing a config field.
BACKENDS = ("file", "tinydb", "mongo")

#: How much of the project-name hash becomes a directory. 128 bits, and the reason is the same one
#: `attachments.py` records: a full sha256 is 64 characters, and added to a project path of any
#: depth that crosses Windows' 260-character limit — which Windows then reports as
#: ``FileNotFoundError`` about a directory that demonstrably exists.
ID_CHARS = 32

#: Excel stops reading a cell here and says nothing. A work order serialised into one cell passes
#: this routinely, so a CSV export that promised visibility would lose the end of exactly the rows
#: a reader cared about. The data is written whole and the row is flagged.
SPREADSHEET_CELL_LIMIT = 32767

#: A cell starting with any of these executes as a formula when the file is opened in a
#: spreadsheet, and ``=HYPERLINK(...)`` is an exfiltration channel — reached, in a local-only
#: project, through the export whose stated purpose is to be opened in a spreadsheet.
FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")

#: The **only** Mongo URI options that may appear without `--store-remote allow`, lower-cased.
#:
#: An allowlist, and the reason is a finding: the first version refused `replicaSet` and
#: `directConnection=false` by name and passed everything else straight to `MongoClient`. A seat
#: found `?proxyHost=attacker.example&proxyPort=1080` accepted — the seed host stays loopback while
#: the driver sends the whole connection through a SOCKS proxy off this machine. A denylist answers
#: "safe" about every option nobody thought of, which is this repository's second-most-frequent
#: defect written as a config field.
#:
#: Matched case-insensitively, because Mongo's option parsing is and the same seat showed
#: `?replicaset=rs0` walking past the check that refused `replicaSet=rs0`.
MONGO_OPTIONS = frozenset({
    "directconnection", "authsource", "appname", "connecttimeoutms", "sockettimeoutms",
    "servselectiontimeoutms", "serverselectiontimeoutms", "maxpoolsize", "minpoolsize",
    "retrywrites", "retryreads", "w", "journal", "readpreference", "uuidrepresentation",
})

#: What counts as loopback in a Mongo URI. Same set the server uses for `Origin`, and for the same
#: reason; see `local_mongo_uri` for why the analogy stops there.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: The marker written beside a journal so a resumed walk re-attaches to the conversation it started
#: rather than minting a second one. The journal directory is already the one durable place a run
#: has, so this invents no new authority — it uses the one that exists.
MARKER = ".conversation"


class ConversationError(Exception):
    """Refused. Never raised for a store write that failed — see `Conversation.write_errors`."""


def project_id(name: str) -> str:
    """A directory name that cannot be anything else.

    The first design defaulted the project to the plan file's parent directory, and both seats named
    it: that files every ``examples/plan.json`` run under a project called *"examples"*, and `serve`
    may have no plan at all. A location is not an identity — so the name is required, and it is
    stored as **data** while a hash of it is what touches the filesystem.
    """
    if not isinstance(name, str) or not name.strip():
        raise ConversationError(
            "a project name is required: it is what the conversation is categorised by, and there "
            "is no fact available to default it from — a plan's parent directory is a location, "
            "not a project")
    return hashlib.sha256(name.strip().encode("utf-8")).hexdigest()[:ID_CHARS]


def new_conversation_id() -> str:
    return uuid.uuid4().hex[:ID_CHARS]


def local_mongo_uri(uri: str) -> str:
    """Refuse a Mongo URI that would take the conversation off this machine, and return it hardened.

    **The host check alone does not constrain the driver**, which is what both seats refused about
    the first design. `MongoClient` performs topology discovery: given a loopback seed that turns
    out to be a replica-set member or a `mongos`, it reads the topology *from the server* and
    connects to every member it learns of, including remote ones, without consulting the URI again.
    A host check would answer "local" about a URI while the driver went off-machine — a coarse check
    answering safe about something it had not examined, which is the second-most-frequent defect in
    this repository's record.

    So five things hold, and only the last one constrains the client:

    1. scheme is ``mongodb`` — ``mongodb+srv://`` is a DNS seedlist lookup by construction
    2. exactly one host
    3. the host is loopback, **or** a percent-encoded unix socket path — genuinely local, allowed
    4. no ``replicaSet=``
    5. ``directConnection=true`` is forced

    Out of scope, and said rather than implied: an SSH tunnel is loopback at the socket and remote
    at the destination, and no URI can tell. The threat model is a URI somebody pasted, not a
    determined operator.
    """
    if not isinstance(uri, str) or not uri.strip():
        raise ConversationError("a mongo store needs a URI")
    text = uri.strip()
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        # A malformed URI is refused, never raised through. `urlsplit` raises `Invalid IPv6 URL` on
        # some inputs under some Pythons and not others — CI found that in CHG-20260823-16 after it
        # passed on one interpreter, and which inputs raise is not something one Python can tell you.
        raise ConversationError(f"refused: not a URI this can check ({exc})") from None
    if parts.scheme == "mongodb+srv":
        raise ConversationError(
            "refused: mongodb+srv:// resolves its hosts from DNS, so nothing in the URI says where "
            "the data goes. Use mongodb:// with a loopback host, or --store-remote allow")
    if parts.scheme != "mongodb":
        raise ConversationError(f"refused: {parts.scheme or '(none)'}:// is not a mongo URI")
    netloc = parts.netloc.rsplit("@", 1)[-1]
    if "," in netloc:
        raise ConversationError(
            "refused: several hosts. One of them being loopback says nothing about the others")
    try:
        host = (parts.hostname or "").lower()
    except ValueError as exc:
        raise ConversationError(f"refused: not a host this can check ({exc})") from None
    socket_path = _unix_socket(netloc)
    if not socket_path:
        # The host must **round-trip**, not merely parse. `urlsplit` reads
        # `mongodb://[::1].evil.example` as host `::1` and silently drops the rest, so a hostname
        # check alone accepts a domain an attacker registers. This is the same defect CI caught in
        # `server._loopback_origin` two changes ago, and it was already present here until a test
        # written for that finding was pointed at this function.
        literal = f"[{host}]" if ":" in host else host
        port = f":{parts.port}" if parts.port else ""
        if f"{literal}{port}" != netloc.lower():
            raise ConversationError(
                f"refused: {netloc!r} is not a host this can check. It parses to {host!r} and the "
                f"rest is dropped, which is how a lookalike domain gets read as loopback.")
    if not socket_path and host not in LOOPBACK_HOSTS:
        raise ConversationError(
            f"refused: {host or '(no host)'} is not loopback. The whole operating flow is "
            f"local-only; a conversation carries every work order and every instruction verbatim. "
            f"Pass --store-remote allow to send it there anyway, and it is recorded.")
    query = {k.lower(): v for k, v in
             parse_qs(parts.query, keep_blank_values=True).items()}
    unknown = sorted(set(query) - MONGO_OPTIONS)
    if unknown:
        raise ConversationError(
            f"refused: {', '.join(unknown)} — this checks an allowlist, because a rule that names "
            f"the dangerous options answers 'safe' about every option nobody thought of. "
            f"`proxyHost` is the one that showed it: a loopback seed and the whole connection "
            f"through somebody else's SOCKS proxy. Pass --store-remote allow to skip the checks, "
            f"and it is recorded.")
    if query.get("directconnection", ["true"])[0].lower() == "false":
        raise ConversationError(
            "refused: directConnection=false lets topology discovery widen the connection past the "
            "host you named")
    return text


def _unix_socket(netloc: str) -> bool:
    """Is this netloc a unix socket path, rather than a name that merely looks like one?

    **A `.sock` suffix is not a socket and a `%2f` anywhere is not a path.** The first version tested
    exactly that, and a seat got `mongodb://remote.evil.sock` accepted without `--store-remote
    allow`: a registrable DNS name, which the driver resolves and dials over TCP, classified as
    "genuinely local" on the strength of how it ends. `mongodb://remote.evil.example%2f:27017`
    passed the same way. Both skipped the loopback test entirely, because the check that decides
    *whether* to apply the loopback test was the coarse one.

    A unix socket in a MongoDB URI is a **percent-encoded absolute path**. So it is decoded and
    required to be one: it starts at the root and it ends `.sock`. `remote.evil.sock` has no root
    and `remote.evil.example%2f` decodes to a relative path, so neither is one.
    """
    decoded = unquote(netloc.split("?", 1)[0])
    return decoded.startswith("/") and decoded.endswith(".sock")


def _hardened(uri: str) -> str:
    """``directConnection=true``, forced. Points 1-4 above constrain the URI; this constrains the
    driver, and without it the other four are decoration."""
    if "directconnection=" in uri.lower():
        return uri
    return uri + ("&" if "?" in uri else "?") + "directConnection=true"


@dataclass
class Turn:
    seq: int
    kind: str
    at: str = ""
    body: Dict[str, object] = field(default_factory=dict)

    #: Body keys that may never reach a stored turn, because they *are* the turn's identity.
    ENVELOPE = ("seq", "kind", "at")

    def as_dict(self) -> Dict[str, object]:
        """The body first, then the envelope — and the order is the whole point.

        The first version spread the body **last**, so a body key silently replaced `seq`, `at` or
        `kind`: `turn("note", seq=999, at="not-a-time")` stored a turn whose identity disagreed with
        the number `Conversation` had allocated and the time it recorded. `kind` survived only
        because Python raises `TypeError` on the keyword collision — luck, not a schema.

        A log whose payload can rewrite its own envelope cannot be ordered, deduplicated or dated,
        which is all a log is for. Found by an independent seat reading this line.
        """
        collided = [k for k in self.ENVELOPE if k in self.body]
        if collided:
            raise ConversationError(
                f"turn body carries {collided}, which name the turn's own identity. A body that "
                f"can rewrite its envelope makes seq, kind and at unreliable for every reader.")
        return {**self.body, "seq": self.seq, "kind": self.kind, "at": self.at}


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Backends. What the three actually guarantee in common — codex-seat asked, and the honest answer
# is short: append-only, unique (conversation_id, seq), ordered by that integer, a partial write
# visible rather than dropped, and **no concurrent writers**. One runner per conversation.
# ──────────────────────────────────────────────────────────────────────────────────────────────

class Backend:
    """Append turns and read them back. No update path exists on any backend, on purpose."""

    def open_conversation(self, header: Mapping[str, object]) -> None:
        raise NotImplementedError

    def append(self, header: Mapping[str, object], turn: Turn) -> None:
        raise NotImplementedError

    def read(self, pid: str, cid: str) -> Dict[str, object]:
        raise NotImplementedError

    def conversations(self, pid: Optional[str] = None) -> List[Dict[str, object]]:
        raise NotImplementedError

    def projects(self) -> List[Dict[str, object]]:
        raise NotImplementedError


class FileBackend(Backend):
    """JSON Lines under ``<root>/<project_id>/<conversation_id>.jsonl``.

    Append-only in the strongest sense available without a server: the file is opened ``"a"`` and one
    line is written. There is no read-modify-write to lose a concurrent turn, and a crash costs at
    most the line being written — which the reader reports rather than silently dropping.

    This is the default, and it is a directory of files. The user asked for a NoSQL DB and this is
    not one; fable-seat was right that the honest thing is to name that rather than argue it away.
    It is a document store with the filesystem as its index. `--store tinydb` and `--store mongo`
    are real document databases and are one flag away.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._own(self.root)

    @staticmethod
    def _own(path: Path) -> None:
        """0700, best effort. Not claimed as protection — see the design's §6: on Windows this does
        little, and the store is exactly as sensitive as the journal already sitting beside it."""
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass

    def _dir(self, pid: str) -> Path:
        d = self.root / pid
        d.mkdir(parents=True, exist_ok=True)
        self._own(d)
        return d

    def _path(self, pid: str, cid: str) -> Path:
        return self._dir(pid) / f"{cid}.jsonl"

    def open_conversation(self, header: Mapping[str, object]) -> None:
        pid = str(header["project"]["id"])          # type: ignore[index]
        path = self._path(pid, str(header["conversation_id"]))
        if path.exists():
            raise ConversationError(f"refused: {path.name} already exists; a conversation id is "
                                    f"minted once and never reopened")
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"header": dict(header)}, ensure_ascii=False, sort_keys=True) + "\n")
        # The project's name lives beside its conversations, so `projects()` reads a fact rather
        # than an index that can drift from what it indexes.
        marker = self._dir(pid) / "_project.json"
        if not marker.exists():
            marker.write_text(
                json.dumps(dict(header["project"]), ensure_ascii=False, sort_keys=True) + "\n",  # type: ignore[arg-type]
                encoding="utf-8")

    def append(self, header: Mapping[str, object], turn: Turn) -> None:
        path = self._path(str(header["project"]["id"]), str(header["conversation_id"]))  # type: ignore[index]
        if not path.exists():
            raise ConversationError(f"refused: no conversation at {path.name} to append to")
        with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(turn.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def read(self, pid: str, cid: str) -> Dict[str, object]:
        path = self._path(pid, cid)
        if not path.exists():
            raise ConversationError(f"no conversation {cid} in project {pid}")
        header: Dict[str, object] = {}
        turns: List[Dict[str, object]] = []
        partial: List[int] = []
        for n, line in enumerate(io.open(path, encoding="utf-8")):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                # A crash mid-line. Reported, not dropped: a store that quietly discards its last
                # turn is worse than one that says the last turn is incomplete.
                partial.append(n + 1)
                continue
            if "header" in row and not header:
                header = row["header"]
            else:
                turns.append(row)
        return _assemble(header, turns, partial)

    def conversations(self, pid: Optional[str] = None) -> List[Dict[str, object]]:
        dirs = [self.root / pid] if pid else [d for d in sorted(self.root.iterdir()) if d.is_dir()]
        out: List[Dict[str, object]] = []
        for d in dirs:
            if not d.is_dir():
                continue
            for path in sorted(d.glob("*.jsonl")):
                try:
                    first = json.loads(io.open(path, encoding="utf-8").readline() or "{}")
                except ValueError:
                    continue
                head = first.get("header") or {}
                if head:
                    out.append(head)
        return out

    def projects(self) -> List[Dict[str, object]]:
        out = []
        for d in sorted(self.root.iterdir()):
            marker = d / "_project.json"
            if d.is_dir() and marker.exists():
                out.append(json.loads(marker.read_text(encoding="utf-8")))
        return out


class _DocumentBackend(Backend):
    """Shared shape for the two real document databases: one row per turn, plus a header row.

    ``(conversation_id, seq)`` is unique and a duplicate is **refused**, never silently overwritten —
    which is the one guarantee that makes an append-only log worth reading back.
    """

    def _rows(self, cid: str) -> List[Dict[str, object]]:
        raise NotImplementedError

    def _insert(self, row: Mapping[str, object]) -> None:
        raise NotImplementedError

    def open_conversation(self, header: Mapping[str, object]) -> None:
        if self._rows(str(header["conversation_id"])):
            raise ConversationError("refused: that conversation id already has turns")
        self._insert({"conversation_id": header["conversation_id"], "seq": -1,
                      "project_id": header["project"]["id"], "header": dict(header)})  # type: ignore[index]

    #: Whether `_insert` refuses a duplicate ``(conversation_id, seq)`` on its own. Mongo does, with
    #: a unique index; TinyDB has no such thing, so it needs the scan. Declared rather than assumed,
    #: because a pre-scan on top of an index is quadratic and a missing one loses a turn silently.
    enforces_unique_seq = False

    def append(self, header: Mapping[str, object], turn: Turn) -> None:
        cid = str(header["conversation_id"])
        if not self.enforces_unique_seq and any(r.get("seq") == turn.seq for r in self._rows(cid)):
            raise ConversationError(f"refused: seq {turn.seq} is already written for {cid}")
        self._insert({"conversation_id": cid, "project_id": header["project"]["id"],  # type: ignore[index]
                      **turn.as_dict()})

    def read(self, pid: str, cid: str) -> Dict[str, object]:
        rows = self._rows(cid)
        if not rows:
            raise ConversationError(f"no conversation {cid}")
        header = next((r["header"] for r in rows if r.get("seq") == -1), {})
        turns = [{k: v for k, v in r.items() if k not in ("conversation_id", "project_id")}
                 for r in rows if r.get("seq", -1) >= 0]
        return _assemble(header, turns, [])


class TinyDBBackend(_DocumentBackend):
    """A single-file document database, for somebody who wants one file rather than a tree."""

    def __init__(self, path: str | Path):
        try:
            from tinydb import Query, TinyDB  # noqa: F401
        except ImportError:
            raise ConversationError(
                "the tinydb store needs the `tinydb` package, and it is not installed. This does "
                "not fall back to the file store: you asked for a document database, and quietly "
                "handing you a directory instead is a name standing in for a constraint."
            ) from None
        from tinydb import TinyDB
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(str(path))
        self._table = self._db.table("turns")

    def _rows(self, cid: str) -> List[Dict[str, object]]:
        from tinydb import Query
        return sorted(self._table.search(Query().conversation_id == cid),
                      key=lambda r: r.get("seq", -1))

    def _insert(self, row: Mapping[str, object]) -> None:
        self._table.insert(dict(row))

    def conversations(self, pid: Optional[str] = None) -> List[Dict[str, object]]:
        from tinydb import Query
        q = Query()
        rows = self._table.search((q.seq == -1) & (q.project_id == pid)) if pid \
            else self._table.search(q.seq == -1)
        return [r["header"] for r in rows if "header" in r]

    def projects(self) -> List[Dict[str, object]]:
        seen: Dict[str, Dict[str, object]] = {}
        for head in self.conversations():
            p = head.get("project") or {}
            if p.get("id"):
                seen[str(p["id"])] = dict(p)
        return [seen[k] for k in sorted(seen)]


class MongoBackend(_DocumentBackend):
    """A real document database, for somebody who already runs one — with the locality rule that
    `local_mongo_uri` documents, including the `directConnection=true` that actually enforces it."""

    enforces_unique_seq = True

    def __init__(self, uri: str, remote: bool = False, database: str = "ai_sdlc_runner"):
        try:
            import pymongo  # noqa: F401
        except ImportError:
            raise ConversationError(
                "the mongo store needs the `pymongo` package, and it is not installed. This does "
                "not fall back to the file store — see the tinydb backend for why."
            ) from None
        import pymongo
        self.relaxed = bool(remote)
        target = uri if remote else _hardened(local_mongo_uri(uri))
        self._client = pymongo.MongoClient(target, serverSelectionTimeoutMS=3000)
        self._turns = self._client[database]["turns"]
        self._turns.create_index([("conversation_id", 1), ("seq", 1)], unique=True)

    def _rows(self, cid: str) -> List[Dict[str, object]]:
        return [{k: v for k, v in r.items() if k != "_id"}
                for r in self._turns.find({"conversation_id": cid}).sort("seq", 1)]

    def _insert(self, row: Mapping[str, object]) -> None:
        import pymongo
        try:
            self._turns.insert_one(dict(row))
        except pymongo.errors.DuplicateKeyError:
            raise ConversationError(
                f"refused: seq {row.get('seq')} is already written for "
                f"{row.get('conversation_id')}") from None

    def conversations(self, pid: Optional[str] = None) -> List[Dict[str, object]]:
        query: Dict[str, object] = {"seq": -1}
        if pid:
            query["project_id"] = pid
        return [r["header"] for r in self._turns.find(query) if "header" in r]

    def projects(self) -> List[Dict[str, object]]:
        seen: Dict[str, Dict[str, object]] = {}
        for head in self.conversations():
            p = head.get("project") or {}
            if p.get("id"):
                seen[str(p["id"])] = dict(p)
        return [seen[k] for k in sorted(seen)]


def backend(kind: str, root: Optional[str] = None, uri: Optional[str] = None,
            remote: bool = False) -> Backend:
    """Open one. An unknown kind is refused by name rather than defaulted."""
    if kind not in BACKENDS:
        raise ConversationError(f"unknown store {kind!r}; one of {', '.join(BACKENDS)}")
    if kind == "file":
        return FileBackend(root or ".runner/conversations")
    if kind == "tinydb":
        return TinyDBBackend(root or ".runner/conversations/conversations.json")
    return MongoBackend(uri or "mongodb://127.0.0.1:27017", remote=remote)


def _assemble(header: Mapping[str, object], turns: Sequence[Mapping[str, object]],
              partial: Sequence[int]) -> Dict[str, object]:
    """One document, turns ordered by the integer ``seq``.

    Never by insertion order and never by filename. The journal sorts filenames and
    ``'%03d' % 1000`` lands between the 100th and the 101st ask; a store that presented "the ordered
    sequence of turns" would have inherited that silently, and at a scale where a demo looks fine.
    """
    doc = dict(header)
    doc["turns"] = sorted((dict(t) for t in turns), key=lambda t: int(t.get("seq", 0)))
    if partial:
        doc["incomplete_lines"] = list(partial)
    # `file` cannot refuse a duplicate seq at write time without a read per append, and the design
    # already declares one writer per conversation. So the guarantee is stated where it is true: a
    # duplicate is **refused** by the two backends that can (Mongo's unique index, TinyDB's check)
    # and **reported** by the reader. The first version claimed all three refused, which was a
    # guarantee two of them did not keep -- a name standing in for a constraint, found by a seat.
    seen, repeated = set(), []
    for t in doc["turns"]:
        n = int(t.get("seq", 0))
        (repeated.append(n) if n in seen else seen.add(n))
    if repeated:
        doc["duplicate_seqs"] = sorted(set(repeated))
    return doc


class Conversation:
    """One conversation, open and being written to as turns happen.

    Not derived from anything afterwards. Every write is durable at the moment the turn occurs, so
    a crashed run has everything up to the crash — which is the half of "every conversation stored"
    that a post-run derivation cannot give.
    """

    def __init__(self, store: Backend, project: str, journal_dir: Optional[str | Path] = None,
                 conversation_id: Optional[str] = None, run: Optional[Mapping[str, object]] = None):
        self.store = store
        self.project = {"id": project_id(project), "name": project.strip()}
        self.id = conversation_id or new_conversation_id()
        self.header = {
            "schema": SCHEMA,
            "conversation_id": self.id,
            "project": dict(self.project),
            "run": dict(run or {}),
        }
        self._seq = 0
        #: Store writes that failed. **A failed store write never fails a run** — and is never
        #: silent either: it lands here, in `RunReport.store_errors`, and on stderr. The first
        #: design said "must not be silent" and named no mechanism, which is how a sentence ships
        #: with nothing checking it.
        self.write_errors: List[str] = []
        self._opened = False
        self._journal_dir = Path(journal_dir) if journal_dir else None
        #: `serve` re-walks the whole flow on every approval, so the same instruction reaches
        #: `walk` again and again. A conversation that recorded it each time would say the operator
        #: asked five times for something they asked for once — the log would be counting walks
        #: while claiming to count turns. An ask is not re-recorded either: `_ask` returns a
        #: journalled answer before reaching this module, because nothing happened.
        self._instructions_seen = 0
        self._said: set = set()

    # ── opening and re-attaching ──────────────────────────────────────────────────────────────

    @classmethod
    def resume_or_open(cls, store: Backend, project: str,
                       journal_dir: Optional[str | Path] = None,
                       run: Optional[Mapping[str, object]] = None) -> "Conversation":
        """Re-attach to the conversation this journal already started, or start one.

        The marker beside the journal **is** the run instance. `run_id` — the resolved journal
        directory — identifies storage rather than one execution, which is why two fresh runs in one
        directory collide; a minted id written once fixes that without inventing a new place to keep
        it, because the journal directory is already the one durable place a run has.

        A resume that names a **different project** is refused. The document records the project at
        first write, and changing it would silently rewrite categorisation history.
        """
        marker = Path(journal_dir) / MARKER if journal_dir else None
        if marker is not None and marker.exists():
            existing = json.loads(marker.read_text(encoding="utf-8"))
            if existing.get("project") and existing["project"] != project.strip():
                raise ConversationError(
                    f"refused: this run's conversation is filed under project "
                    f"{existing['project']!r} and you asked for {project.strip()!r}. One run "
                    f"cannot be two projects — its categorisation was fixed when it opened.")
            conv = cls(store, project, journal_dir, conversation_id=existing["conversation_id"],
                       run=run)
            conv._opened = True
            try:
                turns = store.read(conv.project["id"], conv.id).get("turns") or []
                conv._seq = 1 + max((int(t["seq"]) for t in turns), default=-1)
                conv._instructions_seen = max(
                    (int(t.get("nth") or 0) for t in turns if t.get("kind") == INSTRUCTION),
                    default=0)
                conv._said = {("relaxation", t.get("text"))
                              for t in turns if t.get("kind") == RELAXATION}
            except ConversationError:
                conv._seq = 0
                conv._opened = False
            return conv
        conv = cls(store, project, journal_dir, run=run)
        conv.open()
        conv._note_earlier_asks()
        return conv

    def _note_earlier_asks(self) -> None:
        """Say so when a journal already holds answers this conversation was not open for.

        Found in round 2: adding `--project` to a resume whose journal already has answers stores
        none of them, because `_ask` returns a journalled answer before this module is reached — by
        design, since re-recording a reused answer would say something happened twice.

        Backfilling them would be **deriving the conversation from the journal**, which is the whole
        thing both round-1 verdicts refused: the journal holds the latest question at each position
        and no operator turn at all. So the honest move is neither to invent those turns nor to let
        the gap pass unmarked — the conversation says how many answers predate it.
        """
        if self._journal_dir is None:
            return
        try:
            earlier = len([p for p in self._journal_dir.glob("*.json")])
        except OSError:
            return
        if earlier:
            self.note(f"{earlier} ask(s) were already answered in this journal before the "
                      f"conversation was opened. They are not turns here: reconstructing them from "
                      f"the journal is the derivation this store exists not to do.")

    def open(self) -> "Conversation":
        if self._opened:
            return self
        self._guarded(lambda: self.store.open_conversation(self.header), "open")
        self._opened = True
        if self._journal_dir is not None:
            try:
                self._journal_dir.mkdir(parents=True, exist_ok=True)
                (self._journal_dir / MARKER).write_text(
                    json.dumps({"conversation_id": self.id, "project": self.project["name"]},
                               ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            except OSError as exc:
                self.write_errors.append(f"could not mark the journal: {exc}")
        self.turn(OPENED, project=self.project["name"], run=dict(self.header["run"] or {}))
        return self

    # ── writing turns ─────────────────────────────────────────────────────────────────────────

    def turn(self, kind: str, **body: object) -> Optional[Turn]:
        if kind not in KINDS:
            raise ConversationError(f"unknown turn kind {kind!r}")
        # Checked HERE, before `_guarded`, and this placement is the point. A body naming its own
        # envelope is a bug in the caller, not a disk that filled up -- and `_guarded` exists to
        # stop archival failures reaching a run. Left inside it, a programming error would be
        # swallowed into `write_errors` and the run would carry on with a turn it never stored.
        collided = [k for k in Turn.ENVELOPE if k in body]
        if collided:
            raise ConversationError(
                f"turn body carries {collided}, which name the turn's own identity. A body that "
                f"can rewrite its envelope makes seq, kind and at unreliable for every reader.")
        t = Turn(seq=self._seq, kind=kind, at=_now(), body=dict(body))
        self._seq += 1
        self._guarded(lambda: self.store.append(self.header, t), f"turn {t.seq} ({kind})")
        return t

    def instruction(self, text: str, nth: int) -> None:
        if nth <= self._instructions_seen:
            return
        self._instructions_seen = nth
        self.turn(INSTRUCTION, nth=nth, text=text)

    def ask(self, ask_id: str, node_id: str, role: str, seat: Optional[str],
            model: Optional[str], order: Mapping[str, object]) -> None:
        """The work order sent, **with the model that was asked**.

        `_ask` has always received `model` and never passed it to the journal, so the existing
        durable record cannot say which model said what — which is most of what a panel is for.
        codex-seat found it; this is where it is kept.
        """
        self.turn(ASK, ask_id=ask_id, node_id=node_id, role=role, seat=seat, model=model,
                  order=dict(order))

    def answer(self, ask_id: str, result: Mapping[str, object],
               model: Optional[str] = None, backend: Optional[str] = None) -> None:
        """``model`` is what was asked for; ``backend`` is what answered.

        They are not the same and a seat panel is where they come apart: it routes by seat name and
        passes no model at all, so `model` is `None` for every seat while the backend is known.
        """
        self.turn(ANSWER, ask_id=ask_id, model=model, backend=backend, result=dict(result))

    def unanswered(self, ask_id: str, why: str) -> None:
        self.turn(UNANSWERED, ask_id=ask_id, why=why)

    def decision(self, what: str, where: str, why: str = "", who: str = "operator") -> None:
        self.turn(DECISION, decision=what, at_node=where, why=why, who=who)

    def relaxation(self, text: str) -> None:
        """Recorded **in the document**, not only in the run report.

        `export` runs outside any walk, so there is no `RunReport` at the moment a relaxation like
        `--store-remote allow` is actually used. A mechanism whose name outlives its availability
        records nothing, which fable-seat found in the first design.
        """
        if ("relaxation", text) in self._said:
            return
        self._said.add(("relaxation", text))
        self.turn(RELAXATION, text=text)

    def note(self, text: str) -> None:
        self.turn(NOTE, text=text)

    def close(self, state: str) -> None:
        """Recorded on **every** walk, including the suspended ones `serve` produces per approval.

        Not deduplicated, and that is the difference from an instruction: a walk ending suspended
        and later ending finished are two things that happened, while one instruction reaching five
        walks is one thing that happened five times over.
        """
        self.turn(CLOSED, state=state)

    def document(self) -> Dict[str, object]:
        doc = self.store.read(self.project["id"], self.id)
        if self.write_errors:
            doc["write_errors"] = list(self.write_errors)
        return doc

    def _guarded(self, work, what: str) -> None:
        """A store write that fails must not fail the run, and must not be silent.

        Both halves, because either alone is wrong: failing the run makes an archive able to stop
        work, and swallowing it means the conversation and the evidence of its loss are both gone at
        process exit.

        **It speaks on stderr here**, at the moment of failure. The first version collected the
        failures into a list and named three channels in its own docstring; a seat checked and found
        that nothing anywhere wrote the stderr line, and that no caller printed the report field
        either -- so a store that failed every write was completely silent to the operator. That is
        the exact shape of "must not be silent" naming no mechanism, which the round-1 review had
        already found in the design, reappearing one layer down in the code that answered it.
        """
        try:
            work()
        except Exception as exc:  # noqa: BLE001 - archival never propagates into a run
            note = f"{what}: {exc}"
            self.write_errors.append(note)
            print(f"conversation store failed: {note}", file=sys.stderr)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Export — 「JSON, Markdown, CSV 都支援，但用戶可選哪種形式匯出」
# ──────────────────────────────────────────────────────────────────────────────────────────────

FORMATS = ("json", "markdown", "csv")

#: The CSV columns. Fixed, because "one row per turn" is not something anybody can implement or
#: check against. A ``_json`` suffix says the cell holds JSON text — which is also the only honest
#: place to put that notice, since CSV has no comments and a note row is a data row.
CSV_COLUMNS = ("seq", "at", "kind", "node_id", "ask_id", "role", "seat", "model",
               "text_or_state", "body_json", "over_spreadsheet_cell_limit")


def export_conversation(document: Mapping[str, object], fmt: str) -> str:
    if fmt not in FORMATS:
        raise ConversationError(f"unknown format {fmt!r}; one of {', '.join(FORMATS)}")
    if fmt == "json":
        return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if fmt == "markdown":
        return _markdown(document)
    return _csv(document)


def _fence(text: str) -> str:
    """A fence longer than the longest run of backticks inside it.

    An answer containing ``` ends a three-backtick fence early, and "for reading" is this format's
    whole claim — fable-seat found it in the design, before there was anything to break.
    """
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _inline(value: object) -> str:
    """A value safe to interpolate into a markdown line.

    A project name is operator text and was written straight into the header, so a name carrying a
    newline and a `#` produced a heading outside any fence. Found by a seat -- the same finding as
    the fence length, one line further up, where I had not looked for it.
    """
    text = re.sub(r"[\r\n]+", " ", str(value))
    ticks = "`" * (max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)
    return f"{ticks}{text}{ticks}" if text else "``"


def _markdown(document: Mapping[str, object]) -> str:
    project = (document.get("project") or {})
    out = [f"# Conversation {_inline(document.get('conversation_id', '?'))}", "",
           f"- Project: {_inline(project.get('name', '?'))} ({_inline(project.get('id', '?'))})",
           f"- Schema: {document.get('schema', '?')}"]
    run = document.get("run") or {}
    if run:
        out.append(f"- Run: {_inline(json.dumps(run, ensure_ascii=False, sort_keys=True))}")
    if document.get("incomplete_lines"):
        out.append(f"- **Incomplete lines in the store:** {document['incomplete_lines']} — a write "
                   f"was interrupted. Reported rather than dropped.")
    if document.get("write_errors"):
        out.append(f"- **Store write errors:** {len(document['write_errors'])}")
    out.append("")
    for turn in document.get("turns") or []:
        body = {k: v for k, v in turn.items() if k not in ("seq", "kind", "at")}
        out.append(f"## {turn.get('seq')} · {turn.get('kind')}  \n<sub>{turn.get('at', '')}</sub>")
        out.append("")
        text = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True)
        fence = _fence(text)
        out.extend([fence + "json", text, fence, ""])
    return "\n".join(out) + "\n"


def _defuse(cell: str) -> str:
    """A cell whose first non-blank character is one of `FORMULA_LEADERS` executes as a formula.

    The text is model-produced, the export's stated purpose is to be opened in a spreadsheet, and
    `=HYPERLINK(...)` is an exfiltration channel -- in a project whose standing constraint is
    local-only. RFC-compliant quoting does not neutralise a formula; a leading apostrophe does.

    **The first non-blank character, not the first character.** A cell whose formula sat behind a
    newline was emitted unchanged by the first version of this function, and a seat found it:
    leading whitespace does not stop a spreadsheet evaluating what comes after it.
    """
    leading = cell[:1] in FORMULA_LEADERS or cell.lstrip()[:1] in FORMULA_LEADERS
    return "'" + cell if leading else cell


def _csv(document: Mapping[str, object]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for turn in document.get("turns") or []:
        body = {k: v for k, v in turn.items()
                if k not in ("seq", "kind", "at", "node_id", "ask_id", "role", "seat", "model")}
        body_json = json.dumps(body, ensure_ascii=False, sort_keys=True)
        summary = str(turn.get("text") or turn.get("state") or turn.get("decision") or "")
        over = len(body_json) > SPREADSHEET_CELL_LIMIT or len(summary) > SPREADSHEET_CELL_LIMIT
        writer.writerow([_defuse(str(v)) for v in (
            turn.get("seq", ""), turn.get("at", ""), turn.get("kind", ""),
            turn.get("node_id", "") or "", turn.get("ask_id", "") or "",
            turn.get("role", "") or "", turn.get("seat", "") or "", turn.get("model", "") or "",
            summary, body_json, "yes" if over else "no")])
    # No header comment row: CSV has no comments, and a note row is a data row to every consumer.
    # The `_json` suffixes and `over_spreadsheet_cell_limit` are where that notice actually lives.
    return buf.getvalue()
