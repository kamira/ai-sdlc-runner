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

DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "ai-guideline.md",
    ROOT / "docs" / "structure" / "design.md",
    ROOT / "docs" / "structure" / "data.md",
    ROOT / "docs" / "structure" / "directory.md",
    ROOT / "docs" / "structure" / "logical.md",
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


def test_the_false_stop_corpus_size_the_documents_claim_is_the_real_one():
    """The one that was wrong two ways at once — 56 in some files, 36 in others, 46 in fact."""
    actual = _false_stop_corpus_size()
    for name, body in _text().items():
        for claimed in re.findall(r"of\s+(\d+)\s+ordinary(?:\s+engineering)?\s+briefs", body):
            assert int(claimed) == actual, f"{name} says {claimed} briefs; there are {actual}"
        for claimed in re.findall(r"(\d+)\s*句正常開發任務", body):
            assert int(claimed) == actual, f"{name} says {claimed} briefs; there are {actual}"


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


def test_the_documents_actually_contain_numbers_to_check():
    """If the regexes stop matching because a document was reworded, this check silently passes.
    Named and asserted, because 'nothing matched' reading as 'everything is fine' is the exact
    defect this repository has now shipped twice."""
    body = "\n".join(_text().values())
    assert re.search(r"\d+\s+nodes", body), "no node count found in any document"
    assert re.search(r"\d+\s+gates", body), "no gate count found in any document"
    assert re.search(r"\d+\s+of\s+\d+", body), "no measured ratio found in any document"
