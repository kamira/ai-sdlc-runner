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


def _strings(value) -> List[str]:
    """Read a seat's answer generously in shape and strictly in content."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def collect(answers: Mapping[str, Mapping[str, object]]) -> Survey:
    """Aggregate the seats' answers. Union of problems, union of missing aspects.

    ``answers`` is ``seat -> {"problems": [...], "missing": [...], "unsafe": [...]}``.

    An aspect a seat names that is not in ``ASPECTS`` is an error rather than a shrug: a seat
    reporting `"database"` missing has answered a question this runner did not ask, and quietly
    dropping it would lose a real observation while looking like agreement.
    """
    survey = Survey()
    missing: List[str] = []
    for seat in sorted(answers):
        answer = answers[seat] or {}
        problems = _strings(answer.get("problems"))
        if problems:
            survey.problems[seat] = problems
        unsafe = _strings(answer.get("unsafe"))
        if unsafe:
            survey.safety[seat] = unsafe
        for aspect in _strings(answer.get("missing")):
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


def needs_options(history: Sequence[Mapping[str, object]], aspect: str) -> bool:
    """Has asking for this aspect failed often enough to stop asking?

    ``>=`` rather than ``>``: the third unanswered ask is the one that has failed, not the fourth.
    """
    return times_asked(history, aspect) >= ASK_LIMIT


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
    """
    options = _strings((answer or {}).get("options"))
    if len(options) < MIN_OPTIONS:
        raise IntakeError(
            f"asked for at least {MIN_OPTIONS} options for {aspect!r} and got {len(options)}. Two "
            f"is a false choice and one is a decision wearing a question mark; the point of asking "
            f"was to widen the decision, not to narrow it.")
    return options


def stop_reason(survey: Survey, history: Sequence[Mapping[str, object]]) -> str:
    """One plain sentence for a person, naming what is missing and how often it has been asked."""
    parts = []
    for aspect in survey.missing:
        seen = times_asked(history, aspect) + 1
        nth = {1: "asked once", 2: "asked twice"}.get(seen, f"asked {seen} times")
        parts.append(f"{BY_ASPECT[aspect]} ({nth})")
    joined = "; ".join(parts)
    return (f"The requirement does not say: {joined}. Nothing has been planned or built — this "
            f"stopped before any of that.")
