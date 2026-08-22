## This is unit/build level — not the operational test

The task `test:` line proves **the part is correct** (RED-GREEN). It is **not** the operational acceptance test — that runs the whole change for real and lives in the plan's `### Acceptance operation` section, gated at the end of the run (see autopilot-loop's operational verify). All tasks green is necessary, not sufficient; a code CHG still can't reach ACC without an operational test on record.
