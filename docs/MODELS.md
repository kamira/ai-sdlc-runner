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

| | Where it lives | Persisted? | Closed? |
|---|---|---|---|
| Registry | the `models` table (and `models.json`, still written) | **yes** — `POST /models` | **yes**, entry *and* envelope |
| Assignment | the `node_assignments` / `seat_assignments` tables **and** the plan | **yes** — `POST /config/nodes`, `POST /config/seats` | node and seat and model id all checked |

### Both halves persist — and this is new

Until CHG-20260823-25 the assignment had **no writer anywhere in `src/`**: read from the plan at
startup, held in memory, exposed read-only. Through the console you could add a model and never
assign it.

The user ruled that 「模型配置」 means both halves, so [`store.py`](../src/ai_sdlc_runner/store.py)
now holds them: two tables and two routes for the assignment halves — `node_assignments` and
`seat_assignments`, `POST /config/nodes` and `POST /config/seats`.

### Precedence: the plan wins, and it is never silent

An assignment can come from two places:

- the **plan file** — this change's declaration;
- the **store** — the project's standing assignment, edited through the console.

**The plan wins where it says something; the store fills where the plan is silent.** That is
`settings.py`'s rule one layer out — *"a flag beats the file"* — and for the same reason: a
per-change declaration must not be silently overridden by something configured weeks ago.

`GET /config/nodes` returns a **`source`** map beside the merged assignment, saying which of the two
put each one there. A merged dict alone cannot say, and an override nobody can see is worse than no
override.

### What the store refuses

| Refused | Because |
|---|---|
| a node id the flow does not have | — |
| a node whose **mode ignores a model list** — `runner`, `follows`, `seat_panel`, `survey` | *a setting that looks configured and does nothing is worse than one that was rejected* |
| a model id the registry does not have | enforced by a foreign key, and refused **by name**: "assigned a model the project does not have" must not read the same as "assigned nothing" |
| a seat this runner does not define | checked against every seat, not only the ones today's floor opens — a standing assignment must survive a run that opens more |

Only **registry model ids** can be assigned through the store. A raw command line remains a plan and
`--seat-model` thing: the registry is what the store can point a foreign key at.

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
  "note":      "",
  "tier":      "" | "high" | "mid" | "low",      // a label a person gives it; empty = unclassified
  "effort_argv": ["--effort", "{effort}"],      // cli only — appended when an effort is in force
  "declared_reach": "" | "local" | "internal" | "external" } // optional; may only raise the derived reach (§4)
```

Eleven fields, listed in `models.Model`, persist. Three more are **computed on every read and never stored**:

```jsonc
{ "reach": "local" | "internal" | "external",
  "leaves_this_machine": false,
  "reach_guessed": false }
```

`save()` strips them, and `models.py` gives the reason where `models.COMPUTED` is declared:
*"Storing one would let a stale label outlive the truth."*

> Until CHG-20260907-14 this quoted *"both are computed; storing them would…"*, a comment
> `models.py` stopped carrying when the exclusion moved into `models.COMPUTED`
> (CHG-20260903-39). The count was two and the words were a sentence nothing said.

### `tier` and `effort_argv` (CHG-20261005-01)

`tier` is a **label**, not an inference: the runner holds no name→tier table, because one goes stale
with every model release. `setup` or the person gives a model its tier.

`effort_argv` is an argv **template** rather than a vendor table, so the runner holds no knowledge of
any one CLI and a local model needs no code. When an effort is in force the factory appends the
template, each element with `{effort}` substituted, after `command`. When the model has none the run
says so — `effort_not_applied` on the report and an `effort:` line in `runner run` — rather than
refusing, because a local model may have no such control and the effort is a request, not a gate.

Usage is read the same way — from what the backend prints, never from a table of ours: `claude -p
--output-format json` gives cost and tokens but no remaining quota, `codex exec --json` gives tokens
and its remaining quota only in its local session log, and any other backend is recorded as *not
reported* (`usage` on the report, `GET /usage`; CHG-20261006-01). Those two flags are why `setup`
proposes them: without them neither CLI prints usage. With them the answer is no longer stdout but the
string inside claude's `{"type":"result","result":"…"}` or codex's last `agent_message`, and the
runner unwraps those envelopes to read it; an agent's own JSON that is not exactly that shape is left
alone, and a claude envelope with `is_error: true` is a failed answer.

### `command` is a list, not a string

Deliberate: a string would be re-split by a shell that was never run. `["claude", "-p"]` is two
arguments no matter what is inside them.

### `key_env` holds a name, never a value

Checked against `^[A-Za-z_][A-Za-z0-9_]*$` — which is also what catches somebody pasting the key
itself into the field. `sk-ant-…` fails the pattern, so the **shape** refuses it before a human has
to notice.

---

## 3 · Every refusal `validate` makes on a load, and the one `validate_new` adds

`validate()`'s docstring: *"Every refusal this registry makes on a load, in one place so none of
them is optional."* Below, the `validate_new` row comes first and is the only one that is not made
on a load; the rest are `validate`'s. The `declared_reach` rows run after the transport checks in
the code, not before them.

### Only where a model is created or renamed (`validate_new`)

| Refused | Because |
|---|---|
| a **new** `id` of `none` (any case): setup's Add and Edit, `POST /models` (through `Registry.add`) | `none` is what the settings store for "no default coder model"; a model so named would read as a refusal once chosen as the coder |

An entry already called `none` still loads, because `validate` does not refuse it and refusing it on
load would stop `run` and `serve`. It is named in a warning, and it is never the coder:
`cli.coder_defaults` skips it in the lone-`mid` rule, treats `coder_model` = `none` (any case) as a
No, and refuses an `engineer_build` assignment naming it from the plan or the store. Another node
may still be assigned it.

### Always (`validate`)

| Refused | Because |
|---|---|
| an `id` that is not a plain name | it is a key in config *and* on the wire; something that needs quoting gets quoted differently in two places |
| no `vendor` | which API this speaks is not derivable from the endpoint, and guessing would be inventing one |
| no `name` | — |
| a `transport` outside `cli` / `api` | — |
| a `tier` outside `high` / `mid` / `low` / empty | a label nothing reads, or a typo that classifies nothing |
| an `effort_argv` with no `{effort}` in any element | the effort asked for would never reach the process |
| a `declared_reach` outside `local` / `internal` / `external` / empty | a reach nobody can read |
| a `declared_reach` nearer than the transport shows | a model labelled nearer than it is reads as safe and is not |

### A `cli` model

| Refused | Because |
|---|---|
| no `command` | there is nothing to run |
| **any `endpoint` or `key_env`** | *"a field nothing reads is one somebody will later assume was honoured"* |

(`effort_argv` is read by a `cli` model only.)

### An `api` model

| Refused | Because |
|---|---|
| no `endpoint` | — |
| a scheme other than `http`/`https` | — |
| **a secret in the query string** | query strings land in access logs and proxy logs — the two places nobody thinks to inspect |
| any `command` | it cannot use one |
| **an `effort_argv`** | nothing dispatches an `api` model, so nothing would read it |
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

## 4 · `reach` — computed from the transport; a declaration can only raise it

The one field worth being certain about, and the one an operator must never label *nearer* than it is:

> *"Asking the operator to label this themselves would put the one fact worth being sure about behind
> the one place a mistake is invisible — a model labelled `internal` pointing at a public host is a
> configuration that reads as safe and is not."*

```
declared_reach set                        -> that (never nearer than what follows)
transport == cli                          -> local   (where the process runs, not where its prompt goes)
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

**`cli` means the process runs here, not that the work stays here.** `claude` and `codex` are thin
clients that send the prompt, which carries the work order and the repository's content, to a
vendor. `declared_reach` says so: `runner setup` writes `external` for both, and for any
hand-written entry like them you should too. A declaration can only raise the reach, so it cannot
make a public endpoint read `local`. `ollama` entries stay derived (`local`), which assumes the
daemon is local: `OLLAMA_HOST` pointing at another machine is not detected as a different reach,
though `setup` prints a note (host and port only, never credentials) when it is set to a
non-loopback host. The exception is an Ollama
**cloud** model (a `ollama list` name whose tag ends in `cloud`, such as `qwen3-coder:480b-cloud`):
`ollama run` sends it to ollama.com, so `setup` proposes it as `declared_reach: external` with vendor
`ollama.com`.

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
| `seat_panel` / `survey` | the list is ignored — seats route by seat, and by `seat_models`, see below |
| `runner` | nobody is asked |

A node with nothing here is asked **once**, however it is declared.

### `seat_models` — by review seat

```jsonc
"seat_models": { "conformance": "opus", "defect": ["opus", "codex"] }
```

Or on the command line: `--seat-model SEAT=COMMAND`, repeatable (one command, and it replaces the
seat's list for that run). A model may not appear twice on one seat — the plan, the store, the
console and the factory all refuse it, and the seat panel judges each session by its position, so a
duplicate could not hide a `fail` even if one got through.

**A seat has a list of models (CHG-20261005-02).** Each is its own session and its own journalled ask,
and the seat passes only when **every** one passes: any `fail` is the seat's `fail`; otherwise any
`undecided` makes it `undecided`, which `adjudicate` counts as not passing. The seats' words are then
adjudicated as before — veto, then majority. A seat with no models is one ask on the default backend.
A model that returns no verdict at all is **unreached**: with no `fail` beside it the seat is
unreached and the run stops, as one seat's silence always did; with a `fail` the seat is `fail` and
the unreached model is listed under `unreached` in the adjudication. A resumed run reuses a seat
model's journaled answer only if it was put to the same model — the id and the command it resolves
to; a changed assignment is asked again.

**The contract.** A value is a string (a model id, or a command line, as before) or a list of model
ids. Every id in a list must be one the registry has, and none may repeat; an unknown id is refused
naming it, and so is a list when there is no registry (`--assignment-store none`). A list is never
read as a command. The plan accepts a string or a non-empty list of strings, checked by `cmd_run`
and `serve` against the registry before a run; the store holds ids only; `POST /config/seats` takes
`model_id` as a string or a list of ids.

**The one legacy form** is a flat argv list — `--seat-model SEAT="python3 agent.py"`, or
`session_factory(seat_models={"conformance": ["python3", "agent.py"]})`. `cli.session_factory`
alone reads it, and only when the list's first word is not a registry model id (or there is no
registry). A list that starts with a model id is a list of ids, so `["opus", "missing"]` is refused
rather than run as `opus missing`; and `--seat-model defect=opus` names the model `opus`, not a
program of that name.

A seat may name a **registry model id** or a raw command. The id is resolved **first**, deliberately:
*"a plain string that happens to be a model id meaning 'run this program called claude' would be a
nasty way to find out the two naming schemes had diverged."*

**A model id the registry does not have is an error, not a fallback.** Falling back to the default
would mean a panel of three quietly answered three times by one backend — the exact failure the whole
mechanism exists to prevent.

### Resolution order, most specific first

Per session — a seat with several models runs this once for each, by position:

```
a seat naming a registry model id      (resolved first, so the two naming schemes cannot diverge)
  →  the model a node's mode picked    (registry lookup; raises if the project has no such model)
  →  the seat's raw command
  →  agent_command from runner.yaml
  →  a stub that answers nothing
```

### The coding role's default (CHG-20261005-01)

`engineer_build` is the one coding node that picks a model; `fix_pass` and `engineer_selfverify`
follow it. When nothing is assigned to it — by the plan or by the store — `cli.coder_defaults`
fills it, **after** `store.resolve` so the dispatch record is unchanged. (An assignment of a model
called `none` to `engineer_build` is the one thing it refuses rather than leaves alone.)

```
an assignment from the plan or the store         (untouched)
  →  settings.coder_model                        (must name a registry cli model; an unknown id or an
                                                  api model is an error at run time, not at save
                                                  time — the registry is not known to settings.
                                                  The value "none" is a No from `runner setup`: no
                                                  default coder model, and the two steps below do
                                                  not run — nothing is picked, agent_command or
                                                  the stub builds.
                                                  When agent_command is configured, an id here
                                                  overrides it, and a notice says so, naming where
                                                  the work goes if it leaves the machine)
  →  the registry's only tier "mid" model          (not when agent_command is configured: the rule
                                                  fills the place where the stub would be and never
                                                  displaces the operator's own command, and says so
                                                  in a notice.
                                                  A "mid" api model is skipped, with a notice:
                                                  nothing dispatches an api model; the pick itself
                                                  prints a notice naming the model, and saying so
                                                  when it leaves the machine. A model called "none"
                                                  is not counted)
  →  several "mid" models, no coder_model: a notice naming them, and nothing assigned — no random pick
  →  agent_command                                (the runner.yaml's own command)
  →  the stub
```

The console shows the model that will build under `engineer_build`, `fix_pass` and
`engineer_selfverify`, marked as the coder default rather than an assignment (`GET /config/nodes`,
`by_model[...].nodes[].default`).

`settings.coder_effort` (`low` | `medium` | `high`, default `medium`) is the effort for
`engineer_build` and the nodes that follow it. Other nodes get none.

### `runner setup`

Looks for `claude`, `codex` and `ollama` on the **absolute** entries of `PATH` (`PATHEXT` on
Windows), never in the working directory, and runs exactly one thing: `ollama list`, with a timeout.
It probes no port. It proposes entries — `claude-sonnet-5-5` (`claude -p --model claude-sonnet-5-5 --output-format json`,
tier `mid`, with an `--effort {effort}` template), one `codex` entry (`codex exec --json -`) with the
model left for you, and one `ollama run <model>`
wrapper per listed model. The `claude` and `codex` entries are `declared_reach: external` and the
`propose:` line says their prompts, repository content included, go to Anthropic and OpenAI;
offering one as `coder_model` repeats that in the prompt (`--yes` prints it as a note). The Yes
answer says it takes precedence over a configured `agent_command`; **`--yes` does not set
`coder_model` when `agent_command` is configured in runner.yaml** (it says so, and the off-terminal
hint says what `--yes` will do), and sets it only when there is none. `command[0]`
is the absolute path that was found, so dispatch runs the program `setup` showed. On Windows only
the `PATHEXT` forms are looked for (`claude.cmd`, never npm's extensionless shell shim). Writes only what is accepted: on a terminal each proposal is **Add**ed,
**Edit**ed (id, tier, effort template, reach, which can only be raised; the command stays as
detected; bad input is refused and re-asked) or **Skip**ped; `--yes` accepts all unchanged; off a
terminal without `--yes` nothing is written, and the store is not touched either: the ids already in
it are read through a read-only connection that does not migrate it, so only an accepted write can
change its schema. Entries go to the registry file and the store `serve` reads (`--models`,
`--assignment-store`, `--token-dir`); when the store is empty, everything already in `models.json`
is saved with them so `serve` does not lose it. Once the store has entries, `run` and `serve` read
the registry from it and no longer read `models.json`. The codex entry names no model; choose
**Edit** in `setup` and give a model name — for codex it is appended as `-m <name>`, for claude it
replaces the `--model` value — and the edited entry keeps its `external` reach. It offers to set `coder_model` to an accepted `mid` model. **A No is recorded**: `coder_model` is
saved as `none`, which means no default coder model, so the lone-`mid` rule does not pick the model
just declined (the settings screen shows it as declined; a blank answer there clears it back to the
rule). Only an explicit No is recorded: backing out of the question (an empty line, `q`, EOF, Esc)
writes nothing and exits non-zero. A store that exists but cannot be read is refused before anything
is asked, and `coder_model` is set only after the persisted entry is read back and equals the accepted
one. It assigns nothing to any node. Nothing found: it says so, points here, and exits 0.

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

Counted over every (seat, model) session, so one seat with two models is two voices. Which models
answered which seat is `RunReport.seat_models`, printed as `seat models:`. Recorded in
`RunReport.single_model_panels` and printed. **Independence of sessions is not
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
