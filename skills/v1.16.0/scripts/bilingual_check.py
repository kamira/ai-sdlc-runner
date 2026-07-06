#!/usr/bin/env python3
"""
bilingual_check.py — en↔zh-tw 雙語結構漂移檢查 / bilingual structural drift check

本 skill 的每份文件都有 `.md`(英)與 `.zh-tw.md`(繁中)兩份,靠人工同步——本腳本把
「兩語言結構是否還平行」變成機器可驗:比對每對檔案的 章節標題數(##/###)、程式碼區塊數,
不比語意(語意一致性交給 reviewer)。結構數對不上,幾乎必然是某次只改了單邊。

用法:
  python3 bilingual_check.py --skill-dir skills/ai-sdlc
退出碼:0 = 通過;1 = 有漂移;2 = 參數錯誤。
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path


def profile(f: Path) -> dict:
    text = f.read_text(encoding="utf-8", errors="ignore")
    return {
        "h2": len(re.findall(r"^## ", text, re.MULTILINE)),
        "h3": len(re.findall(r"^### ", text, re.MULTILINE)),
        "fence": len(re.findall(r"^```", text, re.MULTILINE)),
    }


def pairs(skill_dir: Path):
    for en in sorted(skill_dir.rglob("*.md")):
        if en.name.endswith(".zh-tw.md"):
            continue
        zh = en.with_name(en.name[:-3] + ".zh-tw.md")
        yield en, zh


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", default=".")
    args = ap.parse_args(argv[1:])
    root = Path(args.skill_dir).resolve()
    if not root.is_dir():
        print(f"找不到目錄:{root}")
        return 2

    problems = []
    checked = 0
    for en, zh in pairs(root):
        if not zh.exists():
            problems.append(f"{en.relative_to(root)} 缺對應的 zh-tw 版")
            continue
        checked += 1
        pe, pz = profile(en), profile(zh)
        diffs = [f"{k}: en={pe[k]} zh={pz[k]}" for k in pe if pe[k] != pz[k]]
        if diffs:
            problems.append(f"{en.relative_to(root)} ↔ zh-tw 結構不平行({'; '.join(diffs)})— 多半是只改了單邊")

    if problems:
        print(f"❌ 雙語檢查未通過(共查 {checked} 對):")
        for p in problems:
            print(f"  - {p}")
        print("\n請把落後的那一邊補到與另一邊平行(語意由審閱者把關,本檢查只看結構)。")
        return 1
    print(f"✅ 雙語檢查通過({checked} 對檔案結構平行:##/###/``` 數一致)。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
