#!/usr/bin/env python3
"""合併前 CI 閘的斷言(CHG-20260803-04)。stdlib-only、不連網、三平台一致。

`decide()` 是純函式,狀態以 fixture 餵入——這道閘的正確性不該取決於當下有沒有網路,
也不該在測試時真的去打 GitHub。`fetch()` 的錯誤路徑另以自訂指令模擬。

最重要的一組:**綠與 pending 混合**。那正是實際踩過的情境——
三項打勾、一項還在跑,看起來就像好了。
"""
import json
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ci_gate as CI  # noqa: E402

PY = f'"{sys.executable}"'


def ck(name, bucket):
    return {"name": name, "bucket": bucket, "state": bucket.upper()}


def main() -> int:
    checks = []

    def case(label, data, want_ok, needle=None, allow_no_ci=False):
        ok, msg = CI.decide(data, None, allow_no_ci)
        good = ok == want_ok and (needle is None or needle in msg)
        checks.append((f"{label} → {'放行' if want_ok else '擋下'}", good))

    # ---------- 整體狀態 ----------
    case("全部完成且全綠", [ck("governance", "pass"), ck("tests", "pass")], True)
    case("有一項 pending",
         [ck("governance", "pass"), ck("tests (windows-latest)", "pending")], False)
    case("有一項 failing", [ck("governance", "pass"), ck("tests", "fail")], False)
    case("全部 pending", [ck("a", "pending"), ck("b", "pending")], False)
    # 實際踩過的那一格:三綠一 pending
    case("三綠一 pending(實際踩過的情境)",
         [ck("governance", "pass"), ck("tests (ubuntu)", "pass"),
          ck("tests (macos)", "pass"), ck("tests (windows-latest)", "pending")], False)
    case("cancel 視同阻擋", [ck("a", "pass"), ck("b", "cancel")], False)
    case("skipping 視同綠(未觸發不等於失敗)", [ck("a", "pass"), ck("b", "skipping")], True)

    # pending 必須點名
    ok, msg = CI.decide([ck("governance", "pass"), ck("tests (windows-latest)", "pending")], None)
    checks.append(("pending 時點名該項名稱", not ok and "tests (windows-latest)" in msg))
    checks.append(("訊息點明「pending 不是綠燈」", "pending 不是綠燈" in msg))

    # failing 必須點名
    ok, msg = CI.decide([ck("tests (macos-latest)", "fail")], None)
    checks.append(("failing 時點名該項名稱", not ok and "tests (macos-latest)" in msg))

    # ---------- 無法評估 → fail-closed ----------
    ok, msg = CI.decide(None, "找不到 gh CLI,無法確認 CI 狀態")
    checks.append(("查不到狀態 → 擋下(fail-closed)", not ok))
    checks.append(("訊息含「無法確認」", "無法確認" in msg))
    checks.append(("訊息說明為何此處 fail-closed", "難以回收" in msg))

    # ---------- 沒有任何檢查 ----------
    ok, msg = CI.decide([], None)
    checks.append(("查無任何檢查 → 擋下", not ok))
    checks.append(("訊息區分「沒有檢查」與「檢查都通過」", "不是同一件事" in msg))
    ok, msg = CI.decide([], None, allow_no_ci=True)
    checks.append(("--allow-no-ci → 放行", ok))
    checks.append(("放行時標明為逃生口", "逃生口" in msg))

    # ---------- fetch 的錯誤路徑(以自訂指令模擬,不連網)----------
    d = Path(tempfile.mkdtemp())
    data, err = CI.fetch(d, override=f'{PY} -c "print(\'[]\')"')
    checks.append(("自訂指令輸出空陣列 → 無錯誤", err is None and data == []))
    # 經檔案傳遞,避開多層 shell 引號轉義(那本身就是跨平台的坑)
    jf = d / "checks.json"
    jf.write_text(json.dumps([ck("x", "pass")]), encoding="utf-8")
    data, err = CI.fetch(d, override=f'{PY} -c "import sys;sys.stdout.write(open(sys.argv[1]).read())" "{jf}"')
    checks.append(("自訂指令輸出合法 JSON → 解析成功",
                   err is None and data and data[0]["bucket"] == "pass"))
    data, err = CI.fetch(d, override=f'{PY} -c "print(\'not json\')"')
    checks.append(("自訂指令輸出非 JSON → 回錯誤(不得當成空)", err is not None and data is None))
    data, err = CI.fetch(d, override="no_such_ci_cmd_xyz")
    checks.append(("自訂指令跑不起來 → 回錯誤", err is not None))
    data, err = CI.fetch(d, override=f'{PY} -c "print(\'{{}}\')"')
    checks.append(("JSON 但非陣列 → 回錯誤", err is not None))

    # 端到端:錯誤一路傳到 decide 仍是擋下
    ok, _ = CI.check(d, override="no_such_ci_cmd_xyz")
    checks.append(("check() 端到端:查詢失敗 → 擋下", not ok))

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
