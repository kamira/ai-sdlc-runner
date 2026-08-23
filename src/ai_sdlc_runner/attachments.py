"""attachments.py — what the operator hands the runner (CHG-20260823-11 tasks 9, 17 and 19).

A spec, a flow diagram, a screenshot of the thing that is wrong. They go on **every** node's work
order, so the reviewer reads the same material the engineer built from — a review against a
different brief than the build is not a review.

## The interaction that makes this dangerous

An independent seat found it before a line was written, and it is worth restating because it is not
obvious: `input_artifacts` is a field `_spoken_halt` **scans for red lines**. Put attachment paths
there and a file stored at `…/production/spec.pdf` raises an unrelaxable permanent halt — on every
node, of every run.

The tempting fix — exempt `input_artifacts` from the scan — is worse than the bug. It would mean a
brief that genuinely names a production target stops halting. One direction of a safety check traded
for the other, which is this repository's oldest mistake wearing new clothes.

So instead: **attachments are stored under names that cannot collide.** The stored path is
`<store>/<sha256>` — no extension, no operator-chosen segment, nothing a scanner can mistake for a
deployment target. The original filename travels in the *manifest*, where it is data about the
attachment rather than a path the runner might act on. Both directions of the check survive, because
neither was weakened.

## Content-addressed, so "the same spec" means the same bytes

The id is the hash. Two uploads of one file are one attachment, a changed file is a different one,
and a work order that cites an attachment cites bytes rather than a name somebody can swap
underneath it. That is also what makes "an attachment changed mid-run" answerable: it cannot. A new
version is a new id, and the orders already sent still refer to what they were sent with.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: What the runner will hold. Not a guess at what is useful — a list of what it can be given without
#: having to decide anything about it. Anything else is refused rather than stored as bytes nobody
#: knows the shape of.
ALLOWED = {
    "text/markdown": (".md",), "text/plain": (".txt",), "application/pdf": (".pdf",),
    "image/png": (".png",), "image/jpeg": (".jpg", ".jpeg"), "image/svg+xml": (".svg",),
    "text/html": (".html", ".htm"), "application/json": (".json",),
    "text/csv": (".csv",), "image/gif": (".gif",), "image/webp": (".webp",),
}

#: 25 MB. Large enough for a spec with screenshots in it, small enough that a mistake is a mistake
#: rather than a disk. A limit nobody can state is a limit nobody enforces.
MAX_BYTES = 25 * 1024 * 1024

#: How much of the hash becomes the filename. 128 bits, not 256, and the reason is Windows.
#:
#: A full sha256 is 64 characters. Added to a project path of any depth that is enough to cross the
#: 260-character limit — and Windows reports that as ``FileNotFoundError``, about a directory that
#: demonstrably exists. Found live: the store had just been created, the write failed, and the
#: message sent the search in exactly the wrong direction.
#:
#: 128 bits is past the point where a collision is a thing that happens. The **id** stays the full
#: digest, because identity is not the thing under pressure here; only the filename is.
_NAME_CHARS = 32

#: A stored name is a hash and nothing else. Stated as a pattern because the *point* is that it
#: cannot contain an operator-chosen segment — see the module docstring.
_STORED_NAME = re.compile(r"^[0-9a-f]{%d}$" % _NAME_CHARS)


def stored_name(attachment_id: str) -> str:
    """The filename for an attachment id. Shorter than the id, and derived from nothing else."""
    return attachment_id[:_NAME_CHARS]


class AttachmentError(Exception):
    """Refused. Storing it anyway would put something in a work order nobody vouched for."""


@dataclass(frozen=True)
class Attachment:
    """One thing the operator handed over."""

    #: The sha256 of the bytes, and also the stored filename. Same file twice is one attachment.
    id: str
    #: What it was called when it arrived. **Data, never a path** — it is shown to a person and
    #: never joined onto the store, which is what keeps a filename out of the red-line scanner.
    filename: str
    media_type: str
    size: int
    #: Which instruction it arrived with, so a later brief can say where a document came from.
    instruction: int = 0

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    for media, suffixes in ALLOWED.items():
        if suffix in suffixes:
            return media
    raise AttachmentError(
        f"{filename!r} has extension {suffix or '(none)'}, which this runner does not accept. It "
        f"takes {sorted(s for group in ALLOWED.values() for s in group)}. Refusing is deliberate: "
        f"a file the runner cannot describe is one it would put in a work order without being able "
        f"to say what it is.")


class Store:
    """Where attachments live, and the only thing that decides their names."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    def add(self, filename: str, data: bytes, instruction: int = 0) -> Attachment:
        if not filename or filename.strip() != filename:
            raise AttachmentError("an attachment needs a name, and one without padding")
        if not data:
            raise AttachmentError(f"{filename!r} is empty — an empty brief is not a brief")
        if len(data) > MAX_BYTES:
            raise AttachmentError(
                f"{filename!r} is {len(data)} bytes; the limit is {MAX_BYTES}. A limit nobody can "
                f"state is a limit nobody enforces.")
        media = _media_type(filename)

        digest = hashlib.sha256(data).hexdigest()
        # Ensured here and not only in __init__: the store owns this directory for the life of the
        # process, and a directory that went away between startup and an upload should be recreated
        # rather than crash a request. Found by clearing the store between runs of a live demo.
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / stored_name(digest)
        if not target.exists():                 # the same bytes twice is the same attachment
            try:
                target.write_bytes(data)
            except OSError as exc:
                # Say what actually happened. Windows raises FileNotFoundError for a path that is
                # merely too long, about a directory that exists — which is the most misleading
                # error in this whole module, and the one that cost an hour to read correctly.
                raise AttachmentError(
                    f"could not store {filename!r} at {target}: {exc}. "
                    f"The path is {len(str(target.resolve()))} characters; Windows refuses past 260 "
                    f"and reports it as a missing file. Run the project from a shorter path, or "
                    f"point --attachments somewhere shallower.")

        # The name a person typed never reaches the filesystem. Only its bytes do, under their hash.
        attachment = Attachment(id=digest, filename=Path(filename).name, media_type=media,
                                size=len(data), instruction=instruction)
        manifest = {a.id: a for a in self.all()}
        manifest[attachment.id] = attachment
        self._write(list(manifest.values()))
        return attachment

    def all(self) -> List[Attachment]:
        if not self.manifest_path.exists():
            return []
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise AttachmentError(f"{self.manifest_path} is not valid JSON: {exc}")
        return [Attachment(**entry) for entry in raw.get("attachments", [])]

    def path_for(self, attachment_id: str) -> Path:
        """The stored path — a hash under the store, and never anything else.

        Checked rather than assumed, because this is the one function whose output becomes a string
        in a work order that a safety scanner then reads.
        """
        if not _STORED_NAME.match(stored_name(attachment_id)):
            raise AttachmentError(
                f"{attachment_id!r} is not a stored attachment name. Stored names are content "
                f"hashes precisely so that nothing an operator typed ends up on a path the runner "
                f"passes around.")
        target = self.dir / stored_name(attachment_id)
        if not target.exists():
            raise AttachmentError(f"attachment {attachment_id} is not in this store")
        return target

    def order_paths(self) -> List[str]:
        """What goes on every work order's ``input_artifacts``.

        Hashed paths, so `policy.derive` scanning them finds nothing — while a brief that genuinely
        names a production target still halts, because that check was never weakened.
        """
        return [str(self.dir / stored_name(a.id)) for a in self.all()]

    def missing(self) -> List[str]:
        """Attachments the manifest lists and the store no longer holds.

        Task 19 asked what happens when an attachment disappears mid-run. This is the answer's first
        half: it becomes **visible**. A run whose brief has quietly lost a document is worse than one
        that says so.
        """
        return [a.id for a in self.all() if not (self.dir / stored_name(a.id)).exists()]

    def _write(self, attachments: Sequence[Attachment]) -> None:
        payload = {"attachments": [a.as_dict() for a in
                                   sorted(attachments, key=lambda a: (a.instruction, a.filename))]}
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
