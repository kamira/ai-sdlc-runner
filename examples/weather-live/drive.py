"""Drive `runner serve` the way an operator does through the console, for the weather-live brief.

    python3 examples/weather-live/drive.py --keep-serving

There is no agent in this directory. The runner builds the page, with whatever `runner.yaml` names
as its backend, and this script is only the person: it types the brief, starts the run, approves
each gate the run stops at, and says where `site/` ended up. The wire is `weather-spa/scenarios.py`'s
scenario A -- copied rather than imported, so the two examples stay independent.

`--dry-run` checks the plan, `runner.yaml` and the brief, starts nothing and spends nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

#: The ten files the brief names. The dry run refuses a brief that lost one.
MODULES = ("index.html", "styles.css", "sources.js", "openmeteo.js", "cwa.js",
           "normalize.js", "now.js", "week.js", "chart.js", "app.js")



def utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def validate(runner_yaml: Path) -> str:
    """Load the plan, the settings file and the brief the way the runner will. Returns the brief."""
    sys.path.insert(0, str(REPO / "src"))
    from ai_sdlc_runner import cli, plan

    plan.load(str(HERE / "plan.json"))
    config = cli.load_config(str(runner_yaml))
    if not config.get("agent_command"):
        raise SystemExit(f"{runner_yaml} names no agent_command: the runner would answer with its stub")
    brief = (HERE / "brief.md").read_text(encoding="utf-8")
    missing = [name for name in MODULES if name not in brief]
    if missing:
        raise SystemExit(f"brief.md does not name {', '.join(missing)}")
    return brief


class Console:
    """The console's side of the wire: the token, an Origin, and the version being answered."""

    def __init__(self, port: int, token: str):
        self.base = f"http://127.0.0.1:{port}"
        self.token = token

    def call(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     method="POST" if data else "GET")
        req.add_header("X-Operator-Token", self.token)
        req.add_header("Origin", self.base)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=None) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw or "{}")
            except json.JSONDecodeError:
                return exc.code, {"error": raw}

    def state(self):
        return self.call("/run")[1]

    def act(self, path, body):
        """What every button does: read the version, then answer it."""
        status, answer = self.call(path, dict(body, version=self.state()["version"]))
        if status >= 400:
            raise SystemExit(f"{path} was refused ({status}): {answer.get('error', answer)}")
        return answer


def start_server(work: Path, runner_yaml: Path, brief: str):
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "plan.json", work / "plan.json")
    shutil.copy(runner_yaml, work / "runner.yaml")
    (work / "brief.md").write_text(brief, encoding="utf-8")
    port = free_port()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONPATH=str(REPO / "src"))
    proc = subprocess.Popen(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(work / "runner.yaml"), "serve",
         "--plan", str(work / "plan.json"), "--port", str(port),
         "--project", "一週氣象 Taipei live",
         "--store-root", str(work / "conv"),
         "--ask-journal", str(work / ".runner" / "asks")],
        cwd=str(work), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace")
    token_file = work / ".runner" / "operator.token"
    for _ in range(120):
        if token_file.exists() and proc.poll() is None:
            break
        if proc.poll() is not None:
            raise SystemExit("the server exited before it wrote a token:\n"
                             + (proc.stdout.read() if proc.stdout else ""))
        time.sleep(0.25)
    else:
        proc.terminate()
        raise SystemExit("the server never wrote a token")
    return proc, Console(port, token_file.read_text(encoding="utf-8").strip()), token_file


def journal_nodes(journal: Path, seen: set):
    """The nodes whose question has been written down since the last look, oldest first.

    The server publishes its snapshot only when a walk comes to rest, so `/run` cannot show a node
    change while one is running. The ask journal can: each ask's order is written to it *before* the
    ask is made, so a new file is a node entered. Runner nodes that ask nobody (`next_module`,
    `module_built`) leave no file; they show in the final `visited` count instead.
    """
    found = []
    for path in sorted(journal.glob("*.json")) if journal.is_dir() else []:
        if path.name in seen:
            continue
        seen.add(path.name)
        try:
            found.append(json.loads(path.read_text(encoding="utf-8"))["node_id"])
        except (OSError, ValueError, KeyError):
            found.append(path.stem.split("-", 1)[-1])      # `007-engineer_build` -> the node
    return found


def walk(console: Console, brief: str, journal: Path, on_node):
    """Type the brief, start, approve each gate, and print one line per node change."""
    run_id = None
    seen: set = set()
    last = None

    def announce(state):
        nonlocal run_id, last
        # The id is only on the snapshot while the run is stopped at a gate.
        run_id = (state.get("suspended") or {}).get("run_id") or run_id
        for node in journal_nodes(journal, seen):
            if node == last:                 # several seats on one node are one change
                continue
            last = node
            stamp = utc()
            print(f"{stamp}  {node}", flush=True)
            if on_node:
                subprocess.run([*on_node, node, stamp], check=False)

    def press(path, body):
        """A button press. The server answers only when the walk it starts has come to rest, so the
        press runs on its own thread and the node changes are read meanwhile -- one blocking
        call would print every line at the end, with the end's time."""
        outcome = {}

        def go():
            try:
                outcome["answer"] = console.act(path, body)
            except BaseException as exc:      # SystemExit from a refusal included
                outcome["error"] = exc

        worker = threading.Thread(target=go, daemon=True)
        worker.start()
        while worker.is_alive():
            announce(console.state())
            worker.join(0.2)
        if "error" in outcome:
            raise outcome["error"]
        state = console.state()
        announce(state)
        return state

    state = press("/run", {"instruction": brief})
    while state.get("state") == "suspended":
        stop = state.get("suspended") or {}
        print(f"{utc()}  stopped at gate {stop.get('gate')} ({stop.get('node_id')}); approving",
              flush=True)
        state = press("/run/gate", {"gate": stop.get("gate"), "node_id": stop.get("node_id")})
    return state, run_id


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runner-yaml", type=Path, default=HERE / "runner.yaml",
                    help="the backend to build with (default: the real one beside this file)")
    ap.add_argument("--workdir", type=Path, default=None,
                    help="where the run lives (default: a new temporary directory)")
    ap.add_argument("--keep-serving", action="store_true",
                    help="stay up after the end and print the console URL and the token file's path")
    ap.add_argument("--on-node", default=None, metavar="CMD",
                    help="run CMD <node-id> <utc-time> on every node change")
    ap.add_argument("--start-when", type=Path, default=None, metavar="PATH",
                    help="once serving, wait until PATH exists before typing the brief")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the plan, runner.yaml and brief, then exit without a run")
    args = ap.parse_args(argv)

    runner_yaml = args.runner_yaml.resolve()
    brief = validate(runner_yaml)
    if args.dry_run:
        print(f"ok: plan, {runner_yaml.name} and brief ({len(MODULES)} modules named) are valid; "
              f"nothing was started")
        return 0

    work = (args.workdir or Path(tempfile.mkdtemp(prefix="weather-live-"))).resolve()
    proc, console, token_file = start_server(work, runner_yaml, brief)
    try:
        print(f"{utc()}  serving {console.base} in {work}", flush=True)
        if args.start_when:
            print(f"{utc()}  waiting for {args.start_when} before starting the run", flush=True)
            while not args.start_when.exists():
                if proc.poll() is not None:
                    raise SystemExit("the server exited while waiting to start")
                time.sleep(0.5)
        state, run_id = walk(console, brief, work / ".runner" / "asks", args.on_node.split() if args.on_node else None)
        print(f"run id:      {run_id or 'unknown (the run never stopped at a gate)'}")
        print(f"final node:  {state.get('at')}  (state {state.get('state')}, "
              f"{len(state.get('visited') or [])} nodes walked)")
        site = work / "site"
        print(f"site/:       {site}" + ("" if site.exists() else "  (nothing was built)"))
        if args.keep_serving:
            print(f"console:     {console.base}/")
            print(f"token file:  {token_file}")
            print("serving until interrupted (Ctrl-C)", flush=True)
            try:
                while proc.poll() is None:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        return 0 if state.get("state") == "finished" else 1
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
