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
OFF_BY_DEFAULT = ["observability", "supply_chain", "i18n"]


# ── 1 · the fifteen seats ──────────────────────────────────────────────────────────────────────

def test_the_fifteen_seat_ids_are_pinned_in_order():
    assert [s.name for s in policy.SEATS] == FIFTEEN
    assert policy.seat_names(15) == FIFTEEN, "the cap is the count of seats that exist"


def test_the_four_existing_seats_are_unchanged_and_only_conformance_vetoes():
    first = policy.SEATS[:4]
    assert [(s.name, s.label, s.veto) for s in first] == [
        ("conformance", "規格合規", True), ("defect", "缺陷", False),
        ("risk", "風險與可逆性", False), ("idiom", "慣例與簡潔", False)]
    assert first[0].question.startswith("Is this the thing the task asked for?")
    assert [s.name for s in policy.SEATS if s.veto] == ["conformance"]


def test_three_seats_are_off_unless_chosen_and_the_default_is_still_four_seats_deep():
    assert [s.name for s in policy.SEATS if not s.enabled_by_default] == OFF_BY_DEFAULT
    # An install that sets nothing opens the floor, which is a prefix of the first four.
    assert settings_mod.Settings().seats() == policy.SEAT_FLOOR
    assert policy.seat_names(policy.SEAT_FLOOR) == FIFTEEN[:3]


def test_the_labels_and_questions_are_the_ones_the_user_gave():
    by = policy.BY_SEAT
    assert by["security"].label == "資訊安全"
    assert by["security"].question.startswith("Look for injection, secret exposure")
    assert by["i18n"].label == "國際化/在地化"
    assert by["modularity"].question.endswith("calls it (KN-8)?")
    assert all(s.question.strip() and s.label.strip() for s in policy.SEATS)


def test_the_seats_match_config_panel_json_when_that_file_exists():
    panel = ROOT / "config" / "panel.json"
    if not panel.is_file():
        pytest.skip("config/panel.json lands with CHG-20260929-01; until it does there is nothing "
                    "to compare the runner's seat vocabulary against")
    dims = json.loads(panel.read_text(encoding="utf-8"))["dimensions"]
    assert [(d["id"], d["label"]) for d in dims] == [(s.name, s.label) for s in policy.SEATS]


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
    s = settings_mod.Settings(review_seats=4, review_dimensions=("ux", "ci", "docs"))
    assert s.seats() == 3
    assert "review_seats is ignored" in s.describe()
    assert "ux, ci, docs" in s.describe()
    assert "ignored" not in settings_mod.Settings(review_seats=4).describe()
    # And the command that prints it.
    path = _write(tmp_path, review_seats=2, review_dimensions=["ux", "ci", "docs"])
    out = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(out):
        code = cli.main(["--settings", path, "settings", "--show"])
    assert code == 0 and "review_seats is ignored" in out.getvalue()


def test_the_seat_count_cap_reflects_fifteen(tmp_path):
    assert settings_mod._check_seats(15) == 15
    with pytest.raises(settings_mod.SettingsError, match="defines 15"):
        settings_mod._check_seats(16)


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
    answers = _pick(["security", "conformance", "ci", "ux", "conformance"])
    chosen = settings_mod._edit_dimensions(
        settings_mod.Settings(), input_fn=lambda _p: next(answers), stream_out=io.StringIO())
    assert chosen.review_dimensions == ("security", "ci", "ux")
    # Clear unsets it.
    clear = iter([str(len(policy.SEATS) + 2)])
    cleared = settings_mod._edit_dimensions(
        chosen, input_fn=lambda _p: next(clear), stream_out=io.StringIO())
    assert cleared.review_dimensions is None


def test_the_editor_below_the_floor_asks_and_declining_changes_nothing():
    start = settings_mod.Settings()
    # One scripted stream: the ticks, Done, then the confirmation's answer ("Keep the floor" = 1).
    script = list(_pick(["security", "ci"])) + ["1"]
    it = iter(script)
    out = settings_mod._edit_dimensions(start, input_fn=lambda _p: next(it),
                                        stream_out=io.StringIO())
    assert out == start, "declining the high-risk confirmation must leave the settings alone"
    script = list(_pick(["security", "ci"])) + ["2"]
    it = iter(script)
    out = settings_mod._edit_dimensions(start, input_fn=lambda _p: next(it),
                                        stream_out=io.StringIO())
    assert out.review_dimensions == ("security", "ci") and out.high_risk_mode is True


def test_turning_high_risk_off_is_kept_while_dimensions_are_below_the_floor():
    s = settings_mod.Settings(review_dimensions=("security", "ci"), high_risk_mode=True)
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
    `(seat, label)` — or just `seat` — to what that voice says at `lead_review`; everything else
    passes. `journal_dir`, when given, lets a session check that its question was written down
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
                    said = me.verdicts.get((seat, label), me.verdicts.get(seat, "pass"))
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
    chosen = ("defect", "risk", "docs")
    report = engine.walk(_cfg(review_dimensions=chosen, review_seats=1), Panel(), enabled=True)
    assert [s for s, _ in _seats_at(report, "lead_review")] == list(chosen)


def test_the_engine_enforces_the_floor_on_dimensions_too():
    with pytest.raises(policy.PolicyError, match="below the floor"):
        engine.walk(_cfg(review_dimensions=("security", "docs")), Panel(), enabled=True)
    with pytest.raises(policy.PolicyError, match="no seat"):
        engine.walk(_cfg(review_dimensions=("security", "docs", "nope")), Panel(), enabled=True)
    low = engine.walk(_cfg(review_dimensions=("security", "docs"), high_risk_mode=True,
                           seats_from="settings.json"), Panel(), enabled=True)
    assert any("below the floor" in r and "security, docs" in r for r in low.relaxations)


def test_resolve_dimensions_is_the_policy_the_settings_and_engine_share():
    assert policy.resolve_dimensions(["docs", "ci", "ux"], False) == ["docs", "ci", "ux"]
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
    f = cli.session_factory({"agent_command": ["d"]}, {"defect": [["custom", "cmd"], "opus"]},
                            registry=reg)
    assert f(seat="defect", position=1).argv == ["claude-x"]
    assert models.seat_entries(None) == [] and models.seat_entries("") == []
    assert models.seat_entries(["opus", "codex"], reg) == ["opus", "codex"]
    assert models.seat_entries(["opus", "codex"]) == [["opus", "codex"]], "no registry: one argv"


def test_an_unknown_id_in_a_seat_list_is_an_error_not_a_fallback_to_the_default():
    f = cli.session_factory({"agent_command": ["d"]}, {"defect": ["opus", "nobody-x"]},
                            registry=_registry())
    assert f.seat_models == {"defect": [["opus", "nobody-x"]]}, "read as the old one-argv shape"
    assert f(seat="defect").argv == ["opus", "nobody-x"], "as it always did for an unknown word"


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
        tmp_path, py_stub, review_dimensions=["security", "ux", "docs"])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge"])
    out = capsys.readouterr().out
    assert code == 0, out
    for seat in ("security", "ux", "docs"):
        assert f"{seat}=pass" in out
    assert "conformance=" not in out
    assert "seat models:   lead_review: security=(default backend); ux=" in out


def test_a_seat_count_typed_for_this_run_beats_the_saved_list(tmp_path, py_stub, capsys):
    from test_settings import _shipped
    config, settings_file, plan_file = _shipped(
        tmp_path, py_stub, review_dimensions=["security", "ux", "docs"])
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan_file, "--confirm", "merge", "--review-seats", "3"])
    out = capsys.readouterr().out
    assert "conformance=pass" in out and "security=" not in out


def test_serve_builds_its_config_from_the_saved_list(tmp_path, py_stub, monkeypatch):
    """The other half of the wire: `cmd_serve`'s `make_config` carries `review_dimensions`."""
    from test_settings import _shipped
    from ai_sdlc_runner import server
    config, settings_file, plan_file = _shipped(
        tmp_path, py_stub, review_dimensions=["ci", "docs", "ux"])
    caught = {}

    def fake_serve(runner, *a, **k):
        caught["runner"] = runner
        raise server.ServerError("stop here")
    monkeypatch.setattr(server, "serve", fake_serve)
    cli.main(["--config", config, "--settings", settings_file, "serve", "--plan", plan_file,
              "--token-dir", str(tmp_path / "tok"),
              "--assignment-store", str(tmp_path / "config.sqlite")])
    cfg = caught["runner"]._make_config([], (), ())
    assert cfg.review_dimensions == ("ci", "docs", "ux")
