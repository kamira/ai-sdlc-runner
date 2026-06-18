# AI Guideline — ai-sdlc-runner

- Project: ai-sdlc-runner
- Version: v1.0
- Date: 2026-06-17
- Status: Confirmed
- Source requirement: `ai-sdlc-runner-build-guide.md` (the build guide is the requirement input for the first runner)

## 1. Background & Goals

Building the first `ai-sdlc-runner`: an **external Python orchestrator** that drives the `ai-sdlc`
skill through a semi-autonomous development loop (requirement analysis → structure design →
implement → acceptance), stopping at gated halt-points for human approval.

Core positioning: **the skill stays pure (markdown + zero-dependency gate scripts); the runner is
an external driver. The skill does not know the runner exists.** Dependency is strictly one-way.

Success = a runner that (a) references — never copies — the skill via a pinned submodule, (b) reads
all governance logic (halt-points, role definitions, CHG/ACC fields) from the skill rather than
re-implementing it, (c) locks the contract at `major.minor` per governed project with a validating
`migrate`, (d) runs the four stages sequentially with shallow per-stage fan-out, and (e) mechanically
locks down the V1 verifier's tool layer. This repo is itself governed by ai-sdlc (dogfooding).

## 2. Scope

### In scope
- The runner Python package per build-guide §2/§3: `cli`, `contract`, `agents`, `gates`, `state`, `orchestrator`.
- `config/runner.yaml`, `pyproject.toml`, `README.md`, `tests/test_contract.py`.
- Governance docs for this repo: `docs/ai-guideline.md`, `docs/structure/*.md`, `docs/changes/CHG-*.md`, `docs/acceptance/ACC-*.md`.
- Submodule scaffolding (`.gitmodules`) expecting `ai-skills` pinned to tag `v1.0.0` (the submodule itself is provided by the user).

### Out of scope (explicitly excluded)
- Re-implementing any skill logic (halt matrix, role table, CHG/ACC field lists) inside the runner.
- Copying any skill markdown into the runner.
- The §4 autonomous loop as a *build step* — §4 is the runner's runtime behavior spec (a product to implement), not how the first runner is built.
- Driving real deployment/migration/deletion/money/secret/publish actions automatically — these always halt for a human.
- Pinning the submodule to `main` or any floating branch.
- Any browser storage / frontend concern (pure backend Python tool).

## 3. Stakeholders

| Role | Concern |
|------|---------|
| Runner author (human-in-the-loop) | Builds the first runner via ai-sdlc four stages; approves at halt-points |
| ai-skills maintainer | Owns the contract surface (skill version, scripts, role table); provides the pinned submodule |
| Governed-project teams | Future consumers whose projects the runner will drive via the §4 loop |
| V1 verifier (independent role) | Accepts the runner against §6 criteria; read-only, no Agent tool |

## 4. Functional Requirements

| ID | Requirement | Priority | Notes |
|----|-------------|----------|-------|
| FR-1 | `contract.read_skill_version(skill_path)` reads the skill version from SKILL.md frontmatter (`version` or `metadata.version`) | P0 | Version detected from file, not from a git tag |
| FR-2 | `contract.contract_key(ver)` reduces `"1.2.3"`→`(1,2)`, ignoring patch | P0 | Lock granularity is major.minor |
| FR-3 | `contract.resolve_contract(project, requested)` writes `<project>/.sdlc-lock.json` on first run; on later runs rejects a differing `(major,minor)` with a migrate prompt; same/unspecified continues the locked version | P0 | per-project lock |
| FR-4 | PATCH differences pass freely; `minor`/`major` bumps force explicit `migrate` | P0 | §5 semantics |
| FR-5 | `contract.migrate(project, to_version)` re-reads ALL existing docs/CHG/ACC/structure under the new contract; any that fail to parse → stop, list incompatibilities, do NOT raise the lock; only if all pass, write the new lock | P0 | Validating upgrade, not forced |
| FR-6 | `agents.parse_role_table(skill_path)` parses the "Role startup spec" table in `references/agent-hierarchy.md` → `{role: {tools, can_spawn, writable, scope}}` | P0 | Read from skill, not hardcoded |
| FR-7 | `agents.spawn(role, scope, task)` starts an agent with that role's tools allowlist; **V1's tools must exclude `Agent`**; prompt carries "load ai-sdlc skill + your role & scope" | P0 | Role chain A1→I1(→I1.x)→V1 |
| FR-8 | `gates.check_halt(gate, risk, action, autonomy)` subprocess-calls the skill's `halt_gate.py` and branches on exit code 0=AUTO / 10=HALT / else error; no risk matrix re-written in the runner | P0 | Calls skill script |
| FR-9 | `gates.check_cross_repo_drift(...)` subprocess-calls the skill's `cross_repo_check.py` and branches on exit code | P1 | Calls skill script |
| FR-10 | `state` writes a checkpoint (`state.json`) at each stage boundary; `--resume` continues from the last checkpoint without re-running completed stages | P0 | Crash-resumable |
| FR-11 | `orchestrator` runs four stages sequentially, each passing its halt gate, with shallow fan-out (depth ≤ 3, concurrency ≤ 4) inside the implement stage | P0 | §4 runtime spec |
| FR-12 | `cli` exposes `run` / `migrate` / `status` subcommands | P0 | entry point `runner` |
| FR-13 | Runtime limits (nesting/concurrency) come from `config/runner.yaml` and are probed at startup; contract targets the skill's stable output, not Claude Code's current behavior | P0 | runtime isolation |
| FR-14 | `before_merge_or_release` and always-halt actions (deploy/release/migration/delete/money/secret/publish) always surface for human approval | P0 | red lines |

## 5. Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| Performance | Conservative fan-out (depth ≤ 3, concurrency ≤ 4) to save tokens, even though the platform supports more |
| Security | Least-privilege tool allowlists per role; V1 mechanically cannot spawn or edit code under review; red-line actions never auto-run |
| Maintainability | Single source of truth = skill; runner holds no duplicated governance logic; runtime variability isolated in config |
| Compatibility/Scale | Standard-library-only runner (PyYAML optional); Python ≥ 3.9; one-way dependency keeps the skill reusable without the runner |

## 6. Constraints & Assumptions

- Constraints: never re-implement skill logic; never track `main`; never auto-run red-line actions.
- **Override (CHG-20260617-05, user-approved):** the original "reference-not-copy via submodule" constraint (§1.2/§7) is **deliberately relaxed** — the skill is now vendored into a local offline store (`skills/v1.0.0`, `skills/v1.1.0`) as the primary source, so the runner runs fully offline. Mitigations: versions are extracted verbatim from the ai-skills git tags (offline `git archive`, no fork), the submodule is retained as an optional fallback, governance logic is still read from the store's own scripts/refs (not duplicated), and `runner check` flags newer versions. The runner never fetches the skill online.
- Assumptions: the user provides the `ai-skills` submodule; the actual contract version is detected by reading SKILL.md; for offline verification the runner may point `skill_path` at a local skill cache (e.g. via `--skill-path`).
- Open items: the canonical `ai-skills` repo URL and the existence of tag `v1.0.0` are the user's responsibility (build-guide §0); a missing/incorrect tag surfaces as a contract-version mismatch rather than silent drift.

## 7. Acceptance Criteria

- [ ] Submodule `ai-skills` is configured to pin tag `v1.0.0` (not main); `git submodule status` shows it once wired up by the provider.
- [ ] `contract.py`: first run writes `.sdlc-lock.json`; a later run with a different `major.minor` is rejected with a migrate prompt; a different patch passes normally.
- [ ] `gates.py`: `check_halt` actually subprocess-calls the skill's `halt_gate.py` and branches on exit code 0/10; no risk matrix re-written in the runner.
- [ ] `agents.py`: parses the role table; `spawn("V1", ...)` yields tools that exclude `Agent`.
- [ ] `orchestrator.py`: a stub-agent dry-run completes the four stages and correctly halts at one high-risk gate awaiting approval; `--resume` continues from a checkpoint.
- [ ] `tests/test_contract.py`: covers lock comparison (patch passes, minor/major blocked) and the migrate-failure (incompatibility list) path.
- [ ] Governance docs present: `docs/ai-guideline.md`, `docs/structure/*.md`, relevant `CHG-*.md`, `ACC-*.md`.

## 8. AI Development Conventions

- **Read, don't re-implement**: all governance truth (halt matrix, role definitions, CHG/ACC fields) is read from the skill or obtained by calling its scripts. The runner contains no duplicated *logic*. (Note: per the CHG-05 override, the skill *files* are now vendored into a local offline store rather than referenced via submodule; the no-duplicated-logic principle still holds.)
- **Calls, not re-implementations**: halt decisions via `subprocess` to `halt_gate.py`; cross-repo drift via `cross_repo_check.py`; roles by parsing `references/agent-hierarchy.md`.
- **Contract targets the skill's stable output**, not Claude Code's current runtime. Nesting depth / concurrency live in `config/runner.yaml`, probed at startup; if the platform changes, change the runner, not the contract.
- **Version lock is major.minor, patch-permissive**; version changes go through a validating `migrate` (re-read everything; upgrade only if all parse).
- **Stages run sequentially, fan-out is shallow** (depth ≤ 3, concurrency ≤ 4) inside a stage only.
- **V1 tool-layer lockdown**: the verifier never receives the `Agent` tool and is read-only on the code/structure under review (but may execute tests/CLI/GUI to verify).
- **Red lines always halt**: deploy/release, data migration/irreversible schema, delete/drop, money, secrets/permissions, publish — never auto-run; always surface to a human.
- **This repo is governed by ai-sdlc**: every change leaves a `CHG-*.md`; acceptance closes in the same round with an `ACC-*.md`. Docs are the source of truth (§1 principles and §7 prohibitions are inviolable guardrails).
