## The loop

1. **Read the actual failure** — the full error text, not the summary line. Most wrong fixes come from fixing the imagined error.
2. **One hypothesis** — a single, falsifiable statement of the cause ("the config is read before it is written").
3. **Cheapest observation first** — what is the smallest probe that would *disprove* it? A log line, a single assert, printing one value. Instrument, run, observe.
4. **Verdict** — hypothesis confirmed → fix it, re-run the task's tests, remove the probes. Disproved → next hypothesis with the new evidence.
5. **Bound** — after **3 hypotheses** (default) without a confirmed cause: halt (exit 3), write the evidence trail to the worklog. A bounded stop with evidence beats an unbounded thrash.

