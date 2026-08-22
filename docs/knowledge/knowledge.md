# knowledge — ai-sdlc-runner knowledge base

> Single-file mode (entries < 30); spec: ai-sdlc `references/knowledge.md`. On entry read the
> INDEX and load only in-scope entries — never the whole file. Founded empty per the bootstrap
> rule (an empty INDEX is a legitimate knowledge base); see CHG-20260706-01.
> **Split threshold:** when entries reach 30, split into `entries/` (one file per entry, id as
> filename) and keep this file as the INDEX only; register every new tag in `vocabulary.json` first.

## INDEX (read this, not the whole file)

| id | tier | tags/scope | rule (one line) | status |
|----|------|-----------|-----------------|--------|
| KN-1 | pattern | contract / skill sourcing | `skills/` is the **only** skill source — a vendored `git archive` of the published skill's main HEAD, labelled by SKILL.md frontmatter, never copied from. The `ai-skills/` submodule fallback was deleted in CHG-20260822-02 (upstream archived 2026-08-04, succeeded by `skill-ai-sdlc-autopilot`). | active |
| KN-2 | pattern | contract / version lock | Per-project `.sdlc-lock.json` locks major.minor; `runner.yaml` `contract_version` is a first-run default only; version bumps never touch existing locks; `migrate` is explicit & validating (patch=auto, minor/major=migrate-required), never silent auto-migrate. | active |
| KN-3 | pattern | dashboard / TUI | Terminal-only stdlib `curses` with a numbered / non-TTY fallback; the vertical `render_snapshot` path is always preserved; panels are computed on real events and cached (no per-keystroke I/O); red-line gates still require explicit human approval. | active |
| KN-4 | pattern | toolchain / handshake step 0 | `requirements-dev.txt` is a DERIVED, probe-facing view of `pyproject.toml`'s extras: **bare distribution names only** — the probe returns `NOT_RUN` (not PASS) for version ranges, `-e`/`-r` lines, URLs, extras and markers, so "adding the version floors back" silently disables the gate. | active |
| KN-5 | pattern | node-engine / work order | A work order carries **exactly** the closed D5 field set and nothing else: no tool names, no allowlist, no skill-loading line, no session or prior-turn context, no model/dispatch settings. Bodies are never inlined — paths and anchors only — and a content element id never appears without the path and anchor it resolves to. Routing (which model answers) lives in the dispatcher, never in the order. | active |
| KN-6 | pattern | node-engine / idempotence | An operation may be an **effect** only if it leaves a probeable postcondition in the ledger, git or the forge; constructing one without a probe raises. Probes describe the **postcondition, not the action**, and read the world rather than any record the runner wrote. Unanswerable **raises** — never `False`. Nothing already true is re-applied, before or after the frontier. | active |
| KN-7 | pattern | node-engine / sessions | Every **asking** node gets its own session: opened, asked once, closed in a `finally`; a factory that returns a session it already returned is refused. A multi-seat review is several asks, so each seat is its own session. The question is journalled **before** the session opens, so a dropped session costs the answer and not the question. | active |

<!-- Append DIR-n (user directives) / KN-n (observed patterns) as anchored sections below and add
     one INDEX row each; register any new tag in vocabulary.json first. -->

## KN-1 — Offline skill-store vendoring pattern
*tags: contract · source: CHG-20260703-01, CHG-20260703-06, CHG-20260822-02, CHG-20260822-03 · tier: pattern*

The runner sources the `ai-sdlc` skill **offline-first**. `skills/<version>/` is the PRIMARY store,
each version vendored verbatim as an offline `git archive` of the published skill's `main` HEAD and
labelled by that checkout's SKILL.md frontmatter version (e.g. `v1.12.1` @ `605425e`, `v1.16.0` @
`b4d6ef3`, `v1.64.0` @ `e3d27c3`) — versions without a git tag are still pinned by commit. The
upstream repo is now `kamira/skill-ai-sdlc-autopilot` (CHG-20260822-02). The store is treated as read-only
reference: the runner **never re-implements skill logic and never copies skill markdown into itself**
(ai-guideline §7).

**There is no longer a submodule fallback.** `.gitmodules` declared one against `kamira/ai-skills`,
which was **archived 2026-08-04** and succeeded by `kamira/skill-ai-sdlc-autopilot` (which also
merged `ai-sdlc` + `ai-sdlc-autopilot` into one skill at v1.18.0, so the inner path changed too).
The submodule had never been wired up and the directory never existed; CHG-20260822-02 deleted the
declaration. To use a skill checkout outside the store, pass `--skill-path` at its skill root.
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

## KN-5 — The work-order contract: what a dispatched node receives, and what it must never receive
*tags: node-engine · source: CHG-20260822-04 task 5 · tier: pattern*

`workorder.WORK_ORDER_FIELDS` is the complete set, and rendering asserts the produced keys are
**exactly** it — no more, no fewer. The exclusions are the load-bearing half, because they are what
makes an order runnable on a model that has never seen this runner: concrete tool names and
allowlists, the "load the ai-sdlc skill" bootstrap line, session or prior-turn context, model and
dispatch settings. An order carrying any of them runs on one harness only, however short it is.

Two traps this repo has already fallen into, both recorded so the next reader does not repeat them:

- **`agents.RoleSpec` is not a source of truth for capabilities.** Its `tools` list is *synthesised
  here* — `Read`, `Bash`, `Edit`, `Write`, `Agent` are Claude Code names hard-coded in `agents.py`,
  not shipped data — and its `writes_docs` flag is guessed from prose in the Notes column. Only the
  three shipped booleans (`can_spawn` / `writable` / `can_execute`) may be read, and they must never
  be derived back from tool names.
- **Check the exclusion by enumerating what is present, never by searching for banned words.** A
  substring search for a forbidden term scores 21 false positives on this corpus — `pr` inside "Org
  **pr**inciples", `merge` inside "E**merge**ncy" — and it failed the guard test written for task 2
  on its first run. Two instruments work: a closed key set, and a **sentinel** injected through the
  field you fear leaking, asserted absent from the serialised order by exact value.

**Nine of thirteen declared roles cannot be rendered at all**, and that is deliberate: the shipped
role table has four rows, and `orchestrator`, `integrator`, `reviewer` and the six `seat-*` roles
have no capability data anywhere in the store. Rendering one is a hard error naming the role.
Defaulting the flags is not a neutral safe default but this runner authoring an authorization policy.

## KN-6 — Effect admissibility and the shape of a probe
*tags: node-engine · source: CHG-20260822-04 tasks 6–7 (D6) · tier: pattern*

An operation may be an **effect** only if it leaves a probeable postcondition (D6.2), and that is
enforced rather than documented: `effects.Effect` raises if constructed without a probe, so an
unprobeable step never reaches a sequence. Resume means finding the **first unmet postcondition** and
running from there.

Three rules that are easy to get backwards, each learned the hard way:

1. **A probe describes the postcondition, not the action.** "Did we run push?" needs a record we
   wrote — the thing a crash destroys or leaves stale. "Does the remote have this branch?" asks the
   thing itself. A probe that inspects our own records reintroduces the receipts D6.4/D6.5 refuses.
   The ledger probes are not an exception: a CHG naming its `Branch:`, a ticked box, an ACC file are
   the *deliverable*, read by the next session too. A receipt says "I did the thing"; the ledger *is*
   the thing.
2. **Unanswerable is not "not done".** An unreachable remote or a failing forge must raise, never
   return `False`. Collapsing the two is what makes a resume push twice or open a second PR.
3. **Nothing already true is ever re-applied** — before the frontier *or* after it. The first version
   applied everything past the frontier blindly, and the test named for that case asserted the unsafe
   behaviour, so it was hiding the hazard rather than catching it; **both review seats independently
   named it their worst finding**. An effect found true *past* the frontier means the world is out of
   causal order, usually the residue of an abandoned attempt: report it, do not silently redo it and
   do not silently accept it.

Verification bar for anything in this family: kill a **real process** with `os._exit` against a
**real** repository. An in-process exception is not a stand-in — an exception unwinds, and unwinding
is the courtesy a killed process does not extend.

## KN-7 — One ask, one session; the question outlives it
*tags: node-engine · source: CHG-20260822-04 task 6 · tier: pattern*

Every node that asks a model gets its own session, opened and closed around that single ask. This is
a **correctness** property, not an economy: continuity breeds bias, which is the same reason the
shipped review panel runs phase 1 blind — *"a seat that reads first agrees first"*. A multi-seat
review is several asks, so each seat is its own session; otherwise "three seats" is one model
answering three times in one context.

The engine owns the lifecycle so this is enforced rather than hoped for: open, ask once, close in a
`finally`, and **a factory that hands back a session it already returned is refused** — that is the
persistent case by definition. Two mistakes made while building this, both worth inheriting:

- **Tell a session factory from a plain dispatcher by arity, not by duck-typing.** Both are usually
  plain callables; sniffing for an `ask` attribute calls one with the other's arguments.
- **`id()` is not identity.** Tracking sessions by `id()` broke on Python 3.13 and passed on 3.9 and
  3.11 by allocation luck: every ask drops its session, so CPython is free to hand a fresh one a
  recycled address. Hold the objects and compare with `is`. **This was the first thing the CI
  version axis ever caught** — the OS axis was added after five Windows-only failures survived four
  CHGs, and the same argument holds one axis over.

The question is journalled **before** the session opens and marked answered after, so a dropped
session costs the answer and not the question; what is pending is re-askable verbatim. Reconstructing
a question later risks asking a subtly different one, and a subtly different question is how a rerun
quietly stops being a rerun.
