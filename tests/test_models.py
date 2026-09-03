"""Task 8 — the model registry, and the one fact it exists to make impossible to miss.

The console is local only; the models are not, and that is deliberate. A run is useful because it can
call out — to a vendor's API, or to something on this network. Inbound closed, outbound open.

What this registry refuses is not an external model. It refuses an operator having to **infer** that
they configured one. `reach` is computed from what the endpoint actually is, never declared, because
a model *labelled* `internal` while pointing at a public host is a configuration that reads as safe
and is not — and this repository has already had to stop itself treating a name as evidence once.
"""
import json
import pathlib

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


# --- the one the mutation group found unpinned (CHG-20260830-02) ------------------------------


@pytest.mark.parametrize("endpoint", ["https://", "not a url", "file:///x", "://nohost"])
def test_an_endpoint_with_no_host_is_refused_rather_than_given_a_reach(endpoint):
    """`reach_of` refuses when it cannot find a host, and nothing pinned that.

    Replacing the refusal with `return EXTERNAL` left every test green — and `external` is the
    *safe-looking* wrong answer here, because it is the grade that makes `validate` demand a key
    and then wave the entry through. An endpoint of `https://` with a `key_env` set would have been
    registered as a real public model that resolves to nothing.

    Guessing any answer is wrong when the question is where data goes: this is the same argument
    the unresolvable-name branch already makes, at the one input where there is nothing to guess
    from at all.
    """
    with pytest.raises(models.ModelError, match="before its reach can be known"):
        models.reach_of(models.API, endpoint)


def test_a_hostless_endpoint_does_not_survive_validate():
    """End to end, because `reach` is a property: the refusal has to reach the caller that matters.

    `validate` reads `model.reach`, so a guard that only fired inside `reach_of` while `validate`
    swallowed it would be a refusal nobody meets.
    """
    hostless = _api(endpoint="https://")
    with pytest.raises(models.ModelError, match="before its reach can be known"):
        models.validate(hostless)


def test_a_cli_model_needs_no_endpoint_to_have_a_reach():
    """The other direction: the refusal is about `api`, and must not spread to `cli`.

    A command runs here, so its reach is known without an endpoint — and a rule that demanded one
    would refuse every local model in the project's own examples.
    """
    assert models.reach_of(models.CLI, "") == models.LOCAL


#: URLs that carry a credential somewhere other than `?key=`. Each validated clean for six rounds
#: and was written to the registry and to `config.sqlite` — the harm `_secret_in_url`'s docstring
#: says it exists to prevent (CHG-20260831-02, ruled a defect by the round-7 risk seat).
SECRET_ELSEWHERE = [
    ("https://user:sk-ant-SECRET@api.vendor.com/v1", "a credential in the userinfo"),
    ("https://sk-ant-SECRET@api.vendor.com/v1", "a bare token in the userinfo"),
    ("https://api.vendor.com/v1?api_key=SECRET", "the original case, still refused"),
    ("https://api.vendor.com/v1#api_key=SECRET", "a key in the fragment, not the query"),
    # Eight vendors the round-9 defect and risk seats pasted in to show that gating the refusal on
    # a shape guess let real tokens through. Every one validated clean and reached `config.sqlite`
    # for one round; the guess picks the wording now and refuses either way (CHG-20260831-04).
    ("https://gsk_A1b2C3d4E5f6G7h8@api.groq.com/v1", "a Groq key"),
    ("https://hf_QwErTyUiOpAsDf@api-inference.hf.co/v1", "a Hugging Face token"),
    ("https://r8_abcdefGHIJKLmnop@api.replicate.com/v1", "a Replicate token"),
    ("https://glpat-ABCDEFGHIJKLMNOPQRST@gl.example.com/api", "a GitLab PAT, 26 characters"),
    ("https://npm_AbCdEfGhIjKlMnOpQr@registry.example.com/v1", "an npm token"),
    ("https://ATATT3xFfGF0T4JQ@jira.example.com/v1", "an Atlassian token"),
    ("https://co-1a2b3c4d5e6f@api.cohere.ai/v1", "a Cohere key"),
    ("https://3f9a1c8e77b04d21@api.vendor.com/v1", "16 hex characters and no prefix at all"),
]


@pytest.mark.parametrize("endpoint,why", SECRET_ELSEWHERE, ids=[c[1] for c in SECRET_ELSEWHERE])
def test_a_secret_outside_the_query_string_is_still_refused(endpoint, why):
    """`https://user:TOKEN@host` is a credential by position and needs no key to recognise.

    The scan read `?…` and nothing else. `server.py` already refused `parts.username or
    parts.password` on its own bind URL, so this codebase checked the shape in one place and not
    the other.
    """
    assert models._secret_in_url(endpoint) is not None, why


def test_a_url_with_an_ordinary_fragment_is_not_a_secret():
    """The other direction — the fragment is read, not feared."""
    assert models._secret_in_url("https://api.vendor.com/v1#section") is None


def test_a_plain_user_name_is_refused_with_a_remedy_that_applies_to_it():
    """`https://alice@host/v1` carries no key — so the *sentence* changes, not the answer.

    For one round this asserted `is None`: the round-8 objection was that sending the operator to
    move a non-existent credential into `key_env` names a remedy that does not apply, and I answered
    it by accepting the userinfo. The round-9 defect and risk seats then measured eight real vendor
    token formats validating clean and reaching `config.sqlite` (CHG-20260831-04).

    Nothing can tell a user name from a pasted token, which is the argument for refusing both — and
    for saying something different about each.
    """
    found, where, remedy = models._secret_in_url("https://alice@api.vendor.com/v1")

    assert (found, where) == ("a user name", "the userinfo before @")
    assert "key_env" not in remedy, "there is no key to move; that instruction does not apply"
    assert "Remove it" in remedy


def test_the_refusal_names_where_it_found_the_secret():
    """It said "query string" for a credential in the userinfo and for one in the fragment.

    A fragment is never sent to a server, so that sentence was false as well as misdirecting — and
    `cli.py`'s comment on the token link says exactly that. Nothing read the message the
    operator reads; these do.
    """
    for endpoint, place in [("https://u:sk-ant-S@api.v.com/v1", "the userinfo before @"),
                            ("https://api.v.com/v1#api_key=S", "the fragment"),
                            ("https://api.v.com/v1?api_key=S", "the query string")]:
        model = models.Model(id="m", vendor="v", name="n", transport="api", endpoint=endpoint)
        with pytest.raises(models.ModelError) as caught:
            models.validate(model)
        assert place in str(caught.value), f"{endpoint} -> {caught.value}"


#: Every endpoint the console's disclosure could name, and whether the bare-host **guess** is what
#: graded it. Four of these six are `internal` on a fact, not a guess, and the disclosure named
#: two of them: it restated the rule as `"." not in hostname` instead of calling it, and an IPv6
#: literal has no dot (CHG-20260831-03, conformance and defect seats).
BARE_HOST_CASES = [
    ("http://gpu-box:8000/v1", True, "the guess itself: a single label and nothing else"),
    ("http://[fd00::1]:8000/v1", False, "RFC 4193 unique-local — a fact, and it has no dot"),
    ("http://[fe80::1]:8000/v1", False, "link-local — also a fact, also dotless"),
    ("http://box.local/v1", False, "a suffix somebody wrote deliberately"),
    ("http://192.168.1.9/v1", False, "RFC 1918"),
    ("http://127.0.0.1:8000/v1", False, "loopback is LOCAL, and never reaches the rule"),
]


@pytest.mark.parametrize("endpoint,guessed,why", BARE_HOST_CASES,
                         ids=[c[0] for c in BARE_HOST_CASES])
def test_the_console_names_only_the_models_the_guess_graded(endpoint, guessed, why):
    """The line exists to name the models resting on a judgement. Naming others is the same
    failure as naming none — the operator cannot tell which grade to go and check.
    """
    model = models.Model(id="m", vendor="v", name="n", transport="api", endpoint=endpoint)
    assert models.graded_by_guess(endpoint) is guessed, why

    named = models.Registry(models=(model,)).internal_by_guess()
    assert [m.id for m in named] == (["m"] if guessed else []), why


@pytest.mark.parametrize("endpoint,guessed,why", BARE_HOST_CASES,
                         ids=[c[0] for c in BARE_HOST_CASES])
def test_the_guess_and_the_grade_cannot_disagree_about_the_rule(endpoint, guessed, why):
    """Every endpoint the disclosure names must in fact be graded `internal`, and no other.

    The disclosure used to restate `reach_of`'s rule in its own words. It calls it now, and this is
    what says the two have not drifted apart again.

    Parametrised, not a `for` inside the body: as a loop under `if guessed:` five of the six rows
    were walked past in silence, a table that looked like six guarantees and was one — which is the
    defect this file's sibling table had one round earlier (CHG-20260831-04, idiom seat).
    """
    graded_internal = models.reach_of("api", endpoint) == models.INTERNAL
    if guessed:
        assert graded_internal, f"{why}: the disclosure names it, so the grade must be internal"
    else:
        assert not models.graded_by_guess(endpoint), (
            f"{why}: whatever the grade is, the guess is not what produced it")


# ── a guessed reach says it is a guess, where the person who can judge it looks ──────────────────


def test_a_guessed_reach_says_so_on_the_wire():
    """`internal_by_guess`'s docstring: *"The console names these, so the guess is visible to the
    person who can tell whether it is right."*

    Measured before this: its only caller was `runner models`' stdout footer; `Model.as_dict`
    carried `reach` and `leaves_this_machine` and nothing saying the reach was inferred; and
    `console/index.html` rendered `m.reach` as a fact with **zero** mentions of the guess.

    What the guess buys is the exemption at `graded_by_guess` from the refusal that an external
    endpoint must name a key variable. **A disclosure that makes an exemption acceptable has to
    reach the surface, or the exemption is unaccompanied** (idiom seat L-47).
    """
    guessed = models.Model(id="gpu", vendor="v", name="n", transport="api",
                           endpoint="http://gpu-box/v1")
    measured = models.Model(id="api", vendor="v", name="n", transport="api",
                            endpoint="https://api.example.com/v1", key_env="API_KEY")

    assert guessed.as_dict()["reach"] == models.INTERNAL
    assert guessed.as_dict()["reach_guessed"] is True
    assert measured.as_dict()["reach_guessed"] is False


def test_the_console_names_the_guess():
    """The surface the docstring promises. It had zero mentions of it."""
    page = (pathlib.Path(models.__file__).parent / "console" / "index.html").read_text(
        encoding="utf-8")

    assert "reach_guessed" in page
    assert "no dot in it" in page, "the page must say what the guess was made from"


def test_no_computed_field_is_written_to_disk():
    """**The rule.** `save` excluded computed fields with a literal tuple, so a third one meant
    remembering a second place — and this record added a third.

    Derived from `models.COMPUTED` now, so a fourth cannot reach disk by being forgotten.
    """
    import json
    import tempfile

    path = pathlib.Path(tempfile.mkdtemp()) / "models.json"
    models.save(models.Registry(models=(models.Model(
        id="gpu", vendor="v", name="n", transport="api", endpoint="http://gpu-box/v1"),)), path)

    stored = json.loads(path.read_text(encoding="utf-8"))["models"][0]

    leaked = sorted(name for name in models.COMPUTED if name in stored)
    assert leaked == [], f"these are computed and were written to disk: {leaked}"
    assert set(models.COMPUTED) <= set(
        models.Model(id="g", vendor="v", name="n", transport="api",
                     endpoint="http://b/v1").as_dict()), (
        "COMPUTED names a field `as_dict` does not produce")


def test_nothing_hand_writes_the_computed_field_set():
    """**The rule that the fifth copy earned.**

    Adding one computed field turned five guards red, and each held its own hand-written version
    of the same fact: the exclusion literal inside `models.save`, two in `test_models_schema.py`
    (one of them asserting the literal SOURCE TEXT of the first), one in `test_schemas.py`, and
    one in `test_database_schema.py`. A sixth would have been found the same way — by breaking.
    `models.COMPUTED` is the one name, and this refuses a second spelling of it.

    **This docstring names those five without reproducing any of them**, because the first draft
    of it did reproduce them, and the rule flagged its own explanation. The exemption that would
    have hidden that — skip the file the rule lives in — is the shape CHG-20260903-33 got wrong,
    so the prose was changed instead of the scope (CHG-20260903-39).
    """
    # **A set literal, not the two words.** The first version matched any line naming both,
    # and flagged five: four prose explanations (including this docstring) and a test function
    # whose *name* contains one of them. None was a copy. A rule that fires on prose about the
    # thing rather than on the thing is the rule's defect — the fourth time this session that
    # distinction has had to be drawn, and the fourth time the answer was to narrow the rule
    # rather than reword the code (CHG-20260903-39).
    import re

    root = pathlib.Path(models.__file__).resolve().parents[2]
    literal = re.compile(r"[({]\s*\"reach\"\s*,\s*\"leaves_this_machine\"\s*[)}]")
    copies = []
    for path in list((root / "src").rglob("*.py")) + list((root / "tests").glob("*.py")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if literal.search(line) and "COMPUTED" not in line:
                copies.append(f"{path.relative_to(root).as_posix()}: {line.strip()[:64]}")

    assert copies == [], (
        f"these spell out the computed-field set instead of reading `models.COMPUTED`: {copies}")
