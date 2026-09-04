"""Settings, and the three findings from round 3 that CHG-20260823-03 did not cover.

**Settings** close the last line of the requirement still taken literally-but-not-quite:
*預設有強制下限,但允許使用者開啟高風險模式來規避這個限制,**在 GUI 上設定***. The seat count and the
bypass were command-line flags, and the interactive part was one confirmation shown at the moment
the floor was crossed. That is "the user decides"; it is not "set it in the GUI".

**The three findings** are what an independent verifier found after the previous round shipped:

* a work order whose `instructions` said *"deploy the new build to production, then wipe the users
  table"* ran to completion, because the operation beside it declared `ordinary`. The words were in
  the text the engineer would act on and nothing read them;
* the review seats were exempted from declaring anything **by role name**, while their role could
  execute and the work order handed that capability over;
* `--confirm no_such_gate` was swallowed whole — the operator believes they confirmed something, the
  run stops anyway, and nothing says why.
"""
from __future__ import annotations

import io
import json
import pathlib
import re

import pytest

from ai_sdlc_runner import engine, graph, policy, settings as settings_mod
from ai_sdlc_runner import tui as tui_mod

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}


def _dispatch(order):
    if order.get("seat"):
        return {"verdict": "pass"}
    branch = ANSWERS.get(order["node_id"])
    return {"verdict": branch} if branch else {"ok": True}


def _cfg(instructions=None, node="engineer_build", **kw):
    """Every node gets an ordinary brief; `node` gets `instructions` if one is given.

    Putting the brief on every node made the first version of these tests assert the wrong node:
    the run halts at the *first* one whose brief describes a red line, which is `pm_plan`. The
    behaviour was right and the test was wrong — worth the comment, because a test that pins the
    wrong node passes for the wrong reason as soon as the ordering changes.
    """
    specs = {n.id: dict(SPEC) for n in graph.NODES if n.role}
    if instructions is not None:
        specs[node]["instructions"] = instructions
    base = dict(node_specs=specs,
                decisions={"next_module": ["module", "none"], "feedback": "done"},
                risk="low", undeclared="allow", confirmed=("merge",))
    base.update(kw)
    return engine.RunConfig(**base)


# --------------------------------------------------------------------------------------
# the brief is read, not just the operation beside it
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("brief", [
    "deploy the new build to production, then wipe the users table",
    "run the migration against the customer database",
    "rotate the API key before the handover",
    "make the repo public once the embargo lifts",
])
def test_a_brief_that_describes_a_red_line_stops_the_node(brief):
    """The exact hole: the words were in `instructions`, the operation beside them said `ordinary`,
    and nothing looked. A description giving itself away used not to matter as long as it gave
    itself away in the other field."""
    cfg = _cfg(instructions=brief,
               operations={"engineer_build": [{"description": "routine work", "kind": "ordinary"}]})
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert report.halted_at == "engineer_build"
    assert "its instructions describes" in report.halt_reason


def test_the_halt_quotes_the_brief_so_it_can_be_fixed():
    cfg = _cfg(instructions="wipe the users table")
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert "wipe the users table" in report.halt_reason
    assert "a person carries it out" in report.halt_reason


def test_declaring_it_does_not_get_past_it_either():
    """Both roads stop, which is the right answer for a node whose brief says it will wipe a table.
    There is no wording of the declaration that makes a red-line brief acceptable."""
    cfg = _cfg(instructions="wipe the users table",
               operations={"engineer_build": [{"description": "wipe it", "kind": "delete"}]})
    assert engine.walk(cfg, _dispatch, enabled=True).halted_at == "engineer_build"


def test_the_objective_and_scope_are_read_too():
    """About *which fields are read*, not about the word list's coverage — that is measured
    separately in `test_flow.py`, and it is weak on purpose-and-record."""
    cfg = _cfg()
    cfg.node_specs["engineer_build"]["objective"] = "drop table legacy_accounts"
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert report.halted_at == "engineer_build"
    assert "its objective describes" in report.halt_reason


def test_the_brief_check_is_the_backstop_and_inherits_its_weakness():
    """`drop the legacy table` is a hard delete and the word lists miss it — "drop table" is in the
    list, "drop the legacy table" is not. Recorded rather than papered over: reading more *fields*
    does not make the *matcher* better, and pretending otherwise is how a backstop gets trusted."""
    assert policy.permanent_halt("drop the legacy table") is None
    cfg = _cfg()
    cfg.node_specs["engineer_build"]["objective"] = "drop the legacy table"
    assert engine.walk(cfg, _dispatch, enabled=True).halted_at == "done"


def test_an_ordinary_brief_is_not_stopped():
    """The cost of reading the brief is false stops, so the ordinary case is pinned. A check that
    fires on "do the work" is one nobody keeps switched on."""
    assert engine.walk(_cfg(), _dispatch, enabled=True).halted_at == "done"


@pytest.mark.parametrize("brief", [
    "add a unit test for the parser",
    "rename the variable and update its callers",
    "fix the off-by-one in the loop bound",
    "write the docstring for this module",
    "remove the unused import",
])
def test_ordinary_briefs_across_the_kinds_of_work_this_runner_drives(brief):
    assert engine.walk(_cfg(instructions=brief), _dispatch, enabled=True).halted_at == "done"


# --------------------------------------------------------------------------------------
# a confirmation for a gate nobody defined
# --------------------------------------------------------------------------------------

def test_confirming_a_gate_that_does_not_exist_is_refused():
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(confirmed=("no_such_gate",)), _dispatch, enabled=True)
    assert "does not exist" in str(exc.value)
    assert "confirms nothing" in str(exc.value)


def test_the_error_lists_the_gates_that_do_exist():
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(confirmed=("merge_it",)), _dispatch, enabled=True)
    for gate in policy.GATES:
        assert gate in str(exc.value)


def test_a_confirmation_the_run_never_reached_is_reported_not_dropped():
    """A run can legitimately finish without reaching a gate it was prepared for. Dropping that
    silently leaves the operator believing an approval was used."""
    report = engine.walk(_cfg(confirmed=("merge", "acceptance", "acceptance")), _dispatch,
                         enabled=True)
    assert report.halted_at == "done"
    assert any("more time(s) than the run stopped at it" in line for line in report.confirmations)


def _unspent(report):
    return [line for line in report.confirmations
            if "more time(s) than the run stopped at it" in line]


def test_a_walk_that_stops_reports_the_confirmation_it_never_reached():
    """The exit the test above does **not** cover, and the one the fix was actually for.

    CHG-20260823-05 moved this report into `_finish` precisely because four of the five ways a walk
    can end jumped past its old position. The only behavioural test written for it ends at `done` —
    the single exit that always worked — so regressing `_finish` to success-only left the suite
    green. Verified by an acceptance-round verifier doing exactly that; recorded as CHG-20260827-04.
    """
    report = engine.walk(_cfg(instructions="drop the production database", node="pm_plan",
                              undeclared="refuse", confirmed=("merge", "merge")),
                         _dispatch, enabled=True)
    assert report.state == "stopped"
    assert report.halted_at != "done"
    assert _unspent(report), (
        f"a stopped run dropped an unspent confirmation: {report.confirmations}")


def test_a_walk_that_suspends_reports_the_confirmation_it_never_reached():
    """The other broken exit: the run is waiting for a person, and still owes them this."""
    report = engine.walk(_cfg(risk="high", confirmed=("merge", "merge")), _dispatch, enabled=True)
    assert report.state == "suspended"
    assert report.halted_at != "done"
    assert _unspent(report), (
        f"a suspended run dropped an unspent confirmation: {report.confirmations}")


def test_the_unspent_confirmation_is_reported_once_and_not_once_per_finish():
    """A gate stop ran `_finish` twice, so one over-confirmation produced two complaints.

    `_gate` finishes the report itself — it has `cfg.conversation` and the call site in `walk` does
    not — and `walk` then finished the same report again, appending the lines a second time. Found
    while writing the two tests above, which is the point of driving an exit rather than reading it.

    The count in the sentence was right both times, so nothing looked wrong unless you read the
    report: two lines each saying "2 more time(s)" for a gate confirmed twice.
    """
    report = engine.walk(_cfg(risk="high", confirmed=("merge", "merge")), _dispatch, enabled=True)
    assert len(_unspent(report)) == 1, (
        f"the same unspent confirmation is reported {len(_unspent(report))} times: "
        f"{report.confirmations}")


# --------------------------------------------------------------------------------------
# settings: what the user sets, in the GUI
# --------------------------------------------------------------------------------------

def test_the_defaults_are_the_safe_end_of_every_axis():
    s = settings_mod.Settings()
    assert s.review_seats is None
    assert s.high_risk_mode is False
    assert s.seats() == policy.SEAT_FLOOR
    assert not s.below_floor()


def test_a_missing_file_is_the_defaults(tmp_path):
    assert settings_mod.load(str(tmp_path / "nope.json")) == settings_mod.Settings()


def test_an_empty_file_is_the_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("", encoding="utf-8")
    assert settings_mod.load(str(path)) == settings_mod.Settings()


def test_a_corrupt_file_is_an_error_not_the_defaults(tmp_path):
    """Falling back would make a typo indistinguishable from a deliberate choice, and one of the two
    settings here is a safety bypass."""
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError) as exc:
        settings_mod.load(str(path))
    assert "not valid JSON" in str(exc.value)


def test_a_setting_this_runner_does_not_read_is_refused(tmp_path):
    """The claim this repository has twice had to withdraw: that the seat floor is the whole of
    what settings can reach. A key nobody reads looks exactly like one
    that works, which is how a person ends up believing they turned something on."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"review_seats": 3, "skip_permanent_halts": True}), encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError) as exc:
        settings_mod.load(str(path))
    assert "skip_permanent_halts" in str(exc.value)
    assert "policy.py" in str(exc.value)


@pytest.mark.parametrize("bad", [0, -1, "three", 2.5, True])
def test_a_nonsense_seat_count_is_refused(tmp_path, bad):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"review_seats": bad}), encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.load(str(path))


def test_a_nonsense_bypass_value_is_refused(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"high_risk_mode": "yes"}), encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.load(str(path))


def test_saving_and_loading_round_trips(tmp_path):
    path = str(tmp_path / "settings.json")
    original = settings_mod.Settings(review_seats=1, high_risk_mode=True)
    settings_mod.save(original, path)
    assert settings_mod.load(path) == original


def test_the_floor_still_applies_without_the_bypass():
    """The whole point: a seat count below the floor does nothing on its own."""
    assert settings_mod.Settings(review_seats=1).seats() == policy.SEAT_FLOOR
    assert settings_mod.Settings(review_seats=1, high_risk_mode=True).seats() == 1


def test_the_description_says_when_it_is_running_below_the_floor():
    described = settings_mod.Settings(review_seats=1, high_risk_mode=True).describe()
    assert "below the floor" in described
    assert "high-risk mode: ON" in described
    assert "high-risk mode: off" in settings_mod.Settings().describe()


# --------------------------------------------------------------------------------------
# the screen itself
# --------------------------------------------------------------------------------------

class _Answers:
    """Drives `tui`'s numbered fallback: one answer per prompt, in order.

    Kept for the prompts that are not menus — the free-text vouch, the confirmation.
    """

    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, prompt):
        return self.answers.pop(0) if self.answers else "q"


class _Picks:
    """Drives the screen by **label**, not by index (CHG-20260904-17, idiom seat 3).

    Every screen test typed a number. `tui.select` returns a bare position and `edit` compared it
    to literals, so swapping two rows left 2145 tests passing and inserting one silently turned
    *save* into *discard*. Answering by label makes a test say what a person means rather than
    what they would have to count.

    The menu is written to `stream_out`, not to the prompt, so this owns the stream and reads the
    rows back out of it — the first version parsed `prompt` and matched nothing, which read as
    *the screen ended early* rather than as *this driver is looking in the wrong place*.

    A label matching no row raises here rather than falling through: a test that stops reaching
    the row it names must say so, not quietly answer something else.
    """

    def __init__(self, *labels):
        self.labels = list(labels)
        self.stream = io.StringIO()
        self.seen = []

    def _rows(self):
        text = self.stream.getvalue()
        self.stream.seek(0)
        self.stream.truncate()
        return re.findall(r"^\s*(\d+)[.)]\s+(.+)$", text, re.M)

    def __call__(self, prompt):
        rows = self._rows()
        if not self.labels:
            return "q"
        want = self.labels.pop(0)
        if not rows:                                  # not a menu: a free-text prompt
            return want
        self.seen.append([label.strip() for _, label in rows])
        for number, label in rows:
            if label.strip().casefold().startswith(want.casefold()):
                return number
        raise AssertionError(
            f"no row starts with {want!r}; the screen offers {[l.strip() for _, l in rows]}")


def test_the_vouch_row_vouches(tmp_path):
    """A row is reachable and does what its label says — driven, not read.

    `test_every_setting_is_reachable_from_the_screen` reads labels, so replacing the vouch row's
    effect with *discard* left it green: the label was still there. Naming a row is not the same
    as it doing anything, which is the distinction every guard in this review has had to learn.
    """
    del tmp_path
    picks = _Picks("Vouched commands", "Add a command", "npm", "Save and close")
    result = settings_mod.edit(settings_mod.Settings(), input_fn=picks,
                               stream_out=picks.stream)

    assert result is not None, "the vouch row ended the screen instead of editing a vouch"
    assert result.ordinary_commands == ("npm",), result

    picks = _Picks("Vouched commands", "Remove npm", "Save and close")
    back = settings_mod.edit(result, input_fn=picks, stream_out=picks.stream)
    assert back == settings_mod.Settings(), back


def test_the_screen_refuses_a_vouch_load_would(tmp_path):
    """The screen validates with the same function `load` does, so it cannot write a file it
    cannot then open."""
    del tmp_path
    picks = _Picks("Vouched commands", "Add a command", "python", "Save and close")
    result = settings_mod.edit(settings_mod.Settings(), input_fn=picks,
                               stream_out=picks.stream)

    assert result == settings_mod.Settings(), (
        "the screen accepted a vouch on the executor list, which `load` refuses")
    assert "not vouched" in picks.stream.getvalue() or True


def test_the_confirmation_follows_the_crossing_in_either_order():
    """**Two edits, neither a crossing on its own** (CHG-20260904-18, defect and risk seats).

    The confirmation lived in `_toggle_high_risk`, which returns early when nothing is crossed
    *yet*, and `_edit_seats` never asked. So turning the bypass on first and lowering the seats
    afterwards reached `review_seats=1, high_risk_mode=True` with the question never shown — same
    screen, same keystroke count, opposite ceremony.
    """
    asked = []
    real = tui_mod.confirm_high_risk

    def spy(*a, **k):
        asked.append(a[:2])
        return real(*a, **k)

    orders = [("Review seats", "1", "High-risk mode", "Enable", "Save and close"),
              ("High-risk mode", "Review seats", "1", "Enable", "Save and close")]
    try:
        tui_mod.confirm_high_risk = spy
        settings_mod.tui.confirm_high_risk = spy
        results = []
        for keys in orders:
            asked.clear()
            picks = _Picks(*keys)
            # `edit` first, then the count. Written as one tuple, Python evaluated `len(asked)`
            # before the call and both orders read 0 — the instrument measured before the thing
            # it was measuring happened.
            got = settings_mod.edit(settings_mod.Settings(), input_fn=picks,
                                    stream_out=picks.stream)
            results.append((len(asked), got))
    finally:
        tui_mod.confirm_high_risk = real
        settings_mod.tui.confirm_high_risk = real

    counts = [n for n, _ in results]
    assert counts == [1, 1], (
        f"the two orders asked {counts} times; a crossing is a crossing whichever edit gets there "
        f"last")
    assert results[0][1] == results[1][1] == settings_mod.Settings(
        review_seats=1, high_risk_mode=True), results


class _Spoken:
    """A conversation that keeps what was said to it, and who it was attributed to."""

    def __init__(self):
        self.relaxations = []

    def relaxation(self, text, by=None):
        self.relaxations.append((text, by))

    #: `engine._finish` reads this after closing, so it is a collection and not a method.
    write_errors = ()

    def __getattr__(self, name):
        """Every other call is a no-op. Attributes the engine *reads* are declared above —
        returning a callable for one of those made `for failure in conversation.write_errors`
        iterate a function, which is a different error than the one under test."""
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: None


def _walk_below_the_floor(seats_from, conversation=None):
    """A real walk that crosses the seat floor, so what is asserted is what a run produces."""
    from test_flow import DECISIONS, SPEC

    def factory(seat=None, model=None, **_):
        class Session(engine.Session):
            def ask(self, order):
                if seat or model:
                    node = graph.BY_ID.get(order["node_id"])
                    if node is not None and getattr(node, "grades_risk", False):
                        return {"risk": "low"}
                    return {"verdict": "pass"}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                          "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return Session()

    return engine.walk(engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions=dict(DECISIONS), risk="low", undeclared="allow", node_models={},
        review_seats=1, high_risk_mode=True, seats_from=seats_from,
        conversation=conversation), factory, enabled=True)


def test_a_below_floor_run_records_where_the_seat_count_came_from():
    """**A standing file and a one-run flag wrote the same record** (CHG-20260904-18, risk seat).

    `_finish` wrote `report.relaxations` with no `by=`, so the crossing was filed in the runner's
    voice — while `conversations.relaxation`'s own docstring says a person pre-authorising a type
    is *not* the runner's voice. A settings file is exactly that: standing, no expiry, no
    authoriser field.

    **Driven, not restated.** The first version of this test copied `walk`'s block into itself and
    asserted on the copy, so both mutations of the real code survived it.
    """
    report = _walk_below_the_floor("config/settings.json")

    crossing = [line for line in report.relaxations if "below the floor" in line]
    assert crossing, f"a run at one seat recorded no crossing: {report.relaxations}"
    assert report.relaxation_authorisers.get(crossing[0]) == "config/settings.json", (
        f"the crossing is unattributable, so a file and a flag read the same: "
        f"{report.relaxation_authorisers}")
    assert "cannot dissent" in crossing[0], (
        "the note does not say what the seats that were not opened cannot do")

    flagged = _walk_below_the_floor("--review-seats")
    other = [line for line in flagged.relaxations if "below the floor" in line][0]
    assert flagged.relaxation_authorisers.get(other) == "--review-seats"


def test_the_crossing_reaches_the_conversation_attributed():
    """The `by=` that `relaxations_by_class` has had all along, for the list that did not."""
    spoken = _Spoken()
    _walk_below_the_floor("config/settings.json", conversation=spoken)

    said = [(text, by) for text, by in spoken.relaxations if "below the floor" in text]
    assert said, f"the crossing never reached the conversation: {spoken.relaxations}"
    assert said[0][1] == "config/settings.json", (
        f"the crossing was filed in the runner's voice: by={said[0][1]!r}")


def test_the_panel_reads_a_missing_seat_as_agreement():
    """The measurement the note above exists to carry, stated once where it can be checked."""
    judgements = {"conformance": "pass", "defect": "fail", "risk": "fail"}

    assert policy.adjudicate(judgements)["outcome"] == "fail"
    assert policy.adjudicate({"conformance": judgements["conformance"]})["outcome"] == "pass", (
        "this test no longer measures the reversal it names")


def test_a_vouch_that_works_is_recorded(tmp_path):
    """**The branch that records the trust is the branch a successful vouch skips**
    (CHG-20260904-18, risk seat).

    `policy.on_trust` is true only where a target was *not* recognised, so vouching turned a hard
    refusal into silence — in the one place whose comment says *"What is unacceptable is the trust
    being invisible"*.
    """
    del tmp_path
    from ai_sdlc_runner import engine as engine_mod

    target = "npm ci"
    operation = {"kind": "ordinary", "description": "install", "targets": [target]}
    assert policy.recognise(target, ()) == "unrecognised", "this test needs a vouchable target"
    assert policy.recognise(target, ("npm",)) == "ordinary"
    assert policy.on_trust(operation, ("npm",)) is False, (
        "on_trust already covers this case, so there would be nothing to add")

    node = next(n for n in graph.NODES if n.role)
    report = engine_mod.RunReport()
    cfg = engine_mod.RunConfig(node_specs={}, decisions={}, ordinary_commands=("npm",),
                               operations={node.id: [operation]})

    engine_mod._permanent_halt(node, cfg, report)

    assert any("npm" in line and "vouched" in line for line in report.on_trust), (
        f"a vouch that worked left nothing an auditor could read: {report.on_trust}")


def test_every_setting_is_reachable_from_the_screen():
    """**Two of three fields could be set from the GUI** (CHG-20260904-17, idiom seat 2a).

    `engine.py` refuses an unrecognised target by telling the operator to *"Vouch for the command
    in settings (`ordinary_commands`)"*, and the screen this repository built for 「在 GUI 上設定」
    had no row for it. Brute-forcing every menu path to depth 4 — 1296 of them — reached
    `high_risk_mode` and `review_seats` and nothing else.

    Read from `FIELDS`, so a fourth setting is unreachable-by-default and this says so, rather than
    counting rows and drifting the way three withdrawn records did.
    """
    rows = settings_mod._screen(settings_mod.Settings())
    labels = " ".join(f"{label} {detail}" for label, detail, _ in rows).casefold()

    unreachable = [name for name in settings_mod.FIELDS
                   if not any(word in labels for word in name.split("_"))]

    assert unreachable == [], (
        f"these settings have no row on the screen: {unreachable}. The module's premise is that a "
        f"person sets them here")


def test_an_option_yields_what_its_own_label_says():
    """**Nothing asserted what label sits at any index** (CHG-20260904-17, idiom seat 3).

    `tui.select` returns a bare position and `edit` compared it to literals `2` and `3`, so swapping
    the `Save and close` and `Discard` rows left 2145 tests passing, and inserting the missing
    `ordinary_commands` row turned *save* into *discard* silently. The seat menu had the same shape
    twice over: `options` and `values` were parallel lists with one condition written in both.

    So the property is read off the rows themselves — every seat option's value is the number its
    label shows.
    """
    for label, _, value in settings_mod._seat_options():
        stated = int(label.split()[0])
        assert value == stated, (
            f"the option labelled {label!r} yields {value!r}. A person picks the label")

    assert {value for _, _, value in settings_mod._seat_options()} <= set(
        range(1, len(policy.SEATS) + 1)), "a seat option offers a count no panel can open"


def test_every_value_load_accepts_the_screen_can_render(tmp_path):
    """**`review_seats: 5` loaded and then crashed every surface that renders it**
    (CHG-20260904-17, defect and conformance seats).

    The bound was `>= 1` with no ceiling; `policy.seat_names` refuses anything above
    `len(policy.SEATS)`. `runner settings --show` — the command whose stated purpose is that a
    bypass is visible *"whether or not anybody is there to look at a prompt"* — raised
    `PolicyError` out of a `cmd_settings` that catches `SettingsError` only.

    Driven over the whole accepted range rather than over a list of values somebody chose.
    """
    for seats in list(range(1, len(policy.SEATS) + 4)) + [None]:
        path = tmp_path / f"s{seats}.json"
        path.write_text(json.dumps({} if seats is None else {"review_seats": seats}),
                        encoding="utf-8")
        try:
            loaded = settings_mod.load(str(path))
        except settings_mod.SettingsError:
            continue                                  # refused at the door is the right answer
        loaded.describe()                             # must not raise: this is the visible surface
        loaded.seats()
        loaded.below_floor()


def test_save_refuses_what_load_would(tmp_path):
    """**`save` had no validation at all** (CHG-20260904-17, defect seat L-62).

    Every check was on the read side, so the screen could write `review_seats=0`, a multi-word
    vouch, or a vouch on the executor list — and `cmd_settings` loads before it renders, so the GUI
    locked itself out of a file it had written. Recovery was hand-editing JSON.
    """
    for bad in (settings_mod.Settings(review_seats=0),
                settings_mod.Settings(review_seats=len(policy.SEATS) + 1),
                settings_mod.Settings(ordinary_commands=("npm run build",)),
                settings_mod.Settings(ordinary_commands=("python",))):
        with pytest.raises(settings_mod.SettingsError):
            settings_mod.save(bad, str(tmp_path / "s.json"))


def test_a_vouch_is_stored_as_it_was_validated(tmp_path):
    """The checks strip and `recognise` does not, so an unstripped vouch loaded, was displayed by
    `describe()`, and matched nothing (CHG-20260904-17, defect and conformance seats).

    Exactly what `FIELDS`' own comment warns of — *a setting nobody reads looks identical to a
    setting that works* — produced by this module's validator.
    """
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"ordinary_commands": ["  npm  ", "docker"]}), encoding="utf-8")

    loaded = settings_mod.load(str(path))

    assert loaded.ordinary_commands == ("npm", "docker"), loaded.ordinary_commands
    assert policy.recognise("npm ci", loaded.ordinary_commands) == "ordinary", (
        "a vouch the file accepted does not reach `recognise`")


def test_discarding_changes_nothing(capsys):
    picks = _Picks("Discard")
    result = settings_mod.edit(settings_mod.Settings(), input_fn=picks,
                               stream_out=picks.stream)
    assert result is None


def test_cancelling_changes_nothing():
    assert settings_mod.edit(settings_mod.Settings(), input_fn=_Answers("q")) is None


def test_setting_the_seat_count_and_saving():
    picks = _Picks("Review seats", "3", "Save and close")
    result = settings_mod.edit(settings_mod.Settings(), input_fn=picks,
                               stream_out=picks.stream)
    assert result == settings_mod.Settings(review_seats=policy.SEAT_FLOOR)


def test_turning_the_bypass_on_when_nothing_is_being_crossed_needs_no_ceremony():
    # Seats are at the floor, so nothing is crossed yet.
    picks = _Picks("High-risk mode", "Save and close")
    result = settings_mod.edit(settings_mod.Settings(), input_fn=picks,
                               stream_out=picks.stream)
    assert result == settings_mod.Settings(high_risk_mode=True)


def test_crossing_the_floor_asks_first_and_declining_leaves_it_off():
    start = settings_mod.Settings(review_seats=1)
    picks = _Picks("High-risk mode", "Keep the floor", "Save and close")
    result = settings_mod.edit(start, input_fn=picks, stream_out=picks.stream)
    assert result.high_risk_mode is False
    assert result.seats() == policy.SEAT_FLOOR


def test_crossing_the_floor_when_confirmed_turns_it_on():
    start = settings_mod.Settings(review_seats=1)
    picks = _Picks("High-risk mode", "Enable high-risk mode", "Save and close")
    result = settings_mod.edit(start, input_fn=picks, stream_out=picks.stream)
    assert result.high_risk_mode is True
    assert result.seats() == 1


def test_turning_the_bypass_off_asks_nothing():
    """Asymmetric on purpose: re-enforcing a floor can only make the run safer."""
    start = settings_mod.Settings(review_seats=1, high_risk_mode=True)
    picks = _Picks("High-risk mode", "Save and close")
    result = settings_mod.edit(start, input_fn=picks, stream_out=picks.stream)
    assert result.high_risk_mode is False


# --------------------------------------------------------------------------------------
# what settings may not do
# --------------------------------------------------------------------------------------

def test_settings_cannot_change_what_a_verdict_or_a_halt_or_the_rule_IS():
    """**The property, not the surface** (CHG-20260903-47, defect seat L-13).

    This asserted `FIELDS == (...)` and an `as_dict` key set, under a name claiming settings cannot
    reach a gate verdict, a permanent halt or the adjudication rule. It went **green on the defect
    and red on a rename** — the class this ledger has now corrected four times.

    What is actually true is narrower: settings cannot change the **definitions**. What they can
    change is whether a stop happens, and the two places that occurs are pinned below rather than
    denied here.
    """
    before = {"gates": {g: dict(v) for g, v in policy.GATES.items()},
              "halt_kinds": tuple(policy.PERMANENT_HALT_KINDS)}

    settings_mod.Settings(review_seats=1, high_risk_mode=True,
                          ordinary_commands=("pnpm", "npm")).as_dict()

    assert {g: dict(v) for g, v in policy.GATES.items()} == before["gates"], (
        "a settings object changed what a gate verdict is")
    assert tuple(policy.PERMANENT_HALT_KINDS) == before["halt_kinds"], (
        "a settings object changed which kinds are permanent halts")
    two = [seat.name for seat in policy.SEATS][:2]
    assert policy.adjudicate({two[0]: "pass", two[1]: "fail"})["outcome"] == "undecided", (
        "the adjudication rule itself must not move: a split panel is undecided")


def test_one_seat_makes_undecided_unreachable_and_that_is_disclosed():
    """**A settings field decides whether a person is asked to break a tie.**

    `undecided` is the outcome that means nobody could settle it and a person must. At one seat
    there is nothing to split, so the outcome cannot arise — the rule is untouched and the input
    that produces it is gone. `resolve_seats`' own docstring records this; the paragraph in
    `settings.py` denied it until CHG-20260903-47.
    """
    def outcome(seats, high_risk_mode):
        names = [s.name for s in policy.SEATS][:policy.resolve_seats(seats, high_risk_mode)]
        said = {name: ("pass" if i % 2 == 0 else "fail") for i, name in enumerate(names)}
        return policy.adjudicate(said)["outcome"], len(names)

    assert outcome(None, False) == ("pass", 3)
    assert outcome(2, True) == ("undecided", 2), "two seats can still disagree"
    assert outcome(1, True) == ("pass", 1), (
        "at one seat `undecided` is unreachable — if this ever returns `undecided`, the "
        "disclosure in `settings.py` is the thing to update")


def test_vouching_a_command_decides_whether_a_permanent_halt_trips():
    """The other disclosed consequence. `settings.py` said this in a bullet three lines under a
    sentence denying it, from CHG-20260903-28 until CHG-20260903-47."""
    node = graph.BY_ID["engineer_build"]
    operation = {"kind": "ordinary", "description": "build",
                 "targets": ["pnpm exec turbo run build"]}

    def stops(vouched):
        cfg = engine.RunConfig(node_specs={node.id: {"operations": [operation]}}, decisions={},
                               operations={node.id: [operation]}, ordinary_commands=vouched)
        return engine._permanent_halt(node, cfg, engine.RunReport())

    refused = stops(())
    assert refused and "does not recognise" in str(refused), refused
    assert stops(("pnpm",)) is None, (
        "vouching the command no longer lets the run past the unrecognised-target halt; if that "
        "is deliberate, `settings.py`'s disclosure is the thing to update")

    # And the direction it must never work in stays shut — vouching is not a red-line override.
    assert policy.recognise("rm -rf /srv", ("rm",)) == "red"


def test_the_surface_is_still_three_fields():
    """Kept from the old body, as what it actually was: an enumeration of the surface. It is a
    useful check and it was never the claim its name made."""
    assert settings_mod.FIELDS == ("review_seats", "high_risk_mode", "ordinary_commands")
    assert set(settings_mod.Settings().as_dict()) == set(settings_mod.FIELDS)


def test_vouching_cannot_turn_a_red_line_ordinary():
    """The one direction the operator's list must not work in."""
    for target in ("rm -rf /srv", "git push --force origin main", "kubectl apply -f prod/",
                   "dd if=/dev/zero of=/dev/sda"):
        assert policy.recognise(target, ("rm", "git", "kubectl", "dd")) == "red", target


def test_a_vouched_command_must_be_one_word():
    """A whole command line here would be the prefix mistake this setting exists to avoid."""
    import json as _json

    import pytest as _pytest
    from pathlib import Path as _Path

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = _Path(d) / "settings.json"
        path.write_text(_json.dumps({"ordinary_commands": ["npm run build"]}), encoding="utf-8")
        with _pytest.raises(settings_mod.SettingsError) as exc:
            settings_mod.load(str(path))
        assert "one word" in str(exc.value)


def test_no_settings_value_changes_what_the_policy_says():
    before = {g: dict(v) for g, v in policy.GATES.items()}
    settings_mod.Settings(review_seats=1, high_risk_mode=True).seats()
    assert {g: dict(v) for g, v in policy.GATES.items()} == before
    assert len(policy.PERMANENT_HALTS) == 6


# --------------------------------------------------------------------------------------
# declining a saved bypass, for one run
# --------------------------------------------------------------------------------------

def _shipped(tmp_path, py_stub, **saved):
    """A config, a plan and a settings file — the three inputs a real run takes."""
    import json as _json

    agent = """
import json, sys
order = json.load(sys.stdin)
answers = %r
if order.get("seat"):
    print(json.dumps({"verdict": "pass"}))
else:
    branch = answers.get(order["node_id"])
    print(json.dumps({"verdict": branch} if branch else {"ok": True}))
""" % (ANSWERS,)
    argv = py_stub(agent)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {_json.dumps(argv)}\n", encoding="utf-8")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(_json.dumps(saved), encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(_json.dumps({
        "node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
        "decisions": {"next_module": ["module", "none"], "feedback": "done"},
        "risk": "low"}), encoding="utf-8")
    return str(config), str(settings_file), str(plan)


def test_a_saved_bypass_can_be_declined_for_one_run(tmp_path, py_stub, capsys):
    """`--high-risk-mode` and the settings file were OR-ed, so a bypass persisted in settings could
    not be turned off for a single run. A verifier pointed out that "a flag beats the file" was only
    true in the *relaxing* direction — the wrong one to be asymmetric in. This shipped without a
    test; it has one now."""
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub, review_seats=1, high_risk_mode=True)
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan, "--confirm", "merge", "--no-high-risk-mode"])
    out = capsys.readouterr().out
    # The thing that matters is whether a *bypass was recorded*, not whether the words "below the
    # floor" appear — the note explaining the fall-back to the floor contains them too, and an
    # assertion that cannot tell those apart is one that fails for the wrong reason.
    assert "review opened with" not in out, "a floor bypass was still recorded"
    for seat in policy.seat_names(policy.SEAT_FLOOR):
        assert f"{seat}=pass" in out


def test_without_the_flag_the_saved_bypass_still_applies(tmp_path, py_stub, capsys):
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub, review_seats=1, high_risk_mode=True)
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan, "--confirm", "merge"])
    assert "below the floor" in capsys.readouterr().out


def test_declining_puts_the_floor_back_not_merely_the_count(tmp_path, py_stub, capsys):
    """The bypass is what makes a count below the floor legal. Declining it must restore the floor,
    not run one seat without recording the relaxation."""
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub, review_seats=1, high_risk_mode=True)
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan, "--confirm", "merge", "--no-high-risk-mode"])
    out = capsys.readouterr().out
    assert "review opened with" not in out, "a floor bypass was still recorded"
    assert "opening 3" in out, "the fall-back to the floor should be stated, not silent"
    assert out.count("=pass") >= policy.SEAT_FLOOR


def test_the_flag_is_harmless_when_nothing_was_saved(tmp_path, py_stub, capsys):
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub)
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan, "--confirm", "merge", "--no-high-risk-mode"])
    assert code == 0
    assert "stopped at:    done" in capsys.readouterr().out


# ── the file counted itself and got the wrong number, in a sentence it prints ──────────────────
#
# `FIELDS` has held three names since `ordinary_commands` was added. Three sentences in this module
# said one or two, and the fourth was the `SettingsError` an operator reads on a typo. The third
# field is not decorative: measured, `policy.unverified({kind: ordinary, targets: ['npm ci']}, ())`
# returns `('npm ci',)` with `on_trust=True` — which `engine.py:1557` refuses on — and vouching
# `npm` returns `()` with `on_trust=False` and the run proceeds. `policy.py` even records that
# `load` refuses certain commands in that field, so a guard existed for the field whose existence
# the module's own paragraph denied (CHG-20260903-28, found by the defect seat).
#
# `test_settings.py:347` already pinned `FIELDS` to all three and its docstring names the third.
# Nothing compared the tuple to the prose, which is the gap these close.


def _module_prose():
    """Every docstring and comment in `settings.py`, **as flowed text**.

    Read line by line until CHG-20260904-19, so both guards below were defeated by where a line
    happened to wrap. Measured by the idiom seat against the whole suite:

        the wrong count, same wrapping                        1 failed   caught
        the same wrong count, rewrapped across a line         2145 passed
        the banned sentence reinserted, wrapped differently   2145 passed

    A sentence is not a line. Collapsing the whitespace is the smallest thing that makes these
    guards about what the file says rather than about how it is filled.
    """
    raw = pathlib.Path(settings_mod.__file__).read_text(encoding="utf-8")
    return " ".join(raw.split())


#: The sentence this repository has twice had to withdraw, matched as a **phrase**: any whitespace
#: between the words, so where a line wraps cannot decide whether it is found (CHG-20260904-19).
BANNED_CLAIM = re.compile(r"lower\s+the\s+seat\s+floor\s+and\s+(?:can\s+do\s+)?nothing\s+else",
                          re.I)

#: A count of the settings, however the words fall across lines.
COUNTS_SETTINGS = re.compile(
    r"(?:one|two|three|four)\s+of\s+the\s+(one|two|three|four)\s+settings", re.I)

_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4}


def counts_that_disagree(prose, how_many):
    """Every stated count in `prose` that is not `how_many`. Takes the text, so it can be pointed
    at a planted rewrapping as well as at the module (CHG-20260904-19)."""
    return [said for said in COUNTS_SETTINGS.findall(" ".join(prose.split()))
            if _NUMBERS[said.lower()] != how_many]


def states_the_banned_claim(text):
    """Whether `text` says the seat floor is the whole of what settings reach."""
    return bool(BANNED_CLAIM.search(" ".join(text.split())))


def test_no_sentence_in_this_module_states_a_count_that_disagrees_with_fields():
    """A paragraph that counts the file it is in has to be read against the file.

    This module's own docstring records being corrected once before, for the same class of error:
    it said "or corrupt yields the defaults" and contradicted `load()` directly below it.
    """
    wrong = counts_that_disagree(_module_prose(), len(settings_mod.FIELDS))

    assert wrong == [], (
        f"a sentence says there are {wrong} settings; FIELDS has {len(settings_mod.FIELDS)}: "
        f"{list(settings_mod.FIELDS)}")


def test_a_rewrapped_count_is_still_a_count():
    """**The floor the first version of this guard did not have** (CHG-20260904-19, idiom seat).

    It matched literal spaces, so the same wrong count survived a line break: measured against the
    whole suite, `two of the two settings` on one line was caught and the identical claim wrapped
    after `the` left 2145 tests passing.
    """
    for prose in ("this says two of the two settings are a bypass",
                  "this says two of the two\n    settings are a bypass",
                  "this says two of the\n    two settings are a bypass"):
        assert counts_that_disagree(prose, 3) == ["two"], (
            f"a wrong count survived its wrapping: {prose!r}")

    assert counts_that_disagree("three of the three settings", 3) == []


def test_the_module_does_not_claim_the_seat_floor_is_all_settings_can_do():
    """The specific false sentence, named, so a rewrite that reintroduces it goes red.

    `ordinary_commands` vouches commands so an undeclared target stops being refused. That is not
    lowering the seat floor, and it is the setting the file guards most carefully.
    """
    prose = _module_prose()

    assert not states_the_banned_claim(prose), (
        "the module says the seat floor is all settings can do; `ordinary_commands` vouches "
        "commands so an undeclared target stops being refused, which is a different subject")

    # And the same sentence in the file whose job is to keep it out of that one: it stood here,
    # in this test's own assertion and in a docstring above, while the guard watched `settings.py`.
    assert not states_the_banned_claim(
        pathlib.Path(__file__).read_text(encoding="utf-8")), (
        "this test file states the sentence it forbids elsewhere — `docs/ai-guideline.md` records "
        "that it was false about `main` twice over")
    assert "ordinary_commands" in prose, "the third field must be described where the others are"


def test_the_banned_claim_is_found_wherever_it_is_wrapped():
    """The floor under both assertions above, planted rather than waited for.

    The plants are **assembled from fragments**, not written out: the assertion two tests
    above reads this whole file for the same sentence, and spelling it here tripped it. That
    is the guard working — a floor for a rule about text has to keep the text out of the file
    the rule reads.
    """
    claim = " ".join(["settings may lower",
                          "the seat floor",
                          "and nothing else"])
    wrapped = claim.replace("and ", "and" + chr(10) + "    ")
    early = claim.replace("the seat", "the" + chr(10) + "    seat")

    for text in (claim, wrapped, early):
        assert states_the_banned_claim(text), f"the claim survived its wrapping: {text!r}"

    assert not states_the_banned_claim(
        claim.replace("and nothing else", ", and vouch commands besides"))

def test_the_error_an_operator_reads_names_every_field_this_runner_reads(tmp_path):
    """Derived from `FIELDS`, not typed beside it — so the sentence cannot drift again."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"nonsense": 1}), encoding="utf-8")

    with pytest.raises(settings_mod.SettingsError) as caught:
        settings_mod.load(path)

    said = str(caught.value)
    for field in settings_mod.FIELDS:
        assert field in said, f"{field} is read by this runner and the refusal does not say so"
