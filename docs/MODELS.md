# Managing models — the schema

The `Model` **shape** appears in three places already: the registry file in
[`SCHEMAS.md`](SCHEMAS.md), the `models` table in [`DATABASE.md`](DATABASE.md), and `GET`/`POST
/models` in [`API.md`](API.md).

**The rules that govern it appeared in none of them**, and the rules are the whole of what makes this
schema more than a list: what a model must have, what it may not have, how *reach* is decided, and
how a model gets from the registry to an actual ask.

Defined by [`models.py`](../src/ai_sdlc_runner/models.py) (the registry) and
[`engine.py`](../src/ai_sdlc_runner/engine.py) + [`cli.py`](../src/ai_sdlc_runner/cli.py) (the
routing). Pinned by [`tests/test_models_schema.py`](../tests/test_models_schema.py).

---

## 1 · The two halves, and why they are separate

```
Registry            "the models this project may use, and nothing about which node uses which"
Assignment          "which node, and which seat, gets which model"
```

`Registry`'s own docstring draws that line. It matters because they change for different reasons and
live in different files: the registry is **what exists**, the assignment is **what this change
does**. A model added to the registry runs nothing until something names it.

| | Where it lives | Closed? |
|---|---|---|
| Registry | `models.json` → moving into SQLite | **yes**, entry *and* envelope |
| Assignment | the plan's `node_models` / `seat_models`, and `--seat-model` | **no** — the plan file is open, and that is a recorded gap |

---

## 2 · The Model

```jsonc
{ "id":        "opus",                    // a plain name; used as a key in config and on the wire
  "vendor":    "anthropic",               // which API this speaks
  "name":      "claude-opus-5",           // the vendor's own identifier
  "transport": "cli" | "api",
  "command":   ["claude", "-p"],          // cli only — argv as a LIST
  "endpoint":  "https://api…/v1/messages",// api only
  "key_env":   "ANTHROPIC_API_KEY",       // api only — the NAME of a variable. Never a key.
  "note":      "" }
```

Eight fields persist. Two more are **computed on every read and never stored**:

```jsonc
{ "reach": "local" | "internal" | "external",
  "leaves_this_machine": false }
```

`save()` strips them, with the reason on the line that does it: *"both are computed; storing them
would let a stale label outlive the truth."*

### `command` is a list, not a string

Deliberate: a string would be re-split by a shell that was never run. `["claude", "-p"]` is two
arguments no matter what is inside them.

### `key_env` holds a name, never a value

Checked against `^[A-Za-z_][A-Za-z0-9_]*$` — which is also what catches somebody pasting the key
itself into the field. `sk-ant-…` fails the pattern, so the **shape** refuses it before a human has
to notice.

---

## 3 · Every refusal, in the order `validate` makes them

`validate()`'s docstring: *"Every refusal this registry makes, in one place so none of them is
optional."*

### Always

| Refused | Because |
|---|---|
| an `id` that is not a plain name | it is a key in config *and* on the wire; something that needs quoting gets quoted differently in two places |
| no `vendor` | which API this speaks is not derivable from the endpoint, and guessing would be inventing one |
| no `name` | — |
| a `transport` outside `cli` / `api` | — |

### A `cli` model

| Refused | Because |
|---|---|
| no `command` | there is nothing to run |
| **any `endpoint` or `key_env`** | *"a field nothing reads is one somebody will later assume was honoured"* |

### An `api` model

| Refused | Because |
|---|---|
| no `endpoint` | — |
| a scheme other than `http`/`https` | — |
| **a secret in the query string** | query strings land in access logs and proxy logs — the two places nobody thinks to inspect |
| any `command` | it cannot use one |
| a `key_env` that is not a variable name | see above — the shape catches a pasted key |
| **`reach == external` with no `key_env`** | an unauthenticated public endpoint is more likely a half-finished entry than a real one, and half-finished is worth stopping on |

### The secret check matches **keys**, not shapes

```python
_SECRET_KEYS = ("key", "token", "secret", "password", "apikey", "api_key", "access_token", "sig")
```

*"Matching on the key rather than trying to recognise a secret's shape: shapes differ per vendor and
change without notice, while somebody writing `?api_key=` has told you what it is."*

**Not exhaustive, and it says so.** A vendor using `?auth=` gets through. This is a check that
refuses what it recognises and does not claim to recognise everything — which is the opposite of the
coarse check that answers "safe" about what it never examined.

### And one refusal at the registry level

Two models with the same `id` are refused. `__post_init__` validates every model on construction, so
there is no path to a `Registry` holding an invalid one.

---

## 4 · `reach` — computed, never declared

The one field worth being certain about, and the one an operator must never label themselves:

> *"Asking the operator to label this themselves would put the one fact worth being sure about behind
> the one place a mistake is invisible — a model labelled `internal` pointing at a public host is a
> configuration that reads as safe and is not."*

```
transport == cli                          -> local
host is localhost / localhost.localdomain -> local
IP and is_loopback                        -> local
IP and is_private or is_link_local        -> internal
name with no dot ("gpu-box")              -> internal
name ending .local .internal .lan .home.arpa -> internal
anything else                             -> external
```

Two decisions in there are worth reading twice:

- **A single-label name is `internal`.** `gpu-box` is a network name; `api.example.com` is not.
- **Unresolvable is `external`.** Not "unknown", not "assume local" — *"guessing the generous answer
  about where data goes is the wrong way to be wrong."*

`leaves_this_machine` is simply `reach != local`. `Registry.leaving()` returns those models, and
`GET /models` sends the list at the top level so *"what goes out from here"* never requires reading
hostnames off a list.

---

## 5 · Assignment — from the registry to an actual ask

The registry says a model **exists**. Three separate mechanisms say a model is **used**.

### `node_models` — by node, and the node's `mode` decides what the list means

```jsonc
"node_models": { "lead_review": ["opus", "gpt", "gemini"] }
```

**The same three ids mean different things at different nodes**, and the difference is the node's
declared `mode` — never its name:

| mode | what the list means |
|---|---|
| `single` | one model, one session |
| `model_panel` | **N voices on one question**, adjudicated |
| `pool` | N candidates; **one** does the work, chosen at random |
| `follows` | the list is ignored — it reuses whichever model answered the node named in `follows` |
| `seat_panel` / `survey` | the list is ignored — seats route by seat, see below |
| `runner` | nobody is asked |

A node with nothing here is asked **once**, however it is declared.

### `seat_models` — by review seat

```jsonc
"seat_models": { "conformance": "opus", "defect": ["python3", "agent.py"] }
```

Or on the command line: `--seat-model SEAT=COMMAND`, repeatable.

A seat may name a **registry model id** or a raw command. The id is resolved **first**, deliberately:
*"a plain string that happens to be a model id meaning 'run this program called claude' would be a
nasty way to find out the two naming schemes had diverged."*

**A model id the registry does not have is an error, not a fallback.** Falling back to the default
would mean a panel of three quietly answered three times by one backend — the exact failure the whole
mechanism exists to prevent.

### Resolution order, most specific first

```
a seat naming a registry model id      (resolved first, so the two naming schemes cannot diverge)
  →  the model a node's mode picked    (registry lookup; raises if the project has no such model)
  →  the seat's raw command
  →  agent_command from runner.yaml
  →  a stub that answers nothing
```

Routing lives in the **factory**, never in the work order. That is what makes a panel meaningful:
every voice receives an identical order and only the answerer differs.

### An `api` model validates, appears in the console — and cannot be dispatched to

This is the sharpest thing on the page, and it is easy to miss because nothing about registering
one goes wrong:

```
model 'gpt' is 'api', and this runner dispatches by running a command. An api model needs a
backend that speaks to it — there is none yet, and pretending otherwise would send the work to
the default and report it as 'gpt'.
```

`validate()` accepts an `api` model, `GET /models` lists it, the console shows its `reach`, and the
first ask routed to it **raises**. The refusal is the right one — the alternative named in its own
message is *sending the work to the default and reporting it as `gpt`*, which is a lie in the
dispatch record — but it means **`transport: "api"` is a declaration this runner cannot yet honour.**

If every model you register is `cli`, none of this reaches you. If you register an `api` model
expecting it to work, it fails at the first ask rather than at registration.

### A pool's choice is random **and** reproducible

```python
random.Random(f"{cfg.dispatch_seed}:{node.id}:{nth_ask}")
```

Not a contradiction: *"the choice is arbitrary with respect to the work, not with respect to the
record."* Any cleverer rule would be the runner ranking models at a task it has not seen, and the
ranking would be one nobody wrote down.

The seed is `dispatch_seed` (default `0`, and the CLI does not set it), the node id, and **which ask
this is** — so two nodes, and two visits to one node in the module loop, do not march in lockstep
through the pool. Inserting an earlier ask shifts the ordinal and can change later dispatches.

**Every dispatch is recorded** in `RunReport.dispatches` and in the conversation's `ask` turn. That
recording is what makes "at random" acceptable: an unrecorded random dispatch is indistinguishable
from a preference nobody declared.

### `follows` reuses the **most recent** visit

Not the first. The module loop revisits `engineer_build` once per module, and a self-verification
reusing the model from *module one* would be checking work it never saw.

---

## 6 · Where a model is used — `GET /config/nodes`

The question a registry cannot answer about itself. *"A model listed and used nowhere looks
configured, and a model on eight nodes looks the same in a list as one on a single node."*

```jsonc
"by_model": { "opus": { "nodes": [ {"node_id": "lead_review", "mode": "seat_panel"} ],
                        "seats": [ "conformance" ],
                        "known": true } }
```

- `known: false` — a plan names it and the registry does not have it.
- **Every registry model appears**, even with empty `nodes` and `seats`. That is how "configured but
  unused" becomes visible instead of looking identical to "in use".

---

## 7 · The single-model-panel warning

Not a refusal — a statement. When every seat on a panel was answered by the same backend:

> *"every seat was answered by the same backend. The sessions were independent; the model was not,
> so the seats share whatever it cannot see."*

Recorded in `RunReport.single_model_panels` and printed. **Independence of sessions is not
independence of blind spots**, and a panel that cannot tell you which is which has kept the votes and
thrown away the thing being voted on.

---

## 8 · What model management does **not** have

- **No removal through the API.** `Registry.remove` exists; nothing routes to it. `POST /models`
  adds, and there is no `DELETE`.
- **No liveness check.** Nothing verifies an endpoint answers or a command exists until an ask is
  dispatched to it. A registry entry is a *declaration*, not a probe.
- **No credential validation.** `key_env` names a variable; nothing checks the variable is set, and
  a missing one surfaces as a failed ask.
- **No versioning.** The registry has no schema number.
- **The assignment side is not closed.** `node_models` and `seat_models` come from the plan file,
  which ignores unknown keys — a misspelt `node_models` silently assigns nothing, and every node
  falls back to one backend. Recorded in [`SCHEMAS.md`](SCHEMAS.md); not fixed.
- **`_SECRET_KEYS` is not exhaustive**, by design and by its own comment.
