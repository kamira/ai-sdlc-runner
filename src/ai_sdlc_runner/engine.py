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
        return [e for e in self.entries() if e.get("status") == "pending"]

    def entries(self) -> List[Dict[str, object]]:
        """Every ask, answered or not, in the order they were asked."""
        return [json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(self.dir.glob("*.json"))]

    def answers(self) -> Dict[str, Mapping[str, object]]:
        """``ask_id -> result`` for everything already answered.

        This is what a resumed run consults, and until it existed the journal was write-only: a
        second run restarted from `intake` and re-asked everything, overwriting the same files. The
        test named `test_what_was_already_answered_is_not_re_asked` checked that statuses had been
        *written*, not that anything was skipped — a test named for a behaviour nobody had built,
        which is how the gap survived four rounds of review until a verifier read the caller.

        Keyed by ask id rather than node id, because a node is asked more than once: the module loop
        revisits `engineer_build` per module, and the second visit is a different question wearing
        the same node's name.
        """
        return {e["ask_id"]: e["result"] for e in self.entries()
                if e.get("status") == "answered" and "result" in e}

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


#: What a returned report **is**. Before task 1 there was no way to tell: a gate halt set
#: ``halted_at``, and so did every TERMINAL node including ``done`` — so "stopped for a decision"
#: and "ran to the end" were the same shape, and an independent seat found that the one property
#: task 1 rests on did not exist.
FINISHED = "finished"    #: reached a terminal node; the flow ended where it was designed to
SUSPENDED = "suspended"  #: stopped at a gate, and a decision can continue it
STOPPED = "stopped"      #: stopped, and nothing continues it — a permanent halt, or an effect that failed
STATES = (FINISHED, SUSPENDED, STOPPED)


@dataclass
class Approval:
    """One approval of one gate, aimed at one stop.

    **This is the same ledger as ``confirmed``, not a second one beside it.** The question task 1
    was blocked on was whether a resumed gate decision spends the existing confirmation counter or
    opens a parallel mechanism, and the answer is the former: two overlapping approval ledgers with
    slightly different audit semantics is the one failure here that would be **silent** — a gate
    opening on an approval one ledger spent and the other never saw, with no way to reconstruct who
    approved what afterwards. So a decision is a confirmation that knows where it belongs.

    ``node_id`` and ``run_id`` are what make refusing a stale or misdirected answer possible.
    Leaving both out gives exactly today's behaviour: an untargeted confirmation, spendable at the
    first stop on that gate — which is what every existing caller passes and why they still work.
    """

    gate: str
    #: The node this answers for. ``None`` means "any stop on this gate", as ``--confirm`` has
    #: always meant.
    node_id: Optional[str] = None
    #: The run this answers for — see ``RunConfig.run_id``. ``None`` means "any run", which is the
    #: right default for an approval given up-front on the command line, and the wrong one for an
    #: answer typed into a console after a stop.
    run_id: Optional[str] = None

    def __str__(self) -> str:
        where = f" at {self.node_id}" if self.node_id else ""
        which = f" of run {self.run_id}" if self.run_id else ""
        return f"{self.gate}{where}{which}"


@dataclass
class Ruling:
    """A person's answer to a tie: **which branch**, at a node whose panel decided nothing.

    A separate thing from ``Approval``, deliberately, and the reason matters because task 1's answer
    was "one ledger, not two". The hazard there was two mechanisms answering the **same** question —
    an approval one ledger spends and the other never sees, so a gate opens untraceably. These
    answer *different* questions and cannot substitute for each other: an approval says *may this
    proceed past a gate*, a ruling says *which way*. A ruling can never open a gate and an approval
    can never pick a branch, so there is no spend either one could miss.

    It carries the same staleness checks for the same reason: an answer from a view of the run that
    has moved on must be refused rather than quietly applied.
    """

    node_id: str
    #: The branch the person chose. Must be one the node actually offers.
    branch: str
    run_id: Optional[str] = None

    def __str__(self) -> str:
        which = f" of run {self.run_id}" if self.run_id else ""
        return f"{self.node_id} → {self.branch}{which}"


@dataclass
class RunReport:
    visited: List[str] = field(default_factory=list)
    asks: List[Ask] = field(default_factory=list)
    #: ``finished`` / ``suspended`` / ``stopped`` — see ``STATES``. The distinction task 1 exists
    #: to create: a caller can tell a run that ended from one waiting for an answer.
    state: str = FINISHED
    #: When suspended: what is being waited for, and what would have to match to continue it.
    suspended: Optional[Dict[str, object]] = None
    halted_at: Optional[str] = None
    halt_reason: str = ""
    #: Recorded, not just honoured: every relaxation the run was granted.
    relaxations: List[str] = field(default_factory=list)
    #: What the policy said at each node, so a halt can be audited afterwards.
    verdicts: Dict[str, Dict[str, object]] = field(default_factory=dict)
    #: Operations nothing could check: declared ordinary with no targets named. The planner's word
    #: is the only thing behind them, and this is where that shows.
    on_trust: List[str] = field(default_factory=list)
    #: Gates the operator had already confirmed, recorded so an approval leaves a trace.
    confirmations: List[str] = field(default_factory=list)
    #: Every panel decision, with the seats' verdicts that produced it.
    adjudications: List[Dict[str, object]] = field(default_factory=list)
    #: Said out loud when every seat was answered by the same backend. Sessions are independent of
    #: each other's context either way; they are not independent of one model's blind spots, and
    #: that is most of what a panel is for.
    single_model_panels: List[str] = field(default_factory=list)
    #: What each node's effects did — applied, already met, and anything found true out of order.
    effects: Dict[str, Dict[str, object]] = field(default_factory=dict)
    #: Asks answered from the journal rather than by opening a session, on a resumed run.
    resumed: List[str] = field(default_factory=list)
    #: Ties a person broke, and which way. Kept apart from ``confirmations`` because they answer a
    #: different question — "which branch" rather than "may this pass a gate" — and merging them
    #: would make the audit trail say a gate was confirmed when nobody confirmed anything.
    rulings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "visited": list(self.visited),
            "asks": [{"node_id": a.node_id, "role": a.role, "seat": a.seat} for a in self.asks],
            "state": self.state,
            "suspended": dict(self.suspended) if self.suspended else None,
            "halted_at": self.halted_at,
            "halt_reason": self.halt_reason,
            "relaxations": list(self.relaxations),
            "verdicts": {k: dict(v) for k, v in self.verdicts.items()},
            "on_trust": list(self.on_trust),
            "confirmations": list(self.confirmations),
            "adjudications": [dict(a) for a in self.adjudications],
            "single_model_panels": list(self.single_model_panels),
            "effects": {k: dict(v) for k, v in self.effects.items()},
            "resumed": list(self.resumed),
            "rulings": list(self.rulings),
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
    #: What to do when this runner **could not verify** what a node does — it declares no
    #: operations, or it names targets nothing recognises. ``refuse`` is the
    #: default and the only safe one: a plan that simply omits `operations` used to be checked
    #: against nothing at all, so "run a deploy without stopping" was a matter of saying less rather
    #: than saying something false. ``allow`` exists for dry runs and records itself as a relaxation
    #: — never silently.
    undeclared: str = "refuse"
    #: Commands the operator vouches for as ordinary. Empty means only repo paths and read-only
    #: version control are recognised — safe, and it stops a lot, which is the honest default when
    #: nobody has said what this project's toolchain is.
    ordinary_commands: Sequence[str] = ()
    #: Continue an interrupted run: skip what the journal already answered, re-ask only what it
    #: does not have. Off by default — a run that silently continues somebody else's because a
    #: directory happened to exist is worse than one that starts over.
    resume: bool = False
    #: Gates a human has already confirmed. Without this a stopping verdict ends every run at the
    #: same place forever — an independent verifier found that medium and high risk could never get
    #: past the first gate, which made most of the matrix unreachable. A halt is a pause with a way
    #: back, not a wall.
    #:
    #: Entries may be a plain gate name — "any stop on this gate", which is what ``--confirm`` has
    #: always meant — or a ``Decision`` naming the node and run it answers for. Both spend from the
    #: same ledger; see ``Decision``.
    confirmed: Sequence[object] = ()
    #: A person's answers to ties — see ``Ruling``. Empty by default: a run with no rulings stops
    #: at the first undecided panel, which is the honest behaviour when nobody has been asked yet.
    rulings: Sequence["Ruling"] = ()
    max_steps: int = 200
    journal: Optional[AskJournal] = None

    @property
    def run_id(self) -> Optional[str]:
        """What identifies this run, and **who mints it**: the journal does.

        The second question task 1 was blocked on. The answer invents no new authority, because
        there is already exactly one durable identity here — the journal directory is what a
        resumed run reads, and a run without one cannot be resumed at all (``resume=True`` without
        a journal is already refused). So the run id *is* the journal's resolved path, and a run
        with no journal has no id and cannot be sent a targeted decision.

        Deriving it rather than generating one keeps the two facts from drifting: a minted id would
        need storing somewhere, and the only durable somewhere is the directory it would be stored
        beside.
        """
        if self.journal is None:
            return None
        return str(self.journal.dir.resolve())


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
         ask_id: Optional[str] = None, node_id: str = "",
         answered: Optional[Mapping[str, Mapping[str, object]]] = None):
    """Open a session, ask once, close it — the close guaranteed even if the ask raises.

    ``seen`` holds the session **objects**, not their ``id()``: an id is not an identity once the
    object is gone, and every ask drops its session. Tracking ids passed on 3.9 and 3.11 by
    allocation luck and failed on 3.13.

    ``answered`` is what a resumed run already knows. A hit returns it **without opening a session
    at all**, which is the point of writing the question down before asking it — and which the
    previous version did not do: it wrote the record, then re-asked everything anyway.
    """
    if answered and ask_id in answered:
        return answered[ask_id]
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


def _has_effects(node: graph.Node, cfg: "RunConfig") -> bool:
    """Does this node carry effects the engine will apply itself?"""
    return bool(cfg.effects is not None and cfg.effects(node.id))


def _does_work(node: graph.Node, cfg: "RunConfig") -> bool:
    """Could this node change the world? Then it owes a declaration.

    True when the node dispatches a role that may write or execute, or when it carries effects.

    The criterion is the **capability**, never the role's name. An earlier version exempted the
    review seats by name while `policy.role("seat").can_execute` was True and the work order handed
    that capability over — so the panel was dispatched with no declaration at all, on the reasoning
    that a reviewer only reads. A reviewer that may execute can do whatever executing can do, and a
    verifier found the exemption disagreeing with this function's own stated rule. Seats owe a
    declaration like anything else that can act.
    """
    if _has_effects(node, cfg):
        return True
    if not node.role:
        return False
    role = policy.role(node.role)
    return bool(role.can_write or role.can_execute)


#: Spec fields that name things rather than describe them — paths in, paths out, where the work
#: happens. These are read as **targets** as well as prose: a node whose expected output is
#: `prod/manifest.yaml` has said something about what it touches, and that is a fact rather than a
#: phrasing.
_TARGET_FIELDS = ("input_artifacts", "expected_outputs", "workdir")


def _spoken_halt(node: graph.Node, cfg: "RunConfig") -> Optional[str]:
    """A red line the node's **own brief** describes or names, or ``None``.

    **Every** field of the spec is read, not a chosen few. Choosing was the mistake, and it was the
    same mistake twice: the check first read only `operation["description"]` while the giveaway sat
    in `instructions`, and then read three fields while the giveaway could sit in `done_criteria` or
    `acceptance_predicate`. A list of places to look has exactly as many blind spots as the places
    it does not name, and each round of "add the field it hid in" buys one round.

    Two passes over the same brief, because the two questions are different:

    * the fields that **name things** — inputs, outputs, workdir — go through `policy.derive`, which
      reads targets as facts;
    * every field goes through `policy.permanent_halt`, the word-list backstop, which reads prose
      and is weak on purpose-and-record.

    There is deliberately no way past this except changing what the node is told to do — declaring
    it halts too, which is the right answer for a node whose brief says it will wipe a table. The
    cost is false stops, and it is named in the change record and pinned by a corpus of ordinary
    engineering briefs.
    """
    spec = cfg.node_specs.get(node.id) or {}

    targets = []
    for field_name in _TARGET_FIELDS:
        value = spec.get(field_name)
        if not value:
            continue
        targets.extend(value if isinstance(value, (list, tuple)) else [value])
    derived = policy.derive(targets)
    if derived:
        named = " and ".join(policy.PERMANENT_HALT_KINDS[k] for k in derived)
        return (
            f"permanent halt at {node.id!r}: the paths it names are {named} — {targets}. "
            f"No risk grade, confirmation or mode relaxes this — a person does it.")

    for field_name in sorted(spec):
        value = spec.get(field_name)
        if not value:
            continue
        text = " ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)
        halt = policy.permanent_halt(text)
        if halt is not None:
            return (
                f"permanent halt at {node.id!r}: its {field_name} describes {halt} — "
                f"{text.strip()[:120]!r}. If that is what this node does, it is not automated at "
                f"any risk grade and a person carries it out. If it is not, the brief has to say "
                f"so, because this runner reads it.")
    return None


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
    # Read first, and unconditionally. Placed after the undeclared check, this never ran on the
    # path that matters: `allow` returns early, and `allow` is exactly the setting somebody uses
    # when they have not declared anything — which is when the brief is the only evidence there is.
    described = _spoken_halt(node, cfg)
    if described is not None:
        return described

    declared = cfg.operations.get(node.id)
    if not declared and _does_work(node, cfg):
        # `allow` never covers a node that carries effects. It is documented as "for a dry run",
        # and a dry run changes nothing — but an independent verifier built a run with `allow` set
        # and a real effect attached, and watched the effect apply with nothing checked against the
        # permanent halts. A relaxation that waves through the one case it was never meant to cover
        # is worse than no relaxation, because its name says otherwise.
        if cfg.undeclared != "allow" or _has_effects(node, cfg):
            covered = " `allow` does not cover it: this node applies effects, and a run that " \
                      "changes the world is not a dry run." if _has_effects(node, cfg) else \
                      " Or pass undeclared='allow' for a dry run, which is recorded."
            return (
                f"{node.id!r} does work that could change the world and declares no operations. "
                f"Say what it will do — each as {{'description': ..., 'kind': ...}}."
                f"{covered} Silence is not a declaration that nothing risky happens.")
        report.relaxations.append(f"{node.id} ran undeclared: nothing was checked against the "
                                  f"permanent halts")
        return None

    for operation in declared or ():
        halt = policy.classify(operation)

        # A target this runner cannot place is not evidence of anything, and it is certainly not
        # evidence of safety. It falls under the same setting as a node that declared nothing,
        # because it is the same fact about the world: *we could not verify what this does.*
        unknown = policy.unverified(operation, cfg.ordinary_commands)
        if halt is None and unknown and cfg.undeclared != "allow":
            return (
                f"{node.id!r} names target(s) this runner does not recognise: {list(unknown)}. "
                f"They are declared ordinary, and nothing confirmed that — a red-line list finding "
                f"nothing has said nothing. Vouch for the command in settings "
                f"(`ordinary_commands`), declare the operation's real kind, or pass "
                f"undeclared='allow' to proceed on the plan's word, which is recorded.")

        if halt is None and policy.on_trust(operation, cfg.ordinary_commands):
            # Nothing about this was checked except its own prose: it declares `ordinary` and names
            # no targets. Not blocked — forcing every operation to name one buys ceremony, since an
            # empty list is as forgeable as a wrong `kind`. What is unacceptable is the trust being
            # invisible, so it goes in the report where an auditor reads it.
            why = (f"no targets named" if not operation.get("targets")
                   else f"target(s) not recognised: "
                        f"{list(policy.unverified(operation, cfg.ordinary_commands))}")
            report.on_trust.append(
                f"{node.id}: {operation.get('description', '')!r} was taken on the plan's word — "
                f"declared ordinary, {why}, nothing verified")
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


def _note_panel_diversity(node: graph.Node, report: "RunReport", opened_for_panel: List[object]
                          ) -> None:
    """Record whether the seats were actually answered by different things.

    Asks each session what it is — `describe()` if it offers one, else its class. Identical
    descriptions across every seat means one backend answered the whole panel: independent sessions,
    one set of blind spots. Not refused; **stated**, because a report that reads like a cross-model
    panel while one model answered it is the assurance this design is against.
    """
    if len(opened_for_panel) < 2:
        return
    kinds = set()
    for session in opened_for_panel:
        describe = getattr(session, "describe", None)
        kinds.add(describe() if callable(describe) else type(session).__name__)
    if len(kinds) == 1:
        report.single_model_panels.append(
            f"{node.id}: every seat was answered by the same backend ({kinds.pop()}). The sessions "
            f"were independent; the model was not, so the seats share whatever it cannot see. Use "
            f"--seat-model SEAT=COMMAND to make the review cross-model.")


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
    reached = str(outcome["outcome"])
    if reached not in policy.OUTCOMES:
        raise EngineError(
            f"{node.id!r} adjudicated to {reached!r}, which is not an outcome this engine knows how "
            f"to route. An unrecognised outcome is not a failure and must not be treated as one.")
    return reached


def _finish(report: "RunReport", confirmations: Dict[str, int]) -> "RunReport":
    """Close out a walk, however it ended.

    A confirmation the run never spent is **not** an error: a run can legitimately finish without
    reaching a gate it was prepared for. But dropping it silently leaves the operator believing an
    approval was used, and it matters most for the gate they thought hardest about.

    Every exit from `walk` goes through here. The first version put this after the loop, where four
    of the five ways a walk can end — halt, terminal, permanent halt, effect failure — jumped
    straight past it. A report that is only correct when the run succeeds is not a report.
    """
    unspent = {gate: n for gate, n in confirmations.items() if n > 0}
    report.confirmations.extend(
        f"{gate} was confirmed {n} more time(s) than the run stopped at it"
        for gate, n in sorted(unspent.items()))

    # Every exit passes through here, so this is the one place that can promise the caller a report
    # says what it is. A state outside the closed set would leave "is this waiting for me?"
    # unanswerable, which is the question task 1 exists to make answerable.
    if report.state not in STATES:
        raise EngineError(
            f"a run ended in state {report.state!r}, which is not one of {list(STATES)} — a report "
            f"that cannot say whether it is waiting for a decision is the ambiguity this state "
            f"exists to remove")
    if (report.state == SUSPENDED) != (report.suspended is not None):
        raise EngineError(
            f"a {report.state!r} report {'carries' if report.suspended else 'lacks'} suspension "
            f"details — the two must agree, or a caller reading one and not the other gets a "
            f"different answer about whether the run can continue")
    return report


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
    # What a previous run already answered. `resume=False` (the default) ignores it, so an ordinary
    # run is never silently continuing somebody else's — resuming is a decision, not a side effect
    # of a journal directory happening to exist.
    already: Dict[str, Mapping[str, object]] = {}
    if cfg.resume:
        if cfg.journal is None:
            raise EngineError(
                "resume=True needs a journal to resume from. Pass --ask-journal at the directory "
                "the interrupted run wrote to; without it there is nothing to read and continuing "
                "would silently re-ask everything.")
        already = cfg.journal.answers()

    # One ledger. Untargeted entries stay a per-gate count, exactly as before; targeted ones are
    # held alongside and spent first, so a decision aimed at the stop it answers is preferred over
    # a blanket approval that happens to fit.
    targeted: List[Approval] = []
    confirmations: Dict[str, int] = {}
    for entry in cfg.confirmed:
        if isinstance(entry, Approval):
            if entry.gate not in policy.GATES:
                raise EngineError(
                    f"approval for gate {entry.gate!r} does not exist. This runner's gates are "
                    f"{sorted(policy.GATES)}.")
            if entry.node_id is not None and entry.node_id not in graph.BY_ID:
                raise EngineError(
                    f"approval {entry} names node {entry.node_id!r}, which is not in the flow — an "
                    f"answer aimed at a node nobody has cannot be spent anywhere, and holding it "
                    f"would leave you believing a gate was confirmed")
            if entry.run_id is not None and entry.run_id != cfg.run_id:
                # Stale tab, or an answer to a different run. Refusing loudly is the whole reason
                # the decision carries a run id: silently spending it would open a gate on an
                # approval given for something else.
                raise EngineError(
                    f"approval {entry} is for another run — this run is "
                    f"{cfg.run_id or 'un-identified (no journal)'}. An answer from a stale view "
                    f"must not open a gate here.")
            targeted.append(entry)
            continue
        gate = entry
        if gate not in policy.GATES:
            # Silently ignoring it is the worst option available: the operator believes they
            # confirmed something, the run stops anyway, and nothing says why. A verifier found
            # `--confirm no_such_gate` swallowed whole, against this repo's own no-silent-fallback
            # rule — the exact shape KN-9 is about.
            raise EngineError(
                f"confirmed gate {gate!r} does not exist. This runner's gates are "
                f"{sorted(policy.GATES)} — a confirmation for a gate nobody defined confirms "
                f"nothing, and passing it silently would leave you believing otherwise.")
        confirmations[gate] = confirmations.get(gate, 0) + 1

    # Same up-front checks as approvals, and for the same reason: an answer that cannot be applied
    # anywhere must say so now, not be held and silently never spent.
    unspent_rulings: List[Ruling] = []
    for ruling in cfg.rulings:
        if ruling.node_id not in graph.BY_ID:
            raise EngineError(
                f"ruling {ruling} names a node that is not in the flow — a branch chosen at a node "
                f"nobody has cannot be taken anywhere")
        offered = graph.BY_ID[ruling.node_id].branches
        if ruling.branch not in offered:
            raise EngineError(
                f"ruling {ruling} chooses a branch {ruling.node_id!r} does not offer; it offers "
                f"{sorted(offered)}. A branch nobody wrote down is not a decision this run can take")
        if ruling.run_id is not None and ruling.run_id != cfg.run_id:
            raise EngineError(
                f"ruling {ruling} is for another run — this run is "
                f"{cfg.run_id or 'un-identified (no journal)'}. A tie broken in a stale view must "
                f"not route this one.")
        unspent_rulings.append(ruling)

    node_id: Optional[str] = "intake"
    for _ in range(cfg.max_steps):
        if node_id is None:
            break
        node = graph.BY_ID[node_id]
        report.visited.append(node.id)

        tripped = _permanent_halt(node, cfg, report)
        if tripped is not None:
            # STOPPED, never SUSPENDED: a permanent halt is the one stop no decision continues, and
            # a caller that could not tell it from a gate would offer somebody a button that does
            # nothing -- or worse, appear to accept an approval for something unapprovable.
            report.state = STOPPED
            report.halted_at = node.id
            report.halt_reason = tripped
            return _finish(report, confirmations)

        verdict = resolve_verdict(node, cfg.risk, cfg.autonomy)
        report.verdicts[node.id] = dict(verdict)

        def _gate(phase: str):
            """Stop here if the policy says so and nobody has confirmed it yet.

            A gate the operator has already confirmed is **recorded** rather than silently skipped:
            an approval that leaves no trace is one nobody can audit afterwards.
            """
            if node.gate_when != phase or not policy.stops(str(verdict["verdict"])):
                return None

            # A decision naming this node is spent first: it is the more specific answer, and
            # preferring the blanket one would let a targeted approval survive its own stop and open
            # some later gate nobody meant it for.
            for i, approval in enumerate(targeted):
                if approval.gate != node.gate:
                    continue
                if approval.node_id is not None and approval.node_id != node.id:
                    continue
                targeted.pop(i)
                report.confirmations.append(
                    f"{node.gate} = {verdict['verdict']} at risk {verdict['risk']} at {node.id}, "
                    f"decided by the operator ({approval})")
                return None

            if confirmations.get(node.gate, 0) > 0:
                confirmations[node.gate] -= 1
                report.confirmations.append(
                    f"{node.gate} = {verdict['verdict']} at risk {verdict['risk']} at {node.id}, "
                    f"confirmed by the operator")
                return None

            # Suspended, not finished. The stop is still a *return* -- no waiting happens inside the
            # walk, so "alive and stopped" never exists and cannot be mistaken for "alive and
            # continuing". What is new is that the report says which of the two it is, and carries
            # what an answer would have to match.
            report.state = SUSPENDED
            report.suspended = {
                "node_id": node.id,
                # Both kinds of suspension carry the same keys, so a caller never has to know which
                # shape it is holding before it can read one. A gate has no branches to choose
                # between and a tie has no gate to confirm, and each says so rather than omitting
                # the field -- a missing key and a false one read the same way only until they do
                # not.
                "undecided": False,
                "gate": node.gate,
                "gate_when": node.gate_when,
                "verdict": verdict["verdict"],
                "risk": verdict["risk"],
                "branches": [],
                "run_id": cfg.run_id,
            }
            report.halted_at = node.id
            report.halt_reason = (
                f"{verdict['gate']} = {verdict['verdict']} at risk {verdict['risk']} "
                f"(per {verdict['source']}) — confirm it to continue")
            return _finish(report, confirmations)

        stop = _gate("before")
        if stop is not None:
            return _finish(stop, confirmations)

        answers: List[Mapping[str, object]] = []
        if node.role:
            if node.mode == graph.SEAT_PANEL:
                panel_sessions: List[object] = []
                before = len(opened)
                for seat in policy.seat_names(seats):
                    result = _ask(
                        factory, _order_for(node, cfg, verdict, seat), opened, seat=seat,
                        journal=cfg.journal, ask_id=f"{len(report.asks):03d}-{node.id}-{seat}",
                        node_id=node.id, answered=already)
                    ask_key = f"{len(report.asks):03d}-{node.id}-{seat}"
                    if ask_key in already:
                        report.resumed.append(ask_key)
                    report.asks.append(Ask(node.id, node.role, seat, result))
                    answers.append(result)
                panel_sessions = opened[before:]
                _note_panel_diversity(node, report, panel_sessions)
            else:
                result = _ask(
                    factory, _order_for(node, cfg, verdict), opened, journal=cfg.journal,
                    ask_id=f"{len(report.asks):03d}-{node.id}", node_id=node.id,
                    answered=already)
                if f"{len(report.asks):03d}-{node.id}" in already:
                    report.resumed.append(f"{len(report.asks):03d}-{node.id}")
                report.asks.append(Ask(node.id, node.role, None, result))
                answers.append(result)

        stop = _gate("after")
        if stop is not None:
            return _finish(stop, confirmations)

        stop = _run_effects(node, cfg, report)
        if stop is not None:
            return _finish(stop, confirmations)

        if node.kind == graph.TERMINAL:
            report.state = FINISHED
            report.halted_at = node.id
            report.halt_reason = node.note or node.label
            return _finish(report, confirmations)

        if node.branches:
            if node.mode == graph.SEAT_PANEL:
                choice = _adjudicate(node, report, seats)
            elif node.answer_decides:
                choice = _answered_branch(node, answers)
            else:
                choice = _choose(cfg, node, taken)
            if choice == policy.UNDECIDED:
                last = report.adjudications[-1] if report.adjudications else {}
                ruled = next((r for r in unspent_rulings if r.node_id == node.id), None)
                if ruled is not None:
                    # A person decided. It is recorded as *theirs* — the panel is not credited with
                    # a verdict it never reached, which is the whole distinction `undecided` exists
                    # to draw.
                    unspent_rulings.remove(ruled)
                    report.rulings.append(
                        f"{node.id} was undecided ({last.get('reason', 'the panel was split')}) "
                        f"and a person chose {ruled.branch!r}")
                    choice = ruled.branch
                else:
                    # Nobody decided, so the runner does not decide either -- it suspends and says
                    # what an answer would have to look like. Not `stopped`: a person CAN continue
                    # this, and reporting it as unresumable would hide a live decision from the one
                    # party entitled to make it.
                    report.state = SUSPENDED
                    report.suspended = {
                        "node_id": node.id,
                        "undecided": True,
                        "gate": None,
                        "gate_when": None,
                        "verdict": policy.UNDECIDED,
                        "risk": cfg.risk,
                        "branches": sorted(node.branches),
                        "reason": last.get("reason", "the panel was split"),
                        "verdicts": dict(last.get("verdicts") or {}),
                        "run_id": cfg.run_id,
                    }
                    report.halted_at = node.id
                    report.halt_reason = (
                        f"{node.id} reached no decision — "
                        f"{last.get('reason', 'the panel was split')}. The runner will not pick a "
                        f"side; choose {' or '.join(sorted(node.branches))}")
                    return _finish(report, confirmations)
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

    return _finish(report, confirmations)
