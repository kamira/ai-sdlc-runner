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
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

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
    Role("pm", "PM", can_spawn=False, can_write=True, can_execute=False,
         note="turns the user's instruction into a plan and confirms it; writes the plan, not the code"),
    Role("lead", "主管 / lead agent", can_spawn=True, can_write=True, can_execute=True,
         note="confirms feasibility and risk, dispatches the engineers, reviews what they produce — "
              "the only role that dispatches"),
    Role("engineer", "工程師 / sub-agent", can_spawn=False, can_write=True, can_execute=True,
         note="builds one small module and verifies its own work; cannot dispatch further, so the "
              "tree stays two deep"),
    Role("qa", "QA", can_spawn=False, can_write=False, can_execute=True,
         note="tests and verifies the whole change for real; deliberately cannot write, so it "
              "cannot fix while verifying"),
    Role("seat", "審議席 / review seat", can_spawn=False, can_write=False, can_execute=True,
         note="one review seat; several of them cross-check each other, which is the whole reason "
              "they exist"),
)

BY_ROLE: Dict[str, Role] = {r.name: r for r in ROLES}

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
#: "token", "permission". That bought a measured **8 of 18** on the verifier sentences — and a
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
#: stops on 36 real briefs, 6 of 18 verifier sentences caught.** Trading two catches on the weakest
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
        r"\bdelete\s+from\b", r"\bgit\s+push\s+.*--force\b", r"\bgh\s+repo\s+delete\b",
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
       8 times out of 18 known attempts. Never trusted on its own.

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

    derived = derive(targets)
    if derived:
        return " and ".join(PERMANENT_HALT_KINDS[k] for k in derived)
    if kind in PERMANENT_HALT_KINDS:
        return PERMANENT_HALT_KINDS[kind]
    return permanent_halt(description)


def on_trust(operation: Mapping[str, object]) -> bool:
    """Is this operation being taken on the planner's word alone?

    True when it declares `ordinary` and names no targets: nothing about it was checked against
    anything except its own prose. The engine records these rather than blocking them — forcing
    every operation to name a target would buy ceremony rather than safety, since an empty list is
    as forgeable as a wrong `kind`. What is *not* acceptable is the trust being invisible.
    """
    return operation.get("kind") == ORDINARY and not operation.get("targets")


def permanent_halt(text: str) -> Optional[str]:
    """The halt an operation's *wording* suggests, or ``None`` — the backstop only.

    Never the guarantee on its own: see `classify`. Matching is deliberately generous, because in
    this direction a false stop costs one question and a miss costs the thing that cannot be undone.
    """
    lowered = text.casefold()
    for kind, words in _HALT_WORDS.items():
        if any(word in lowered for word in words):
            return PERMANENT_HALT_KINDS[kind]
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


def verdict(gate: str, risk: str, autonomy: Optional[str] = None) -> Dict[str, object]:
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


def adjudicate(verdicts: Mapping[str, str]) -> Dict[str, object]:
    """Turn the seats' verdicts into one outcome: veto first, then majority.

    A veto seat's ``fail`` cannot be outvoted — its subject is a matter of fact, and counting votes
    on a fact is how a panel talks itself out of one. Everything else is a majority, and a tie does
    not pass: the panel exists to catch what one view would miss, so an even split has caught it.
    """
    unknown = [s for s in verdicts if s not in BY_SEAT]
    if unknown:
        raise PolicyError(f"unknown seat(s): {sorted(unknown)}")
    if not verdicts:
        raise PolicyError("no seat verdicts to adjudicate")

    vetoed = [s for s, v in verdicts.items() if BY_SEAT[s].veto and v != "pass"]
    if vetoed:
        return {"outcome": "fail", "reason": f"veto from {sorted(vetoed)}", "vetoed": sorted(vetoed)}

    passes = sum(1 for v in verdicts.values() if v == "pass")
    if passes * 2 > len(verdicts):
        return {"outcome": "pass", "reason": f"{passes}/{len(verdicts)} seats passed", "vetoed": []}
    return {"outcome": "fail",
            "reason": f"only {passes}/{len(verdicts)} seats passed; a tie does not pass",
            "vetoed": []}
