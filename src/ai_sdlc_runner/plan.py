"""plan.py — the plan file, closed (CHG-20260823-28).

The plan is the outermost schema: every other shape rides inside it. It was the **only** entry point
with no validation at all — read key by key with `plan.get(...)`, unknown keys silently accepted and
doing nothing.

Six independent seat reviews named it, and one gave the case that decides it:

> a plan whose `ship` key is misspelled runs **with no side effects and reports `finished`** — a dry
> run wearing a shipped run's report, produced by one typo nothing refuses.

That is the repository's own doctrine failing at its front door. `settings.py` and `models.py`
enforce exactly this for files far less consequential, and both say why in the same words:

    a setting that looks configured and does nothing is worse than one that was rejected

## Closed at two levels

The top level, and the `ship` block inside it — because `ship` is where the silent-dry-run case
lives, and closing the outside while leaving that open would answer the complaint and not the
finding.

## Types, not only keys

`node_specs` must be an object, `operations` an object of lists. A key of the right name holding the
wrong shape is the same defect one step in: `"node_specs": []` reads as configured and supplies
nothing.

**Not exhaustive, and it says so.** This refuses what it can name. It does not validate the interior
of a node spec — `workorder._check` does that, closed, at render time — and it does not check that a
node id exists, because a plan may legitimately name nodes for a graph it has not been run against
yet.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, Tuple

#: Every key this runner reads from a plan. Anything else is refused.
#:
#: Derived from the code that reads them, not from memory: each of these appears as a `plan.get(...)`
#: in `cli.py`, and a test walks the source to prove the two lists have not drifted apart.
FIELDS: Tuple[str, ...] = (
    "risk",          # the change's grade — low | medium | high
    "autonomy",      # tighten-only override
    "node_specs",    # {node id: the closed 9-field spec}
    "operations",    # {node id: [{description, kind, targets}]}
    "decisions",     # {node id: branch}
    "node_models",   # {node id: [model id]}
    "seat_models",   # {seat: model id or argv}
    "ship",          # the side effects — see SHIP_FIELDS
)

#: The `ship` block's own closed set. `repo`, `chg_id`, `branch` and `message` are required by
#: `effects_provider`; the rest are optional there and listed so a typo in one is caught.
SHIP_FIELDS: Tuple[str, ...] = (
    "repo", "chg_id", "chg_body", "branch", "message", "remote",
    "task", "acc_id", "acc_body",
)

#: `ship` keys `effects_provider` indexes directly — a missing one is an unhandled `KeyError` deep
#: in a run rather than a refusal at the door.
SHIP_REQUIRED: Tuple[str, ...] = ("repo", "chg_id", "branch", "message")

#: The keys whose value must be an object keyed by something.
_MAPPINGS = ("node_specs", "operations", "decisions", "node_models", "seat_models", "ship")


class PlanError(Exception):
    """Refused. A plan this runner accepted while not understanding is worse than one it refused."""


def check(payload: Mapping[str, object], where: str = "the plan") -> Dict[str, object]:
    """Refuse a plan this runner would not fully honour, and return it otherwise."""
    if not isinstance(payload, Mapping):
        raise PlanError(f"{where} should be a JSON object with keys like {list(FIELDS[:3])}")

    unknown = sorted(set(payload) - set(FIELDS))
    if unknown:
        raise PlanError(
            f"{where} sets {unknown}, which this runner does not read. Ignoring them would let a "
            f"setting look configured and do nothing — and the case that decides it is `ship`: a "
            f"misspelt one makes a run perform no side effects and report `finished`. "
            f"This runner reads {list(FIELDS)}.")

    for key in _MAPPINGS:
        value = payload.get(key)
        if value is not None and not isinstance(value, Mapping):
            raise PlanError(
                f"{where} has {key!r} as {type(value).__name__}, and this runner reads it as an "
                f"object. A key of the right name holding the wrong shape reads as configured and "
                f"supplies nothing.")

    for key in ("node_models", "seat_models"):
        for owner, value in (payload.get(key) or {}).items():
            if key == "node_models" and not isinstance(value, (list, tuple)):
                raise PlanError(
                    f"{where} assigns {owner!r} a single {type(value).__name__}; `node_models` "
                    f"holds a **list** of model ids, and the order is load-bearing.")

    ship = payload.get("ship")
    if ship is not None:
        _check_ship(ship, where)
    return dict(payload)


def _check_ship(ship: Mapping[str, object], where: str) -> None:
    """The block whose typo produced a silent dry run. Closed, and its required keys named."""
    unknown = sorted(set(ship) - set(SHIP_FIELDS))
    if unknown:
        raise PlanError(
            f"{where}'s `ship` sets {unknown}, which nothing reads. This is the block a misspelt "
            f"key makes silent, so it refuses rather than skips. It reads {list(SHIP_FIELDS)}.")
    missing = [key for key in SHIP_REQUIRED if not ship.get(key)]
    if missing:
        raise PlanError(
            f"{where}'s `ship` is missing {missing}. Those are indexed directly, so leaving one out "
            f"is a KeyError partway through a run rather than a refusal before it starts.")


def load(path: str | Path) -> Dict[str, object]:
    """Read a plan file and refuse it if this runner would not fully honour it."""
    file = Path(path)
    if not file.is_file():
        raise PlanError(f"no plan at {file}")
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PlanError(f"{file} is not valid JSON: {exc}") from None
    return check(payload, where=str(file))
