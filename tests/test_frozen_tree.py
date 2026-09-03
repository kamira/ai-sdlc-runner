"""KN-14 with a mechanism behind it (CHG-20260827-13).

The rule — *freeze the tree before verification* — was a paragraph for as long as it existed, and
the acceptance round of 2026-08-27 broke it while closing forty-seven changes. These tests are what
stops `tools/frozen_tree.py` from becoming another paragraph: a check nobody has watched fail is a
check nobody should rely on.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import frozen_tree  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path) -> Path:
    """A real git repository with one commit. Real, because the tool shells out to git and a fake
    would be testing the fake."""
    def git(*args):
        done = subprocess.run(["git", *args], cwd=str(tmp_path), capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return done.stdout

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (tmp_path / "kept.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("built/\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "first")
    return tmp_path


def test_a_clean_tree_reports_the_commit_it_is_frozen_at(tmp_path, capsys):
    repo = _repo(tmp_path)
    assert frozen_tree.main(["--repo", str(repo)]) == 0
    printed = capsys.readouterr().out.strip()
    assert len(printed) == 40 and all(c in "0123456789abcdef" for c in printed), printed


def test_a_dirty_tree_is_refused_and_the_files_are_named(tmp_path, capsys):
    """Naming them is half the point. "something changed" sends a verifier hunting."""
    repo = _repo(tmp_path)
    (repo / "kept.txt").write_text("two\n", encoding="utf-8")

    assert frozen_tree.main(["--repo", str(repo)]) == 1
    said = capsys.readouterr().out
    assert "NOT frozen" in said
    assert "kept.txt" in said, said
    assert "KN-14" in said, "the refusal should say which rule it is enforcing"


def test_an_uncommitted_new_file_counts_as_dirty(tmp_path, capsys):
    """The shape the acceptance round actually hit: a verifier's scratch edit, never committed.

    A file nobody has committed is a file the next reader of this sha will not have, which is the
    ambiguity a frozen tree exists to remove.
    """
    repo = _repo(tmp_path)
    (repo / "scratch.py").write_text("# a verifier's experiment\n", encoding="utf-8")

    assert frozen_tree.main(["--repo", str(repo)]) == 1
    assert "scratch.py" in capsys.readouterr().out


def test_what_git_ignores_does_not_fail_a_round(tmp_path, capsys):
    """The over-refusal direction. A check that fires on build output is one people switch off —
    KN-13, and the reason this tool is not a commit hook."""
    repo = _repo(tmp_path)
    (repo / "built").mkdir()
    (repo / "built" / "artefact.bin").write_text("x", encoding="utf-8")

    assert frozen_tree.main(["--repo", str(repo)]) == 0, capsys.readouterr().out


def test_not_being_able_to_tell_is_not_the_same_as_clean(tmp_path, capsys):
    """Exit 2, not 0. "I could not answer" reading as "it is fine" is how a check becomes a
    formality — the same false-green this repository has shipped in three other shapes."""
    assert frozen_tree.main(["--repo", str(tmp_path)]) == 2
    assert "cannot tell" in capsys.readouterr().out


def test_the_dirty_branch_is_what_produces_the_refusal(tmp_path):
    """Proof the check can fail for the reason it claims, not merely that it returns 1.

    `state()` is what the round would read; this asserts it reports the path rather than the tool
    happening to exit non-zero for some other reason.
    """
    repo = _repo(tmp_path)
    head, clean = frozen_tree.state(repo)
    assert clean == []

    (repo / "kept.txt").write_text("changed\n", encoding="utf-8")
    still_head, dirty = frozen_tree.state(repo)
    assert still_head == head, "the commit does not move when the tree is edited"
    assert dirty == ["kept.txt"]


def test_kn14_names_the_tool_so_the_rule_is_no_longer_only_advice():
    """The rule and the mechanism have to know about each other, or the next reader finds the
    paragraph and not the check."""
    knowledge = (ROOT / "docs" / "knowledge" / "knowledge.md").read_text(encoding="utf-8")
    assert "frozen_tree.py" in knowledge, (
        "KN-14 does not name the tool that enforces it, which leaves it reading as advice")


# ── a staged rename is not one path with an arrow (CHG-20260903-36) ─────────────────────────────


def test_a_staged_rename_yields_both_paths_and_invents_neither():
    """`--porcelain` without `-z` renders a staged rename on ONE line as `R  <old> -> <new>`.

    `line[3:]` therefore produced `'LICENSE -> LICENCE.txt'` — a single string that is not a
    filename, and neither of the two real paths. This function's own docstring promises *"the paths
    that differ from it"* and *"name the files when it is not"*, in the tool a verification round
    runs to decide whether it may proceed.

    `CHG-20260903-31` fixed this exact shape in `worktree.uncommitted()` and swept no further
    (conformance seat L-54).
    """
    raw = "R  LICENSE\0LICENCE.txt\0 M agent.py\0"

    paths = sorted(frozen_tree._porcelain_paths(raw))

    assert paths == ["LICENCE.txt", "LICENSE", "agent.py"], paths
    assert not any("->" in path for path in paths)


def test_an_ordinary_status_field_is_unchanged():
    """The false-stop guard: the common case must parse exactly as it did."""
    raw = " M agent.py\0?? new.txt\0A  added.py\0"

    assert sorted(frozen_tree._porcelain_paths(raw)) == ["added.py", "agent.py", "new.txt"]


def test_every_porcelain_reader_in_this_repo_uses_the_nul_form():
    """**The family rule**, which is the part `CHG-20260903-31` did not ship.

    That record fixed one `[3:]` slice over `git status --porcelain` and left an identical one in
    `tools/frozen_tree.py`. The sweep for this record found that one, and also found
    `worktree.py`'s other `[3:]` in `carry()` — which is **correct**, because it is guarded by
    `entry.startswith("!! ")` so an unprefixed old-path field is skipped rather than sliced.

    `-z` is what makes a rename's two fields separable at all, and it also removes v1's path
    quoting. A reader without it cannot be right about either.
    """
    # **Scoped to readers that turn the output into paths.** The first version of this rule
    # flagged `probes.working_tree_clean`, which asks only whether the output is empty and
    # never parses a path — `-z` would change nothing there, and adding a flag to satisfy a
    # rule rather than for a reason is its own smell. What `-z` buys is that a rename's two
    # fields are separable and paths are not quoted, and only a reader that splits or slices
    # needs either.
    root = Path(__file__).resolve().parents[1]
    readers = []
    for path in list((root / "src").rglob("*.py")) + list((root / "tools").glob("*.py")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if '"status"' not in line or "--porcelain" not in line or '"-z"' in line:
                continue
            nearby = " ".join(lines[i:i + 8])
            parses = any(mark in nearby for mark in ("[3:]", ".splitlines()", ".split("))
            if parses:
                readers.append(f"{path.relative_to(root)}: {line.strip()[:70]}")

    assert readers == [], (
        f"these turn porcelain output into paths without -z, so a rename is one string with "
        f"an arrow in it and a non-ASCII name keeps its quotes: {readers}")
