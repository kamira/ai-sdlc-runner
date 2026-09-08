"""intake.py — the seats read the requirement before anybody builds against it.

A requirement arrives, and the first thing that happens to it is **not** planning. It goes to the
review seats, who say what is wrong with it and what is missing, and the run stops until somebody
has answered.

## Why this is a survey and not a vote

Everywhere else in this runner, several voices are **adjudicated**: veto, then majority, and a tie
decides nothing. Here they are **collected**, and every problem raised is kept whether or not
anybody else agrees.

That is deliberate and it is the opposite rule, so it is worth saying why. Adjudication answers
*"may this proceed?"* — a question with one answer, where counting is the point. Intake answers
*"what is wrong with this?"* — a question with as many answers as there are things wrong, where
counting **destroys** the information. A problem three seats missed and one saw is still a problem;
outvoting it would be the panel agreeing not to know something.

So: union, not majority. No veto, no tie, no `policy.adjudicate`.

## What a requirement is expected to say

Six aspects, and the list is closed. A requirement missing any of them is not refused as bad — it is
**incomplete**, which is a different thing and gets a different response: the run stops and says
exactly what it does not have.

## Being asked three times

Asking again is the right first move; asking forever is not. After the third time a given aspect has
been asked for and not supplied, the runner stops asking and **proposes at least three options** for
it — because at that point the question has failed, and the honest reading is usually that the person
does not have the answer either. Options are not the runner deciding: it puts three on the table and
the choice is still somebody else's.

The options come from a **model**, recorded as an ask like any other. The runner does not invent
them, because a runner that quietly authors requirements has stopped being a runner.
"""
from __future__ import annotations

import hashlib

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

#: What a requirement is expected to say. Closed on purpose: an open list is one nobody can be
#: incomplete against, and "incomplete" is the whole point of this module.
ASPECTS: Tuple[Tuple[str, str], ...] = (
    ("flow", "the flow — what happens, in what order, and where it can go wrong"),
    ("architecture", "the architecture — what the pieces are and which one owns what"),
    ("requirements", "the requirement itself — what must be true when this is done"),
    ("inputs", "the inputs — what goes in, from where, in what shape"),
    ("outputs", "the outputs — what comes out, and what a caller does with it"),
    ("ui", "the screen — what a person sees and what they can do to it"),
)

ASPECT_IDS: Tuple[str, ...] = tuple(name for name, _ in ASPECTS)
BY_ASPECT: Dict[str, str] = dict(ASPECTS)

#: How many times one aspect may be asked for before the runner stops asking and offers options.
#: Three, because the first ask can be missed, the second can be misread, and a third that goes
#: unanswered is evidence about the question rather than about the person.
ASK_LIMIT = 3

#: How many options must be offered once asking has failed. "At least three" because two is a
#: false choice and one is a decision wearing a question mark.
MIN_OPTIONS = 3


class IntakeError(Exception):
    """The requirement cannot be read at all. Distinct from it being incomplete."""


@dataclass
class Survey:
    """What the seats said about one requirement. **A union, never a tally.**"""

    #: ``seat -> the problems that seat raised``. Kept per seat, because "who saw this" is most of
    #: what makes a problem actionable, and a flattened list loses it.
    problems: Dict[str, List[str]] = field(default_factory=dict)
    #: Every aspect any seat could not find. Union: one seat noticing is enough.
    missing: List[str] = field(default_factory=list)
    #: Anything a seat flagged as unsafe. Separated from ordinary problems because "this is
    #: dangerous" and "this is underspecified" want different responses from a person.
    safety: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.missing

    def all_problems(self) -> List[str]:
        """Every problem, attributed, in seat order. What the operator actually reads."""
        out = []
        for seat in sorted(self.problems):
            for problem in self.problems[seat]:
                out.append(f"{seat}: {problem}")
        return out

    def as_dict(self) -> Dict[str, object]:
        return {
            "problems": {k: list(v) for k, v in self.problems.items()},
            "missing": list(self.missing),
            "safety": {k: list(v) for k, v in self.safety.items()},
            "complete": self.complete,
        }


def _text(item, where: str) -> Optional[str]:
    """One item of a seat's answer as words, or `None` if the seat said nothing there.

    **A value that is not text is not a finding** (CHG-20260903-36, idiom seat; extended to every
    item by CHG-20260907-03). A falsy value means the seat said nothing: `"problems": false` is a
    plausible JSON shape for *none*, and it was once recorded as one problem named `False`,
    attributed to the seat and printed to the operator. Measured before that fix:

        _strings(False) -> ['False']    _strings(0) -> ['0']    _strings({}) -> ['{}']

    A **truthy** value that is not text was left doing exactly the same thing, in both branches,
    for another fifteen days. The sentence above this used to end *"a truthy one that is not text
    is still not text, and reading it as a problem invents one"* — an intention written down and
    never implemented, in no change record, no task table and no test.

    Refused rather than dropped, for the reason `collect` refuses an aspect it does not recognise:
    dropping loses a real observation while looking like agreement, and reading it as text invents
    a finding nobody made. Measured on `aea1398`, three seats answering
    `{"unsafe": [{"issue": "rm -rf /"}]}`:

        today                        stops, and a person is asked to decide about
                                     `unsafe: risk: {'issue': 'rm -rf /'}` — a Python repr, and
                                     the digest `--proceed-unsafe` is spent against
        dropping in the fallback     identical: the list branch is untouched, and a list is the
                                     shape `docs/SCHEMAS.md` documents
        dropping in both branches    halted=done, safety=None, **merge reached**

    The last is CHG-20260906-07's finding through another door, and worse than the one
    CHG-20260907-01 closed: that counted silence as agreement, this turns a seat that spoke into
    silence first.
    """
    if not item:
        return None
    if isinstance(item, str):
        return item.strip() or None
    raise IntakeError(
        f"{where} is {type(item).__name__} {item!r}, which is not text. This has to be words a "
        f"person can read, or a list of them — a finding, an aspect or an option. Reading it as "
        f"text would invent one; dropping it would lose a real observation while looking like "
        f"agreement.")


def _strings(value, where: str = "an answer") -> List[str]:
    """Read a seat's answer generously in shape and strictly in content.

    Generous in shape: one string or a list of them. Strict in content: every item goes through
    the same rule, because the list branch and the scalar fallback were one defect and repairing
    only one of them is what left this open — `CHG-20260903-36` swept the fallback and the list
    beside it kept reading `{'issue': ...}` as a finding.
    """
    if isinstance(value, (list, tuple)):
        texts = [_text(v, f"{where}[{i}]") for i, v in enumerate(value)]
        return [text for text in texts if text]
    text = _text(value, where)
    return [text] if text else []


#: The three keys an intake answer may carry. An answer with none of them has not answered.
ANSWER_KEYS = frozenset(("missing", "problems", "unsafe"))


def collect(answers: Mapping[str, Mapping[str, object]]) -> Survey:
    """Aggregate the seats' answers. Union of problems, union of missing aspects.

    ``answers`` is ``seat -> {"problems": [...], "missing": [...], "unsafe": [...]}``.

    An aspect a seat names that is not in ``ASPECTS`` is an error rather than a shrug: a seat
    reporting `"database"` missing has answered a question this runner did not ask, and quietly
    dropping it would lose a real observation while looking like agreement.

    **An answer carrying none of the three keys is an error for the same reason.** A seat that
    looked and found nothing says so with empty lists; a seat that answered something else
    entirely — `{"verdict": "pass"}`, the shape every *other* seat node in this runner expects —
    said nothing about the requirement at all, and counting that as "nothing wrong" is the
    survey agreeing with a voice that did not speak.

    `engine.walk` already refuses this eleven branches up, for model panels, in as many words:
    *"a voice that said nothing is not a voice that voted no"*. The survey had no equivalent, at
    the one node whose whole purpose is to find problems. Measured with the shipped default
    backend and no test harness: `cli._Stub` answers `{"backend", "node_id", "role"}`, all three
    seats were counted as finding nothing, the run planned at `pm_plan`, and only `pm_confirm`
    refused it — the node after the one where the silence mattered.
    """
    survey = Survey()
    missing: List[str] = []
    for seat in sorted(answers):
        answer = answers[seat] or {}
        if not ANSWER_KEYS & set(answer):
            raise IntakeError(
                f"seat {seat!r} answered without saying anything about the requirement. An "
                f"intake answer carries at least one of {sorted(ANSWER_KEYS)} — three empty "
                f"lists is how a seat says it looked and found nothing. It sent "
                f"{sorted(answer) or 'nothing at all'}.")
        problems = _strings(answer.get("problems"), f"seat {seat!r}, 'problems'")
        if problems:
            survey.problems[seat] = problems
        unsafe = _strings(answer.get("unsafe"), f"seat {seat!r}, 'unsafe'")
        if unsafe:
            survey.safety[seat] = unsafe
        for aspect in _strings(answer.get("missing"), f"seat {seat!r}, 'missing'"):
            key = aspect.strip().lower()
            if key not in BY_ASPECT:
                raise IntakeError(
                    f"seat {seat!r} says {aspect!r} is missing, which is not one of the aspects this "
                    f"runner asks about ({list(ASPECT_IDS)}). Dropping it would lose a real "
                    f"observation while looking like agreement.")
            if key not in missing:
                missing.append(key)
    survey.missing = [a for a in ASPECT_IDS if a in missing]      # a stable, readable order
    return survey


def times_asked(history: Sequence[Mapping[str, object]], aspect: str) -> int:
    """How many times this run has already stopped asking for one aspect."""
    return sum(1 for stop in history if aspect in (stop.get("missing") or ()))


def asks_including_this_one(history: Sequence[Mapping[str, object]], aspect: str,
                            in_flight: bool = True) -> int:
    """How many times this has been asked, **counting the ask being made right now**.

    `times_asked` is the raw tally over *recorded* stops, and the engine checks both of the
    questions below **before** the current stop is written: `server.py` walks with a snapshot of
    `intake_history` and appends this run's stop only after the walk returns. So a reader that wants
    "how many times has this person been asked" — which is what both questions are actually about —
    is one lap behind unless it adds the ask in flight.

    `stop_reason` added it and `needs_options` did not, twelve lines apart in this module, and the
    result was that on the third ask the operator read *"(asked 3 times)"* while the decision beside
    it counted two and asked again — against three declarations in this file that say the third
    (CHG-20260903-42). One name both of them read, so they cannot drift apart again.

    **`in_flight` is whether this walk is an ask at all** (CHG-20260907-27). The `+ 1` was
    unconditional, and CHG-20260904-05 had already measured that it must not be: three methods can
    walk from an incomplete stop, and on `attach` the requirement did not grow, so nobody was
    asked. That record repaired the *tally* — `server._walk_once` stops appending — and left the
    `+ 1` alone, so after two recorded asks an `attach` walk read `2 + 1`, crossed `ASK_LIMIT` and
    put options on the table. The same headline one lap over: the runner gives up on somebody
    nobody asked again.

    A parameter and not an inference. This module is handed a history of stops and an aspect; an
    attachment leaves no trace in either, and nothing in `intake_history`, the instructions or the
    artifacts tells the two walks apart. Only the caller that performed the walk knows, so only the
    caller can say. Defaulted to `True` because that is what every caller meant before this record
    existed — and because the two errors are not symmetric: counting an ask that did not happen
    ends the asking early and is unrecoverable, while missing one asks a person once more.
    """
    return times_asked(history, aspect) + (1 if in_flight else 0)


def needs_options(history: Sequence[Mapping[str, object]], aspect: str,
                  in_flight: bool = True) -> bool:
    """Has asking for this aspect failed often enough to stop asking?

    ``>=`` rather than ``>``: the third unanswered ask is the one that has failed, not the fourth.
    The lap was never lost here — it was lost in what the history held at the moment of the check.

    ``in_flight`` is `asks_including_this_one`'s and is passed straight through: a walk that is not
    an ask must not be the ask that runs out of patience.
    """
    return asks_including_this_one(history, aspect, in_flight) >= ASK_LIMIT


def option_request(aspect: str, instructions: Sequence[str]) -> Dict[str, object]:
    """The ask that produces options for an aspect nobody has supplied.

    Returned as data rather than sent from here: the runner asks a **model** for these, recorded as
    an ask like any other. A runner that quietly authored requirements would have stopped being a
    runner.
    """
    return {
        "aspect": aspect,
        "description": BY_ASPECT[aspect],
        "minimum": MIN_OPTIONS,
        "asked_for": " / ".join(instructions) if instructions else "(no instruction given)",
        "question": (
            f"This has been asked for {ASK_LIMIT} times and not supplied: {BY_ASPECT[aspect]}. "
            f"Propose at least {MIN_OPTIONS} concrete, different options a person could pick "
            f"between. Do not pick one. Each option: what it is, and what it costs."),
    }


def read_options(answer: Mapping[str, object], aspect: str) -> List[str]:
    """The options a model came back with, refused if there are too few.

    Fewer than three is refused rather than shown. Two is a false choice and one is a decision
    wearing a question mark — and the point of reaching this stage at all was to stop the runner
    narrowing somebody else's decision.

    **Counted distinct, because the question asked for distinct.** `option_request`, twenty lines
    up, is the text this runner actually sends a model:

        Propose at least 3 concrete, *different* options a person could pick between.

    This counted the length of the list, so three copies of one label answered a question that had
    asked for three different ones — one option wearing a question mark three times. The runner
    asked for different and accepted identical, in the same module.

    Distinct by exact string, after the strip `_strings` already does. Not case-folded: `Fast` and
    `fast` are two labels a person can tell apart, and they may be two real things — identifiers,
    flags, filenames on a store that distinguishes them. Refusing those to catch a model repeating
    itself in different case would refuse more than it caught, and it could not detect a model
    repeating itself in different words anyway.
    """
    options = _strings((answer or {}).get("options"),
                       f"the options offered for {aspect!r}")
    distinct = len(set(options))
    if distinct < MIN_OPTIONS:
        raise IntakeError(
            f"asked for at least {MIN_OPTIONS} different options for {aspect!r} and got "
            f"{distinct} from {len(options)} offered. Two is a false choice and one is a decision "
            f"wearing a question mark; the point of asking was to widen the decision, not to "
            f"narrow it.")
    return options


def shown_digest(safety: Mapping[str, Sequence[str]]) -> str:
    """A name for **what was put in front of a person**, so a later flag can say it read this.

    Not a run id and not a brief hash. The ask journal's files carry neither, so a journal
    directory shared by two runs lets one brief's history answer for another's — measured by the
    risk seat this round. Digesting the findings themselves sidesteps that: an answer is accepted
    only against the findings it was given for, whichever run produced them.

    The seats are sorted and each seat's lines keep the order it gave them, because that is the
    order they were printed in. Two seats raising the same concern is not one concern.
    """
    shown = tuple(sorted((str(seat), tuple(str(line) for line in lines))
                         for seat, lines in safety.items()))
    return hashlib.sha256(repr(shown).encode("utf-8")).hexdigest()[:16]


def unsafe_reason(survey: Survey) -> str:
    """One plain sentence for a person, when a seat calls an otherwise complete requirement unsafe.

    Deliberately not `stop_reason`'s sentence. That one says the requirement does not *say* enough,
    and the answer to it is to say more. This one says the requirement says something a seat thinks
    is dangerous, and the answer to it is a decision — the two want different things from a person,
    which is what `Survey.safety`'s own docstring says.
    """
    seats = ", ".join(sorted(survey.safety))
    count = sum(len(lines) for lines in survey.safety.values())
    what, verb = ("finding", "says") if count == 1 else ("findings", "say")
    read = "Read it and decide." if count == 1 else "Read them and decide."
    return (f"{count} {what} from {seats} {verb} this requirement is unsafe. Nothing has been "
            f"planned or built — this stopped before any of that. {read}")


def proceeded_note(survey: Survey) -> str:
    """What goes in the relaxation ledger when a person read the findings and continued anyway."""
    seats = ", ".join(sorted(survey.safety))
    count = sum(len(lines) for lines in survey.safety.values())
    what = "finding" if count == 1 else "findings"
    return (f"intake_review ran past {count} unsafe {what} from {seats}: they were shown to a "
            f"person, who chose to continue")


def stop_reason(survey: Survey, history: Sequence[Mapping[str, object]],
                in_flight: bool = True) -> str:
    """One plain sentence for a person, naming what is missing and how often it has been asked.

    ``in_flight`` is `asks_including_this_one`'s, and it is here for the reason that function
    exists at all: `stop_reason` and `needs_options` answer the same question at the same moment,
    and a keyword given to one and not the other is CHG-20260903-42's defect back in a new spelling
    — the sentence saying *"asked 3 times"* beside a decision that counted two. One number, two
    readers, one input.

    **Zero has a spelling**, because `in_flight=False` made it reachable and a table that stopped
    at one produced *"asked 0 times"* (CHG-20260907-27, second round). A `serve` `start` against a
    persisted journal is the shape: the `RunState` is fresh so nothing is in `history`, every seat
    answers out of the journal so no session is opened, and the stop is neither recorded nor an
    ask. Measured rather than reasoned — the sentence was read off a real `Runner` started twice on
    one journal — and `test_the_same_brief_started_twice_says_one_number` is where it is pinned.

    The page is deliberately **not** given the same word. `console/index.html` renders its count
    only where options are on the table, and options need `ASK_LIMIT` asks, so nothing the console
    can draw counts zero. Prose nothing can produce is what this record already had to withdraw a
    mutation entry for.
    """
    parts = []
    for aspect in survey.missing:
        seen = asks_including_this_one(history, aspect, in_flight)
        nth = {0: "not asked yet", 1: "asked once",
               2: "asked twice"}.get(seen, f"asked {seen} times")
        parts.append(f"{BY_ASPECT[aspect]} ({nth})")
    joined = "; ".join(parts)
    return (f"The requirement does not say: {joined}. Nothing has been planned or built — this "
            f"stopped before any of that.")
