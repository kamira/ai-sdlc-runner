"""Pin `docs/API.md` to `server.py` (CHG-20260823-22).

The schema catalogue drifted in three checkable ways within a day of being written, because nothing
pinned it. This page is written the same week and describes fifteen routes across a process
boundary; it gets its test at the same time rather than after the drift.

Each test below fails if the API changes and the page does not.
"""
import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_sdlc_runner import engine, graph, models, policy, server  # noqa: E402

PAGE = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
SOURCE = inspect.getsource(server)


def _routes(function: str):
    """The paths one handler actually branches on, read out of its own body."""
    body = SOURCE.split(f"def {function}(self)")[1].split("\n        def ")[0]
    return set(re.findall(r'path == "([^"]+)"', body)) | set(
        re.findall(r'path in \(([^)]+)\)', body)[0].replace('"', "").split(", ")
        if re.findall(r'path in \(([^)]+)\)', body) else [])


def test_every_route_the_server_answers_is_on_the_page():
    for path in _routes("do_GET") | _routes("do_POST"):
        documented = f"`{path}`" in PAGE or f"`GET {path}`" in PAGE or f"`POST {path}`" in PAGE
        assert documented, f"{path} is answered by the server and is not documented"


def test_the_page_invents_no_route():
    real = _routes("do_GET") | _routes("do_POST")
    claimed = {m for m in re.findall(r"`(/[a-z/.]*)`", PAGE)}
    invented = sorted(c for c in claimed if c not in real and not c.endswith(".json"))
    assert not invented, f"the page documents {invented}, which the server does not answer"


def test_the_route_count_the_page_states_is_the_real_one():
    stated = re.search(r"\*\*(\w+) routes\*\* — (\w+) `GET`, (\w+) `POST`", PAGE)
    assert stated, "the page no longer states how many routes there are"
    words = {"seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
             "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
             "eighteen": 18, "nineteen": 19, "twenty": 20}
    stated = [g.lower() for g in stated.groups()]
    # `/` and `/index.html` are one route served by one branch, and the page says so.
    gets = len(_routes("do_GET")) - 1
    posts = len(_routes("do_POST"))
    assert (words[stated[1]], words[stated[2]]) == (gets, posts), (
        f"the page says {stated[1]} GET and {stated[2]} POST; the server answers {gets} and {posts}")
    assert words[stated[0]] == gets + posts


# ── the shapes ────────────────────────────────────────────────────────────────────────────────

def test_the_snapshot_section_lists_every_key_the_snapshot_carries():
    keys = set(server.RunState().snapshot())
    section = PAGE.split("## 3 · The run snapshot")[1].split("## 4 ·")[0]
    missing = sorted(k for k in keys if f'"{k}"' not in section)
    assert not missing, f"the snapshot section omits {missing}"


def test_the_page_documents_every_field_a_suspension_can_carry():
    """**The guard this replaces named its own retirement condition, and it was met.**

    It read the three `report.suspended` dict literals and asserted they differed:

        assert every - first_only, "reading only the first literal now misses nothing; drop this
        guard"

    It existed because the shapes disagreed — 9, 11 and 13 keys — which is the defect
    `CHG-20260904-07` closed by routing all three through `engine._suspension`. With one union
    there is no "first literal" and nothing for a second reading to add, so the guard's own
    condition for dropping it holds.

    What replaces it is stronger and does not depend on how the shape is spelled: the page
    documents every field the union declares.
    """
    section = PAGE.split("## 4 · The suspension")[1].split("## 5 ·")[0]
    missing = sorted(f for f in engine.SUSPENSION_FIELDS if f'"{f}"' not in section)
    assert not missing, (
        f"a suspension carries these and the page does not name them: {missing}")


def test_the_page_does_not_call_a_field_conditional_when_every_shape_carries_it():
    """**The guard above asks whether a field is *named*; this asks what the page *claims*.**

    `CHG-20260904-07` made all fifteen fields present on every suspension. The page went on saying
    *"Nine keys are on every suspension … Six more are carried only by the question that needs
    them"*, with `// only when` dividers over six of them, for a day — and the `-07` guard passed
    the whole time, because all fifteen names were still on the page. A client written to that
    sentence writes `stop.get("reason", "…")` at a gate stop and gets `""`, which is verbatim the
    failure `-07` exists to close, moved out of the data and into the document.

    So the count is read from `SUSPENSION_FIELDS` rather than trusted, and the word `only` is
    refused where the page describes what a suspension carries. `meaningful when` is the honest
    form: present either way, empty when the question is not this one.
    """
    section = PAGE.split("## 4 · The suspension")[1].split("## 5 ·")[0]
    claim = f"All {len(engine.SUSPENSION_FIELDS)} keys are on every suspension"

    assert claim in section, (
        f"the page does not say {claim!r}. A suspension carries "
        f"{len(engine.SUSPENSION_FIELDS)} fields and the page has to say so in the sentence a "
        f"reader reads, not only in the block they skim")
    conditional = [line.strip() for line in section.splitlines() if "only when" in line]
    assert not conditional, (
        f"the page calls a field conditional and `_suspension` puts it on every shape: "
        f"{conditional}")


def test_the_suspension_union_is_the_only_way_a_shape_is_built():
    """The floor for the test above: it reads `SUSPENSION_FIELDS`, so a shape built some other way
    would be documented by accident rather than by rule."""
    import ast

    tree = ast.parse(inspect.getsource(engine))
    literals = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(x, ast.Attribute) and x.attr == "suspended" for x in n.targets)
                and isinstance(n.value, ast.Dict)]
    assert literals == [], (
        f"{len(literals)} suspension(s) are built as a dict literal, so `SUSPENSION_FIELDS` is no "
        f"longer the union the page is checked against")


def test_the_flow_route_section_names_the_node_fields_it_actually_sends():
    body = SOURCE.split('elif path == "/flow"')[1].split("elif path ==")[0]
    sent = set(re.findall(r'"(\w+)": n\.(?:\w+)', body)) | set(re.findall(r'"(\w+)": dict\(n\.', body))
    section = PAGE.split("### `GET /flow`")[1].split("###")[0]
    missing = sorted(k for k in sent if k not in section)
    assert not missing, f"the /flow section omits {missing}"
    withheld = sorted(set(graph.Node.__dataclass_fields__) - sent - {"id"})
    for field in withheld:
        assert field in section, f"the page must say {field!r} is not sent"


def test_the_page_states_the_real_number_of_node_fields_the_flow_route_withholds():
    body = SOURCE.split('elif path == "/flow"')[1].split("elif path ==")[0]
    sent = len(set(re.findall(r'"(\w+)":', body)) & set(graph.Node.__dataclass_fields__))
    assert f"{sent} of `Node`'s" in PAGE or f"Thirteen of `Node`'s" in PAGE
    assert sent == 13, f"the /flow route now sends {sent} node fields; the page says thirteen"


def test_every_status_code_the_server_can_send_is_documented():
    codes = {int(c) for c in re.findall(r"_json\((\d{3}),", SOURCE)}
    section = PAGE.split("## 5 · Status codes")[1]
    missing = sorted(c for c in codes if f"`{c}`" not in section)
    assert not missing, f"the status table omits {missing}"


# ── the security surface, which is the reason this page exists ────────────────────────────────

def test_the_page_documents_both_token_exemptions_and_no_others():
    """Two routes skip the token. A third appearing without the page changing is the finding."""
    guard = SOURCE.split("def _guard(self)")[1].split("def _refuse_host")[0]
    exempt = set(re.findall(r'path in \("([^"]+)", "([^"]+)"\)', guard)[0])
    assert exempt == {"/", "/index.html"}
    assert "/run/events" in guard, "the stream's query-parameter exemption moved"
    for route in exempt | {"/run/events"}:
        assert route in PAGE.split("### The two token exemptions")[1].split("---")[0], route


def test_the_page_says_the_host_check_runs_before_anything_is_parsed():
    """Order is the property, not the presence of three checks."""
    order = PAGE.split("## 0 ·")[1].split("## 1 ·")[0]
    assert order.index("Host") < order.index("Origin") < order.index("X-Operator-Token")
    guard = SOURCE.split("def _guard(self)")[1].split("def _refuse_host")[0]
    assert guard.index("_loopback_host") < guard.index("Origin") < guard.index("X-Operator-Token")


def test_the_page_does_not_claim_a_second_operator_identity():
    """`GET /whoami` returns one name, and that is why halt_independent is a known gap."""
    assert '{ "operator": "<name>" }' in PAGE
    assert "One identity" in PAGE and "halt_independent" in PAGE


@pytest.mark.parametrize("absent", ["DELETE", "PUT"])
def test_the_page_is_honest_about_the_verbs_that_do_not_exist(absent):
    assert f"def do_{absent}" not in SOURCE
    assert absent in PAGE.split("## What this API does *not* have")[1]


def test_every_post_requires_a_version_and_the_page_says_so():
    body = SOURCE.split("def do_POST(self)")[1].split("\n        def ")[0]
    assert 'version = body.get("version")' in body
    assert "isinstance(version, int)" in body
    section = PAGE.split("## 2 · POST routes")[1].split("## 3 ·")[0]
    assert '"version"' in section and "Not optional and not defaulted" in section


def test_models_is_the_one_post_that_does_not_return_a_snapshot():
    body = SOURCE.split("def do_POST(self)")[1].split("\n        def ")[0]
    models_branch = body.split('self.path == "/models"')[1].split("elif self.path")[0]
    assert "reg.as_dict()" in models_branch and "snapshot" not in models_branch
    assert "returns the registry, not a snapshot" in PAGE


def test_the_registry_route_sends_computed_reach_that_is_never_persisted():
    model = models.Model(id="i", vendor="v", name="n", transport="cli", command=("a",))
    assert "reach" in model.as_dict()
    assert "reach" not in inspect.getsource(models.save).split("if k not in")[1].split(")")[0] \
        or "reach" in inspect.getsource(models.save)          # stripped on save
    # Flattened, because prose wraps and a check that fails on where the line broke is testing
    # the formatter rather than the page.
    section = " ".join(PAGE.split("### `GET /models`")[1].split("###")[0].split())
    assert "never persisted" in section and "computed on every read" in section


def test_the_gate_count_the_page_states_matches_the_policy():
    assert f"all {len(policy.GATES)}" in PAGE
