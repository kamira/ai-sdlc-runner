# ai-sdlc-runner

A governed development agent. It drives an ordinary development flow — the seats read the
requirement, PM plans, the lead judges feasibility, engineers build one small module each, the lead
reviews, a panel cross-checks, QA verifies, and the user's feedback returns to PM — and it decides,
at every step, whether that step may proceed on its own or has to **stop and ask a person**.

It depends on no other company's agent, and it holds no skill, prompt pack, or vendored contract.
The flow and the governance are this repository's own, in two files anyone can read:

| File | What it holds |
| --- | --- |
| [`policy.py`](src/ai_sdlc_runner/policy.py) | the governance: roles and their capabilities, ten gates × three risk grades, the never-automated actions, the review seats and how their verdicts are adjudicated |
| [`graph.py`](src/ai_sdlc_runner/graph.py) | the flow: 24 nodes, one kind of work each, with the module loop, the bounded retry, and the feedback edge back to PM |

Everything else serves those two: [`engine.py`](src/ai_sdlc_runner/engine.py) walks the flow and
enforces the policy, [`workorder.py`](src/ai_sdlc_runner/workorder.py) renders the closed-schema
order each ask is given, [`server.py`](src/ai_sdlc_runner/server.py) and
[`console/`](src/ai_sdlc_runner/console/) put an operator in front of it, and
[`cli.py`](src/ai_sdlc_runner/cli.py) connects them to real models.

---

## The idea in one paragraph

Most agent frameworks make a plan and then execute it. This one **asks a different question at every
node**: given what this step is, and how risky this change is, may it happen without a person? The
answer comes from a table you can read, not from a model's judgement — and when the answer is no, the
run **stops and returns**, rather than waiting, retrying, or deciding on your behalf.

---

## Install

```bash
pip install -e ".[test]"
```

Standard library only. PyYAML is optional — `runner.yaml` is read by a small built-in parser when it
is absent.

`runner.yaml` says what to dispatch to:

```yaml
agent_command: ["claude", "-p"]   # one process per ask; the work order arrives on stdin
agent_timeout: 600
agent_retries: 0                  # retries are for a backend that FAILED TO ANSWER, never for an
                                  # answer somebody dislikes — see policy on retries below
```

---

## The flow

24 nodes. Each does **one kind of work**, which is what decides where the boundaries fall: building,
verifying your own work, and having it reviewed are three kinds of work, so they are three nodes.

```
intake  →  intake_review        the seats read the requirement — before anything is planned
             │
             ↓
           pm_plan  →  pm_confirm ◆plan_confirmed
                          ├─ yes → lead_assess ◆feasibility_confirmed
                          │           └─→ pm_signoff ◆before_dispatch
                          │                  ├─ yes → next_module
                          │                  └─ no  ──────────────┐
                          └─ no ─────────────────────────────────┤
                                                        (back to pm_plan)

next_module ─┬─ module → engineer_build            one engineer, one small module
             │             └─→ engineer_selfverify ◆self_verify  its own work, never the last word
             │                    └─→ lead_task_review ◆task_review
             │                           ├─ pass → record_module ──→ next_module
             │                           └─ fail → fix_pass → re_review
             │                                                  ├─ pass → record_module
             │                                                  └─ fail → halt_second_fail  ■
             │                                       (bounded: exactly one fix pass)
             │
             └─ none → lead_review ◆lead_review     the seats cross-check the whole change
                          ├─ fail → review_failed ──────→ next_module
                          └─ pass → qa_verify ◆qa_verify        run it for real
                                      └─→ qa_accept ◆acceptance
                                             ├─ fail → acceptance_failed ─→ next_module
                                             └─ pass → pr ◆pr
                                                        └─→ merge ◆merge   the one-way door
                                                              └─→ close_out → feedback
                                                                               ├─ more → pm_plan
                                                                               └─ done → done ■
```

`◆` marks a gate; `■` marks a terminal. The three failure paths — `halt_second_fail`,
`review_failed`, `acceptance_failed` — are drawn because they are the ones an operator most needs to
see, and because leaving them out is exactly the defect a review seat found in this project's own
mock-up.

Three shapes carry most of the meaning and are explicit rather than flattened:

- **the per-module loop** — one engineer per small module, and the loop *is* the resume mechanism: an
  already-recorded module is simply not the frontier;
- **the bounded retry** — one fix pass, one re-review, and a second failure halts. Not
  repeat-until-green;
- **the feedback loop** — user feedback returns to PM, so the flow closes rather than ends.

```bash
runner flow      # print all 24 nodes, their roles, gates and branches
```

---

## The governance

### Gates: risk decides where it stops

Ten gates, three risk grades. The rule behind every grade is one sentence: **a gate stops when
getting it wrong is expensive to undo.**

| Risk | Stops at | Where |
|---|---|---|
| `low` | 1 | `merge` |
| `medium` | 4 | `pm_confirm`, `lead_assess`, `pm_signoff`, `merge` |
| `high` | 8 | the above plus `lead_review`, `qa_verify`, `acceptance`, `pr` |

Merging is a one-way door, so it stops earliest of anything — **including at low risk**, where it
asks rather than halts. "Low risk" grades the change, not the door.

Acceptance on a high-risk change is graded `halt_independent`. **That grade always stops for a
person; it does not currently enforce that the person differs from the builder.** `STOPPING` treats
it exactly like `halt`, the server has a single operator identity, and nothing records or checks who
confirmed. The name states an intent the code does not yet keep — found by an independent seat, and
named here rather than left for a reader to assume. See *Known gaps*.

```bash
runner policy    # print every gate at every grade, the seats, the never-automated actions
```

### Six things that are never automated

No risk grade and no configuration relaxes these. Declared by **kind**, and also derived from what a
node's targets actually say, so a plan that names `kubectl apply -f prod/` has declared a production
deploy whatever word it put in `kind`:

`deploy` · `migration` · `delete` · `money` · `access` · `publish`

A command whose name constrains nothing — `python`, `sh`, `rm`, `curl`, `xargs` — can never be
vouched for as ordinary, because the name says nothing about what it will do.

### Review seats

Four seats, each answering a **different question**. The floor is three; going below it needs an
explicit high-risk-mode bypass, which is recorded.

| Seat | Asks | |
|---|---|---|
| `conformance` | Is this the thing the task asked for — line by line? | **veto** |
| `defect` | Where is this wrong? Concrete inputs and the wrong result. | |
| `risk` | What does this make hard to undo? | |
| `idiom` | Does this read like the code around it? Is any of it unnecessary? | |

Adjudication is **veto → majority → a tie decides nothing**. The veto seat's subject is a matter of
fact, and counting votes on a fact is how a panel talks itself out of one.

A tie is `undecided` — **not** a failure. A failure sends work back, which is a judgement an even
split did not make. An undecided panel suspends for a person, and the person's choice is recorded as
*theirs*: the panel is never credited with a verdict it did not reach.

---

## How several models are used

A node may have several models configured, and that means **two entirely different things** depending
on the node. The difference is declared in `graph.Node.mode`, never inferred from a node's name:

| mode | Several models means | Sessions |
|---|---|---|
| `runner` | nobody is asked; the runner does it | — |
| `single` | exactly one model | 1 |
| `model_panel` | N voices on **one question**, adjudicated | N |
| `pool` | a pool the main dispatches to; **one** does the work | 1 |
| `follows` | whichever model answered the node it names | 1 |
| `seat_panel` | the review seats — independence is not configurable | one per seat |
| `survey` | every seat asked, **all** answers kept, nothing adjudicated | one per seat |

Same three ids in `node_models`; entirely different runs. A pool's choice is **random on purpose** —
any cleverer rule is the runner deciding which model is better at a task it has not seen — and
**deterministic**, seeded by `dispatch_seed`, the node id, and which ask this is. The default seed is
`0` and the CLI does not set it, so the same plan dispatches the same way every time; inserting an
earlier ask shifts the ordinal and can change later dispatches. Every dispatch is recorded, which is
what actually makes "which model built this" answerable.

**One ask, one session.** Every asking node gets its own session, opened and closed around a single
ask. A multi-seat review is several asks, so each seat is its own session — otherwise "three seats"
is one model answering three times in one context, which is the anchoring the seats were bought to
avoid.

---

## Requirements come in through the seats

A requirement no longer goes straight to planning. `intake_review` asks every seat what is wrong with
it and what is **missing**, across six aspects:

**flow · architecture · requirements · inputs · outputs · UI**

This is the one place several voices are **collected rather than adjudicated**, and the reason is
worth stating because every other multi-voice node works the other way:

> Adjudication answers *"may this proceed?"* — one question, one answer, and counting is how you get
> it. Intake answers *"what is wrong with this?"* — as many answers as there are things wrong, where
> counting **destroys** the information.

Missing an aspect is not "bad", it is **incomplete**: the run stops before anything is planned and
says exactly what it does not have. Asking again is right; asking forever is not — once an aspect has
gone unanswered **three** times, the next pass puts **at least three options** on the table, authored
by a model and recorded as an ask. It does not pick one.

Precisely: `needs_options` becomes true when three misses are already on record, so the options
appear on the *fourth* survey rather than instead of the third. The seats are asked again on that
pass too.

---

## Running it

### From the command line

```bash
runner --config runner.yaml run --plan plan.json --risk medium --ask-journal .runner/asks
```

`--config` is a **global** flag and must come before the subcommand. It is where `agent_command`
lives — the program each ask is dispatched to. Without it every ask goes to a stub that answers
nothing, and the run completes while having asked nobody.

A halted run tells you what stopped it. Answer it and resume:

```bash
runner --config runner.yaml run --plan plan.json --resume \
       --ask-journal .runner/asks --confirm plan_confirmed
```

Useful flags:

| Flag | |
|---|---|
| `--confirm GATE` | a gate you have already approved; repeatable |
| `--rule NODE=BRANCH` | break a tie a panel could not decide |
| `--review-seats N` / `--seat-model SEAT=CMD` | how many seats, and which backend answers each |
| `--undeclared refuse\|allow` | what to do with a working node that declares no operations |
| `--risk low\|medium\|high` | override the plan's grade |
| `--project NAME` | store this conversation under that project. No default — see below |

### Every conversation is kept, and can be exported

Add `--project NAME` to `run` or `serve` and every turn is written down **as it happens**: each work
order and the model that answered it, each answer, each ask that failed, every instruction with the
number it arrived as, and **every operator decision** — approval, refusal, tie-break — with the
relaxations the run was granted and the state it ended in.

```bash
runner --config runner.yaml run --plan plan.json --project "Login page" --ask-journal .runner/asks
runner conversations --project "Login page"
runner export --project "Login page" --conversation <id> --format markdown -o talk.md
```

| Flag | |
|---|---|
| `--store file\|tinydb\|mongo` | which document store (default `file`). A missing package **refuses by name** and never falls back |
| `--store-root DIR` | where `file` and `tinydb` live (default `.runner/conversations`) |
| `--store-uri URI` | the mongo URI — loopback only unless relaxed |
| `--store-remote refuse\|allow` | `allow` sends conversations off this machine, and records that it did |
| `--format json\|markdown\|csv` | on `export`. Required, because only `json` is lossless and a default would choose what you lose |

A store write that fails **never fails the run**, and is never silent: a line on stderr the moment
it fails, and `store_errors` on the report at the end. No attempt is made to write that note *into*
the store — the thing that would hold it is the thing that just failed.

**It is not derived from the ask journal**, and that distinction is the whole design. The journal
answers *"what is the current question at position N"* — a resume index, keyed by position, which
`record` overwrites; two runs in one journal directory leave one entry. The store answers *"what
happened, in order"*, append-only, and a crashed run keeps everything up to the crash. The journal
has also never held an operator turn, so a store derived from it would contain only the model's half
of a conversation.

Both review seats returned **`not sound`** on the first design, which proposed exactly that
derivation, and on four other points: the Mongo host check, the `(project, run)` key, CSV formula
injection, and where a relaxation is recorded. Their verdicts are committed whole in
[`docs/design/reviews/`](docs/design/reviews/) and the design that answers them is
[`docs/design/conversation-store.md`](docs/design/conversation-store.md).

**On a Mongo store, a loopback host is not the check.** `MongoClient` performs topology discovery:
given a loopback seed that turns out to be a replica-set member or a `mongos`, it reads the topology
*from the server* and connects to every member it learns of. So the URI must be `mongodb://` (not
`+srv`), single-host, a host that **round-trips** to loopback or a unix socket, and carrying only
options on an **allowlist** — and `directConnection=true` is **forced on the client**, which is the
one of the five that constrains the driver rather than the string.

The allowlist is there because the first version named the two dangerous options instead, and a seat
got past it twice: `?proxyHost=…&proxyPort=…` keeps the seed loopback and routes the connection
through somebody else's SOCKS proxy, and `?replicaset=` walked past a check spelled `replicaSet`. A
tunnel to a remote mongod remains out of scope — no URI can reveal one.

The store holds every work order verbatim and is **exactly as sensitive as the ask journal already
sitting beside it**, and no better protected: the `file` backend is created `0700` best-effort,
which does little on Windows, and a local `mongod` typically has no auth at all.

`csv` is the lossy export and says so structurally rather than in a note row — CSV has no comments.
Nested values are JSON text in `*_json` columns, every cell is defused against spreadsheet formula
execution (`=HYPERLINK(…)` in model-produced text is an exfiltration channel), and
`over_spreadsheet_cell_limit` flags the rows a spreadsheet will silently truncate at 32,767
characters.

### With the console

```bash
runner --config runner.yaml serve --plan plan.json --port 8765
```

```
journal        .runner/asks — the run's identity, and what a resume reads
attachments    .runner/attachments — content-addressed; the filename never becomes a path
listening on   http://127.0.0.1:8765 — this machine only, no external connections
open           http://127.0.0.1:8765/#token=…
models         3 registered, 0 of which leave this machine
```

The screen is four things: an **instruction box** (with attachments), **where the run is**, **the
whole flow as a diagram** with the current node highlighted, and **the log** — every ask, who was
asked, which model answered, and what it said.

A run in progress can be added to: type more and press *add to the brief*, or attach a spec. Every
work order from then on carries all of it, numbered, so a reviewer can see that something **arrived
late** rather than being handed a brief that looks as though it was always complete.

**Local only, and it means three things** — because binding to loopback stops the network but not a
browser:

1. a non-loopback `Host` is refused (DNS rebinding);
2. a cross-origin `Origin` is refused;
3. **a token is required on every request that carries data** — minted at startup, written
   owner-only (best-effort: `chmod 0600` does little on Windows). Two deliberate exemptions, both
   documented in `server.py`: the **static shell page** (`/`), because a browser cannot attach a
   header to a navigation, and the **event stream**, which accepts the token as a query parameter
   because `EventSource` has no way to set headers. A query string reaches access logs, which is why
   it is that one read-only route and not a general fallback.

The token travels to the page in the URL **fragment**, which browsers never send to a server and
never put in a `Referer`. From there the page sends it as a header — except on the event stream,
above.

The `Origin` check **parses** the origin and requires it to round-trip exactly. It used to compare
prefixes, which accepted `http://localhost.evil.example`; an independent seat found it by reading the
check, and three lookalike origins were accepted when run. A prefix is not a host.

The models it dispatches to need not be local. Each carries a computed **reach** — `local`,
`internal`, `external` — and the console says which ones leave the machine. Choosing an external
model should be a decision somebody made, not one they discover later.

---

## How the plan is written

```jsonc
{
  "risk": "medium",
  "decisions": { "next_module": "frontier", "feedback": "done" },
  "node_models": {
    "lead_task_review": ["claude", "codex", "gemini"],   // model_panel → three voices
    "engineer_build":   ["claude", "codex", "gemini"]    // pool → one builds
  },
  "seat_models": { "conformance": "claude", "defect": "codex" },
  "node_specs": {
    "engineer_build": {
      "scope": "src/slugify.py",
      "objective": "write slugify",
      "instructions": ["lowercase", "collapse runs to one hyphen", "trim the ends"],
      "done_criteria": ["tests pass"],
      "acceptance_predicate": "pytest exits 0",
      "input_artifacts": ["docs/plan.md"],
      "expected_outputs": ["src/slugify.py"],
      "idempotence_probes": [],
      "workdir": "."
    }
  }
}
```

**The plan file is closed too**, at the top level and inside its `ship` block. It was the outermost
schema and the only entry point with no validation at all, and six independent reviews named it. The
case that decided it: a misspelt `ship` key made a run perform **no side effects and report
`finished`** — a dry run wearing a shipped run's report.

The node spec's fields are a **closed schema** — exactly these, no more and no fewer. A field outside
it is refused rather than ignored, because a setting that looks configured and does nothing is worse
than one that was rejected. **Every asking node needs one** — 15 of the 24 — and the walk stops at
the first one that has none.

A plan also needs an **`operations`** block for every node that can act, including the review seats:
`policy.role("seat").can_execute` is true, and the criterion is the capability, never the role's
name. A node that declares nothing is refused unless you pass `--undeclared allow`, which records
that you did.

```jsonc
"operations": {
  "engineer_build": [
    { "description": "write one module file", "kind": "ordinary", "targets": ["greet.py"] }
  ]
}
```

### A plan you can actually run

The snippets above are illustrative and **will not run** — they are `jsonc`, and `plan.json` is
parsed with `json.loads`. A complete, comment-free, working example is in
[`examples/`](examples/):

```bash
runner --config examples/runner.yaml run --plan examples/plan.json --risk low --confirm merge
```

That drives all 24 nodes, asks 17 questions, writes a real `greet.py`, and finishes. It is three
files: [`plan.json`](examples/plan.json) (15 node specs and 15 operation blocks),
[`runner.yaml`](examples/runner.yaml), and [`agent.py`](examples/agent.py) — which is also the only
place **the answer contract** is written down:

| The node | must answer |
|---|---|
| a decision node | `{"verdict": "<branch>"}` — one the node offers |
| `pm_plan` | `{"modules": [...]}` when `next_module` is `"frontier"` |
| `engineer_build` | `{"module": "<id>"}` |
| a seat on a panel | `{"verdict": "pass"\|"fail", "why": "…"}` |
| a seat at intake | `{"missing": [...], "problems": [...], "unsafe": [...]}` |
| anything else | any JSON object |

The work order arrives as JSON on **stdin**; the answer goes to **stdout** as JSON. A non-zero exit
is a failed attempt.

`decisions.next_module` may be `"frontier"`, which reads two recorded facts — what the PM most
recently planned, and what the engineers have built — instead of a list written before the first
module exists. A blueprint that grows during a run needs that.

---

## The practice this repository follows

The governance is not only what the runner enforces; it is how the runner itself was built. Both are
in [`docs/`](docs/).

**Every change gets a record** in [`docs/changes/`](docs/changes/) before it is built: what is
changing, why, the risk grade, the tasks with a **done-when** each, and what is *not* being claimed.
A done-when is written so that code which does not do the job fails it — *"a node configured with N
models that opens fewer than N sessions is refused"* rather than *"panels work"*.

**Nothing is ticked until it is demonstrated.** [`tools/ledger_check.py`](tools/ledger_check.py) runs
in CI and refuses a record whose status says finished with no acceptance record beside it. It caught
one of mine.

**Substantial changes go to two independent seats**, each with the same brief, neither seeing the
other, against a frozen tree. Their verdicts are committed whole in
[`docs/design/reviews/`](docs/design/reviews/) rather than summarised — a summary is where an
objection gets softened, and this repository's recorded history is disagreement being flattened.

**This is a practice, not a mechanism, and it has been broken.** CHG-20260823-14 and -15 — the two
changes that wrote this section — **landed before any seat had read them**, and their own Status
lines said so at the time. A reviewer reading the commit they shipped in could disprove the sentence
that used to stand here, and one did. Nothing in CI enforces review-before-merge; the ledger check
enforces only that a record claiming *finished* has an acceptance record beside it.

**A split does not pass** — when a review is held. The runner enforces that for runs; for design
records it is followed by hand, and the same caveat applies.

**Some tests exist to catch a shape of mistake rather than a specific one**, and they are the ones
that keep earning their keep:

| Test | What it refuses |
|---|---|
| `test_nothing_is_unwired.py` | a public name in `src/` that nothing in `src/` calls — a mechanism nobody invokes is not built |
| `test_documented_numbers` | a figure in the docs that disagrees with the code, recomputed rather than trusted |
| `test_the_console_has_a_handler_for_every_button_it_draws` | a control that does nothing |

**[`docs/defect-log.md`](docs/defect-log.md)** records every defect hit while building this, grouped
by *how it was found*. The short version: **thirteen were found by a reader before the change's code existed, nine only by
running it on a real project, and four by the test suite** — and several of the nine had been
shipping for changes, invisible to a suite passing 800+ tests, because a one-module,
one-instruction, one-server demo had the same bug and looked fine.

---

## Layout

```
src/ai_sdlc_runner/
  graph.py        the flow: 24 nodes, their modes, gates and branches
  policy.py       the governance: roles, gates × risk, permanent halts, seats, adjudication
  engine.py       walks the flow, enforces the policy, opens one session per ask
  workorder.py    the closed-schema order every ask receives
  intake.py       the six aspects, the union of what the seats found, the escalation to options
  models.py       the model registry: transport, key-by-name, computed reach
  attachments.py  content-addressed storage; the filename never becomes a path
  server.py       the local-only back end
  console/        the operator console — one page, no build step
  cli.py          flow · policy · settings · run · serve
docs/
  changes/        one record per change, with done-whens and what is not claimed
  design/         briefs, the interaction mock-up, and every seat verdict in full
  defect-log.md   every defect, grouped by how it was found
tools/
  ledger_check.py CI's check that no record claims more than was demonstrated
```

---

## Every schema in one place

[`docs/SCHEMAS.md`](docs/SCHEMAS.md) lists all sixteen — the node, the plan, the node spec, the
operation, the work order, the answer contract, the journal entry, the conversation turn, the CSV
columns, the model registry, the settings, the attachment manifest, the run report, and the proposed
SQLite DDL, and the server's HTTP API. **Five** are closed schemas — the plan file, the node spec,
the work order, the model registry and the settings: a field outside them is refused rather than
ignored.

Three have pages of their own — [`docs/API.md`](docs/API.md) for the fifteen HTTP routes,
[`docs/DATABASE.md`](docs/DATABASE.md) for the proposed SQLite schema, and
[`docs/MODELS.md`](docs/MODELS.md) for the rules that govern models: every refusal, how reach is
computed, and how a model reaches an ask. All three pages are pinned by
tests, because the catalogue drifted three ways in a day when nothing checked it.

---

## Known gaps

Named here rather than left for a reader to discover, because a governance tool that overstates what
it enforces is worse than one that enforces less and says so. All three were found by independent
seats reviewing this README.

**`halt_independent` does not check independence.** It is graded on `acceptance` at high risk and it
always stops for a person — but `STOPPING` treats it identically to `halt`, the server has a single
operator identity, and nothing records or compares who confirmed against who built. The name is an
intent. Closing it needs a second identity, which nothing in the design has yet.

**A seat panel that keeps failing has no bound.** `lead_review` → `review_failed` → `next_module` →
`lead_review` cycles until `max_steps`. The **module** review is explicitly bounded — one fix pass,
one re-review, then halt — and the seat panel is not. It changes the flow's topology, so it needs its
own record.

**Review-before-merge is a practice, not a mechanism.** See above; CI enforces the ledger, not the
review.

---

## Testing

```bash
pytest -q
```

CI runs the suite on Ubuntu and Windows, Python 3.9 and 3.13, plus the ledger check.
