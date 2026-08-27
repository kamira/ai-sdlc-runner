"""Generate the demo pages **from the agents that build them**.

    python3 examples/demo/build.py

Each page is what the example's own `agent.py` writes, inlined into one file. Generated rather than
kept by hand for one reason: a demo page copied once is a screenshot with a `.html` extension, and
it goes stale the first time the agent changes without anybody noticing. `tests/test_demo_pages.py`
regenerates and compares, so a stale page fails the suite.

The pages are self-contained — the CSS and both scripts inlined — because a demo you cannot open by
double-clicking is not much of a demo.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent
REPO = EXAMPLES.parent
sys.path.insert(0, str(REPO / "src"))

#: Each demo: which example builds it, and what the page is.
DEMOS = [
    {
        "slug": "tide",
        "example": "tide-spa",
        "title": "Porthcurno Tide Table",
        "blurb": "Four modules from four visits to one node. The curve is a demonstration "
                 "shape, not a forecast — the page says so itself.",
        "entry": "index.html",
        "scripts": ("tides.js", "app.js"),
    },
    {
        "slug": "weather",
        "example": "weather-spa",
        "title": "一週氣象 · Taipei",
        "blurb": "Built through the console: a brief typed by a person, a gate approved by "
                 "clicking. Seven days, current conditions in the middle, and no network call.",
        "entry": "index.html",
        "scripts": ("weather.js", "app.js"),
    },
]


def build_site(example: str, into: Path) -> Path:
    """Run the example's agent until it says every module is written, and return the site dir."""
    agent = EXAMPLES / example / "agent.py"
    work = into / example
    work.mkdir(parents=True, exist_ok=True)
    (work / "agent.py").write_text(agent.read_text(encoding="utf-8"), encoding="utf-8")

    order = json.dumps({"node_id": "engineer_build", "seat": None})
    for _ in range(12):
        done = subprocess.run([sys.executable, str(work / "agent.py")], input=order,
                              capture_output=True, encoding="utf-8", errors="replace",
                              cwd=str(work))
        if done.returncode != 0:
            raise SystemExit(f"{example}: the agent failed\n{done.stdout}{done.stderr}")
        answer = json.loads(done.stdout)
        if not answer.get("module"):
            break                       # every module already matches the brief
    else:
        raise SystemExit(f"{example}: the agent never reported itself finished — it is "
                         f"probably picking the next module by which file is missing")
    return work / "site"


def inline(site: Path, entry: str, scripts) -> str:
    """One file: the stylesheet and every script folded in where they were linked."""
    page = (site / entry).read_text(encoding="utf-8")
    page = page.replace('<link rel="stylesheet" href="styles.css">',
                        "<style>\n" + (site / "styles.css").read_text(encoding="utf-8") + "\n</style>")
    tags = "".join(f'<script src="{name}"></script>' for name in scripts)
    folded = "\n".join(
        "<script>\n" + (site / name).read_text(encoding="utf-8") + "\n</script>" for name in scripts)
    if tags not in page:
        raise SystemExit(f"{entry}: expected {tags!r} and did not find it")
    page = page.replace(tags, folded)
    for leftover in ('href="styles.css"', *(f'src="{n}"' for n in scripts)):
        if leftover in page:
            raise SystemExit(f"{entry}: {leftover} survived inlining")
    return page


#: The conversation the recording demo replays. A committed fixture, not a fresh run: a recording
#: carries wall-clock timestamps, so a page regenerated on every build could never be byte-compared
#: against the committed one. `make_fixture.py` refreshes it from a real console-driven run.
RECORDING = {
    "slug": "recording",
    "title": "A run, replayed",
    "blurb": "The console-driven weather run as something you press play on — what a person typed, "
             "what the model answered, and where the walk stopped for an approval.",
    "from": "examples/weather-spa",
}


def recording_page() -> str:
    """`runner export --format playback`, called directly.

    Rendered by the shipped exporter rather than by anything local to this directory, so the demo
    is a demonstration *of the feature* — if `playback` breaks, this page breaks with it.
    """
    from ai_sdlc_runner import conversations as conv

    store = HERE / "conversations"
    if not store.exists():
        raise SystemExit("no conversation fixture; run `python3 examples/demo/make_fixture.py`")

    # The fixture stays JSONL and the page is rendered from **SQLite**, by importing it into a
    # throwaway database first (CHG-20260823-41). Two reasons, and both are about review:
    #
    #   * a committed fixture has to be readable in a diff, and a `.sqlite` file is not;
    #   * the import path is the migration every existing store has to take, so running it on every
    #     build is the cheapest possible test of it.
    #
    # If the importer ever stops being lossless, this page changes and the byte-compare fails.
    with tempfile.TemporaryDirectory(prefix="demo-db-") as tmp:
        into = conv.backend("sqlite", root=Path(tmp))
        report = conv.import_file_store(store, into)
        if len(report["imported"]) != 1:
            raise SystemExit(
                f"expected exactly one conversation in the fixture, imported {report['imported']}")
        entry = into.conversations()[0]
        document = into.read(entry["project"]["id"], entry["conversation_id"])
        page = conv.export_conversation(document, "playback")
        into.close()
    return page


def index_page(demos) -> str:
    entries = [{"slug": d["slug"], "title": d["title"], "blurb": d["blurb"],
                "from": f'examples/{d["example"]}'} for d in demos]
    entries.append({k: RECORDING[k] for k in ("slug", "title", "blurb", "from")})
    cards = "\n".join(
        f'''    <li class="card">
      <a href="{e["slug"]}.html">
        <h2>{e["title"]}</h2>
        <p>{e["blurb"]}</p>
        <span class="from">{e["from"]}</span>
      </a>
    </li>''' for e in entries)
    return _INDEX.replace("__CARDS__", cards)


_INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ai-sdlc-runner demos</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap">
<style>
:root{--ink:#141920;--bg:#EEF1F5;--surface:#fff;--line:#D6DCE4;--muted:#586170;--faint:#8A93A1;
--accent:#37567C}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--ink:#E3E8EF;--bg:#0E1117;
--surface:#171B22;--line:#272D37;--muted:#939BAA;--faint:#6C7585;--accent:#84A5CE}}
:root[data-theme=dark]{--ink:#E3E8EF;--bg:#0E1117;--surface:#171B22;--line:#272D37;
--muted:#939BAA;--faint:#6C7585;--accent:#84A5CE}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.6 "IBM Plex Sans",system-ui,sans-serif}
.wrap{max-width:52rem;margin:0 auto;padding:3rem 1.25rem 5rem}
h1{font-family:"IBM Plex Serif",Georgia,serif;font-size:2rem;margin:0;letter-spacing:-.02em}
.lede{color:var(--muted);margin:.5rem 0 0;max-width:38rem}
ul{list-style:none;padding:0;margin:2rem 0 0;display:grid;gap:.75rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px}
.card a{display:block;padding:1.1rem 1.3rem;text-decoration:none;color:inherit}
.card:hover{border-color:var(--accent)}
.card h2{font-family:"IBM Plex Serif",Georgia,serif;font-size:1.1rem;margin:0 0 .3rem}
.card p{margin:0;color:var(--muted);font-size:.92rem}
.from{display:inline-block;margin-top:.6rem;font-family:"IBM Plex Mono",monospace;
font-size:.72rem;color:var(--faint)}
footer{margin-top:2.5rem;color:var(--muted);font-size:.85rem}
footer code{font-family:"IBM Plex Mono",monospace;font-size:.85em}
a.plain{color:var(--accent)}
</style></head><body>
<div class="wrap">
  <h1>Demos</h1>
  <p class="lede">The pages the examples build, plus a run replayed as it happened. Everything here
  is generated by <code>examples/demo/build.py</code> and checked by the suite, so a page cannot
  drift from the agent &mdash; or the exporter &mdash; that produced it.</p>
  <ul>
__CARDS__
  </ul>
  <footer>
    The examples that build them: <a class="plain" href="../minimal/README.md">minimal</a> &middot;
    <a class="plain" href="../tide-spa/README.md">tide-spa</a> &middot;
    <a class="plain" href="../weather-spa/README.md">weather-spa</a>.
    <br>The minimal example builds a Python function rather than a page, so it has no demo here.
  </footer>
</div>
</body></html>
"""


def generate() -> dict:
    """Return {filename: contents} for every page this directory should hold."""
    pages = {}
    with tempfile.TemporaryDirectory(prefix="demo-") as tmp:
        for demo in DEMOS:
            site = build_site(demo["example"], Path(tmp))
            pages[f'{demo["slug"]}.html'] = inline(site, demo["entry"], demo["scripts"])
    pages["recording.html"] = recording_page()
    pages["index.html"] = index_page(DEMOS)
    return pages


def main():
    pages = generate()
    for name, body in pages.items():
        io.open(HERE / name, "w", encoding="utf-8", newline="\n").write(body)
        print(f"  wrote {name} ({len(body):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
