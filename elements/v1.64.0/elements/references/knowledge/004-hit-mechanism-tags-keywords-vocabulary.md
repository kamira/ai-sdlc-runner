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

