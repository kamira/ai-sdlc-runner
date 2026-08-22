"""workorder.py — render one node's work order: self-contained, and portable across models.

CHG-20260822-04 task 5 (D5). A work order is what a node actually receives. Its done-when has two
clauses and they guard the same risk from opposite sides: it must contain **no harness-specific
field** (check the contents) and must **render without any sibling element** (check self-sufficiency).

Portability is the whole point — reason ③ of the requirement is running different nodes on different
models — and it is the easiest thing to under-serve, because a work order that only runs on the
harness that produced it looks finished. So the exclusions are enforced mechanically:

* **The schema is closed.** ``WORK_ORDER_FIELDS`` is the complete D5 whitelist and rendering asserts
  the produced key set is exactly it. Absence is proven by **enumerating what is present**, never by
  searching for forbidden names — a substring search for a banned term scores 21 false positives on
  this repo's own corpus, and did so on the guard test written for task 2.
* **A sentinel proves the tool names never escape.** ``agents.RoleSpec`` carries a ``tools`` list
  that this runner *synthesises* — ``Read``, ``Bash``, ``Edit``, ``Write``, ``Agent`` are Claude Code
  names hard-coded here, not shipped data — plus a ``writes_docs`` flag guessed from prose in the
  Notes column. D5 excludes concrete tool names and lists only three capability flags, so this module
  reads **only** ``can_spawn`` / ``writable`` / ``can_execute`` and never derives them back from tool
  names. The test feeds a unique sentinel through ``tools`` and asserts it appears nowhere in the
  serialised order.

## Self-sufficiency: what "without any sibling element" binds

It binds the **artifact**, not the renderer. The renderer runs where the whole element tree lives and
dereferences content element ids into source paths and anchors; the node that receives the order needs
only the order plus the store. This is the same boundary the panel settled when loadouts became
ids-only in task 3 — constraint 5's self-sufficiency lands on the work order, not on intermediate
manifests. The operational form of the rule: **a content element id must never appear in a work order
without the path and anchor it resolves to.** Bodies are never inlined either way.

## Capability flags: nine of thirteen roles cannot be rendered, and that is deliberate

``references/agent-hierarchy.md``'s "Role startup spec" table ships **four** rows — A1, I1, I1.x, V1.
``role_refs.json`` declares **thirteen** roles. Via ``aliases`` the table covers analyst,
lead-implementer, sub-implementer and verifier; ``orchestrator``, ``integrator``, ``reviewer`` and the
six ``seat-*`` roles have **no shipped capability data at all**. Nothing else in the store supplies it:
``review_seats.json`` names different seats entirely (``conformance``…), and the one prose sentence in
``role_refs.json``'s ``_doc`` about seats being read-only is prose, not data.

Rendering a work order for an uncovered role is therefore a **hard error naming the role**, not a
default. Defaulting the three flags to ``false`` would be the runner inventing an authorization
policy and dressing it as a safe default: ``orchestrator`` plainly must be able to spawn, so an
all-false order would look governed while being wrong, and a silently over-tightened node fails work
it was supposed to do. Both directions of the guess are harmful, which is exactly when guessing is
not available. This is the same shape as D7's "untemplated node = hard error naming the node id".

**The consequence is known and is not to be worked around**: until the skill ships machine-readable
capability data for those nine roles, the engine cannot dispatch them — including the review-panel
seats. Recorded in CHG-20260822-04 alongside the missing ``scripts/lib/`` finding rather than patched
over with defaults at dispatch time, which would smuggle the rejected default-deny option back in.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from . import agents, decompose

#: The complete D5 portable-required set. The rendered order has exactly these keys — no more (a
#: harness-specific field would have to be one of them) and no fewer (a missing field is a partial
#: order, which the no-silent-fallback constraint forbids).
WORK_ORDER_FIELDS = (
    "node_id",
    "element_id",
    "store_version",
    "role",
    "scope",
    "objective",
    "done_criteria",
    "sources",
    "input_artifacts",
    "expected_outputs",
    "acceptance_predicate",
    "policy_verdict",
    "capabilities",
    "idempotence_probes",
    "workdir",
)

#: Supplied per CHG task by the caller (task 6's engine). None of it can be derived from a store
#: version — it is the same class of runtime input as risk, and for the same reason: the elements
#: exist before any CHG does.
NODE_SPEC_FIELDS = (
    "scope",
    "objective",
    "done_criteria",
    "input_artifacts",
    "expected_outputs",
    "acceptance_predicate",
    "idempotence_probes",
    "workdir",
)

#: The only three capability facts D5 admits. `writes_docs` and `tools` are excluded — see the
#: module docstring for why both are runner inventions rather than shipped data.
CAPABILITY_FIELDS = ("can_spawn", "writable", "can_execute")

#: Shape required of the resolved verdict the caller passes in.
VERDICT_FIELDS = ("checkpoint", "risk", "verdict", "source")


class WorkOrderError(Exception):
    """Raised when an order cannot be rendered truthfully — never softened into a partial order."""


def capabilities_for(skill_path: str | Path, role: str) -> Dict[str, bool]:
    """The three shipped capability flags for a role, or a hard error naming the role.

    Resolution goes role → ``role_refs.json``'s ``aliases`` → the startup-spec table's row code. A
    role with no alias, or an alias with no row, has no shipped capability data and cannot be
    rendered. The error lists the roles that *are* covered, so the caller learns the shape of the gap
    rather than just that it hit one.
    """
    cfg_path = Path(skill_path) / "assets" / "role_refs.json"
    if not cfg_path.is_file():
        raise WorkOrderError(f"{cfg_path} not found — cannot resolve capabilities for {role!r}")
    cfg = json.loads(decompose.normalize(cfg_path.read_bytes()))
    if role not in cfg.get("roles", {}):
        raise WorkOrderError(f"role {role!r} is not declared in role_refs.json")

    specs = agents.parse_role_table(skill_path)
    covered = sorted(
        target for alias, target in (cfg.get("aliases") or {}).items() if alias in specs
    )
    alias = next((a for a, target in (cfg.get("aliases") or {}).items() if target == role), None)
    spec = specs.get(alias) if alias else None
    if spec is None:
        raise WorkOrderError(
            f"role {role!r} has no shipped capability row: the 'Role startup spec' table in "
            f"references/agent-hierarchy.md covers {covered}. Refusing to invent flags for it — "
            f"a default in either direction would be this runner authoring an authorization policy "
            f"(see CHG-20260822-04 task 5)."
        )
    # Only the three D5 flags are read. `spec.tools` and `spec.writes_docs` are deliberately not
    # touched, and the flags are never derived back from tool names.
    return {name: bool(getattr(spec, name)) for name in CAPABILITY_FIELDS}


def _manifest(tree: Path, name: str) -> Dict[str, object]:
    path = tree / name
    if not path.is_file():
        raise WorkOrderError(f"element tree is missing {name}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _source_index(tree: Path) -> Dict[str, Dict[str, object]]:
    """``{content element id: {source_path, anchor, anchor_slug, level}}`` from the tree's manifest.

    This is the dereference that makes the rendered order self-sufficient: the node gets paths and
    anchors, so it never has to hold a sibling element to find its own material.
    """
    index = {}
    for record in _manifest(tree, "manifest.json").get("elements", []):
        index[record["element_id"]] = {
            "element_id": record["element_id"],
            "source_path": record["source_path"],
            "anchor": record["anchor"],
            "anchor_slug": record["anchor_slug"],
        }
    return index


def _loadout(tree: Path, role: str) -> Dict[str, object]:
    path = tree / "dispatch" / "roles" / f"{role}.json"
    if not path.is_file():
        raise WorkOrderError(
            f"no loadout element for role {role!r} in {tree} — this store version does not ship a "
            f"role table for it (never a silent fallback; see D7)")
    return json.loads(path.read_text(encoding="utf-8"))


def _situational(tree: Path, flag: str) -> Dict[str, object]:
    path = tree / "dispatch" / "situational" / f"{flag}.json"
    if not path.is_file():
        raise WorkOrderError(f"no situational element for flag {flag!r} in {tree}")
    return json.loads(path.read_text(encoding="utf-8"))


def _element_id(tree: Path, element_id: str, index: Mapping[str, object]) -> str:
    """Resolve the element this node is named by — a checkpoint, or any other real element.

    Most nodes name a checkpoint (`<namespace>:<key>`) and the id comes from that element. A node the
    shipped policy grades no gate for — `whole-branch review` is a code gate, not a risk gate — names
    the element it was written from instead. Either way the id must resolve to something that exists:
    an order carrying an id nothing backs is the fabrication this contract exists to prevent.
    """
    if ":" in element_id and "#" not in element_id:
        namespace, key = element_id.split(":", 1)
        path = tree / "dispatch" / "checkpoints" / namespace / f"{key}.json"
        if not path.is_file():
            raise WorkOrderError(
                f"no checkpoint element {element_id!r} in {tree} — this store version does not ship "
                f"the policy it derives from")
        return str(json.loads(path.read_text(encoding="utf-8"))["element_id"])
    if element_id not in index:
        raise WorkOrderError(
            f"element {element_id!r} is not in this tree's manifest — a work order may not name an "
            f"id that nothing backs")
    return element_id


def _check_node_spec(node_spec: Mapping[str, object]) -> None:
    missing = [f for f in NODE_SPEC_FIELDS if f not in node_spec]
    extra = [k for k in node_spec if k not in NODE_SPEC_FIELDS]
    if missing:
        raise WorkOrderError(f"node spec is missing required field(s): {missing}")
    if extra:
        raise WorkOrderError(
            f"node spec carries field(s) outside the contract: {extra}. The schema is closed so "
            f"that a harness-specific field cannot ride in through the caller.")


def _check_verdict(verdict: Mapping[str, object]) -> None:
    missing = [f for f in VERDICT_FIELDS if f not in verdict]
    extra = [k for k in verdict if k not in VERDICT_FIELDS]
    if missing:
        raise WorkOrderError(f"policy verdict is missing required field(s): {missing}")
    if extra:
        raise WorkOrderError(f"policy verdict carries unexpected field(s): {extra}")


def render(
    skill_path: str | Path,
    tree: str | Path,
    role: str,
    checkpoint_id: str,
    node_spec: Mapping[str, object],
    policy_verdict: Mapping[str, object],
    situational_flags: Sequence[str] = (),
    languages: Sequence[str] = (),
) -> Dict[str, object]:
    """Render one node's work order.

    ``languages`` and ``situational_flags`` select among data the elements already hold complete;
    omitting them takes everything. ``policy_verdict`` arrives **already resolved** (D5): the engine holds the CHG's risk and its
    tighten-only Autonomy override, and resolving here would mean this module re-deriving a decision
    the shipped ``halt_gate.py`` owns. ``node_spec`` likewise carries what only a CHG task can say.
    Both are validated against closed field sets, so nothing outside the contract can ride in.
    """
    tree = Path(tree)
    _check_node_spec(node_spec)
    _check_verdict(policy_verdict)

    capabilities = capabilities_for(skill_path, role)
    loadout = _loadout(tree, role)
    index = _source_index(tree)
    element_id = _element_id(tree, checkpoint_id, index)

    # Language is selected at dispatch for the same reason situational flags and risk are: the
    # element tree holds every language completely and unevaluated, and the engine picks. Sending a
    # node both languages of every section would hand it twice the surface it can use.
    def _pick(by_lang: Mapping[str, Sequence[str]]) -> List[str]:
        wanted = list(languages) if languages else sorted(by_lang)
        unknown = [lang for lang in wanted if lang not in by_lang]
        if unknown:
            raise WorkOrderError(
                f"requested language(s) {unknown} are not in this element set: {sorted(by_lang)}")
        return [element_id for lang in wanted for element_id in by_lang[lang]]

    element_ids: List[str] = list(_pick(loadout["base"]["element_ids"]))
    for flag in situational_flags:
        element_ids.extend(_pick(_situational(tree, flag)["element_ids"]))

    sources = []
    # `source_id`, not `element_id`: the node's own element id is already bound above, and rebinding
    # it here silently made every order name the last source instead of the node — caught by the
    # test that asserts a no-checkpoint node names the element it came from.
    for source_id in sorted(set(element_ids)):
        resolved = index.get(source_id)
        if resolved is None:
            raise WorkOrderError(
                f"loadout for {role!r} names content element {source_id!r}, which is not in the "
                f"tree's manifest — the order would carry an id the node cannot resolve")
        sources.append(resolved)

    order = {
        "node_id": f"{role}@{checkpoint_id}",
        "element_id": element_id,
        "store_version": str(_manifest(tree, "manifest.json")["skill_version"]),
        "role": role,
        "scope": node_spec["scope"],
        "objective": node_spec["objective"],
        "done_criteria": node_spec["done_criteria"],
        "sources": sources,
        "input_artifacts": node_spec["input_artifacts"],
        "expected_outputs": node_spec["expected_outputs"],
        "acceptance_predicate": node_spec["acceptance_predicate"],
        "policy_verdict": dict(policy_verdict),
        "capabilities": capabilities,
        "idempotence_probes": node_spec["idempotence_probes"],
        "workdir": node_spec["workdir"],
    }
    if tuple(sorted(order)) != tuple(sorted(WORK_ORDER_FIELDS)):
        raise WorkOrderError(                                # pragma: no cover - structural guard
            f"rendered order does not match the closed schema: {sorted(order)}")
    return order


def to_json(order: Mapping[str, object]) -> str:
    """Serialise deterministically — same conventions as the element tree (sorted keys, LF, UTF-8)."""
    return json.dumps(order, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
