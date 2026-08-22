# ai-sdlc-runner — Architecture & Feature Overview

*Rewritten by CHG-20260823-01. The previous version described an external driver for a published
skill: version locking, a vendored offline store, a four-stage orchestrator, subprocess calls to the
skill's gate script, a resident curses dashboard. None of that exists now. It is in git history.*

## 1. What it is

A **governed development agent**. It drives an ordinary development flow and decides at every step
whether that step may proceed on its own or has to stop and ask a person.

It exists so that running this flow needs no other company's agent, and it holds no skill, prompt
pack, or vendored contract. The flow and the governance are its own, in two files:

- **`policy.py`** — five roles with capability flags, ten gates × three risk grades, six
  never-automated actions, four review seats and the rule that adjudicates them.
- **`graph.py`** — 23 nodes, one kind of work each.

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

Ten gates, three risk grades. One rule: **a gate stops when getting it wrong is expensive to undo.**
Reviewing a module is cheap to redo, so it never stops the run; merging is a one-way door, so it asks
at every grade.

`auto` proceeds · `confirm` asks · `halt` stops for a person · `halt_independent` stops for a person
**and** forbids the implementer from verifying it.

Each node says **when** its gate is consulted: `before` the work where the work is the risk, `after`
it where the point is to hold the result. A review that halts before it runs is a review a high-risk
change can never get.

A halt is a pause with a way back — `--confirm <gate>` continues past one, and the confirmation is
recorded in the run report.

Six actions are never automated at any grade and no confirmation or mode relaxes them: production
deploys, data migrations, hard deletes, moving money, changing secrets or permissions, publishing.
They are matched against what each node says it is about to do, and stop the run before dispatch.

## 5. Sessions, and why they are short

Every asking node gets **its own session**: opened for one ask, closed straight after, and a factory
that hands back a session it already returned is refused. Continuity breeds bias — a model that can
see the previous exchange coasts on it, and a reviewer who has already seen the answer is not a
second opinion.

The question is written down as `pending` **before** its session opens and marked `answered` after,
for every asking role. A dropped session costs the answer and not the question.

`--seat-model` routes a named seat to a different command: the same question, different answerers,
which is what makes cross-model review real. The routing lives in the CLI and never in the order.

## 6. The panel

One or many seats, count set by the user above a floor of three. Each is asked separately and is
blind to the others; their instructions say so explicitly.

Verdicts are **adjudicated, not averaged**: the `conformance` seat has a veto and cannot be outvoted,
a majority is needed to pass, and a tie does not pass. The engine routes the flow on the result.

The floor may be lowered only through an explicit high-risk mode, and the run records that it was.
Relaxing a safeguard is the user's call; a relaxation nobody can see themselves making is not one
they made.

## 7. Interfaces

- `runner flow` — print the flow. `runner policy` — print the governance. Neither runs anything.
- `runner run --config <yaml> --plan <json> [--risk] [--seats N] [--high-risk-mode]
  [--confirm GATE ...] [--ask-journal DIR]`
- The plan carries `node_specs`, `decisions`, `risk`, `autonomy`, `operations`, `seat_models` and an
  optional `ship` block. The config carries `agent_command` and `agent_timeout` — dispatch settings
  only.
- A backend reads the work order as JSON on stdin and prints its answer as JSON. At a decision node
  the answer must name its branch (`branch`, `verdict` or `outcome`); a non-zero exit means it
  answered nothing, and the question stays pending.

## 8. Inviolable guardrails

- No skill content in this repo and no skill read at runtime — asserted by a test that scans source,
  tools, tests, packaging, the README and CI, docstrings included, and is written so it scans itself.
- The six permanent halts never auto-run, at any grade, under any mode.
- No silent fallback: missing configuration, an unknown gate, a branch the plan did not supply, an
  unanswerable probe, an unrecognised ledger status — each raises and names what is missing.
- **A mechanism is not built until something calls it** (KN-8). This repo's recurring defect is a
  correct piece nothing reaches, shipped green.

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

它**不依賴其他公司的 agent**,repo 內**不存放也不讀取任何 skill**。流程在 `graph.py`(23 節點,一個
節點只做一種工作),治理在 `policy.py`(角色、10 個閘門 × 3 個風險等級、6 個永久停點、審議席與裁決)。

四件事是這個設計的重點:**閘門會真的擋住流程**(而且停下來之後可以用 `--confirm` 續走,並留下紀錄);
**每個詢問都是獨立 session**,問完就關;**問題在 session 開啟之前先落盤**,斷線只損失答案不損失問題;
**審議席的判定會裁決出一個分支**——否決席不可被推翻、需要多數決、平手不過。
