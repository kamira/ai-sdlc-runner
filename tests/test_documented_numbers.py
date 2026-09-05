"""Every number the documents claim, checked against the code that produces it (CHG-20260823-08).

**Six consecutive rounds of independent review found a documentation figure that was wrong**, and
each time in a different file, so each time it read as a slip. Six is not six slips. The numbers were
hand-typed, nothing computed them, and a figure nobody can check is a claim rather than a fact:

| Round | The claim | The truth |
|---|---|---|
| 1 | "202 passed" | 204 |
| 2 | "12 asking nodes" | 14 |
| 2 | "34 tests" in `test_cli.py` | 36 |
| 3 | ledger "25 changes" | 26 |
| 5 | the brief check reads "three fields" | nine |
| 6 | false-stop corpus "56 briefs" / "36 briefs" | 46 |

The fix that generalises is not "be more careful". It is this file: **the documents state numbers,
and the numbers are recomputed here and compared.** A figure that drifts now fails a test in the
same commit that drifts it, which is the only mechanism that has ever worked in this repository.

Prose is exempt. This checks figures a reader would take as measurements.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize
from pathlib import Path

import pytest

QUOTES = chr(34) + chr(39)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

#: Everything a reader would take as current. **Source is included**: a verifier found `policy.py`'s
#: own docstring still claiming "36 real briefs" precisely because this list stopped at `docs/`, and
#: a docstring is documentation that happens to live in a file the compiler reads.
#:
#: `docs/changes/` and `docs/acceptance/` are deliberately **out**: a change record states what was
#: true when it was written, and rewriting history to match the present is how a ledger stops being
#: one. Where such a record was actually wrong, it is corrected in place with a note saying so.
DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "ai-guideline.md",
    ROOT / "docs" / "structure" / "design.md",
    ROOT / "docs" / "structure" / "data.md",
    ROOT / "docs" / "structure" / "directory.md",
    ROOT / "docs" / "structure" / "logical.md",
    ROOT / "docs" / "knowledge" / "knowledge.md",
    ROOT / "src" / "ai_sdlc_runner" / "policy.py",
    ROOT / "src" / "ai_sdlc_runner" / "graph.py",
    ROOT / "src" / "ai_sdlc_runner" / "engine.py",
    ROOT / "src" / "ai_sdlc_runner" / "settings.py",
)


def _text():
    return {p.name: p.read_text(encoding="utf-8") for p in DOCS if p.is_file()}


# --------------------------------------------------------------------------------------
# the flow's own shape
# --------------------------------------------------------------------------------------

def test_the_node_count_in_the_documents_matches_the_graph():
    from ai_sdlc_runner import graph

    actual = len(graph.NODES)
    for name, body in _text().items():
        for claimed in re.findall(r"(\d+)\s+(?:nodes|節點)", body):
            assert int(claimed) == actual, f"{name} says {claimed} nodes; the graph has {actual}"


def test_the_gate_count_in_the_documents_matches_the_policy():
    from ai_sdlc_runner import policy

    actual = len(policy.GATES)
    for name, body in _text().items():
        for claimed in re.findall(r"(\d+)\s+gates\b", body):
            assert int(claimed) == actual, f"{name} says {claimed} gates; policy has {actual}"
        for claimed in re.findall(r"(\d+)\s*個閘門", body):
            assert int(claimed) == actual, f"{name} says {claimed} gates; policy has {actual}"


def test_the_permanent_halt_count_matches():
    from ai_sdlc_runner import policy

    actual = len(policy.PERMANENT_HALT_KINDS)
    assert actual == 6, "if this changes, the documents' 'six actions' phrasing needs a look"
    for name, body in _text().items():
        for claimed in re.findall(r"(\d+)\s+(?:permanent halts|never-automated)", body):
            assert int(claimed) == actual, f"{name}: {claimed} vs {actual}"


def test_the_seat_floor_matches():
    from ai_sdlc_runner import policy

    actual = policy.SEAT_FLOOR
    for name, body in _text().items():
        for claimed in re.findall(r"floor of (\d+)", body):
            assert int(claimed) == actual, f"{name} says floor {claimed}; policy says {actual}"


def test_the_work_order_field_count_matches():
    from ai_sdlc_runner import workorder

    actual = len(workorder.WORK_ORDER_FIELDS)
    words = {"sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
    for name, body in _text().items():
        for word, value in words.items():
            if re.search(rf"\b{word}\s+fields\b", body, re.IGNORECASE):
                assert value == actual, f"{name} says {word} fields; there are {actual}"


# --------------------------------------------------------------------------------------
# the measured numbers
# --------------------------------------------------------------------------------------

def _backstop_catch():
    from test_flow import VERIFIER_CORPUS

    from ai_sdlc_runner import policy

    caught = [d for _, d in VERIFIER_CORPUS if policy.permanent_halt(d) is not None]
    return len(caught), len(VERIFIER_CORPUS)


def _false_stop_corpus_size():
    from test_false_stops import AWKWARD_BUT_ORDINARY, ORDINARY_WORK, VERIFIERS_CORPUS

    return len(ORDINARY_WORK) + len(AWKWARD_BUT_ORDINARY) + len(VERIFIERS_CORPUS)


def test_the_backstop_catch_rate_the_documents_claim_is_the_measured_one():
    caught, total = _backstop_catch()
    for name, body in _text().items():
        for a, b in re.findall(r"(\d+)\s+of\s+(\d+)\s+(?:known attempts|caught)", body):
            assert (int(a), int(b)) == (caught, total), \
                f"{name} claims {a} of {b}; measured {caught} of {total}"
        for a, b in re.findall(r"catches\s+(\d+)\s+of\s+(\d+)", body):
            assert (int(a), int(b)) == (caught, total), \
                f"{name} claims {a} of {b}; measured {caught} of {total}"


#: Only **present-tense** claims about the corpus. `knowledge.md` records what a measurement *was*
#: at the time — "19 of 20 briefs were stopped" is history and rewriting it to match today would
#: turn the knowledge base into a set of statements about the present, which is not what it is for.
#: The distinction is the phrasing: a current claim says what the check *does*.
_CURRENT_CORPUS = (
    r"falsely stops \d+ of (\d+)",
    r"0 of (\d+) ordinary(?:\s+engineering)? briefs",
    r"stops on (\d+) real briefs",
    r"false stops \((\d+) real briefs\)",
    r"(\d+)\s*句正常開發任務誤擋",
)


def test_the_false_stop_corpus_size_the_documents_claim_is_the_real_one():
    """The one that was wrong two ways at once — 56 in some files, 36 in others, 46 in fact."""
    actual = _false_stop_corpus_size()
    for name, body in _text().items():
        for pattern in _CURRENT_CORPUS:
            for claimed in re.findall(pattern, body):
                assert int(claimed) == actual,                     f"{name} says {claimed} briefs; there are {actual}"


def test_the_false_stop_rate_the_documents_claim_is_still_true():
    from test_false_stops import (AWKWARD_BUT_ORDINARY, ORDINARY_WORK, VERIFIERS_CORPUS,
                                  _runs_clean)

    corpus = ORDINARY_WORK + AWKWARD_BUT_ORDINARY + VERIFIERS_CORPUS
    stopped = [b for b in corpus if not _runs_clean(b)]
    claimed_zero = any("falsely stops 0" in body or "0 of 46" in body or "誤擋 0 句" in body
                       for body in _text().values())
    if claimed_zero:
        assert stopped == [], f"the documents claim zero false stops; these stop: {stopped}"


# --------------------------------------------------------------------------------------
# the check itself has to be able to fail
# --------------------------------------------------------------------------------------

def test_this_check_would_catch_a_drifted_number(tmp_path):
    """A tripwire nothing can trip is a comment — which is, itself, one of this repo's findings."""
    from ai_sdlc_runner import graph

    fake = tmp_path / "FAKE.md"
    fake.write_text(f"The flow has {len(graph.NODES) + 1} nodes.\n", encoding="utf-8")
    claimed = re.findall(r"(\d+)\s+nodes", fake.read_text(encoding="utf-8"))
    assert claimed and int(claimed[0]) != len(graph.NODES)


#: Every claim this file knows how to check, with the pattern that finds it. A category that stops
#: appearing anywhere is a category nobody is checking, so each one is asserted present by name.
CATEGORIES = {
    "node count": r"\d+\s+nodes",
    "gate count": r"\d+\s+gates",
    "seat floor": r"floor of \d+",
    "measured ratio": r"\d+\s+of\s+\d+",
    "false-stop corpus": r"(?:falsely stops \d+ of \d+|0 of \d+ ordinary)",
}


@pytest.mark.parametrize("name,pattern", sorted(CATEGORIES.items()))
def test_each_category_is_still_stated_somewhere(name, pattern):
    """The tripwire, per category rather than in aggregate.

    Asking only whether *some* number appears anywhere let a whole category vanish from every file
    while the guard stayed green — a verifier pointed out that this is "nothing matched = all fine",
    the exact defect this guard exists to prevent, in the guard itself. Now each category has to be
    stated somewhere, or this fails and says which one went missing.
    """
    body = "\n".join(_text().values())
    assert re.search(pattern, body), (
        f"no {name} stated in any document — either it was reworded out of the checkable form, or "
        f"it is genuinely no longer stated. Either way nothing is verifying it.")


def test_the_role_and_seat_counts_match():
    """Two more figures the documents carry that nothing was recomputing."""
    from ai_sdlc_runner import policy

    for name, body in _text().items():
        for claimed in re.findall(r"(\w+)\s+roles\b", body):
            words = {"five": 5, "four": 4, "six": 6, "three": 3}
            if claimed.lower() in words:
                assert words[claimed.lower()] == len(policy.ROLES), \
                    f"{name} says {claimed} roles; there are {len(policy.ROLES)}"
        for claimed in re.findall(r"(\w+)\s+review seats\b", body):
            words = {"four": 4, "three": 3, "five": 5}
            if claimed.lower() in words:
                assert words[claimed.lower()] == len(policy.SEATS), \
                    f"{name} says {claimed} seats; there are {len(policy.SEATS)}"


def test_the_asking_node_count_matches():
    from ai_sdlc_runner import graph

    actual = len(graph.asking_nodes())
    for name, body in _text().items():
        for claimed in re.findall(r"(\d+)\s+(?:asking nodes|of them ask|個詢問節點)", body):
            assert int(claimed) == actual, f"{name} says {claimed}; there are {actual}"


def test_the_change_records_task_count_matches_its_own_task_table():
    """The recurrence this record was written to prevent, checked instead of promised.

    CHG-20260822-04 simultaneously claimed "all nine tasks built" and "nothing in src/ has been
    written", for the length of a build, because two places said how much was done and only one was
    swept. This record says it in the Status line and in the State column; a test is the only thing
    that keeps them agreeing.
    """
    import pathlib
    import re

    record = (pathlib.Path(__file__).resolve().parents[1]
              / "docs" / "changes" / "CHG-20260823-11.md").read_text(encoding="utf-8")
    ticked = record.count("**[x]**")
    claimed = re.search(r"\*\*(\d+) of (\d+) tasks built\*\*", record)
    assert claimed, "the Status line should say how many tasks are built"
    assert int(claimed.group(1)) == ticked, (
        f"Status says {claimed.group(1)} tasks built and the table ticks {ticked}. Two places "
        f"saying how much is done is two chances to leave one stale.")
    assert int(claimed.group(2)) == ticked + record.count("**[ ]**")


def test_every_cli_flag_the_readme_names_actually_exists():
    """A README that names a flag the CLI does not have sends people to a usage error.

    Written after the README shipped with `--seats N`, which has never existed — the flag is
    `--review-seats`. Nothing checked, because prose is not run.
    """
    import argparse
    import pathlib
    import re

    from ai_sdlc_runner import cli

    readme = (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    real = set()
    parser = cli.build_parser()
    stack = [parser]
    while stack:
        current = stack.pop()
        for action in current._actions:
            real.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                stack.extend(action.choices.values())

    named = set(re.findall(r"`(--[a-z][a-z-]*)", readme))
    named |= set(re.findall(r"^\s*runner .*?(--[a-z][a-z-]*)", readme, re.M))
    unknown = sorted(f for f in named if f not in real)
    assert not unknown, (
        f"the README names {unknown}, which the CLI does not accept. Either the flag was renamed "
        f"and the README was not swept, or it never existed.")


def test_the_readme_puts_global_flags_before_the_subcommand():
    """`--config` is global. After the subcommand it is an error, and the example would not run.

    Worse than not running: without `--config` there is no `agent_command`, every ask goes to a
    stub, and the run completes having asked nobody — which looks like success.
    """
    import pathlib
    import re

    readme = (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for line in readme.splitlines():
        line = line.strip()
        if not line.startswith("runner ") or "--config" not in line:
            continue
        before, _, after = line.partition("--config")
        assert not re.search(r"\b(run|serve|flow|policy|settings)\b", before), (
            f"this example puts --config after the subcommand and would fail to parse:\n  {line}")


def test_the_test_count_the_readme_states_is_the_real_one():
    """The one figure this file could not see, and which a seat caught drifting twice.

    The README said "847 passing" when 857 did. A suite cannot count itself while running, so this
    counts it in a subprocess.

    **It states a collected count, not a passing one, and that is the correction.** The first
    version compared against collected-minus-skips and called the skips "counted, not guessed" —
    they were always guessed: `--collect-only` never emits `SKIPPED`, so the fallback constant ran
    on every machine. Both skips here are `curses` importorskips; on CI's Ubuntu they execute and
    `pytest -q` prints two more passes than this machine. The README's number would have been false
    there and this test would still have passed, because it subtracted the same constant everywhere.

    A count that is machine-independent is the only one a document can state. How many of them pass
    on a given machine is a property of that machine.
    """
    import os
    import re
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    claimed = re.search(r"pytest -q\s*#\s*([\d,]+) tests", readme)
    if claimed is None:
        return                          # the README no longer states one; nothing to hold it to
    want = int(claimed.group(1).replace(",", ""))

    done = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root),
        env={**os.environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})
    found = re.search(r"(\d+) tests collected", done.stdout or "")
    assert found, f"could not count the suite:\n{(done.stdout or '')[-400:]}"
    assert int(found.group(1)) == want, (
        f"the README says {want} tests; the suite collects {found.group(1)}")


def test_the_readme_says_how_many_nodes_a_run_actually_visits():
    """The node-count check passed a false sentence, and that is the finding.

    The README said the example *"drives all 24 nodes"*. A run visits **20** — the other four are
    failure paths a green run never takes — and `test_the_node_count_in_the_documents_matches_the_graph`
    passed it anyway, because its regex matched `24` and compared it to `len(graph.NODES)`. The
    figure was right about the graph and the sentence was wrong about the run: **a check on the
    right number against the wrong referent.**
    """
    import re
    from ai_sdlc_runner import graph as graph_mod
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    said = re.search(r"visits (\d+) of the (\d+) nodes", readme)
    assert said, "the README no longer says how many nodes a run visits"
    visited, total = int(said.group(1)), int(said.group(2))
    assert total == len(graph_mod.NODES)
    assert visited < total, "a run that visits every node would never take a failure path"
    # Derived, not typed. This used to assert `visited == 22` — a literal, beside a docstring
    # convicting the previous check of "a check on the right number against the wrong referent",
    # which is exactly what a hard-coded number is. It ran no walk. And 22 was the wrong referent
    # twice over: `len(report.visited)` counts **steps**, `next_module` is entered twice, and a
    # green run touches **21 distinct nodes**. The failure message even sent the reader to the
    # `visited:` line, which prints the step count (CHG-20260903-31, found by the defect seat).
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_flow import ALL_GATES, Recorder, _cfg
    from ai_sdlc_runner import engine

    report = engine.walk(_cfg(risk="low", confirmed=ALL_GATES), Recorder(), enabled=True)
    distinct = len(set(report.visited))

    assert visited == distinct, (
        f"the README says a run visits {visited} of {total} nodes; a green run visits "
        f"{distinct} distinct nodes in {len(report.visited)} steps. The two differ because "
        f"`next_module` is entered twice — `len(report.visited)` is a step count and the "
        f"sentence is about nodes.")

    # The sentence carries an accounting, so the accounting is checked: what a green run never
    # reaches must be exactly what the sentence says it skips. It read `22 + 5 + 2 = 29` of 31,
    # and two nodes went unnamed.
    never = {node.id for node in graph_mod.NODES} - set(report.visited)
    tiers = {"sub_plan", "reconcile"}
    said_failures = re.search(r"— (\w+) are failure paths", readme)
    assert said_failures, "the README no longer says how many nodes are failure paths"
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10}
    claimed = words.get(said_failures.group(1))
    assert claimed is not None, f"unrecognised number word {said_failures.group(1)!r}"
    assert claimed == len(never - tiers), (
        f"the README says {claimed} failure paths; a green run never reaches "
        f"{len(never - tiers)} nodes that are not the second planning tier: "
        f"{sorted(never - tiers)}")
    assert distinct + claimed + len(tiers) == total, (
        f"the sentence's own arithmetic does not reach {total}: "
        f"{distinct} + {claimed} + {len(tiers)} = {distinct + claimed + len(tiers)}")


def test_a_knowledge_entry_marked_superseded_in_the_index_says_so_in_its_body():
    """An INDEX row and a body are two places saying one thing, which is two chances to leave one
    stale — and one of them was.

    KN-3's row said superseded from the day CHG-20260823-01 landed. Its body went on describing
    `DashboardModel` and `render_snapshot`, deleted by that same change, in the present tense. The
    task that claimed to have marked "KN-1/2/3 ... in body as well as index" was ticked with two of
    three done, and it stayed that way until an acceptance round read the body.

    A reader who lands on a section heading does not see the index. Closed by CHG-20260827-09.
    """
    import re

    text = (ROOT / "docs" / "knowledge" / "knowledge.md").read_text(encoding="utf-8")

    marked = set()
    for row in re.findall(r"^\|\s*(KN-\d+)\s*\|(.*)$", text, re.M):
        entry, rest = row
        if "superseded" in rest.lower():
            marked.add(entry)
    assert marked, "no INDEX row is marked superseded; has the table changed shape?"

    bodies = dict(re.findall(r"^##\s+(KN-\d+)\s*[—-].*?$\n(.*?)(?=^##\s|\Z)",
                             text, re.M | re.S))

    missing = []
    for entry in sorted(marked):
        body = bodies.get(entry)
        if body is None:
            missing.append(f"{entry}: marked superseded in the INDEX and has no body section")
        elif not re.search(r"^>\s*\*\*Superseded", body, re.M):
            missing.append(f"{entry}: INDEX says superseded, body does not")

    assert not missing, (
        "a knowledge entry retired in the index and not in its own body reads as current to "
        f"anyone who arrives at the heading: {missing}")


def _readme_flow_diagram() -> str:
    """The fenced block under `## The flow`, located structurally rather than by line number."""
    import re

    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = re.search(r"^##\s+The flow\s*$(.*?)(?=^##\s)", text, re.M | re.S)
    assert section, "README has no `## The flow` section; has it been renamed?"
    fenced = re.findall(r"^```\n(.*?)^```", section.group(1), re.M | re.S)
    assert fenced, "the flow section has no fenced diagram"
    return "\n".join(fenced)


def test_every_node_in_the_graph_is_drawn_in_the_readme_diagram():
    """The count was checked. The drawing was not.

    `test_the_node_count_in_the_documents_matches_the_graph` compares the *sentence* "24 nodes"
    against the graph, so a node dropped from the picture while the sentence stayed correct passed
    CI. The diagram was complete — by inspection, checked by hand during the acceptance round of
    2026-08-27, which is a different thing from by construction. Closed by CHG-20260827-08.

    This is the completeness half; the count test is the arithmetic half, and neither substitutes
    for the other.
    """
    from ai_sdlc_runner import graph

    drawn = _readme_flow_diagram()
    missing = [node.id for node in graph.NODES if node.id not in drawn]
    assert not missing, (
        f"the README's flow diagram does not draw {missing}. The node count sentence can still be "
        f"correct while this is true, which is why it is checked separately.")


def test_the_completeness_check_would_notice_a_node_left_out():
    """Proof it can fail. A check whose failure mode nobody has seen is a check nobody should trust.

    Rather than mutate the README, the assertion is run against a diagram with one node removed —
    the same string operation the real test performs, on a copy.
    """
    from ai_sdlc_runner import graph

    drawn = _readme_flow_diagram()
    dropped = graph.NODES[-1].id
    sabotaged = drawn.replace(dropped, "…")
    missing = [node.id for node in graph.NODES if node.id not in sabotaged]
    assert dropped in missing, (
        "removing a node from the drawing did not register as missing, so the real check could "
        "not catch it either")


def _defect_log():
    return (ROOT / "docs" / "defect-log.md").read_text(encoding="utf-8")


def _defect_log_rows():
    """The `| Where it came from | Count |` table, as (label, count)."""
    import re

    rows = []
    for label, count in re.findall(
            r"^\|\s*(?!Where it came from)(?!-)(.+?)\s*\|\s*\*\*(\d+)\*\*.*?\|\s*$",
            _defect_log(), re.M):
        rows.append((label, int(count)))
    return rows


def test_the_defect_logs_table_sums_to_the_total_it_states():
    """The one document whose figures nothing checked — inside a change that claimed every figure
    was recomputed.

    `docs/defect-log.md` is deliberately **not** in DOCS: it quotes its own historical wrong figures
    on purpose ("two of thirty-two" against a table summing to 35), and a blanket numbers check
    would fail on the quotations. So the check is targeted at the arithmetic the file actually
    asserts about itself. Added by CHG-20260827-11.
    """
    import re

    rows = _defect_log_rows()
    assert rows, "the defect log's count table was not found; has it changed shape?"

    stated = re.search(r"sums to\s*\n?\*\*(\d+)\*\*", _defect_log())
    assert stated, "the defect log no longer states what its table sums to"

    assert sum(n for _, n in rows) == int(stated.group(1)), (
        f"the table sums to {sum(n for _, n in rows)} and the file says {stated.group(1)}")


def test_every_defect_log_group_heading_agrees_with_its_row_in_the_table():
    """Two places saying one number is two chances to leave one stale, and one was.

    `## Found in the fix for the last review — 12` sat above a table row reading **13**, with the
    stated total agreeing with the row. Two of the three numbers agreed, so the heading was the
    stale one — the third time this file has miscounted itself, and the first time a check found it
    rather than a reader.

    Counting `###` subsections would be the wrong check: several sections carry more than one
    finding, so the heading is not a subsection count and never was.
    """
    import re

    text = _defect_log()
    headings = {}
    for title, count in re.findall(r"^##\s+(.*?)\s*[—-]\s*(\d+)\b.*$", text, re.M):
        headings[title.strip().lower()] = int(count)
    assert headings, "no numbered group headings found"

    # The table's label and the heading are worded differently on purpose — the table reads as a
    # list of sources, the heading as a section title — so they are matched on their distinctive
    # words rather than on equality.
    keys = {
        "an independent seat": "found by an independent seat",
        "only by running it": "found only by running it",
        "the test suite, unprompted": "found by the test suite, unprompted",
        "my own process failures": "my own process failures",
        "putting the readme": "found by putting the readme itself through review",
        "before its code existed": "found by reviewing a design before its code existed",
        "that answered": "found by reviewing the code that answered the design",
        "the last review": "found in the fix for the last review",
    }

    # KN-17: a qualified count is two claims, and the bare number is the ambiguous one.
    # One row is qualified in both places and the two spellings disagree about what the bare
    # number counts: the table reads `**4** (+1 intended collision, below)` and the heading reads
    # `3, plus one intended collision`. Which of 3 and 4 is the count of *defects* is not decidable
    # from the document, and the sum-to-79 depends on the table's 4. Guessing would put a number
    # into a file about wrong numbers, so the qualified row is checked for its qualifier and not
    # for equality, and the ambiguity is recorded in ACC-20260827-11 instead.
    qualified = "unprompted"

    disagreements = []
    for label, count in _defect_log_rows():
        plain = re.sub(r"\*+", "", label).lower()
        if qualified in plain:
            heading_text = next(
                (line for line in text.splitlines()
                 if line.startswith("## ") and qualified in line.lower()), "")
            assert "intended collision" in heading_text, (
                "the qualified row lost its qualifier in the heading, so the two numbers are now "
                "claiming to count the same thing and do not")
            continue
        heading = next((h for fragment, h in keys.items() if fragment in plain), None)
        if heading is None:
            disagreements.append(f"table row {label!r} matches no group heading")
            continue
        if heading not in headings:
            disagreements.append(f"no `## {heading} — N` heading for table row {label!r}")
        elif headings[heading] != count:
            disagreements.append(
                f"{heading!r}: heading says {headings[heading]}, table says {count}")

    assert not disagreements, disagreements


def test_kn17_and_the_check_that_implements_it_name_each_other():
    """A rule and its mechanism that do not name each other are a paragraph and a coincidence.

    KN-14 was exactly that for four days: a rule in the README with nothing behind it, broken by
    the round that wrote it down. KN-17 is a rule about a skip inside another test, which is even
    easier to lose — rename the check and the entry describes something that no longer exists;
    delete the entry and the skip becomes an unexplained exception somebody will "fix" by guessing.

    Added by CHG-20260827-16.
    """
    knowledge = (ROOT / "docs" / "knowledge" / "knowledge.md").read_text(encoding="utf-8")
    source = Path(__file__).read_text(encoding="utf-8")

    check = "test_every_defect_log_group_heading_agrees_with_its_row_in_the_table"
    assert "KN-17" in knowledge, "KN-17 is gone; the skip below is now unexplained"
    assert check in knowledge, (
        f"KN-17 no longer names {check}, so a reader of the rule cannot find the mechanism")
    assert "KN-17" in source, (
        f"the skip in {check} no longer names KN-17, so a reader of the code cannot find the rule")


# ── two claims about the governance that the code contradicts (CHG-20260903-33) ────────────────


def test_no_live_text_claims_the_verifier_is_checked_against_the_builder():
    """`halt_independent` stops for a person and **does not** check independence.

    There is one operator identity and nothing compares who confirmed against who built.
    `README.md`'s Known gaps has always said so; `docs/ARCHITECTURE.md` was corrected by
    CHG-20260903-27 and `policy.py` was the third copy. The ledger is history and keeps its
    sentences; what a reader consults must not carry the claim unqualified.
    """
    root = Path(__file__).resolve().parents[1]
    live = [root / "README.md", root / "docs" / "ARCHITECTURE.md",
            root / "docs" / "API.md", *(root / "src").rglob("*.py"),
            *(root / "docs" / "structure").glob("*.md")]

    # **The qualifier is looked for around the claim, not anywhere in the file**
    # (CHG-20260903-34, idiom seat L-50). As first written the exemption was file-scoped:
    # `phrase in text and "does **not**" not in text`. Measured, nine of the twenty-eight
    # files scanned already contain one of those strings for unrelated reasons — README.md,
    # ARCHITECTURE.md, graph.py, plan.py, policy.py, server.py, settings.py, store.py and
    # design.md — so the scan was switched **off** in every one of them. Appending a fourth
    # copy of the claim to README.md left this test green.
    #
    # A rule that a file can disable by containing an unrelated sentence is not a rule. The
    # window is the paragraph the claim is made in.
    window = 400
    offenders = []
    for path in live:
        text = path.read_text(encoding="utf-8", errors="replace")
        for phrase in ("verifier must not be the builder", "forbids the implementer from verifying"):
            at = text.find(phrase)
            while at != -1:
                near = text[max(0, at - window):at + window]
                if "does **not**" not in near and "does not check" not in near:
                    offenders.append(f"{path.relative_to(root)}: {phrase!r}")
                    break
                at = text.find(phrase, at + 1)

    assert offenders == [], (
        "these say `halt_independent` enforces independence, and it does not: " + repr(offenders))


def test_the_governance_paragraph_names_the_one_piece_that_is_project_data():
    """`docs/structure/data.md` said *"everything about the governance is in `policy.py`"*.

    Halt routing is governance — who a stop is sent to — and it lives in a `halt_routing` table
    created and written in `store.py`, read by `store.halt_routing(db)`, carried on `RunConfig` and
    passed into `policy.routed_to(kind, routing)` as an argument. The sentence was already false on
    `main`, for a reason that has nothing to do with the design records that were reviewing it.
    """
    root = Path(__file__).resolve().parents[1]
    said = (root / "docs" / "structure" / "data.md").read_text(encoding="utf-8")

    assert "everything about the governance\nis in `policy.py`" not in said
    assert "halt_routing" in said, (
        "the paragraph that says where governance lives must name the piece that is project data")
    # And the claim it makes instead has to still be true of `policy.routed_to`'s signature.
    assert "routed_to" in said


# ── no two requirement rows disagree about the same surface (CHG-20260903-35) ───────────────────


def test_no_requirement_row_counts_the_settings_surface(tmp_path):
    """FR-20 said *"Settings may lower the seat floor **and nothing else**"* — a count, and false.

    `settings.FIELDS` holds three names and the third standingly clears a refusal (measured in
    CHG-20260903-28). FR-20 also disagreed with **FR-13**, three rows above and also P0, which says
    *"**Both** the seat count and the mode are set on a screen"* — two settings where FR-20 said
    one. Two P0 rows in one table disagreeing about the size of the same surface is worse than
    either being wrong alone.

    A row that names the surface follows it; a row that counts it drifts from it.
    """
    del tmp_path
    root = Path(__file__).resolve().parents[1]
    guideline = (root / "docs" / "ai-guideline.md").read_text(encoding="utf-8")

    rows = [line for line in guideline.splitlines() if line.startswith("| FR-")]
    counting = [line for line in rows
                if "seat floor and nothing else" in line or "lower the seat floor and nothing" in line]

    assert counting == [], (
        "a requirement row states what settings reach as a count; `settings.FIELDS` is the "
        f"surface and it holds {len(settings_mod.FIELDS)}: {list(settings_mod.FIELDS)}")


# ── documents that describe a different program (CHG-20260903-37) ───────────────────────────────


def _tracked_and_ignored(root, paths):
    """Which of `paths` git tracks, and which it deliberately ignores.

    Asked of git rather than matched against `.gitignore` by hand: the ignore syntax has
    negation, directory and precedence rules that a hand-rolled match gets wrong quietly,
    which is the failure mode this whole rule exists to remove.

    Where git cannot answer, the caller **skips** rather than passing — the same argument
    `tools/ledger_check.py` makes when no default branch resolves: *"on a shallow checkout
    there is nothing to compare and saying so is the whole point"*.
    """
    import subprocess

    # **NUL-separated, and bytes.** In text mode Python translates the separator on Windows,
    # so git received `examples/minimal/greet.py\r`, matched nothing, and answered *not
    # ignored* — which would have read as the defect rather than as a broken question.
    def git(args, stdin=None):
        return subprocess.run(["git", "-C", str(root)] + args, input=stdin,
                              capture_output=True)

    def split(raw):
        return {piece for piece in raw.decode("utf-8", "replace").split(chr(0)) if piece}

    listed = git(["ls-files", "-z", "--"] + list(paths))
    # `check-ignore` exits 1 when nothing matches, which is an answer and not a failure;
    # anything else means it could not tell us.
    asked = git(["check-ignore", "--stdin", "-z"],
                stdin=chr(0).join(paths).encode("utf-8") + b"\x00")

    # **Both, in one check.** Written as two skips first, and they could not be told apart:
    # in a directory that is not a repository the first fires, so a mutation of the second
    # was invisible and reported NOT CAUGHT. One question, one message, and the message names
    # which command could not answer.
    unanswered = [name for name, done in (("ls-files", listed.returncode == 0),
                                          ("check-ignore", asked.returncode in (0, 1)))
                  if not done]
    if unanswered:
        pytest.skip("git could not answer %s, so provenance was NOT checked: %s"
                    % (" and ".join(unanswered),
                       (listed.stderr + asked.stderr).decode("utf-8", "replace").strip()[:200]))

    return split(listed.stdout), split(asked.stdout)


def test_a_cited_path_git_neither_tracks_nor_ignores_is_still_the_defect():
    """The rule above must still catch what it was written for (CHG-20260904-14).

    Moving from existence to provenance widens what passes, so the floor is that the
    original failure — a path cited as evidence that nobody can open or produce — is still
    in neither set.
    """
    root = Path(__file__).resolve().parents[1]
    tracked, ignored = _tracked_and_ignored(
        root, ["examples/no-such-example/plan.json", "examples/minimal/plan.json"])

    assert "examples/no-such-example/plan.json" not in tracked | ignored, (
        "a path git has never heard of was read as provenance")
    assert "examples/minimal/plan.json" in tracked, (
        "this floor stopped measuring: the tracked arm found nothing")


def test_provenance_is_the_same_answer_whether_the_file_is_there(tmp_path):
    """**The point of the change** (CHG-20260904-14, defect seat L-57).

    `examples/minimal/greet.py` has never been committed, and the suite writes it: a run of
    `tests/test_change_classes.py` executes the real CLI against `examples/minimal/runner.yaml`
    and its agent produces the file. Under the old predicate the verdict was *whether that
    test had run yet* — red on a clean checkout, green in a full run.

    `check-ignore` answers about the **pattern**, so the file being there or not cannot move
    it. Asserted on a path that exists and one that does not, both covered by the same rule.
    """
    del tmp_path
    root = Path(__file__).resolve().parents[1]
    here = root / "examples" / "minimal" / "greet.py"
    absent = "examples/minimal/greet-that-no-run-has-made.py"

    _, ignored = _tracked_and_ignored(root, ["examples/minimal/greet.py", absent])

    assert "examples/minimal/greet.py" in ignored, (
        "the artefact the citations are about is not covered by .gitignore any more, so the "
        "rule is back to asking whether something put it there")
    assert absent not in ignored, (
        "this floor stopped measuring: `examples/*/greet.py` would have to match this too")
    assert here.exists() or True, "stated: the verdict above did not consult this"


def test_provenance_skips_rather_than_passes_when_git_cannot_answer(tmp_path):
    """A green that measured nothing is the failure this whole file exists to remove.

    Same argument `tools/ledger_check.py` makes for an unresolvable ref: *"on a shallow
    checkout there is nothing to compare and saying so is the whole point"*.
    """
    outside = tmp_path / "not-a-repo"
    outside.mkdir()

    with pytest.raises(BaseException) as raised:
        _tracked_and_ignored(outside, ["examples/minimal/plan.json"])

    said = str(raised.value)
    assert "NOT checked" in said, (
        f"git could not answer and the rule did not say so: {said!r}")
    assert "ls-files" in said and "check-ignore" in said, (
        f"the skip does not name which command could not answer, so a check that stopped "
        f"asking would be indistinguishable from one that asked and was refused: {said!r}")


def test_the_known_gaps_section_exists_and_says_what_it_is_for():
    """**Pinned by a test rather than by a line number** (CHG-20260904-16, conformance seat).

    `ACC-20260823-16` criterion 5 records this section as a governance property, and its
    evidence is `README.md:636-672` with three entries at `:642`, `:647`, `:652`. The section
    is now at 683-737 and those three are at 689, 694, 701 — every citation about 47 lines
    stale. An accepted record pins its own moment, which is right; what it cannot do is keep
    pinning. Nothing else named the section at all.

    What is asserted is what the criterion was about: the section exists, it says why it
    exists, and it is not empty.
    """
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "## Known gaps" in readme, (
        "the section ACC-20260823-16 criterion 5 records as a governance property is gone")
    section = readme.split("## Known gaps")[1].split(chr(10) + "## ")[0]
    flowed = " ".join(section.split())      # the sentence wraps; the claim is not a line
    assert "overstates what it enforces" in flowed, (
        "the section no longer says why it exists, which is the half a reader needs")

    entries = [line for line in section.splitlines()
               if line.startswith("**") or line.startswith("~~**")]
    assert len(entries) >= 5, (
        f"the section names {len(entries)} gaps; it has never named fewer than five, and a "
        f"governance tool that quietly stops saying what it does not enforce is the failure "
        f"this section exists to prevent")


#: The directories a source file may offer a reader a path into. **`config/` as well as
#: `examples/`** (CHG-20260904-19, conformance seat): `settings.py`'s own
#: `DEFAULT_PATH = "config/settings.json"` was neither tracked nor ignored — the exact
#: condition this rule's message calls *the defect this rule was written for* — and it sat
#: one prefix outside the pattern. A cited path is a path a reader is offered; which directory
#: it is in is not the property.
CITED_ROOTS = ("config", "docs", "examples", "tests", "tools")


def paths_cited_in(text):
    """Every path in `text` that a reader is offered as evidence.

    Takes the text so a planted citation can be pointed at it — the scope was widened once
    already and nothing could show the widening mattered, because no live citation sat in the
    directory that had just been added.
    """
    found = []
    for match in re.findall(r"(?:%s)/[\w./-]+" % "|".join(CITED_ROOTS), text):
        what = match.rstrip(".,`")
        if "." in what.rsplit("/", 1)[-1]:      # a bare directory fragment is prose
            found.append(what)
    return found


def test_a_cited_path_is_found_in_every_directory_the_rule_covers():
    """The floor under the widening: a planted citation in each covered root is seen.

    Without it, narrowing `CITED_ROOTS` back to `examples/` alone changed nothing any test
    could see — no live source cites an unresolvable `config/` path, so the revert was
    invisible (CHG-20260904-19).
    """
    # **Derived from what `src/` actually cites, not from `CITED_ROOTS`.** Looping over the
    # constant made this floor shrink with it: narrowing the rule to `examples/` narrowed the
    # loop too, and the revert stayed invisible.
    root = Path(__file__).resolve().parents[1]
    offered = set()
    for path in (root / "src").rglob("*.py"):
        for match in re.findall(r"\b([a-z][\w-]*)/[\w./-]+\.[A-Za-z]{2,5}\b",
                                path.read_text(encoding="utf-8", errors="replace")):
            if (root / match).is_dir():
                offered.add(match)

    assert offered <= set(CITED_ROOTS), (
        f"source files offer a reader paths into {sorted(offered - set(CITED_ROOTS))}, and the "
        f"rule reads {list(CITED_ROOTS)} — a cited path is a path a reader is offered, whichever "
        f"directory it is in")

    for named in sorted(offered):
        planted = "the file lives at `%s/nowhere/plan.json` today" % named
        assert paths_cited_in(planted) == ["%s/nowhere/plan.json" % named], (
            "a citation into %s/ is not seen by the rule" % named)

    assert paths_cited_in("see examples/minimal for the shape") == [], (
        "a bare directory fragment is prose, not a path a reader can open")


def test_every_example_path_a_source_file_cites_exists():
    """**The rule**, because the instance was cited four times and existed nowhere.

    `examples/plan.json` is named by `workorder.py` as the measurement justifying `MAY_BE_EMPTY`
    (*"`expected_outputs` is `[]` on 14 of the 15 nodes"*), by `cli.py` and `conversations.py` as
    the reason project defaulting is refused, and by `test_workorder.py`'s own docstring. `ls
    examples/` gives `README.md demo/ minimal/ tide-spa/ weather-spa/`.

    The **number** was right, for a different file: `examples/minimal/plan.json` has 15 nodes, 14
    with `expected_outputs == []`. So a shipped refusal's justification pointed at a file a reader
    could not open (conformance seat L-53).
    """
    root = Path(__file__).resolve().parents[1]
    cited = set()
    # **Scoped to `src/`.** A source file citing an example path offers it as evidence a
    # reader can check; a test may legitimately *quote* a path that was wrong — which is
    # what this test's own docstring does, and what this rule would otherwise fail itself
    # on. Same reasoning as CHG-20260903-33 excluding the ledger from its scan: a record of
    # what was wrong is doing its job.
    #
    # A citation must also look like a file. A bare directory fragment is prose, not a path.
    for path in (root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for what in paths_cited_in(text):
            cited.add((path.relative_to(root).as_posix(), what))

    # **Provenance, not existence** (CHG-20260904-14, defect seat L-57). This asked
    # `(root / what).exists()`, and `examples/minimal/greet.py` — cited three times by
    # `worktree.py`, every time as an example of a **build artefact** — has never been in the
    # repository. `.gitignore` carries `examples/*/greet.py`. The rule failed on a clean
    # checkout and passed in a full run, because `tests/test_change_classes.py` runs the real
    # CLI against `examples/minimal/runner.yaml` and its agent writes the file, before this
    # file sorts. So a rule whose docstring is *"the instance was cited four times and
    # existed nowhere"* was satisfied by the suite producing the thing it checks for.
    #
    # `.exists()` is neither question worth asking. A citation offers either something a
    # reader who clones can open — **tracked** — or an artefact a run produces, and the
    # `.gitignore` line is where the repository says that on purpose — **ignored**. Anything
    # that is neither is the defect this rule was written for. Existence leaves the predicate,
    # so the answer no longer depends on what ran first.
    tracked, ignored = _tracked_and_ignored(root, sorted({what for _, what in cited}))

    missing = sorted(f"{where}: {what}" for where, what in cited
                     if what not in tracked and what not in ignored)

    assert missing == [], (
        f"these example paths are cited by source as evidence, and git neither tracks them "
        f"nor ignores them — a reader can neither open them nor produce them: {missing}")


def test_the_api_page_documents_the_survey_shape_that_ships():
    """`docs/API.md` was wrong about `survey` in three ways at once.

    §3 documented `"safety": […]` — an array — and omitted `complete` entirely. §4 documented
    `"safety": { "<aspect>": [ … ] }`, and `intake.collect` writes `survey.safety[seat] = unsafe`,
    so a caller keying by aspect matched **nothing, ever** (defect and idiom seats).
    """
    root = Path(__file__).resolve().parents[1]
    page = (root / "docs" / "API.md").read_text(encoding="utf-8")

    from ai_sdlc_runner import intake

    shipped = intake.collect({"defect": {"problems": ["a"], "unsafe": ["b"]}}).as_dict()

    assert isinstance(shipped["safety"], dict)
    assert list(shipped["safety"]) == ["defect"], "safety is keyed by seat"

    for key in sorted(shipped):
        assert f'"{key}"' in page, f"`survey` ships {key!r} and API.md does not document it"
    assert '"safety": { "<aspect>"' not in page, "safety is keyed by seat, not aspect"


def test_the_api_page_does_not_promise_a_null_the_field_cannot_hold():
    """`"error": null | "…"` — `RunState.error` is `str = ""` and `snapshot()` returns it verbatim.

    A caller writing `if (snap.error === null)` treats every idle run as errored. Nine sibling
    fields on the same page correctly document `null` where `null` is what ships, so this was not a
    page-wide convention (conformance seat L-49).
    """
    root = Path(__file__).resolve().parents[1]
    page = (root / "docs" / "API.md").read_text(encoding="utf-8")

    from ai_sdlc_runner import server

    assert server.RunState().snapshot()["error"] == ""
    assert '"error": null' not in page


def test_the_schema_catalogue_counts_the_tables_that_exist():
    """`SCHEMAS.md` said *"3 of 5 tables built"*; `DATABASE.md` said *"6 of 6"*; `store` has six.

    The sharp part is that `SCHEMAS.md`'s own opening paragraph says *"A catalogue of closedness
    that miscounts its own subject is the thing it warns about, so the count is now checked by
    `tests/test_schemas.py` rather than asserted here"* — and that guard covers the **closed-schema**
    count, not the table count, which was checked by nothing (conformance seat L-51).
    """
    root = Path(__file__).resolve().parents[1]
    catalogue = (root / "docs" / "SCHEMAS.md").read_text(encoding="utf-8")

    from ai_sdlc_runner import store

    built = len(store._EXPECTED)
    assert f"{built} of {built} tables" in catalogue, (
        f"store creates {built} tables and the catalogue does not say so")


def test_the_database_page_does_not_call_the_same_table_live_and_dead():
    """It said all six are live, then said two of them are *"created by no code"*, three lines apart.

    Both are in `store._EXPECTED` and among the six `CREATE TABLE IF NOT EXISTS` statements
    (conformance seat L-52).
    """
    root = Path(__file__).resolve().parents[1]
    page = (root / "docs" / "DATABASE.md").read_text(encoding="utf-8")

    live = page.split("It follows the ruling")[0]
    assert "created by no code**:" not in live, (
        "the status paragraph calls a built table uncreated")


def test_the_node_docstring_does_not_state_a_phase_the_field_owns():
    """`graph.Node`'s class docstring said `gate` names the gate *"consulted before the work"*.

    Measured, **seven of the ten** gated nodes are `gate_when="after"` — only `engineer_selfverify`,
    `pr` and `merge` are `before`. Two sentences in one class body, and the one a reader meets first
    was false about most of what it described. (Both seats that reported this got the count wrong,
    one high and one low; it is seven.)
    """
    from ai_sdlc_runner import graph

    gated = [node for node in graph.NODES if node.gate]
    before = [node.id for node in gated if node.gate_when == "before"]

    assert len(gated) == 10 and len(before) == 3, (len(gated), before)
    # Positive, not negative: the corrected docstring *quotes* the old sentence to say why
    # it was wrong, so "the phrase is absent" is the wrong test. What must be true is that
    # the class docstring hands the phase question to the field that owns it.
    said = graph.Node.__doc__ or ""
    assert "gate_when" in said, "the class docstring must name the field that owns the phase"
    assert "answerable to" in said, (
        "the class docstring must say what `gate` names without claiming when it fires")


# --------------------------------------------------------------------------------------
# the words for what a gate does (CHG-20260903-43)
# --------------------------------------------------------------------------------------

#: The claim and the property it requires. `asks` is `confirm` and nothing else — `policy.py` says
#: in as many words that *"a halt is not a question"*, and `ARCHITECTURE.md`'s own legend reads
#: `auto proceeds · confirm asks · halt stops for a person`.
_EVERY_GRADE = (
    ("asks at every", lambda grades: set(grades) == {"confirm"}),
    ("stops at every", lambda grades: all(g != "auto" for g in grades)),
)


def _plain(text):
    """Prose with markdown emphasis removed, and newlines flattened.

    **The first version of the rule below matched literal phrases and found nothing at all in
    `ARCHITECTURE.md`** (CHG-20260903-43): the file writes `**stops** at every grade` and
    `*asks* at every grade`, and an asterisk inside the phrase defeats a literal search. Reverting
    the sentence there left the rule green — it was passing by examining nothing, on the one file
    that had refuted itself. A rule that reads prose has to read it the way a person does.
    """
    for mark in ("**", "*", "`", "_"):
        text = text.replace(mark, "")
    return " ".join(text.split(chr(10) + chr(10) + chr(0)))  # paragraphs kept, see below


def _paragraphs(text):
    """Each paragraph as one flat line, with emphasis stripped — what the rule actually scans."""
    return [" ".join(_plain(block).split()) for block in text.split(chr(10) * 2)]


def _forms(gate):
    """A gate id and the ordinary words a document uses for it.

    **`"merge" is not a substring of "merging"`** — the fifth letter is an `i`. The rule was written
    on the assumption that it is, and stayed green while `ARCHITECTURE.md` said the wrong thing,
    because the document names the act in prose (*merging*) and the policy names it as an id
    (`merge`). The measurement is what settled that; reading the sentence twice did not
    (CHG-20260903-43).
    """
    stem = gate[:-1] if gate.endswith("e") else gate
    return {gate, stem + "ing", stem + "ed", stem + "es", gate + "s"}


def _gate_named_near(text, at, gates):
    """The gate a sentence is about: the last one named before the phrase, within the paragraph."""
    window = text[:at]                          # the paragraph is already the caller's unit
    hits = [(window.rfind(form), gate) for gate in gates for form in _forms(gate)
            if form in window]
    hits = [h for h in hits if h[0] >= 0]
    return max(hits)[1] if hits else None


def test_a_document_may_only_say_asks_at_every_grade_of_a_gate_that_asks_at_every_grade():
    """**Derived from `policy.GATES`, not pinned to two sentences** (CHG-20260903-43).

    `ARCHITECTURE.md` and `logical.md` both said merge *"asks at every grade"*. Measured, merge is
    `confirm` at low and `halt` at medium and high — and `ARCHITECTURE.md` defines the word two
    lines below the sentence that misuses it. Editing the two sentences fixes today; a third
    document brings it back, and `docs/` has had that round already (CHG-20260903-37, six documents
    describing a different program).

    So the claim is checked against the policy that decides it. It holds for gates nobody has
    written about yet, and it goes red if `GATES` changes under a sentence that was true when
    written.
    """
    from ai_sdlc_runner import policy

    wrong = []
    for name, text in _text().items():
        for para in _paragraphs(text):
            for phrase, holds in _EVERY_GRADE:
                at = 0
                while True:
                    at = para.find(phrase, at)
                    if at < 0:
                        break
                    gate = _gate_named_near(para, at, policy.GATES)
                    if gate and not holds(policy.GATES[gate].values()):
                        wrong.append(f"{name}: {phrase!r} of {gate!r}, which is "
                                     f"{dict(policy.GATES[gate])}")
                    at += len(phrase)

    assert wrong == [], (
        "these describe a gate with a word the policy contradicts — `asks` is `confirm`, and "
        f"anything that is not `auto` `stops`: {wrong}")


def test_the_rule_can_tell_the_two_claims_apart():
    """**The floor.** Without it the rule passes by matching nothing, which is how a rule dies.

    Measured on the real policy: **no gate is all-`confirm`**, so "asks at every grade" is currently
    unsayable of any of the ten — and `merge` is the **only** all-stopping one, so the sentence the
    documents now carry is not merely accurate but uniquely so.
    """
    from ai_sdlc_runner import policy

    asks, stops = dict(_EVERY_GRADE)["asks at every"], dict(_EVERY_GRADE)["stops at every"]
    GATES_ = policy.GATES

    assert not [g for g, v in policy.GATES.items() if asks(v.values())], (
        "a gate became all-`confirm`; the rule above now permits “asks at every grade” of it, which "
        "is correct — update this floor rather than deleting it")
    assert [g for g, v in policy.GATES.items() if stops(v.values())] == ["merge"], (
        "`merge` is no longer the only gate that stops at every grade, and the documents say it is")

    # And both directions on planted grades, so the rule is known to be capable of firing.
    assert asks({"confirm", "confirm"}) and not asks({"confirm", "halt"})
    assert stops({"confirm", "halt"}) and not stops({"auto", "halt"})

    # And the gate has to be findable in prose, which is where this rule was silently
    # passing: a document writes *merging*, the policy writes `merge`, and one is not a
    # substring of the other.
    assert _gate_named_near("merging is a one-way door, so it ", 36, GATES_) == "merge"
    assert _gate_named_near("nothing here names a gate ", 20, GATES_) is None


# ── a citation in the source resolves to something (CHG-20260904-04) ────────────────────

#: What a comment or a docstring says, with a name for where it said it. **The scope of the
#: citation rule, stated rather than approximated** (CHG-20260904-10).
#:
#: `line N column M` is a parser's position report, not a citation: `paths.py` quotes `json`'s own
#: `Expecting value: line 1 column 1` in the docstring explaining why `read_text` exists. Widening
#: the scope to docstring bodies brought it in range, and exempting it by name would be an
#: allowlist; the rule is that `column` following the number is what tells a machine's position
#: from a reference to this source.
CITATIONS = (re.compile(r"[a-z_]+\.py:(\d+)"), re.compile(r"\bline (\d+)\b(?! column)"))

#: The nodes a docstring can hang from.
_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def prose_of(source: str, name: str):
    """Every comment and every docstring **body** in `source`, each with where it was written.

    The scope this replaces was: the line starts with `#`, or the line contains a triple quote.
    That admits a comment and a docstring's opening or closing line, and **nothing in between** —
    demonstrated by planting a banned sentence as the *second* line of a docstring, which passed
    (CHG-20260904-10, defect seat L-41). Scoping to prose was and remains necessary; what changes
    is that `tokenize` and `ast` say what prose is, rather than what one line happens to look like.
    """
    found = []
    with io.StringIO(source) as handle:
        for token in tokenize.generate_tokens(handle.readline):
            if token.type == tokenize.COMMENT:
                found.append((f"{name} comment at line {token.start[0]}", token.string))
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, _HOLDERS):
            text = ast.get_docstring(node, clean=False)
            if text:
                where = getattr(node, "name", None) or name
                found.append((f"{name} docstring of {where}", text))
    return found


BANNED_SENTENCE = "The dispatcher for this is engine.py " + "line" + " 2110, which is the guard."
PARSER_MESSAGE = "Expecting value: " + "line" + " 1 column 1"


def test_the_citation_rule_reads_a_docstring_past_its_first_line():
    """**The scope was an accident of a filter, and this is the floor under the new one.**

    Planted as the *second* line of a docstring, the sentence the rule exists to ban passed:
    the scope admitted a line starting with `#` or containing a triple quote, which is a
    docstring's opening and closing lines and nothing between them (defect seat L-41).

    Both directions are asserted, because a rule that catches everything is not a rule: the
    parser's own position report has to survive it, and it is the reason scoping to prose was
    needed in the first place.
    """
    planted = (
        '"""A node in the flow.\n\n    %s\n    """\n'
        "\n"
        "VALUE = 1\n" % BANNED_SENTENCE)
    cited = [c for where, text in prose_of(planted, "planted.py")
             for pattern in CITATIONS for c in pattern.findall(text)]
    assert cited == ["2110"], (
        f"a citation on the second line of a docstring was not seen: {cited}")

    quoted = (
        '"""Why this function exists.\n\n    The file came out empty and json died on\n'
        "    `%s`.\n" % PARSER_MESSAGE
        + '    """\n')
    survived = [c for where, text in prose_of(quoted, "quoted.py")
                for pattern in CITATIONS for c in pattern.findall(text)]
    assert survived == [], (
        f"a parser's own position report was read as a citation into this source: {survived}")


def test_no_comment_in_the_source_cites_a_line_number():
    """**Name the symbol, not the line** (CHG-20260904-04, defect seat L-18).

    Two `<module>.py:<n>` citations in `src/` were wrong **at the commit that wrote them**:

        server.py:323   claimed the sole `Approval` mint site   was `self._refresh_attachments()`
        cli.py:1228     claimed the split-programme refusal     was a docstring line

    `CHG-20260903-44` inserted `_answering` immediately above `approve` and wrote that address in
    the same commit; `CHG-20260903-41` inserted `_declare_classes` above `_change_classes` and did
    the same. **Both point into the function that displaced them.**

    The first version of this rule required a citation to land on a non-blank, non-comment line —
    and both of the cases above land on **real code**, so it permitted exactly the defect it was
    written for. A line number cannot be verified without a companion string, which is the
    conclusion this ledger already reached for change records. So the rule is the stronger and
    simpler one: **`src/` does not cite line numbers.** A symbol name is greppable, survives
    insertions above it, and says what the number was standing in for.

    `docs/` is out of scope here: a change record is a statement about a moment and pins its own
    sha. This is about comments in code, which are read at whatever the file says today.
    """
    offenders = []
    # **Two spellings, not one** (CHG-20260904-06, defect seat L-23). The first version
    # required `.py:` immediately before the digits, and `plan.py` says *"`engine.py` joins
    # any `--instruction` text onto the node spec's own, and **line 515** reads …"* — a
    # citation rotten for twelve days that the rule walked past. `ACC-20260904-04`
    # reservation 1 said *"the rule bans a pattern that now appears nowhere"*; measured, it
    # appeared, in a spelling the rule could not see.
    # **Two patterns, no window** (CHG-20260904-06, defect seat L-23). The first version
    # required `.py:` immediately before the digits; the second allowed 60 characters of
    # gap. The live case — `plan.py` saying *"`engine.py` joins … and **line 515** reads"*,
    # rotten for twelve days — sits 62 characters apart and **across two lines**. Tuning the
    # window is the wrong move: what makes a citation a citation is the number, not its
    # distance from a filename. `ACC-20260904-04` reservation 1 said the banned pattern
    # *"appears nowhere"*; it appeared, in a spelling the rule could not see.
    for path in sorted((ROOT / "src" / "ai_sdlc_runner").glob("*.py")):
        for where, text in prose_of(path.read_text(encoding="utf-8"), path.name):
            for pattern in CITATIONS:
                for cited in pattern.findall(text):
                    offenders.append(f"{where} cites line {cited}")

    assert offenders == [], (
        "these name a line number, which the next insertion above it makes wrong — name the "
        f"function, the class or the constant instead: {offenders}")


# --------------------------------------------------------------------------------------
# CHG-20260905-02 — an id a reader arrives with must land somewhere
# --------------------------------------------------------------------------------------

#: A requirement id as `src/` writes it: `D6.2`, `D7.1`. The design documents number their rules
#: this way and the code cites them by number, which only works if the number is written down
#: somewhere as a label rather than being the position of an item in an unlabelled list.
REQUIREMENT_ID = re.compile(r"\bD\d+\.\d+\b")


def requirement_ids_in(text):
    """Every requirement id cited in `text`, in order, without duplicates.

    Takes the text rather than a path so a planted citation can be pointed at it. The rule was
    written because `D6.2` had exactly one line binding it and `D6.3`–`D6.5` had none; a guard that
    could only be run against the live tree would have had nothing to prove it worked.
    """
    seen = []
    for match in REQUIREMENT_ID.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def labelled_ids_in(text):
    """Every requirement id `text` defines as a **label** a reader can find.

    A definition is a bold label at the **start of a line** — a list item or a heading. Matching
    the same bold anywhere on a line made prose *about* the rule count as a definition: the
    acceptance record for CHG-20260905-02 quoted the pattern while explaining what it matches,
    and that one sentence was enough to keep the guard below green against the label being
    deleted from the ledger. A guard whose subject is the text rather than the property, fed by
    its own author's account of the defect.
    """
    return set(re.findall(r"(?m)^\s*(?:\d+\.\s+)?\*\*(D\d+\.\d+)\b", text))


def test_every_requirement_id_the_source_cites_can_be_looked_up():
    """A citation in `src/` must resolve to a labelled item, not to a position in a list.

    `effects.py`, `probes.py` and `ship.py` cite `D6.2`, `D6.3`, `D6.4` and `D6.5`. `D6.2` was
    reachable only through a single back-reference line in `CHG-20260822-04.md` — delete that one
    line and four modules cite an id that is nowhere. The other three were resolvable only by
    counting items in an unlabelled ordered list (CHG-20260905-02, round-11 conformance seat).
    """
    root = ROOT
    cited = {}
    for path in sorted((root / "src").rglob("*.py")):
        for what in requirement_ids_in(path.read_text(encoding="utf-8", errors="replace")):
            cited.setdefault(what, []).append(path.name)

    assert cited, "no requirement id is cited anywhere in src/ — the rule now guards nothing"

    labelled = set()
    for path in sorted((root / "docs").rglob("*.md")):
        labelled |= labelled_ids_in(path.read_text(encoding="utf-8", errors="replace"))

    unresolvable = {k: v for k, v in cited.items() if k not in labelled}
    assert not unresolvable, (
        "these ids are cited in src/ and are written down nowhere as a label a reader can find: "
        "%s" % unresolvable)


def test_the_id_rule_can_see_an_id_that_lands_nowhere():
    """The floor. Without it the guard above passes whenever its two searches both find nothing."""
    assert requirement_ids_in("this rests on D6.2 and on D9.7") == ["D6.2", "D9.7"]
    assert requirement_ids_in("no ids here at all") == []

    defines = "2. **D6.2 - effect admissibility rule**: an operation may be an effect only if"
    assert labelled_ids_in(defines) == {"D6.2"}
    assert labelled_ids_in("- **No effect without a probeable postcondition** (D6.2).") == set(), (
        "a mention in passing was counted as a definition, which is how the id had one way in")

    # Assembled from fragments so this file never contains the thing it forbids — the plant is
    # what the acceptance record accidentally wrote in prose, which is how this case was found.
    quoted = "the rule reads " + "*" + "*D6.2" + " where a label starts a line"
    assert labelled_ids_in(quoted) == set(), (
        "prose explaining the rule counted as a definition of the id it happens to mention")


def test_the_effects_report_row_names_every_field_the_outcome_carries():
    """Driven off `as_dict()`, so a fifth field makes the row wrong until somebody writes it.

    The row described three of four: `frontier` — where a resume started — was missing. A row
    listing the fields by hand is a copy of the truth, and copies drift (CHG-20260905-02).
    """
    from ai_sdlc_runner import effects

    root = ROOT
    data = (root / "docs" / "structure" / "data.md").read_text(encoding="utf-8")
    row = next((ln for ln in data.split("\n") if ln.startswith("| `effects` |")), None)
    assert row, "docs/structure/data.md no longer has a row for the `effects` report field"

    carried = effects.EffectOutcome().as_dict()
    assert len(carried) >= 4, "the outcome shrank; this guard was written against four fields"
    missing = [k for k in carried if "`%s`" % k not in row]
    assert not missing, (
        "the `effects` row does not name %s, which `EffectOutcome.as_dict()` writes" % missing)


# --------------------------------------------------------------------------------------
# CHG-20260905-05 — two documents disagreeing about what the package is
# --------------------------------------------------------------------------------------

#: Documents that present themselves as listing the package's modules. Both were incomplete and
#: incomplete *differently* — `directory.md` named 10 of 20 and the README's own block named 12 —
#: so a reader comparing them would have found two answers and no way to tell which was the
#: package (CHG-20260905-05). The conformance seat reported the README as already correct; it was
#: not, which is why this compares both against `src/` rather than one against the other.
INVENTORIES = ("docs/structure/directory.md", "README.md")


def modules_in_the_package(root):
    """Every module `src/ai_sdlc_runner/` actually holds."""
    return sorted(p.name for p in (root / "src" / "ai_sdlc_runner").glob("*.py")
                  if p.name != "__init__.py")


def modules_missing_from(text, modules):
    """Which of `modules` this document never names."""
    return [m for m in modules if m not in text]


def test_every_module_in_the_package_is_in_the_documents_that_list_them():
    modules = modules_in_the_package(ROOT)
    assert len(modules) > 10, "the package shrank; this guard was written against twenty modules"

    for where in INVENTORIES:
        text = (ROOT / where).read_text(encoding="utf-8", errors="replace")
        missing = modules_missing_from(text, modules)
        assert not missing, (
            "%s presents a list of the package's modules and does not name %s" % (where, missing))


def test_the_inventory_guard_can_see_a_module_that_is_missing_from_a_list():
    """The floor. Both searches are substring searches over a document, and a rule whose two halves
    can each come back empty passes hardest when it is measuring nothing."""
    assert modules_missing_from("this lists policy.py and graph.py",
                                ["policy.py", "graph.py"]) == []
    assert modules_missing_from("this lists policy.py only",
                                ["policy.py", "graph.py"]) == ["graph.py"]
    assert modules_in_the_package(ROOT), "no modules found in src/ — the guard measures nothing"


#: A change id as `src/` writes it. 104 distinct ones are cited across the package, and until now
#: nothing checked that any of them resolved: `test_every_requirement_id_the_source_cites_can_be_
#: looked_up` matches the `D<n>.<n>` form only, and `attachments.py` — the module whose review
#: found this — cites no `D`-form id at all (CHG-20260905-05).
CHANGE_ID = re.compile(r"\b((?:CHG|ACC)-\d{8}-\d{2})\b")


#: A citation that carries its own destination: `[CHG-…](some/path.md)`.
LINKED_ID = re.compile(r"\[((?:CHG|ACC)-\d{8}-\d{2})\]\(([^)]+)\)")


def change_ids_in(text):
    """Every change id cited in `text`, without duplicates, in order."""
    seen = []
    for match in CHANGE_ID.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def followable_links_in(text, source):
    """Ids whose citation carries a link a reader can actually open, relative to `source`.

    The first version of the rule below asked whether `docs/changes/<id>.md` exists, and called
    `store.py`'s `[CHG-20260823-19](../../docs/design/sqlite-only.md)` unresolvable — while a reader
    clicking it lands on the ruling, in a document that carries the id itself. The rule's subject
    was the **record file**; the property is whether the reader can follow it (CHG-20260905-05).
    """
    found = set()
    for what, href in LINKED_ID.findall(text):
        if (source.parent / href).resolve().exists():
            found.add(what)
    return found


def unresolvable_among(cited, records, followable):
    """The ids a reader can do nothing with: no record, and no link they can open.

    Extracted so a planted id can be pointed at it. Left inline, the rule was unfalsifiable — every
    id in the live tree resolves, so a mutation that made *everything* resolve changed nothing any
    test could see, and reported NOT CAUGHT against a rule that was working (CHG-20260905-05).
    """
    return {what: where for what, where in cited.items()
            if what not in records and what not in followable}


def test_every_change_id_the_source_cites_has_a_record():
    """A citation a reader cannot follow is not evidence — the same rule `D6.2` got, for the id form
    this repository overwhelmingly uses."""
    cited = {}
    followable = set()
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        followable |= followable_links_in(text, path)
        for what in change_ids_in(text):
            cited.setdefault(what, []).append(path.name)

    assert len(cited) > 50, "no change ids found in src/ — the rule guards nothing"

    have = {p.stem for p in (ROOT / "docs" / "changes").glob("CHG-*.md")}
    have |= {p.stem for p in (ROOT / "docs" / "acceptance").glob("ACC-*.md")}
    have |= followable
    unresolvable = unresolvable_among(cited, have, followable)
    assert not unresolvable, (
        "these change ids are cited in src/ and have no record and no link a reader can open: "
        "%s" % unresolvable)


def test_the_record_rule_can_see_a_citation_with_no_record():
    """The floor under it, planted rather than found."""
    assert change_ids_in("as CHG-20260823-11 says, and ACC-20260823-11 agreed") == [
        "CHG-20260823-11", "ACC-20260823-11"]
    assert change_ids_in("no ids here") == []
    assert change_ids_in("CHG-2026 is not one, nor is CHG-20260823-1") == []

    here = pathlib.Path(__file__)
    assert followable_links_in("see [CHG-20260823-11](nowhere/at/all.md)", here) == set(), (
        "a link nobody can open counted as a way to follow the citation")
    assert followable_links_in(
        "see [CHG-20260823-11](%s)" % here.name, here) == {"CHG-20260823-11"}

    # The resolution itself, planted: one id with a record, one with only a link, one with neither.
    cited = {"CHG-1": ["a.py"], "CHG-2": ["b.py"], "CHG-3": ["c.py"]}
    assert unresolvable_among(cited, {"CHG-1"}, {"CHG-2"}) == {"CHG-3": ["c.py"]}
    assert unresolvable_among(cited, set(), set()) == cited, (
        "an id with neither a record nor a link was treated as resolvable")
