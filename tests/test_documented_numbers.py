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

import re
import sys
from pathlib import Path

import pytest

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
        for match in re.findall(r"examples/[\w./-]+", text):
            what = match.rstrip(".,`")
            if "." in what.rsplit("/", 1)[-1]:
                cited.add((path.relative_to(root).as_posix(), what))

    missing = sorted(f"{where}: {what}" for where, what in cited
                     if not (root / what).exists())

    assert missing == [], (
        f"these example paths are cited by source as evidence and do not exist: {missing}")


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
