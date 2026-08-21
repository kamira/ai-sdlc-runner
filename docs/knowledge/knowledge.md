# knowledge — ai-sdlc-runner knowledge base

> Single-file mode (entries < 30); spec: ai-sdlc `references/knowledge.md`. On entry read the
> INDEX and load only in-scope entries — never the whole file. Founded empty per the bootstrap
> rule (an empty INDEX is a legitimate knowledge base); see CHG-20260706-01.
> **Split threshold:** when entries reach 30, split into `entries/` (one file per entry, id as
> filename) and keep this file as the INDEX only; register every new tag in `vocabulary.json` first.

## INDEX (read this, not the whole file)

| id | tier | tags/scope | rule (one line) | status |
|----|------|-----------|-----------------|--------|
| KN-1 | pattern | contract / skill sourcing | `skills/` is the PRIMARY offline store (vendored `git archive` of the published skill's main HEAD, labelled by SKILL.md frontmatter); the `ai-skills/` submodule is an optional fallback, never copied from. | active |
| KN-2 | pattern | contract / version lock | Per-project `.sdlc-lock.json` locks major.minor; `runner.yaml` `contract_version` is a first-run default only; version bumps never touch existing locks; `migrate` is explicit & validating (patch=auto, minor/major=migrate-required), never silent auto-migrate. | active |
| KN-3 | pattern | dashboard / TUI | Terminal-only stdlib `curses` with a numbered / non-TTY fallback; the vertical `render_snapshot` path is always preserved; panels are computed on real events and cached (no per-keystroke I/O); red-line gates still require explicit human approval. | active |
| KN-4 | pattern | toolchain / handshake step 0 | `requirements-dev.txt` is a DERIVED, probe-facing view of `pyproject.toml`'s extras: **bare distribution names only** — the probe returns `NOT_RUN` (not PASS) for version ranges, `-e`/`-r` lines, URLs, extras and markers, so "adding the version floors back" silently disables the gate. | active |

<!-- Append DIR-n (user directives) / KN-n (observed patterns) as anchored sections below and add
     one INDEX row each; register any new tag in vocabulary.json first. -->

## KN-1 — Offline skill-store vendoring pattern
*tags: contract · source: CHG-20260703-01, CHG-20260703-06 · tier: pattern*

The runner sources the `ai-sdlc` skill **offline-first**. `skills/<version>/` is the PRIMARY store,
each version vendored verbatim as an offline `git archive` of the published skill's `main` HEAD and
labelled by that checkout's SKILL.md frontmatter version (e.g. `v1.12.1` @ `605425e`, `v1.16.0` @
`b4d6ef3`) — versions without a git tag are still pinned by commit. The `ai-skills/` git submodule is
an **optional fallback** (not pulled by default) and is treated as read-only reference: the runner
**never re-implements skill logic and never copies skill markdown into itself** (ai-guideline §7).
Adding a store version bumps `runner.yaml`'s `contract_version` default for *new* projects only.

## KN-2 — Per-project version-lock & migrate semantics
*tags: contract · source: CHG-20260617-01, CHG-20260703-01, CHG-20260703-06 · tier: pattern*

Version resolution is per governed project, not global. Each project carries its own
`.sdlc-lock.json` pinning **major.minor**; the runner resolves the contract against that lock.
`runner.yaml`'s `contract_version` is only the **first-run default** — bumping it (on new vendored
versions) leaves all existing per-project locks untouched (1.0 / 1.1 / 1.12 locks keep resolving to
their stores). Update detection is **read-only** and never auto-migrates: patch drift = auto-OK,
minor/major drift = `migrate`-required, surfaced as a mismatch rather than silent drift. `migrate`
is explicit and validating (ai-guideline §5). Lock files belong to the governed project, never to
this runner repo.

## KN-3 — Dashboard / curses conventions
*tags: dashboard · source: CHG-20260617-02, CHG-20260617-03, CHG-20260703-04, CHG-20260703-05 · tier: pattern*

The interactive view is a **terminal `curses`** app (stdlib only, consistent with the runner's
zero-dependency, pure-backend stance), with a numbered-menu / non-TTY fallback so behaviour degrades
gracefully. The vertical `render_snapshot` path is **always preserved** for snapshot callers. Panels
(status, exec log, verify/ACC list, agent log) are built by `DashboardModel` from real events and
**cached** — refreshed on open / after a run / explicit `refresh()`, so per-keystroke redraws do zero
git/disk I/O (the typing-lag fix). Wide/CJK input goes through `get_wch()` with char-level width.
At a HALT gate the dashboard presents Approve/Reject, but **red lines still require explicit human
approval** — the presentation layer never relaxes a governance gate.

## KN-4 — The toolchain probe only parses bare names; anything richer silently means "not checked"
*tags: toolchain · source: CHG-20260822-01 · tier: pattern*

The ai-sdlc entry handshake's step 0 runs `toolchain_probe.sh`, which reads dev dependencies from
**`requirements-dev.txt` and no other file**. This repo declares them in `pyproject.toml`'s
`[project.optional-dependencies]`, so before CHG-20260822-01 the gate returned `NOT_RUN` (exit 4) on
every session — which means *the check did not run*, not *nothing to check*.

`requirements-dev.txt` here is therefore a **derived, probe-facing view**, and `pyproject.toml`
remains the authority for versions. Two things about it are easy to get wrong, both measured against
the probe rather than reasoned about:

- **Only bare names reach `PASS`.** Measured: `-e .[yaml,test]` → `NOT_RUN`; `PyYAML>=6.0` →
  `NOT_RUN` (range specifiers fall to the "existence verified only" branch, and *any* unparsed line
  forces `NOT_RUN`); `pytest==7.0.0` against a different installed version → `BLOCKED`; bare
  `PyYAML` / `pytest` → **`PASS`**.
- **The dangerous edit looks like an improvement.** Restoring the version floors to this file — the
  natural instinct on reading it — turns the gate back off while making the file *appear* more
  rigorous. `tests/test_requirements_dev_sync.py` exists for exactly this: it fails on any non-bare
  line, and on any drift from the pyproject extras. A mutation check confirmed the test and the probe
  fail together.

Exact `==` pins also reach `PASS` but are rejected here: the dev image is rebuilt every session and
CI spans py3.9/3.13, so a pin would flip to `BLOCKED` on the next routine upgrade.

**What the green means, narrowly:** the dev dependencies are *installed*. It does not check
`>=6.0`/`>=7.0` — pip enforces those at install time. Still strictly more than `NOT_RUN`, which
verified nothing.

**Upstream fix still outstanding:** the probe should read `[project.optional-dependencies]` directly.
That belongs to **`kamira/skill-ai-sdlc-autopilot`** — successor to `ai-skills`, which was archived
2026-08-04 — cloned locally as a sibling directory and still carrying the same unfixed probe. It is
reachable but is a separate governance domain, and a fix there reaches this repo only once a fixed
skill version is installed or vendored. On this side the workaround stands: the submodule is absent,
the vendored store tops out at v1.16.0 (predating the probe), and KN-1 forbids editing the store.
