### Role → references to load (load the subset by responsibility)

When starting a role, load only that role's subset of references (its base set), then add situational ones by detection:

| Role | Base load (references) | Add when detected |
|------|------------------------|-------------------|
| orchestrator | agent-hierarchy · agent-worklog · autonomy · doc-integrity | all, as needed |
| analyst (A1) | requirement-analysis · structure-design · doc-integrity | multi-repo→cross-repo |
| lead-implementer (I1) | modification-guide · structure-design · agent-hierarchy · agent-worklog · doc-integrity | multi-repo→cross-repo; CI→ci-cd |
| sub-implementer (I1.x) | modification-guide · agent-worklog | — |
| verifier (V1) | acceptance-verification · independent-acceptance · doc-integrity | — |
| integrator | independent-acceptance · cross-agent · doc-integrity | — |
| reviewer | doc-integrity · independent-acceptance | — |

Situational adds (detection flags): multi-repo→`cross-repo`, parallel/handoff→`cross-agent`, autonomous run→`autonomy`, CI/CD→`ci-cd`.

> **Machine-readable**: the machine version of this table is [`assets/role_refs.json`](../assets/role_refs.json) (**the JSON is the program's single source of truth; this table is its human view — keep them consistent**). An external orchestrator can query [`scripts/role_loadout.py`](../scripts/role_loadout.py): `python3 scripts/role_loadout.py --role verifier`, `--role I1 --multi-repo --cicd` (prints the load list; `--json` for programs).

