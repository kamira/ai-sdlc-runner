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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

from . import paths

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

#: One backend (CHG-20260823-35). There were three — *「提供所有選擇的可能性」* — and the person
#: then ruled *「只留 sqlite + file，移除 mongo 和 tinydb」*.
#:
#: Kept as a tuple of one rather than deleted, because `backend()` still refuses an unknown kind
#: **by name**: "I asked for Mongo and got a directory" is this repository's oldest mistake wearing
#: a config field, and it stays refused now that Mongo is gone rather than silently becoming a
#: directory. `--store mongo` gets a refusal that says the backend was removed and when.
BACKENDS = ("file",)

#: Named so the refusal can tell "never existed" from "removed, and here is what replaced it". A
#: config field that stops working deserves better than `unknown store 'mongo'`.
RETIRED = {
    "mongo": "removed in CHG-20260823-35; the model registry lives in SQLite (`store.py`) and "
             "conversations in the file store",
    "tinydb": "removed in CHG-20260823-35; it was the document backend with neither SQLite's "
              "durability nor the file store's readability",
}

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

    It is a directory of files: a document store with the filesystem as its index, and not a NoSQL
    database. fable-seat was right that the honest thing is to name that rather than argue it away —
    and it is worth more now than when there were alternatives, because since CHG-20260823-35 there
    are none. The two real document backends were removed by ruling; this is the only conversation
    store, and calling it a document store is a description of its shape, not a claim about its
    guarantees.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        # Through `paths`, because this is the store a seat lost a whole conversation from and a
        # real SPA build lost another: 282 characters against a 260-character limit, reported as
        # `FileNotFoundError` about a directory that had just been created.
        paths.makedirs(self.root)
        self._own(self.root)

    @staticmethod
    def _own(path: Path) -> None:
        """0700, best effort. Not claimed as protection — see the design's §6: on Windows this does
        little, and the store is exactly as sensitive as the journal already sitting beside it."""
        paths.chmod(path, 0o700)

    def _dir(self, pid: str) -> Path:
        d = self.root / pid
        paths.makedirs(d)
        self._own(d)
        return d

    def _path(self, pid: str, cid: str) -> Path:
        return self._dir(pid) / f"{cid}.jsonl"

    def open_conversation(self, header: Mapping[str, object]) -> None:
        pid = str(header["project"]["id"])          # type: ignore[index]
        path = self._path(pid, str(header["conversation_id"]))
        if paths.exists(path):
            raise ConversationError(f"refused: {path.name} already exists; a conversation id is "
                                    f"minted once and never reopened")
        with paths.open_(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"header": dict(header)}, ensure_ascii=False, sort_keys=True) + "\n")
        # The project's name lives beside its conversations, so `projects()` reads a fact rather
        # than an index that can drift from what it indexes.
        marker = self._dir(pid) / "_project.json"
        if not paths.exists(marker):
            paths.write_text(
                marker,
                json.dumps(dict(header["project"]), ensure_ascii=False,  # type: ignore[arg-type]
                           sort_keys=True) + "\n")

    def append(self, header: Mapping[str, object], turn: Turn) -> None:
        path = self._path(str(header["project"]["id"]), str(header["conversation_id"]))  # type: ignore[index]
        if not paths.exists(path):
            raise ConversationError(f"refused: no conversation at {path.name} to append to")
        with paths.open_(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(turn.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def read(self, pid: str, cid: str) -> Dict[str, object]:
        path = self._path(pid, cid)
        if not paths.exists(path):
            raise ConversationError(f"no conversation {cid} in project {pid}")
        header: Dict[str, object] = {}
        turns: List[Dict[str, object]] = []
        partial: List[int] = []
        for n, line in enumerate(paths.open_(path, encoding="utf-8")):
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
        # `paths.listdir` rather than `iterdir`/`glob`: both go through the OS with the plain
        # path, so a store deeper than MAX_PATH lists as empty rather than raising — a directory
        # that silently has nothing in it is the worst of the three failure modes.
        names = [pid] if pid else sorted(paths.listdir(self.root))
        out: List[Dict[str, object]] = []
        for name in names:
            d = self.root / name
            if not paths.exists(d):
                continue
            for entry in sorted(n for n in paths.listdir(d) if n.endswith(".jsonl")):
                path = d / entry
                try:
                    first = json.loads(
                        (paths.read_text(path).splitlines() or ["{}"])[0] or "{}")
                except ValueError:
                    continue
                head = first.get("header") or {}
                if head:
                    out.append(head)
        return out

    def projects(self) -> List[Dict[str, object]]:
        out = []
        for name in sorted(paths.listdir(self.root)):
            marker = self.root / name / "_project.json"
            if paths.exists(marker):
                out.append(json.loads(paths.read_text(marker)))
        return out


def backend(kind: str, root: Optional[str] = None) -> Backend:
    """Open one. An unknown kind is refused by name rather than defaulted.

    A **retired** kind is refused by name too, and told what happened to it. `unknown store 'mongo'`
    would read as a typo to someone whose config worked last week.
    """
    if kind in RETIRED:
        raise ConversationError(f"the {kind} store was {RETIRED[kind]}")
    if kind not in BACKENDS:
        raise ConversationError(f"unknown store {kind!r}; one of {', '.join(BACKENDS)}")
    return FileBackend(root or ".runner/conversations")


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
    # A duplicate `seq` is **reported here and refused nowhere** — and that is now the whole of it.
    #
    # `file` cannot refuse one at write time without a read per append, and the design declares one
    # writer per conversation. Until CHG-20260823-35 the sentence continued "...but Mongo's unique
    # index and TinyDB's check do refuse it", and that clause is what made the guarantee sound
    # stronger than it was. Both backends are gone, so the honest statement is the short one:
    # detection is at read time, by this scan, and nothing prevents the write.
    #
    # Worth writing down because it is the one guarantee this removal genuinely weakened. It was
    # available on two backends nobody was measured using; it is available on none now. If a writer
    # ever becomes concurrent, this is the line that has to change first.
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
        if marker is not None and paths.exists(marker):
            existing = json.loads(paths.read_text(marker))
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
                # The marker names a conversation this store does not have — the journal survived
                # and the store did not, or a store root moved. `_opened = False` was meant to say
                # "so open it", and the code returned instead: every turn of that run then failed
                # with `no conversation at ….jsonl to append to`, once per turn, and the whole
                # conversation was lost to stderr.
                #
                # Found by driving a real project through the runner. No test reached it because
                # every test either starts clean or resumes a store that still has the file.
                #
                # Opened under the **marker's** id, so a resumed run keeps the identity it was
                # given rather than minting a second one for the same journal.
                conv._seq = 0
                conv._opened = False
                conv.open()
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
            earlier = len([n for n in paths.listdir(self._journal_dir)
                           if n.endswith(".json")])
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
                paths.makedirs(self._journal_dir)
                paths.write_text(
                    self._journal_dir / MARKER,
                    json.dumps({"conversation_id": self.id, "project": self.project["name"]},
                               ensure_ascii=False, sort_keys=True) + "\n")
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
            # Stripped of the extended-length prefix — an operator reading `\?\C:\…` on stderr
            # goes looking for a network share instead of at their own store root.
            note = f"{what}: {paths.plain(str(exc))}"
            self.write_errors.append(note)
            print(f"conversation store failed: {note}", file=sys.stderr)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Export — 「JSON, Markdown, CSV 都支援，但用戶可選哪種形式匯出」
# ──────────────────────────────────────────────────────────────────────────────────────────────

FORMATS = ("json", "markdown", "csv", "html", "playback")

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
    if fmt == "html":
        return _html(document)
    if fmt == "playback":
        return _playback(document)
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


# ── html: a waterfall down time, stopped at the flow's nodes ──────────────────────────────────

#: Who said it. A conversation has two sides and the log flattens them into one column of turns —
#: this is where they come apart again, because "the model answered" and "a person decided" are the
#: distinction the whole store exists to keep.
_VOICES = {
    ASK: ("runner", "asked"),
    ANSWER: ("model", "answered"),
    UNANSWERED: ("model", "failed"),
    INSTRUCTION: ("operator", "instructed"),
    DECISION: ("operator", "decided"),
    OPENED: ("runner", "opened"),
    CLOSED: ("runner", "closed"),
    RELAXATION: ("runner", "relaxed"),
    NOTE: ("runner", "noted"),
}


def _escape(value: object) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _pretty(body: Mapping[str, object]) -> str:
    return _escape(json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True))


def _summary(turn: Mapping[str, object]) -> str:
    """One line a reader can scan without opening anything."""
    kind = turn.get("kind")
    if kind == ASK:
        role = turn.get("role") or "?"
        seat = f" · {turn['seat']}" if turn.get("seat") else ""
        return f"{role}{seat}"
    if kind == ANSWER:
        # What actually came back, in the answerer's own words where it said anything. The first
        # version fell through to the bare word "answered" whenever the interesting keys were empty
        # — which is most review answers, since `{"missing": [], "problems": []}` means "nothing
        # wrong". A log of 150 lines reading "answered" is not a log (CHG-20260823-39).
        result = turn.get("result") or {}
        for key in ("verdict", "module", "modules", "note", "why"):
            if key in result and result[key] not in (None, "", [], {}):
                said = json.dumps(result[key], ensure_ascii=False).strip('"')
                extra = f" · {result['why']}" if key == "verdict" and result.get("why") else ""
                return f"{key}: {said}{extra}"[:110]
        empties = [k for k in ("missing", "problems", "unsafe") if k in result]
        if empties and all(not result[k] for k in empties):
            return "nothing " + ", ".join(empties)          # an empty list is an answer, not a gap
        for key in empties:
            if result[key]:
                return f"{key}: {json.dumps(result[key], ensure_ascii=False)[:80]}"
        return "answered"
    if kind == DECISION:
        return f"{turn.get('decision')} at {turn.get('at_node')}"
    if kind == INSTRUCTION:
        return str(turn.get("text") or "")[:90]
    if kind == CLOSED:
        return str(turn.get("state") or "")
    if kind == OPENED:
        # It had no `text` and no `why`, so it fell through to an empty string and rendered as a
        # card with a blank line — the first thing anybody opening the log sees.
        project = turn.get("project")
        return f"conversation opened for {project}" if project else "conversation opened"
    return str(turn.get("text") or turn.get("why") or "")[:90]


#: A pause longer than this plays as this, with the real length named on the page. The same figure
#: `tools/render_cast.py` uses, for the same reason: a run that waited six minutes for CI is not a
#: review anybody sits through at true speed, and one that silently cuts the wait cannot tell a slow
#: answer from a fast one.
IDLE_CAP = 2.0

#: The floor a turn gets on the playback clock, however fast it really was.
#:
#: Without it the first real export was **3 seconds for 55 turns**: a stand-in agent answers in
#: milliseconds, so the whole run flashed past unreadably while being, strictly, accurate. A
#: recording nobody can watch has not recorded anything.
#:
#: It compresses the *ratio* rather than erasing it — a 40-second seat still lands at the 2-second
#: cap against a neighbour's 0.35, which is the six-to-one a reader actually notices. The page says
#: both figures, so the compression is visible rather than implied.
MIN_BEAT = 0.35


def _script_json(value: object) -> str:
    r"""JSON for embedding inside a `<script>` block.

    The waterfall escapes model text for *markup*, because that is where it lands. This one lands
    inside a script element, where the rules are different and stricter: the HTML parser stops the
    script at the first literal `</script>` **inside the string**, so an answer containing that text
    ends the block early and everything after it is parsed as markup. `<!--` opens a comment that
    swallows the rest.

    Found by a test that put `<img src=x onerror=…>` in an answer and looked for it in the page — it
    was there, raw. Escaping `<` at the JSON level is the fix that does not depend on noticing every
    sequence: `\u003c` is the same string to JavaScript and nothing to the HTML parser. `U+2028` and
    `U+2029` go too — legal in JSON, line terminators in JavaScript.
    """
    text = json.dumps(value, ensure_ascii=False)
    return (text.replace("<", "\\u003c").replace(">", "\\u003e")
                .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _seconds(stamp: object) -> Optional[float]:
    """An ISO timestamp as epoch seconds, or None if it will not parse.

    None rather than 0.0 or "now": a turn whose time cannot be read must not be given a *plausible*
    one, because the whole point of the replay is that the timings are real.
    """
    if not stamp:
        return None
    text = str(stamp)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _playback(document: Mapping[str, object]) -> str:
    """The run as something you press play on.

    The waterfall answers *what happened*; this answers *watch it happen* — which node was reached
    when, how long a seat took to answer, where the walk sat still. `markdown` and `html` both
    flatten the run's duration away, and duration is where a review notices that one node took
    forty times longer than its neighbours.

    Real gaps are compressed and **said to be compressed**. A recording that quietly removes the
    waiting is telling you the run was fast.
    """
    project = (document.get("project") or {})
    turns = list(document.get("turns") or [])
    stops, visits = _stops(turns)

    # One clock across the whole run, advanced by the real gap between turns or by IDLE_CAP,
    # whichever is smaller. `waited` carries the real figure so the page can name what it skipped.
    clock, previous = 0.0, None
    play: List[Dict[str, object]] = []
    for index, stop in enumerate(stops):
        for turn in stop["turns"]:                                # type: ignore[union-attr]
            now = _seconds(turn.get("at"))
            waited = None
            if previous is not None and now is not None:
                gap = max(0.0, now - previous)
                if gap > IDLE_CAP:
                    waited, clock = round(gap, 1), clock + IDLE_CAP
                else:
                    clock += max(gap, MIN_BEAT)
            elif play:
                clock += MIN_BEAT       # no readable timestamp: a beat, not an invented duration
            if now is not None:
                previous = now
            who, verb = _VOICES.get(str(turn.get("kind")), ("runner", str(turn.get("kind"))))
            body = {k: v for k, v in turn.items() if k not in ("seq", "kind", "at", "node_id")}
            play.append({
                "t": round(clock, 3),
                "stop": index,
                "who": who,
                "verb": verb,
                "seq": turn.get("seq"),
                "model": turn.get("model") or turn.get("backend") or "",
                "sum": _summary(turn),
                "full": json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True),
                "waited": waited,
            })

    rail = [{"node": s["node"] or "—", "visit": s["visit"],
             "repeat": visits[s["node"]] > 1 and bool(s["node"]),
             "at": (str(s["turns"][0].get("at") or "")            # type: ignore[union-attr]
                    .replace("T", " ")[11:19])}
            for s in stops]

    counts: Dict[object, int] = {}
    for turn in turns:
        counts[turn.get("kind")] = counts.get(turn.get("kind"), 0) + 1
    real = 0.0
    first, last = _seconds(turns[0].get("at")) if turns else None, \
        _seconds(turns[-1].get("at")) if turns else None
    if first is not None and last is not None:
        real = max(0.0, last - first)

    return (_REPLAY
            .replace("__TITLE__", _escape(project.get("name", "conversation")))
            .replace("__CID__", _escape(document.get("conversation_id", "?")))
            .replace("__TURNS__", _script_json(play))
            .replace("__RAIL__", _script_json(rail))
            .replace("__TOTAL__", f"{(play[-1]['t'] if play else 0):.1f}")
            .replace("__NTURNS__", str(len(turns)))
            .replace("__NSTOPS__", str(len(stops)))
            .replace("__REAL__", f"{real / 60:.1f}"))


def _stops(turns: Sequence[Mapping[str, object]]):
    """Group the turns into the stops the walk actually made. Shared by `html` and `playback`.

    Consecutive turns at one node are one stop. **Consecutive**, not gathered — a node revisited
    later is a *second* stop, and collapsing the two hides the loop both formats exist to show.

    Two renderings reading the same run must agree about its shape, so this is one function rather
    than two copies: the waterfall and the replay differ in how they *present* a stop, never in
    where a stop begins.
    """
    stops: List[Dict[str, object]] = []
    for turn in turns:
        # An `answer` carries `ask_id` and no `node_id` — it belongs to the ask above it, and
        # reading it as its own stop split every pair in two: 53 stops for 55 turns, which is a
        # list wearing a waterfall's markup.
        node = turn.get("node_id") or turn.get("at_node") or ""
        if not node and turn.get("ask_id"):
            named = str(turn["ask_id"]).split("-", 1)
            node = named[1] if len(named) > 1 else ""
            if stops and node.startswith(str(stops[-1]["node"])):
                node = stops[-1]["node"]          # `000-lead_review-defect` belongs to lead_review
        if stops and stops[-1]["node"] == node:
            stops[-1]["turns"].append(turn)       # type: ignore[union-attr]
        else:
            stops.append({"node": node, "turns": [turn]})

    visits: Dict[object, int] = {}
    for stop in stops:
        visits[stop["node"]] = visits.get(stop["node"], 0) + 1
        stop["visit"] = visits[stop["node"]]
    return stops, visits


def _html(document: Mapping[str, object]) -> str:
    """The conversation as a waterfall down time, its stops the nodes the run walked.

    Markdown is a transcript and CSV is a spreadsheet; neither shows the **shape** of a run — that
    one node was asked four times because the module loop came back to it, or that three seats
    answered the same question in a row. Grouping consecutive turns by `node_id` puts that on the
    page: one block per visit, in the order the walk made them, with the model's side and the
    operator's side marked apart.
    """
    project = (document.get("project") or {})
    turns = list(document.get("turns") or [])
    stops, visits = _stops(turns)

    rows = []
    for stop in stops:
        node = stop["node"]
        label = _escape(node or "—")
        nth = (f'<span class="nth">visit {stop["visit"]}</span>'
               if visits[node] > 1 and node else "")
        at = _escape((stop["turns"][0].get("at") or "").replace("T", " ")[:19])
        first, last = stop["turns"][0]["seq"], stop["turns"][-1]["seq"]
        span = f"{first}" if first == last else f"{first}–{last}"

        cards = []
        for turn in stop["turns"]:
            who, verb = _VOICES.get(str(turn.get("kind")), ("runner", str(turn.get("kind"))))
            body = {k: v for k, v in turn.items() if k not in ("seq", "kind", "at", "node_id")}
            model = turn.get("model") or turn.get("backend")
            byline = f'<span class="model">{_escape(model)}</span>' if model else ""
            cards.append(
                f'<article class="turn {who}">'
                f'<header><span class="who">{who}</span>'
                f'<span class="verb">{verb}</span>{byline}'
                f'<span class="seq">#{turn["seq"]}</span></header>'
                f'<p class="sum">{_escape(_summary(turn))}</p>'
                f'<details><summary>full</summary><pre>{_pretty(body)}</pre></details>'
                f"</article>")

        rows.append(
            f'<li class="stop"><div class="when"><time>{at}</time>'
            f'<span class="span">{span}</span></div>'
            f'<div class="what"><h2>{label}{nth}</h2>{"".join(cards)}</div></li>')

    counts = {}
    for turn in turns:
        counts[turn.get("kind")] = counts.get(turn.get("kind"), 0) + 1
    stats = " · ".join(f"<b>{n}</b> {k}" for k, n in sorted(counts.items()) if k)

    return _PAGE.format(
        title=_escape(project.get("name", "conversation")),
        cid=_escape(document.get("conversation_id", "?")),
        pid=_escape(project.get("id", "?")),
        stats=stats,
        stops=len(stops),
        rows="\n".join(rows),
    )


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — conversation</title>
<style>
:root{{--ink:#16191f;--ground:#fbfbf9;--panel:#fff;--rule:#e2ded6;--rule2:#c9c3b7;
--runner:#5d6b7a;--model:#1d6a8c;--operator:#a2542c;--muted:#6d7178}}
@media(prefers-color-scheme:dark){{:root{{--ink:#e7e5e0;--ground:#13161a;--panel:#1a1e24;
--rule:#2a2f36;--rule2:#3d434c;--runner:#93a3b4;--model:#5aa8c9;--operator:#d99a63;--muted:#959aa2}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
font:15px/1.6 "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif}}
code,pre,.mono{{font-family:"IBM Plex Mono",ui-monospace,monospace}}
header.top{{max-width:62rem;margin:0 auto;padding:2.5rem 1.25rem 1.25rem;
border-bottom:2px solid var(--ink)}}
h1{{margin:.2rem 0;font-size:2rem;letter-spacing:-.02em}}
.meta{{font-family:"IBM Plex Mono",monospace;font-size:.74rem;color:var(--muted)}}
.stats{{margin-top:.6rem;font-family:"IBM Plex Mono",monospace;font-size:.76rem;color:var(--muted)}}
.stats b{{color:var(--ink)}}
ol.flow{{list-style:none;max-width:62rem;margin:0 auto;padding:2rem 1.25rem 5rem}}
li.stop{{display:grid;grid-template-columns:9.5rem 1fr;gap:1.25rem;position:relative;
padding-bottom:1.6rem}}
li.stop::before{{content:"";position:absolute;left:9.5rem;top:.45rem;bottom:-.4rem;
width:2px;background:var(--rule);transform:translateX(-1px)}}
li.stop:last-child::before{{display:none}}
.when{{text-align:right;padding-top:.15rem;position:relative}}
.when::after{{content:"";position:absolute;right:-1.31rem;top:.5rem;width:9px;height:9px;
border-radius:50%;background:var(--ground);border:2px solid var(--rule2)}}
.when time{{display:block;font-family:"IBM Plex Mono",monospace;font-size:.72rem;color:var(--muted)}}
.when .span{{font-family:"IBM Plex Mono",monospace;font-size:.66rem;color:var(--rule2)}}
.what h2{{margin:0 0 .5rem;font-size:.95rem;font-family:"IBM Plex Mono",monospace;
letter-spacing:-.01em}}
.nth{{margin-left:.5rem;font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;
color:var(--operator);border:1px solid var(--rule2);border-radius:3px;padding:.05rem .3rem}}
.turn{{background:var(--panel);border:1px solid var(--rule);border-left:3px solid var(--runner);
border-radius:0 6px 6px 0;padding:.55rem .8rem;margin-bottom:.45rem}}
.turn.model{{border-left-color:var(--model)}}
.turn.operator{{border-left-color:var(--operator)}}
.turn header{{display:flex;align-items:baseline;gap:.5rem;font-size:.7rem;
font-family:"IBM Plex Mono",monospace}}
.who{{text-transform:uppercase;letter-spacing:.08em;color:var(--runner);font-weight:600}}
.turn.model .who{{color:var(--model)}}
.turn.operator .who{{color:var(--operator)}}
.verb{{color:var(--muted)}}
.model{{color:var(--muted);font-size:.66rem}}
.seq{{margin-left:auto;color:var(--rule2)}}
.sum{{margin:.25rem 0 0;font-size:.86rem;word-break:break-word}}
details{{margin-top:.35rem}}
summary{{cursor:pointer;font-size:.7rem;color:var(--muted);
font-family:"IBM Plex Mono",monospace}}
summary:focus-visible{{outline:2px solid var(--model);outline-offset:2px}}
pre{{margin:.4rem 0 0;padding:.6rem .7rem;background:var(--ground);border:1px solid var(--rule);
border-radius:4px;font-size:.72rem;overflow-x:auto;max-height:22rem}}
@media(max-width:640px){{li.stop{{grid-template-columns:1fr;gap:.3rem}}
li.stop::before,.when::after{{display:none}}.when{{text-align:left}}}}
@media(prefers-reduced-motion:reduce){{*{{transition:none!important;animation:none!important}}}}
</style></head><body>
<header class="top">
  <p class="meta">conversation {cid} · project {pid}</p>
  <h1>{title}</h1>
  <p class="stats">{stats} · <b>{stops}</b> stops on the flow</p>
</header>
<ol class="flow">
{rows}
</ol>
</body></html>
"""


_REPLAY = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ — replay</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{--ink:#16191f;--ground:#f6f5f2;--panel:#fff;--rule:#e0dcd4;--rule2:#c4bdb1;
--runner:#5d6b7a;--model:#1d6a8c;--operator:#a2542c;--muted:#6b6f76;--live:#1d6a8c}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--ink:#e7e5e0;--ground:#12151a;
--panel:#191d23;--rule:#282d35;--rule2:#3b414a;--runner:#93a3b4;--model:#5aa8c9;
--operator:#d99a63;--muted:#949aa2;--live:#5aa8c9}}
:root[data-theme="dark"]{--ink:#e7e5e0;--ground:#12151a;--panel:#191d23;--rule:#282d35;
--rule2:#3b414a;--runner:#93a3b4;--model:#5aa8c9;--operator:#d99a63;--muted:#949aa2;--live:#5aa8c9}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font:15px/1.6 "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif}
.wrap{max-width:74rem;margin:0 auto;padding:2rem 1.25rem 4rem}
header.top{border-bottom:2px solid var(--ink);padding-bottom:1rem;margin-bottom:1.4rem}
h1{margin:0;font-size:1.65rem;letter-spacing:-.02em}
.meta{margin:.3rem 0 0;font-family:"IBM Plex Mono",monospace;font-size:.72rem;color:var(--muted)}
.meta b{color:var(--ink)}
.dim{opacity:.75}
.layout{display:grid;grid-template-columns:15rem 1fr;gap:1.3rem;align-items:start}
ol.rail{list-style:none;margin:0;padding:0;max-height:33rem;overflow-y:auto;
border:1px solid var(--rule);border-radius:8px;background:var(--panel)}
ol.rail li{border-bottom:1px solid var(--rule);padding:.4rem .7rem;
border-left:3px solid transparent;cursor:pointer;opacity:.42}
ol.rail li:last-child{border-bottom:none}
ol.rail li.seen{opacity:1}
ol.rail li.on{border-left-color:var(--live);background:var(--ground)}
.rn{font-family:"IBM Plex Mono",monospace;font-size:.76rem;word-break:break-word}
.rt{font-family:"IBM Plex Mono",monospace;font-size:.64rem;color:var(--muted)}
.nth{margin-left:.35rem;font-size:.6rem;letter-spacing:.07em;text-transform:uppercase;
color:var(--operator);border:1px solid var(--rule2);border-radius:3px;padding:0 .25rem}
.stage{border:1px solid var(--rule);border-radius:8px;background:var(--panel);
min-height:26rem;max-height:33rem;overflow-y:auto;padding:.9rem}
.turn{border-left:3px solid var(--runner);background:var(--ground);border:1px solid var(--rule);
border-radius:0 6px 6px 0;padding:.5rem .75rem;margin-bottom:.45rem}
.turn.model{border-left-color:var(--model)}
.turn.operator{border-left-color:var(--operator)}
.turn.on{border-color:var(--live);box-shadow:0 0 0 2px var(--accent-soft)}
.turn.ahead{opacity:.42}
.turn{cursor:pointer}
.turn details{cursor:auto}
.th{display:flex;align-items:baseline;gap:.45rem;font-size:.68rem;
font-family:"IBM Plex Mono",monospace}
.who{text-transform:uppercase;letter-spacing:.08em;font-weight:600;color:var(--runner)}
.turn.model .who{color:var(--model)}
.turn.operator .who{color:var(--operator)}
.verb,.mdl{color:var(--muted)}
.seq{margin-left:auto;color:var(--rule2)}
.sum{margin:.2rem 0 0;font-size:.83rem;word-break:break-word}
details{margin-top:.3rem}
summary{cursor:pointer;font-size:.67rem;color:var(--muted);font-family:"IBM Plex Mono",monospace}
pre{margin:.3rem 0 0;padding:.5rem .6rem;background:var(--panel);border:1px solid var(--rule);
border-radius:4px;font-size:.7rem;overflow-x:auto;max-height:18rem;
font-family:"IBM Plex Mono",ui-monospace,monospace}
.gap{font-family:"IBM Plex Mono",monospace;font-size:.67rem;color:var(--muted);
font-style:italic;margin:.3rem 0 .45rem}
.bar{display:flex;align-items:center;gap:.7rem;margin-top:.8rem}
button.play{background:var(--live);color:#fff;border:0;border-radius:6px;cursor:pointer;
padding:.45rem .95rem;font:600 .82rem/1 "IBM Plex Sans",sans-serif;min-width:5rem}
input[type=range]{flex:1;accent-color:var(--live)}
select{background:var(--panel);color:var(--ink);border:1px solid var(--rule);border-radius:6px;
padding:.35rem .4rem;font:.76rem "IBM Plex Mono",monospace}
.time{font-family:"IBM Plex Mono",monospace;font-size:.73rem;color:var(--muted);
font-variant-numeric:tabular-nums;min-width:6.5rem;text-align:right}
:focus-visible{outline:2px solid var(--live);outline-offset:2px}
@media(max-width:780px){.layout{grid-template-columns:1fr}ol.rail{max-height:12rem}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style></head><body>
<div class="wrap">
<header class="top">
  <h1>__TITLE__</h1>
  <p class="meta">conversation __CID__ · <b>__NTURNS__</b> turns · <b>__NSTOPS__</b> stops on the
    flow · <b>__TOTAL__</b>s of playback from <b>__REAL__</b> min of real time
    <span class="dim">(every turn is listed below — press play to walk them in order, or click one
    to jump there. A turn plays for at least 0.35s however fast it was; a pause over 2s plays as 2s
    and says what it really took.)</span></p>
</header>
<div class="layout">
  <ol class="rail" id="rail"></ol>
  <div>
    <div class="stage" id="stage"></div>
    <div class="bar">
      <button class="play" id="play">Play</button>
      <input type="range" id="scrub" min="0" max="__TOTAL__" step="0.05" value="0">
      <select id="speed"><option value="0.5">0.5x</option>
        <option value="1" selected>1x</option><option value="2">2x</option>
        <option value="4">4x</option><option value="8">8x</option></select>
      <span class="time" id="time">0.0 / __TOTAL__s</span>
    </div>
  </div>
</div>
</div>
<script>
const TURNS = __TURNS__, RAIL = __RAIL__, TOTAL = parseFloat("__TOTAL__");
const rail = document.getElementById('rail'), stage = document.getElementById('stage');
const scrub = document.getElementById('scrub'), playBtn = document.getElementById('play');
const timeLabel = document.getElementById('time'), speed = document.getElementById('speed');
let clock = 0, playing = false, last = null, shown = -1;

const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

RAIL.forEach((r, i) => {
  const li = document.createElement('li');
  li.innerHTML = '<div class="rn">' + esc(r.node) +
    (r.repeat ? '<span class="nth">visit ' + r.visit + '</span>' : '') +
    '</div><div class="rt">' + esc(r.at) + '</div>';
  li.onclick = () => {
    const first = TURNS.find(t => t.stop === i);
    if (first) { stop(); seek(first.t); }
  };
  rail.appendChild(li);
});

function upto(t) {
  let n = -1;
  for (let i = 0; i < TURNS.length; i++) if (TURNS[i].t <= t) n = i; else break;
  return n;
}

// The whole log is built ONCE, at load. The clock then moves a highlight through it rather than
// revealing it.
//
// The first version rendered only the turns up to the clock, and the clock starts at zero — so
// opening the page showed exactly **one** turn, the `opened` one. 305 answers sat in the payload,
// invisible until somebody pressed play and waited. A reader reasonably concluded the responses had
// not been recorded (CHG-20260823-39).
//
// A recording has to be a readable log first and a replay second. Nothing is hidden now; play walks
// the highlight, and everything ahead of it is dimmed rather than absent.
function build() {
  const html = [];
  TURNS.forEach((x, i) => {
    if (x.waited) html.push('<p class="gap">— waited ' +
      (x.waited >= 60 ? (x.waited / 60).toFixed(1) + ' min' : Math.round(x.waited) + 's') + ' —</p>');
    html.push('<article class="turn ' + x.who + '" data-i="' + i + '">' +
      '<div class="th"><span class="who">' + x.who + '</span>' +
      '<span class="verb">' + esc(x.verb) + '</span>' +
      (x.model ? '<span class="mdl">' + esc(x.model) + '</span>' : '') +
      '<span class="seq">#' + x.seq + '</span></div>' +
      '<p class="sum">' + esc(x.sum) + '</p>' +
      '<details><summary>full</summary><pre>' + esc(x.full) + '</pre></details></article>');
  });
  stage.innerHTML = html.join('');
  return [...stage.querySelectorAll('.turn')];
}

const CARDS = build();

function draw() {
  const n = upto(clock);
  if (n !== shown) {
    shown = n;
    CARDS.forEach((card, i) => {
      card.classList.toggle('on', i === n);
      card.classList.toggle('ahead', i > n);
    });
    if (n >= 0 && playing) CARDS[n].scrollIntoView({block: 'nearest'});
    const at = n >= 0 ? TURNS[n].stop : -1;
    [...rail.children].forEach((li, i) => {
      li.classList.toggle('on', i === at);
      li.classList.toggle('seen', i <= at);
    });
    if (at >= 0 && playing) rail.children[at].scrollIntoView({block: 'nearest'});
  }
  timeLabel.textContent = clock.toFixed(1) + ' / ' + TOTAL + 's';
  scrub.value = clock;
}

// Clicking a turn moves the clock to it, so reading and replaying are the same surface.
stage.addEventListener('click', function (e) {
  const card = e.target.closest('.turn');
  if (!card || e.target.closest('details')) return;
  stop();
  seek(TURNS[Number(card.dataset.i)].t);
});

function seek(t) { clock = Math.max(0, Math.min(TOTAL, t)); shown = -1; draw(); }
function stop() { playing = false; last = null; playBtn.textContent = 'Play'; }

function tick(now) {
  if (!playing) return;
  if (last !== null) clock += ((now - last) / 1000) * parseFloat(speed.value);
  last = now;
  if (clock >= TOTAL) { clock = TOTAL; stop(); }
  draw();
  if (playing) requestAnimationFrame(tick);
}

playBtn.onclick = () => {
  if (playing) { stop(); return; }
  if (clock >= TOTAL) { clock = 0; shown = -1; }
  playing = true; playBtn.textContent = 'Pause'; last = null;
  requestAnimationFrame(tick);
};
scrub.oninput = () => { stop(); seek(parseFloat(scrub.value)); };
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.key === ' ') { e.preventDefault(); playBtn.click(); }
  if (e.key === 'ArrowRight') { stop(); seek(clock + 5); }
  if (e.key === 'ArrowLeft') { stop(); seek(clock - 5); }
});
draw();
</script>
</body></html>
"""
