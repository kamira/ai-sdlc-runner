"""The console example, tested by driving a live server.

`test_example_tide_spa.py` covers the CLI path. This covers the one that has an operator on it —
where an instruction is typed, a gate is clicked, and a token is checked. Those refusals cannot be
reached from `runner run` at all.

Subprocess tests with real sockets. They cost real seconds; that is the price of the README's
numbers being measurements rather than claims.
"""
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "weather-spa"
README = (EXAMPLE / "README.md").read_text(encoding="utf-8")


def _driver():
    spec = importlib.util.spec_from_file_location("weather_scenarios", EXAMPLE / "scenarios.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scenarios = _driver()
BY_LETTER = {label[0]: fn for label, fn in scenarios.SCENARIOS}


@pytest.fixture
def work(tmp_path):
    return tmp_path / "run"


# ── the cheap refusals, which need no walk at all ─────────────────────────────────────────────

def test_the_shell_loads_without_a_token_and_nothing_behind_it_does(work):
    """The exemption is deliberate and narrow: nothing can present a token before it has loaded the
    page that stores one. Both halves are asserted, because the exemption is only safe if the
    second half holds."""
    result = BY_LETTER["D"](work)
    assert result["shell_status"] == 200
    assert result["run_status"] == 401
    assert "operator token" in result["error"]


def test_a_non_loopback_host_and_a_cross_origin_request_are_both_refused(work):
    """A name that resolves to 127.0.0.1 reaches a loopback socket, so binding is not the check —
    the `Host` header is, and it is read before the request is parsed."""
    result = BY_LETTER["E"](work)
    assert result["bad_host_status"] == 403
    assert "loopback" in result["host_error"]
    assert result["cross_origin_status"] == 403
    assert "evil.example" in result["origin_error"], "the refusal must name what it refused"


# ── the walk ──────────────────────────────────────────────────────────────────────────────────

def test_a_brief_typed_into_the_console_builds_the_page_and_stops_at_merge(work):
    result = BY_LETTER["A"](work)
    assert result["built"] == ["app.js", "index.html", "styles.css", "weather.js"]
    assert any("approve merge" in note for note in result["notes"]), (
        "merge is never automated; the console must offer the button rather than proceed")
    assert any("finished" in note for note in result["notes"])
    assert result["instructions"] == 1, "what the operator typed must be in the run's state"


def test_start_the_run_replaces_the_brief_and_add_to_the_brief_appends(work):
    """Two verbs on two routes. Using the first for a follow-up silently drops the original — which
    is how this project lost an instruction the first time it was driven, with nothing failing and
    nothing warning."""
    result = BY_LETTER["B"](work)
    assert result["after_first"] == 1
    assert result["after_start_again"] == 1, "`start the run` appended instead of replacing"
    assert result["after_add_to_brief"] == 2, "`add to the brief` replaced instead of appending"


def test_an_agent_that_cycles_is_stopped_by_the_step_cap(work):
    """The runner catching a bug in the thing it drives, rather than in itself.

    A timeout would have reported a slow run. The cap reports the shape of the failure.
    """
    result = BY_LETTER["C"](work)
    assert result["state"] == "stopped"
    assert "200 steps" in result["error"], "the refusal must say what limit it hit"
    # CHG-20260823-50: this used to assert the phrase "cycling without progress", which is a
    # sentence rather than a claim. What an operator needs from this refusal is which node spun and
    # what it kept answering -- the message said neither, and the real cycle it was written for
    # (`engineer_build` answering the same thing 200 times) was diagnosed by reading the engine.
    assert "Most-visited" in result["error"], (
        f"the refusal does not say what cycled: {result['error']}")
    assert any(node in result["error"] for node in ("engineer_build", "next_module")), (
        f"the refusal names no node from the loop that spun: {result['error']}")
    assert "last answered" in result["error"], (
        f"the refusal does not say what the repeating node kept answering: {result['error']}")


# ── the crash that made all of this unreachable ───────────────────────────────────────────────

def test_serve_does_not_need_settings_passed_to_it():
    """`runner serve` died on startup with a bare `TypeError` from `Path(None)`.

    The `serve` subparser declared `--settings` with `default=None`, shadowing the global flag whose
    default exists precisely so nobody has to pass it. The dashboard in its plainest form did not
    start, and the traceback named `pathlib`, not the flag.

    Asserted against the parser rather than by reading the source, so a re-shadowing under any other
    spelling still fails this.
    """
    from ai_sdlc_runner import cli, settings as settings_mod

    parsed = cli.build_parser().parse_args(["serve", "--plan", "p.json"])
    assert parsed.settings == settings_mod.DEFAULT_PATH
    settings_mod.load(parsed.settings)          # the call that raised


def test_every_subcommand_that_takes_settings_gets_a_usable_default():
    """The general form of the same defect. A subparser flag that shadows a global one and forgets
    its default is a hole any command could acquire."""
    from ai_sdlc_runner import cli, settings as settings_mod

    parser = cli.build_parser()
    subs = [a for a in parser._actions if getattr(a, "choices", None)
            and all(hasattr(c, "_actions") for c in a.choices.values())]
    checked = 0
    for action in subs:
        for name, sub in action.choices.items():
            dests = {x.dest: x for x in sub._actions}
            if "settings" in dests:
                checked += 1
                assert dests["settings"].default is not None, (
                    f"`{name} --settings` defaults to None and will reach Path(None)")
                settings_mod.load(dests["settings"].default)
    assert checked, "no subcommand declares --settings; this test has stopped testing anything"


# ── the example's own claims ──────────────────────────────────────────────────────────────────

def test_the_readme_table_matches_the_scenarios_the_driver_defines():
    letters = [label[0] for label, _ in scenarios.SCENARIOS]
    assert letters == ["A", "B", "C", "D", "E"]
    for letter in letters:
        assert f"| **{letter}** |" in README, f"scenario {letter} is missing from the results table"


def test_the_example_plan_is_one_this_runner_accepts():
    from ai_sdlc_runner import plan as plan_mod
    plan_mod.check(json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8")))


def test_the_page_this_example_builds_asks_the_network_for_nothing():
    """The brief said 不要連外網. A page that quietly fetched a forecast would satisfy every other
    check in this file."""
    agent = (EXAMPLE / "agent.py").read_text(encoding="utf-8")
    for reaching in ("fetch(", "XMLHttpRequest", "EventSource", "navigator.sendBeacon",
                     "https://", "http://"):
        assert reaching not in agent, f"the built page reaches for {reaching}"


def test_the_shipped_agent_rebuilds_by_content_not_by_counting_files(tmp_path):
    """Scenario C's agent is the broken one, on purpose. The one this example ships must not share
    its bug — so it is driven twice and asked what it did the second time."""
    import subprocess
    import sys

    site = tmp_path / "site"
    order = {"node_id": "engineer_build", "seat": None}
    seen = []
    for _ in range(6):
        out = subprocess.run([sys.executable, str(tmp_path / "agent.py")],
                             input=json.dumps(order), capture_output=True, text=True,
                             encoding="utf-8", cwd=str(tmp_path)) if (tmp_path / "agent.py").exists() \
            else None
        if out is None:
            (tmp_path / "agent.py").write_text(
                (EXAMPLE / "agent.py").read_text(encoding="utf-8"), encoding="utf-8")
            continue
        seen.append(json.loads(out.stdout)["module"])

    assert seen[:4] == ["markup", "styles", "weather", "app"]
    assert seen[4] == "", "a fifth build must report nothing to do, not the last module again"
    assert sorted(p.name for p in site.iterdir()) == [
        "app.js", "index.html", "styles.css", "weather.js"]


@pytest.mark.parametrize("name", ["agent.py", "plan.json", "runner.yaml", "scenarios.py"])
def test_the_files_the_readme_lists_are_there(name):
    assert (EXAMPLE / name).exists()
    assert f"`{name}`" in README
