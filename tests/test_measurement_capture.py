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


def test_page_hides_a_secret_held_only_in_a_form_value(tmp_path, monkeypatch):
    need_chromium()
    for name in list(capture.env_secrets()):
        monkeypatch.delenv(name, raising=False)
    page = tmp_path / "f.html"
    page.write_text("<p>ok</p><input id=i type=text value='CWA-0123456789abcdef01234567'>"
                    "<textarea>sk-abcdefghijklmnopqrstuv</textarea>"
                    "<div contenteditable>Bearer abcdefgh12345678</div>", encoding="utf-8")
    assert capture.main(["--root", str(tmp_path / "m"), "page", "--step", "1", "--slug", "pg",
                         "--why", "w", page.as_uri(), "--no-image"]) == 0
    e = json.loads((tmp_path / "m" / "steps" / "steps.jsonl").read_text(encoding="utf-8"))
    assert e["redacted"] is True
    assert capture.check_tree(tmp_path / "m") == []


def test_page_form_value_is_blanked_before_the_screenshot(tmp_path, monkeypatch):
    need_chromium()
    from playwright.sync_api import sync_playwright
    page = tmp_path / "f.html"
    page.write_text("<input type=text value='CWA-0123456789abcdef01234567'>", encoding="utf-8")
    with sync_playwright() as p:
        b = capture._launch(p)
        try:
            pg = b.new_page()
            pg.goto(page.as_uri())
            pg.evaluate(capture._HIDE_JS, ["CWA-0123456789abcdef01234567"])
            assert pg.evaluate(capture._FIELDS_JS) == [""]
        finally:
            b.close()


def test_live_output_never_shows_a_secret_split_across_two_reads(tmp_path, monkeypatch, capsys):
    secret = "supersecretvalue"
    monkeypatch.setenv("SOME_SECRET", secret)
    reads = iter([b"before super", b"secretvalue after\nnext line\n", b""])
    monkeypatch.setattr(capture, "_read_chunk", lambda fd: next(reads))
    out = capture.Out(tmp_path)
    capture.run_cmd(out, 1, "split", "w", argv=[sys.executable, "-c", "pass"], image=False)
    live = capsys.readouterr().out
    assert secret not in live and "super" not in live.replace("[redacted:SOME_SECRET]", "")
    assert "[redacted:SOME_SECRET] after" in live and live.endswith("next line\n")
    assert secret not in (tmp_path / "steps" / "01-split.txt").read_text(encoding="utf-8")


def test_live_redactor_flushes_an_unterminated_tail_redacted(monkeypatch):
    monkeypatch.setenv("SOME_SECRET", "supersecretvalue")
    live = capture.LiveRedactor()
    assert live.feed("abc supersec") == ""
    assert live.feed("retvalue") == ""
    assert live.flush() == "abc [redacted:SOME_SECRET]"


def _live(pieces):
    live = capture.LiveRedactor()
    return "".join(live.feed(p) for p in pieces) + live.flush()


def test_live_redactor_never_splits_a_secret_on_a_long_line_without_a_newline(monkeypatch):
    secret = "supersecretvalue"
    monkeypatch.setenv("SOME_SECRET", secret)
    for text in ("x" * 510 + secret + "y" * 499, "x" * 600 + secret + "y" * 505):
        for size in (1, 7, 100, 513, 4096):
            pieces = [text[i:i + size] for i in range(0, len(text), size)]
            out = _live(pieces)
            assert "super" not in out.replace("[redacted:SOME_SECRET]", "") and "retvalue" not in out
            assert out == text.replace(secret, "[redacted:SOME_SECRET]")
        live = capture.LiveRedactor()
        emitted = live.feed(text)
        assert secret[:5] not in emitted.replace("[redacted:SOME_SECRET]", "")


def test_live_redactor_never_splits_a_cwa_key_across_the_boundary():
    key = "CWA-0123456789ABCDEF0123456789ABCDEF"
    for pad in (480, 510, 600, 1100):
        text = "x" * pad + key + "y" * 700
        out = _live([text[i:i + 64] for i in range(0, len(text), 64)])
        assert "CWA-0" not in out and "0123456789ABCDEF" not in out
        assert out == capture.redact(text)[0]


PEM = ("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n"
       "\nshort\nAbCdEfGhIjKlMnOpQrStUvWx==\n-----END PRIVATE KEY-----")


def test_live_redactor_releases_no_line_of_a_two_line_secret(monkeypatch):
    monkeypatch.setenv("SOME_SECRET", "abcdefgh\nijklmnop")
    live = capture.LiveRedactor()
    out = live.feed("abcdefgh\n") + live.feed("ijklmnop\n") + live.flush()
    assert "abcdefgh" not in out and "ijklmnop" not in out
    assert out.count("[redacted:") == 2


def test_live_redactor_hides_every_line_of_a_pem_value_at_any_chunk_size(monkeypatch):
    monkeypatch.setenv("PRIVATE_KEY", PEM)
    text = "before\n" + PEM + "\nafter\n"
    for size in (1, 5, 17, 64, 4096):
        out = _live([text[i:i + size] for i in range(0, len(text), size)])
        for line in PEM.splitlines():
            if len(line) >= capture.MIN_SECRET:
                assert line not in out
        assert out.startswith("before\n") and out.endswith("\nafter\n")
    assert capture.redact(text)[0] == _live([text])
    prefixed = "".join("> " + line + "\n" for line in PEM.splitlines())  # whole value never matches
    for size in (1, 5, 17, 4096):
        out = _live([prefixed[i:i + size] for i in range(0, len(prefixed), size)])
        for line in PEM.splitlines():
            if len(line) >= capture.MIN_SECRET:
                assert line not in out
        assert "> short\n" in out  # under the floor: cannot be matched alone


def test_check_finds_one_line_of_a_multiline_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATE_KEY", PEM)
    (tmp_path / "a.txt").write_text("x KcwggSjAgEAAoIBAQC7VJTUt9Us8cKj y\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nothing here\n", encoding="utf-8")
    assert [b.split(":")[0] for b in capture.check_tree(tmp_path)] == ["a.txt"]
