## Location: `docs/` by default, switch only when occupied

| Situation | Location |
|---|---|
| `docs/` absent, or present and empty | **`docs/`** (unchanged default) |
| `docs/` already occupied | **`sdlc_docs/`** |

**Occupancy signals** (any one counts):

- A site generator config: `mkdocs.yml`, `docusaurus.config.*`, `_config.yml`, `conf.py`
  (Sphinx), `book.toml` (mdBook), or a repo setting that publishes `docs/` as the Pages source.
- Generated-output markers: `docs/_build/`, `docs/.doctrees/`, `docs/site/`, or a `.gitignore`
  entry covering part of `docs/`.
- `docs/` already holds content that isn't ours, and none of it is a ledger.

**The location always goes into the Guideline header — declared, not inferred.** The next agent
should not have to decide again; a judgement varies with the environment, a declaration does not.

