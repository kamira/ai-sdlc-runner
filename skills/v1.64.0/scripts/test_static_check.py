#!/usr/bin/env python3
"""靜態/安全檢查的斷言(CHG-20260803-06)。stdlib-only,三平台一致。

每條規則都用 fixture 各驗一次「該抓到」與一次「不該誤報」。
誤報是這類工具的主要死因——一旦開始噪音,人就會學會略過整份輸出,
於是真正的發現也一起被略過了。

依 KN-003:所有「該擋」的斷言都另驗輸出不是崩潰。
Run: python3 test_static_check.py → exit 0 全過。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).with_name("static_check.py")


def run(files: dict, *extra):
    d = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(d), "--json", *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        data = {"findings": [], "exempted": [], "_raw": r.stdout + r.stderr}
    return r.returncode, data, d


def rules(data):
    return {f["rule"] for f in data.get("findings", [])}


def main() -> int:
    checks = []

    def hit(label, code, rule, extra_files=None):
        files = {"m.py": code}
        files.update(extra_files or {})
        rc, data, _ = run(files)
        got = rules(data)
        ok = rc == 1 and rule in got and "Traceback" not in json.dumps(data)
        checks.append((f"抓到 {label}" + ("" if ok else f"(實得 {sorted(got)})"), ok))

    def clean(label, code):
        rc, data, _ = run({"m.py": code})
        ok = rc == 0 and not data.get("findings")
        checks.append((f"不誤報:{label}" + ("" if ok else f"(誤報 {rules(data)})"), ok))

    # ---------- 安全 ----------
    hit("eval", "x = eval(user_input)\n", "dangerous-eval")
    hit("exec", "exec(code)\n", "dangerous-eval")
    hit("pickle.loads", "import pickle\npickle.loads(blob)\n", "unsafe-deserialization")
    hit("yaml.load 無 SafeLoader", "import yaml\nyaml.load(s)\n", "unsafe-yaml")
    hit("tempfile.mktemp", "import tempfile\ntempfile.mktemp()\n", "insecure-temp")
    hit("md5", "import hashlib\nhashlib.md5(b'x')\n", "weak-hash")
    hit("TLS 關閉", "import requests\nrequests.get(u, verify=False)\n", "tls-verification-off")
    hit("shell=True(變數指令)",
        "import subprocess\nsubprocess.run(cmd, shell=True)\n", "shell-true")
    hit("shell=True + 字串插值(注入形態)",
        "import subprocess\nsubprocess.run(f'ls {d}', shell=True)\n", "shell-injection")

    # 不誤報:註解與字串裡的 eval、安全的 yaml、argv 陣列
    clean("註解與字串裡的 eval", "# eval(x)\ns = 'eval('\n")
    clean("yaml.safe_load", "import yaml\nyaml.safe_load(s)\n")
    clean("yaml.load 指定 SafeLoader", "import yaml\nyaml.load(s, Loader=yaml.SafeLoader)\n")
    clean("subprocess argv 陣列", "import subprocess\nsubprocess.run(['ls', d])\n")
    clean("verify=True", "import requests\nrequests.get(u, verify=True)\n")
    clean("sha256", "import hashlib\nhashlib.sha256(b'x')\n")

    # ---------- lint ----------
    hit("未使用 import", "import os\nprint(1)\n", "unused-import")
    hit("bare except", "try:\n    f()\nexcept:\n    pass\n", "bare-except")
    hit("可變預設參數", "def f(a=[]):\n    return a\n", "mutable-default")
    clean("有用到的 import", "import os\nprint(os.sep)\n")
    clean("以屬性使用的 import", "import json\njson.dumps({})\n")
    clean("具名 except", "try:\n    f()\nexcept ValueError:\n    pass\n")
    clean("不可變預設參數", "def f(a=None):\n    return a\n")

    # ---------- secrets ----------
    rc, data, _ = run({"conf.yml": "token: ghp_" + "a" * 36 + "\n"})
    checks.append(("secrets 掃描涵蓋 .yml(不只 docs/)",
                   rc == 1 and any(r.startswith("secret:") for r in rules(data))))
    rc, data, _ = run({"deploy.sh": "AKIA" + "A" * 16 + "\n"})
    checks.append(("secrets 掃描涵蓋 .sh", rc == 1 and "secret:aws-access-key" in rules(data)))
    rc, data, _ = run({"m.py": "key = 'short'\n"})
    checks.append(("短字串不誤報為憑證", rc == 0))

    # ---------- allowlist ----------
    files = {"m.py": "import subprocess\nsubprocess.run(cmd, shell=True)\n"}
    d = Path(tempfile.mkdtemp())
    al = d / "allow.json"
    al.write_text(json.dumps({"allow": {"m.py::shell-true": "測試用的正當理由"}},
                             ensure_ascii=False), encoding="utf-8")
    rc, data, _ = run(files, "--allowlist", str(al))
    checks.append(("allowlist 具名豁免 → 放行", rc == 0))
    checks.append(("豁免項仍被列出(不是消失)",
                   len(data.get("exempted", [])) == 1))
    checks.append(("豁免項帶著理由",
                   data.get("exempted", [{}])[0].get("reason") == "測試用的正當理由"))
    # 壞掉的 allowlist 不得讓檢查被略過
    bad = d / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(d),
                        "--allowlist", str(bad)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    checks.append(("allowlist 損毀 → exit 2(不得因此略過檢查)", r.returncode == 2))

    # ---------- 範圍與過濾 ----------
    rc, data, _ = run({"m.py": "import os\n"}, "--only", "security")
    checks.append(("--only security 過濾掉 lint", rc == 0))
    rc, data, _ = run({"m.py": "import os\n"}, "--only", "lint")
    checks.append(("--only lint 保留 lint", rc == 1))
    # --paths 只檢查指定檔
    d2 = Path(tempfile.mkdtemp())
    (d2 / "a.py").write_text("import os\n", encoding="utf-8")
    (d2 / "b.py").write_text("print(1)\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(d2),
                        "--paths", "b.py", "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    checks.append(("--paths 只檢查指定檔", r.returncode == 0))

    # 語法錯誤要回報而非崩潰
    rc, data, _ = run({"m.py": "def f(:\n"})
    checks.append(("語法錯誤 → 回報而非崩潰",
                   rc == 1 and "syntax-error" in rules(data)))

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
