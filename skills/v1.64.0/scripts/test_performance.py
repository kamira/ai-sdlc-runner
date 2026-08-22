#!/usr/bin/env python3
"""效能基準的單元斷言(CHG-20260804-05)。

這道閘有兩個對稱的風險,兩個都要驗:

  · **紅燈可達** —— 真的退步時要擋得住,否則它是裝飾(KN-001)
  · **綠燈穩定** —— 量測本身若不穩,它會無故轉紅,而無故轉紅的閘會被關掉。
                    那與沒有閘是同一件事。

第二條是效能閘特有的:前面每一道閘的輸入都是確定的,只有這一道的輸入是時間。

Run: python3 test_performance.py → exit 0 全過,1 有失敗。
"""
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import bench as BN          # noqa: E402
from lib import quality_judge as QJ  # noqa: E402

AFFIRMATIVE = ("驗證通過", "檢查通過", "全數通過", "已通過")


def _report(ratios, calibration=0.003):
    return {"version": 1, "repeat": 7, "calibration_s": calibration,
            "targets": {k: {"min_s": v * calibration, "ratio": v}
                        for k, v in ratios.items()}}


def _baseline(ratios, tol=2.0):
    return {"performance": {"tolerance": tol,
                            "targets": {k: {"ratio": v} for k, v in ratios.items()}}}


def t_engine(checks):
    """引擎:比值、中位數、校準。"""
    r = BN.run_bench([("noop", lambda x: x, 1)], repeat=3)
    checks.append(("回報校準秒數", r.get("calibration_s", 0) > 0))
    checks.append(("每個目標都有比值", "ratio" in r["targets"]["noop"]))
    checks.append(("比值為正", r["targets"]["noop"]["ratio"] >= 0))
    checks.append(("附上比值的定義", "_ratio_doc" in r))

    # 中位數而非平均:平均會被單一次 GC 或排程延遲拉走
    checks.append(("取中位數", BN._median([1, 2, 100]) == 2))
    checks.append(("偶數個取中間兩個的平均", BN._median([1, 2, 3, 4]) == 2.5))

    # 目標拋例外不該讓整輪基準崩潰——基準不負責驗正確性
    r = BN.run_bench([("boom", lambda x: 1 / 0, 1)], repeat=2)
    checks.append(("目標拋例外時基準仍完成", "boom" in r["targets"]))


def t_green_stable(checks, notes):
    """**綠燈穩定**:量測雜訊必須遠小於退步偵測門檻,否則那個門檻分辨不出訊號與雜訊。

    三態,不是二態(CHG-20260805-01):

      · 雜訊 < 上限            → **通過**
      · 雜訊 ≥ 上限            → **未涵蓋**:這台機器吵到 characterise 不了量測穩定性
      · 上限本身不嚴於偵測門檻  → **失敗**(硬檢查,永遠不放過)

    第三態才是這道斷言真正要守的東西。前兩態的差別在於:雜訊超標**不是程式碼變慢了**,
    是這個環境量不出來——把它判成失敗,就是拿環境噪音當程式碼缺陷,
    而那正是「無故轉紅的閘會被關掉」的成因。

    實測軌跡(同一條斷言,三平台):Windows ×2.39 / ×2.08(牆鐘)→ 換 CPU 時鐘 →
    macOS ×1.63(1 ms 視窗)→ 拉大視窗 → macOS ×1.34(20 ms 視窗)。
    Linux 在 3 倍超額負載下是 1.057。共用 runner 的雜訊就是到不了 1.25,
    而**上限不能為了配合噪音而放寬**——放寬到 1.5 之後,2.0 的偵測門檻只剩 1.33 倍餘裕,
    一個量到 2.0 的「退步」可能只有 1.33 倍是真的。
    """
    def work(n):
        return sum(i * i for i in range(n))

    # 視窗刻意拉大:視窗越大,單次排程雜訊在其中的佔比越小
    W, R = 0.02, 7
    # **湊不出量測視窗時,`run_bench` 會把那個目標整個丟掉**——舊版直接
    # `["targets"]["work"]`,於是同一個條件走出兩條完全不同的路:
    # 雜訊大一點是具名的「[未涵蓋] 量測雜訊」,雜訊大到目標消失就是 `KeyError` 崩潰。
    # 崩潰與具名的未涵蓋在退出碼上一樣,而它們不是同一件事(KN-003)。
    # 實際踩到:CHG-20260812-05 的閘跑了兩輪,第一輪具名、第二輪崩潰。
    raw = [BN.run_bench([("work", work, 20000)], repeat=R, window=W)["targets"].get("work")
           for _ in range(3)]
    dropped = [i for i, r in enumerate(raw) if r is None]
    if dropped:
        notes.append(f"量測視窗湊不出來,{len(dropped)}/3 次的目標被丟掉"
                     f"——這台機器 characterise 不了量測穩定性,**不是**程式碼變慢了。"
                     f"(CHG-20260812-05 已因同一理由把效能閘除役,待補項 #50)")
        # 硬檢查照做:它不依賴量測結果,而它是這一段唯一永遠不放過的一條。
        checks.append((f"穩定性上限嚴於退步偵測門檻"
                       f"({QJ.PERF_STABILITY_MAX} < {QJ.PERF_TOLERANCE})",
                       QJ.PERF_STABILITY_MAX < QJ.PERF_TOLERANCE))
        return
    runs = [r["ratio"] for r in raw]
    lo, hi = min(runs), max(runs)
    spread = hi / lo if lo > 0 else float("inf")

    # 硬檢查:上限必須嚴於偵測門檻,否則這道斷言是循環的。這一條永遠不放過。
    checks.append((f"穩定性上限嚴於退步偵測門檻"
                   f"({QJ.PERF_STABILITY_MAX} < {QJ.PERF_TOLERANCE})",
                   QJ.PERF_STABILITY_MAX < QJ.PERF_TOLERANCE))
    checks.append(("量得到正的比值(量不到就不是穩定性問題)", lo > 0))

    stable = spread < QJ.PERF_STABILITY_MAX
    if stable:
        # 不要在這裡 append 一個字面 True(CHG-20260805-05):那條斷言只要被 append
        # 就一定 PASS,它是**報告**不是檢查,而且會讓通過數 +1,看起來像多驗了一件事。
        # 真正的不變量寫在下面:雜訊在上限內、或已記為未涵蓋——**恰好發生一個**。
        # 只有在雜訊夠小時,「用第一次當基準判第二次」才是有意義的斷言
        okj, _, _ = QJ.judge("performance", json.dumps(
            {"version": 1, "targets": {"work": {"ratio": runs[-1], "min_s": 0}}}),
            {"performance": {"tolerance": QJ.PERF_TOLERANCE,
                             "targets": {"work": {"ratio": runs[0]}}}})
        checks.append(("以第一次為基準判第二次不誤擋", okj))
    else:
        # **未涵蓋**,不是失敗:這台機器吵到量不出穩定性,那不是程式碼變慢了。
        # 措辭刻意不含任何肯定式的通過字樣——未涵蓋讀成通過與讀成失敗一樣錯。
        notes.append(
            f"[未涵蓋] 量測雜訊 ×{spread:.2f} ≥ 上限 ×{QJ.PERF_STABILITY_MAX}"
            f"(三次比值 {[round(r, 4) for r in runs]})——"
            f"這台機器 characterise 不了量測穩定性,**不是**程式碼變慢了。"
            f"退步偵測本身照跑(門檻 {QJ.PERF_TOLERANCE},未放寬)。")

    # 這條在任何機器上都成立,而且真的會因為程式寫錯而變紅:
    # 兩個分支都不記錄、或兩個都記錄,都是錯的。
    noted = any("未涵蓋" in n for n in notes)
    checks.append((f"雜訊在上限內(×{spread:.2f})或已記為未涵蓋——恰好發生一個",
                   stable != noted))


def t_red_reachable(checks):
    """**紅燈可達**:真的退步時要擋得住。"""
    base = _baseline({"p": 0.10})
    ok, msg, _ = QJ.judge("performance", json.dumps(_report({"p": 0.50})), base)
    checks.append(("退步 5 倍 → 擋下", not ok))
    checks.append(("訊息給出前後比值與倍數", "0.1000 → 0.5000" in msg and "5.0 倍" in msg))
    checks.append(("訊息說明為何在意", "會被關掉" in msg))

    for mult, want in ((1.0, True), (1.5, True), (1.99, True), (2.01, False), (10.0, False)):
        ok, _, _ = QJ.judge("performance", json.dumps(_report({"p": 0.10 * mult})), base)
        checks.append((f"×{mult} → {'放行' if want else '擋下'}", ok is want))

    # 變快要被看見(可以更新基準把高度鎖住)
    ok, msg, _ = QJ.judge("performance", json.dumps(_report({"p": 0.01})), base)
    checks.append(("變快 → 放行", ok))
    checks.append(("變快有提示可更新基準", "變快" in msg and "基準" in msg))

    # 目標消失 = 觀測點消失
    ok, msg, _ = QJ.judge("performance", json.dumps(_report({"q": 0.1})), base)
    checks.append(("基準裡的目標消失時被提示", "沒量到" in msg))
    # 新目標沒有可退步的基準,不該擋
    checks.append(("新目標不被誤擋", ok))


def t_degenerate(checks):
    """退化輸入:量不到東西不等於沒有退步。"""
    ok, msg, _ = QJ.judge("performance", json.dumps({"targets": {}}), _baseline({"p": 0.1}))
    checks.append(("0 個目標 → 擋下", not ok))
    checks.append(("並說明那不是「沒有退步」", "不是" in msg))
    checks.append(("不得聲稱通過", not any(a in msg for a in AFFIRMATIVE)))

    ok, msg, _ = QJ.judge("performance",
                          json.dumps({"error": "校準負載量到 0 秒", "targets": {}}),
                          _baseline({"p": 0.1}))
    checks.append(("校準失敗 → 擋下", not ok))
    checks.append(("量不出來就不放行", "量不出來" in msg))

    ok, msg, _ = QJ.judge("performance", json.dumps(_report({"p": 0.1})),
                          {"performance": {}})
    checks.append(("尚無基準時放行", ok))
    checks.append(("但明說這不是「沒有退步」", "不是" in msg))

    ok, msg, _ = QJ.judge("performance", "不是 JSON", _baseline({"p": 0.1}))
    checks.append(("壞產物擋下", not ok))


def t_dropped_target(checks):
    """`run_bench` 把目標整個丟掉時,穩定性那一段**具名未涵蓋,不得崩潰**。

    這一條是被實際的崩潰逼出來的(CHG-20260812-05):湊不出量測視窗時
    `run_bench` 會丟掉目標,而舊版直接 `["targets"]["work"]` → `KeyError`。
    於是同一個條件走出兩條路——雜訊大一點是具名的未涵蓋,雜訊大到目標消失就是崩潰。
    **崩潰與具名的未涵蓋在退出碼上一樣,而它們不是同一件事**(KN-003)。

    這一條**不是**用豁免帶過的:那條分支在正常執行走不到,而讓它走到的方法
    是把儀器換掉一次——那正是這個 repo 對「測不到的分支」的標準處置。
    """
    orig = BN.run_bench
    BN.run_bench = lambda *a, **k: {"targets": {}}      # 目標全部被丟掉
    try:
        sub, notes = [], []
        t_green_stable(sub, notes)
    finally:
        BN.run_bench = orig
    # **這裡刻意不 append 一個「不崩潰」的斷言。** 走到這一行就代表沒有例外,
    # 那條斷言的條件會是字面 `True`——它只要被 append 就一定 PASS,是**報告**不是檢查
    # (CHG-20260805-05,而那段說明就寫在本檔上面幾十行處,我照樣寫了一次,閘抓到)。
    # 崩潰的話上面的呼叫會直接把整支測試打掉,那才是真正的偵測。
    checks.append(("目標被丟掉要記成具名的未涵蓋(不是靜默)",
                   any("量測視窗湊不出來" in n for n in notes)))
    checks.append(("理由要說這不是程式碼變慢",
                   any("不是**程式碼變慢了" in n for n in notes)))
    # 硬檢查不依賴量測結果,所以**即使量不到也必須照做**——否則量不到就等於
    # 整段斷言消失,而那與沒有這段斷言是同一件事。
    checks.append(("量不到時硬檢查仍然照做", len(sub) == 1))
    # **硬檢查的判定也要進計分,不只是數它有幾條。**
    # 舊版只驗 `len(sub) == 1`,於是那條硬檢查(`PERF_STABILITY_MAX < PERF_TOLERANCE`)
    # 的**結果被丟進一個只拿來量長度的清單**——它印 PASS 而沒有在守任何東西。
    # 而這一段的註解自稱它是「唯一永遠不放過的一條」。
    # 修好的 `assertion_probe`(CHG-20260815-01)第一次跑就抓到它。
    checks.extend(sub)


def main() -> int:
    checks: list[tuple[str, bool]] = []
    notes: list[str] = []
    t_engine(checks)
    t_green_stable(checks, notes)
    t_dropped_target(checks)
    t_red_reachable(checks)
    t_degenerate(checks)

    for note in notes:      # 未涵蓋要看得見:靜默的未涵蓋與通過沒有分別
        print(f"  {note}")
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
