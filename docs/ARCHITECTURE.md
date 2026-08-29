# ai-sdlc-runner — Architecture & Feature Overview

*Rewritten by CHG-20260823-01. The previous version described an external driver for a published
skill: version locking, a vendored offline store, a four-stage orchestrator, subprocess calls to the
skill's gate script, a resident curses dashboard. None of that exists now. It is in git history.*

## 1. What it is

A **governed development agent**. It drives an ordinary development flow and decides at every step
whether that step may proceed on its own or has to stop and ask a person.

It exists so that running this flow needs no other company's agent, and it holds no skill, prompt
pack, or vendored contract. The flow and the governance are its own, in two files:

- **`policy.py`** — six roles with capability flags, 10 gates × three risk grades, six
  never-automated actions, four review seats and the rule that adjudicates them.
- **`graph.py`** — 29 nodes, one kind of work each.

Nothing points outside this repository. The dependency graph closes inside `src/`.

## 2. Module map (`src/ai_sdlc_runner/`)

| Module | Responsibility |
|--------|----------------|
| `policy.py` | The governance. Depends on nothing — a governance module that imports what it governs can be argued into agreeing with it |
| `graph.py` | The flow, as data. `validate()` checks it against `policy` |
| `engine.py` | Walks it: gates, sessions, the ask journal, adjudication, answer-routed branches, effects |
| `workorder.py` | One node's order — closed schema, nothing about the harness |
| `effects.py` | Ordered effects, each admitted only if probeable |
| `probes.py` | Postconditions read from git, the forge, the ledger. Unanswerable raises |
| `ship.py` | intent → branch → commit → push → PR, each effect with its probe |
| `cli.py` | `flow` / `policy` / `run`; one process per ask; seat-to-model routing |
| `tui.py` | The selector, and the high-risk-mode confirmation |

Plus `tools/ledger_check.py` — this repo's own ledger lint, outside the runtime.

Direction: `cli → engine → {graph, workorder, effects} → policy`, and `ship → {effects, probes}`.

## 3. The flow

```
intake → pm_plan → pm_confirm → lead_assess → pm_signoff
       → [ next_module ⟳ engineer_build → engineer_selfverify → lead_task_review
             ├ pass → record_module ─────────────────────────────┐
             └ fail → fix_pass → re_review ├ pass → record_module┤
                                           └ fail → HALT        │
         ────────────────────────────────────────────────────────┘ ]
       → lead_review (seats)  ├ pass → qa_verify → qa_accept ├ pass → pr → merge
                              └ fail → back into the loop    └ fail → back into the loop
       → close_out → feedback ├ more → pm_plan
                              └ done
```

Three shapes carry most of the meaning: the **per-module loop** (which is also the resume mechanism
— an already-recorded module is simply not the frontier), the **bounded retry** (one fix pass, one
re-review, second failure halts), and the **feedback edge** (the flow closes rather than ends).

## 4. The gates

10 gates, three risk grades. One rule: **a gate stops when getting it wrong is expensive to undo.**
Reviewing a module is cheap to redo, so it never stops the run; merging is a one-way door, so it asks
at every grade.

`auto` proceeds · `confirm` asks · `halt` stops for a person · `halt_independent` stops for a person
**and** forbids the implementer from verifying it.

Each node says **when** its gate is consulted: `before` the work where the work is the risk, `after`
it where the point is to hold the result. A review that halts before it runs is a review a high-risk
change can never get.

A halt is a pause with a way back — `--confirm <gate>` continues past one, and the confirmation is
recorded in the run report.

Six actions are never automated at any grade and no confirmation, mode or change class relaxes them: production
deploys, data migrations, hard deletes, moving money, changing secrets or permissions, publishing.

Four layers decide, and each may only ever **add** a stop:

1. **The targets** — the commands, paths and URLs the operation will act on. `rm -rf` in a command
   is not a phrasing choice and a path under `secrets/` is not an opinion, so these are read
   directly and **outrank the declaration**. A plan naming `kubectl apply -f prod/` has said
   "production deploy" whatever it wrote in `kind`.

   Each target lands in one of **three** states: red line, recognised-ordinary, or **unrecognised** —
   and the third is not the safe one. What counts as recognised is deliberately small: a plain repo
   path, read-only version control, and the **commands the operator has vouched for**, because they
   know their toolchain and this runner does not.

   Two limits on vouching, both learned by having them broken. A command whose name says nothing
   about what it will do — `python`, `sh`, `rm`, `curl`, `xargs` — **cannot be vouched at all**:
   vouching for an interpreter is vouching for anything it can be told to do, and
   `python -c "…unlink()"` was ordinary until it was refused by name. And vouching covers the
   **tool, not the command line**: `docker volume rm` and `git push origin +main:main` are refused
   from an operator who vouched for `docker` and `git`. The common case survives through shape —
   `python -m pytest` is ordinary because *pytest* is vouched. An earlier version had only two, so "no red-line pattern
   matched" was read as "verified safe", and a verifier declared `dd if=/dev/zero of=/dev/sda`
   `ordinary`, named it as a target, and watched the run finish with an empty report. A blacklist
   that recognises nothing has *said* nothing. An unrecognised target stops the run by default, and
   under `--undeclared allow` it proceeds **recorded**, never silent.

   This layer narrows how far the planner is trusted. It does not remove the planner as a trust
   boundary — no list of dangerous commands is ever finished, and what this list has not seen still
   rests on the declaration. That is why the third state exists and why `on_trust` is a report line.
2. **The declaration** — each operation declares its `kind` from a closed set of the six plus
   `ordinary`, and **an operation that declares nothing is refused**. A declared red line always
   halts.
3. **The description**, against word lists — the backstop, and the weakest by design. Both of its
   numbers are measured and pinned: it catches **6 of 18** adversarial sentences, and stops **0 of
   56** ordinary engineering briefs. It was once tuned to catch 8, which cost a 69% false-stop rate
   — and a check that fires on two jobs in three gets switched off, which protects nothing at all.
   A phrase is listed only if it cannot plausibly describe safe work.

Before any of that, the node's own **brief** is read — **every field of it**, not a chosen few, plus
the paths it names (`input_artifacts`, `expected_outputs`, `workdir`) through the target rules. A
work order saying *"deploy the new build to production, then wipe the users table"* used to run to
completion because the operation beside it said `ordinary`; then a curated three-field version let
the same sentence through in `done_criteria`. Choosing which fields to read has as many blind spots
as the fields it omits. There is no way past this except changing what the node is told to do.

An operation nothing could confirm — declared `ordinary`, and either naming no targets or naming
ones this runner does not recognise — is taken on the plan's word. Under `--undeclared refuse` (the
default) it stops; under `allow` it proceeds and lands in the run report under `on_trust`, so an
auditor sees which steps nothing verified. The condition used to be simply "no targets", which meant
naming any benign path switched the disclosure off — the same mechanism that hid the five silent
passes.

`--undeclared allow` exists for dry runs and records itself as a relaxation. It **never** covers a
node that applies effects: a run that changes the world is not a dry run, whatever the flag says.

## 5. Sessions, and why they are short

Every asking node gets **its own session**: opened for one ask, closed straight after, and a factory
that hands back a session it already returned is refused. Continuity breeds bias — a model that can
see the previous exchange coasts on it, and a reviewer who has already seen the answer is not a
second opinion.

The question is written down as `pending` **before** its session opens and marked `answered` after,
for every asking role. A dropped session costs the answer and not the question.

`--seat-model` routes a named seat to a different command: the same question, different answerers,
which is what makes cross-model review real. The routing lives in the CLI and never in the order.

**When nobody uses it, the run says so.** Three seats answered by one backend are independent of each
other's context and not of that model's blind spots — which is most of what the seats are for. The
report records `single_model_panels` and the CLI prints `single model:`, naming the fix. A
disclosure, not a gate: the seat count is the user's, and refusing to run would make the honest
default unusable. It compares **backends**, not models — two wrappers around the same model read as
diverse, and the runner cannot see past the command it ran.

**Resuming.** `runner run --resume --ask-journal DIR` continues an interrupted run: what the journal
already answered is not asked again, and the pending question is re-asked verbatim. Resuming is a
decision — without the flag, a journal that happens to exist changes nothing, because a run silently
continuing somebody else's is worse than one starting over.

## 6. The panel

One or many seats, count set by the user above a floor of 3. Each is asked separately and is
blind to the others; their instructions say so explicitly.

Verdicts are **adjudicated, not averaged**: the `conformance` seat has a veto and cannot be outvoted,
a majority is needed to pass, and a tie does not pass. The engine routes the flow on the result.

The floor may be lowered only through an explicit high-risk mode — set in `runner settings`, or per
run with `--high-risk-mode` — and the run records that it was.
Relaxing a safeguard is the user's call; a relaxation nobody can see themselves making is not one
they made.

## 7. Interfaces

- `runner flow` — print the flow. `runner policy` — print the governance. Neither runs anything.
- `runner settings` — a **terminal** screen (curses, with a numbered fallback) that sets the review
  seat count and the high-risk bypass, persisted to `config/settings.json`. `runner settings --show`
  prints them without a menu, so a bypass is visible to somebody reading a log rather than sitting
  at a terminal. It is a TUI, not a graphical interface — worth saying plainly, because the
  requirement asked for a GUI and this is what exists.
- `runner run --config <yaml> --plan <json> [--risk low|medium|high] [--seats N]
  [--high-risk-mode] [--confirm GATE ...] [--seat-model SEAT=COMMAND ...] [--ask-journal DIR]`
- The plan carries `node_specs`, `decisions`, `risk`, `autonomy`, `operations` (each declaring its
  `kind`), `seat_models` and an optional `ship` block. `--risk` and `--seat-model` override the
  plan's own values. The config carries `agent_command` and `agent_timeout` — dispatch settings
  only.
- A backend reads the work order as JSON on stdin and prints its answer as JSON. At a decision node
  the answer must name its branch (`branch`, `verdict` or `outcome`); a non-zero exit means it
  answered nothing, and the question stays pending.

## 8. Inviolable guardrails

- No skill content in this repo and no skill read at runtime — asserted by a test that scans source,
  tools, tests, packaging, the README and CI, docstrings included, and is written so it scans itself.
- The six permanent halts never auto-run at any risk grade, and no confirmation
  relaxes them. **`--undeclared allow` is the one mode that can reduce the check** —
  it skips the declaration for a node that only dispatches a question, never for one
  that applies effects, and records itself in the run. This sentence used to read
  "under any mode", which a verifier showed was false; a guardrail described more
  strongly than it behaves is worse than one described honestly.
- No silent fallback: missing configuration, an unknown gate, a branch the plan did not supply, an
  unanswerable probe, an unrecognised ledger status — each raises and names what is missing.
- **A mechanism is not built until something calls it** (KN-8). This repo's recurring defect is a
  correct piece nothing reaches, shipped green — three rounds of it, every one found by an
  independent verifier rather than by CI. `tests/test_nothing_is_unwired.py` now checks it
  mechanically: nothing public in `src/` may be unreachable from `src/`.

## 9. Testing

`pytest tests/` on `{ubuntu, windows} × py{3.9, 3.13}`, `fail-fast: false`, plus the ledger gate, on
every PR and every push to `main`.

The **OS matrix** is load-bearing: the defect that motivated CI was platform-conditional and a
single-OS pipeline would have stayed green through all of it. The **version axis** has since caught
its own — an identity check written with `id(...)` passed on 3.9 and 3.11 by allocation luck and
failed on 3.13.

CI is deliberately not gated on a coverage percentage: measuring the CHG-20260817-09 fix showed
`executors.py` at 86% before and 85% after, because the broken tests were executing the code and
dying inside it — coverage counted the lines while no assertion ever ran.

## 10. Where the detail lives

| Question | File |
|---|---|
| What each module does, and which way the dependencies run | `docs/structure/logical.md` |
| Component contracts, and why each decision went the way it did | `docs/structure/design.md` |
| What is persisted, and the shape of every structure that matters | `docs/structure/data.md` |
| The tree | `docs/structure/directory.md` |
| The requirements and conventions | `docs/ai-guideline.md` |
| Lessons that cost something to learn | `docs/knowledge/knowledge.md` |
| Every change, and its acceptance | `docs/changes/`, `docs/acceptance/` |

## 繁體中文摘要

`ai-sdlc-runner` 是一個**受治理的開發代理**:跑一條普通的開發流程(PM → 主管 → 工程師 → 自我驗證 →
主管 review → 審議席 → QA → 回饋回 PM),並在每一步判斷這一步能不能自己走。

它**不依賴其他公司的 agent**,repo 內**不存放也不讀取任何 skill**。流程在 `graph.py`(29 節點,一個
節點只做一種工作),治理在 `policy.py`(角色、10 個閘門 × 3 個風險等級、6 個永久停點、審議席與裁決)。

四件事是這個設計的重點:**閘門會真的擋住流程**(而且停下來之後可以用 `--confirm` 續走,並留下紀錄);
**每個詢問都是獨立 session**,問完就關;**問題在 session 開啟之前先落盤**,斷線只損失答案不損失問題;
**審議席的判定會裁決出一個分支**——否決席不可被推翻、需要多數決、平手不過。
