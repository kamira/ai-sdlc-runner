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

**Settings cannot change what a gate verdict is, which kinds are permanent halts, or the
adjudication rule** — `policy.GATES`, `policy.PERMANENT_HALT_KINDS` and `policy.adjudicate` own
those and take no input from here.

**Two of the six fields do change whether a stop happens**, and this paragraph used to deny it
(CHG-20260903-47, defect seat L-13). Measured:

- `review_seats=1` makes `undecided` **unreachable**: one seat cannot split, and `undecided` is the
  outcome that means a person must break the tie. The rule is unchanged; the input that could
  produce that output is gone.
- `ordinary_commands` decides whether the `unrecognised-target` halt trips at all — which the third
  bullet below has said in as many words since CHG-20260903-28, three lines under a sentence
  denying it.

`test_settings.py` asserts both of those by **measurement** now. It previously asserted
`FIELDS == (...)` and an `as_dict` key set under this claim's name — green on the defect, red on a
rename.

What the first three *can* do is three things, not one. This paragraph once named the seat floor as the
whole of what settings reach, while `FIELDS` held three names and the third is not
decorative (CHG-20260903-28). It is described rather than quoted here because the guard
that forbids it reads this file as flowed text, and a guard cannot tell a claim from an
account of one (CHG-20260904-19):

- `review_seats` — asks for a seat count. **On its own it lowers nothing**:
  `Settings(review_seats=1).seats()` is `3`, because `seats()` clamps to the floor and
  `policy.resolve_seats` raises rather than lowering one on its own authority.
- `high_risk_mode` — lets `review_seats` go below the floor, and **only that**. Measured:
  `policy.verdict(gate, risk, autonomy, change_class)` has no such parameter, so what a
  high-risk *change* is put through is untouched; with `review_seats` unset the field
  changes nothing at all. The pair is the bypass, which the paragraph above this list
  already says — *high-risk mode is the bypass* — and this bullet did not
  (CHG-20260904-19, idiom seat).
- `ordinary_commands` — **vouches commands, so an undeclared target stops being refused.**
  Measured: `policy.unverified({kind: ordinary, targets: ['npm ci']}, ())` returns
  `('npm ci',)` with `on_trust=True`, which `engine.py` refuses on; vouching `npm` returns
  `()` with `on_trust=False`, and the run proceeds.

The last two (CHG-20261005-01) choose a backend and say nothing about a verdict, a halt or a floor:

- `coder_model` — the registry model that builds when nothing is assigned to `engineer_build`.
  Empty means the registry's only `mid`-tier model, if there is exactly one, and only when no
  `agent_command` is configured. `none` means no default coder model at all (a No in `runner
  setup`). Otherwise it is not checked against a registry here, because the registry lives
  elsewhere; a run that cannot find it refuses.
- `coder_effort` — `low`, `medium` or `high`, for `engineer_build` and the nodes that follow it.
  Whether the model can be told is its own `effort_argv`; where it cannot, the run says so.

This module already guarded that field — `policy.py` records that `load` refuses certain
commands in `ordinary_commands` *"so the operator finds out while configuring"*. A guard
existed for the field whose existence the paragraph above it denied.

A file that is missing or empty yields the **defaults** — floor enforced, high-risk mode off. A file
that **exists and is malformed is an error**, not the defaults: falling back would make a typo
indistinguishable from a deliberate choice, and **two of the six settings here relax a
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

from . import models, paths, policy, tui

DEFAULT_PATH = "config/settings.json"

#: Exactly the keys a settings file may carry. Anything else is refused rather than ignored: a
#: setting nobody reads looks identical to a setting that works, and the whole point of this file is
#: that a relaxation is visible.
FIELDS: Tuple[str, ...] = ("review_seats", "high_risk_mode", "ordinary_commands",
                           "coder_model", "coder_effort", "review_dimensions")

#: The efforts `coder_effort` may name. The runner passes the word through a model's own
#: `effort_argv` template and knows nothing more about it.
EFFORTS: Tuple[str, ...] = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"

#: The `coder_model` value that means *no default coder model*: `runner setup` records a user's No
#: with it (CHG-20261005-01, review round 3). Empty cannot carry that, because empty is "the
#: registry's only `mid` model", which would pick the model that was just declined. The registry
#: refuses new models with this id (`models.RESERVED_ID`); one that predates the rule still loads,
#: warns, and is never the coder: this value always reads as the refusal, `coder_defaults`
#: skips it in the lone-`mid` rule, and refuses an `engineer_build` assignment naming it.
NO_CODER = models.RESERVED_ID


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
    #: The registry model that builds when nothing is assigned to `engineer_build`
    #: (CHG-20261005-01). Empty means the registry's only `mid` model, if there is exactly one and
    #: no `agent_command` is configured; `NO_CODER` means none, whatever the registry holds.
    #: Not checked against a registry here: the registry lives elsewhere, so an unknown id is an
    #: error when a run resolves it (`cli.coder_defaults`), not when it is saved.
    coder_model: str = ""
    #: The effort for `engineer_build` and the nodes that follow it. Other nodes get none.
    coder_effort: str = DEFAULT_EFFORT
    #: The seats the user chose, in the order they open (CHG-20261005-02). ``None`` is today's
    #: behaviour: a prefix of `policy.SEATS` sized by `review_seats`. When it is set it **replaces**
    #: that prefix and `review_seats` is ignored — `describe()` says so. The floor applies to its
    #: length, and only high-risk mode lowers it.
    review_dimensions: Optional[Tuple[str, ...]] = None

    def seats(self) -> int:
        """The seat count a run would actually open.

        `policy.resolve_seats` **raises** on a request below the floor without the bypass — it will
        not lower a floor on its own authority, which is right for the policy. Settings answer a
        different question: "what happens if I run now", and the answer is the floor. Raising a
        count is the safe direction and is the only clamping done here; `describe()` says out loud
        when a request was raised, so it is reported rather than quietly overridden.
        """
        if self.review_dimensions is not None:
            return len(self.review_dimensions)
        if self.review_seats is None:
            return policy.SEAT_FLOOR
        if self.review_seats < policy.SEAT_FLOOR and not self.high_risk_mode:
            return policy.SEAT_FLOOR
        return policy.resolve_seats(self.review_seats, self.high_risk_mode)

    def raised_to_the_floor(self) -> bool:
        """Is a request below the floor currently being ignored because the bypass is off?"""
        return (self.review_dimensions is None
                and self.review_seats is not None
                and self.review_seats < policy.SEAT_FLOOR
                and not self.high_risk_mode)

    def seats_requested(self) -> int:
        """What this file asks for, before the floor is applied. `seats()` is what it gets."""
        if self.review_dimensions is not None:
            return len(self.review_dimensions)
        return self.review_seats if self.review_seats is not None else policy.SEAT_FLOOR

    def below_floor(self) -> bool:
        return self.seats() < policy.SEAT_FLOOR

    def as_dict(self) -> dict:
        return {"review_seats": self.review_seats, "high_risk_mode": self.high_risk_mode,
                "ordinary_commands": list(self.ordinary_commands),
                "coder_model": self.coder_model, "coder_effort": self.coder_effort,
                "review_dimensions": (list(self.review_dimensions)
                                      if self.review_dimensions is not None else None)}

    def describe(self) -> str:
        seats = self.seats()
        line = f"review seats: {seats}"
        if self.review_dimensions is not None:
            line += (f" ({', '.join(self.review_dimensions)} — review_dimensions is set, so "
                     f"review_seats is ignored)")
        elif self.review_seats is None:
            line += " (the floor; nothing set)"
        elif self.raised_to_the_floor():
            line += (f" ({self.review_seats} requested, raised to the floor — turn on high-risk "
                     f"mode to actually run {self.review_seats})")
        no_veto = (policy.vetoes_missing(self.review_dimensions)
                   if self.review_dimensions is not None else [])
        if no_veto:
            line += f"  |  no veto seat open ({', '.join(no_veto)} is not named)"
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
        line += ("  |  coder model: none (declined; no default coder model)"
                 if models.is_reserved(self.coder_model) else
                 f"  |  coder model: {self.coder_model}" if self.coder_model
                 else "  |  coder model: the registry's only mid-tier model, if there is one")
        line += f"  |  coder effort: {self.coder_effort}"
        return line


def load(path: str = DEFAULT_PATH) -> Settings:
    """Read the settings file, or the defaults.

    A missing file is the defaults, and so is an empty one. A file that **exists and is malformed**
    is an error rather than the defaults: silently falling back would make a typo indistinguishable
    from a deliberate choice, and two of the six settings here relax a refusal.
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

    seats = _check_seats(raw.get("review_seats"), where=path)

    high_risk = raw.get("high_risk_mode", False)
    if not isinstance(high_risk, bool):
        raise SettingsError(f"{path}: high_risk_mode must be true or false, got {high_risk!r}")

    commands = raw.get("ordinary_commands", [])
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        raise SettingsError(f"{path}: ordinary_commands must be a list of command names, "
                            f"got {commands!r}")

    coder_model = _check_coder_model(raw.get("coder_model", ""), where=path)
    coder_effort = _check_effort(raw.get("coder_effort", DEFAULT_EFFORT), where=path)
    dimensions = _check_dimensions(raw.get("review_dimensions"), high_risk, where=path)

    # **Stored as it was validated** (CHG-20260904-17). The checks below strip and `recognise`
    # casefolds without stripping, so `"  npm  "` loaded clean, appeared in `describe()`, and
    # matched nothing — which is the failure `FIELDS`' own comment names, produced by this
    # validator.
    return Settings(review_seats=seats, high_risk_mode=high_risk,
                    ordinary_commands=_check_vouched(commands, where=path),
                    coder_model=coder_model, coder_effort=coder_effort,
                    review_dimensions=dimensions)


def _check_dimensions(value, high_risk_mode: bool, *, where: str = "settings"):
    """The chosen seats as a tuple, or `None`. Unknown names, repeats and a count below the floor
    are refused by `policy.resolve_dimensions` — the same floor, the same message, as a count."""
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or not all(isinstance(n, str) for n in value):
        raise SettingsError(f"{where}: review_dimensions must be a list of seat names or null, "
                            f"got {value!r}")
    try:
        return tuple(policy.resolve_dimensions(value, high_risk_mode))
    except policy.PolicyError as exc:
        raise SettingsError(f"{where}: review_dimensions: {exc}") from exc


def _check_coder_model(value, *, where: str = "settings") -> str:
    """The coder model's id, stripped, or empty (or `NO_CODER`). Its existence is checked where a
    registry is."""
    if not isinstance(value, str):
        raise SettingsError(f"{where}: coder_model must be a model id or empty, got {value!r}")
    return value.strip()


def _check_effort(value, *, where: str = "settings") -> str:
    if value not in EFFORTS:
        raise SettingsError(f"{where}: coder_effort must be one of {list(EFFORTS)}, got {value!r}")
    return value


def _check_seats(seats, *, where: str = "settings"):
    """The seat count, or `None`. Bounded **at both ends**.

    The lower bound was here from the start; there was no upper one, and `policy.seat_names`
    refuses anything above `policy.MAX_SEAT_COUNT`. So `{"review_seats": 5}` loaded, and every surface
    that renders it — `runner settings --show`, the edit screen's own header — raised `PolicyError`
    out of a `cmd_settings` that catches `SettingsError` only. The command built to make a bypass
    visible *"whether or not anybody is there to look at a prompt"* was the one that tracebacked
    (CHG-20260904-17, defect and conformance seats).
    """
    if seats is None:
        return None
    if not isinstance(seats, int) or isinstance(seats, bool) or seats < 1:
        raise SettingsError(f"{where}: review_seats must be a whole number of at least 1, "
                            f"got {seats!r}")
    if seats > policy.MAX_SEAT_COUNT:
        raise SettingsError(
            f"{where}: review_seats is {seats} and a seat count opens at most "
            f"{policy.MAX_SEAT_COUNT}: {', '.join(s.name for s in policy.PREFIX_SEATS)}. Asking "
            f"for more opens none of them — the panel is the seats that exist, not a number. "
            f"The opt-in seats ({', '.join(s.name for s in policy.SEATS if s.opt_in)}) open only "
            f"when review_dimensions names them.")
    return seats


def _check_vouched(commands, *, where: str = "settings"):
    """The vouched commands, stripped, or a `SettingsError` naming why one was refused.

    Read by `load`, by `save` and by the screen, so the three cannot disagree about what a vouch
    is. `save` had no validation at all and could write three shapes `load` then refused, which
    left the GUI unable to open on a file it had written itself (CHG-20260904-17, defect seat).
    """
    out = []
    for command in commands:
        name = command.strip()
        if name.casefold() in policy.EXECUTORS:
            raise SettingsError(
                f"{where}: {command!r} cannot be vouched for. Its name says nothing about what it "
                f"will do — the argument is the program, so vouching for it vouches for anything "
                f"it can be told to do. `python -c '...'` and `python -m pytest` are the same "
                f"command as far as a name can tell.\n"
                f"  For an interpreter, vouch for the **tool you run through it**: with `pytest` "
                f"vouched, `python -m pytest` is recognised.\n"
                f"  For a one-off, declare the operation's kind on the work itself — a statement "
                f"about this piece of work rather than a standing permission.")
        if not name or len(name.split()) != 1:
            raise SettingsError(
                f"{where}: ordinary_commands holds {command!r}. Vouch for the **command**, one "
                f"word — `npm`, not `npm run build`. A whole command line here would be the prefix "
                f"mistake this setting exists to avoid.")
        out.append(name)
    return tuple(out)


def save(settings: Settings, path: str = DEFAULT_PATH) -> None:
    """Write the settings file. Sorted keys and a trailing newline, so a diff is readable.

    **Validated before it is written** (CHG-20260904-17, defect seat L-62). Every check in this
    module used to be on the read side, so `save` could write `review_seats=0`, a multi-word vouch
    or a vouch on the executor list — three shapes `load` then refuses, on the path `cmd_settings`
    takes before it renders the screen. The GUI could lock itself out of a file it had written, and
    the only way back was hand-editing JSON.
    """
    _check_seats(settings.review_seats, where=path)
    _check_vouched(settings.ordinary_commands, where=path)
    _check_coder_model(settings.coder_model, where=path)
    _check_effort(settings.coder_effort, where=path)
    _check_dimensions(settings.review_dimensions, settings.high_risk_mode, where=path)
    p = Path(path)
    paths.makedirs(p.parent)
    paths.write_text(p, json.dumps(settings.as_dict(), indent=2, sort_keys=True) + "\n")


def edit(settings: Settings, *, input_fn=input, stream_out=None) -> Optional[Settings]:
    """The GUI: one screen, one choice at a time, until the user leaves.

    Returns the settings to save, or ``None`` if the user backed out — cancelling changes nothing,
    which is what a cancel has to mean when one of the options is a safety bypass.

    **Keyed by name, not by index** (CHG-20260904-17, idiom seat). `tui.select` returns a bare
    position, and this compared it to the literals `2` and `3` while the labels lived in a separate
    list. Adding the missing `ordinary_commands` row in the obvious place therefore moved `Save and
    close` to 3 and `Discard` to 4 — so typing 3 saved nothing and typing 4 discarded — with the
    whole suite green, because nothing in the repository asserted what label sits at any index.

    Everywhere else this repository maps a name to an effect by name: `policy.GATES`,
    `policy.BY_SEAT`, `policy.BY_ROLE`, `graph.BY_ID`, `FIELDS`. This was the one place that did
    not, and it is the one place a wrong answer writes a safety bypass to disk.
    """
    current = settings
    while True:
        rows = _screen(current)
        choice = tui.select(f"Settings — {current.describe()}", [row[:2] for row in rows],
                            input_fn=input_fn, stream_out=stream_out)
        if choice is None:
            return None
        _, _, effect = rows[choice]
        if effect is _SAVE:
            return current
        if effect is _DISCARD:
            return None
        current = effect(current, input_fn=input_fn, stream_out=stream_out)


#: The two effects that end the screen. Sentinels rather than strings, so a row cannot be given an
#: effect by writing a label that happens to match one.
_SAVE = object()
_DISCARD = object()


def _screen(current: Settings):
    """The rows, each carrying its own effect. One list, so a label and what it does cannot drift.

    Every name in `FIELDS` has a row here — asserted by
    `test_every_setting_is_reachable_from_the_screen`, which reads `FIELDS` rather than counting.
    """
    return [
        ("Review seats", f"currently {current.seats()}; the floor is {policy.SEAT_FLOOR}",
         _edit_seats),
        ("Review dimensions",
         ", ".join(current.review_dimensions) if current.review_dimensions is not None
         else "not set — the first review_seats seats open, in the shipped order",
         _edit_dimensions),
        ("High-risk mode",
         "ON — the seat floor may be crossed" if current.high_risk_mode
         else "off — the seat floor is enforced",
         _toggle_high_risk),
        ("Vouched commands",
         ", ".join(current.ordinary_commands) if current.ordinary_commands
         else "none — every target is read against the halts",
         _edit_vouched),
        ("Coder model",
         "none — declined; no default coder model" if models.is_reserved(current.coder_model)
         else current.coder_model if current.coder_model
         else "the registry's only mid-tier model, if there is exactly one",
         _edit_coder_model),
        ("Coder effort", f"currently {current.coder_effort}; engineer_build and what follows it",
         _edit_coder_effort),
        ("Save and close", "write the choices above to the settings file", _SAVE),
        ("Discard", "leave everything as it was", _DISCARD),
    ]


def _seat_options():
    """The seat counts a person may pick, each paired with the value it yields.

    One list rather than two. `options` and `values` were parallel lists with
    `extra <= policy.MAX_SEAT_COUNT` written twice, so a value could drift from the label above it and
    nothing would say so (CHG-20260904-17).
    """
    rows = [(f"{policy.SEAT_FLOOR} (the floor)", "every seat the panel is meant to have",
             policy.SEAT_FLOOR)]
    for n in range(1, policy.SEAT_FLOOR):
        rows.append((f"{n}", "below the floor — needs high-risk mode, and the run records it", n))
    extra = policy.SEAT_FLOOR + 1
    if extra <= policy.MAX_SEAT_COUNT:
        rows.append((f"{extra}", "more review than the floor asks for", extra))
    return rows


def _edit_seats(current: Settings, *, input_fn, stream_out) -> Settings:
    """Pick a seat count. The options below the floor say so in the option itself."""
    rows = _seat_options()
    choice = tui.select(f"How many review seats? (floor {policy.SEAT_FLOOR})",
                        [row[:2] for row in rows], input_fn=input_fn, stream_out=stream_out)
    if choice is None:
        return current
    return _crossing(current, replace(current, review_seats=rows[choice][2]),
                     input_fn=input_fn, stream_out=stream_out)


def _edit_dimensions(current: Settings, *, input_fn, stream_out) -> Settings:
    """Pick the seats that open. A multi-select built on `tui.select`: each pick toggles a seat, and
    the order they were switched on is the order they open. Done keeps the choice; Clear unsets it.

    A choice below the floor goes through `tui.confirm_high_risk` like a seat count does, and
    declining leaves the settings as they were — the screen cannot write what `load` refuses.
    """
    chosen = list(current.review_dimensions or ())
    while True:
        rows = [(f"[{'x' if seat.name in chosen else ' '}] {seat.name}",
                 f"{seat.label}{' — off unless chosen' if seat.opt_in else ''}",
                 seat.name) for seat in policy.SEATS]
        rows.append(("Done", f"open {len(chosen)} seat(s), in the order ticked", None))
        rows.append(("Clear", "unset review_dimensions; review_seats decides again", ""))
        choice = tui.select(f"Review dimensions (floor {policy.SEAT_FLOOR})",
                            [row[:2] for row in rows], input_fn=input_fn, stream_out=stream_out)
        if choice is None:
            return current
        name = rows[choice][2]
        if name == "":
            return replace(current, review_dimensions=None)
        if name is None:
            break
        if name in chosen:
            chosen.remove(name)
        else:
            chosen.append(name)
    if not chosen:
        return replace(current, review_dimensions=None)
    after = replace(current, review_dimensions=tuple(chosen))
    missing = policy.vetoes_missing(chosen)
    if missing and not current.high_risk_mode:
        # `load` refuses this list without the mode, so the screen does not write it. Turn the mode
        # on first — a panel with no veto is a decision, not a side effect of a tick.
        if stream_out is not None:
            print(f"not kept: {missing} is the veto seat, and a list without it needs high-risk "
                  f"mode. Turn that on first, or tick {missing[0]}.", file=stream_out)
        return current
    if len(chosen) < policy.SEAT_FLOOR and not current.high_risk_mode:
        if not tui.confirm_high_risk(len(chosen), policy.SEAT_FLOOR,
                                     input_fn=input_fn, stream_out=stream_out):
            return current
        after = replace(after, high_risk_mode=True)
    return after


def _edit_vouched(current: Settings, *, input_fn, stream_out) -> Settings:
    """Add or remove a vouched command.

    **The field the screen could not reach** (CHG-20260904-17, idiom seat 2a). `engine.py` refuses
    an unrecognised target by telling the operator to *"Vouch for the command in settings
    (`ordinary_commands`)"*, and the screen this repository built for that requirement had no row
    for it — only two settings were reachable, in the module whose premise is 「在 GUI 上設定」.

    A vouch is validated here with the same function `load` uses, so the screen cannot write a file
    the screen will not open.
    """
    rows = [("Add a command", "one word — the tool, never a command line", None)]
    for name in current.ordinary_commands:
        rows.append((f"Remove {name}", "stop treating it as ordinary", name))

    choice = tui.select("Vouched commands", [row[:2] for row in rows],
                        input_fn=input_fn, stream_out=stream_out)
    if choice is None:
        return current
    if rows[choice][2] is not None:
        return replace(current, ordinary_commands=tuple(
            n for n in current.ordinary_commands if n != rows[choice][2]))

    said = str(input_fn("Command to vouch for (blank to cancel): ") or "").strip()
    if not said:
        return current
    try:
        _check_vouched([said])
    except SettingsError as refused:
        if stream_out is not None:
            print(f"not vouched: {refused}", file=stream_out)
        return current
    return replace(current, ordinary_commands=current.ordinary_commands + (said,))


def _edit_coder_model(current: Settings, *, input_fn, stream_out) -> Settings:
    """Name the model that builds, or clear it. The registry is not read here, so a typo is caught
    when a run resolves it, which says so by name."""
    said = str(input_fn(f"Model id for the coding role ({NO_CODER} for no default, "
                        f"blank to clear; a registry model called {NO_CODER} cannot be the coder): ") or "").strip()
    return replace(current, coder_model=said)


def _edit_coder_effort(current: Settings, *, input_fn, stream_out) -> Settings:
    rows = [(name, "the default" if name == DEFAULT_EFFORT else "", name) for name in EFFORTS]
    choice = tui.select("Effort for the coding role", [row[:2] for row in rows],
                        input_fn=input_fn, stream_out=stream_out)
    if choice is None:
        return current
    return replace(current, coder_effort=rows[choice][2])


def _toggle_high_risk(current: Settings, *, input_fn, stream_out) -> Settings:
    """Turning the bypass **on** asks; turning it off does not.

    An asymmetry on purpose. Re-enforcing a floor needs no ceremony — it can only make the run
    safer. Crossing one is the decision `tui.confirm_high_risk` exists to make visible, and it is
    reused here rather than reworded, so the operator sees the same sentence wherever they meet it.
    """
    if current.high_risk_mode:
        if (current.review_dimensions is not None
                and len(current.review_dimensions) < policy.SEAT_FLOOR):
            # Not clamped, as a seat count is: a named list cannot be raised to the floor without
            # choosing seats for the user, and `load` refuses it. Say so rather than write it.
            if stream_out is not None:
                print(f"kept on: review_dimensions names {len(current.review_dimensions)} seat(s), "
                      f"below the floor of {policy.SEAT_FLOOR}. Choose more first.",
                      file=stream_out)
            return current
        if (current.review_dimensions is not None
                and policy.vetoes_missing(current.review_dimensions)):
            if stream_out is not None:
                print(f"kept on: review_dimensions leaves out "
                      f"{policy.vetoes_missing(current.review_dimensions)}, the veto seat. Choose "
                      f"it first.", file=stream_out)
            return current
        return replace(current, high_risk_mode=False)
    return _crossing(current, replace(current, high_risk_mode=True),
                     input_fn=input_fn, stream_out=stream_out)


def _crossing(before: Settings, after: Settings, *, input_fn, stream_out) -> Settings:
    """`after`, if it does not newly cross the floor, or if the person says it may.

    **Bound to the crossing, not to the toggle** (CHG-20260904-18, defect and risk seats). The
    confirmation used to live in `_toggle_high_risk`, which returns early when nothing is being
    crossed *yet* — and `_edit_seats` never asked at all. So two edits, neither a crossing on its
    own, composed into one that was never confirmed:

        seats -> 1, then the bypass on    the confirmation is shown
        the bypass on, then seats -> 1    it is not, and the result is identical

    Asking here means the question follows the state the two edits reach together, in whichever
    order a person gets there. Re-enforcing a floor still asks nothing: it can only make the run
    safer, which is the asymmetry `_toggle_high_risk` was written for and keeps.
    """
    if not after.below_floor() or before.below_floor():
        return after
    if tui.confirm_high_risk(after.seats_requested(), policy.SEAT_FLOOR,
                             input_fn=input_fn, stream_out=stream_out):
        return after
    return before
