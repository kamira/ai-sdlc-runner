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


# --------------------------------------------------------------------------------------
# the vocabulary of "finished" is closed
# --------------------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.mark.parametrize("status", ["accepted", "completed", "merged", "完成", "done", "shipped",
                                    "closed", "已驗收", "released"])
def test_every_way_of_saying_finished_needs_an_acceptance(tmp_path, status):
    """The finding this closes: the lint knew only the word "built", so a change whose status said
    "accepted" or "完成" passed with no ACC at all — a false green written in one word."""
    repo = _repo(tmp_path, HEADER + f"\n## Status\n\n{status}\n")
    problems = ledger_check.check(repo)
    assert any("nothing saying it was checked" in p for p in problems), status


@pytest.mark.parametrize("status", ["draft", "in progress", "blocked", "草稿", "進行中",
                                    "superseded", "pending"])
def test_an_unfinished_change_needs_nothing(tmp_path, status):
    repo = _repo(tmp_path, HEADER + f"\n## Status\n\n{status}\n")
    assert ledger_check.check(repo) == []


def test_a_status_nobody_wrote_down_is_a_problem_not_a_pass(tmp_path):
    """The escape hatch itself: treating an unrecognised word as "not finished" is how the previous
    version let four different words through. An unknown status is now a failure that names the fix.
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nfine\n")
    problems = ledger_check.check(repo)
    assert any("not a recognised one" in p for p in problems)
    assert any("ledger_check.py" in p for p in problems)


def test_the_commentary_after_the_status_does_not_decide_the_status(tmp_path):
    """`draft — all 9 tasks built` is a draft. The status is the head of the line; the rest is
    prose, and prose has changed this repo's document classification before."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**草稿 / draft — all 9 tasks built.**\n")
    assert ledger_check.check(repo) == []


def test_a_finished_status_with_commentary_still_needs_its_acceptance(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\naccepted (see the ACC) — everything green.\n")
    assert any("nothing saying it was checked" in p for p in ledger_check.check(repo))


def test_a_status_that_reads_both_ways_is_refused(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\ndraft done\n")
    assert any("cannot act on it" in p for p in ledger_check.check(repo))


def test_the_two_lists_do_not_overlap():
    """A word on both lists would make every status using it ambiguous, forever."""
    assert not set(ledger_check.DONE) & set(ledger_check.IN_PROGRESS)


# ── the other direction, which nothing walked (CHG-20260828-02) ─────────────────────────────────

def test_an_acceptance_for_a_change_that_does_not_exist_is_refused(tmp_path):
    """Every check above starts at a CHG, so an ACC naming no change was invisible.

    The ledger reported `passed` while an acceptance vouched for nothing. Traceability is the whole
    reason both files are kept, and it only holds if it holds both ways.
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nProposed.\n")
    (repo / "docs" / "acceptance" / "ACC-19990101-01.md").write_text(
        "# ACC-19990101-01\n\n- Target CHG: CHG-19990101-01\n", encoding="utf-8")
    problems = ledger_check.check(repo)
    assert any("ACC-19990101-01" in p and "no change" in p for p in problems), problems


def test_an_acceptance_filed_against_the_wrong_change_is_refused(tmp_path):
    """A record filed under one id while claiming another points two ways, and a reader following
    either lands somewhere the other contradicts."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nAccepted.\n",
                 acc="# ACC-20260901-01\n\n- Target CHG: CHG-20260714-09\n")
    problems = ledger_check.check(repo)
    assert any("Target CHG" in p for p in problems), problems


def test_an_acceptance_that_names_no_target_is_not_a_problem(tmp_path):
    """Absence is not disagreement. Older records predate the field, and requiring it would turn a
    traceability check into a formatting one — which is how a useful check gets switched off."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nAccepted.\n",
                 acc="# ACC-20260901-01\n\nNo target line at all.\n")
    assert ledger_check.check(repo) == []


def test_a_matching_pair_is_still_accepted(tmp_path):
    """The check must not fire on the normal case — it would refuse every real acceptance."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nAccepted.\n",
                 acc="# ACC-20260901-01\n\n- Target CHG: CHG-20260901-01\n")
    assert ledger_check.check(repo) == []


# ── two changes wearing one number (CHG-20260828-06) ────────────────────────────────────────────

HEADER_06 = "- Project: x\n- Branch: b\n- Date: 2026-09-01\n- Risk: low\n"


def _git_repo(tmp_path, title):
    """A repository with one change on `main`, so a branch can be compared against it."""
    import subprocess
    root = tmp_path / "repo"
    (root / "docs" / "changes").mkdir(parents=True)
    (root / "docs" / "acceptance").mkdir(parents=True)
    (root / "docs" / "changes" / "CHG-20260901-01.md").write_text(
        f"# {title}\n\n{HEADER_06}\n## Status\n\nProposed.\n", encoding="utf-8")

    def git(*args):
        subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "T")
    git("config", "user.email", "t@example.invalid")
    git("add", "-A")
    git("commit", "-q", "-m", "one change")
    return root


def test_a_second_change_taking_a_taken_id_is_refused(tmp_path):
    """The collision that happened, and that nothing could see.

    A number is claimed by writing the file, and nothing reserves one. Two sessions pick from the
    same free list, and `check` cannot notice: two files with one name cannot coexist in a tree, so
    it surfaces only as a merge conflict — after both branches have gone green separately.

    CHG-20260828-04 was claimed at 12:23 by an unmerged branch and again at 13:00 by a change that
    merged. Two records, one number, both passing every check that existed. The second was
    renumbered by hand afterwards; this check is what makes that unnecessary next time.
    """
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    (root / "docs" / "changes" / "CHG-20260901-01.md").write_text(
        f"# CHG-20260901-01 — a completely different change\n\n{HEADER_06}\n## Status\n\nProposed.\n",
        encoding="utf-8")

    problems = ledger_check.check_ids_are_not_claimed_twice(root, "main")
    assert problems, "two changes wearing one number went unnoticed"
    assert "wearing one number" in problems[0]
    assert "a completely different change" in problems[0], "it must name both titles"


def test_editing_an_existing_record_is_not_a_collision(tmp_path):
    """Editing a record is not claiming one, and this fires on every PR that touches a CHG.

    CHG-20260827-21 gained two whole sections after it was accepted — task 5a and task 6 — and a
    check that called that a collision would refuse the ordinary way this ledger is kept.
    """
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    path = root / "docs" / "changes" / "CHG-20260901-01.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## A section added later\n\nMore.\n",
                    encoding="utf-8")

    assert ledger_check.check_ids_are_not_claimed_twice(root, "main") == []


def test_a_genuinely_new_id_is_not_a_collision(tmp_path):
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    (root / "docs" / "changes" / "CHG-20260901-02.md").write_text(
        f"# CHG-20260901-02 — the next one\n\n{HEADER_06}\n## Status\n\nProposed.\n",
        encoding="utf-8")

    assert ledger_check.check_ids_are_not_claimed_twice(root, "main") == []


def test_a_ref_that_does_not_resolve_checks_nothing_rather_than_passing_quietly(tmp_path, capsys):
    """On a shallow checkout there is nothing to compare against, and saying so is the point.

    A check that quietly does nothing is worse than one scoped out loud — this repository's own
    finding about `--sandbox`, applied to a lint.
    """
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    assert ledger_check.check_ids_are_not_claimed_twice(root, "origin/nonexistent") == []

    # And through `main`, which has to find nothing to compare against — so a plain directory,
    # not the repository above: that one has a `main` and would be checked normally, which is the
    # correct behaviour and the wrong test.
    plain = _repo(tmp_path / "plain", HEADER + "\n## Status\n\nProposed.\n")
    ledger_check.main(["--repo", str(plain)])
    said = capsys.readouterr().out
    assert "was NOT checked" in said, said
    assert "Fetch the default branch" in said, "it must say how to get the check back"
