#!/usr/bin/env python3
"""哨兵「啟動失敗 vs 真 halt」分層的跨平台斷言(CHG-20260803-01 T3)。

為什麼獨立成一支:`test_autopilot_sentinels.py` 驗的是兩層跳脫的**政策邏輯**;
本檔驗的是**平台判別**——同一份政策在 POSIX 與 Windows 上必須得到相同的分層結果。

背景(實測,2026-08-03):退出碼嗅探在 Windows 上不可靠——cmd.exe 對「指令不存在」
回 **1**,與「check 真的跑了且回 1」無法區分;而 App Execution Alias stub 回 9009。
故 `autopilot_sentinels.launchable()` 改為**執行前解析可執行檔**,退出碼僅作補充訊號。

全部用 tmpdir fixture 政策,不讀 repo 帳本;假指令一律用 `sys.executable -c`,
不使用 POSIX-only 的 true/false。

Run: python3 test_sentinel_launch.py  → exit 0 全過,1 有失敗。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SENT = Path(__file__).with_name("autopilot_sentinels.py")
REPO = Path(__file__).resolve().parents[3]
PY = f'"{sys.executable}"'


def policy(sentinels):
    return {"version": 1, "sentinels": sentinels,
            "reentry": {"max_reentry": 20, "base_case": []}, "escape": {}}


def run(pol, bom=False):
    d = Path(tempfile.mkdtemp())
    f = d / "pol.json"
    f.write_text(json.dumps(pol, ensure_ascii=False),
                 encoding="utf-8-sig" if bom else "utf-8")
    r = subprocess.run([sys.executable, str(SENT), "poll", "--repo", str(REPO),
                        "--policy", str(f)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(REPO))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    checks = []

    # 指令不存在 → Tier A。POSIX 回 127、Windows cmd 回 1,兩者都必須歸 A
    # ——這正是「只認退出碼」會在 Windows 誤判的那一格。
    rc, out = run(policy({"x": {"cmd": "no_such_cmd_xyz_123 --foo"}}))
    checks.append(("指令不存在 → A 層 exit 0", rc == 0 and "A:無法評估" in out))

    # check 真的跑了且旗標問題 → Tier B(訊號不得被啟動失敗判定吃掉)
    rc, out = run(policy({"x": {"cmd": f'{PY} -c "import sys;sys.exit(4)"'}}))
    checks.append(("真旗標 → B 層 exit 3", rc == 3 and "B:真 halt" in out))

    # 綠燈可達(KN-001):正常情況必須能回 exit 0 且不含任何 B 層
    rc, out = run(policy({"x": {"cmd": f'{PY} -c "import sys;sys.exit(0)"'}}))
    checks.append(("全過 → 綠燈 exit 0", rc == 0 and "[OK]" in out and "B:真 halt" not in out))

    # 帶 BOM 的政策檔仍須可載入:Windows 工具(記事本、PowerShell Set-Content)
    # 預設寫 BOM;讀不了會讓整組哨兵靜默降級,等同永久失效。
    rc, out = run(policy({"x": {"cmd": f'{PY} -c "import sys;sys.exit(0)"'}}), bom=True)
    checks.append(("BOM 政策仍可載入", rc == 0 and "無法載入政策" not in out))

    # 邊界取樣(KN-002):已知的啟動失敗碼須歸 A。
    # **退出碼在 POSIX 上只有 8 bits**:`sys.exit(9009)` 實際回 9009 % 256 = 49,
    # 所以 9009 這一格無法用子行程重現(在 Windows 上可以)。分兩層驗:
    #   · 127 可跨平台以子行程重現 → 走完整路徑
    #   · 9009 改為直接斷言分類表,不假裝子行程能產生它
    rc, _ = run(policy({"x": {"cmd": f'{PY} -c "import sys;sys.exit(127)"'}}))
    checks.append(("退出碼 127 → A 層 exit 0(子行程實測)", rc == 0))
    sys.path.insert(0, str(SENT.parent))
    import autopilot_sentinels as AS
    checks.append(("9009 在啟動失敗分類表內(Windows cmd 的 not-recognized)",
                   9009 in AS.LAUNCH_FAIL))
    checks.append(("127 在啟動失敗分類表內(POSIX command not found)",
                   127 in AS.LAUNCH_FAIL))
    checks.append(("一般失敗碼不得被當成啟動失敗",
                   1 not in AS.LAUNCH_FAIL and 2 not in AS.LAUNCH_FAIL))

    # 政策不得寫死 python3:內建政策的每個 cmd 都要用 {python} 佔位
    pol = json.loads((SENT.parent.parent / "assets" / "sentinel_policy.json")
                     .read_text(encoding="utf-8-sig"))
    cmds = [s.get("cmd", "") for s in pol.get("sentinels", {}).values()]
    checks.append(("內建政策不寫死 python3",
                   all(c.startswith("{python} ") for c in cmds) and len(cmds) > 0))

    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    if failed:
        print(f"❌ {len(failed)} 失敗")
        return 1
    print(f"✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
