"""Record one real console-driven run and keep it as the fixture the demo recording renders from.

    python3 examples/demo/make_fixture.py

Run this when the fixture should be refreshed — it is **not** part of `build.py`, and that is the
point. A recording carries wall-clock timestamps, so a page generated fresh on every build could
never be byte-compared against a committed one. Rendering from a fixed conversation makes the demo
recording reproducible while still being a real run: the fixture is what a console-driven run
actually wrote, not a hand-made sample.

What it drives, through the same routes the operator console uses:

1. the brief, typed and started
2. `merge` — the run stops, and a person approves it
3. a second instruction, added to the brief the way the page's second button does

Absolute paths are scrubbed on the way out. The `opened` turn records the journal directory this
happened to run in, and nobody needs a stranger's temp path in their repository.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent
REPO = EXAMPLES.parent
OUT = HERE / "conversations"

sys.path.insert(0, str(REPO / "src"))


def _scenarios():
    spec = importlib.util.spec_from_file_location(
        "weather_scenarios", EXAMPLES / "weather-spa" / "scenarios.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scrub(line: str) -> str:
    """Replace anything that names this machine.

    Windows and POSIX both, and the JSON escaping of a Windows path doubles every separator — so the
    pattern has to match `C:\\\\Users\\\\…` as it appears *inside* a JSON string, not as it appears
    on disk.
    """
    line = re.sub(r'"[A-Za-z]:\\\\(?:[^"\\]|\\\\)*"', '"<journal>"', line)
    line = re.sub(r'"/(?:tmp|var|home|Users)/[^"]*"', '"<journal>"', line)
    return line


def main():
    scenarios = _scenarios()
    with tempfile.TemporaryDirectory(prefix="fixture-") as tmp:
        work = Path(tmp) / "run"
        proc, console = scenarios.start(work)
        try:
            console.act("/run", {"instruction": scenarios.BRIEF})
            state = console.settle()
            if state.get("state") != "suspended":
                raise SystemExit(f"expected a stop at a gate, got {state.get('state')}")
            gate = (state["suspended"] or {})
            print(f"  stopped at {gate.get('gate')} — approving, as the page's button does")
            console.act("/run/gate", {"gate": gate.get("gate"), "node_id": gate.get("node_id")})
            console.settle()

            print("  adding a second instruction to the brief")
            console.act("/run/instruct", {"instruction": scenarios.SECOND})
            state = console.settle()
            print(f"  finished: {state.get('state')} at {state.get('at')}")
        finally:
            proc.terminate()

        source = work / "conv"
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)

        total = 0
        for project_dir in sorted(p for p in source.iterdir() if p.is_dir()):
            target = OUT / project_dir.name
            target.mkdir()
            for path in sorted(project_dir.iterdir()):
                text = path.read_text(encoding="utf-8")
                cleaned = "".join(scrub(line) + "\n" for line in text.splitlines() if line.strip())
                io.open(target / path.name, "w", encoding="utf-8", newline="\n").write(cleaned)
                total += len(cleaned)
                if path.suffix == ".jsonl":
                    turns = len(cleaned.splitlines()) - 1
                    print(f"  {path.name}: {turns} turns, {len(cleaned):,} bytes")

        leaked = [ln for f in OUT.rglob("*") if f.is_file()
                  for ln in f.read_text(encoding="utf-8").splitlines()
                  if re.search(r"[A-Za-z]:\\\\|/(tmp|home|Users)/", ln)]
        if leaked:
            raise SystemExit(f"a path survived scrubbing: {leaked[0][:160]}")
        print(f"  wrote {total:,} bytes to {OUT.relative_to(REPO)}")

    print("\nnow run: python3 examples/demo/build.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
