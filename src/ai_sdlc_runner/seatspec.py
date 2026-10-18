"""seatspec.py — the user's role and spec for a review seat (CHG-20261016-01).

A seat may carry two optional texts the user wrote: a **role** (the point of view to review from)
and a **spec** (the conditions to judge against). They are added to the seat's brief, below its
question, labelled as the user's. They change what a seat considers and never how its answer is
counted: this module has no import of `policy.adjudicate`, no vote, no veto, and nothing here is
read by them.

## Three levels, and replace rather than merge

Most specific first: one **model** on one seat; the whole **seat**; **shared** by every open seat.
Each of the two texts is taken from the most specific level that sets it, so a seat's own role over
a shared device spec reads as both, and a model's own role replaces the seat's. Two roles are never
joined — "an auditor" plus "a blind user" reads as nonsense — and the record says which level
applied.

## Shape

One entry is `{"seat": ..., "model": ..., "role": ..., "spec": {...}}`. No `seat` is the shared
level; a `seat` with no `model` is the whole seat. `spec` is `{"kind": "text", "text": "..."}`
(inline) or `{"kind": "text", "path": "docs/ARCHITECTURE.md"}` (a text file inside the repository).
`kind` is reserved: only `text` exists, and any other is refused rather than ignored
(`docs/MODELS.md` says what a later kind would need). One validator reads every door — the settings
file, the settings screen, the store and the console — so they cannot disagree about what a spec is.

## Where a spec file may be

Inside the directory the runner is started from, which is also where `config/settings.json` is
looked up. No `..`, and the path is resolved with symlinks followed, so a link out of the tree is
refused the same way. The check runs when the spec is saved and again when the run starts, because a
link can be changed in between. A file that cannot be read stops the run before any seat is asked.

## Caps

`MAX_ROLE_CHARS`, `MAX_SPEC_CHARS` (after the file is decoded) and `MAX_SPEC_FILE_BYTES`. A spec is
sent to the seat's model on every round, so each text is bounded, and a file is size-checked before
it is read.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import paths, policy

#: The kinds of spec there are. Only text: a seat reads words and reasons from them. A later kind
#: would attach evidence from a real or emulated run (a CI matrix entry, an emulator profile, a
#: remote device, a measured benchmark); each is its own change and would have to say what runs,
#: where, and what leaves the machine. The field is reserved so that needs no change of shape.
KINDS: Tuple[str, ...] = ("text",)

MAX_ROLE_CHARS = 500
MAX_SPEC_CHARS = 8000
#: Four bytes a character is the most UTF-8 takes, so a file at this size can still decode to the
#: character cap; it is a bound on the read, not a promise about the text.
MAX_SPEC_FILE_BYTES = 32768
MAX_MODEL_CHARS = 200

MODEL, SEAT, SHARED = "model", "seat", "shared"

INLINE, FILE = "inline", "file"

#: The delimiters around the user's text in a brief. A spec that contains the closing line can end
#: its own block early; the runner does not scan for it (the spec's correctness is the user's), and
#: the hash in the record makes such a file visible.
OPEN = ("--- the user's text for this seat. It is the user's, not the runner's, and it never "
        "changes how answers are counted. ---")
CLOSE = "--- end of the user's text ---"

_ENTRY_KEYS = ("seat", "model", "role", "spec")
_SPEC_KEYS = ("kind", "text", "path")


class SeatSpecError(policy.PolicyError):
    """A role or a spec this runner will not act on."""


@dataclass(frozen=True)
class SeatSpec:
    """One level's entry. `seat` empty is shared; `model` empty is the whole seat."""

    seat: str = ""
    model: str = ""
    role: str = ""
    kind: str = ""
    text: str = ""
    path: str = ""

    @property
    def key(self) -> Tuple[str, str]:
        return (self.seat, self.model)

    @property
    def level(self) -> str:
        return MODEL if self.model else SEAT if self.seat else SHARED

    @property
    def has_spec(self) -> bool:
        return bool(self.text or self.path)

    def spec_dict(self) -> Optional[Dict[str, str]]:
        if not self.has_spec:
            return None
        return {"kind": self.kind, **({"path": self.path} if self.path else {"text": self.text})}

    def as_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {}
        if self.seat:
            out["seat"] = self.seat
        if self.model:
            out["model"] = self.model
        if self.role:
            out["role"] = self.role
        if self.has_spec:
            out["spec"] = self.spec_dict()
        return out


@dataclass(frozen=True)
class Loaded:
    """A `SeatSpec` with its spec text in hand: read from the file now, or the inline text."""

    seat: str
    model: str
    role: str
    kind: str
    source: str
    path: str
    text: str
    sha256: str


def root_dir(root: "str | Path | None" = None) -> Path:
    """The directory spec paths are relative to and may not leave: the given one, or the cwd."""
    return Path(root) if root else Path.cwd()


# ── validation: one validator for every door ──────────────────────────────────────────────────────

def check_path(path: object, root: "str | Path | None" = None, *, where: str = "seat_specs") -> str:
    """A spec file's path as stored (relative to the root, forward slashes), or a `SeatSpecError`.

    Refused: a blank path, a `..` component, a path that resolves outside the root (an absolute path
    elsewhere, or a symlink out of the tree), and the root itself. Whether the file exists is not
    asked here: it may be written later, and the run refuses it if it is still missing then.
    """
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        raise SeatSpecError(f"{where}: a spec path must be a non-empty path, got {path!r}")
    text = path.strip().replace("\\", "/")
    if ".." in text.split("/"):
        raise SeatSpecError(f"{where}: spec path {text!r} has a '..' in it. A spec file must sit "
                            f"inside the repository, named without leaving it.")
    base = os.path.realpath(str(root_dir(root)))
    candidate = text if os.path.isabs(text) else os.path.join(base, text)
    real = os.path.realpath(candidate)
    try:
        inside = os.path.commonpath([os.path.normcase(base), os.path.normcase(real)]) \
            == os.path.normcase(base)
    except ValueError:                      # another drive: no common path exists
        inside = False
    if not inside or os.path.normcase(real) == os.path.normcase(base):
        raise SeatSpecError(
            f"{where}: spec path {text!r} resolves to {real}, which is not a file inside the "
            f"repository ({base}). A spec file must sit inside the repository, and a link that "
            f"leaves it does not count as inside.")
    relative = os.path.relpath(os.path.normpath(candidate), base)
    return relative.replace(os.sep, "/")


def _text(value: object, label: str, limit: int, where: str) -> str:
    if not isinstance(value, str):
        raise SeatSpecError(f"{where}: {label} must be text, got {value!r}")
    text = value.strip()
    if len(text) > limit:
        raise SeatSpecError(f"{where}: {label} is {len(text)} characters and the most this runner "
                            f"sends a seat is {limit}. Shorten it.")
    return text


def parse_entry(raw: object, root: "str | Path | None" = None, *, where: str = "seat_specs"
                ) -> SeatSpec:
    """One entry, checked. Unknown keys, an unknown seat or kind and an empty entry are refused."""
    if not isinstance(raw, Mapping):
        raise SeatSpecError(f"{where}: each seat spec must be an object, got {raw!r}")
    unknown = sorted(set(raw) - set(_ENTRY_KEYS))
    if unknown:
        raise SeatSpecError(f"{where}: a seat spec reads {list(_ENTRY_KEYS)} and nothing else, "
                            f"got {unknown}")
    seat = raw.get("seat") or ""
    model = raw.get("model") or ""
    if not isinstance(seat, str) or not isinstance(model, str):
        raise SeatSpecError(f"{where}: seat and model must be text")
    seat, model = seat.strip(), model.strip()
    if seat and seat not in policy.BY_SEAT:
        raise SeatSpecError(f"{where}: no seat {seat!r}; this runner's seats are "
                            f"{', '.join(policy.BY_SEAT)}")
    if model and not seat:
        raise SeatSpecError(f"{where}: a model-level spec says which seat: {model!r} has none")
    if len(model) > MAX_MODEL_CHARS:
        raise SeatSpecError(f"{where}: model id {model[:40]!r}… is longer than "
                            f"{MAX_MODEL_CHARS} characters")
    role = _text(raw.get("role") or "", "role", MAX_ROLE_CHARS, where)
    kind = text = path = ""
    spec = raw.get("spec")
    if spec is not None:
        if not isinstance(spec, Mapping):
            raise SeatSpecError(f"{where}: spec must be an object like "
                                f'{{"kind": "text", "text": "..."}} or '
                                f'{{"kind": "text", "path": "docs/ARCHITECTURE.md"}}, got {spec!r}')
        extra = sorted(set(spec) - set(_SPEC_KEYS))
        if extra:
            raise SeatSpecError(f"{where}: a spec reads {list(_SPEC_KEYS)} and nothing else, "
                                f"got {extra}")
        kind = spec.get("kind", KINDS[0])
        if kind not in KINDS:
            raise SeatSpecError(
                f"{where}: spec kind {kind!r} does not exist; the kinds are {list(KINDS)}. A kind "
                f"that hands a seat evidence from a real or emulated run is a later change.")
        given = [k for k in ("text", "path") if spec.get(k) not in (None, "")]
        if len(given) != 1:
            raise SeatSpecError(f"{where}: a spec has either `text` (inline) or `path` (a file in "
                                f"the repository), exactly one; got {given or 'neither'}")
        if given[0] == "text":
            text = _text(spec["text"], "spec text", MAX_SPEC_CHARS, where)
            if not text:
                raise SeatSpecError(f"{where}: spec text is blank")
        else:
            path = check_path(spec["path"], root, where=where)
    if not role and not (text or path):
        raise SeatSpecError(f"{where}: a seat spec sets neither a role nor a spec")
    return SeatSpec(seat=seat, model=model, role=role, kind=kind, text=text, path=path)


def parse(value: object, root: "str | Path | None" = None, *, where: str = "seat_specs"
          ) -> Tuple[SeatSpec, ...]:
    """The `seat_specs` list: `None` is none; a repeat of one (seat, model) is refused."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise SeatSpecError(f"{where}: seat_specs must be a list of objects or null, got {value!r}")
    out: List[SeatSpec] = []
    for raw in value:
        # A `SeatSpec` is checked again as the object it would be written as: the path may have
        # been fine when it was built and not be now.
        entry = parse_entry(raw.as_dict() if isinstance(raw, SeatSpec) else raw, root, where=where)
        if any(entry.key == other.key for other in out):
            raise SeatSpecError(
                f"{where}: more than one spec for {describe_key(entry.key)}. One level holds one "
                f"role and one spec; a more specific level replaces a less specific one.")
        out.append(entry)
    return tuple(out)


def describe_key(key: Tuple[str, str]) -> str:
    seat, model = key
    return (f"model {model!r} on seat {seat!r}" if model
            else f"seat {seat!r}" if seat else "every open seat (shared)")


def merge(settings: Sequence[SeatSpec], stored: Sequence[SeatSpec]
          ) -> Tuple[Tuple[SeatSpec, ...], Dict[Tuple[str, str], str]]:
    """The entries in force, and where each came from: `settings` or `store`.

    The settings file is written by hand and wins where it speaks, as the plan does over the store
    for models; the store (the console) fills where it is silent. An entry replaces the other
    source's entry for the same level as a whole — it is not merged field by field.
    """
    source: Dict[Tuple[str, str], str] = {}
    out: Dict[Tuple[str, str], SeatSpec] = {}
    for origin, entries in (("store", stored), ("settings", settings)):
        for entry in entries:
            out[entry.key] = entry
            source[entry.key] = origin
    ordered = sorted(out.values(), key=lambda e: (e.seat != "", e.seat, e.model != "", e.model))
    return tuple(ordered), source


# ── reading the files, once, before any seat is asked ─────────────────────────────────────────────

def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_file(path: str, root: "str | Path | None" = None, *, where: str = "seat_specs") -> str:
    """The text of a spec file, or a `SeatSpecError` that names the file and why.

    The containment check is made again here: a link can be changed between save and run.
    """
    relative = check_path(path, root, where=where)
    target = root_dir(root) / relative
    try:
        real = paths.real(target)
        if not os.path.isfile(real):
            raise SeatSpecError(f"{where}: spec file {relative} does not exist or is not a file")
        size = os.path.getsize(real)
        if size > MAX_SPEC_FILE_BYTES:
            raise SeatSpecError(f"{where}: spec file {relative} is {size} bytes and the most this "
                                f"runner reads is {MAX_SPEC_FILE_BYTES}")
        text = paths.read_text(target, encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise SeatSpecError(f"{where}: spec file {relative} cannot be read as UTF-8 text: "
                            f"{type(exc).__name__}: {paths.plain_in(str(exc))}") from exc
    if not text:
        raise SeatSpecError(f"{where}: spec file {relative} is empty")
    if len(text) > MAX_SPEC_CHARS:
        raise SeatSpecError(f"{where}: spec file {relative} is {len(text)} characters and the most "
                            f"this runner sends a seat is {MAX_SPEC_CHARS}")
    return text


def load(specs: Iterable[SeatSpec], seats: Sequence[str], root: "str | Path | None" = None
         ) -> Dict[Tuple[str, str], Loaded]:
    """Every spec that can apply to the seats about to open, with its text read.

    Shared entries and entries for an opened seat are read; an entry for a seat this run does not
    open is not (a stale file there must not stop a run that never asks that seat). A file that
    cannot be read raises, so the walk stops before it asks anybody.
    """
    out: Dict[Tuple[str, str], Loaded] = {}
    for entry in specs:
        if entry.seat and entry.seat not in seats:
            continue
        if entry.path:
            text, source = read_file(entry.path, root, where=describe_key(entry.key)), FILE
        else:
            text, source = entry.text, INLINE
        out[entry.key] = Loaded(
            seat=entry.seat, model=entry.model, role=entry.role, kind=entry.kind, source=source,
            path=entry.path, text=text, sha256=digest(text) if text else "")
    return out


# ── the brief ─────────────────────────────────────────────────────────────────────────────────────

def _chain(by_key: Mapping[Tuple[str, str], object], seat: str, model: Optional[str]):
    """The entries that can apply to one (seat, model), most specific first, with their level."""
    for key, level in (((seat, model or ""), MODEL), ((seat, ""), SEAT), (("", ""), SHARED)):
        if level == MODEL and not model:
            continue
        entry = by_key.get(key)
        if entry is not None:
            yield level, entry


def levels(entries: Iterable[SeatSpec], seat: str, model: Optional[str]
           ) -> Dict[str, Optional[str]]:
    """Which level a (seat, model)'s role and spec come from, or `None`. For the console."""
    chain = list(_chain({e.key: e for e in entries}, seat, model))
    return {"role": next((lv for lv, e in chain if e.role), None),
            "spec": next((lv for lv, e in chain if e.has_spec), None)}


def brief_for(loaded: Mapping[Tuple[str, str], Loaded], seat: str, model: Optional[str]
              ) -> Optional[Dict[str, object]]:
    """The role and spec one (seat, model) session is given, with the level each came from.

    `None` when neither applies: that session is asked today's question and nothing more. Each text
    comes from the most specific level that sets it.
    """
    role: Optional[Dict[str, object]] = None
    spec: Optional[Dict[str, object]] = None
    for level, entry in _chain(loaded, seat, model):
        if role is None and entry.role:
            role = {"text": entry.role, "level": level}
        if spec is None and entry.text:
            spec = {"kind": entry.kind, "source": entry.source,
                    "path": entry.path or None, "text": entry.text, "sha256": entry.sha256,
                    "level": level}
    if role is None and spec is None:
        return None
    return {"role": role, "spec": spec}


def render(brief: Optional[Mapping[str, object]]) -> str:
    """The text appended to the seat's instructions, or `""` — today's brief, byte for byte."""
    if not brief:
        return ""
    lines = [OPEN]
    if brief.get("role"):
        lines.append(f"Review as: {brief['role']['text']}")
    if brief.get("spec"):
        lines.append(f"Judge against this spec: {brief['spec']['text']}")
    lines.append(CLOSE)
    return "\n\n" + "\n".join(lines)


def summary(brief: Optional[Mapping[str, object]]) -> str:
    """One line for the report. A seat with neither says so, so an empty one is visible."""
    # A journaled record is a dict even for a seat with neither, so ask for the two texts.
    if not brief or not (brief.get("role") or brief.get("spec")):
        return "no role, no spec"
    parts = []
    if brief.get("role"):
        parts.append(f"role from the {brief['role']['level']} level")
    if brief.get("spec"):
        spec = brief["spec"]
        named = f" ({spec['path']})" if spec.get("path") else ""
        parts.append(f"spec {spec['source']}{named} from the {spec['level']} level")
    return "; ".join(parts) + (" — reasoned from the text, not measured on a device"
                                if brief.get("spec") else "")
