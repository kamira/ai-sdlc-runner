"""effects.py — ordered effects, each with a probe, so a killed run resumes at the right place.

CHG-20260822-04 task 6 (D6). The engine's crash-safety rests on one rule and one loop:

**The admissibility rule (D6.2).** An operation may be an effect **only if it leaves a probeable
postcondition** in the ledger, in git, or on the forge. Anything that cannot be probed is not
permitted as an effect and must be restructured until it can. That is enforced here rather than
documented: constructing an :class:`Effect` without a probe raises, so an unprobeable step cannot
reach the sequence at all.

**The resume loop (D6.3).** Effects are ordered and each carries its own probe. Resuming means
finding the **first unmet probe in order** and running from there. A partial state is therefore never
readable as "never started" — which is the failure the whole design exists to prevent.

The worked example that settled the design, and the one task 7's kill-and-resume test uses: a node
killed between ``git push`` and ``gh pr create``. ``git ls-remote origin <branch>`` reads met;
``gh pr list --head <branch>`` reads empty; the frontier is exactly "PR not created", and the engine
re-runs only the PR creation.

**Probes are the authority; there are no receipts** (D6.4/D6.5). Nothing here writes a "step done"
marker to be trusted later. ``state.json`` degrades to a cache: it may speed a resume up, but every
decision is made by re-probing the world, so a stale or absent cache changes nothing but latency.

One consequence worth stating because it is easy to get backwards: **a probe must describe the
postcondition, not the action.** "did we run push?" is a receipt question and cannot survive a crash;
"does the remote have this branch?" is a postcondition and can. A probe that inspects our own records
instead of the world reintroduces exactly the receipts this design refuses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

#: A probe answers "is this effect's postcondition already true?" by reading the world — the ledger,
#: git, or the forge — never by reading a record the runner itself wrote.
Probe = Callable[[], bool]
Apply = Callable[[], None]


class EffectError(Exception):
    """Raised when an effect sequence is inadmissible, or an effect fails to establish its own
    postcondition after running."""


@dataclass(frozen=True)
class Effect:
    """One ordered effect and the postcondition that proves it happened.

    ``probe`` is mandatory and is the whole reason this type exists: D6.2 makes probeability the
    admission criterion for being an effect at all, so there is deliberately no way to construct one
    without it.
    """

    name: str
    probe: Probe
    apply: Apply
    #: What the probe actually reads, in words, for the log and for review. An effect whose
    #: postcondition cannot be named in one line usually cannot be probed either.
    postcondition: str = ""

    def __post_init__(self) -> None:
        if not callable(self.probe):
            raise EffectError(
                f"effect {self.name!r} has no probe — D6.2: an operation may be an effect only if "
                f"it leaves a probeable postcondition. Restructure it until it can be probed.")
        if not callable(self.apply):
            raise EffectError(f"effect {self.name!r} has no apply")
        if not self.name:
            raise EffectError("every effect must be named — the name is what a resume log reports")


@dataclass
class EffectOutcome:
    """What one pass over a sequence did, in enough detail to explain a resume."""

    frontier: Optional[str] = None            # first effect whose probe was unmet, if any
    already_met: List[str] = field(default_factory=list)
    applied: List[str] = field(default_factory=list)
    #: Effects found already true *after* the frontier — the world is not in causal order. Usually
    #: the residue of an abandoned attempt. Neither redone nor waved through: surfaced.
    out_of_order: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "frontier": self.frontier,
            "already_met": list(self.already_met),
            "applied": list(self.applied),
            "out_of_order": list(self.out_of_order),
        }


def find_frontier(effects: Sequence[Effect]) -> Optional[int]:
    """Index of the first effect whose postcondition is not yet true, or ``None`` if all are.

    Ordered and short-circuiting on purpose: once an unmet probe is found, later probes are not
    consulted. A later effect whose postcondition happens to be true does not mean the earlier one
    can be skipped — effects are ordered because the order is causal, and probing past the frontier
    would invite exactly that misreading.
    """
    for index, effect in enumerate(effects):
        if not effect.probe():
            return index
    return None


def run(effects: Sequence[Effect], dry_run: bool = False) -> EffectOutcome:
    """Bring the sequence to completion from wherever it actually is.

    No effect whose postcondition is already true is ever applied — before the frontier or after it.
    Re-running one is at best wasted work and at worst a **duplicate side effect**, which is the
    accident D6 exists to prevent; "resume from the frontier" says where to start looking, not that
    everything past it may be redone blindly. An effect found true *after* the frontier is reported
    in ``out_of_order``: the world is not in causal order, usually because an earlier attempt was
    abandoned, and that is worth a human's attention rather than a silent redo or a silent pass.

    Each effect that *is* applied is then **re-probed**: one that runs without establishing its own
    postcondition is a bug in that effect, and failing loudly is what stops the engine from marching
    past a step that silently did nothing.

    ``dry_run`` probes and reports without applying, which is how a caller inspects the frontier
    before deciding to act.
    """
    outcome = EffectOutcome()
    start = find_frontier(effects)
    if start is None:
        outcome.already_met = [e.name for e in effects]
        return outcome

    outcome.already_met = [e.name for e in effects[:start]]
    outcome.frontier = effects[start].name
    if dry_run:
        return outcome

    for effect in effects[start:]:
        # Re-probe each one rather than applying everything past the frontier blindly. An effect
        # whose postcondition is *already* true must not be applied again: `gh pr create` against
        # an existing PR is a duplicate side effect, and "resume from the frontier" was never a
        # licence to redo work that is demonstrably done.
        if effect.probe():
            # Met, but something earlier was not — the world is out of causal order, which usually
            # means an abandoned earlier attempt left this behind. Reported rather than silently
            # accepted or silently redone: both of those turn a suspicious state into a confident one.
            outcome.already_met.append(effect.name)
            outcome.out_of_order.append(effect.name)
            continue
        effect.apply()
        if not effect.probe():
            raise EffectError(
                f"effect {effect.name!r} ran but its postcondition is still not true "
                f"({effect.postcondition or 'no postcondition described'}). Refusing to continue: "
                f"a step that reports success without leaving evidence is the false-green this "
                f"design exists to prevent.")
        outcome.applied.append(effect.name)
    return outcome
