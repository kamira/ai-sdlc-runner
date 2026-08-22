## Scale: per-entry files (split mode)

Past **~30 entries** a single file becomes a liability: it's the single-writer hotspot under parallel agents, a merge-conflict magnet across branches, and the `applied` counters make its diffs noisy; a hand-maintained INDEX starts drifting from the entries. At that point **split**:

- **One entry per file, canonical format = JSON**: `docs/knowledge/entries/KN-004.json` (filename = id = the first-level filter; retired → `entries/archive/`). JSON because parsing is binary — success or a **loud failure**, never a silent reinterpretation. Not YAML: implicit typing (`1.10`→`1.1`, `no`→`false`) is exactly the misreading this exists to eliminate; not regex-parsed markdown: tolerant parsing is where misreads breed. Comments live in fields (`note`, `reason`), not syntax. Legacy `.md` entries are still read during migration.

```json
{
  "id": "KN-004",
  "tier": "shallow",
  "rule": "always export CSV as UTF-8 with BOM",
  "tags": ["report", "export"],
  "branch": "all",
  "date": "2026-07-03",
  "evidence": ["CHG-20260615-02", "CHG-20260702-01"],
  "counters": {"seen": 2, "applied": 0, "last_applied": null},
  "status": "observing",
  "note": "comments are fields, not syntax"
}
```

<!-- claim: knowledge-lint-fail-loud -->
  Schema: [`assets/knowledge_entry.schema.json`](../assets/knowledge_entry.schema.json) — required `id/tier/rule/tags/status`, enum-checked. The lint validates **fail-loud**: an unparseable or invalid entry blocks the commit rather than being skipped — a silently dropped rule is worse than a blocked commit.
- **INDEX becomes a generated artifact**: `docs/knowledge/INDEX.md`, regenerated from entry metadata by `scripts/knowledge_index.py` — **never hand-edited** (hand-maintained copies drift; generated ones can't). `--check` verifies freshness; the doc-integrity lint cross-checks entry files ↔ INDEX ids both ways.
- Retrieval is unchanged and mode-agnostic: read the INDEX (file-top section in single-file mode, `INDEX.md` in split mode) → load only in-scope entries.
- **Division of labor (context & hallucination)**: bulk parsing belongs to the **scripts** — the index generator, lint, and health each read *every* JSON deterministically, at **zero model-context cost**. The model never loads all entries: it reads the generated INDEX (≈1 line per entry) and then the **few in-scope files** (typically 3–5). Net context *shrinks* as the base grows — menu + a handful of entries beats one ever-growing file — and fixed keys/enums leave far less room for misreading than prose. If one task matches 20+ entries, the tags are too broad: tighten the vocabulary, don't load more.

