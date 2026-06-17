"""Tests for the multi-panel dashboard (CHG-20260617-03).

Covers the DashboardModel panels (status / exec log / verify / agent merged+tabbed), the display-width
helpers, the snapshot renderer, and that the orchestrator's on_event hook feeds the model — all without
a real TTY (curses path is not unit-tested).
"""
from __future__ import annotations

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
