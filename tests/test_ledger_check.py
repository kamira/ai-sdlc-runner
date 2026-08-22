"""Our own ledger lint (CHG-20260823-01).

Replaces a gate that lived inside the vendored skill. Two of its three checks exist because the old
one got them wrong here, so both failures are reproduced rather than assumed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ledger_check  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _repo(tmp_path, chg_body, acc=None):
    (tmp_path / "docs" / "changes").mkdir(parents=True)
    (tmp_path / "docs" / "acceptance").mkdir(parents=True)
    (tmp_path / "docs" / "changes" / "CHG-20260901-01.md").write_text(chg_body, encoding="utf-8")
    if acc:
        (tmp_path / "docs" / "acceptance" / "ACC-20260901-01.md").write_text(acc, encoding="utf-8")
    return tmp_path


HEADER = "- Project: x\n- Branch: b\n- Date: 2026-09-01\n- Risk: low\n"


def test_this_repos_own_ledger_passes():
    assert ledger_check.check(REPO) == []


def test_a_change_reported_built_without_an_acceptance_record_fails(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nbuilt and shipped.\n")
    problems = ledger_check.check(repo)
    assert any("no matching ACC" in p or "nothing saying it was checked" in p for p in problems)


def test_the_same_change_passes_once_it_has_one(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nbuilt and shipped.\n", acc="# ACC\n")
    assert ledger_check.check(repo) == []


def test_a_draft_needs_no_acceptance_record(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\ndraft — nothing built yet.\n")
    assert ledger_check.check(repo) == []


def test_prose_about_acceptance_does_not_change_a_documents_status(tmp_path):
    """The failure this lint was rewritten to stop. The previous gate scanned the whole document, so
    writing the word in a paragraph flipped the classification — three times in one session, twice
    inside the sentence explaining the first time. Status is a field; this reads the field."""
    body = (HEADER +
            "\n## Independent review\n\nThe first round was not accepted, and every task is built.\n"
            "\n## Status\n\ndraft — nothing built yet.\n")
    assert ledger_check.check(_repo(tmp_path, body)) == []


def test_a_missing_required_field_is_reported(tmp_path):
    repo = _repo(tmp_path, "- Project: x\n- Date: 2026-09-01\n\n## Status\n\ndraft.\n")
    problems = ledger_check.check(repo)
    assert any("Risk" in p and "Branch" in p for p in problems)


def test_the_field_rule_is_prospective(tmp_path):
    """A lint that fails on history it cannot change teaches people to ignore the lint."""
    (tmp_path / "docs" / "changes").mkdir(parents=True)
    (tmp_path / "docs" / "acceptance").mkdir(parents=True)
    (tmp_path / "docs" / "changes" / "CHG-20260101-01.md").write_text(
        "- Project: x\n- Date: 2026-01-01\n- Risk: low\n\n## Status\n\ndraft.\n", encoding="utf-8")
    assert ledger_check.check(tmp_path) == []


def test_a_change_with_no_status_section_is_reported(tmp_path):
    assert any("no Status section" in p
               for p in ledger_check.check(_repo(tmp_path, HEADER)))
