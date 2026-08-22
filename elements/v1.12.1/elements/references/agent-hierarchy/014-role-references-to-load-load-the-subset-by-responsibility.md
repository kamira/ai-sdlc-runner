### Role → references to load (load the subset by responsibility)

When starting a role, load the **common set** first, then that role's **base set**, then add situational ones by detection:

**Common set (loaded by every role on entry)**: `handshake` · `knowledge` · `doc-integrity`.

| Role | Base load (beyond common) | Add when detected |
|------|---------------------------|-------------------|
| orchestrator | agent-hierarchy · agent-worklog · autonomy | all, as needed |
| analyst (A1) | requirement-analysis · structure-design | multi-repo→cross-repo; multi-branch→branch-isolation |
| lead-implementer (I1) | modification-guide · structure-design · agent-hierarchy · agent-worklog | multi-repo→cross-repo; CI→ci-cd; multi-branch→branch-isolation |
| sub-implementer (I1.x) | modification-guide · agent-worklog | — |
| verifier (V1) | acceptance-verification · independent-acceptance | multi-branch→branch-isolation |
| integrator | independent-acceptance · cross-agent | — |
| reviewer | independent-acceptance | — |
| panel seat (seat-*) | review-panel + its one domain ref (risk/impact→modification-guide; drift→doc-integrity; compliance→knowledge; security→autonomy; consistency→branch-isolation·cross-repo) | — (read-only, no spawn) |

Situational adds (detection flags): multi-repo→`cross-repo`, multi-branch→`branch-isolation`, parallel/handoff→`cross-agent`, autonomous run→`autonomy`, CI/CD→`ci-cd`.

> **Machine-readable**: the machine version of this table is [`assets/role_refs.json`](../assets/role_refs.json) (**the JSON is the program's single source of truth; this table is its human view — keep them consistent**). An external orchestrator can query [`scripts/role_loadout.py`](../scripts/role_loadout.py): `python3 scripts/role_loadout.py --role verifier`, `--role I1 --multi-repo --cicd` (prints the load list; `--json` for programs).

