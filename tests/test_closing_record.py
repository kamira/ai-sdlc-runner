"""A run that hit a red line recorded the word `stopped` and nothing else (CHG-20260828-09).

Two acceptances disclosed halves of this and neither was acted on:

* `ACC-20260827-19` #4 — *"Task 6 says 'appears in the export'. It appears in `report.halts` and in
  the `run` output. The conversation export was not extended, so a halt's recipient is in the run
  report and not in `--format markdown`."*
* `ACC-20260827-17` #5 — *"The grade appears in the report, not in the conversation export."*

Checking them found something larger than either. A run stopped by a **permanent halt** — a
`deploy`, the reddest line this runner has — produced a conversation of `opened, ask×3, answer×3,
closed: stopped`. Nothing about the halt, the rule it broke, or who it is for.

All of that was in the run report, which is **stdout**, and gone when the terminal is. The
conversation is the durable artefact: a governance record that keeps every question and loses the
reason the run stopped has kept the least important half.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import conversations as conv  # noqa: E402


def _conversation(tmp_path, name="P"):
    return conv.Conversation(conv.FileBackend(tmp_path / "store"), name).open()


def _closed(c):
    turns = c.store.read(c.project["id"], c.id)["turns"]
    return [t for t in turns if t.get("kind") == conv.CLOSED][0]


def test_the_closing_turn_carries_why_the_run_ended(tmp_path):
    c = _conversation(tmp_path)
    c.close("stopped", at_node="pm_plan", why="permanent halt: this one is for release",
            risk="high", change_class="the 'standard' class, authorised by alex")
    turn = _closed(c)
    assert turn["state"] == "stopped"
    assert turn["at_node"] == "pm_plan"
    assert "for release" in turn["why"], "the recipient is the half an operator acts on"
    assert turn["risk"] == "high"
    assert "alex" in turn["change_class"]


def test_a_run_with_nothing_to_add_records_exactly_what_it_did_before(tmp_path):
    """The compatibility half. An absent field writes no key, so a conversation from before this
    change and one written after it are the same bytes for the same run."""
    c = _conversation(tmp_path)
    c.close("finished")
    assert sorted(_closed(c)) == ["at", "kind", "seq", "state"]


def test_the_summary_says_where_and_why_not_only_the_state(tmp_path):
    """`stopped` alone scanned identically whether the run hit a gate or a red line."""
    c = _conversation(tmp_path)
    c.close("stopped", at_node="merge", why="a person does it")
    said = conv._summary(_closed(c))
    assert said.startswith("stopped at merge")
    assert "a person does it" in said


def test_at_node_not_at_because_at_is_the_turns_own_timestamp(tmp_path):
    """The first draft used `at`, and `Turn.as_dict` refused it — *"a body that can rewrite its
    envelope makes seq, kind and at unreliable for every reader"*.

    The closing turn then vanished from the record entirely, and the guard said so loudly rather
    than dropping it quietly. `DECISION` had already settled the name with `at_node`. Pinned here so
    the collision cannot be reintroduced by someone who finds `at` the more natural word.
    """
    with pytest.raises(conv.ConversationError) as exc:
        conv.Turn(seq=1, kind=conv.CLOSED, at="now", body={"at": "pm_plan"}).as_dict()
    assert "envelope" in str(exc.value)


# ── through the real CLI, because the point is the durable artefact ─────────────────────────────

def test_a_permanent_halt_reaches_the_export(tmp_path):
    """The whole finding, end to end.

    A `deploy` is refused by `PERMANENT_HALT_KINDS` at every grade. Before this the export of that
    run said `closed: stopped`, and an auditor reading it could not tell a red line from a gate.
    """
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / "examples/minimal/plan.json").read_text(encoding="utf-8"))
    plan["risk"] = "low"
    plan["operations"]["pm_plan"] = [{"description": "ship it", "kind": "deploy",
                                      "targets": ["kubectl apply -f prod/"]}]
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "ai_sdlc_runner.cli", *args], cwd=str(root),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, timeout=900)

    ran = cli("--config", str(root / "examples/minimal/runner.yaml"), "run",
              "--plan", str(tmp_path / "plan.json"), "--risk", "low",
              "--project", "halted", "--store-root", str(tmp_path))
    assert "permanent halt" in (ran.stdout or ""), (ran.stdout or "")[-500:]

    listed = (cli("conversations", "--project", "halted",
                  "--store-root", str(tmp_path)).stdout or "").split()
    page = cli("export", "--project", "halted", "--store-root", str(tmp_path),
               "--conversation", listed[0], "--format", "markdown").stdout or ""

    assert "permanent halt" in page, (
        "the run stopped at a red line and the durable record does not say so:\n" + page[-600:])
    assert "for release" in page, "and it must name who the halt is for"
    assert '"at_node": "pm_plan"' in page, "and where it stopped"
