"""Fifteen review seats, the user's choice of them, and several models on one seat (CHG-20261005-02).

Every behaviour here has a test that fails when its wire is cut (KN-8): the engine's loop over
`review_dimensions`, the engine's loop over a seat's models, the conjunction, the factory's routing
by position, the store's list, the plan's list, the route's list. Where a test below was run with the
wire cut, its docstring says what was cut.
"""
from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest

from ai_sdlc_runner import cli, engine, graph, models, plan, policy, store
from ai_sdlc_runner import settings as settings_mod

ROOT = Path(__file__).resolve().parents[1]

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}

FIFTEEN = ["conformance", "defect", "risk", "idiom", "security", "ux", "ci", "modularity",
           "privacy", "performance", "portability", "docs", "observability", "supply_chain", "i18n"]
OPT_IN = ["observability", "supply_chain", "i18n"]


# ── 1 · the fifteen seats ──────────────────────────────────────────────────────────────────────

def test_the_fifteen_seat_ids_are_pinned_in_order():
    assert [s.name for s in policy.SEATS] == FIFTEEN
    assert policy.seat_names(12) == FIFTEEN[:12], "the cap is the seats that are not opt-in"
    for count in (13, 15):
        with pytest.raises(policy.PolicyError, match="opt-in"):
            policy.seat_names(count)


def test_the_four_existing_seats_are_unchanged_and_only_conformance_vetoes():
    first = policy.SEATS[:4]
    assert [(s.name, s.label, s.veto) for s in first] == [
        ("conformance", "規格合規", True), ("defect", "缺陷", False),
        ("risk", "風險與可逆性", False), ("idiom", "慣例與簡潔", False)]
    assert first[0].question.startswith("Is this the thing the task asked for?")
    assert [s.name for s in policy.SEATS if s.veto] == ["conformance"]


def test_three_seats_are_opt_in_and_the_default_is_three_seats_deep():
    assert [s.name for s in policy.SEATS if s.opt_in] == OPT_IN
    # An install that sets nothing opens the floor, which is the first three seats.
    assert settings_mod.Settings().seats() == policy.SEAT_FLOOR == 3
    assert policy.seat_names(policy.SEAT_FLOOR) == FIFTEEN[:3]


def test_no_seat_count_opens_an_opt_in_seat_and_only_a_named_list_does(tmp_path):
    """Cut the wire (`seat_names` taking `SEATS[:count]` again) and a count of 13 opens one."""
    assert not set(policy.seat_names(policy.MAX_SEAT_COUNT)) & set(OPT_IN)
    assert policy.MAX_SEAT_COUNT == 12
    with pytest.raises(settings_mod.SettingsError, match="opt-in"):
        settings_mod.load(_write(tmp_path, review_seats=13))
    with pytest.raises(policy.PolicyError, match="opt-in"):
        engine.walk(_cfg(review_seats=13), Panel(), enabled=True)
    named = ("conformance", "defect", "observability")
    report = engine.walk(_cfg(review_dimensions=named), Panel(), enabled=True)
    assert [s for s, _ in _seats_at(report, "lead_review")] == list(named)


def test_the_labels_and_questions_are_the_ones_the_user_gave():
    by = policy.BY_SEAT
    assert by["security"].label == "資訊安全"
    assert by["security"].question.startswith("Look for injection, secret exposure")
    assert by["i18n"].label == "國際化/在地化"
    assert by["modularity"].question.endswith("calls it (KN-8)?")
    assert all(s.question.strip() and s.label.strip() for s in policy.SEATS)


def test_the_seats_match_config_panel_json():
    """Ids, labels and opt-in for all fifteen; questions for the eleven new seats only. The four
    existing seats keep the questions the runner's panel has always asked, which `config/panel.json`
    words differently (CHG-20261005-02, Interpreted)."""
    dims = json.loads((ROOT / "config" / "panel.json").read_text(encoding="utf-8"))["dimensions"]
    assert [(d["id"], d["label"]) for d in dims] == [(s.name, s.label) for s in policy.SEATS]
    assert [d["enabled"] for d in dims] == [not s.opt_in for s in policy.SEATS]
    assert [d["question"] for d in dims[4:]] == [s.question for s in policy.SEATS[4:]]
    assert [d["question"] for d in dims[:4]] != [s.question for s in policy.SEATS[:4]], (
        "the four existing seats' questions are the runner's own; if they now match, say so in "
        "the record and compare all fifteen")


# ── 2 · review_dimensions in settings ──────────────────────────────────────────────────────────

def _write(tmp_path, **body):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


def test_unset_is_todays_behaviour_exactly(tmp_path):
    loaded = settings_mod.load(_write(tmp_path, review_seats=4))
    assert loaded.review_dimensions is None
    assert loaded.seats() == 4
    assert settings_mod.load(str(tmp_path / "nothing.json")).review_dimensions is None


def test_a_list_loads_in_the_order_given_and_round_trips(tmp_path):
    names = ["security", "conformance", "ci"]
    path = _write(tmp_path, review_dimensions=names)
    loaded = settings_mod.load(path)
    assert loaded.review_dimensions == tuple(names)
    assert loaded.seats() == 3
    settings_mod.save(loaded, path)
    assert json.loads(Path(path).read_text(encoding="utf-8"))["review_dimensions"] == names
    assert settings_mod.load(path) == loaded


@pytest.mark.parametrize("bad,match", [
    (["conformance", "defect", "nobody"], "no seat"),
    (["conformance", "defect", "defect"], "more than once"),
    (["conformance", "defect"], "below the floor of 3"),
    (["defect", "risk", "idiom"], "the veto seat"),
    ([], "at least one"),
    ("conformance", "list of seat names"),
    ([1, 2, 3], "list of seat names"),
])
def test_a_bad_list_is_refused_at_load(tmp_path, bad, match):
    with pytest.raises(settings_mod.SettingsError, match=match):
        settings_mod.load(_write(tmp_path, review_dimensions=bad))


def test_below_the_floor_needs_high_risk_mode_and_the_message_is_the_counts(tmp_path):
    two = ["security", "docs"]
    with pytest.raises(settings_mod.SettingsError) as refused:
        settings_mod.load(_write(tmp_path, review_dimensions=two))
    with pytest.raises(policy.PolicyError) as counted:
        policy.resolve_seats(2, False)
    assert str(counted.value).split(" — ", 1)[0].replace("2 seat(s)", "") in str(refused.value)
    allowed = settings_mod.load(_write(tmp_path, review_dimensions=two, high_risk_mode=True))
    assert allowed.review_dimensions == tuple(two) and allowed.below_floor()


def test_save_refuses_what_load_would(tmp_path):
    bad = settings_mod.Settings(review_dimensions=("security", "docs"))
    with pytest.raises(settings_mod.SettingsError, match="below the floor"):
        settings_mod.save(bad, str(tmp_path / "s.json"))
    assert not (tmp_path / "s.json").exists()
    bad = settings_mod.Settings(review_dimensions=("security", "nobody", "docs"))
    with pytest.raises(settings_mod.SettingsError, match="no seat"):
        settings_mod.save(bad, str(tmp_path / "s.json"))


def test_review_seats_is_ignored_when_dimensions_are_set_and_show_says_so(tmp_path):
    s = settings_mod.Settings(review_seats=4, review_dimensions=("conformance", "ci", "docs"))
    assert s.seats() == 3
    assert "review_seats is ignored" in s.describe()
    assert "conformance, ci, docs" in s.describe()
    assert "ignored" not in settings_mod.Settings(review_seats=4).describe()
    # And the command that prints it.
    path = _write(tmp_path, review_seats=2, review_dimensions=["conformance", "ci", "docs"])
    out = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(out):
        code = cli.main(["--settings", path, "settings", "--show"])
    assert code == 0 and "review_seats is ignored" in out.getvalue()


def test_the_seat_count_cap_is_the_twelve_seats_that_are_not_opt_in(tmp_path):
    assert settings_mod._check_seats(12) == 12
    with pytest.raises(settings_mod.SettingsError, match="at most 12"):
        settings_mod._check_seats(13)


def _pick(names_in_order, *, done=True):
    """The numbered answers that tick `names_in_order` in the multi-select, then Done."""
    index = {s.name: i + 1 for i, s in enumerate(policy.SEATS)}
    answers = [str(index[n]) for n in names_in_order]
    if done:
        answers.append(str(len(policy.SEATS) + 1))
    return iter(answers)


def test_the_screen_has_a_row_and_the_multi_select_keeps_the_order_ticked():
    rows = settings_mod._screen(settings_mod.Settings())
    assert settings_mod._edit_dimensions in [row[2] for row in rows], "no row reaches the editor"
    answers = _pick(["security", "conformance", "ci"])
    chosen = settings_mod._edit_dimensions(
        settings_mod.Settings(), input_fn=lambda _p: next(answers), stream_out=io.StringIO())
    assert chosen.review_dimensions == ("security", "conformance", "ci")
    # A second pick of the same seat un-ticks it.
    answers = _pick(["security", "conformance", "ci", "ux", "ux", "defect"])
    chosen = settings_mod._edit_dimensions(
        settings_mod.Settings(), input_fn=lambda _p: next(answers), stream_out=io.StringIO())
    assert chosen.review_dimensions == ("security", "conformance", "ci", "defect")
    # Clear unsets it.
    clear = iter([str(len(policy.SEATS) + 2)])
    cleared = settings_mod._edit_dimensions(
        chosen, input_fn=lambda _p: next(clear), stream_out=io.StringIO())
    assert cleared.review_dimensions is None


def test_the_editor_below_the_floor_asks_and_declining_changes_nothing():
    start = settings_mod.Settings()
    # One scripted stream: the ticks, Done, then the confirmation's answer ("Keep the floor" = 1).
    script = list(_pick(["conformance", "ci"])) + ["1"]
    it = iter(script)
    out = settings_mod._edit_dimensions(start, input_fn=lambda _p: next(it),
                                        stream_out=io.StringIO())
    assert out == start, "declining the high-risk confirmation must leave the settings alone"
    script = list(_pick(["conformance", "ci"])) + ["2"]
    it = iter(script)
    out = settings_mod._edit_dimensions(start, input_fn=lambda _p: next(it),
                                        stream_out=io.StringIO())
    assert out.review_dimensions == ("conformance", "ci") and out.high_risk_mode is True


def test_turning_high_risk_off_is_kept_while_dimensions_are_below_the_floor():
    s = settings_mod.Settings(review_dimensions=("conformance", "ci"), high_risk_mode=True)
    out = settings_mod._toggle_high_risk(s, input_fn=input, stream_out=io.StringIO())
    assert out == s


# ── the engine, driven ─────────────────────────────────────────────────────────────────────────

def _cfg(**kw):
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions={"next_module": ["module", "none"], "feedback": "done"},
                risk="low", undeclared="allow", confirmed=("merge",))
    base.update(kw)
    return engine.RunConfig(**base)


class Panel:
    """A factory that records every session it opens and answers by (seat, label).

    `seat_models` is the attribute `cli.session_factory` sets and the engine reads. `verdicts` maps
    `(seat, position)`, `(seat, label)` — or just `seat` — to what that voice says at
    `lead_review`, first match winning in that order; everything else passes. `journal_dir`, when given, lets a session check that its question was written down
    before it opened (KN-7).
    """

    def __init__(self, seat_models=None, verdicts=None, journal_dir=None, describe=None):
        self.seat_models = seat_models or {}
        self.verdicts = verdicts or {}
        self.journal_dir = journal_dir
        self.describe_as = describe or {}
        self.opened = []                        # (seat, position) in order
        self.journal_sizes = []

    def __call__(self, seat=None, position=None):
        if self.journal_dir is not None:
            self.journal_sizes.append(len(list(Path(self.journal_dir).glob("*.json"))))
        self.opened.append((seat, position))
        entries = self.seat_models.get(seat) or []
        label = models.entry_label(entries[position or 0]) if entries else None
        me = self

        class Session:
            def ask(self, order):
                node = order["node_id"]
                if order.get("seat"):
                    if node == "intake_review":
                        return {"problems": [], "missing": [], "unsafe": []}
                    said = me.verdicts.get(
                        (seat, position),
                        me.verdicts.get((seat, label), me.verdicts.get(seat, "pass")))
                    return {} if said is None else {"verdict": said}
                branch = ANSWERS.get(node)
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass

            def describe(self):
                return me.describe_as.get(label, label or "default")

        return Session()


def _seats_at(report, node_id):
    return [(a.seat, a.model) for a in report.asks if a.node_id == node_id and a.seat]


def test_default_asks_exactly_todays_seats_one_session_each():
    panel = Panel()
    report = engine.walk(_cfg(), panel, enabled=True)
    assert report.halted_at == "done"
    assert [s for s, _ in _seats_at(report, "lead_review")] == FIFTEEN[:3]
    assert all(m is None for _, m in _seats_at(report, "lead_review"))
    assert report.seat_models["lead_review"] == {s: ["(default backend)"] for s in FIFTEEN[:3]}


def test_review_dimensions_decide_which_seats_lead_review_and_the_survey_open():
    """Cut the wire (`seat_list` back to `policy.seat_names(seats)` in the two loops) and this fails."""
    chosen = ("security", "conformance", "ux", "i18n")
    report = engine.walk(_cfg(review_dimensions=chosen, review_seats=3), Panel(), enabled=True)
    assert report.halted_at == "done"
    assert [s for s, _ in _seats_at(report, "lead_review")] == list(chosen)
    # SURVEY asks the same seats: the safe reading, documented at the loop.
    assert [s for s, _ in _seats_at(report, "intake_review")] == list(chosen)
    # And the veto is still conformance's alone: it is in the panel, and says pass.
    assert report.adjudications[-1]["verdicts"] == {s: "pass" for s in chosen}


def test_review_seats_is_ignored_when_dimensions_are_given_even_below_the_floor():
    """`review_seats=1` without high-risk mode would raise on its own; with dimensions it is unread."""
    chosen = ("conformance", "risk", "docs")
    report = engine.walk(_cfg(review_dimensions=chosen, review_seats=1), Panel(), enabled=True)
    assert [s for s, _ in _seats_at(report, "lead_review")] == list(chosen)


def test_the_engine_enforces_the_floor_on_dimensions_too():
    with pytest.raises(policy.PolicyError, match="below the floor"):
        engine.walk(_cfg(review_dimensions=("security", "docs")), Panel(), enabled=True)
    with pytest.raises(policy.PolicyError, match="no seat"):
        engine.walk(_cfg(review_dimensions=("security", "docs", "nope")), Panel(), enabled=True)
    low = engine.walk(_cfg(review_dimensions=("conformance", "docs"), high_risk_mode=True,
                           seats_from="settings.json"), Panel(), enabled=True)
    assert any("below the floor" in r and "conformance, docs" in r for r in low.relaxations)


def test_resolve_dimensions_is_the_policy_the_settings_and_engine_share():
    names = ["docs", "conformance", "ux"]
    assert policy.resolve_dimensions(names, False) == names
    with pytest.raises(policy.PolicyError):
        policy.resolve_dimensions(["docs", "docs", "ux"], False)


# ── 3/4 · several models on a seat ─────────────────────────────────────────────────────────────

TWO = {"defect": ["opus", "codex"]}


def test_one_session_per_seat_and_model_each_its_own_journalled_ask(tmp_path):
    """KN-7. Cut the wire (loop over `_seat_voices` back to one ask per seat) and this fails; so does
    moving `journal.record` after `_open`, because each session sees the journal first."""
    journal = engine.AskJournal(tmp_path / "journal")
    panel = Panel(seat_models=TWO, journal_dir=tmp_path / "journal")
    report = engine.walk(_cfg(journal=journal), panel, enabled=True)
    assert report.halted_at == "done"
    review = _seats_at(report, "lead_review")
    assert review == [("conformance", None), ("defect", "opus"), ("defect", "codex"),
                      ("risk", None)]
    assert [p for s, p in panel.opened if s == "defect"] == [0, 1, 0, 1], "survey, then review"
    # Every session opened with its own question already on disk: the journal held one more entry
    # than there had been sessions before it.
    assert panel.journal_sizes == [i + 1 for i in range(len(panel.opened))]
    ids = sorted(p.stem for p in (tmp_path / "journal").glob("*lead_review*"))
    assert len(ids) == 4 and len(set(ids)) == 4
    assert sum(1 for i in ids if "-defect-m" in i) == 2


@pytest.mark.parametrize("opus,codex,expect", [
    ("pass", "pass", "pass"),
    ("pass", "fail", "fail"),
    ("fail", "pass", "fail"),
    ("fail", "fail", "fail"),
    ("pass", "undecided", "undecided"),
    ("undecided", "pass", "undecided"),
    ("undecided", "fail", "fail"),
])
def test_a_seat_passes_only_when_every_model_passes(opus, codex, expect):
    """Cut the wire (`_seat_verdict` returning the last word) and the order cases fail."""
    panel = Panel(seat_models=TWO, verdicts={("defect", "opus"): opus, ("defect", "codex"): codex})
    report = engine.walk(_cfg(review_seats=3, high_risk_mode=False,
                              review_dimensions=("conformance", "defect", "risk")),
                         panel, enabled=True)
    final = [a for a in report.adjudications if a["node_id"] == "lead_review"][0]
    assert final["verdicts"]["defect"] == expect
    assert final["verdicts"]["conformance"] == "pass" and final["verdicts"]["risk"] == "pass"
    # Who said what is kept beside the seat's own word, for any seat with several models.
    assert final["by_model"] == {"defect": [opus, codex]}


def test_the_seat_words_still_go_through_adjudicate_unchanged():
    """Two of three seats pass -> pass; the failing seat's models are conjoined first."""
    panel = Panel(seat_models=TWO, verdicts={("defect", "codex"): "fail"})
    report = engine.walk(_cfg(), panel, enabled=True)
    first = [a for a in report.adjudications if a["node_id"] == "lead_review"][0]
    assert first["outcome"] == "pass" and first["reason"] == "2/3 seats passed"
    # A veto is not extended to a model: conformance with two models and one fail is the veto.
    panel = Panel(seat_models={"conformance": ["opus", "codex"]},
                  verdicts={("conformance", "codex"): "fail"})
    again = {"next_module": ["module", "none", "none", "none", "none", "none"], "feedback": "done"}
    report = engine.walk(_cfg(decisions=again), panel, enabled=True)
    first = [a for a in report.adjudications if a["node_id"] == "lead_review"][0]
    assert first["outcome"] == "fail" and first["vetoed"] == ["conformance"]


def test_a_model_that_names_no_verdict_stops_the_run_as_one_silent_seat_always_did():
    panel = Panel(seat_models=TWO, verdicts={("defect", "codex"): None})
    with pytest.raises(engine.EngineError, match=r"defect \(codex\)"):
        engine.walk(_cfg(), panel, enabled=True)


def test_an_unreadable_word_is_still_refused_by_name():
    panel = Panel(seat_models=TWO, verdicts={("defect", "codex"): "PASS"})
    with pytest.raises(policy.PolicyError, match="PASS"):
        engine.walk(_cfg(), panel, enabled=True)


def test_a_seat_with_no_models_is_one_ask_on_the_default_backend():
    panel = Panel(seat_models={"defect": ["opus", "codex"], "risk": []})
    report = engine.walk(_cfg(), panel, enabled=True)
    assert _seats_at(report, "lead_review")[-1] == ("risk", None)
    assert report.seat_models["lead_review"]["risk"] == ["(default backend)"]


def test_the_report_says_which_models_answered_which_seat():
    """Cut the wire (`_record_seat_model`) and the mapping is empty."""
    report = engine.walk(_cfg(), Panel(seat_models=TWO), enabled=True)
    assert report.seat_models["lead_review"] == {
        "conformance": ["(default backend)"], "defect": ["opus", "codex"],
        "risk": ["(default backend)"]}
    assert report.seat_models["intake_review"]["defect"] == ["opus", "codex"]
    assert report.as_dict()["seat_models"]["lead_review"]["defect"] == ["opus", "codex"]


def test_panel_diversity_counts_every_seat_and_model_voice():
    """One backend answering three seats is flagged; two models on one seat makes four voices,
    two of them different, and is not."""
    same = engine.walk(_cfg(), Panel(), enabled=True)
    assert any("lead_review" in n for n in same.single_model_panels)
    mixed = engine.walk(_cfg(), Panel(seat_models=TWO), enabled=True)
    assert not any("lead_review" in n for n in mixed.single_model_panels)
    # Every voice, across (seat, model), on one backend is flagged even though a seat has two
    # models; one different backend among them is not.
    all_same = {"conformance": ["a"], "defect": ["a", "b"], "risk": ["a"]}
    flagged = engine.walk(_cfg(), Panel(seat_models=all_same, describe={"a": "m", "b": "m"}),
                          enabled=True)
    assert any("lead_review" in n for n in flagged.single_model_panels)
    split = engine.walk(_cfg(), Panel(seat_models=all_same, describe={"a": "m", "b": "n"}),
                        enabled=True)
    assert not any("lead_review" in n for n in split.single_model_panels)


def test_a_survey_answer_per_model_is_kept_not_tallied():
    seen = {}

    class Surveyed(Panel):
        def __call__(self, seat=None, position=None):
            session = super().__call__(seat, position)
            ask = session.ask

            def ask_(order):
                if order["node_id"] == "intake_review" and seat == "defect":
                    who = "opus" if position == 0 else "codex"
                    seen[who] = True
                    return {"problems": [f"{who} found one"], "missing": [], "unsafe": []}
                return ask(order)
            session.ask = ask_
            return session

    report = engine.walk(_cfg(), Surveyed(seat_models=TWO), enabled=True)
    assert seen == {"opus": True, "codex": True}
    assert report.survey["problems"] == {"defect[opus]": ["opus found one"],
                                         "defect[codex]": ["codex found one"]}


# ── the factory is what the engine counts ──────────────────────────────────────────────────────

def _registry():
    return models.Registry(models=(
        models.Model(id="opus", vendor="a", name="o", transport="cli", command=("claude-x",)),
        models.Model(id="codex", vendor="b", name="c", transport="cli", command=("codex-x",))))


def test_the_factory_routes_each_position_to_its_own_model_and_exposes_what_it_routes():
    """Cut the wire (`entries[position or 0]` back to the first) and the second session is opus."""
    factory = cli.session_factory({"agent_command": ["default-x"]}, {"defect": ["opus", "codex"]},
                                  registry=_registry())
    assert factory.seat_models == {"defect": ["opus", "codex"]}
    assert factory(seat="defect", position=0).argv == ["claude-x"]
    assert factory(seat="defect", position=1).argv == ["codex-x"]
    assert factory(seat="risk").argv == ["default-x"]


def test_the_old_shapes_still_read():
    reg = _registry()
    f = cli.session_factory({"agent_command": ["d"]}, {"defect": "opus"}, registry=reg)
    assert f.seat_models == {"defect": ["opus"]} and f(seat="defect").argv == ["claude-x"]
    f = cli.session_factory({"agent_command": ["d"]}, {"defect": ["custom", "cmd"]}, registry=reg)
    assert f.seat_models == {"defect": [["custom", "cmd"]]}
    assert f(seat="defect").argv == ["custom", "cmd"]
    assert models.seat_entries(None) == [] and models.seat_entries("") == []
    assert models.seat_entries(["opus", "codex"], reg) == ["opus", "codex"]
    # The legacy argv is read only where `session_factory` asks for it, and no registry is needed.
    assert models.seat_entries(["custom", "cmd"], reg, legacy_argv=True) == [["custom", "cmd"]]
    assert models.seat_entries(["custom", "cmd"], None, legacy_argv=True) == [["custom", "cmd"]]


def test_a_list_is_model_ids_and_never_a_command():
    """Cut the wire (`seat_entries` returning `[items]` for an unknown id again) and these three
    read `["opus", "missing"]` as one argv."""
    reg = _registry()
    with pytest.raises(models.ModelError, match="'missing'"):
        models.seat_entries(["opus", "missing"], reg)
    with pytest.raises(models.ModelError, match="no model registry"):
        models.seat_entries(["opus", "codex"])
    with pytest.raises(models.ModelError, match="model ids"):
        models.seat_entries([["custom", "cmd"], "opus"], reg)
    # Through the factory the legacy argv still reads, and a list that starts with an id does not
    # turn into an argv when a later word is not one.
    with pytest.raises(cli.CliError, match="'nobody-x'"):
        cli.session_factory({"agent_command": ["d"]}, {"defect": ["opus", "nobody-x"]},
                            registry=reg)
    with pytest.raises(cli.CliError, match="repeated|more than once"):
        cli.session_factory({"agent_command": ["d"]}, {"defect": ["opus", "opus"]}, registry=reg)
    # A plan's or the store's list is checked strictly before the factory ever sees it.
    with pytest.raises(cli.CliError, match="seat 'defect'.*'nobody-x'"):
        cli.check_seat_models({"defect": ["custom", "nobody-x"]}, reg)
    with pytest.raises(cli.CliError, match="no model registry"):
        cli.check_seat_models({"defect": ["opus", "codex"]}, None)
    cli.check_seat_models({"defect": ["opus", "codex"], "risk": "anything at all"}, reg)


def test_a_walk_through_the_real_factory_opens_a_session_per_model(tmp_path):
    """The two halves joined: `session_factory` sets `seat_models`, the engine reads it."""
    opened = []

    class Echo:
        def __init__(self, argv):
            self.argv = argv

        def ask(self, order):
            opened.append((order.get("seat"), self.argv[0]))
            if order.get("seat"):
                if order["node_id"] == "intake_review":
                    return {"problems": [], "missing": [], "unsafe": []}
                return {"verdict": "pass"}
            branch = ANSWERS.get(order["node_id"])
            return {"verdict": branch} if branch else {"ok": True}

        def close(self):
            pass

        def describe(self):
            return self.argv[0]

    real = cli.session_factory({"agent_command": ["default-x"]}, {"defect": ["opus", "codex"]},
                               registry=_registry())

    def factory(seat=None, position=None):
        return Echo(real(seat=seat, position=position).argv)
    factory.seat_models = real.seat_models
    report = engine.walk(_cfg(), factory, enabled=True)
    assert report.halted_at == "done"
    assert [w for s, w in opened if s == "defect"] == ["claude-x", "codex-x"] * 2


# ── 3 · the store, the plan, the route ─────────────────────────────────────────────────────────

def _v4_store(path):
    """A database exactly as schema 4 left it: every statement group, a single seat assignment."""
    db = sqlite3.connect(str(path))
    for statement in store._SCHEMA_1 + store._SCHEMA_2 + store._SCHEMA_3:
        db.execute(statement)
    for column, statement in store._SCHEMA_4:
        db.execute(statement)
    db.execute("INSERT INTO models (id, vendor, name, transport, command_json) "
               "VALUES ('opus', 'v', 'n', 'cli', '[\"agent\"]')")
    db.execute("INSERT INTO models (id, vendor, name, transport, command_json) "
               "VALUES ('codex', 'v', 'n', 'cli', '[\"agent2\"]')")
    db.execute("INSERT INTO seat_assignments VALUES ('defect', 'opus')")
    db.execute("INSERT INTO seat_assignments VALUES ('risk', 'codex')")
    db.execute("INSERT INTO node_assignments VALUES ('engineer_build', 0, 'opus')")
    db.execute("PRAGMA user_version = 4")
    db.commit()
    assert [r[1] for r in db.execute("PRAGMA table_info(seat_assignments)")] == ["seat", "model_id"]
    db.close()


def test_a_real_v4_store_migrates_to_5_and_keeps_every_single_assignment(tmp_path):
    path = tmp_path / "v4.sqlite"
    _v4_store(path)
    db = store.connect(path)
    assert store.SCHEMA_VERSION == 5
    assert db.execute("PRAGMA user_version").fetchone()[0] == 5
    assert [r[1] for r in db.execute("PRAGMA table_info(seat_assignments)")] == [
        "seat", "position", "model_id"]
    assert store.seat_models(db) == {"defect": ["opus"], "risk": ["codex"]}
    assert store.node_models(db) == {"engineer_build": ["opus"]}, "nothing else moved"
    # And a list can now be written and read back in order.
    store.set_seat_model(db, "defect", ["codex", "opus"])
    assert store.seat_models(store.connect(path))["defect"] == ["codex", "opus"]
    # The old table is not left behind, and migrating again is a no-op.
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "seat_assignments_v4" not in names
    db.close()
    again = store.connect(path)
    assert store.seat_models(again)["risk"] == ["codex"]


def test_a_fresh_store_is_schema_5_and_a_v3_store_goes_all_the_way(tmp_path):
    fresh = store.connect(tmp_path / "new.sqlite")
    assert [r[1] for r in fresh.execute("PRAGMA table_info(seat_assignments)")] == [
        "seat", "position", "model_id"]
    path = tmp_path / "v3.sqlite"
    db = sqlite3.connect(str(path))
    for statement in store._SCHEMA_1 + store._SCHEMA_2 + store._SCHEMA_3:
        db.execute(statement)
    db.execute("INSERT INTO models (id, vendor, name, transport, command_json) "
               "VALUES ('opus', 'v', 'n', 'cli', '[\"agent\"]')")
    db.execute("INSERT INTO seat_assignments VALUES ('idiom', 'opus')")
    db.execute("PRAGMA user_version = 3")
    db.commit()
    db.close()
    assert store.seat_models(store.connect(path)) == {"idiom": ["opus"]}


def test_a_mangled_seat_assignments_table_is_still_refused(tmp_path):
    path = tmp_path / "odd.sqlite"
    _v4_store(path)
    db = sqlite3.connect(str(path))
    db.execute("DROP TABLE seat_assignments")
    db.execute("CREATE TABLE seat_assignments (seat TEXT, who TEXT)")
    db.commit()
    db.close()
    with pytest.raises(store.StoreError, match="seat_assignments"):
        store.connect(path)


def test_set_seat_model_takes_a_string_a_list_or_nothing(tmp_path):
    db = store.connect(tmp_path / "c.sqlite")
    store.save_registry(db, _registry())
    store.set_seat_model(db, "risk", "opus")
    assert store.seat_models(db) == {"risk": ["opus"]}
    store.set_seat_model(db, "risk", ["opus", "codex"])
    assert store.seat_models(db) == {"risk": ["opus", "codex"]}
    store.set_seat_model(db, "security", ["codex"])          # one of the new seats
    assert store.seat_models(db)["security"] == ["codex"]
    with pytest.raises(store.StoreError, match="no model 'nobody'"):
        store.set_seat_model(db, "risk", ["opus", "nobody"])
    assert store.seat_models(db)["risk"] == ["opus", "codex"], "a refused write changes nothing"
    store.set_seat_model(db, "risk", [])
    assert "risk" not in store.seat_models(db)
    with pytest.raises(store.StoreError, match="no seat"):
        store.set_seat_model(db, "vibes", ["opus"])


def test_deleting_a_model_names_every_seat_it_is_on(tmp_path):
    db = store.connect(tmp_path / "c.sqlite")
    store.save_registry(db, _registry())
    store.set_seat_model(db, "defect", ["opus", "codex"])
    assert store._assigned_to(db, "opus") == ["seat 'defect'"]


def _plan_file(tmp_path, seat_models):
    from test_cli import _plan_file as base  # noqa: F401  (the shared minimal plan)
    payload = json.loads(Path(base(tmp_path)).read_text(encoding="utf-8"))
    payload["seat_models"] = seat_models
    path = tmp_path / "plan2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_the_plan_accepts_a_string_or_a_list_of_ids(tmp_path):
    assert plan.load(_plan_file(tmp_path, {"defect": "opus"}))["seat_models"] == {"defect": "opus"}
    assert plan.load(_plan_file(tmp_path, {"defect": ["opus", "codex"]}))["seat_models"] == {
        "defect": ["opus", "codex"]}
    for bad in ([""], ["opus", ""], [1], [["a", "b"]]):
        with pytest.raises(plan.PlanError, match="model id per seat"):
            plan.load(_plan_file(tmp_path, {"defect": bad}))


def test_the_route_takes_a_list_and_reads_it_back_and_still_takes_a_string(tmp_path):
    from test_store import _Console
    console = _Console(tmp_path)
    try:
        assert console.post("/models", {"model": {
            "id": "opus", "vendor": "a", "name": "o", "transport": "cli",
            "command": ["claude", "-p"]}})[0] == 200
        assert console.post("/models", {"model": {
            "id": "codex", "vendor": "b", "name": "c", "transport": "cli",
            "command": ["codex", "-p"]}})[0] == 200
        code, out = console.post("/config/seats", {"seat": "defect", "model_id": ["opus", "codex"]})
        assert code == 200 and out["seat_models"] == {"defect": ["opus", "codex"]}, out
        assert console.call("/config/nodes")[1]["seat_models"] == {"defect": ["opus", "codex"]}
        by_model = console.call("/config/nodes")[1]["by_model"]
        assert by_model["opus"]["seats"] == ["defect"] and by_model["codex"]["seats"] == ["defect"]
        code, out = console.post("/config/seats", {"seat": "risk", "model_id": "opus"})
        assert code == 200 and out["seat_models"]["risk"] == ["opus"]
        code, out = console.post("/config/seats", {"seat": "defect", "model_id": ["opus", 3]})
        assert code == 409 and "list of them" in out["error"]
        code, out = console.post("/config/seats", {"seat": "defect", "model_id": ["opus", "nobody"]})
        assert code == 409 and "no model 'nobody'" in out["error"]
        code, out = console.post("/config/seats", {"seat": "defect", "model_id": []})
        assert code == 200 and "defect" not in out["seat_models"]
    finally:
        console.close()


def test_a_plan_list_overrides_a_store_list_as_a_whole():
    merged, source = store.resolve({"seat_models": {"defect": ["a"]}},
                                   {"seat_models": {"defect": ["b", "c"], "risk": ["d"]}})
    assert merged["seat_models"] == {"defect": ["a"], "risk": ["d"]}
    assert source["seat_models.defect"] == store.FROM_PLAN


# ── the command line reads the setting ─────────────────────────────────────────────────────────

def test_run_opens_the_seats_the_settings_file_names(tmp_path, py_stub, capsys):
    """Cut the wire (`review_dimensions=dimensions` in `cmd_run`'s RunConfig) and the panel opens the
    default three, so `security` never appears."""
    from test_settings import _shipped
    config, settings_file, plan_file = _shipped(
        tmp_path, py_stub, review_dimensions=["security", "ux", "conformance"])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge"])
    out = capsys.readouterr().out
    assert code == 0, out
    for seat in ("security", "ux", "conformance"):
        assert f"{seat}=pass" in out
    assert "defect=" not in out
    assert "seat models:   lead_review: security=(default backend); ux=" in out


def test_a_seat_count_typed_for_this_run_beats_the_saved_list(tmp_path, py_stub, capsys):
    from test_settings import _shipped
    config, settings_file, plan_file = _shipped(
        tmp_path, py_stub, review_dimensions=["security", "ux", "docs", "conformance"])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge", "--review-seats", "3"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "conformance=pass" in out and "security=" not in out


def test_serve_builds_its_config_from_the_saved_list(tmp_path, py_stub, monkeypatch):
    """The other half of the wire: `cmd_serve`'s `make_config` carries `review_dimensions`."""
    from test_settings import _shipped
    from ai_sdlc_runner import server
    config, settings_file, plan_file = _shipped(
        tmp_path, py_stub, review_dimensions=["ci", "docs", "conformance"])
    caught = {}

    def fake_serve(runner, *a, **k):
        caught["runner"] = runner
        raise server.ServerError("stop here")
    monkeypatch.setattr(server, "serve", fake_serve)
    cli.main(["--config", config, "--settings", settings_file, "serve", "--plan", plan_file,
              "--token-dir", str(tmp_path / "tok"),
              "--assignment-store", str(tmp_path / "config.sqlite")])
    cfg = caught["runner"]._make_config([], (), ())
    assert cfg.review_dimensions == ("ci", "docs", "conformance")


# ── review round 1 ─────────────────────────────────────────────────────────────────────────────

def _lead_review(report):
    return [a for a in report.adjudications if a["node_id"] == "lead_review"][0]


def test_the_same_model_twice_on_a_seat_cannot_hide_a_fail():
    """Round 1, finding 1. Cut the wire (`_adjudicate` keying `latest` by `ask.model` again) and
    position 0's `fail` is overwritten by position 1's `pass`, so the seat passes."""
    twice = {"defect": ["opus", "opus"]}
    panel = Panel(seat_models=twice, verdicts={("defect", 0): "fail", ("defect", 1): "pass"})
    first = _lead_review(engine.walk(_cfg(), panel, enabled=True))
    assert first["verdicts"]["defect"] == "fail"
    assert first["by_model"] == {"defect": ["fail", "pass"]}, "the dissent is in the report"
    # Either order, and the veto seat too: a duplicate cannot launder a veto.
    panel = Panel(seat_models={"conformance": ["opus", "opus"]},
                  verdicts={("conformance", 1): "fail"})
    again = {"next_module": ["module", "none", "none", "none", "none", "none"], "feedback": "done"}
    report = engine.walk(_cfg(decisions=again), panel, enabled=True)
    veto = _lead_review(report)
    assert veto["outcome"] == "fail" and veto["vetoed"] == ["conformance"]


def test_the_same_model_twice_keeps_both_survey_answers():
    class Surveyed(Panel):
        def __call__(self, seat=None, position=None):
            session = super().__call__(seat, position)
            ask = session.ask

            def ask_(order):
                if order["node_id"] == "intake_review" and seat == "defect":
                    return {"problems": [f"voice {position}"], "missing": [], "unsafe": []}
                return ask(order)
            session.ask = ask_
            return session

    report = engine.walk(_cfg(), Surveyed(seat_models={"defect": ["opus", "opus"]}), enabled=True)
    assert sorted(report.survey["problems"].values()) == [["voice 0"], ["voice 1"]]


def test_a_duplicate_model_on_one_seat_is_refused_at_every_door(tmp_path):
    with pytest.raises(plan.PlanError, match="more than once on seat 'defect'"):
        plan.load(_plan_file(tmp_path, {"defect": ["opus", "opus"]}))
    db = store.connect(tmp_path / "c.sqlite")
    store.save_registry(db, _registry())
    with pytest.raises(store.StoreError, match="more than once on seat 'defect'"):
        store.set_seat_model(db, "defect", ["opus", "codex", "opus"])
    assert store.seat_models(db) == {}, "a refused write changes nothing"
    with pytest.raises(models.ModelError, match="more than once"):
        models.seat_entries(["opus", "opus"], _registry())
    from test_store import _Console
    console = _Console(tmp_path / "console")
    try:
        for model_id in ("opus", "codex"):
            assert console.post("/models", {"model": {
                "id": model_id, "vendor": "a", "name": "o", "transport": "cli",
                "command": [model_id, "-p"]}})[0] == 200
        code, out = console.post("/config/seats", {"seat": "defect", "model_id": ["opus", "opus"]})
        assert code == 409 and "more than once" in out["error"], out
    finally:
        console.close()


# A seat's models in the report and the journal are bound to who they were put to.

def _journaled_walk(tmp_path, seat_models, *, resume, factory=None):
    journal = engine.AskJournal(tmp_path / "journal")
    panel = factory or Panel(seat_models=seat_models)
    report = engine.walk(_cfg(journal=journal, resume=resume), panel, enabled=True)
    return panel, report


def test_a_resume_with_the_same_assignment_reuses_every_answer(tmp_path):
    seats = {"defect": ["opus", "codex"]}
    _journaled_walk(tmp_path, seats, resume=False)
    panel, report = _journaled_walk(tmp_path, seats, resume=True)
    assert panel.opened == [], "nothing was asked again"
    assert report.halted_at == "done" and report.resumed


def test_a_resume_with_a_replaced_model_asks_the_replacement_not_the_old_answer(tmp_path):
    """Round 1, finding 2. Cut the wire (`identity=` in the two seat `_ask` calls, or the
    comparison in `_ask`) and the replacement is never opened and is reported as answering."""
    _journaled_walk(tmp_path, {"defect": ["opus", "codex"]}, resume=False)
    panel, report = _journaled_walk(
        tmp_path, {"defect": ["opus", "replacement"]}, resume=True,
        factory=Panel(seat_models={"defect": ["opus", "replacement"]},
                      verdicts={("defect", "replacement"): "fail"}))
    assert [p for s, p in panel.opened if s == "defect"] == [1, 1], "survey and review, position 1"
    assert ("defect", 0) not in panel.opened, "the unchanged model is not asked again"
    assert _lead_review(report)["verdicts"]["defect"] == "fail", "the replacement's own word"
    assert report.seat_models["lead_review"]["defect"] == ["opus", "replacement"]


def test_a_resume_re_asks_when_the_same_id_now_runs_another_command(tmp_path):
    """The identity is the command the factory resolves, not only the id."""
    def real(command):
        reg = models.Registry(models=(
            models.Model(id="opus", vendor="a", name="o", transport="cli", command=(command,)),
            models.Model(id="codex", vendor="b", name="c", transport="cli",
                         command=("codex-x",))))
        inner = cli.session_factory({"agent_command": ["default-x"]},
                                    {"defect": ["opus", "codex"]}, registry=reg)
        opened = []

        def factory(seat=None, position=None):
            opened.append((seat, position))
            return Panel()(seat, position)
        factory.seat_models = inner.seat_models
        factory.voice_identity = inner.voice_identity
        factory.opened = opened
        return factory
    _journaled_walk(tmp_path, None, resume=False, factory=real("claude-x"))
    same = real("claude-x")
    _journaled_walk(tmp_path, None, resume=True, factory=same)
    assert same.opened == []
    moved = real("claude-y")
    _journaled_walk(tmp_path, None, resume=True, factory=moved)
    assert sorted({p for s, p in moved.opened if s == "defect"}) == [0], "only opus moved"


def _real_factory(assignment, default=("default-x",)):
    """`cli.session_factory`'s own routing and identity, with the Panel's sessions."""
    inner = cli.session_factory({"agent_command": list(default)}, assignment, registry=_registry())
    opened = []

    def factory(seat=None, position=None):
        opened.append((seat, position))
        return Panel()(seat, position)
    factory.seat_models = inner.seat_models
    factory.voice_identity = inner.voice_identity
    factory.opened = opened
    return factory


def _conformance_opened(factory):
    return [p for s, p in factory.opened if s == "conformance"]


@pytest.mark.parametrize("before, after, reused", [
    (["opus"], None, False),               # named -> default backend
    (None, ["opus"], False),               # default backend -> named
    (["opus"], ["codex"], False),          # named -> another named
    (None, None, True),                    # default -> default: unchanged
    (["opus"], ["opus"], True),            # named -> the same named: unchanged
])
def test_a_resume_compares_the_default_backend_as_a_voice_too(tmp_path, before, after, reused):
    """Round 2, finding 1. Cut the default backend's identity (`voice_identity` returning `None`
    for a seat with no model, or `_seat_identity` returning `None` for it) and the first two cases
    reuse an answer given by the other backend."""
    first = _real_factory({"conformance": before} if before else {})
    _journaled_walk(tmp_path, None, resume=False, factory=first)
    second = _real_factory({"conformance": after} if after else {})
    _, report = _journaled_walk(tmp_path, None, resume=True, factory=second)
    assert report.halted_at == "done"
    if reused:
        assert _conformance_opened(second) == [], "nothing was asked again"
    else:
        assert _conformance_opened(second), "the new voice was asked"
        assert all(s == "conformance" for s, _ in second.opened), "and only that seat"


def test_a_default_backend_whose_command_changed_is_asked_again(tmp_path):
    _journaled_walk(tmp_path, None, resume=False, factory=_real_factory({}, default=("one",)))
    again = _real_factory({}, default=("two",))
    _journaled_walk(tmp_path, None, resume=True, factory=again)
    assert _conformance_opened(again)


def test_a_journal_entry_with_no_voice_is_asked_again(tmp_path):
    """This change has not shipped, so an entry without a `voice` is not trusted: re-ask."""
    first = _real_factory({})
    _journaled_walk(tmp_path, None, resume=False, factory=first)
    for path in (tmp_path / "journal").glob("*conformance*.json"):
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert entry["voice"] == {"model": None, "argv": ["default-x"]}
        del entry["voice"]
        path.write_text(json.dumps(entry), encoding="utf-8")
    second = _real_factory({})
    _journaled_walk(tmp_path, None, resume=True, factory=second)
    assert _conformance_opened(second), "the legacy entries were not reused"
    assert all(s == "conformance" for s, _ in second.opened), "the other seats' entries were"


# Seat verdicts: all pass -> pass; any fail -> fail; any unreached (no fail) -> the run stops.

PREFIX_SEATS = [s.name for s in policy.PREFIX_SEATS]


def _dims_with(seat):
    return tuple(dict.fromkeys(("conformance", "defect", "risk", seat)))


@pytest.mark.parametrize("seat", PREFIX_SEATS)
def test_every_seat_is_pass_fail_or_unreached_by_its_models(seat):
    """Round 1, finding 4. A model that names no verdict is unreached. Without a `fail` it makes
    the seat unreached and the run stops, naming it; with one the seat is `fail`, and the
    unreached model is listed beside it."""
    models_here = {seat: ["opus", "codex"]}
    dims = _dims_with(seat)

    def run(opus, codex):
        panel = Panel(seat_models=models_here,
                      verdicts={(seat, "opus"): opus, (seat, "codex"): codex})
        again = {"next_module": ["module"] + ["none"] * 8, "feedback": "done"}
        return engine.walk(_cfg(review_dimensions=dims, high_risk_mode=True, decisions=again),
                           panel, enabled=True)

    assert _lead_review(run("pass", "pass"))["verdicts"][seat] == "pass"
    assert _lead_review(run("pass", "fail"))["verdicts"][seat] == "fail"
    assert _lead_review(run("fail", "pass"))["verdicts"][seat] == "fail"
    for opus, codex in (("pass", None), (None, "pass"), (None, "undecided")):
        with pytest.raises(engine.EngineError, match=rf"{seat} \((opus|codex)\)"):
            run(opus, codex)
    mixed = _lead_review(run("fail", None))
    assert mixed["verdicts"][seat] == "fail" and mixed["unreached"] == {seat: [f"{seat} (codex)"]}


# The veto seat can be left out of a named list only in high-risk mode, and the run says so.

def test_a_list_without_the_veto_seat_is_refused_unless_high_risk_mode_is_on(tmp_path):
    """Round 1, finding 6. Cut the wire (`vetoes_missing` in `resolve_dimensions`) and all of the
    refusals below load."""
    names = ["defect", "risk", "idiom"]
    with pytest.raises(policy.PolicyError, match="veto seat"):
        policy.resolve_dimensions(names, False)
    assert policy.resolve_dimensions(names, True) == names
    with pytest.raises(settings_mod.SettingsError, match="conformance.*veto seat"):
        settings_mod.load(_write(tmp_path, review_dimensions=names))
    with pytest.raises(settings_mod.SettingsError, match="veto seat"):
        settings_mod.save(settings_mod.Settings(review_dimensions=tuple(names)),
                          str(tmp_path / "s.json"))
    allowed = settings_mod.load(_write(tmp_path, review_dimensions=names, high_risk_mode=True))
    assert allowed.review_dimensions == tuple(names)
    assert "no veto seat open (conformance is not named)" in allowed.describe()
    with pytest.raises(policy.PolicyError, match="veto seat"):
        engine.walk(_cfg(review_dimensions=tuple(names)), Panel(), enabled=True)


def test_a_run_without_the_veto_seat_records_it_like_the_high_risk_note():
    names = ("defect", "risk", "idiom")
    report = engine.walk(_cfg(review_dimensions=names, high_risk_mode=True,
                              seats_from="settings.json"), Panel(), enabled=True)
    note = [r for r in report.relaxations if "veto seat" in r]
    assert len(note) == 1
    assert note[0].startswith("high-risk mode: review opened without conformance")
    assert report.relaxation_authorisers[note[0]] == "settings.json"
    assert [s for s, _ in _seats_at(report, "lead_review")] == list(names)
    with_veto = engine.walk(_cfg(review_dimensions=("conformance", "defect", "risk")),
                            Panel(), enabled=True)
    assert not [r for r in with_veto.relaxations if "veto seat" in r]


def test_the_editor_and_the_toggle_keep_a_list_without_the_veto_seat_out_of_the_file():
    start = settings_mod.Settings()
    out = io.StringIO()
    it = _pick(["defect", "risk", "idiom"])
    kept = settings_mod._edit_dimensions(start, input_fn=lambda _p: next(it), stream_out=out)
    assert kept == start and "veto seat" in out.getvalue()
    on = settings_mod.Settings(review_dimensions=("defect", "risk", "idiom"), high_risk_mode=True)
    out = io.StringIO()
    assert settings_mod._toggle_high_risk(on, input_fn=input, stream_out=out) == on
    assert "veto seat" in out.getvalue()


def test_no_high_risk_mode_on_the_command_line_drops_a_list_without_the_veto_seat(
        tmp_path, py_stub, capsys):
    from test_settings import _shipped
    config, settings_file, plan_file = _shipped(
        tmp_path, py_stub, review_dimensions=["defect", "risk", "idiom"], high_risk_mode=True)
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge", "--no-high-risk-mode"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "leaves out conformance, the veto seat" in out and "conformance=pass" in out


def test_run_refuses_a_plan_list_the_registry_cannot_resolve(tmp_path, py_stub, capsys):
    """The wire from `cmd_run` to `cli.check_seat_models`: cut it and the list reaches the factory
    as the legacy argv, and the run starts."""
    from test_settings import _shipped
    config, settings_file, _ = _shipped(tmp_path, py_stub)
    plan_file = _plan_file(tmp_path, {"defect": ["opus", "codex"]})
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge",
                     "--assignment-store", "none"])
    out = capsys.readouterr().out
    assert code == 2 and "seat 'defect'" in out and "no model registry" in out, out


def test_serve_refuses_a_plan_list_the_registry_cannot_resolve(tmp_path, monkeypatch):
    """Round 2, finding 2: the wire from `serve`'s `build_factory` to `cli.check_seat_models`.
    Cut it and the list reaches `session_factory` as the legacy argv, and the walk starts."""
    from ai_sdlc_runner import server
    seen = {}

    class Httpd:
        server_address = ("127.0.0.1", 0)

        def serve_forever(self):
            try:
                seen["runner"]._walk(None)      # `build_factory` runs before the config is read
            except Exception as exc:            # noqa: BLE001 - whatever it raised is the result
                seen["raised"] = exc

        def server_close(self):
            pass

    def fake_serve(runner, *args, **kwargs):
        seen["runner"] = runner
        return Httpd()
    monkeypatch.setattr(server, "serve", fake_serve)
    code = cli.main(["serve", "--plan", _plan_file(tmp_path, {"defect": ["opus", "codex"]}),
                     "--assignment-store", str(tmp_path / "config.sqlite"),
                     "--token-dir", str(tmp_path / "tok")])
    assert code == 0
    assert isinstance(seen.get("raised"), cli.CliError), seen.get("raised")
    assert "seat 'defect'" in str(seen["raised"]) and "unknown model id" in str(seen["raised"])


# The settings screen in a real session: no `stream_out`, and curses erases each menu.

def _fake_curses(monkeypatch, screen):
    curses = pytest.importorskip("curses")
    monkeypatch.setattr(curses, "COLS", 80, raising=False)
    monkeypatch.setattr(curses, "wrapper", lambda fn: fn(screen))
    monkeypatch.setattr(curses, "curs_set", lambda n: None)
    monkeypatch.setattr(curses, "use_default_colors", lambda: None)
    monkeypatch.setattr(curses, "init_pair", lambda *a: None)
    monkeypatch.setattr("ai_sdlc_runner.tui._want_curses", lambda *a: True)
    return curses


def test_a_refused_dimension_list_is_on_the_next_menu_in_a_real_session(monkeypatch):
    """Round 2, finding 4. Cut `notes` (the body of the next menu) and the reason is printed
    nowhere: `cmd_settings` passes no stream, and curses erases whatever came before a menu."""
    from test_tui import _FakeScreen
    curses = pytest.importorskip("curses")
    down, enter = curses.KEY_DOWN, 10
    keys = ([down, enter]                         # main menu: Review dimensions
            + [down, enter]                       # tick defect (conformance left out)
            + [down] * len(policy.SEATS) + [enter]  # the picker reopens at its top: to "Done"
            + [ord("q")])                         # the next main menu: cancel
    screen = _FakeScreen(keys, size=(30, 100))
    _fake_curses(monkeypatch, screen)
    assert settings_mod.edit(settings_mod.Settings(), input_fn=lambda p: "") is None
    last = " ".join(" ".join(screen.at_input[-1]).split())
    assert "conformance is the veto seat" in last and "needs high-risk mode" in last, last
    assert not any("is the veto seat, and a list" in " ".join(f) for f in screen.at_input[:-1])


def test_a_refused_dimension_list_is_on_the_next_numbered_menu(monkeypatch, capsys):
    monkeypatch.setenv("AI_SDLC_NO_CURSES", "1")
    done = len(policy.SEATS) + 1
    answers = iter(["2", "2", str(done), "q"])    # dimensions; tick defect; Done; cancel
    assert settings_mod.edit(settings_mod.Settings(), input_fn=lambda p: next(answers)) is None
    out = capsys.readouterr().out
    reason = out.index("is the veto seat, and a list without it")
    assert reason < out.rindex("Settings —"), "before the menu that follows the refusal"
    assert out.count("is the veto seat, and a list without it") == 1, "shown once, not carried on"


def test_the_picker_says_conformance_is_the_veto_seat_and_shows_each_question(monkeypatch):
    shown = {}

    def capture(title, options, **kw):
        shown.update({label: desc for label, desc in options})
        return None
    monkeypatch.setattr("ai_sdlc_runner.tui.select", capture)
    settings_mod._edit_dimensions(settings_mod.Settings(), input_fn=None, stream_out=None)
    conformance = shown["[ ] conformance"]
    assert "veto seat" in conformance and "required unless high-risk mode" in conformance
    for seat in policy.SEATS:
        assert seat.question in shown[f"[ ] {seat.name}"]


def test_the_seat_count_editor_offers_every_count_up_to_the_most_a_count_opens():
    counts = [row[2] for row in settings_mod._seat_options()]
    assert sorted(counts) == list(range(1, policy.MAX_SEAT_COUNT + 1))


def test_runner_policy_shows_each_seat_in_full_with_its_question(capsys):
    assert cli.main(["policy"]) == 0
    out = capsys.readouterr().out
    for seat in policy.SEATS:
        assert seat.question in out
    line = [l for l in out.splitlines() if l.startswith("  observability")][0]
    assert "(off unless chosen)" in line and line.split()[1] != "(off", line


def test_the_dimension_picker_shows_done_and_clear_in_a_short_terminal(monkeypatch, capsys):
    """Round 2, finding 5. Cut the unconditional size check and the 18-row screen draws the first
    rows and silently loses Done and Clear."""
    from test_tui import _FakeScreen
    options = [(f"seat {i}", "") for i in range(15)] + [("Done", ""), ("Clear", "")]
    short = _FakeScreen([10], size=(18, 80))
    _fake_curses(monkeypatch, short)
    import ai_sdlc_runner.tui as tui_mod
    with pytest.raises(tui_mod._TooSmall):
        tui_mod._curses_select_on(short, "t", options)
    # Through `select`: the numbered prompt prints every row, so Done is reachable.
    assert tui_mod.select("t", options, input_fn=lambda p: "16") == 15
    out = capsys.readouterr().out
    assert "16. Done" in out and "17. Clear" in out
    assert short.at_input == [], "nothing was drawn on the short screen"
    # A tall enough screen shows both rows, inside its height.
    tall = _FakeScreen([10], size=(24, 80))
    assert tui_mod._curses_select_on(tall, "t", options) == 0
    assert any(line.endswith("Done") for line in tall.at_input[0])
    assert max(tall.screen) < 24, "every row drawn is inside the window"
