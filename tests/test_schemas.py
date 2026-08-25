"""Pin `docs/SCHEMAS.md` to the code (CHG-20260823-21).

Both review seats found the same root cause independently: **nothing pinned the catalogue.**
`test_documented_numbers.py` holds the README's counts, flags and examples to the code; the schema
page had no test at all and drifted in three checkable ways within a day of being written —

1. it said the attachment `id` **is** the stored filename (it is the full 64-char digest; the
   filename is `id[:32]`);
2. it said *"Two schemas are closed"* above a table marking three, when four are actually enforced;
3. it said *"two are per-connection state, one is the file's"* over five pragmas, when three are
   per-connection and two are the file's.

Every test below is written for one of those, or for a field list a future edit could silently
diverge from. A catalogue nobody checks is worse than none, because people stop reading the source.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_sdlc_runner import (  # noqa: E402
    attachments, conversations, engine, graph, models, policy, settings, workorder,
)

PAGE = ROOT / "docs" / "SCHEMAS.md"
TEXT = PAGE.read_text(encoding="utf-8")


def _section(number: int) -> str:
    """The body of one numbered entry, so a claim is checked where it is made."""
    match = re.search(rf"^## {number} · .*?$(.*?)(?=^## |\Z)", TEXT, re.M | re.S)
    assert match, f"the catalogue has no entry {number}"
    return match.group(1)


# ── the catalogue describes what exists ───────────────────────────────────────────────────────

def test_every_entry_names_a_file_that_exists():
    """A map pointing at a file that is gone is worse than a blank."""
    for link in set(re.findall(r"\]\(\.\./([^)]+)\)", TEXT)):
        target = ROOT / link.split("#")[0]
        assert target.exists(), f"the catalogue links to {link}, which does not exist"


def test_every_row_of_the_index_has_an_entry_below_it():
    """Counted from the table rather than hard-coded, so adding a schema does not need two edits
    in two files — the failure mode that produced this page's first three drifts."""
    rows = [int(m) for m in re.findall(r"^\| (\d+) \| ", TEXT, re.M)]
    numbered = [int(n) for n in re.findall(r"^## (\d+) · ", TEXT, re.M)]
    assert rows == list(range(1, len(rows) + 1)), f"the index is not numbered 1..N: {rows}"
    assert numbered == rows, (
        f"the index lists {rows} and the entries below are {numbered}")


# ── the drift that actually happened, each pinned ─────────────────────────────────────────────

def test_the_closed_count_is_the_number_of_schemas_that_are_actually_closed():
    """Drift #2. The page miscounted its own subject, in its own second sentence.

    "Closed" is checked here by **exercising** each one, not by trusting a label: a schema is closed
    when a field outside its set is refused rather than ignored.
    """
    closed = 0

    # node spec, and the work order rendered from it
    good = {k: "" for k in workorder.NODE_SPEC_FIELDS}
    node = graph.BY_ID["engineer_build"]
    verdict = engine.resolve_verdict(node, "low")
    for extra in ({**good, "surprise": 1},):
        with pytest.raises(Exception):
            workorder.render(node, extra, verdict)
    closed += 2                                   # node spec and work order share `_check`

    # the model registry, entry and envelope
    with pytest.raises(models.ModelError):
        models._model_from({"id": "x", "vendor": "v", "name": "n",
                            "transport": "cli", "command": ["a"], "surprise": 1})
    closed += 1

    # settings -- driven through its real loader, because that is the path an operator's file takes
    scratch = Path(tempfile.mkdtemp()) / "settings.json"
    scratch.write_text(json.dumps({"review_seats": 3, "surprise": 1}), encoding="utf-8")
    with pytest.raises(settings.SettingsError):
        settings.load(str(scratch))
    closed += 1

    stated = re.search(r"\*\*(\w+)\*\* schemas are \*\*closed\*\*", TEXT)
    assert stated, "the catalogue no longer states how many schemas are closed"
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    assert words[stated.group(1).lower()] == closed, (
        f"the catalogue says {stated.group(1)} schemas are closed; {closed} actually refuse an "
        f"unknown field")


def test_the_attachment_id_is_not_the_stored_filename():
    """Drift #1 — the page was false about the field its entry leads with.

    Anyone joining manifest ids to stored files off that line would have written a bug.
    """
    digest = "a" * 64
    assert attachments.stored_name(digest) != digest
    assert len(attachments.stored_name(digest)) == 32

    # Pin the CLAIM, not the vocabulary. The first version of this test asserted that "64" and
    # "stored_name" appeared somewhere in the entry -- and when the false line was put back to
    # check the test, it passed, because the corrective prose underneath still contained both
    # words. A test that looks for words rather than for what is being said is the same coarse
    # check this page exists to catch, written into the check itself.
    example = re.search(r"```jsonc\n(.*?)```", _section(12), re.S)
    assert example, "entry 12 must show the manifest shape"
    id_line = next(ln for ln in example.group(1).splitlines() if '"id"' in ln)
    assert "stored filename" not in id_line.lower(), (
        f"entry 12 says the id is the stored filename: {id_line.strip()!r}. It is not -- "
        f"stored_name(id) is id[:{len(attachments.stored_name(digest))}], and joining ids to "
        f"files off this line writes a bug.")
    assert str(len(digest)) in id_line, (
        f"entry 12 must say the id is all {len(digest)} characters: {id_line.strip()!r}")


def test_the_sqlite_entry_says_which_pragmas_survive_a_reconnect():
    """Drift #3, and the one that matters most: a pragma set once and reset per connection is a
    name standing in for a constraint — which is the exact defect the DDL block is about."""
    import os
    import sqlite3

    path = os.path.join(tempfile.mkdtemp(), "probe.sqlite")
    first = sqlite3.connect(path)
    for pragma in ("journal_mode=WAL", "foreign_keys=ON", "synchronous=NORMAL", "user_version=7"):
        first.execute("pragma " + pragma)
    first.commit()
    first.close()

    again = sqlite3.connect(path)
    survived = {p for p in ("journal_mode", "user_version")
                if str(again.execute("pragma " + p).fetchone()[0]).lower() in ("wal", "7")}
    reset = {p for p in ("foreign_keys",)
             if again.execute("pragma " + p).fetchone()[0] == 0}
    again.close()

    assert survived == {"journal_mode", "user_version"}
    assert reset == {"foreign_keys"}, (
        "foreign_keys survived a reconnect on this platform — the catalogue's claim that it is "
        "per-connection state would then be wrong, and REFERENCES would enforce more than stated")
    body = _section(14)
    assert "per connection" in body.lower()
    # The DDL BLOCK, not the prose around it -- the prose explains why `opened_at` was removed and
    # must keep saying so. Scoping the check to the code fence is the difference between pinning a
    # schema and pinning an argument about it.
    fences = re.findall(r"```sql\n(.*?)```", body, re.S)
    ddl = chr(10).join(fences)
    assert ddl, "entry 14 has no sql block"
    assert "opened_at" not in ddl, (
        "opened_at is back in the DDL; it was removed as a second copy of the OPENED turn's `at`")
    assert "PRIMARY KEY (conversation_id, seq)" in ddl


# ── field lists a future edit could silently diverge from ─────────────────────────────────────

@pytest.mark.parametrize("entry, names", [
    (3, workorder.NODE_SPEC_FIELDS),
    (5, workorder.WORK_ORDER_FIELDS),
    (5, workorder.VERDICT_FIELDS),
    (9, conversations.CSV_COLUMNS),
    (8, conversations.KINDS),
    (1, graph.MODES),
    (4, tuple(policy.PERMANENT_HALT_KINDS)),
    (11, settings.FIELDS),
])
def test_every_name_the_entry_lists_is_a_real_name(entry, names):
    body = _section(entry)
    missing = [n for n in names if n not in body]
    assert not missing, f"entry {entry} does not mention {missing}, which the code defines"


def test_the_run_report_entry_lists_every_field_the_report_emits():
    body = _section(13)
    emitted = set(engine.RunReport().as_dict())
    missing = sorted(f for f in emitted if f not in body)
    assert not missing, f"entry 13 omits {missing}"


def test_the_model_entry_lists_exactly_what_persists():
    """Eight fields persist; `reach` and `leaves_this_machine` are computed and stripped on save.

    The entry must not list them as stored — that was the worst finding of the SQLite round, one
    document over.
    """
    model = models.Model(id="i", vendor="v", name="n", transport="cli", command=("a",))
    persisted = set(model.as_dict()) - {"reach", "leaves_this_machine"}
    body = _section(10)
    for field in persisted:
        assert field in body, f"entry 10 omits the persisted field {field!r}"
    assert "computed, never stored" in body.lower() or "computed" in body.lower()


def test_the_node_entry_lists_every_field_of_a_node():
    body = _section(1)
    missing = [f for f in graph.Node.__dataclass_fields__ if f not in body]
    assert not missing, f"entry 1 omits {missing}"


def test_the_counts_the_page_states_are_the_real_ones():
    assert f"{len(graph.NODES)} of these" in _section(1)
    assert str(len(policy.GATES)) in _section(1)
