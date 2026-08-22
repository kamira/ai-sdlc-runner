## Batch approval (halt fatigue)

High risk halts at every gate — five prompts for one change train the human to rubber-stamp, which defeats the halts. A human may **batch-approve per CHG**: when approving at a gate, explicitly say the remaining gates for this CHG are approved too; record it in the CHG header (`Autonomy: auto (remaining gates approved by <user> at <gate>, <time UTC+0>)`) and proceed without re-asking. Limits: **always-halt actions are never batchable**; the batch covers **this CHG only**; an acceptance failure or scope change **voids it** (back to per-gate).

