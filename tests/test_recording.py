"""The recorder and the player, tested by recording things and reading what came out.

A recording is evidence, so these tests run real subprocesses that really print at intervals and
check the *timings* landed — not that the code mentions timings.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


session_record = _load("session_record")
render_cast = _load("render_cast")


def _child(body):
    return [sys.executable, "-c", body]


def _read(path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return json.loads(lines[0]), [json.loads(ln) for ln in lines[1:]]


# ── the recorder ──────────────────────────────────────────────────────────────────────────────

def test_output_is_recorded_as_it_arrives_not_as_one_lump(tmp_path):
    """The timings *are* the recording. A child printing three times over half a second must land
    as three events at three different offsets."""
    code, path = session_record.record(_child(
        "import time\n"
        "for i in range(3):\n"
        "    print('line', i)\n"
        "    time.sleep(0.25)\n"), tmp_path)
    header, events = _read(path)

    assert code == 0 and header["exit_code"] == 0
    assert len(events) >= 3, f"{len(events)} events: output arrived as a lump, not a stream"
    offsets = [e[0] for e in events]
    assert offsets == sorted(offsets)
    assert offsets[-1] - offsets[0] > 0.3, "the half-second the child spent is not in the record"


def test_a_child_that_would_block_buffer_still_streams(tmp_path):
    """A recorder is always a pipe, and Python block-buffers into a pipe. This child does not pass
    `-u` and does not flush: unless the recorder forces unbuffered, everything it printed arrives
    in one event at the end and every timing is lost.

    Asserted by counting events on a child that never flushes — not by looking for the environment
    variable, which would pass just as well if it were spelled wrong.
    """
    _, path = session_record.record(_child(
        "import time\n"
        "print('first')\n"
        "time.sleep(0.4)\n"
        "print('second')\n"), tmp_path)
    _, events = _read(path)
    assert len(events) >= 2, "the child's output was buffered into a single event"


def test_a_multibyte_character_split_across_two_reads_survives(tmp_path):
    """Chunks are read at a fixed size, so a boundary lands mid-character on any real output with
    CJK or an em-dash in it. Decoding each chunk independently corrupts exactly one glyph per
    boundary — rare enough to survive a smoke test and wrong in every long recording."""
    size = session_record.CHUNK * 3 + 7          # guarantees boundaries inside the run of text
    _, path = session_record.record(_child(
        f"print('節' * {size // 3})"), tmp_path)
    _, events = _read(path)
    text = "".join(e[2] for e in events)
    assert "�" not in text, "a character was replaced at a chunk boundary"
    assert text.count("節") == size // 3


def test_the_exit_code_of_a_failing_command_is_recorded(tmp_path):
    code, path = session_record.record(_child("raise SystemExit(3)"), tmp_path)
    header, _ = _read(path)
    assert code == 3 and header["exit_code"] == 3


def test_each_command_gets_its_own_numbered_cast(tmp_path):
    for _ in range(3):
        session_record.record(_child("print('x')"), tmp_path)
    names = sorted(p.name for p in tmp_path.glob("*.cast"))
    assert len(names) == 3
    assert [n.split("-", 1)[0] for n in names] == ["000", "001", "002"]


def test_the_command_is_kept_as_data_not_only_in_the_title(tmp_path):
    argv = _child("print('x')")
    _, path = session_record.record(argv, tmp_path)
    header, _ = _read(path)
    assert header["command"] == argv, "a reader must not have to parse the title back apart"


# ── the player ────────────────────────────────────────────────────────────────────────────────

def test_a_long_pause_plays_short_and_names_its_real_length(tmp_path):
    """Both halves matter. Cut silently, the review cannot tell a slow failure from a fast one;
    played at true speed, nobody watches it."""
    cast = tmp_path / "000-slow.cast"
    cast.write_text(
        json.dumps({"version": 2, "timestamp": 0, "duration": 31,
                    "command": ["pytest"], "exit_code": 0}) + "\n"
        + json.dumps([0.0, "o", "start\n"]) + "\n"
        + json.dumps([30.0, "o", "done\n"]) + "\n", encoding="utf-8")

    steps = render_cast.load(tmp_path)
    assert steps[0]["end"] == pytest.approx(render_cast.IDLE_CAP, abs=0.01), (
        "thirty seconds of waiting must not be thirty seconds of playback")
    assert steps[0]["pauses"], "the pause must be recorded, not merely skipped"
    assert steps[0]["pauses"][0][1] == pytest.approx(30.0, abs=0.1), (
        "the real duration must survive so the page can name it")


def test_short_gaps_play_at_their_real_length(tmp_path):
    """Only *long* gaps are compressed. Squeezing everything would flatten the difference the
    recording exists to show."""
    cast = tmp_path / "000-quick.cast"
    cast.write_text(
        json.dumps({"version": 2, "timestamp": 0, "duration": 1,
                    "command": ["x"], "exit_code": 0}) + "\n"
        + json.dumps([0.0, "o", "a\n"]) + "\n"
        + json.dumps([0.9, "o", "b\n"]) + "\n", encoding="utf-8")
    steps = render_cast.load(tmp_path)
    assert steps[0]["end"] == pytest.approx(0.9, abs=0.01)
    assert steps[0]["pauses"] == []


def test_colour_survives_and_cursor_moves_do_not():
    """`runner`'s refusals are the point of most of these recordings and it colours them. But a
    cursor-move means nothing in a transcript that only appends, and guessing at one would corrupt
    the text around it."""
    got = render_cast.ansi_to_html("\x1b[31mrefused\x1b[0m ok\x1b[2Kgone")
    assert '<span class="c1">refused</span>' in got
    assert "\x1b" not in got and "[2K" not in got
    assert "gone" in got


def test_markup_in_recorded_output_is_escaped():
    """Recorded output is whatever a command printed, going into a page."""
    got = render_cast.ansi_to_html("<script>alert(1)</script>")
    assert "<script>" not in got and "&lt;script&gt;" in got


def test_an_unterminated_colour_does_not_leak_into_the_rest_of_the_page():
    got = render_cast.ansi_to_html("\x1b[31mstill red at the end")
    assert got.count("<span") == got.count("</span>")


def test_the_page_fetches_nothing_but_a_font(tmp_path):
    """A recording that needs the network to replay is not a recording you can keep."""
    session_record.record(_child("print('x')"), tmp_path)
    page = render_cast.render(render_cast.load(tmp_path), "t")
    for marker in ("<script src=", "cdn.", "unpkg", "jsdelivr", "fetch(", "XMLHttpRequest"):
        assert marker not in page, f"the page reaches for {marker}"
    assert page.count("https://") == page.count("https://fonts.googleapis.com")


def test_a_failing_step_is_marked_as_one(tmp_path):
    session_record.record(_child("print('ok')"), tmp_path)
    session_record.record(_child("raise SystemExit(2)"), tmp_path)
    steps = render_cast.load(tmp_path)
    assert [s["exit"] for s in steps] == [0, 2]
    assert "1</b> non-zero exits" in render_cast.render(steps, "t")
