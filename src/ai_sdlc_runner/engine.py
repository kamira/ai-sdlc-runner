"""engine.py — walk the flow, one independent session per ask.

CHG-20260823-01. `graph.py` says what the flow is, `policy.py` says what the gates decide, and this
walks the one consulting the other. Nothing here reads a skill: the governance is ours.

## One ask, one session

Every node that asks a model gets **its own session**, and it is a correctness property rather than
an economy — the requirement gives the reason: continuity breeds bias, a model coasting on or
anchored by the previous exchange. The engine therefore owns the lifecycle: **open, ask once, close
in a `finally`**, and a factory that hands back a session it already returned is refused outright,
because that is the persistent case by definition.

A **multi-seat review is several asks**, so each seat is its own session. Otherwise "three seats" is
one model answering three times in one context, which is the anchoring the seats were bought to
avoid. The count is the user's to set; the independence is not.

## The gate is consulted, not carried

`policy.verdict` is asked **before** anything is dispatched, because halting after the work was done
is not halting. Anything that is not `auto` stops the run, so no ordering between `confirm`, `halt`
and `halt_independent` is needed anywhere.

## The question outlives the session

`AskJournal` writes the order down **before** the session opens and marks it answered afterwards, so
a dropped session costs the answer and not the question; what is still pending is re-askable
verbatim. Reconstructing a question later risks asking a subtly different one, and a subtly different
question is how a rerun quietly stops being a rerun.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from . import graph, policy, workorder

SessionFactory = Callable[[], "Session"]
Dispatcher = Callable[[Dict[str, object]], Mapping[str, object]]


class EngineError(Exception):
    """Raised when the run cannot continue truthfully. Never softened into a skip."""


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

    A factory takes nothing and returns a session; a dispatcher takes the order. Both are usually
    plain callables, so sniffing for an ``ask`` attribute calls one with the other's arguments.
    """
    import inspect

    try:
        params = inspect.signature(dispatch).parameters
    except (TypeError, ValueError):                      # pragma: no cover - exotic callables
        return dispatch
    required = [p for p in params.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return (lambda: _OneShot(dispatch)) if len(required) == 1 else dispatch


class AskJournal:
    """Write the question down before asking it, so a lost session costs only the answer."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ask_id: str) -> Path:
        return self.dir / f"{ask_id}.json"

    def record(self, ask_id: str, node_id: str, seat: Optional[str],
               order: Mapping[str, object]) -> str:
        self._write(ask_id, {"ask_id": ask_id, "node_id": node_id, "seat": seat,
                             "status": "pending", "order": dict(order)})
        return ask_id

    def answered(self, ask_id: str, result: Mapping[str, object]) -> None:
        payload = json.loads(self._path(ask_id).read_text(encoding="utf-8"))
        payload["status"] = "answered"
        payload["result"] = dict(result)
        self._write(ask_id, payload)

    def pending(self) -> List[Dict[str, object]]:
        """Every ask written down but never answered — the re-ask list, in order."""
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
    #: What the policy said at each node, so a halt can be audited afterwards.
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


@dataclass
class RunConfig:
    """Everything the walk needs that the governance definitions cannot supply."""

    node_specs: Mapping[str, Mapping[str, object]]
    decisions: Mapping[str, object]
    #: The change's risk grade. The engine resolves each gate from it — it is never handed a verdict.
    risk: str = "high"
    #: The change's autonomy override. Tighten-only; `policy.verdict` enforces that.
    autonomy: Optional[str] = None
    review_seats: Optional[int] = None
    high_risk_mode: bool = False
    max_steps: int = 200
    journal: Optional[AskJournal] = None


def resolve_verdict(node: graph.Node, risk: str, autonomy: Optional[str] = None) -> Dict[str, object]:
    """What the policy says at this node, or a plain pass where the flow puts no gate.

    A node with no gate says so rather than borrowing one. An earlier version defaulted such nodes to
    somebody else's gate, inside a module whose own docstring forbids silent fallbacks; an
    independent verifier found it.
    """
    if not node.gate:
        return {"gate": None, "risk": risk, "verdict": policy.AUTO, "tightened": False,
                "source": "the flow puts no gate on this node"}
    return policy.verdict(node.gate, risk, autonomy)


def _order_for(node: graph.Node, cfg: RunConfig, verdict: Mapping[str, object],
               seat: Optional[str] = None) -> Dict[str, object]:
    spec = cfg.node_specs.get(node.id)
    if spec is None:
        raise EngineError(
            f"node {node.id!r} has no work order: no node spec was supplied for it. A node the "
            f"engine cannot template is a hard error naming the node — never a fall back to a "
            f"generic prompt.")
    return workorder.render(node, spec, verdict, seat=seat)


def _open(factory: SessionFactory, seat: Optional[str]):
    """Open a session, letting a factory route by seat if it accepts one.

    Routing — which model answers — lives in the factory and never in the order, which is what makes
    cross-model review meaningful: **the same question, different answerers.**
    """
    import inspect

    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):                      # pragma: no cover - exotic callables
        return factory()
    return factory(seat=seat) if "seat" in params else factory()


def _ask(factory: SessionFactory, order: Mapping[str, object], seen: List[object],
         seat: Optional[str] = None, journal: Optional[AskJournal] = None,
         ask_id: Optional[str] = None, node_id: str = ""):
    """Open a session, ask once, close it — the close guaranteed even if the ask raises.

    ``seen`` holds the session **objects**, not their ``id()``: an id is not an identity once the
    object is gone, and every ask drops its session. Tracking ids passed on 3.9 and 3.11 by
    allocation luck and failed on 3.13.
    """
    if journal is not None and ask_id is not None:
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


def _choose(cfg: RunConfig, node: graph.Node, taken: Dict[str, int]) -> Optional[str]:
    """The branch this visit takes: one label always, or a sequence consumed one per visit.

    The module loop needs the second form to say "module, module, none"; a static map would silently
    turn the shipped loop into either an infinite one or a single pass.
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


def walk(cfg: RunConfig, dispatch: Dispatcher, enabled: bool = False) -> RunReport:
    """Walk the flow from ``intake``, dispatching one work order per ask.

    ``enabled`` is the opt-in flag. It refuses rather than quietly doing nothing, so a caller cannot
    mistake "flag off" for "ran and found nothing to do".
    """
    if not enabled:
        raise EngineError(
            "the node engine is opt-in and is not enabled. Pass enabled=True — or --engine.")

    graph.validate()
    factory = _as_factory(dispatch)
    opened: List[object] = []
    taken: Dict[str, int] = {}
    report = RunReport()

    seats = policy.resolve_seats(cfg.review_seats, cfg.high_risk_mode)
    if cfg.review_seats is not None and cfg.review_seats < policy.SEAT_FLOOR:
        report.relaxations.append(
            f"high-risk mode: review opened with {seats} seat(s), below the floor of "
            f"{policy.SEAT_FLOOR}")

    node_id: Optional[str] = "intake"
    for _ in range(cfg.max_steps):
        if node_id is None:
            break
        node = graph.BY_ID[node_id]
        report.visited.append(node.id)

        verdict = resolve_verdict(node, cfg.risk, cfg.autonomy)
        report.verdicts[node.id] = dict(verdict)
        if policy.stops(str(verdict["verdict"])):
            report.halted_at = node.id
            report.halt_reason = (
                f"{verdict['gate']} = {verdict['verdict']} at risk {verdict['risk']} "
                f"(per {verdict['source']})")
            return report

        if node.role:
            if node.role == "seat":
                for seat in policy.seat_names(seats):
                    report.asks.append(Ask(node.id, node.role, seat, _ask(
                        factory, _order_for(node, cfg, verdict, seat), opened, seat=seat,
                        journal=cfg.journal, ask_id=f"{len(report.asks):03d}-{node.id}-{seat}",
                        node_id=node.id)))
            else:
                report.asks.append(Ask(node.id, node.role, None, _ask(
                    factory, _order_for(node, cfg, verdict), opened, journal=cfg.journal,
                    ask_id=f"{len(report.asks):03d}-{node.id}", node_id=node.id)))

        if node.kind == graph.TERMINAL:
            report.halted_at = node.id
            report.halt_reason = node.note or node.label
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
        raise EngineError(
            f"walk exceeded {cfg.max_steps} steps — the flow is cycling without progress")

    return report
