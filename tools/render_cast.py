"""Turn a directory of casts into one page you can press play on.

    python3 tools/render_cast.py docs/recordings/chg-34 -o docs/recordings/chg-34.html

Self-contained: no fetch, no CDN, no player library. The events are embedded as JSON and the player
is forty lines of it at the bottom of the file, because a page that needs the network to replay a
local recording is not a recording you can keep.

## Idle is compressed, and says so

A real session spends most of its wall-clock waiting — a suite for two minutes, CI for six. Played
back at true speed that is a review nobody finishes; cut silently, it is a review that cannot tell a
slow failure from a fast one. So a gap longer than `IDLE_CAP` plays as `IDLE_CAP` and leaves a
marker naming the real duration. The time you see is honest about being compressed.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

#: A pause longer than this plays as this, with the real length shown. Two seconds is long enough to
#: read as a pause and short enough that forty of them are not forty minutes.
IDLE_CAP = 2.0

#: SGR codes worth keeping. Everything else in the escape space is dropped rather than guessed at:
#: cursor movement and screen clears mean nothing in a transcript that only ever appends.
_SGR = {
    "1": "b", "2": "dim", "3": "i", "4": "u",
    "30": "c0", "31": "c1", "32": "c2", "33": "c3",
    "34": "c4", "35": "c5", "36": "c6", "37": "c7",
    "90": "c8", "91": "c9", "92": "c10", "93": "c11",
    "94": "c12", "95": "c13", "96": "c14", "97": "c15",
}

_ESCAPE = re.compile(r"\x1b\[([0-9;]*)m|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]")


def _escape_html(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def ansi_to_html(text: str) -> str:
    """SGR colours to spans; every other escape dropped.

    Kept rather than stripped because `runner`'s refusals are the point of most of these recordings
    and it colours them — a review that reads a red halt as ordinary output is reading something
    other than what happened.
    """
    out, classes, pos = [], [], 0
    for match in _ESCAPE.finditer(text):
        out.append(_escape_html(text[pos:match.start()]))
        pos = match.end()
        if match.group(1) is None:
            continue                                   # not SGR: dropped
        codes = [c for c in match.group(1).split(";") if c != ""] or ["0"]
        for code in codes:
            if code == "0":
                out.append("</span>" * len(classes))
                classes = []
            elif code in _SGR:
                classes.append(_SGR[code])
                out.append(f'<span class="{_SGR[code]}">')
    out.append(_escape_html(text[pos:]))
    out.append("</span>" * len(classes))
    return "".join(out)


def load(cast_dir: Path):
    """Read the casts in name order, compress idle, and lay them on one timeline."""
    steps, clock = [], 0.0
    previous_end_wall = None

    for path in sorted(cast_dir.glob("*.cast")):
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            continue
        header = json.loads(lines[0])
        raw = [json.loads(ln) for ln in lines[1:]]

        # The gap *between* commands is real time too — the minutes spent reading, deciding, waiting
        # for a review. Recorded as a marker rather than dropped, because a session that looks
        # continuous when it took two hours is a misleading recording.
        between = None
        if previous_end_wall is not None:
            gap = header["timestamp"] - previous_end_wall
            if gap > IDLE_CAP:
                between = gap
                clock += IDLE_CAP
        previous_end_wall = header["timestamp"] + header.get("duration", 0)

        events, last, skipped = [], 0.0, []
        for at, _kind, data in raw:
            delta = at - last
            if delta > IDLE_CAP:
                skipped.append((round(clock, 3), round(delta, 1)))
                clock += IDLE_CAP
            else:
                clock += delta
            last = at
            events.append([round(clock, 3), ansi_to_html(data)])

        steps.append({
            "title": header.get("title") or " ".join(header.get("command", [])),
            "command": " ".join(header.get("command", [])),
            "note": header.get("note", ""),
            "exit": header.get("exit_code"),
            "real": round(header.get("duration", 0), 1),
            "start": round(events[0][0] if events else clock, 3),
            "end": round(clock, 3),
            "waited": between,
            "pauses": skipped,
            "events": events,
        })

    return steps


def render(steps, title):
    total = steps[-1]["end"] if steps else 0
    real = sum(s["real"] for s in steps) + sum(s["waited"] or 0 for s in steps)
    failed = [s for s in steps if s["exit"] not in (0, None)]
    return _PAGE.replace("__TITLE__", _escape_html(title)) \
                .replace("__STEPS__", json.dumps(steps, ensure_ascii=False)) \
                .replace("__TOTAL__", f"{total:.1f}") \
                .replace("__REAL__", f"{real / 60:.1f}") \
                .replace("__COUNT__", str(len(steps))) \
                .replace("__FAILED__", str(len(failed)))


def main():
    parser = argparse.ArgumentParser(description="Render recorded casts as a playable page.")
    parser.add_argument("cast_dir", help="directory of .cast files")
    parser.add_argument("-o", "--out", required=True, help="the HTML file to write")
    parser.add_argument("--title", help="what this session was")
    args = parser.parse_args()

    cast_dir = Path(args.cast_dir)
    steps = load(cast_dir)
    if not steps:
        raise SystemExit(f"no .cast files in {cast_dir}")

    page = render(steps, args.title or cast_dir.name)
    Path(args.out).write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {args.out} — {len(steps)} steps, {steps[-1]['end']:.0f}s of playback")


_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{--ink:#16191f;--ground:#f6f5f2;--panel:#fff;--rule:#e0dcd4;--rule2:#c4bdb1;
--accent:#1d6a8c;--warn:#a2542c;--muted:#6b6f76;
--term-bg:#12161b;--term-ink:#d6dde4;--term-dim:#7d8794}
:root:not([data-theme="light"]){}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--ink:#e7e5e0;--ground:#12151a;
--panel:#191d23;--rule:#282d35;--rule2:#3b414a;--accent:#5aa8c9;--warn:#d99a63;--muted:#949aa2}}
:root[data-theme="dark"]{--ink:#e7e5e0;--ground:#12151a;--panel:#191d23;--rule:#282d35;
--rule2:#3b414a;--accent:#5aa8c9;--warn:#d99a63;--muted:#949aa2}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font:15px/1.6 "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif}
.wrap{max-width:78rem;margin:0 auto;padding:2rem 1.25rem 4rem}
header.top{border-bottom:2px solid var(--ink);padding-bottom:1rem;margin-bottom:1.5rem}
h1{margin:0;font-size:1.6rem;letter-spacing:-.02em}
.stats{margin:.45rem 0 0;font-family:"IBM Plex Mono",monospace;font-size:.75rem;color:var(--muted)}
.stats b{color:var(--ink)}
.layout{display:grid;grid-template-columns:17rem 1fr;gap:1.25rem;align-items:start}
ol.steps{list-style:none;margin:0;padding:0;max-height:34rem;overflow-y:auto;
border:1px solid var(--rule);border-radius:8px;background:var(--panel)}
ol.steps li{border-bottom:1px solid var(--rule)}
ol.steps li:last-child{border-bottom:none}
ol.steps button{width:100%;text-align:left;background:none;border:0;cursor:pointer;color:inherit;
padding:.55rem .75rem;font:inherit;display:block;border-left:3px solid transparent}
ol.steps button:hover{background:var(--ground)}
ol.steps li.on button{border-left-color:var(--accent);background:var(--ground)}
ol.steps li.bad button{border-left-color:var(--warn)}
.st{font-family:"IBM Plex Mono",monospace;font-size:.7rem;color:var(--muted);
display:flex;gap:.4rem;align-items:baseline}
.st .n{color:var(--rule2)}
.sl{font-size:.82rem;margin-top:.1rem;word-break:break-word}
.term{background:var(--term-bg);border-radius:8px;padding:1rem 1.1rem;min-height:26rem;
max-height:34rem;overflow:auto;border:1px solid var(--rule)}
.term pre{margin:0;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.76rem;
line-height:1.55;color:var(--term-ink);white-space:pre-wrap;word-break:break-word}
.cmd{color:#7fd1a8}.cmd::before{content:"$ ";color:var(--term-dim)}
.pause{color:var(--term-dim);font-style:italic}
.b{font-weight:600}.dim{opacity:.65}.i{font-style:italic}.u{text-decoration:underline}
.c1,.c9{color:#e08a7a}.c2,.c10{color:#8fcf9b}.c3,.c11{color:#d9bb72}.c4,.c12{color:#7fb4d6}
.c5,.c13{color:#c39ad4}.c6,.c14{color:#78c6c6}.c0,.c8{color:#8a939c}.c7,.c15{color:#e4e9ee}
.bar{display:flex;align-items:center;gap:.7rem;margin-top:.8rem}
button.play{background:var(--accent);color:#fff;border:0;border-radius:6px;cursor:pointer;
padding:.45rem .95rem;font:600 .82rem/1 "IBM Plex Sans",sans-serif;min-width:5rem}
input[type=range]{flex:1;accent-color:var(--accent)}
.time{font-family:"IBM Plex Mono",monospace;font-size:.74rem;color:var(--muted);
font-variant-numeric:tabular-nums;min-width:6.5rem;text-align:right}
select{background:var(--panel);color:var(--ink);border:1px solid var(--rule);border-radius:6px;
padding:.35rem .4rem;font:.76rem "IBM Plex Mono",monospace}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:820px){.layout{grid-template-columns:1fr}ol.steps{max-height:14rem}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style></head><body>
<div class="wrap">
<header class="top">
  <h1>__TITLE__</h1>
  <p class="stats"><b>__COUNT__</b> steps · <b>__FAILED__</b> non-zero exits ·
     <b>__TOTAL__</b>s of playback from <b>__REAL__</b> min of real time
     <span class="dim">(pauses over 2s are compressed and marked)</span></p>
</header>
<div class="layout">
  <ol class="steps" id="steps"></ol>
  <div>
    <div class="term" id="term"><pre id="out"></pre></div>
    <div class="bar">
      <button class="play" id="play">Play</button>
      <input type="range" id="scrub" min="0" max="__TOTAL__" step="0.05" value="0">
      <select id="speed">
        <option value="1">1x</option><option value="2">2x</option>
        <option value="4">4x</option><option value="8">8x</option>
      </select>
      <span class="time" id="time">0.0 / __TOTAL__s</span>
    </div>
  </div>
</div>
</div>
<script>
const STEPS = __STEPS__;
const TOTAL = parseFloat("__TOTAL__");
const out = document.getElementById('out'), list = document.getElementById('steps');
const scrub = document.getElementById('scrub'), playBtn = document.getElementById('play');
const timeLabel = document.getElementById('time'), speed = document.getElementById('speed');
const term = document.getElementById('term');
let clock = 0, playing = false, last = null, current = -1;

STEPS.forEach((s, i) => {
  const li = document.createElement('li');
  if (s.exit !== 0 && s.exit !== null) li.className = 'bad';
  const b = document.createElement('button');
  b.innerHTML = '<span class="st"><span class="n">' + String(i).padStart(2, '0') + '</span>' +
    '<span>' + s.real + 's</span>' + (s.exit ? '<span class="c1">exit ' + s.exit + '</span>' : '') +
    '</span><span class="sl">' + s.title.replace(/[&<>]/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])) + '</span>';
  b.onclick = () => { seek(s.start); };
  li.appendChild(b); list.appendChild(li);
});

function stepAt(t) {
  let n = 0;
  for (let i = 0; i < STEPS.length; i++) if (STEPS[i].start <= t) n = i;
  return n;
}

function draw() {
  const n = stepAt(clock), s = STEPS[n];
  const html = [];
  if (s.waited) html.push('<span class="pause">-- ' + fmt(s.waited) + ' between steps --</span>\n');
  html.push('<span class="cmd">' + s.command.replace(/[&<>]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])) + '</span>\n');
  if (s.note) html.push('<span class="pause">' + s.note + '</span>\n');
  let pauseIdx = 0;
  for (const [at, data] of s.events) {
    if (at > clock) break;
    while (pauseIdx < s.pauses.length && s.pauses[pauseIdx][0] <= at) {
      html.push('<span class="pause">-- waited ' + fmt(s.pauses[pauseIdx][1]) + ' --</span>\n');
      pauseIdx++;
    }
    html.push(data);
  }
  if (n !== current) {
    current = n;
    [...list.children].forEach((li, i) => li.classList.toggle('on', i === n));
    list.children[n].scrollIntoView({block: 'nearest'});
  }
  out.innerHTML = html.join('');
  term.scrollTop = term.scrollHeight;
  timeLabel.textContent = clock.toFixed(1) + ' / ' + TOTAL + 's';
  scrub.value = clock;
}

function fmt(sec) {
  return sec >= 60 ? (sec / 60).toFixed(1) + ' min' : Math.round(sec) + 's';
}

function seek(t) { clock = Math.max(0, Math.min(TOTAL, t)); current = -1; draw(); }

function tick(now) {
  if (!playing) return;
  if (last !== null) clock += ((now - last) / 1000) * parseFloat(speed.value);
  last = now;
  if (clock >= TOTAL) { clock = TOTAL; stop(); }
  draw();
  if (playing) requestAnimationFrame(tick);
}

function stop() { playing = false; last = null; playBtn.textContent = 'Play'; }

playBtn.onclick = () => {
  if (playing) { stop(); return; }
  if (clock >= TOTAL) clock = 0;
  playing = true; playBtn.textContent = 'Pause'; last = null;
  requestAnimationFrame(tick);
};
scrub.oninput = () => { stop(); seek(parseFloat(scrub.value)); };
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.key === ' ') { e.preventDefault(); playBtn.click(); }
  if (e.key === 'ArrowRight') { stop(); seek(clock + 5); }
  if (e.key === 'ArrowLeft') { stop(); seek(clock - 5); }
});
draw();
</script>
</body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
