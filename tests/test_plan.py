"""The plan file, closed (CHG-20260823-28).

It was the outermost schema and the only entry point with **no validation at all** — six seat
reviews named it, and one gave the case that decided it:

> a plan whose `ship` key is misspelled runs with no side effects and reports `finished`

Every test below drives the refusal rather than reading the source, and the last two drive the whole
CLI so the refusal is proven at the door an operator actually walks through.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_sdlc_runner import cli, plan  # noqa: E402

GOOD_SHIP = {"repo": ".", "chg_id": "CHG-1", "branch": "b", "message": "m"}


# ── closed at the top level ───────────────────────────────────────────────────────────────────

def test_the_shipped_example_still_loads():
    """The refusal must not refuse the plan the README tells people to run."""
    loaded = plan.load(ROOT / "examples" / "plan.json")
    assert set(loaded) <= set(plan.FIELDS)
    assert loaded["risk"] == "low"


@pytest.mark.parametrize("typo", ["operationz", "node_spec", "seatmodels", "Ship", "notes"])
def test_an_unknown_top_level_key_is_refused(typo):
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"risk": "low", typo: {}})
    assert typo in str(exc.value)
    assert "look configured and do nothing" in str(exc.value)


def test_every_key_the_code_reads_is_one_the_plan_may_carry():
    """The two lists must not drift: a key `cli.py` reads and `FIELDS` lacks would be refused on a
    plan that is correct, which is the failure mode of a closed schema built from memory."""
    import re
    source = (ROOT / "src" / "ai_sdlc_runner" / "cli.py").read_text(encoding="utf-8")
    read = set(re.findall(r'plan\.get\("(\w+)"', source))
    assert read, "cli.py no longer reads the plan by key"
    assert read <= set(plan.FIELDS), f"cli.py reads {sorted(read - set(plan.FIELDS))}, not in FIELDS"


def test_a_plan_that_is_not_an_object_is_refused():
    with pytest.raises(plan.PlanError):
        plan.check([])


# ── the ship block, where the silent dry run lived ────────────────────────────────────────────

def test_a_misspelt_ship_key_is_refused_rather_than_skipped():
    """The case six reviews pointed at."""
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"risk": "low", "ship": {**GOOD_SHIP, "tsak": "x"}})
    assert "tsak" in str(exc.value)
    assert "a misspelt key makes silent" in str(exc.value)


@pytest.mark.parametrize("missing", plan.SHIP_REQUIRED)
def test_a_ship_block_missing_a_key_it_indexes_is_refused_at_the_door(missing):
    """Those four are indexed directly — leaving one out was a `KeyError` partway through a run."""
    incomplete = {k: v for k, v in GOOD_SHIP.items() if k != missing}
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"risk": "low", "ship": incomplete})
    assert missing in str(exc.value)


def test_a_complete_ship_block_is_accepted():
    assert plan.check({"risk": "low", "ship": dict(GOOD_SHIP)})["ship"]["repo"] == "."


def test_every_ship_key_the_code_reads_is_one_the_block_may_carry():
    import inspect
    import re
    source = inspect.getsource(cli.effects_provider)
    read = set(re.findall(r'settings\[?\.?g?e?t?\(?["\'](\w+)["\']', source))
    known = set(plan.SHIP_FIELDS)
    assert read & known, "effects_provider no longer reads the ship block"
    stray = sorted(k for k in read if k not in known and k not in ("origin",))
    assert not stray, f"effects_provider reads ship keys SHIP_FIELDS does not list: {stray}"


# ── types, not only keys ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["node_specs", "operations", "decisions", "node_models",
                                 "seat_models", "ship"])
def test_a_key_of_the_right_name_holding_the_wrong_shape_is_refused(key):
    """`"node_specs": []` reads as configured and supplies nothing."""
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"risk": "low", key: []})
    assert key in str(exc.value)
    assert "reads as configured and supplies nothing" in str(exc.value)


def test_a_single_model_where_a_list_belongs_is_refused():
    """The order of a node's list is load-bearing, so a bare string is not a one-item list."""
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"risk": "low", "node_models": {"pm_plan": "opus"}})
    assert "order is load-bearing" in str(exc.value)


# ── driven through the CLI, at the door an operator walks through ─────────────────────────────

def _run(tmp_path, payload, *extra):
    written = tmp_path / "plan.json"
    written.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli", "run", "--plan", str(written),
         "--assignment-store", "none", *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env={**__import__("os").environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})


def test_the_cli_refuses_a_typo_instead_of_running(tmp_path):
    """The whole point: it must stop before it starts, not run and report success."""
    done = _run(tmp_path, {"risk": "low", "shp": dict(GOOD_SHIP)})
    assert done.returncode == 2, done.stdout
    assert "shp" in done.stdout
    # The report LINE, not the word. The refusal message itself contains "finished" — it explains
    # the defect it is preventing — and a check for the bare word matched that and called it a
    # failure. Checking vocabulary rather than the claim, in the test written for a defect that is
    # exactly that.
    assert "state:" not in done.stdout, (
        f"a plan with a typo reached a run and reported a state:{chr(10)}{done.stdout}")
    assert "visited:" not in done.stdout


def test_the_cli_refuses_a_plan_that_is_not_json(tmp_path):
    written = tmp_path / "plan.json"
    written.write_text("{not json", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli", "run", "--plan", str(written)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
        env={**__import__("os").environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})
    assert done.returncode == 2
    assert "not valid JSON" in done.stdout
