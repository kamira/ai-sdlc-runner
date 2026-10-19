"""Measure a run from its own conversation record. (CHG-20261019-01, the way CHG-20260827-21 Task 6 did)

    python3 docs/measurements/CHG-20261019-01/measure.py WORKDIR [--json OUT]

WORKDIR is the directory `examples/weather-live/drive.py` ran in (`runner serve` wrote its store
under `WORKDIR/conv`); a store root given directly works too. Every number comes from the `ASK` and
`ANSWER` turns, read through the runner's own `conversations` backend, paired by `ask_id`. Which
nodes are "the module loop" is derived from the flow by `graph.module_cycle()`, not listed here.
The "writes" check lists every file under `WORKDIR/site/` with its modification time, attributed to
the ask whose ASK..ANSWER interval contains it, and flags a file written by a node other than
`engineer_build`/`fix_pass`, by `engineer_selfverify` for any file but the module its
`engineer_build` visit just built, or outside every ask. Needs no network and writes nothing but the
optional JSON.

Waiting for a person. A stop is a `closed` turn whose `state` is `suspended`. The record tells the
operator's own gates from a stop that needs a person: a gate answer writes a `decision` turn
(`approval` or `rejection`) next, and the other three kinds (unsafe, incomplete requirement, tie)
do not. The wait runs from that `closed` turn to the first `ask`, `instruction` or `decision` turn
after it. What the record cannot say is the moment the person answered -- the answer to `/run/proceed`
writes nothing of its own -- so that end is the next turn, and includes the few milliseconds the
runner takes to restart. `--drive-log FILE` (drive.py's stdout) gives the moment: each
`PERSON-ANSWERED <route> <UTC>` line ends the wait that began at the last stop before it. The wait is
reported as "waiting for a person" and is not "runner overhead".
"""
from __future__ import annotations

import argparse
import json
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from ai_sdlc_runner import conversations, graph  # noqa: E402

BUILDERS = 4
FORMULA = "ceiling(n) = 1 / ((1 - s) + s / n)      s = the loop's share; n = builders (inf: 1 / (1 - s))"


def _when(stamp: object) -> float:
    return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()


def open_store(workdir: Path) -> conversations.Backend:
    """`WORKDIR/conv` if it is there (what drive.py passes to serve), else WORKDIR itself."""
    root = workdir / "conv" if (workdir / "conv").is_dir() else workdir
    for kind in conversations.BACKENDS:
        try:
            back = conversations.backend(kind, root=str(root))
            if back.conversations():
                return back
        except Exception:  # noqa: BLE001 - try the next kind; reported below if none has a run
            continue
    raise SystemExit(f"no conversation record under {root}")


def turns_of(back: conversations.Backend) -> List[dict]:
    """Every turn of every conversation in the store, in time order (one run is one conversation)."""
    turns: List[dict] = []
    for head in back.conversations():
        pid = str((head.get("project") or {}).get("id"))
        turns += back.read(pid, str(head["conversation_id"]))["turns"]
    return sorted(turns, key=lambda t: (_when(t["at"]), int(t["seq"])))


def asks_of(turns: Sequence[dict]) -> List[dict]:
    """One row per answered ask: node, start, end, seconds, and the answer's result."""
    sent: Dict[str, dict] = {}
    rows: List[dict] = []
    for t in turns:
        if t["kind"] == conversations.ASK:
            sent[t["ask_id"]] = t
        elif t["kind"] == conversations.ANSWER and t.get("ask_id") in sent:
            a = sent.pop(t["ask_id"])
            start, end = _when(a["at"]), _when(t["at"])
            rows.append({"node": a["node_id"], "start": start, "end": end,
                         "seconds": end - start, "result": t.get("result") or {}})
    return rows


#: What a gate answer writes (engine: `conversation.decision("approval" | "rejection", ...)`).
GATE_ANSWERS = ("approval", "rejection")
ANSWERED = re.compile(r"^PERSON-ANSWERED \S+ (\S+Z)\s*$", re.M)


def answered_in(log: str) -> List[float]:
    """The moments drive.py printed `PERSON-ANSWERED`, from its log."""
    return sorted(_when(m.group(1)) for m in ANSWERED.finditer(log))


def person_waits(turns: Sequence[dict], answered: Sequence[float] = ()) -> List[dict]:
    """Every stop that needed a person: node, start, end and seconds, from stop to answer.

    A stop with no turn after it was never answered, and is not counted. With `answered` (from
    `--drive-log`) the end is the last answer given before the next turn, not the next turn.
    """
    waits: List[dict] = []
    for i, t in enumerate(turns):
        if t["kind"] != conversations.CLOSED or t.get("state") != "suspended":
            continue
        after = next((u for u in turns[i + 1:]
                      if u["kind"] in (conversations.ASK, conversations.INSTRUCTION, conversations.DECISION)),
                     None)
        if after is None or (after["kind"] == conversations.DECISION
                             and after.get("decision") in GATE_ANSWERS):
            continue                                      # the operator's gate, or never answered
        start, end, source = _when(t["at"]), _when(after["at"]), "record"
        said = [a for a in answered if start <= a <= end]
        if said:
            end, source = said[-1], "drive log"
        waits.append({"node": t.get("at_node"), "start": start, "end": end,
                      "seconds": end - start, "source": source})
    return waits


def union_seconds(spans: Sequence[Tuple[float, float]]) -> float:
    """Wall-clock covered by the spans, so overlapping asks are not counted twice."""
    total, edge = 0.0, None
    for start, end in sorted(spans):
        if edge is None or start > edge:
            total += end - start
            edge = end
        elif end > edge:
            total += end - edge
            edge = end
    return total


def amdahl(share: float, n: Optional[int]) -> float:
    return 1.0 / ((1.0 - share) + (share / n if n else 0.0))


def measure(turns: Sequence[dict], loop_nodes: Sequence[str], answered: Sequence[float] = ()) -> dict:
    rows = asks_of(turns)
    if not rows:
        raise SystemExit("the record holds no answered ask")
    wall = _when(turns[-1]["at"]) - _when(turns[0]["at"])
    loop = [r for r in rows if r["node"] in loop_nodes]
    inside = union_seconds([(r["start"], r["end"]) for r in rows])
    waits = person_waits(turns, answered)
    waiting = union_seconds([(w["start"], w["end"]) for w in waits])
    in_loop = union_seconds([(r["start"], r["end"]) for r in loop])
    per_node: Dict[str, dict] = {}
    for r in rows:
        n = per_node.setdefault(r["node"], {"asks": 0, "total": 0.0})
        n["asks"] += 1
        n["total"] += r["seconds"]
    for node, n in per_node.items():
        n["mean"] = n["total"] / n["asks"]
        n["loop"] = node in loop_nodes
    built = [r for r in rows if r["node"] == "engineer_build" and r["result"].get("module")]
    # A person's wait is not work concurrency could touch, so it stays out of the denominator.
    working = wall - waiting
    share_t = in_loop / working if working > 0 else 0.0
    share_n = len(loop) / len(rows)
    out = {
        "wall_seconds": wall,
        "inside_asks_seconds": inside,
        "module_loop_seconds": in_loop,
        "everything_else_seconds": inside - in_loop,
        "waiting_for_person_seconds": waiting,
        "working_seconds": working,
        "person_stops": waits,
        "runner_overhead_seconds": wall - inside - waiting,
        "loop_nodes": sorted(loop_nodes),
        "per_node": dict(sorted(per_node.items(), key=lambda kv: -kv[1]["total"])),
        "modules_built": len(built),
        "asks_total": len(rows),
        "asks_in_loop": len(loop),
        "formula": FORMULA,
        "builders": BUILDERS,
        "share_time": share_t,
        "share_asks": share_n,
        "ceiling": {
            "time": {"at_builders": amdahl(share_t, BUILDERS), "at_infinity": amdahl(share_t, None)},
            "asks": {"at_builders": amdahl(share_n, BUILDERS), "at_infinity": amdahl(share_n, None)},
        },
    }
    return out


#: The nodes whose job is to write a file. `engineer_selfverify` may write only the module just built.
WRITERS = ("engineer_build", "fix_pass")
SELFVERIFY = "engineer_selfverify"


def writes(rows: Sequence[dict], workdir: Path) -> List[dict]:
    """Every file under `workdir/site/`, the ask it was written in, and whether that was allowed."""
    site = workdir / "site"
    files = sorted(p for p in site.rglob("*") if p.is_file()) if site.is_dir() else []
    out: List[dict] = []
    for path in files:
        when = path.stat().st_mtime
        name = path.relative_to(site).as_posix()
        hit = next((i for i, r in enumerate(rows) if r["start"] <= when <= r["end"]), None)
        entry = {"file": f"site/{name}", "mtime": when, "node": None, "ask": None, "flag": ""}
        if hit is None:
            entry["flag"] = "written outside every ask"
        else:
            node = rows[hit]["node"]
            entry.update(node=node, ask=hit + 1)
            if node == SELFVERIFY:
                # The module its own build visit just built: the latest engineer_build answer before it.
                built = next((r["result"].get("module") for r in reversed(rows[:hit])
                              if r["node"] == "engineer_build"), None)
                if not built or name != built:
                    entry["flag"] = f"selfverify wrote a file other than the module just built ({built or 'none'})"
            elif node not in WRITERS:
                entry["flag"] = f"written by {node}, which is not a build node"
        out.append(entry)
    return out


def render_writes(found: Sequence[dict]) -> str:
    if not found:
        return "writes: no file under site/"
    lines = ["", f"{'file':<22}{'node':<22}{'ask':>5}  mtime (UTC)", ]
    for w in found:
        stamp = datetime.fromtimestamp(w["mtime"], tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        lines.append(f"{w['file']:<22}{w['node'] or '-':<22}{('#' + str(w['ask'])) if w['ask'] else '-':>5}"
                     f"  {stamp}" + (f"   !! {w['flag']}" if w["flag"] else ""))
    bad = [w for w in found if w["flag"]]
    lines.append(f"writes: {len(found)} files, {len(bad)} flagged" if bad else
                 f"writes: {len(found)} files, all by a build node")
    return "\n".join(lines)


def render(m: dict) -> str:
    wall = m["wall_seconds"] or 1.0

    def line(label, seconds, tag=""):
        return f"{label:<21}{seconds:>7.2f}s  {seconds / wall * 100:>4.0f}%{tag}"

    lines = [
        f"first -> last turn   {m['wall_seconds']:.2f}s",
        line("inside asks", m["inside_asks_seconds"]),
        line("  module loop", m["module_loop_seconds"], "   <- everything concurrency can touch"),
        line("  everything else", m["everything_else_seconds"]),
        line("waiting for a person", m["waiting_for_person_seconds"],
             f"   {len(m['person_stops'])} stop(s)" if m["person_stops"] else ""),
        line("runner overhead", m["runner_overhead_seconds"]),
        "",
        f"nodes counted as the module loop (graph.module_cycle): {', '.join(m['loop_nodes'])}",
        f"modules built {m['modules_built']}   asks {m['asks_total']}   asks in the loop {m['asks_in_loop']}",
        "",
        f"{'node':<22}{'asks':>5}{'total s':>10}{'mean s':>9}",
    ]
    for node, n in m["per_node"].items():
        lines.append(f"{node:<22}{n['asks']:>5}{n['total']:>10.2f}{n['mean']:>9.2f}"
                     + ("  (loop)" if n["loop"] else ""))
    c = m["ceiling"]
    b = m["builders"]
    lines += [
        "",
        m["formula"],
        f"{'share s':<28}{'at ' + str(b) + ' builders':>16}{'at infinity':>13}",
        f"{'time share  ' + format(m['share_time'] * 100, '.0f') + '%':<28}"
        f"{c['time']['at_builders']:>15.2f}x{c['time']['at_infinity']:>12.2f}x",
        "            of working time = wall - waiting for a person",
        f"{'ask share   ' + format(m['share_asks'] * 100, '.0f') + '%':<28}"
        f"{c['asks']['at_builders']:>15.2f}x{c['asks']['at_infinity']:>12.2f}x",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workdir", type=Path, help="the directory drive.py ran in (or a store root)")
    ap.add_argument("--json", type=Path, default=None, metavar="OUT", help="also write the numbers as JSON")
    ap.add_argument("--drive-log", type=Path, default=None, metavar="FILE",
                    help="drive.py's output; its PERSON-ANSWERED lines time when a person answered")
    args = ap.parse_args(argv)
    workdir = args.workdir.resolve()
    turns = turns_of(open_store(workdir))
    answered = answered_in(args.drive_log.read_text(encoding="utf-8", errors="replace")) if args.drive_log else []
    m = measure(turns, graph.module_cycle(), answered)
    m["writes"] = writes(asks_of(turns), workdir)
    print(render(m))
    print(render_writes(m["writes"]))
    if args.json:
        args.json.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
