## Guideline maintenance (revise after any change)

The Guideline is a living document, not one-off: **whenever the structure is adjusted or requirements change, the existing Guideline must be revised in sync and bumped** (update the affected FR/scope/acceptance criteria, version +1, note it in the change history). The modification flow (modification-guide) checks at close-out that the Guideline kept up; doc verification (doc-integrity) treats "Guideline lagging behind the agreed structure/requirements" as drift. A stale Guideline misleads every later stage.

**Major revision (pivot)**: when the requirement fundamentally changes direction, don't rewrite history — bump the Guideline a **major** version; mark dropped FRs **deprecated (date + superseded-by)** instead of deleting them; **never reuse FR ids**. Old CHG/ACC remain valid **against the Guideline version they cite** (records carry dates and versions, so the old trail still reads correctly); only new work aligns to the new version. The pivot itself goes through modification-guide — it is a change, usually high-risk.

