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

---

## The flow

24 nodes. Each does **one kind of work**, which is what decides where the boundaries fall: building,
verifying your own work, and having it reviewed are three kinds of work, so they are three nodes.

```
intake
  └─ intake_review          the seats read the requirement — before anything is planned
       └─ pm_plan
            └─ pm_confirm                    ◆ plan_confirmed
                 └─ lead_assess              ◆ feasibility_confirmed
                      └─ pm_signoff          ◆ before_dispatch
                           └─ next_module ─┐
   ┌───────────────────────────────────────┘
   │  per module:
   │    engineer_build            one engineer, one small module
   │      └─ engineer_selfverify  ◆ self_verify — its own work, never the last word
   │           └─ lead_task_review ◆ task_review
   │                ├─ pass → record_module → next_module
   │                └─ fail → fix_pass → re_review
   │                                       ├─ pass → record_module
   │                                       └─ fail → halt_second_fail   (bounded: one fix pass)
   └─ when no modules remain:
        lead_review               ◆ lead_review — the seats cross-check the whole change
          └─ qa_verify            ◆ qa_verify — run for real
               └─ qa_accept       ◆ acceptance
                    └─ pr         ◆ pr
                         └─ merge ◆ merge — the one-way door
                              └─ close_out → feedback → pm_plan | done
```

`◆` marks a gate. Three shapes carry most of the meaning and are explicit rather than flattened:

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

Acceptance on a high-risk change is `halt_independent`: the verifier must not be the builder.

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
**reproducible on purpose too**, seeded by run and node, so "which model built this" stays answerable
afterwards. Every dispatch is recorded.

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
says exactly what it does not have. Asking again is right; asking forever is not — after the **third**
unanswered ask for one aspect, the runner stops asking and puts **at least three options** on the
table, authored by a model and recorded as an ask. It does not pick one.

---

## Running it

### From the command line

```bash
runner run --plan plan.json --risk medium --ask-journal .runner/asks
```

A halted run tells you what stopped it. Answer it and resume:

```bash
runner run --plan plan.json --resume --ask-journal .runner/asks --confirm plan_confirmed
```

Useful flags:

| Flag | |
|---|---|
| `--confirm GATE` | a gate you have already approved; repeatable |
| `--rule NODE=BRANCH` | break a tie a panel could not decide |
| `--seats N` / `--seat-model SEAT=CMD` | how many seats, and which backend answers each |
| `--undeclared refuse\|allow` | what to do with a working node that declares no operations |
| `--risk low\|medium\|high` | override the plan's grade |

### With the console

```bash
runner serve --plan plan.json --port 8765
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
3. **a token is required on every request** — minted at startup, written owner-only. A cross-origin
   page can *send* a request but cannot **read a file on disk**, which is what makes local-only hold.

The token travels in the URL **fragment**, which browsers never send to a server and never put in a
`Referer`.

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

The node spec's fields are a **closed schema** — exactly these, no more and no fewer. A field outside
it is refused rather than ignored, because a setting that looks configured and does nothing is worse
than one that was rejected.

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

**Changes are reviewed by two independent seats** before they land, each with the same brief, neither
seeing the other, against a frozen tree. Their verdicts are committed whole in
[`docs/design/reviews/`](docs/design/reviews/) rather than summarised — a summary is where an
objection gets softened, and this repository's recorded history is disagreement being flattened.

**A split does not pass.** The runner's own rule — a tie decides nothing — applies to its own design
records, or it is not a rule.

**Some tests exist to catch a shape of mistake rather than a specific one**, and they are the ones
that keep earning their keep:

| Test | What it refuses |
|---|---|
| `test_nothing_is_unwired` | a public name in `src/` that nothing in `src/` calls — a mechanism nobody invokes is not built |
| `test_documented_numbers` | a figure in the docs that disagrees with the code, recomputed rather than trusted |
| `test_the_console_has_a_handler_for_every_button_it_draws` | a control that does nothing |

**[`docs/defect-log.md`](docs/defect-log.md)** records every defect hit while building this, grouped
by *how it was found*. The short version: **thirteen were found by a reader before the code existed,
nine only by running it on a real project, and four by the test suite** — and the nine that only
running it found had all been shipping, invisible to a suite passing 800+ tests, because a
one-module, one-instruction, one-server demo had the same bug and looked fine.

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

## Testing

```bash
pytest -q          # 847 passing
```

CI runs the suite on Ubuntu and Windows, Python 3.9 and 3.13, plus the ledger check.
