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

