#!/usr/bin/env python3
"""Standalone assertions for autopilot_sentinels.py (no test framework in repo).

Uses synthetic policies (true/false/missing commands) so the two-tier escape is
exercised deterministically, independent of repo state.
Run: python3 scripts/test_autopilot_sentinels.py  → exit 0 all pass, 1 on failure.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# 釘住輸出編碼(CHG-20260803-01 T1):不依賴主控台/locale 的 ambient 編碼。
# 非 UTF-8 主控台(如 Windows cp932)印 CJK/emoji 會 UnicodeEncodeError;
# 釘住後同一份程式在任何平台的輸出行為一致。errors="replace" 確保永不因輸出而崩潰。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SENT = Path(__file__).with_name("autopilot_sentinels.py")


def policy(sentinels):
    return {"version": 1, "sentinels": sentinels,
            "reentry": {"max_reentry": 20, "base_case": ["max_reentry_reached"]},
            "escape": {"tier_a_cannot_evaluate": {"outcome": "exit0_baseline"},
                       "tier_b_real_halt": {"outcome": "exit3_escalate"}}}


def run(pol, extra=None):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(pol, f)
        path = f.name
    cmd = [sys.executable, str(SENT), "poll", "--repo", ".", "--policy", path] + (extra or [])
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode


# 跨平台假指令(CHG-20260803-01 T4):原本用 POSIX 的 `true` / `false`,
# Windows cmd.exe 沒有這兩個指令 —— 「必定成功」的假指令在 Windows 上必定失敗,
# 斷言在該平台全數失去意義。改用執行期直譯器,三平台語意完全相同。
PY = f'"{sys.executable}"'
OK_CMD = f'{PY} -c "import sys;sys.exit(0)"'
FAIL_CMD = f'{PY} -c "import sys;sys.exit(1)"'


def main():
    checks = []

    # all OK → exit 0
    checks.append(("all-ok → 0", run(policy({"a": {"cmd": OK_CMD}})) == 0))
    # a check ran and flagged → Tier B → exit 3
    checks.append(("flag(non-zero) → 3 (Tier B)",
                   run(policy({"a": {"cmd": OK_CMD}, "b": {"cmd": FAIL_CMD}})) == 3))
    # command missing → Tier A cannot-evaluate → exit 0 baseline
    checks.append(("missing cmd → 0 (Tier A)",
                   run(policy({"a": {"cmd": "no_such_cmd_xyz_123"}})) == 0))
    # base case: reentry over max → exit 0
    checks.append(("reentry>max → 0 (base case)",
                   run(policy({"a": {"cmd": FAIL_CMD}}), ["--reentry-count", "999"]) == 0))
    # requires_chg 且無 --chg → A 層略過(不得以預設值做恆真查詢而恆紅)
    checks.append(("requires_chg w/o --chg → 0 (skip, not tautology)",
                   run(policy({"a": {"cmd": OK_CMD},
                               "b": {"cmd": FAIL_CMD, "requires_chg": True}})) == 0))
    # 有 CHG 脈絡時,同一 check 仍須能回 B 層
    checks.append(("requires_chg w/ --chg → 3 (still escalates)",
                   run(policy({"b": {"cmd": FAIL_CMD, "requires_chg": True}}),
                       ["--chg", "dummy.md"]) == 3))

    # unloadable policy path → exit 0 degrade
    r = subprocess.run([sys.executable, str(SENT), "poll", "--repo", ".",
                        "--policy", "/nonexistent/policy.json"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    checks.append(("unloadable policy → 0 (degrade)", r.returncode == 0))

    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    if failed:
        print(f"❌ {len(failed)} 失敗")
        return 1
    print(f"✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
