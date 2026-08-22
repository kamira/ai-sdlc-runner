---
name: ai-sdlc-autopilot
description: >
  Governed AI-SDLC in one skill: **governance** (requirement analysis, structure design,
  modification governance, acceptance — every task reads the docs first and stays traceable)
  plus **autopilot execution** (a confirmed requirement is driven to a merged change: plan →
  per-task TDD build → multi-seat review panel → verification gates → acceptance → PR → merge).
  Use it whenever the user plans a project or feature, clarifies requirements, designs
  architecture or a database, proposes any modification, asks whether results meet the bar, or
  wants a change executed end-to-end under governance. Halt points are driven by risk grading
  (low = full auto, medium = one confirm gate, high / irreversible = always halts for a human).
  Important: as soon as a modification or new feature is proposed, go through modification
  governance first rather than editing code directly.
metadata:
  version: 1.64.0
---

# ai-sdlc-autopilot — governed autopilot execution

> 語言 / Language: [繁體中文](SKILL.zh-tw.md) · **English**

**One sentence**: ai-sdlc keeps the ledger and the gates; this skill does the building and the driving — a requirement goes in, a governed, reviewed, tested, merged change comes out, and every step lands in the ai-sdlc ledger automatically.

Three layers: **governance** (ai-sdlc, external, read-only), **execution** (the references here: plan format, TDD, task review, debugging), **drive** (autopilot-loop contract + `assets/autopilot_policy.json` + `scripts/autopilot_runner.py`).

## Two layers, one skill

This skill is both the **governance layer** and the **execution layer**: governance keeps the ledger and the gates (requirement analysis, structure design, modification governance, acceptance); execution does the building and the driving (plan format, TDD, per-task review, the runner).

These were two skills (`ai-sdlc` and `ai-sdlc-autopilot`) shipped inside one plugin. They merged into one at **v1.18.0** — they always had to be installed and used together, and splitting them bought no isolation, only the coordination cost of "which depends on which, and do the versions line up".

**No parallel ledger**: the plan lives in the target project's CHG (modification-guide section), review verdicts land in the ACC evidence column, errors land in `docs/knowledge/`. If you find yourself writing to a new docs directory, you are drifting.

## Detect → load


**Auto-detect by default: when you detect the situations below, proactively load the matching reference without being told. But the user may explicitly choose or override — the user's instruction wins** (e.g. "force team mode", "no CI/CD this time", "skip cross-repo", "self-verify is fine"); auto-detection applies only when the user hasn't specified.

| Situation | Detection cues (any one counts) | Load |
|-----------|----------------------------------|------|
| Multiple repos / shared contract | several repo paths/URLs; mentions of frontend+backend, microservice, SDK+server, multi-package monorepo; changes to API/schema/event/shared types/protobuf; words: cross-repo, contract, upstream/downstream, integrate | `cross-repo` (+ `scripts/cross_repo_check.py`) |
| Parallel / cross-session handoff | multiple agents at once; taking over someone's / a prior session's project; words: take over, hand off, continue, simultaneously, in parallel, split up | `cross-agent` |
| Dispatch sub-agents / multi-agent split | you plan to spawn subagents; task large enough to split across units; words: dispatch, sub-agent, split tasks, divide, orchestrate | `agent-worklog` + `agent-hierarchy` |
| Modification / new feature (existing system) | adjust/fix/extend/refactor/rename/delete an existing feature/file/table; words: change, add, tweak, refactor, optimize, fix bug, replace | `modification-guide` (**mandatory**) |
| Acceptance / confirm it meets the bar | "done / is this right / verify / check / test it"; a change just implemented | `acceptance-verification`; **high-risk → `independent-acceptance`** |
| Medium/high-risk change decision | CHG graded medium or high; grading disputed; rules exceed one agent's context | `review-panel` (seats by domain; full panel at high, **≥5 seats** at medium when spawnable; two-phase cross-validation; serialized self-review when spawning isn't available) |
| Taking over / cross-session entry | every new session start, or taking over an existing `docs/` project | `handshake` (entry handshake: read docs+knowledge+branch+working tree, echo back; dispatched subagents use the scoped tier) + `doc-integrity` |
| **No ledger yet** (no `CHG-*.md` anywhere) | new project from zero; code already built but never governed; `docs/` occupied by a docs site or generated output; moving a ledger to a new location; words: initialize, onboard, adopt, bring under governance, existing project | `onboarding` (four-state routing init/adopt/governed/`docs` occupied; location rule; no-overwrite and resume; the **governance baseline** for existing codebases — inventoried ≠ accepted) |
| User correction directive / request conflicts with a known rule / recurring need | "don't do this", "I told you before"; a new request violates an existing directive; **the same need/purpose recurs across CHGs/requirements** | `knowledge` (record/update; autonomous shallow→deep pattern records; on conflict → triple confirm + impact disclosure) |
| Multiple branches exist | feature/release/hotfix in parallel; requirements/acceptance on different branches | `branch-isolation` (use only current-branch sources; no cross-branch reference) |
| Has / adopting CI/CD | repo has `.github/`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`, Jenkinsfile; or mentions pipeline/hook/gate | `ci-cd` (optional) |
| Autonomous multi-stage run / external orchestrator drives the flow | an agent will auto-run several stages, or Python/etc. drives it; words: run end-to-end, autonomous, unattended, automated flow | `autonomy` (halt-point contract; query `scripts/halt_gate.py`) |

**Close false negatives (better over-load than miss)**: cues are often implicit — "while you're at it, also tweak the backend" = multi-repo + modification; "you split it up" = multi-agent; "continue that earlier project" = cross-session takeover. **If a cue plausibly matches, load the reference**; over-loading is cheap, missing governance is costly. When unsure, lean toward loading.

Explicit wins, else detect: **follow an explicit instruction when given; otherwise use detection.** Overrides may tighten safety freely; when the user wants to relax a high-risk gate, flag the risk first, then follow their decision.

**The execution layer has its own detection set:**


| Situation | Cues | Load |
|-----------|------|------|
| Writing / validating an executable plan | task breakdown, constraints, interfaces, "plan this" | [`references/execution-plan.md`](references/execution-plan.md) |
| Building a task | implement, code it, red-green, test-first | [`references/tdd-loop.md`](references/tdd-loop.md) |
| A task's diff needs judging | review this task, verdict, spec compliance | [`references/task-review.md`](references/task-review.md) |
| Tests keep failing | 2+ consecutive failures on one task | [`references/systematic-debugging.md`](references/systematic-debugging.md) |
| Running the whole flow / resuming / wiring CI | autopilot, run it end-to-end, resume, halt policy | [`references/autopilot-loop.md`](references/autopilot-loop.md) |
| Declaring how a reusable artefact gets exercised | interaction spec, mouse/UI test, CLI surface, reused component | [`references/interaction-verification.md`](references/interaction-verification.md) |


## Why this is needed


The biggest problems with AI-assisted development are amnesia and drift: each conversation
lacks the context of prior decisions, so it's easy to make changes that conflict with the
existing architecture. This process fixes each stage's output into a document (AI Guideline,
structure docs, change records, acceptance reports) so any single task reads the docs first,
then acts.

## Four stages and their guides


```
 [requirement / new feature]
      |
      v
 requirement analysis --> structure design --> implement --> acceptance
 (Guideline)              (four structures)                  |
                                                    +--------+--------+
                                                  pass             fail
                                                    |                |
                                                    v                v
                                                  done       modification governance
                                                          (mod guide + record + struct sync)
                                                                  |
                                                                  v
                                                   re-implement --> re-verify (back to acceptance)

 Other entry: the user proposes a "modification / new feature" at any time
   --> mandatory modification governance --> implement --> acceptance
```

| Stage | When to use | Guide | Main output |
|-------|-------------|-------|-------------|
| 1. Requirement analysis | New project/requirement; clarify what to build | [`references/requirement-analysis.md`](references/requirement-analysis.md) | `docs/ai-guideline.md` |
| 2. Structure design | Guideline confirmed; define system structure | [`references/structure-design.md`](references/structure-design.md) | `docs/structure/*.md` |
| 3. Modification governance | A modification/new feature is proposed (**mandatory**) | [`references/modification-guide.md`](references/modification-guide.md) | `docs/changes/*.md` + updated structure |
| 4. Acceptance | Implementation/change done; confirm it meets the bar | [`references/acceptance-verification.md`](references/acceptance-verification.md) | `docs/acceptance/*.md` |

Two cross-cutting guides (available anytime):

| Aspect | When to use | Guide |
|--------|-------------|-------|
| Document anti-drift & verification | confirm existing docs are trustworthy; at change close-out; on takeover (needed even solo) | [`references/doc-integrity.md`](references/doc-integrity.md) |
| Subagent worklog + error knowledge base | before you dispatch subagents, or before running a dispatched task (applies to solo dispatching subagents too) | [`references/agent-worklog.md`](references/agent-worklog.md) |
| Agent hierarchy & org | a task is split across multiple agents, or an agent dispatches sub-agents (ID + fixed scope + no exceeding remit; recursion depends on platform) | [`references/agent-hierarchy.md`](references/agent-hierarchy.md) |
| Cross-repo coordination & consistency | a requirement/change spans multiple git repos, or repos share a contract | [`references/cross-repo.md`](references/cross-repo.md) |
| CI/CD integration (**optional**) | per need, to automate acceptance & structure-consistency as pre-commit or pipeline gates | [`references/ci-cd.md`](references/ci-cd.md) |

Read only the reference for the current stage to avoid loading irrelevant content at once.

> **Multi-person / multi-agent teams**: team collaboration (handoff, parallel work, independent acceptance, roles and read/write permissions) is **built into this skill** — when it detects a collaboration situation it auto-loads `cross-agent` / `independent-acceptance` / `agent-hierarchy`. No separate skill to install.
>
> **Cross-project**: when multiple projects are involved at once, the Guideline / CHG / ACC / structure docs must note their owning "Project" in the header, and change/acceptance ids should carry a project prefix, to avoid mixing records across projects.

## Session startup check (required for cross-session / incremental development)


**On every re-entry, before touching any new requirement, scan existing docs for stages left half-done:**

1. Read the latest CHG under `docs/changes/`: any whose status is not "Accepted" means the previous session's change is only half complete. (A status of "Paused" is legitimate WIP: list it and consciously resume or close it, rather than treating it as broken.)
2. Cross-check `docs/acceptance/`: if a CHG has no matching ACC report, acceptance was handed off but nobody picked it up.
3. Check the working tree (`git status`): every uncommitted change must map to some CHG's modification steps; an unmatched change means interrupted or ungoverned work — reconcile it per handshake / doc-integrity.
4. **Close those pending items first (run acceptance-verification / reconcile the working tree), then start the new requirement.**

Why: the most common break in cross-session work is "the modification flow treats acceptance as the next step and hands it off, but the next session brings a new feature, not the acceptance" — so acceptance hangs forever. Checking on entry lets the "modify -> verify" loop reconnect across sessions.

## Mandatory rule: changes always go through governance first


**Whenever the user proposes a "modification" or "new feature" within a session, you must first
read and follow `references/modification-guide.md` — do not edit code directly.** Any change can
touch existing structure and prior decisions; skipping governance causes architectural drift and
missing records. Modification governance has two entry points: (1) a user-initiated change, and
(2) a failed acceptance routed back for fixes — both go through "governance -> re-implement ->
re-verify", closing the loop.

**Close acceptance in the same round**: once a change is implemented, **immediately run
acceptance-verification in the same round to produce the ACC** and set the CHG status to
"Accepted" — do NOT just mark it "pending acceptance" and stop. In cross-session work nobody
will come back to do a deferred acceptance.

## Solo fast path (the default for solo + low risk)


Lightweight is the **default**, not a favor to ask for. Solo + whitelist-eligible low risk (copy/comments, styling, docs-only, tested internal refactors) = **CHG-lite + inline self-acceptance** (see modification-guide), with the confirm gate skippable via **pre-authorization** (narrow directives; the AI proactively suggests one after repeated same-class confirmations). What never turns off: commit anchoring, the one-line reproducible evidence, lint, and the misfire rule (a lite change caught breaking something → full CHG + the pre-authorization auto-revokes). Heavier machinery — full template, review panel, independent acceptance — engages by risk: light where being wrong is cheap, heavy where it isn't.

## Document storage convention


Outputs live under the **target project's** `docs/` (not this skill):

```
target-project/docs/
├── ai-guideline.md          # from requirement analysis
├── structure/{directory,logical,design,data}.md   # from structure design
├── changes/CHG-YYYYMMDD-NN.md                      # one per change
├── acceptance/ACC-YYYYMMDD-NN.md                   # one per acceptance
└── knowledge/                                      # founded at start (see knowledge); entry handshake bootstraps repos governed before this rule
```

If the target project already has a documentation convention, follow that and note the actual
paths in the AI Guideline.

**Entry anchor (root-level, any-AI)**: the entry point lives at the **repo root, not under
`docs/`** — the root is where every agent, from any vendor, looks first; `docs/` is the archive,
not the door. The first time you create `docs/`, also create a root **`AGENTS.md`** (the closest
thing to a vendor-neutral convention) that is scannable in seconds: what the entry is, what's
mandatory, what's non-negotiable:

```markdown
# AGENTS.md — AI entry point (any agent, any vendor)
1. MANDATORY before any change: run the ai-sdlc entry handshake —
   docs/ai-guideline.md → docs/knowledge/ INDEX → open CHG / branch state.
2. Governance lives under docs/ (changes/ acceptance/ structure/ knowledge/).
3. Non-negotiables: changes go through governance first (CHG); every commit
   message carries its CHG id; confirm with the user before implementing.
```

In-suite platform neutrality is not enough — **the entry must be findable by different AIs**.
For every tool-specific convention file present (`CLAUDE.md`, `GEMINI.md`, `.cursorrules`,
`.github/copilot-instructions.md`, …) keep a **two-line stub pointing at `AGENTS.md`**; stubs
never carry content of their own (duplicates drift). The lint enforces both: a governed repo
(`docs/changes/` exists) must have the root entry, and existing stubs must still point.

**Time convention (UTC+0)**: every timestamp in governance docs — the date in CHG/ACC ids and
filenames, header dates, worklog times, claim/lease times — uses **UTC+0**, and written times
state it (e.g. `2026-07-02 09:30 (UTC+0)`). Lease expiry and "same-day" sequence numbers are
judged on the UTC+0 clock, so cross-timezone teams share one clock.

## Operating principles


1. **Read before doing**: read the stage guide and existing docs before acting.
2. **Documents are the truth**: if the structure changes, update the structure docs in sync.
3. **Trace every change**: a modification always leaves a record under `docs/changes/`.
4. **Acceptance aligns to source**: criteria come from the Guideline and the change's mod guide.
5. **Don't rely on memory — rely on the docs**: a long conversation's context may be compacted, losing or distorting earlier decisions. **Don't go by recollection** — before acting, re-confirm existing constraints and decisions from the files under `docs/` (Guideline, structure, CHG, ACC); when memory and the docs disagree, the docs win. This keeps compaction, cross-session work, and handoffs from causing drift. Re-reading has concrete triggers, not just goodwill: at every autonomy gate, before starting acceptance, on signs of compaction, and periodically in long sessions, re-read the Guideline + active CHG and emit a mini-ack (see handshake "mid-session re-sync").
6. **Ask before deciding for the user**: when a choice can't be derived from the docs or the user's instructions — a new requirement surfacing mid-task, an out-of-scope dependency, a spec blank, an ambiguous adjudication — present options + a recommendation and **ask**; don't decide unilaterally and inform afterwards. Only low-risk, reversible implementation details may proceed unasked, and those are marked "decided on user's behalf" in the CHG for review at the confirm gate (see modification-guide).
Where dispatch is available, questions are **relayed by the elicitor** (A1) — the decision agent stays out of the Q&A and reads the resulting proposal (see requirement-analysis "elicitation by proxy"); approval still goes to the user directly.
7. **Act as if each action is your last**: the session may end after any single step — intent lands on disk before acting, the outcome immediately after (one step, one durable write; see handshake "last-act discipline"). When this holds, a graceful exit and a crash leave identical states, and interruption recovery stops being an emergency procedure — it's just ordinary entry.
## The loop


```
ai-sdlc handshake → CHG (plan-check gate)
  → [ per task: TDD build → unit/build tests → read-only task review → tick + commit ]
  → whole-branch review → operational verify (run it for real) → ACC → PR → (policy) merge → knowledge close-out
```

Interruption at any point is safe: ticked checkboxes are the resume point, and the live handshake file (`docs/worklog/handshake-autopilot.md`) is updated at every task boundary.

**Task tests ≠ acceptance**: per-task `test:` is unit/build level; before ACC the runner requires an **operational test** (the plan's `### Acceptance operation` — operate/observe/pass, run for real). A code CHG without it (and without a `docs-only` marker) halts before acceptance — see autopilot-loop.

## Halt policy (risk × stage — tighten only)


| Risk | confirm gate | task review | operational verify | acceptance | PR | merge |
|------|--------------|-------------|--------------------|------------|----|-------|
| low | auto | auto | auto (verify-cmd / human) | auto (self-verify) | auto | auto |
| medium | **confirm** (pre-authorizable) | auto | auto (verify-cmd / human) | auto | auto | **halt** |
| high | **halt** | auto | **halt** (human-performed) | **halt** (independent verifier) | auto | **halt** |

**Medium/high-risk confirm gates carry design diagrams** (v1.21.0) — this **adds no halt point**; whether the flow stops is still decided by the table above. What it adds is *what the user is shown* when it does stop. That left-hand cell used to hand over pure prose: motivation, impact scope, decisions made on their behalf, risk grade. But what the user actually needs to catch — "you wired that module to the wrong side", "the data flows the other way" — is exactly what prose expresses worst and what is easiest to nod through unread. **A confirmation material nobody can read buys acquiescence, not confirmation.** So a medium/high-risk CHG carries a `## Design diagrams` section (an architecture diagram of the affected area + a flow diagram of this change; Mermaid by default, ASCII is fine), **shown to the user and corrected until they confirm, before anything else proceeds** — and structure design for a new project works the same way (see structure-design step 5). The user may decide not to look: `Diagrams: skipped — <reason>`, where **a blank reason counts as undeclared** (a blank signature is not a signature), and the default when nothing is declared is to draw. Low risk and `Template: lite`/`classic` are exempt — bookkeeping cost scales with risk. plan-check blocks (exit 2), but it only checks that something was handed over; it **does not judge whether the diagram is right**: that semantic call belongs to the user, not the lint, and validating Mermaid syntax would need an external parser while the code under test is stdlib-only. **Prospective** (`DIAGRAM_SINCE = (1, 21)`): no existing record is affected.

<!-- claim: local-selfcheck-ahead-of-ci -->
**A local self-check runs before merge** (v1.22.0) — **ahead of the CI gate**, and **for code-bearing changes only**. Merging used to have exactly one gate (CI green, next paragraph), and that gate has two holes: (1) **CI may fail to start at all**, for reasons unrelated to the code (quota, billing, runner queues); (2) when CI does run, **it is still not your machine** — what exists locally (the developer's venv, a real filesystem, platform specifics) may not exist in CI, and the reverse holds too. So the change gets run once on the local machine first. Command precedence: **the operator's `--local-gate-cmd` → the CHG's `### Local gate` → the project's conventional carrier** (`.github/ci_local.sh`, `scripts/check.sh`, `make check`, `just check`); **if none of the four exist it halts** (exit 3) — merging is a one-way door, so not knowing means not merging (same direction as the CI gate; see KN-004). Docs-only (`Acceptance-operation: n/a`) and `Template: lite`/`classic` are exempt — bookkeeping cost scales with risk. **The trust boundary is unchanged**: a `### Local gate` `cmd` comes from repo content rather than the operator, so it **does not run by default**; it needs `--trust-chg-commands` (which echoes the command first) — the same line the interaction gate draws, with no new back door. The `--allow-no-local-gate` escape hatch is logged. **Prospective** (`LOCAL_GATE_SINCE = (1, 22)`): no existing record is affected.

**Before merge, CI must be complete and green** (v1.7.0) — `pending` is not green. Cannot determine the status? That halts too: merging is a one-way door, so this gate is fail-closed, unlike the sentinels' fail-open. A project with no CI must say so with `--allow-no-ci`, which is logged.

**Permanent halts** (never automated, hard-coded, no config can relax them): irreversible deletion, payments, production data migration, security-boundary changes. Decision order: permanent halts → CHG `Autonomy:` field (tighten only) → policy matrix → unknown = halt.

## Runner


```
python3 scripts/autopilot_runner.py plan-check --chg <CHG.md>
python3 scripts/autopilot_runner.py run --chg <CHG.md> --repo . \
    [--agent-cmd 'claude -p "$(cat {brief})"'] [--test-cmd 'pytest -q'] [--verify-cmd './run-smoke.sh'] [--dry-run] [--no-commit]
python3 scripts/autopilot_runner.py status --chg <CHG.md>
python3 scripts/autopilot_runner.py sentinels --repo . [--chg <CHG.md>] [--reentry-count N]
python3 scripts/autopilot_runner.py plan|build|review|verify|accept --chg <CHG.md> --repo .
python3 scripts/autopilot_runner.py build --chg <CHG.md> --repo . --agent-cmd '<builder>' --review-cmd '<reviewer>'
```

Each loop stage is also a **standalone role command** (and a slash command: `/autopilot-plan`, `-build`, `-review`, `-verify`, `-accept`, `-sentinels`); `run` is their composition. Splitting into commands is **not a governance bypass** — every role goes through the same halt policy and ledger, and a missing precondition halts (build needs an approved CHG; accept needs review + operational verify). See autopilot-loop "Roles as separate commands".

**Gates on the code the agent writes** (v1.5.0). `--test-cmd` going green only proves *the agent's own tests didn't catch the agent's own mistakes* — the same model wrote both, so they share blind spots. Four gates close that:

- **unit is mandatory**: no `--test-cmd` now **halts** (was: silently skipped). `--allow-untested` is the explicit, logged escape hatch for docs-only tasks. **Breaking change.**
- **mutation is on by default** (v1.10.0; `--min-kill-rate` default 90): seeds faults into the files this task changed and checks the agent's tests actually go red. Survivors are printed by line and operator. Python only — other languages are reported as **not covered**, never as passed. `--no-mutation` is the explicit, logged escape hatch; `--mutation` is kept as a compatibility no-op. **Breaking change** — existence of tests was already mandatory while *strength* was opt-in, and that ordering was backwards.
- **behaviour spec** (`### Behaviour spec` in the CHG → `.feature`): the user stories become runnable. Prospective from v1.5.0; run at the verify stage.
- **whole-branch review** is no longer a no-op: it really calls the review command and requires a verdict line. No output is not a pass.

**performance is wired** (v1.17.0) — every non-functional kind that applies to this repo now runs. It had been deferred twice with the same reason: *a baseline built before there's a single instance of "slow" is a number nobody looks at.* That reason was right, but it pointed at something fixable rather than at "don't build it".

Nobody looks at it because on shared CI runners it goes red for no reason, and **a gate that goes red for no reason gets switched off** — which is the same as not having one. So the measurement is a **ratio**, not a duration: each run first executes a fixed calibration workload in the same process, and every target's time is divided by it. Machine speed cancels in the numerator and denominator. The threshold is a **multiple** (2×), not a percentage — the target is O(n) → O(n²), not 10% of scheduler jitter. Median of seven, never the mean.

What gets measured is **the gates themselves**, because they run per task: the cost of a slower gate is multiplied by the task count, and the concrete harm of "slow" here is not that someone waits — it is that verification gets abandoned.

This kind has a risk the others don't: every other gate's input is deterministic; this one's input is time. So **green stability is a standing assertion** — the same workload measured twice must not judge itself as regressed — alongside the usual red-reachability one. Measuring zero targets, or a calibration that rounds to zero seconds, both block: reporting "no regression" over nothing measured is the always-true report again.

**api-contract and property-fuzz are wired** (v1.16.0) — all five non-functional kinds that apply to this repo now run. Both were deferred for wanting a new dependency; both turned out to be stdlib problems.

- **api-contract** snapshots what this project actually promises — public top-level function signatures (imported by the MCP server and hooks) and the runner's CLI flags — with `ast`. It blocks **breaking** changes only: a module or public function disappearing, a required parameter disappearing *or appearing* (existing callers under-supply), a flag disappearing. Additions never block; a contract check that taxes extension gets switched off.
- **property-fuzz** targets the parsers that eat human-written text — the CHG parser, the verdict line, every `### …` declaration block, the four tool report formats. One invariant: **a parser must never raise an uncaught exception.** Returning empty, returning None, reporting an error are all fine; crashing is not, because a crash and a correct block are indistinguishable by exit code (KN-003).

The fuzzer raised a question the other kinds didn't: **it passed on its first run.** Zero failures and a broken engine look identical. So the engine takes injectable targets and a fixed seed, and a standing assertion feeds it a deliberately fragile function to prove the red light is reachable. Reporting zero failures over zero cases is treated as *not run*, never as passed.

**license-compliance and build-reproducibility are wired** (v1.15.0), and non-functional artifacts are now *judged* rather than merely counted. v1.14.0 shipped the dispatch (which kinds apply to which profile) but left the hole C2 had just closed elsewhere: it checked "command exited 0 and the artifact exists" and never read the contents. A report saying "12 GPL dependencies" exists and is non-empty — it would have passed.

- **license-compliance** reads dependency licences through stdlib `importlib.metadata` (License-Expression → License → Classifier), so checking licences doesn't itself add a dependency. **The project's own missing LICENSE blocks** — auditing everyone else's licence while never checking your own is the easiest square to miss, and this repo was missing one. Copyleft or unknown licences on dev-only dependencies are **named but not auto-blocked**: they don't infect what you ship, but somebody has to decide.
- **build-reproducibility** asserts two different things: the sync is idempotent (run twice, hashes match) *and* the committed plugin copies equal a fresh build. The first catches an unstable build; the second catches a hand-edited build artefact.
- **Per-kind `- defer: <reason>`** — a whole-section `n/a` would waive the kinds you *did* wire. A named deferral reports as **not covered**, never as passed; an empty one is treated as undeclared.

**Non-functional checks, scoped by project profile** (v1.14.0). Everything before this verified *correctness*; this covers *fast enough / stable / leak-free* — nine kinds: performance, load-stress, concurrency, resource-leak, build-reproducibility, license-compliance, api-contract, visual-regression, property-fuzz.

Adding all nine to every project would be the classic mistake: **tax a CLI/library repo with load testing and people switch the whole thing off**. So each kind declares `applies_to`, the project declares its own profiles once in `.ai-sdlc/profile.json` (multiple allowed), and the runner takes the intersection — it holds no built-in opinion about project types, because adding a new type should be editing data, not editing the runner.

This introduces a **third state**, and keeping the three apart is the entire point:

| state | meaning | what follows |
|---|---|---|
| pass | ran it, it passed | nothing |
| **not covered** | should verify, this environment can't | fix the environment |
| **not applicable** | this project type doesn't need it | permanent conclusion |

Reading "not applicable" as "pass" is the same error as reading "not covered" as "pass". A `Non-functional: n/a` waiver **must carry a reason** — otherwise anyone can delete the whole block by claiming "I'm not a backend". An undeclared profile means **everything applies**: when in doubt, err toward verifying more.

**The delegated four now actually run** (v1.13.0). They had a *place* since v1.9.0 — a kinds table, a declaration parser, an artifact check — but had never been run once. Reading the code showed why it wasn't merely "not done yet": it would have been **broken on arrival**. `run_gate` judged by *exit code* (mypy has 72 findings in this repo → red from day one) and otherwise only checked that the artifact *existed* (a report full of errors exists and is non-empty). Judging by exit code is permanently red; judging by existence is not judging.

So the unit of judgement is the **delta against a baseline**: existing findings are baselined (each with a named reason), **new ones always block**, and the baseline **only ratchets down** — a finding that disappears is reported so the entry gets removed. Fingerprints exclude line numbers (they drift; rules and files don't). bandit is graded by severity × confidence — the 80 LOW findings are listed but don't block, because noise is what makes people switch a gate off. Coverage is a ratchet, not a threshold. A baseline entry without a reason is rejected outright: a waiver has to be signed.

**The review is a panel, not one opinion** (v1.12.0). The runner used to *print* "same model = shared blind spots" and then do nothing about it — a warning nobody acts on becomes background noise. Review now scales with risk, reusing the governance layer's panel machinery (ai-sdlc `references/review-panel.md`) rather than inventing a second one:

- **Seats, one domain each** — `conformance` (does it do what the task said, verbatim), `defect` (will it break, with a triggering condition), `idiom` (does it read like this codebase). Each seat gets **only its own row**; the panel view belongs to the dispatcher. `--seat-cmd conformance=<cmd>` points seats at different models; without it, all seats share one and the runner **says so**.
- **Risk-scaled**: low = 1 seat (the existing fast path, unchanged), medium/high = 3. `--review-panel N` can raise the count, never lower it below the floor.
- **Confidence downgrades, never averages** — a verdict below `--confidence-threshold` (default 80) becomes `cannot-verify`. review-panel is explicit that disagreement is *reconciled or escalated, never averaged*: one confident objection must not be diluted by two seats that never looked at that corner.
- **`spec: fail` is a veto** the adjudicator cannot overrule, and **all-seats-cannot-verify halts** — "couldn't tell" is not "no problem" (KN-004).
- **High risk adds a cross-read phase**: seats first verdict independently (anti-anchoring), then read each other's and flag agree/disagree. A disagreement escalates; the runner never reconciles it for them.

The arithmetic runs in the runner (no LLM). Handing the tally to a model would put that model's blind spot over every seat's, and add one more layer of model-relaying-model.

<!-- claim: gates-wired-blocks-gate-deletion -->
**Two gates on the tests themselves** (v1.11.0). `test_gates_wired.py` blocks *deleting a gate*; the same sentence one level down had nobody watching it — **the cheapest way to turn a build green is to delete the failing test**. The unit gate only asks whether the test command returned 0, and it does once that test is gone; the mutation gate reports *not covered* when there are no tests at all, never failure.

- **test ratchet**: the task's diff must not net-reduce test functions or assertions (AST-counted, so `# assert` in a comment and `"assert"` in a string do not inflate the baseline). Deleting a whole test file counts as a full loss — otherwise deleting a function is blocked while deleting the file it lives in gets through. Merging three small test files into one is *not* blocked: the judgement is on totals, not per file. Statement count carries a 10% tolerance band, which catches "kept the function shell, deleted the assertions" without flagging ordinary tidying. `--allow-test-reduction` is the explicit, logged escape hatch.
- **flaky detection**: once the unit tests go green, they are re-run on the *same code*. Passing once is not passing — an unstable green and an always-true green are the same failure (KN-001). `--flaky-runs N` (default 2, floor 1) sets the total; N=1 disables it and is logged.

Gate order stays cheapest-first: test → ratchet (AST + git) → static (AST) → flaky (re-runs tests) → mutation.

**The fix loop carries the failure back** (v1.10.0). A gate going red used to retry with the *same brief* — the builder never saw why it failed, so the retry was a re-roll, not a fix. Now every round feeds the previous round's **verbatim** failure (test stderr, static finding, surviving mutants, review verdict line) into the next brief, and the re-review gets the same findings list to confirm item by item. `--max-fix-rounds` (default 3, floor 1) bounds it; the last round switches to `--escalate-cmd` if given, and says so plainly if not (same model = only the prompt changed, not the blind spot). Hitting the cap halts (exit 3) and prints **every round's unresolved finding**, not just the last line.

**The verifier is itself verified.** `verifier_integrity.py` anchors SHA-256 of the 100 files that constitute the checking apparatus; re-anchoring requires naming the authorising CHG. `test_gates_wired.py` asserts by AST that the gates are still wired in — because the cheapest way to defeat a gate is to delete it, and a deleted gate does not complain. Since v1.10.0 that includes the feedback path itself: removing it breaks no test on its own, because the loop still runs the same number of rounds — it just re-rolls each time.

`--test-cmd` = per-task unit/build tests; `--verify-cmd` = the end-stage operational test (run the change for real). Without `--verify-cmd` the operational-verify stage halts (exit 3) for a human to perform it.

<!-- claim: sentinels-two-tier-escape -->
`sentinels` runs deterministic requirement-confirmation polling with two-tier escape (A cannot-evaluate → exit 0 baseline; B real halt → exit 3 escalate); wire it on a schedule via `scripts/sentinel_install.py` (creating cron/CI **halts for human authorization**). Governance semantics are anchored in ai-sdlc `references/autonomy.md` — this layer only drives. See autopilot-loop "Standing sentinels & scheduled re-entry".

`--review-cmd` sends the per-task review to a **different command/model from the builder**; omitting it falls back to `--agent-cmd` and **says so** (same model = shared blind spots). Model choice per role: ai-sdlc `agent-hierarchy`.

The runner contains **no LLM**: it is a state machine and referee — the building and reviewing are done by whatever headless agent command you configure. Exit codes: `0` done, `1` unexpected error, `2` invalid plan, `3` legitimate halt (the reason is printed; wire cron/CI on these).

## Storage convention


Everything lands in the **target project's** existing ai-sdlc ledger — see the mapping in [`docs/ai-sdlc-autopilot/structure/data.md`](../../docs/ai-sdlc-autopilot/structure/data.md) (plan → CHG, verdicts → ACC evidence, root causes → knowledge, one commit per task carrying the CHG id).

## NOTICE (attribution)


The execution methodology here — the plan's Global Constraints / per-task Interfaces blocks, single-reviewer dual verdict (spec + quality) with a legitimate "cannot-verify from diff" outcome, end-of-run whole-branch review, and the TDD / systematic-debugging discipline — is adapted from **Superpowers** by Jesse Vincent (obra), MIT License, © 2025 Jesse Vincent. See [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md). Differences: outputs land in the ai-sdlc ledger (no separate plans/specs directories), triggering is skill-detection + runner (no harness hooks), and halts are driven by governance-layer risk grading.
