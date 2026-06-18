---
name: autonomy
description: >
  Autonomy and halt-point contract: defines, for an AI that runs the flow autonomously or an
  external orchestrator (Python, etc.), WHERE it must halt and await human approval vs WHERE it may
  proceed on its own — instead of letting the orchestrator infer from the Risk field by feel. Read
  this when letting an agent run multiple stages autonomously, or when an external program drives
  this flow. Covers halt gates, the risk × gate decision matrix, always-halt actions, per-CHG
  override, and a machine-readable contract (assets/halt_policy.json) + query tool
  (scripts/halt_gate.py).
---

# autonomy — autonomy & halt-point contract

> 語言 / Language: [繁體中文](autonomy.zh-tw.md) · **English**

## Purpose

Give "running the flow autonomously" clear boundaries: **which gates may proceed on their own (auto) and which must halt and await human approval (halt)**. This is a contract for an agent that auto-runs several stages, or an orchestrator (Python, etc.) driving this flow — express the halt points as **machine-readable rules** the orchestrator reads, rather than inferring from Risk by feel.

> Note: this differs from `ci-cd`'s pre-commit / pipeline — those gate "commit/merge"; this gates "should we pause mid-autonomous-run and wait for a human". They are complementary.

## Halt gates

The forward-progress transitions in the flow are potential halt points:

| gate | location |
|------|----------|
| `requirement_confirmed` | after requirement analysis produces the Guideline, before structure design |
| `structure_confirmed` | after structure design, before implementation |
| `before_implement` | after modification governance produces the CHG, before editing code |
| `acceptance_failed` | acceptance failed, before entering the re-fix loop |
| `before_merge_or_release` | after acceptance passes, before merge / release / delivery |

## Decision: risk × gate

Look up `auto` or `halt` by the change's **Risk** (from the CHG/ACC risk field):

| gate \ Risk | low | medium | high |
|-------------|-----|--------|------|
| requirement_confirmed | auto | auto | **halt** |
| structure_confirmed | auto | auto | **halt** |
| before_implement | auto | auto | **halt** |
| acceptance_failed | auto | **halt** | **halt** |
| before_merge_or_release | auto | **halt** | **halt** |

Intuition: **low risk runs fully autonomously; medium halts at "merge/deliver" and "acceptance failed"; high halts at every gate.**

## Always-halt actions (regardless of risk)

These **always halt for a human**, even at low risk (safety red lines):

- production deploy / release
- data migration / irreversible schema change
- delete data / drop table / hard delete
- move money / financial transaction
- change secrets / credentials / access control / permissions
- publish public content

## Per-CHG override

A single change may override via an `Autonomy:` field in the CHG header:
- `Autonomy: halt` (tighten) → halt immediately; always allowed.
- `Autonomy: auto` (loosen) → **only effective for non-"always-halt" items, and loosening a high-risk halt requires prior human approval**; the contract won't auto-loosen high risk (still returns HALT for a human to confirm).
Principle: **overrides may only tighten; loosening needs a human's nod.**

## Machine-readable contract & query tool

- Contract: [`assets/halt_policy.json`](../assets/halt_policy.json) (editable; the gates matrix + always_halt_actions).
- Query: [`scripts/halt_gate.py`](../scripts/halt_gate.py) — the orchestrator calls it at each gate to read the contract and get a decision:

```bash
python3 scripts/halt_gate.py --gate before_merge_or_release --risk high
# prints AUTO or HALT; exit code 0=AUTO, 10=HALT. Example:
#   python3 scripts/halt_gate.py --gate "$G" --risk "$R" --action "$ACTION" || await_human_approval
```

So "where to stop" is decided by the contract — the orchestrator reads the rules rather than each inferring its own: reproducible, auditable, adjustable.

## Relation to the rest of the flow

- Risk source: the CHG risk field in `modification-guide` / the ACC risk field in `acceptance-verification`.
- With `agent-hierarchy`: in an autonomous org, the parent agent checks the halt contract at each gate to decide whether to report to the human.
- With `ci-cd`: halt points govern "mid-autonomous-run"; CI gates govern "commit/merge". Both can coexist.
