## Core principle: docs/ is the single source of truth between agents

Don't pass state between agents through conversation memory — it can't cross agents and gets compacted. Every agent **reads `docs/` on entry** (echoing this skill's "Session startup check" and the principle "don't rely on memory, rely on the docs"). The precondition for the next agent to continue is that the previous agent wrote the full state into the docs.

