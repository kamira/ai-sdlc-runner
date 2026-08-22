---
name: execution-plan
description: >
  Executable plan format for autopilot runs: a Global Constraints block that binds every task,
  plus per-task Interfaces (consumes/produces) and a test line, tracked with checkboxes. The plan
  lives inside the target project's CHG (modification-guide section) — never in a separate file.
  Read this when writing or validating a plan, before the first task is built.
---

# execution-plan — the plan that a machine can drive

> 語言 / Language: [繁體中文](execution-plan.zh-tw.md) · **English**

