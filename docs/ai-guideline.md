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

Success = a runner that (a) ~~references — never copies — the skill via a pinned submodule~~
**(superseded twice: CHG-20260617-05 replaced the submodule with a vendored store, CHG-20260822-02
deleted the submodule declaration, and CHG-20260822-04 added deterministically derived elements —
the runner now *holds* skill text, under the named §6 overrides; what it still never does is
hand-copy or hand-edit it)**, (b) reads all governance logic (halt-points, role definitions, CHG/ACC
fields) from the skill rather than re-implementing it, (c) locks the contract at `major.minor` per
governed project with a validating `migrate`, (d) runs the four stages sequentially with shallow
per-stage fan-out — **and, behind the opt-in `--engine` flag (CHG-20260822-04), walks the skill's own
shipped node graph instead; the four-stage default is unchanged until a separate later decision
flips it** — and (e) mechanically locks down the V1 verifier's tool layer. This repo is itself governed by ai-sdlc (dogfooding).

## 2. Scope

### In scope
- The runner Python package per build-guide §2/§3: `cli`, `contract`, `agents`, `gates`, `state`, `orchestrator`.
- `config/runner.yaml`, `pyproject.toml`, `README.md`, `tests/test_contract.py`.
- Governance docs for this repo: `docs/ai-guideline.md`, `docs/structure/*.md`, `docs/changes/CHG-*.md`, `docs/acceptance/ACC-*.md`.
- ~~Submodule scaffolding (`.gitmodules`) expecting `ai-skills` pinned to tag `v1.0.0` (the submodule itself is provided by the user).~~ **(Superseded, CHG-20260617-05 → removed, CHG-20260822-02):** the vendored offline store replaced the submodule as the skill source, and the declaration was deleted once the upstream repo was archived (2026-08-04).

### Out of scope (explicitly excluded)
- Re-implementing any skill logic (halt matrix, role table, CHG/ACC field lists) inside the runner.
- Copying any skill markdown into the runner. **(Narrowly overridden, CHG-20260822-04):** still
  forbidden for hand-copied or edited text; the override covers **deterministically derived
  artifacts only** — see §6 "Derived-artifact baseline". Anything a human typed or adjusted by hand
  remains excluded, and the prohibition is unchanged for it.
- The §4 autonomous loop as a *build step* — §4 is the runner's runtime behavior spec (a product to implement), not how the first runner is built.
- Driving real deployment/migration/deletion/money/secret/publish actions automatically — these always halt for a human.
- Pinning the submodule to `main` or any floating branch.
- Any browser storage / frontend concern (pure backend Python tool).

## 3. Stakeholders

| Role | Concern |
|------|---------|
| Runner author (human-in-the-loop) | Builds the first runner via ai-sdlc four stages; approves at halt-points |
| Upstream skill maintainer (`skill-ai-sdlc-autopilot`; formerly `ai-skills`, archived 2026-08-04) | Owns the contract surface (skill version, scripts, role table); publishes the versions vendored into `skills/` |
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
| Maintainability | Single source of truth = skill; runner holds no duplicated governance **logic** — it does hold derived skill **text** under the §6 overrides, but only as machine output that CI regenerates and byte-compares, never as something a person may edit; runtime variability isolated in config |
| Compatibility/Scale | Standard-library-only runner (PyYAML optional); Python ≥ 3.9; one-way dependency keeps the skill reusable without the runner |

## 6. Constraints & Assumptions

- Constraints: never re-implement skill logic; never track `main`; never auto-run red-line actions.
- **Override (CHG-20260617-05, user-approved):** the original "reference-not-copy via submodule" constraint (§1.2/§7) is **deliberately relaxed** — the skill is now vendored into a local offline store (`skills/v1.0.0`, `skills/v1.1.0`) as the primary source, so the runner runs fully offline. Mitigations: versions are extracted verbatim from the upstream skill repo's git tags (offline `git archive`, no fork), the submodule was retained as an optional fallback at the time (deleted in CHG-20260822-02), governance logic is still read from the store's own scripts/refs (not duplicated), and `runner check` flags newer versions. The runner never fetches the skill online.
- Assumptions: ~~the user provides the `ai-skills` submodule~~ **(Superseded, CHG-20260822-02:** no submodule exists; the vendored `skills/` store is the only source**)**; the actual contract version is detected by reading SKILL.md; for offline verification the runner may point `skill_path` at a local skill cache (e.g. via `--skill-path`).
- **(Superseded, CHG-20260703-01):** the offline store also vendors `skills/v1.12.1` (offline `git archive` of the published skill's main HEAD `605425e`, labelled ai-sdlc v1.12.1 in its SKILL.md frontmatter — v1.12.1 has no git tag). `config/runner.yaml`'s `contract_version` default was bumped to `"1.12.1"`; existing 1.0/1.1 per-project locks were untouched and still resolve against `skills/v1.0.0`/`skills/v1.1.0`.
- **Current baseline (CHG-20260703-06):** the offline store now also vendors `skills/v1.16.0` (offline `git archive` of the published skill's main HEAD `b4d6ef3`, labelled ai-sdlc v1.16.0 in its SKILL.md frontmatter — v1.16.0 has no git tag). `config/runner.yaml`'s `contract_version` default is bumped to `"1.16.0"` so new projects lock at the current published skill; existing 1.0/1.1/1.12 per-project locks are untouched and still resolve against `skills/v1.0.0`/`skills/v1.1.0`/`skills/v1.12.1`.
- **Current baseline (CHG-20260822-03):** the offline store now also vendors `skills/v1.64.0`
  (offline `git archive` of the upstream skill's main HEAD `e3d27c3`, labelled ai-sdlc v1.64.0 in its
  SKILL.md frontmatter — v1.64.0 has no git tag, so it is pinned by commit). This is a 48-minor jump
  from v1.16.0 and is what makes the skill's machine-readable policy (`autopilot_policy.json`,
  `review_seats.json`, `sentinel_policy.json`, …) available to the runner at all: v1.16.0 shipped 3
  assets, v1.64.0 ships 26. `config/runner.yaml`'s `contract_version` default is bumped to `"1.64.0"`
  so new projects lock at the current published skill; existing 1.0/1.1/1.12/1.16 per-project locks
  are untouched and still resolve against their own store version (demonstrated, not assumed).
- **Derived-artifact baseline (CHG-20260822-04) — a narrow, named extension of the CHG-20260617-05
  override.** The runner now holds `elements/v<version>/`: the store's references split at their
  stable `##`/`###` anchors, plus dispatch elements derived from the shipped policy JSONs. This is
  **skill content living in this repo**, the same category as the vendored store itself, so it needs
  the same kind of named override rather than an argument that it is somehow different — determinism
  changes the drift risk, not the category. Scope of the extension, stated so it cannot creep:
  **deterministically derived artifacts only**, regenerated by `src/ai_sdlc_runner/decompose.py` and
  `dispatch.py` and byte-compared against the store in CI. Hand-copied or hand-edited skill text
  stays excluded by §2. What the override does *not* cover, and stays runner-authored interpretation:
  the segmentation heuristics (which headings are stable anchors; fenced-code headings are not),
  the LF-normalised hash basis, the composition of loadouts as element ids, and the tighten-only
  ordering on the four-valued autopilot axis. Each is named as a fork point in CHG-20260822-04.
  (The CHG's own D3 cites "§7/§8" for the copying prohibition; the prohibition is actually the §2
  out-of-scope line, and §8's closing line is what makes it inviolable. Corrected here rather than
  in the merged CHG, which is left as the historical record.)
- **Runner-authored fork points under the derived-artifact override (CHG-20260822-04) — the full
  index.** The override covers deterministic derivation; it does **not** cover the judgements the
  derivation rests on. Each is a place a different reader could have chosen otherwise, so each is
  named here rather than left looking like it fell out of the data:

  | # | Fork point | Where | Chosen because |
  |---|------------|-------|----------------|
  | 1 | A heading inside a fenced code block is **not** an anchor | `decompose.py` | 56 of 257 `^##?#` lines in the English references sit inside fences — document skeletons being *shown*. Splitting on them invents 56 elements and shreds the prose around them |
  | 2 | The hash basis is **LF-normalised** content, not raw working-tree bytes | `decompose.py` | `.gitattributes` is `* text=auto`, so the store checks out CRLF on Windows and LF on Linux; a raw-bytes hash would hard-fail one leg of the CI matrix for a store nobody touched |
  | 3 | The two checkpoint namespaces are **not de-duplicated** | `dispatch.py` | `before_merge_or_release` and `merge` are related, but the merge key exists in no shipped file — a human would have to write it, which is the hand-written node id the done-when forbids |
  | 4 | A loadout's anchor set is the role's **whole shipped file set** | `dispatch.py` | Narrowing by policy-key name scores **0 true positives and 21 false positives** against the 402 real headings. A matcher that selects nothing while looking like a refinement is the KN-4 shape |
  | 5 | Which policy file feeds which family | `dispatch.py` | Three lines, not derivable from the files themselves; a different reader could key families off something else |
  | 6 | The tighten-only total order on the **four-valued** autopilot axis | *deferred* | `_doc` says "只准加嚴" without ordering `halt` against `halt_independent`, and no usable resolver ships (`scripts/autopilot_runner.py` cannot import — its `lib/` was not archived). Left undecided rather than invented |
  | 7 | Loadouts name content element **ids**, not full records | `dispatch.py` | Inlining cost 265 KB of byte-identical duplication and made one role manifest larger than the biggest reference in the corpus. Found by measuring, corrected in task 3 |
  | 8 | The node graph is **authored and pinned**, not parsed | `graph.py` | The shipped block has 19 arrows and at least two are prose. Either way a hand-written rule is needed; parsing changes the *direction* of failure — a misreading yields a wrong graph silently and the regeneration gate cannot see it |

  Fork points 1–5 and 7–8 are implemented and pinned by tests; **6 is deliberately open** and is
  recorded as such rather than resolved by guesswork.
- **Governance baseline (CHG-20260706-01):** this repo's own ai-sdlc governance now carries the v1.17+ root entry anchor (`AGENTS.md`, SKILL.md template) and the pre-founded knowledge base skeleton (`docs/knowledge/knowledge.md` zero-entry INDEX + `vocabulary.json` seed), as enforced by the skill's `doc_integrity_check.py` (entry-anchor + knowledge-bootstrap lints).
- **CI baseline (CHG-20260817-10):** this repo had no CI at all until 2026-08-17 (0 workflows, 0 Actions runs, no branch protection) — every prior change merged on locally-run, self-reported evidence, which is how the five Windows-only test failures fixed by CHG-20260817-09 survived four CHGs unnoticed. `.github/workflows/ci.yml` now runs the suite on `{ubuntu, windows} × py{3.9, 3.13}` (`fail-fast: false`) plus the `doc_integrity_check.py` gate, on every PR and every push to `main`. The **OS matrix is the load-bearing part** — the motivating defect was platform-conditional and a single-OS pipeline would have stayed green through all of it. CI is deliberately **not** gated on a coverage percentage: measuring the CHG-20260817-09 fix showed `executors.py` at 86% *before* and 85% *after*, because the broken tests were executing the code and dying inside it, so coverage counted the lines while no assertion ever ran.
- ~~Open items: the canonical `ai-skills` repo URL and the existence of tag `v1.0.0` are the user's responsibility (build-guide §0); a missing/incorrect tag surfaces as a contract-version mismatch rather than silent drift.~~ **(Closed, CHG-20260822-02):** `ai-skills` was archived 2026-08-04 and succeeded by `skill-ai-sdlc-autopilot`; the runner no longer references either repo at runtime, so no tag is load-bearing. Versions are pinned by the vendored store.

## 7. Acceptance Criteria

- ~~[ ] Submodule `ai-skills` is configured to pin tag `v1.0.0` (not main); `git submodule status` shows it once wired up by the provider.~~ **(Superseded, CHG-20260617-05; struck CHG-20260822-02):** the vendored offline store replaced the submodule as the skill source, so this criterion was already moot; it became permanently unsatisfiable when `ai-skills` was archived on 2026-08-04. Struck rather than rewritten — §6 already states the vendored-store requirement, and the original wording is kept legible as history. `git submodule status` is now empty by design.
- [ ] `contract.py`: first run writes `.sdlc-lock.json`; a later run with a different `major.minor` is rejected with a migrate prompt; a different patch passes normally.
- [ ] `gates.py`: `check_halt` actually subprocess-calls the skill's `halt_gate.py` and branches on exit code 0/10; no risk matrix re-written in the runner.
- [ ] `agents.py`: parses the role table; `spawn("V1", ...)` yields tools that exclude `Agent`.
- [ ] `orchestrator.py`: a stub-agent dry-run completes the four stages and correctly halts at one high-risk gate awaiting approval; `--resume` continues from a checkpoint.
- [ ] `tests/test_contract.py`: covers lock comparison (patch passes, minor/major blocked) and the migrate-failure (incompatibility list) path.
- [ ] Governance docs present: `docs/ai-guideline.md`, `docs/structure/*.md`, relevant `CHG-*.md`, `ACC-*.md`.

## 8. AI Development Conventions

- **Read, don't re-implement**: all governance truth (halt matrix, role definitions, CHG/ACC fields) is read from the skill or obtained by calling its scripts. The runner contains no duplicated *logic*. (Note: per the CHG-05 override, the skill *files* are now vendored into a local offline store rather than referenced via submodule; the no-duplicated-logic principle still holds.)
- **Derived artifacts are generated, never edited** (CHG-20260822-04): `elements/v<version>/` is machine output, regenerated from `skills/v<version>/` and byte-compared in CI. Editing an element by hand is the same category as hand-copying skill markdown and is forbidden by §2; fix the generator or the store instead. The generator's segmentation and composition heuristics are runner-authored and each one is named as a fork point in that CHG.
- **Calls, not re-implementations**: halt decisions via `subprocess` to `halt_gate.py`; cross-repo drift via `cross_repo_check.py`; roles by parsing `references/agent-hierarchy.md`.
- **Contract targets the skill's stable output**, not Claude Code's current runtime. Nesting depth / concurrency live in `config/runner.yaml`, probed at startup; if the platform changes, change the runner, not the contract.
- **Version lock is major.minor, patch-permissive**; version changes go through a validating `migrate` (re-read everything; upgrade only if all parse).
- **Stages run sequentially, fan-out is shallow** (depth ≤ 3, concurrency ≤ 4) inside a stage only.
- **V1 tool-layer lockdown**: the verifier never receives the `Agent` tool and is read-only on the code/structure under review (but may execute tests/CLI/GUI to verify).
- **Red lines always halt**: deploy/release, data migration/irreversible schema, delete/drop, money, secrets/permissions, publish — never auto-run; always surface to a human.
- **This repo is governed by ai-sdlc**: every change leaves a `CHG-*.md`; acceptance closes in the same round with an `ACC-*.md`. Docs are the source of truth (§1 principles and §7 prohibitions are inviolable guardrails).
