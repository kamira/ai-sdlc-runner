## Cross-repo anti-drift (extends doc-integrity)

Each repo's doc verification additionally compares: **does the local "authority pointer version" equal the authority's current contract version?** Behind = cross-repo drift (that repo is still on an old contract) and must catch up.

**Executable check**: this skill bundles `scripts/cross_repo_check.py`, which reads each repo's pinned version in `docs/authority.md` vs the authority's `docs/contracts/VERSION`; on mismatch it reports and exits non-zero (wire it into pre-commit / CI). Usage:

```bash
python3 scripts/cross_repo_check.py manifest.json
# manifest.json: { "authority": "authority-repo", "repos": ["repoA","repoB"] }
```

See the `examples/ai-sdlc/cross-repo/` template project in the repo (authority + two consumer repos + an XCHG example).

