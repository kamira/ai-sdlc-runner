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

