## Workflow

1. **Read existing context**: if the project already has `docs/ai-guideline.md`, read it first to avoid duplication or conflict.
2. **Clarify, don't assume**: proactively ask about key unknowns — goals, users, scale, constraints, deadlines, tech preferences, acceptance criteria. Ask the important things; don't drown the user in a wall of questions at once.
3. **Consolidate**: split the conversation into functional and non-functional requirements; flag assumptions and open items.
4. **Produce the Guideline**: write `docs/ai-guideline.md` using the template below.
5. **Hand back for confirmation**: ask the user to confirm the Guideline before entering structure design.

**Elicitation by proxy (when subagents can be dispatched)**: the **decision agent does not conduct the user Q&A**. The elicitor (A1) owns the whole conversation — asks, iterates until the requirement is **fully understood** (open items resolved or explicitly deferred) — then hands up a **proposal (企劃)**: the draft Guideline + resolved clarifications + an impact sketch. The decision agent reads **the proposal, not the transcript** (transcripts replicate anchoring — the same reason verifiers never get the implementer's narrative), and convenes the review panel on it (decision quota ≥5, see review-panel). This separates *information gathering* from *adjudication*; the **confirm gate still goes to the user directly** — approval authority is never proxied. No spawn available → the same agent asks and decides, and notes that limitation in the record.

**Knowledge bootstrap (founded before work, not lazily)**: creating `docs/` includes creating `docs/knowledge/` **at this stage** — an empty INDEX (+ a vocabulary stub) is a valid knowledge base. Don't wait for the first correction: interaction-style observations count from the very first exchange — even "how the user prefers to deliver instructions needs adjusting" is a knowledge entry (tag `interaction`; see knowledge).

