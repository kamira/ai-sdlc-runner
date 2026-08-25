"""Pin `docs/DATABASE.md` (CHG-20260823-22).

The schema is proposed and unbuilt, so there is no implementation to compare it against. What *can*
be checked is the thing that matters most about a DDL nobody has run: **does it run, and do its
constraints actually refuse?**

Three rounds of review found the same failure mode in this schema three times — a `reach` column
persisting a computed safety label, a `REFERENCES` clause with `foreign_keys` off, and a
`user_version` named in prose and absent from the SQL. All three are the same defect: a constraint
that is a name. So this file executes the page's SQL **verbatim** and tries to violate it.
"""
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_sdlc_runner import conversations, models  # noqa: E402

PAGE = (ROOT / "docs" / "DATABASE.md").read_text(encoding="utf-8")
BLOCKS = re.findall(r"```sql\n(.*?)```", PAGE, re.S)


def _built():
    """A database built from the page's own SQL, with nothing typed in by this test."""
    path = os.path.join(tempfile.mkdtemp(), "probe.sqlite")
    db = sqlite3.connect(path)
    for block in BLOCKS:
        if "SELECT" not in block:
            db.executescript(block)
    return db


# ── the SQL is real SQL ───────────────────────────────────────────────────────────────────────

def test_the_page_has_sql_to_check():
    assert BLOCKS, "docs/DATABASE.md has no sql blocks"


def test_every_ddl_statement_on_the_page_executes():
    db = _built()
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"conversations", "turns", "models"} <= tables


def test_every_query_the_page_promises_to_serve_actually_runs():
    db = _built()
    db.execute("INSERT INTO conversations VALUES ('c1','p1','P',1,'{}')")
    ran = 0
    for block in BLOCKS:
        if "SELECT" not in block:
            continue
        for chunk in block.split(";"):
            statement = "\n".join(
                line for line in chunk.splitlines() if not line.strip().startswith("--")).strip()
            if statement:
                db.execute(statement.replace("?", "'c1'"))
                ran += 1
    assert ran >= 5, f"the page lists {ran} queries; it claims five"


# ── the constraints refuse, rather than being named ───────────────────────────────────────────

def test_a_duplicate_turn_is_refused():
    """The guarantee neither the JSONL nor the TinyDB backend could give."""
    db = _built()
    db.execute("INSERT INTO conversations VALUES ('c1','p1','P',1,'{}')")
    db.execute("INSERT INTO turns VALUES ('c1',0,'opened','t','{}')")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        db.execute("INSERT INTO turns VALUES ('c1',0,'note','t','{}')")


def test_an_orphan_turn_is_refused_because_the_page_turns_foreign_keys_on():
    """`PRAGMA foreign_keys` is OFF by default and **per connection**.

    A seat proved an orphan row inserts fine without it, which made `REFERENCES` decorative. This
    test fails if that pragma is ever dropped from the page's setup block.
    """
    db = _built()
    assert db.execute("pragma foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute("INSERT INTO turns VALUES ('ghost',9,'note','t','{}')")


def test_the_file_level_pragmas_are_set_and_survive():
    db = _built()
    assert db.execute("pragma journal_mode").fetchone()[0] == "wal"
    assert db.execute("pragma user_version").fetchone()[0] >= 1, (
        "user_version is the migration mechanism; a number nobody assigns is a name")


def test_the_page_says_which_pragmas_reset_on_a_reconnect():
    """The distinction three rounds got wrong. Measured here, not asserted."""
    path = os.path.join(tempfile.mkdtemp(), "reconnect.sqlite")
    first = sqlite3.connect(path)
    for block in BLOCKS:
        if "SELECT" not in block:
            first.executescript(block)
    first.commit()
    first.close()

    again = sqlite3.connect(path)
    assert again.execute("pragma journal_mode").fetchone()[0] == "wal"    # file
    assert again.execute("pragma user_version").fetchone()[0] >= 1       # file
    assert again.execute("pragma foreign_keys").fetchone()[0] == 0       # per connection
    again.close()

    setup = next(b for b in BLOCKS if "PRAGMA" in b)
    assert "PER CONNECTION" in setup and "FILE-level" in setup, (
        "the setup block must mark which pragmas reset — getting that backwards is how a "
        "REFERENCES clause ends up enforcing nothing")


# ── the columns that must never come back ─────────────────────────────────────────────────────

@pytest.mark.parametrize("column, why", [
    ("reach", "computed from (transport, endpoint); persisting it lets a stale label outlive the "
              "truth, and _model_from would refuse a payload carrying it"),
    ("leaves_this_machine", "same — computed, and stripped by models.save"),
    ("opened_at", "a second copy of the OPENED turn's `at`"),
    ("updated_at", "invented; nothing in models.py produces or reads one"),
])
def test_a_column_three_review_rounds_removed_has_not_come_back(column, why):
    db = _built()
    for table in ("conversations", "turns", "models"):
        columns = {row[1] for row in db.execute(f"pragma table_info({table})")}
        assert column not in columns, f"{table}.{column} is back — {why}"


def test_the_models_table_holds_exactly_what_the_registry_persists():
    """Eight fields persist. `command` is a list, so it is `command_json` here."""
    persisted = set(models.Model(id="i", vendor="v", name="n", transport="cli",
                                 command=("a",)).as_dict()) - {"reach", "leaves_this_machine"}
    db = _built()
    columns = {row[1] for row in db.execute("pragma table_info(models)")}
    assert columns == (persisted - {"command"}) | {"command_json"}, (
        f"the models table is {sorted(columns)}; the registry persists {sorted(persisted)}")


def test_the_turns_table_can_hold_every_kind_the_store_defines():
    db = _built()
    db.execute("INSERT INTO conversations VALUES ('c1','p1','P',1,'{}')")
    for n, kind in enumerate(conversations.KINDS):
        db.execute("INSERT INTO turns VALUES ('c1',?,?,'t','{}')", (n, kind))
    stored = {row[0] for row in db.execute("SELECT kind FROM turns")}
    assert stored == set(conversations.KINDS)


def test_the_page_states_it_is_not_built():
    """The one claim that must not drift silently in the other direction."""
    assert "proposed, not built" in PAGE
    assert not list((ROOT / "src").rglob("*sqlite*.py")), (
        "a sqlite module now exists; DATABASE.md must stop saying it is unbuilt")
