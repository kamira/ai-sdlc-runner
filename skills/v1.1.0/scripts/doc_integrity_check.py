#!/usr/bin/env python3
"""
doc_integrity_check.py — 文檔抗漂移的機器檢查 / doc-integrity enforcement

把 doc-integrity 從「靠自律遵守」變成「CI / pre-commit 可擋」。它不替你寫文件的語意內容
(那需要人/agent),但會把可機器判斷的漂移擋下,逼你補齊。

檢查項:
  1) 結構漂移:本次(staged)改了結構性程式(預設比對 models / schema / migration / .proto),
     卻沒有一併更動 docs/structure/ → 失敗。(對應「改結構就要同步結構文件」)
  2) CHG↔ACC 連結:docs/changes/ 內狀態為「已實作 / Implemented」(非草稿)的 CHG,
     若 docs/acceptance/ 沒有任何 ACC 提到它 → 失敗。(對應「當場驗收、不可懸空」)

用法 / usage:
  # pre-commit(檢查 staged 變更的結構漂移 + CHG/ACC):
  python3 doc_integrity_check.py --staged
  # 全 repo 掃描(CI / 手動):
  python3 doc_integrity_check.py --repo .
  # 自訂結構性路徑(regex,可多個):
  python3 doc_integrity_check.py --staged --structural 'models/' 'schema' '\\.proto$' 'migrations?/'

退出碼:0 = 通過;1 = 偵測到漂移;2 = 環境/參數錯誤。
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_STRUCTURAL = [r"models?/", r"schema", r"migrations?/", r"\.proto$", r"entities?/"]
CHG_RE = re.compile(r"CHG-\d{8}-\d+", re.IGNORECASE)
# 視為「已實作、應有 ACC」的狀態字樣
IMPLEMENTED_HINTS = ["已實作", "已驗收", "implemented", "accepted", "待驗收", "待 acceptance", "pending acceptance"]
DRAFT_HINTS = ["草稿", "draft"]


def git_staged_files(repo: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"],
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [l.strip() for l in out.splitlines() if l.strip()]


def check_structural_sync(changed: list[str], structural: list[str]) -> list[str]:
    pats = [re.compile(p, re.IGNORECASE) for p in structural]
    structural_changed = [f for f in changed
                          if any(p.search(f) for p in pats) and not f.startswith("docs/")]
    docs_structure_changed = any(f.startswith("docs/structure/") for f in changed)
    problems = []
    if structural_changed and not docs_structure_changed:
        problems.append("改了結構性程式卻未同步 docs/structure/ — 觸發檔:\n    "
                        + "\n    ".join(structural_changed))
    return problems


def check_chg_acc(repo: Path) -> list[str]:
    changes = sorted((repo / "docs" / "changes").glob("CHG-*.md")) if (repo / "docs" / "changes").is_dir() else []
    acc_dir = repo / "docs" / "acceptance"
    acc_text = ""
    if acc_dir.is_dir():
        for a in acc_dir.glob("ACC-*.md"):
            acc_text += a.read_text(encoding="utf-8", errors="ignore") + "\n"
    problems = []
    for chg in changes:
        text = chg.read_text(encoding="utf-8", errors="ignore")
        low = text.lower()
        is_draft = any(h in low for h in DRAFT_HINTS) and not any(h in low for h in ("已實作", "已驗收", "implemented", "accepted"))
        looks_implemented = any(h.lower() in low for h in IMPLEMENTED_HINTS)
        if is_draft and not looks_implemented:
            continue
        m = CHG_RE.search(chg.stem) or CHG_RE.search(text)
        chg_id = m.group(0) if m else chg.stem
        if chg_id.lower() not in acc_text.lower():
            problems.append(f"{chg.name}({chg_id})已實作但 docs/acceptance/ 找不到對應 ACC — 驗收懸空")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--staged", action="store_true", help="檢查 git staged 變更的結構漂移")
    ap.add_argument("--structural", nargs="*", default=DEFAULT_STRUCTURAL)
    args = ap.parse_args(argv[1:])
    repo = Path(args.repo).resolve()

    problems: list[str] = []
    if args.staged:
        changed = git_staged_files(repo)
        problems += check_structural_sync(changed, args.structural)
    problems += check_chg_acc(repo)

    if problems:
        print("❌ doc-integrity 檢查未通過:")
        for p in problems:
            print(f"  - {p}")
        print("\n請補同步文件(改結構→更新 docs/structure;已實作的 CHG→補對應 ACC)後再提交。")
        return 1
    print("✅ doc-integrity 檢查通過(結構同步 + CHG↔ACC 連結)。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
