# The server's HTTP API

The console's back end. **Eighteen routes** — eight `GET`, ten `POST` — every one crossing a process
boundary to a browser, and until now none of them written down. An independent seat called this the
largest omission in [`SCHEMAS.md`](SCHEMAS.md); this is that entry.

Defined by [`server.py`](../src/ai_sdlc_runner/server.py). That file is authoritative; this is a map,
and [`tests/test_api_schema.py`](../tests/test_api_schema.py) pins it so it cannot rot the way the
schema catalogue did within a day of being written.

---

## 0 · Before any route: what every request must satisfy

`_guard()` runs first, on every request, and refuses in this order:

| # | Check | Refusal |
|---|---|---|
| 1 | `Host` is loopback | `403 {"error": "this server answers only to a loopback host"}` |
| 2 | `Origin`, if present, round-trips to loopback | `403 {"error": "cross-origin request from <origin> refused"}` |
| 3 | `X-Operator-Token` matches | `401 {"error": "no operator token. It is in <path>, readable by you alone."}` |

**Order matters and is deliberate.** A non-loopback `Host` on a loopback socket is DNS rebinding, and
that request should not get as far as being *understood* — so it is refused before anything is
parsed.

### The two token exemptions, both deliberate

- **`GET /` and `/index.html`** — the shell page is served **without a token**, because nothing can
  present a token before it has loaded the page that stores one. It is still `Host`-checked.
- **`GET /run/events`** — accepts the token as a **query parameter** `?token=…`, because
  `EventSource` has no API for setting headers. A query string reaches access logs, which is why it
  is this one route and not a general fallback: the stream is read-only and the token is
  per-process.

The token reaches the page in the URL **fragment**, which browsers never send to a server and never
put in a `Referer`.

---

## 1 · GET routes

### `GET /` · `GET /index.html`
The console page. `text/html`. **No token required** — see above.

### `GET /flow`
The whole graph, so the console can draw it without embedding a copy.

```jsonc
{ "nodes": [ { "id": …, "kind": …, "label": …, "role": …, "gate": …, "gate_when": …,
               "mode": …, "main": …, "follows": …, "rejects_to": …,
               "branches": { "<label>": "<node id>" }, "next": …,
               "permanent": … } ],                                      // all 28
  "gates": { "<gate>": { "<risk>": "<verdict>" } },                     // all 10
  "modes": [ "runner", "single", "seat_panel", … ] }                    // all 7
```

Thirteen of `Node`'s eighteen fields. `answer_decides`, `note`, `grades_risk`, `settles_risk` and `panel_branches` are **not** sent.

`permanent` (CHG-20260827-22) **is** sent, and the distinction is the one this section keeps making. It says a terminal node is a *give-up* rather than an ending — `halt_second_fail` and `halt_unreconciled` against `done`. Drawing those three the same way is the confusion the field was added to end, and drawing is exactly what the console is for. A field it cannot act on is withheld; this is one it must act on.

`grades_risk` and `settles_risk` (CHG-20260827-17) say which node's voices answer with a **risk grade** and which node's sign-off makes that grade the run's. They are withheld for the same reason as `answer_decides`: the console draws the flow and does not adjudicate it, and a field it cannot act on is a field it should not be handed.

`panel_branches` (CHG-20260901-11) is withheld for that same reason, and it is the sharpest case of it. It translates a panel's `pass`/`fail` into the branch words a node offers — `pm_confirm` says `yes` and `no` — so it exists only for adjudication, which is the one thing the console does not do. What the console draws is `branches`, which it already has.

### `GET /run`
The run snapshot — [§3](#3--the-run-snapshot).

### `GET /run/events`
`text/event-stream`. **The current snapshot is pushed first**, so a stream and a poll never disagree
about what the client is looking at; then one `data:` frame per state change, each frame the same
snapshot shape.

```
Content-Type: text/event-stream
Cache-Control: no-store
Connection: close

data: {…snapshot…}

data: {…snapshot…}
```

### `GET /models`
The registry, plus the one question a registry cannot answer for itself.

```jsonc
{ "models": [ { "id", "vendor", "name", "transport", "command", "endpoint", "key_env", "note",
                "reach", "leaves_this_machine" } ],
  "leaving": [ "<model id>", … ] }
```

**`reach` and `leaves_this_machine` appear here and are never persisted** — they are computed on
every read from `(transport, endpoint)`. `leaving` is the same fact stated at the top level, because
*"what goes out from here"* should not require a reader to scan a list and notice a hostname.

### `GET /attachments`
```jsonc
{ "attachments": [ { "id", "filename", "media_type", "size", "instruction" } ],
  "missing": [ "<id>", … ] }        // handed over, and the store has since lost
```

`id` is the **full 64-character digest**. The stored filename is `id[:32]` and is never sent.

### `GET /config/nodes`
Where each model is actually **used** — a model listed and used nowhere looks configured, and a model
on eight nodes looks the same in a list as one on a single node.

```jsonc
{ "node_models": { "<node id>": ["<model id>", …] },
  "seat_models": { "<seat>": "<model id or joined command line>" },
  "by_model": { "<model id or command>": { "nodes": [ {"node_id", "mode"} ],
                                           "seats": [ "<seat>", … ],
                                           "known": true } },
  "models": [ …as in GET /models, without `leaving`… ],
  "source": { "node_models.<node id>": "plan" | "store", "seat_models.<seat>": … },
  "assignable": [ "single", "model_panel", "pool" ] }
```

**`source` says which of two places put each assignment there.** An assignment can come from the
plan file (this change's declaration) or from the store (the project's standing one), and **the plan
wins**. A console showing the merged result with no provenance could not say that it had — and an
override nobody can see is worse than no override.

**`assignable` is the three modes that do anything with a list.** The other four ignore it, so the
console can grey them out rather than let somebody configure a node that will not read it.

`known: false` marks a model a plan names and the registry does not have. Every registry model
appears in `by_model` even with empty `nodes` and `seats` — that is how "configured but unused"
becomes visible.

### `GET /whoami`
```jsonc
{ "operator": "<name>" }
```

**One identity, and it is why `halt_independent` cannot enforce independence** — there is no second
identity to compare against. See *Known gaps* in the README.

### Anything else
`404 {"error": "no route <path>"}`

---

## 2 · POST routes

**Every POST body must carry `"version": <int>`.** Not optional and not defaulted:

```jsonc
409 { "error": "every answer must name the version it is answering — without it two tabs cannot be
                told apart, and a double-click spends two approvals" }
```

If the version does not match the run's current one:

```jsonc
409 { "error": "this run is at version N and you answered version M. Something moved — another tab,
                or a click that already landed. Reload and look at what it is actually waiting for
                before answering again." }
```

**Every POST except `/models` returns the run snapshot** ([§3](#3--the-run-snapshot)) with `200`.

| Route | Body | Refuses when |
|---|---|---|
| `POST /run` | `{version, instruction?}` | a run is already `running` or `suspended` — *"one project, one runner, one run at a time"* |
| `POST /run/gate` | `{version, gate, node_id?}` | the run is not suspended, or is suspended on a **tie** rather than a gate |
| `POST /run/reject` | `{version, gate, node_id?, reason?}` | as above, or the node has no `rejects_to` |
| `POST /run/decide` | `{version, node_id, branch}` | the run is not suspended, or is suspended on a **gate** rather than a tie |
| `POST /config/nodes` | `{version, node_id, models: [...]}` | no such node; a node whose **mode ignores** a model list; a model the registry does not have; `models` not a list |
| `POST /config/seats` | `{version, seat, model_id}` | no such seat; a model the registry does not have |
| `POST /config/halts` | `{version, kind, recipient?}` | a `kind` that is not one of the six permanent halts. A `recipient` is **never** refused — an organisation names its own functions, and an unrecognised one still reaches somebody because the operator is on every halt. A blank or missing `recipient` clears the route |
| `POST /run/instruct` | `{version, instruction}` | the instruction is empty — *"an empty instruction says nothing"* |
| `POST /attachments` | `{version, filename, data}` — `data` is **base64** | the base64 is invalid, or `attachments.py` refuses the type or size |
| `POST /models` | `{version, model: {…8 fields…}}` | `_model_from` refuses an unknown field, or `validate` refuses the model |

### Gate and tie are not interchangeable

```jsonc
409 { "error": "this run is waiting for a tie to break, and that is not what you sent." }
```

A gate asks *whether the run may proceed*; a tie asks *which way*. Accepting one for the other would
record an answer to a question nobody was asked — so `/run/gate` and `/run/decide` each check
`suspended.undecided` and refuse the other's case.

### The two assignment routes return the resolved assignment

```jsonc
{ "node_models": { … }, "seat_models": { … }, "source": { … } }
```

Not a run snapshot — they change configuration, not the run. **An empty `models` list clears a
node**; there is no `DELETE` verb and adding one for a single case would be a second way to say a
thing that already has one.

**Clearing a node the plan speaks for changes nothing visible.** The store row goes and the plan's
assignment still stands, with `source` still saying `"plan"`. That is the precedence working, and it
is shown rather than left to surprise somebody.

### `POST /models` returns the registry, not a snapshot

```jsonc
{ "models": [ … ], "leaving": [ … ] }      // same shape as GET /models
```

It also **writes `models.json`** when the server was given a registry path.

---

## 3 · The run snapshot

Returned by `GET /run`, by every SSE frame, and by every POST except `/models`. One shape, so a
caller never has to know which of the three it is holding.

```jsonc
{
  "state": "idle" | "running" | "suspended" | "finished" | "stopped",
  "version": 7,                     // bumped on EVERY state change; answers must match it
  "instructions": [ "…", … ],       // in the order they were given
  "attachments": [ {…manifest…} ],
  "attachments_missing": [ "<id>" ],
  "error": "" | "…",          // never null: `RunState.error` is `str = ""`,
                              // and `snapshot()` returns it verbatim (CHG-20260903-37)

  "at": "<node id>" | null,         // where it stopped
  "reason": "…",                    // why, in words
  "visited": [ "<node id>", … ],
  "suspended": null | { …§4… },

  "confirmations": [ "…" ],         // gates approved, as recorded sentences
  "rulings":       [ "…" ],         // ties a person broke
  "rejections":    [ "…" ],         // gates refused, and where the run went
  "survey":        null | { "problems": {"<seat>": […]}, "missing": […],
                            "safety": {"<seat>": […]}, "complete": false },
  "intake_asks_by_aspect": {},      // per aspect, how many times it has been asked for
                                    // — counted after this stop was recorded, so it matches
                                    // the sentence `reason` carries (CHG-20260904-03)
  "send_backs":    [ {…} ],
  "dispatches":    [ "…" ],         // which model a pool chose, and which a follows reused
  "adjudications": [ {…} ],         // every panel decision, with the seats' verdicts
  "adjudication_here": {…} | null,  // the one belonging to the stop, or null when the node
                                    // being decided has no panel. NOT `adjudications[-1]`,
                                    // which is whichever happened last: at `merge` on a
                                    // default install that is `lead_review`'s verdict on
                                    // built work (CHG-20260904-11)

  "log": [ { "node_id", "role", "seat", "model" } ]   // one per ask
}
```

**`state` has five values here, not three.** `engine.RunReport.state` has three — `finished`,
`suspended`, `stopped`. The server adds `idle` (nothing has run) and `running` (a walk is in
progress), which are states of the *server*, not of a report.

**`log` carries `model` and not the answer.** The answer is in the conversation store; this is the
console's list of who was asked.

---

## 4 · The suspension

`null` unless `state == "suspended"`. **All 15 keys are on every suspension** — a gate has no
branches to choose between and a tie has no gate to confirm, and each says so rather than omitting
the field, because *a missing key and a false one read the same way only until they do not*. Five of
them are **meaningful** for exactly one of the three questions, and one — `reason` — for **two**;
the rest carry their empty value otherwise, and the two booleans below say which question this is.

`reason` was documented as tie-only until CHG-20260904-13. It is also what an incomplete stop
carries — the sentence naming the aspect and how many times it has been asked, which is the only
ask text the console renders, and the field CHG-20260904-07 moved earlier in the walk so that
the shape could carry it. `-10`'s guards check the count and the phrase; neither asks **which
question** a field is meaningful for.

That sentence has been false in both directions. The page said *"every kind of suspension carries
the same keys"* until CHG-20260901-16 found the engine building three literals of 9, 11 and 13 keys
— so it was corrected to name nine as universal and six as conditional, which described the data.
CHG-20260904-07 then routed all three shapes through `engine._suspension`, which fills every field
from `SUSPENSION_FIELDS`, and the original sentence became true while the corrected one became
false. It stayed false for a day, because the guard that shipped with `-07` asks only whether each
field is **named** on this page, not what the page says about it (CHG-20260904-10, defect seat
L-36).

```jsonc
{ "node_id":    "<node id>",
  "undecided":  false,      // true = a tie, answer with POST /run/decide
  "incomplete": false,      // true = the requirement is incomplete, answer with POST /run/instruct
  "gate":       "<gate>" | null,
  "gate_when":  "before" | "after",
  "verdict":    "halt" | "confirm" | "halt_independent" | …,
  "risk":       "low" | "medium" | "high",
  "branches":   [ "<branch>", … ],     // empty for a gate; the choices for a tie
  "run_id":     "<absolute journal path>" | null,

  // meaningful when `incomplete` — the intake survey. Present either way: `[]`, `{}`, `[]`, `{}`
  "missing":    [ "<aspect>", … ],
  "options":    { "<aspect>": [ …≥3… ] },
  "problems":   [ "<problem>", … ],    // what the seats found wrong with the requirement
  "safety":     { "<seat>": [ … ] },   // what they found that is a safety question.
                                       // Keyed by SEAT, not aspect: `intake.collect`
                                       // writes `survey.safety[seat] = unsafe`, and a
                                       // caller keying by aspect matched nothing, ever
                                       // (CHG-20260903-37)

  // meaningful on TWO of the three: the tie, and the incomplete requirement — where it carries
  // the sentence naming the aspect and how many times it has been asked, and is the only ask
  // text the console renders. Empty at a gate.
  "reason":     "<why this is being asked>",

  // meaningful when `undecided` — the tie. Present either way: `{}`
  "verdicts":   { "<voice>": "<verdict>", … } }   // who said what, so a tie can be read
```

Three questions, told apart by two booleans:

| `undecided` | `incomplete` | The run is waiting for | Answer with |
|---|---|---|---|
| `false` | `false` | a gate to be approved or refused | `POST /run/gate` · `POST /run/reject` |
| `true` | `false` | a tie to be broken | `POST /run/decide` |
| `false` | `true` | a requirement that is not complete | `POST /run/instruct` |

---

## 5 · Status codes

| Code | Means |
|---|---|
| `200` | done — body as above |
| `401` | no operator token, or the wrong one |
| `403` | non-loopback `Host`, or cross-origin `Origin` |
| `404` | no such route |
| `409` | **the request was understood and refused** — wrong version, wrong kind of answer, nothing waiting, a model the registry will not accept |
| `500` | `{"error": "<ExceptionType>: <message>"}` |

**`409` is the interesting one.** It is not a conflict in the REST sense — it is this server saying
*"I understood you and I am not doing that"*, and the message says why in a sentence.

**`500` always answers.** Without it the handler thread dies, the socket closes, and the client sees
`RemoteDisconnected` — a failure with no message, which sends whoever is debugging it to the network
rather than to the traceback. Found live: a missing store directory took down the request instead of
reporting itself.

---

## What this API does *not* have

Stated rather than left to be discovered:

- **No versioning.** No `Accept` negotiation, no `/v1/` prefix, no version field on any response
  shape. The `version` integer in a body is the **run's** version, not the API's. Every other durable
  shape in this project has the same gap; only the conversation document carries a schema number.
- **No pagination or filtering.** `GET /run` returns the whole snapshot including the entire log,
  and `/config/nodes` returns every model. Fine for one operator and one run; stated because
  "it scales" is not being claimed.
- **No `DELETE`, no `PUT`.** A model can be added and never removed through the API — `Registry`
  has `remove` and nothing routes to it. Assignments *can* be cleared, by posting an empty list.
- **No CSRF token beyond the operator token**, which is what the `Origin` check and the
  header-not-cookie design are for.
- **One operator.** `GET /whoami` returns a single name, and that is why `halt_independent` is in
  *Known gaps* rather than in the enforced list.
