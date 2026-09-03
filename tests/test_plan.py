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
    loaded = plan.load(ROOT / "examples" / "minimal" / "plan.json")
    assert set(loaded) <= set(plan.FIELDS)
    assert loaded["risk"] == "low"


@pytest.mark.parametrize("typo", ["operationz", "node_spec", "seatmodels", "Ship", "notes"])
def test_an_unknown_top_level_key_is_refused(typo):
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"risk": "low", typo: {}})
    assert typo in str(exc.value)
    assert "look configured and do nothing" in str(exc.value)


def test_every_key_the_code_reads_is_one_the_plan_may_carry():
    """The two lists must not drift, **in either direction**.

    A key `cli.py` reads and `FIELDS` lacks would be refused on a plan that is correct — the failure
    mode of a closed schema built from memory. A key in `FIELDS` that `cli.py` never reads is the
    mirror image and the one `plan.check`'s own refusal is about: *"Ignoring them would let a
    setting look configured and do nothing."* A plan could carry it, the door would accept it, and
    nobody would read it.

    This checked one direction until CHG-20260902-20. `FIELDS`' own comment claims both — *"each of
    these appears as a `plan.get(...)` in `cli.py`, and a test walks the source to prove the two
    lists have not drifted apart"* — and the unchecked half is exactly what CHG-20260901-17 M-3
    found in a different file: a guard reporting "no drift" for the half it never looked at.
    """
    import re
    source = (ROOT / "src" / "ai_sdlc_runner" / "cli.py").read_text(encoding="utf-8")
    read = set(re.findall(r'plan\.get\("(\w+)"', source))
    assert read, "cli.py no longer reads the plan by key"
    assert read <= set(plan.FIELDS), f"cli.py reads {sorted(read - set(plan.FIELDS))}, not in FIELDS"
    assert set(plan.FIELDS) <= read, (
        f"FIELDS carries {sorted(set(plan.FIELDS) - read)}, which `cli.py` never reads. A plan may "
        f"set it, the door accepts it, and nothing acts on it — a setting that looks configured and "
        f"does nothing, which is what this schema was closed to prevent.")


def test_the_ship_block_does_not_drift_in_either_direction_either():
    """`SHIP_FIELDS` carries the same claim and had the same one-way guard.

    `effects_provider` reads the ship block by key; a name in `SHIP_FIELDS` it never reads is a key
    a plan may set that changes nothing, which is the exact case `plan.py`'s module docstring calls
    the repository's doctrine failing at its front door.
    """
    import re
    source = (ROOT / "src" / "ai_sdlc_runner" / "cli.py").read_text(encoding="utf-8")
    block = source.split("def effects_provider")[1].split("\ndef ")[0]
    read = set(re.findall(r'settings\.get\("(\w+)"', block)) | set(
        re.findall(r'settings\["(\w+)"\]', block))
    assert read, "effects_provider no longer reads the ship block by key"
    assert read <= set(plan.SHIP_FIELDS), (
        f"effects_provider reads {sorted(read - set(plan.SHIP_FIELDS))}, not in SHIP_FIELDS")
    assert set(plan.SHIP_FIELDS) <= read, (
        f"SHIP_FIELDS carries {sorted(set(plan.SHIP_FIELDS) - read)}, which `effects_provider` "
        f"never reads.")


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


# ── round 2: what the first closing accepted ──────────────────────────────────────────────────

def test_acc_id_without_a_task_is_refused():
    """The headline of round 2, and the same silent dry run one conditional deeper.

    `record_effects` is called only `if task`, so `acc_id` and `acc_body` without one are read by
    nothing: the acceptance record is never written and the run reports `finished`. Every key was in
    `SHIP_FIELDS` and all four required ones were present, so the first closing accepted it —
    answering the complaint (a misspelt key) and not the finding (ship configuration that silently
    does nothing).
    """
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"risk": "low", "ship": {**GOOD_SHIP, "acc_id": "ACC-9", "acc_body": "y"}})
    assert "read by nothing" in str(exc.value)
    assert "acc_id" in str(exc.value)


def test_a_task_with_no_acceptance_id_is_refused():
    with pytest.raises(plan.PlanError, match="no identity"):
        plan.check({"risk": "low", "ship": {**GOOD_SHIP, "task": "T"}})


def test_the_acceptance_effect_is_reachable_when_the_plan_passes():
    """The other direction, and the one that matters: a plan this accepts must actually ship."""
    from ai_sdlc_runner import cli
    complete = {"risk": "low",
                "ship": {**GOOD_SHIP, "chg_body": "x", "task": "1", "acc_id": "ACC-9",
                         "acc_body": "evidence"}}
    plan.check(complete)
    effects = cli.effects_provider(complete)("record_module")
    assert effects, "a plan that passes must produce the effects it configured"


@pytest.mark.parametrize("payload, fragment", [
    ({"risk": "banana"}, "the grades are"),
    ({"risk": 7}, "the grades are"),
    ({"autonomy": 42}, "verdict name"),
    ({"decisions": {"next_module": 7}}, "consumed one per visit"),
    ({"decisions": {"next_module": [1, 2]}}, "consumed one per visit"),
    ({"operations": {"x": "write stuff"}}, "character by character"),
    ({"operations": {"x": ["not an object"]}}, "each one is an object"),
])
def test_a_value_the_runner_cannot_use_is_refused_at_the_door(payload, fragment):
    """Each of these was accepted and became a traceback or a halt somewhere else."""
    with pytest.raises(plan.PlanError) as exc:
        plan.check(payload)
    assert fragment in str(exc.value)


@pytest.mark.parametrize("key", ["repo", "chg_id", "branch", "message", "task"])
def test_a_ship_value_that_is_not_a_string_is_refused(key):
    """Every one is written into a file or a commit; a number reached `ship.py` as an
    AttributeError about `splitlines` before the run had started."""
    with pytest.raises(plan.PlanError, match="non-string"):
        plan.check({"risk": "low", "ship": {**GOOD_SHIP, key: 123}})


def test_the_module_no_longer_claims_to_refuse_what_it_cannot():
    """`check`'s docstring said "a plan this runner would fully honour" — a name standing in for a
    constraint, in the module written against exactly that."""
    # The SUMMARY LINE, not the whole docstring. The corrected docstring quotes the false claim in
    # order to mark it false, so a search of the whole thing matches the correction and calls it the
    # defect. Third time this session a check has matched prose explaining a defect rather than the
    # defect -- the pattern is the finding, not this instance.
    summary = (plan.check.__doc__ or "").strip().splitlines()[0]
    assert "would fully honour" not in summary, summary
    assert 'Not "a plan this runner would fully honour"' in (plan.check.__doc__ or ""), (
        "the docstring must still say which claim it retracted")
    assert "Nothing closes an operation's interior" in (plan.__doc__ or ""), (
        "the module must name what it leaves to nobody, not only what it leaves to another check")


def test_no_public_docstring_in_the_module_still_makes_the_retracted_claim():
    """The retraction reached `check` and stopped there.

    `load`'s summary line said "refuse it if this runner would not fully honour it" — the same claim,
    one function along, where the test above does not look. It survived four days and an acceptance
    round found it (CHG-20260827-10).

    So the check widens from one docstring to every public one in the module. A retraction that only
    covers the line somebody happened to test is a retraction with a gap the same shape as the claim.
    """
    import inspect

    offenders = []
    for name, value in vars(plan).items():
        if name.startswith("_") or not inspect.isfunction(value):
            continue
        if getattr(value, "__module__", None) != plan.__name__:
            continue
        doc = value.__doc__ or ""
        summary = doc.strip().splitlines()[0] if doc.strip() else ""
        if "fully honour" in summary:
            offenders.append(f"{name}: {summary}")

    assert not offenders, (
        "these docstrings still promise what this module cannot deliver, which is the exact claim "
        f"CHG-20260823-30 retracted: {offenders}")


def test_all_three_decision_forms_are_accepted():
    """ names three: a label, a sequence consumed one per visit, and "frontier".

    The first version of the check took only the first, and twenty-five existing tests caught it.
    That is the other failure mode of a closed schema — refusing what it should accept, which is
    worse than the reverse: a plan that was correct stops working, and the message calls it
    malformed.
    """
    for form in ("module", ["module", "none"], "frontier"):
        assert plan.check({"risk": "low", "decisions": {"next_module": form}})


# ── blank required fields (CHG-20260823-34) ───────────────────────────────────────────────────

def _spec(**over):
    from ai_sdlc_runner import workorder
    spec = {f: f"the {f}" for f in workorder.NODE_SPEC_FIELDS}
    spec.update({"input_artifacts": [], "expected_outputs": [], "idempotence_probes": [],
                 "workdir": "."})
    spec.update(over)
    return spec


def test_a_blank_required_field_is_refused_at_the_door():
    """Refused at load so it costs no asks: a blank `engineer_build` caught only at dispatch
    surfaces after seven asks have already been spent reaching it."""
    with pytest.raises(plan.PlanError) as caught:
        plan.check({"node_specs": {"engineer_build": _spec(objective="")}})
    assert "objective" in str(caught.value)
    assert "engineer_build" in str(caught.value)


def test_whitespace_is_blank():
    """`" "` is the same defect one character deeper."""
    with pytest.raises(plan.PlanError):
        plan.check({"node_specs": {"n": _spec(scope="   ")}})


def test_a_list_of_blanks_is_blank():
    """`done_criteria` is a string in some plans and a list in others. Both forms have an empty
    case, and a list holding only empty strings supplies no criterion either."""
    with pytest.raises(plan.PlanError):
        plan.check({"node_specs": {"n": _spec(done_criteria=[])}})
    with pytest.raises(plan.PlanError):
        plan.check({"node_specs": {"n": _spec(done_criteria=["", "  "])}})


@pytest.mark.parametrize("field", ["input_artifacts", "expected_outputs", "idempotence_probes"])
def test_the_three_that_may_be_empty_still_may(field):
    """The inverted defect this rule could easily have been. `expected_outputs` is `[]` on 14 of the
    15 nodes in `examples/minimal/plan.json`; refusing it would refuse the repository's own example."""
    plan.check({"node_specs": {"n": _spec(**{field: []})}})


def test_instructions_may_be_blank_at_load_because_the_engine_may_supply_them():
    """The one field the two boundaries disagree about, and the disagreement is deliberate.

    `engine.py` joins `--instruction` text onto the node spec's own, and reads
    `own = spec.get("instructions") or ()` — explicitly tolerating a blank. A plan that leaves every
    node's `instructions` empty and supplies the text on the command line is coherent and works, so
    refusing it here would be this same defect inverted.
    """
    plan.check({"node_specs": {"n": _spec(instructions="")}})


def test_render_does_refuse_a_blank_instructions_because_by_then_nothing_can_fill_it():
    """The other half: by render time the engine has already appended whatever it had. Still blank
    means there is genuinely nothing to say."""
    from ai_sdlc_runner import graph, workorder

    verdict = {"gate": "g", "risk": "low", "verdict": "allow", "source": "grade",
               "tightened": False}
    with pytest.raises(workorder.WorkOrderError) as caught:
        workorder.render(graph.NODES[0], _spec(instructions=""), verdict)
    assert "instructions" in str(caught.value)


def test_a_missing_key_is_not_reported_twice_in_different_words():
    """Absence is `_check`'s complaint. Reporting it again as 'blank' helps nobody."""
    from ai_sdlc_runner import workorder

    assert workorder.content_problem("n", {"scope": "x"}, "w") is None


def test_one_definition_of_blank_serves_both_boundaries():
    """Two copies of this rule drifting apart give a plan that loads and will not dispatch."""
    from ai_sdlc_runner import workorder

    assert set(workorder.CONTENTFUL_FIELDS) | set(workorder.MAY_BE_EMPTY) == \
        set(workorder.NODE_SPEC_FIELDS), "every field must be on exactly one of the two lists"
    assert not set(workorder.CONTENTFUL_FIELDS) & set(workorder.MAY_BE_EMPTY)


# ── an empty seat assignment reads as configured and dispatches the default (CHG-20260903-35) ───


@pytest.mark.parametrize("value", ["", None, [], {}, 0])
def test_an_empty_seat_assignment_is_refused_the_way_a_node_one_is(tmp_path, value):
    """`seat_models` got **no shape check at all** where `node_models` gets one.

    The validation loop iterated `("node_models", "seat_models")` with a body wholly guarded by
    `if key == "node_models"`, so walking `seat_models` checked nothing. The guard is right —
    `store.seat_models(db)` is `Dict[str, str]` — but the omission is not merely unchecked, it is
    silent: `cli.py` does `argv = seat_argv or default`, so an operator who configured the defect
    seat and mistyped the value gets the **default backend** with nothing said (defect seat L-55).
    """
    payload = json.loads((Path(__file__).resolve().parents[1] /
                          "examples" / "minimal" / "plan.json").read_text(encoding="utf-8"))
    payload["seat_models"] = {"defect": value}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(plan.PlanError, match="one model id per seat"):
        plan.load(path)


def test_a_real_seat_assignment_still_loads(tmp_path):
    """The false-stop guard: the shape an operator actually writes must survive."""
    payload = json.loads((Path(__file__).resolve().parents[1] /
                          "examples" / "minimal" / "plan.json").read_text(encoding="utf-8"))
    payload["seat_models"] = {"defect": "opus", "risk": "codex"}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert plan.load(path)
