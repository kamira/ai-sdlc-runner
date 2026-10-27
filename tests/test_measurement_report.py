"""The measurement report holds together: its links resolve, every step is in it, no secret is kept. (CHG-20261019-01)

Needs no network and no browser; it reads the files the measurement left behind.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MEASURE = ROOT / "docs" / "measurements" / "CHG-20261019-01"
REPORT = MEASURE / "report.md"
STEPS = MEASURE / "steps" / "steps.jsonl"

spec = importlib.util.spec_from_file_location("measurement_capture", MEASURE / "capture.py")
capture = importlib.util.module_from_spec(spec)
sys.modules["measurement_capture"] = capture
spec.loader.exec_module(capture)

LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def report_text():
    return REPORT.read_text(encoding="utf-8")


def test_every_relative_link_and_image_in_the_report_exists():
    missing = []
    for target in LINK.findall(report_text()):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|#|/", target):
            continue                                  # a URL, an anchor, or not a repo-relative path
        path = target.split("#")[0].split("?")[0]
        if path and not (REPORT.parent / path).exists():
            missing.append(target)
    assert not missing


def test_every_step_names_files_that_exist_and_the_report_shows_them():
    text = report_text()
    lines = [ln for ln in STEPS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines
    problems = []
    for ln in lines:
        entry = json.loads(ln)
        assert entry["files"], "step %s names no file" % entry["step"]
        for rel in entry["files"]:
            if not (MEASURE / rel).is_file():
                problems.append("step %s: %s does not exist" % (entry["step"], rel))
            if rel.endswith((".png", ".txt")) and rel not in text:
                problems.append("step %s: %s is not in report.md" % (entry["step"], rel))
    assert not problems


@pytest.mark.parametrize("tree", [MEASURE, ROOT / "examples" / "weather-live"], ids=lambda p: p.name)
def test_no_secret_is_kept_under_the_measurement_or_the_example(tree):
    assert tree.is_dir()
    assert capture.check_tree(tree, {}) == []         # empty environment: only the patterns count
