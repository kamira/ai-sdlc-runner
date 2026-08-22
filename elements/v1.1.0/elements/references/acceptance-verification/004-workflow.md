## Workflow

1. **Gather the baseline**: list all criteria this round must satisfy (each tied to a requirement ID or modification-guide step).
2. **Check item by item**: for each, actually check whether the result conforms and record evidence (point to the file/behavior/test that proves it). For things checkable programmatically (e.g. whether a corresponding test exists, whether a field is present), write a script or run it — don't eyeball it.
3. **Judge**: mark each Pass / Fail / N/A, with evidence or the gap.
4. **Produce the report**: write `docs/acceptance/ACC-YYYYMMDD-NN.md` using the template below.
5. **Handle failures**: route failed items back to `modification-guide` to generate fixes, forming a loop, until all pass or the user accepts.

