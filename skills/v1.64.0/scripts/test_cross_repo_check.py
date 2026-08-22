#!/usr/bin/env python3
"""cross_repo_check.py 的斷言(CHG-20260803-01 T8)。stdlib-only,三平台一致。

驗的是「消費 repo 釘住的契約版本 vs 權威 repo 現行版本」。這裡最容易出的錯是
**把讀不到檔案當成一致**——那會讓跨 repo 漂移在最需要擋的時候靜默放行。
故「缺檔」必須有明確的非零退出碼,不得混入「全部一致」。

Run: python3 test_cross_repo_check.py → exit 0 全過。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).with_name("cross_repo_check.py")


def make(authority_ver="v3", pinned=("v3", "v3"), omit_version=False, omit_pin=False):
    root = Path(tempfile.mkdtemp())
    auth = root / "authority"
    (auth / "docs" / "contracts").mkdir(parents=True)
    if not omit_version:
        (auth / "docs" / "contracts" / "VERSION").write_text(authority_ver + "\n", encoding="utf-8")
    repos = []
    for i, ver in enumerate(pinned):
        r = root / f"repo{i}"
        (r / "docs").mkdir(parents=True)
        if not omit_pin:
            (r / "docs" / "authority.md").write_text(
                f"# authority\n\n- 釘住版本: {ver}(fixture)\n", encoding="utf-8")
        repos.append(r)
    return root, auth, repos


def run_manifest(auth, repos):
    d = Path(tempfile.mkdtemp())
    m = d / "manifest.json"
    m.write_text(json.dumps({"authority": str(auth), "repos": [str(r) for r in repos]}),
                 encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(m)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_args(auth, repos):
    r = subprocess.run([sys.executable, str(SCRIPT), "--authority", str(auth),
                        "--repos", *[str(x) for x in repos]],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    checks = []

    # 全部一致 → exit 0(兩種呼叫方式都要成立)
    _, auth, repos = make(pinned=("v3", "v3"))
    rc, _ = run_manifest(auth, repos)
    checks.append(("manifest:全部釘同版 → exit 0", rc == 0))
    rc, _ = run_args(auth, repos)
    checks.append(("--authority/--repos:全部釘同版 → exit 0", rc == 0))

    # 其中一個落後 → exit 1 且點名該 repo(紅燈可達)
    _, auth, repos = make(authority_ver="v3", pinned=("v3", "v2"))
    rc, out = run_manifest(auth, repos)
    checks.append(("有 repo 落後 → exit 1", rc == 1))
    checks.append(("落後時點名該 repo", "repo1" in out))
    checks.append(("不得誤報一致的那個 repo", out.count("repo0") <= out.count("repo1")))

    # 全部落後
    _, auth, repos = make(authority_ver="v4", pinned=("v3", "v3"))
    rc, _ = run_manifest(auth, repos)
    checks.append(("全部落後 → exit 1", rc == 1))

    # 權威缺 VERSION → 設定錯誤(exit 2),不得當成一致
    _, auth, repos = make(omit_version=True)
    rc, _ = run_manifest(auth, repos)
    checks.append(("權威缺 VERSION → exit 2(不得當成一致)", rc == 2))

    # 消費 repo 缺 authority.md → **目前靜默跳過**(exit 0)。
    # 這是 read_repo_pinned 的刻意設計(「此 repo 未宣告指標,可能不參與跨 repo 契約」),
    # 但同時也是一條無聲關閉檢查的路徑:manifest 列了某 repo、該 repo 卻沒有 authority.md 時,
    # 結果與「一致」無法區分。本斷言釘住**現行行為**,並在
    # docs/ai-sdlc-suite/acceptance/verification-coverage.md 登記為已知缺口(不在本 CHG 的
    # 行為變更白名單內,故記錄不修)。
    _, auth, repos = make(omit_pin=True)
    rc, _ = run_manifest(auth, repos)
    checks.append(("消費 repo 缺 authority.md → 目前靜默跳過(已知缺口,見 coverage 登記簿)",
                   rc == 0))

    # manifest 不存在 → **目前拋未捕捉的 FileNotFoundError**(traceback,退出碼 1),
    # 與 docstring 承諾的「2 = 設定/檔案錯誤」不符。同樣登記為已知偏差、記錄不修。
    r = subprocess.run([sys.executable, str(SCRIPT), str(Path(tempfile.mkdtemp()) / "nope.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    checks.append(("manifest 不存在 → 目前為 traceback/exit 1(文件承諾 2,已知偏差)",
                   r.returncode == 1 and "FileNotFoundError" in (r.stderr or "")))

    # 版本比對須看內容而非字串前綴(v3 不得被 v30 誤判為相同)
    _, auth, repos = make(authority_ver="v3", pinned=("v30",))
    rc, _ = run_manifest(auth, repos)
    checks.append(("v30 不得被當成 v3(前綴誤判防護)", rc == 1))

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
