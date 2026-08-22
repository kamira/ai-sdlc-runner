## Priority and conflict handling (req 5)

The knowledge base is a **high-priority rule set**, not optional advice — it represents "the user already taught this; don't repeat it".

**Confidence & lifecycle (one ladder, pollution-guarded)**: since every later session obeys this file, a wrong or over-generalized entry poisons everything downstream. Every rule sits on one ladder:

| Tier | Who established it | Behavior | Overriding it |
|------|--------------------|----------|---------------|
| **shallow** (KN) | AI observed a recurrence — a **hypothesis** | apply + **announce each use**; every uncorrected use increments `applied` | one plain user sentence |
| **deep** (KN) | shallow that survived use (`applied ≥ 3`, no correction) | apply by default **without per-use announcement**, but listed in the handshake ack | one plain user sentence |
| **user-confirmed** (DIR) | the user said it explicitly (or confirmed a KN) | binding | triple confirmation below |

- **Promotion**: shallow → deep when `applied ≥ 3` with no correction (threshold adjustable; record the promotion date). KN → DIR only via an **actual user statement** — never self-promote.
- **Demotion**: a corrected deep record drops back to shallow or is retired (root cause noted); if the correction states a rule, that becomes a DIR (the reverse got established).
- Agents must never record an entry as user-confirmed without an actual user statement.

