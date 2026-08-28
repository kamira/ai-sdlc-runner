"""Break a guarantee on purpose and check that a test notices.

    python3 tools/mutation_check.py
    python3 tools/mutation_check.py --only importer
    python3 tools/mutation_check.py --only examples

Exit 0 if every mutation was caught, 1 otherwise.

## Why this exists

A test that stays green when the behaviour it names is broken is not a test, and this repository has
shipped three of them. The one that forced this file:

```python
def test_a_directory_named_like_a_conversation_does_not_stop_the_import(...):
    ...
    assert good.id in report["imported"] or report["refused"]
```

When the directory **did** stop the import, `imported` was empty and `refused` held one entry saying
the store could not be listed — so the `or` was satisfied and the test passed on the exact failure
its own name forbids. It shipped in CHG-20260823-45, it was marked done, and a review seat found it
rather than the suite.

Nothing in an ordinary green run distinguishes that test from a real one. Reverting the fix and
watching a test go red does.

## What this is not

**It is not coverage, and it is not mutation testing.** A real mutation tester generates variants
mechanically and finds the ones nobody thought about. Every entry here was written *after* a defect
was known, by the same person who fixed it. It proves the tests for the classes we have named can
fail; it proposes no new class.

That limitation is the honest reading of the table it produces, and it is worth stating twice
because a clean table invites the other reading.

**It is not a check on which scenarios got tested.** CHG-20260823-50's `frontier` group was 2/2
caught, its table read clean, and the defect shipped anyway — because the test pinning the claim
asserted over an ask history the shipped graph cannot produce. No mutation of the *code* can expose
a test whose *scenario* is unreachable. A review seat put it exactly: this answers "can the tests I
wrote fail?", never "did I write the test for the case that matters?"

**And a red is only meaningful against a green.** Until CHG-20260823-51 any non-zero exit counted as
caught, including a collection error or an unrelated pre-existing failure. Each file is now run
unmutated first.

## Adding a mutation

Add a `Mutation` with the smallest edit that makes the guarantee false — an inverted condition, a
dropped exception type, a normalisation skipped. Then check it fails for the *right* reason: the
first draft of the importer's first mutation rebound a dict to an equal dict, which changes nothing
and would have reported a false "not caught".
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/ai_sdlc_runner"

#: The checkers themselves (CHG-20260828-02). A guard is code that can be wrong: `ledger_check`
#: walked changes and never acceptances, so an ACC naming no change read as a pass. Mutating the
#: guards is the only way to know they still refuse.
TOOLS = REPO / "tools"


class Mutation(NamedTuple):
    group: str
    #: What becomes untrue. Phrased as the defect returning, because that is what is being tested.
    says: str
    path: Path
    before: str
    after: str
    #: The tests that must notice. A narrow file keeps a run to seconds.
    tests: str


MUTATIONS: List[Mutation] = [
    Mutation(
        "importer", "the walk collapses same-named files across projects again",
        SRC / "conversations.py",
        '''    files = _inventory(root)''',
        '''    files = _inventory(root)
    files = list({r["name"]: r for r in files}.values())''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a refusal names the bare stem instead of the file",
        SRC / "conversations.py",
        '''            where = f"{record['project']}/{record['name']}" if record["project"] else record["name"]''',
        '''            where = str(record["name"]).split(".")[0]''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a broken target is blamed on the source conversation again",
        SRC / "conversations.py",
        '''        except (TargetError, OSError) as exc:''',
        '''        except (TargetError,) as exc:''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "the collision comparison stops normalising the two sides",
        SRC / "conversations.py",
        '''    body = {k: v for k, v in turn.items() if k not in Turn.ENVELOPE}
    return (int(turn.get("seq", 0)), str(turn.get("kind") or ""), str(turn.get("at") or ""),
            json.dumps(body, ensure_ascii=False, sort_keys=True))''',
        '''    return (json.dumps(dict(turn), ensure_ascii=False, sort_keys=True),)''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a header naming a different project than its directory is accepted",
        SRC / "conversations.py",
        '''            if in_header != project:''',
        '''            if False:''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a filename disagreeing with its header's id is accepted",
        SRC / "conversations.py",
        '''            if name != f"{cid}.jsonl":''',
        '''            if False:''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "examples", "the agent runs in the operator's shell directory again",
        SRC / "cli.py",
        '''                                      cwd=self.cwd)''',
        '''                                      cwd=None)''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "examples", "agent_cwd stops defaulting to the config file's directory",
        SRC / "cli.py",
        '''    config_cwd = config.get("agent_cwd") or None''',
        '''    config_cwd = None''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "provenance", "the plan a run walked is recorded as the operator's keystrokes again",
        SRC / "cli.py",
        # Pinned to `cmd_run` by the journal line above it: `cmd_serve` builds the same
        # conversation and the bare line matched both (CHG-20260828-01).
        '''        args, journal_dir=args.ask_journal,
        run={"journal": str(Path(args.ask_journal).resolve()) if args.ask_journal else None,
             "plan": _where(args.plan)})''',
        '''        args, journal_dir=args.ask_journal,
        run={"journal": str(Path(args.ask_journal).resolve()) if args.ask_journal else None,
             "plan": str(args.plan)})''',
        "tests/test_run_provenance.py"),

    Mutation(
        "frontier", "an engineer reporting nothing left is discarded again",
        SRC / "engine.py",
        '''    if remaining and last_word == "":''',
        '''    if False:''',
        "tests/test_rerun_idempotence.py"),

    Mutation(
        "frontier", "a missing module key is read as 'nothing left'",
        SRC / "engine.py",
        '''        if "module" not in ask.result:''',
        '''        if False:''',
        "tests/test_rerun_idempotence.py"),

    Mutation(
        "routing", "an unrouted halt stops reaching the operator",
        SRC / "policy.py",
        '''    told.append(DEFAULT_RECIPIENT)
    return tuple(told)''',
        '''    return tuple(told)''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a kind nobody has heard of raises instead of falling back",
        SRC / "policy.py",
        '''    return DEFAULT_RECIPIENT, "default"''',
        '''    raise PolicyError(f"no route for {kind!r}")''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a kind with a typo in it is accepted at configuration time",
        SRC / "policy.py",
        '''    unknown = sorted(k for k in routing if k not in PERMANENT_HALT_KINDS)''',
        '''    unknown = []''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a project's own routing stops overriding the policy table",
        SRC / "policy.py",
        '''    if routing:
        named = str(routing.get(kind) or "").strip()''',
        '''    if False:
        named = str(routing.get(kind) or "").strip()''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "the owners stop being listed in the order their kinds were crossed",
        SRC / "policy.py",
        '''        if owner != DEFAULT_RECIPIENT and owner not in told:
            told.append(owner)''',
        '''        if owner != DEFAULT_RECIPIENT and owner not in told:
            told.insert(0, owner)''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a halt stops recording who it was for",
        SRC / "engine.py",
        '''            report.halts.append({"node_id": node.id, "kinds": kinds,''',
        '''            [].append({"node_id": node.id, "kinds": kinds,''',
        "tests/test_halt_routing.py"),

    Mutation(
        "frontier", "an empty answer latches, foreclosing every later plan",
        SRC / "engine.py",
        '''            last_word = None
            continue''',
        '''            continue''',
        "tests/test_frontier_latch.py"),

    Mutation(
        "frontier", "an engineer reporting a failure is read as 'nothing left' again",
        SRC / "engine.py",
        '''        if not name and _went_wrong(ask.result):''',
        '''        if False:''',
        "tests/test_frontier_latch.py"),

    Mutation(
        "examples", "a --seat-model command is relocated into the config's directory again",
        SRC / "cli.py",
        # Re-anchored (CHG-20260828-02): stale since CHG-20260827-23 added `risk` and `can_write`
        # to this call, so this mutation had been reporting ANCHOR GONE to anyone who ran the group
        # and nothing to anyone who did not.
        '''                        timeout, retries, cwd=config_cwd if from_config else None,
                        risk=risk, can_write=_may_write(seat, role),''',
        '''                        timeout, retries, cwd=config_cwd,
                        risk=risk, can_write=_may_write(seat, role),''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "examples", "an explicit relative agent_cwd is left for the shell to resolve",
        SRC / "cli.py",
        '''    elif not Path(str(given)).is_absolute():
        config["agent_cwd"] = str((here / str(given)).resolve())''',
        '''    elif False:
        config["agent_cwd"] = str((here / str(given)).resolve())''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "importer", "one unreadable conversation in the target aborts the whole import again",
        SRC / "conversations.py",
        '''        except Exception as exc:
            named = ""''',
        '''        except Exception as exc:
            raise
            named = ""''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "risk", "gates read the proposed grade again, not the strictest candidate",
        SRC / "engine.py",
        '''        candidates = [cfg.risk] + list(report.risk_proposed.values()) + list(
            cfg.workstreams.values())
        return policy.strictest([c for c in candidates if c])''',
        '''        return cfg.risk''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a signed-off grade stops taking effect",
        SRC / "engine.py",
        '''    settled = report.risk_settled
    if not settled:''',
        '''    settled = report.risk_settled
    if True:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "one cautious voice can set the grade alone again",
        SRC / "policy.py",
        '''    if top * 2 > total:''',
        '''    if True:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a voice that answered something other than a grade is accepted",
        SRC / "policy.py",
        '''    unknown = sorted({g for g in grades.values() if g not in RISKS})''',
        '''    unknown = []''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "the grader stops having to be a panel",
        SRC / "graph.py",
        '''        if node.grades_risk and node.mode != MODEL_PANEL:''',
        '''        if False:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a work-producing step may be a panel again",
        SRC / "graph.py",
        '''        if node.mode == MODEL_PANEL and node.kind != DECISION and not node.grades_risk:''',
        '''        if False:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a node in no workstream reads the loosest instead of the strictest",
        SRC / "engine.py",
        '''        return policy.strictest(list(cfg.workstreams.values()) + [settled])''',
        '''        return min(list(cfg.workstreams.values()) + [settled], key=policy.RISKS.index)''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a node stops reading its own workstream's grade",
        SRC / "engine.py",
        '''            grade = cfg.workstreams.get(named)
            if grade:
                return grade''',
        '''            grade = cfg.workstreams.get(named)
            if False:
                return grade''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "the operator's override stops overriding",
        SRC / "engine.py",
        '''    if cfg.risk_override:
        return cfg.risk_override''',
        '''    if False:
        return cfg.risk_override''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a workstream graded with a word that is not a grade is accepted",
        SRC / "plan.py",
        '''        if grade not in policy.RISKS:''',
        '''        if False:''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a node may point at a workstream nobody declared",
        SRC / "plan.py",
        # This anchor was unique when it was written. CHG-20260827-22 added a second
        # `if name not in workstreams:` — the interfaces guard — and silently made it ambiguous;
        # nothing reported that until CHG-20260828-01 added the check. Pinned by its own message.
        '''        if name not in workstreams:
            raise PlanError(
                f"{where} puts node {node_id!r} in workstream {name!r}''',
        '''        if False:
            raise PlanError(
                f"{where} puts node {node_id!r} in workstream {name!r}''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a declared workstream may have no name",
        SRC / "plan.py",
        '''        if not str(name).strip():''',
        '''        if False:''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "the plan's workstreams stop reaching the run",
        SRC / "cli.py",
        # Pinned to `cmd_run`: `cmd_serve` builds the same RunConfig, and mutating the console path
        # would leave the tested path working while the run printed CAUGHT (CHG-20260828-01).
        '''        workstreams=plan.get("workstreams") or {},
        node_workstream=plan.get("node_workstream") or {},
        interfaces=plan.get("interfaces") or {},
        # From the command line and nowhere else''',
        '''        workstreams={},
        node_workstream=plan.get("node_workstream") or {},
        interfaces=plan.get("interfaces") or {},
        # From the command line and nowhere else''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "sandbox", "a role that may not write gets a pen again",
        SRC / "policy.py",
        '''    if not can_write:
        policy_for_grade["write"] = "none"''',
        '''    if False:
        policy_for_grade["write"] = "none"''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "a high grade binds the workspace writable",
        SRC / "sandbox.py",
        '''    if wanted["write"] == "workspace":
        out += ["--bind", root, root]''',
        '''    if True:
        out += ["--bind", root, root]''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "the network is never denied",
        SRC / "sandbox.py",
        '''    if not wanted["network"]:
        out += ["--unshare-net"]''',
        '''    if False:
        out += ["--unshare-net"]''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "an unenforceable sandbox is reported as enforced",
        SRC / "sandbox.py",
        '''        return list(argv), {**wanted, "mechanism": None, "enforced": False}''',
        '''        return list(argv), {**wanted, "mechanism": None, "enforced": True}''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "asking for a sandbox the machine cannot give proceeds anyway",
        SRC / "sandbox.py",
        '''        if required:
            raise SandboxError(''',
        '''        if False:
            raise SandboxError(''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "the platform stops deciding which mechanism is used",
        SRC / "sandbox.py",
        '''        if not running.startswith(needs_platform):
            continue''',
        '''        if False:
            continue''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "the dispatched process stops being told the role's capability",
        SRC / "cli.py",
        '''        named = policy.BY_ROLE.get(role or "")''',
        '''        named = None''',
        "tests/test_sandbox.py"),

    Mutation(
        "planning", 'a programme with several workstreams is planned as one',
        SRC / 'engine.py',
        '    return "split" if len(cfg.workstreams or {}) > 1 else "single"',
        '    return "single"',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the run gets to answer the scope question itself',
        SRC / 'engine.py',
        '    if node.id == "plan_scope":',
        '    if node.id == "plan_scope" and value is None:',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'interfaces are compared by signature instead of by name',
        SRC / 'engine.py',
        '            seen.setdefault(label, {})[workstream] = signature',
        '            seen.setdefault(signature, {})[workstream] = signature',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'a conflict is reported as agreement',
        SRC / 'engine.py',
        '    found = conflicts(cfg.interfaces)\n    if not found:\n        return "agree"',
        '    found = conflicts(cfg.interfaces)\n    if True:\n        return "agree"',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'an unresolvable conflict cycles instead of halting',
        SRC / 'engine.py',
        '    if all(note in report.dispatches for note in notes):',
        '    if False:',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the plan may declare interfaces for a workstream nobody declared',
        SRC / 'plan.py',
        '        if name not in workstreams:\n            raise PlanError(\n                f"{where} declares interfaces for workstream {name!r}',
        '        if False:\n            raise PlanError(\n                f"{where} declares interfaces for workstream {name!r}',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the declared interfaces never reach the run',
        SRC / 'cli.py',
        # Re-anchored (CHG-20260828-02): CHG-20260827-20 inserted `change_class=` between these two
        # lines the same day this was written, and nothing said so. Pinned to `cmd_run` by the
        # comment that follows only there.
        '''        interfaces=plan.get("interfaces") or {},
        # From the command line and nowhere else''',
        '''        interfaces={},
        # From the command line and nowhere else''',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the dispatch tree is no longer bounded on a run',
        SRC / 'engine.py',
        '    policy.check_dispatch_depth(graph.dispatch_edges(), graph.roles_asked_directly())',
        '    pass',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'a halt reports itself as a normal finish again',
        SRC / 'engine.py',
        '            report.state = STOPPED if node.permanent else FINISHED',
        '            report.state = FINISHED',
        'tests/test_sub_planning.py'),

    Mutation(
        "classes", 'a class dissolves a halt, not only a confirm',
        SRC / 'policy.py',
        '    if not named.relaxes or graded != CONFIRM:',
        '    if not named.relaxes:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", '`normal` starts relaxing gates',
        SRC / 'policy.py',
        '    ChangeClass("normal", relaxes=False, reviewed_after=False,',
        '    ChangeClass("normal", relaxes=True, reviewed_after=False,',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'a class never expires',
        SRC / 'policy.py',
        '    if review_by < today:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", "a pre-authorisation needs nobody's signature",
        SRC / 'policy.py',
        '    if not who:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'a class may be declared with no review date',
        SRC / 'policy.py',
        '    if not review_by:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'the class stops reaching the gate',
        SRC / 'engine.py',
        '    return policy.verdict(node.gate, risk, autonomy, change_class)',
        '    return policy.verdict(node.gate, risk, autonomy)',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'a plan may class itself again',
        SRC / 'plan.py',
        '    classing = sorted(set(unknown) & {"change_class", "class", "pre_authorised", "standard"})',
        '    classing = []',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'the command line accepts a class with parts missing',
        SRC / 'cli.py',
        '    if len(parts) != 3 or not all(p.strip() for p in parts):',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'an unknown class is guessed at instead of refused',
        SRC / 'cli.py',
        '    if name not in policy.BY_CLASS:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'the run stops recording which class let it through',
        SRC / 'engine.py',
        '    report.change_class = why',
        '    report.change_class = ""',
        'tests/test_change_classes.py'),

    Mutation(
        'guards', 'an acceptance for a change that does not exist is accepted again',
        TOOLS / 'ledger_check.py',
        '        if suffix not in known:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'guards', 'an acceptance filed against the wrong change stops being noticed',
        TOOLS / 'ledger_check.py',
        '        if stated and stated != f"CHG-{suffix}":',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        "cli", "refusal text goes to the terminal with its control characters intact",
        SRC / "cli.py",
        '''    return "".join(c if (c.isprintable() or c == " ") else''',
        '''    return str(value) or "".join(c if (c.isprintable() or c == " ") else''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "clock", "the turn clock loses millisecond resolution again",
        SRC / "conversations.py",
        '''    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")''',
        '''    return datetime.now(timezone.utc).isoformat(timespec="seconds")''',
        "tests/test_conversations.py"),

    Mutation(
        "finish", "the unspent-confirmation report goes back to success-only",
        SRC / "engine.py",
        '''    unspent = {gate: n for gate, n in confirmations.items() if n > 0}''',
        '''    unspent = ({gate: n for gate, n in confirmations.items() if n > 0}
               if report.halted_at == "done" else {})''',
        "tests/test_settings.py"),

    Mutation(
        "finish", "a gate stop is finished twice, so it complains twice",
        SRC / "engine.py",
        '''            # Already finished inside `_gate`; see the `before` site above.
            return stop''',
        '''            return _finish(stop, confirmations)''',
        "tests/test_settings.py"),
]


def _pytest(tests: str):
    """One narrow pytest run. Shared so the baseline and the mutated run are the same command."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", tests, "-q", "-p", "no:randomly", "--no-header",
         "-x", "--tb=no"],
        cwd=REPO, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})


def run(mutation: Mutation, baseline: Dict[str, bool]) -> bool:
    """Apply, run, restore. The restore is in a `finally` because leaving a mutated tree behind is
    a worse outcome than any result this function can report.

    ## Green first, or the red proves nothing

    `caught = returncode != 0` cannot on its own tell *"the pinning test failed for the pinned
    reason"* from a collection error, an import failure, or an unrelated red that was already
    there. Both review seats named this independently on CHG-20260823-47..50. A mutation that
    merely made a module unimportable would have been "caught" by every test file in the list.

    So each file is run **unmutated** once first, and a mutation whose file is not already green is
    reported as `NO BASELINE` rather than as caught. A red suite no longer turns into twelve
    confident ticks.

    This still does not prove a failure happened for the *right* reason — only that there was a
    green state for the mutation to break. That limit is real and is in the module docstring.
    """
    if not baseline.get(mutation.tests, False):
        print(f"  NO BASELINE  {mutation.says}")
        print(f"               {mutation.tests} does not pass unmutated, so a failure here would "
              f"prove nothing.")
        return False
    original = io.open(mutation.path, encoding="utf-8").read()
    found = original.count(mutation.before)
    if found == 0:
        print(f"  ANCHOR GONE  {mutation.says}")
        print(f"               {mutation.path.name} no longer contains the text this mutates. The "
              f"mutation is stale, which is not the same as caught.")
        return False
    if found > 1:
        # `ANCHOR GONE`'s twin, and it was missing (CHG-20260828-01). The write below is
        # `replace(..., 1)`, so an anchor appearing more than once reverts **whichever comes
        # first** — which need not be the guarantee `says` names. The run then reports about a
        # different line, and CAUGHT is the dangerous reading: it looks exactly like coverage.
        #
        # This is not hypothetical. Three shipped mutations were ambiguous when this check was
        # added, and one of them became ambiguous *because a later change added a second copy of
        # its anchor* — nothing said so at the time, and the group went on reporting clean.
        print(f"  AMBIGUOUS    {mutation.says}")
        print(f"               {mutation.path.name} contains this text {found} times, so the "
              f"mutation would revert whichever comes first rather than the one it names. Narrow "
              f"`before` with enough surrounding context to be unique.")
        return False
    io.open(mutation.path, "w", encoding="utf-8", newline="\n").write(
        original.replace(mutation.before, mutation.after, 1))
    try:
        proc = _pytest(mutation.tests)
    finally:
        io.open(mutation.path, "w", encoding="utf-8", newline="\n").write(original)

    caught = proc.returncode != 0
    summary = next((ln for ln in reversed(proc.stdout.splitlines())
                    if "passed" in ln or "failed" in ln or "error" in ln), "")
    print(f"  {'CAUGHT     ' if caught else 'NOT CAUGHT '}{mutation.says}")
    print(f"               {summary}")
    return caught


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run one group only (e.g. `importer`)")
    args = parser.parse_args()

    chosen = [m for m in MUTATIONS if not args.only or m.group == args.only]
    if not chosen:
        groups = sorted({m.group for m in MUTATIONS})
        raise SystemExit(f"no mutations in group {args.only!r}; have {groups}")

    print(f"{len(chosen)} mutation(s)\n")
    # Every file the chosen mutations touch, unmutated, once.
    baseline: Dict[str, bool] = {}
    for tests in sorted({m.tests for m in chosen}):
        green = _pytest(tests).returncode == 0
        baseline[tests] = green
        print(f"  {'baseline ok  ' if green else 'BASELINE RED '}{tests}")
    print()
    missed = [m for m in chosen if not run(m, baseline)]
    print()
    if missed:
        print(f"{len(missed)} of {len(chosen)} NOT caught — a test names a guarantee it does not "
              f"check:")
        for m in missed:
            print(f"  - {m.says}  ({m.tests})")
        return 1
    print(f"all {len(chosen)} caught. This says the named classes are pinned. It does not say the "
          f"suite is complete — see this file's docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
