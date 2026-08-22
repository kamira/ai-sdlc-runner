## Workflow

1. **Read the baseline**: read `docs/ai-guideline.md` and `docs/structure/*.md` to grasp the current state. If these don't exist, create them first (return to the matching skill) or note the gap in the record. **If you entered because acceptance failed, first read the relevant `docs/acceptance/ACC-*.md` and treat its unmet items as the target list for this fix.**
2. **Impact analysis**: determine which modules, components, data, and interfaces this change touches, plus knock-on effects (dependency direction, compatibility, data migration).
3. **Produce the modification guide**: use the template below to write concrete, executable steps so an implementer (human or AI) can just follow them.
4. **Adjust structure documents**: if the change alters the structure, **update** the corresponding files under `docs/structure/` — structure docs must always reflect the latest truth.
5. **Leave a change record**: add a record under `docs/changes/` (see template), stating motivation and trade-offs clearly. For a fix driven by failed acceptance, link back to that ACC report in the record's "Related" field.
6. **Close acceptance in the same round (no handoff)**: once implemented, **immediately produce the matching `docs/acceptance/ACC-*.md` via `acceptance-verification` within the same round**, and update this CHG's status to "Accepted" with a link to the ACC. **Do not just mark it "pending acceptance" and stop** — in cross-session work the next session brings a new requirement, nobody comes back to do a deferred acceptance, so it hangs forever. **If items still fail, return to step 1, forming a "fix → re-implement → re-verify" loop until everything passes or the user explicitly accepts.**

