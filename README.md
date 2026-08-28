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
| [`graph.py`](src/ai_sdlc_runner/graph.py) | the flow: 28 nodes, one kind of work each, with the module loop, the bounded retry, and the feedback edge back to PM |

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

28 nodes. Each does **one kind of work**, which is what decides where the boundaries fall: building,
verifying your own work, and having it reviewed are three kinds of work, so they are three nodes.

```
intake  →  intake_review        the seats read the requirement — before anything is planned
             │
             ↓
           pm_plan  →  plan_scope ─┬─ single ──────────────→ pm_confirm
                                      │                            (one workstream: unchanged)
                                      └─ split → sub_plan          one planner per workstream
                                                    └─→ reconcile  the declared interfaces are
                                                          ├─ agree → pm_confirm    compared, and
                                                          ├─ conflict → pm_plan    nobody votes
                                                          └─ unresolved → halt_unreconciled  ■
                                                             (one revision pass, then it halts)

                       pm_confirm ◆plan_confirmed
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
runner flow      # print all 28 nodes, their roles, gates and branches
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

### Where the agent runs

`agent_command` is run with its working directory set to **the directory holding the `runner.yaml`
that named it** — `agent_cwd`, which defaults to exactly that. A relative path in `agent_command`
therefore means one thing no matter where you are standing.

`agent_cwd` can be set explicitly. A relative value is resolved **against the config file**, the
same rule as everything else in it; an absolute value is used as written.

**It applies only to the command `runner.yaml` names.** A `--seat-model` command was typed in your
shell and runs there, and so does a command named by the models registry. Until CHG-20260823-51
every spawned command was relocated into the config's directory, which let a same-named file beside
the config silently stand in for an operator's own review seat.

It did not always. Before CHG-20260823-48 the command inherited **your shell's** directory, nothing
said so, and the three shipped examples disagreed about which directory they meant — `minimal` wrote
its path relative to the repository root, the two SPA examples relative to themselves. Two of the
three could not be run from the root at all, and neither of their READMEs mentioned it. The one that
could wrote its build output into the repository; a copy of that output was committed in PR #49 and
sat there for thirty changes.

**If you keep your own `runner.yaml`:** a relative `agent_command` path written for the directory you
type commands in stops working, at the first ask, with `can't open file`. Either make it relative to
the config file (recommended — they travel together) or set `agent_cwd` to the directory you meant.
An absolute path is unaffected.

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
| `--store sqlite\|file` | the conversation store. **`sqlite` since CHG-20260823-41**; `file` is the JSONL layout that came before it, kept so an existing store can be read and imported. `mongo` and `tinydb` are refused **by name** |
| `--store-root DIR` | where it lives (default `.runner/conversations`); for `sqlite` the database is `<DIR>/conversations.sqlite` |
| `--import-from DIR` | on `conversations`. Copies a JSONL store into this one, once, and **leaves the directory where it is** |
| `--format json\|markdown\|html\|playback\|csv` | on `export`. Required, because only `json` is lossless and a default would choose what you lose. `html` is a waterfall down the flow — one stop per node visit, the model's side and the operator's side marked apart; `playback` is the same walk as something you press play on. See [docs/RECORDING.md](docs/RECORDING.md) |

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

**The conversation store is SQLite** (CHG-20260823-41), which completes the second clause of
*「只留 sqlite + file，移除 mongo 和 tinydb / file 只作為 server 的 config 才處理」*. The JSONL
layout remains readable so an existing store can be brought across:

```bash
runner conversations --import-from .runner/conversations
```

Nothing is deleted by that. A migration that removes its own source has no way back if it was wrong,
so the directory is left where it is and a conversation already present is skipped rather than
merged — a turn whose `seq` matches and whose body differs has no answer that is not a guess.

**The Mongo and TinyDB backends were removed** in CHG-20260823-35, on the same ruling. Roughly 250 lines went with them, most of it URI
hardening: `MongoClient` performs topology discovery, so a loopback *host* was never the check — a
loopback seed that turns out to be a replica-set member is read from the server and every member it
names gets connected to. That needed a single-host `mongodb://` URI, a host that **round-tripped**
to loopback, an option **allowlist**, and `directConnection=true` forced on the client. A seat got
past an earlier denylist version of it twice.

None of that is needed by a directory of files, and the `store-uri` and `store-remote` flags went
with it: no store can be off this machine now, so there is no locality to relax, and a flag that no
longer changes anything is the "looks configured and does nothing" this repository refuses
everywhere else. (Written without their leading dashes on purpose: a gate here asserts that every
option this file names in flag form still exists, and it should not learn an exception for prose.)

**The guarantee CHG-20260823-35 weakened is back.** A duplicate `seq` was *refused* at write
time by Mongo's unique index and TinyDB's check; with only the JSONL backend it was **detected at
read time and prevented nowhere**. `PRIMARY KEY (conversation_id, seq)` refuses it again, at the
moment of the write, enforced by the database rather than by a convention:

```
UNIQUE constraint failed: turns.conversation_id, turns.seq
```

A turn belonging to no conversation is refused too — but only because the connection sets
`PRAGMA foreign_keys = ON`, which is per-connection and **OFF by default**. The declaration alone
would enforce nothing, so a test asserts the pragma rather than the schema.

What is lost is that a conversation is no longer readable with `cat`. That was a real property of
the JSONL store; `runner export --format json` is the replacement and it is not the same thing at
three in the morning.

The store holds every work order verbatim and is **exactly as sensitive as the ask journal already
sitting beside it**, and no better protected: it is created `0700` best-effort, which does little on
Windows.

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
parsed with `json.loads`. Three complete, comment-free, working examples are in
[`examples/`](examples/README.md), each with its own README:

| | what it shows | |
|---|---|---|
| **minimal** | the smallest plan this runner accepts, and the answer contract | [read](examples/minimal/README.md) |
| **tide-spa** | one brief run five times, each differing by a single field — **where a run stops and why** | [read](examples/tide-spa/README.md) |
| **weather-spa** | the **console** path: a brief typed by a person, a gate approved by clicking | [read](examples/weather-spa/README.md) |

The pages they build are at [`examples/demo/`](examples/demo/index.html), along with
[a console-driven run replayed](examples/demo/recording.html) — what a person typed, what the model
answered, and where the walk stopped to be approved. All of it is generated (the recording by
`--format playback` itself) and byte-compared by the suite, because a demo page kept by hand is a
screenshot with an `.html` extension.

```bash
runner --config examples/minimal/runner.yaml run --plan examples/minimal/plan.json --risk low --confirm merge
```

**Run that from anywhere.** `agent_command` in a `runner.yaml` is resolved against **the directory
that file is in**, not against your shell — so an example works the same whether you type it from
the repository root, from inside the example, or from somewhere else entirely. See
[Where the agent runs](#where-the-agent-runs) if you keep your own `runner.yaml`.

That **visits 21 of the 28 nodes** — five are failure paths a green run never takes, and two
(`sub_plan`, `reconcile`) are the second planning tier, which a single-workstream plan skips —
asks 17 questions, writes a real `examples/minimal/greet.py` beside the agent that wrote it, and
finishes. It is three
files: [`plan.json`](examples/minimal/plan.json) (15 node specs and 15 operation blocks),
[`runner.yaml`](examples/minimal/runner.yaml), and [`agent.py`](examples/minimal/agent.py) — which
is also the only place **the answer contract** is written down:

| The node | must answer |
|---|---|
| a decision node | `{"verdict": "<branch>"}` — one the node offers |
| `pm_plan` | `{"modules": [...]}` when `next_module` is `"frontier"` |
| `engineer_build` | `{"module": "<id>"}` — or `{"module": ""}` for **nothing left to build**, which ends the module loop. Omitting the key is not the same thing: it means the question was not answered, and the loop stays open |
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
other, against a frozen tree — `python tools/frozen_tree.py` says whether it is one, printing the
commit being verified or naming the files that differ from it. That check exists because the rule
did not have one: on 2026-08-27 an acceptance round of this repository's own ledger ran eleven
verifiers against a single shared worktree and broke it (CHG-20260827-13). Their verdicts are committed whole in
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
  graph.py        the flow: 28 nodes, their modes, gates and branches
  policy.py       the governance: roles, gates × risk, permanent halts, seats, adjudication
  engine.py       walks the flow, enforces the policy, opens one session per ask
  workorder.py    the closed-schema order every ask receives
  intake.py       the six aspects, the union of what the seats found, the escalation to options
  models.py       the model registry: transport, key-by-name, computed reach
  plan.py         the plan file, closed at the top level and inside its ship block
  store.py        the SQLite store: the registry, and which node or seat gets which model
  conversations.py  every turn of every conversation, append-only, categorised by project
  attachments.py  content-addressed storage; the filename never becomes a path
  server.py       the local-only back end
  console/        the operator console — one page, no build step
  cli.py          flow · policy · settings · run · serve · conversations · export
docs/
  SCHEMAS.md      all sixteen schemas, and which a machine enforces
  API.md          the seventeen HTTP routes, and the guard that runs before every one
  DATABASE.md     the SQLite schema, and every column that is deliberately not in it
  MODELS.md       the rules that govern a model: refusals, reach, assignment
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

Three have pages of their own — [`docs/API.md`](docs/API.md) for the **seventeen** HTTP routes,
[`docs/DATABASE.md`](docs/DATABASE.md) for the SQLite schema (**three of its five tables are
built**), and [`docs/MODELS.md`](docs/MODELS.md) for the rules that govern models: every refusal,
how reach is computed, and how a model reaches an ask.

A **[schema chart](docs/schema-atlas.html)** draws the same sixteen: the pipeline one ask travels,
the database with its real foreign keys, and which of the three axes — closed/open, built/designed,
persisted/in-memory — each schema sits on.

**All four pages are pinned by tests** — the catalogue drifted three checkable ways within a day of
being written, because nothing checked it. The tests execute the DDL, drive every refusal, and
compare each page against the code it maps.

---

## Where model configuration lives

Two halves, and both persist.

| | What it says | Where |
|---|---|---|
| **the registry** | which models exist | the `models` table (and `models.json`, still written) |
| **the assignment** | which node and which seat gets which model | `node_assignments` / `seat_assignments`, **and** the plan |

```bash
runner --config runner.yaml serve --plan plan.json          # POST /config/nodes, /config/seats
runner --config runner.yaml run   --plan plan.json          # reads the same store
runner run --plan plan.json --assignment-store none         # the plan alone
```

**The plan wins where it says something; the store fills where the plan is silent.** That is
`settings.py`'s rule one layer out — a per-change declaration must not be silently overridden by
something configured weeks ago — and `GET /config/nodes` returns a **`source`** map saying which of
the two put each assignment there. A merged answer alone cannot say, and an override nobody can see
is worse than no override.

The store refuses an unknown node, a node whose **mode ignores a model list** (four of the seven
do), a model the registry does not have, and a seat this runner does not define. Only registry model
ids can be assigned through it; a raw command line stays a plan and `--seat-model` thing.

---

## Known gaps

Named here rather than left for a reader to discover, because a governance tool that overstates what
it enforces is worse than one that enforces less and says so. Every one was found by an independent
seat, and several by seats reviewing the fix for the previous one.

**`halt_independent` does not check independence.** It is graded on `acceptance` at high risk and it
always stops for a person — but `STOPPING` treats it identically to `halt`, the server has a single
operator identity, and nothing records or compares who confirmed against who built. The name is an
intent. Closing it needs a second identity, which nothing in the design has yet.

**A seat panel that keeps failing has no bound.** `lead_review` → `review_failed` → `next_module` →
`lead_review` cycles until `max_steps`. The **module** review is explicitly bounded — one fix pass,
one re-review, then halt — and the seat panel is not. It changes the flow's topology, so it needs its
own record.

**Review-before-merge is a practice, not a mechanism.** CI enforces the ledger, not the review. It
has been followed since CHG-20260823-17, and it has been broken before that — the changes that broke
it are named in their own records.

**An `api` model registers and cannot be dispatched to.** It validates, it lists, the console shows
its reach — and the first ask routed to one raises, because this runner dispatches by running a
command. The refusal is right: the alternative it names in its own message is sending the work to
the default and reporting it as the named model. But `transport: "api"` is a declaration the runner
cannot yet honour.

**Two processes on one store are not covered.** A lock serialises threads inside one process;
`busy_timeout` is all there is between two, and each holds its own in-memory cache the other cannot
refresh. No harness exists, and four review rounds have said so.

**Only the conversation document carries a schema version.** Plans, answers, ask journals, the
registry, settings, attachment manifests and run reports all persist or cross a process boundary,
and none of them can say which shape it is.

**A decision node's answer is read under three names.** `branch`, then `verdict`, then `outcome`,
first one winning — so two of them disagreeing inside one answer resolves silently.

---

## Testing

```bash
pytest -q          # 1596 tests
```

CI runs the suite on Ubuntu and Windows, Python 3.9 and 3.13, plus the ledger check. The matrix is
the point: several defects here were Windows-only, and one — a `ValueError` on a malformed origin —
was found by CI on 3.9 and 3.13 after passing on the developer machine's 3.11.

Four kinds of claim in the documents are machine-checked rather than trusted:

| Test | Refuses |
|---|---|
| `test_documented_numbers` | a figure in the README that the graph or the policy no longer supports — including the **count of tests**, and how many nodes a run of the example actually visits |
| `test_every_cli_flag_the_readme_names_actually_exists` | a flag `argparse` would not accept, aliases included |
| `test_schemas` · `test_api_schema` · `test_models_schema` | a page that has drifted from the code it maps — including the **count** of closed schemas, which it derives by *exercising* each one rather than reading a label |
| `test_database_schema` | the DDL on the page failing to execute, or its constraints failing to refuse |

What no test holds is the prose explaining *why* a gate stops where it does. That is argument.
