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


def _qualified_uses(root: Path):
    """Uses resolved to where they came from: ``{(module_stem, name)}``.

    `policy.adjudicate` yields `("policy", "adjudicate")`; `from .policy import adjudicate` yields
    the same; `subprocess.run` yields `("subprocess", "run")` — which no longer vouches for a local
    function called `run`.

    Narrower than the name-level pass on purpose: it sees qualified and imported uses but not bare
    same-module calls, so it is used to **confirm** a hit for names likely to collide rather than to
    replace the broad pass.
    """
    uses = set()
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # `from . import effects as effects_mod` means `effects_mod.run` is a use of `effects.run`.
        # Without this the checker reported three real, wired symbols as orphans — a false positive
        # in a checker written to catch false negatives, which is its own small lesson.
        alias_of = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.asname:
                        alias_of[alias.asname] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        alias_of[alias.asname] = alias.name.split(".")[-1]

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                module = alias_of.get(node.value.id, node.value.id)
                uses.add((module, node.attr))
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    uses.add((node.module.split(".")[-1], alias.name))
    return uses


def _used_inside_its_own_module(root: Path, home: str, name: str) -> bool:
    """A same-module caller is a real use the qualified pass cannot see."""
    path = root / home
    if not path.is_file():
        return False
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == name:
            return True
    return False


#: Names common enough that an unrelated call elsewhere would mask an orphan of the same name.
#: `subprocess.run` masking a local `run` is not hypothetical — a verifier planted exactly that and
#: the check passed it.
COLLIDING = ("run", "load", "save", "check", "read", "write", "close", "open", "record", "render",
             "select", "verdict", "entries", "answers", "pending", "classify", "derive")


def test_nothing_public_in_src_is_unreachable_from_src():
    used = _used_names(SRC)
    orphans = sorted(f"{home}:{name}" for name, home in _public_symbols(SRC).items()
                     if name not in PUBLIC_API and name not in used)
    assert not orphans, (
        f"these exist and nothing in src/ uses them: {orphans}. Either wire each one in, delete it, "
        f"or add it to PUBLIC_API with a reason. A mechanism nothing calls is not built — see "
        f"docs/knowledge/knowledge.md KN-8.")


def test_a_symbol_with_a_common_name_needs_a_qualified_use(tmp_path):
    """The name-level pass alone lets `subprocess.run` vouch for an orphan called `run`.

    For names likely to collide, the use must be **module-qualified** — `policy.classify`, or an
    explicit `from .policy import classify` — or inside the symbol's own module. A bare call to the
    same word somewhere unrelated proves nothing.
    """
    qualified = _qualified_uses(SRC)
    unconfirmed = [
        f"{home}:{name}" for name, home in _public_symbols(SRC).items()
        if name in COLLIDING and name not in PUBLIC_API
        and (home[:-3], name) not in qualified
        and not _used_inside_its_own_module(SRC, home, name)
    ]
    assert not unconfirmed, (
        f"common-named and never qualified: {unconfirmed}. Something calls a word that looks like "
        f"these, but nothing calls *these*.")


def test_the_qualified_pass_is_not_fooled_by_a_stdlib_namesake(tmp_path):
    """The exact planted orphan a verifier used."""
    (tmp_path / "orphan.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "user.py").write_text(
        "import subprocess\ndef go():\n    return subprocess.run(['ls'])\n", encoding="utf-8")

    # the broad pass is fooled...
    assert "run" in _used_names(tmp_path)
    # ...and the qualified pass is not.
    assert ("orphan", "run") not in _qualified_uses(tmp_path)
    assert not _used_inside_its_own_module(tmp_path, "orphan.py", "run")


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


def _test_names(source: str):
    """Top-level `def test_*` names in one module, in the order the file defines them."""
    import ast

    return [n.name for n in ast.parse(source).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")]


def test_no_test_module_defines_the_same_test_name_twice():
    """A shadowed test is coverage that looks present and is not collected.

    `tests/test_conversations_sqlite.py` carried two functions called
    `test_one_bad_conversation_does_not_stop_the_others` — CHG-42's and CHG-45's. Python keeps the
    last one, so CHG-42's stopped running the day CHG-45 landed. Nothing broke, because the
    replacement was stronger; nothing reported it either, for four days, until an acceptance round
    counted the collected items and found six where the file appeared to define seven.

    Same family as this module's other check: a thing that reads as present and is not. The suite
    cannot notice a test it never collects, so the check has to read the file rather than run it.
    """
    from collections import Counter
    from pathlib import Path

    duplicates = {}
    for module in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
        counted = Counter(_test_names(module.read_text(encoding="utf-8")))
        repeated = {name: n for name, n in counted.items() if n > 1}
        if repeated:
            duplicates[module.name] = repeated

    assert not duplicates, (
        "these test names are defined more than once in one module, so only the last of each is "
        f"collected and the rest never run: {duplicates}")


def test_the_duplicate_name_check_reads_definitions_rather_than_text():
    """Proof it can fail, and proof it does not cry wolf.

    A name in a string or a comment is not a definition — the mention of
    `test_one_bad_conversation_does_not_stop_the_others` in the docstring above must not trip it,
    or the check gets switched off the first time somebody writes about a test.
    """
    planted = (
        "def test_alpha():\n    pass\n"
        "def test_alpha():\n    pass\n"
        "# def test_beta():\n"
        "NOTE = 'def test_beta():'\n"
        "def test_beta():\n    pass\n")
    names = _test_names(planted)
    assert names.count("test_alpha") == 2, "the check must see a real redefinition"
    assert names.count("test_beta") == 1, "a name in a comment or a string is not a definition"
