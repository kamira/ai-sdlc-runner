"""Measure a run from its own conversation record. (CHG-20261019-01, the way CHG-20260827-21 Task 6 did)

    python3 docs/measurements/CHG-20261019-01/measure.py WORKDIR [--json OUT]

WORKDIR is the directory `examples/weather-live/drive.py` ran in (`runner serve` wrote its store
under `WORKDIR/conv`); a store root given directly works too. Every number comes from the `ASK` and
`ANSWER` turns, read through the runner's own `conversations` backend, paired by `ask_id`. Which
nodes are "the module loop" is derived from the flow by `graph.module_cycle()`, not listed here.
Needs no network and writes nothing but the optional JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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


def measure(turns: Sequence[dict], loop_nodes: Sequence[str]) -> dict:
    rows = asks_of(turns)
    if not rows:
        raise SystemExit("the record holds no answered ask")
    wall = _when(turns[-1]["at"]) - _when(turns[0]["at"])
    loop = [r for r in rows if r["node"] in loop_nodes]
    inside = union_seconds([(r["start"], r["end"]) for r in rows])
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
    share_t = in_loop / wall if wall else 0.0
    share_n = len(loop) / len(rows)
    out = {
        "wall_seconds": wall,
        "inside_asks_seconds": inside,
        "module_loop_seconds": in_loop,
        "everything_else_seconds": inside - in_loop,
        "runner_overhead_seconds": wall - inside,
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


def render(m: dict) -> str:
    wall = m["wall_seconds"] or 1.0

    def line(label, seconds, tag=""):
        return f"{label:<21}{seconds:>7.2f}s  {seconds / wall * 100:>4.0f}%{tag}"

    lines = [
        f"first -> last turn   {m['wall_seconds']:.2f}s",
        line("inside asks", m["inside_asks_seconds"]),
        line("  module loop", m["module_loop_seconds"], "   <- everything concurrency can touch"),
        line("  everything else", m["everything_else_seconds"]),
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
        f"{'ask share   ' + format(m['share_asks'] * 100, '.0f') + '%':<28}"
        f"{c['asks']['at_builders']:>15.2f}x{c['asks']['at_infinity']:>12.2f}x",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workdir", type=Path, help="the directory drive.py ran in (or a store root)")
    ap.add_argument("--json", type=Path, default=None, metavar="OUT", help="also write the numbers as JSON")
    args = ap.parse_args(argv)
    m = measure(turns_of(open_store(args.workdir.resolve())), graph.module_cycle())
    print(render(m))
    if args.json:
        args.json.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
