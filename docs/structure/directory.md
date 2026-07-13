# Directory Structure

Answers: FR-12 (CLI layout), NFR maintainability, build-guide §2.

## Tree
```
ai-sdlc-runner/
├── AGENTS.md                  # AI entry anchor (any agent, any vendor): handshake order, governance map, non-negotiables; CHG-20260706-01
├── README.md                  # positioning + "depends on ai-skills contract v1, per-project major.minor lock"
├── .gitignore                 # Python
├── .gitmodules                # declares the ai-skills submodule (pinned to tag v1.0.0)
├── pyproject.toml             # deps & entry point (runner = ai_sdlc_runner.cli:main)
├── skills/                    # PRIMARY offline skill store (CHG-05, CHG-20260703-01, CHG-20260703-06): v1.0.0/, v1.1.0/, v1.12.1/, v1.16.0/ (vendored verbatim)
│   ├── v1.0.0/                 #   full skill root (SKILL.md, references/, scripts/, assets/)
│   ├── v1.1.0/                 #   + role catalog (role_loadout.py, role_refs.json)
│   ├── v1.12.1/                #   offline `git archive` @ 605425e
│   └── v1.16.0/                #   current baseline (config default); offline `git archive` @ b4d6ef3
├── ai-skills/                 # OPTIONAL git submodule fallback (not pulled by default); pinned ai-sdlc-v1.0.0
├── src/ai_sdlc_runner/
│   ├── __init__.py
│   ├── cli.py                 # entry: run / migrate / status subcommands
│   ├── contract.py            # read skill version, per-project lock, migrate
│   ├── agents.py              # parse role table, spawn by role (tools/permissions)
│   ├── gates.py               # call skill's halt_gate.py / cross_repo_check.py
│   ├── state.py               # checkpoint / resume (state.json)
│   ├── orchestrator.py        # main loop: four stages sequential + shallow fan-out (emits events)
│   ├── tui.py                 # interactive menu (stdlib curses + numbered fallback); CHG-02
│   ├── dashboard.py           # multi-panel view (status/log/verify/agents); curses + snapshot; CHG-03
│   ├── skillstore.py          # offline multi-version skill store resolver (by project lock); CHG-05
│   ├── executors.py           # pluggable agent backends: stub | command(subscription) | api; CHG-06
│   ├── workspace.py           # multi-project workspace: authority(main) + consumers, persisted; CHG-08
│   └── structure_scan.py      # structure analysis: scan + scaffold 4 structures + authority/pointers; CHG-08
├── config/
│   └── runner.yaml            # contract version, skill path, concurrency/depth limits
├── docs/
│   ├── ARCHITECTURE.md         # handover-oriented architecture & feature overview (non-canonical map; canon lives in the files below)
│   ├── ai-guideline.md
│   ├── structure/{directory,logical,design,data}.md
│   ├── changes/CHG-*.md
│   ├── acceptance/ACC-*.md
│   └── knowledge/             # pre-founded knowledge base: knowledge.md (INDEX-first, zero entries at bootstrap) + vocabulary.json (tag registry); CHG-20260706-01
└── tests/
    ├── conftest.py            # shared pytest fixtures
    ├── test_contract.py       # version-lock and migrate decisions
    ├── test_skillstore.py     # offline multi-version skill store resolver; CHG-05
    ├── test_executors.py      # pluggable agent backends (stub/command/api); CHG-06
    ├── test_workspace.py      # multi-project workspace authority/consumers; CHG-08
    ├── test_tui.py            # interactive menu (curses + numbered fallback); CHG-02
    └── test_dashboard.py      # multi-panel dashboard view; CHG-03
```

## Responsibility per directory
| Path | Responsibility | Notes |
|------|----------------|-------|
| `src/ai_sdlc_runner/` | The runner package (all driver logic) | One module per concern |
| `ai-skills/` | Read-only reference to the skill (submodule) | Never modified; never copied from |
| `config/` | Runtime-variable settings (limits, paths) | Isolated from the contract |
| `docs/` | ai-sdlc governance artifacts for this repo | Dogfooding |
| `tests/` | Unit tests for contract/lock/migrate | pytest |

## Naming & placement rules
- One responsibility per module file; no module re-implements skill logic.
- The submodule lives at repo root as `ai-skills/`; `skill_path` in config points inside it.
- Governance docs follow the ai-sdlc convention under `docs/` (guideline, structure, changes, acceptance).
- Lock files (`.sdlc-lock.json`) belong to the *governed project*, never to this runner repo.
