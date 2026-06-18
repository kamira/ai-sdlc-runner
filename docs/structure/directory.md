# Directory Structure

Answers: FR-12 (CLI layout), NFR maintainability, build-guide §2.

## Tree
```
ai-sdlc-runner/
├── README.md                  # positioning + "depends on ai-skills contract v1, per-project major.minor lock"
├── .gitignore                 # Python
├── .gitmodules                # declares the ai-skills submodule (pinned to tag v1.0.0)
├── pyproject.toml             # deps & entry point (runner = ai_sdlc_runner.cli:main)
├── skills/                    # PRIMARY offline skill store (CHG-05): v1.0.0/, v1.1.0/ (vendored verbatim)
│   ├── v1.0.0/                 #   full skill root (SKILL.md, references/, scripts/, assets/)
│   └── v1.1.0/                 #   + role catalog (role_loadout.py, role_refs.json)
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
│   └── skillstore.py          # offline multi-version skill store resolver (by project lock); CHG-05
├── config/
│   └── runner.yaml            # contract version, skill path, concurrency/depth limits
├── docs/
│   ├── ai-guideline.md
│   ├── structure/{directory,logical,design,data}.md
│   ├── changes/CHG-*.md
│   └── acceptance/ACC-*.md
└── tests/
    └── test_contract.py       # at least version-lock and migrate decisions
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
