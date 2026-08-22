#!/usr/bin/env python3
"""bilingual_check.py 的斷言(CHG-20260803-01 T8)。stdlib-only,三平台一致。

這支檢查刻意**只看結構**(##/###/``` 的數量),不看語意——所以測試也要把那條界線
釘住:結構平行但內容講不同的事必須「通過」。這不是漏洞,是分工;若哪天有人以為
它擋得住語意漂移,這條斷言就是白紙黑字的反證(語意由 reviewer 負責)。

fixture 一律建在 tmpdir。Run: python3 test_bilingual_check.py → exit 0 全過。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).with_name("bilingual_check.py")


def build(files: dict):
    d = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


def run(d):
    r = subprocess.run([sys.executable, str(SCRIPT), "--skill-dir", str(d)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


EN = "# T\n\n## A\n\n### A1\n\n```\ncode\n```\n\n## B\n"
ZH_OK = "# 標題\n\n## 甲\n\n### 甲一\n\n```\ncode\n```\n\n## 乙\n"


def main() -> int:
    checks = []

    rc, out = run(build({"SKILL.md": EN, "SKILL.zh-tw.md": ZH_OK}))
    checks.append(("結構平行 → exit 0", rc == 0 and "1 對" in out))

    # 語意完全不同但結構平行 → 仍通過。這是**刻意**的界線,不是缺陷。
    rc, _ = run(build({"SKILL.md": EN,
                       "SKILL.zh-tw.md": "# 無關\n\n## 貓\n\n### 狗\n\n```\nx\n```\n\n## 魚\n"}))
    checks.append(("語意不同但結構平行 → 仍 exit 0(只驗結構,語意交 reviewer)", rc == 0))

    # 各項結構數不一致都要抓到
    rc, out = run(build({"SKILL.md": EN, "SKILL.zh-tw.md": ZH_OK.replace("## 乙\n", "")}))
    checks.append(("h2 數不一致 → 擋", rc == 1 and "h2" in out))
    rc, out = run(build({"SKILL.md": EN, "SKILL.zh-tw.md": ZH_OK.replace("### 甲一\n\n", "")}))
    checks.append(("h3 數不一致 → 擋", rc == 1 and "h3" in out))
    rc, out = run(build({"SKILL.md": EN, "SKILL.zh-tw.md": ZH_OK.replace("```\ncode\n```", "code")}))
    checks.append(("程式區塊數不一致 → 擋", rc == 1 and "fence" in out))

    # 缺整份譯本
    rc, out = run(build({"SKILL.md": EN}))
    checks.append(("缺 zh-tw 對應檔 → 擋", rc == 1 and "缺對應" in out))

    # 只有 zh 沒有 en:**孤兒譯稿**(待補項 #61)。
    #
    # 這一條原本斷言 `rc == 0`,措辭是「目前不擋(已知界線)」——而那讓**測試在
    # 替缺陷背書**:閘漏了一整個方向,而斷言把那個漏洞寫成規格。
    # `pairs()` 只從英側出發且第一件事就 `continue` 掉所有 `.zh-tw.md`,
    # 於是沒有英側的譯稿永遠不會被檢查。修好之後這一條翻成擋下,而且要**指名孤兒**。
    rc, out = run(build({"SKILL.zh-tw.md": ZH_OK}))
    checks.append(("只有 zh-tw 而無 en → 擋(孤兒譯稿)", rc == 1))
    checks.append(("孤兒的訊息與缺譯**分開措辭**(修法方向相反)",
                   "孤兒譯稿" in out and "缺對應的英文版" in out))
    # 子目錄裡的孤兒也要抓——對稱於下面那條 `references/` 的遞迴斷言。
    rc, out = run(build({"SKILL.md": EN, "SKILL.zh-tw.md": ZH_OK,
                         "references/orphan.zh-tw.md": ZH_OK}))
    checks.append(("子目錄裡的孤兒也抓得到",
                   rc == 1 and "references" in out and "孤兒譯稿" in out))

    # 遞迴掃子目錄(references/ 也要驗到)
    rc, out = run(build({"SKILL.md": EN, "SKILL.zh-tw.md": ZH_OK,
                         "references/x.md": EN, "references/x.zh-tw.md": ZH_OK}))
    checks.append(("遞迴掃 references/ → 2 對", rc == 0 and "2 對" in out))
    rc, out = run(build({"SKILL.md": EN, "SKILL.zh-tw.md": ZH_OK,
                         "references/x.md": EN, "references/x.zh-tw.md": ZH_OK.replace("## 乙\n", "")}))
    checks.append(("子目錄的不平行也會被抓", rc == 1 and "references" in out))

    # 目錄不存在 → exit 2(參數錯誤,與「有漂移」的 1 分開)
    r = subprocess.run([sys.executable, str(SCRIPT), "--skill-dir", str(Path(tempfile.mkdtemp()) / "nope")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    checks.append(("目錄不存在 → exit 2(與漂移的 1 區分)", r.returncode == 2))

    # 空目錄 → 0 對、exit 0。這是**已知的靜默通過**:沒有檔案也算「全部平行」。
    rc, out = run(build({}))
    checks.append(("空目錄 → exit 0 且明示 0 對(已知:無檔案=通過)", rc == 0 and "0 對" in out))

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
