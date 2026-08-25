"""Four runs of the same brief, differing by one field each, driven end to end.

The point of the example is not the tide table. It is that **one changed field moves where the run
stops**, and that the runner says which field and which gate rather than failing somewhere further
down as a missing file.

Each scenario starts from `plan.json` — the plan that walks the whole flow — and applies a single
named mutation. Run it:

    python3 examples/tide-spa/scenarios.py

It writes nothing into the repository: every run gets its own temporary directory, with its own
copy of `agent.py`, its own ask journal and its own conversation store.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PLAN = json.loads((HERE / "plan.json").read_text(encoding="utf-8"))


# ── the four mutations ────────────────────────────────────────────────────────────────────────
#
# Each takes the working plan and changes exactly one thing. The comment on each is the claim the
# scenario tests; `scenarios.py` is run by `tests/test_example_tide_spa.py`, so a claim that stops
# being true fails the suite rather than going stale in a README.

def unchanged(plan):
    """The whole flow: 24 nodes, four modules, a merge."""
    return plan


def a_deploy_operation(plan):
    """`deploy` is one of the six kinds never automated at any risk grade. Declaring one inside an
    otherwise ordinary build is the realistic version of this mistake — nobody writes a plan whose
    every operation is a deploy."""
    plan["operations"]["engineer_build"] = [{
        "description": "push the site to production",
        "kind": "deploy",
        "targets": ["https://tides.example.com"],
    }]
    return plan


def an_empty_spec(plan):
    """A node spec whose fields are present but blank. The closed schema accepts the *shape*; the
    node still has nothing to build from, and the runner must say so before dispatching a model
    against an empty objective."""
    for node in ("engineer_build", "engineer_selfverify"):
        for field in ("scope", "objective", "expected_outputs"):
            plan["node_specs"][node][field] = ""
    return plan


def a_misspelled_key(plan):
    """`operationz` instead of `operations`. A schema that ignored the unknown key would run the
    whole flow with no declared operations at all — the silent dry run this project has hit twice."""
    plan["operationz"] = plan.pop("operations")
    return plan


def an_orphan_acceptance(plan):
    """`ship.acc_id` names an acceptance record with no task to hang it on. The ledger would take
    it; nothing would ever close it."""
    plan["ship"] = {"repo": ".", "branch": "b", "message": "m",
                    "chg_id": "CHG-1", "acc_id": "ACC-9", "acc_body": "evidence"}
    return plan


SCENARIOS = [
    ("A · the flow as written", unchanged),
    ("B · a deploy inside the build", a_deploy_operation),
    ("C · a spec with nothing in it", an_empty_spec),
    ("D · operations, misspelled", a_misspelled_key),
    ("E · an acceptance with no task", an_orphan_acceptance),
]


def run_one(label, mutate, keep=None):
    """Drive one scenario in its own directory. Returns (exit code, stdout+stderr, workdir)."""
    work = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="tide-"))
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "agent.py", work / "agent.py")
    (work / "runner.yaml").write_text(
        (HERE / "runner.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    plan = mutate(copy.deepcopy(PLAN))
    (work / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(REPO / "src"))
    proc = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(work / "runner.yaml"),
         "run", "--plan", str(work / "plan.json"),
         "--ask-journal", str(work / "asks"),
         "--project", "Porthcurno Tide SPA",
         "--store-root", str(work / "conv")],
        cwd=str(work), env=env, capture_output=True, timeout=600,
        # `text=True` alone decodes with the *caller's* locale codec, and the runner's messages are
        # full of em-dashes: on a cp950 console this driver died with UnicodeDecodeError while the
        # run underneath it had succeeded. The example must not depend on the caller having set
        # PYTHONUTF8 before invoking it.
        encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr), work


def main():
    keep = sys.argv[1] if len(sys.argv) > 1 else None
    rows = []
    for n, (label, mutate) in enumerate(SCENARIOS):
        where = Path(keep) / f"scenario-{chr(65 + n)}" if keep else None
        code, output, work = run_one(label, mutate, where)
        asks = len(list((work / "asks").glob("*.json"))) if (work / "asks").exists() else 0
        built = sorted(p.name for p in (work / "site").iterdir()) if (work / "site").exists() else []
        last = [ln for ln in output.splitlines() if ln.strip()][-1] if output.strip() else ""
        rows.append((label, code, asks, built, last))
        print(f"\n{'─' * 92}\n{label}\n{'─' * 92}")
        print(f"exit {code} · {asks} asks · built {built or 'nothing'}")
        print(f"last line: {last[:200]}")

    print(f"\n{'═' * 92}\nsummary\n{'═' * 92}")
    for label, code, asks, built, _ in rows:
        print(f"  {label:<34} exit {code}  {asks:>2} asks  {len(built)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
