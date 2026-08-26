"""The agent the runner dispatches to, for the local week-ahead weather project.

One process per ask: work order on stdin, JSON on stdout. It writes one module per
`engineer_build` visit, and the files it writes are the files the browser loads.

The forecast is generated, not fetched. The whole operating flow is local-only and this page makes
no network request — so it says so in its own footer rather than implying a live feed.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "site"

MODULES = {
    "markup": ("index.html", """<!doctype html>
<html lang="zh-Hant"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>\u4e00\u9031\u6c23\u8c61 \u00b7 Taipei</title><link rel="stylesheet" href="styles.css">
</head><body>
  <header>
    <p class="eyebrow">25.0330&deg;N 121.5654&deg;E &middot; \u81fa\u5317</p>
    <h1>\u4e00\u9031\u6c23\u8c61</h1>
    <p class="sub" id="today"></p>
  </header>
  <main>
    <section class="days" aria-label="week ahead">
      <ol class="week" id="week-before"></ol>
    </section>

    <!-- The middle band: what it is doing right now. -->
    <section class="now" id="now" aria-live="polite">
      <div class="now-main">
        <div class="glyph" id="now-glyph" aria-hidden="true"></div>
        <div>
          <p class="now-label">\u73fe\u5728</p>
          <p class="now-temp" id="now-temp"></p>
          <p class="now-sky" id="now-sky"></p>
        </div>
      </div>
      <dl class="now-facts" id="now-facts"></dl>
    </section>

    <section class="days" aria-label="rest of the week">
      <ol class="week" id="week-after"></ol>
    </section>

    <section>
      <h2>\u4eca\u65e5\u6eab\u5ea6\u8b8a\u5316</h2>
      <div class="chartwrap"><canvas id="chart" width="720" height="180"></canvas></div>
    </section>
  </main>
  <footer>Built by ai-sdlc-runner. \u9810\u5831\u70ba\u793a\u7bc4\u66f2\u7dda\uff0c\u4e26\u975e\
\u5be6\u6e2c\u8cc7\u6599 &mdash; this page makes no network request.</footer>
<script src="weather.js"></script><script src="app.js"></script></body></html>
"""),
    "styles": ("styles.css", """:root{--ink:#12181d;--ground:#f4f7f9;--panel:#fff;--rule:#dde5ea;
--sky:#2b6f9e;--sky-soft:#e4eff6;--sun:#c8862a;--rain:#4a7fa8;--muted:#5f6d78;--warm:#b3552f}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font:15px/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI","Noto Sans TC",sans-serif}
header,main,footer{max-width:47rem;margin:0 auto;padding:0 1.25rem}
header{padding-top:2.5rem;padding-bottom:1.25rem;border-bottom:2px solid var(--ink)}
.eyebrow{margin:0;font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h1{margin:.2rem 0 .1rem;font-size:2.4rem;letter-spacing:-.02em}
.sub{margin:0;color:var(--muted)}
main{padding-top:1.75rem;display:flex;flex-direction:column;gap:1.4rem}
h2{font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0 0 .7rem}

.week{list-style:none;display:grid;grid-template-columns:repeat(auto-fit,minmax(5.4rem,1fr));
gap:.5rem;margin:0;padding:0}
.week li{background:var(--panel);border:1px solid var(--rule);border-radius:9px;padding:.7rem .5rem;
text-align:center}
.week .d{font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.week .g{font-size:1.5rem;line-height:1.2;margin:.2rem 0}
.week .hi{font-weight:700;font-variant-numeric:tabular-nums}
.week .lo{color:var(--muted);font-variant-numeric:tabular-nums}
.week .pop{display:block;font-size:.7rem;color:var(--rain);font-variant-numeric:tabular-nums}

/* the middle band */
.now{background:var(--sky);color:#fff;border-radius:12px;padding:1.15rem 1.35rem;
display:flex;gap:1.4rem;flex-wrap:wrap;align-items:center;justify-content:space-between}
.now-main{display:flex;align-items:center;gap:1rem}
.now .glyph{font-size:3.1rem;line-height:1}
.now-label{margin:0;font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;opacity:.8}
.now-temp{margin:.05rem 0;font-size:2.5rem;line-height:1;font-weight:700;
font-variant-numeric:tabular-nums}
.now-sky{margin:0;opacity:.9;font-size:.95rem}
.now-facts{margin:0;display:grid;grid-template-columns:repeat(3,auto);gap:.15rem 1.5rem}
.now-facts dt{font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;opacity:.75}
.now-facts dd{margin:0 0 .45rem;font-size:1.15rem;font-weight:600;
font-variant-numeric:tabular-nums}
.chartwrap{border:1px solid var(--rule);border-radius:10px;background:var(--panel);
padding:.75rem;overflow-x:auto}
canvas{display:block;width:100%;height:180px}
footer{padding:2rem 1.25rem 3rem;color:var(--muted);font-size:.8rem}
@media (prefers-color-scheme:dark){:root{--ink:#e8eef2;--ground:#0f1418;--panel:#171f25;
--rule:#26323a;--sky:#2f7ba8;--sky-soft:#16242d;--muted:#93a3ae}}
"""),
    "weather": ("weather.js", """// The model: a deterministic week, so the page is the same every time it is opened.
const DAYS = ['\\u9031\\u65e5','\\u9031\\u4e00','\\u9031\\u4e8c','\\u9031\\u4e09','\\u9031\\u56db',
              '\\u9031\\u4e94','\\u9031\\u516d'];
const SKIES = [
  { key: 'sun',   glyph: '\\u2600\\ufe0f', text: '\\u6674' },
  { key: 'part',  glyph: '\\u26c5',        text: '\\u591a\\u96f2' },
  { key: 'cloud', glyph: '\\u2601\\ufe0f', text: '\\u9670' },
  // A surrogate pair, not '\\u1f327': a JavaScript \\u escape takes exactly four hex digits, so
  // that spelling parsed as '\\u1f32' followed by a literal '7' and rendered as broken glyph text.
  { key: 'rain',  glyph: '\\ud83c\\udf27\\ufe0f', text: '\\u9663\\u96e8' },
];

// A fixed seed: a forecast that changed on every reload would be a random number generator
// wearing a weather page.
function noise(n) {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

function week(startDay) {
  const out = [];
  for (let i = 0; i < 7; i++) {
    const r = noise(i + 1), r2 = noise(i + 40);
    const hi = Math.round(24 + r * 8);
    const lo = Math.round(hi - 4 - r2 * 4);
    const sky = SKIES[Math.floor(r2 * SKIES.length)];
    out.push({
      day: DAYS[(startDay + i) % 7],
      hi, lo, sky,
      pop: Math.round((sky.key === 'rain' ? 45 + r * 45 : r * 30)),
    });
  }
  return out;
}

// Now: temperature follows the day's arc between the low (just before dawn) and the high (mid
// afternoon); humidity moves the other way, which is why both are shown rather than one.
function currently(minutes, today) {
  const phase = Math.cos(((minutes - 15 * 60) / (24 * 60)) * 2 * Math.PI);
  const temp = today.lo + (today.hi - today.lo) * (phase * 0.5 + 0.5);
  const humidity = Math.round(92 - (temp - today.lo) / Math.max(1, today.hi - today.lo) * 34);
  const feels = temp + (humidity > 75 ? (temp - 24) * 0.18 : 0);
  return {
    temp: Math.round(temp * 10) / 10,
    humidity,
    feels: Math.round(feels * 10) / 10,
    sky: today.sky,
    wind: Math.round(6 + noise(minutes) * 12),
  };
}

window.Weather = { week, currently, DAYS, SKIES };
"""),
    "app": ("app.js", """// The view: a week either side of the current conditions, and today's temperature curve.
(function () {
  const { week, currently } = window.Weather;
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const days = week(now.getDay());
  const today = days[0];
  const here = currently(minutes, today);

  document.getElementById('today').textContent =
    now.toLocaleDateString('zh-TW', { month: 'long', day: 'numeric', weekday: 'long' });

  function card(d, i) {
    const li = document.createElement('li');
    li.innerHTML = '<div class="d">' + (i === 0 ? '\\u4eca\\u5929' : d.day) + '</div>' +
      '<div class="g">' + d.sky.glyph + '</div>' +
      '<div><span class="hi">' + d.hi + '\\u00b0</span> ' +
      '<span class="lo">' + d.lo + '\\u00b0</span></div>' +
      '<span class="pop">' + d.pop + '%</span>';
    return li;
  }

  const before = document.getElementById('week-before');
  const after = document.getElementById('week-after');
  days.slice(0, 3).forEach((d, i) => before.appendChild(card(d, i)));
  days.slice(3).forEach((d, i) => after.appendChild(card(d, i + 3)));

  document.getElementById('now-glyph').textContent = here.sky.glyph;
  document.getElementById('now-temp').textContent = here.temp.toFixed(1) + '\\u00b0C';
  document.getElementById('now-sky').textContent = here.sky.text;
  document.getElementById('now-facts').innerHTML = [
    ['\\u6fd5\\u5ea6', here.humidity + '%'],
    ['\\u9ad4\\u611f', here.feels.toFixed(1) + '\\u00b0'],
    ['\\u98a8\\u901f', here.wind + ' km/h'],
  ].map(([k, v]) => '<dt>' + k + '</dt><dd>' + v + '</dd>').join('');

  const c = document.getElementById('chart'), g = c.getContext('2d');
  const w = c.width, h = c.height;
  const lo = today.lo - 2, hi = today.hi + 2;
  const y = v => h - 16 - ((v - lo) / (hi - lo)) * (h - 34);
  g.clearRect(0, 0, w, h);
  g.strokeStyle = 'rgba(128,150,165,.3)';
  for (let t = Math.ceil(lo / 5) * 5; t <= hi; t += 5) {
    const gy = y(t);
    g.beginPath(); g.moveTo(0, gy); g.lineTo(w, gy); g.stroke();
  }
  const at = m => currently(m, today).temp;
  g.beginPath();
  for (let m = 0; m <= 1440; m += 10) {
    const px = (m / 1440) * w, py = y(at(m));
    m ? g.lineTo(px, py) : g.moveTo(px, py);
  }
  g.lineTo(w, h); g.lineTo(0, h); g.closePath();
  g.fillStyle = 'rgba(43,111,158,.15)'; g.fill();
  g.beginPath();
  for (let m = 0; m <= 1440; m += 10) {
    const px = (m / 1440) * w, py = y(at(m));
    m ? g.lineTo(px, py) : g.moveTo(px, py);
  }
  g.strokeStyle = '#2b6f9e'; g.lineWidth = 2; g.stroke();
  g.fillStyle = getComputedStyle(document.body).color;
  g.beginPath();
  g.arc((minutes / 1440) * w, y(here.temp), 4.5, 0, Math.PI * 2);
  g.fill();
})();
"""),
}

ORDER = ["markup", "styles", "weather", "app"]


def main():
    order = json.loads(sys.stdin.read())
    node = order["node_id"]
    seat = order.get("seat")

    if node == "intake_review":
        print(json.dumps({"missing": [], "problems": [], "unsafe": []}))
        return
    if seat:
        text = str(order.get("instructions") or "")
        print(json.dumps({
            "verdict": "pass",
            "why": f"{seat}: read the brief ({len(text)} chars of instruction) and the module",
        }))
        return
    if node == "pm_plan":
        print(json.dumps({"modules": ORDER}))
        return
    if node == "engineer_build":
        OUT.mkdir(parents=True, exist_ok=True)
        # Compare content, do not count files. The first version picked "the next module whose file
        # does not exist" — so once all four existed, a re-walk had nothing left to advance to,
        # rewrote the last one forever, and `next_module: frontier` never moved. The runner cut it
        # off with "walk exceeded 200 steps — the flow is cycling without progress", which is
        # exactly the right complaint about exactly this bug.
        for key in ORDER:
            name, body = MODULES[key]
            path = OUT / name
            if path.exists() and path.read_text(encoding="utf-8") == body:
                continue
            path.write_text(body, encoding="utf-8")
            print(json.dumps({"module": key, "wrote": name}))
            return
        print(json.dumps({"module": "", "wrote": "",
                          "note": "every module already matches the brief"}))
        return

    branches = {
        "pm_confirm": "yes", "pm_signoff": "yes", "next_module": "module",
        "lead_task_review": "pass", "re_review": "pass", "lead_review": "pass",
        "qa_accept": "pass", "feedback": "done",
    }
    print(json.dumps({"verdict": branches.get(node, "pass"), "note": f"{node} ok"}))


main()
