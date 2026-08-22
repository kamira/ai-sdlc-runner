"""decompose.py — split a vendored skill's references into dispatchable, anchored elements.

CHG-20260822-04 task 1 (D1, "content elements"). The runner dispatches one node at a time, and a
node that needs one section of ``modification-guide.md`` must not pay for the whole 343,366-byte
reference corpus. This module is the deterministic transform that makes that possible: a reference
goes in, a list of ``Element`` records comes out, each one a byte-exact slice of the source anchored
at a stable ``##``/``###`` heading, each one carrying the provenance needed to prove it still
matches the store it came from.

Three properties are load-bearing, and each is pinned by a test in ``tests/test_decompose.py``:

1. **Deterministic.** Same store in, byte-identical elements out. No timestamps, no absolute paths,
   no dict-order leakage (JSON is emitted with ``sort_keys``), no filesystem iteration order (paths
   are sorted).
2. **Traceable.** Every element is a contiguous slice of its source and names the anchor it came
   from; concatenating a file's elements in order reproduces the source exactly. Nothing is
   summarised, reordered or dropped — this is a *split*, not a rewrite.
3. **Provenanced.** Every element records the generator and its version, the store-relative source
   path, the source SHA-256 and its own emitted SHA-256, so task 4's regeneration gate can
   three-state the result (match / regenerable drift / source missing).

Two implementation decisions are runner-authored interpretation, not skill content, and CHG-20260822-04
D3 requires them to be named as the fork points they are:

**A. Headings inside fenced code blocks are not anchors.** Measured against ``skills/v1.64.0``: of
257 lines matching ``^##?#`` across the 23 English references, **56 sit inside ``` fences** — they
are document skeletons being *shown* (``structure-design.md`` alone accounts for 17), not sections of
the reference. Splitting on them would invent 56 elements and shred the surrounding prose. The fence
tracker follows the CommonMark rule (a fence closes only on the same character, at least as long),
so a ```` ``` ```` shown inside a ```` ```` ```` block does not terminate anything.

**B. The hash basis is LF-normalised content, not raw working-tree bytes.** This repo's
``.gitattributes`` is ``* text=auto``, so all 46 store references check out CRLF on Windows and LF on
Linux while the git blob stays LF. Hashing raw bytes would make ``source_sha256`` **OS-dependent**,
and CI runs ``{ubuntu, windows}`` — task 4's gate would hard-fail on one leg of the matrix for a
store that never changed. That is the same shape as the five Windows-only failures CHG-20260817-09
had to fix, so newlines are normalised to ``\\n`` before hashing and before emitting.

The skill itself is never modified: ``skills/<version>/`` stays a verbatim archive and this module
only ever reads it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import contract

#: Identifies the producing code in every element's provenance.
GENERATOR = "ai_sdlc_runner.decompose"

#: Bump whenever the segmentation heuristics change: a different value means elements emitted by an
#: older generator are legitimately different bytes, which is drift the gate must be able to explain
#: rather than a store that moved.
GENERATOR_VERSION = "1"

#: Anchors are ``##`` and ``###`` only (D1). ``#`` is the document title and lives in the preamble.
_HEADING = re.compile(r"^(#{2,3})[ \t]+(\S.*?)[ \t]*$")
_H1 = re.compile(r"^#[ \t]+(\S.*?)[ \t]*$")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")

# Markdown inline markup is stripped from slugs so that an anchor's id does not depend on how the
# heading happens to be emphasised.
_SLUG_STRIP = re.compile(r"[`*_~\[\]()<>]")
_SLUG_SEP = re.compile("[^0-9a-z㐀-䶿一-鿿]+")


class DecomposeError(Exception):
    """Raised when a store cannot be decomposed (missing references, undecodable source)."""


@dataclass(frozen=True)
class Element:
    """One dispatchable slice of one reference.

    ``body`` is the verbatim source text of the section *including* its heading line, LF-normalised.
    It is never inlined into a work order (D5) — a work order carries ``source_path`` plus
    ``anchor_slug``, and the body is read from the emitted element only by whoever actually needs it.
    """

    element_id: str
    source_path: str          # store-relative, POSIX separators
    lang: str                 # "en" | "zh-tw"
    anchor: str               # heading text, verbatim
    anchor_slug: str
    level: int                # 1 = preamble (document title), 2 = ##, 3 = ###
    parent_slug: Optional[str]
    ordinal: int              # 0-based position within its source file
    line_start: int           # 1-based, inclusive, in the LF-normalised source
    line_end: int             # 1-based, inclusive
    rel_path: str             # where emit() writes the body, relative to the output root
    body: str
    generator: str
    generator_version: str
    source_sha256: str
    emitted_sha256: str

    def manifest_record(self) -> Dict[str, object]:
        """The element as it appears in ``manifest.json`` — everything except the body.

        Bodies stay in their own files: a manifest that inlined them would be the whole corpus
        again, which is the cost this decomposition exists to remove.
        """
        record = {
            "element_id": self.element_id,
            "source_path": self.source_path,
            "lang": self.lang,
            "anchor": self.anchor,
            "anchor_slug": self.anchor_slug,
            "level": self.level,
            "parent_slug": self.parent_slug,
            "ordinal": self.ordinal,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "rel_path": self.rel_path,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "source_sha256": self.source_sha256,
            "emitted_sha256": self.emitted_sha256,
        }
        return record


def sha256(text: str) -> str:
    """SHA-256 of ``text`` as UTF-8. Callers pass LF-normalised text — see decision B in the module docstring."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(raw: bytes) -> str:
    """Decode UTF-8 and normalise CRLF / lone CR to LF.

    Applied to every source before hashing or slicing, so a checkout's line endings never reach a
    hash or an emitted byte (decision B).
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:                       # pragma: no cover - store is UTF-8
        raise DecomposeError(f"source is not valid UTF-8: {exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def slugify(heading: str) -> str:
    """Stable, filesystem-safe slug for a heading.

    ASCII is lowercased and word-separated by ``-``; CJK is kept verbatim so the Chinese references
    get readable ids rather than a run of empty separators.
    """
    slug = _SLUG_STRIP.sub("", heading.strip().lower())
    slug = _SLUG_SEP.sub("-", slug).strip("-")
    return slug or "section"


def _lang_of(path: str) -> str:
    """``references/handshake.zh-tw.md`` → ``zh-tw``; anything else → ``en``."""
    return "zh-tw" if path.endswith(".zh-tw.md") else "en"


def _heading_lines(lines: Sequence[str]) -> List[int]:
    """Indices of the lines that are real ``##``/``###`` anchors — fenced code excluded (decision A)."""
    found: List[int] = []
    fence: Optional[str] = None
    for i, line in enumerate(lines):
        marker = _FENCE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None and _HEADING.match(line):
            found.append(i)
    return found


def _document_title(lines: Sequence[str]) -> Optional[str]:
    """The ``# Title`` line, if the preamble has one — it becomes the preamble element's anchor."""
    for line in lines:
        m = _H1.match(line)
        if m:
            return m.group(1)
    return None


def _body_for(lines: Sequence[str], start: int, end: int) -> str:
    """Lines ``[start, end)`` rejoined so that concatenating every span reproduces the source.

    ``text.split("\\n")`` drops the separators, so every span except the file's last one has to carry
    the newline that followed it. Getting this wrong is invisible in a diff and fatal to the
    reconstruction property, which is why a test asserts it directly.
    """
    body = "\n".join(lines[start:end])
    if end < len(lines):
        body += "\n"
    return body


def decompose_text(text: str, source_path: str) -> List[Element]:
    """Split one already-normalised reference into elements.

    The first element is the **preamble** (frontmatter, ``# Title``, and any prose before the first
    anchor); it exists so that nothing in the file is unrepresented — a reference whose frontmatter
    vanished would still look complete while having lost the name and description a dispatched node
    identifies it by. Files that open directly on a ``##`` get no preamble element.
    """
    lines = text.split("\n")
    heads = _heading_lines(lines)
    lang = _lang_of(source_path)
    src_hash = sha256(text)
    stem = source_path[:-3] if source_path.endswith(".md") else source_path

    spans: List[Dict[str, object]] = []
    if not heads or heads[0] > 0:
        end = heads[0] if heads else len(lines)
        title = _document_title(lines[:end])
        spans.append({
            "anchor": title if title is not None else Path(source_path).name,
            "level": 1,
            "start": 0,
            "end": end,
        })
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        m = _HEADING.match(lines[start])
        assert m is not None                                # _heading_lines only returns matches
        spans.append({
            "anchor": m.group(2),
            "level": len(m.group(1)),
            "start": start,
            "end": end,
        })

    used: Dict[str, int] = {}
    parent: Optional[str] = None
    elements: List[Element] = []
    for ordinal, span in enumerate(spans):
        anchor = str(span["anchor"])
        level = int(span["level"])
        base = slugify(anchor)
        seen = used.get(base, 0)
        used[base] = seen + 1
        # Duplicate headings within one file are real (several references reuse "## Purpose" under
        # different parents). Suffixing by occurrence keeps ids unique and stable under re-runs.
        slug = base if seen == 0 else f"{base}-{seen + 1}"
        if level <= 2:
            parent = slug if level == 2 else None
        body = _body_for(lines, int(span["start"]), int(span["end"]))
        elements.append(Element(
            element_id=f"{stem}#{slug}",
            source_path=source_path,
            lang=lang,
            anchor=anchor,
            anchor_slug=slug,
            level=level,
            parent_slug=parent if level == 3 else None,
            ordinal=ordinal,
            line_start=int(span["start"]) + 1,
            line_end=int(span["end"]),
            rel_path=f"elements/{stem}/{ordinal:03d}-{slug}.md",
            body=body,
            generator=GENERATOR,
            generator_version=GENERATOR_VERSION,
            source_sha256=src_hash,
            emitted_sha256=sha256(body),
        ))
    return elements


def decompose_reference(path: str | Path, source_path: Optional[str] = None) -> List[Element]:
    """Read one reference off disk and split it. ``source_path`` is the store-relative id to record."""
    p = Path(path)
    if not p.is_file():
        raise DecomposeError(f"reference not found: {p}")
    rel = source_path if source_path is not None else f"references/{p.name}"
    return decompose_text(normalize(p.read_bytes()), rel)


def reference_paths(skill_path: str | Path) -> List[Path]:
    """Every shipped ``references/*.md`` in the store, sorted — both languages.

    Both, deliberately: ``assets/role_refs.json`` maps a role to ``references/<name>.md (+ .zh-tw.md)``,
    so the Chinese variants are part of the shipped load set. Dropping them would be a hand-made cap
    on the element set, which constraint 8 rules out, and would leave a node whose loadout names a
    ``.zh-tw`` reference with no element at all — task 6 turns that into a hard error.
    """
    refs = Path(skill_path) / "references"
    if not refs.is_dir():
        raise DecomposeError(f"store has no references/ directory: {refs}")
    return sorted(refs.glob("*.md"))


def decompose_store(skill_path: str | Path) -> List[Element]:
    """Split every shipped reference in a store version. Sorted by source path, then file order."""
    elements: List[Element] = []
    for p in reference_paths(skill_path):
        elements.extend(decompose_reference(p, f"references/{p.name}"))
    return elements


def build_manifest(skill_path: str | Path, elements: Sequence[Element]) -> Dict[str, object]:
    """The manifest describing one store version's decomposition.

    Records the store's **version**, never its path: a path is machine-specific and would break the
    byte-identical property the moment the repo is checked out somewhere else.
    """
    return {
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "skill_version": contract.read_skill_version(skill_path),
        "element_count": len(elements),
        "elements": [e.manifest_record() for e in elements],
    }


def _write(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings, no BOM — never ``open(..., "w")``, whose newline translation
    would put CRLF into the artifacts on Windows and undo decision B at the last step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def emit(skill_path: str | Path, out_dir: str | Path) -> Dict[str, object]:
    """Decompose a store version into ``out_dir`` and return the manifest.

    Writes ``manifest.json`` plus one file per element. Byte-identical across runs and across
    platforms: sorted inputs, sorted JSON keys, LF everywhere, no timestamps, no absolute paths.
    """
    out = Path(out_dir)
    elements = decompose_store(skill_path)
    manifest = build_manifest(skill_path, elements)
    for element in elements:
        _write(out / element.rel_path, element.body)
    _write(out / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest
