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

from . import effects as effects_mod
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
    #: Gates the operator had already confirmed, recorded so an approval leaves a trace.
    confirmations: List[str] = field(default_factory=list)
    #: Every panel decision, with the seats' verdicts that produced it.
    adjudications: List[Dict[str, object]] = field(default_factory=list)
    #: What each node's effects did — applied, already met, and anything found true out of order.
    effects: Dict[str, Dict[str, object]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "visited": list(self.visited),
            "asks": [{"node_id": a.node_id, "role": a.role, "seat": a.seat} for a in self.asks],
            "halted_at": self.halted_at,
            "halt_reason": self.halt_reason,
            "relaxations": list(self.relaxations),
            "verdicts": {k: dict(v) for k, v in self.verdicts.items()},
            "confirmations": list(self.confirmations),
            "adjudications": [dict(a) for a in self.adjudications],
            "effects": {k: dict(v) for k, v in self.effects.items()},
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
    #: The ordered effects a node carries out, looked up by node id. `record_module` says in the
    #: flow that it ticks, commits and updates the worklog — "three ordered effects" — and until
    #: this hook existed that sentence was a comment: the node did nothing at all. Each effect is
    #: probed before it is applied and re-probed after, so a resumed run redoes nothing.
    effects: Optional[Callable[[str], Sequence["effects_mod.Effect"]]] = None
    #: What each node is about to actually do, keyed by node id. Each entry **declares** its kind:
    #: ``{"description": ..., "kind": one of policy.PERMANENT_HALT_KINDS or policy.ORDINARY}``. A
    #: declared red line stops the run at every risk grade, whatever is confirmed and whatever mode
    #: is on — and an operation that declares nothing is refused rather than assumed safe.
    operations: Mapping[str, Sequence[Mapping[str, object]]] = field(default_factory=dict)
    #: What to do at a node that does real work and declares no operations. ``refuse`` is the
    #: default and the only safe one: a plan that simply omits `operations` used to be checked
    #: against nothing at all, so "run a deploy without stopping" was a matter of saying less rather
    #: than saying something false. ``allow`` exists for dry runs and records itself as a relaxation
    #: — never silently.
    undeclared: str = "refuse"
    #: Gates a human has already confirmed. Without this a stopping verdict ends every run at the
    #: same place forever — an independent verifier found that medium and high risk could never get
    #: past the first gate, which made most of the matrix unreachable. A halt is a pause with a way
    #: back, not a wall.
    confirmed: Sequence[str] = ()
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


def _run_effects(node: graph.Node, cfg: "RunConfig", report: "RunReport"):
    """Carry out this node's ordered effects, if it has any, and record what happened.

    Effects are applied through `effects.run`, which never re-applies one whose postcondition is
    already true and re-probes every one it does apply. An effect that fails to establish its own
    postcondition halts the run rather than letting the flow march past a step that did nothing.
    """
    if cfg.effects is None:
        return None
    sequence = cfg.effects(node.id)
    if not sequence:
        return None
    try:
        outcome = effects_mod.run(sequence)
    except effects_mod.EffectError as exc:
        report.halted_at = node.id
        report.halt_reason = f"effect failed at {node.id!r}: {exc}"
        return report
    report.effects[node.id] = outcome.as_dict()
    return None


def _does_work(node: graph.Node, cfg: "RunConfig") -> bool:
    """Could this node change the world? Then it owes a declaration.

    True when the node dispatches a role that may write or execute, or when it carries effects.
    A review seat reads and answers, so it is not asked to declare anything.
    """
    if cfg.effects is not None and cfg.effects(node.id):
        return True
    if not node.role or node.role == "seat":
        return False
    role = policy.role(node.role)
    return bool(role.can_write or role.can_execute)


def _permanent_halt(node: graph.Node, cfg: "RunConfig", report: "RunReport") -> Optional[str]:
    """The halt reason if this node's work trips a permanent halt, else ``None``.

    Checked before the gate, and unaffected by `confirmed` and by high-risk mode: these are the
    actions whose worst case is not "redo the work". Everything else in this file is a policy the
    operator can turn down; this one is not.

    A node that does real work and declares **nothing** is refused by default. An independent
    verifier found the hole: the check only ever looked at what a plan volunteered, so omitting
    `operations` skipped it entirely — the red lines could be walked past by saying less rather
    than by saying something false.
    """
    declared = cfg.operations.get(node.id)
    if not declared and _does_work(node, cfg):
        if cfg.undeclared != "allow":
            return (
                f"{node.id!r} does work that could change the world and declares no operations. "
                f"Say what it will do — each as {{'description': ..., 'kind': ...}} — or pass "
                f"undeclared='allow' for a dry run, which is recorded. Silence is not a "
                f"declaration that nothing risky happens.")
        report.relaxations.append(f"{node.id} ran undeclared: nothing was checked against the "
                                  f"permanent halts")
        return None

    for operation in declared or ():
        halt = policy.classify(operation)
        if halt is not None:
            what = operation.get("description", operation) if isinstance(operation, Mapping) \
                else operation
            return (
                f"permanent halt at {node.id!r}: {what!r} is {halt}. No risk grade, confirmation "
                f"or mode relaxes this — a person does it.")
    return None


def _answered_branch(node: graph.Node, answers: List[Mapping[str, object]]) -> str:
    """The branch the answer names, at a node where somebody was asked to decide.

    A decision node whose branch comes from the plan while somebody is being asked is a question
    whose answer changes nothing — which is exactly what an independent verifier demonstrated by
    answering every ask with `fail` and still reaching the end of the flow.
    """
    if not answers:
        raise EngineError(f"node {node.id!r} decides on its answer, but nothing answered")
    answer = answers[-1]
    branch = answer.get("branch") or answer.get("verdict") or answer.get("outcome")
    if branch is None:
        raise EngineError(
            f"node {node.id!r} decides on its answer, but the answer named no branch. It must "
            f"carry one of {sorted(node.branches)} as `branch`, `verdict` or `outcome`.")
    if branch not in node.branches:
        raise EngineError(
            f"node {node.id!r} was answered {branch!r}, which is not one of {sorted(node.branches)}")
    return str(branch)


def _adjudicate(node: graph.Node, report: "RunReport", seats: int) -> str:
    """Turn the seats' verdicts into one branch, through `policy.adjudicate`.

    This is the requirement's own sentence made operational — *多數決才允許放行* — and it is what both
    verifiers found missing: the seats were asked, and their answers routed nothing.
    """
    verdicts = {}
    for ask in report.asks:
        if ask.node_id == node.id and ask.seat:
            answer = ask.result or {}
            verdicts[ask.seat] = str(answer.get("verdict") or answer.get("outcome") or "")
    if len(verdicts) != seats:
        raise EngineError(
            f"{node.id!r} opened {seats} seat(s) but collected {len(verdicts)} verdict(s) — a panel "
            f"short of a seat has not reached the majority it was opened for")
    outcome = policy.adjudicate(verdicts)
    report.adjudications.append({"node_id": node.id, **outcome, "verdicts": dict(verdicts)})
    return "pass" if outcome["outcome"] == "pass" else "fail"


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

    # A confirmation is spent, not standing. Counted per gate and decremented at each stop it
    # covers, because the operator confirmed *that* stop having seen it — an independent verifier
    # found that one `--confirm plan_confirmed`, given to unlock a revision loop, also waved through
    # the final approval on the way out. Confirming twice takes two.
    confirmations: Dict[str, int] = {}
    for gate in cfg.confirmed:
        confirmations[gate] = confirmations.get(gate, 0) + 1

    node_id: Optional[str] = "intake"
    for _ in range(cfg.max_steps):
        if node_id is None:
            break
        node = graph.BY_ID[node_id]
        report.visited.append(node.id)

        tripped = _permanent_halt(node, cfg, report)
        if tripped is not None:
            report.halted_at = node.id
            report.halt_reason = tripped
            return report

        verdict = resolve_verdict(node, cfg.risk, cfg.autonomy)
        report.verdicts[node.id] = dict(verdict)

        def _gate(phase: str):
            """Stop here if the policy says so and nobody has confirmed it yet.

            A gate the operator has already confirmed is **recorded** rather than silently skipped:
            an approval that leaves no trace is one nobody can audit afterwards.
            """
            if node.gate_when != phase or not policy.stops(str(verdict["verdict"])):
                return None
            if confirmations.get(node.gate, 0) > 0:
                confirmations[node.gate] -= 1
                report.confirmations.append(
                    f"{node.gate} = {verdict['verdict']} at risk {verdict['risk']} at {node.id}, "
                    f"confirmed by the operator")
                return None
            report.halted_at = node.id
            report.halt_reason = (
                f"{verdict['gate']} = {verdict['verdict']} at risk {verdict['risk']} "
                f"(per {verdict['source']}) — confirm it to continue")
            return report

        stop = _gate("before")
        if stop is not None:
            return stop

        answers: List[Mapping[str, object]] = []
        if node.role:
            if node.role == "seat":
                for seat in policy.seat_names(seats):
                    result = _ask(
                        factory, _order_for(node, cfg, verdict, seat), opened, seat=seat,
                        journal=cfg.journal, ask_id=f"{len(report.asks):03d}-{node.id}-{seat}",
                        node_id=node.id)
                    report.asks.append(Ask(node.id, node.role, seat, result))
                    answers.append(result)
            else:
                result = _ask(
                    factory, _order_for(node, cfg, verdict), opened, journal=cfg.journal,
                    ask_id=f"{len(report.asks):03d}-{node.id}", node_id=node.id)
                report.asks.append(Ask(node.id, node.role, None, result))
                answers.append(result)

        stop = _gate("after")
        if stop is not None:
            return stop

        stop = _run_effects(node, cfg, report)
        if stop is not None:
            return stop

        if node.kind == graph.TERMINAL:
            report.halted_at = node.id
            report.halt_reason = node.note or node.label
            return report

        if node.branches:
            if node.role == "seat":
                choice = _adjudicate(node, report, seats)
            elif node.answer_decides:
                choice = _answered_branch(node, answers)
            else:
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
