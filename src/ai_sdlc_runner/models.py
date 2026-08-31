"""models.py — the model registry (CHG-20260823-11 task 8).

The console is **local only**: nothing outside this machine may reach it. The models it dispatches to
are the opposite — a run is useful precisely because it can call out, to a vendor's API or to
something on the network. Inbound closed, outbound open, and the two are not in tension: one is about
who may drive this runner, the other about where its work is done.

## What this module exists to prevent

Both reaches are allowed. What is *not* allowed is the operator having to **infer** which one they
picked. "This work order leaves the machine" is a fact about a configuration, and a registry that
records `endpoint` and leaves the reader to notice the hostname has made that fact into a detail.

So every model carries a **reach** — ``local``, ``internal`` or ``external`` — computed from what it
actually is, and the console shows it. The point is not to discourage external models. It is that
choosing one should be a decision somebody made rather than one they discover later, in the same way
this repository refuses to let a node's *name* decide how its models are read.

## Keys are named, never held

An API model stores the **name of an environment variable**, never a value. Two reasons, and the
second is the one that bites: a key in a config file reaches a screenshot, a bug report, a pasted
snippet, and a git history that does not forget. The name is checked to *look* like a variable name,
which is also what catches somebody pasting the key itself into the field — the shape refuses it
before a human has to notice.

An endpoint carrying a secret in its query string is refused for the same reason with a sharper edge:
query strings land in access logs and proxy logs, which are the two places nobody remembers to
inspect.
"""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from . import paths

CLI = "cli"      #: a command run on this machine
API = "api"      #: an HTTP endpoint
TRANSPORTS = (CLI, API)

LOCAL = "local"        #: a subprocess here, or an endpoint on loopback
INTERNAL = "internal"  #: reachable on a private network — a self-hosted model, not the internet
EXTERNAL = "external"  #: a public endpoint; work orders leave this network
REACHES = (LOCAL, INTERNAL, EXTERNAL)

#: An environment variable's name, not its value. `sk-ant-...` fails this, which is the point.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Query keys that mean a secret is in the URL. Not exhaustive by design — see `_secret_in_url`.
_SECRET_KEYS = ("key", "token", "secret", "password", "apikey", "api_key", "access_token", "sig")


class ModelError(Exception):
    """Refused. A registry that accepted this would be describing something else."""


#: A userinfo value that is recognisably a pasted credential. This picks the **wording** of a
#: refusal; it does not decide whether to refuse. For one round it decided that too, and the round-9
#: defect and risk seats measured what the shape guess let through: `gsk_…` (Groq), `hf_…`, `r8_…`,
#: `glpat-…`, `npm_…`, `ATATT…`, `co-…` and any hex token under 32 characters all validated clean
#: and were written to `config.sqlite` — the exact harm this module's docstring says the scan exists
#: to prevent. The argument for narrowing was that `https://alice@host/v1` got a remedy that did not
#: apply to it; that is an argument about the sentence, and it is fixed in the sentence
#: (CHG-20260831-04).
_SECRET_PREFIXES = ("sk-", "sk_", "pk-", "ghp_", "gho_", "xox", "AKIA", "AIza",
                    # Seven of the eight credentials the round-9 seats pasted in. The eighth was
                    # `3f9a1c8e77b04d21` — sixteen hex characters and no prefix at all — which no
                    # entry here can represent, and which is refused anyway because this tuple only
                    # picks the sentence. A `Bearer-` entry stood here for one round: invented, in a
                    # comment claiming to list what was measured (CHG-20260831-05, conformance and
                    # idiom seats).
                    "gsk_", "hf_", "r8_", "glpat-", "npm_", "ATATT", "co-")


def _looks_secret(value: str) -> bool:
    """Is this userinfo recognisably a pasted credential? Chooses wording, never whether to refuse.

    Wrong in both directions and it does not matter, because both directions are refused. A vendor
    prefix this does not know gets the milder sentence and the same refusal.
    """
    return value.startswith(_SECRET_PREFIXES) or len(value) >= 32


#: What to do about a key that is in the URL and should not be.
_KEY_ENV = "Put the key in an environment variable and name it in `key_env`."

#: And what to do about userinfo that is not a key. `key_env` would be the wrong instruction — there
#: is nothing to move — and this runner sends no HTTP basic auth, so the field is unused either way.
_DROP_USERINFO = ("Remove it: this runner sends no HTTP basic auth, so userinfo in an endpoint is "
                  "never read — and nothing here can tell a user name from a pasted token.")


def _secret_in_url(endpoint: str) -> Optional[Tuple[str, str, str]]:
    """Where a secret sits in this URL, if it does — `(what was found, where, what to do)`.

    The remedy travels with the finding because it differs: a key in the query string moves to
    `key_env`; a bare user name has nothing to move and is simply dropped. Sending the second case
    to `key_env` is what the round-8 seats objected to, and answering that by *accepting* the
    userinfo is what the round-9 seats measured as eight real credentials reaching the store.

    Returns the place as well as the finding, because the refusal has to name it. Saying "query
    string" about a credential in the userinfo sends the operator to look somewhere it is not, and
    about a fragment it says something false as well — a fragment is never sent to a server, which
    is why it needs a different reason rather than the same sentence (CHG-20260831-03).

    Matching on the *key* wherever there is a key to match on: shapes differ per vendor and change
    without notice, while somebody writing ``?api_key=`` has told you what it is.

    The userinfo has no key — `https://TOKEN@host/v1` is a bare value — so there is nothing to
    match on and the branch refuses **all** of it. `_looks_secret` reads the shape only to pick
    which sentence to print, so the price this paragraph describes is not paid: a vendor prefix
    nobody has heard of gets the milder wording and the same refusal (CHG-20260831-05).
    """
    parts = urlsplit(endpoint)

    # Userinfo first, and it needs no key to recognise: `https://user:TOKEN@host/…` *is* a
    # credential by position. Six rounds of review disclosed only that the key list is
    # non-exhaustive; nobody had disclosed that the scan reads the query string and nothing else, so
    # a secret written this way validated clean and was stored in the registry and in
    # `config.sqlite` — the harm this function's own docstring says it exists to prevent. `server.py`
    # already refuses `parts.username or parts.password` on its own bind URL, so the codebase
    # checked the shape in one place and not the other (CHG-20260831-02, ruled a defect by the
    # round-7 risk seat after six rounds as a disclosure).
    if parts.password:
        return ("a password", "the userinfo before @", _KEY_ENV)
    if parts.username:
        # Refused either way. The shape only chooses which sentence, and the value itself is never
        # echoed: the message's own reason is that these travel into logs, and it was printing the
        # first six characters of the thing it was refusing (CHG-20260831-04, risk seat).
        looks = _looks_secret(parts.username)
        return ("a value shaped like a credential" if looks else "a user name",
                "the userinfo before @",
                _KEY_ENV if looks else _DROP_USERINFO)

    # The fragment travels with the URL and is read the same way; `#api_key=…` hid from a scan that
    # looked only at `?`.
    for carrier, where in ((parts.query, "the query string"), (parts.fragment, "the fragment")):
        for pair in carrier.split("&"):
            name = pair.split("=", 1)[0].strip().lower()
            if name in _SECRET_KEYS:
                return (name, where, _KEY_ENV)
    return None


#: Name suffixes that say "my own network" outright, as against the bare-host judgement below.
#: Read by `reach_of` alone; the single-label half of its judgement lives in `graded_by_guess`,
#: which `reach_of` calls. For one round the disclosure had its own copy of `"." not in host` and
#: the record said it "calls the rule" — the rename happened and the body did not
#: (CHG-20260831-05, defect seat). A disclosure that restates its subject's rule
#: instead of calling it drifts from it — and did: the restatement `"." not in hostname` named every
#: dotless host, and an IPv6 literal has no dot (CHG-20260831-03, conformance and defect seats).
LOCAL_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")


def graded_by_guess(endpoint: str) -> bool:
    """Would `reach_of` call this endpoint `internal` *because its host has no dot in it*?

    Not "is it internal" — `fd00::1` is internal on an RFC 4193 fact, and `gpu-box.local` on a
    suffix somebody wrote deliberately. Only the single-label guess is a judgement, and only it is
    what the console discloses.
    """
    host = (urlsplit(endpoint).hostname or "").lower()
    if not host or host in ("localhost", "localhost.localdomain"):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return "." not in host
    return False


def reach_of(transport: str, endpoint: str = "") -> str:
    """Where a model actually is. Computed, never declared.

    Asking the operator to label this themselves would put the one fact worth being sure about
    behind the one place a mistake is invisible — a model labelled ``internal`` pointing at a public
    host is a configuration that reads as safe and is not.
    """
    if transport == CLI:
        return LOCAL
    host = (urlsplit(endpoint).hostname or "").lower()
    if not host:
        raise ModelError("an api model needs an endpoint before its reach can be known")
    if host in ("localhost", "localhost.localdomain"):
        return LOCAL
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A name. A single label (`gpu-box`) or an explicitly local suffix is a network name; a
        # dotted public name is not. Unresolvable is treated as external, because guessing the
        # generous answer about where data goes is the wrong way to be wrong.
        if graded_by_guess(endpoint) or host.endswith(LOCAL_SUFFIXES):
            return INTERNAL
        return EXTERNAL
    if address.is_loopback:
        return LOCAL
    if address.is_private or address.is_link_local:
        return INTERNAL
    return EXTERNAL


@dataclass(frozen=True)
class Model:
    """One model the runner can dispatch to."""

    id: str
    vendor: str
    #: The vendor's own identifier — `claude-opus-5`, `gpt-5`, whatever the endpoint expects.
    name: str
    transport: str
    #: `cli` only: argv. A list, not a string, so nothing is re-split by a shell that was never run.
    command: Tuple[str, ...] = ()
    #: `api` only.
    endpoint: str = ""
    #: `api` only: the **name** of an environment variable holding the key. Never the key.
    key_env: str = ""
    note: str = ""

    @property
    def reach(self) -> str:
        return reach_of(self.transport, self.endpoint)

    @property
    def leaves_this_machine(self) -> bool:
        return self.reach != LOCAL

    def as_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        payload["reach"] = self.reach
        payload["leaves_this_machine"] = self.leaves_this_machine
        return payload


def validate(model: Model) -> Model:
    """Every refusal this registry makes, in one place so none of them is optional."""
    if not model.id or not _ENV_NAME.match(model.id.replace("-", "_")):
        raise ModelError(
            f"model id {model.id!r} is not a plain name. It is used as a key in config and on the "
            f"wire; something that needs quoting will be quoted differently in two places.")
    if not model.vendor:
        raise ModelError(f"model {model.id!r} names no vendor — which API this speaks is not "
                         f"derivable from the endpoint, and guessing it would be inventing one")
    if not model.name:
        raise ModelError(f"model {model.id!r} names no model at the vendor")
    if model.transport not in TRANSPORTS:
        raise ModelError(f"model {model.id!r} has unknown transport {model.transport!r}; this "
                         f"runner speaks {list(TRANSPORTS)}")

    if model.transport == CLI:
        if not model.command:
            raise ModelError(f"cli model {model.id!r} has no command to run")
        if model.endpoint or model.key_env:
            raise ModelError(
                f"cli model {model.id!r} carries an endpoint or a key name it cannot use. A field "
                f"nothing reads is one somebody will later assume was honoured.")
        return model

    if not model.endpoint:
        raise ModelError(f"api model {model.id!r} has no endpoint")
    scheme = urlsplit(model.endpoint).scheme
    if scheme not in ("http", "https"):
        raise ModelError(
            f"model {model.id!r} has endpoint scheme {scheme or '(none)'}; this runner speaks http "
            f"and https")
    leaked = _secret_in_url(model.endpoint)
    if leaked:
        found, where, remedy = leaked
        raise ModelError(
            f"model {model.id!r} puts {found} in {where} of its endpoint. A URL is copied into "
            f"logs, bug reports and shell history whole, so anything inside it travels with it. "
            f"{remedy}")
    if model.command:
        raise ModelError(f"api model {model.id!r} carries a command it cannot use")
    if model.key_env and not _ENV_NAME.match(model.key_env):
        raise ModelError(
            f"model {model.id!r} has key_env {model.key_env!r}, which is not the name of an "
            f"environment variable. If that is the key itself: this registry stores the **name** of "
            f"the variable holding it, so the key never reaches a file, a screenshot or a git "
            f"history.")
    if model.reach not in REACHES:                  # pragma: no cover - only a bug reaches this
        raise ModelError(
            f"model {model.id!r} computed reach {model.reach!r}, which is not one of {list(REACHES)}"
            f" — a reach nobody can read is worse than no reach at all")
    if model.reach == EXTERNAL and not model.key_env:
        # Not a guess about the vendor's auth: an unauthenticated public endpoint is more likely a
        # half-finished entry than a real one, and half-finished is worth stopping on.
        raise ModelError(
            f"model {model.id!r} reaches a public endpoint with no key named. If it genuinely needs "
            f"no key, say so in `note` and name the variable anyway — an empty one is fine.")
    return model


@dataclass
class Registry:
    """The models this project may use, and nothing about which node uses which."""

    models: Tuple[Model, ...] = ()

    def __post_init__(self) -> None:
        seen = set()
        for model in self.models:
            validate(model)
            if model.id in seen:
                raise ModelError(f"two models are called {model.id!r}")
            seen.add(model.id)

    def __iter__(self):
        return iter(self.models)

    def __len__(self) -> int:
        return len(self.models)

    def get(self, model_id: str) -> Model:
        for model in self.models:
            if model.id == model_id:
                return model
        raise ModelError(f"no model {model_id!r}; this project has {[m.id for m in self.models]}")

    def add(self, model: Model) -> "Registry":
        return Registry(models=self.models + (validate(model),))

    def remove(self, model_id: str) -> "Registry":
        self.get(model_id)
        return Registry(models=tuple(m for m in self.models if m.id != model_id))

    def leaving(self) -> List[Model]:
        """Every model whose work orders leave this machine, so the console can say so plainly."""
        return [m for m in self.models if m.leaves_this_machine]

    def internal_by_guess(self) -> List[Model]:
        """Models called `internal` only because somebody wrote a host with no dot in it.

        That is a judgement, not a fact, and what it buys is the exemption from the refusal that an
        external endpoint must name a key variable. On a network where `gpu-box` resolves publicly
        the grade is wrong. The console names these, so the guess is visible to the person who can
        tell whether it is right (CHG-20260831-02, risk seat).
        """
        return [m for m in self.models
                if m.transport == "api" and graded_by_guess(m.endpoint)]

    def as_dict(self) -> Dict[str, object]:
        return {"models": [m.as_dict() for m in self.models]}


def _model_from(payload: Dict[str, object]) -> Model:
    unknown = set(payload) - {f for f in Model.__dataclass_fields__}
    if unknown:
        raise ModelError(
            f"model {payload.get('id')!r} has field(s) this runner does not know: "
            f"{sorted(unknown)}. Ignoring them would let a setting look configured and do nothing.")
    return Model(
        id=str(payload.get("id") or ""),
        vendor=str(payload.get("vendor") or ""),
        name=str(payload.get("name") or ""),
        transport=str(payload.get("transport") or ""),
        command=tuple(payload.get("command") or ()),
        endpoint=str(payload.get("endpoint") or ""),
        key_env=str(payload.get("key_env") or ""),
        note=str(payload.get("note") or ""),
    )


def load(path: str | Path) -> Registry:
    """Read the registry. A missing file is an empty one; a malformed file is an error.

    The same rule `settings.py` uses, for the same reason: falling back to empty on a typo would make
    "you have no models" and "your file has a comma in the wrong place" the same message.
    """
    file = Path(path)
    if not file.exists():
        return Registry()
    text = file.read_text(encoding="utf-8").strip()
    if not text:
        return Registry()
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ModelError(f"{file} is not valid JSON: {exc}")
    if isinstance(payload, dict):
        # The **envelope** is closed too, and it was not. A seat found that
        # `{"models": [], "modelz": [...]}` loaded as an empty registry: one typo and every model
        # you configured is gone, with no message. That is the same failure this module's own
        # `_model_from` refuses one level down, and the same sentence applies -- ignoring a key
        # would let a setting look configured and do nothing.
        unknown = sorted(set(payload) - {"models"})
        if unknown:
            raise ModelError(
                f"{file} has top-level key(s) this runner does not know: {unknown}. Ignoring them "
                f"would let a whole registry look configured and do nothing -- a misspelt 'models' "
                f"loads as no models at all.")
        entries = payload.get("models")
    else:
        entries = payload
    if not isinstance(entries, list):
        raise ModelError(f"{file} should hold a list of models, or an object with a 'models' list")
    return Registry(models=tuple(_model_from(e) for e in entries))


def save(registry: Registry, path: str | Path) -> None:
    file = Path(path)
    paths.makedirs(file.parent)
    payload = {"models": [
        {k: v for k, v in m.as_dict().items()
         if k not in ("reach", "leaves_this_machine")}     # both are computed; storing them would
        for m in registry.models]}                          # let a stale label outlive the truth
    paths.write_text(
        file,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
