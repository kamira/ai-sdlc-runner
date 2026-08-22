"""KN-8, made mechanical (CHG-20260823-02).

This repository's most expensive recurring defect is a **right mechanism that nothing reaches**,
shipped with a green suite: an engine that walked past its own policy verdict, a `policy.adjudicate`
with no caller, six permanent halts printed into every work order and never checked, three modules
imported by nobody, three probes with no user, a `to_json` nothing serialised with. Every one passed
the tests written beside it, because those tests called the mechanism directly. Every one was found
by an independent verifier rather than by CI.

Three rounds of that is enough to stop relying on someone noticing. This file is the check:

* nothing public in `src/` exists without something in `src/` **using** it, and
* the flow's own claims about itself — the counts a person reads in `runner flow` — come from the
  graph rather than from a sentence somebody typed.

A symbol whose only references are its own definition and its own test file is not wired in,
whatever the done-when says.

**Uses are counted from the syntax tree, not from the text.** The first version of this check
searched for the name and counted every hit, so `tui.prompt` — which nothing called — scored two
from the words "role prompt" and "generic prompt" in two unrelated docstrings, and the check
reported it wired. A verifier found it: a guard that counts prose is the "looks rigorous, checks
nothing" shape one level up from the defect it was written to catch. Reading loads and attribute
accesses out of the AST excludes prose *and* the definition itself by construction, which is a
property rather than a pattern that happens to hold.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "ai_sdlc_runner"

#: Symbols that are deliberately part of the package's public surface without an internal user.
#: The list is the point: adding to it is a decision somebody makes on purpose, in a diff, with a
#: reason — which is exactly what did not happen the last three times.
PUBLIC_API = {
    "main",       # the console-script entry point; pyproject names it, so nothing in src/ calls it
}


def _public_symbols(root: Path):
    """Every top-level public function, class and constant, with its home module."""
    found = {}
    for path in sorted(root.glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    found[node.name] = path.name
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        found[target.id] = path.name
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id.isupper():
                    found[node.target.id] = path.name
    return found


def _used_names(root: Path):
    """Every name the code actually *uses*, anywhere under `root`.

    Loads, attribute accesses, decorators and imported aliases. A definition binds a name in `Store`
    context and a docstring is a `Constant`, so neither reaches this set — which is the whole reason
    for reading the tree instead of the text.
    """
    used = set()
    for path in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.alias):
                used.add(node.asname or node.name.split(".")[-1])
    return used


def test_nothing_public_in_src_is_unreachable_from_src():
    used = _used_names(SRC)
    orphans = sorted(f"{home}:{name}" for name, home in _public_symbols(SRC).items()
                     if name not in PUBLIC_API and name not in used)
    assert not orphans, (
        f"these exist and nothing in src/ uses them: {orphans}. Either wire each one in, delete it, "
        f"or add it to PUBLIC_API with a reason. A mechanism nothing calls is not built — see "
        f"docs/knowledge/knowledge.md KN-8.")


def test_the_check_catches_a_planted_orphan(tmp_path):
    """A tripwire nothing can trip is a comment."""
    (tmp_path / "orphan.py").write_text(
        "def a_function_nobody_calls():\n    return 1\n\n\n"
        "def one_that_is_called():\n    return 2\n", encoding="utf-8")
    (tmp_path / "user.py").write_text(
        "from .orphan import one_that_is_called\n"
        "def used():\n    return one_that_is_called()\n", encoding="utf-8")

    used = _used_names(tmp_path)
    orphans = sorted(name for name in _public_symbols(tmp_path) if name not in used)
    assert orphans == ["a_function_nobody_calls", "used"]


def test_prose_does_not_count_as_a_use(tmp_path):
    """The exact miss: `tui.prompt` had no caller and scored two hits from the words "role prompt"
    and "generic prompt" in unrelated docstrings."""
    (tmp_path / "m.py").write_text(
        '"""A docstring naming widget twice: widget, widget."""\n'
        "# and a comment about widget\n"
        "def widget():\n    return 1\n", encoding="utf-8")
    assert "widget" not in _used_names(tmp_path)


def test_a_definition_does_not_count_as_its_own_use(tmp_path):
    (tmp_path / "m.py").write_text("def alone():\n    return 1\n", encoding="utf-8")
    assert "alone" not in _used_names(tmp_path)


def test_an_attribute_call_counts(tmp_path):
    """`policy.adjudicate(...)` is how most of this package reaches most of the rest."""
    (tmp_path / "a.py").write_text("def adjudicate():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from . import a\ndef go():\n    return a.adjudicate()\n",
                                   encoding="utf-8")
    assert "adjudicate" in _used_names(tmp_path)


@pytest.mark.parametrize("claim,derived", [
    ("nodes", lambda g: len(g.NODES)),
    ("asking", lambda g: len(g.asking_nodes())),
    ("gates", lambda g: len(set(g.gates_used()))),
])
def test_what_the_cli_says_about_the_flow_is_computed_from_the_flow(capsys, claim, derived):
    """The counts a person reads are derived, never typed. A hand-written "12 asking nodes" was
    wrong — the flow has 14 — and nothing caught it because nothing computed it."""
    from ai_sdlc_runner import cli, graph

    cli.main(["flow"])
    summary = capsys.readouterr().out.splitlines()[-1]
    assert str(derived(graph)) in summary, claim


def test_every_role_the_flow_uses_is_named_in_the_summary(capsys):
    from ai_sdlc_runner import cli, graph

    cli.main(["flow"])
    summary = capsys.readouterr().out.splitlines()[-1]
    for role in graph.roles_used():
        assert role in summary
