---
name: onboarding
description: >
  Bringing a repo under governance: when there is no ledger yet, decide which path it takes
  (greenfield init / brownfield adopt) and where the ledger goes. The predicate is "a ledger was
  found", not "a docs/ directory exists" — a directory name is not an identity. Covers the
  location rule (docs/ by default, sdlc_docs/ when occupied), the no-overwrite and resume
  discipline, the governance baseline for existing codebases, and migrating an old path. Read
  this before touching an ungoverned repo.
---

# onboarding — bringing a repo under governance

> 語言 / Language: [繁體中文](onboarding.zh-tw.md) · **English**

## Purpose

`init` and `adopt` are two halves of one question: **this repo has no governance — which door
does it go through, and what must not be destroyed?** Both use this file, because the routing
decision **can only live in one place**. Split across two, the two doors each guess — and they
guess differently.

Handshake (see handshake) handles what happens once a ledger exists. This file handles the step
before that.

## The predicate: find a ledger, don't look for `docs/`

**`docs/` is not an identity.** It is the location this process *proposes*, not one that is
guaranteed to exist or to be ours. The skill itself says "if the target project already has a
documentation convention, follow that". And `docs/` is one of the most common directory names in
software:

| Someone else's use | What writing the ledger there does |
|---|---|
| Publish root (MkDocs / Docusaurus / Jekyll / Pages source) | CHG/ACC get built into the site nav as user-facing product pages; generators that require front matter **fail the build** |
| Generated output (Sphinx build, generated API docs) | The next regeneration **deletes the ledger**, silently |
| Another agent convention's territory | The two overwrite each other |

The second row is **data loss**, not disclosure — a governance ledger is meant to be public; the
problem was never confidentiality.

**`AGENTS.md` is not an identity either**: it is now a cross-vendor convention that other tools
also write.

The only unambiguous marker is **the ledger itself** — a directory holding
`CHG-YYYYMMDD-NN.md`, wherever it lives. Machine assist:
`doc_integrity_check.ledger_roots(repo)`, whose candidate roots come from `DOC_ROOT_NAMES`
(data, not a hardcoded line). **Not found returns an empty list, never an assumption** —
"assume `docs/` when nothing is found" makes callers scan zero files and then report no
problems, and nobody investigates a green light (the mirror of KN-001).

## Four-state routing

```
find a ledger (do not assume docs/)
├─ found ──────────────────────► governed: go to handshake
└─ not found
   ├─ no existing code ────────► init
   ├─ existing code ───────────► adopt
   └─ docs/ exists but is theirs ► decide the location first (below), then take one of the two
```

"Existing code" means: any source, tests, or build configuration beyond docs and settings.
**When you cannot tell, fall toward `adopt`** — treating an empty repo as brownfield costs a few
extra questions; treating a brownfield repo as empty costs someone else's files (KN-004: follow
where the cost of being wrong falls).

## Location: `docs/` by default, switch only when occupied

| Situation | Location |
|---|---|
| `docs/` absent, or present and empty | **`docs/`** (unchanged default) |
| `docs/` already occupied | **`sdlc_docs/`** |

**Occupancy signals** (any one counts):

- A site generator config: `mkdocs.yml`, `docusaurus.config.*`, `_config.yml`, `conf.py`
  (Sphinx), `book.toml` (mdBook), or a repo setting that publishes `docs/` as the Pages source.
- Generated-output markers: `docs/_build/`, `docs/.doctrees/`, `docs/site/`, or a `.gitignore`
  entry covering part of `docs/`.
- `docs/` already holds content that isn't ours, and none of it is a ledger.

**The location always goes into the Guideline header — declared, not inferred.** The next agent
should not have to decide again; a judgement varies with the environment, a declaration does not.

## In-progress marker: "half onboarded" must not look like "onboarded"

The routing predicate is "a ledger was found" — and **the ledger becomes findable partway
through onboarding**. If `init` / `adopt` is interrupted after creating the first `CHG-*.md`
(or even the first `changes/` directory), the next entry finds a ledger, concludes "governed",
and **skips whatever was left undone**. A half-built skeleton walks straight into the change
flow, and nothing complains.

So onboarding's **first** action is to write a marker, and its **last** action is to remove it:

```
<root>/.onboarding        # contents: INIT|ADOPT + which step it reached + time (UTC+0)
```

- **Marker still present on entry** → the previous onboarding never finished. **Do not proceed
  into the change flow**; resume from the recorded step (see "Never overwrite, always resumable"
  above), and remove the marker only on completion.
- Relationship to handshake: step 5's reconciliation reads it and treats it as an unclosed stage.
- This is the last-act discipline applied to onboarding: intent lands on disk before acting, the
  outcome immediately after. Hold that, and an interruption leaves a state distinguishable from a
  clean finish — and **distinguishable** is the only thing wanted here (KN-003: "half done" and
  "done" must not look alike).

## Never overwrite, always resumable

Both `init` and `adopt` are multi-step flows that write files, and the session can end at any
step (see handshake, "last-act discipline"). So both must:

- **Never overwrite an existing file.** If it exists, skip it and name it, and let a human decide
  whether to merge. "Re-running is faster" is not a reason to overwrite someone's corrections.
- **Be resumable**: a re-run fills only what is missing and rebuilds nothing that already exists;
  an interruption leaves no half-set.
- **Print the plan first**: before writing, list which files will be created, marking existing
  ones as skipped.

## init — starting from zero

1. Decide the location (above) and write it into the Guideline header.
2. requirement-analysis → `<root>/ai-guideline.md`.
3. structure-design → `<root>/structure/{directory,logical,design,data}.md`.
4. Create `<root>/changes/`, `<root>/acceptance/`, `<root>/knowledge/` (a zero-entry INDEX plus a
   seed `vocabulary.json` — see knowledge, "found it first").
5. Create a root `AGENTS.md`; every tool-specific convention file present (`CLAUDE.md`,
   `GEMINI.md`, `.cursorrules`, `.github/copilot-instructions.md`, …) keeps a **two-line stub**
   pointing at it, carrying no content of its own (duplicates drift).

## adopt — bringing an existing codebase in

The code already runs and has never been governed. The difference from init is not the number of
steps — it is that **two things run in the opposite direction**: the structure docs are
*reverse-engineered*, and the history **must not pretend it was governed**.

### Label the evidence level when reverse-engineering

Everything derived from existing code must be labelled:

| Label | Meaning |
|---|---|
| **Observed** | Readable directly from the code (this module imports that one) |
| **Inferred** | Intent deduced from evidence (this looks like it supports multi-tenancy) |
| **Unknown** | Cannot tell; a human has to answer |

The cost of skipping the labels is concrete: **an accidental implementation, a historical defect,
or even dead code acquires normative status by being written into a structure document.**
"Unknown" is not a failure, it is a to-do item; writing "unknown" as "inferred" is the failure.

### The governance baseline: six minimums

Declaring one commit as the baseline is not enough to prevent a forged history. These six are
the minimum:

1. **The baseline can only be the full SHA seen at adopt time** — not a date, not a tag (tags
   move), not an abbreviation.
2. **Create a separate adopt commit** and record its **parent SHA**. The baseline is the state
   before adoption; the adopt commit is the adoption itself. Merged into one, "what was already
   there" and "what was fixed during adoption" become indistinguishable.
   **This rule is machine-enforced** (CHG-20260811-02). Declare it in the Guideline header:

   ```markdown
   - Governance-baseline: <full 40-hex SHA>   # the state before adoption
   - Adopt-commit: <full 40-hex SHA>          # the adoption itself
   ```

   `doc_integrity_check` verifies each part against git: the commit exists, it has **exactly one
   parent** (a merge blurs the boundary; a root commit has no "before"), that **parent equals the
   declared baseline**, and the adopt commit **touches only governance files**. Both fields are
   required **together** — a baseline alone is no anchor, an adopt commit alone has no starting
   point. **And once the declaration has appeared in history it may not vanish**: deleting it
   makes this check report "not applicable", and not-applicable looks exactly like a pass.
   Projects that never declared it (most of them — they weren't adopted) are reported as **not
   applicable**, which is not the same as passing.
3. **Record the working-tree state**: uncommitted changes, untracked files, submodules, LFS
   pointers. The declared commit is not the same as what was actually inventoried.
4. **Never backfill a CHG before the baseline.** There was no governance, and that fact *is* the
   record. Writing it up as though there had been replaces "no record" with "a false record",
   and the second is harder to detect.
5. **The first governed change starts after the adopt commit**, never before it.
6. **"Inventoried" is not "accepted".** Existing defects, coverage holes, and security debt are
   not ratified by adoption; acceptance goes through acceptance-verification and cannot be a side
   effect of adopting.

The sixth is the one that gives way first: after adoption the repo looks tidy, and tidy reads as
healthy.

### What to do with defects found along the way

Register defects found while reverse-engineering as **named, findable pending items** — do not
quietly fix them and do not quietly leave them. Quietly fixing mixes substantive change into the
adopt commit (violating rule 2); quietly leaving them lets adoption ratify them.

## Migrating an old path

When a ledger already exists somewhere but the location must change (for example `docs/` later
becomes a site generator's root):

- **Move only our files**: `CHG-*.md`, `ACC-*.md`, `structure/`, `knowledge/`,
  `ai-guideline.md`. The test is **what a file is, not which directory it sits in** — nothing of
  theirs moves.
- **`git mv`**, so history follows. Non-git projects degrade to copy-then-delete, declared in the
  ack.
- **Dry run by default**: print the full move list first, act only after confirmation. Moving
  files inside someone else's repo runs in the irreversible direction.
- **Resumable**: a re-run moves only what is left, leaving no half-set.
- The migration itself gets a CHG, and the Guideline header's location is updated.

Machine assist: `scripts/ledger_migrate.py` (dry run by default).

## Relationship to the existing flow

- This file comes **before** handshake: the handshake assumes the ledger can be found; this file
  is what makes that true.
- Steps 2 and 3 of `init` are requirement-analysis and structure-design; this file does not
  restate their content.
- Acceptance for `adopt` goes through acceptance-verification. Adoption **is not** acceptance.
- The location decision governs every machine assist's search scope — `doc_integrity_check` and
  `governance_health` both go through `ledger_roots()` and hardcode no directory name.
