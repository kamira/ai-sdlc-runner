#!/usr/bin/env python3
"""role_loadout.py 的斷言(CHG-20260803-01 T8)。stdlib-only,三平台一致。

role_loadout 決定「這個角色進場要載哪些 references」。載少了 = 該角色不知道自己
該遵守什麼規則,而且不會有任何錯誤訊息——所以「未知角色必須 exit 2 而非回空清單」
是這裡最重要的一條:靜默回空 = 角色以為自己沒有規則要讀。

Run: python3 test_role_loadout.py → exit 0 全過。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).with_name("role_loadout.py")
ASSET = SCRIPT.parent.parent / "assets" / "role_refs.json"


def run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    checks = []
    cfg = json.loads(ASSET.read_text(encoding="utf-8-sig"))
    roles = list(cfg.get("roles", {}))
    aliases = cfg.get("aliases", {})

    checks.append(("出貨的 role_refs.json 至少定義一個角色", len(roles) > 0))

    # 每個出貨角色都必須解析成功,且輸出非空(載入清單為空 = 該角色沒規則可讀)
    for role in roles:
        rc, out = run("--role", role, "--json")
        ok = rc == 0
        if ok:
            try:
                data = json.loads(out)
                # 契約:{"role": <解析後角色>, "load": [<reference 名稱>, ...]}
                ok = (data.get("role") == role and isinstance(data.get("load"), list)
                      and len(data["load"]) > 0)
            except json.JSONDecodeError:
                ok = False
        checks.append((f"角色 {role} → exit 0 且 load 清單非空", ok))

    # 別名必須指到真角色(指錯 = 進場載到別人的規則)
    for alias, target in aliases.items():
        rc, _ = run("--role", alias)
        checks.append((f"別名 {alias} → {target} 可解析", rc == 0 and target in roles))

    # 未知角色必須 exit 2,不得靜默回空清單
    rc, out = run("--role", "no_such_role_xyz")
    checks.append(("未知角色 → exit 2 且明示(不得靜默回空)", rc == 2 and "未知角色" in out))

    # --list 與無 --role 都列出角色
    rc, out = run("--list")
    checks.append(("--list → exit 0 且列出角色", rc == 0 and all(r in out for r in roles)))
    rc, out = run()
    checks.append(("無 --role 視同 --list", rc == 0 and "角色" in out))

    # 情境旗標只增不減(加旗標後的清單必須是原清單的超集)
    base_rc, base_out = run("--role", roles[0], "--json")
    for flag in ("--multi-repo", "--parallel", "--autonomous", "--cicd", "--multi-branch"):
        rc, out = run("--role", roles[0], flag, "--json")
        ok = rc == 0 and len(out) >= len(base_out)
        checks.append((f"{flag} 只增不減({roles[0]})", ok))

    # 設定檔壞掉 → exit 2(不得回退成空清單而看起來像成功)
    d = Path(tempfile.mkdtemp())
    bad = d / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    rc, _ = run("--role", roles[0], "--policy", str(bad))
    checks.append(("設定檔損毀 → exit 2(不得靜默回空)", rc == 2))

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
