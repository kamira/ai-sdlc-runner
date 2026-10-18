"""A review seat can carry the user's role and spec, and every brief is recorded (CHG-20261016-01).

Each test names the wire it fails when cut (KN-8). The record's "Build notes" says which cuts were
made by hand and seen to fail.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from ai_sdlc_runner import cli, engine, graph, models, policy  # noqa: E402
from ai_sdlc_runner import seatspec, store, workorder  # noqa: E402
from ai_sdlc_runner import settings as settings_mod  # noqa: E402
from test_console_flow import Console, needs_node, _seat_node  # noqa: E402
from test_review_dimensions import ANSWERS, SPEC, _v4_store  # noqa: E402

AUDITOR = "a payments-industry security auditor"
PI = "target: Raspberry Pi 4, ARM64, 2 GB RAM, Python 3.9"

# Today's seat instructions, written out here rather than read from `workorder`, so a change to the
# unset brief is a change to this file too.
def _todays(seat):
    s = policy.BY_SEAT[seat]
    return (f"do the work\n\nYou are the {s.label} seat, and this seat only. {s.question}\n"
            f"Answer independently: you have not seen and will not see the other seats' answers.")


def _cfg(**kw):
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions={"next_module": ["module", "none"], "feedback": "done"},
                risk="low", undeclared="allow", confirmed=("merge",))
    base.update(kw)
    return engine.RunConfig(**base)


def entry(seat="", model="", role="", text="", path=""):
    spec = None
    if text:
        spec = {"kind": "text", "text": text}
    if path:
        spec = {"kind": "text", "path": path}
    return seatspec.parse_entry({"seat": seat, "model": model, "role": role, "spec": spec})


class Rec:
    """A factory that records the exact order every seat session was handed, by (seat, label)."""

    def __init__(self, seat_models=None, verdicts=None, on_ask=None):
        self.seat_models = seat_models or {}
        self.verdicts = verdicts or {}
        self.on_ask = on_ask
        self.opened = []
        self.orders = []                       # (seat, label, node_id, the order as received)

    def __call__(self, seat=None, position=None):
        self.opened.append((seat, position))
        entries = self.seat_models.get(seat) or []
        label = models.entry_label(entries[position or 0]) if entries else None
        me = self

        class Session:
            def ask(self, order):
                me.orders.append((seat, label, order["node_id"], copy.deepcopy(order)))
                if me.on_ask:
                    me.on_ask(seat, label, order)
                if order.get("seat"):
                    if order["node_id"] == "intake_review":
                        return {"problems": [], "missing": [], "unsafe": []}
                    return {"verdict": me.verdicts.get(seat, "pass")}
                branch = ANSWERS.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass

            def describe(self):
                return label or "default"

        return Session()

    def lead(self, seat, label=None):
        return [o for s, lb, n, o in self.orders
                if s == seat and n == "lead_review" and lb == label]


def walk(specs=(), *, panel=None, journal=None, resume=False, root="", **kw):
    panel = panel or Rec()
    report = engine.walk(_cfg(seat_specs=tuple(specs), journal=journal, resume=resume,
                              spec_root=root, **kw), panel, enabled=True)
    return panel, report


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A working directory that is the repository: spec paths are relative to it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "device.md").write_text(PI, encoding="utf-8")
    return tmp_path


# ── 2 · the brief: unset is today's, byte for byte ───────────────────────────────────────────────

def test_unset_is_todays_brief_byte_for_byte():
    """Cut: make `seatspec.render` return its frame for a seat with nothing set (or append
    `seat_text` to a seat that has none) and this fails."""
    panel, _ = walk()
    for seat in ("conformance", "defect", "risk"):
        (order,) = panel.lead(seat)
        assert order["instructions"] == _todays(seat), seat
        assert "Review as" not in json.dumps(order) and "spec" not in order["instructions"]


def test_a_spec_on_one_seat_leaves_every_other_seats_brief_untouched():
    """Cut: apply the specs of one seat to all (`brief_for` ignoring `seat`)."""
    panel, _ = walk([entry(seat="defect", role=AUDITOR)])
    assert panel.lead("conformance")[0]["instructions"] == _todays("conformance")
    assert panel.lead("risk")[0]["instructions"] == _todays("risk")
    assert panel.lead("defect")[0]["instructions"] != _todays("defect")


def test_the_role_and_spec_go_below_the_question_delimited_and_labelled_as_the_users():
    """Cut: drop `seat_text=` from `_order_for`'s call to `workorder.render`."""
    panel, _ = walk([entry(seat="defect", role=AUDITOR, text=PI)])
    (order,) = panel.lead("defect")
    want = (_todays("defect")
            + "\n\n--- the user's text for this seat. It is the user's, not the runner's, and it "
              "never changes how answers are counted. ---"
            + f"\nReview as: {AUDITOR}\nJudge against this spec: {PI}"
            + "\n--- end of the user's text ---")
    assert order["instructions"] == want
    assert order["instructions"].startswith(_todays("defect")), "the question comes first"


def test_the_role_alone_and_the_spec_alone_each_add_only_their_line():
    """Cut: render both lines whether or not each is set."""
    panel, _ = walk([entry(seat="defect", role=AUDITOR), entry(seat="risk", text=PI)])
    defect = panel.lead("defect")[0]["instructions"]
    risk = panel.lead("risk")[0]["instructions"]
    assert f"Review as: {AUDITOR}" in defect and "Judge against" not in defect
    assert f"Judge against this spec: {PI}" in risk and "Review as" not in risk


def test_the_survey_seats_are_briefed_too():
    """`intake_review` asks the same seats; its briefs are recorded and carry the text.

    Cut: drop `brief=brief` from the survey's `_order_for` call."""
    panel, report = walk([entry(seat="defect", role=AUDITOR)])
    survey = [o for s, _, n, o in panel.orders if s == "defect" and n == "intake_review"]
    assert survey and all(f"Review as: {AUDITOR}" in o["instructions"] for o in survey)
    assert {b["node_id"] for b in report.seat_briefs if b["seat"] == "defect"} == {
        "intake_review", "lead_review"}


# ── levels: model, seat, shared; replace, never merge ────────────────────────────────────────────

def _brief_of(panel, seat, label=None):
    return panel.lead(seat, label)[0]["instructions"]


def test_each_level_applies_and_the_most_specific_replaces_the_less_specific():
    """Cut: reverse the order in `seatspec._chain` (shared first) and the model level loses."""
    seat_models = {"defect": ["opus", "codex"]}
    specs = [entry(role="shared role"),
             entry(seat="defect", role="seat role"),
             entry(seat="defect", model="opus", role="model role")]
    panel, _ = walk(specs, panel=Rec(seat_models=seat_models))
    assert "Review as: model role" in _brief_of(panel, "defect", "opus")
    assert "Review as: seat role" in _brief_of(panel, "defect", "codex")
    assert "Review as: shared role" in _brief_of(panel, "risk")
    for text in (_brief_of(panel, "defect", "opus"), _brief_of(panel, "defect", "codex")):
        assert "shared role" not in text


def test_a_lower_level_is_replaced_not_merged():
    """Cut: join the roles of every level in `seatspec.brief_for`."""
    panel, _ = walk([entry(seat="ux", role="a blind user"), entry(role="an auditor")],
                    review_dimensions=("conformance", "defect", "ux"))
    text = _brief_of(panel, "ux")
    assert "Review as: a blind user" in text and "auditor" not in text
    assert text.count("Review as:") == 1


def test_role_and_spec_are_each_taken_from_the_most_specific_level_that_sets_it():
    """The shared device spec still reaches a seat that has only its own role."""
    specs = [entry(text=PI), entry(seat="ux", role="a blind user"),
             entry(seat="ux", model="opus", text="its own spec")]
    panel, report = walk(specs, panel=Rec(seat_models={"ux": ["opus", "codex"]}),
                         review_dimensions=("conformance", "defect", "ux"))
    opus, codex = _brief_of(panel, "ux", "opus"), _brief_of(panel, "ux", "codex")
    assert "Review as: a blind user" in opus and "Judge against this spec: its own spec" in opus
    assert PI not in opus
    assert "Review as: a blind user" in codex and f"Judge against this spec: {PI}" in codex
    levels = {b["model"]: (b["role"]["level"], b["spec"]["level"])
              for b in report.seat_briefs if b["seat"] == "ux" and b["node_id"] == "lead_review"}
    assert levels == {"opus": ("seat", "model"), "codex": ("seat", "shared")}


def test_a_model_level_spec_does_not_reach_another_model_on_the_seat():
    """Cut: key the model level by seat alone."""
    panel, _ = walk([entry(seat="defect", model="opus", role="only opus")],
                    panel=Rec(seat_models={"defect": ["opus", "codex"]}))
    assert "only opus" in _brief_of(panel, "defect", "opus")
    assert "only opus" not in _brief_of(panel, "defect", "codex")


def test_a_spec_for_a_seat_this_run_does_not_open_stops_nothing_and_is_not_read(repo):
    """A stale file for a seat nobody asks must not stop a run that never asks it."""
    walk([entry(seat="privacy", path="docs/gone.md")])


# ── 1 · validation: one validator for every door ─────────────────────────────────────────────────

BAD = [
    ({"seat": "defect", "role": "x" * (seatspec.MAX_ROLE_CHARS + 1)}, "role is 501 characters"),
    ({"seat": "defect", "spec": {"kind": "text", "text": "x" * (seatspec.MAX_SPEC_CHARS + 1)}},
     "spec text is 8001 characters"),
    ({"seat": "defect", "spec": {"kind": "text", "path": "docs/../docs/device.md"}}, "'..'"),
    ({"seat": "defect", "spec": {"kind": "text", "path": "/etc/passwd"}}, "not a file inside"),
    ({"seat": "defect", "spec": {"kind": "text", "path": "../outside.md"}}, "'..'"),
    ({"seat": "defect", "spec": {"kind": "emulator", "text": "x"}}, "does not exist"),
    ({"seat": "defect", "spec": {"kind": "text", "text": "a", "path": "docs/device.md"}},
     "exactly one"),
    ({"seat": "defect", "spec": {"kind": "text", "text": "  "}}, "blank"),
    ({"seat": "nobody", "role": "x"}, "no seat 'nobody'"),
    ({"model": "opus", "role": "x"}, "says which seat"),
    ({"seat": "defect"}, "neither a role nor a spec"),
    ({"seat": "defect", "role": "x", "colour": "red"},
     "reads \\['seat', 'model', 'role', 'spec'\\]"),
    ({"seat": "defect", "role": 7}, "must be text"),
]


@pytest.mark.parametrize("raw, said", BAD)
def test_every_refusal_is_the_same_in_the_settings_file_the_store_and_the_validator(
        repo, raw, said):
    """Cut a check out of `seatspec.parse_entry` / `check_path` and its row fails at all three
    doors, which is the point of having one validator."""
    with pytest.raises(seatspec.SeatSpecError, match=said):
        seatspec.parse_entry(raw)
    path = repo / "settings.json"
    path.write_text(json.dumps({"seat_specs": [raw]}), encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError, match=said):
        settings_mod.load(str(path))
    db = store.connect(repo / "c.sqlite")
    if said != "neither a role nor a spec":       # the store reads that entry as "clear the level"
        with pytest.raises(store.StoreError, match=said):
            store.set_seat_spec(db, raw)
    assert store.seat_specs(db) == (), "nothing was written"


def test_the_caps_are_exact_at_the_edge(repo):
    """At the cap passes, one over is refused. Cut a cap (`_text`'s limit): the over case fails."""
    seatspec.parse_entry({"seat": "defect", "role": "x" * seatspec.MAX_ROLE_CHARS,
                          "spec": {"kind": "text", "text": "y" * seatspec.MAX_SPEC_CHARS}})
    big = repo / "docs" / "big.md"
    big.write_text("z" * (seatspec.MAX_SPEC_FILE_BYTES + 1), encoding="utf-8")
    with pytest.raises(seatspec.SeatSpecError, match="bytes and the most this runner reads"):
        seatspec.read_file("docs/big.md")
    wide = repo / "docs" / "wide.md"
    wide.write_text("é" * (seatspec.MAX_SPEC_CHARS + 1), encoding="utf-8")   # 16002 bytes
    with pytest.raises(seatspec.SeatSpecError, match="characters and the most"):
        seatspec.read_file("docs/wide.md")


def test_a_symlink_out_of_the_repository_is_refused(repo, tmp_path_factory):
    """Cut: `os.path.realpath` -> `os.path.abspath` in `check_path`, and the link passes."""
    outside = tmp_path_factory.mktemp("outside") / "secret.md"
    outside.write_text("not yours", encoding="utf-8")
    link = repo / "docs" / "link.md"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot make a symlink here")
    with pytest.raises(seatspec.SeatSpecError, match="not a file inside the repository"):
        seatspec.parse_entry({"seat": "defect", "spec": {"kind": "text", "path": "docs/link.md"}})
    # And a link that was fine when saved and points out when the run starts.
    ok = repo / "docs" / "ok.md"
    ok.write_text("fine", encoding="utf-8")
    saved = entry(seat="defect", path="docs/ok.md")
    ok.unlink()
    os.symlink(outside, ok)
    panel = Rec()
    with pytest.raises(engine.EngineError, match="not a file inside the repository"):
        walk([saved], panel=panel)
    assert panel.opened == []


def test_a_symlink_to_a_file_inside_the_repository_is_fine(repo):
    link = repo / "docs" / "alias.md"
    try:
        os.symlink(repo / "docs" / "device.md", link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot make a symlink here")
    panel, _ = walk([entry(seat="defect", path="docs/alias.md")])
    assert f"Judge against this spec: {PI}" in _brief_of(panel, "defect")


@pytest.mark.parametrize("make, said", [
    (lambda d: None, "does not exist or is not a file"),
    (lambda d: (d / "docs" / "gone.md").mkdir(), "does not exist or is not a file"),
    (lambda d: (d / "docs" / "gone.md").write_bytes(b"\xff\xfe\x00bad"), "cannot be read as UTF-8"),
    (lambda d: (d / "docs" / "gone.md").write_text("  \n", encoding="utf-8"), "is empty"),
])
def test_a_spec_file_that_cannot_be_read_stops_the_run_before_any_seat_is_asked(repo, make, said):
    """Cut: replace the `seatspec.load` call in `_walk` with `{}`: the seat is asked without it."""
    make(repo)
    panel = Rec()
    with pytest.raises(engine.EngineError, match=said) as stop:
        walk([entry(seat="defect", path="docs/gone.md")], panel=panel)
    assert "docs/gone.md" in str(stop.value) and "before any seat was asked" in str(stop.value)
    assert panel.opened == [], "not one session was opened"


def test_the_shared_spec_file_is_read_for_every_run(repo):
    panel = Rec()
    with pytest.raises(engine.EngineError, match="shared"):
        walk([entry(path="docs/gone.md")], panel=panel)
    assert panel.opened == []


def test_a_level_is_held_once_and_a_second_entry_is_refused():
    with pytest.raises(seatspec.SeatSpecError, match="more than one spec for seat 'defect'"):
        seatspec.parse([{"seat": "defect", "role": "a"}, {"seat": "defect", "role": "b"}])


def test_the_settings_file_round_trips_and_save_refuses_what_load_would(repo):
    path = str(repo / "settings.json")
    saved = settings_mod.Settings(seat_specs=(
        entry(role="r"), entry(seat="ux", model="opus", text="t"),
        entry(seat="docs", path="docs/device.md")))
    settings_mod.save(saved, path)
    assert settings_mod.load(path).seat_specs == saved.seat_specs
    assert json.loads(Path(path).read_text(encoding="utf-8"))["seat_specs"][2] == {
        "seat": "docs", "spec": {"kind": "text", "path": "docs/device.md"}}
    bad = settings_mod.Settings(seat_specs=(seatspec.SeatSpec(
        seat="ux", kind="text", path="../x.md"),))
    with pytest.raises(settings_mod.SettingsError, match="'..'"):
        settings_mod.save(bad, str(repo / "other.json"))
    assert not (repo / "other.json").exists()


def test_the_settings_screen_sets_replaces_and_removes_a_level_and_shows_a_refusal(repo):
    """Cut: drop the `Seat specs` row from `_screen` or `parse_entry` from the editor."""
    rows = settings_mod._screen(settings_mod.Settings())
    assert settings_mod._edit_seat_specs in [r[2] for r in rows]
    # row 1 (add/replace); seat, model, role, where, text
    script = iter(["1", "ux", "opus", "a blind user", "text", "reads with a screen reader"])
    out = settings_mod._edit_seat_specs(settings_mod.Settings(), input_fn=lambda _p: next(script),
                                        stream_out=io.StringIO())
    (kept,) = out.seat_specs
    assert (kept.seat, kept.model, kept.role, kept.text) == (
        "ux", "opus", "a blind user", "reads with a screen reader")
    # Replace the same level: still one entry.
    script = iter(["1", "ux", "opus", "someone else", ""])
    again = settings_mod._edit_seat_specs(out, input_fn=lambda _p: next(script),
                                          stream_out=io.StringIO())
    assert [(e.role, e.has_spec) for e in again.seat_specs] == [("someone else", False)]
    # A refusal is the validator's own, shown, and nothing is kept.
    shown = io.StringIO()
    script = iter(["1", "ux", "", "", "path", "../../etc/passwd"])
    refused = settings_mod._edit_seat_specs(again, input_fn=lambda _p: next(script),
                                            stream_out=shown)
    assert refused == again and "not kept" in shown.getvalue() and "'..'" in shown.getvalue()
    # Remove: row 2 is the first Remove row.
    script = iter(["2"])
    gone = settings_mod._edit_seat_specs(again, input_fn=lambda _p: next(script),
                                         stream_out=io.StringIO())
    assert gone.seat_specs == ()


# ── 1 · the store ────────────────────────────────────────────────────────────────────────────────

def _v5_store(path):
    """A database exactly as schema 5 left it: the v4 build, with `seat_assignments` as a list."""
    _v4_store(path)
    db = sqlite3.connect(str(path))
    db.execute("ALTER TABLE seat_assignments RENAME TO old")
    db.execute(store._SEAT_ASSIGNMENTS_5)
    db.execute("INSERT INTO seat_assignments SELECT seat, 0, model_id FROM old")
    db.execute("DROP TABLE old")
    db.execute("PRAGMA user_version = 5")
    db.commit()
    assert "seat_specs" not in {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    db.close()


def test_a_real_v5_store_migrates_to_6_and_keeps_everything_it_held(tmp_path):
    """Cut: remove the `found < 6` block from `store._migrate`."""
    path = tmp_path / "v5.sqlite"
    _v5_store(path)
    assert store.SCHEMA_VERSION == 6
    db = store.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 6
    assert store.seat_models(db) == {"defect": ["opus"], "risk": ["codex"]}
    assert store.node_models(db) == {"engineer_build": ["opus"]}
    assert store.seat_specs(db) == ()
    store.set_seat_spec(db, {"seat": "defect", "model": "opus", "role": AUDITOR})
    store.set_seat_spec(db, {"role": "shared"})
    store.set_seat_spec(db, {"seat": "defect", "spec": {"kind": "text", "text": PI}})
    db.close()
    again = store.connect(path)                      # migrating again is a no-op
    assert [(e.seat, e.model, e.role) for e in store.seat_specs(again)] == [
        ("", "", "shared"), ("defect", "", ""), ("defect", "opus", AUDITOR)]


def test_a_mangled_seat_specs_table_is_refused_not_blessed(tmp_path):
    """Cut: leave `seat_specs` out of `store._EXPECTED`, and `IF NOT EXISTS` keeps the wrong one."""
    path = tmp_path / "c.sqlite"
    _v5_store(path)
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE seat_specs (seat TEXT, who TEXT)")
    db.commit()
    db.close()
    with pytest.raises(store.StoreError, match="seat_specs"):
        store.connect(path)


def test_the_store_sets_replaces_clears_and_checks_the_model(tmp_path):
    db = store.connect(tmp_path / "c.sqlite")
    db.execute("INSERT INTO models (id, vendor, name, transport, command_json) "
               "VALUES ('opus', 'v', 'n', 'cli', '[\"agent\"]')")
    store.set_seat_spec(db, {"seat": "ux", "role": "first"})
    store.set_seat_spec(db, {"seat": "ux", "role": "second", "spec": {"text": PI}})
    (one,) = store.seat_specs(db)
    assert (one.role, one.text, one.kind) == ("second", PI, "text"), "replaced, not added"
    with pytest.raises(store.StoreError, match="no model 'nobody'"):
        store.set_seat_spec(db, {"seat": "ux", "model": "nobody", "role": "x"})
    store.set_seat_spec(db, {"seat": "ux", "model": "opus", "role": "x"})
    with pytest.raises(store.StoreError, match="the spec for it on seat 'ux'"):
        store.save_registry(db, models.Registry(models=()))
    store.set_seat_spec(db, {"seat": "ux"})                      # clears that level
    store.set_seat_spec(db, {"seat": "ux", "model": "opus"})
    assert store.seat_specs(db) == ()
    with pytest.raises(store.StoreError, match="no seat 'typo'"):
        store.set_seat_spec(db, {"seat": "typo"})


def test_the_settings_file_wins_per_level_and_the_store_fills_the_rest():
    """Cut: swap the two origins in `seatspec.merge`."""
    merged, source = seatspec.merge(
        [entry(seat="ux", role="from the file")],
        [entry(seat="ux", role="from the store", text="stored spec"),
         entry(seat="docs", role="only stored")])
    by = {e.key: e for e in merged}
    assert by[("ux", "")].role == "from the file" and not by[("ux", "")].has_spec, \
        "a level is replaced whole, not merged field by field"
    assert by[("docs", "")].role == "only stored"
    assert source == {("ux", ""): "settings", ("docs", ""): "store"}


# ── 3 · every brief is recorded ──────────────────────────────────────────────────────────────────

def _journal(tmp_path):
    return engine.AskJournal(tmp_path / "journal")


def test_the_stored_brief_is_exactly_what_the_seat_received(tmp_path, repo):
    """Cut: drop `journal.record_brief` in `_ask`, or store anything but `to_json(order)`."""
    journal = _journal(tmp_path)
    panel, report = walk([entry(seat="defect", role=AUDITOR, path="docs/device.md")],
                         panel=Rec(seat_models={"defect": ["opus", "codex"]}), journal=journal)
    assert report.seat_briefs
    for brief in report.seat_briefs:
        stored = Path(brief["file"])
        assert stored.parent == (tmp_path / "journal" / "briefs").resolve()
        data = stored.read_bytes()
        assert hashlib.sha256(data).hexdigest() == brief["sha256"]
        received = [o for s, lb, n, o in panel.orders
                    if (s, lb, n) == (brief["seat"], brief["model"] if brief["model"] in
                                      ("opus", "codex") else None, brief["node_id"])]
        assert data in [workorder.to_json(o).encode("utf-8") for o in received], brief["ask_id"]
    # One file per session: three seats, one with two models, at two nodes.
    assert len(list((tmp_path / "journal" / "briefs").glob("*.json"))) == len(report.seat_briefs)
    assert len(report.seat_briefs) == 2 * 4


def test_the_journal_entry_records_the_role_the_spec_its_source_hash_and_level(tmp_path, repo):
    """Cut: drop `brief=kept` from `journal.record` in `_ask`."""
    journal = _journal(tmp_path)
    walk([entry(role="shared role"), entry(seat="docs", path="docs/device.md"),
          entry(seat="defect", text="inline spec")],
         journal=journal, review_dimensions=("conformance", "defect", "docs"))
    by_id = {e["ask_id"]: e for e in journal.entries()}
    docs = next(e for k, e in by_id.items() if e.get("seat") == "docs" and "lead_review" in k)
    assert docs["brief"]["role"] == {"text": "shared role", "level": "shared"}
    assert docs["brief"]["spec"] == {
        "kind": "text", "source": "file", "path": "docs/device.md", "text": PI,
        "sha256": hashlib.sha256(PI.encode("utf-8")).hexdigest(), "level": "seat"}
    defect = next(e for k, e in by_id.items() if e.get("seat") == "defect" and "lead_review" in k)
    assert defect["brief"]["spec"]["source"] == "inline" and defect["brief"]["spec"]["path"] is None
    assert defect["brief"]["file"] == f"briefs/{defect['ask_id']}.json"
    assert defect["brief"]["sha256"] == hashlib.sha256(
        (journal.dir / defect["brief"]["file"]).read_bytes()).hexdigest()
    pm = next(e for e in by_id.values() if e.get("seat") is None)
    assert "brief" not in pm, "only a seat session has a brief"
    assert (journal.dir / "briefs").is_dir() and journal.pending() == [], \
        "a stored brief is not mistaken for an ask"


def test_a_spec_file_edited_after_the_run_leaves_the_record_unchanged(tmp_path, repo):
    journal = _journal(tmp_path)
    _, report = walk([entry(seat="docs", path="docs/device.md")], journal=journal,
                     review_dimensions=("conformance", "defect", "docs"))
    before_entries = json.dumps(journal.entries(), sort_keys=True)
    before_files = {p.name: p.read_bytes() for p in (journal.dir / "briefs").glob("*.json")}
    before_report = json.dumps(report.as_dict()["seat_briefs"], sort_keys=True)
    (repo / "docs" / "device.md").write_text("target: something else entirely", encoding="utf-8")
    assert json.dumps(journal.entries(), sort_keys=True) == before_entries
    assert {p.name: p.read_bytes() for p in (journal.dir / "briefs").glob("*.json")} == before_files
    assert json.dumps(report.as_dict()["seat_briefs"], sort_keys=True) == before_report
    docs = [e for e in journal.entries() if e.get("seat") == "docs"][0]
    assert docs["brief"]["spec"]["text"] == PI


def test_a_spec_file_is_read_once_when_the_run_starts_so_two_seats_never_get_two_texts(repo):
    """Cut: read the file at ask time (in `brief_for`) instead of once in `seatspec.load`."""
    def edit_after_first(seat, label, order):
        (repo / "docs" / "device.md").write_text("changed mid-run", encoding="utf-8")
    panel, _ = walk([entry(path="docs/device.md")], panel=Rec(on_ask=edit_after_first))
    texts = {o["instructions"].split("Judge against this spec: ")[1].split("\n")[0]
             for s, _, n, o in panel.orders if o.get("seat") and n == "lead_review"}
    assert texts == {PI}, "every seat was told the text as it was when the run began"


def test_the_report_lists_every_session_and_says_no_role_no_spec_for_an_empty_one(tmp_path, repo):
    """Cut: drop the `briefs=report.seat_briefs` argument from the seat `_ask` calls."""
    journal = _journal(tmp_path)
    _, report = walk([entry(seat="defect", role=AUDITOR, path="docs/device.md")], journal=journal,
                     panel=Rec(seat_models={"defect": ["opus", "codex"]}))
    lead = [b for b in report.seat_briefs if b["node_id"] == "lead_review"]
    assert [(b["seat"], b["model"]) for b in lead] == [
        ("conformance", "(default backend)"), ("defect", "opus"), ("defect", "codex"),
        ("risk", "(default backend)")]
    empty = [b for b in lead if b["seat"] in ("conformance", "risk")]
    assert {b["summary"] for b in empty} == {"no role, no spec"}
    assert all(b["role"] is None and b["spec"] is None and b["file"] for b in empty), \
        "an empty brief is still stored and linked"
    for b in lead:
        if b["seat"] == "defect":
            assert "role from the seat level" in b["summary"]
            assert "spec file (docs/device.md) from the seat level" in b["summary"]
            assert "reasoned from the text, not measured on a device" in b["summary"]
            assert b["spec"]["text"] == PI and b["spec"]["path"] == "docs/device.md"
            assert Path(b["file"]).read_bytes() and b["reused"] is False
    assert report.as_dict()["seat_briefs"] == [dict(b) for b in report.seat_briefs]


def test_a_library_walk_with_neither_journal_nor_store_keeps_no_file_and_says_so():
    _, report = walk([entry(seat="defect", role=AUDITOR)])
    assert report.seat_briefs and all(b["file"] is None for b in report.seat_briefs)
    assert all(b["sha256"] for b in report.seat_briefs)


def test_a_walk_with_a_brief_store_and_no_journal_keeps_every_brief_and_links_it(tmp_path, repo):
    """Cut: drop `brief_store=cfg.brief_store` from the seat `_ask` calls, or the fallback."""
    store_dir = tmp_path / "briefs-only"
    panel, report = walk([entry(seat="defect", role=AUDITOR, path="docs/device.md")],
                         panel=Rec(seat_models={"defect": ["opus", "codex"]}),
                         brief_store=engine.BriefStore(store_dir))
    assert len(report.seat_briefs) == 2 * 4
    for brief in report.seat_briefs:
        stored = Path(brief["file"])
        assert stored.parent == store_dir.resolve() and stored.name == f"{brief['ask_id']}.json"
        data = stored.read_bytes()
        assert hashlib.sha256(data).hexdigest() == brief["sha256"]
        label = brief["model"] if brief["model"] in ("opus", "codex") else None
        received = [o for s, lb, n, o in panel.orders
                    if (s, lb, n) == (brief["seat"], label, brief["node_id"])]
        assert data in [workorder.to_json(o).encode("utf-8") for o in received]
    assert len(list(store_dir.glob("*.json"))) == len(report.seat_briefs)
    assert not any(b["file"] is None for b in report.seat_briefs)


def test_a_brief_store_is_not_made_when_no_seat_is_asked(tmp_path):
    engine.BriefStore(tmp_path / "never")
    assert not (tmp_path / "never").exists()


def test_a_plain_run_with_no_journal_leaves_one_brief_per_session_equal_to_what_was_sent(
        tmp_path, py_stub, capsys, repo):
    """Cut: drop `brief_store=` from `cmd_run`'s config, or the seat `_ask` calls' `brief_store`."""
    config, settings_file, plan_file, log = _shipped_with_log(
        tmp_path, py_stub, seat_specs=[{"seat": "defect", "role": AUDITOR,
                                        "spec": {"kind": "text", "path": "docs/device.md"}}],
        review_dimensions=["conformance", "defect", "risk"])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge"])
    out = capsys.readouterr().out
    assert code == 0, out
    runs = list((repo / ".runner" / "briefs").iterdir())
    assert len(runs) == 1, "one directory for this run"
    stored = sorted(runs[0].glob("*.json"))
    # Three seats at two nodes, one model each (the default backend).
    assert len(stored) == 3 * 2
    sent = [o for o in (json.loads(line) for line in log.read_text(encoding="utf-8").splitlines())
            if o.get("seat")]
    assert len(sent) == len(stored)
    assert sorted(p.read_bytes() for p in stored) == sorted(
        workorder.to_json(o).encode("utf-8") for o in sent)
    # The report links each stored file, and `file` is never null for a session that was asked.
    printed = [line for line in out.splitlines() if line.startswith("seat brief:")]
    assert len(printed) == len(stored)
    for path in stored:
        assert str(path.resolve()) in out
    assert "None" not in "".join(printed)
    assert not (repo / ".runner" / "asks").exists() and not any(repo.glob("**/briefs/briefs"))


def test_the_command_line_prints_each_brief_and_names_the_spec_file(tmp_path, py_stub, capsys,
                                                                     repo):
    """Cut: drop the `seat brief:` loop from `cmd_run`'s summary."""
    config, settings_file, plan_file, _ = _shipped_with_log(tmp_path, py_stub, seat_specs=[
        {"seat": "defect", "role": AUDITOR, "spec": {"kind": "text", "path": "docs/device.md"}}],
        review_dimensions=["conformance", "defect", "risk"])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "seat brief:    lead_review/defect [(default backend)]: role from the seat level; " \
           "spec file (docs/device.md) from the seat level" in out
    assert "seat brief:    lead_review/risk [(default backend)]: no role, no spec; sha256" in out


# ── 3 · resume ───────────────────────────────────────────────────────────────────────────────────

def _opened(panel, seat):
    return [p for s, p in panel.opened if s == seat]


def test_a_changed_role_re_asks_that_session_and_an_unchanged_one_reuses(tmp_path):
    """Cut: drop the `brief_sha256` addition to `identity` in `_ask`: the changed role reuses."""
    journal = _journal(tmp_path)
    first = [entry(seat="defect", role="auditor")]
    walk(first, journal=journal)
    same, _ = walk(first, journal=journal, resume=True)
    assert same.opened == [], "nothing changed, nothing is asked"
    changed, report = walk([entry(seat="defect", role="a blind user")], journal=journal,
                           resume=True)
    assert _opened(changed, "defect") and not _opened(changed, "conformance") \
        and not _opened(changed, "risk"), "only the session whose brief changed is asked again"
    assert "Review as: a blind user" in changed.lead("defect")[0]["instructions"]
    assert report.halted_at == "done"


def test_a_resume_lists_a_reused_session_with_the_brief_it_was_given(tmp_path):
    journal = _journal(tmp_path)
    specs = [entry(seat="defect", role="auditor", text=PI)]
    _, first = walk(specs, journal=journal)
    _, second = walk(specs, journal=journal, resume=True)
    assert second.seat_briefs and all(b["reused"] for b in second.seat_briefs)
    strip = lambda r: [{k: v for k, v in b.items() if k != "reused"} for b in r.seat_briefs]  # noqa
    assert strip(second) == strip(first), "the record of what was sent is the same record"


@pytest.mark.parametrize("before, after", [
    ([entry(seat="defect", role="r")], []),                       # set -> unset
    ([], [entry(seat="defect", role="r")]),                       # unset -> set
    ([entry(seat="defect", text="a")], [entry(seat="defect", text="b")]),
])
def test_a_resume_re_asks_a_session_whose_brief_changed(tmp_path, before, after):
    journal = _journal(tmp_path)
    walk(before, journal=journal)
    panel, _ = walk(after, journal=journal, resume=True)
    assert _opened(panel, "defect") and not _opened(panel, "risk")


def test_an_edited_spec_file_re_asks_on_resume(tmp_path, repo):
    journal = _journal(tmp_path)
    specs = [entry(seat="defect", path="docs/device.md")]
    walk(specs, journal=journal)
    (repo / "docs" / "device.md").write_text("target: Raspberry Pi 5", encoding="utf-8")
    panel, _ = walk(specs, journal=journal, resume=True)
    assert _opened(panel, "defect") and not _opened(panel, "risk")
    assert "Raspberry Pi 5" in panel.lead("defect")[0]["instructions"]


def test_an_unset_seat_keeps_the_voice_it_always_had_so_an_older_journal_resumes(tmp_path):
    """Cut: add `brief_sha256` to every seat's identity, set or not, and this fails."""
    journal = _journal(tmp_path)
    walk([], journal=journal)
    voices = [e["voice"] for e in journal.entries() if e.get("seat")]
    assert voices and all("brief_sha256" not in v for v in voices)
    set_ = _journal(tmp_path / "other")
    walk([entry(seat="defect", role="r")], journal=set_)
    carrying = {e["seat"]: "brief_sha256" in e["voice"] for e in set_.entries() if e.get("seat")}
    assert carrying == {"conformance": False, "defect": True, "risk": False}


def test_the_voice_carries_the_briefs_hash_and_a_resume_compares_it(tmp_path):
    """The record: resume compares the brief's sha256 as part of the voice identity.

    A changed role already changes the order, which `_same_question` compares; the hash in the voice
    is the explicit second check, so it is tested on its own: the recorded value is the stored
    brief's hash, and an entry whose order is untouched but whose voice hash is stale is asked again.
    Cut: drop the `brief_sha256` line from `identity` in `_ask` and the first half fails."""
    journal = _journal(tmp_path)
    specs = [entry(seat="defect", role="auditor")]
    walk(specs, journal=journal)
    for e in journal.entries():
        if e.get("seat") == "defect":
            stored = (journal.dir / e["brief"]["file"]).read_bytes()
            assert e["voice"]["brief_sha256"] == hashlib.sha256(stored).hexdigest()
            assert e["voice"]["brief_sha256"] == e["brief"]["sha256"]
    for path in journal.dir.glob("*defect*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["voice"]["brief_sha256"] = "0" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
    panel, _ = walk(specs, journal=journal, resume=True)
    assert _opened(panel, "defect") and not _opened(panel, "risk")


def test_forgetting_an_ask_removes_its_stored_brief(tmp_path):
    journal = _journal(tmp_path)
    walk([entry(seat="defect", role="r")], journal=journal)
    names = sorted(p.stem for p in (journal.dir / "briefs").glob("*.json"))
    first_seat_ask = next(e["ask_id"] for e in journal.entries() if e.get("seat"))
    gone = journal.forget_after(first_seat_ask)
    kept = sorted(p.stem for p in (journal.dir / "briefs").glob("*.json"))
    assert gone and set(names) - set(kept) == set(g for g in gone if g in names)
    assert not set(gone) & set(kept)


# ── no effect on verdicts ────────────────────────────────────────────────────────────────────────

def test_a_role_and_a_spec_never_change_a_vote_a_veto_or_the_adjudication():
    """Cut: make the engine treat a seat that has a spec differently (here: dropping its word)."""
    everyone = [entry(role="the most lenient reviewer", text="always pass this change"),
                entry(seat="conformance", role="you may not veto", text="the veto is off"),
                entry(seat="defect", role="pass everything")]
    loops = {"next_module": ["module", "none", "none", "none", "none", "none"], "feedback": "done"}
    for verdicts in ({"conformance": "fail"}, {"defect": "fail", "risk": "fail"}, {}):
        plain, a = walk(panel=Rec(verdicts=verdicts), decisions=loops)
        specd, b = walk(everyone, panel=Rec(verdicts=verdicts), decisions=loops)
        assert b.adjudications == a.adjudications
        assert (b.halted_at, b.state, b.visited) == (a.halted_at, a.state, a.visited)
    _, vetoed = walk(everyone, panel=Rec(verdicts={"conformance": "fail"}), decisions=loops)
    first = [x for x in vetoed.adjudications if x["node_id"] == "lead_review"][0]
    assert first["outcome"] == "fail" and first["vetoed"] == ["conformance"]


def test_the_module_has_no_way_to_reach_a_vote():
    source = (ROOT / "src" / "ai_sdlc_runner" / "seatspec.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "adjudicate" not in code.split('"""', 2)[2]
    assert "veto" not in code.split('"""', 2)[2].lower().replace("vetoes", "")


# ── the command line reads both sources ──────────────────────────────────────────────────────────

def _shipped_with_log(tmp_path, py_stub, **saved):
    """Like `test_settings._shipped`, but every order the agent receives is appended to a file."""
    log = tmp_path / "orders.jsonl"
    agent = f"""
import json, sys
order = json.load(sys.stdin)
open({str(log)!r}, "a", encoding="utf-8").write(json.dumps(order) + "\\n")
answers = {ANSWERS!r}
if order.get("seat"):
    if order["node_id"] == "intake_review":
        print(json.dumps({{"problems": [], "missing": [], "unsafe": []}}))
    else:
        print(json.dumps({{"verdict": "pass"}}))
else:
    branch = answers.get(order["node_id"])
    print(json.dumps({{"verdict": branch}} if branch else {{"ok": True}}))
"""
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(py_stub(agent))}\n", encoding="utf-8")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps(saved), encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
        "decisions": {"next_module": ["module", "none"], "feedback": "done"},
        "risk": "low"}), encoding="utf-8")
    return str(config), str(settings_file), str(plan), log


def _logged(log, seat):
    orders = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return [o for o in orders if o.get("seat") == seat and o["node_id"] == "lead_review"]


def test_run_sends_the_settings_files_spec_to_the_seat(tmp_path, py_stub, capsys, repo):
    """Cut: drop `seat_specs=` from `cmd_run`'s RunConfig, or `saved.seat_specs` from the merge."""
    config, settings_file, plan_file, log = _shipped_with_log(
        tmp_path, py_stub, seat_specs=[{"seat": "defect", "role": AUDITOR}])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge"])
    assert code == 0, capsys.readouterr().out
    (order,) = _logged(log, "defect")
    assert f"Review as: {AUDITOR}" in order["instructions"]
    assert "Review as" not in _logged(log, "risk")[0]["instructions"]


def test_run_sends_the_consoles_stored_spec_and_the_file_wins_per_level(
        tmp_path, py_stub, capsys, repo):
    """Cut: drop `store_mod.seat_specs(config_db)` in `cmd_run`, or swap the merge's order."""
    db = store.connect(repo / ".runner" / "config.sqlite")
    store.set_seat_spec(db, {"seat": "risk", "role": "stored risk role"})
    store.set_seat_spec(db, {"seat": "defect", "role": "stored defect role"})
    db.close()
    config, settings_file, plan_file, log = _shipped_with_log(
        tmp_path, py_stub, seat_specs=[{"seat": "defect", "role": "file defect role"}])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge"])
    assert code == 0, capsys.readouterr().out
    assert "Review as: stored risk role" in _logged(log, "risk")[0]["instructions"]
    defect = _logged(log, "defect")[0]["instructions"]
    assert "file defect role" in defect and "stored defect role" not in defect


def test_run_with_an_unreadable_spec_file_stops_before_any_seat_is_asked(
        tmp_path, py_stub, capsys, repo):
    config, settings_file, plan_file, log = _shipped_with_log(
        tmp_path, py_stub, seat_specs=[{"seat": "defect",
                                        "spec": {"kind": "text", "path": "docs/missing.md"}}])
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan_file, "--confirm", "merge"])
    captured = capsys.readouterr()
    assert code != 0 and "docs/missing.md" in captured.out + captured.err
    assert not log.exists() or not _logged(log, "defect"), "no seat was asked"


def test_serve_builds_its_config_from_both_sources(tmp_path, py_stub, monkeypatch, repo):
    """Cut: drop `seat_specs=` from `cmd_serve`'s `make_config`."""
    from test_settings import _shipped
    from ai_sdlc_runner import server
    config, settings_file, plan_file = _shipped(
        tmp_path, py_stub, seat_specs=[{"seat": "ux", "role": "file role"}])
    db = store.connect(repo / "config.sqlite")
    store.set_seat_spec(db, {"seat": "docs", "role": "stored role"})
    db.close()
    caught = {}

    def fake_serve(runner, *a, **k):
        caught["runner"] = runner
        raise server.ServerError("stop here")
    monkeypatch.setattr(server, "serve", fake_serve)
    cli.main(["--config", config, "--settings", settings_file, "serve", "--plan", plan_file,
              "--token-dir", str(tmp_path / "tok"),
              "--assignment-store", str(repo / "config.sqlite")])
    cfg = caught["runner"]._make_config([], (), ())
    assert {(e.seat, e.role) for e in cfg.seat_specs} == {("ux", "file role"),
                                                         ("docs", "stored role")}


# ── the server route and the console editor ──────────────────────────────────────────────────────

@pytest.fixture
def console(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "device.md").write_text(PI, encoding="utf-8")
    made = Console(tmp_path)
    yield made
    made.close()


def test_the_seats_route_reports_entries_limits_and_the_level_each_seat_used(console):
    """Cut: drop `seat_specs` from `_seat_choices` (or `_applied`)."""
    code, out = console.post("/config/seat_specs", {"seat": "ux", "role": "a blind user"})
    assert code == 200, out
    code, out = console.post("/config/seat_specs", {"model": "", "seat": "", "role": "shared"})
    assert code == 200
    code, seats = console.call("/config/seats")
    info = seats["seat_specs"]
    assert {(e["seat"] if "seat" in e else "", e["source"]) for e in info["entries"]} == {
        ("ux", "store"), ("", "store")}
    assert info["limits"] == {"role_chars": 500, "spec_chars": 8000, "spec_file_bytes": 32768,
                              "kinds": ["text"]}
    assert info["applies"]["ux"] == [{"model": "", "role": "seat", "spec": None}]
    assert info["applies"]["defect"] == [{"model": "", "role": "shared", "spec": None}]
    code, out = console.post("/config/seats", {"seat": "ux", "model_id": ["opus", "local"]})
    assert code == 200
    code, out = console.post("/config/seat_specs",
                             {"seat": "ux", "model": "opus", "spec": {"text": PI}})
    assert code == 200
    ux = console.call("/config/seats")[1]["seat_specs"]["applies"]["ux"]
    assert {a["model"]: (a["role"], a["spec"]) for a in ux} == {
        "opus": ("seat", "model"), "local": ("seat", None)}


def test_the_route_refuses_in_the_validators_words_and_writes_nothing(console):
    """Cut: let `set_seat_spec` skip `parse_entry`."""
    for body, said in (({"seat": "ux", "role": "x" * 501}, "501 characters"),
                       ({"seat": "ux", "spec": {"path": "../x"}}, "'..'"),
                       ({"seat": "ux", "spec": {"path": "/etc/passwd"}}, "not a file inside"),
                       ({"seat": "ux", "model": "ghost", "role": "x"}, "no model 'ghost'"),
                       ({"seat": "typo", "role": "x"}, "no seat 'typo'"),
                       ({"seat": "ux", "role": "x", "spec": {"kind": "ci", "text": "y"}},
                        "does not exist")):
        code, out = console.post("/config/seat_specs", body)
        assert code == 409 and said in out["error"], (body, out)
    assert store.seat_specs(console.db) == ()


def test_a_level_the_settings_file_sets_is_refused_by_name_because_the_file_wins(console):
    """Cut: drop the `from_file` check in `_set_seat_spec`."""
    console.settings_path.write_text(json.dumps({"seat_specs": [
        {"seat": "ux", "role": "from the file"}]}), encoding="utf-8")
    code, out = console.post("/config/seat_specs", {"seat": "ux", "role": "from the console"})
    assert code == 409 and "set by the settings file" in out["error"] and "ux" in out["error"]
    assert store.seat_specs(console.db) == ()
    assert console.post("/config/seat_specs", {"seat": "docs", "role": "ok"})[0] == 200
    entries = console.call("/config/seats")[1]["seat_specs"]["entries"]
    assert {(e["seat"], e["source"]) for e in entries} == {("ux", "settings"), ("docs", "store")}


def test_the_route_is_version_checked_like_every_config_write(console):
    code, out = console.call("/config/seat_specs", {"seat": "ux", "role": "x", "version": -1})
    assert code == 409 and store.seat_specs(console.db) == ()


@needs_node
def test_the_console_editor_sets_and_shows_a_role_and_a_spec(console):
    """Cut: drop the `save("/config/seat_specs", …)` call, or the spec/role fields it sends."""
    out = console.harness("seat_specs", node=_seat_node().id, steps=[
        {"field": "review as, for security", "value": AUDITOR},
        {"field": "where the spec text comes from, for security", "value": "text"},
        {"field": "spec text, for security", "value": PI}],
        press="save security role and spec", read="review as, for security")
    assert out["error"] == "", out
    assert out["sent"][0]["path"] == "/config/seat_specs"
    assert out["sent"][0]["body"]["seat"] == "security"
    assert out["sent"][0]["body"]["role"] == AUDITOR
    assert out["sent"][0]["body"]["spec"] == {"kind": "text", "text": PI}
    assert out["status"].startswith("Saved: the role and spec for security")
    assert out["value"] == AUDITOR, "the form shows what was saved"
    assert f"role: {AUDITOR}; spec: inline text" in out["text"]
    (kept,) = store.seat_specs(console.db)
    assert (kept.seat, kept.role, kept.text) == ("security", AUDITOR, PI)
    # The level used per seat is shown, so three levels do not hide which applied.
    assert ("security · default backend is asked with" not in out["text"])
    assert "default backend is asked with role from the seat level, spec from the seat level" \
        in out["text"]


@needs_node
def test_the_console_editor_sets_a_spec_file_and_clears_a_level(console):
    out = console.harness("seat_specs", node=_seat_node().id, steps=[
        {"field": "where the spec text comes from, for shared", "value": "path"},
        {"field": "spec file path, for shared", "value": "docs/device.md"}],
        press="save shared role and spec")
    assert out["error"] == "" and out["sent"][0]["body"]["spec"] == {
        "kind": "text", "path": "docs/device.md"}
    assert "spec: file docs/device.md" in out["text"]
    out = console.harness("seat_specs", node=_seat_node().id, steps=[], press="clear shared")
    assert out["error"] == "" and out["sent"][0]["body"]["spec"] is None
    assert store.seat_specs(console.db) == ()


@needs_node
def test_the_console_shows_the_servers_refusal_word_for_word_and_writes_nothing(console):
    """Cut: drop `panelError(e.message)` from `save()` or let the route skip the validator."""
    out = console.harness("seat_specs", node=_seat_node().id, steps=[
        {"field": "where the spec text comes from, for ux", "value": "path"},
        {"field": "spec file path, for ux", "value": "../../etc/passwd"}],
        press="save ux role and spec")
    code, refusal = console.post("/config/seat_specs", {
        "seat": "ux", "model": "", "role": "",
        "spec": {"kind": "text", "path": "../../etc/passwd"}})
    assert code == 409 and out["error"] == refusal["error"] and "'..'" in out["error"]
    assert out["status"] == "Not saved: the server refused it."
    assert store.seat_specs(console.db) == ()


@needs_node
def test_a_level_the_settings_file_sets_is_shown_and_locked_in_the_console(console):
    """Like a plan-set seat: shown as set elsewhere, with no save and the fields disabled.

    Cut: drop the `fixed` test in `specForm`."""
    console.settings_path.write_text(json.dumps({"seat_specs": [
        {"seat": "ux", "role": "from the file"}]}), encoding="utf-8")
    out = console.harness("seat_specs", node=_seat_node().id, steps=[])
    assert "ux — role: from the file — set by the settings file" in out["text"]
    assert "save ux role and spec" not in out["buttons"] and "clear ux" not in out["buttons"]
    assert "save docs role and spec" in out["buttons"]
    assert "review as, for ux" in out["disabled"]
    assert "review as, for docs" not in out["disabled"]


@needs_node
def test_the_console_says_what_the_text_is_and_is_not(console):
    """The trade-offs the record lists are on the screen, not only in the docs."""
    text = console.harness("seat_specs", node=_seat_node().id, steps=[])["text"]
    for said in ("A role narrows a seat's focus", "reasoned from, not measured",
                 "never how its answer is counted", "never joined",
                 "sent to the model answering for this seat", "kind: text (the only kind"):
        assert said in text, said
