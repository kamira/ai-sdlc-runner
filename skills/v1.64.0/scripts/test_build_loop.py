#!/usr/bin/env python3
"""回修迴圈的單元斷言(CHG-20260803-07)。

原本的 `_build_one` 叫「一次回修機會」,但兩輪都用同一份 brief——沒有帶上一輪
失敗的原因。那不是回修,是再擲一次骰子。本檔驗的是修好之後的那條路:
失敗原因擷取 → 回送下一輪 → 分級升階 → 達上限逐項列出未解項。

決策核心一律寫成純函式(不起 subprocess),理由同 ci_gate:
行為不該取決於當下有沒有可用的 agent 指令。

Run: python3 test_build_loop.py → exit 0 全過,1 有失敗。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import exec_util as EU    # noqa: E402

RUNNER = Path(__file__).with_name("autopilot_runner.py")
PY = f'"{sys.executable}"'

CHG = """# CHG-20260101-02 — fixture:回修迴圈

- 風險分級:低 | 實作者:fixture agent

### Global Constraints
- 一律以 stdlib 實作

### Tasks
- [ ] T1. 實作 addmod 並附測試
  - interfaces: consumes 兩數 / produces 和
  - test: 測試指令全綠

### Acceptance operation
- operate: 匯入 add 跑一次
- observe: 回傳和
- pass: 邊界正確

## 狀態
開單
"""

# 假 agent:把收到的 brief 原封不動存檔(供斷言「回饋有沒有進到 brief」),再寫實作。
BRIEF_SPY = '''
import sys, pathlib
brief = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
log = pathlib.Path("briefs.log")
prev = log.read_text(encoding="utf-8") if log.exists() else ""
log.write_text(prev + "\\n===BRIEF===\\n" + brief, encoding="utf-8")
pathlib.Path("addmod.py").write_text("def add(a, b):\\n    return a + b\\n", encoding="utf-8")
pathlib.Path("test_addmod.py").write_text(
    "from addmod import add\\n"
    "assert add(1, 2) == 3\\n"
    "assert add(-1, 1) == 0\\n"
    "assert add(0, 0) == 0\\n", encoding="utf-8")
print("agent wrote addmod")
'''

# 第一次跑必失敗(印出可辨識的原文),之後放行——用來製造「第 1 輪紅、第 2 輪綠」
FLAKY_TEST = '''
import pathlib, sys
c = pathlib.Path("_round")
n = int(c.read_text()) if c.exists() else 0
c.write_text(str(n + 1))
if n == 0:
    print("BOOM_MARKER_XYZ: expected 3 got 4")
    sys.exit(1)
import test_addmod
'''

# 假審查者:同樣把 brief 存檔(複審有沒有拿到 findings 清單要靠這個驗),再印判定行。
REVIEW_SPY = '''
import sys, pathlib
brief = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
log = pathlib.Path("reviews.log")
prev = log.read_text(encoding="utf-8") if log.exists() else ""
log.write_text(prev + "\\n===REVIEW===\\n" + brief, encoding="utf-8")
print("[task-review] T1 | spec: pass | quality: pass | ok")
'''


def _mkrepo():
    d = Path(tempfile.mkdtemp())
    (d / "CHG-20260101-02.md").write_text(CHG, encoding="utf-8")
    (d / "_agent.py").write_text(BRIEF_SPY, encoding="utf-8")
    (d / "_review.py").write_text(REVIEW_SPY, encoding="utf-8")
    (d / "_flaky.py").write_text(FLAKY_TEST, encoding="utf-8")
    # argv 陣列而非 shell=True:這裡不需要管線或重導向,而 shell=True 是注入形態,
    # 能不用就不該用——少一條具名豁免,勝過多一條寫得很好的理由。
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=f", "-c", "user.email=f@e.com",
                  "commit", "-q", "-m", "CHG-20260101-02: fixture"]):
        subprocess.run(["git", *args], cwd=str(d), capture_output=True)
    return d


def _run_build(d, *extra, test_cmd=None):
    agent = f'{PY} "{d / "_agent.py"}"' + " {brief}"
    rev = f'{PY} "{d / "_review.py"}"' + " {brief}"
    cmd = [sys.executable, str(RUNNER), "build", "--chg", str(d / "CHG-20260101-02.md"),
           "--repo", str(d), "--agent-cmd", agent, "--review-cmd", rev,
           "--test-cmd", test_cmd or f'{PY} "{d / "_flaky.py"}"', "--no-commit", *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def t2_t6_t7_wiring(checks):
    """T2/T6/T7:回饋真的進到 brief、複審拿到 findings、變異閘預設開。"""
    d = _mkrepo()
    rc, out = _run_build(d)
    briefs = (d / "briefs.log").read_text(encoding="utf-8") if (d / "briefs.log").exists() else ""
    rounds = briefs.split("===BRIEF===")[1:]

    checks.append(("回修後整體通過", rc == 0))
    checks.append(("確實跑了兩輪施工", len(rounds) >= 2))
    if len(rounds) >= 2:
        # T2:第一輪不含回饋,第二輪含第一輪失敗的**原文**
        checks.append(("第 1 輪 brief 不含回饋段", "上一輪失敗原因" not in rounds[0]))
        checks.append(("第 2 輪 brief 含回饋段", "上一輪失敗原因" in rounds[1]))
        checks.append(("第 2 輪 brief 含第 1 輪失敗原文", "BOOM_MARKER_XYZ" in rounds[1]))
        checks.append(("回饋標明來源為 test", "[failed-gate: test]" in rounds[1]))
    # T6:複審 brief 帶上前一輪的 findings 清單,並要求逐項回覆
    reviews = (d / "reviews.log").read_text(encoding="utf-8") if (d / "reviews.log").exists() else ""
    checks.append(("複審 brief 帶 findings 清單", "本輪須確認的 findings" in reviews))
    checks.append(("複審 brief 含前一輪失敗原文", "BOOM_MARKER_XYZ" in reviews))
    checks.append(("複審 brief 要求逐項回覆", "已解" in reviews and "未解" in reviews))
    # T7:沒給任何變異旗標 → 變異閘仍執行
    checks.append(("變異閘預設執行", "變異閘" in out))

    # T7 反例:--no-mutation 明示關閉且留痕
    d2 = _mkrepo()
    rc2, out2 = _run_build(d2, "--no-mutation")
    checks.append(("--no-mutation 有留痕", "--no-mutation 明示關閉" in out2))
    checks.append(("--no-mutation 須記入 ACC", "未涵蓋欄" in out2))
    checks.append(("--no-mutation 後變異閘不執行", "變異閘:" not in out2))

    # T3 接線:上限設 1 → 第一輪失敗即 halt,且列出未解項
    d3 = _mkrepo()
    rc3, out3 = _run_build(d3, "--max-fix-rounds", "1")
    checks.append(("上限 1 時失敗即 halt", rc3 == 3))
    checks.append(("halt 訊息列出未解項", "各輪未解項" in out3 and "第 1 輪" in out3))
    checks.append(("halt 訊息標明來源", "[test]" in out3))


def t1_failure_note(checks):
    """T1:失敗原因擷取成帶來源標籤的段落,原文不轉述。"""
    for src, payload in (("test", "AssertionError: expected 3 got 4"),
                         ("static", "S102 eval() 於 lib/foo.py:12"),
                         ("mutation", "存活: lib/bar.py:88 compare Lt -> Le"),
                         ("review", "[task-review] T3 | spec: fail | quality: pass | 理由")):
        note = EU.failure_note(src, payload)
        checks.append((f"failure_note[{src}] 含原文", payload in note))
        checks.append((f"failure_note[{src}] 標明來源", src in note))

    # 過長輸入:截斷且**標明**截斷——沒標明的截斷會讓人以為那就是全部
    long_note = EU.failure_note("test", "x" * 5000, limit=200)
    checks.append(("過長輸入被截斷", len(long_note) < 5000))
    checks.append(("截斷有標明", "截斷" in long_note))

    # 空輸出:不炸,且不得聲稱通過(否則回饋會反過來誤導下一輪)
    empty = EU.failure_note("review", "")
    checks.append(("空輸出不炸且標明來源", "review" in empty))
    checks.append(("空輸出不得聲稱通過",
                   "通過" not in empty and "pass" not in empty.lower()))

    # ANSI 色碼要清掉:實際操作驗收時發現彩色 traceback 會把逃脫序列送進回饋,
    # 那是給終端機看的,而且會吃掉截斷額度
    ansi = EU.failure_note("test", "\x1b[35mAssertionError\x1b[0m: boom")
    checks.append(("ANSI 色碼被清除", "\x1b[" not in ansi))
    checks.append(("清 ANSI 後訊息本體仍在", "AssertionError" in ansi and "boom" in ansi))

    # 未知來源要擋:來源標籤是給下一輪讀的,拼錯了等於沒標
    try:
        EU.failure_note("typo-source", "x")
        checks.append(("未知來源應被拒絕", False))
    except ValueError:
        checks.append(("未知來源應被拒絕", True))

    # compose_extra:第一輪(無 notes)必須是空字串
    checks.append(("第一輪附加段為空", EU.compose_extra([]) == ""))
    extra = EU.compose_extra([EU.failure_note("test", "AssertionError: boom")])
    checks.append(("附加段含原文", "AssertionError: boom" in extra))
    checks.append(("附加段要求逐項修正", "修正" in extra))


def t3_t4_rounds(checks):
    """T3/T4:輪數參數化 + 最後一輪升階。"""
    # T3:未達上限就續作,達上限即停下——不得靜默放行
    cont, verdict = EU.next_round(1, 3)
    checks.append(("第 1/3 輪:續作", cont and verdict == "retry"))
    cont, verdict = EU.next_round(3, 3)
    checks.append(("第 3/3 輪:停下", (not cont) and verdict == "halt"))
    cont, verdict = EU.next_round(1, 1)
    checks.append(("上限為 1 時第一輪失敗即停下", (not cont) and verdict == "halt"))

    # T4:前幾輪用原指令,最後一輪換升階指令
    for rnd, want in ((1, "agent-cmd"), (2, "agent-cmd"), (3, "strong-cmd")):
        cmd, warn = EU.agent_for_round(rnd, 3, "agent-cmd", "strong-cmd")
        checks.append((f"第 {rnd} 輪使用 {want}", cmd == want))
        checks.append((f"第 {rnd} 輪有升階指令時不該有警語", warn is None))

    # 未給升階指令:沿用原指令,但**必須明講盲點沒換**
    cmd, warn = EU.agent_for_round(3, 3, "agent-cmd", None)
    checks.append(("未給升階指令時沿用原指令", cmd == "agent-cmd"))
    checks.append(("未給升階指令時有警語", bool(warn)))
    checks.append(("警語點明同模型盲點", bool(warn) and "盲點" in warn))
    cmd, warn = EU.agent_for_round(1, 3, "agent-cmd", None)
    checks.append(("未給升階指令時前幾輪不出警語", warn is None))


def t5_unresolved(checks):
    """T5:達上限時逐項列出各輪未解項,而不是只印最後一行。"""
    entries = [(1, "test", "AssertionError: expected 3 got 4"),
               (2, "static", "S102 eval() 於 lib/foo.py:12"),
               (3, "review", "[task-review] T3 | spec: fail | quality: pass")]
    msg = EU.unresolved_report(entries)
    checks.append(("未解項報告含三筆", all(e[2][:20] in msg for e in entries)))
    for rnd, src, _ in entries:
        checks.append((f"第 {rnd} 輪標明輪次", f"第 {rnd} 輪" in msg))
        checks.append((f"第 {rnd} 輪標明來源 {src}", src in msg))
    # 只有一筆時也要是同一種格式,不能退化成單行
    one = EU.unresolved_report([(1, "test", "boom")])
    checks.append(("單筆也標明輪次與來源", "第 1 輪" in one and "test" in one))
    checks.append(("空清單不炸", isinstance(EU.unresolved_report([]), str)))
    # 報告是印給人看的,夾帶 ANSI 會讓輪次之間的界線讀不出來
    ansi_rep = EU.unresolved_report([(1, "test", "\x1b[35mAssertionError\x1b[0m: boom")])
    checks.append(("未解項報告清掉 ANSI", "\x1b[" not in ansi_rep))


def t8_handshake(checks):
    """T8:交接文件的既有內容不得被機器覆寫。"""
    human = ("# handshake — autopilot(常駐)\n\n"
             "## 交接第一優先\n\n委派層的四種驗證尚未真的接上工具。\n")

    # 有人寫內容、無標記 → 附加區塊,既有內容一字不動
    d1 = Path(tempfile.mkdtemp())
    hs1 = d1 / "docs" / "worklog" / "handshake-autopilot.md"
    hs1.parent.mkdir(parents=True, exist_ok=True)
    hs1.write_text(human, encoding="utf-8")
    EU.write_handshake(d1, "CHG-20260803-07", "task T8", "接線")
    got1 = hs1.read_text(encoding="utf-8")
    checks.append(("既有內容逐字保留", human.strip() in got1))
    checks.append(("附加了 autopilot 標記", EU.HANDSHAKE_BEGIN in got1))
    checks.append(("區塊含當前進度", "CHG-20260803-07" in got1 and "task T8" in got1))

    # 已有標記 → 只換區塊內容,標記不重複長出來
    EU.write_handshake(d1, "CHG-20260803-07", "task T9", "測試")
    got2 = hs1.read_text(encoding="utf-8")
    checks.append(("二次寫入仍保留人寫內容", human.strip() in got2))
    checks.append(("標記只有一組", got2.count(EU.HANDSHAKE_BEGIN) == 1
                   and got2.count(EU.HANDSHAKE_END) == 1))
    checks.append(("區塊內容已更新", "task T9" in got2 and "task T8" not in got2))

    # 檔案不存在 → 建檔且含標記
    d2 = Path(tempfile.mkdtemp())
    EU.write_handshake(d2, "CHG-20260803-07", "task T1", "起步")
    got3 = (d2 / "docs" / "worklog" / "handshake-autopilot.md").read_text(encoding="utf-8")
    checks.append(("無檔案時建檔含標記", EU.HANDSHAKE_BEGIN in got3 and "task T1" in got3))
    checks.append(("仍標記 UTC+0", "UTC+0" in got3))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t1_failure_note(checks)
    t3_t4_rounds(checks)
    t5_unresolved(checks)
    t8_handshake(checks)
    t2_t6_t7_wiring(checks)

    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        if not ok:
            print(f"  [FAIL] {n}")
    if failed:
        print(f"❌ {len(failed)}/{len(checks)} 失敗")
        return 1
    print(f"✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
