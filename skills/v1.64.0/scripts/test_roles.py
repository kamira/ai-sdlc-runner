#!/usr/bin/env python3
"""Standalone assertions for the role commands (no test framework in repo).

Focus: 拆指令**非治理繞道**——前置條件缺失必須 halt(exit 3)。
Run: python3 scripts/test_roles.py  → exit 0 all pass, 1 on failure.
"""
import os
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

RUNNER = Path(__file__).with_name("autopilot_runner.py")

CHG_TMPL = """# CHG-20260101-01 — fixture

- Risk: {risk}
- Skill: ai-sdlc v1.18

### Global Constraints
- fixture

### Tasks
{tasks}

{aop}

## 狀態
開單
"""
TASK = "- [{tick}] T{n}. task {n}\n  - interfaces: consumes a / produces b\n  - test: true"
AOP = "### Acceptance operation\n- operate: run it\n- observe: output\n- pass: ok"


def fixture(tasks_ticked, risk="low", aop=True):
    tasks = "\n".join(TASK.format(tick="x" if t else " ", n=i + 1)
                      for i, t in enumerate(tasks_ticked))
    d = Path(tempfile.mkdtemp())
    p = d / "CHG-20260101-01.md"
    p.write_text(CHG_TMPL.format(risk=risk, tasks=tasks, aop=AOP if aop else ""), encoding="utf-8")
    return d, p


def gh_env(present: bool) -> dict:
    """建構一份 PATH 受控的環境(CHG-20260803-01 T4)。

    `role_accept` 以 `shutil.which("gh")` 決定放行或 halt,所以測試結果原本取決於
    「這台機器有沒有裝 gh」——CI runner 有、開發機常常沒有,同一份斷言在兩邊給不同答案。
    改為兩個分支都明確建構:present=True 放一支假 gh 進 PATH,False 則給一個空 PATH。
    Windows 需 .bat(`shutil.which` 依 PATHEXT 解析),POSIX 需可執行位元。
    """
    d = Path(tempfile.mkdtemp())
    if present:
        if os.name == "nt":
            (d / "gh.bat").write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
        else:
            p = d / "gh"
            p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            p.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(d)
    return env


def run(role, chg, repo, *extra, env=None):
    cmd = [sys.executable, str(RUNNER), role, "--chg", str(chg)]
    if role not in ("plan", "plan-check", "status"):
        cmd += ["--repo", str(repo)]
    cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode


def main():
    checks = []

    # 負向:未完成 task 時,review / verify / accept 皆須 halt(非治理繞道)
    d, c = fixture([True, False])
    for role in ("review", "verify", "accept"):
        checks.append((f"{role} w/ unbuilt task → 3", run(role, c, d, "--dry-run") == 3))

    # 負向:全建完但未 verify → accept halt
    d, c = fixture([True, True])
    checks.append(("accept w/o verify → 3", run("accept", c, d) == 3))
    # CI 閘(CHG-20260803-04):即使 gh 存在、--verified 已給,
    # 查不到 CI 檢查仍不得合併——「沒有檢查」不等於「檢查都通過」。
    checks.append(("accept --verified w/ gh 但查無 CI → 3",
                   run("accept", c, d, "--verified", env=gh_env(True)) == 3))
    # 正向:明示 --allow-no-ci 後才放行(低風險)
    checks.append(("accept --verified + --allow-no-ci → 0",
                   run("accept", c, d, "--verified", "--allow-no-ci", env=gh_env(True)) == 0))
    # 負向:gh 不存在時必須 halt 交人開 PR(不得靜默當成已合併)
    checks.append(("accept --verified w/o gh → 3",
                   run("accept", c, d, "--verified", env=gh_env(False)) == 3))

    # 正向:全建完 → review / verify(dry-run)通過
    checks.append(("review all-built → 0", run("review", c, d, "--dry-run") == 0))
    checks.append(("verify all-built+AOP → 0", run("verify", c, d, "--dry-run") == 0))

    # 負向:程式類變更缺 Acceptance operation → verify halt
    d2, c2 = fixture([True, True], aop=False)
    checks.append(("verify w/o AOP → 3", run("verify", c2, d2) == 3))

    # 負向:高風險 confirm gate → build halt(未 --confirmed)
    d3, c3 = fixture([False], risk="high")
    checks.append(("build high-risk w/o --confirmed → 3", run("build", c3, d3, "--dry-run") == 3))

    # 相容:plan-check 別名 == plan
    d4, c4 = fixture([False])
    checks.append(("plan-check alias → 0", run("plan-check", c4, d4) == 0))
    checks.append(("plan → 0", run("plan", c4, d4) == 0))
    checks.append(("status → 0", run("status", c4, d4) == 0))

    # run 組合:低風險全流程 dry-run → 0
    d5, c5 = fixture([False, False])
    checks.append(("run compose dry-run → 0", run("run", c5, d5, "--dry-run") == 0))

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
