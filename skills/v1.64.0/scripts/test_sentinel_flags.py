#!/usr/bin/env python3
"""哨兵安裝(C-5)與 runner 旗標層(C-6)的斷言(CHG-20260804-09)。

**C-5**:`sentinel_install.py` 至今零測試,而它做的是「建立持久設定」——
ai-sdlc 把那歸為**永遠停點**。一個永遠停點若因為沒人測而悄悄變成放行,
它擋不住的正是最不該自動化的那一類動作。

**C-6**:runner 的 argparse 層一直只由 E2E 間接覆蓋,沒有專屬斷言。
旗標是這套工具的**對外契約**:預設值改了、旗標打錯字、逃生口被加到不該有的
子指令上——這些都不會讓任何既有測試變紅,因為 E2E 只走它自己那條路。

Run: python3 test_sentinel_flags.py → exit 0 全過,1 有失敗。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
INSTALL = HERE / "sentinel_install.py"
RUNNER = HERE / "autopilot_runner.py"

import sentinel_install as SI    # noqa: E402


def run(script: Path, *args, timeout=60):
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def t_cron_expr(checks):
    """週期換算:分鐘欄上限 59,超過要換算成時/日。"""
    cases = [(1, "*/1 * * * *"), (5, "*/5 * * * *"), (59, "*/59 * * * *"),
             (60, "0 */1 * * *"), (180, "0 */3 * * *"),
             (1440, "0 2 * * *"), (4320, "0 2 */3 * *")]
    for mins, want in cases:
        got = SI.cron_expr(mins)
        checks.append((f"cron_expr({mins}) → {want}", got == want))

    # 值域邊界:每一段的頭尾都要是合法的 cron(KN-002 —— 換算成外部格式字串時取邊界例)
    for mins in (0, 1, 59, 60, 61, 1439, 1440, 1441, 100000):
        expr = SI.cron_expr(mins)
        fields = expr.split()
        ok = len(fields) == 5
        if ok and fields[0].startswith("*/"):
            ok = 1 <= int(fields[0][2:]) <= 59
        if ok and fields[1].startswith("*/"):
            ok = 1 <= int(fields[1][2:]) <= 23
        if ok and fields[2].startswith("*/"):
            ok = 1 <= int(fields[2][2:]) <= 28
        checks.append((f"cron_expr({mins}) 產出合法的五欄 cron:{expr}", ok))


def t_permanent_halt(checks):
    """建立持久設定是**永遠停點**:沒有明示授權一律 halt。"""
    d = Path(tempfile.mkdtemp())
    rc, out = run(INSTALL, "install", "--repo", str(d), "--interval-min", "30")
    checks.append(("未授權 → exit 3(永遠停點)", rc == 3))
    checks.append(("未授權時仍印出安裝計畫供審閱", "cron" in out.lower()))
    checks.append(("訊息指出需要授權", "authorize" in out.lower() or "授權" in out))

    rc, out = run(INSTALL, "install", "--repo", str(d), "--interval-min", "30", "--dry-run")
    checks.append(("--dry-run → exit 0 且不落地", rc == 0))

    rc, out = run(INSTALL, "install", "--repo", str(d), "--interval-min", "30", "--i-authorize-cron")
    checks.append(("明示授權 → exit 0", rc == 0))
    checks.append(("授權後產出可審閱的 re-entry 設定", "actions/checkout" in out))
    # 即使授權也**不得**逕自寫入系統
    checks.append(("不逕自寫入 crontab(產出到 stdout 供人放置)",
                   not (d / "crontab").exists()))


def t_runner_flags(checks):
    """C-6:旗標是對外契約——預設值與歸屬的子指令都要被釘住。"""
    rc, out = run(RUNNER, "--help")
    checks.append(("runner --help 可用", rc == 0))
    for sub in ("plan-check", "run", "status", "sentinels", "plan", "build",
                "review", "verify", "accept"):
        checks.append((f"子指令 {sub} 存在", sub in out))

    # 每個子指令的旗標歸屬:逃生口不得出現在不該有的地方
    def flags(sub):
        _rc, o = run(RUNNER, sub, "--help")
        return o

    build = flags("build")
    for f in ("--test-cmd", "--allow-untested", "--no-mutation", "--max-fix-rounds",
              "--escalate-cmd", "--allow-test-reduction", "--flaky-runs",
              "--review-panel", "--seat-cmd", "--confidence-threshold"):
        checks.append((f"build 有 {f}", f in build))

    verify = flags("verify")
    for f in ("--verify-cmd", "--trust-chg-commands", "--quality-baseline",
              "--nonfunctional-kinds"):
        checks.append((f"verify 有 {f}", f in verify))

    # 信任邊界的旗標**不得**出現在 build:CHG 內容宣告的指令只在 verify 階段執行
    checks.append(("--trust-chg-commands 不在 build(信任邊界只在 verify)",
                   "--trust-chg-commands" not in build))
    # plan-check 是唯讀的:不得帶任何會執行東西的旗標
    plan = flags("plan-check")
    for f in ("--agent-cmd", "--test-cmd", "--verify-cmd", "--trust-chg-commands"):
        checks.append((f"plan-check 不得有 {f}(它是唯讀的)", f not in plan))

    # 預設值:這些是承諾,改了要有人知道
    checks.append(("--min-kill-rate 預設 90", "90" in build and "min-kill-rate" in build))
    checks.append(("--flaky-runs 說明寫明預設 2 下限 1",
                   "預設 2" in build and "下限 1" in build))
    checks.append(("--max-fix-rounds 說明寫明預設 3", "預設 3" in build))
    checks.append(("--confidence-threshold 說明寫明預設 80", "預設 80" in build))
    checks.append(("--mutation 已標明為相容保留(已無作用)",
                   "相容保留" in build and "已無作用" in build))

    # 壞子指令要有明確訊息,不是 traceback
    rc, out = run(RUNNER, "不存在的子指令")
    checks.append(("未知子指令 → 非零且非 traceback",
                   rc != 0 and "Traceback" not in out))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t_cron_expr(checks)
    t_permanent_halt(checks)
    t_runner_flags(checks)

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
