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
because the number "7/7 caught" invites the other reading.

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
from typing import List, NamedTuple

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/ai_sdlc_runner"


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
        '''    cwd = config.get("agent_cwd") or None''',
        '''    cwd = None''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "provenance", "the plan a run walked is recorded as the operator's keystrokes again",
        SRC / "cli.py",
        '''             "plan": _where(args.plan)})''',
        '''             "plan": str(args.plan)})''',
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


def run(mutation: Mutation) -> bool:
    """Apply, run, restore. The restore is in a `finally` because leaving a mutated tree behind is
    a worse outcome than any result this function can report."""
    original = io.open(mutation.path, encoding="utf-8").read()
    if mutation.before not in original:
        print(f"  ANCHOR GONE  {mutation.says}")
        print(f"               {mutation.path.name} no longer contains the text this mutates. The "
              f"mutation is stale, which is not the same as caught.")
        return False
    io.open(mutation.path, "w", encoding="utf-8", newline="\n").write(
        original.replace(mutation.before, mutation.after, 1))
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", mutation.tests, "-q", "-p", "no:randomly",
             "--no-header", "-x", "--tb=no"],
            cwd=REPO, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})
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
    missed = [m for m in chosen if not run(m)]
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
