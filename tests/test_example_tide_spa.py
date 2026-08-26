"""The example is documentation, so it is tested like code.

`examples/tide-spa/README.md` states five outcomes as measurements — exit codes, asks spent, files
built, where each run stopped. A README is the one place in this project where a claim can go stale
without anything failing, which is how `docs/defect-log.md` opened. These tests drive the real CLI
through the real driver and check the numbers the README prints.

They are subprocess tests and cost real seconds. That is the price of the claim being true.
"""
import importlib.util
import json
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "tide-spa"
README = (EXAMPLE / "README.md").read_text(encoding="utf-8")


def _driver():
    spec = importlib.util.spec_from_file_location("tide_scenarios", EXAMPLE / "scenarios.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scenarios = _driver()
BY_LETTER = {label[0]: (label, fn) for label, fn in scenarios.SCENARIOS}


def _run(letter, tmp_path):
    label, mutate = BY_LETTER[letter]
    code, output, work = scenarios.run_one(label, mutate, tmp_path / letter)
    asks = len(list((work / "asks").glob("*.json"))) if (work / "asks").exists() else 0
    built = sorted(p.name for p in (work / "site").iterdir()) if (work / "site").exists() else []
    return code, output, asks, built


# ── the two that cost nothing to find out ─────────────────────────────────────────────────────

def test_a_misspelled_key_is_refused_before_a_single_ask(tmp_path):
    """The silent dry run: `operationz` accepted would run the whole flow with no declared
    operations and report success. Zero asks is the measurement that matters — a refusal after
    seven asks is a different, worse thing."""
    code, output, asks, built = _run("D", tmp_path)
    assert code == 2
    assert asks == 0, "a malformed plan must cost nothing"
    assert built == []
    assert "operationz" in output, "the refusal must name the key it rejected"
    assert "operations" in output, "and list what is actually read, so the fix is one edit"


def test_an_orphan_acceptance_is_refused_before_a_single_ask(tmp_path):
    code, output, asks, built = _run("E", tmp_path)
    assert code == 2
    assert asks == 0
    assert "acc_id" in output and "task" in output


# ── the halt no grade relaxes ─────────────────────────────────────────────────────────────────

def test_a_deploy_inside_the_build_halts_and_offers_no_way_on(tmp_path):
    """Every other halt names a way to continue. This one must not — a permanent halt that suggests
    `--confirm` is a speed bump wearing a halt's message."""
    code, output, asks, built = _run("B", tmp_path)
    assert "permanent halt" in output
    assert "engineer_build" in output
    assert built == [], "it must stop before the work, not after it"
    assert "--confirm engineer_build" not in output
    assert "--resume" not in output.split("stopped at:")[-1]


# ── the whole walk ────────────────────────────────────────────────────────────────────────────

def test_the_flow_as_written_builds_the_product_and_stops_at_merge(tmp_path):
    """The loop is the claim: four modules from four visits to one node, then a stop at a gate a
    person owns."""
    code, output, asks, built = _run("A", tmp_path)
    assert code == 0
    assert built == ["app.js", "index.html", "styles.css", "tides.js"]
    assert "--confirm merge" in output, "merge is never automated; the run must hand over"
    assert asks == 25


def test_the_run_says_when_three_seats_are_one_model(tmp_path):
    """Three seats are a cross-check only if the thing answering differs. The warning is the whole
    reason the seat count cannot be read as rigour on its own."""
    _, output, _, _ = _run("A", tmp_path)
    assert "single model" in output
    assert "--seat-model" in output


# ── the finding, recorded as it behaves ───────────────────────────────────────────────────────

def test_a_blank_spec_is_refused_before_a_single_ask(tmp_path):
    """`objective: ""` used to render a valid work order, because the check tested key presence and
    not content: 25 asks, four files, exit 0. CHG-20260823-34 closed it at both ends.

    The previous version of this test asserted the **broken** behaviour on purpose, so that the fix
    could not land without the README moving with it. It worked — this test, the README's scenario C
    and the results table all changed in one commit.
    """
    code, output, asks, built = _run("C", tmp_path)
    assert code == 2
    assert asks == 0, "a blank spec must cost nothing to find out"
    assert built == []
    assert "engineer_build" in output, "the refusal must name the node"


def test_the_refusal_names_the_blank_fields_and_not_the_ones_allowed_to_be_blank(tmp_path):
    """The whole ruling in one assertion.

    Scenario C blanks three fields; only two of them are defects. `expected_outputs` is `[]` on 14
    of the 15 nodes in `examples/plan.json` — a review node produces nothing — so a rule refusing
    every blank would refuse this repository's own example. That is the same coarse check inverted,
    and it is the failure mode a rule like this actually has.
    """
    _, output, _, _ = _run("C", tmp_path)
    assert "'scope'" in output and "'objective'" in output
    assert "leaves ['scope', 'objective']" in output, (
        "expected_outputs was blanked too and must not be in the refusal")
    assert "may be empty" in output, "the refusal must name the boundary, or callers pad to be safe"


def test_the_example_plan_survives_the_rule_it_documents():
    """The adversarial half: the rule must not refuse the plan the example ships with."""
    from ai_sdlc_runner import plan as plan_mod

    for name in ("examples/tide-spa/plan.json", "examples/plan.json"):
        path = EXAMPLE.parent.parent / name
        plan_mod.check(json.loads(path.read_text(encoding="utf-8")), name)


# ── the page and the plan the README describes ────────────────────────────────────────────────

def test_the_readme_table_matches_the_scenarios_the_driver_defines():
    letters = [label[0] for label, _ in scenarios.SCENARIOS]
    assert letters == ["A", "B", "C", "D", "E"]
    for letter in letters:
        assert f"| **{letter}** |" in README, f"scenario {letter} is missing from the results table"


def test_the_example_plan_is_one_this_runner_accepts():
    from ai_sdlc_runner import plan as plan_mod
    plan_mod.check(json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8")))


def test_the_driver_does_not_depend_on_the_callers_locale():
    """`text=True` alone decodes subprocess output with the caller's codec, and the runner's
    messages are full of em-dashes: on a cp950 console the driver died with UnicodeDecodeError
    while the run underneath it had succeeded.

    Read out of the syntax tree rather than grepped for. The first version of this test searched the
    file for `text=True` and failed on the *comment* that explains why it is not used — a check
    reading vocabulary instead of the thing it claims, which is the defect this suite exists to
    catch.
    """
    import ast

    tree = ast.parse((EXAMPLE / "scenarios.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run"]
    assert calls, "the driver must actually invoke the CLI"
    for call in calls:
        keywords = {k.arg: k.value for k in call.keywords}
        assert "text" not in keywords, "text=True decodes with the caller's locale codec"
        assert ast.literal_eval(keywords["encoding"]) == "utf-8"


@pytest.mark.parametrize("name", ["agent.py", "plan.json", "runner.yaml", "scenarios.py"])
def test_the_files_the_readme_lists_are_there(name):
    assert (EXAMPLE / name).exists()
    assert f"`{name}`" in README
