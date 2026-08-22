#!/usr/bin/env python3
"""變異引擎自身的斷言(CHG-20260803-01 T10)。stdlib-only,三平台一致。

引擎是「用來量測其他測試強度」的工具——它自己壞掉的話,量出來的 kill rate 全是假的,
而且會以**虛高**的方向假(殺不掉卻回報殺掉 = 假綠)。故本檔用兩個 fixture 模組:
  strong fixture:測試涵蓋完整 → kill rate 應該高
  weak fixture:測試刻意只驗一個路徑 → 引擎必須**如實回報存活變異體**
若引擎對 weak fixture 也回報 100%,就是它在說謊。

另驗基線護欄:被測模組本身壞掉時,引擎必須中止(exit 2)而非產出漂亮的 100%。

Run: python3 test_mutation_harness.py → exit 0 全過。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HARNESS = Path(__file__).with_name("mutation_harness.py")

MODULE = '''
def grade(score):
    if score >= 90:
        return "A"
    if score >= 60:
        return "B"
    return "F"
'''

STRONG_TEST = '''
import sys
sys.path.insert(0, sys.argv[1])
from mod import grade
cases = [(100, "A"), (90, "A"), (89, "B"), (60, "B"), (59, "F"), (0, "F")]
sys.exit(0 if all(grade(s) == w for s, w in cases) else 1)
'''

WEAK_TEST = '''
import sys
sys.path.insert(0, sys.argv[1])
from mod import grade
# 刻意只驗一個點:邊界與其他分支全無斷言
sys.exit(0 if grade(100) == "A" else 1)
'''


def setup(test_src):
    d = Path(tempfile.mkdtemp())
    (d / "mod.py").write_text(MODULE, encoding="utf-8")
    (d / "t.py").write_text(test_src, encoding="utf-8")
    return d


def run_harness(d, *extra):
    cmd = [sys.executable, str(HARNESS), "--target", str(d / "mod.py"),
           "--test", f'"{sys.executable}" "{d / "t.py"}" "{d}"',
           "--cwd", str(d), "--json", *extra]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    try:
        return r.returncode, json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.returncode, {"_raw": (r.stdout or "") + (r.stderr or "")}


def main() -> int:
    checks = []

    # --- 強測試:kill rate 應該高,且引擎不得把原檔改壞 ---
    d = setup(STRONG_TEST)
    before = (d / "mod.py").read_text(encoding="utf-8")
    rc, res = run_harness(d, "--min-kill-rate", "50")
    checks.append(("強測試 → 產出結果 JSON", "kill_rate" in res))
    checks.append(("強測試 kill rate ≥ 50%", res.get("kill_rate", 0) >= 50))
    checks.append(("變異點數 > 0(算子對此模組有效)", res.get("mutants_total", 0) > 0))
    checks.append(("跑完後原檔完整還原", (d / "mod.py").read_text(encoding="utf-8") == before))
    checks.append(("達門檻 → exit 0", rc == 0))

    # --- 弱測試:引擎必須如實回報存活,不得虛報 100% ---
    d2 = setup(WEAK_TEST)
    rc2, res2 = run_harness(d2, "--min-kill-rate", "90")
    checks.append(("弱測試必有存活變異體(引擎不說謊)", res2.get("survived", 0) > 0))
    checks.append(("弱測試 kill rate < 100%", res2.get("kill_rate", 100) < 100))
    checks.append(("未達門檻 → exit 1", rc2 == 1))
    checks.append(("存活清單具名(可據以補斷言)",
                   isinstance(res2.get("survivors"), list) and len(res2["survivors"]) > 0))
    checks.append(("存活項標明算子與行號",
                   any("@L" in s for s in res2.get("survivors", []))))

    # --- 強測試的 kill rate 必須高於弱測試(引擎有鑑別力)---
    checks.append(("強測試 kill rate > 弱測試(有鑑別力)",
                   res.get("kill_rate", 0) > res2.get("kill_rate", 100)))

    # --- 基線護欄:被測模組本身就跑不過測試 → 必須 exit 2 中止 ---
    d3 = setup(STRONG_TEST)
    (d3 / "mod.py").write_text(MODULE.replace('return "A"', 'return "WRONG"'), encoding="utf-8")
    rc3, res3 = run_harness(d3)
    checks.append(("基線就紅 → exit 2 中止(不得產出假 kill rate)", rc3 == 2))
    checks.append(("基線失敗時不輸出 kill_rate", "kill_rate" not in res3))

    # --- 取樣上限:丟棄數必須被回報,不做無聲截斷 ---
    d4 = setup(STRONG_TEST)
    rc4, res4 = run_harness(d4, "--max-mutants", "3", "--min-kill-rate", "0")
    checks.append(("--max-mutants 生效", res4.get("mutants_run", 99) <= 3))
    checks.append(("丟棄數如實回報(不無聲截斷)",
                   res4.get("dropped_by_cap", 0) ==
                   res4.get("mutants_total", 0) - res4.get("mutants_run", 0)))

    # --- target 不存在 → exit 2 ---
    r = subprocess.run([sys.executable, str(HARNESS), "--target", str(Path(tempfile.mkdtemp()) / "nope.py"),
                        "--test", "echo x"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    checks.append(("target 不存在 → exit 2", r.returncode == 2))

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
