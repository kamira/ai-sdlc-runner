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

So instead: **the stored leaf is a hash.** `<store>/<sha256 prefix>` — no extension, nothing an
operator typed. The original filename travels in the *manifest*, where it is data about the
attachment rather than a path the runner might act on. Both directions of the check survive,
because neither was weakened.

The **leaf** is what carries nothing the operator typed. The **store directory** carries
everything they typed, and `order_paths` returns the whole path, so `--attachments` under a
directory named for a red line halts every node of every run — measured: `spec prod files` reads
as a deploy target, `billing/att` as money. This docstring used to claim the path had "no
operator-chosen segment", which was true of half of it. `cli.py`'s `serve` refuses such a store
at startup, naming the directory (CHG-20260905-04); the sentence is corrected here rather than
left standing on the refusal (CHG-20260905-05).

## Content-addressed, so "the same spec" means the same bytes

The id is the hash. Two uploads of one file are one attachment, a changed file is a different one,
and a work order that cites an attachment cites bytes rather than a name somebody can swap
underneath it. A new version is a new id, and the orders already sent still refer to what they
were sent with.

Stated exactly, because the short form — *"an attachment cannot change mid-run"* — is more than
is true: an attachment's **identity** cannot change, for anything that goes through `add`.
Overwriting a stored blob on disk is not prevented and is not detected. Measured: the manifest
still reports the old size, the sha of what is on disk no longer equals the id, and `missing()`
returns `[]`, because nothing re-hashes (CHG-20260905-05).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import paths

#: What the runner will hold. Not a guess at what is useful — a list of what it can be given without
#: having to decide anything about it. Anything else is refused rather than stored as bytes nobody
#: knows the shape of.
ALLOWED = {
    "text/markdown": (".md",), "text/plain": (".txt",), "application/pdf": (".pdf",),
    "image/png": (".png",), "image/jpeg": (".jpg", ".jpeg"), "image/svg+xml": (".svg",),
    "text/html": (".html", ".htm"), "application/json": (".json",),
    "text/csv": (".csv",), "image/gif": (".gif",), "image/webp": (".webp",),
}

#: What each binary type must actually **begin with**.
#:
#: `_media_type` reads `Path(filename).suffix` — the one part of the filename this module
#: elsewhere refuses to trust — and the answer it produces reaches the console and the models.
#: `add("screenshot.png", b"%PDF-1.4 …")` was announced as `image/png` (CHG-20260905-04).
#:
#: Only types with an unambiguous signature are here. The text types have none, and a guard
#: that refused what it cannot read would refuse every valid `.md` in order to catch a
#: mislabelled `.png`.
SIGNATURES = {
    "image/png": (bytes([137, 80, 78, 71, 13, 10, 26, 10]),),
    "image/jpeg": (bytes([255, 216, 255]),),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "application/pdf": (b"%PDF-",),
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
        paths.makedirs(self.dir)

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
        expected = SIGNATURES.get(media)
        if expected and not any(data.startswith(sig) for sig in expected):
            raise AttachmentError(
                f"{filename!r} says it is {media} and its bytes do not begin like one. The "
                f"type is read from the extension, which is the one part of a filename this "
                f"store does not otherwise trust, and it is what the console and every "
                f"answering model are told the document is.")

        digest = hashlib.sha256(data).hexdigest()
        # Ensured here and not only in __init__: the store owns this directory for the life of the
        # process, and a directory that went away between startup and an upload should be recreated
        # rather than crash a request. Found by clearing the store between runs of a live demo.
        paths.makedirs(self.dir)
        target = self.dir / stored_name(digest)
        # Read once. `missing()` and the manifest rebuild below both used to re-read and
        # re-parse what this call already has, three to four times per state-changing call.
        held = self.all()
        # A stored name is a **128-bit prefix** of the digest, not the whole of it. Two
        # documents that shared that prefix used to become one silently: `add` returned
        # success, never wrote the second file, and `path_for` handed back the first
        # attachment's bytes while `missing()` reported nothing wrong.
        #
        # Detected rather than widened. The docstring's reason for truncating is stale —
        # `paths.py` supplies the extended-length prefix now, and 64 characters was measured
        # working under a 400-character store — but widening the name orphans every store that
        # exists: the manifest holds full digests, the files on disk are named with 32
        # characters, and `missing()` would report every one of them. The width is not what
        # makes this safe; noticing is (CHG-20260905-04).
        clash = [a.id for a in held
                 if stored_name(a.id) == stored_name(digest) and a.id != digest]
        if clash:
            raise AttachmentError(
                f"{filename!r} hashes to {digest}, which is stored under the same name as "
                f"{clash[0]}. Two different documents cannot share a stored name: one would "
                f"be handed out for the other, on every work order, with nothing reporting "
                f"it.")
        # `paths.exists`, not `Path.exists` — and the comment eight lines below is why:
        # past MAX_PATH Windows reports a path that is merely too long as **absent**,
        # about a directory that exists. Every write in this module was wrapped for that
        # and every read was left bare, so a deep store accepted uploads and read back
        # empty, and `missing()` — the detector written for exactly this — agreed with it
        # (CHG-20260903-28, found by the defect seat).
        if not paths.exists(target):            # the same bytes twice is the same attachment
            try:
                paths.write_bytes(target, data)
            except OSError as exc:
                # Say what actually happened. Windows raises FileNotFoundError for a path that is
                # merely too long, about a directory that exists — which is the most misleading
                # error in this whole module, and the one that cost an hour to read correctly.
                raise AttachmentError(
                    f"could not store {filename!r} at {target}: {paths.plain_in(str(exc))}. "
                    f"The path is {len(str(target.resolve()))} characters; Windows refuses past 260 "
                    f"and reports it as a missing file. Run the project from a shorter path, or "
                    f"point --attachments somewhere shallower.")

        # The name a person typed never reaches the filesystem. Only its bytes do, under their hash.
        attachment = Attachment(id=digest, filename=Path(filename).name, media_type=media,
                                size=len(data), instruction=instruction)
        manifest = {a.id: a for a in held}
        manifest[attachment.id] = attachment
        self._write(list(manifest.values()))
        return attachment

    def all(self) -> List[Attachment]:
        # The load-bearing one. `_write` rebuilds the manifest from this, so a bare
        # `exists()` that says "absent" on a deep path turned every `add()` into a
        # **truncation**: the second upload destroyed the first, and both calls returned
        # successfully (CHG-20260903-28).
        if not paths.exists(self.manifest_path):
            return []
        try:
            raw = json.loads(paths.read_text(self.manifest_path))
        except ValueError as exc:
            raise AttachmentError(f"{self.manifest_path} is not valid JSON: {exc}")
        # Valid JSON of the wrong **shape** used to escape as `TypeError` or `AttributeError`:
        # a list instead of an object, a row missing a field, a row carrying an extra one, a
        # row that is a string. Every caller catches `AttachmentError` only, so those went out
        # of `server.py` as a raw 500 and out of the module's stated contract
        # (CHG-20260905-04). `"{oops"` — the one shape the old code handled — is a JSON parse
        # failure, and it is what the existing test wrote.
        if not isinstance(raw, dict):
            raise AttachmentError(
                f"{self.manifest_path} is valid JSON but not an object: it is a "
                f"{type(raw).__name__}")
        rows = raw.get("attachments", [])
        if not isinstance(rows, list):
            raise AttachmentError(
                f"{self.manifest_path}: `attachments` is a {type(rows).__name__}, not a list")
        out = []
        for index, entry in enumerate(rows):
            if not isinstance(entry, dict):
                raise AttachmentError(
                    f"{self.manifest_path}: attachment {index} is a "
                    f"{type(entry).__name__}, not an object")
            try:
                attachment = Attachment(**entry)
            except TypeError as exc:
                raise AttachmentError(
                    f"{self.manifest_path}: attachment {index} does not have the fields an "
                    f"attachment has ({exc})") from exc
            # Checked because `_write` sorts on it, so a string here read fine and then killed
            # the *next* upload, after its bytes were already on disk.
            if not isinstance(attachment.instruction, int) or isinstance(
                    attachment.instruction, bool):
                raise AttachmentError(
                    f"{self.manifest_path}: attachment {index} has instruction "
                    f"{attachment.instruction!r}, which is not a number")
            out.append(attachment)
        return out

    def path_for(self, attachment_id: str) -> Path:
        """The stored path — a hash under the store, and never anything else, and it must exist.

        The **checked accessor**, for a caller that wants one attachment and wants to know it is
        there. It has no production caller today; `server.py` and `cli.py` go through `all` and
        `order_paths`.

        It used to say it was *"the one function whose output becomes a string in a work order
        that a safety scanner then reads"*, which described `order_paths` — the function that
        had no check. That sentence now lives there, with the check (CHG-20260905-04/-05).
        """
        if not _STORED_NAME.match(stored_name(attachment_id)):
            raise AttachmentError(
                f"{attachment_id!r} is not a stored attachment name. Stored names are content "
                f"hashes precisely so that nothing an operator typed ends up on a path the runner "
                f"passes around.")
        target = self.dir / stored_name(attachment_id)
        # Bare, this raised *"is not in this store"* about a file the store was holding.
        if not paths.exists(target):
            raise AttachmentError(f"attachment {attachment_id} is not in this store")
        return target

    def order_paths(self) -> List[str]:
        """What goes on every work order's ``input_artifacts``.

        Hashed paths, so `policy.derive` scanning them finds nothing — while a brief that genuinely
        names a production target still halts, because that check was never weakened.

        **This** is the function whose output becomes a string in a work order that a safety
        scanner then reads. `path_for` said that about itself and has no production caller;
        the check lived on the door nobody uses while this one rebuilt the path unguarded, so a
        hand-edited manifest row put a traversal out of the store and into a production
        path on every node's ``input_artifacts``, and halted the whole run at the first
        node (CHG-20260905-04).

        The **shape** only. Routing this through `path_for` would add its existence check too,
        which silently drops a missing attachment from every order — exactly what `missing()`
        exists to prevent. A document the store has lost still belongs on the order, and still
        gets reported as lost.
        """
        out = []
        for attachment in self.all():
            name = stored_name(attachment.id)
            if not _STORED_NAME.match(name):
                raise AttachmentError(
                    f"the manifest holds {attachment.id!r}, which is not a stored attachment "
                    f"name. Stored names are content hashes precisely so that nothing an "
                    f"operator typed ends up on a path the runner passes around — and this is "
                    f"the path it passes around.")
            out.append(str(self.dir / name))
        return out

    def missing(self) -> List[str]:
        """Attachments the manifest lists and the store no longer holds.

        Task 19 asked what happens when an attachment disappears mid-run. This is the answer's first
        half: it becomes **visible**. A run whose brief has quietly lost a document is worse than one
        that says so.
        """
        # Wrong in **both** directions before this. Measured with `LongPathsEnabled = 0`,
        # the Windows default: at a 252-character store directory it returned `[]` while
        # nothing was readable, and at 235 it reported every attachment missing while the
        # directory listing showed all of them present. It inherits whichever answer
        # `all()` gives and then asks the same bare question again, once per attachment.
        return [a.id for a in self.all()
                if not paths.exists(self.dir / stored_name(a.id))]

    def _write(self, attachments: Sequence[Attachment]) -> None:
        payload = {"attachments": [a.as_dict() for a in
                                   sorted(attachments, key=lambda a: (a.instruction, a.filename))]}
        # Written beside the manifest and moved onto it, because `paths.write_text` opens "w"
        # and truncates first. Measured on the old form: the file is 0 bytes on disk between
        # the open and the first write, and two processes adding at once lost an attachment
        # that had already been reported as added in 4 of 10 trials. The single-writer case is
        # worse — a Ctrl-C or a full disk in that window empties the manifest permanently, and
        # the manifest is the only record of what each stored blob was called
        # (CHG-20260905-04).
        staging = self.dir / "manifest.json.writing"
        paths.write_text(
            staging,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        paths.replace(staging, self.manifest_path)
