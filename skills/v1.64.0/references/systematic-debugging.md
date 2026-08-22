---
name: systematic-debugging
description: >
  Hypothesis-driven debugging loop for when a task's tests fail twice in a row: read the actual
  error, form one falsifiable hypothesis, find the cheapest observation that would disprove it,
  verify, then fix or move to the next hypothesis. Bounded (default 3 hypotheses) — then halt.
  Root causes land in the knowledge base. Read this instead of blind-retrying.
---

# systematic-debugging — hypotheses, not guesses

> 語言 / Language: [繁體中文](systematic-debugging.zh-tw.md) · **English**

## Trigger

The same task fails its tests **twice in a row**. That is the signal that the mental model is wrong — a third try from the same model of the problem is a coin flip, not engineering.

## The loop

1. **Read the actual failure** — the full error text, not the summary line. Most wrong fixes come from fixing the imagined error.
2. **One hypothesis** — a single, falsifiable statement of the cause ("the config is read before it is written").
3. **Cheapest observation first** — what is the smallest probe that would *disprove* it? A log line, a single assert, printing one value. Instrument, run, observe.
4. **Verdict** — hypothesis confirmed → fix it, re-run the task's tests, remove the probes. Disproved → next hypothesis with the new evidence.
5. **Bound** — after **3 hypotheses** (default) without a confirmed cause: halt (exit 3), write the evidence trail to the worklog. A bounded stop with evidence beats an unbounded thrash.

## Hard rules

- **Never make a test pass by weakening it** while debugging — the tdd-loop rule holds double here.
- **Every confirmed root cause becomes a knowledge entry** (error type: symptom → cause → fix), so the same bug costs the project only once. This is the wiring into ai-sdlc's error knowledge base — debugging that leaves no entry is work the next session repeats.
