---
name: knowledge
description: >
  Knowledge base governance: record "errors hit during execution", "user correction directives",
  and "AI-observed recurring patterns" (autonomous shallow records that promote to deep after
  repeated uncorrected use) so the AI doesn't repeat mistakes or re-ask settled things; when a
  rule is updated, overwrite in place (no contradictory duplicates); the knowledge base is a
  high-priority rule set with an INDEX for scoped retrieval — read the index and load only the
  entries in scope, never the whole file. Read this when you receive a correction, when the same
  need/purpose recurs across CHGs/requirements, before entry, or when a request conflicts with a
  known rule. Distinction: requirement changes go through modification-guide; rules live here.
---

# knowledge — error & correction-directive knowledge base

> 語言 / Language: [繁體中文](knowledge.zh-tw.md) · **English**

## Purpose

The knowledge base is the durable memory that keeps the AI from repeating the same mistakes. Two entry types:

- **error**: technical errors hit during execution and their fixes (from agent-worklog).
- **directive (DIR)**: an **explicit user correction** — "don't use X", "do it this way", "I told you before". This is **not a requirement change** (those go through modification-guide as a CHG); it corrects "approach/style/taboo" and must be recorded so it isn't repeated.
- **pattern record (KN)**: an **AI-observed recurrence** — the same need/purpose keeps showing up across CHGs/requirements. Recorded **autonomously** as a shallow record, promoted to deep by uncorrected use (see lifecycle below).

- **Interaction rules are first-class**: how the user prefers to deliver instructions, confirmation style, communication adjustments — these are DIR/KN entries like any other, tagged `interaction`. Even "the way instructions are given needs adjusting" is knowledge.

Location: `docs/knowledge/` (suggest `errors.md`, `directives.md` — or a combined `knowledge.md` with an INDEX). **Founded at project start** (created with `docs/` during requirement analysis — an empty INDEX is a valid knowledge base; don't wait for the first correction). **Read the index on entry, load only in-scope entries** (see retrieval below and handshake).

## Recording correction directives (req 3)

When you receive a user correction (not a requirement change), **write it into the knowledge base immediately**, not just fix it in the moment:

```markdown
## DIR-<n> — <one-line rule>
- date / branch: YYYY-MM-DD (UTC+0) / <branch>
- context: <when it applies>
- rule: <do / don't>
- reason: <why (user's reason or inferred)>
- confidence: user-confirmed / agent-inferred   ← who established the rule (see priority below)
- status: active
```

## Updating an existing directive (req 4)

When a directive is **updated later**, **rewrite the existing entry, don't add a contradictory new one**:

- Find the matching DIR entry → update the rule; move the old wording to "history" or mark it superseded, keeping dates.
- Goal: each rule always has exactly **one current version**, so the knowledge base doesn't contradict itself (that would be a form of drift).
- If the new directive conflicts with the old, the new wins and record "supersedes DIR-x (reason)".

## Hit mechanism (tags + keywords + vocabulary)

Retrieval needs a **contract**, not intuition. Two axes and a bridge:

- **`tags` = classification axis**: controlled vocabulary, lowercase English — the INDEX's primary key.
- **`keywords` = hit axis** (optional field): free language, **any language** — the user's original words, API names, error strings. Surfaced as an INDEX column so matching happens from the index alone.
- **`docs/knowledge/vocabulary.json` = the bridge and the registry**: tag → aliases. It normalizes free task words into controlled tags, and it's what makes "fixed vocabulary" actually fixed — the lint fails an entry whose tag isn't registered (and fails loud on an unparseable vocabulary). No vocabulary file = exempt (tiny projects).

```json
{
  "_doc": "tag registry + alias bridge: key = controlled tag, values = aliases in any language",
  "payment": ["金流", "付款", "pay", "billing"],
  "report": ["報表", "匯出", "export"]
}
```

**Hit procedure**: task-side keys = branch + structural location + file-path segments + requirement nouns → normalize through the aliases → intersect with INDEX `tags`; additionally, raw task text substring-matches the `keywords` column. **Recall over precision**: over-hit and filter after reading (entries are small); a missed rule is the expensive failure. Hitting 20+ entries still means the tags are too broad.

**Database-like, deliberately not a database**: filename = primary key, schema = DDL, fail-loud lint = constraints, INDEX = materialized view, vocabulary = dimension table. The storage engine stays plain text because git mergeability, direct AI readability, and reviewable diffs are non-negotiable — a binary store breaks all three. (At thousands of entries, a script may load entries into a **derived, disposable** query cache — never the source of truth.)

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

## Autonomous triggering (shallow records)

Don't wait to be corrected — **the same need/purpose appearing a second time across CHGs/requirements triggers a shallow record** (threshold 2, adjustable). It may span sessions, so **the evidence and counters live in the entry, not in memory**. Checked at CHG close-out (see modification-guide): does this change's motive repeat a prior CHG's?

```markdown
## KN-<n> — <one-line rule hypothesis>
- tier: shallow / deep(+ promotion date)
- date / branch: YYYY-MM-DD (UTC+0) / <branch or all-branches>
- tags/scope: <module / topic — lowercase English, fixed vocabulary; these are the retrieval keys>
- evidence: <CHG-… ids / requirement mentions (≥2 occurrences)>
- counters: seen <n> / applied <n> / last-applied <date>
- status: observing / active / retired (reason)
```

## AI-friendly structure & scoped retrieval (INDEX)

Nobody reads the whole knowledge base — that's catalog-thinking. The file **starts with an INDEX**; entries are anchored sections with `tags/scope`:

```markdown
## INDEX (read this, not the whole file)
| id | tier | tags/scope | one-line rule | status |
|----|------|-----------|---------------|--------|
| DIR-1 | user-confirmed | all-branches · api | amounts always integer minor units | active |
| KN-2 | deep | report | exports always UTF-8 BOM | active (applied 5) |
| KN-3 | shallow | payment | prefer dry-run first | observing (seen 2 / applied 1) |
```

Retrieval rule (entry and dispatch alike): read the INDEX → load **global entries + entries whose tags intersect your current scope** — nothing else. Dispatch briefings carry the matching entries the same way (see handshake's scoped tier).

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

  Schema: [`assets/knowledge_entry.schema.json`](../assets/knowledge_entry.schema.json) — required `id/tier/rule/tags/status`, enum-checked. The lint validates **fail-loud**: an unparseable or invalid entry blocks the commit rather than being skipped — a silently dropped rule is worse than a blocked commit.
- **INDEX becomes a generated artifact**: `docs/knowledge/INDEX.md`, regenerated from entry metadata by `scripts/knowledge_index.py` — **never hand-edited** (hand-maintained copies drift; generated ones can't). `--check` verifies freshness; the doc-integrity lint cross-checks entry files ↔ INDEX ids both ways.
- Retrieval is unchanged and mode-agnostic: read the INDEX (file-top section in single-file mode, `INDEX.md` in split mode) → load only in-scope entries.
- **Division of labor (context & hallucination)**: bulk parsing belongs to the **scripts** — the index generator, lint, and health each read *every* JSON deterministically, at **zero model-context cost**. The model never loads all entries: it reads the generated INDEX (≈1 line per entry) and then the **few in-scope files** (typically 3–5). Net context *shrinks* as the base grows — menu + a handful of entries beats one ever-growing file — and fixed keys/enums leave far less room for misreading than prose. If one task matches 20+ entries, the tags are too broad: tighten the vocabulary, don't load more.

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

## Relation to the rest of the flow

- With agent-worklog: worklog collects "errors"; this file spells out KB governance (directives, updates, priority, conflict); the parent agent consolidates errors and directives here.
- With handshake: the KB is a required read on entry.
- With modification-guide: **requirement change → CHG**; **correction directive → knowledge**. Keep them separate.
- With branch-isolation: tag directives with a branch; cross-branch reference follows the requirement rule (default: current branch only; a general rule may be tagged "all branches").
