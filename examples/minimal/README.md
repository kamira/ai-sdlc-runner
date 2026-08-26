# The minimal example

The smallest plan this runner accepts, and the smallest agent that can answer it. One module:
`greet(name) -> str`.

Start here. It is the shape of a plan and the **answer contract** with nothing else in the way — no
loop, no seats disagreeing, no SPA to look at.

```bash
python3 -m ai_sdlc_runner.cli --config examples/minimal/runner.yaml run --plan examples/minimal/plan.json --risk low
```

## What is here

| file | what it is |
|---|---|
| `plan.json` | 15 node specs, the operations, and the branch decisions. Every field a plan may carry, and no field it may not |
| `agent.py` | the agent the runner dispatches to. One process per ask: the work order arrives on stdin, one JSON object goes to stdout |
| `runner.yaml` | two lines: the agent command and a timeout |

## The answer contract

This is the part worth reading. `agent.py` is where it is written down — which node must answer
what, and what happens when it does not.

| node | must answer |
|---|---|
| `intake_review` | `{"missing": [], "problems": [], "unsafe": []}` |
| `pm_plan` | `{"modules": [...]}` — the list the module loop walks |
| `engineer_build` | `{"module": "..."}` — **which** module was built |
| a decision node | `{"verdict": "<one of the node's branches>"}` |
| a review seat | `{"verdict": "pass" \| "fail", "why": "..."}` |

Two of those are sharper than they look:

**A decision node's verdict must name one of *that node's* branches.** `pm_confirm` branches to
`['no', 'yes']`, so answering `"pass"` there names no branch and the run halts on it. The first
version of the tide example's agent answered `"pass"` everywhere and stopped at exactly that node.

**`engineer_build`'s `module` is not enforced.** A build that omits it never shrinks the frontier,
so `next_module` keeps sending the flow back and the run dies at the 200-step cap — a long way from
the cause. `examples/weather-spa` scenario C shows that failure on purpose.

## Why `expected_outputs` is empty almost everywhere

`[]` on **14 of the 15** nodes here, because a review or gate node genuinely produces nothing. That
figure is why `CHG-20260823-34` refuses a blank `scope` and `objective` but *not* a blank
`expected_outputs`: a rule that refused every empty field would refuse this file.

## Then

| | |
|---|---|
| [`../tide-spa`](../tide-spa/README.md) | the same flow with a real page coming out of it, and five plans that each stop somewhere different |
| [`../weather-spa`](../weather-spa/README.md) | the console path — an instruction typed by a person, a gate approved by clicking |
