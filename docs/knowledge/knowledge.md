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
