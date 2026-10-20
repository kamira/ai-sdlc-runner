"""Drive `runner serve` the way an operator does through the console, for the weather-live brief.

    python3 examples/weather-live/drive.py --keep-serving

There is no agent in this directory. The runner builds the page, with whatever `runner.yaml` names
as its backend, and this script is only the person: it types the brief, starts the run, approves
each ordinary gate the run stops at, and says where `site/` ended up. The wire is
`weather-spa/scenarios.py`'s scenario A -- copied rather than imported, so the two examples stay
independent.

A stop that asks a person to read something is never answered here. Those are a seat calling the
requirement unsafe (`POST /run/proceed`), an incomplete requirement (`POST /run/instruct`) and a
panel that tied (`POST /run/decide`). drive.py writes the server's text to
`<NNN>-<node>.md` in a temporary directory outside the workdir (the build model can write inside
the workdir, so it must not be able to answer), prints `AWAITING-PERSON <that path>`, and waits for
`<NNN>-<node>.proceed` (its text is the instruction, or the branch, where the route takes one) or
`<NNN>-<node>.stop` beside it. A `.proceed` that already exists when the stop is written is refused.

`--dry-run` checks the plan, `runner.yaml` and the brief, starts nothing and spends nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
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


def models_beside(runner_yaml: Path) -> Path | None:
    """The registry of the backend `runner_yaml` names: `models.json` in its directory, if any."""
    found = runner_yaml.parent / "models.json"
    return found if found.is_file() else None


def validate(runner_yaml: Path, models: Path | None) -> str:
    """Load the plan, the settings file and the brief the way the runner will. Returns the brief."""
    sys.path.insert(0, str(REPO / "src"))
    from ai_sdlc_runner import cli, models as models_mod, plan

    loaded = plan.load(str(HERE / "plan.json"))
    wanted = {m for ids in (loaded.get("node_models") or {}).values() for m in ids}
    if models is not None:
        try:
            registry = models_mod.load(models)
            for model_id in wanted:
                registry.get(model_id)
        except models_mod.ModelError as exc:
            raise SystemExit(f"{models}: {exc}")
    elif wanted:
        print(f"note: no models.json beside {runner_yaml.name}, so the plan's node_models "
              f"({', '.join(sorted(wanted))}) are dropped and agent_command answers every node")
    config = cli.load_config(str(runner_yaml))
    if not config.get("agent_command"):
        raise SystemExit(f"{runner_yaml} names no agent_command: the runner would answer with its stub")
    brief = (HERE / "brief.md").read_text(encoding="utf-8")
    missing = [name for name in MODULES if name not in brief]
    if missing:
        raise SystemExit(f"brief.md does not name {', '.join(missing)}")
    return brief


class Refused(Exception):
    """A route answered with a 4xx or 5xx. The message is the server's own."""


class PersonStop(Exception):
    """The person asked for the run to end at a stop they were shown."""


#: What the server's `suspended` says -> the route that answers it and the body fields it needs.
#: Read from `server._require_suspension`, which refuses the other three for each.
PERSON_ROUTES = {"unsafe": "/run/proceed", "incomplete": "/run/instruct", "undecided": "/run/decide"}


def stop_kind(stop: dict) -> str:
    """`gate`, or the shape of a stop that needs a person: `unsafe`, `incomplete`, `undecided`."""
    for kind in ("unsafe", "incomplete", "undecided"):
        if stop.get(kind):
            return kind
    return "gate"


def person_text(state: dict, kind: str, number: int) -> str:
    """Everything the server says about this stop, for the person to read."""
    stop = state.get("suspended") or {}
    lines = [f"# Stop {number:03d}: {stop.get('node_id')} ({kind})", "",
             f"Answered by `POST {PERSON_ROUTES[kind]}`.", "",
             f"The run says: {state.get('reason') or stop.get('reason') or '(nothing)'}", ""]
    if kind == "unsafe":
        lines += ["## What the seats called unsafe", ""]
        for seat, said in sorted((stop.get("safety") or {}).items()):
            lines += [f"### seat: {seat}", ""] + [f"- {line}" for line in said] + [""]
    if stop.get("missing"):
        lines += ["## Missing", ""] + [f"- {m}" for m in stop["missing"]] + [""]
    if stop.get("problems"):
        lines += ["## Problems the seats raised", ""] + [f"- {m}" for m in stop["problems"]] + [""]
    if kind == "undecided":
        lines += ["## Branches", "", ", ".join(stop.get("branches") or []), ""]
        for seat, verdict in sorted((stop.get("verdicts") or {}).items()):
            lines.append(f"- {seat}: {verdict}")
        lines.append("")
    lines += ["## How to answer", "",
              {"unsafe": "Create the `.proceed` file to continue past this, or `.stop` to end the run.",
               "incomplete": "Put the missing requirement in the `.proceed` file (its text is added "
                             "to the brief), or create `.stop` to end the run.",
               "undecided": "Put the branch you choose in the `.proceed` file, or create `.stop`."
               }[kind], ""]
    return "\n".join(lines)


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
            raise Refused(f"{path} was refused ({status}): {answer.get('error', answer)}")
        return answer


def start_server(work: Path, runner_yaml: Path, brief: str, models: Path | None):
    work.mkdir(parents=True, exist_ok=True)
    if models is not None:
        # `serve` reads `<token dir>/models.json`, and the token dir is `.runner`.
        (work / ".runner").mkdir(exist_ok=True)
        shutil.copy(models, work / ".runner" / "models.json")
        shutil.copy(HERE / "plan.json", work / "plan.json")
    else:
        stripped = json.loads((HERE / "plan.json").read_text(encoding="utf-8"))
        stripped.pop("node_models", None)
        (work / "plan.json").write_text(json.dumps(stripped, indent=2) + "\n", encoding="utf-8")
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


def walk(console: Console, brief: str, journal: Path, on_node, person_dir: Path, server=None):
    """Type the brief, start, approve each ordinary gate, hand every other stop to a person, and
    print one line per node change. Returns the state and the run id; `Refused` and `PersonStop`
    leave the state on the console."""
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

    def ask_person(state, kind, number):
        """Write the stop down, wait for the person's file, answer with the route the server named."""
        stop = state.get("suspended") or {}
        node = stop.get("node_id")
        person_dir.mkdir(parents=True, exist_ok=True)
        text_path = person_dir / f"{number:03d}-{node}.md"
        proceed, halt = text_path.with_suffix(".proceed"), text_path.with_suffix(".stop")
        if proceed.exists():
            raise Refused(f"{proceed} already existed before the stop at {node} was written; "
                          f"an answer must come after the question, so it is not taken")
        text_path.write_text(person_text(state, kind, number), encoding="utf-8")
        print(f"{utc()}  stopped at {node} for a person to read ({kind})", flush=True)
        print(f"AWAITING-PERSON {text_path}", flush=True)
        said = ""
        while True:
            if halt.exists():
                raise PersonStop(f"{utc()}  STOPPED-BY-PERSON at {node} ({halt.name}); "
                                 f"the run was not continued")
            if proceed.exists():
                said = proceed.read_text(encoding="utf-8").strip()
                if said or kind == "unsafe":
                    break
            if server is not None and server.poll() is not None:
                raise Refused("the server exited while waiting for a person")
            time.sleep(0.5)
        route = PERSON_ROUTES[kind]
        body = {"node_id": node}
        if kind == "incomplete":
            body = {"instruction": said}
        elif kind == "undecided":
            body["branch"] = said.split()[0]
        # Printed when the answer is sent, not when the walk it starts has come to rest.
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        print(f"PERSON-ANSWERED {route.rsplit('/', 1)[-1]} {stamp}", flush=True)
        return press(route, body)

    state = press("/run", {"instruction": brief})
    people = 0
    while state.get("state") == "suspended":
        stop = state.get("suspended") or {}
        kind = stop_kind(stop)
        if kind == "gate":
            print(f"{utc()}  stopped at gate {stop.get('gate')} ({stop.get('node_id')}); approving",
                  flush=True)
            state = press("/run/gate", {"gate": stop.get("gate"), "node_id": stop.get("node_id")})
        else:
            people += 1
            state = ask_person(state, kind, people)
    return state, run_id


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runner-yaml", type=Path, default=HERE / "runner.yaml",
                    help="the backend to build with (default: the real one beside this file)")
    ap.add_argument("--models", type=Path, default=None, metavar="PATH",
                    help="the model registry the plan's node_models name (default: models.json "
                         "beside --runner-yaml; none there means agent_command answers every node)")
    ap.add_argument("--workdir", type=Path, default=None,
                    help="where the run lives (default: a new temporary directory)")
    ap.add_argument("--keep-serving", action="store_true",
                    help="stay up after the end and print the console URL and the token file's path")
    ap.add_argument("--on-node", default=None, metavar="CMD",
                    help="run CMD <node-id> <utc-time> on every node change")
    ap.add_argument("--start-when", type=Path, default=None, metavar="PATH",
                    help="once serving, wait until PATH exists before typing the brief")
    ap.add_argument("--person-dir", type=Path, default=None, metavar="DIR",
                    help="where a stop that needs a person is written, and where their .proceed or "
                         ".stop file is looked for; must be outside --workdir "
                         "(default: a new temporary directory)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the plan, runner.yaml and brief, then exit without a run")
    args = ap.parse_args(argv)

    runner_yaml = args.runner_yaml.resolve()
    models = args.models.resolve() if args.models else models_beside(runner_yaml)
    brief = validate(runner_yaml, models)
    if args.dry_run:
        print(f"ok: plan, {runner_yaml.name} and brief ({len(MODULES)} modules named) are valid; "
              f"nothing was started")
        return 0

    work = (args.workdir or Path(tempfile.mkdtemp(prefix="weather-live-"))).resolve()
    if args.person_dir:
        person_dir = args.person_dir.resolve()
        if person_dir == work or work in person_dir.parents:
            raise SystemExit(f"--person-dir {person_dir} is inside the workdir {work}, where the "
                             f"build model can write; choose a directory outside it")
    else:
        person_dir = Path(tempfile.mkdtemp(prefix="weather-live-person-")).resolve()
        print(f"{utc()}  a stop that needs a person is written to {person_dir}", flush=True)
    proc, console, token_file = start_server(work, runner_yaml, brief, models)
    try:
        print(f"{utc()}  serving {console.base} in {work}", flush=True)
        if args.start_when:
            print(f"{utc()}  waiting for {args.start_when} before starting the run", flush=True)
            while not args.start_when.exists():
                if proc.poll() is not None:
                    raise SystemExit("the server exited while waiting to start")
                time.sleep(0.5)
        run_id, failure, ended = None, None, False
        try:
            state, run_id = walk(console, brief, work / ".runner" / "asks",
                                 shlex.split(args.on_node, posix=(os.name != "nt"))
                                 if args.on_node else None, person_dir, proc)
        except PersonStop as exc:
            failure, ended = str(exc), True
        except Refused as exc:
            failure = f"{utc()}  REFUSED: {exc}"
        if failure:
            print(failure, flush=True)
            state = console.state() if proc.poll() is None else {}
        print(f"run id:      {run_id or 'unknown (the run never stopped at a gate)'}")
        print(f"final node:  {state.get('at')}  (state {state.get('state')}, "
              f"{len(state.get('visited') or [])} nodes walked)")
        site = work / "site"
        print(f"site/:       {site}" + ("" if site.exists() else "  (nothing was built)"))
        if args.keep_serving and not ended and proc.poll() is None:
            print(f"console:     {console.base}/")
            print(f"token file:  {token_file}")
            print("serving until interrupted (Ctrl-C)", flush=True)
            try:
                while proc.poll() is None:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        return 0 if state.get("state") == "finished" and not failure else 1
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
