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
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/ai_sdlc_runner"

#: The checkers themselves (CHG-20260828-02). A guard is code that can be wrong: `ledger_check`
#: walked changes and never acceptances, so an ACC naming no change read as a pass. Mutating the
#: guards is the only way to know they still refuse.
TOOLS = REPO / "tools"

#: The harness's own safety net lives next door, in `mutation_recovery.py`. Not tidiness: a
#: mutation's `before` string sits in THIS file, so any anchor into it appears twice and the
#: uniqueness guard correctly refuses it. A file cannot pin guarantees about itself by exact
#: text, and the recovery is the part that most needed pinning (CHG-20260828-18).
from mutation_recovery import (DEFAULT_IN_FLIGHT, IN_FLIGHT, MutationInFlight,  # noqa: E402
                               apply, recover, restore, restore_on_signal)


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
        '''                                      cwd=self.cwd,''',
        '''                                      cwd=None,''',
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
        # Re-anchored twice now: by CHG-20260828-02 after CHG-20260827-23 added `risk`/`can_write`,
        # and again here after CHG-20260827-21 moved the directory decision into `_cwd_for`. The
        # second time the staleness check added by CHG-20260828-02 caught it the same day, which is
        # the argument for that check rather than for remembering.
        '''                        timeout, retries, cwd=_cwd_for(workspace, from_config),
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

    # ── CHG-20260828-16: the codec is named, not inherited from whoever ran the process ────────
    #
    # These revert one call site each. A revert that only removed the keyword from `ledger_check`
    # would prove the guard test reads that one file; reverting in `cli` as well proves it reads
    # the tree rather than a remembered list of paths.

    Mutation(
        'codecs', "the id-collision guard decodes git with the caller's locale again",
        TOOLS / 'ledger_check.py',
        '''        done = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)''',
        '''        done = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(repo),
                              capture_output=True, text=True, timeout=60)''',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', "an agent's reply is decoded with the caller's locale again",
        SRC / 'cli.py',
        '                                      capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout,',
        '                                      capture_output=True, text=True, timeout=self.timeout,',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'the agent picks its own codec for the order it is sent',
        SRC / 'cli.py',
        '                                      env={**os.environ, "PYTHONIOENCODING": "utf-8"})',
        '                                      env=None)',
        'tests/test_cli.py'),

    Mutation(
        'codecs', 'a stray byte can kill the reader thread again, silently',
        SRC / 'worktree.py',
        '        return self._run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)',
        '        return self._run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'the recorder reads UTF-8 without asking the child to write it',
        TOOLS / 'session_record.py',
        '    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")',
        '    env = dict(os.environ, PYTHONUNBUFFERED="1")',
        'tests/test_recording.py'),

    Mutation(
        'codecs', 'the rule matches a keyword spelled `text` rather than a process launch',
        REPO / 'tests' / 'test_subprocess_codecs.py',
        '        if keywords & TEXT_SWITCHES and keywords & PROCESS_KEYWORDS:',
        '        if keywords & TEXT_SWITCHES:',
        'tests/test_subprocess_codecs.py'),

    # ── CHG-20260830-04: the probes underneath the sequence ────────────────────────────────────
    #
    # CHG-20260830-03 reserved this: every effect in `ship` delegates its probe here, so a probe
    # that answers wrongly defeats all of that from underneath. The failure mode is not "it breaks"
    # — it is "it answers", when it could not find out.

    Mutation(
        'probes', 'an unreachable remote is reported as "not pushed"',
        SRC / 'probes.py',
        '''    proc = _run(["git", "ls-remote", "--heads", remote, branch], cwd=repo)
    if proc.returncode != 0:''',
        '''    proc = _run(["git", "ls-remote", "--heads", remote, branch], cwd=repo)
    if False:''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'the push probe reads a local ref, which is stale in both directions',
        SRC / 'probes.py',
        '''    proc = _run(["git", "ls-remote", "--heads", remote, branch], cwd=repo)''',
        '''    proc = _run(["git", "rev-parse", "--verify", f"refs/remotes/{remote}/{branch}"], cwd=repo)''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'an unreachable forge is reported as an absent PR',
        SRC / 'probes.py',
        '''    proc = _run([*argv, "--head", branch], cwd=repo)
    if proc.returncode != 0:''',
        '''    proc = _run([*argv, "--head", branch], cwd=repo)
    if False:''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a CHG id is treated as a regular expression when searching commits',
        SRC / 'probes.py',
        '''    argv = ["git", "log", "--fixed-strings", f"--grep={needle}", "--format=%H"]''',
        '''    argv = ["git", "log", f"--grep={needle}", "--format=%H"]''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a failed git log answers "no commit" instead of refusing',
        SRC / 'probes.py',
        '''        raise ProbeError(f"git log failed in {repo}: {proc.stderr.strip()}")''',
        '''        return False''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a failed git status answers "clean" instead of refusing',
        SRC / 'probes.py',
        '''        raise ProbeError(f"git status failed in {repo}: {proc.stderr.strip()}")''',
        '''        return True''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a missing binary answers instead of saying it is not there',
        SRC / 'probes.py',
        '''        raise ProbeError(f"{argv[0]!r} is not available: {paths.plain_in(str(exc))}") from None''',
        '''        return subprocess.CompletedProcess(argv, 0, "", "")''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a probe that timed out answers instead of saying so',
        SRC / 'probes.py',
        '''        raise ProbeError(f"{' '.join(argv)} timed out after {timeout}s: {exc}") from None''',
        '''        return subprocess.CompletedProcess(argv, 0, "", "")''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a half-written CHG with no Branch reads as intent recorded',
        SRC / 'probes.py',
        '''    return bool(re.search(r"^\\s*-?\\s*Branch\\s*[:：]", text, re.MULTILINE))''',
        '''    return True''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'an unticked task reads as ticked',
        SRC / 'probes.py',
        '''        if task in line and re.search(r"\\[\\s*[xX]\\s*\\]|\\*\\*\\[\\s*[xX]\\s*\\]\\*\\*", line):''',
        '''        if task in line:''',
        'tests/test_probes.py'),

    # ── CHG-20260830-03: the sequence that carries a change out ────────────────────────────────
    #
    # `ship.py` is the only module whose effects reach outside this machine, and the only one whose
    # steps are irreversible in the ordinary case. Measured with the harness against the file that
    # drives the sequence end to end.

    Mutation(
        'ship', 'a git command that failed is treated as having worked',
        SRC / 'ship.py',
        '    if proc.returncode != 0:\n        raise ShipError(f"git',
        '    if False:\n        raise ShipError(f"git',
        'tests/test_ship_refuses.py'),

    Mutation(
        # A real reorder, not a rename. The first version changed `name="record-intent"` to
        # `name="zzz-record-intent"` and reported CAUGHT — because the test compares effect names
        # literally, not because anything moved. Renaming an entry does not reorder a list, so the
        # guarantee this row names had no mutation at all until the review panel said so
        # (CHG-20260830-05).
        'ship', 'the intent is recorded after the effects it describes, not before',
        SRC / 'ship.py',
        '''    return [
        effects.Effect(
            name="record-intent",
            probe=lambda: probes.chg_recorded(repo, chg_id),
            apply=write_chg,
            postcondition=f"docs/changes/{chg_id}.md exists and names its Branch",
        ),
        effects.Effect(
            name="branch",
            probe=lambda: probes.branch_exists_locally(repo, branch),
            apply=lambda: _git(repo, "checkout", "-b", branch),
            postcondition=f"refs/heads/{branch} exists",
        ),''',
        '''    return [
        effects.Effect(
            name="branch",
            probe=lambda: probes.branch_exists_locally(repo, branch),
            apply=lambda: _git(repo, "checkout", "-b", branch),
            postcondition=f"refs/heads/{branch} exists",
        ),
        effects.Effect(
            name="record-intent",
            probe=lambda: probes.chg_recorded(repo, chg_id),
            apply=write_chg,
            postcondition=f"docs/changes/{chg_id}.md exists and names its Branch",
        ),''',
        'tests/test_kill_resume.py'),

    Mutation(
        'ship', 'a commit over a dirty tree counts as done, so a resume pushes half of it',
        SRC / 'ship.py',
        '            probe=lambda: (probes.commit_exists_for(repo, chg_id)\n                           and probes.working_tree_clean(repo)),',
        '            probe=lambda: probes.commit_exists_for(repo, chg_id),',
        'tests/test_ship_refuses.py'),

    Mutation(
        'ship', 'the PR step stops asking whether a PR is already open',
        SRC / 'ship.py',
        '            probe=lambda: probes.pr_open_for(repo, branch, gh_list),',
        '            probe=lambda: False,',
        'tests/test_kill_resume.py'),

    Mutation(
        'ship', 'the push step stops asking whether the branch is already on the remote',
        SRC / 'ship.py',
        '            probe=lambda: probes.branch_on_remote(repo, branch, remote),',
        '            probe=lambda: False,',
        'tests/test_kill_resume.py'),

    Mutation(
        'ship', 'the runner invents the content of a governance record nobody supplied',
        SRC / 'ship.py',
        '''            apply=tick or _refuse("tick", f"task {task!r} of {chg_id}"),''',
        '''            apply=tick or (lambda: None),''',
        'tests/test_ship_refuses.py'),

    Mutation(
        'ship', 'a failed PR creation is reported as success',
        SRC / 'ship.py',
        '''        raise ShipError(f"could not open a PR for {branch}: {proc.stderr.strip()}")''',
        '''        pass''',
        'tests/test_ship_refuses.py'),

    # ── CHG-20260830-02: where a model is, and what it must not carry ──────────────────────────
    #
    # `reach` decides whether a work order leaves this network, and `validate` decides whether a key
    # can end up in a file. Measured with the harness, pointed at the existing tests.

    Mutation(
        'reach', 'reach becomes something the operator declares rather than something computed',
        SRC / 'models.py',
        '    if transport == CLI:\n        return LOCAL',
        '    if transport == CLI:\n        return EXTERNAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a name nobody can resolve is called internal, the generous way to be wrong',
        SRC / 'models.py',
        '        if "." not in host or host.endswith(LOCAL_SUFFIXES):\n            return INTERNAL',
        '        return INTERNAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a private address is called external, so an internal model looks like a leak',
        SRC / 'models.py',
        '    if address.is_private or address.is_link_local:\n        return INTERNAL',
        '    if False:\n        return INTERNAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'loopback stops being local',
        SRC / 'models.py',
        '    if address.is_loopback:\n        return LOCAL',
        '    if False:\n        return LOCAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'an api model with no endpoint gets a reach guessed for it',
        SRC / 'models.py',
        '''        raise ModelError("an api model needs an endpoint before its reach can be known")''',
        '''        return EXTERNAL''',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a secret in the query string is accepted into the registry',
        SRC / 'models.py',
        '    leaked = _secret_in_url(model.endpoint)\n    if leaked:',
        '    leaked = _secret_in_url(model.endpoint)\n    if False:',
        'tests/test_models.py'),

    Mutation(
        'reach', 'the secret scan reads the value instead of the key, so ?api_key= passes',
        SRC / 'models.py',
        '        name = pair.split("=", 1)[0].strip().lower()',
        '        name = pair.split("=", 1)[-1].strip().lower()',
        'tests/test_models.py'),

    Mutation(
        'reach', 'key_env takes the key itself, so it reaches a file and a git history',
        SRC / 'models.py',
        '    if model.key_env and not _ENV_NAME.match(model.key_env):',
        '    if False:',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a public endpoint with no key named is registered anyway',
        SRC / 'models.py',
        '    if model.reach == EXTERNAL and not model.key_env:',
        '    if False:',
        'tests/test_models.py'),

    Mutation(
        'reach', 'an endpoint scheme this runner does not speak is accepted',
        SRC / 'models.py',
        '''    if scheme not in ("http", "https"):''',
        '''    if False:''',
        'tests/test_models.py'),

    Mutation(
        'reach', 'an api model may carry a command it cannot use',
        SRC / 'models.py',
        '''        raise ModelError(f"api model {model.id!r} carries a command it cannot use")''',
        '''        pass''',
        'tests/test_models.py'),

    Mutation(
        'reach', 'two models may share one id',
        SRC / 'models.py',
        '''                raise ModelError(f"two models are called {model.id!r}")''',
        '''                pass''',
        'tests/test_models.py'),

    # ── CHG-20260830-01: the console's network boundary ────────────────────────────────────────
    #
    # `_guard` is the only thing between a local HTTP server holding an operator token and whatever
    # else is running on the machine. Measured the way CHG-20260828-24's acceptance said it should
    # have been: pointed at the existing test file, and the ones that come back NOT CAUGHT are the
    # holes — no second instrument.

    Mutation(
        'console', 'a non-loopback Host reaches the router, so DNS rebinding works again',
        SRC / 'server.py',
        '            if not _loopback_host(self.headers.get("Host")):',
        '            if False:',
        'tests/test_server.py'),

    Mutation(
        'console', 'the shell is served to any Host at all',
        SRC / 'server.py',
        '                return _loopback_host(self.headers.get("Host")) or self._refuse_host()',
        '                return True',
        'tests/test_server.py'),

    Mutation(
        'console', 'a cross-origin request is answered',
        SRC / 'server.py',
        '            if origin and not _loopback_origin(origin):',
        '            if False:',
        'tests/test_server.py'),

    Mutation(
        'console', 'no operator token is needed',
        SRC / 'server.py',
        '            if not operator.accepts(presented):',
        '            if False:',
        'tests/test_server.py'),

    Mutation(
        'console', 'the token is compared with `==`, leaking its prefix by timing',
        SRC / 'server.py',
        '        return bool(presented) and secrets.compare_digest(presented, self.token)',
        '        return bool(presented) and presented == self.token',
        'tests/test_server.py'),

    Mutation(
        'console', 'every route takes the token from the query string, not only the stream',
        SRC / 'server.py',
        '            if presented is None and urlsplit(self.path).path == "/run/events":',
        '            if presented is None:',
        'tests/test_server.py'),

    Mutation(
        'console', 'a Host with a port stops matching, so the console refuses itself',
        SRC / 'server.py',
        '        host = host.rsplit(":", 1)[0]',
        '        host = host',
        'tests/test_server.py'),

    Mutation(
        'console', 'a body that is not JSON comes back as a traceback',
        SRC / 'server.py',
        '            except ValueError as exc:\n                raise ServerError(f"the request body is not JSON: {exc}")',
        '            except TypeError as exc:\n                raise ServerError(f"the request body is not JSON: {exc}")',
        'tests/test_server.py'),

    # ── CHG-20260828-24: the model store ───────────────────────────────────────────────────────
    #
    # Measured before writing: nine of ten were already pinned. The tenth was not, and writing its
    # test found the guarantee was not delivered at all — which is why this group also mutates
    # `paths.py` below.
    #
    # This comment used to say "TEN OF TEN were already pinned. No hole was found." That was the
    # figure a discarded probe reported; the harness said nine and was right, and CHG-20260828-24's
    # own acceptance records the correction. The records were updated and this line was not, so the
    # permanent registry stated the opposite of the change it heads — the review panel's conformance
    # seat vetoed on it (CHG-20260830-05).

    Mutation(
        'store', 'a file that is not a database comes back as a raw traceback',
        SRC / 'store.py',
        '''    except sqlite3.DatabaseError as exc:
        # A file that is not a database''',
        '''    except NotImplementedError as exc:
        # A file that is not a database''',
        'tests/test_store.py'),

    Mutation(
        'store', 'the extended-length prefix reaches the operator in the message',
        SRC / 'store.py',
        'f"{file} could not be opened as a store: {paths.plain_in(str(exc))}. If it is a real "',
        'f"{file} could not be opened as a store: {exc}. If it is a real "',
        'tests/test_store.py'),

    Mutation(
        # The defect this group found. `plain` strips a LEADING prefix; an OS error quotes a
        # path mid-sentence, so the guard was a no-op wearing the name of the thing it did not do.
        'store', 'the prefix is stripped only from the start again, so a message keeps it',
        SRC / 'paths.py',
        # A raw triple-quote. The escaped one-line form this shipped as put sixteen consecutive
        # backslashes on a 214-character line, which nobody can check against source by eye — an
        # unverifiable anchor in the file whose meta-test exists to keep anchors honest. The `r`
        # prefix is new here; the plain `'''` multi-line form is not (`store.py`'s anchor, 18 lines
        # above). CHG-20260830-06 cited it as precedent for the raw form, which it is not.
        r'''    return (text
            .replace(_DOUBLED_UNC_PREFIX, "\\\\\\\\")
            .replace(_DOUBLED_PREFIX, "")
            .replace(UNC_PREFIX, "\\\\")
            .replace(PREFIX, ""))''',
        '    return plain(text)',
        'tests/test_paths.py'),

    Mutation(
        # The defect the REVIEW PANEL found. Only the undoubled spelling was handled — and the
        # undoubled spelling is the one no real error carries, because `str(OSError)` embeds
        # `repr(filename)` and doubles every backslash (CHG-20260830-05).
        'store', 'only the spelling a real OS error never uses is stripped',
        SRC / 'paths.py',
        r'''            .replace(_DOUBLED_UNC_PREFIX, "\\\\\\\\")
            .replace(_DOUBLED_PREFIX, "")
''',
        '',
        'tests/test_paths.py'),

    Mutation(
        'store', r'a UNC path is left as UNC\server\share, which is not a path anybody can use',
        SRC / 'paths.py',
        r'''            .replace(UNC_PREFIX, "\\\\")
            .replace(PREFIX, ""))''',
        r'''            .replace(PREFIX, "")
            .replace(UNC_PREFIX, "\\\\"))''',
        'tests/test_paths.py'),

    Mutation(
        'store', 'a store from a newer schema is opened and written anyway',
        SRC / 'store.py',
        '    if found > SCHEMA_VERSION:',
        '    if False:',
        'tests/test_store.py'),

    Mutation(
        'store', 'a table already there with the wrong columns is blessed as current',
        SRC / 'store.py',
        '        if found != columns:',
        '        if False:',
        'tests/test_store.py'),

    Mutation(
        'store', 'foreign keys stay off, so a delete can orphan an assignment',
        SRC / 'store.py',
        'db.execute("PRAGMA foreign_keys = ON")',
        'db.execute("PRAGMA foreign_keys = OFF")',
        'tests/test_store.py'),

    Mutation(
        'store', 'a node that is not in this flow can be assigned models',
        SRC / 'store.py',
        '''    if node is None:
        raise StoreError(f"no node {node_id!r} in this flow")''',
        '''    if False:
        raise StoreError(f"no node {node_id!r} in this flow")''',
        'tests/test_store.py'),

    Mutation(
        'store', 'a node whose mode does nothing with models is configured anyway',
        SRC / 'store.py',
        '    if node.mode not in MODES_THAT_USE_MODELS:',
        '    if False:',
        'tests/test_store.py'),

    Mutation(
        'store', 'an unknown seat is assigned a model',
        SRC / 'store.py',
        '    if seat not in known:',
        '    if False:',
        'tests/test_store.py'),

    Mutation(
        'store', "the standing store setting overrides this change's plan",
        SRC / 'store.py',
        '        combined = {**from_store, **from_plan}          # plan last, so the plan wins',
        '        combined = {**from_plan, **from_store}          # plan last, so the plan wins',
        'tests/test_store.py'),

    Mutation(
        'store', 'nobody can tell which source put an assignment there',
        SRC / 'store.py',
        '            source[f"{half}.{key}"] = FROM_PLAN if key in from_plan else FROM_STORE',
        '            source[f"{half}.{key}"] = FROM_STORE',
        'tests/test_store.py'),

    # ── CHG-20260828-23: the closed-schema renderer, pinned deliberately ───────────────────────
    #
    # `workorder.py` had no mutation and no test file of its own. Measured before writing either:
    # seven of these nine were already caught by tests written about other things. The last two
    # were not — and the source marks one of them `# pragma: no cover`, which is the code admitting
    # nothing exercised it.

    Mutation(
        'workorder', 'a harness-specific field rides in through the caller',
        SRC / 'workorder.py',
        '    if extra:', '    if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'a partial node spec is filled in rather than refused',
        SRC / 'workorder.py',
        '    if missing:', '    if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'whitespace stops counting as blank',
        SRC / 'workorder.py',
        '        return not value.strip()', '        return not value',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'a list holding only blanks passes as content',
        SRC / 'workorder.py',
        '        return not value or all(_blank(item) for item in value)',
        '        return not value',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'a blank field is accepted again, as long as the key exists',
        SRC / 'workorder.py',
        '''    if problem:
        raise WorkOrderError(problem)''',
        '''    if False:
        raise WorkOrderError(problem)''',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'an unknown seat is accepted',
        SRC / 'workorder.py',
        '        if chair is None:', '        if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'the permanent halts are emptied out of the order',
        SRC / 'workorder.py',
        '        "permanent_halts": list(policy.PERMANENT_HALTS),',
        '        "permanent_halts": [],',
        'tests/test_workorder.py'),

    # The two nothing pinned.
    Mutation(
        'workorder', 'the rendered order stops being checked against the closed schema',
        SRC / 'workorder.py',
        '    if tuple(sorted(order)) != tuple(sorted(WORK_ORDER_FIELDS)):',
        '    if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'the order reaches the agent in whatever key order it happened to have',
        SRC / 'workorder.py',
        'sort_keys=True', 'sort_keys=False',
        'tests/test_workorder.py'),

    # ── CHG-20260828-22: the whole-change loop is bounded ──────────────────────────────────────

    Mutation(
        'bounds', 'a rejected change goes round for ever again, until the step cap',
        SRC / 'engine.py',
        '''    if node.id == "change_retry":''',
        '''    if False:''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'the panel and acceptance get a budget each, so neither is ever spent',
        SRC / 'engine.py',
        '''_WHOLE_CHANGE_REJECTED = ("review_failed", "acceptance_failed")''',
        '''_WHOLE_CHANGE_REJECTED = ("review_failed",)''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'the bound fires on the first rejection instead of the second',
        SRC / 'engine.py',
        '''    return "again" if rejections > 1 else "first"''',
        '''    return "again" if rejections > 0 else "first"''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'a seat panel counts once per seat again, so three seats halt a first rejection',
        SRC / 'engine.py',
        '''    rejections = sum(1 for node_id in report.visited if node_id in _WHOLE_CHANGE_REJECTED)''',
        '''    rejections = sum(1 for ask in report.asks if ask.node_id in ("lead_review", "qa_accept")
                     and isinstance(ask.result, Mapping)
                     and str(ask.result.get("verdict") or "") == "fail")''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'acceptance stops routing through the bound, leaving its loop unbounded',
        SRC / 'graph.py',
        '''    Node("acceptance_failed", STEP, "back into the module loop", next="change_retry", mode=RUNNER),''',
        '''    Node("acceptance_failed", STEP, "back into the module loop", next="next_module", mode=RUNNER),''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'the halt is not permanent, so a class or a confirmation could pass it',
        SRC / 'graph.py',
        '''    Node("halt_change_rejected", TERMINAL, "the whole change was rejected twice", mode=RUNNER,
         permanent=True,''',
        '''    Node("halt_change_rejected", TERMINAL, "the whole change was rejected twice", mode=RUNNER,
         permanent=False,''',
        'tests/test_change_bound.py'),

    # ── CHG-20260828-21: an emergency run is chased ────────────────────────────────────────────
    #
    # The failure that matters here is a FALSE CLOSE — a run marked reviewed by something that is
    # not a person, or by reviewing something that never needed it. Those three refusals get one
    # mutation each; the queue merely being wrong is the milder half.

    Mutation(
        'emergency', 'a review signed by nobody closes the obligation',
        SRC / 'conversations.py',
        '''    if not who:
        raise ConversationError(
            "a review must name who did it.''',
        '''    if False:
        raise ConversationError(
            "a review must name who did it.''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'the queue empties by reviewing any run at all',
        SRC / 'conversations.py',
        '    run = runs.get(cid)',
        '    run = runs.get(cid) or {"conversation_id": cid, "project_id": "", "reviewed_by": None}',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'a second review is written over the first, losing who looked',
        SRC / 'conversations.py',
        '''    if run["reviewed_by"]:''',
        '''    if False:''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'the word emergency anywhere queues a run again',
        SRC / 'conversations.py',
        '''    return "'emergency'" in str(turn.get("change_class") or "")''',
        '''    return "emergency" in str(turn)''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'a reviewed run stays in the queue, so the queue never empties',
        SRC / 'conversations.py',
        '''    return [run for run in emergency_runs(back, pid) if not run["reviewed_by"]]''',
        '''    return list(emergency_runs(back, pid))''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', "a person's review is filed under the runner in the export",
        SRC / 'conversations.py',
        '''    REVIEW: ("operator", "reviewed"),''',
        '''    NOTE: ("runner", "noted"),''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'nothing chases the queue after a run again',
        SRC / 'cli.py',
        '''    _chase_emergencies(args)
    return 0''',
        '''    return 0''',
        'tests/test_emergency_queue.py'),

    # ── CHG-20260828-20: a record's evidence has to be findable ────────────────────────────────

    Mutation(
        'closure', 'a record can name a test that does not exist again',
        TOOLS / 'ledger_check.py',
        '                  if name not in known and not _excused(text, name, ledger_ids)]',
        '                  if False]',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'the remedy the ghost refusal offers stops being honoured',
        TOOLS / 'ledger_check.py',
        '            if BLANK_LINE not in found.group(0) and found.group(1) in ledger_ids:',
        '            if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'the evidence check is written but never run by the ledger',
        TOOLS / 'ledger_check.py',
        '    problems.extend(check_named_tests_exist(repo))',
        '    pass',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'naming a test module stops counting, so every file reference is a ghost',
        TOOLS / 'ledger_check.py',
        '        names.add(path.stem)',
        '        pass',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'the rule reaches back over history it cannot change',
        TOOLS / 'ledger_check.py',
        '        if stamp < TESTS_MUST_EXIST_FROM:',
        '        if False:',
        'tests/test_ledger_check.py'),

    # ── CHG-20260828-19: the file half of the same question ───────────────────────────

    Mutation(
        # The helper the file survey EXEMPTS. Most file I/O here goes through it, so if its default
        # stopped naming a codec the survey would go on quietly exempting it — the exemption is
        # load-bearing and had nothing checking it until this mutation had nowhere else to land.
        'codecs', 'the file helper the survey trusts stops defaulting to utf-8',
        SRC / 'paths.py',
        '''def read_text(path: str | Path, encoding: str = "utf-8") -> str:''',
        '''def read_text(path: str | Path, encoding: str = None) -> str:''',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'going through `paths` stops counting as naming a codec',
        REPO / 'tests' / 'test_subprocess_codecs.py',
        '''CODEC_BY_DEFAULT = "paths"''',
        '''CODEC_BY_DEFAULT = "not-paths"''',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'the file survey stops looking at bare open() as well',
        REPO / 'tests' / 'test_subprocess_codecs.py',
        '        if name == "open" and receiver not in (None, "io"):',
        '        if name == "open":',
        'tests/test_subprocess_codecs.py'),

    # ── CHG-20260828-18: a killed run does not leave the tree mutated ──────────────────
    #
    # Every one of these anchors into `mutation_recovery.py` rather than into this file. A
    # mutation's `before` string lives HERE, so an anchor into this file appears twice and the
    # uniqueness guard refuses it — which is why the recovery is next door.

    Mutation(
        # Was "two runs in one worktree overwrite each other's way back" — which this pins only
        # half of, and the half it does not pin was broken. See CHG-20260830-06 below.
        'stranded', 'a record already on disk is overwritten instead of refused',
        TOOLS / 'mutation_recovery.py',
        r'''        with io.open(IN_FLIGHT, "x", encoding="utf-8", newline="\n") as handle:''',
        r'''        with io.open(IN_FLIGHT, "w", encoding="utf-8", newline="\n") as handle:''',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'a file a killed run left mutated stays mutated',
        TOOLS / 'mutation_recovery.py',
        '    if not IN_FLIGHT.exists():',
        '    if True:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the mutation is applied before it is recorded, so the window reopens',
        TOOLS / 'mutation_recovery.py',
        """    begin(path, original, mutated)
    write(path, mutated)""",
        """    write(path, mutated)
    begin(path, original, mutated)""",
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'recovery overwrites a file somebody has edited since the run died',
        TOOLS / 'mutation_recovery.py',
        '    if now == mutated:',
        '    if now != original:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the in-flight record outlives the run that wrote it',
        TOOLS / 'mutation_recovery.py',
        """    write(path, original)
    end()""",
        """    write(path, original)""",
        'tests/test_mutation_recovery.py'),

    # ── CHG-20260830-06: exclusive creation was not the lock ───────────────────────────────────
    #
    # The entry above says two runs cannot overwrite each other's way back, and for one round that
    # was false while its mutation came back CAUGHT: `main()` calls `recover()` before its first
    # `apply()`, so the second run cleared the first one's record on the way in and never reached
    # the exclusive create. The test carrying the claim called `begin` twice in one process — the
    # path no real second run takes. Three seats of the CHG-20260830-05 panel found it, one by veto.

    Mutation(
        'stranded', 'a second run recovers over a live run and reports on unmutated source',
        TOOLS / 'mutation_recovery.py',
        '    if owner != os.getpid() and _alive(owner):',
        '    if False:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'a finishing run deletes a record another run is relying on',
        TOOLS / 'mutation_recovery.py',
        '    if owner is not None and owner != os.getpid():',
        '    if False:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'every process reads as dead, so the owner check never refuses anything',
        TOOLS / 'mutation_recovery.py',
        """    if pid is None:
        return False""",
        """    if pid is None:
        return False
    return False""",
        'tests/test_mutation_recovery.py'),

    # ── CHG-20260830-07: the liveness probe answered wrongly three ways ────────────────────────
    #
    # The owner check above is only as good as `_alive`, and nothing tested whether `_alive` was
    # right — ACC-20260830-06 row 16 checked only that it does not *kill* what it asks about. Three
    # seats of the round-3 panel found three separate wrong answers in it.

    Mutation(
        'stranded', 'a live process this run may not open reads as dead, so recovery overwrites it',
        TOOLS / 'mutation_recovery.py',
        '        return ctypes.get_last_error() == ERROR_ACCESS_DENIED',
        '        return False',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the wait is asked without SYNCHRONIZE, so every live process reads as dead',
        TOOLS / 'mutation_recovery.py',
        '    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)',
        '    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)',
        'tests/test_mutation_recovery.py'),

    # The two entries above mutate lines inside `_alive_nt`, so on POSIX they are unreachable:
    # this group is **10 of 12** there. Counted, not carried — CHG-20260830-08 wrote 9/11 here and
    # 11/12 in its acceptance while the group held twelve entries, and CHG-20260830-09's claims
    # table corrected both to 10/12 without touching this line (CHG-20260831-01, conformance).
    # Nothing reports the difference: CI never runs this file. The entry below is their POSIX twin
    # and is the one that runs everywhere.

    Mutation(
        'stranded', 'a process this run may not signal reads as dead on POSIX too',
        TOOLS / 'mutation_recovery.py',
        """    except PermissionError:
        return True""",
        """    except PermissionError:
        return False""",
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the record stops saying who owns it, so no later run can tell',
        TOOLS / 'mutation_recovery.py',
        '                         "owner": os.getpid()}, ensure_ascii=False)',
        '                         }, ensure_ascii=False)',
        'tests/test_mutation_recovery.py'),

    # ── CHG-20260828-17: the two records are read, not just counted ────────────────────────────

    Mutation(
        'closure', 'a change goes on waiting for a decision its acceptance already made',
        TOOLS / 'ledger_check.py',
        '        if waiting:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'a change accepted and later superseded is called a contradiction',
        TOOLS / 'ledger_check.py',
        '    "proposed", "draft", "under review", "in progress", "wip", "pending",',
        '    "proposed", "draft", "under review", "in progress", "wip", "pending", "superseded",',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'a verdict nobody wrote down is treated as a pass',
        TOOLS / 'ledger_check.py',
        '        if not passed and not refused:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'a verdict that reads both ways is settled by whichever list is checked first',
        TOOLS / 'ledger_check.py',
        '        if passed and refused:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'voice', "a person's pre-authorisation is filed under the runner again",
        SRC / 'conversations.py',
        '    if kind == RELAXATION and turn.get("by"):',
        '    if False:',
        'tests/test_export_voice.py'),

    Mutation(
        'voice', 'the declaration stops recording who made it',
        SRC / 'cli.py',
        '            by=str(declared_class["authorised_by"]))',
        '            by=None)',
        'tests/test_export_voice.py'),

    Mutation(
        'modules', 'each module builds from HEAD again, so N+1 cannot see N',
        SRC / 'worktree.py',
        '        done = self._run(["git", "worktree", "add", "--detach", str(where), self.tip],',
        '        done = self._run(["git", "worktree", "add", "--detach", str(where), "HEAD"],',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'the finished module is no longer committed when the next one starts',
        SRC / 'worktree.py',
        '        if self._live is not None and self._live != key:\n            self.finish(self._live)',
        '        if False:\n            self.finish(self._live)',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'an ignored build artifact is committed after all',
        SRC / 'worktree.py',
        '        staged = self._git(["add", "-A"], where)',
        '        staged = self._git(["add", "-A", "--force"], where)',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', "the build's artifacts stop reaching the working tree",
        SRC / 'worktree.py',
        '        for key, where in sorted(self._trees.items()):\n            for rel in self.artifacts(key):',
        '        for key, where in []:\n            for rel in self.artifacts(key):',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', "the operator's branch is moved even when that would discard their work",
        SRC / 'worktree.py',
        '        done = self._git(["merge", "--ff-only", self.tip], top)',
        '        done = self._git(["merge", self.tip], top)',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'a module that halted is committed as though it had passed',
        SRC / 'cli.py',
        '        if live and int(str(live).rsplit("-", 1)[-1] or 0) <= recorded:',
        '        if live:',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'the run stops saying that uncommitted edits will not be seen',
        SRC / 'cli.py',
        '        dirty = trees.uncommitted()',
        '        dirty = []',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'a new tree starts empty, so a filesystem-reading agent rebuilds the same module',
        SRC / 'worktree.py',
        '        self._carry_forward_into(str(where))',
        '        pass',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', "an ignored directory is skipped, dropping the whole of a build's output",
        SRC / 'worktree.py',
        '            if source.is_dir():',
        '            if False:',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'guards', 'two changes may wear one number again',
        TOOLS / 'ledger_check.py',
        '        if mine and landed and mine != landed:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'guards', 'editing a record starts counting as a collision',
        TOOLS / 'ledger_check.py',
        '        mine = _title(path.read_text(encoding="utf-8"))',
        '        mine = path.read_text(encoding="utf-8")',
        'tests/test_ledger_check.py'),

    Mutation(
        'guards', 'an unresolvable ref passes quietly instead of saying nothing was checked',
        TOOLS / 'ledger_check.py',
        # Removes the message outright. The first draft mutated only the FIRST line of the
        # two-line string, and `was NOT checked` lives on the second — so the mutated code still
        # printed what the test asserts, and the run reported NOT CAUGHT for a mutation that had
        # not broken anything. A mutation that does not make the guarantee false proves nothing
        # either way.
        '''        print("ledger check: no main to compare against, so a change taking an id another change "
              "already has was NOT checked. Fetch the default branch to get that check.")''',
        '''        pass''',
        'tests/test_ledger_check.py'),

    Mutation(
        'classes', 'a change-level gate relaxes when only some parts were pre-authorised',
        SRC / 'policy.py',
        '    if not seen or any(n == DEFAULT_CLASS for n in seen):',
        '    if not seen:',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', 'an emergency part is reported as a standard one',
        SRC / 'policy.py',
        '    return "emergency" if "emergency" in seen else "standard"',
        '    return "standard"',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', "a node stops reading its own workstream's class",
        SRC / 'engine.py',
        '    if mine is not None:\n        return policy.class_in_force(per.get(mine), today)',
        '    if False:\n        return policy.class_in_force(per.get(mine), today)',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', 'one sentence pre-authorises every part of a split programme again',
        SRC / 'cli.py',
        '    if run_level and len(workstreams or {}) > 1:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', 'a class may name a workstream the plan never declared',
        SRC / 'cli.py',
        '            if name not in (workstreams or {}):',
        '            if False:',
        'tests/test_change_classes.py'),

    Mutation(
        'record', 'a run records that it stopped and not why',
        SRC / 'engine.py',
        '        conversation.close(report.state, at_node=report.halted_at, why=report.halt_reason,\n                           risk=report.risk_settled, change_class=report.change_class or None)',
        '        conversation.close(report.state)',
        'tests/test_closing_record.py'),

    Mutation(
        'record', 'the closing summary goes back to the bare state word',
        SRC / 'conversations.py',
        '        where = f" at {turn[\'at_node\']}" if turn.get("at_node") else ""',
        '        where = ""',
        'tests/test_closing_record.py'),

    Mutation(
        'record', "a body may rewrite the turn's own envelope again",
        SRC / 'conversations.py',
        '        collided = [k for k in self.ENVELOPE if k in self.body]',
        '        collided = []',
        'tests/test_closing_record.py'),

    Mutation(
        'planning', 'a formatting difference stops a run again',
        SRC / 'engine.py',
        '        distinct = sorted({_same_signature(s) for s in by_workstream.values()})',
        '        distinct = sorted(set(by_workstream.values()))',
        'tests/test_sub_planning.py'),

    Mutation(
        'planning', 'all whitespace is stripped, so two different declarations read as one',
        SRC / 'engine.py',
        '    return re.sub(r"\\s*([^\\w\\s])\\s*", r"\x01", signature.strip())',
        '    return re.sub(r"\\s+", "", signature)',
        'tests/test_sub_planning.py'),

    Mutation(
        'modules', 'a module is recorded on the lap the engineer said there was nothing',
        SRC / 'graph.py',
        '         branches={"yes": "record_module", "no": "next_module"},',
        '         branches={"yes": "record_module", "no": "record_module"},',
        'tests/test_module_built.py'),

    Mutation(
        'modules', 'silence is read as a build',
        SRC / 'engine.py',
        '        return "yes" if str(ask.result.get("module") or "") else "no"',
        '        return "yes"',
        'tests/test_module_built.py'),

    Mutation(
        'modules', 'the guard can be answered instead of read',
        SRC / 'engine.py',
        '    if node.id == "module_built":',
        '    if node.id == "module_built" and value is None:',
        'tests/test_module_built.py'),

    Mutation(
        'modules', 'the module cycle escapes the loop and puts review nodes in a worktree',
        SRC / 'graph.py',
        'def module_cycle(start: str = "engineer_build", end: str = "next_module") -> List[str]:',
        'def module_cycle(start: str = "engineer_build", end: str = "record_module") -> List[str]:',
        'tests/test_module_built.py'),

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
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
        # `PYTHONIOENCODING`, not `PYTHONUTF8` (CHG-20260828-16). Both make pytest write UTF-8 down
        # the pipe, which is all this needed — CHG-20260823-47 reached for the bigger switch and it
        # worked. But `PYTHONUTF8=1` also makes `locale.getpreferredencoding()` return UTF-8 *inside
        # the suite*, and that is what `subprocess`'s text mode reads. So every mutation ran in a
        # locale no ordinary run of this suite has, and a guarantee about decoding could not be
        # pinned here: reverting the fix left the tests green. `PYTHONIOENCODING` fixes the pipe and
        # leaves the locale alone, which is the part that had to stay real.
        # `MUTATION_RUN` is how the harness announces itself to
        # `test_this_repository_has_no_mutation_in_flight`, which would otherwise fail on the record
        # this run legitimately holds. It was keyed on the record's owner being *alive* instead, and
        # that coupled the guard to `_alive`: a mutation that broke `_alive` made the guard fail, so
        # the run stopped there under `-x` and the tests written for `_alive` never ran — while a
        # genuinely stranded tree whose dead owner's pid had been reused read as alive and went
        # **green**. Announcing beats inferring (CHG-20260830-08, defect and risk seats).
        env={**os.environ, "PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8",
             "MUTATION_RUN": str(os.getpid())})


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
    mutated = original.replace(mutation.before, mutation.after, 1)
    apply(mutation.path, original, mutated)
    try:
        proc = _pytest(mutation.tests)
    finally:
        restore(mutation.path, original)

    caught = proc.returncode != 0
    summary = next((ln for ln in reversed(proc.stdout.splitlines())
                    if "passed" in ln or "failed" in ln or "error" in ln), "")
    print(f"  {'CAUGHT     ' if caught else 'NOT CAUGHT '}{mutation.says}")
    print(f"               {summary}")
    return caught


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run one group only (e.g. `importer`)")
    parser.add_argument("--recover", action="store_true",
                        help="put back a file a killed run left mutated, then stop")
    args = parser.parse_args()

    # Before anything else. A tree left mutated by a previous run would make every baseline below
    # a measurement of the wrong code.
    restore_on_signal()
    if os.environ.get("MUTATION_IN_FLIGHT"):
        # A mutation run must write its record where the guard looks for it, and this moves it. The
        # override exists for one caller — the child pytest that drives
        # `test_this_repository_has_no_mutation_in_flight` — and a run that honoured it would mutate
        # source while `tools/.mutation-in-flight.json` stayed absent: `--recover` from an ordinary
        # shell then says "nothing in flight; the tree is as it should be" and exits 0 over a
        # mutated file, and the record is the lock, so a second run takes it uncontended.
        #
        # CHG-20260830-09 claimed a leaked value "points the harness at a file it will not find,
        # which fails loudly". It does not: `begin()` *creates* the record, so every writable value
        # is the silent case. Measured, and made true here rather than restated
        # (CHG-20260831-01, risk seat).
        raise SystemExit(
            f"MUTATION_IN_FLIGHT is set ({os.environ['MUTATION_IN_FLIGHT']}), which moves the "
            f"in-flight record there instead of {DEFAULT_IN_FLIGHT}. A mutation run must write it "
            f"where the stranded-tree guard reads it. Unset the variable and run again.")

    said = recover()
    if args.recover:
        # Before the refusal below, not after it — though the ordering changes nothing, and the
        # comment that shipped here said otherwise. It claimed the old order meant `--recover`
        # "exited 1 without ever reaching this branch, so the documented way out could not be
        # taken". Measured: both orderings produce byte-identical output and both exit 1, because
        # the refusal comes from `recover()` itself. The defect the reorder claimed to fix did not
        # exist; this order is simply the one that reads correctly (CHG-20260831-01, conformance).
        if said is None:
            print("nothing in flight; the tree is as it should be")
        return 1 if said and said.startswith("REFUSING") else 0
    if said and said.startswith("REFUSING"):
        # Refuse here rather than at the first `apply()`. That is minutes of baselines away, and
        # `apply` sits outside `run`'s try/finally, so the exception left main() as a traceback with
        # no summary line at all (CHG-20260830-06, defect seat).
        raise SystemExit(1)

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
    try:
        missed = [m for m in chosen if not run(m, baseline)]
    except MutationInFlight as blocked:
        # The tool's own refusal shape, not a traceback -- this is an operator telling
        # them what to do, the same as the unknown-group refusal above.
        raise SystemExit(str(blocked)) from None
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
