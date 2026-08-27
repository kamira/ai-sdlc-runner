"""Task 8 — the model registry, and the one fact it exists to make impossible to miss.

The console is local only; the models are not, and that is deliberate. A run is useful because it can
call out — to a vendor's API, or to something on this network. Inbound closed, outbound open.

What this registry refuses is not an external model. It refuses an operator having to **infer** that
they configured one. `reach` is computed from what the endpoint actually is, never declared, because
a model *labelled* `internal` while pointing at a public host is a configuration that reads as safe
and is not — and this repository has already had to stop itself treating a name as evidence once.
"""
import json

import pytest

from ai_sdlc_runner import models


def _cli(**over):
    base = dict(id="local-opus", vendor="anthropic", name="claude-opus-5",
                transport=models.CLI, command=("claude", "-p"))
    base.update(over)
    return models.Model(**base)


def _api(**over):
    base = dict(id="opus", vendor="anthropic", name="claude-opus-5", transport=models.API,
                endpoint="https://api.anthropic.com/v1/messages", key_env="ANTHROPIC_API_KEY")
    base.update(over)
    return models.Model(**base)


# --- reach is computed, never taken on trust -----------------------------------------------

def test_a_cli_model_is_local():
    assert _cli().reach == models.LOCAL
    assert _cli().leaves_this_machine is False


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:8080/v1/chat",
    "http://localhost:11434/api/generate",
    "http://[::1]:8080/v1",
])
def test_a_loopback_endpoint_is_local(endpoint):
    model = _api(endpoint=endpoint, key_env="")
    assert model.reach == models.LOCAL
    assert model.leaves_this_machine is False


@pytest.mark.parametrize("endpoint", [
    "http://10.0.0.7:8000/v1",
    "http://192.168.1.40:8000/v1",
    "http://172.16.3.9:8000/v1",
    "http://gpu-box:8000/v1",
    "http://models.internal/v1",
    "http://inference.local/v1",
])
def test_a_private_endpoint_is_internal(endpoint):
    """Self-hosted on this network. Allowed, and named as what it is."""
    model = _api(endpoint=endpoint, key_env="")
    assert model.reach == models.INTERNAL
    assert model.leaves_this_machine is True, "it leaves the machine even if not the network"


@pytest.mark.parametrize("endpoint", [
    "https://api.anthropic.com/v1/messages",
    "https://api.openai.com/v1/responses",
    "https://8.8.8.8/v1",
])
def test_a_public_endpoint_is_external(endpoint):
    assert _api(endpoint=endpoint).reach == models.EXTERNAL


def test_an_unresolvable_name_is_treated_as_external():
    """Guessing the generous answer about where data goes is the wrong way to be wrong."""
    assert _api(endpoint="https://who-knows.example.com/v1").reach == models.EXTERNAL


def test_reach_cannot_be_declared():
    """The field does not exist, so a stale or wishful label cannot outlive the truth."""
    assert "reach" not in models.Model.__dataclass_fields__
    with pytest.raises(models.ModelError, match="does not know"):
        models._model_from({"id": "x", "vendor": "v", "name": "n", "transport": "cli",
                            "command": ["x"], "reach": "local"})


def test_the_computed_reach_is_not_written_to_disk(tmp_path):
    """Storing it would let a file say `local` about an endpoint that has since been edited."""
    path = tmp_path / "models.json"
    models.save(models.Registry(models=(_api(),)), path)
    stored = json.loads(path.read_text(encoding="utf-8"))["models"][0]
    assert "reach" not in stored
    assert "leaves_this_machine" not in stored
    assert models.load(path).get("opus").reach == models.EXTERNAL


# --- keys are named, never held -----------------------------------------------------------

def test_a_key_env_is_a_variable_name():
    assert _api(key_env="ANTHROPIC_API_KEY").key_env == "ANTHROPIC_API_KEY"


def test_pasting_the_key_itself_is_refused():
    """The shape refuses it before a human has to notice."""
    with pytest.raises(models.ModelError, match="name of an\nenvironment|name of an environment"):
        models.validate(_api(key_env="sk-ant-api03-not-a-real-key"))


def test_a_secret_in_the_query_string_is_refused():
    """Query strings land in access logs and proxy logs — the two nobody thinks to inspect."""
    with pytest.raises(models.ModelError, match="query string"):
        models.validate(_api(endpoint="https://api.example.com/v1?api_key=abc123"))


@pytest.mark.parametrize("key", ["key", "token", "secret", "password", "access_token", "sig"])
def test_every_known_secret_query_key_is_refused(key):
    with pytest.raises(models.ModelError, match="query string"):
        models.validate(_api(endpoint=f"https://api.example.com/v1?{key}=abc"))


def test_an_ordinary_query_parameter_is_fine():
    models.validate(_api(endpoint="https://api.example.com/v1?version=2024-01-01"))


def test_a_public_endpoint_with_no_key_named_is_refused():
    with pytest.raises(models.ModelError, match="no key named"):
        models.validate(_api(key_env=""))


# --- fields that would silently do nothing ------------------------------------------------

def test_a_cli_model_carrying_an_endpoint_is_refused():
    """A field nothing reads is one somebody will later assume was honoured."""
    with pytest.raises(models.ModelError, match="cannot use"):
        models.validate(_cli(endpoint="https://api.example.com/v1"))


def test_an_api_model_carrying_a_command_is_refused():
    with pytest.raises(models.ModelError, match="cannot use"):
        models.validate(_api(command=("claude",)))


def test_an_unknown_field_is_refused_rather_than_ignored():
    with pytest.raises(models.ModelError, match="does not know"):
        models._model_from({"id": "x", "vendor": "v", "name": "n", "transport": "cli",
                            "command": ["x"], "temperature": 0.7})


@pytest.mark.parametrize("missing,message", [
    ({"vendor": ""}, "names no vendor"),
    ({"name": ""}, "names no model"),
    ({"transport": "carrier pigeon"}, "unknown transport"),
])
def test_incomplete_entries_are_refused(missing, message):
    with pytest.raises(models.ModelError, match=message):
        models.validate(_api(**missing))


def test_a_cli_model_with_no_command_is_refused():
    with pytest.raises(models.ModelError, match="no command"):
        models.validate(_cli(command=()))


def test_an_api_model_with_no_endpoint_is_refused():
    with pytest.raises(models.ModelError, match="no endpoint"):
        models.validate(_api(endpoint=""))


@pytest.mark.parametrize("endpoint", ["ftp://api.example.com/v1", "file:///etc/passwd",
                                      "api.example.com/v1"])
def test_an_endpoint_this_runner_does_not_speak_is_refused(endpoint):
    with pytest.raises(models.ModelError, match="scheme"):
        models.validate(_api(endpoint=endpoint))


# --- the registry -------------------------------------------------------------------------

def test_duplicate_ids_are_refused():
    with pytest.raises(models.ModelError, match="two models"):
        models.Registry(models=(_api(), _api()))


def test_add_and_remove():
    registry = models.Registry().add(_cli()).add(_api())
    assert len(registry) == 2
    assert registry.get("opus").vendor == "anthropic"
    assert len(registry.remove("opus")) == 1


def test_removing_something_that_is_not_there_says_what_is():
    with pytest.raises(models.ModelError, match="no model"):
        models.Registry(models=(_cli(),)).remove("nope")


def test_leaving_lists_exactly_what_goes_out():
    """The one question the console has to be able to answer without the operator squinting."""
    registry = models.Registry(models=(
        _cli(),
        _api(id="ollama", vendor="ollama", endpoint="http://127.0.0.1:11434/api", key_env=""),
        _api(id="onprem", vendor="vllm", endpoint="http://10.0.0.7:8000/v1", key_env=""),
        _api(),
    ))
    assert [m.id for m in registry.leaving()] == ["onprem", "opus"]


def test_a_missing_file_is_an_empty_registry(tmp_path):
    assert len(models.load(tmp_path / "nothing.json")) == 0


def test_a_malformed_file_is_an_error_not_an_empty_registry(tmp_path):
    """Same rule as settings.py: a typo and "you have no models" must not be the same message."""
    path = tmp_path / "models.json"
    path.write_text('{"models": [', encoding="utf-8")
    with pytest.raises(models.ModelError, match="not valid JSON"):
        models.load(path)


def test_a_round_trip_keeps_every_field(tmp_path):
    path = tmp_path / "models.json"
    original = models.Registry(models=(_cli(note="the one on this laptop"), _api()))
    models.save(original, path)
    reloaded = models.load(path)
    assert [m.as_dict() for m in reloaded] == [m.as_dict() for m in original]


# --- a seat may name a model the same way a node does -------------------------------------------

def test_a_seat_can_name_a_registry_model():
    """One naming scheme.

    Found by building the panel that shows where each model is used: `claude` and
    `python3 agent.py --as claude` appeared as two different models, because `node_models` names a
    **model id** and `seat_models` named an **argv**. The panel is where that stopped being
    invisible.
    """
    from ai_sdlc_runner import cli

    registry = models.Registry(models=(_cli(id="claude", command=("run-claude", "-p")),))
    factory = cli.session_factory({"agent_command": ["default"]},
                                  seat_models={"defect": "claude"}, registry=registry)
    assert factory(seat="defect").argv == ["run-claude", "-p"]


def test_an_argv_seat_still_works():
    """It predates the registry, and some projects will have it. The fallback is the older scheme."""
    from ai_sdlc_runner import cli

    factory = cli.session_factory({"agent_command": ["default"]},
                                  seat_models={"defect": ["custom", "cmd"]},
                                  registry=models.Registry())
    assert factory(seat="defect").argv == ["custom", "cmd"]


def test_a_seat_naming_something_that_is_not_a_model_falls_back_to_argv():
    from ai_sdlc_runner import cli

    factory = cli.session_factory({"agent_command": ["default"]},
                                  seat_models={"defect": "not-a-model"},
                                  registry=models.Registry())
    assert factory(seat="defect").argv == ["not-a-model"]


def test_a_registry_with_an_unknown_top_level_key_is_refused(tmp_path):
    """CHG-20260823-21's other refusal, which nothing tested until CHG-20260827-07.

    A seat found that `{"models": [], "modelz": [...]}` loaded as an **empty registry**: one typo
    and every model you configured is gone, with no message. The fix closed the envelope; no test
    was written for it, so an acceptance-round verifier had to drive it by hand to confirm it fires.

    The refusal must name the offending key. "invalid registry" sends the reader back to a file
    they have already re-read twice — the typo is the thing they cannot see.
    """
    from ai_sdlc_runner import models as models_mod

    written = tmp_path / "models.json"
    written.write_text(json.dumps({"models": [], "modelz": [{"id": "opus"}]}),
                       encoding="utf-8")

    with pytest.raises(models_mod.ModelError) as caught:
        models_mod.load(str(written))

    message = str(caught.value)
    assert "modelz" in message, f"the refusal does not name the offending key: {message}"
    assert "models" in message, "the refusal should say what the key was probably meant to be"


def test_a_registry_whose_envelope_is_correct_still_loads(tmp_path):
    """The over-refusal direction. A closed envelope that refuses the legitimate shape is worse
    than the open one it replaced."""
    from ai_sdlc_runner import models as models_mod

    written = tmp_path / "models.json"
    written.write_text(json.dumps({"models": []}), encoding="utf-8")
    assert models_mod.load(str(written)) is not None
