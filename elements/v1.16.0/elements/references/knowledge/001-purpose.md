## Purpose

The knowledge base is the durable memory that keeps the AI from repeating the same mistakes. Two entry types:

- **error**: technical errors hit during execution and their fixes (from agent-worklog).
- **directive (DIR)**: an **explicit user correction** — "don't use X", "do it this way", "I told you before". This is **not a requirement change** (those go through modification-guide as a CHG); it corrects "approach/style/taboo" and must be recorded so it isn't repeated.
- **pattern record (KN)**: an **AI-observed recurrence** — the same need/purpose keeps showing up across CHGs/requirements. Recorded **autonomously** as a shallow record, promoted to deep by uncorrected use (see lifecycle below).

- **Interaction rules are first-class**: how the user prefers to deliver instructions, confirmation style, communication adjustments — these are DIR/KN entries like any other, tagged `interaction`. Even "the way instructions are given needs adjusting" is knowledge.

Location: `docs/knowledge/` (suggest `errors.md`, `directives.md` — or a combined `knowledge.md` with an INDEX). **Founded at project start** (created with `docs/` during requirement analysis — an empty INDEX is a valid knowledge base; don't wait for the first correction). **Read the index on entry, load only in-scope entries** (see retrieval below and handshake).

