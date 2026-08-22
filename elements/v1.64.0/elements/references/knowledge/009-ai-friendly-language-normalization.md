## AI-friendly language (normalization)

Structure isn't enough — the words matter too:

- **tags: lowercase English, fixed vocabulary.** Cheap tokens, stable grep, cross-model (see platform neutrality); CJK word-boundary ambiguity hurts retrieval.
- **Rule line: normalized.** Imperative mood, one rule per entry, **testable wording** ("always X" — never "prefer X when possible"), no ambiguous pronouns; when a rule invites misreading, add one positive and one negative example.
- **No source quotes** (deprecated): the rule is what the user confirmed at recording time — that's the fidelity mechanism; later disputes re-consult the user (triple confirmation), and git history already archives every version of the entry. A quote inside the entry is a second, never-updated representation (a drift surface) and the biggest PII vector in the knowledge base. `evidence` (CHG ids) carries traceability.
- The shallow → deep promotion includes a **language-normalization pass** — cleaning the wording is part of the promotion ritual.

- Read it on entry (handshake); planning and implementation must obey current directives.
- **When the knowledge base conflicts with a new user request** (the new request would violate a directive): **do not decide unilaterally** (neither silently follow knowledge nor silently follow the new request). Use **triple confirmation + impact disclosure**:
  1. **First**: point out the conflict — "this contradicts DIR-x '…'", and **explain the impact** (what it touches, why it was set, the risk).
  2. **Second**: ask the user to explicitly override that rule (not offhand), listing the affected scope again.
  3. **Third**: final confirm "override DIR-x for sure?"; only proceed on a yes.
- All three confirmed → proceed, and **update the knowledge base**: mark that directive "overridden/relaxed by user on <date> (reason)" or rewrite the rule; not silently ignored.
- If any of the three isn't clearly confirmed → keep the directive, don't do the conflicting action.

> Why three: overturning a high-priority rule should be a deliberate, traceable decision, not a one-liner reversal; triple confirmation + impact disclosure lets the user decide fully informed and leaves a record.

