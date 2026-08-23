# docs/design

Design artefacts that are **not** the implementation, kept where the change record can point at them.

| File | What it is | Governed by |
|---|---|---|
| `console-mockup.html` | The operator console, simulated in the browser. Real node/gate/seat data, no back end. | CHG-20260823-11 |

## Why the mock-up is in the repo

It is the specification. The change record describes the four decisions in prose; the mock-up is
where you can press the button and see what a tie actually looks like when it reaches a person.
A specification you cannot operate is one people agree to without reading.

It is also **kept honest by being here**: when the console is built and the mock-up disagrees with
it, that is a diff in this repository rather than a link somebody remembers differently.

**It has no back end.** It simulates the flow in JavaScript so the interaction could be judged
before anything was built. Nothing here talks to `src/ai_sdlc_runner`, and the day something does,
this file stops being the specification and starts being a lie — so it gets deleted then, not kept
as a museum piece.

Open it in a browser, or read it at
https://claude.ai/code/artifact/2e387693-6720-4d06-a803-62cfc8e8d0a7

## Review artefacts

| File | What it is |
|---|---|
| `review-round-1-brief.md` | The brief both seats answered in round 1 of CHG-20260823-11. |
| `review-round-2-brief.md` | The brief for round 2 — judging the corrections round 1 forced. |
| `reviews/` | Every seat's verdict, whole. See its README for provenance. |

The briefs are kept because a later round has to be comparable against the same questions rather
than a remembered version of them — and because round 2 caught a real defect by reading round 1's
brief: it had **handed both seats** the alternative they then agreed on, which the record reported as
independent convergence.

The verdicts are in `reviews/`. The change record summarises them, separated into what both seats
found and what one found — different strengths of claim, and collapsing them throws away the only
thing two independent reviewers buy you. **Where a summary and a verdict disagree, the verdict is
right.**
