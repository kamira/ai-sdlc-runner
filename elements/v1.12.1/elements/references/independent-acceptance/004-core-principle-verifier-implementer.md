## Core principle: verifier ≠ implementer

Assign an **independent agent** to do acceptance, and:
- **Role = verifier, permission = read-only**: the verifying agent may only **read** the code under review and the criteria, and may only **write** its own ACC report; it **must not modify the code or structure docs under review**. Once the verifier can edit code, it "fixes things while verifying" — losing independence and possibly planting new issues. Found a problem → record it in the ACC → return to `modification-guide` for the implementer role to fix, not the verifier.
- Give it only the **source of the criteria** (Guideline §7 / the CHG's goal and acceptance criteria) + the **result (code/system)**.
- Do **not** give it the implementer's reasoning or "I think this is right" narrative — that would lead it along and replicate the same blind spots.
- Trace criteria back to the **source docs / user requirement**, not the implementer's self-report.

