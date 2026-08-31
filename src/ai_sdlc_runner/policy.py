"""policy.py — this runner's own governance: roles, capabilities, gates, seats.

CHG-20260823-01 task 1. Until now every value here was read out of a vendored skill and the runner
was forbidden to hold any of it (`ai-guideline` §8, "read, don't re-implement"). That constraint
assumed a skill to read. There is none: **the flowchart is a design input, not a runtime
dependency**, and this module is the governance it describes, implemented here.

Two consequences worth stating, because they are the difference between this being a port and being
a re-implementation:

* **Correctness is judged against the requirement, not against a file.** There is no shipped table to
  diff against, so "matches the skill" is not available as an argument and was not used as one. What
  each value has instead is a reason, written next to it.
* **Completeness is structural.** The old design inherited a role table covering four of thirteen
  roles, which is why nine of them could not be dispatched at all. Here the roles *are* the ones the
  flow uses, so every role a node names has capabilities by construction — and a test asserts it
  rather than trusting the arithmetic.

## The roles, and why these

Straight from the requirement's own description of the flow: the user issues the instruction, PM
confirms the plan, the lead confirms feasibility and risk and dispatches, engineers build one small
module each and verify their own work, the lead reviews, QA tests and verifies the whole thing, and
user feedback returns to PM. Review seats sit alongside as the cross-checking mechanism.

The capability flags stay the three abstract ones — `can_spawn`, `can_write`, `can_execute` — because
they are what a work order can carry without naming any harness's tools.

## The gates

Same shape as the flow needs: risk × gate → `auto` / `confirm` / `halt` / `halt_independent`.
`confirm` and above stop the run; nothing continues on anything but `auto`, which is why no ordering
between the stopping values is needed.

The grades follow one rule, applied consistently: **a gate stops when getting it wrong is expensive
to undo.** Merging is a one-way door, so it stops earlier than a task review does. Acceptance on a
high-risk change wants someone other than the builder, so it is `halt_independent`. A task review is
cheap to redo and never stops.
"""
from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

AUTO = "auto"
CONFIRM = "confirm"
HALT = "halt"
HALT_INDEPENDENT = "halt_independent"

#: Anything that is not `auto` stops the run. Stated once, so no caller has to rank the others.
STOPPING = (CONFIRM, HALT, HALT_INDEPENDENT)

RISKS = ("low", "medium", "high")


class PolicyError(Exception):
    """Raised when something is asked of the policy that it does not define. Never defaulted."""


@dataclass(frozen=True)
class Role:
    """One role in the flow, with the three capabilities a work order may carry.

    ``can_spawn`` is the one that carries real weight: the lead is the only role that dispatches, so
    an engineer cannot start further work of its own, and a reviewer cannot quietly become a builder.
    """

    name: str
    label: str
    can_spawn: bool
    can_write: bool
    can_execute: bool
    note: str = ""


ROLES: Tuple[Role, ...] = (
    Role("pm", "PM", can_spawn=True, can_write=True, can_execute=False,
         note="turns the user's instruction into a plan and confirms it; writes the plan, not the "
              "code. **Dispatches since CHG-20260827-22**: a programme with several workstreams is "
              "planned at two levels, and the PM is who opens the second. Before that this flag was "
              "`False` and the file said the tree stays two deep — see `MAX_DISPATCH_DEPTH` for the "
              "bound that replaced it"),
    Role("lead", "主管 / lead agent", can_spawn=True, can_write=True, can_execute=True,
         note="confirms feasibility and risk, dispatches the engineers, reviews what they produce — "
              "the only role that dispatches"),
    Role("engineer", "工程師 / sub-agent", can_spawn=False, can_write=True, can_execute=True,
         note="builds one small module and verifies its own work; cannot dispatch further. That "
              "used to make the tree two deep on its own; since CHG-20260827-22 the PM dispatches "
              "too, so the bound is three and it is `MAX_DISPATCH_DEPTH` that holds it"),
    Role("qa", "QA", can_spawn=False, can_write=False, can_execute=True,
         note="tests and verifies the whole change for real; deliberately cannot write, so it "
              "cannot fix while verifying"),
    Role("seat", "審議席 / review seat", can_spawn=False, can_write=False, can_execute=True,
         note="one review seat; several of them cross-check each other, which is the whole reason "
              "they exist"),
)

#: A role that plans one workstream (CHG-20260827-22). `can_spawn=False` is the bound: the PM
#: opens this tier and this tier opens nothing, so the tree is three deep and not four.
#:
#: `can_write=True` because a plan is a written thing; `can_execute=False` because planning is not
#: building, and a planner that could run commands would be an engineer with a different name.
PLANNER = Role("planner", "分項規劃 / workstream planner", can_spawn=False, can_write=True,
               can_execute=False,
               note="plans one workstream. Dispatched by the PM and dispatches nothing itself, "
                    "which is what bounds the tree at three")

ROLES = ROLES + (PLANNER,)

BY_ROLE: Dict[str, Role] = {r.name: r for r in ROLES}

#: How deep the dispatch tree may go, counting the operator's run as depth 0.
#:
#: **Two**, and CHG-20260827-22 did not change it. The chains are `pm → planner` and
#: `lead → engineer`; they are siblings, not nested, because `reconcile` returns to the runner's
#: main line rather than letting a planner open the build. Adding a second spawner widened the tree,
#: not its depth.
#:
#: The number is here, and `check_dispatch_depth` derives the real depth from the graph and refuses
#: to exceed it, because the sentence this replaces — engineer's *"cannot dispatch further, so the
#: tree stays two deep"* — was a property of the role table **by construction**. Once a second role
#: could spawn, that sentence stayed true while its reason stopped being. A bound that nothing
#: computes is the same defect one release later.
MAX_DISPATCH_DEPTH = 2


def dispatch_depth(edges: Mapping[str, Sequence[str]], direct: Sequence[str]) -> int:
    """The longest chain of dispatches, counting a role the runner asks itself as depth 1.

    `edges` is `{spawner: [roles it dispatches]}` and `direct` the roles the runner asks. Both come
    from the graph; this function knows nothing about which nodes exist, so it cannot drift from
    them the way a hand-written list can.
    """
    reachable = {role: list(edges.get(role, ())) for role in set(edges) | set(direct)}

    def longest(role: str, seen: FrozenSet[str]) -> int:
        if role in seen:  # a cycle is unbounded depth, and the caller must hear about it, not hang
            raise PolicyError(
                f"the dispatch tree loops: {role!r} is reachable from itself. A role that can "
                f"reach its own dispatcher has no depth, and no bound can hold it.")
        below = reachable.get(role, ())
        return 1 + max((longest(r, seen | {role}) for r in below), default=0)

    return max((longest(r, frozenset()) for r in direct), default=0)


def check_dispatch_depth(edges: Mapping[str, Sequence[str]],
                         direct: Sequence[str]) -> int:
    """Refuse a flow that dispatches deeper than `MAX_DISPATCH_DEPTH`, naming the chain.

    Called on every run rather than only in a test: a test says the shipped graph is within the
    bound, and this says *this* run is — including one whose graph a caller has altered in memory.
    """
    depth = dispatch_depth(edges, direct)
    if depth > MAX_DISPATCH_DEPTH:
        chains = "; ".join(f"{k} dispatches {', '.join(v)}" for k, v in sorted(edges.items()))
        raise PolicyError(
            f"the dispatch tree is {depth} deep and the bound is {MAX_DISPATCH_DEPTH} "
            f"({chains}). Each tier is one more layer between the operator and the work, and one "
            f"more place a decision is made by something nobody asked for. Raise "
            f"MAX_DISPATCH_DEPTH deliberately, or do not add the tier.")
    return depth

#: The gates, and what each risk grade does at them. The rule behind the grades: a gate stops when
#: getting it wrong is expensive to undo.
GATES: Dict[str, Dict[str, str]] = {
    # The plan itself. Wrong plans are cheap to fix now and expensive to fix later.
    "plan_confirmed":        {"low": AUTO, "medium": CONFIRM, "high": HALT},
    # Feasibility and risk, judged by the lead before anyone is dispatched.
    "feasibility_confirmed": {"low": AUTO, "medium": CONFIRM, "high": HALT},
    # The last point before work starts. On a high-risk change a human sees it.
    "before_dispatch":       {"low": AUTO, "medium": CONFIRM, "high": HALT},
    # The engineer checking its own work. Never stops: catching nothing here costs one review.
    "self_verify":           {"low": AUTO, "medium": AUTO, "high": AUTO},
    # The lead reviewing one module. Cheap to redo, so it never stops the run either.
    "task_review":           {"low": AUTO, "medium": AUTO, "high": AUTO},
    # The whole change, reviewed by seats that cross-check. High risk wants eyes on it.
    "lead_review":           {"low": AUTO, "medium": AUTO, "high": HALT},
    # QA running it for real. Same.
    "qa_verify":             {"low": AUTO, "medium": AUTO, "high": HALT},
    # Acceptance. On a high-risk change the verifier must not be the builder.
    "acceptance":            {"low": AUTO, "medium": AUTO, "high": HALT_INDEPENDENT},
    # Opening a PR is reversible and closing one costs nothing, so low and medium proceed. High
    # asks: a high-risk change becoming visible to reviewers and to CI is the last cheap moment to
    # say "not like this". Graded auto everywhere, this gate could never fire and its phase was
    # unobservable — a verifier called that out, and a gate that cannot fire is decoration.
    "pr":                    {"low": AUTO, "medium": AUTO, "high": CONFIRM},
    # Merging is a one-way door, so it stops earliest of anything here — including at low risk,
    # where it asks rather than halts. "Low risk" grades the change, not the door.
    "merge":                 {"low": CONFIRM, "medium": HALT, "high": HALT},
}

@dataclass(frozen=True)
class ChangeClass:
    """One of the three ways a change can be governed (CHG-20260827-20).

    The split is ITIL's, and it is the column this table never had: today every change is `normal`,
    so `merge = confirm` at every grade means **every** change needs a person. At a mid-to-large
    scale that is not a strict policy, it is a policy that gets bypassed — the failure this
    repository already documented once about the red-line word list.
    """

    name: str
    #: May instances of this class stop **less** often than the grade says? Only `standard` and
    #: `emergency` may, and only ever `confirm` → `auto` — see `relax` for why never a halt.
    relaxes: bool
    #: Is the run reviewed **after** rather than before? True only for `emergency`, and it is what
    #: makes emergency different from standard rather than just louder.
    reviewed_after: bool
    note: str


#: The three classes, and the one that is not new: `normal` is what every change is today, so a
#: runner with nothing declared behaves exactly as it did.
CLASSES: Tuple[ChangeClass, ...] = (
    ChangeClass("standard", relaxes=True, reviewed_after=False,
                note="the TYPE was assessed once by a person and pre-authorised, so individual "
                     "instances do not stop. What is recorded is a person's judgement about a "
                     "type — made once, written down, and revocable — never a model's judgement "
                     "about an instance"),
    ChangeClass("normal", relaxes=False, reviewed_after=False,
                note="full approval: what every change is today, and what every change stays "
                     "unless somebody declares otherwise"),
    ChangeClass("emergency", relaxes=True, reviewed_after=True,
                note="proceeds, and is reviewed afterwards. Nothing may mark itself emergency — an "
                     "answer that could would be a model granting itself an exemption"),
)

BY_CLASS: Dict[str, ChangeClass] = {c.name: c for c in CLASSES}

#: The class in force when nobody has declared one. Named rather than written `"normal"` at each
#: use, because "what happens when nothing is declared" is the property this whole change must not
#: get wrong.
DEFAULT_CLASS = "normal"


def relax(graded: str, klass: Optional[str]) -> Tuple[str, str]:
    """The verdict a class leaves in place, and why — `confirm` may become `auto`, a halt never.

    **`confirm` → `auto`, and nothing else.** `confirm` means *a person is asked and may say yes*,
    and pre-authorising a type is exactly saying yes in advance about every instance of it. `halt`
    and `halt_independent` say something stronger: stop, and route this to somebody. A
    pre-authorisation is a person's *approval*; it is not a person's *attention*, and dissolving a
    halt would silently trade the second for the first.

    So the strongest thing a class can do is skip a question somebody already answered. It can never
    skip a stop that exists to put the change in front of someone who has not seen it.
    """
    if not klass or klass == DEFAULT_CLASS:
        return graded, ""
    named = BY_CLASS.get(klass)
    if named is None:
        raise PolicyError(
            f"no change class {klass!r}; this runner defines {sorted(BY_CLASS)}")
    if not named.relaxes or graded != CONFIRM:
        if named.relaxes and graded in STOPPING:
            return graded, (f"; the {klass!r} class does not relax {graded!r} — a class "
                            f"pre-authorises, and a halt is not a question")
        return graded, ""
    return AUTO, (f"; relaxed from {CONFIRM} by the {klass!r} class, which a person declared")


def combined_class(names: Sequence[str]) -> str:
    """What a change-level gate reads when a programme has several workstreams
    (CHG-20260828-07).

    `merge`, `pr` and `close_out` belong to no workstream, so they need one answer over all of
    them. This is the analogue of `strictest` for risk, and it leans the same way:

    * **any workstream without an in-force class → `normal`.** A part nobody pre-authorised means
      the change as a whole is not pre-authorised. Reading the loosest would let a `standard` copy
      tweak carry an unassessed schema change through the door they both pass.
    * **any `emergency` → `emergency`.** Both relaxing classes turn `confirm` into `auto`
      identically, so the gate is the same either way — but `emergency` carries the obligation to
      review afterwards, and a programme containing one has that obligation. Reporting it as
      `standard` would drop the half that is not about gates.
    * otherwise `standard`.

    Empty means nothing was declared, which is `normal` — the same answer as declaring nothing.
    """
    seen = [n if n in BY_CLASS else DEFAULT_CLASS for n in names]
    if not seen or any(n == DEFAULT_CLASS for n in seen):
        return DEFAULT_CLASS
    return "emergency" if "emergency" in seen else "standard"


def class_in_force(declared: Optional[Mapping[str, object]], today: str) -> Tuple[str, str]:
    """The class that actually applies now, and why — an unreviewed one expires to `normal`.

    Task 4 of the record: *"A class carries a review date. An unreviewed class expires back to
    `normal` rather than persisting on nobody's authority."* Expiry is the floor under the drift,
    and the record says plainly it is not a fix for it: a class renewed without thought is a rubber
    stamp with a calendar.

    Dates are compared as ISO strings, which sorts correctly and needs no timezone argument about a
    review deadline that is a day rather than an instant.
    """
    if not declared:
        return DEFAULT_CLASS, "nothing was declared"
    name = str(declared.get("class") or "")
    if name not in BY_CLASS:
        raise PolicyError(
            f"no change class {name!r}; this runner defines {sorted(BY_CLASS)}")
    who = str(declared.get("authorised_by") or "").strip()
    if not who:
        raise PolicyError(
            "a change class must name who authorised it. A pre-authorisation nobody signed is a "
            "relaxation on nobody's authority, which is the thing this class exists to avoid.")
    review_by = str(declared.get("review_by") or "").strip()
    if not review_by:
        raise PolicyError(
            "a change class must carry a review date. Without one it never expires, and a class "
            "that never expires outlives the assessment it was granted for.")
    if review_by < today:
        return DEFAULT_CLASS, (
            f"the {name!r} class was authorised by {who} and was due for review on {review_by}; "
            f"today is {today}, so it has expired back to {DEFAULT_CLASS!r}")
    return name, f"the {name!r} class, authorised by {who}, due for review on {review_by}"


#: Never automated, at any risk grade, and no configuration relaxes them. These are the actions whose
#: worst case is not "redo the work" but "the work cannot be undone".
#:
#: Keyed by the **kind** a plan declares, valued by the description a person reads. The kind is what
#: is checked; the description is what a halt reason quotes, so the stop names the rule rather than
#: whatever happened to match.
PERMANENT_HALT_KINDS: Dict[str, str] = {
    "deploy":     "production deploy or release",
    "migration":  "data migration or irreversible schema change",
    "delete":     "deleting data, dropping a table, any hard delete",
    "money":      "moving money",
    "access":     "changing secrets, credentials, access control or permissions",
    "publish":    "publishing public content",
}

@dataclass(frozen=True)
class Recipient:
    """A function that owns one of the permanent halts (CHG-20260827-19).

    **Not a `Role`.** A role is dispatched a work order and carries the three capabilities that
    describe what that order may do; a recipient is *told* something stopped and decides whether it
    proceeds. Nothing here is ever handed a module, so `can_write` and the rest would be three
    `False`s pretending to be a description — and `test_policy.py` refuses a role no node names,
    correctly, which is how the first draft of this change was caught putting them in `ROLES`.
    """

    name: str
    label: str
    note: str = ""


#: The functions the six permanent halts imply. In a small team these are all one person, which is
#: exactly what the runner assumed until now; at the scale being targeted they are five different
#: people, and a `deploy` halt that reaches whoever happened to start the run reaches the wrong desk.
RECIPIENTS: Tuple[Recipient, ...] = (
    Recipient("release", "發布負責人 / release owner",
              note="production deploys and releases"),
    Recipient("data", "資料負責人 / data owner",
              note="the database: migrations and hard deletes, both irreversible against data "
                   "somebody else answers for"),
    Recipient("finance", "財務 / finance",
              note="moving money — the one kind whose worst case is not technical"),
    Recipient("security", "資安 / security",
              note="secrets, credentials, access control"),
    Recipient("comms", "對外溝通 / communications",
              note="public content — the only kind whose damage lands outside the system"),
)

BY_RECIPIENT: Dict[str, Recipient] = {r.name: r for r in RECIPIENTS}

#: What a halt reaches when nothing else claims it. Deliberately **not** in `RECIPIENTS`: the
#: operator is the person running this, not a function inside the organisation, and keeping it out
#: means editing the roster can never delete the fallback.
DEFAULT_RECIPIENT = "operator"

#: Who is told first when a permanent halt fires. Data, beside `GATES`, and read the same way.
#:
#: ## Routing narrows who is told FIRST. It never narrows who is told.
#:
#: A routing table is a new way for a halt to go missing, and that is the whole risk in this change.
#: So: `routed_to` never raises, a kind absent from this table is not an error, and `recipients`
#: puts the operator on every halt whether or not a specialist is named.
#:
#: `migration` and `delete` share `data` on purpose. Both are irreversible against data somebody
#: else answers for, and separating them would imply the difference matters to who decides. It does
#: not.
HALT_ROUTING: Dict[str, str] = {
    "deploy":    "release",
    "migration": "data",
    "delete":    "data",
    "money":     "finance",
    "access":    "security",
    "publish":   "comms",
}


def recipient_label(name: str) -> str:
    """A recipient as a person would read it: the roster's label if it is one of ours, else as given.

    An organisation names its own functions — `sre-oncall`, `dba`, whatever the rota is called — and
    a routing table that only accepted `RECIPIENTS` would be a table nobody could use. So an unknown
    name is not an error here; it is simply printed as typed. `RECIPIENTS` supplies a label for the
    five this runner ships an opinion about, and nothing more.
    """
    known = BY_RECIPIENT.get(name)
    return known.label if known else name


def routed_to(kind: str, routing: Optional[Mapping[str, str]] = None) -> Tuple[str, str]:
    """Who is told first about a halt of this kind, and where that answer came from.

    Returns ``(recipient, source)`` with `source` one of ``"project"``, ``"policy"`` or
    ``"default"``, because *"who decided this"* is the question an operator asks second, straight
    after *"who is it for"*.

    A project's own table wins. `None`, an empty mapping, a mapping without this kind, and a blank
    value all fall through to the same place — as does a kind nobody has ever heard of. **No path
    here raises:** a routing table that can refuse is a routing table that can swallow a halt.
    """
    if routing:
        named = str(routing.get(kind) or "").strip()
        if named:
            return named, "project"
    if kind in HALT_ROUTING:
        return HALT_ROUTING[kind], "policy"
    return DEFAULT_RECIPIENT, "default"


def check_routing(routing: Mapping[str, str]) -> None:
    """Refuse a routing table that names a **kind** this runner does not have. Configuration time.

    The asymmetry is deliberate and it is the whole design:

    * A wrong **kind** is refused here, loudly, when somebody types it. `{"deploy ": "release"}` or
      `{"deploys": "release"}` would otherwise sit in the store looking configured and route
      nothing, for ever, silently — the operator believing the `deploy` halt goes to release when
      it never will.
    * A wrong **recipient** is not refused, here or anywhere. Organisations name their own
      functions, and a table that only accepted this module's five would be one nobody could use.
      A name nobody recognises still reaches somebody, because the operator is on every halt.

    So: fail early on the half that can silently do nothing, and never fail on the half that cannot.
    """
    unknown = sorted(k for k in routing if k not in PERMANENT_HALT_KINDS)
    if unknown:
        raise PolicyError(
            f"halt routing names kind(s) that do not exist: {unknown}. They must be from "
            f"{sorted(PERMANENT_HALT_KINDS)} — a kind with a typo in it is configuration that "
            f"looks set and routes nothing, and the halt it was meant for would go on reaching "
            f"only the operator with nobody noticing why.")


def recipients(kinds: object, routing: Optional[Mapping[str, str]] = None) -> Tuple[str, ...]:
    """Everyone a halt must reach, owners in the order their kinds were crossed, operator last.

    `routed_to` says who is told **first**; this says who is told, and the distance between those
    two sentences is the entire safety property of this change.

    Takes one kind or several. Several is the real case: `secrets/prod.env` is a credentials file
    *and* sits in something called production, so it crosses `deploy` and `access` and both owners
    are answerable for it.

    **The operator is appended once, at the end**, rather than per kind. Building this at the call
    site instead produced `['release', 'operator', 'security']` — a list documented first-named-first
    with the operator sitting in the middle of it, misreporting who is told first. That is why the
    ordering rule is here, next to the tests for it, and not inlined wherever a halt is raised.
    """
    wanted = (kinds,) if isinstance(kinds, str) else tuple(kinds or ())
    told: List[str] = []
    for kind in wanted:
        owner, _ = routed_to(str(kind), routing)
        if owner != DEFAULT_RECIPIENT and owner not in told:
            told.append(owner)
    told.append(DEFAULT_RECIPIENT)
    return tuple(told)


#: What a plan declares for work that crosses none of them. It is a **declaration**, not a default:
#: see `classify`.
ORDINARY = "ordinary"

PERMANENT_HALTS: Tuple[str, ...] = tuple(PERMANENT_HALT_KINDS.values())

#: A **backstop**, not the guarantee, and deliberately **narrow**. kind -> phrases that suggest it,
#: used only to catch an operation declared `ordinary` whose own wording says otherwise, and to read
#: a node's brief. It can add a stop and can never remove one.
#:
#: ## Why these are phrases and not words
#:
#: An earlier version of this file made the word list *the* check and, when two verifiers broke all
#: six red lines with ordinary English, widened it: single verbs like "delete", "deploy", "publish",
#: "token", "permission". That bought a measured 8 of 18 on the verifier sentences at the time — and a
#: measured **69% false-stop rate on ordinary engineering work**. "Fix the token parser" was a
#: secrets change. "Remove all unused imports" was a hard delete. "Add production-grade error
#: messages" was a production deploy.
#:
#: A check that fires on two jobs in three is not a strict check; it is a check that gets switched
#: off, and switching it off is one `--undeclared allow` away. At which point four changes of safety
#: work protect nothing. **The false-stop rate is a safety property, not an ergonomics one.**
#:
#: So: a phrase belongs here only if it **cannot plausibly describe safe work**. Single common verbs
#: are the vocabulary of ordinary engineering and are out. Measured after narrowing: **0% false
#: stops on 46 real briefs, 6 of 18 verifier sentences caught.** Trading two catches on the weakest
#: of four layers for twenty-five false stops is not a close call — and the other three layers, the
#: ones that actually carry the guarantee, are untouched by it.
#:
#: `tests/test_false_stops.py` pins both numbers. Either one moving is a fact somebody has to look
#: at.
_HALT_WORDS: Dict[str, Tuple[str, ...]] = {
    "deploy": (
        "deploy to production", "deploy to prod", "release to production", "push to production",
        "push to prod", "ship to production", "promote to production", "cut a release",
        "go live with", "roll out to production", "上線部署", "部署到正式",
    ),
    "migration": (
        "alter table", "drop column", "schema migration", "run the migration",
        "migrate the database", "migrate the production", "backfill the table",
        "irreversible schema", "資料庫遷移",
    ),
    "delete": (
        "rm -rf", "drop table", "drop database", "truncate table", "delete from",
        "hard delete", "wipe the users", "wipe the database", "purge the database",
        "erase every", "delete all customer", "delete the production", "永久刪除", "清空資料庫",
    ),
    "money": (
        "transfer funds", "wire usd", "wire $", "issue a refund", "charge the card",
        "send a payout", "move money", "transfer money", "轉帳", "匯款",
    ),
    "access": (
        "rotate the key", "rotate the signing", "rotate the api key", "grant admin",
        "grant administrator", "grant full control", "revoke access", "change permissions",
        "set the api key", "publish the secret", "commit the secret", "變更權限", "外洩金鑰",
    ),
    "publish": (
        "publish to the public", "publish publicly", "make public", "make the repo public",
        "visible to everyone", "post to twitter", "post to the public",
        "send email to customers", "announce publicly", "對外發布", "公開發布",
    ),
}


#: What an operation will actually touch, matched to the kind of work touching it is. Keyed by kind,
#: valued by regexes over a **target** — a command it will run, a path it will write, or a URL it
#: will call.
#:
#: This is the difference between reading what somebody *says* and reading what they will *do*. The
#: description is prose a planner writes; a target is the thing itself, and a plan that names
#: `kubectl apply -f prod/` has said "production deploy" whatever word it put in `kind`.
_TARGET_RULES: Dict[str, Tuple[str, ...]] = {
    "deploy": (
        r"\bkubectl\s+(apply|rollout|set|scale)\b", r"\bhelm\s+(install|upgrade)\b",
        r"\bdocker\s+push\b", r"\b(terraform|pulumi)\s+apply\b",
        r"\bserverless\s+deploy\b", r"\baws\s+(deploy|ecs|lambda)\b",
        r"\bgh\s+release\s+create\b", r"\bnpm\s+publish\b", r"\bcargo\s+publish\b",
        r"\btwine\s+upload\b", r"\bfly\s+deploy\b", r"\bvercel\s+(deploy|--prod)\b",
        r"(^|[\s/@:.])prod(uction)?([\s/.:]|$)",
    ),
    "migration": (
        r"\balter\s+table\b", r"\bcreate\s+index\b", r"\bdrop\s+column\b",
        r"\b(alembic|flyway|liquibase|knex|prisma)\b", r"\bdjango-admin\s+migrate\b",
        r"\bmanage\.py\s+migrate\b", r"(^|/)migrations?/",
    ),
    "delete": (
        r"\brm\s+-[a-z]*[rf]", r"\bdrop\s+(table|database|schema)\b", r"\btruncate\b",
        r"\bdelete\s+from\b",
        # Every one of these was demonstrated running to completion by a verifier while the
        # recogniser called it ordinary.
        r"\bshred\b", r"\bmkfs(\.\w+)?\b", r"\bwipefs\b", r"\bdd\s+.*\bof=",
        r"\bfind\b.*\s-delete\b", r"\bfind\b.*-exec\s+rm\b", r"\bcp\s+/dev/null\s+\S",
        r">\s*/dev/(sd|nvme|hd|disk)", r"\brsync\b.*--delete\b",
        r"\bflushall\b", r"\bflushdb\b",
        r"\bgit\s+push\s+.*--delete\b", r"\bgit\s+push\s+\S+\s+:\S",
        r"\bgit\s+branch\s+-[a-z]*d\b", r"\bgit\s+tag\s+-[a-z]*d\b",
        r"\bgit\s+stash\s+(clear|drop)\b", r"\bgit\s+reflog\s+expire\b",
        r"\bgit\s+gc\b.*--prune", r"\bgit\s+filter-branch\b",
        r"\bgit\s+checkout\s+--\s", r"\bgit\s+restore\b", r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+update-ref\s+-d\b", r"\bgit\s+clean\s+-[a-z]*[fd]",
        r"\bkubectl\s+delete\b", r"\bdocker\s+compose\s+down\b.*-v",
        # Both spellings. Matching only `--force` let `git push -f` read as an ordinary push once
        # the allowlist existed — a short flag is the same command, and the pair is the kind of gap
        # that only shows up when someone writes it the other way.
        r"\bgit\s+push\s+.*(--force|(^|\s)-f(\s|$))", r"\bgit\s+push\s+-[a-z]*f\b",
        r"\bgh\s+repo\s+delete\b",
        r"\baws\s+s3\s+rm\b", r"\bshred\b",
    ),
    "money": (
        r"\b(stripe|paypal|braintree|adyen|wise|plaid|square)\b",
        r"/v\d+/(charges|payments|payouts|transfers|refunds)\b",
        r"\bcheckout\.session\b", r"\bbilling\b",
    ),
    "access": (
        r"(^|/)\.env(\.|$)", r"\.(pem|key|p12|pfx|jks|keystore)$", r"(^|/)(secrets?|creds?)/",
        r"(^|/)id_(rsa|ed25519|ecdsa)$", r"\bvault\s+(write|kv\s+put)\b",
        r"\baws\s+iam\b", r"\bgcloud\s+(iam|projects\s+add-iam)\b",
        r"\bgh\s+(secret|api\s+.*collaborators)\b", r"\bchmod\s+[0-7]*777\b",
        r"(^|/)authorized_keys$",
    ),
    "publish": (
        r"\bgh\s+repo\s+edit\s+.*--visibility\s+public\b",
        r"\bgh\s+(release|gist)\s+create\b",
        r"\b(api\.twitter|graph\.facebook|slack\.com/api|discord\.com/api|api\.telegram)",
        r"/v\d+/(messages|posts|tweets|statuses)\b",
        r"\b(sendgrid|mailgun|ses\.amazonaws|postmark)\b",
        r"\baws\s+s3\s+.*--acl\s+public",
    ),
}


#: Shell composition. Any of these makes a target un-ordinary whatever its prefix looks like,
#: because composition hides everything after the part a prefix matched: `cat` is harmless and
#: `cat /dev/urandom > /dev/sda` is not, and the difference is a character the prefix never saw.
#: A verifier used exactly that to walk past the previous version.
_COMPOSED = r"[>|;&`]|\$\(|(^|[\s/])\.\.([\s/]|$)"

#: A plain path inside the project: no traversal, no metacharacters, no leading slash. **Decidable**,
#: which is the whole reason it is one of only two things recognised without the operator's help.
_REPO_PATH = r"^[\w.][\w./+-]*$"

#: Read-only version control. Nothing here can change a file, so it can be built in safely.
_READ_ONLY = r"^git\s+(status|log|diff|show|blame|remote\s+-v|config\s+--get)\b"


#: Commands whose **name says nothing about what will happen**: the argument is the program.
#:
#: Vouching for one of these is vouching for anything it can be told to do, which is not a
#: declaration — it is a blank cheque wearing one. A verifier demonstrated it in one line:
#: `python -c "__import__('pathlib').Path('customers.db').unlink()"`, ordinary because somebody had
#: vouched for `python`. `rm important-backups.tar` was ordinary for the same reason.
#:
#: These are never `ordinary`, and `settings.load` refuses to accept one in `ordinary_commands` so
#: the operator finds out while configuring rather than while it matters.
EXECUTORS: FrozenSet[str] = frozenset({
    "python", "python3", "py", "node", "deno", "bun", "ruby", "perl", "php", "lua", "rscript",
    "sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "pwsh", "powershell", "cmd",
    "eval", "exec", "source", "env", "xargs", "nohup", "timeout", "watch", "ssh", "sudo", "doas",
    "rm", "rmdir", "mv", "dd", "tee", "install", "chmod", "chown", "chgrp", "ln", "crontab",
    "curl", "wget", "nc", "ncat", "socat",
    # Stdlib modules that are themselves execution engines. `python -m os` is as unbounded as
    # `python -c`, and the module form must not become a way back in.
    "os", "subprocess", "pty", "code", "pdb", "runpy", "timeit", "shutil",
    "socketserver", "smtpd", "telnetlib", "ftplib", "webbrowser", "http", "venv",
})

#: `python -m pytest` is ordinary because **pytest** is a vouched bounded tool — not because anyone
#: vouched for `python`. The shape carries the meaning, so the common case survives without the
#: interpreter ever becoming trustworthy.
_MODULE_FORM = r"^(python3?|py)\s+-m\s+([\w.]+)"

#: Verbs that destroy, stop or publish. Matched **in subcommand position** — a bare word, not a
#: flag — which is the distinction the previous version missed in both directions at once:
#:
#: * `docker volume rm pgdata` and `git remote remove origin` slipped through, because the list was
#:   built from flags like `--force` and never held the plainest verb there is;
#: * `cargo build --release` and `docker compose up -d` were stopped, because `release` and `-d`
#:   were matched anywhere they appeared, including as a flag value.
#:
#: A verb in subcommand position is a statement about what the command does. The same letters in a
#: flag are not.
_DESTRUCTIVE_VERBS = (
    "rm", "remove", "delete", "destroy", "drop", "purge", "prune", "clear", "clean", "wipe",
    "reset", "revoke", "stop", "kill", "down", "uninstall", "erase", "flush", "truncate",
    "publish", "deploy", "release",
    # `push` is deliberately absent: an ordinary push is how work ships, and the destructive forms
    # (`--force`, a `+refspec`) are caught by _DANGEROUS_FORMS. Listing the verb stopped
    # `git push origin feature/x`, which is the false-positive side of the same coin.
)

#: Flag and argument forms that are dangerous however they appear. Short and specific: a long list
#: here is how `cargo build --release` got stopped.
_DANGEROUS_FORMS = (
    r"--force\b", r"--delete\b", r"--hard\b", r"--prune\b", r"--no-verify\b",
    r"\s\+\w+:\w+",                 # a `+refspec`: force-overwrite a remote branch
    r"\s-[a-z]*[rf]{2}\b",           # -rf and friends
)


def _suspect(text: str) -> bool:
    """Does this command line carry a destructive verb or a dangerous form?

    Only ever removes `ordinary` status, so an over-match costs one question and an under-match
    costs the irreversible thing.
    """
    for pattern in _DANGEROUS_FORMS:
        if re.search(pattern, text):
            return True
    words = [w for w in text.split() if not w.startswith("-")]
    return any(w in _DESTRUCTIVE_VERBS for w in words[1:4])


def recognise(target: str, vouched: Sequence[str] = ()) -> str:
    """``"red"``, ``"ordinary"`` or ``"unrecognised"``.

    ## Why this stopped trying to be clever

    Two rounds of independent review broke two versions of this, in opposite directions:

    * **Round 5** — an enumerated blacklist, where "nothing matched" was read as *safe*. Five
      destructive commands declared `ordinary` ran a flow to completion with an empty report.
    * **Round 6** — a prefix allowlist, where "the command is on the list" was read as *safe*. So
      `git push origin --delete main` was ordinary because `git` was listed, `cat ... > /dev/sda`
      was ordinary because `cat` was — **and 10 of 10 real development commands were stopped**.

    Wrong in both directions at once is not a mistuning. A runner cannot classify an arbitrary shell
    string, and pretending otherwise produced a check that was both unsafe and unusable.

    So this only answers what it can actually know:

    1. does it **match a known-dangerous pattern** — imperfect, and every addition is safe;
    2. is it a **plain repo-relative path**, or **read-only version control** — decidable;
    3. has **the operator vouched for the command** — they know their toolchain; this runner does
       not, and guessing on their behalf is what went wrong twice.

    Everything else is `unrecognised`, which is a true statement about this runner's knowledge
    rather than a verdict about the target. `unrecognised` stops by default and is recorded when
    allowed through.
    """
    text = str(target).casefold().strip()
    if not text:
        return "unrecognised"
    for kind in PERMANENT_HALT_KINDS:
        if any(re.search(pattern, text) for pattern in _TARGET_RULES[kind]):
            return "red"
    if re.search(_COMPOSED, text):
        return "unrecognised"
    if re.match(_REPO_PATH, text) or re.search(_READ_ONLY, text):
        return "ordinary"
    vouched_set = {str(v).casefold() for v in vouched}
    first = text.split()[0]

    module = re.match(_MODULE_FORM, text)
    if module:
        name = module.group(2).split(".")[0]
        if name in vouched_set and name not in EXECUTORS and not _suspect(text):
            return "ordinary"
        return "unrecognised"

    if first in EXECUTORS:
        # Never ordinary, vouched or not. The operator may still declare the operation's kind, which
        # is a statement about *this* piece of work rather than a standing permission for a tool
        # that can be told to do anything.
        return "unrecognised"

    if first in vouched_set and not _suspect(text):
        return "ordinary"
    return "unrecognised"


def unrecognised(targets: Sequence[str], vouched: Sequence[str] = ()) -> Tuple[str, ...]:
    """The targets this runner cannot place. Empty when it recognises every one."""
    return tuple(t for t in targets if recognise(t, vouched) == "unrecognised")


def derive(targets: Sequence[str]) -> Tuple[str, ...]:
    """Every kind these targets **are**, read from the targets themselves.

    A target is a command, a path, or a URL the operation will act on. Unlike `permanent_halt`, this
    does not read prose: `rm -rf` in a command is not a phrasing choice, and neither is a path under
    `secrets/`. That is why it is allowed to overrule a declaration, and why the word lists are not.

    **All** matching kinds are returned, not the first. `.env.production` is a secrets file *and*
    sits in something called production; picking one and reporting it alone names the operation
    wrongly while still stopping it, which is the kind of half-truth that erodes trust in a stop.
    """
    haystack = " ".join(str(t) for t in targets).casefold()
    if not haystack.strip():
        return ()
    return tuple(kind for kind in PERMANENT_HALT_KINDS
                 if any(re.search(pattern, haystack) for pattern in _TARGET_RULES[kind]))


def classify(operation: Mapping[str, object]) -> Optional[str]:
    """The permanent halt this operation crosses, or ``None``.

    An operation is ``{"description": str, "kind": str, "targets": [str, ...]}``. ``kind`` is one of
    `PERMANENT_HALT_KINDS` or `ORDINARY`; ``targets`` are the commands, paths and URLs it will act
    on, and are optional.

    Three things decide, in this order, and each may only ever **add** a stop:

    1. **The targets.** What an operation will touch is a fact, not a phrasing, so a target that is
       a red line overrules a declaration that says otherwise. This is the layer that stops the
       planner from being the trust boundary — a plan naming `kubectl apply -f prod/` has said
       "production deploy" whatever it wrote in ``kind``.
    2. **The declaration.** A declared red line halts, whatever its targets and description say.
    3. **The description**, against `_HALT_WORDS` — the backstop, and the weakest of the three. It
       catches a red line mis-declared as ordinary *only* when the wording gives it away, which is
       6 times out of 18 known attempts. Never trusted on its own.

    **An operation that declares nothing is refused.** That inversion is the fix that came before
    this one: a red line whose default branch is "proceed" is not a red line.
    """
    if not isinstance(operation, Mapping):
        raise PolicyError(
            f"an operation must declare what kind of work it is, as "
            f"{{'description': ..., 'kind': one of {sorted(PERMANENT_HALT_KINDS) + [ORDINARY]}, "
            f"'targets': [...]}}. Got {operation!r}. A bare description would have to be classified "
            f"by guessing at its words, and a guess that comes out wrong dispatches something "
            f"irreversible.")

    kind = operation.get("kind")
    description = str(operation.get("description", ""))
    targets = operation.get("targets") or ()
    if isinstance(targets, str):
        raise PolicyError(
            f"operation {description!r} gives targets as a single string. It must be a list — one "
            f"entry per command, path or URL — or the whole lot is matched as one blob and a "
            f"boundary between two of them can hide a third.")

    if kind is None:
        raise PolicyError(
            f"operation {description!r} declares no kind. It must be one of "
            f"{sorted(PERMANENT_HALT_KINDS) + [ORDINARY]} — an undeclared operation is not assumed "
            f"to be safe.")
    if kind != ORDINARY and kind not in PERMANENT_HALT_KINDS:
        raise PolicyError(
            f"operation {description!r} declares kind {kind!r}, which is not one of "
            f"{sorted(PERMANENT_HALT_KINDS) + [ORDINARY]}")

    crossed_kinds = _crossed(kind, description, targets)
    if not crossed_kinds:
        return None
    return " and ".join(PERMANENT_HALT_KINDS[k] for k in crossed_kinds)


def _crossed(kind: object, description: str, targets: Sequence[str]) -> Tuple[str, ...]:
    """The three layers, answering in **kind keys**. `classify` is this, formatted.

    Split out for CHG-20260827-19, which needs to route a halt to whoever owns that kind — and a
    description cannot be routed. The alternative was a second function repeating the ordering, and
    two functions that must agree about what is a red line will eventually disagree about one.
    """
    derived = derive(targets)
    if derived:
        return derived
    if kind in PERMANENT_HALT_KINDS:
        return (str(kind),)
    spoken = _halt_word_kind(description)
    return (spoken,) if spoken else ()


def crossed(operation: Mapping[str, object]) -> Tuple[str, ...]:
    """Every permanent-halt kind this operation crosses, as keys of `PERMANENT_HALT_KINDS`.

    Same decision as `classify` and the same validation — this is the routable form of the answer.
    Empty means the operation crosses nothing.
    """
    if classify(operation) is None:
        return ()
    return _crossed(operation.get("kind"), str(operation.get("description", "")),
                    operation.get("targets") or ())


def unverified(operation: Mapping[str, object],
               vouched: Sequence[str] = ()) -> Tuple[str, ...]:
    """The targets of an `ordinary` operation that nothing could confirm.

    Separate from `on_trust`, which answers yes/no; this names them, so a halt or a report can quote
    the thing nobody could place rather than saying "something here".
    """
    if operation.get("kind") != ORDINARY:
        return ()
    return unrecognised(operation.get("targets") or (), vouched)


def on_trust(operation: Mapping[str, object], vouched: Sequence[str] = ()) -> bool:
    """Is this operation being taken on the planner's word alone?

    True when it declares `ordinary` and **nothing independently confirmed that** — either it named
    no targets, or it named some this runner does not recognise.

    The second half was missing, and its absence undid the first. The condition used to be simply
    "no targets", so naming *any* target — a benign `a.py` would do — switched the disclosure off.
    A verifier used that: it declared destructive commands `ordinary`, named them as targets the
    red-line list happens not to enumerate, and the run finished with `on_trust` empty. The
    operation was neither stopped nor recorded, which is the one outcome KN-11 exists to forbid:
    *where a trust boundary cannot be removed, record it — not in silence.*

    A target the runner cannot place is not evidence of anything. Only a **recognised** one counts
    as having been checked.
    """
    if operation.get("kind") != ORDINARY:
        return False
    targets = operation.get("targets") or ()
    if not targets:
        return True
    return bool(unrecognised(targets, vouched))


def permanent_halt(text: str) -> Optional[str]:
    """The halt an operation's *wording* suggests, or ``None`` — the backstop only.

    Never the guarantee on its own: see `classify`. Matching is deliberately generous, because in
    this direction a false stop costs one question and a miss costs the thing that cannot be undone.
    """
    kind = _halt_word_kind(text)
    return PERMANENT_HALT_KINDS[kind] if kind else None


def _halt_word_kind(text: str) -> Optional[str]:
    """The same backstop, answering in a kind key so it can be routed. See `_crossed`."""
    lowered = text.casefold()
    for kind, words in _HALT_WORDS.items():
        if any(word in lowered for word in words):
            return kind
    return None


#: The review seats, in opening order — least negotiable first, so opening fewer means taking a
#: prefix rather than picking favourites. A seat with `veto` cannot be outvoted: its subject is a
#: matter of fact, not of opinion.
@dataclass(frozen=True)
class Seat:
    name: str
    label: str
    question: str
    veto: bool


SEATS: Tuple[Seat, ...] = (
    Seat("conformance", "規格合規",
         "Is this the thing the task asked for? Line by line against what was written down — "
         "including work that was not asked for, which is equally out of scope.", veto=True),
    Seat("defect", "缺陷",
         "Where is this wrong? Concrete inputs and the wrong result they produce, not a feeling "
         "that something looks off.", veto=False),
    Seat("risk", "風險與可逆性",
         "What does this make hard to undo, and what happens if it is wrong in production?",
         veto=False),
    Seat("idiom", "慣例與簡潔",
         "Does this read like the code around it, and is any of it unnecessary?", veto=False),
)

BY_SEAT: Dict[str, Seat] = {s.name: s for s in SEATS}

#: The floor: how many seats open by default. Fewer than this needs the user's explicit high-risk
#: mode, because a single reviewer is exactly the single point of view the panel exists to avoid.
SEAT_FLOOR = 3


def role(name: str) -> Role:
    if name not in BY_ROLE:
        raise PolicyError(
            f"no role {name!r}; this runner defines {sorted(BY_ROLE)}. Roles are not defaulted — a "
            f"node naming one that does not exist is a mistake, not a case to guess at.")
    return BY_ROLE[name]


def capabilities(name: str) -> Dict[str, bool]:
    """The three flags a work order may carry for this role."""
    r = role(name)
    return {"can_spawn": r.can_spawn, "can_write": r.can_write, "can_execute": r.can_execute}


def verdict(gate: str, risk: str, autonomy: Optional[str] = None,
            change_class: Optional[str] = None) -> Dict[str, object]:
    """What the policy says at this gate for this risk, tightened by ``autonomy`` if it is stricter.

    ``autonomy`` is the per-change override. It may **tighten only** — a change may declare itself
    more dangerous than its grade suggests, never less. Asking to loosen is not honoured and is
    reported, because a request to relax a gate is worth seeing rather than silently dropping.
    """
    if gate not in GATES:
        raise PolicyError(f"no gate {gate!r}; this runner defines {sorted(GATES)}")
    if risk.lower() not in RISKS:
        raise PolicyError(f"no risk grade {risk!r}; this runner defines {list(RISKS)}")

    graded = GATES[gate][risk.lower()]
    result = {"gate": gate, "risk": risk.lower(), "verdict": graded,
              "source": "policy.GATES", "tightened": False}
    if autonomy:
        want = autonomy.lower()
        if want not in (AUTO, *STOPPING):
            raise PolicyError(f"autonomy {autonomy!r} is not one of {[AUTO, *STOPPING]}")
        if graded == AUTO and want in STOPPING:
            result.update(verdict=want, tightened=True,
                          source="policy.GATES tightened by the change's Autonomy field")
        elif want == AUTO and graded in STOPPING:
            # Reported through `source` rather than as an extra key: the verdict's shape is fixed so
            # a work order's closed schema can carry it, and a refusal the node never sees is a
            # refusal that may as well not have happened.
            result["source"] += (
                f"; the change asked for {AUTO} here and was refused — tighten-only")
    # LAST, and after `autonomy` on purpose (CHG-20260827-20). A change that declared itself more
    # dangerous than its grade has said something about *this* instance; a class says something
    # about the *type*. The instance's own word is the more specific of the two, so relaxing is
    # applied to what is left standing rather than to the table — a `standard` class cannot undo a
    # tightening the change asked for itself.
    relaxed, why = relax(str(result["verdict"]), change_class)
    if why:
        result["source"] += why
    # The verdict, and NOTHING else. The `autonomy` branch above says why in as many words — "the
    # verdict's shape is fixed so a work order's closed schema can carry it" — and the first draft
    # of this added `relaxed` and `change_class` keys anyway, in the function carrying that comment.
    # `workorder.render` refused them. A caller that needs to know whether the class changed the
    # outcome asks for the verdict without it and compares; that is also the better question,
    # because "what would have happened otherwise" is what an audit note wants to say.
    result["verdict"] = relaxed
    return result


def stops(verdict_value: str) -> bool:
    """Does this verdict stop the run? Everything but ``auto`` does."""
    return verdict_value != AUTO


def seat_names(count: int) -> List[str]:
    if count < 1:
        raise PolicyError("a review needs at least one seat")
    if count > len(SEATS):
        raise PolicyError(f"{count} seats requested but this runner defines {len(SEATS)}")
    return [s.name for s in SEATS[:count]]


def resolve_seats(requested: Optional[int], high_risk_mode: bool) -> int:
    """How many seats a run opens, refusing to go below the floor on its own authority."""
    if requested is None:
        return SEAT_FLOOR
    if requested < SEAT_FLOOR and not high_risk_mode:
        raise PolicyError(
            f"{requested} seat(s) is below the floor of {SEAT_FLOOR}. Enable high-risk mode to go "
            f"below it — one reviewer is the single point of view the panel exists to avoid, so "
            f"this runner does not lower the floor by itself.")
    seat_names(requested)        # raises if the count is not one this runner can actually open
    return requested


#: The three outcomes a panel can reach. ``undecided`` is not a kind of failure — it is the absence
#: of a decision, and the difference is the whole of CHG-20260823-11's second design decision: a
#: failure sends the work back, which is a judgement nobody made.
PASS = "pass"
FAIL = "fail"
UNDECIDED = "undecided"
OUTCOMES = (PASS, FAIL, UNDECIDED)


#: What a dispatched process may touch, by risk grade (CHG-20260827-23).
#:
#: `policy.py`'s capability flags have always been **advisory**: `Role("qa", can_write=False)` carries
#: the note *"deliberately cannot write, so it cannot fix while verifying"*, which is a real safety
#: property, and nothing enforced it. The flags went into the work order and the process ran with the
#: operator's full rights.
#:
#: ## Why the grade decides it
#:
#: The runner already computes a grade per change, and per workstream since CHG-20260827-18. A
#: sandbox policy configured once per session — which is what comparable tools do — would be a second
#: thing to keep in step with the first. Deriving it means there is one answer to "how dangerous is
#: this" and everything reads it.
#:
#: ## This table is a claim, and it is the part most likely to be wrong
#:
#: It applies "expensive to undo" to a second axis, and the first axis took several rounds to grade
#: well. Written as data so a review seat can argue with the table rather than with the code.
#:
#: The failure mode to fear is **not** too loose. `policy.py` already names it about the red lines:
#: a check that stops everything is a check that gets switched off. `low` keeps the network because
#: builds fetch things, and a sandbox that breaks every build is one nobody runs.
SANDBOX: Dict[str, Dict[str, object]] = {
    "low":    {"write": "workspace", "network": True},
    "medium": {"write": "workspace", "network": False},
    "high":   {"write": "none",      "network": False},
}

#: What `write` may say. `workspace` is the directory the command runs in; `none` is read-only
#: everywhere. There is no "everywhere" — a sandbox that allows it is not one.
WRITE_SCOPES = ("workspace", "none")


def sandbox_for(risk: str, can_write: bool = True) -> Dict[str, object]:
    """The policy for one dispatched process: the grade's, narrowed by the role's capability.

    A role with `can_write=False` gets no write **whatever the grade allows**. That is the direction
    the two combine in, and it is the only direction that keeps the flag's promise: QA is
    `can_write=False` so it cannot quietly repair what it is verifying, and a `low` grade must not
    hand it a pen.

    Narrowing only. Nothing here can widen what the grade permits.
    """
    if risk not in SANDBOX:
        raise PolicyError(
            f"no sandbox policy for grade {risk!r}; the grades are {list(RISKS)}. Defaulting here "
            f"would pick a blast radius nobody chose.")
    policy_for_grade = dict(SANDBOX[risk])
    if not can_write:
        policy_for_grade["write"] = "none"
    # A scope the wrappers do not implement would be read as "not workspace" and silently become
    # read-only -- safe, and not what the table says. `SANDBOX` is edited by hand and is the part of
    # this change most likely to be got wrong, so a typo in it is refused rather than absorbed.
    if policy_for_grade["write"] not in WRITE_SCOPES:
        raise PolicyError(
            f"grade {risk!r} allows write scope {policy_for_grade['write']!r}, which is not one of "
            f"{list(WRITE_SCOPES)}. `sandbox.py` implements those two and reads anything else as "
            f"no write at all, so this would bound the process more tightly than the table claims "
            f"and say nothing about it.")
    return policy_for_grade


def strictest(grades: Sequence[str]) -> str:
    """The strictest grade in a set. `RISKS` is ordered low → high, so this is a max over it.

    Used while the grade is still being decided, never to decide it — see `adjudicate_grade` for
    why those are different jobs.
    """
    known = [g for g in grades if g in RISKS]
    if not known:
        raise PolicyError(
            f"no grade among {list(grades)!r} is one of {list(RISKS)}. There is no strictest of "
            f"nothing, and defaulting here would pick a protection level nobody proposed.")
    return max(known, key=RISKS.index)


def adjudicate_grade(grades: Mapping[str, str]) -> Dict[str, object]:
    """A panel's risk grades, turned into one grade or into nobody's decision.

    ## Why this is not `adjudicate(voices="models")`

    CHG-20260827-17 proposed reusing it. It cannot do this job: that function counts how many voices
    said `pass` and returns pass / undecided / fail. It is **binary**, and a grade is one of three.
    Asking it for "medium" would get a count of passes back.

    ## Majority, and a tie is nobody's decision — not "the strictest wins"

    "Any voice saying `high` makes it high" is the tempting rule and it is wrong here. `adjudicate`'s
    own docstring says a model panel has **no veto**, because every voice answers the same question
    and there is no per-voice subject for a veto to be about. Letting one voice set `high` alone is a
    veto wearing another name.

    So: a strict majority decides, and anything else is `undecided` and reaches a person. Three
    voices splitting low / medium / high decide nothing, which is the honest answer — they disagree
    about the thing every later gate is indexed by.

    **Strictness has a job, and it is not this one.** While the grade is unsettled the runner
    protects at `strictest(...)` of what was proposed — see `engine._grade_in_force`. That is about
    how much protection applies to an open question; this is about what the answer is. Collapsing
    the two would let one voice decide by being cautious.
    """
    if not grades:
        raise PolicyError("no grades to adjudicate")
    unknown = sorted({g for g in grades.values() if g not in RISKS})
    if unknown:
        raise PolicyError(
            f"grade(s) {unknown} are not one of {list(RISKS)}. A voice that answered something else "
            f"has not graded the change, and reading it as a grade would invent one.")

    counts: Dict[str, int] = {}
    for grade in grades.values():
        counts[grade] = counts.get(grade, 0) + 1
    top = max(counts.values())
    winners = sorted((g for g, n in counts.items() if n == top), key=RISKS.index)
    total = len(grades)

    if top * 2 > total:
        return {"outcome": PASS, "grade": winners[0],
                "reason": f"{top}/{total} voices graded it {winners[0]}",
                "proposed": dict(grades)}
    return {"outcome": UNDECIDED, "grade": None,
            "reason": (f"no majority: {', '.join(f'{g}×{counts[g]}' for g in winners)} out of "
                       f"{total}. The grade indexes every later gate, so a panel that has not "
                       f"agreed on it has not decided anything a person can be spared."),
            "proposed": dict(grades)}


def adjudicate(verdicts: Mapping[str, str], *, voices: str = "seats") -> Dict[str, object]:
    """Turn a panel's verdicts into one outcome: veto first, then majority, and a tie decides nothing.

    ``voices`` says **what kind of panel this is**, and it is a parameter rather than something
    inferred from the names because the two kinds adjudicate differently:

    ``"seats"``
        The review seats. Each answers a *different* question, and one of them — conformance — holds
        a **veto**: its subject is a matter of fact, and counting votes on a fact is how a panel
        talks itself out of one. Every name must be a seat this policy defines.

    ``"models"``
        N models on **one** question (``graph.MODEL_PANEL``). **No voice vetoes.** A veto belongs to
        a seat because that seat owns a subject; a model panel has no per-voice subject — every
        voice answers the same question — so there is nothing for a veto to be *about*. Giving one
        model a veto would be giving it authority for being itself, which is the ranking nobody
        wrote down that this design refuses elsewhere. Majority, and that is all.

    **A tie is ``undecided``, not ``fail``.** An even split has not decided anything, and returning
    ``fail`` would send the work back on nobody's judgement. Callers must handle three outcomes;
    ``engine._adjudicate`` used to collapse everything that was not ``pass`` into ``fail``, which
    would have turned this whole change into a no-op that still went green.
    """
    if voices not in ("seats", "models"):
        raise PolicyError(f"unknown panel kind {voices!r}")
    if voices == "models":
        if not verdicts:
            raise PolicyError("no verdicts to adjudicate")
        passes = sum(1 for v in verdicts.values() if v == PASS)
        if passes * 2 > len(verdicts):
            return {"outcome": PASS, "vetoed": [],
                    "reason": f"{passes}/{len(verdicts)} voices passed"}
        if passes * 2 == len(verdicts):
            return {"outcome": UNDECIDED, "vetoed": [],
                    "reason": f"{passes}/{len(verdicts)} voices passed — an even split decides "
                              f"nothing, so this is a person's to call"}
        return {"outcome": FAIL, "vetoed": [],
                "reason": f"only {passes}/{len(verdicts)} voices passed"}

    unknown = [s for s in verdicts if s not in BY_SEAT]
    if unknown:
        raise PolicyError(f"unknown seat(s): {sorted(unknown)}")
    if not verdicts:
        raise PolicyError("no seat verdicts to adjudicate")

    vetoed = [s for s, v in verdicts.items() if BY_SEAT[s].veto and v != "pass"]
    if vetoed:
        # The *rule*, not a speech act. What this knows is that a seat holding a veto did not return
        # `pass`; it does not know that the seat chose to veto. Round 4's conformance seat returned
        # `fail` and wrote "No veto" with reasons, and this reported `veto from ['conformance']` —
        # a record stating something its own author denied, which is this repository's recurring
        # defect class appearing in the code that adjudicates it.
        #
        # Only the sentence changes. `outcome` and `vetoed` are byte-identical, so no gate, class or
        # graph edge moves. The rule itself is right and was ruled so by the seat that holds the
        # veto: a seat able to decline its own veto makes the veto advisory, and counting votes on a
        # matter of fact is what the veto exists to prevent. What remains — that `policy` and the
        # seat prompts use "veto" for two different things — is a design question for a person, and
        # is the same collision `ledger_check` had between `wrong` and `void` (CHG-20260830-09).
        # `", ".join(...)`, not the list itself. An operator reads this through `report.halt_reason`,
        # and `['conformance'] holds a veto` puts a Python repr in the subject of a sentence — which
        # nothing else in `src/` does: all twenty other `{sorted(...)}` interpolations put the list
        # after a colon, after a verb, or at the end (CHG-20260831-01, idiom seat).
        held = "holds" if len(vetoed) == 1 else "hold"
        return {"outcome": "fail", "vetoed": sorted(vetoed),
                "reason": f"{', '.join(sorted(vetoed))} {held} a veto and did not pass"}

    passes = sum(1 for v in verdicts.values() if v == PASS)
    if passes * 2 > len(verdicts):
        return {"outcome": PASS, "reason": f"{passes}/{len(verdicts)} seats passed", "vetoed": []}
    if passes * 2 == len(verdicts):
        return {"outcome": UNDECIDED, "vetoed": [],
                "reason": f"{passes}/{len(verdicts)} seats passed — an even split decides nothing, "
                          f"so this is a person's to call"}
    return {"outcome": FAIL,
            "reason": f"only {passes}/{len(verdicts)} seats passed",
            "vetoed": []}
