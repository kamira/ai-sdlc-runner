"""What the auditor reads, and what the cap left out (CHG-20261028-01, task 2a)."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ai_sdlc_runner import auditscope, cli, engine, policy

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """pkg/a.py is changed; pkg/b.py is what it imports; pkg/c.py imports it; pkg/d.py is unrelated."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("from pkg import b\n\ndef run():\n    return b.value()\n", "utf-8")
    (pkg / "b.py").write_text("def value():\n    return 1\n", "utf-8")
    (pkg / "c.py").write_text("from pkg.a import run\n\nrun()\n", "utf-8")
    (pkg / "d.py").write_text("x = 1\n", "utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = auditscope.capture_base(str(tmp_path))
    (pkg / "a.py").write_text("from pkg import b\n\ndef run():\n    return b.value() + 1\n", "utf-8")
    return tmp_path, base


def _by_path(scope):
    return {e["path"]: e for e in scope["files"]}


def test_the_cap_is_provisional_and_cites_the_change():
    """The cap is a first estimate; the comment saying so is part of the contract (Q3)."""
    import inspect
    source = inspect.getsource(auditscope)
    assert "AUDIT_SCOPE_MAX_CHARS = " in source
    before = source.split("AUDIT_SCOPE_MAX_CHARS = ")[0].splitlines()[-6:]
    assert "Provisional" in " ".join(before).title().replace("**", "")
    assert "CHG-20261028-01" in " ".join(before)
    assert isinstance(auditscope.AUDIT_SCOPE_MAX_CHARS, int) and auditscope.AUDIT_SCOPE_MAX_CHARS > 0


@needs_git
def test_the_scope_is_the_diff_its_callees_and_its_callers(repo):
    root, base = repo
    scope = auditscope.assemble(str(root), base)
    files = _by_path(scope)
    assert files["pkg/a.py"]["why"] == "diff"
    assert files["pkg/b.py"]["why"] == "callee"
    assert files["pkg/c.py"]["why"] == "caller"
    assert "pkg/d.py" not in files, "an unrelated module is not the change's neighbourhood"
    assert scope["cut"] == [] and scope["base"] == base
    assert all(e["state"] == "read" for e in scope["files"])
    assert scope["total_chars"] == scope["read_chars"] > 0


@needs_git
def test_a_new_untracked_file_is_part_of_the_change(repo):
    root, base = repo
    (root / "pkg" / "new.py").write_text("from pkg import d\n", "utf-8")
    files = _by_path(auditscope.assemble(str(root), base))
    assert files["pkg/new.py"]["why"] == "diff" and files["pkg/d.py"]["why"] == "callee"


@needs_git
def test_a_scope_over_the_cap_records_the_cut_files(repo):
    """The wire: cut `state = "cut"` (or the cap check) and every file reads as `read`."""
    root, base = repo
    full = auditscope.assemble(str(root), base)
    cap = _by_path(full)["pkg/a.py"]["chars"]          # room for the diff and nothing else
    scope = auditscope.assemble(str(root), base, max_chars=cap)
    files = _by_path(scope)
    assert files["pkg/a.py"]["state"] == "read"
    assert files["pkg/b.py"]["state"] == "cut" and files["pkg/c.py"]["state"] == "cut"
    assert sorted(scope["cut"]) == ["pkg/b.py", "pkg/c.py"]
    assert scope["cap"] == cap and scope["total_chars"] == full["total_chars"]
    assert scope["read_chars"] == cap
    # The empty package file costs nothing, so it fits; b and c do not, and are not listed.
    assert auditscope.reading_list(scope) == ["pkg/a.py", "pkg/__init__.py"]


def test_a_cut_scope_is_printed_and_a_whole_one_is_not_called_cut():
    cut = {"cap": 10, "total_chars": 30, "read_chars": 8, "cut": ["x.py"],
           "files": [{"path": "a.py", "state": "read"}, {"path": "x.py", "state": "cut"}],
           "notes": ["callers and callees are resolved for Python only"]}
    lines = auditscope.summary(cut)
    assert lines[0].startswith("audit scope: 1 of 2 file(s) read, 8 of 30 characters (cap 10)")
    assert any("CUT" in l and "x.py" in l for l in lines)
    whole = dict(cut, cut=[], files=[{"path": "a.py", "state": "read"}], notes=[])
    assert not any("CUT" in l for l in auditscope.summary(whole))
    assert auditscope.summary({}) == [], "no audit, nothing to say"


def test_the_run_prints_a_cut_scope_beside_the_outcome(tmp_path, py_stub, capsys, monkeypatch):
    """The wire from the report to the terminal: cut the loop in `cmd_run` and nothing prints."""
    from test_settings import _shipped
    real = engine.walk

    def walk(cfg, factory, enabled=False):
        report = real(cfg, factory, enabled=enabled)
        report.audit_scope = {"cap": 10, "total_chars": 30, "read_chars": 8, "cut": ["x.py"],
                              "files": [{"path": "a.py", "state": "read"},
                                        {"path": "x.py", "state": "cut"}], "notes": []}
        return report

    monkeypatch.setattr(engine, "walk", walk)
    config, settings_file, plan = _shipped(tmp_path, py_stub)
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan, "--confirm", "merge"])
    out = capsys.readouterr().out
    assert "audit scope: 1 of 2 file(s) read" in out
    assert "audit scope CUT, the auditor did not read: x.py" in out
    assert engine.RunReport().as_dict()["audit_scope"] == {}


def test_without_git_the_scope_says_so_instead_of_pretending(tmp_path):
    scope = auditscope.assemble(str(tmp_path), None)
    if shutil.which("git") is not None:
        # tmp_path may sit inside someone's repository; either way nothing is invented.
        assert isinstance(scope["files"], list)
    assert "notes" in scope


@needs_git
def test_the_base_is_remembered_across_a_resume(tmp_path):
    auditscope.save_base(tmp_path / "audit", "abc123")
    assert auditscope.load_base(tmp_path / "audit") == (True, "abc123")
    auditscope.save_base(tmp_path / "audit2", None)
    assert auditscope.load_base(tmp_path / "audit2") == (True, None)
    assert auditscope.load_base(tmp_path / "nowhere") == (False, None)


def test_a_scope_is_saved_as_json(tmp_path):
    auditscope.save(tmp_path / "audit", {"cap": 1, "files": []})
    assert json.loads((tmp_path / "audit" / "scope.json").read_text("utf-8"))["cap"] == 1


# ── a finding with no location is refused ────────────────────────────────────────────────────


@pytest.mark.parametrize("drop", ["file", "line"])
def test_a_finding_without_file_or_line_is_refused(drop):
    finding = {"id": "1", "file": "a.py", "line": "3", "claim": "wrong", "trigger": "x -> y",
               "severity": "important", "origin": "introduced"}
    del finding[drop]
    with pytest.raises(policy.PolicyError, match=drop):
        policy.read_findings([finding], source="defect")


@pytest.mark.parametrize("bad", ["", "0", "-2", "three"])
def test_a_line_that_is_not_a_line_is_refused(bad):
    finding = {"id": "1", "file": "a.py", "line": bad, "claim": "wrong", "trigger": "x -> y",
               "severity": "important", "origin": "introduced"}
    with pytest.raises(policy.PolicyError):
        policy.read_findings([finding], source="defect")
