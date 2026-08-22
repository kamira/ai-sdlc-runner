"""Tests for the reference decomposer (CHG-20260822-04 task 1).

The three ``done-when`` clauses of task 1 map to three groups here, in order: **determinism** (same
store in, byte-identical elements out), **traceability** (every element traces to a source anchor,
and the elements reconstruct the source exactly), and **provenance** (generator version, source
path, source SHA-256, emitted SHA-256).

The remaining groups pin the two runner-authored heuristics that CHG-20260822-04 D3 requires to be
named: fenced-code headings are not anchors, and the hash basis is LF-normalised content. The second
one is not a style preference — with ``* text=auto`` in ``.gitattributes`` the store checks out CRLF
on Windows and LF on Linux, and CI runs both, so a raw-bytes hash would split the matrix.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ai_sdlc_runner import decompose

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "skills" / "v1.64.0"


@pytest.fixture(scope="module")
def store() -> Path:
    """The vendored store this task decomposes. Skipped rather than failed if a checkout lacks it."""
    if not (STORE / "references").is_dir():
        pytest.skip(f"vendored store not present: {STORE}")
    return STORE


@pytest.fixture(scope="module")
def elements(store):
    return decompose.decompose_store(store)


def _tree(root: Path):
    """Every file under ``root`` as ``{relative posix path: bytes}`` — the unit determinism is judged in."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --------------------------------------------------------------------------------------
# done-when 1 — determinism
# --------------------------------------------------------------------------------------

def test_two_emits_are_byte_identical(store, tmp_path):
    """Same store in, byte-identical output out — the whole point of a regeneration gate (task 4)."""
    a, b = tmp_path / "a", tmp_path / "b"
    decompose.emit(store, a)
    decompose.emit(store, b)
    tree_a, tree_b = _tree(a), _tree(b)
    assert sorted(tree_a) == sorted(tree_b)
    differing = [name for name in tree_a if tree_a[name] != tree_b[name]]
    assert differing == []


def test_decompose_store_is_stable_across_calls(store):
    """Determinism holds in memory too, not only after a round-trip through the filesystem."""
    assert decompose.decompose_store(store) == decompose.decompose_store(store)


def test_manifest_holds_no_machine_specific_paths(store, tmp_path):
    """A manifest carrying an absolute path would differ per checkout and defeat byte-comparison."""
    decompose.emit(store, tmp_path)
    text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert str(STORE) not in text
    manifest = json.loads(text)
    assert manifest["skill_version"] == "1.64.0"
    assert manifest["element_count"] == len(manifest["elements"])
    for record in manifest["elements"]:
        assert not record["source_path"].startswith("/")
        assert ":" not in record["source_path"]          # no Windows drive letter


def test_manifest_json_is_key_sorted(store, tmp_path):
    """dict iteration order must not leak into the bytes; ``sort_keys`` is what prevents it."""
    decompose.emit(store, tmp_path)
    raw = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------------------
# done-when 2 — traceability
# --------------------------------------------------------------------------------------

def test_every_element_traces_to_a_source_anchor(elements):
    """Anchored elements start on their heading line; the preamble is the file's title."""
    assert elements
    for e in elements:
        assert e.source_path.startswith("references/")
        assert e.anchor_slug and e.anchor_slug in e.element_id
        assert e.anchor_slug in e.rel_path
        assert 1 <= e.line_start <= e.line_end
        if e.level in (2, 3):
            first = e.body.split("\n", 1)[0]
            assert first.startswith("#" * e.level + " ")
            assert first[e.level:].strip() == e.anchor
        else:
            assert e.level == 1                          # preamble only


def test_elements_reconstruct_each_source_byte_for_byte(store):
    """The strongest form of traceability: a split, not a rewrite — nothing dropped, nothing reordered."""
    for path in decompose.reference_paths(store):
        source = decompose.normalize(path.read_bytes())
        parts = decompose.decompose_reference(path, f"references/{path.name}")
        assert "".join(p.body for p in parts) == source, path.name


def test_element_line_spans_are_contiguous_and_complete(store):
    """Spans tile the file with no gap and no overlap, so a work order can cite lines safely."""
    for path in decompose.reference_paths(store):
        line_count = len(decompose.normalize(path.read_bytes()).split("\n"))
        parts = decompose.decompose_reference(path, f"references/{path.name}")
        assert parts[0].line_start == 1
        assert parts[-1].line_end == line_count
        for previous, current in zip(parts, parts[1:]):
            assert current.line_start == previous.line_end + 1


def test_sub_reference_granularity_is_reached(elements):
    """D1 requires sub-reference granularity: level-3 sections are their own elements, parented."""
    level3 = [e for e in elements if e.level == 3]
    assert level3
    for e in level3:
        assert e.parent_slug is not None
    assert all(e.parent_slug is None for e in elements if e.level != 3)


def test_element_ids_are_unique(elements):
    """Duplicate headings are real in these references; ids must still be unique and stable."""
    ids = [e.element_id for e in elements]
    assert len(ids) == len(set(ids))


def test_both_languages_are_decomposed(elements):
    """``role_refs.json`` maps roles to ``<name>.md (+ .zh-tw.md)``; dropping a language would
    leave those loadouts with no element, which task 6 turns into a hard error."""
    langs = {e.lang for e in elements}
    assert langs == {"en", "zh-tw"}
    zh = [e for e in elements if e.lang == "zh-tw"]
    assert any("一" <= ch <= "鿿" for e in zh for ch in e.anchor_slug)


# --------------------------------------------------------------------------------------
# done-when 3 — provenance
# --------------------------------------------------------------------------------------

def test_provenance_is_complete_and_verifiable(store):
    """Every element carries generator + version + source path + source sha + emitted sha, and both
    hashes actually verify against the bytes they claim to describe."""
    for path in decompose.reference_paths(store):
        expected_source = hashlib.sha256(
            decompose.normalize(path.read_bytes()).encode("utf-8")
        ).hexdigest()
        for e in decompose.decompose_reference(path, f"references/{path.name}"):
            assert e.generator == decompose.GENERATOR
            assert e.generator_version == decompose.GENERATOR_VERSION
            assert e.source_path == f"references/{path.name}"
            assert e.source_sha256 == expected_source
            assert e.emitted_sha256 == hashlib.sha256(e.body.encode("utf-8")).hexdigest()


def test_emitted_bodies_match_their_recorded_hash(store, tmp_path):
    """The gate compares files on disk, so the recorded hash must describe the emitted file."""
    manifest = decompose.emit(store, tmp_path)
    for record in manifest["elements"]:
        written = (tmp_path / record["rel_path"]).read_bytes()
        assert hashlib.sha256(written).hexdigest() == record["emitted_sha256"]


# --------------------------------------------------------------------------------------
# heuristic A — fenced-code headings are not anchors
# --------------------------------------------------------------------------------------

def test_fenced_code_headings_are_not_anchors(store):
    """``structure-design.md`` (v1.64.0) shows 17 skeleton headings inside fences and has 11 real
    ones. Splitting on the skeletons would invent elements and shred the prose around them."""
    parts = decompose.decompose_reference(
        store / "references" / "structure-design.md", "references/structure-design.md"
    )
    anchored = [p for p in parts if p.level in (2, 3)]
    assert len(anchored) == 11
    assert len(parts) == 12                              # + the preamble
    shown_only = {"Tree", "Layers / modules", "Main flows", "Entities / tables", "Relations"}
    assert not shown_only & {p.anchor for p in anchored}


def test_longer_fence_is_not_closed_by_a_shorter_one():
    """CommonMark: a ```` ``` ```` displayed inside a ```` ```` ```` block closes nothing, so the
    heading after it stays inside the fence."""
    text = "# T\n\n````\n```\n## Shown\n```\n````\n\n## Real\n\nbody\n"
    parts = decompose.decompose_text(text, "references/x.md")
    assert [p.anchor for p in parts] == ["T", "Real"]


def test_tilde_fences_are_tracked_too():
    text = "# T\n\n~~~\n## Shown\n~~~\n\n## Real\n\nbody\n"
    parts = decompose.decompose_text(text, "references/x.md")
    assert [p.anchor for p in parts] == ["T", "Real"]


# --------------------------------------------------------------------------------------
# heuristic B — LF-normalised hash basis (the OS-matrix guard)
# --------------------------------------------------------------------------------------

def test_crlf_and_lf_sources_produce_identical_elements(tmp_path):
    """The regression this exists for: ``* text=auto`` gives Windows CRLF and Linux LF for the same
    blob. If the hash basis were raw bytes, task 4's gate would hard-fail on one leg of the CI
    matrix for a store nobody touched (the shape of CHG-20260817-09's Windows-only failures)."""
    body = "---\nname: x\n---\n\n# T\n\n## A\n\nalpha\n\n## B\n\nbeta\n"
    lf, crlf = tmp_path / "lf.md", tmp_path / "crlf.md"
    lf.write_bytes(body.encode("utf-8"))
    crlf.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))

    from_lf = decompose.decompose_reference(lf, "references/x.md")
    from_crlf = decompose.decompose_reference(crlf, "references/x.md")
    assert from_lf == from_crlf


def test_emitted_files_never_contain_cr(store, tmp_path):
    """Emission must not undo the normalisation at the last step — hence ``write_bytes``, never
    ``open(..., "w")``, whose newline translation would write CRLF on Windows."""
    decompose.emit(store, tmp_path)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"\r" not in path.read_bytes(), path


# --------------------------------------------------------------------------------------
# segmentation edge cases
# --------------------------------------------------------------------------------------

def test_preamble_captures_frontmatter_and_title():
    text = "---\nname: h\n---\n\n# Handshake\n\nintro\n\n## Purpose\n\nbody\n"
    parts = decompose.decompose_text(text, "references/handshake.md")
    assert parts[0].level == 1
    assert parts[0].anchor == "Handshake"
    assert "name: h" in parts[0].body
    assert parts[1].anchor == "Purpose"


def test_file_opening_on_a_heading_gets_no_preamble():
    parts = decompose.decompose_text("## Only\n\nbody\n", "references/x.md")
    assert len(parts) == 1
    assert parts[0].level == 2


def test_file_without_any_heading_is_one_element():
    parts = decompose.decompose_text("just prose\n", "references/x.md")
    assert len(parts) == 1
    assert parts[0].level == 1
    assert parts[0].anchor == "x.md"


def test_duplicate_headings_get_stable_distinct_slugs():
    text = "# T\n\n## Purpose\n\na\n\n## Purpose\n\nb\n\n## Purpose\n\nc\n"
    parts = decompose.decompose_text(text, "references/x.md")
    assert [p.anchor_slug for p in parts[1:]] == ["purpose", "purpose-2", "purpose-3"]
    assert decompose.decompose_text(text, "references/x.md") == parts


def test_slug_strips_markdown_and_keeps_cjk():
    assert decompose.slugify("**Why** this `matters`") == "why-this-matters"
    assert decompose.slugify("進場握手 — 固定順序") == "進場握手-固定順序"
    assert decompose.slugify("###") == "section"


def test_missing_references_directory_is_an_error(tmp_path):
    with pytest.raises(decompose.DecomposeError):
        decompose.decompose_store(tmp_path)


def test_missing_reference_file_is_an_error(tmp_path):
    with pytest.raises(decompose.DecomposeError):
        decompose.decompose_reference(tmp_path / "nope.md")
