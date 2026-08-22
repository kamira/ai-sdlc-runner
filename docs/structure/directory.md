# Directory Structure

Answers: FR-16 (CLI surface), and the maintainability NFR.

**CHG-20260823-01 removed the skill dependency**, and with it roughly half this tree: the vendored
store, the derived element tree, and every module that existed to read or call a skill. What is left
is what the runner actually is.

## Tree
```
ai-sdlc-runner/
├── AGENTS.md                  # AI entry anchor: handshake order, governance map, non-negotiables
├── README.md
├── .github/
│   └── workflows/ci.yml       # pytest on {ubuntu,windows} × py{3.9,3.13} + the ledger gate
├── pyproject.toml             # deps & entry point (runner = ai_sdlc_runner.cli:main)
├── requirements-dev.txt       # derived, probe-facing view of pyproject's optional-dependencies
├── tools/
│   └── ledger_check.py        # this repo's own ledger lint; CHG-20260823-01
├── src/ai_sdlc_runner/
│   ├── policy.py              # THE GOVERNANCE: roles, capabilities, gates, seats, permanent halts
│   ├── graph.py               # THE FLOW: 23 nodes, one kind of work each, designed from the flowchart
│   ├── engine.py              # walks the flow; one session per ask, opened and closed around it
│   ├── workorder.py           # renders one node's order: closed schema, no harness-specific field
│   ├── effects.py             # ordered effects, each admitted only if probeable
│   ├── probes.py              # postconditions read from the world: git, the forge, the ledger
│   ├── ship.py                # the ordered ship sequence, each effect paired with its probe
│   ├── cli.py                 # flow / policy / run
│   └── tui.py                 # the interactive selector, and the high-risk-mode toggle
├── docs/ARCHITECTURE.md       # the overview; the structure docs below carry the detail
├── config/
│   └── runner.yaml            # dispatch settings only — no skill path, because there is no skill
└── docs/
    ├── ai-guideline.md
    ├── structure/{directory,logical,design,data}.md
    ├── changes/CHG-*.md
    ├── acceptance/ACC-*.md
    ├── knowledge/
    └── worklog/
```

## Responsibility per directory
| Path | Responsibility | Notes |
|------|----------------|-------|
| `src/ai_sdlc_runner/` | The runner: its governance, its flow, and the machinery to walk it | One responsibility per module |
| `tools/` | Repo-level checks that are not part of the runner's runtime | Stdlib only |
| `config/` | What genuinely varies between machines and runs | Dispatch settings |
| `docs/` | ai-sdlc governance artifacts for this repo | Dogfooding |
| `tests/` | | pytest |
| `.github/workflows/` | Mechanical verification of every PR and push to `main` | Tests + the ledger gate. Not gated on a coverage % — see CHG-20260817-10 |

## Naming & placement rules
- One responsibility per module file.
- **No skill content, and nothing that reaches for one.** Two tests assert it:
  `test_no_file_reaches_for_a_skill` scans source, tools, tests, packaging, the README and CI —
  docstrings and comments included, and itself — while `test_no_skill_content_is_stored_in_the_repo`
  checks the stronger claim that no copy exists to read.
- Governance values live in `policy.py` with a reason written next to each.
- Governance docs follow the ai-sdlc convention under `docs/`.
