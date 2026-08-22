## Relation to the rest of the flow

- Risk source: the CHG risk field in `modification-guide` / the ACC risk field in `acceptance-verification`.
- With `agent-hierarchy`: in an autonomous org, the parent agent checks the halt contract at each gate to decide whether to report to the human.
- With `ci-cd`: halt points govern "mid-autonomous-run"; CI gates govern "commit/merge". Both can coexist.
