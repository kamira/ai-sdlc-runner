"""Tests for the multi-panel dashboard (CHG-20260617-03).

Covers the DashboardModel panels (status / exec log / verify / agent merged+tabbed), the display-width
helpers, the snapshot renderer, and that the orchestrator's on_event hook feeds the model — all without
a real TTY (curses path is not unit-tested).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_sdlc_runner import contract, dashboard, orchestrator, state


# --------------------------------------------------------------------------------------
# Display-width helpers (CJK alignment)
# --------------------------------------------------------------------------------------

def test_display_width_counts_cjk_as_two():
    assert dashboard._dw("abc") == 3
    assert dashboard._dw("狀態") == 4          # two wide chars
    assert dashboard._dw("a狀") == 3


def test_fit_truncates_and_pads_to_display_width():
    assert dashboard._fit("abc", 5) == "abc  "
    assert dashboard._fit("狀態", 4) == "狀態"
    # Never split a wide char: width-3 budget keeps only the first wide char + pad.
    out = dashboard._fit("狀態", 3)
    assert dashboard._dw(out) == 3


def test_panel_borders_align_with_cjk_title():
    lines = dashboard._panel("狀態 / Status", ["x"], width=40)
    # Every rendered line has identical display width (top, body, bottom all align).
    widths = {dashboard._dw(ln) for ln in lines}
    assert widths == {40}


# --------------------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------------------

def test_status_panel_progress_and_lock(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.0")
    st = state.RunState()
    state.checkpoint(tmp_path, st, "requirement_analysis")
    model = dashboard.DashboardModel.from_saved(tmp_path)
    body = "\n".join(model.status_panel())
    assert "1/4 stages" in body
    assert "locked 1.2.x" in body
    assert "branch:" in body  # tmp_path isn't a git repo -> "(not a git repo)"


def test_exec_log_panel_from_events():
    m = dashboard.DashboardModel(project_dir=".")
    m.add({"type": "stage", "stage": "implement"})
    m.add({"type": "gate", "gate": "before_implement", "risk": "low", "result": "AUTO"})
    m.add({"type": "halt", "gate": "before_merge_or_release"})
    body = "\n".join(m.exec_log_panel())
    assert "implement" in body and "AUTO" in body and "HALTED" in body


def test_verify_panel_reads_acc(tmp_path):
    acc = tmp_path / "docs" / "acceptance"
    acc.mkdir(parents=True)
    (acc / "ACC-1.md").write_text("# ACC-1\n- Conclusion: **Pass**\n")
    model = dashboard.DashboardModel.from_saved(tmp_path)
    body = "\n".join(model.verify_panel())
    assert "ACC-1.md" in body and "Pass" in body


def test_agent_panel_merged_vs_tabbed():
    m = dashboard.DashboardModel(project_dir=".")
    for role in ("A1", "I1", "I1.1", "V1"):
        m.add({"type": "agent", "role": role, "phase": "dispatch", "scope": f"scope-{role}"})
    merged = m.agent_panel(dashboard.AGENT_VIEW_MERGED)
    assert all(line.startswith("[") for line in merged)          # chronological, prefixed by role
    tabbed = "\n".join(m.agent_panel(dashboard.AGENT_VIEW_TABBED))
    assert "[A1]" in tabbed and "[V1]" in tabbed                 # grouped headers per agent


def test_render_snapshot_has_all_panels(tmp_path):
    model = dashboard.DashboardModel.from_saved(tmp_path)
    snap = dashboard.render_snapshot(model)
    for title in ("Status", "Execution log", "Verification", "Agent log"):
        assert title in snap


# --------------------------------------------------------------------------------------
# Panel caching (CHG-20260703-05): zero git/disk I/O per keystroke in the resident dashboard.
# --------------------------------------------------------------------------------------

def test_status_panel_is_cached_until_refresh(tmp_path, monkeypatch):
    """`status_panel()` must shell out to `_git` only on the first call after construction/`refresh()`
    — repeated calls (simulating per-keystroke redraws) must hit the cache, not re-run git."""
    calls = {"n": 0}
    real_git = dashboard._git

    def counting_git(project_dir, *args):
        calls["n"] += 1
        return real_git(project_dir, *args)

    monkeypatch.setattr(dashboard, "_git", counting_git)

    model = dashboard.DashboardModel.from_saved(tmp_path)
    model.status_panel()
    first_call_count = calls["n"]
    assert first_call_count > 0  # sanity: status_panel does call _git at least once

    # Many more "redraws" must not touch git again.
    for _ in range(20):
        model.status_panel()
    assert calls["n"] == first_call_count

    # refresh() invalidates the cache: the next call recomputes exactly once more.
    model.refresh()
    model.status_panel()
    assert calls["n"] > first_call_count
    second_call_count = calls["n"]

    # And it's cached again after that single recompute.
    for _ in range(20):
        model.status_panel()
    assert calls["n"] == second_call_count


def test_verify_panel_is_cached_until_refresh(tmp_path, monkeypatch):
    """`verify_panel()` must read the ACC directory only on the first call after construction/
    `refresh()` — repeated calls must hit the cache, not re-glob/re-read disk."""
    acc = tmp_path / "docs" / "acceptance"
    acc.mkdir(parents=True)
    (acc / "ACC-1.md").write_text("# ACC-1\n- Conclusion: **Pass**\n")

    reads = {"n": 0}
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self.name.startswith("ACC-") and self.suffix == ".md":
            reads["n"] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    model = dashboard.DashboardModel.from_saved(tmp_path)
    model.verify_panel()
    assert reads["n"] == 1

    for _ in range(20):
        model.verify_panel()
    assert reads["n"] == 1  # still just the one read — cache held

    model.refresh()
    model.verify_panel()
    assert reads["n"] == 2  # refresh() forced exactly one more recompute

    for _ in range(20):
        model.verify_panel()
    assert reads["n"] == 2


def test_refresh_leaves_exec_log_and_agent_panel_live():
    """`refresh()` must only touch the cached I/O-bound panels; exec_log/agent panels always read
    the live in-memory event list, uncached, before and after a refresh()."""
    m = dashboard.DashboardModel(project_dir=".")
    m.add({"type": "stage", "stage": "implement"})
    before = m.exec_log_panel()
    m.refresh()
    m.add({"type": "stage", "stage": "verify"})
    after = m.exec_log_panel()
    assert before != after
    assert "verify" in "\n".join(after)


def test_render_snapshot_cold_cache_matches_uncached_output(tmp_path):
    """The read-only snapshot path (`render_snapshot` after `from_saved`) computes each panel exactly
    once (cache cold -> compute), producing identical output to today's uncached behavior."""
    contract.resolve_contract(tmp_path, "1.2.0")
    st = state.RunState()
    state.checkpoint(tmp_path, st, "requirement_analysis")
    acc = tmp_path / "docs" / "acceptance"
    acc.mkdir(parents=True)
    (acc / "ACC-1.md").write_text("# ACC-1\n- Conclusion: **Pass**\n")

    model = dashboard.DashboardModel.from_saved(tmp_path)
    snap = dashboard.render_snapshot(model)
    assert "1/4 stages" in snap
    assert "locked 1.2.x" in snap
    assert "ACC-1.md" in snap and "Pass" in snap


# --------------------------------------------------------------------------------------
# Orchestrator event hook feeds the model
# --------------------------------------------------------------------------------------

def test_on_event_feeds_model(tmp_path, _skill_path):
    model = dashboard.DashboardModel(project_dir=str(tmp_path))
    report = orchestrator.run(
        tmp_path,
        skill_path=_skill_path,
        config={"concurrency_max": 2, "nesting_depth_max": 2},
        requested_version="1.0.0",
        risk="medium",
        on_event=model.add,
    )
    # The delivery red-line halts the run; events captured along the way.
    assert report.status == "halted_for_approval"
    types = {e["type"] for e in model.events}
    assert {"stage", "gate", "agent"} <= types
    # Agent events include the role chain.
    roles = {e.get("role") for e in model.events if e["type"] == "agent"}
    assert "A1" in roles and "I1" in roles and "V1" in roles


# --------------------------------------------------------------------------------------
# Resident interactive console (CHG-20260703-03) — command parser
# --------------------------------------------------------------------------------------

def test_parse_command_open_requires_path():
    cmd = dashboard.parse_command("/open /some/path")
    assert cmd.kind == "open" and cmd.arg == "/some/path"

    missing = dashboard.parse_command("/open")
    assert missing.kind == "unknown" and "usage" in missing.error


def test_parse_command_run_with_and_without_inline_text():
    assert dashboard.parse_command("/run").kind == "run"
    assert dashboard.parse_command("/run").arg == ""
    with_text = dashboard.parse_command("/run add the login flow")
    assert with_text.kind == "run" and with_text.arg == "add the login flow"


@pytest.mark.parametrize("raw,kind", [
    ("/status", "status"),
    ("/check", "check"),
    ("/menu", "menu"),
    ("/help", "help"),
    ("/quit", "quit"),
    ("/QUIT", "quit"),          # case-insensitive
    ("  /status  ", "status"),  # tolerates surrounding whitespace
])
def test_parse_command_known_slash_commands(raw, kind):
    assert dashboard.parse_command(raw).kind == kind


def test_parse_command_plain_text_is_a_task():
    cmd = dashboard.parse_command("add a login page")
    assert cmd.kind == "task"
    assert cmd.arg == "add a login page"


def test_parse_command_empty_line_is_noop():
    assert dashboard.parse_command("").kind == "noop"
    assert dashboard.parse_command("   ").kind == "noop"


def test_parse_command_unknown_slash_has_helpful_error():
    cmd = dashboard.parse_command("/bogus")
    assert cmd.kind == "unknown"
    assert "/bogus" in cmd.error
    assert "/help" in cmd.error


# --------------------------------------------------------------------------------------
# 2-col bounded-height layout — Status + Verification always present under log overflow
# --------------------------------------------------------------------------------------

def _model_with_many_events(tmp_path):
    model = dashboard.DashboardModel(project_dir=str(tmp_path))
    for i in range(200):
        model.add({"type": "stage", "stage": f"stage-{i}"})
        model.add({"type": "agent", "role": "I1", "phase": "dispatch", "scope": f"scope-{i}"})
    return model


def test_render_layout_keeps_top_panels_under_log_overflow(tmp_path):
    model = _model_with_many_events(tmp_path)
    for height in (8, 12, 24, 50):
        lines = dashboard.render_layout(model, width=90, height=height, input_line="")
        text = "\n".join(lines)
        assert "Status" in text
        assert "Verification" in text
        # Not every one of the 200 synthetic events fits — the log column is bounded.
        assert text.count("stage-") < 200


def test_render_layout_bounds_log_lines_by_available_height(tmp_path):
    model = _model_with_many_events(tmp_path)
    tall = dashboard.render_layout(model, width=90, height=40, input_line="")
    # The taller layout has more room, so it must include the very last synthetic event; a much
    # shorter terminal (see the overflow test above) still never pushes Status/Verification off.
    assert "stage-199" in "\n".join(tall)


def test_render_layout_shows_input_line_and_current_project():
    project = "/proj/demo"  # short, deliberately, so it survives the panel's column-width truncation
    model = dashboard.DashboardModel(project_dir=project)
    lines = dashboard.render_layout(model, width=80, height=20, input_line="hello world",
                                     current_project=project)
    text = "\n".join(lines)
    assert "> hello world" in text
    assert project in text


def test_render_layout_empty_start_shows_no_project_hint(tmp_path):
    model = dashboard.DashboardModel.from_saved(tmp_path)
    lines = dashboard.render_layout(model, width=80, height=20, input_line="", current_project=None)
    assert "/open" in "\n".join(lines)


# --------------------------------------------------------------------------------------
# Approver decision mapping
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("selection,expected", [
    (0, True),                 # arrow-key index 0 == "Approve"
    (1, False),                # arrow-key index 1 == "Reject"
    (True, True),
    (False, False),
    ("y", True),
    ("yes", True),
    ("approve", True),
    ("n", False),
    ("no", False),
    ("reject", False),
    (None, None),               # cancelled selector -> no decision, never an implicit approval
    ("", None),
    ("banana", None),
    (2, None),                  # out-of-range index -> no decision
])
def test_approve_decision_mapping(selection, expected):
    assert dashboard.approve_decision(selection) is expected


def test_approve_options_are_approve_then_reject():
    labels = [label for label, _desc in dashboard.APPROVE_OPTIONS]
    assert labels == ["Approve", "Reject"]


# --------------------------------------------------------------------------------------
# apply_key (CHG-20260703-04: any-language / CJK input via get_wch())
# --------------------------------------------------------------------------------------

def test_apply_key_appends_ascii_char():
    buf, action = dashboard.apply_key("h", "i")
    assert (buf, action) == ("hi", "edit")


def test_apply_key_appends_single_cjk_char():
    # get_wch() hands back one fully-decoded character per keystroke, even for CJK — prove a
    # single Chinese character appends as itself, not as mangled Latin-1 bytes.
    buf, action = dashboard.apply_key("", "你")
    assert (buf, action) == ("你", "edit")


def test_apply_key_builds_multi_char_cjk_string_across_keystrokes():
    buf, action = dashboard.apply_key("", "你")
    assert action == "edit"
    buf, action = dashboard.apply_key(buf, "好")
    assert (buf, action) == ("你好", "edit")


def test_apply_key_mixed_ascii_and_cjk_sequence():
    buf = ""
    for ch in "a你b好c":
        buf, action = dashboard.apply_key(buf, ch)
        assert action == "edit"
    assert buf == "a你b好c"


@pytest.mark.parametrize("enter_char", ["\n", "\r"])
def test_apply_key_enter_submits_without_changing_buffer(enter_char):
    buf, action = dashboard.apply_key("你好", enter_char)
    assert (buf, action) == ("你好", "submit")


@pytest.mark.parametrize("backspace_char", ["\x7f", "\b", "\x08"])
def test_apply_key_backspace_removes_last_char(backspace_char):
    buf, action = dashboard.apply_key("你好", backspace_char)
    assert (buf, action) == ("你", "edit")


@pytest.mark.parametrize("backspace_char", ["\x7f", "\b", "\x08"])
def test_apply_key_backspace_on_empty_buffer_stays_empty(backspace_char):
    buf, action = dashboard.apply_key("", backspace_char)
    assert (buf, action) == ("", "edit")


def test_apply_key_other_control_char_is_noop():
    buf, action = dashboard.apply_key("你好", "\x01")  # e.g. Ctrl-A, not Enter/Backspace
    assert (buf, action) == ("你好", "noop")


# --------------------------------------------------------------------------------------
# Resident app: current-project state + plain-text-task dispatch
# --------------------------------------------------------------------------------------

def test_resident_state_starts_with_no_project():
    st = dashboard.ResidentState()
    assert st.current_project is None


def test_resident_state_open_project_sets_current(tmp_path):
    st = dashboard.ResidentState()
    st.open_project(str(tmp_path))
    assert st.current_project == str(tmp_path)
    assert isinstance(st.model, dashboard.DashboardModel)


def test_resident_state_open_project_leaves_caches_cold(tmp_path):
    """`open_project` builds a fresh model and calls `refresh()` — the caches must be cold (None)
    so the next render recomputes for the newly-opened project rather than reusing a stale cache."""
    st = dashboard.ResidentState()
    st.open_project(str(tmp_path))
    assert st.model._status_cache is None
    assert st.model._verify_cache is None


def test_resident_app_open_command_sets_current_project(tmp_path):
    app = dashboard.ResidentApp()
    assert app.state.current_project is None
    cont = app.dispatch(f"/open {tmp_path}")
    assert cont is True
    assert app.state.current_project == str(tmp_path)


def test_resident_app_quit_command_stops_the_loop():
    app = dashboard.ResidentApp()
    assert app.dispatch("/quit") is False


def test_resident_app_task_without_project_gives_clear_hint():
    app = dashboard.ResidentApp()
    app.dispatch("fix the login bug")
    assert "/open" in app.state.status_line


def test_resident_app_plain_text_task_starts_a_run(tmp_path, _skill_path):
    """A plain-text (non-slash) line on an open project records the requirement into the exec feed
    and drives a real (stub-backend) run through the unchanged orchestrator — including blocking for
    an approval at the delivery red-line gate, answered here by an injected asker (never an implicit
    auto-approve)."""
    app = dashboard.ResidentApp(project=str(tmp_path),
                                config={"concurrency_max": 1, "nesting_depth_max": 1,
                                        "skill_path": _skill_path, "contract_version": "1.0.0"})
    app.dispatch("add a login page", asker=lambda decision: 0)  # 0 == Approve every gate
    body = "\n".join(app.state.model.exec_log_panel())
    assert "add a login page" in body
    assert app.state.status_line.startswith("run:")


def test_resident_app_start_run_refreshes_caches_after_run(tmp_path, _skill_path):
    """`_start_run` must call `model.refresh()` after `orchestrator.run(...)` returns, so status/
    verification reflect the run's checkpoints + any new ACC files on the next redraw."""
    app = dashboard.ResidentApp(project=str(tmp_path),
                                config={"concurrency_max": 1, "nesting_depth_max": 1,
                                        "skill_path": _skill_path, "contract_version": "1.0.0"})
    model = app.state.model
    # Warm the caches before the run, as a per-keystroke redraw would.
    model.status_panel()
    model.verify_panel()
    assert model._status_cache is not None
    assert model._verify_cache is not None

    app.dispatch("add a login page", asker=lambda decision: 0)  # 0 == Approve every gate

    # Same model instance (ensure_model reuses it); caches must be cold again post-run.
    assert app.state.model is model
    assert model._status_cache is None
    assert model._verify_cache is None


def test_resident_app_reject_at_halt_gate_halts_the_run(tmp_path, _skill_path):
    """Rejecting at a HALT gate must actually stop the run (never an implicit continue)."""
    app = dashboard.ResidentApp(project=str(tmp_path),
                                config={"concurrency_max": 1, "nesting_depth_max": 1,
                                        "skill_path": _skill_path, "contract_version": "1.0.0"})
    app.dispatch("ship it", asker=lambda decision: 1)  # 1 == Reject every gate
    assert "halted_for_approval" in app.state.status_line


def test_resident_app_run_command_uses_inline_requirement(tmp_path, _skill_path):
    app = dashboard.ResidentApp(project=str(tmp_path),
                                config={"concurrency_max": 1, "nesting_depth_max": 1,
                                        "skill_path": _skill_path, "contract_version": "1.0.0"})
    app.dispatch("/run ship the feature", asker=lambda decision: 0)
    body = "\n".join(app.state.model.exec_log_panel())
    assert "ship the feature" in body
