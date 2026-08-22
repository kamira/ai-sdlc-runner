## Coordinated change template (XCHG)

At the authority `docs/changes/XCHG-YYYYMMDD-NN.md`:

```markdown
# XCHG-YYYYMMDD-NN — <cross-repo change title>

- Authority: <authority repo / contract path>
- Repos involved: <repoA, repoB, ...>
- Risk: high / medium / low
- Contract version: vN → vN+1 (what contract changed)
- Per-repo child changes: repoA → CHG-...; repoB → CHG-...
- Integration acceptance: <integration ACC link>
- Status: draft / implementing across repos / integration accepted

## Motivation / overall intent
...
## Per-repo impact and order
<who changes first; contract compatibility and migration>
```

