"""Tests for the multi-project workspace, structure analysis, cross-repo gate, and executor cwd
(CHG-20260617-08)."""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ai_sdlc_runner import agents, executors, gates, structure_scan, workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_V11 = REPO_ROOT / "skills" / "v1.1.0"


def _mkproj(base: Path, name: str, files: dict) -> Path:
    d = base / name
    (d / "src").mkdir(parents=True)
    for rel, content in files.items():
        (d / rel).write_text(content)
    return d


# --------------------------------------------------------------------------------------
# Workspace model
# --------------------------------------------------------------------------------------

def test_workspace_build_and_save_load(tmp_path):
    a = _mkproj(tmp_path, "main", {"src/app.py": "print(1)"})
    b = _mkproj(tmp_path, "svc", {"index.js": "x"})
    ws = workspace.build(a, [b], name="demo")
    assert ws.is_multi and ws.authority == str(a.resolve())
    path = ws.save()
    assert path.endswith(workspace.WORKSPACE_FILENAME)
    loaded = workspace.load(a)
    assert loaded.authority == ws.authority and loaded.consumers == ws.consumers and loaded.name == "demo"


def test_workspace_single_project_not_multi(tmp_path):
    a = _mkproj(tmp_path, "solo", {"src/app.py": "x"})
    ws = workspace.build(a)
    assert not ws.is_multi and ws.all_projects == [str(a.resolve())]


def test_workspace_validate_missing_path(tmp_path):
    a = _mkproj(tmp_path, "main", {"src/app.py": "x"})
    ws = workspace.Workspace(authority=str(a), consumers=[str(tmp_path / "nope")])
    with pytest.raises(workspace.WorkspaceError):
        ws.validate()


def test_set_authority_swaps(tmp_path):
    a = _mkproj(tmp_path, "a", {"src/x.py": "1"})
    b = _mkproj(tmp_path, "b", {"src/y.py": "1"})
    ws = workspace.build(a, [b])
    ws.set_authority(b)
    assert ws.authority == str(b.resolve()) and str(a.resolve()) in ws.consumers


# --------------------------------------------------------------------------------------
# Structure scan + analyze
# --------------------------------------------------------------------------------------

def test_scan_detects_languages_and_entrypoints(tmp_path):
    p = _mkproj(tmp_path, "app", {"src/app.py": "print(1)", "main.py": "x", "index.js": "y"})
    scan = structure_scan.scan_repo(p)
    assert "Python" in scan.languages and "JavaScript" in scan.languages
    assert any("main.py" in e for e in scan.entrypoints)


def test_write_structure_baseline_creates_four_docs(tmp_path):
    p = _mkproj(tmp_path, "app", {"src/app.py": "print(1)"})
    scan = structure_scan.scan_repo(p)
    written = structure_scan.write_structure_baseline(p, scan)
    names = {Path(w).name for w in written}
    assert names == {"directory.md", "logical.md", "design.md", "data.md"}
    assert "Tree" in (p / "docs" / "structure" / "directory.md").read_text()


def test_analyze_workspace_sets_authority_and_pointers(tmp_path):
    a = _mkproj(tmp_path, "main", {"src/app.py": "x"})
    b = _mkproj(tmp_path, "svc", {"index.js": "y"})
    ws = workspace.build(a, [b])
    result = structure_scan.analyze_workspace(ws, "1.0.0")
    assert len(result.scanned) == 2 and len(result.scaffolded) == 8
    assert (a / "docs" / "contracts" / "VERSION").read_text().strip() == "v1.0.0"
    pointer = (b / "docs" / "authority.md").read_text()
    assert "Pinned version: v1.0.0" in pointer     # exact format cross_repo_check.py parses


def test_analyze_single_project_no_contracts(tmp_path):
    a = _mkproj(tmp_path, "solo", {"src/app.py": "x"})
    ws = workspace.build(a)
    structure_scan.analyze_workspace(ws, "1.0.0")
    assert not (a / "docs" / "contracts").exists()   # no cross-repo wiring for a single project


# --------------------------------------------------------------------------------------
# Executor working directory (CLI agent runs inside the target project)
# --------------------------------------------------------------------------------------

def test_agent_spec_carries_workdir():
    spec = agents.spawn(STORE_V11, "I1", scope="src", task="impl", workdir="/tmp/proj")
    assert spec.workdir == "/tmp/proj" and "/tmp/proj" in spec.prompt


def test_command_executor_runs_in_workdir(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    script = tmp_path / "pwd.sh"
    script.write_text("#!/bin/sh\npwd\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    ex = executors.CommandExecutor(argv=[str(script)])
    spec = agents.AgentSpec("I1", ["Read"], False, True, "src", "p", workdir=str(proj))
    r = ex.run(spec)
    assert r["output"].strip() == str(proj)


# --------------------------------------------------------------------------------------
# Cross-repo gate via the skill's script
# --------------------------------------------------------------------------------------

@pytest.mark.skipif(not STORE_V11.is_dir(), reason="skill store not present")
def test_cross_repo_gate_consistent_then_drift(tmp_path):
    a = _mkproj(tmp_path, "main", {"src/app.py": "x"})
    b = _mkproj(tmp_path, "svc", {"index.js": "y"})
    ws = workspace.build(a, [b])
    structure_scan.analyze_workspace(ws, "1.0.0")
    # Consistent.
    d = gates.check_cross_repo_drift(STORE_V11, ws.authority, ws.consumers)
    assert not d.is_halt
    # Bump the authority contract; the consumer is now behind → drift.
    (a / "docs" / "contracts" / "VERSION").write_text("v2\n")
    d2 = gates.check_cross_repo_drift(STORE_V11, ws.authority, ws.consumers)
    assert d2.is_halt
