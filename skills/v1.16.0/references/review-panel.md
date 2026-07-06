---
name: review-panel
description: >
  Decision review panel & adjudication: when the rules outgrow one agent's context, split the
  review — each reviewer seat loads ONE governance domain and renders a one-line verdict on the
  change; the dispatcher adjudicates (hard-rule fails veto). Read this for medium/high-risk
  changes, when dispatching reviewer seats, or when you are a seat. Covers seats, briefings,
  the verdict format, veto adjudication, risk-scaled invocation, recursive roll-up (hard fails
  escalate uncompressed), and the no-spawn degradation (serialized self-review).
---

# review-panel — decision review panel & adjudication

> 語言 / Language: [繁體中文](review-panel.zh-tw.md) · **English**

## Purpose

One agent holding fifteen rulebooks forgets rules under context pressure; N reviewers each holding **one** rulebook don't. The panel turns rule compliance from a memory problem into an architecture problem: seats deliberate independently with undiluted attention, and the dispatcher reads **conclusions (KB), not rulebooks (tens of KB)**. It extends independent-acceptance ("reviewer ≠ author") from the acceptance stage forward to the **decision** stage.

## Seats (one domain each)

| Seat | Loads | Verdict question |
|------|-------|------------------|
| risk | modification-guide (grading) | is the risk grade right? high-list hit? |
| impact | modification-guide (impact / assumptions) | knock-on effects? broken prior assumptions? |
| drift | doc-integrity | docs↔code consistent before and after? |
| compliance | knowledge | does this violate any directive? |
| security | autonomy (always-halt list) | does it touch an always-halt action? |
| consistency | branch-isolation / cross-repo | same-branch sources only? contract impact? |

Each seat gets a **scoped briefing**: the CHG draft + its one domain reference (+ global knowledge) + **only its own seat row — not this whole table** (the panel view belongs to the dispatcher). Seats are **read-only and spawn nothing** (no spawn capability — `Agent` tool on Claude, or your platform's equivalent). Machine loads: `role_refs.json` v3 `seat-*` roles.

## Verdict format (one line per seat)

```
[verdict] <seat> | <model> | pass / fail / concern | <evidence pointer> | <one-line reason>
```

Seats **need not share a model** — when the platform offers several, spread seats across models (same-model panels share the same blind spots); record each seat's model in its verdict line; on a single-model platform, note the limitation.

Verdicts are appended to the CHG (a "Review verdicts" section) — the lint checks that **implemented high-risk CHGs carry them**.

## Two-phase cross-validation

Verdicts are not just collected — they cross-check each other, in two phases:

- **Phase 1 — independent**: every seat produces its verdict **without seeing the others'** (anti-anchoring; a seat that reads first agrees first).
- **Phase 2 — cross-read**: each seat then reads the other verdicts and flags disagreements: `[cross] <seatA>→<seatB> | agree / disagree | <one-line reason>`. A disagreement is **reconciled or escalated — never averaged**; unresolved cross-flags go to the user via the confirm gate.

The dispatcher adjudicates on the **post-cross** set; cross lines are appended to the CHG alongside the verdicts.

## Adjudication (the dispatcher)

- **Hard-rule fail = veto**: a fail from the risk / security / compliance seats **cannot be overruled by the dispatcher** — overruling requires the user, via the confirm gate.
- **Concerns** are weighed by the dispatcher and recorded in the CHG's decisions & trade-offs — accepted or not, the reasoning stays.
- The dispatcher's own judgment covers only what no hard rule decides.

## Risk-scaled invocation (panels are depth for risk, not a tax on everything)

| Risk | Panel (when spawning is available) |
|------|------------------------------------|
| high | **full panel (all six seats), mandatory** |
| medium | **at least five seats** (pick by relevance from the six) |
| low | none — fast path (see modification-guide "CHG-lite") |

Quotas bind only **when subagents can be dispatched** — decisions take no fewer than **5** reviewers, verification no fewer than **3** (see independent-acceptance). The no-spawn degradation (serialized self-review) keeps the same seat list without the headcount, and notes it.

The panel's remit isn't only CHG decisions: **an elicited proposal (企劃) handed up by A1** (see requirement-analysis "elicitation by proxy") goes through the same joint review at the decision quota before the flow proceeds.

## Recursive roll-up (the pyramid)

Every dispatching layer owes three things: a **briefing down**, an **adjudication at its own level**, and a **one-line verdict summary up**. Per-layer compression is the point — but **hard fails escalate uncompressed, unconditionally: no intermediate layer may swallow one** (the review-layer mirror of worklog's "never silently swallow an error"). Prefer **wide over deep** — spawning is cheap, hops are lossy. Panels are task forces: they dissolve when the change closes; the memory stays in `docs/`, not in the org.

## Degradation (no spawn available)

Run the same seats **serially as self-review**: load one domain at a time, emit the same verdict line, then move to the next. The format itself forces one-domain-at-a-time attention even without subagents — note "serialized (no spawn)" in the verdicts section.

## Relation to the rest of the flow

- handshake: seat briefings follow the scoped tier (four keys; briefing composed by the dispatcher).
- modification-guide: invocation is driven by the CHG risk grade; verdicts live in the CHG; veto overrule goes through the confirm gate.
- agent-hierarchy: the dispatcher's duties gain "convene panel + adjudicate"; the tools allowlist keeps seats read-only and spawn-free.
- independent-acceptance: V1's independent acceptance still happens after implementation — the panel guards the decision, V1 guards the result.
