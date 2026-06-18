---
name: agent-worklog
description: >
  Subagent worklog and error knowledge base: when one agent dispatches subagents to run tasks (which
  can happen solo or in a team), each subagent must first write down "what it's about to do", and on
  error must record "what error + how it was resolved" before continuing; the orchestrating agent
  then consolidates all errors into a knowledge base so future tasks don't repeat them. Read this
  when you're about to dispatch subagents, or when you're a dispatched subagent about to start.
---

# agent-worklog — subagent worklog & error knowledge base

> 語言 / Language: [繁體中文](agent-worklog.zh-tw.md) · **English**

## Purpose

When one agent dispatches subagents to run tasks — **this isn't team-only; a single person using an AI that spawns subagents hits it too** — use a worklog to record "what I'm doing, what error I hit, how I fixed it", and have the orchestrating agent consolidate errors into a **knowledge base** so future tasks don't repeat them. Memory breaks, gets compacted, changes hands; the worklog and knowledge base are its durable replacement.

## When to read

- You (the orchestrator / parent agent) are about to dispatch subagents
- You are a dispatched subagent, before starting the task

## Subagent rules (the dispatched agent)

1. **Write before executing**: before acting, write in the worklog "what I'm about to do" — task, locked scope, expected output, role and read/write permission. So if it's interrupted / compacted / handed off, others or your future self can see how far you got and what you intended.
2. **Record the error and the fix, then continue**: on an error, record "**what error + root cause + how resolved**", and only continue after resolving; **never silently swallow it or pretend nothing happened**. If you can't resolve it, record the blocker and what you tried, and report up — don't force ahead.
3. **Report on completion**: report the output + **the list of errors hit this run** (for the parent to consolidate); if none, say so.

## Orchestrator rules (parent agent)

- **Assign role and read/write permission before dispatching**: every subagent has an explicit role and readable/writable scope (see cross-agent, independent-acceptance); verifier-type subagents are read-only.
- **Collect and consolidate errors**: aggregate every subagent's reported errors into the **knowledge base** `docs/knowledge/errors.md` — dedupe, generalize common patterns, write "error → root cause → fix → prevention".
- **The knowledge base is a cumulative asset**: every agent, on entry (alongside the Session startup check), **reads the knowledge base first** to avoid repeating known errors.

## File locations

- **Worklog (short-term, runtime)**: `docs/worklog/` (one entry per subagent, or one append-only file); for parallel work it can be merged into the coordination file. Clean up or archive after the task closes.
- **Error knowledge base (persistent, cross-task)**: `docs/knowledge/errors.md`.

## Knowledge base template

```markdown
# Error knowledge base
| Date | Context / task | Error | Root cause | Fix | Prevention |
|------|----------------|-------|------------|-----|------------|
| YYYY-MM-DD | <what you were doing> | <message/symptom> | <why it happened> | <how fixed> | <how to avoid next time> |
```

## Worklog entry template

```markdown
## <subagent/task name> — YYYY-MM-DD HH:MM
- Role / R-W scope: <role / RW scope>
- Doing: <task, locked scope, expected output>
- Progress: in progress / done / blocked
- Errors hit:
  - error: ... | root cause: ... | fix: ...  (or: unresolved, blocked on X, tried Y → reported up)
```

## Relation to the rest of the flow

- "Write before executing" echoes doc-integrity and "don't rely on memory, rely on the docs": state lives in files, not in the head — resilient to interruption / compaction / handoff.
- The error knowledge base is a third kind of trail beyond "decisions (CHG) / acceptance (ACC)": it records not just "what was decided" but "what pitfalls were hit and how to avoid them".
- Consolidation is the parent agent's job; **it applies solo too** — there, you are the parent.
