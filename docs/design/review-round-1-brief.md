# Design review — CHG-20260823-11 (an operator console)

You are one of two independent reviewers. The other has the same brief and you will not see
its answer. Do not soften a verdict to look agreeable, and do not manufacture a disagreement
to look independent.

## What this is NOT

This is **not** an acceptance review. **No code has been written.** `src/` is untouched by this
change; the only files added are `docs/changes/CHG-20260823-11.md` and
`docs/design/console-mockup.html` (a browser mock-up with no back end).

So do not look for an implementation and do not report "the tasks are unticked" as a finding —
that is the record's own claim. Review **the design**, and review **whether the record tells the
truth about itself**.

## Read, in this order

1. `docs/changes/CHG-20260823-11.md`   — the design record
2. `src/ai_sdlc_runner/engine.py`      — especially `walk`, `_adjudicate`, `_answered_branch`,
                                          `_note_panel_diversity`, `_finish`
3. `src/ai_sdlc_runner/policy.py`      — especially `adjudicate`, `GATES`, `classify`
4. `src/ai_sdlc_runner/graph.py`       — the 23 nodes and what a node's role means
5. `docs/design/console-mockup.html`   — skim; it is the interaction spec, not code to be shipped

## The seven questions

**Q1 — The front/back line.** The record says the front end holds *no* governance: never decides a
verdict, never adjudicates, never skips a gate, and closing the tab does not stop a run. Read the
endpoint list in the record and the mock-up's behaviour. **Is there any place where the front end is
in fact deciding something, or where the back end would be trusting a value the front end computed?**
Name the endpoint.

**Q2 — `Approver`, and the halt guarantee.** Today every halt works by ending the process. Task 1
makes a gate *block and wait*. The record calls this the dangerous change and grades the record high
risk for it. Look at how `engine.walk` currently reaches a stopping verdict and how `_finish` reports.
**Is a callable `Approver` the right shape? What state becomes reachable that is not reachable today,
and is there a way for "alive and stopped" to be mistaken for "alive and continuing"?** If you think
a different shape is safer (e.g. the walk returning a suspended state the caller resumes, rather than
calling out mid-walk), say which and why.

**Q3 — `undecided` in `policy.adjudicate`.** Task 2 changes `adjudicate` to return `undecided` on a
tie where it returns fail today. There are tests asserting the current rule.
**Does `undecided` belong in `policy`, or should `policy` keep returning fail and the caller decide
to stop?** Concretely: is there any existing caller that would treat a new third return value as
falsy / not-fail and continue? Grep for the call sites and say.

**Q4 — Pool vs panel.** A verdict node with N models is N adjudicated voices. A coding node
(main → sub) with N models is a **pool** the main dispatches to at random; one does the work.
**Is the distinction well-founded and, more importantly, is it decidable from the node data in
`graph.py`?** If the runner has to infer which kind a node is, that inference is the failure. The
repo has shipped the same defect class four times: a coarse check answering "safe" about something
it had not examined. **Could a node be configured with three models and silently ask one?**

**Q5 — The re-run carry.** An undecided panel may be re-run N times; from round 2 each voice is told
what every reviewer said last round, for and against, with attribution. The record accepts the
anchoring cost knowingly. **Is the reasoning sound, or does this destroy the independence the panel
exists for?** Note that the seats' own independence (`halt_independent`, `_note_panel_diversity`) is
governance, and a panel on an ordinary node is not the same thing — say whether the record conflates
them.

**Q6 — What is missing.** The record names three unsettled items (pool retry behaviour; a
work-producing node with several models and no main/sub; two browsers on one runner). **What else is
missing from the 11 tasks that would have to exist for this to work?** Be specific — a missing task,
not a topic.

**Q7 — Does the record tell the truth about itself?** CHG-20260822-04 was design-only, said so, and
was never swept when its tasks landed, so it simultaneously claimed "all nine tasks built" and
"nothing in src/ has been written". This record's Status section is written to prevent that.
**Read it as an adversary: what does this record assert that a reader could not verify from the repo,
and where would it go stale first?**

## Answer format

For each question: a verdict word, then the reasoning, then the file:line evidence.
End with one overall line: `DESIGN: sound` / `DESIGN: sound with changes` / `DESIGN: not sound`
and, if not simply sound, a numbered list of what must change before Task 1 may start.

Cite `file:line`. If you cannot substantiate a claim from the repo, say "not substantiated" rather
than reasoning from what a system like this usually does.
