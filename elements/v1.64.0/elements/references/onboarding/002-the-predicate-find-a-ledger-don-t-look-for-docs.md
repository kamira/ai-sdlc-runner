## The predicate: find a ledger, don't look for `docs/`

**`docs/` is not an identity.** It is the location this process *proposes*, not one that is
guaranteed to exist or to be ours. The skill itself says "if the target project already has a
documentation convention, follow that". And `docs/` is one of the most common directory names in
software:

| Someone else's use | What writing the ledger there does |
|---|---|
| Publish root (MkDocs / Docusaurus / Jekyll / Pages source) | CHG/ACC get built into the site nav as user-facing product pages; generators that require front matter **fail the build** |
| Generated output (Sphinx build, generated API docs) | The next regeneration **deletes the ledger**, silently |
| Another agent convention's territory | The two overwrite each other |

The second row is **data loss**, not disclosure — a governance ledger is meant to be public; the
problem was never confidentiality.

**`AGENTS.md` is not an identity either**: it is now a cross-vendor convention that other tools
also write.

The only unambiguous marker is **the ledger itself** — a directory holding
`CHG-YYYYMMDD-NN.md`, wherever it lives. Machine assist:
`doc_integrity_check.ledger_roots(repo)`, whose candidate roots come from `DOC_ROOT_NAMES`
(data, not a hardcoded line). **Not found returns an empty list, never an assumption** —
"assume `docs/` when nothing is found" makes callers scan zero files and then report no
problems, and nobody investigates a green light (the mirror of KN-001).

