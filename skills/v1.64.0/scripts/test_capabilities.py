#!/usr/bin/env python3
"""能力偵測層的單元測試(CHG-20260807-02 T1)。

**這一份最重要的斷言不是「探針回對的值」,而是「探針壞掉時回 False 而不是炸掉」。**
理由是 KN-003 的直接後果:一個因為自己崩潰而回不出答案的探針,與一個
正確回報「不支援」的探針,在呼叫端看起來完全一樣——而兩者的後續動作相反
(前者要修探針,後者要換機制)。

**刻意不驗機器相關的值**:不斷言「本機 junction 為 True」。那在 Linux 上必然紅,
而且紅得毫無意義——那是環境事實,不是程式行為。機器相關的實測放在 CHG 的
「實際操作驗收」裡,由人看著跑。把環境寫進單元測試會製造一種最糟的紅:
每次都紅、每次都不是缺陷,於是整份測試被忽略(KN-001 的社會版本)。

Run: python3 test_capabilities.py → exit 0 全過,1 有失敗。
"""
import ast
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from lib import capabilities as C  # noqa: E402


class Boom(Exception):
    """刻意用一個**不在** except 子句裡的例外型別。

    如果實作寫成 `except OSError`,這個型別會直接穿出去——
    那正是要擋的東西:探針只擋自己預期的失敗,等於沒擋。
    """


def raiser(*_a, **_k):
    raise Boom("注入的失敗")


def main() -> int:
    checks: list[tuple[str, bool]] = []

    # --- 每個探針:注入失敗 → 回 False,且不得拋出 ---------------------------
    # 各自具名呼叫,不用 `**{動態鍵}` 展開:注入參數名(`_link`/`_run`/`_io`/`_import`)
    # 是刻意不同的——它要說出替換掉的是哪一個底層動作。動態展開會讓型別檢查器
    # 完全看不到簽章,於是這一份自己欠一筆基線豁免;那不划算,寫開就好。
    injected = [
        ("symlink", lambda: C.probe_symlink(_link=raiser)),
        ("junction", lambda: C.probe_junction(_run=raiser)),
        ("utf8_locale", lambda: C.probe_utf8_locale(_io=raiser)),
        ("tool", lambda: C.probe_tool("json", _import=raiser)),
    ]
    for name, call in injected:
        try:
            got = call()
            checks.append((f"{name}:注入失敗回 False", got is False))
            checks.append((f"{name}:注入失敗不得拋出", True))
        except Boom:
            checks.append((f"{name}:注入失敗回 False", False))
            checks.append((f"{name}:注入失敗不得拋出", False))

    # --- 探針必須真的做那件事,不是回一個常數 -------------------------------
    # 注入一個「成功」的替身,結果必須跟著變 True。只驗失敗那一側的話,
    # `return False` 這種實作會全過——恆假與恆真是同一種裝飾(KN-001)。
    #
    # 假替身必須產出**可穿越**的路徑,不能只回 True:探針在建完之後會真的走進去
    # 讀 marker(「建得出來不等於用得了」)。一個只回 True 的替身會讓這條斷言
    # 永遠紅,而紅的原因是替身寫得不對,不是被測程式有問題——那種紅最浪費人。
    calls: list[str] = []

    def ok_link(link, target, **_k):
        calls.append("link")
        shutil.copytree(target, link)

    checks.append(("symlink:注入成功回 True(不是恆假)",
                   C.PROBES["symlink"](_link=ok_link) is True))
    checks.append(("symlink:成功路徑確實呼叫了底層動作", "link" in calls))

    def ok_run(args, **_k):
        # args = ["cmd", "/c", "mklink", "/J", <link>, <target>]
        calls.append("run")
        shutil.copytree(args[5], args[4])
        return 0

    checks.append(("junction:注入成功回 True(不是恆假)",
                   C.PROBES["junction"](_run=ok_run) is True))

    # --- utf8_locale 判的是**往返一致**,不是編碼名稱 ------------------------
    # 名稱比對分不出意圖:cp950 讀 UTF-8 位元組多半不拋例外,只是讀成亂碼。
    checks.append(("utf8_locale:往返不一致 → False",
                   C.PROBES["utf8_locale"](_io=lambda _s: "��") is False))
    checks.append(("utf8_locale:往返一致 → True",
                   C.PROBES["utf8_locale"](_io=lambda s: s) is True))

    # --- tool 探針:真的 import,不是查檔案在不在 ---------------------------
    checks.append(("tool:stdlib 模組回 True", C.probe_tool("json") is True))
    checks.append(("tool:不存在的模組回 False",
                   C.probe_tool("no_such_module_zzz") is False))

    # --- 快取:同一個名字只探一次 -------------------------------------------
    hits = []

    def counting(**_k):
        hits.append(1)
        return True

    cache: dict = {}
    C.supports("x", probes={"x": counting}, cache=cache)
    C.supports("x", probes={"x": counting}, cache=cache)
    checks.append(("supports:同名只探一次(有快取)", len(hits) == 1))

    # 未知能力名不得靜默回 False —— 那會讓打錯字的能力名變成「不支援」,
    # 於是整條驗證被降級為未涵蓋,而且沒有人會發現。
    unknown_raised = False
    try:
        C.supports("no_such_capability", probes={}, cache={})
    except KeyError:
        unknown_raised = True
    checks.append(("supports:未知能力名要炸,不得靜默回 False", unknown_raised))

    # --- 判準不得用平台名稱(CHG-20260807-02 Global Constraint)--------------
    # 「Windows」不等於「建不出 symlink」——開了開發者模式就建得出。
    # 用平台名判會把**一台機器的設定**寫死成**整個平台的性質**。
    src = (SCRIPTS / "lib" / "capabilities.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    platform_reads = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("name", "platform"):
            base = node.value
            if isinstance(base, ast.Name) and base.id in ("os", "sys"):
                platform_reads.append(f"{base.id}.{node.attr}")
    checks.append((f"判準未引用平台名稱(實得 {sorted(set(platform_reads))})",
                   not platform_reads))

    # --- report():必須回三個欄位齊全的東西,且不得因單一探針壞掉而整份消失 ---
    rep = C.report(probes={"good": lambda **_k: True, "bad": raiser})
    checks.append(("report:壞掉的探針記為 False 而非讓整份報告消失",
                   rep.get("good") is True and rep.get("bad") is False))

    failed = [label for label, ok in checks if not ok]
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if failed:
        print(f"\n❌ {len(failed)}/{len(checks)} 失敗")
        return 1
    print(f"\n✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
