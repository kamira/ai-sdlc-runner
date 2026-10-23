"""The measurement capture tool: redaction, the steps record, `cmd`, `check`. (CHG-20261019-01)

Needs no network. The tests that render an image need Playwright and its Chromium and skip without.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "docs" / "measurements" / "CHG-20261019-01" / "capture.py"
spec = importlib.util.spec_from_file_location("measurement_capture", TOOL)
capture = importlib.util.module_from_spec(spec)
sys.modules["measurement_capture"] = capture
spec.loader.exec_module(capture)

ENV = {"CWA_API_KEY": "CWA-0123456789ABCDEF-0123456789", "SHORT_TOKEN": "abc", "HOME": "/home/x",
       "MY_PASSWORD": "hunter2hunter2"}


def need_chromium():
    pytest.importorskip("playwright.sync_api")
    if not capture.chromium_available():
        pytest.skip("Chromium is not available")


def test_env_values_are_redacted_by_name():
    text, changed = capture.redact("key=CWA-0123456789ABCDEF-0123456789 pw hunter2hunter2 abc /home/x",
                                   ENV)
    assert changed
    assert "[redacted:CWA_API_KEY]" in text and "[redacted:MY_PASSWORD]" in text
    assert "0123456789ABCDEF" not in text and "hunter2" not in text
    assert "abc" in text and "/home/x" in text      # too short, and not a secret name


def test_patterns_are_redacted_including_in_a_url_query():
    url = ("https://opendata.cwa.gov.tw/api/v1/rest?Authorization=CWA-AAAAAAAAAA-BBBBBBBBBB-CCCC&x=1"
           " Bearer abcdefgh12345678 sk-abcdefghijklmnop1234 CWA-1234567890abcdef1234")
    text, changed = capture.redact(url, {})
    assert changed
    for leaked in ("CWA-AAAA", "abcdefgh12345678", "sk-abcdef", "1234567890abcdef1234"):
        assert leaked not in text
    assert "&x=1" in text


def test_clean_text_is_untouched():
    assert capture.redact("nothing here", ENV) == ("nothing here", False)


def test_strip_url_drops_query_and_fragment():
    assert capture.strip_url("http://h:1/p?Authorization=x#token=y") == "http://h:1/p"


def test_cmd_writes_text_and_steps_line(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_SECRET", "supersecretvalue")
    rc = capture.main(["--root", str(tmp_path), "cmd", "--step", "3", "--slug", "hello", "--why",
                       "say hi", "--no-image", "--", sys.executable, "-c",
                       "import os,sys;print('hi');print(os.environ['SOME_SECRET']);"
                       "print('err',file=sys.stderr);sys.exit(4)"])
    assert rc == 0
    txt = (tmp_path / "steps" / "03-hello.txt").read_text(encoding="utf-8")
    assert "hi\n" in txt and "err" in txt and "# exit    4" in txt
    assert "supersecretvalue" not in txt and "[redacted:SOME_SECRET]" in txt
    (line,) = (tmp_path / "steps" / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    e = json.loads(line)
    assert (e["step"], e["slug"], e["kind"], e["why"], e["exit_code"]) == (3, "hello", "cmd", "say hi", 4)
    assert e["redacted"] is True and e["files"] == ["steps/03-hello.txt"]
    assert e["started_utc"].endswith("Z") and "supersecretvalue" not in line


def test_cmd_png_is_rendered(tmp_path):
    need_chromium()
    assert capture.main(["--root", str(tmp_path), "cmd", "--step", "1", "--slug", "p", "--why", "w",
                         "--", sys.executable, "-c", "print('\\n'.join(map(str, range(300))))"]) == 0
    png = tmp_path / "steps" / "01-p.png"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    height = int.from_bytes(png.read_bytes()[20:24], "big")
    assert height > 3000                              # full page, not cut at the viewport


def test_file_step_records_sha(tmp_path):
    f = tmp_path / "in.yaml"
    f.write_text("a: 1\n", encoding="utf-8")
    assert capture.main(["--root", str(tmp_path / "m"), "file", "--step", "2", "--slug", "cfg",
                         "--why", "w", "--no-image", str(f)]) == 0
    txt = (tmp_path / "m" / "steps" / "02-cfg.txt").read_text(encoding="utf-8")
    assert "sha256 " in txt and "a: 1" in txt


def test_check_fails_on_a_planted_secret_and_passes_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANT_TOKEN", "plantedvalue123")
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.txt").write_text("nothing\n", encoding="utf-8")
    assert capture.main(["--root", str(clean), "check"]) == 0
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "a.txt").write_text("x plantedvalue123 y\n", encoding="utf-8")
    (dirty / "b.txt").write_text("?Authorization=CWA-AAAAAAAAAA-BBBBBBBBBB-CCCC\n", encoding="utf-8")
    assert capture.main(["--root", str(dirty), "check"]) == 1
    assert [b.split(":")[0] for b in capture.check_tree(dirty)] == ["a.txt", "b.txt"]


def test_page_refuses_when_a_secret_stays_visible(tmp_path, monkeypatch):
    need_chromium()
    monkeypatch.setenv("PAGE_SECRET", "visiblesecret99")
    page = tmp_path / "p.html"
    page.write_text("<p id=a>ok</p><p>visiblesecret99</p><input type=password value=zzz>",
                    encoding="utf-8")
    # The element showing it is hidden, so the page is captured, and the text file lacks it.
    assert capture.main(["--root", str(tmp_path / "m"), "page", "--step", "1", "--slug", "pg",
                         "--why", "w", page.as_uri()]) == 0
    txt = (tmp_path / "m" / "steps" / "01-pg.txt").read_text(encoding="utf-8")
    assert "visiblesecret99" not in txt and "ok" in txt
    e = json.loads((tmp_path / "m" / "steps" / "steps.jsonl").read_text(encoding="utf-8"))
    assert e["redacted"] is True and "?" not in e["url"]
