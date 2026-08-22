#!/usr/bin/env python3
"""knowledge_index.py 的斷言(CHG-20260803-01 T8)。stdlib-only,三平台一致。

INDEX 是**生成物**:手維護必漂移。所以最重要的兩條是
(1) 生成後 `--check` 必須說「新鮮」,(2) 條目變了而 INDEX 沒重生時 `--check` 必須說「過期」。
若第二條不成立,`--check` 就是恆真式,掛在 CI 上等於沒掛(KN-001)。

Run: python3 test_knowledge_index.py → exit 0 全過。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).with_name("knowledge_index.py")


def entry(eid, tier="shallow", rule="一句規則", status="observing", tags="a · b"):
    return json.dumps({"id": eid, "tier": tier, "rule": rule, "status": status,
                       "tags": tags}, ensure_ascii=False, indent=2)


def build(entries: dict):
    d = Path(tempfile.mkdtemp())
    e = d / "docs" / "knowledge" / "entries"
    e.mkdir(parents=True)
    for eid, content in entries.items():
        (e / f"{eid}.json").write_text(content, encoding="utf-8")
    return d


def run(d, *extra):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(d), *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    checks = []
    idx = lambda d: d / "docs" / "knowledge" / "INDEX.md"  # noqa: E731

    # 無 INDEX 時 --check → 過期(exit 1),不得當成「沒事」
    d = build({"KN-001": entry("KN-001")})
    rc, _ = run(d, "--check")
    checks.append(("無 INDEX 時 --check → exit 1(不得靜默通過)", rc == 1))

    # 生成 → 檔案出現且含條目 id 與「生成物」標記
    rc, _ = run(d)
    text = idx(d).read_text(encoding="utf-8") if idx(d).is_file() else ""
    checks.append(("生成 INDEX → exit 0 且檔案存在", rc == 0 and idx(d).is_file()))
    checks.append(("INDEX 含條目 id", "KN-001" in text))
    checks.append(("INDEX 標記為生成物(勿手改)",
                   "generated" in text.lower() or "生成物" in text))

    # 生成後 --check → 新鮮
    rc, _ = run(d, "--check")
    checks.append(("生成後 --check → exit 0(新鮮)", rc == 0))

    # 新增條目但不重生 → --check 必須說過期(紅燈可達)
    (d / "docs" / "knowledge" / "entries" / "KN-002.json").write_text(
        entry("KN-002"), encoding="utf-8")
    rc, _ = run(d, "--check")
    checks.append(("新增條目未重生 → --check exit 1(紅燈可達)", rc == 1))

    # 重生後回復新鮮
    run(d)
    rc, _ = run(d, "--check")
    checks.append(("重生後 → --check exit 0", rc == 0))
    checks.append(("INDEX 同時含兩個條目",
                   all(k in idx(d).read_text(encoding="utf-8") for k in ("KN-001", "KN-002"))))

    # 移除條目未重生 → 同樣要說過期(雙向偵測,不能只抓新增)
    (d / "docs" / "knowledge" / "entries" / "KN-002.json").unlink()
    rc, _ = run(d, "--check")
    checks.append(("移除條目未重生 → --check exit 1(雙向偵測)", rc == 1))

    # 排序契約:user-confirmed(DIR)須排在 shallow 之前
    d2 = build({"KN-010": entry("KN-010", tier="shallow"),
                "DIR-001": entry("DIR-001", tier="user-confirmed")})
    run(d2)
    t2 = idx(d2).read_text(encoding="utf-8")
    checks.append(("排序:DIR(user-confirmed)排在 KN(shallow)之前",
                   t2.find("DIR-001") < t2.find("KN-010")))

    # 沒有 entries/ 目錄(單檔模式)→ 不得崩潰
    d3 = Path(tempfile.mkdtemp())
    (d3 / "docs" / "knowledge").mkdir(parents=True)
    rc, _ = run(d3, "--check")
    checks.append(("單檔模式(無 entries/)不崩潰", rc in (0, 1)))

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
