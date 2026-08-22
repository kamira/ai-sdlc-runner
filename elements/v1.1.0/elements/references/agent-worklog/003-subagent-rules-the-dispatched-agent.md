## Subagent rules (the dispatched agent)

1. **Write before executing**: before acting, write in the worklog "what I'm about to do" — task, locked scope, expected output, role and read/write permission. So if it's interrupted / compacted / handed off, others or your future self can see how far you got and what you intended.
2. **Record the error and the fix, then continue**: on an error, record "**what error + root cause + how resolved**", and only continue after resolving; **never silently swallow it or pretend nothing happened**. If you can't resolve it, record the blocker and what you tried, and report up — don't force ahead.
3. **Report on completion**: report the output + **the list of errors hit this run** (for the parent to consolidate); if none, say so.

