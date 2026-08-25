"""Pin `docs/schema-atlas.html` (CHG-20260823-30).

The chart's footer claimed it was pinned by four named tests. **None of them read it** — a seat
grepped `tests/` and found zero hits, and the page was claiming the very property whose absence had
let four contradictions stand in it at once:

1. the legend still called the plan file the open one that matters, while a callout below said it
   was closed;
2. the pipeline said *"two of them are closed"* over three closed chips;
3. the constraints header said *"four are enforced"* over a legend saying five;
4. the footer's own pinning claim.

Claiming a check is worse than having none, because it stops anybody looking.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_sdlc_runner import conversations, graph, policy, store  # noqa: E402

PAGE = (ROOT / "docs" / "schema-atlas.html").read_text(encoding="utf-8")
FLAT = " ".join(PAGE.split())

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10}


def test_the_page_exists_and_is_the_one_the_readme_links():
    assert PAGE.strip(), "the chart is empty"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/schema-atlas.html" in readme


def test_the_counts_in_the_header_are_the_real_ones():
    header = PAGE.split("</header>")[0]
    for number, label in [(len(graph.NODES), "nodes"), (len(graph.MODES), "modes"),
                          (len(policy.GATES), "gates"),
                          (len(policy.PERMANENT_HALT_KINDS), "never-automated kinds"),
                          (len(policy.SEATS), "seats")]:
        assert f"<b>{number}</b> {label}" in header, f"the header's {label} count is not {number}"


def test_the_page_does_not_contradict_itself_about_how_many_are_closed():
    """Three places say a number, and a seat found two of them disagreeing."""
    stated = set()
    for pattern in (r"(\w+) schemas are \*?\*?closed",
                    r"(\w+) schemas are closed",
                    r"<p>A field outside the set is <strong>refused</strong>[^<]*?(\w+) schemas",
                    r"(\w+) are enforced in code"):
        stated |= {WORDS[m.lower()] for m in re.findall(pattern, FLAT) if m.lower() in WORDS}
    assert stated, "the page no longer states how many schemas are closed"
    assert len(stated) == 1, f"the page states {sorted(stated)} in different places"

    chips = len(re.findall(r'chip c-closed">closed<', PAGE))
    assert chips, "no schema is chipped closed"


def test_the_pipeline_says_how_many_of_its_stages_are_closed_and_means_it():
    pipeline = PAGE.split('class="pipe"')[1].split("</div>\n  </div>")[0]
    closed_stages = len(re.findall(r'chip c-closed', pipeline))
    said = re.search(r"(\w+) of them are closed", FLAT)
    assert said, "the pipeline no longer says how many of its stages are closed"
    assert WORDS[said.group(1).lower()] == closed_stages, (
        f"the pipeline says {said.group(1)} closed and chips {closed_stages}")


def test_the_plan_file_is_not_called_open_anywhere():
    """It was, in the legend, while a callout below said it was closed."""
    lowered = FLAT.lower()
    for phrase in ("the plan file is the one that matters",
                   "the plan file is the one open schema"):
        assert phrase not in lowered, f"the chart still says: {phrase!r}"


def test_the_tables_it_draws_are_the_tables_the_code_builds(tmp_path):
    built = set()
    live = store.connect(tmp_path / "probe.sqlite")
    built = {row[0] for row in live.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    live.close()
    for table in built:
        block = re.search(rf'<span class="name">{table}</span>(.*?)</div>', PAGE, re.S)
        assert block, f"{table} is built and not drawn"
        assert "c-built" in block.group(1) or "c-built" in PAGE.split(table)[1][:200], (
            f"{table} is built and the chart does not say so")


def test_every_turn_kind_and_route_count_it_states_is_real():
    assert f"<b>{len(conversations.KINDS)}</b> turn kinds" in PAGE
    from ai_sdlc_runner import server
    import inspect
    source = inspect.getsource(server)
    gets = set(re.findall(r'path == "([^"]+)"',
                          source.split("def do_GET(self)")[1].split("\n        def ")[0]))
    posts = set(re.findall(r'self\.path == "([^"]+)"',
                           source.split("def do_POST(self)")[1].split("\n        def ")[0]))
    routes = len(gets | {"/", "/index.html"}) - 1 + len(posts)
    assert f"<b>{routes}</b> HTTP routes" in PAGE, f"the chart's route count is not {routes}"


def test_the_footer_does_not_claim_a_test_that_does_not_exist():
    """The failure that produced this file: it named four tests, none of which read it."""
    named = set(re.findall(r"tests/(\w+\.py)", PAGE)) | set(re.findall(r"<code class=\"m\">(\w+\.py)</code>", PAGE))
    for test_file in named:
        assert (ROOT / "tests" / test_file).exists(), f"the chart names {test_file}, which is gone"
    assert "test_schema_atlas.py" in PAGE, (
        "the chart must name the test that actually reads it")
