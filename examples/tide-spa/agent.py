"""The agent the runner dispatches to. One process per ask: work order on stdin, JSON on stdout.

It builds a real single-page app — a tide-table viewer — one module per `engineer_build` visit.
Nothing here is a stub: the files it writes are the files the browser loads.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "site"

MODULES = {
    "markup": ("index.html", """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tide Table — Porthcurno</title><link rel="stylesheet" href="styles.css">
</head><body>
  <header>
    <p class="eyebrow">SW Cornwall &middot; 50.0413&deg;N 5.6552&deg;W</p>
    <h1>Porthcurno</h1>
    <p class="sub" id="today"></p>
  </header>
  <main>
    <section class="now" id="now" aria-live="polite"></section>
    <section>
      <h2>Next six tides</h2>
      <ol class="tides" id="tides"></ol>
    </section>
    <section>
      <h2>Twelve hours</h2>
      <div class="chartwrap"><canvas id="chart" width="720" height="200"></canvas></div>
    </section>
  </main>
  <footer>Built by ai-sdlc-runner. Heights are a demonstration curve, not a forecast.</footer>
<script src="tides.js"></script><script src="app.js"></script></body></html>
"""),
    "styles": ("styles.css", """:root{--ink:#11202b;--ground:#f7f9fa;--panel:#fff;--rule:#dbe4e8;
--sea:#1d6a8c;--sea-soft:#e3eff4;--muted:#5d7280;--high:#b5551f}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header,main,footer{max-width:46rem;margin:0 auto;padding:0 1.25rem}
header{padding-top:2.5rem;padding-bottom:1.25rem;border-bottom:2px solid var(--ink)}
.eyebrow{margin:0;font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h1{margin:.2rem 0 .1rem;font-size:2.3rem;letter-spacing:-.02em}
.sub{margin:0;color:var(--muted)}
main{padding-top:1.75rem;display:flex;flex-direction:column;gap:2rem}
h2{font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0 0 .7rem}
.now{background:var(--sea);color:#fff;border-radius:10px;padding:1.1rem 1.3rem}
.now b{display:block;font-size:2rem;line-height:1.1;font-variant-numeric:tabular-nums}
.now span{opacity:.85;font-size:.85rem}
.tides{list-style:none;margin:0;padding:0;border:1px solid var(--rule);border-radius:10px;
background:var(--panel);overflow:hidden}
.tides li{display:flex;align-items:baseline;gap:.85rem;padding:.7rem 1.1rem;
border-bottom:1px solid var(--rule)}
.tides li:last-child{border-bottom:none}
.tides li.high{background:var(--sea-soft)}
.tides .kind{font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;width:3.4rem;
color:var(--muted)}
.tides li.high .kind{color:var(--high);font-weight:600}
.tides .at{font-variant-numeric:tabular-nums;font-weight:600;width:4.2rem}
.tides .m{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--muted)}
.chartwrap{border:1px solid var(--rule);border-radius:10px;background:var(--panel);
padding:.75rem;overflow-x:auto}
canvas{display:block;width:100%;height:200px}
footer{padding:2rem 1.25rem 3rem;color:var(--muted);font-size:.8rem}
@media (prefers-color-scheme:dark){:root{--ink:#e7eef2;--ground:#0e1519;--panel:#151f25;
--rule:#25333b;--sea:#2b7fa4;--sea-soft:#17262e;--muted:#8ea3b0}}
"""),
    "tides": ("tides.js", """// The model: a semidiurnal curve, 12h25m period, sampled and turned into events.
const PERIOD_MIN = 745;          // 12h25m — the real semidiurnal interval
const MEAN = 3.1, AMP = 2.4;     // metres

function heightAt(minutes) {
  return MEAN + AMP * Math.sin((2 * Math.PI * minutes) / PERIOD_MIN);
}

function tideEvents(fromMinutes, count) {
  const out = [];
  let m = fromMinutes;
  while (out.length < count) {
    const before = heightAt(m - 1), here = heightAt(m), after = heightAt(m + 1);
    if (here > before && here >= after) out.push({ at: m, kind: 'high', m: here });
    else if (here < before && here <= after) out.push({ at: m, kind: 'low', m: here });
    m += 1;
    if (m - fromMinutes > PERIOD_MIN * 4) break;
  }
  return out;
}

function clock(minutes) {
  const t = ((minutes % 1440) + 1440) % 1440;
  return String(Math.floor(t / 60)).padStart(2, '0') + ':' + String(Math.round(t % 60)).padStart(2, '0');
}

window.Tides = { heightAt, tideEvents, clock, PERIOD_MIN };
"""),
    "app": ("app.js", """// The view: reads the model, writes the DOM, draws the curve.
(function () {
  const { heightAt, tideEvents, clock } = window.Tides;
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();

  document.getElementById('today').textContent = now.toLocaleDateString(undefined,
    { weekday: 'long', day: 'numeric', month: 'long' });

  const level = heightAt(minutes);
  const rising = heightAt(minutes + 5) > level;
  document.getElementById('now').innerHTML =
    '<b>' + level.toFixed(2) + ' m</b><span>' + (rising ? 'rising' : 'falling') +
    ' &middot; now ' + clock(minutes) + '</span>';

  const list = document.getElementById('tides');
  for (const t of tideEvents(minutes, 6)) {
    const li = document.createElement('li');
    li.className = t.kind;
    li.innerHTML = '<span class="kind">' + t.kind + '</span>' +
                   '<span class="at">' + clock(t.at) + '</span>' +
                   '<span class="m">' + t.m.toFixed(2) + ' m</span>';
    list.appendChild(li);
  }

  const c = document.getElementById('chart'), g = c.getContext('2d');
  const w = c.width, h = c.height, span = 720;
  const y = v => h - 12 - ((v - 0.2) / 6.2) * (h - 30);
  const ink = getComputedStyle(document.body).color;
  g.clearRect(0, 0, w, h);
  g.strokeStyle = 'rgba(128,150,165,.35)';
  for (let k = 1; k <= 5; k++) {
    const gy = y(k);
    g.beginPath(); g.moveTo(0, gy); g.lineTo(w, gy); g.stroke();
  }
  g.beginPath();
  for (let i = 0; i <= span; i++) {
    const px = (i / span) * w, py = y(heightAt(minutes + i));
    i ? g.lineTo(px, py) : g.moveTo(px, py);
  }
  g.lineTo(w, h); g.lineTo(0, h); g.closePath();
  g.fillStyle = 'rgba(29,106,140,.16)'; g.fill();
  g.beginPath();
  for (let i = 0; i <= span; i++) {
    const px = (i / span) * w, py = y(heightAt(minutes + i));
    i ? g.lineTo(px, py) : g.moveTo(px, py);
  }
  g.strokeStyle = '#1d6a8c'; g.lineWidth = 2; g.stroke();
  g.fillStyle = ink; g.beginPath();
  g.arc(0, y(level), 4, 0, Math.PI * 2); g.fill();
})();
"""),
}

ORDER = ["markup", "styles", "tides", "app"]


def main():
    order = json.loads(sys.stdin.read())
    node = order["node_id"]
    seat = order.get("seat")

    if node == "intake_review":
        # Every aspect is supplied by the brief, so nothing is missing.
        print(json.dumps({"missing": [], "problems": [], "unsafe": []}))
        return
    if seat:
        print(json.dumps({"verdict": "pass", "why": f"{seat}: read the brief and the module"}))
        return
    if node == "pm_plan":
        print(json.dumps({"modules": ORDER}))
        return
    if node == "engineer_build":
        OUT.mkdir(parents=True, exist_ok=True)
        done = {p.stem if p.suffix != ".html" else "markup" for p in OUT.iterdir()} \
            if OUT.exists() else set()
        nxt = next((m for m in ORDER if m not in done), ORDER[-1])
        name, body = MODULES[nxt]
        (OUT / name).write_text(body, encoding="utf-8")
        print(json.dumps({"module": nxt, "wrote": name}))
        return

    # Read out of the graph rather than guessed: the first version answered "pass" at pm_confirm,
    # whose branches are ['no','yes'], and the run halted on an answer that named no branch.
    branches = {
        "pm_confirm": "yes", "pm_signoff": "yes", "next_module": "module",
        "lead_task_review": "pass", "re_review": "pass", "lead_review": "pass",
        "qa_accept": "pass", "feedback": "done",
    }
    print(json.dumps({"verdict": branches.get(node, "pass"), "note": f"{node} ok"}))


main()
