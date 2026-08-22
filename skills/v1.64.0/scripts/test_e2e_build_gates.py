#!/usr/bin/env python3
"""端到端:對 **agent 真的寫出來的程式碼** 跑施工階段的四道閘(CHG-20260803-02 T8)。

這不是模擬。fixture 裡的「agent」是一支真的會寫檔案的腳本:它會產生一個 Python 模組
與一份對應的測試,分成兩種人格——

  weak   只驗一條 happy path(典型的「AI 寫完程式順手補個測試」)
  strong 涵蓋分支與邊界

兩者的 `--test-cmd` **都會全綠**。差別只有變異閘看得出來:weak 的測試殺不掉種進去的錯。
這正是本閘存在的理由——同一個模型既寫程式又寫測試時,測試會系統性地只覆蓋它想得到的情況。

全部在 tmpdir 的真 git repo 內進行,不碰本 repo。
Run: python3 test_e2e_build_gates.py → exit 0 全過,1 有失敗。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

RUNNER = Path(__file__).with_name("autopilot_runner.py")
PY = f'"{sys.executable}"'

CHG = """# CHG-20260101-01 — fixture:分級函式

- 風險分級:低 | 實作者:fixture agent

### Global Constraints
- 一律以 stdlib 實作

### Tasks
- [ ] T1. 實作 grade() 並附測試
  - interfaces: consumes 分數 / produces 等第字串
  - test: 測試指令全綠

### Acceptance operation
- operate: 匯入 grade 跑一次
- observe: 回傳等第
- pass: 邊界正確

## 狀態
開單
"""

# 被寫出來的產品程式碼(兩種人格共用)——有三個分支、兩個邊界值
IMPL = '''
def grade(score):
    if score >= 90:
        return "A"
    if score >= 60:
        return "B"
    return "F"
'''

WEAK_TEST = '''
import sys
from calcmod import grade
sys.exit(0 if grade(100) == "A" else 1)
'''

STRONG_TEST = '''
import sys
from calcmod import grade
cases = [(100, "A"), (90, "A"), (89, "B"), (60, "B"), (59, "F"), (0, "F")]
sys.exit(0 if all(grade(s) == w for s, w in cases) else 1)
'''

# 「agent」:被 runner 以 {brief} 呼叫,真的寫檔進 cwd(runner 以 repo 為 cwd)
AGENT = '''
import sys, pathlib
mode = sys.argv[1]
pathlib.Path("calcmod.py").write_text({impl!r}, encoding="utf-8")
pathlib.Path("test_calcmod.py").write_text(
    {weak!r} if mode == "weak" else {strong!r}, encoding="utf-8")
print("agent wrote calcmod.py + test_calcmod.py")
'''.format(impl=IMPL, weak=WEAK_TEST, strong=STRONG_TEST)

DOCS_AGENT = '''
import sys, pathlib
pathlib.Path("NOTES.md").write_text("# notes\\n\\nagent wrote docs only\\n", encoding="utf-8")
print("agent wrote NOTES.md")
'''

# 注意:內層一律用單引號。python -c 的內容外面要包雙引號給 cmd.exe,
# 內層再用雙引號會被 shell 吃掉——這在 POSIX 下不會出錯,只有 Windows 會,
# 正是「全平台」這條需求存在的理由。
REVIEW_PASS = "import sys; print('[task-review] T1 | spec: pass | quality: pass | ok')"
REVIEW_BRANCH_PASS = "import sys; print('[task-review] branch | spec: pass | quality: pass | ok')"
REVIEW_SILENT = "import sys; print('看起來還行')"


def make_repo(agent_src, chg=CHG):
    d = Path(tempfile.mkdtemp())
    (d / "CHG-20260101-01.md").write_text(chg, encoding="utf-8")
    (d / "_agent.py").write_text(agent_src, encoding="utf-8")
    for args in ("init -q", "add -A",
                 '-c user.name=f -c user.email=f@e.com commit -q -m "CHG-20260101-01: fixture"'):
        subprocess.run(f"git {args}", shell=True, cwd=str(d), capture_output=True)
    return d


def run_build(d, *extra, agent_mode="strong", review=REVIEW_PASS):
    """跑 build;agent 指令會真的寫檔,review 指令回傳判定行。"""
    agent = f'{PY} "{d / "_agent.py"}" {agent_mode}'
    rev = f'{PY} -c "{review}"'
    cmd = [sys.executable, str(RUNNER), "build", "--chg", str(d / "CHG-20260101-01.md"),
           "--repo", str(d), "--agent-cmd", agent, "--review-cmd", rev, *extra]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    checks = []
    test_cmd = f'{PY} test_calcmod.py'

    # ---------- T1:沒有測試指令不得靜默放行 ----------
    d = make_repo(AGENT)
    rc, out = run_build(d)
    checks.append(("無 --test-cmd → halt(exit 3)", rc == 3 and "test-cmd" in out))
    checks.append(("halt 訊息點明「未經執行即打勾」風險", "一行測試都沒跑過" in out))
    d = make_repo(AGENT)
    rc, out = run_build(d, "--allow-untested")
    checks.append(("--allow-untested → 放行", rc == 0))
    checks.append(("--allow-untested 會印警告留痕", "未經執行" in out))

    # ---------- 單元測試真的被執行 ----------
    d = make_repo(AGENT)
    rc, out = run_build(d, "--test-cmd", test_cmd)
    checks.append(("強測試 + 單元閘 → exit 0", rc == 0))
    checks.append(("agent 真的寫出程式碼", (d / "calcmod.py").is_file()))
    checks.append(("agent 真的寫出測試", (d / "test_calcmod.py").is_file()))
    ticked = "- [x] T1." in (d / "CHG-20260101-01.md").read_text(encoding="utf-8")
    checks.append(("task 被打勾(續作點推進)", ticked))
    log = subprocess.run("git log --oneline -1", shell=True, cwd=str(d),
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    checks.append(("commit message 帶 CHG 編號", "CHG-20260101-01" in (log.stdout or "")))
    hs = d / "docs" / "worklog" / "handshake-autopilot.md"
    checks.append(("handshake 於 task 邊界落盤", hs.is_file()))

    # ---------- 變異閘:弱測試必須被擋,強測試必須放行 ----------
    d = make_repo(AGENT)
    rc, out = run_build(d, "--test-cmd", test_cmd, "--mutation", "--min-kill-rate", "90",
                        agent_mode="weak")
    checks.append(("弱測試(單元仍全綠)被變異閘擋下 → exit 3", rc == 3))
    checks.append(("擋下時列出存活變異體", "[存活]" in out))
    checks.append(("訊息點明『改錯了也不會被發現』", "不會被發現" in out))
    weak_ticked = "- [x] T1." in (d / "CHG-20260101-01.md").read_text(encoding="utf-8")
    checks.append(("被擋下的 task 不得被打勾", not weak_ticked))

    d = make_repo(AGENT)
    rc, out = run_build(d, "--test-cmd", test_cmd, "--mutation", "--min-kill-rate", "90",
                        agent_mode="strong")
    checks.append(("強測試通過變異閘 → exit 0", rc == 0))
    checks.append(("通過時回報 kill rate", "kill rate" in out))
    checks.append(("變異對象排除測試檔本身",
                   "test_calcmod.py: kill rate" not in out))

    # ---------- 非 Python 變更:必須是「未涵蓋」而非「通過」 ----------
    d = make_repo(DOCS_AGENT)
    rc, out = run_build(d, "--test-cmd", f'{PY} -c "import sys;sys.exit(0)"',
                        "--mutation", agent_mode="strong")
    checks.append(("純文件變更 → 放行", rc == 0))
    checks.append(("純文件變更標『未涵蓋』而非『通過』",
                   "未涵蓋" in out and "變異閘通過" not in out))

    # ---------- 平台涵蓋差集 ----------
    d = make_repo(AGENT)
    rc, out = run_build(d, "--test-cmd", test_cmd, "--test-platforms", "linux,macos,windows")
    checks.append(("宣告三平台 → 列出本輪未涵蓋者", rc == 0 and "未涵蓋" in out))

    # ---------- 整支 branch review 不再是 no-op ----------
    def run_review(d, review):
        cmd = [sys.executable, str(RUNNER), "review", "--chg", str(d / "CHG-20260101-01.md"),
               "--repo", str(d), "--review-cmd", f'{PY} -c "{review}"']
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    d = make_repo(AGENT, chg=CHG.replace("- [ ] T1.", "- [x] T1."))
    rc, out = run_review(d, REVIEW_BRANCH_PASS)
    checks.append(("整支 review 有判定行 → exit 0", rc == 0 and "整支 review 判定" in out))
    rc, out = run_review(d, REVIEW_SILENT)
    checks.append(("整支 review 無判定行 → exit 3(無輸出不得當通過)",
                   rc == 3 and "無判定行" in out))
    cmd = [sys.executable, str(RUNNER), "review", "--chg", str(d / "CHG-20260101-01.md"),
           "--repo", str(d)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    checks.append(("整支 review 未給審查指令 → exit 3(不得空跑)", r.returncode == 3))

    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    if failed:
        print(f"❌ {len(failed)}/{len(checks)} 失敗")
        return 1
    print(f"✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
