#!/usr/bin/env python3
"""halt_gate.py 的斷言(CHG-20260803-01 T6)。無測試框架,stdlib-only,三平台一致。

halt_gate 是治理層唯一「該不該停下等人」的裁決點——這裡靜默翻轉一格,
整個自主流程就會在不該放行的地方放行,而且不會有任何徵兆。故本檔逐格覆蓋:
5 個 gate × 3 個風險 = 15 格全數具名斷言,不抽樣。

同時把**出貨的 assets/halt_policy.json** 與**程式內建的 DEFAULT_POLICY** 逐格比對:
兩者是同一個矩陣的兩份表示,漂移了就是治理語意分岔。

Run: python3 test_halt_gate.py  → exit 0 全過,1 有失敗。
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
SCRIPT = HERE / "halt_gate.py"
sys.path.insert(0, str(HERE))
import halt_gate as HG  # noqa: E402

# 停點矩陣的**期望值**——與 ai-sdlc SKILL 的停點表、autopilot SKILL 的風險×階段表同源。
# 這份是斷言的來源,不是從程式讀回來的(從程式讀回來等於什麼都沒驗)。
EXPECTED = {
    "requirement_confirmed":    {"low": "auto", "medium": "auto", "high": "halt"},
    "structure_confirmed":      {"low": "auto", "medium": "auto", "high": "halt"},
    "before_implement":         {"low": "auto", "medium": "auto", "high": "halt"},
    "acceptance_failed":        {"low": "auto", "medium": "halt", "high": "halt"},
    "before_merge_or_release":  {"low": "auto", "medium": "halt", "high": "halt"},
}


def cli(*args, policy=None):
    cmd = [sys.executable, str(SCRIPT), *args]
    if policy:
        cmd += ["--policy", str(policy)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "").strip()


def main() -> int:
    checks = []
    shipped = HG.load_policy(None)

    # --- 15 格逐格:出貨政策的裁決必須等於期望矩陣 ---
    for gate, row in EXPECTED.items():
        for risk, want in row.items():
            got, _ = HG.decide(shipped, gate, risk, None, None)
            checks.append((f"矩陣 {gate}/{risk} = {want}", got == want.upper()))

    # --- 出貨 asset 與程式內建預設不得漂移(同一矩陣的兩份表示)---
    checks.append(("assets/halt_policy.json 的 gates 與 DEFAULT_POLICY 一致",
                   shipped.get("gates") == HG.DEFAULT_POLICY["gates"] == EXPECTED))

    # --- always-halt:不論風險多低一律 HALT ---
    for action in ("production deploy", "drop table users", "move money to escrow",
                   "rotate credentials", "irreversible schema change",
                   "publish public content"):
        got, why = HG.decide(shipped, "before_implement", "low", action, None)
        checks.append((f"always-halt「{action}」即使 low 也 HALT",
                       got == "HALT" and "always-halt" in why))
    # 反例:一般動作不得被誤判為 always-halt(否則等同恆真式,見 KN-001)
    got, _ = HG.decide(shipped, "before_implement", "low", "rename a local variable", None)
    checks.append(("一般動作不觸發 always-halt(綠燈可達)", got == "AUTO"))

    # --- Autonomy 覆寫:只縮不放 ---
    got, why = HG.decide(shipped, "before_implement", "low", None, "halt")
    checks.append(("Autonomy=halt 可加嚴(low auto → HALT)",
                   got == "HALT" and "加嚴" in why))
    got, why = HG.decide(shipped, "before_merge_or_release", "high", None, "auto")
    checks.append(("Autonomy=auto 不得放寬 high(仍 HALT)",
                   got == "HALT" and "需人預先核准" in why))
    got, _ = HG.decide(shipped, "before_implement", "low", None, "auto")
    checks.append(("Autonomy=auto 對本就 auto 的格子無副作用", got == "AUTO"))

    # --- 未知輸入一律保守停點(unknown = halt)---
    for gate, risk in (("no_such_gate", "low"), ("before_implement", "no_such_risk"),
                       ("", "low")):
        got, why = HG.decide(shipped, gate, risk, None, None)
        checks.append((f"未知輸入({gate or '空'}/{risk})→ HALT",
                       got == "HALT" and "未知" in why))
    # risk 缺值(None 或空字串)→ 視為 high(最保守),不得因缺值而放行。
    # 注意這與「未知 risk」是**不同路徑**:缺值落到 high 那一格(理由為 policy[...]),
    # 未知值查不到格子(理由為「未知」)。兩條路都必須 HALT,但不可互相冒充。
    # 用不同的變數名:同名會與前面已宣告為 str 的 risk 衝突,而這裡的重點
    # 正是「缺值(None / 空字串)也要能餵進去,且必須 HALT」
    for missing_risk in (None, ""):
        got, why = HG.decide(shipped, "before_implement", missing_risk, None, None)
        checks.append((f"risk 缺值({missing_risk!r})→ 當 high → HALT",
                       got == "HALT" and "未知" not in why))
    # 大小寫不敏感(邊界取樣,KN-002)
    got, _ = HG.decide(shipped, "before_implement", "LOW", None, None)
    checks.append(("risk 大小寫不敏感(LOW = low)", got == "AUTO"))

    # --- CLI 退出碼契約:AUTO=0 / HALT=10 / 參數錯誤=2 ---
    rc, out = cli("--gate", "before_implement", "--risk", "low")
    checks.append(("CLI AUTO → exit 0", rc == 0 and out == "AUTO"))
    rc, out = cli("--gate", "before_merge_or_release", "--risk", "high")
    checks.append(("CLI HALT → exit 10", rc == 10 and out == "HALT"))
    rc, _ = cli("--risk", "low")           # 缺 --gate
    checks.append(("CLI 缺必填參數 → exit 2", rc == 2))
    rc, out = cli("--gate", "before_implement", "--risk", "low", "--why")
    checks.append(("CLI --why 附上理由", rc == 0 and "policy[" in out))

    # --- 壞掉的政策檔:回退內建預設,不得崩潰也不得靜默放行 ---
    d = Path(tempfile.mkdtemp())
    bad = d / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    rc, out = cli("--gate", "before_merge_or_release", "--risk", "high", policy=bad)
    checks.append(("政策檔損毀 → 回退預設且仍 HALT", rc == 10 and out == "HALT"))

    # 自訂政策確實會被採用(否則 --policy 等於裝飾品)
    custom = d / "custom.json"
    custom.write_text(json.dumps({"gates": {"before_implement": {"low": "halt"}}}),
                      encoding="utf-8")
    rc, _ = cli("--gate", "before_implement", "--risk", "low", policy=custom)
    checks.append(("--policy 自訂矩陣生效(low 被改為 halt)", rc == 10))

    # 帶 BOM 的政策檔仍須生效。Windows 工具預設寫 BOM;若讀不了會落進上面那條
    # 「損毀 → 回退預設」的路徑而**靜默失效**——操作者加嚴過的矩陣等於沒寫。
    bom = d / "bom.json"
    bom.write_text(json.dumps({"gates": {"before_implement": {"low": "halt"}}}),
                   encoding="utf-8-sig")
    rc, _ = cli("--gate", "before_implement", "--risk", "low", policy=bom)
    checks.append(("帶 BOM 的自訂政策仍生效(不得靜默回退)", rc == 10))

    # 獨立可用:把腳本單獨複製到沒有 assets/ 的目錄仍須正常裁決。
    # docstring 明寫「本檔內建同樣的預設,確保獨立可用」——這條沒有斷言時,
    # 內建預設整個消失也不會有人發現(變異測試存活點 return@L64)。
    alone = Path(tempfile.mkdtemp()) / "halt_gate.py"
    alone.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(alone), "--gate", "before_merge_or_release",
                        "--risk", "high"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    checks.append(("無 assets/ 時以內建預設獨立運作 → HALT",
                   r.returncode == 10 and "HALT" in (r.stdout or "")))
    r = subprocess.run([sys.executable, str(alone), "--gate", "before_implement",
                        "--risk", "low"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    checks.append(("無 assets/ 時內建預設的 auto 格仍為 AUTO",
                   r.returncode == 0 and "AUTO" in (r.stdout or "")))

    # 自訂 always_halt_actions 的**短關鍵字**(3 字)必須生效。
    # 關鍵字長度門檻若被調鬆一格,出貨清單剛好沒有 3 字詞而不會露餡,
    # 但使用者自訂的短關鍵字會靜默失效(變異測試存活點 num@L75)。
    short = d / "short.json"
    short.write_text(json.dumps({"always_halt_actions": ["ssh 金鑰輪替"]}, ensure_ascii=False),
                     encoding="utf-8")
    rc, out = cli("--gate", "before_implement", "--risk", "low",
                  "--action", "rotate ssh key", "--why", policy=short)
    checks.append(("自訂 3 字 always-halt 關鍵字生效", rc == 10 and "always-halt" in out))

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
