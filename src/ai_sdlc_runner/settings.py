"""settings.py — what the user sets, and where it is kept (CHG-20260823-05).

The requirement says it in one line: *預設有強制下限,但允許使用者開啟高風險模式來規避這個限制,
**在 GUI 上設定***. Until now the seat count and high-risk mode were command-line flags, and the
interactive part was a single confirmation shown at the moment the floor was crossed. That satisfies
"the user decides" and not "set it in the GUI".

## Why settings are a file rather than flags

A flag is a decision retyped every run, which means in practice it is a decision made once and then
copied out of shell history. These two in particular are worth persisting:

* **the seat count** describes how much review this project wants, which is a property of the project
  and not of a run;
* **high-risk mode** is the bypass, and a bypass that has to be re-typed each time is one that ends
  up in an alias.

Persisting it also gives the bypass somewhere to be *seen*. `runner settings` prints the current
state whether or not anybody is there to look at a prompt, so "we run below the floor" is a fact in
a file rather than a habit nobody wrote down.

## What settings may not do

**Settings cannot touch a gate verdict, a permanent halt, or the adjudication rule** —
`policy.py` owns those and takes no input, and `test_settings.py` asserts the absence rather
than trusting this paragraph.

What they *can* do is three things, not one. This paragraph said *"lower the seat floor and
can do nothing else"* while `FIELDS` held three names, and the third is not decorative
(CHG-20260903-28):

- `review_seats` — lowers the seat floor.
- `high_risk_mode` — changes what a high-risk change is put through.
- `ordinary_commands` — **vouches commands, so an undeclared target stops being refused.**
  Measured: `policy.unverified({kind: ordinary, targets: ['npm ci']}, ())` returns
  `('npm ci',)` with `on_trust=True`, which `engine.py` refuses on; vouching `npm` returns
  `()` with `on_trust=False`, and the run proceeds.

This module already guarded that field — `policy.py` records that `load` refuses certain
commands in `ordinary_commands` *"so the operator finds out while configuring"*. A guard
existed for the field whose existence the paragraph above it denied.

A file that is missing or empty yields the **defaults** — floor enforced, high-risk mode off. A file
that **exists and is malformed is an error**, not the defaults: falling back would make a typo
indistinguishable from a deliberate choice, and **two of the three settings here relax a
refusal**.
(This paragraph has now been corrected twice for the same class of error. It once said "or
corrupt yields the defaults" and contradicted `load()` directly below it; a verifier caught
that, and the code was right. It then said *two* settings while `FIELDS` held three, and a
seat caught that. A paragraph that counts the file it is in should be read against the file.)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Tuple

from . import paths, policy, tui

DEFAULT_PATH = "config/settings.json"

#: Exactly the keys a settings file may carry. Anything else is refused rather than ignored: a
#: setting nobody reads looks identical to a setting that works, and the whole point of this file is
#: that a relaxation is visible.
FIELDS: Tuple[str, ...] = ("review_seats", "high_risk_mode", "ordinary_commands")


class SettingsError(Exception):
    """Raised when a settings file says something this runner will not act on."""


@dataclass(frozen=True)
class Settings:
    """What the user has chosen. Defaults are the safe end of every axis."""

    #: How many review seats open. ``None`` means the floor.
    review_seats: Optional[int] = None
    #: Whether the seat floor may be crossed at all. Off unless somebody turned it on.
    high_risk_mode: bool = False
    #: Commands the operator vouches for as ordinary development work: `python`, `npm`, `docker`.
    #:
    #: This runner recognises **danger** (imperfectly, and every addition is safe) and recognises a
    #: plain repo path (decidably). It does **not** recognise safety in an arbitrary command, and
    #: two rounds of review proved what guessing costs: one version passed
    #: `cat /dev/urandom > /dev/sda` as ordinary, and the next stopped 10 of 10 real development
    #: commands. The operator knows their toolchain; this runner does not.
    #:
    #: Vouching is for the **tool**, never the whole command line. `policy._SUSPECT` still refuses
    #: `npm run release` from an operator who vouched for `npm` — otherwise this is the same
    #: prefix mistake one level out.
    ordinary_commands: Tuple[str, ...] = ()

    def seats(self) -> int:
        """The seat count a run would actually open.

        `policy.resolve_seats` **raises** on a request below the floor without the bypass — it will
        not lower a floor on its own authority, which is right for the policy. Settings answer a
        different question: "what happens if I run now", and the answer is the floor. Raising a
        count is the safe direction and is the only clamping done here; `describe()` says out loud
        when a request was raised, so it is reported rather than quietly overridden.
        """
        if self.review_seats is None:
            return policy.SEAT_FLOOR
        if self.review_seats < policy.SEAT_FLOOR and not self.high_risk_mode:
            return policy.SEAT_FLOOR
        return policy.resolve_seats(self.review_seats, self.high_risk_mode)

    def raised_to_the_floor(self) -> bool:
        """Is a request below the floor currently being ignored because the bypass is off?"""
        return (self.review_seats is not None
                and self.review_seats < policy.SEAT_FLOOR
                and not self.high_risk_mode)

    def below_floor(self) -> bool:
        return self.seats() < policy.SEAT_FLOOR

    def as_dict(self) -> dict:
        return {"review_seats": self.review_seats, "high_risk_mode": self.high_risk_mode,
                "ordinary_commands": list(self.ordinary_commands)}

    def describe(self) -> str:
        seats = self.seats()
        line = f"review seats: {seats}"
        if self.review_seats is None:
            line += " (the floor; nothing set)"
        elif self.raised_to_the_floor():
            line += (f" ({self.review_seats} requested, raised to the floor — turn on high-risk "
                     f"mode to actually run {self.review_seats})")
        if self.high_risk_mode:
            line += "  |  high-risk mode: ON"
            if self.below_floor():
                line += f" — running {seats} below the floor of {policy.SEAT_FLOOR}"
        else:
            line += "  |  high-risk mode: off"
        if self.ordinary_commands:
            line += f"  |  vouched commands: {', '.join(sorted(self.ordinary_commands))}"
        else:
            line += "  |  no vouched commands (only repo paths and read-only git are recognised)"
        return line


def load(path: str = DEFAULT_PATH) -> Settings:
    """Read the settings file, or the defaults.

    A missing file is the defaults, and so is an empty one. A file that **exists and is malformed**
    is an error rather than the defaults: silently falling back would make a typo indistinguishable
    from a deliberate choice, and two of the three settings here relax a refusal.
    """
    p = Path(path)
    if not p.is_file():
        return Settings()
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return Settings()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{path} is not valid JSON: {exc}. Fix it or delete it — this runner "
                            f"will not guess what a corrupt settings file meant.") from exc
    if not isinstance(raw, dict):
        raise SettingsError(f"{path} must hold a JSON object, got {type(raw).__name__}")

    unknown = sorted(set(raw) - set(FIELDS))
    if unknown:
        raise SettingsError(
            f"{path} sets {unknown}, which this runner does not read. This runner reads "
            f"{list(FIELDS)} and nothing else — gates, permanent halts and the "
            f"adjudication rule live in policy.py and take no input. A setting nobody "
            f"reads looks exactly like one that works.")

    seats = raw.get("review_seats")
    if seats is not None:
        if not isinstance(seats, int) or isinstance(seats, bool) or seats < 1:
            raise SettingsError(f"{path}: review_seats must be a whole number of at least 1, "
                                f"got {seats!r}")
    high_risk = raw.get("high_risk_mode", False)
    if not isinstance(high_risk, bool):
        raise SettingsError(f"{path}: high_risk_mode must be true or false, got {high_risk!r}")

    commands = raw.get("ordinary_commands", [])
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        raise SettingsError(f"{path}: ordinary_commands must be a list of command names, "
                            f"got {commands!r}")
    for command in commands:
        if command.strip().casefold() in policy.EXECUTORS:
            raise SettingsError(
                f"{path}: {command!r} cannot be vouched for. Its name says nothing about what it "
                f"will do — the argument is the program, so vouching for it vouches for anything it "
                f"can be told to do. `python -c '...'` and `python -m pytest` are the same command "
                f"as far as a name can tell.\n"
                f"  For an interpreter, vouch for the **tool you run through it**: with `pytest` "
                f"vouched, `python -m pytest` is recognised.\n"
                f"  For a one-off, declare the operation's kind on the work itself — a statement "
                f"about this piece of work rather than a standing permission.")
        if not command.strip() or len(command.split()) != 1:
            raise SettingsError(
                f"{path}: ordinary_commands holds {command!r}. Vouch for the **command**, one word "
                f"— `npm`, not `npm run build`. A whole command line here would be the prefix "
                f"mistake this setting exists to avoid.")

    return Settings(review_seats=seats, high_risk_mode=high_risk,
                    ordinary_commands=tuple(commands))


def save(settings: Settings, path: str = DEFAULT_PATH) -> None:
    """Write the settings file. Sorted keys and a trailing newline, so a diff is readable."""
    p = Path(path)
    paths.makedirs(p.parent)
    paths.write_text(p, json.dumps(settings.as_dict(), indent=2, sort_keys=True) + "\n")


def edit(settings: Settings, *, input_fn=input, stream_out=None) -> Optional[Settings]:
    """The GUI: one screen, one choice at a time, until the user leaves.

    Returns the settings to save, or ``None`` if the user backed out — cancelling changes nothing,
    which is what a cancel has to mean when one of the options is a safety bypass.
    """
    current = settings
    while True:
        choice = tui.select(
            f"Settings — {current.describe()}",
            [
                ("Review seats", f"currently {current.seats()}; the floor is {policy.SEAT_FLOOR}"),
                ("High-risk mode",
                 "ON — the seat floor may be crossed" if current.high_risk_mode
                 else "off — the seat floor is enforced"),
                ("Save and close", "write the choices above to the settings file"),
                ("Discard", "leave everything as it was"),
            ],
            input_fn=input_fn, stream_out=stream_out)

        if choice is None or choice == 3:
            return None
        if choice == 2:
            return current
        if choice == 0:
            current = _edit_seats(current, input_fn=input_fn, stream_out=stream_out)
        elif choice == 1:
            current = _toggle_high_risk(current, input_fn=input_fn, stream_out=stream_out)


def _edit_seats(current: Settings, *, input_fn, stream_out) -> Settings:
    """Pick a seat count. The options below the floor say so in the option itself."""
    options = [(f"{policy.SEAT_FLOOR} (the floor)", "every seat the panel is meant to have")]
    below = [n for n in range(1, policy.SEAT_FLOOR)]
    for n in below:
        options.append((f"{n}", f"below the floor — needs high-risk mode, and the run records it"))
    extra = policy.SEAT_FLOOR + 1
    if extra <= len(policy.SEATS):
        options.append((f"{extra}", "more review than the floor asks for"))

    choice = tui.select(f"How many review seats? (floor {policy.SEAT_FLOOR})", options,
                        input_fn=input_fn, stream_out=stream_out)
    if choice is None:
        return current
    values = [policy.SEAT_FLOOR] + below + ([extra] if extra <= len(policy.SEATS) else [])
    return replace(current, review_seats=values[choice])


def _toggle_high_risk(current: Settings, *, input_fn, stream_out) -> Settings:
    """Turning the bypass **on** asks; turning it off does not.

    An asymmetry on purpose. Re-enforcing a floor needs no ceremony — it can only make the run
    safer. Crossing one is the decision `tui.confirm_high_risk` exists to make visible, and it is
    reused here rather than reworded, so the operator sees the same sentence wherever they meet it.
    """
    if current.high_risk_mode:
        return replace(current, high_risk_mode=False)
    requested = current.review_seats if current.review_seats is not None else policy.SEAT_FLOOR
    if requested >= policy.SEAT_FLOOR:
        # Nothing is being crossed yet, so there is nothing to confirm — but the mode still says
        # "this project may cross the floor", so it is recorded as such rather than refused.
        return replace(current, high_risk_mode=True)
    if tui.confirm_high_risk(requested, policy.SEAT_FLOOR,
                             input_fn=input_fn, stream_out=stream_out):
        return replace(current, high_risk_mode=True)
    return current
