## Gates on agent-written code

`--test-cmd` going green proves only that *the agent's own tests did not catch the agent's own
mistakes*. The same model wrote both, so they share one set of blind spots — ai-sdlc
`independent-acceptance` already says as much about verification; it applies with equal force
when one agent writes the code and its tests in the same breath.

Four gates sit on the code the agent produces, in this order:

1. **Unit execution — mandatory.** No `--test-cmd` now halts (exit 3). Previously it was skipped
   silently, so a task could be ticked and committed with not one line ever executed.
   `--allow-untested` is the explicit escape hatch; it prints a warning and is written to the
   handshake file.
2. **Mutation.** `--mutation` seeds faults into the files *this task* changed and re-runs the
   task's own tests. Survivors are reported by line and operator: those are the lines that could
   be wrong without anything going red. Below `--min-kill-rate` (default 90) the task gets one
   repair attempt, then halts. Test files are excluded from mutation — mutating a test inflates
   the kill rate with a tautology. Python only; other languages are reported as **not covered**.
3. **Behaviour spec.** A code CHG at Skill >= v1.5.0 must declare `### Behaviour spec` with
   `- feature: <path>`. The verify stage runs each one. The CHG's user stories thereby become
   re-runnable assertions instead of prose someone reads.
4. **Whole-branch review.** No longer a no-op: it calls the review command against the branch
   diff and requires a verdict line. Absence of output is not a pass.

