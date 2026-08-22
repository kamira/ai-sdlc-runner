"""Tests for the dispatch-element derivation (CHG-20260822-04 task 2).

The task's done-when is two clauses — "every gate and decision point covered" and "no hand-written
node ids" — and both are checked against the shipped files rather than against numbers written here.
Coverage compares emitted ids to the policy JSONs' own keys; the no-hand-written-ids check reads
this repo's own source and asserts that not one of the 24 node ids appears in it as a literal.

The remaining groups carry forward what task 1 established (determinism, provenance, LF-only bytes)
and pin the three decisions the review panel converged on in round 2: the two checkpoint namespaces
stay un-deduplicated, situational flags are never evaluated at generation time, and risk stays a
runtime parameter rather than part of an element key.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sdlc_runner import decompose, dispatch

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "skills" / "v1.64.0"


@pytest.fixture(scope="module")
def store() -> Path:
    if not (STORE / "assets").is_dir():
        pytest.skip(f"vendored store not present: {STORE}")
    return STORE


@pytest.fixture(scope="module")
def cps(store):
    return dispatch.checkpoints(store)


@pytest.fixture(scope="module")
def roles(store):
    return dispatch.role_loadouts(store)


@pytest.fixture(scope="module")
def sits(store):
    return dispatch.situational_sets(store)


def _policy(store, name):
    return json.loads((store / "assets" / name).read_text(encoding="utf-8-sig"))


def _literals_in_dispatch_source(names):
    """Which of ``names`` appear as a quoted string literal in dispatch.py's executable part.

    The module docstring legitimately names ids while explaining the design, so it is excluded; and
    the match is on the quoted literal, never a bare substring — see the note in
    ``test_no_node_id_is_written_in_the_source``.
    """
    source = (REPO_ROOT / "src" / "ai_sdlc_runner" / "dispatch.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]
    return [n for n in names if f'"{n}"' in code or f"'{n}'" in code]


def _tree(root: Path):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


# --------------------------------------------------------------------------------------
# done-when — every gate and decision point covered
# --------------------------------------------------------------------------------------

def test_coverage_matches_the_shipped_policy_exactly(store):
    """Coverage is judged against the files' own keys, so it cannot drift from them."""
    cov = dispatch.coverage(store)
    assert cov["declared"] == cov["emitted"]
    assert cov["declared"]["halt"], "the shipped halt policy declares no gates"
    assert cov["declared"]["autopilot"], "the shipped autopilot policy declares no decision points"
    assert cov["declared"]["roles"], "the shipped role table declares no roles"


def test_every_halt_gate_becomes_a_checkpoint(store, cps):
    declared = set(_policy(store, "halt_policy.json")["gates"])
    assert {c.key for c in cps if c.namespace == "halt"} == declared


def test_every_autopilot_decision_point_becomes_a_checkpoint(store, cps):
    defaults = _policy(store, "autopilot_policy.json")["defaults"]
    declared = {p for row in defaults.values() for p in row}
    assert {c.key for c in cps if c.namespace == "autopilot"} == declared


def test_every_role_becomes_a_loadout(store, roles):
    assert {r.role for r in roles} == set(_policy(store, "role_refs.json")["roles"])


# --------------------------------------------------------------------------------------
# done-when — no hand-written node ids
# --------------------------------------------------------------------------------------

def test_no_node_id_is_written_in_the_source(store, cps, roles):
    """The strong form: every id is read from a shipped file, so none may appear in our source.

    Written as an absence check because the failure it guards against — someone "helpfully" adding a
    missing gate by hand — reads as a fix and would leave coverage green while the ids stopped being
    derived. Container keys like ``gates`` and ``defaults`` are structure, not ids, and are allowed.

    It looks for the id **as a string literal**, not as a substring: a substring search reports
    ``merge`` inside "merged" and ``pr`` inside "preauthorizable". That is the same false-positive
    trap that killed the anchor-matching option in the panel's Q2 (0 true positives, 21 false ones),
    and it bit this very test on first run.
    """
    ids = [c.key for c in cps] + [r.role for r in roles]
    assert ids
    assert _literals_in_dispatch_source(ids) == []


def test_situational_flag_names_are_not_written_in_the_source(store, roles):
    flags = sorted(_policy(store, "role_refs.json")["situational"])
    assert flags
    assert _literals_in_dispatch_source(flags) == []


# --------------------------------------------------------------------------------------
# panel decision 1 — the two namespaces stay un-deduplicated
# --------------------------------------------------------------------------------------

def test_namespaces_are_unioned_verbatim_without_dedup(store, cps):
    """``before_merge_or_release`` and ``merge`` are semantically related but no shipped file says
    so; merging them would need a hand-written key. Both survive, each under its own namespace."""
    halt = {c.key for c in cps if c.namespace == "halt"}
    auto = {c.key for c in cps if c.namespace == "autopilot"}
    assert len(cps) == len(halt) + len(auto)
    assert len({c.element_id for c in cps}) == len(cps)
    for c in cps:
        assert c.element_id == f"{c.namespace}:{c.key}"


def test_role_and_checkpoint_are_not_multiplied(cps, roles):
    """The join is the engine's job at dispatch: no element claims a role stands at a checkpoint,
    because no shipped file asserts that pairing."""
    for c in cps:
        assert "role" not in c.record()
    for r in roles:
        rendered = json.dumps(r.record(), ensure_ascii=False)
        assert not any(c.element_id in rendered for c in cps)


# --------------------------------------------------------------------------------------
# panel decision 2 — anchors come from the role's shipped file set; nothing is narrowed or dropped
# --------------------------------------------------------------------------------------

def test_loadout_covers_common_plus_the_role_refs(store, roles):
    cfg = _policy(store, "role_refs.json")
    for r in roles:
        assert r.base_references == cfg["common"] + cfg["roles"][r.role]


def test_loadout_ids_point_at_real_content_elements(store, roles, sits):
    """Every content element a dispatch element names must exist — the join that would otherwise
    fail silently at dispatch time. `check_dangling` runs the same proof at generation time."""
    known = {e.element_id for e in decompose.decompose_store(store)}
    assert known
    for r in roles:
        for lang, ids in r.base_element_ids.items():
            assert ids, f"{r.role} has no {lang} elements"
            assert all(i in known for i in ids)
    for st in sits:
        for lang, ids in st.element_ids.items():
            assert ids and all(i in known for i in ids)
    assert dispatch.check_dangling(store) == []


def test_loadout_names_ids_and_nothing_else(roles):
    """D5, and the A2 repackaging: a loadout carries content element **ids**, never bodies and
    never a copy of the fields `manifest.json` already holds authoritatively."""
    for r in roles:
        rendered = json.dumps(r.payload(), ensure_ascii=False)
        assert "body" not in rendered
        for ids in r.base_element_ids.values():
            assert all(isinstance(i, str) for i in ids)


def test_a_reference_with_no_element_is_a_hard_error(store, tmp_path):
    """A loadout that quietly lost a reference is the exact failure task 6 turns into a hard error;
    it must not be representable as an empty anchor list."""
    fake = tmp_path / "store"
    (fake / "assets").mkdir(parents=True)
    (fake / "references").mkdir()
    (fake / "assets" / "role_refs.json").write_bytes(json.dumps({
        "common": [], "roles": {"r": ["nope"]}, "situational": {}, "aliases": {},
    }).encode("utf-8"))
    with pytest.raises(dispatch.DispatchError) as exc:
        dispatch.role_loadouts(fake)
    assert "nope" in str(exc.value)


# --------------------------------------------------------------------------------------
# panel decision 3 — risk is a runtime parameter; the halt lists travel complete
# --------------------------------------------------------------------------------------

def test_risk_is_not_part_of_any_element_key(store, cps):
    """Elements are per-store-version artifacts; a CHG's risk does not exist when they are built,
    and burning a verdict in would bypass the tighten-only Autonomy override."""
    risks = set(_policy(store, "autopilot_policy.json")["defaults"])
    for c in cps:
        assert not any(c.element_id.endswith(f":{r}") for r in risks)
    assert len({c.element_id for c in cps}) == len(cps)


def test_each_checkpoint_carries_its_risk_table_verbatim(store, cps):
    halt = _policy(store, "halt_policy.json")["gates"]
    defaults = _policy(store, "autopilot_policy.json")["defaults"]
    for c in cps:
        if c.namespace == "halt":
            assert c.risk_table == halt[c.key]
        else:
            assert c.risk_table == {risk: row[c.key] for risk, row in defaults.items()}


def test_both_halt_lists_travel_complete_namespaced_and_unmerged(store, cps):
    """Filtering to "the ones this node could hit" would need a hand-written node→hazard table, and
    every omission would silently disarm a gate (KN-4). The two lists differ and stay separate."""
    halt = _policy(store, "halt_policy.json")
    auto = _policy(store, "autopilot_policy.json")
    expected = {
        "halt_policy.json#always_halt_actions": halt["always_halt_actions"],
        "autopilot_policy.json#permanent_halts": auto["permanent_halts"],
    }
    assert expected["halt_policy.json#always_halt_actions"] != expected[
        "autopilot_policy.json#permanent_halts"]
    for c in cps:
        assert c.unconditional_halts == expected
        assert c.preauthorizable == auto["preauthorizable"]


def test_halt_axis_delegates_to_the_shipped_script(store, cps):
    """FR-8 / guideline §8: the runner calls the skill's resolver, it does not re-derive verdicts."""
    for c in (c for c in cps if c.namespace == "halt"):
        assert c.resolver["kind"] == "shipped_script"
        assert (store / c.resolver["script"]).is_file()
        assert c.resolver["exit_codes"] == {"0": "AUTO", "10": "HALT"}
        assert c.resolver["arguments"]["gate"] == c.key


def test_autopilot_axis_states_that_no_resolver_ships(store, cps):
    """Measured, not assumed: autopilot_runner.py is present but its lib/ package was not archived,
    so it cannot be imported from the store. The element says so instead of implying a resolver."""
    assert (store / "scripts" / "autopilot_runner.py").is_file()
    assert not (store / "scripts" / "lib").exists()
    for c in (c for c in cps if c.namespace == "autopilot"):
        assert c.resolver["kind"] == "embedded_table"
        assert c.resolver["shipped_resolver"] is None
        assert c.resolver["tighten_only"] is True


def test_situational_sets_are_present_but_never_evaluated(store, roles, sits):
    """Every flag exists as its own element and every role names all of them. Flipping a flag at
    dispatch selects among data already in the artifact instead of changing what the artifact
    contains — which is what keeps task 4's byte-comparison meaningful."""
    cfg = _policy(store, "role_refs.json")["situational"]
    assert {st.flag for st in sits} == set(cfg)
    for st in sits:
        assert st.references == cfg[st.flag]
        assert st.element_ids
    expected = sorted(f"situational:{flag}" for flag in cfg)
    for r in roles:
        assert sorted(r.situational_refs) == expected


def test_situational_sets_are_emitted_once_not_per_role(store, tmp_path):
    """The A2 fix, pinned. Inlining the five sets into all 13 role manifests produced 265 KB of
    byte-identical duplication and a 54,670-byte role file — larger than the biggest reference in
    the corpus the whole design exists to stop nodes from paying for."""
    dispatch.emit(store, tmp_path)
    sit_files = sorted((tmp_path / "dispatch" / "situational").glob("*.json"))
    assert len(sit_files) == len(_policy(store, "role_refs.json")["situational"])
    for role_file in (tmp_path / "dispatch" / "roles").glob("*.json"):
        body = role_file.read_text(encoding="utf-8")
        assert len(body) < 15_000, f"{role_file.name} is {len(body)} bytes — the A2 defect is back"
        # the flag is named, its contents are not copied in
        assert '"references"' in body
        assert "situational:" in body


# --------------------------------------------------------------------------------------
# determinism and provenance, on task 1's terms
# --------------------------------------------------------------------------------------

def test_two_emits_are_byte_identical(store, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    dispatch.emit(store, a)
    dispatch.emit(store, b)
    tree_a, tree_b = _tree(a), _tree(b)
    assert sorted(tree_a) == sorted(tree_b)
    assert [n for n in tree_a if tree_a[n] != tree_b[n]] == []


def test_derivation_is_stable_across_calls(store):
    assert dispatch.checkpoints(store) == dispatch.checkpoints(store)
    assert dispatch.role_loadouts(store) == dispatch.role_loadouts(store)
    assert dispatch.situational_sets(store) == dispatch.situational_sets(store)


def test_provenance_is_complete_and_verifiable(store, cps, roles, sits):
    """Same four fields task 1 established, and the emitted hash must describe the emitted file."""
    expected = {
        "assets/halt_policy.json": decompose.sha256(
            decompose.normalize((store / "assets" / "halt_policy.json").read_bytes())),
        "assets/autopilot_policy.json": decompose.sha256(
            decompose.normalize((store / "assets" / "autopilot_policy.json").read_bytes())),
        "assets/role_refs.json": decompose.sha256(
            decompose.normalize((store / "assets" / "role_refs.json").read_bytes())),
    }
    for e in list(cps) + list(roles) + list(sits):
        assert e.generator == dispatch.GENERATOR
        assert e.generator_version == dispatch.GENERATOR_VERSION
        assert e.source_sha256 == expected[e.source_path]
        assert e.emitted_sha256


def test_emitted_files_match_their_recorded_hash(store, tmp_path):
    manifest = dispatch.emit(store, tmp_path)
    for record in manifest["elements"]:
        written = (tmp_path / record["rel_path"]).read_bytes()
        assert decompose.sha256(written.decode("utf-8")) == record["emitted_sha256"]


def test_manifest_is_key_sorted_and_machine_independent(store, tmp_path):
    dispatch.emit(store, tmp_path)
    raw = (tmp_path / "dispatch" / "manifest.json").read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert str(tmp_path) not in raw and str(STORE) not in raw
    manifest = json.loads(raw)
    assert manifest["skill_version"] == "1.64.0"
    assert (manifest["checkpoint_count"] + manifest["role_count"]
            + manifest["situational_count"]) == len(manifest["elements"])


def test_emitted_files_never_contain_cr(store, tmp_path):
    dispatch.emit(store, tmp_path)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"\r" not in path.read_bytes(), path


def test_missing_policy_asset_is_an_error(tmp_path):
    with pytest.raises(dispatch.DispatchError):
        dispatch.checkpoints(tmp_path)
