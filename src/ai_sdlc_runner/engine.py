"""engine.py — walk the shipped node graph, one independent session per asking node.

CHG-20260822-04 task 6. `graph.py` says what the flow is; this walks it. Behind an opt-in flag: the
four-stage path in `orchestrator.py` is untouched until someone turns this on, and flipping the
default is a separate, later decision (D7).

## One asking node, one session

Every node that asks a model gets **its own session**. Not as an optimisation — as a correctness
property, and the requirement states why: continuity breeds bias. It is the same reason the shipped
review panel runs phase 1 blind, in its own words, *"a seat that reads first agrees first"*.

So the engine hands the dispatcher a **work order and nothing else**: no transcript, no prior result,
no accumulated context. That is enforced rather than intended — `workorder.render` produces a closed
schema with no field able to carry history, and `dispatch` is called once per ask with exactly that
one object. A node the runner performs itself — reading the ledger, evaluating a gate — asks no model
and is not covered.

A **multi-seat review is several asks**, so each seat is its own session too. Otherwise "three seats"
degrades into one model answering three times in one context, which is the anchoring the seat count
was bought to avoid. The count is configurable; the independence is not.

## The seat floor, and the way past it

`review_seats.json` ships three seats, so three is the default and the floor — a machine-readable
number, not a number chosen here. The shipped risk-scaled quotas (`review-panel.md`: high = all six,
medium ≥ five; `review_seats.json`'s `_ordering`: low = first seat only, medium/high = first three)
live in **prose fields**, so they are recorded as a known gap rather than parsed; see
CHG-20260822-04.

A user may go below the floor by enabling **high-risk mode**, which is their call to make: relaxing a
gate needs a human's prior approval and they gave it. What it does not get to be is quiet. Enabling
it is **written to the ledger with the run**, the same treatment the shipped design gives
`--allow-no-ci` and `--allow-untested` — a bypass that leaves no trace is the failure this repo keeps
finding.

## Nothing is skipped

Two hard stops, both naming what stopped and neither advancing the run:

* a node with **no work order** — untemplated, per D7 — is a hard error naming the node id.
* a node whose **role has no shipped capability data** is a hard error naming the role. Nine of the
  thirteen declared roles are in that state; the engine must not step over them. Skipping is the
  silent downgrade the whole design refuses.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from . import graph, workorder

#: A session is opened for one ask and closed when that ask is done. The engine owns the lifecycle
#: so that "no persistent session" is a property it enforces rather than one it hopes a dispatcher
#: honours: `open → ask → close`, with the close in a `finally`, and a factory that hands back the
#: same session twice is refused outright — that is precisely the persistent case.
#:
#: A plain callable is still accepted and is wrapped as a one-shot session, which is the same thing
#: with the lifecycle made implicit.
SessionFactory = Callable[[], "Session"]
Dispatcher = Callable[[Dict[str, object]], Mapping[str, object]]


class Session:
    """One ask's session. Subclass or duck-type: ``ask(order)`` then ``close()``."""

    def ask(self, order: Mapping[str, object]) -> Mapping[str, object]:   # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:                                              # pragma: no cover
        raise NotImplementedError


class _OneShot(Session):
    """Wraps a plain ``dispatch(order)`` callable so it still gets a session per ask."""

    def __init__(self, dispatch: Dispatcher):
        self._dispatch = dispatch
        self._used = False

    def ask(self, order):
        if self._used:
            raise EngineError("a session is opened for exactly one ask and this one is spent")
        self._used = True
        return self._dispatch(order)

    def close(self) -> None:
        self._dispatch = None


def _as_factory(dispatch) -> SessionFactory:
    """Tell a session factory from a plain dispatcher by **arity**, not by duck-typing.

    A factory takes nothing and returns a session; a dispatcher takes the work order. Sniffing for
    an ``ask`` attribute cannot tell them apart — a factory is usually a plain callable too — and
    getting it wrong calls one with the other's arguments, which is how this first went wrong.
    """
    import inspect

    try:
        params = inspect.signature(dispatch).parameters
    except (TypeError, ValueError):                      # pragma: no cover - exotic callables
        return dispatch
    required = [p for p in params.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(required) == 1:
        return lambda: _OneShot(dispatch)
    return dispatch


class EngineError(Exception):
    """Raised when the run cannot continue truthfully. Never softened into a skip."""


class AskJournal:
    """Write the question down **before** asking it, so a lost session costs nothing but the answer.

    Sessions drop. When one does, the work that must not be lost is the *question*: reconstructing it
    later risks asking a subtly different one, and a subtly different question is how a rerun quietly
    stops being a rerun. So the order is persisted first, marked answered afterwards, and anything
    still pending is re-askable **verbatim** on recovery.

    This is D6's discipline applied to asking: intent lands on disk before the act, the outcome
    lands immediately after, and the pending set is the frontier. It is also what makes the
    anti-bias property survive a crash — a re-ask is the same question put to a fresh session, not a
    continuation of one that already half-answered it.
    """

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ask_id: str) -> Path:
        return self.dir / f"{ask_id}.json"

    def record(self, ask_id: str, node_id: str, seat: Optional[str],
               order: Mapping[str, object]) -> str:
        """Persist a pending ask. Returns the id. Called before the session is even opened."""
        payload = {"ask_id": ask_id, "node_id": node_id, "seat": seat,
                   "status": "pending", "order": dict(order)}
        self._write(ask_id, payload)
        return ask_id

    def answered(self, ask_id: str, result: Mapping[str, object]) -> None:
        payload = json.loads(self._path(ask_id).read_text(encoding="utf-8"))
        payload["status"] = "answered"
        payload["result"] = dict(result)
        self._write(ask_id, payload)

    def pending(self) -> List[Dict[str, object]]:
        """Every ask that was written down but never answered — the re-ask list, in order."""
        out = []
        for path in sorted(self.dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") == "pending":
                out.append(payload)
        return out

    def _write(self, ask_id: str, payload: Dict[str, object]) -> None:
        self._path(ask_id).write_bytes(
            (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            .encode("utf-8"))


@dataclass
class Ask:
    """One dispatch: which node, which seat (if any), and what came back."""

    node_id: str
    role: str
    seat: Optional[str] = None
    result: Optional[Mapping[str, object]] = None


@dataclass
class RunReport:
    visited: List[str] = field(default_factory=list)
    asks: List[Ask] = field(default_factory=list)
    halted_at: Optional[str] = None
    halt_reason: str = ""
    #: Recorded, not just honoured: every relaxation the run was granted.
    relaxations: List[str] = field(default_factory=list)
    #: The verdict the shipped policy gave at each node, so a halt can be audited afterwards.
    verdicts: Dict[str, Dict[str, object]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "visited": list(self.visited),
            "asks": [{"node_id": a.node_id, "role": a.role, "seat": a.seat} for a in self.asks],
            "halted_at": self.halted_at,
            "halt_reason": self.halt_reason,
            "relaxations": list(self.relaxations),
            "verdicts": {k: dict(v) for k, v in self.verdicts.items()},
        }


def seat_floor(skill_path: str | Path) -> int:
    """The shipped seat count: how many seats ``review_seats.json`` actually declares.

    A number read from the archive rather than chosen here. The risk-scaled quotas in
    ``review-panel.md`` are prose and are not parsed — recorded as a gap instead.
    """
    path = Path(skill_path) / "assets" / "review_seats.json"
    if not path.is_file():
        raise EngineError(f"{path} not found — the seat floor is read from the store, not assumed")
    seats = json.loads(path.read_text(encoding="utf-8")).get("seats", {})
    if not seats:
        raise EngineError(f"{path} declares no seats")
    return len(seats)


def resolve_seats(skill_path: str | Path, requested: Optional[int], high_risk_mode: bool) -> int:
    """How many seats this run opens, and whether that needed a relaxation.

    Raises unless ``high_risk_mode`` is on when the request is below the shipped floor: going below
    is a loosening, and the runner does not loosen a gate on its own authority.
    """
    floor = seat_floor(skill_path)
    if requested is None:
        return floor
    if requested < 1:
        raise EngineError("a review needs at least one seat")
    if requested < floor and not high_risk_mode:
        raise EngineError(
            f"{requested} seat(s) is below the shipped floor of {floor} "
            f"(assets/review_seats.json declares {floor}). Enable high-risk mode to go below it — "
            f"the runner does not relax a gate on its own authority.")
    return requested


def seat_names(skill_path: str | Path, count: int) -> List[str]:
    """The first ``count`` shipped seats, in the archive's own order.

    ``_ordering`` says the order *is* the opening order and puts the least negotiable first, so
    taking a prefix is the shipped way to open fewer — not a choice made here.
    """
    path = Path(skill_path) / "assets" / "review_seats.json"
    names = list(json.loads(path.read_text(encoding="utf-8")).get("seats", {}))
    if count > len(names):
        raise EngineError(f"{count} seats requested but only {len(names)} ship")
    return names[:count]


@dataclass
class RunConfig:
    """Everything the walk needs that a store cannot supply."""

    node_specs: Mapping[str, Mapping[str, object]]
    decisions: Mapping[str, object]
    #: The CHG's risk grade. The engine resolves each checkpoint's verdict from the shipped policy
    #: itself — it is not handed one. A caller supplying verdicts would be the runner trusting
    #: somebody else's reading of a gate, which is the opposite of what the gate is for.
    risk: str = "high"
    #: The CHG's `Autonomy:` field, passed through to the shipped resolver. Tighten-only: it can
    #: make a gate stricter and never looser (the shipped script enforces that, not this module).
    review_seats: Optional[int] = None
    high_risk_mode: bool = False
    autonomy: Optional[str] = None
    situational_flags: Sequence[str] = ()
    languages: Sequence[str] = ()
    max_steps: int = 200
    #: Where pending asks are written before they are asked. Without it a dropped session loses the
    #: question as well as the answer.
    journal: Optional[AskJournal] = None


def _choose(cfg: RunConfig, node: graph.Node, taken: Dict[str, int]) -> Optional[str]:
    """The branch this visit takes.

    A decision may be a single label — always this way — or a sequence consumed one per visit. The
    loop node needs the second form to say "task, task, none", and a run that cannot express that
    cannot express the shipped per-task loop at all; a static map would silently turn it into either
    an infinite loop or a single pass.
    """
    value = cfg.decisions.get(node.id)
    if value is None or isinstance(value, str):
        return value
    visit = taken.get(node.id, 0)
    taken[node.id] = visit + 1
    if visit >= len(value):
        raise EngineError(
            f"node {node.id!r} was reached {visit + 1} time(s) but only {len(value)} decision(s) "
            f"were supplied for it — the run does not guess how the loop ends")
    return value[visit]


def resolve_verdict(skill_path: str | Path, tree: str | Path, node: graph.Node,
                    risk: str, autonomy: Optional[str] = None) -> Dict[str, object]:
    """The verdict for this node, resolved from the shipped policy — never taken on trust.

    The Goal says the engine halts "only where the shipped policy says halt", and that is only true
    if the engine asks the policy. An earlier version took a verdict from the caller's plan and
    walked past it without looking; **both independent verifiers named that as their worst finding**,
    and they were right — a gate nobody consults is not a gate.

    Two axes, resolved the way each one ships:

    * ``halt:*`` — delegated to the store's own ``halt_gate.py`` through ``gates.check_halt``
      (FR-8, guideline §8 "calls, not re-implementations"). The CHG's ``Autonomy`` field goes with
      it, and the shipped script is what enforces tighten-only.
    * ``autopilot:*`` — read from the verdict table the element carries verbatim, because no usable
      resolver ships for that axis (``scripts/autopilot_runner.py`` cannot import; its ``lib/`` was
      not archived).

    A node with **several** checkpoints is judged by all of them and the **strictest wins** — which
    is why this never has to settle fork point 6. Ordering ``halt`` against ``halt_independent``
    would only matter if something continued on one of them; nothing does. Anything that is not
    ``auto`` stops the run, so the engine needs the two-way split it can actually derive, and the
    raw verdict travels for the record.
    """
    from . import gates

    if not node.checkpoints:
        # No checkpoint means the shipped policy grades no gate here — `whole-branch review` is a
        # code gate, not a risk gate. Inventing one (an earlier version defaulted to
        # `halt:before_implement`) is the silent fallback this module's own docstring forbids.
        return {"checkpoint": None, "risk": risk, "verdict": "auto",
                "source": "no policy checkpoint on this node"}

    resolved = []
    for checkpoint_id in node.checkpoints:
        namespace, key = checkpoint_id.split(":", 1)
        if namespace == graph.HALT_NS:
            decision = gates.check_halt(skill_path, key, risk, autonomy=autonomy)
            verdict = "auto" if decision.result == "AUTO" else "halt"
            source = "scripts/halt_gate.py"
        else:
            table = _checkpoint_table(tree, checkpoint_id)
            verdict = table.get(risk.lower())
            if verdict is None:
                raise EngineError(
                    f"{checkpoint_id} ships no verdict for risk {risk!r}; it grades "
                    f"{sorted(table)}. The engine does not guess a gate.")
            source = f"assets/autopilot_policy.json#{key}"
        resolved.append({"checkpoint": checkpoint_id, "verdict": verdict, "source": source})

    stopping = [r for r in resolved if r["verdict"] != "auto"]
    chosen = stopping[0] if stopping else resolved[0]
    return {"checkpoint": chosen["checkpoint"], "risk": risk, "verdict": chosen["verdict"],
            "source": chosen["source"]}


def _checkpoint_table(tree: str | Path, checkpoint_id: str) -> Dict[str, str]:
    namespace, key = checkpoint_id.split(":", 1)
    path = Path(tree) / "dispatch" / "checkpoints" / namespace / f"{key}.json"
    if not path.is_file():
        raise EngineError(f"no checkpoint element {checkpoint_id!r} in {tree}")
    return json.loads(path.read_text(encoding="utf-8"))["risk_table"]


def _order_for(skill_path, tree, node: graph.Node, cfg: RunConfig,
               verdict: Mapping[str, object]) -> Dict[str, object]:
    spec = cfg.node_specs.get(node.id)
    if spec is None:
        raise EngineError(
            f"node {node.id!r} has no work order: no node spec was supplied for it. A node the "
            f"engine cannot template is a hard error naming the node — never a fall back to a "
            f"generic prompt (D7).")
    # The work order names the element this node came from. With a checkpoint that is the checkpoint
    # element; without one it is the shipped flow element the node was written from — a real element
    # either way, never a fabricated id.
    element_id = verdict["checkpoint"] or graph.SOURCE_ELEMENT
    return workorder.render(
        skill_path, tree, node.role, element_id, spec, verdict,
        situational_flags=cfg.situational_flags, languages=cfg.languages,
    )


def _open(factory: SessionFactory, seat: Optional[str]):
    """Open a session, letting the caller route by seat if its factory accepts one.

    Routing lives in the factory, never in the work order: which model answers is a dispatch setting
    and D5 keeps those out of the order entirely. That separation is what makes cross-model review
    meaningful — **the same question**, put to different answerers.
    """
    import inspect

    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):                      # pragma: no cover - exotic callables
        return factory()
    if "seat" in params:
        return factory(seat=seat)
    return factory()


def _ask(factory: SessionFactory, order: Mapping[str, object], seen: List[object],
         seat: Optional[str] = None, journal: Optional[AskJournal] = None,
         ask_id: Optional[str] = None, node_id: str = ""):
    """Open a session, ask once, close it — the close guaranteed even if the ask raises.

    The identity check is the teeth: a factory that returns a session it has returned before is
    keeping one alive across asks, which is the continuity the requirement rules out.

    ``seen`` holds the session **objects**, not their ``id()``. The first version stored ids, which
    is not identity at all once the object is gone: CPython reuses addresses, so a fresh session
    could be handed the id of a collected one and be rejected as a reuse. It passed on 3.9 and 3.11
    by allocation luck and failed on 3.13 — the version matrix earning its place. Holding the
    references also guarantees no address can be recycled while the run is comparing against it.
    """
    if journal is not None and ask_id is not None:
        # Written down before the session is even opened: if everything after this line is lost, the
        # question survives and the next run asks exactly it.
        journal.record(ask_id, node_id, seat, order)
    session = _open(factory, seat)
    if any(previous is session for previous in seen):
        raise EngineError(
            "the session factory returned a session it already returned: every ask opens its own "
            "session and closes it afterwards, so nothing carries over between asks")
    seen.append(session)
    try:
        result = session.ask(order)
    finally:
        session.close()
    if journal is not None and ask_id is not None:
        journal.answered(ask_id, result)
    return result


def walk(skill_path: str | Path, tree: str | Path, cfg: RunConfig,
         dispatch: Dispatcher, enabled: bool = False) -> RunReport:
    """Walk the graph from ``handshake``, dispatching one work order per ask.

    ``enabled`` is the opt-in flag. Off by default so the four-stage path stays the only thing that
    runs until someone chooses otherwise; the engine refuses rather than quietly doing nothing, so a
    caller cannot mistake "flag off" for "ran and found nothing to do".
    """
    if not enabled:
        raise EngineError(
            "the node engine is opt-in and is not enabled: the four-stage path is still the default "
            "(D7). Pass enabled=True — or --engine — to run it.")

    graph.validate()
    factory = _as_factory(dispatch)
    opened: List[object] = []
    taken: Dict[str, int] = {}
    report = RunReport()
    seats = resolve_seats(skill_path, cfg.review_seats, cfg.high_risk_mode)
    if cfg.review_seats is not None and cfg.review_seats < seat_floor(skill_path):
        report.relaxations.append(
            f"high-risk mode: review opened with {seats} seat(s), below the shipped floor of "
            f"{seat_floor(skill_path)}")

    node_id: Optional[str] = "handshake"
    for _ in range(cfg.max_steps):
        if node_id is None:
            break
        node = graph.BY_ID[node_id]
        report.visited.append(node.id)

        # The gate is consulted *before* anything is dispatched: halting after the work was done
        # is not halting.
        verdict = resolve_verdict(skill_path, tree, node, cfg.risk, cfg.autonomy)
        report.verdicts[node.id] = dict(verdict)
        if verdict["verdict"] != "auto":
            report.halted_at = node.id
            report.halt_reason = (
                f"{verdict['checkpoint']} = {verdict['verdict']} at risk {verdict['risk']} "
                f"(per {verdict['source']})")
            return report

        if node.role:
            # Capability first: a role with no shipped data stops the run where it stands, so the
            # frontier does not advance past a node that was never actually performed.
            try:
                workorder.capabilities_for(skill_path, node.role)
            except workorder.WorkOrderError as exc:
                report.halted_at = node.id
                report.halt_reason = str(exc)
                raise EngineError(
                    f"node {node.id!r} dispatches role {node.role!r}, which has no shipped "
                    f"capability data — stopping rather than skipping it. {exc}") from None

            if node.id == "branch_review":
                for seat in seat_names(skill_path, seats):
                    order = _order_for(skill_path, tree, node, cfg, verdict)
                    # One ask, one session — per seat, not per node. Three seats answering inside one
                    # context would be one opinion repeated.
                    report.asks.append(Ask(node.id, node.role, seat, _ask(
                        factory, order, opened, seat=seat, journal=cfg.journal,
                        ask_id=f"{len(report.asks):03d}-{node.id}-{seat}", node_id=node.id)))
            else:
                order = _order_for(skill_path, tree, node, cfg, verdict)
                report.asks.append(Ask(node.id, node.role, None, _ask(
                    factory, order, opened, journal=cfg.journal,
                    ask_id=f"{len(report.asks):03d}-{node.id}", node_id=node.id)))

        if node.kind == graph.TERMINAL:
            report.halted_at = node.id
            report.halt_reason = node.note or f"terminal node {node.id}"
            return report

        if node.branches:
            choice = _choose(cfg, node, taken)
            if choice is None:
                raise EngineError(
                    f"node {node.id!r} branches on {sorted(node.branches)} but the run supplied no "
                    f"choice for it — the engine does not guess a branch")
            if choice not in node.branches:
                raise EngineError(
                    f"node {node.id!r} has no branch {choice!r}; it offers {sorted(node.branches)}")
            node_id = node.branches[choice]
        else:
            node_id = node.next
    else:
        raise EngineError(f"walk exceeded {cfg.max_steps} steps — the graph is cycling without progress")

    return report
