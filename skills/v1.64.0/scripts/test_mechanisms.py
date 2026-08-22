#!/usr/bin/env python3
"""性質→機制→三態 + 未涵蓋棘輪的單元測試(CHG-20260807-02 T2)。

這一份的重點是**三態要真的分得開**,以及**棘輪真的擋得住**。
後者尤其重要:三態一旦存在,「把紅燈改成不支援」就是讓它消失的按鈕,
而棘輪是那個按鈕的鎖。鎖沒被驗過的話,這整層是負分——
它讓失敗有了一個看起來合法的出口。

Run: python3 test_mechanisms.py → exit 0 全過,1 有失敗。
"""
import json
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from lib import mechanisms as M  # noqa: E402


def mech(name, requires, result):
    def run():
        if isinstance(result, Exception):
            raise result
        return result
    return M.Mechanism(name=name, requires=tuple(requires), run=run)


def caps(**table):
    return lambda c: table.get(c, False)


def main() -> int:
    checks: list[tuple[str, bool]] = []

    # --- 三態 -----------------------------------------------------------------
    o = M.run_property("P", [mech("a", ["x"], True)], caps(x=True))
    checks.append(("能力齊且通過 → pass", o.state == M.PASS and o.used == ("a",)))

    o = M.run_property("P", [mech("a", ["x"], False)], caps(x=True))
    checks.append(("能力齊但判定失敗 → fail(不得降級為未涵蓋)", o.state == M.FAIL))

    o = M.run_property("P", [mech("a", ["x"], True)], caps(x=False))
    checks.append(("唯一機制不支援 → uncovered", o.state == M.UNCOVERED))
    checks.append(("未涵蓋要具名缺哪個能力",
                   bool(o.skipped) and "x" in o.skipped[0]))

    # --- 核心:**只要有一種機制支援,就不得降級為未涵蓋** ----------------------
    # 這是使用者裁示「當不支援時要採取適用於該系統的驗證」的機器化形式。
    o = M.run_property("P", [mech("sym", ["symlink"], True),
                             mech("junc", ["junction"], True)],
                       caps(symlink=False, junction=True))
    checks.append(("一種不支援、另一種支援 → 仍然 pass(不是未涵蓋)",
                   o.state == M.PASS and o.used == ("junc",)))
    checks.append(("沒跑的那種機制要被具名列出,不得靜靜跳過",
                   any("sym" in s for s in o.skipped)))

    # 支援多種就全跑 —— 挑一種等於自願放棄另一半偵測力
    o = M.run_property("P", [mech("sym", ["symlink"], True),
                             mech("junc", ["junction"], True)],
                       caps(symlink=True, junction=True))
    checks.append(("兩種都支援 → 兩種都跑", set(o.used) == {"sym", "junc"}))

    # 其中一種紅 → 整體紅(不得被另一種的綠蓋掉)
    o = M.run_property("P", [mech("sym", ["symlink"], True),
                             mech("junc", ["junction"], False)],
                       caps(symlink=True, junction=True))
    checks.append(("一種紅就整體紅(綠的不得蓋掉紅的)", o.state == M.FAIL))
    checks.append(("失敗訊息指名是哪一種機制", "junc" in o.detail))

    # 機制執行時炸掉 = 失敗,不是未涵蓋
    o = M.run_property("P", [mech("a", ["x"], RuntimeError("boom"))], caps(x=True))
    checks.append(("支援的機制執行時崩潰 → fail(不得降級為未涵蓋)", o.state == M.FAIL))
    checks.append(("崩潰訊息保留例外型別", "RuntimeError" in o.detail))

    # --- 未涵蓋棘輪 -----------------------------------------------------------
    base = {"known": {"reason": "已具名", "chg": "CHG-X"}}
    ok, msg = M.judge_uncovered(["known"], base)
    checks.append(("基線內且具名 → 放行", ok))

    ok, msg = M.judge_uncovered(["known", "brand_new"], base)
    checks.append(("基線外的新未涵蓋 → 擋下", not ok))
    checks.append(("擋下訊息指名是哪一項", "brand_new" in msg))

    ok, msg = M.judge_uncovered(["unsigned"], {"unsigned": {"chg": "CHG-X"}})
    checks.append(("基線條目沒有理由 → 擋下(KN-006)", not ok))

    ok, msg = M.judge_uncovered(["unsigned"], {"unsigned": {"reason": "", "chg": "C"}})
    checks.append(("理由是空字串 → 擋下(空白豁免視同沒宣告)", not ok))

    ok, msg = M.judge_uncovered([], base)
    checks.append(("項目離開清單 → 放行但要報出來(基線只准往下)",
                   ok and "known" in msg))

    ok, msg = M.judge_uncovered([], {"__unreadable__": {}})
    checks.append(("基線讀不到 → 擋下(刪掉基線檔不得等於關掉棘輪)", not ok))

    # 基線檔真的讀得起來,而且不是空的 —— 一份空基線會讓上面每條斷言都恆真
    real = M.load_baseline()
    checks.append((f"出貨的基線檔解析得開且非空(實得 {len(real)} 條)",
                   bool(real) and "__unreadable__" not in real))
    checks.append(("出貨基線每條都有 reason 與 chg",
                   all(e.get("reason") and e.get("chg") for e in real.values())))
    checks.append(("出貨基線每條都有 scope(否則「已離開清單」的建議會恆假)",
                   all(e.get("scope") for e in real.values())))

    # scope 過濾:不同收集者不得互相宣告對方的項目「已離開清單」
    two = {"a": {"scope": "s1", "reason": "r", "chg": "C"},
           "b": {"scope": "s2", "reason": "r", "chg": "C"}}
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "b.json"
        f.write_text(json.dumps({"version": 1, "entries": two}), encoding="utf-8")
        s1 = M.load_baseline(f, scope="s1")
        checks.append(("load_baseline(scope) 只回該範圍", set(s1) == {"a"}))
        checks.append(("不給 scope 時回全部", set(M.load_baseline(f)) == {"a", "b"}))
        # s1 的收集者回報「我這邊沒有未涵蓋」時,不得因為 s2 的項目而說它離開了
        ok_s, msg_s = M.judge_uncovered([], M.load_baseline(f, scope="s1"))
        checks.append(("跨 scope 不得誤報「已離開清單」",
                       ok_s and "b" not in msg_s))

    # 讀不到時回的是擋下用的哨兵,不是空 dict —— 空 dict 會讓棘輪變成「什麼都放行」
    with tempfile.TemporaryDirectory() as td:
        missing = M.load_baseline(Path(td) / "nope.json")
    checks.append(("基線檔不存在 → 回哨兵而非空 dict",
                   "__unreadable__" in missing))

    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.json"
        bad.write_text("{ this is not json", encoding="utf-8")
        checks.append(("基線檔壞掉 → 回哨兵而非空 dict",
                       "__unreadable__" in M.load_baseline(bad)))

    # --- 可跑集為空 = 失敗 -----------------------------------------------------
    ok, _ = M.require_runnable(3)
    checks.append(("可跑集非空 → 放行", ok))
    ok, msg = M.require_runnable(0)
    checks.append(("可跑集為 0 → 失敗(KN-001)", not ok))
    checks.append(("訊息要說這不是「全部通過」", "全部通過" in msg))

    failed = [label for label, ok_ in checks if not ok_]
    for label, ok_ in checks:
        print(f"  [{'PASS' if ok_ else 'FAIL'}] {label}")
    if failed:
        print(f"\n❌ {len(failed)}/{len(checks)} 失敗")
        return 1
    print(f"\n✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
