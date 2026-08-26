"""Five runs against the **console**, not the CLI. Every one is something that really happened.

`examples/tide-spa` drives `runner run` and changes the plan. This one starts `runner serve` and
talks to it the way the operator console does — an instruction typed into a box, a gate approved by
clicking a button. The failures it shows are the ones that only exist on that path.

    python3 examples/weather-spa/scenarios.py

Each scenario gets its own temporary directory, its own port, and its own server, which is stopped
again afterwards. Nothing is written into the repository.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Console:
    """The console's side of the wire, and nothing more than it does.

    Every request carries `X-Operator-Token` and an `Origin`, because the server refuses without
    them — and every mutating call carries the version it is answering, because the server refuses
    that too: *"without it two tabs cannot be told apart, and a double-click spends two approvals"*.
    """

    def __init__(self, work: Path, port: int, token: str):
        self.work, self.port, self.token = work, port, token
        self.base = f"http://127.0.0.1:{port}"

    def call(self, path, body=None, token=None, origin=None, host=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     method="POST" if data else "GET")
        presented = self.token if token is None else token
        if presented:
            req.add_header("X-Operator-Token", presented)
        req.add_header("Origin", origin or self.base)
        if host:
            req.add_header("Host", host)
        if data:
            req.add_header("Content-Type", "application/json")
        def decode(raw):
            # `/` answers with the console's HTML, every other route with JSON. Assuming JSON
            # everywhere turned a working shell into `Expecting value: line 1 column 1`.
            try:
                return json.loads(raw or "{}")
            except json.JSONDecodeError:
                return {"html": len(raw)}

        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, decode(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            return exc.code, decode(exc.read().decode("utf-8", "replace"))

    def state(self):
        return self.call("/run")[1]

    def act(self, path, body):
        """What every button on the page does: read the version, then answer it."""
        return self.call(path, dict(body, version=self.state()["version"]))

    def settle(self, seconds=240):
        end = time.time() + seconds
        while time.time() < end:
            s = self.state()
            if s.get("state") in ("suspended", "finished", "stopped", "error", "idle"):
                if s.get("state") != "running":
                    return s
            time.sleep(0.5)
        return self.state()


def start(work: Path, agent_body: str | None = None, extra=()):
    """Lay out a project and start `runner serve` on it. Returns (process, Console)."""
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "plan.json", work / "plan.json")
    (work / "runner.yaml").write_text((HERE / "runner.yaml").read_text(encoding="utf-8"),
                                      encoding="utf-8")
    (work / "agent.py").write_text(
        agent_body if agent_body is not None else (HERE / "agent.py").read_text(encoding="utf-8"),
        encoding="utf-8")

    port = free_port()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONPATH=str(REPO / "src"))
    proc = subprocess.Popen(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(work / "runner.yaml"), "serve",
         "--plan", str(work / "plan.json"), "--port", str(port),
         "--project", "一週氣象 Taipei",
         "--store-root", str(work / "conv"),
         "--ask-journal", str(work / ".runner" / "asks"), *extra],
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
        raise SystemExit("the server never wrote a token")

    return proc, Console(work, port, token_file.read_text(encoding="utf-8").strip())


BRIEF = ("做一個當地一週氣象的單頁網站，地點台北。七天預報要有每天的最高溫、最低溫和降雨機率；"
         "中間要顯示現在天氣，包含現在氣溫和濕度。不要連外網。")
SECOND = "中間那塊除了氣溫和濕度，也把體感溫度和風速加上去。另外今天的溫度變化畫成曲線，標出現在的位置。"


# ── A · the brief, typed into the box ─────────────────────────────────────────────────────────

def scenario_a(work):
    """`start the run` with the brief in `#instruction`, then `approve merge`."""
    proc, c = start(work)
    try:
        c.act("/run", {"instruction": BRIEF})
        s = c.settle()
        note = [f"walked to {s.get('at')} · state {s.get('state')}"]
        if s.get("state") == "suspended":
            gate = (s["suspended"] or {}).get("gate")
            note.append(f"the page shows a button reading 'approve {gate}'")
            c.act("/run/gate", {"gate": gate, "node_id": (s["suspended"] or {}).get("node_id")})
            s = c.settle()
            note.append(f"after approving: {s.get('state')} at {s.get('at')}")
        built = sorted(p.name for p in (work / "site").iterdir()) if (work / "site").exists() else []
        return {"built": built, "instructions": len(s.get("instructions") or []), "notes": note}
    finally:
        proc.terminate()


# ── B · the two buttons are not the same button ───────────────────────────────────────────────

def scenario_b(work):
    """`start the run` **replaces** the brief; `add to the brief` appends.

    Using the first for a follow-up silently drops the original instruction — which is what happened
    the first time this project was driven, and it is invisible until you read the conversation.
    """
    proc, c = start(work)
    try:
        c.act("/run", {"instruction": BRIEF})
        c.settle()
        after_first = len(c.state().get("instructions") or [])

        c.act("/run", {"instruction": SECOND})          # `start the run` again
        c.settle()
        replaced = len(c.state().get("instructions") or [])

        c.act("/run/instruct", {"instruction": SECOND})  # `add to the brief`
        c.settle()
        appended = len(c.state().get("instructions") or [])

        return {"after_first": after_first, "after_start_again": replaced,
                "after_add_to_brief": appended,
                "notes": [f"`start the run` left {replaced} instruction(s), not 2",
                          f"`add to the brief` left {appended}"]}
    finally:
        proc.terminate()


# ── C · an agent that cannot tell "done" from "done again" ────────────────────────────────────

CYCLING_AGENT = '''"""An agent that picks the next module by asking which FILE does not exist yet."""
import json, sys
from pathlib import Path
OUT = Path(__file__).resolve().parent / "site"
ORDER = ["markup", "styles", "weather", "app"]
NAMES = {"markup": "index.html", "styles": "styles.css",
         "weather": "weather.js", "app": "app.js"}


def main():
    order = json.loads(sys.stdin.read())
    node, seat = order["node_id"], order.get("seat")
    if node == "intake_review":
        print(json.dumps({"missing": [], "problems": [], "unsafe": []})); return
    if seat:
        print(json.dumps({"verdict": "pass", "why": seat})); return
    if node == "pm_plan":
        print(json.dumps({"modules": ORDER})); return
    if node == "engineer_build":
        OUT.mkdir(parents=True, exist_ok=True)
        have = {p.name for p in OUT.iterdir()}
        nxt = next((m for m in ORDER if NAMES[m] not in have), ORDER[-1])
        (OUT / NAMES[nxt]).write_text("/* built */\\n", encoding="utf-8")
        print(json.dumps({"module": nxt, "wrote": NAMES[nxt]})); return
    branches = {"pm_confirm": "yes", "pm_signoff": "yes", "next_module": "module",
                "lead_task_review": "pass", "re_review": "pass", "lead_review": "pass",
                "qa_accept": "pass", "feedback": "done"}
    print(json.dumps({"verdict": branches.get(node, "pass")}))


main()
'''


def scenario_c(work):
    """Once all four files exist, that agent answers with the last module forever and
    `next_module: frontier` never advances. The runner stops it rather than looping."""
    proc, c = start(work, agent_body=CYCLING_AGENT)
    try:
        c.act("/run", {"instruction": BRIEF})
        s = c.settle()
        if s.get("state") == "suspended":
            gate = (s["suspended"] or {}).get("gate")
            c.act("/run/gate", {"gate": gate, "node_id": (s["suspended"] or {}).get("node_id")})
            c.settle()
        c.act("/run/instruct", {"instruction": SECOND})   # a second walk over finished work
        s = c.settle()
        return {"state": s.get("state"), "error": str(s.get("error") or "")[:150],
                "notes": ["the step cap is what ends this, not a timeout"]}
    finally:
        proc.terminate()


# ── D · no token ──────────────────────────────────────────────────────────────────────────────

def scenario_d(work):
    """The page loads without one — nothing can present a token before loading the page that stores
    it — but every route behind it refuses."""
    proc, c = start(work)
    try:
        shell = c.call("/")
        code, body = c.call("/run", token="")
        return {"shell_status": shell[0], "run_status": code,
                "error": str(body.get("error") or "")[:120]}
    finally:
        proc.terminate()


# ── E · a Host header that is not loopback ────────────────────────────────────────────────────

def scenario_e(work):
    """DNS rebinding: a name that resolves to 127.0.0.1 reaches the socket, and the `Host` header is
    the only thing that says which name was asked for. Refused before the request is understood."""
    proc, c = start(work)
    try:
        code, body = c.call("/run", host="weather.attacker.example")
        cross, cbody = c.call("/run", origin="http://evil.example")
        return {"bad_host_status": code, "host_error": str(body.get("error") or "")[:90],
                "cross_origin_status": cross, "origin_error": str(cbody.get("error") or "")[:90]}
    finally:
        proc.terminate()


SCENARIOS = [
    ("A · the brief, typed into the console", scenario_a),
    ("B · `start the run` is not `add to the brief`", scenario_b),
    ("C · an agent that cycles, and the cap that stops it", scenario_c),
    ("D · a request with no operator token", scenario_d),
    ("E · a Host header that is not loopback", scenario_e),
]


def main():
    keep = sys.argv[1] if len(sys.argv) > 1 else None
    rows = []
    for n, (label, run) in enumerate(SCENARIOS):
        work = (Path(keep) / f"scenario-{chr(65 + n)}" if keep
                else Path(tempfile.mkdtemp(prefix="weather-")))
        print(f"\n{'─' * 88}\n{label}\n{'─' * 88}")
        result = run(work)
        for key, value in result.items():
            if key == "notes":
                for note in value:
                    print(f"    · {note}")
            else:
                print(f"  {key}: {value}")
        rows.append((label, result))

    print(f"\n{'═' * 88}\nsummary\n{'═' * 88}")
    for label, result in rows:
        head = next((f"{k}={v}" for k, v in result.items() if k != "notes"), "")
        print(f"  {label:<48} {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
