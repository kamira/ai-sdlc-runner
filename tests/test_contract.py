"""Tests for the version-lock core and migrate decisions (build-guide §6).

Covers: contract_key (patch ignored), resolve_contract first-run/patch-pass/minor-block/major-block,
and migrate (success vs incompatibility list with the lock left unchanged). Also a smoke test that
a spawned V1 never receives the `Agent` tool, using the local skill cache when available.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ai_sdlc_runner import contract


# --------------------------------------------------------------------------------------
# contract_key — patch is ignored
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("ver,key", [
    ("1.2.3", (1, 2)),
    ("1.2.0", (1, 2)),
    ("1.2.99", (1, 2)),
    ("2.0.0", (2, 0)),
    ("10.4.7", (10, 4)),
])
def test_contract_key_ignores_patch(ver, key):
    assert contract.contract_key(ver) == key


def test_contract_key_invalid():
    with pytest.raises(contract.ContractError):
        contract.contract_key("nope")


# --------------------------------------------------------------------------------------
# resolve_contract — per-project lock behavior
# --------------------------------------------------------------------------------------

def test_first_run_writes_lock(tmp_path):
    ver = contract.resolve_contract(tmp_path, "1.2.0")
    assert ver == "1.2.0"
    lock = json.loads((tmp_path / contract.LOCK_FILENAME).read_text())
    assert (lock["contract_major"], lock["contract_minor"]) == (1, 2)
    assert lock["contract_version"] == "1.2.0"


def test_patch_bump_passes(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.0")
    # Same major.minor, higher patch -> passes freely.
    assert contract.resolve_contract(tmp_path, "1.2.7") == "1.2.7"


def test_minor_bump_blocked(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.0")
    with pytest.raises(contract.MigrateRequired) as exc:
        contract.resolve_contract(tmp_path, "1.3.0")
    assert exc.value.locked == (1, 2)
    assert exc.value.requested == (1, 3)


def test_major_bump_blocked(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.0")
    with pytest.raises(contract.MigrateRequired):
        contract.resolve_contract(tmp_path, "2.0.0")


def test_none_requested_continues_lock(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.5")
    # No new request -> continue the locked version.
    assert contract.resolve_contract(tmp_path, None) == "1.2.5"


def test_no_lock_no_request_errors(tmp_path):
    with pytest.raises(contract.ContractError):
        contract.resolve_contract(tmp_path, None)


# --------------------------------------------------------------------------------------
# migrate — validating upgrade
# --------------------------------------------------------------------------------------

def _seed_docs(project: Path, good: bool = True):
    (project / "docs" / "structure").mkdir(parents=True, exist_ok=True)
    (project / "docs" / "changes").mkdir(parents=True, exist_ok=True)
    (project / "docs" / "ai-guideline.md").write_text("# Guideline\nok\n" if good else "")
    (project / "docs" / "structure" / "logical.md").write_text("# Logical\nok\n")
    (project / "docs" / "changes" / "CHG-1.md").write_text("# CHG\nok\n")


def test_migrate_success_raises_lock(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.0")
    _seed_docs(tmp_path, good=True)
    result = contract.migrate(tmp_path, "1.3.0")
    assert result.ok is True
    assert len(result.checked) >= 3
    lock = json.loads((tmp_path / contract.LOCK_FILENAME).read_text())
    assert (lock["contract_major"], lock["contract_minor"]) == (1, 3)


def test_migrate_failure_lists_incompat_and_keeps_lock(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.0")
    _seed_docs(tmp_path, good=False)  # empty ai-guideline.md => incompatibility
    result = contract.migrate(tmp_path, "1.3.0")
    assert result.ok is False
    assert any("ai-guideline.md" in item for item in result.incompatibilities)
    # Lock must be unchanged after a failed migrate.
    lock = json.loads((tmp_path / contract.LOCK_FILENAME).read_text())
    assert (lock["contract_major"], lock["contract_minor"]) == (1, 2)


def test_migrate_then_resolve_consistent(tmp_path):
    contract.resolve_contract(tmp_path, "1.2.0")
    _seed_docs(tmp_path, good=True)
    contract.migrate(tmp_path, "1.3.0")
    # After a successful migrate, 1.3.x resolves without requiring another migrate.
    assert contract.resolve_contract(tmp_path, "1.3.4") == "1.3.4"


# --------------------------------------------------------------------------------------
# read_skill_version + V1 tool lockdown (uses local skill cache if reachable)
# --------------------------------------------------------------------------------------

_SKILL_CACHE = os.environ.get("AI_SDLC_SKILL_PATH")


@pytest.mark.skipif(not _SKILL_CACHE or not Path(_SKILL_CACHE).is_dir(),
                    reason="skill cache not provided via AI_SDLC_SKILL_PATH")
def test_read_skill_version_from_cache():
    ver = contract.read_skill_version(_SKILL_CACHE)
    assert contract.contract_key(ver)  # parses to (major, minor)


@pytest.mark.skipif(not _SKILL_CACHE or not Path(_SKILL_CACHE).is_dir(),
                    reason="skill cache not provided via AI_SDLC_SKILL_PATH")
def test_v1_spawn_excludes_agent():
    from ai_sdlc_runner import agents
    spec = agents.spawn(_SKILL_CACHE, "V1", scope="read-only", task="verify")
    assert "Agent" not in spec.tools
