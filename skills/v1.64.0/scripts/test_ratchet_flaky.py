#!/usr/bin/env python3
"""測試棘輪與不穩定測試偵測的單元斷言(CHG-20260803-08)。

`test_gates_wired.py` 擋住了「拔掉閘門」;本檔守的是下一層——**拔掉測試**。
變異閘對「測試被刪光」完全無感(沒有測試就沒有存活變異體,它回報未涵蓋),
而讓 build 轉綠最省事的做法正是刪掉那個紅的測試。

第二道守的是「跑一次剛好綠」:同一份程式碼重跑,結果必須一致。

決策層一律純函式(不起 subprocess、不碰 git),IO 層另以整合斷言驗一次。

Run: python3 test_ratchet_flaky.py → exit 0 全過,1 有失敗。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ratchet as R    # noqa: E402

TWO_TESTS = '''
def test_a():
    pass

def test_b():
    pass
'''

THREE_ASSERTS = '''
def test_a():
    assert 1 == 1
    assert 2 == 2
    assert 3 == 3
'''

COMMENTED_ASSERT = '''
def test_a():
    # assert 1 == 2
    pass
'''

STRING_ASSERT = '''
def test_a():
    msg = "assert 1 == 2"
    return msg
'''


def t1_metrics(checks):
    """T1:三個指標以 AST 計數;註解與字串不算。"""
    m = R.test_metrics(TWO_TESTS)
    checks.append(("兩個測試函式 → tests=2", m and m["tests"] == 2))
    m = R.test_metrics(THREE_ASSERTS)
    checks.append(("三個 assert → asserts=3", m and m["asserts"] == 3))
    checks.append(("同一份也數得出 tests=1", m and m["tests"] == 1))

    # grep 會誤報的兩種形態——這正是不用 grep 的理由(同 CHG-20260803-06)
    m = R.test_metrics(COMMENTED_ASSERT)
    checks.append(("註解裡的 assert 不算", m and m["asserts"] == 0))
    m = R.test_metrics(STRING_ASSERT)
    checks.append(("字串裡的 assert 不算", m and m["asserts"] == 0))

    # 語句數是資訊欄位,不參與棘輪判定,但要真的有數到
    m = R.test_metrics(TWO_TESTS)
    checks.append(("語句數為正", m and m["stmts"] > 0))

    # 語法錯誤:回報而非崩潰(沿用 static_check 的處置)
    try:
        bad = R.test_metrics("def test_a(:\n  pass\n")
        checks.append(("語法錯誤回 None 而非拋例外", bad is None))
    except Exception:
        checks.append(("語法錯誤回 None 而非拋例外", False))

    # 命名慣例因專案而異(本 repo 的測試就叫 t1_metrics),所以測試檔裡的
    # **每一個**函式都算。綁死 `test_` 前綴等於綁死適用範圍。
    m = R.test_metrics("def helper():\n    assert 1\n")
    checks.append(("不限 test_ 前綴,函式都計入 tests", m and m["tests"] == 1))
    checks.append(("其中的 assert 仍計入", m and m["asserts"] == 1))

    # unittest 風格:只認 ast.Assert 會對整個生態失效
    m = R.test_metrics("def test_a(self):\n    self.assertEqual(1, 1)\n"
                       "    self.assertTrue(True)\n")
    checks.append(("assertEqual/assertTrue 也算斷言", m and m["asserts"] == 2))

    # 迴歸:本 repo 自己的測試檔必須量得出東西——
    # 一個對自己的程式碼失效的閘,是最難發現的失效
    own = R.test_metrics(Path(__file__).read_text(encoding="utf-8"))
    checks.append(("本檔自身量得出 tests > 0(自家慣例不用 assert)",
                   own and own["tests"] > 0))


def _m(files, tests, asserts, stmts=0):
    return {"files": files, "tests": tests, "asserts": asserts, "stmts": stmts}


def t3_decide(checks):
    """T3:淨減少即擋下,正當重構不誤擋。"""
    cases = [
        ("刪掉一個測試函式", _m(1, 3, 9), _m(1, 2, 6), False),
        ("刪掉一整個測試檔", _m(2, 4, 10), _m(1, 2, 5), False),
        ("assert 變少但函式數不變", _m(1, 2, 6), _m(1, 2, 4), False),
        # 檔案數下降但總量不變——這是重構,不是規避。files 若列入棘輪就會誤擋這一格
        ("三檔合併為一檔、總量不變", _m(3, 6, 12), _m(1, 6, 12), True),
        ("新增測試", _m(1, 2, 4), _m(2, 5, 11), True),
        ("完全沒動測試", _m(1, 2, 4), _m(1, 2, 4), True),
    ]
    for name, before, after, want_ok in cases:
        ok, _msg = R.decide(before, after)
        checks.append((f"棘輪[{name}] → {'放行' if want_ok else '擋下'}", ok is want_ok))

    # 擋下時要說清楚是哪個指標、少了多少
    ok, msg = R.decide(_m(1, 3, 9), _m(1, 2, 6))
    checks.append(("擋下訊息點名指標 tests", (not ok) and "tests" in msg))
    checks.append(("擋下訊息給出前後數量", "3 → 2" in msg))
    checks.append(("擋下訊息指出逃生口", "--allow-test-reduction" in msg))

    # 明示豁免 → 放行,但必須留痕
    ok, msg = R.decide(_m(1, 3, 9), _m(1, 2, 6), allow_reduction=True)
    checks.append(("明示豁免後放行", ok))
    checks.append(("豁免須記入 ACC", "未涵蓋欄" in msg))

    # 非 Python:未涵蓋而非通過
    ok, msg = R.decide(_m(1, 2, 4), _m(1, 2, 4), uncovered=[".ts"])
    checks.append(("非 Python 測試檔標未涵蓋", ok and "未涵蓋" in msg))
    checks.append(("未涵蓋時不得聲稱全面通過", "棘輪通過" not in msg))

    # 通過時的訊息要能讓人看到實際數字(否則綠燈沒有資訊量)
    ok, msg = R.decide(_m(1, 2, 4), _m(1, 3, 6))
    checks.append(("通過訊息含前後數量", ok and "tests 2→3" in msg))

    # 語句數的容忍帶:抓「斷言被整批刪掉」,不抓「順手把測試寫短一點」。
    # 這一條是實測踩出來的——本 repo 的測試用 checks.append 註冊斷言,
    # 只看 tests/asserts 的話,把斷言全刪掉而保留函式外殼會整個放行。
    def s(t, a, st):
        return {"files": 1, "tests": t, "asserts": a, "stmts": st}
    band = [("刪掉一半的斷言註冊", s(2, 0, 88), s(2, 0, 44), False),
            ("寫短 5%(正當整理)", s(2, 0, 88), s(2, 0, 84), True),
            ("寫短 9%(容忍帶內)", s(2, 0, 88), s(2, 0, 80), True),
            ("砍掉 15%(超出容忍帶)", s(2, 0, 88), s(2, 0, 74), False)]
    for name, b, a, want_ok in band:
        ok, _ = R.decide(b, a)
        checks.append((f"語句容忍帶[{name}] → {'放行' if want_ok else '擋下'}", ok is want_ok))


def t4_flaky(checks):
    """T4:同一份程式碼重跑,結果必須一致。"""
    for codes, want_ok in ((("0,0"), True), ("0,1", False), ("1,0", False),
                           ("0,0,0", True), ("0,0,1", False)):
        seq = [int(c) for c in codes.split(",")]
        ok, _msg = R.flaky_decide(seq)
        checks.append((f"flaky[{codes}] → {'放行' if want_ok else '擋下'}", ok is want_ok))

    ok, msg = R.flaky_decide([0, 1])
    checks.append(("不穩定訊息含兩次退出碼", (not ok) and "0, 1" in msg))

    # 重跑次數:下限 1,且為 1 時必須留痕
    n, note = R.flaky_runs(1)
    checks.append(("次數 1 即為 1", n == 1))
    checks.append(("次數 1 須留痕且記入 ACC", bool(note) and "未涵蓋欄" in note))
    n, note = R.flaky_runs(0)
    checks.append(("次數 0 被夾到 1", n == 1))
    n, note = R.flaky_runs(None)
    checks.append(("未指定時用預設 2", n == R.DEFAULT_FLAKY_RUNS and note is None))
    n, _ = R.flaky_runs("不是數字")
    checks.append(("非數值輸入回退預設而非崩潰", n == R.DEFAULT_FLAKY_RUNS))
    ok, msg = R.flaky_decide([0])
    checks.append(("只有一次執行時不誤判為不穩定", ok))


def _repo_with(files: dict) -> Path:
    d = Path(tempfile.mkdtemp())
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=f", "-c", "user.email=f@e.com",
                  "commit", "-q", "-m", "base"]):
        subprocess.run(["git", *args], cwd=str(d), capture_output=True)
    return d


def t2_before_after(checks):
    """T2:以 git 取前後版本,涵蓋新增/修改/刪除。"""
    # 修改:刪掉一個測試函式
    d = _repo_with({"test_a.py": THREE_ASSERTS + "\ndef test_b():\n    assert 1\n"})
    (d / "test_a.py").write_text(THREE_ASSERTS, encoding="utf-8")
    before, after, unc = R.before_after(d)
    checks.append(("修改:前 tests 為 2", before["tests"] == 2))
    checks.append(("修改:後 tests 為 1", after["tests"] == 1))
    ok, _ = R.decide(before, after)
    checks.append(("修改後淨減少被擋下", not ok))

    # 刪除整檔:算完整損失,不能比刪函式便宜
    d2 = _repo_with({"test_a.py": THREE_ASSERTS, "test_b.py": TWO_TESTS})
    (d2 / "test_b.py").unlink()
    before, after, unc = R.before_after(d2)
    # 範圍是「本 task 動到的檔案」而非整個 repo(與變異閘同一套歸屬):
    # 純刪除時 before 只含被刪的那支,after 為 0——完整損失,不比刪函式便宜
    checks.append(("刪整檔:前含被刪檔的指標", before["tests"] == 2))
    checks.append(("刪整檔:後為 0(完整損失)", after["tests"] == 0))
    ok, _ = R.decide(before, after)
    checks.append(("刪整檔被擋下", not ok))

    # 新增:只計入「後」
    d3 = _repo_with({"test_a.py": THREE_ASSERTS})
    (d3 / "test_new.py").write_text(TWO_TESTS, encoding="utf-8")
    before, after, unc = R.before_after(d3)
    checks.append(("新增檔只計入後", after["tests"] > before["tests"]))
    ok, _ = R.decide(before, after)
    checks.append(("新增測試放行", ok))

    # 非 Python 測試檔 → 未涵蓋
    d4 = _repo_with({"test_a.py": THREE_ASSERTS})
    (d4 / "test_x.ts").write_text("it('x', () => expect(1).toBe(1))\n", encoding="utf-8")
    before, after, unc = R.before_after(d4)
    checks.append(("非 Python 測試檔列為未涵蓋", ".ts" in unc))

    # 沒動測試檔:閘不該有意見
    d5 = _repo_with({"test_a.py": THREE_ASSERTS, "impl.py": "x = 1\n"})
    (d5 / "impl.py").write_text("x = 2\n", encoding="utf-8")
    ok, msg, _ = R.ratchet_gate(d5)
    checks.append(("未動測試檔時通過", ok and "未動到測試檔" in msg))


RUNNER = Path(__file__).with_name("autopilot_runner.py")
PY = f'"{sys.executable}"'

CHG = """# CHG-20260101-04 — fixture:棘輪與 flaky

- 風險分級:低 | 實作者:fixture agent

### Global Constraints
- 一律以 stdlib 實作

### Tasks
- [ ] T1. 動一下實作
  - interfaces: consumes 需求 / produces 程式
  - test: 測試指令全綠

### Acceptance operation
- operate: 跑一次
- observe: 輸出
- pass: 正確

## 狀態
開單
"""

KEEP_TESTS = ("def test_a():\n    assert 1 == 1\n\n"
              "def test_b():\n    assert 2 == 2\n\n"
              "def test_c():\n    assert 3 == 3\n")

# 施工者:把三個測試砍成兩個(測試仍然全綠——這正是問題所在)
DELETER = '''
import pathlib, sys
brief = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
log = pathlib.Path("briefs.log")
log.write_text((log.read_text(encoding="utf-8") if log.exists() else "") + "\\n===B===\\n" + brief,
               encoding="utf-8")
pathlib.Path("test_keep.py").write_text(
    "def test_a():\\n    assert 1 == 1\\n\\ndef test_b():\\n    assert 2 == 2\\n", encoding="utf-8")
print("agent deleted test_c")
'''

# 施工者:寫一個交替紅綠的測試(第一次綠、第二次紅)
FLAKY_WRITER = '''
import pathlib, sys
pathlib.Path("test_keep.py").write_text(
    "import pathlib\\n"
    "c = pathlib.Path('_n')\\n"
    "n = int(c.read_text()) if c.exists() else 0\\n"
    "c.write_text(str(n + 1))\\n"
    "assert n % 2 == 0, 'flaky!'\\n"
    "def test_a():\\n    assert 1 == 1\\n"
    "def test_b():\\n    assert 2 == 2\\n"
    "def test_c():\\n    assert 3 == 3\\n", encoding="utf-8")
print("agent wrote a flaky test")
'''

REVIEW_PASS = "import sys; print('[task-review] T1 | spec: pass | quality: pass | ok')"


def _build_repo(agent_src):
    d = Path(tempfile.mkdtemp())
    (d / "CHG-20260101-04.md").write_text(CHG, encoding="utf-8")
    (d / "test_keep.py").write_text(KEEP_TESTS, encoding="utf-8")
    (d / "_agent.py").write_text(agent_src, encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=f", "-c", "user.email=f@e.com",
                  "commit", "-q", "-m", "CHG-20260101-04: fixture"]):
        subprocess.run(["git", *args], cwd=str(d), capture_output=True)
    return d


def _run_build(d, *extra):
    cmd = [sys.executable, str(RUNNER), "build", "--chg", str(d / "CHG-20260101-04.md"),
           "--repo", str(d), "--agent-cmd", f'{PY} "{d / "_agent.py"}"' + " {brief}",
           "--review-cmd", f'{PY} -c "{REVIEW_PASS}"',
           "--test-cmd", f'{PY} "{d / "test_keep.py"}"',
           "--max-fix-rounds", "2", "--no-mutation", "--no-commit", *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def t6_t7_wiring(checks):
    """T6/T7:兩道閘真的接在 _build_one 上,失敗也真的回送下一輪。"""
    # 刪測試 → 棘輪擋下(注意:測試指令本身是綠的,單元閘完全看不出問題)
    d = _build_repo(DELETER)
    rc, out = _run_build(d)
    checks.append(("刪測試 → 整體 halt", rc == 3))
    checks.append(("棘輪指出淨減少", "淨減少了測試" in out))
    checks.append(("棘輪點名 tests 指標", "tests" in out and "3 → 2" in out))
    briefs = (d / "briefs.log").read_text(encoding="utf-8") if (d / "briefs.log").exists() else ""
    checks.append(("棘輪失敗有回送下一輪", "[failed-gate: ratchet]" in briefs))

    # 明示豁免 → 放行且留痕
    d2 = _build_repo(DELETER)
    rc2, out2 = _run_build(d2, "--allow-test-reduction")
    checks.append(("明示豁免後不再被棘輪擋", "淨減少了測試" not in out2))
    checks.append(("豁免留痕要求記入 ACC", "未涵蓋欄" in out2))

    # 交替紅綠 → flaky 擋下
    d3 = _build_repo(FLAKY_WRITER)
    rc3, out3 = _run_build(d3)
    checks.append(("交替紅綠 → 整體 halt", rc3 == 3))
    checks.append(("flaky 指出重跑不一致", "重跑結果不一致" in out3))
    checks.append(("flaky 列出兩次退出碼", "0, 1" in out3))

    # --flaky-runs 1 → 不重跑,但留痕
    d4 = _build_repo(FLAKY_WRITER)
    rc4, out4 = _run_build(d4, "--flaky-runs", "1")
    checks.append(("--flaky-runs 1 不再偵測不穩定", "重跑結果不一致" not in out4))
    checks.append(("--flaky-runs 1 有留痕", "不穩定測試偵測已關閉" in out4))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t1_metrics(checks)
    t2_before_after(checks)
    t3_decide(checks)
    t4_flaky(checks)
    t6_t7_wiring(checks)

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
