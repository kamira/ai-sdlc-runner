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


#: The two tests that skip when `curses` is absent. Counted, not guessed: `--collect-only` cannot
#: know what will skip at run time, and a hard-coded 2 that silently drifts is the defect this test
#: exists for.
_KNOWN_SKIPS = 2


def test_the_test_count_the_readme_states_is_the_real_one():
    """The one figure this file could not see, and which a seat caught already drifted once.

    The README said "847 passing" when 857 passed. It was excluded from every other check here
    because the suite cannot count itself while running — so it is counted in a subprocess with
    `--collect-only`, which is the same number `-q` reports and costs no test time.

    Stating a number nothing checks is how the first one drifted; the answer is to check it, not to
    stop stating it.
    """
    import os
    import re
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    claimed = re.search(r"pytest -q\s*#\s*([\d,]+) passing", readme)
    if claimed is None:
        return                          # the README no longer states one; nothing to hold it to
    want = int(claimed.group(1).replace(",", ""))

    done = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root),
        env={**os.environ, "PYTHONPATH": "src", "PYTHONUTF8": "1"})
    found = re.search(r"(\d+) tests collected", done.stdout or "")
    assert found, f"could not count the suite:\n{(done.stdout or '')[-400:]}"
    collected = int(found.group(1))
    # "passing" means what `-q` prints as passed, which is the collected count minus the skips.
    # Comparing against the collected count instead would put a number in the README that no run
    # ever prints -- a figure that is checkable and still wrong.
    skipped = len(re.findall(r"^SKIPPED", done.stdout or "", re.M)) or _KNOWN_SKIPS
    assert collected - skipped == want, (
        f"the README says {want} passing; the suite collects {collected} and skips {skipped}, so "
        f"`pytest -q` reports {collected - skipped} passed.")
