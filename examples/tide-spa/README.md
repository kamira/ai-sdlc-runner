# The tide-table example

One brief, built five times. Each run changes **exactly one field** in the plan, and the point of
the example is where each run stops — and what it says about why.

The product is real: a single-page tide table, four modules, no build step and no dependencies.
The runner dispatches a model per node; the model writes one module per `engineer_build` visit, and
the flow comes back to that node until the module list is exhausted.

```bash
python3 examples/tide-spa/scenarios.py
```

It writes nothing into the repository. Every scenario gets its own temporary directory with its own
copy of the agent, its own ask journal, and its own conversation store. Pass a directory to keep
them:

```bash
python3 examples/tide-spa/scenarios.py /tmp/tide-runs
```

## What is here

| file | what it is |
|---|---|
| `plan.json` | the plan that walks the whole flow — 15 node specs, the operations, the branch decisions |
| `agent.py` | the model the runner dispatches to. One process per ask: work order on stdin, JSON on stdout. Not a stub — the files it writes are the files the browser loads |
| `runner.yaml` | two lines: the agent command and a timeout |
| `scenarios.py` | the driver. Each scenario is `plan.json` plus one named mutation |

The four variants are **derived in the driver**, not stored as four copies of an 14 KB plan. A copy
would show you five nearly identical files and leave you to diff them; a named mutation function
shows you the one field that matters, next to the reason it matters.

## The five runs, measured

| | one changed field | exit | asks spent | files built | stopped |
|---|---|---|---|---|---|
| **A** | — | 0 | 25 | 4 | at `merge`, waiting for a person |
| **B** | `operations.engineer_build.kind` → `deploy` | 0 | 7 | 0 | permanent halt at `engineer_build` |
| **C** | `scope`/`objective`/`expected_outputs` → `""` | 2 | 0 | 0 | refused at the door |
| **D** | `operations` → `operationz` | 2 | 0 | 0 | refused at the door |
| **E** | `ship.acc_id` with no `task` | 2 | 0 | 0 | refused at the door |

Read the *asks spent* column alongside the *exit* column. That is the whole argument for refusing at
load time: **C**, **D** and **E** are malformed plans and cost nothing to find out. **B** is a
well-formed plan that describes work no grade of risk permits, so it is found where the work would
happen — but only after seven asks were spent getting there.

**C used to be the exception**, and the row above is what changed. It ran the whole flow on a spec
that said nothing — 25 asks, four files, exit 0 — until CHG-20260823-34.

---

## A · the flow as written

Walks all 24 nodes. `pm_plan` returns a module list; `engineer_build` is visited four times, once
per module, each visit followed by a self-verify and a task review; three review seats answer at
`intake_review` and three more at `lead_review`; QA verifies and accepts.

It stops at `merge`, and the last line is not an error:

```
continue with: --resume --confirm merge
```

`merge` is one of the six kinds never automated. The run did everything up to it and then handed
over, which is the intended ending, not a failure.

One warning worth reading, printed at the top:

```
single model: intake_review: every seat was answered by the same backend (python3 agent.py).
The sessions were independent; the model was not, so the seats share whatever it cannot see.
Use --seat-model SEAT=COMMAND to make the review cross-model.
```

Three seats answering independently is a cross-check only if the thing answering differs. Same
model three times is one opinion asked three times, and the runner says so rather than letting the
seat count imply a rigour it does not have.

## B · a deploy inside the build

```json
"engineer_build": [{
  "description": "push the site to production",
  "kind": "deploy",
  "targets": ["https://tides.example.com"]
}]
```

```
visited:    8 node(s)
asks:       7
stopped at: engineer_build — permanent halt at 'engineer_build': 'push the site to
            production' is production deploy or release. No risk grade, confirmation
            or mode relaxes this — a person does it.
state:      stopped
```

Note what is **not** offered. Every other halt in this runner comes with a way to continue —
`--confirm <gate>`, a risk grade, a mode. This one does not, and the message says why in the same
breath as the refusal. A halt that can be argued out of is a speed bump; this is the list of six
things the runner will not do regardless of how the plan is written.

This is also the realistic shape of the mistake. Nobody writes a plan whose every operation is a
deploy. Somebody writes an ordinary build plan and puts one deploy in the middle of it.

## C · a spec with nothing in it

`scope`, `objective` and `expected_outputs` set to `""` on the build nodes. The fields are
**present**, so the closed schema accepts the shape.

Zero asks, exit 2:

```
error: plan.json: node spec 'engineer_build' leaves ['scope', 'objective'] blank. The field is
present and says nothing — which reads as configured and constrains nothing, the same silent pass
as a missing key one level down; the old check tested that the key existed, not that the value
said anything. Write the constraint: a node genuinely unconstrained must say so in words, because
'any file in the repository' is a scope and '' is not. ['input_artifacts', 'expected_outputs',
'idempotence_probes'] may be empty; these may not.
```

Two things in that message are worth reading closely.

**It names `scope` and `objective` and not `expected_outputs`** — although the mutation blanked all
three. `expected_outputs` is `[]` on 14 of the 15 nodes in [`examples/minimal/plan.json`](../minimal/plan.json),
because a review node genuinely produces nothing. A rule that refused every blank would refuse this
repository's own example, which is the same coarse check inverted. Both review seats reached that
exclusion independently.

**It names the boundary out loud.** A refusal that only scolds invites the reader to pad
`idempotence_probes` with a fake probe to be safe — manufacturing the defect the rule exists to
stop.

### How this one was found

By **running** the example, not by reading the code. `workorder._check` tested
`[f for f in required if f not in supplied]` — the presence of the *key*. A key whose value was
`""` passed, and `render()` copied the blank into the order it dispatched. This project's dominant
defect class — a name standing in for a constraint — sitting in the work-order builder itself.

It is checked at both ends now: at load, so it costs no asks, and at render, which is the choke
point every dispatch passes through including callers that never open a plan file. `instructions` is
the one field checked at render only — the engine may legitimately fill it in from `--instruction`
between the two.

## D · operations, misspelled

`operationz`. Zero asks, exit 2:

```
error: plan.json sets ['operationz'], which this runner does not read. Ignoring them would
let a setting look configured and do nothing — and the case that decides it is `ship`: a
misspelt one makes a run perform no side effects and report `finished`. This runner reads
['risk', 'autonomy', 'node_specs', 'operations', 'decisions', 'node_models', 'seat_models',
 'ship'].
```

A schema that ignored the unknown key would have run the whole flow with **no declared operations at
all** and reported success — the silent dry run, which this project has shipped twice and caught
twice. The message names what was rejected, gives the case that settles the argument, and lists
what is actually read, so the fix is a one-line edit rather than a search.

## E · an acceptance with no task

`ship.acc_id` and `ship.acc_body` with no `task`. Zero asks, exit 2. The acceptance effect only
runs when a task is named, so those two fields would be read by nobody: the ledger would take the
record and nothing would ever close it. Refused at the door for the same reason as D — a field that
looks configured and does nothing.

---

## Seeing the conversation afterwards

Every run stores its conversation. Point the export at the store the driver made:

```bash
python3 -m ai_sdlc_runner.cli conversations --store-root <workdir>/conv --project "Porthcurno Tide SPA"
```

```bash
python3 -m ai_sdlc_runner.cli export --store-root <workdir>/conv --project "Porthcurno Tide SPA" --conversation <id> --format html -o talk.html
```

`--format html` renders the run as a waterfall down time whose stops are the flow's nodes: scenario
A comes out as 24 stops for 55 turns, with `engineer_build` marked `visit 2`, `visit 3`, `visit 4`
where the module loop came back to it. The three voices are told apart — what the runner asked, what
the model answered, what a person decided — and each card opens to the raw record it was rendered
from. `json` is the lossless format; `markdown` reads as a transcript; `csv` is the lossy one.
