"""dispatch.py — derive dispatch elements from the store's shipped policy.

CHG-20260822-04 task 2 (D1, "dispatch elements"). Task 1 turned the references into 448 anchored
content elements; this module derives the elements that say **which** anchors a node gets and
**what the policy says at each checkpoint**. Both come only from the shipped policy JSONs — nothing
here is hand-authored, and a test proves it by asserting that none of the node ids appear as a
literal anywhere in this file.

Two families, deliberately **not** a cartesian product:

* **Checkpoint elements.** The verbatim, un-deduplicated union of two namespaces: ``halt:*`` (the
  gates in ``halt_policy.json``) and ``autopilot:*`` (the per-risk decision points in
  ``autopilot_policy.json``). Each carries its own risk table copied verbatim from the shipped JSON,
  whichever unconditional-halt lists that version ships (complete, namespaced by source file), and a
  description of how the verdict is resolved. For ``skills/v1.64.0``: 5 + 6 = **11**.
* **Role loadout manifests.** One per role in ``role_refs.json``, naming the content element **ids**
  for ``common ∪ roles[r]``, plus the ids of the situational sets — **not evaluated**. v1.64.0: 13.
* **Situational sets.** One per ``situational`` flag, emitted once for the whole store version.
  v1.64.0: 5.

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

## Why loadouts name ids

A loadout carries content element **ids** and nothing else, and each situational set is emitted once
rather than inlined into all 13 roles. This corrects a packaging defect in task 2's first shape,
found by measuring the tree task 3 would commit — recorded rather than quietly changed:

| | first shape | now |
|---|---|---|
| one role manifest | 54,670 bytes | **6,644** |
| all 13 role manifests | 819,984 bytes | **110,920** |
| whole element tree | 1,536,506 bytes | **838,922** |

819,984 bytes is **2.4× the 343,366-byte reference corpus** the decomposition exists to stop nodes
from paying for, and a single role manifest was larger than the biggest reference in it. Two causes,
both measured: the five situational blocks were byte-identical across all 13 roles (265 KB of pure
duplication), and every anchor repeated ``source_path``, ``anchor``, ``anchor_slug`` and ``level``
that ``element_id`` already determines and that ``manifest.json`` already holds authoritatively.

The self-sufficiency constraint (constraint 5, "every node retryable without a session") applies to
the **work order**, not to intermediate manifests: the renderer holds the whole element tree and
joins ids against ``manifest.json`` at zero cost, and a loadout is never dispatched to a node. Naming
ids also keeps one fact in one place — a renamed heading changes one record instead of fanning out
across 13 files × 5 fields, which is what keeps task 4's regeneration diff readable and free of the
false positives a denormalised copy would produce.

## Older store versions: what derives is read off the archive

The vendored store holds five versions and they do not ship the same assets. Measured:

| version | content elements | ``halt:*`` | ``autopilot:*`` | role loadouts | situational |
|---|---|---|---|---|---|
| v1.0.0 | 220 | 5 | — | — | — |
| v1.1.0 | 238 | 5 | — | 7 | 4 |
| v1.12.1 | 322 | 5 | — | 13 | 5 |
| v1.16.0 | 330 | 5 | — | 13 | 5 |
| v1.64.0 | 448 | 5 | 6 | 13 | 5 |

Every version therefore gets elements, which is what task 3's done-when requires — and what KN-2
requires in substance, since 1.0 / 1.1 / 1.12 / 1.16 per-project locks still resolve to their own
store version. A family derives when the archive ships the policy it reads and not otherwise.

The load-bearing part is **where that expectation comes from**: ``assets/`` ships *inside* the
archive, so it is the inventory. No hand-maintained per-version table is involved — and must never
be introduced, because a table is a second source of truth that goes stale silently, which is the
KN-4 shape the panel rejected in both of its forms (a per-version capability baseline, and a frozen
list of "legacy" versions). The gate reads both directions off the archive: a family whose policy is
present must exist and byte-match; a family whose policy is absent must not exist.

What this deliberately does **not** catch: an archive that silently lost a policy file, the way
CHG-20260822-03's archive lost ``scripts/lib/``. That is store-vs-upstream drift, which D4 assigns
to ``runner check``, not to the regeneration gate — "elements ≡ the store they came from" is the
property here, and conflating the two would be the false-green this repo keeps catching.

## Runner-authored fork points (D3 requires these named)

1. **Namespacing and non-deduplication** of the two checkpoint families (``halt:`` / ``autopilot:``).
   A different reader could pick one namespace as canonical and map the other onto it — at the cost
   of the hand-written mapping described above.
2. **The whole-file anchor set** rather than a narrowed one, justified by the zero-true-positive
   measurement above. If the skill ever ships a machine-readable section→checkpoint map, this
   becomes narrowable without changing the element shape.
3. **Which policy file feeds which family** — the mapping from ``halt_policy.json`` to ``halt:*``,
   ``autopilot_policy.json`` to ``autopilot:*`` and ``role_refs.json`` to loadouts. It is three
   lines and it is not derivable from the files themselves; a different reader could key families
   off something else entirely.
4. **The tighten-only total order on the four-valued autopilot axis.** ``halt_policy``'s axis is
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

    def payload(self) -> Dict[str, object]:
        """Exactly what gets written to ``rel_path`` — ``emitted_sha256`` is taken over this."""
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
            "generator": self.generator,
            "generator_version": self.generator_version,
        }

    def record(self) -> Dict[str, object]:
        record = self.payload()
        record["rel_path"] = self.rel_path
        record["emitted_sha256"] = self.emitted_sha256
        return record


@dataclass(frozen=True)
class SituationalSet:
    """One ``situational`` flag's reference set, emitted once and referred to by every role.

    Its own element rather than a block inside each role manifest — see "Why loadouts name ids"
    in the module docstring for the measurement that forced this.
    """

    element_id: str                       # "situational:<flag>"
    flag: str
    source_path: str
    source_sha256: str
    references: List[str]
    element_ids: Dict[str, List[str]]     # {lang: [content element id, ...]}
    rel_path: str
    generator: str
    generator_version: str
    emitted_sha256: str

    def payload(self) -> Dict[str, object]:
        return {
            "element_id": self.element_id,
            "kind": "situational_set",
            "flag": self.flag,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "references": list(self.references),
            "element_ids": {k: list(v) for k, v in sorted(self.element_ids.items())},
            "generator": self.generator,
            "generator_version": self.generator_version,
        }

    def record(self) -> Dict[str, object]:
        rec = self.payload()
        rec["element_count"] = {k: len(v) for k, v in sorted(self.element_ids.items())}
        rec.pop("element_ids")
        rec["rel_path"] = self.rel_path
        rec["emitted_sha256"] = self.emitted_sha256
        return rec


@dataclass(frozen=True)
class RoleLoadout:
    """One role's addressable surface: the content element ids it may open, plus the flag keys."""

    element_id: str                       # "role:<role>"
    role: str
    aliases: List[str]
    source_path: str
    source_sha256: str
    base_references: List[str]
    base_element_ids: Dict[str, List[str]]        # {lang: [content element id, ...]}
    situational_refs: List[str]                   # ["situational:<flag>", ...]
    rel_path: str
    generator: str
    generator_version: str
    emitted_sha256: str

    def payload(self) -> Dict[str, object]:
        return {
            "element_id": self.element_id,
            "kind": "role_loadout",
            "role": self.role,
            "aliases": list(self.aliases),
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "base": {
                "references": list(self.base_references),
                "element_ids": {k: list(v) for k, v in sorted(self.base_element_ids.items())},
            },
            "situational": list(self.situational_refs),
            "generator": self.generator,
            "generator_version": self.generator_version,
        }

    def record(self) -> Dict[str, object]:
        return {
            "element_id": self.element_id,
            "kind": "role_loadout",
            "role": self.role,
            "aliases": list(self.aliases),
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "base_references": list(self.base_references),
            "element_count": {k: len(v) for k, v in sorted(self.base_element_ids.items())},
            "situational": list(self.situational_refs),
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


def _maybe_load(skill_path: str | Path, name: str):
    """``_load`` if the asset is in this version's archive, else ``None``.

    The distinction that makes per-version derivation safe: a **missing file** means the version
    never shipped that policy, so the family it feeds does not exist for that version; a **present
    but malformed** file is still a hard error. Absence is read off the archive, never off a table
    someone maintains by hand — see "Older store versions" in the module docstring.
    """
    if not (Path(skill_path) / "assets" / name).is_file():
        return None
    return _load(skill_path, name)


def supported_families(skill_path: str | Path) -> Dict[str, bool]:
    """Which dispatch families this version's archive can support, derived from the archive itself.

    ``assets/`` **is** the inventory — it ships inside the archive — so no second source of truth is
    needed to tell "this version never had that policy" from "this regeneration lost something".
    The gate reads both directions off this: a family whose policy is present **must** exist and
    byte-match; a family whose policy is absent **must not** exist.
    """
    assets = Path(skill_path) / "assets"
    return {
        _HALT_NS: (assets / _HALT_ASSET).is_file(),
        _AUTOPILOT_NS: (assets / _AUTOPILOT_ASSET).is_file(),
        "roles": (assets / _ROLE_ASSET).is_file(),
    }


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
    """The checkpoint elements: the verbatim, un-deduplicated union of the two policy namespaces.

    Both files are read for their *keys* — the ids are never written here. ``halt_policy`` is keyed
    gate → risk → verdict; ``autopilot_policy`` is keyed risk → decision point → verdict, so its
    table is transposed to the same ``{risk: verdict}`` shape without renaming anything.

    **The two namespaces derive independently.** Older store versions ship ``halt_policy.json``
    without ``autopilot_policy.json``, and coupling them — as this function first did — made the
    halt family refuse to derive for four of the five vendored versions over the absence of a file
    it never needed.
    """
    halt_loaded = _maybe_load(skill_path, _HALT_ASSET)
    auto_loaded = _maybe_load(skill_path, _AUTOPILOT_ASSET)
    if halt_loaded is None and auto_loaded is None:
        raise DispatchError(
            f"store ships neither assets/{_HALT_ASSET} nor assets/{_AUTOPILOT_ASSET} — "
            f"no checkpoint family can be derived")

    halt, halt_sha = halt_loaded if halt_loaded else ({}, "")
    auto, auto_sha = auto_loaded if auto_loaded else ({}, "")
    gates = halt.get("gates") if halt_loaded else None
    defaults = auto.get("defaults") if auto_loaded else None
    if halt_loaded and (not isinstance(gates, dict) or not gates):
        raise DispatchError(f"assets/{_HALT_ASSET} has no usable 'gates' mapping")
    if auto_loaded and (not isinstance(defaults, dict) or not defaults):
        raise DispatchError(f"assets/{_AUTOPILOT_ASSET} has no usable 'defaults' mapping")

    # Whichever lists this version ships travel with every checkpoint, complete and keyed by where
    # they came from. Filtering them to "the ones this node could hit" would need a generation-time
    # semantic judgement — a hand-written node→hazard table whose every omission silently disarms a
    # gate (KN-4). They are a dozen short strings; carrying all of them costs nothing and keeps a
    # work order self-sufficient. A version that ships only one list carries only that one, which is
    # the truth about that version rather than a padded-out imitation of the current one.
    unconditional = {}
    if halt_loaded:
        unconditional[f"{_HALT_ASSET}#always_halt_actions"] = list(halt.get("always_halt_actions", []))
    if auto_loaded:
        unconditional[f"{_AUTOPILOT_ASSET}#permanent_halts"] = list(auto.get("permanent_halts", []))
    preauthorizable = list(auto.get("preauthorizable", [])) if auto_loaded else []
    meanings = halt.get("gate_meaning", {}) if isinstance(halt.get("gate_meaning"), dict) else {}

    out: List[Checkpoint] = []

    for key in sorted(gates or {}):
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
    points = sorted({p for row in (defaults or {}).values() if isinstance(row, dict) for p in row})
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
    return _finish(Checkpoint(
        element_id=f"{namespace}:{key}", namespace=namespace, key=key, source_path=source,
        source_sha256=source_sha, meaning=meaning, risk_table=risk_table,
        unconditional_halts=unconditional, preauthorizable=list(preauthorizable),
        resolver=resolver, rel_path=f"dispatch/checkpoints/{namespace}/{key}.json",
        generator=GENERATOR, generator_version=GENERATOR_VERSION, emitted_sha256="",
    ))


def _anchor_index(skill_path: str | Path) -> Dict[str, Dict[str, List[str]]]:
    """``{reference name: {lang: [content element id, ...]}}`` built from task 1's elements.

    Ids only. ``element_id`` is ``references/<stem>#<slug>``, so the source path, the slug and the
    language all follow from it, and ``manifest.json`` already carries the full record for every
    element — repeating those fields here would be denormalising the one authoritative index.
    """
    index: Dict[str, Dict[str, List[str]]] = {}
    for e in decompose.decompose_store(skill_path):
        stem = e.source_path[len("references/"):-len(".md")]
        name = stem[: -len(".zh-tw")] if stem.endswith(".zh-tw") else stem
        index.setdefault(name, {}).setdefault(e.lang, []).append(e.element_id)
    return index


def _element_ids_for(index, references: Sequence[str], where: str) -> Dict[str, List[str]]:
    """Content element ids for a list of reference names, grouped by language.

    A name with no element is a **hard error naming the reference** — never an empty list. A loadout
    that silently lost a reference is the failure this whole design exists to make impossible, and
    it is also exactly how task 6's untemplated-node rule expects to find out.
    """
    out: Dict[str, List[str]] = {}
    for name in references:
        langs = index.get(name)
        if not langs:
            raise DispatchError(
                f"{_ROLE_ASSET} {where} names reference {name!r}, but no content element exists "
                f"for it — the store and the role table disagree"
            )
        for lang, ids in langs.items():
            out.setdefault(lang, []).extend(ids)
    return {lang: out[lang] for lang in sorted(out)}


def situational_sets(skill_path: str | Path) -> List[SituationalSet]:
    """One element per ``situational`` flag, emitted once for the whole store version.

    No flag is evaluated here: all of them exist as elements, and dispatch selects among data that
    is already in the artifact rather than changing what the artifact contains — which is what keeps
    task 4's byte-comparison meaningful.
    """
    loaded = _maybe_load(skill_path, _ROLE_ASSET)
    if loaded is None:
        return []                       # this version never shipped a role table (e.g. v1.0.0)
    cfg, sha = loaded
    index = _anchor_index(skill_path)
    out: List[SituationalSet] = []
    for flag in sorted(cfg.get("situational", {}) or {}):
        refs = list(cfg["situational"][flag])
        ids = _element_ids_for(index, refs, f"situational.{flag}")
        s = SituationalSet(
            element_id=f"situational:{flag}", flag=flag, source_path=f"assets/{_ROLE_ASSET}",
            source_sha256=sha, references=refs, element_ids=ids,
            rel_path=f"dispatch/situational/{flag}.json", generator=GENERATOR,
            generator_version=GENERATOR_VERSION, emitted_sha256="",
        )
        out.append(_finish(s))
    return out


def role_loadouts(skill_path: str | Path) -> List[RoleLoadout]:
    """One manifest per shipped role: the content element ids for ``common ∪ roles[r]``.

    Situational sets are **named, not inlined** — the flag's own element carries the ids. Inlining
    them cost 265 KB of byte-identical duplication across the 13 roles; see the module docstring.
    """
    loaded = _maybe_load(skill_path, _ROLE_ASSET)
    if loaded is None:
        return []                       # this version never shipped a role table (e.g. v1.0.0)
    cfg, sha = loaded
    roles = cfg.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise DispatchError(f"assets/{_ROLE_ASSET} has no usable 'roles' mapping")
    common = list(cfg.get("common", []))
    alias_cfg = cfg.get("aliases", {}) or {}
    index = _anchor_index(skill_path)
    flags = [f"situational:{flag}" for flag in sorted(cfg.get("situational", {}) or {})]

    out: List[RoleLoadout] = []
    for role in sorted(roles):
        refs = common + list(roles[role])
        r = RoleLoadout(
            element_id=f"role:{role}", role=role,
            aliases=sorted(a for a, target in alias_cfg.items() if target == role),
            source_path=f"assets/{_ROLE_ASSET}", source_sha256=sha, base_references=refs,
            base_element_ids=_element_ids_for(index, refs, f"roles.{role}"),
            situational_refs=flags, rel_path=f"dispatch/roles/{role}.json",
            generator=GENERATOR, generator_version=GENERATOR_VERSION, emitted_sha256="",
        )
        out.append(_finish(r))
    return out


def _finish(element):
    """Re-stamp an element with the hash of the bytes it will actually be written as.

    The hash has to be taken over ``payload()`` — the same call ``emit`` writes — so the two can
    never drift apart the way a separately-assembled dict would.
    """
    from dataclasses import replace
    return replace(element, emitted_sha256=decompose.sha256(_canonical(element.payload())))


def check_dangling(skill_path: str | Path) -> List[str]:
    """Every content element id named by a dispatch element must exist. Returns the offenders.

    A generation-time check rather than a dispatch-time surprise: a loadout pointing at an id that
    no longer exists is precisely the silent-coverage-loss this design is built to prevent, and it
    is cheap to prove absent while both sides are in hand.
    """
    known = {e.element_id for e in decompose.decompose_store(skill_path)}
    named: List[str] = []
    for r in role_loadouts(skill_path):
        for ids in r.base_element_ids.values():
            named.extend(ids)
    for s in situational_sets(skill_path):
        for ids in s.element_ids.values():
            named.extend(ids)
    return sorted({i for i in named if i not in known})


def coverage(skill_path: str | Path) -> Dict[str, Dict[str, List[str]]]:
    """What the shipped policy declares vs what was emitted — the done-when, made mechanical.

    Returns ``{"declared": {...}, "emitted": {...}}`` with matching key sets; a test asserts the two
    are equal per namespace, so "every gate and decision point covered" is checked against the files
    rather than against a number someone wrote down.
    """
    halt = (_maybe_load(skill_path, _HALT_ASSET) or ({}, ""))[0]
    auto = (_maybe_load(skill_path, _AUTOPILOT_ASSET) or ({}, ""))[0]
    cfg = (_maybe_load(skill_path, _ROLE_ASSET) or ({}, ""))[0]
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
                   roles: Sequence[RoleLoadout],
                   sits: Sequence[SituationalSet]) -> Dict[str, object]:
    from . import contract
    return {
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "skill_version": contract.read_skill_version(skill_path),
        "checkpoint_count": len(cps),
        "role_count": len(roles),
        "situational_count": len(sits),
        "elements": [c.record() for c in cps] + [r.record() for r in roles]
                    + [s.record() for s in sits],
    }


def emit(skill_path: str | Path, out_dir: str | Path) -> Dict[str, object]:
    """Write the dispatch elements under ``out_dir`` and return the manifest.

    Byte-identical across runs and platforms, on the same terms as task 1: sorted inputs, sorted JSON
    keys, LF-only, no timestamps, no absolute paths. Every element file is ``payload()`` verbatim,
    which is also what its ``emitted_sha256`` was taken over.
    """
    out = Path(out_dir)
    cps = checkpoints(skill_path)
    roles = role_loadouts(skill_path)
    sits = situational_sets(skill_path)

    dangling = check_dangling(skill_path)
    if dangling:
        raise DispatchError(
            "dispatch elements name content elements that do not exist: " + ", ".join(dangling))

    for element in list(cps) + list(roles) + list(sits):
        _write(out / element.rel_path, _canonical(element.payload()))

    manifest = build_manifest(skill_path, cps, roles, sits)
    _write(out / "dispatch" / "manifest.json", _canonical(manifest))
    return manifest


def _write(path: Path, text: str) -> None:
    """UTF-8, LF, no BOM — never ``open(..., "w")``, whose newline translation would put CRLF in the
    artifacts on Windows and split the CI matrix (task 1, decision B)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def elements_dir(repo_root: str | Path, version: str) -> Path:
    """Where a store version's derived elements live: ``elements/v<version>/``.

    A sibling of ``skills/v<version>/`` rather than a child of it — the store stays a **verbatim**
    archive, and writing derived files inside it would break the one property the whole vendoring
    rests on (KN-1).
    """
    v = version if version.startswith("v") else f"v{version}"
    return Path(repo_root) / "elements" / v


#: The gate's three states, worst last. Both failures are hard, and they are distinguishable
#: because they call for different actions: drift means regenerate (or stop hand-editing elements),
#: source-missing means the store the elements were derived from is no longer there to derive from.
MATCH = "match"
DRIFT = "drift"
SOURCE_MISSING = "source_missing"
_SEVERITY = {MATCH: 0, DRIFT: 1, SOURCE_MISSING: 2}

#: Exit codes, following the shipped `halt_gate.py` convention the runner already branches on:
#: 0 continues, anything else stops, and the specific code says which stop it is.
EXIT_MATCH = 0
EXIT_DRIFT = 10
EXIT_SOURCE_MISSING = 11


def _committed_sources(tree: Path) -> List[str]:
    """Every store-relative path the committed elements claim they were derived from.

    Read out of the committed manifests' own provenance rather than inferred from the directory
    layout: that is what makes "the source of this element is gone" a mechanical finding instead of
    a judgement about which files a version ought to have had.
    """
    sources: List[str] = []
    for name in ("manifest.json", "dispatch/manifest.json"):
        path = tree / name
        if not path.is_file():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise DispatchError(f"{path} is not valid JSON: {exc}") from exc
        for record in manifest.get("elements", []):
            source = record.get("source_path")
            if source:
                sources.append(source)
    return sorted(set(sources))


def verify_elements(repo_root: str | Path) -> Dict[str, object]:
    """Re-derive every store version and compare against the committed tree. Three states.

    | | |
    |---|---|
    | `match` | committed bytes are what the generators produce right now |
    | `drift` | regeneration succeeds and disagrees — the store moved without the elements being regenerated, or an element was hand-edited (guideline §2/§8) |
    | `source_missing` | something the committed elements name as their source is gone, so the comparison cannot even be made |

    Versions are enumerated from **both** `skills/` and `elements/`, so a tree whose store version
    was deleted is found rather than skipped — skipping it is precisely how a missing source would
    otherwise read as "nothing to check".
    """
    import tempfile
    from . import skillstore

    root = Path(repo_root)
    store_versions = set(skillstore.store_versions(root / "skills"))
    tree_versions = {
        d.name[1:] for d in (root / "elements").glob("v*") if d.is_dir()
    } if (root / "elements").is_dir() else set()

    results: List[Dict[str, object]] = []
    for version in sorted(store_versions | tree_versions):
        results.append(_verify_one(root, version, store_versions, tree_versions, tempfile))

    worst = max((r["state"] for r in results), key=lambda s: _SEVERITY[s], default=MATCH)
    return {"state": worst, "versions": results}


def _verify_one(root: Path, version: str, store_versions, tree_versions, tempfile) -> Dict[str, object]:
    skill = root / "skills" / f"v{version}"
    tree = elements_dir(root, version)

    if version not in store_versions:
        return {"version": version, "state": SOURCE_MISSING,
                "detail": f"elements/v{version}/ exists but skills/v{version}/ does not"}
    if version not in tree_versions:
        return {"version": version, "state": DRIFT,
                "detail": f"skills/v{version}/ has no elements/v{version}/ — regenerate"}

    gone = [s for s in _committed_sources(tree) if not (skill / s).exists()]
    if gone:
        return {"version": version, "state": SOURCE_MISSING,
                "detail": f"committed elements name sources that no longer exist in the store: "
                          + ", ".join(gone[:5]) + (" …" if len(gone) > 5 else "")}

    with tempfile.TemporaryDirectory() as tmp:
        try:
            emit_all(skill, tmp)
        except DispatchError as exc:
            return {"version": version, "state": SOURCE_MISSING,
                    "detail": f"regeneration could not run: {exc}"}
        fresh = _bytes_under(Path(tmp))

    committed = _bytes_under(tree)
    missing = sorted(set(fresh) - set(committed))
    extra = sorted(set(committed) - set(fresh))
    differing = sorted(n for n in fresh if n in committed and fresh[n] != committed[n])
    if missing or extra or differing:
        parts = []
        if differing:
            parts.append(f"{len(differing)} file(s) differ (e.g. {differing[0]})")
        if missing:
            parts.append(f"{len(missing)} regenerated file(s) not committed (e.g. {missing[0]})")
        if extra:
            parts.append(f"{len(extra)} committed file(s) no longer regenerate (e.g. {extra[0]})")
        return {"version": version, "state": DRIFT, "detail": "; ".join(parts)}

    return {"version": version, "state": MATCH,
            "detail": f"{len(committed)} file(s) byte-identical"}


def _bytes_under(root: Path) -> Dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def emit_all(skill_path: str | Path, out_dir: str | Path) -> Dict[str, object]:
    """Emit a store version's **complete** decomposition: content elements and dispatch elements.

    The single entry point vendoring calls (D2): there is to be no state in which a store version
    exists without its derived elements, so the two emissions are one operation rather than two
    steps a change could land only half of.
    """
    return {
        "content": decompose.emit(skill_path, out_dir),
        "dispatch": emit(skill_path, out_dir),
    }
