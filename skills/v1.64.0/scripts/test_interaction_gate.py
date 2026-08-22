#!/usr/bin/env python3
"""互動驗證閘的斷言(CHG-20260803-03 T9)。stdlib-only,三平台一致。

本閘的核心主張是「**指令回 0 不等於真的操作過**」——所以最重要的一組斷言是:
一個回報成功卻不產生任何產物的指令,必須被擋下。少了那一條,
`--interaction-cmd 'echo ok'` 就能過關,而那正是這套機制最想防的東西。

依 KN-003:所有「該擋而擋下」的斷言都另驗輸出不是崩潰。
Run: python3 test_interaction_gate.py → exit 0 全過,1 有失敗。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import interaction as INT  # noqa: E402

RUNNER = HERE / "autopilot_runner.py"
PY = f'"{sys.executable}"'

CHG_TMPL = """# CHG-20260101-01 — fixture

- 風險分級:{risk} | 實作者:fixture
- Skill: ai-sdlc-autopilot {ver}

### Global Constraints
- fixture

### Tasks
- [x] T1. 做完了
  - interfaces: consumes a / produces b
  - test: t

### Behaviour spec
- feature: dummy.feature

{ispec}

### Acceptance operation
- operate: x
- observe: y
- pass: z

## 狀態
開單
"""


def chg(ispec="", risk="低", ver="v1.6.0"):
    return CHG_TMPL.format(ispec=ispec, risk=risk, ver=ver)


def repo_with(ispec="", risk="低", ver="v1.6.0", make_artifact=None):
    d = Path(tempfile.mkdtemp())
    (d / "CHG-20260101-01.md").write_text(chg(ispec, risk, ver), encoding="utf-8")
    (d / "dummy.feature").write_text("# language: zh-TW\n功能: dummy\n", encoding="utf-8")
    if make_artifact:
        p = d / make_artifact
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    return d


def run_verify(d, *extra, trust=True):
    """trust 預設 True:本檔多數案例驗的是互動閘的機制,不是信任邊界。
    信任邊界本身另有三條專屬斷言(見下方),以及 features/chg_command_trust.feature。"""
    cmd = [sys.executable, str(RUNNER), "verify", "--chg", str(d / "CHG-20260101-01.md"),
           "--repo", str(d), "--verify-cmd", f'{PY} -c "import sys;sys.exit(0)"',
           "--gherkin-cmd", f'{PY} -c "import sys;sys.exit(0)" #', *extra]
    if trust:
        cmd.append("--trust-chg-commands")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_plan(d, *extra):
    cmd = [sys.executable, str(RUNNER), "plan", "--chg", str(d / "CHG-20260101-01.md"), *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def no_crash(out):
    return "Traceback" not in out


def main() -> int:
    checks = []
    kinds = INT.load_kinds()

    # ---------- 分類表 ----------
    checks.append(("分類表五種內建齊全",
                   set(kinds) == {"gui-web", "gui-native", "cli", "library-api",
                                  "service-protocol"}))
    checks.append(("每種都有非空 surface 與 artifacts",
                   all(k.get("surface") and k.get("artifacts") for k in kinds.values())))
    checks.append(("gui-web 的 surface 含滑鼠點擊",
                   any("滑鼠" in s for s in kinds["gui-web"]["surface"])))
    checks.append(("library-api 的 surface 含錯誤路徑",
                   any("錯誤路徑" in s for s in kinds["library-api"]["surface"])))

    # ---------- 前瞻適用與豁免 ----------
    checks.append(("v1.6.0 程式類 → 需要互動規格", INT.required(chg())))
    checks.append(("v1.5.0 → 不追溯", not INT.required(chg(ver="v1.5.0"))))
    checks.append(("docs-only → 不需要",
                   not INT.required(chg() + "\nAcceptance-operation: n/a (docs-only)\n")))
    checks.append(("空豁免視同未宣告", INT.exemption("Interaction-spec: n/a") == (True, None)))
    checks.append(("帶理由的豁免可辨識",
                   INT.exemption("Interaction-spec: n/a(一次性腳本)")[1] == "一次性腳本"))
    # 文件示例不得被當成真的豁免:CHG 內說明語法的那一行(反引號包住)
    # 曾讓任何提到這個語法的 CHG 意外豁免自己。
    checks.append(("行內程式碼的語法說明不算豁免",
                   INT.exemption("豁免寫成 `Interaction-spec: n/a(<理由>)` 這樣")
                   == (False, None)))
    checks.append(("句中提及(非行首)不算豁免",
                   INT.exemption("請參考 Interaction-spec: n/a 的寫法") == (False, None)))
    checks.append(("清單項的豁免仍可辨識",
                   INT.exemption("- Interaction-spec: n/a(純設定變更)")[1] == "純設定變更"))

    # ---------- plan-check 層 ----------
    rc, out = run_plan(repo_with())
    checks.append(("無互動規格 → plan-check exit 2", rc == 2 and no_crash(out)))
    checks.append(("擋下時列出全部可選種類(無預設值)",
                   all(k in out for k in kinds) and "預設" not in out.split("無預設值")[-1]))
    rc, out = run_plan(repo_with("Interaction-spec: n/a"))
    checks.append(("空豁免 → plan-check exit 2 且要求理由",
                   rc == 2 and "理由" in out and no_crash(out)))
    rc, out = run_plan(repo_with("Interaction-spec: n/a(一次性遷移腳本,不會被複用)"))
    checks.append(("帶理由豁免 → plan-check 通過", rc == 0 and "已豁免" in out))
    rc, out = run_plan(repo_with(ver="v1.5.0"))
    checks.append(("v1.5.0 缺規格 → 不擋(前瞻適用)", rc == 0))

    # ---------- 種類合法性 ----------
    SPEC = ("### Interaction spec\n- kind: {kind}\n- cmd: {cmd}\n- artifacts: {art}\n")
    d = repo_with(SPEC.format(kind="我發明的種類", cmd="echo x", art="a.png"))
    rc, out = run_verify(d)
    checks.append(("未登記的種類 → halt 並列出可選項",
                   rc == 3 and "不在分類表內" in out and "gui-web" in out and no_crash(out)))

    # 自訂分類表可增補
    custom = Path(tempfile.mkdtemp()) / "kinds.json"
    custom.write_text(json.dumps({"kinds": {"我的種類": {
        "label": "自訂", "surface": ["某個操作"], "artifacts": ["out.log"]}}},
        ensure_ascii=False), encoding="utf-8")
    touch = f'{PY} -c "open(\'out.log\',\'w\').write(\'x\')"'
    d = repo_with(SPEC.format(kind="我的種類", cmd=touch, art="out.log"))
    rc, out = run_verify(d, "--interaction-kinds", str(custom))
    checks.append(("使用者增補的種類生效", rc == 0 and no_crash(out)))

    # ---------- 產物是核心:回 0 但沒產物必須擋 ----------
    d = repo_with(SPEC.format(kind="cli", cmd=f'{PY} -c "import sys;sys.exit(0)"',
                              art="session.log"))
    rc, out = run_verify(d)
    checks.append(("指令回 0 但產物未出現 → halt",
                   rc == 3 and "產物" in out and no_crash(out)))
    checks.append(("訊息點明「指令回 0 不等於真的操作過」", "不等於真的操作過" in out))
    checks.append(("訊息列出實際檢查的路徑", "實際檢查的路徑" in out))

    # 產物存在但為 0 bytes → 同樣視同缺少(0 bytes 的截圖不是證據)
    d = repo_with(SPEC.format(kind="cli", cmd=f'{PY} -c "open(\'session.log\',\'w\')"',
                              art="session.log"))
    rc, out = run_verify(d)
    checks.append(("產物存在但為空檔 → 仍 halt", rc == 3 and "產物" in out))

    # 正例:產物真的出現
    good = f'{PY} -c "open(\'session.log\',\'w\').write(\'ran\')"'
    d = repo_with(SPEC.format(kind="cli", cmd=good, art="session.log"))
    rc, out = run_verify(d)
    checks.append(("產物齊備 → 通過", rc == 0 and "互動驗證通過" in out))
    checks.append(("通過時列出產物", "session.log" in out))

    # ---------- 缺 cmd ----------
    d = repo_with("### Interaction spec\n- kind: cli\n- artifacts: a.log\n")
    rc, out = run_verify(d)
    checks.append(("宣告種類但無 cmd → halt", rc == 3 and "cmd" in out and no_crash(out)))

    # ---------- 驅動不存在 → 依風險分級 ----------
    missing = "no_such_driver_xyz --run"
    for risk, want_rc, needle in (("低", 0, "未涵蓋"), ("中", 3, "停下交人"), ("高", 3, "停下交人")):
        d = repo_with(SPEC.format(kind="gui-web", cmd=missing, art="shot.png"), risk=risk)
        rc, out = run_verify(d)
        checks.append((f"{risk}風險 + 驅動不存在 → {'放行標未涵蓋' if want_rc == 0 else 'halt'}",
                       rc == want_rc and needle in out and no_crash(out)))
    # 未涵蓋不得看起來像通過
    d = repo_with(SPEC.format(kind="gui-web", cmd=missing, art="shot.png"), risk="低")
    _, out = run_verify(d)
    checks.append(("未涵蓋的輸出不得含「互動驗證通過」", "互動驗證通過" not in out))

    # ---------- 信任邊界(CHG-20260803-05)----------
    # CHG 檔案裡的 cmd 是**內容驅動執行**:能讓一份 CHG 進到 repo 的人,
    # 就能讓 autopilot 以 shell 跑任意指令,而且產物存在就算通過。
    d = repo_with(SPEC.format(kind="cli", cmd=good, art="session.log"))
    rc, out = run_verify(d, trust=False)
    checks.append(("預設不執行 CHG 宣告的指令 → halt",
                   rc == 3 and "內容驅動執行" in out))
    checks.append(("擋下時不得已經執行過(產物不該存在)",
                   not (d / "session.log").exists()))
    checks.append(("訊息指出兩條路(--interaction-cmd / --trust-chg-commands)",
                   "--interaction-cmd" in out and "--trust-chg-commands" in out))
    d = repo_with(SPEC.format(kind="cli", cmd=good, art="session.log"))
    rc, out = run_verify(d, trust=True)
    checks.append(("明示信任後才執行", rc == 0 and (d / "session.log").exists()))
    checks.append(("成功訊息記錄指令來源(供 ACC 稽核)", "指令來源" in out))
    checks.append(("執行前印出指令原文", "即將執行" in out))

    # ---------- --interaction-cmd 覆寫 ----------
    d = repo_with(SPEC.format(kind="cli", cmd="no_such_cmd", art="session.log"))
    rc, out = run_verify(d, "--interaction-cmd", good)
    checks.append(("--interaction-cmd 可覆寫且產物檢查仍生效", rc == 0 and no_crash(out)))

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
