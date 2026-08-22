"""dispatch.py — derive dispatch elements from the store's shipped policy.

CHG-20260822-04 task 2 (D1, "dispatch elements"). Task 1 turned the references into 448 anchored
content elements; this module derives the elements that say **which** anchors a node gets and
**what the policy says at each checkpoint**. Both come only from the shipped policy JSONs — nothing
here is hand-authored, and a test proves it by asserting that none of the node ids appear as a
literal anywhere in this file.

Two families, deliberately **not** a cartesian product:

* **Checkpoint elements — 11.** The verbatim, un-deduplicated union of two namespaces:
  ``halt:*`` (5 gates from ``halt_policy.json``) and ``autopilot:*`` (6 per-risk decision points
  from ``autopilot_policy.json``). Each carries its own risk table copied verbatim from the shipped
  JSON, both unconditional-halt lists complete and namespaced by source file, and a description of
  how the verdict is resolved.
* **Role loadout manifests — 13.** One per role in ``role_refs.json``, naming the anchors of
  ``common ∪ roles[r]`` plus every ``situational`` set, expanded but **not evaluated**.

The organising principle behind both, and the thing that makes the elements re-generatable:
**generation is complete and unevaluated; selection happens at dispatch.** Risk, situational flags
and language are all left as complete, verbatim data in the element; the engine (task 6) picks. This
is why no CHG, no repo state and no runtime flag can change what this module emits — which is what
task 4's byte-comparison gate needs.

## Why the axes are not multiplied (review panel, round 2, both seats)

The literal reading of D1 — 13 roles × 5 gates × 6 decision points — was rejected by both seats, and
codex switched to this shape in round 2. Two reasons, both checkable:

* **role × checkpoint is not in any shipped file.** Nothing in ``role_refs.json``, ``halt_policy.json``
  or ``autopilot_policy.json`` asserts that (say) ``seat-security`` stands at
  ``requirement_confirmed``. Materialising 143 such pairs would put a runner-invented relation inside
  an artifact whose provenance claims it was derived from shipped policy — worse than leaving the
  join in engine code, because the artifact would misrepresent its own source.
* **Merging the two namespaces would require a hand-written mapping.** ``before_merge_or_release``
  and ``merge`` are plainly related, but the merge key exists in no shipped file — a human would
  have to write it, which is exactly the "hand-written node ids" the done-when forbids. So the union
  is taken **verbatim and un-deduplicated**, and the overlap is resolved where the skill says to
  resolve it: at decision time, by the shipped tighten-only rule
  (``autopilot-loop.md`` "Halt decision order (strict, tighten-only)"; ``halt_policy._doc``
  "只准加嚴").

## Why the anchor set is the role's whole shipped file set

D1 says a dispatch element "names only the section anchors it needs", and the obvious mechanism —
match the policy key names against section headings — was **measured and rejected**. Across all 402
real headings in the 46 shipped references, the 11 policy keys score **zero true positives and 21
false positives** (``pr`` matches "Org **pr**inciples", ``merge`` matches "E**merge**ncy override").
The semantically right anchors do exist and are shipped — ``autonomy.md`` has "Halt gates",
"Decision: risk × gate", "Always-halt actions (regardless of risk)" — but they are reachable by
reading, not by matching key names.

So the finest defensible definition of "needed" in the shipped data is the one ``role_refs.json``
itself gives: ``common ∪ roles[r]`` (+ situational). That still reduces a node's addressable surface
from the 402-anchor / 343,366-byte corpus to roughly 58 anchor ids, and D5 keeps bodies out of the
work order regardless. A matcher with no true positives would have been the KN-4 shape: a gate that
looks like a refinement while quietly selecting nothing.

## Runner-authored fork points (D3 requires these named)

1. **Namespacing and non-deduplication** of the two checkpoint families (``halt:`` / ``autopilot:``).
   A different reader could pick one namespace as canonical and map the other onto it — at the cost
   of the hand-written mapping described above.
2. **The whole-file anchor set** rather than a narrowed one, justified by the zero-true-positive
   measurement above. If the skill ever ships a machine-readable section→checkpoint map, this
   becomes narrowable without changing the element shape.
3. **The tighten-only total order on the four-valued autopilot axis.** ``halt_policy``'s axis is
   three-valued (auto/halt) and its resolver ships as ``scripts/halt_gate.py``; the autopilot axis
   adds ``confirm`` and ``halt_independent``, and **no usable resolver for it ships in the store** —
   ``scripts/autopilot_runner.py`` fails at import because its ``lib/`` package was not included in
   the vendored archive. The shipped ``_doc`` says "只准加嚴" without defining whether
   ``halt_independent`` is stricter than ``halt``. This module therefore does **not** decide the
   order: it copies the table verbatim and records that the autopilot axis has no shipped resolver,
   leaving the ordering to be settled where it can be tested (task 6).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import decompose

#: Reuses task 1's generator identity: a dispatch element is only meaningful against the content
#: elements it names, so they version together.
GENERATOR = "ai_sdlc_runner.dispatch"
GENERATOR_VERSION = "1"

# Which shipped file supplies which family, and how to read a risk table out of it. Only container
# keys appear here — never a gate name, a decision-point name, a role name or a flag name. Those are
# read from the files, which is what "no hand-written node ids" means and what
# `test_no_node_id_is_written_in_the_source` checks.
_HALT_ASSET = "halt_policy.json"
_AUTOPILOT_ASSET = "autopilot_policy.json"
_ROLE_ASSET = "role_refs.json"

_HALT_NS = "halt"
_AUTOPILOT_NS = "autopilot"


class DispatchError(Exception):
    """Raised when the shipped policy is missing or not shaped as the contract requires."""


@dataclass(frozen=True)
class Checkpoint:
    """One decision point, with its policy verdicts copied verbatim from the shipped JSON."""

    element_id: str                       # "<namespace>:<key>"
    namespace: str
    key: str
    source_path: str                      # store-relative, e.g. "assets/halt_policy.json"
    source_sha256: str
    meaning: Optional[str]                # shipped gate_meaning, when the file ships one
    risk_table: Dict[str, str]            # {risk: verdict}, verbatim
    unconditional_halts: Dict[str, List[str]]   # {"<file>#<key>": [...]}, complete, unmerged
    preauthorizable: List[str]
    resolver: Dict[str, object]
    rel_path: str
    generator: str
    generator_version: str
    emitted_sha256: str

    def record(self) -> Dict[str, object]:
        return {
            "element_id": self.element_id,
            "kind": "checkpoint",
            "namespace": self.namespace,
            "key": self.key,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "meaning": self.meaning,
            "risk_table": dict(self.risk_table),
            "unconditional_halts": {k: list(v) for k, v in self.unconditional_halts.items()},
            "preauthorizable": list(self.preauthorizable),
            "resolver": self.resolver,
            "rel_path": self.rel_path,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "emitted_sha256": self.emitted_sha256,
        }


@dataclass(frozen=True)
class RoleLoadout:
    """One role's addressable anchor surface: base plus every situational set, unevaluated."""

    element_id: str                       # "role:<role>"
    role: str
    aliases: List[str]
    source_path: str
    source_sha256: str
    base_references: List[str]
    base_anchors: Dict[str, List[Dict[str, object]]]              # {lang: [anchor ref, ...]}
    situational: Dict[str, Dict[str, object]]                     # {flag: {references, anchors}}
    rel_path: str
    generator: str
    generator_version: str
    emitted_sha256: str

    def record(self) -> Dict[str, object]:
        return {
            "element_id": self.element_id,
            "kind": "role_loadout",
            "role": self.role,
            "aliases": list(self.aliases),
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "base_references": list(self.base_references),
            "anchor_count": {lang: len(v) for lang, v in sorted(self.base_anchors.items())},
            "situational_flags": sorted(self.situational),
            "rel_path": self.rel_path,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "emitted_sha256": self.emitted_sha256,
        }


def _asset(skill_path: str | Path, name: str) -> Path:
    p = Path(skill_path) / "assets" / name
    if not p.is_file():
        raise DispatchError(f"shipped policy asset not found: assets/{name}")
    return p


def _load(skill_path: str | Path, name: str):
    """Read a shipped asset as LF-normalised text, returning (parsed, sha256-of-normalised)."""
    text = decompose.normalize(_asset(skill_path, name).read_bytes())
    try:
        return json.loads(text), decompose.sha256(text)
    except ValueError as exc:
        raise DispatchError(f"assets/{name} is not valid JSON: {exc}") from exc


def _canonical(obj) -> str:
    """The exact bytes an element file gets — one place, so hashes and files cannot disagree."""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _halt_resolver(key: str) -> Dict[str, object]:
    """How a ``halt:*`` verdict is resolved: by calling the store's own script (FR-8, guideline §8).

    Named abstractly — script path, argument names, exit-code meanings. No interpreter, no tool
    name, nothing a specific harness owns (D5).
    """
    return {
        "kind": "shipped_script",
        "script": "scripts/halt_gate.py",
        "arguments": {"gate": key, "risk": "<risk>", "autonomy": "<CHG Autonomy, optional>"},
        "exit_codes": {"0": "AUTO", "10": "HALT"},
        "note": "The runner never re-derives this verdict; it branches on the script's exit code.",
    }


def _autopilot_resolver(key: str) -> Dict[str, object]:
    """How an ``autopilot:*`` verdict is resolved: from the embedded table, because nothing ships.

    Stated plainly rather than papered over — ``scripts/autopilot_runner.py`` is present but cannot
    be imported from the vendored store (its ``lib/`` package was not archived), so there is no
    shipped resolver for this axis. Fork point 3 in the module docstring.
    """
    return {
        "kind": "embedded_table",
        "table": "risk_table",
        "shipped_resolver": None,
        "note": (
            "No usable resolver for this axis ships in the store: scripts/autopilot_runner.py "
            "fails at import because its lib/ package is absent from the vendored archive. The "
            "table is copied verbatim and the tighten-only ordering of halt vs halt_independent "
            "is left to the engine, where it can be tested."
        ),
        "tighten_only": True,
    }


def checkpoints(skill_path: str | Path) -> List[Checkpoint]:
    """The 11 checkpoint elements: the verbatim, un-deduplicated union of the two policy namespaces.

    Both files are read for their *keys* — the ids are never written here. ``halt_policy`` is keyed
    gate → risk → verdict; ``autopilot_policy`` is keyed risk → decision point → verdict, so its
    table is transposed to the same ``{risk: verdict}`` shape without renaming anything.
    """
    halt, halt_sha = _load(skill_path, _HALT_ASSET)
    auto, auto_sha = _load(skill_path, _AUTOPILOT_ASSET)

    gates = halt.get("gates")
    defaults = auto.get("defaults")
    if not isinstance(gates, dict) or not gates:
        raise DispatchError(f"assets/{_HALT_ASSET} has no usable 'gates' mapping")
    if not isinstance(defaults, dict) or not defaults:
        raise DispatchError(f"assets/{_AUTOPILOT_ASSET} has no usable 'defaults' mapping")

    # Both lists travel with every checkpoint, complete and keyed by where they came from. Filtering
    # them to "the ones this node could hit" would need a generation-time semantic judgement — a
    # hand-written node→hazard table whose every omission silently disarms a gate (KN-4). They are a
    # dozen short strings; carrying all of them costs nothing and keeps a work order self-sufficient.
    unconditional = {
        f"{_HALT_ASSET}#always_halt_actions": list(halt.get("always_halt_actions", [])),
        f"{_AUTOPILOT_ASSET}#permanent_halts": list(auto.get("permanent_halts", [])),
    }
    preauthorizable = list(auto.get("preauthorizable", []))
    meanings = halt.get("gate_meaning", {}) if isinstance(halt.get("gate_meaning"), dict) else {}

    out: List[Checkpoint] = []

    for key in sorted(gates):
        table = gates[key]
        if not isinstance(table, dict):
            raise DispatchError(f"{_HALT_ASSET}: gate {key!r} has no risk table")
        out.append(_checkpoint(
            namespace=_HALT_NS, key=key, source=f"assets/{_HALT_ASSET}", source_sha=halt_sha,
            meaning=meanings.get(key), risk_table={r: str(v) for r, v in table.items()},
            unconditional=unconditional, preauthorizable=preauthorizable,
            resolver=_halt_resolver(key),
        ))

    # risk → {decision point: verdict}  becomes  decision point → {risk: verdict}
    points = sorted({p for row in defaults.values() if isinstance(row, dict) for p in row})
    for key in points:
        table = {risk: str(row[key]) for risk, row in sorted(defaults.items())
                 if isinstance(row, dict) and key in row}
        out.append(_checkpoint(
            namespace=_AUTOPILOT_NS, key=key, source=f"assets/{_AUTOPILOT_ASSET}",
            source_sha=auto_sha, meaning=None, risk_table=table,
            unconditional=unconditional, preauthorizable=preauthorizable,
            resolver=_autopilot_resolver(key),
        ))
    return out


def _checkpoint(namespace: str, key: str, source: str, source_sha: str, meaning: Optional[str],
                risk_table: Dict[str, str], unconditional: Dict[str, List[str]],
                preauthorizable: Sequence[str], resolver: Dict[str, object]) -> Checkpoint:
    element_id = f"{namespace}:{key}"
    rel_path = f"dispatch/checkpoints/{namespace}/{key}.json"
    payload = {
        "element_id": element_id,
        "kind": "checkpoint",
        "namespace": namespace,
        "key": key,
        "source_path": source,
        "source_sha256": source_sha,
        "meaning": meaning,
        "risk_table": risk_table,
        "unconditional_halts": unconditional,
        "preauthorizable": list(preauthorizable),
        "resolver": resolver,
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
    }
    return Checkpoint(
        element_id=element_id, namespace=namespace, key=key, source_path=source,
        source_sha256=source_sha, meaning=meaning, risk_table=risk_table,
        unconditional_halts=unconditional, preauthorizable=list(preauthorizable),
        resolver=resolver, rel_path=rel_path, generator=GENERATOR,
        generator_version=GENERATOR_VERSION, emitted_sha256=decompose.sha256(_canonical(payload)),
    )


def _anchor_index(skill_path: str | Path) -> Dict[str, Dict[str, List[Dict[str, object]]]]:
    """``{reference name: {lang: [anchor reference, ...]}}`` built from task 1's elements.

    An anchor reference names where the text lives — id, path, anchor, slug, level — and never the
    body (D5). The engine reads a body only for the anchors a node actually opens.
    """
    index: Dict[str, Dict[str, List[Dict[str, object]]]] = {}
    for e in decompose.decompose_store(skill_path):
        stem = e.source_path[len("references/"):-len(".md")]
        name = stem[: -len(".zh-tw")] if stem.endswith(".zh-tw") else stem
        index.setdefault(name, {}).setdefault(e.lang, []).append({
            "element_id": e.element_id,
            "source_path": e.source_path,
            "anchor": e.anchor,
            "anchor_slug": e.anchor_slug,
            "level": e.level,
        })
    return index


def _anchors_for(index, references: Sequence[str], where: str) -> Dict[str, List[Dict[str, object]]]:
    """Anchors for a list of reference names, grouped by language.

    A name with no element is a **hard error naming the reference** — never an empty list. A loadout
    that silently lost a reference is the failure this whole design exists to make impossible, and
    it is also exactly how task 6's untemplated-node rule expects to find out.
    """
    out: Dict[str, List[Dict[str, object]]] = {}
    for name in references:
        langs = index.get(name)
        if not langs:
            raise DispatchError(
                f"{_ROLE_ASSET} {where} names reference {name!r}, but no content element exists "
                f"for it — the store and the role table disagree"
            )
        for lang, anchors in langs.items():
            out.setdefault(lang, []).extend(anchors)
    return {lang: out[lang] for lang in sorted(out)}


def role_loadouts(skill_path: str | Path) -> List[RoleLoadout]:
    """One manifest per shipped role: ``common ∪ roles[r]``, plus every situational set expanded.

    No situational flag is evaluated here. All five sets are present in every manifest, verbatim by
    key, so that flipping a flag at dispatch selects among data that is already in the artifact
    rather than changing what the artifact contains — which is what keeps task 4's byte-comparison
    meaningful.
    """
    cfg, sha = _load(skill_path, _ROLE_ASSET)
    roles = cfg.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise DispatchError(f"assets/{_ROLE_ASSET} has no usable 'roles' mapping")
    common = list(cfg.get("common", []))
    situational_cfg = cfg.get("situational", {}) or {}
    alias_cfg = cfg.get("aliases", {}) or {}
    index = _anchor_index(skill_path)

    situational = {}
    for flag in sorted(situational_cfg):
        refs = list(situational_cfg[flag])
        situational[flag] = {
            "references": refs,
            "anchors": _anchors_for(index, refs, f"situational.{flag}"),
        }

    out: List[RoleLoadout] = []
    for role in sorted(roles):
        refs = common + list(roles[role])
        aliases = sorted(a for a, target in alias_cfg.items() if target == role)
        anchors = _anchors_for(index, refs, f"roles.{role}")
        payload = {
            "element_id": f"role:{role}",
            "kind": "role_loadout",
            "role": role,
            "aliases": aliases,
            "source_path": f"assets/{_ROLE_ASSET}",
            "source_sha256": sha,
            "base": {"references": refs, "anchors": anchors},
            "situational": situational,
            "generator": GENERATOR,
            "generator_version": GENERATOR_VERSION,
        }
        out.append(RoleLoadout(
            element_id=f"role:{role}", role=role, aliases=aliases,
            source_path=f"assets/{_ROLE_ASSET}", source_sha256=sha, base_references=refs,
            base_anchors=anchors, situational=situational,
            rel_path=f"dispatch/roles/{role}.json", generator=GENERATOR,
            generator_version=GENERATOR_VERSION,
            emitted_sha256=decompose.sha256(_canonical(payload)),
        ))
    return out


def coverage(skill_path: str | Path) -> Dict[str, Dict[str, List[str]]]:
    """What the shipped policy declares vs what was emitted — the done-when, made mechanical.

    Returns ``{"declared": {...}, "emitted": {...}}`` with matching key sets; a test asserts the two
    are equal per namespace, so "every gate and decision point covered" is checked against the files
    rather than against a number someone wrote down.
    """
    halt, _ = _load(skill_path, _HALT_ASSET)
    auto, _ = _load(skill_path, _AUTOPILOT_ASSET)
    cfg, _ = _load(skill_path, _ROLE_ASSET)
    declared = {
        _HALT_NS: sorted(halt.get("gates", {})),
        _AUTOPILOT_NS: sorted({p for row in auto.get("defaults", {}).values()
                               if isinstance(row, dict) for p in row}),
        "roles": sorted(cfg.get("roles", {})),
    }
    cps = checkpoints(skill_path)
    emitted = {
        _HALT_NS: sorted(c.key for c in cps if c.namespace == _HALT_NS),
        _AUTOPILOT_NS: sorted(c.key for c in cps if c.namespace == _AUTOPILOT_NS),
        "roles": sorted(r.role for r in role_loadouts(skill_path)),
    }
    return {"declared": declared, "emitted": emitted}


def build_manifest(skill_path: str | Path, cps: Sequence[Checkpoint],
                   roles: Sequence[RoleLoadout]) -> Dict[str, object]:
    from . import contract
    return {
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "skill_version": contract.read_skill_version(skill_path),
        "checkpoint_count": len(cps),
        "role_count": len(roles),
        "elements": [c.record() for c in cps] + [r.record() for r in roles],
    }


def emit(skill_path: str | Path, out_dir: str | Path) -> Dict[str, object]:
    """Write the dispatch elements under ``out_dir`` and return the manifest.

    Byte-identical across runs and platforms, on the same terms as task 1: sorted inputs, sorted JSON
    keys, LF-only, no timestamps, no absolute paths.
    """
    out = Path(out_dir)
    cps = checkpoints(skill_path)
    roles = role_loadouts(skill_path)

    for c in cps:
        # The emitted file is the record minus the two fields that describe it from outside; the
        # hash in `emitted_sha256` was taken over exactly this shape, and a test re-checks it.
        payload = c.record()
        payload.pop("rel_path")
        payload.pop("emitted_sha256")
        _write(out / c.rel_path, _canonical(payload))
    for r in roles:
        _write(out / r.rel_path, _canonical({
            "element_id": r.element_id,
            "kind": "role_loadout",
            "role": r.role,
            "aliases": r.aliases,
            "source_path": r.source_path,
            "source_sha256": r.source_sha256,
            "base": {"references": r.base_references, "anchors": r.base_anchors},
            "situational": r.situational,
            "generator": r.generator,
            "generator_version": r.generator_version,
        }))

    manifest = build_manifest(skill_path, cps, roles)
    _write(out / "dispatch" / "manifest.json", _canonical(manifest))
    return manifest


def _write(path: Path, text: str) -> None:
    """UTF-8, LF, no BOM — never ``open(..., "w")``, whose newline translation would put CRLF in the
    artifacts on Windows and split the CI matrix (task 1, decision B)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
