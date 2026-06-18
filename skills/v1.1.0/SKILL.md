---
name: ai-sdlc
description: >
  AI development governance suite that splits work into four documented stages — requirement
  analysis, structure design, modification governance, and acceptance — so every AI task reads
  the docs first and stays consistent and traceable. Use this whenever the user plans a new
  project or feature, clarifies requirements, designs system architecture or a database,
  proposes any modification or new feature, or wants to verify whether results meet the bar;
  follow the staged flow and read the matching guide under references. Covers producing an AI
  Guideline, the four structures (directory/logical/design/data), change records with impact
  analysis, and acceptance reports with a re-fix loop. Important: as soon as the user proposes
  a modification or new feature, go through modification governance first rather than editing
  code directly.
metadata:
  version: 1.1.0
---

# ai-sdlc — AI Development Governance

> 語言 / Language: [繁體中文](SKILL.zh-tw.md) · **English**

This skill gives the AI a consistent process when assisting with development. Core idea:
**capture requirements, structure, changes, and acceptance as documents first, then read those
documents as the basis for later work** — instead of guessing from scratch each time. Before
acting, read here to decide "which stage applies now", then read the matching guide under
`references/`.

**One skill, solo to team**: defaults to solo / single-agent; **when it detects collaboration (multiple agents, cross-session handoff, multiple repos) it auto-escalates to team mode**, loading the matching collaboration references. "Team" isn't limited to humans — it can be an **AI-agent team** (different instances / contexts) collaborating through `docs/`. No edition to choose; one skill adapts.

## Detect → load (auto-detect, user can choose / override)

**Auto-detect by default: when you detect the situations below, proactively load the matching reference without being told. But the user may explicitly choose or override — the user's instruction wins** (e.g. "force team mode", "no CI/CD this time", "skip cross-repo", "self-verify is fine"); auto-detection applies only when the user hasn't specified.

| Situation | Detection cues (any one counts) | Load |
|-----------|----------------------------------|------|
| Multiple repos / shared contract | several repo paths/URLs; mentions of frontend+backend, microservice, SDK+server, multi-package monorepo; changes to API/schema/event/shared types/protobuf; words: cross-repo, contract, upstream/downstream, integrate | `cross-repo` (+ `scripts/cross_repo_check.py`) |
| Parallel / cross-session handoff | multiple agents at once; taking over someone's / a prior session's project; words: take over, hand off, continue, simultaneously, in parallel, split up | `cross-agent` |
| Dispatch sub-agents / multi-agent split | you plan to spawn subagents; task large enough to split across units; words: dispatch, sub-agent, split tasks, divide, orchestrate | `agent-worklog` + `agent-hierarchy` |
| Modification / new feature (existing system) | adjust/fix/extend/refactor/rename/delete an existing feature/file/table; words: change, add, tweak, refactor, optimize, fix bug, replace | `modification-guide` (**mandatory**) |
| Acceptance / confirm it meets the bar | "done / is this right / verify / check / test it"; a change just implemented | `acceptance-verification`; **high-risk → `independent-acceptance`** |
| Taking over / cross-session entry | every new session start, or taking over an existing `docs/` project | Session startup check: read existing docs/ + error knowledge base + `doc-integrity` |
| Has / adopting CI/CD | repo has `.github/`, `.gitlab-ci.yml`, `.pre-commit-config.yaml`, Jenkinsfile; or mentions pipeline/hook/gate | `ci-cd` (optional) |
| Autonomous multi-stage run / external orchestrator drives the flow | an agent will auto-run several stages, or Python/etc. drives it; words: run end-to-end, autonomous, unattended, automated flow | `autonomy` (halt-point contract; query `scripts/halt_gate.py`) |

**Close false negatives (better over-load than miss)**: cues are often implicit — "while you're at it, also tweak the backend" = multi-repo + modification; "you split it up" = multi-agent; "continue that earlier project" = cross-session takeover. **If a cue plausibly matches, load the reference**; over-loading is cheap, missing governance is costly. When unsure, lean toward loading.

Explicit wins, else detect: **follow an explicit instruction when given; otherwise use detection.** Overrides may tighten safety freely; when the user wants to relax a high-risk gate, flag the risk first, then follow their decision.

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

1. Read the latest CHG under `docs/changes/`: any whose status is not "Accepted" means the previous session's change is only half complete.
2. Cross-check `docs/acceptance/`: if a CHG has no matching ACC report, acceptance was handed off but nobody picked it up.
3. **Close those pending acceptances first (run acceptance-verification), then start the new requirement.**

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

## Document storage convention

Outputs live under the **target project's** `docs/` (not this skill):

```
target-project/docs/
├── ai-guideline.md          # from requirement analysis
├── structure/{directory,logical,design,data}.md   # from structure design
├── changes/CHG-YYYYMMDD-NN.md                      # one per change
└── acceptance/ACC-YYYYMMDD-NN.md                   # one per acceptance
```

If the target project already has a documentation convention, follow that and note the actual
paths in the AI Guideline.

## Operating principles

1. **Read before doing**: read the stage guide and existing docs before acting.
2. **Documents are the truth**: if the structure changes, update the structure docs in sync.
3. **Trace every change**: a modification always leaves a record under `docs/changes/`.
4. **Acceptance aligns to source**: criteria come from the Guideline and the change's mod guide.
5. **Don't rely on memory — rely on the docs**: a long conversation's context may be compacted, losing or distorting earlier decisions. **Don't go by recollection** — before acting, re-confirm existing constraints and decisions from the files under `docs/` (Guideline, structure, CHG, ACC); when memory and the docs disagree, the docs win. This keeps compaction, cross-session work, and handoffs from causing drift.
