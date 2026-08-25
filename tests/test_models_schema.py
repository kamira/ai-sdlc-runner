"""Pin `docs/MODELS.md` to `models.py` (CHG-20260823-23).

The `Model` shape was in three documents; the rules that govern it were in none. These tests hold
the page to the rules, and they hold the rules to themselves — every refusal `validate()` makes is
**driven**, not read out of the source, so a refusal that stops firing fails here rather than
quietly widening what the registry accepts.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_sdlc_runner import models  # noqa: E402

PAGE = (ROOT / "docs" / "MODELS.md").read_text(encoding="utf-8")
FLAT = " ".join(PAGE.split())


def _cli(**over):
    base = dict(id="opus", vendor="anthropic", name="claude-opus-5", transport="cli",
                command=("claude", "-p"))
    return models.Model(**{**base, **over})


def _api(**over):
    base = dict(id="gpt", vendor="openai", name="gpt-5", transport="api",
                endpoint="https://api.example.com/v1", key_env="OPENAI_API_KEY")
    return models.Model(**{**base, **over})


# ── the shape ─────────────────────────────────────────────────────────────────────────────────

def test_the_page_lists_exactly_the_fields_that_persist():
    persisted = set(_cli().as_dict()) - {"reach", "leaves_this_machine"}
    for field in persisted:
        assert f'"{field}"' in PAGE, f"the page omits the persisted field {field!r}"
    assert len(persisted) == 8, f"the registry now persists {len(persisted)} fields, not eight"
    assert "Eight fields persist" in FLAT


def test_the_page_says_reach_is_computed_and_never_stored():
    assert "reach" in _cli().as_dict()
    saved = models.save.__doc__ or ""
    del saved
    import inspect
    assert 'k not in ("reach", "leaves_this_machine")' in inspect.getsource(models.save)
    assert "computed on every read and never stored" in FLAT


# ── every refusal, driven ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model, fragment", [
    (_cli(id=""),                       "not a plain name"),
    (_cli(id="two words"),              "not a plain name"),
    (_cli(vendor=""),                   "names no vendor"),
    (_cli(name=""),                     "names no model at the vendor"),
    (_cli(transport="carrier-pigeon"),  "unknown transport"),
    (_cli(command=()),                  "no command to run"),
    (_cli(endpoint="https://x.example"), "cannot use"),
    (_cli(key_env="SOME_KEY"),          "cannot use"),
    (_api(endpoint=""),                 "no endpoint"),
    (_api(endpoint="ftp://x.example"),  "endpoint scheme"),
    (_api(endpoint="https://x.example/v1?api_key=sk-live-abc"), "query string"),
    (_api(command=("x",)),              "carries a command"),
    (_api(key_env="sk-ant-not-a-name"), "not the name of an"),
    (_api(endpoint="https://public.example.com/v1", key_env=""), "no key named"),
])
def test_every_refusal_the_page_documents_actually_fires(model, fragment):
    with pytest.raises(models.ModelError) as exc:
        models.validate(model)
    assert fragment in str(exc.value)


def test_two_models_with_one_id_are_refused():
    with pytest.raises(models.ModelError, match="two models are called"):
        models.Registry(models=(_cli(), _cli()))


def test_a_valid_model_of_each_transport_is_accepted():
    assert models.validate(_cli()).reach == models.LOCAL
    assert models.validate(_api()).reach == models.EXTERNAL


def test_the_page_documents_a_refusal_for_every_raise_in_validate():
    """A refusal that exists and is undocumented is one an operator meets with no explanation."""
    import inspect
    raises = len(re.findall(r"raise ModelError", inspect.getsource(models.validate)))
    documented = len(re.findall(r"^\| [a-z*`]", PAGE, re.M))
    assert documented >= raises - 1, (          # `reach not in REACHES` is a bug-only branch
        f"validate() makes {raises} refusals; the page's tables list {documented} rows")


# ── reach ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("endpoint, expected", [
    ("",                              models.LOCAL),      # cli, endpoint unused
    ("http://localhost:8080/v1",      models.LOCAL),
    ("http://localhost.localdomain/", models.LOCAL),
    ("http://127.0.0.1/v1",           models.LOCAL),
    ("http://[::1]/v1",               models.LOCAL),
    ("http://10.0.0.5/v1",            models.INTERNAL),
    ("http://192.168.1.9/v1",         models.INTERNAL),
    ("http://169.254.1.1/v1",         models.INTERNAL),   # link-local
    ("http://gpu-box/v1",             models.INTERNAL),   # single label
    ("http://box.local/v1",           models.INTERNAL),
    ("http://box.internal/v1",        models.INTERNAL),
    ("http://box.lan/v1",             models.INTERNAL),
    ("http://box.home.arpa/v1",       models.INTERNAL),
    ("https://api.openai.com/v1",     models.EXTERNAL),
    ("https://api.anthropic.com/v1",  models.EXTERNAL),
])
def test_reach_is_computed_the_way_the_page_says(endpoint, expected):
    transport = models.CLI if not endpoint else models.API
    assert models.reach_of(transport, endpoint) == expected


def test_an_unresolvable_name_is_external_because_guessing_generously_is_the_wrong_error():
    assert models.reach_of(models.API, "https://nothing.invalid/v1") == models.EXTERNAL
    assert "guessing the generous answer" in FLAT


def test_an_api_model_with_no_host_cannot_have_a_reach():
    with pytest.raises(models.ModelError, match="before its reach can be known"):
        models.reach_of(models.API, "https:///v1")


def test_the_page_lists_every_reach_the_code_defines():
    for reach in models.REACHES:
        assert f"`{reach}`" in PAGE or f'"{reach}"' in PAGE, reach
    assert len(models.REACHES) == 3


def test_leaves_this_machine_is_reach_that_is_not_local():
    assert _cli().leaves_this_machine is False
    assert _api().leaves_this_machine is True
    registry = models.Registry(models=(_cli(), _api()))
    assert [m.id for m in registry.leaving()] == ["gpt"]


# ── the secret check ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", models._SECRET_KEYS)
def test_every_secret_key_the_code_knows_is_refused_in_a_query_string(key):
    with pytest.raises(models.ModelError, match="query string"):
        models.validate(_api(endpoint=f"https://x.example/v1?{key}=abc"))


def test_the_page_is_honest_that_the_secret_list_is_not_exhaustive():
    """A check that refuses what it recognises, and does not claim to recognise everything."""
    assert models._secret_in_query("https://x.example/v1?auth=abc") is None
    assert "Not exhaustive" in FLAT and "does not claim to recognise everything" in FLAT


# ── assignment ────────────────────────────────────────────────────────────────────────────────

def test_the_page_says_what_each_mode_does_with_a_model_list():
    from ai_sdlc_runner import graph
    section = PAGE.split("### `node_models`")[1].split("### `seat_models`")[0]
    for mode in graph.MODES:
        assert f"`{mode}`" in section, f"the page does not say what {mode!r} does with the list"


def test_a_pool_dispatch_is_reproducible_and_depends_on_all_three_seeds():
    from ai_sdlc_runner import engine, graph

    node = graph.BY_ID["engineer_build"]
    pool = ["a", "b", "c", "d", "e"]
    cfg = engine.RunConfig(node_specs={}, decisions={})
    first = [engine._dispatch_from(pool, cfg, node, n) for n in range(6)]
    again = [engine._dispatch_from(pool, cfg, node, n) for n in range(6)]
    assert first == again, "the same run must dispatch the same way twice"
    assert len(set(first)) > 1, "the ordinal must move the choice, or the pool is one model"

    other = graph.BY_ID["pm_plan"]
    assert [engine._dispatch_from(pool, cfg, other, n) for n in range(6)] != first, (
        "two nodes must not march in lockstep through the pool")

    seeded = engine.RunConfig(node_specs={}, decisions={}, dispatch_seed=7)
    assert [engine._dispatch_from(pool, seeded, node, n) for n in range(6)] != first


def test_the_page_states_the_resolution_order_the_factory_uses():
    """The order INSIDE `factory`, not where `default` happens to be bound.

    The first version of this test asserted against the line that *assigns* `default`, which sits
    near the top of the enclosing function and is used last — so it compared a binding to a branch
    and failed for a reason that had nothing to do with resolution order.
    """
    import inspect
    from ai_sdlc_runner import cli
    body = inspect.getsource(cli.session_factory).split("def factory(")[1]
    seat_named = body.index("model is None and seat is not None")
    by_model = body.index("if model and registry is not None")
    raw_seat = body.index("argv = seat_models.get(seat) or default")
    assert seat_named < by_model < raw_seat, "the factory's resolution order moved"
    assert "most specific first" in FLAT.lower()


def test_an_api_model_registers_and_cannot_be_dispatched_to():
    """It validates, it lists, and the first ask routed to it raises.

    The refusal is right — the alternative its own message names is sending the work to the
    default and reporting it as the named model, which is a lie in the dispatch record. But it
    means `transport: "api"` is a declaration this runner cannot yet honour, and the page has to
    say so rather than leave it to be found at the first ask.
    """
    from ai_sdlc_runner import cli
    registry = models.Registry(models=(_api(),))
    assert models.validate(_api())                        # registration is fine
    factory = cli.session_factory({}, registry=registry)
    with pytest.raises(cli.CliError, match="dispatches by running"):
        factory(model="gpt")
    assert "cannot be dispatched to" in FLAT


def test_the_page_admits_the_assignment_side_is_not_closed():
    """The plan file ignores unknown keys, so a misspelt `node_models` assigns nothing."""
    section = FLAT.split("What model management does **not** have")[1]
    assert "not closed" in section and "node_models" in section
