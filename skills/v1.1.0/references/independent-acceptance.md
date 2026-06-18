---
name: independent-acceptance
description: >
  Cross-agent / multi-scenario independent acceptance: when a code change is done and needs
  verifying, it must NOT be verified by the same agent that implemented it (player as referee) —
  a different agent must run verification under different scenarios, then results are aggregated
  into an ACC. Read this when a change is implemented and acceptance is due. Covers verifier ≠
  implementer, multi-scenario verification, guarding against self-confirmation and consensus bias,
  and result aggregation. Applies to AI-agent teams.
---

# independent-acceptance — cross-agent / multi-scenario independent acceptance

> 語言 / Language: [繁體中文](independent-acceptance.zh-tw.md) · **English**

## Purpose

When code is done and needs verifying, it **must not be verified by the agent that wrote it** — player as referee tends to test only the happy paths it thought of, reuse its own wrong assumptions, and stay blind to its own blind spots. This requires verification by a **different agent**, under **different scenarios**, aggregated into one ACC. This strengthens the acceptance-verification stage (independent + multi-scenario).

> "Team" is not limited to humans. **AI-agent teams** apply equally: the implementing agent and the verifying agent are different instances/contexts — and that's exactly where the independence comes from.

## When to read

- A change (CHG) is implemented and acceptance is due
- You need gating more trustworthy than self-verification (high-risk or structural changes)

## Rigor by risk

Read the CHG's "Risk" to decide how strict: **high** → mandatory independent acceptance (verifier ≠ implementer) + multi-scenario; **medium** → at least independent or full tests; **low** → self-verify is allowed. When recording the result in the ACC, **fill in the "Verifier" field** (person / agent id) so that "verifier ≠ implementer" can be checked by a human or by CI (see ci-cd's identity-check gate).

## Core principle: verifier ≠ implementer

Assign an **independent agent** to do acceptance, and:
- **Role = verifier, permission = read-only**: the verifying agent may only **read** the code under review and the criteria, and may only **write** its own ACC report; it **must not modify the code or structure docs under review**. Once the verifier can edit code, it "fixes things while verifying" — losing independence and possibly planting new issues. Found a problem → record it in the ACC → return to `modification-guide` for the implementer role to fix, not the verifier.
- Give it only the **source of the criteria** (Guideline §7 / the CHG's goal and acceptance criteria) + the **result (code/system)**.
- Do **not** give it the implementer's reasoning or "I think this is right" narrative — that would lead it along and replicate the same blind spots.
- Trace criteria back to the **source docs / user requirement**, not the implementer's self-report.

## Multi-scenario verification

Verify each criterion under several scenarios for real coverage:
- **Different inputs/boundaries**: normal, boundary, abnormal, empty and extreme.
- **Different environments**: reinstall/rebuild in a clean environment, then run tests (catches "works on my machine" issues).
- **Different entry points**: unit, API, and end-to-end — not just one.
- **Different agents splitting the work**: when needed, several agents each verify a slice (e.g. A functional correctness, B compatibility/regression, C non-functional), then aggregate.

## Guarding against bias

- **Self-confirmation bias**: self-verification tends to prove "it's right"; independent acceptance tends to find "where it breaks".
- **Consensus bias (specific to agent teams)**: if multiple agents share the same (possibly wrong) assumption or the same polluted context, they "fail together". Countermeasure: anchor criteria to the source requirement/docs, and run at least one verification scenario in a clean context (without the implementation conversation).
- **Cross-model review (break same-model blind spots)**: one model carries the same training biases and blind spots — if implementation and verification use the same model, some errors are "systematically invisible to both". **Prefer a different model/provider for the verifier** (cross-model review); especially for high-risk changes. Record the implementer model and verifier model in the ACC for traceability. If the platform has only one model, fall back to "clean context + a different role/system setup" to reduce correlation, and note this limitation in the ACC.
- **Blind check (advanced)**: don't tell the verifying agent the "expected answer" — give only criteria and result, and let it judge independently.

## Aggregation and close-out

- Aggregate the independent/multi-scenario results **into one ACC**: list each scenario's pass/fail with evidence.
- **Any scenario failing = fail**: return to `modification-guide` for fixes (the failure→re-fix loop), then re-verify independently.
- Only when all pass, backfill the CHG status to "Accepted" and link the ACC (per "close acceptance in the same round").

## Relation to the base flow

- Extends this skill's `acceptance-verification`: same "align to source, evidence per item, run what's scriptable", but upgrades "who verifies and under how many scenarios" to **independent + multi-scenario**.
- Pairs with `cross-agent`: the verifying agent gets the criteria and current result via docs/, no verbal handoff from the implementer.
- Pairs with `ci-cd` (optional): the scenarios that can be automated (clean environment, many inputs, regression) are run repeatedly by the pipeline.
