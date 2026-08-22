#!/usr/bin/env python3
"""文件裡手抄的計數,與現實對帳(CHG-20260810-03,待補項 #27)。stdlib-only。

文件裡的數字**不是斷言,只是散文**。沒有東西比對它們,於是每次新增測試檔或
規格檔,它們就有一部分變成謊話——而且沒有人會發現:`AGENTS.md` 是任何 agent 的
第一份入口文件,它說「全部 32 支」時,下一棒不會去數。
與 KN-001 的鏡像同形:沒有人會去追查一個看起來正常的數字。

這一族連續三輪在同一個地方現形(2026-08-06 的 63/15、CHG-20260810-01 一次 5 處、
-02 的規格數),三次的處置都是「順手訂正」——**那正是 KN-005 要消滅的東西**。

判準是兩層,而**第一層比第二層重要**:

  1. 每條宣稱的 pattern 必須命中**剛好一次**。0 次代表措辭被改寫或搬走了,
     這條規則已經沒在看任何東西;2+ 次代表分不出在驗哪一個。兩者都失敗——
     「掃不到」與「數字正確」在退出碼上一樣,那正是 KN-003 的形狀。
  2. 命中之後才比對數值。

清單為空同樣失敗:對零條宣稱回報「全部一致」是恆真回報(KN-001)。

Run: python3 test_doc_counts.py → exit 0 全過,1 有失敗。
"""
import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[2]
REGISTRY = SCRIPTS.parent / "assets" / "doc_counts.json"


def count_test_files(repo: Path) -> int:
    """與 `.github/run_tests.sh` 的搜尋範圍逐字一致:`find skills plugins`,
    排除 `plugins/*/skills/*`(那是 build_suite 產生的複本)。

    兩邊若不一致,這道閘會用一個沒有人在跑的數字去驗文件。
    """
    out = []
    for root in ("skills", "plugins"):
        base = repo / root
        if not base.is_dir():
            continue
        for p in base.rglob("test_*.py"):
            rel = p.relative_to(repo).as_posix()
            if re.match(r"plugins/[^/]+/skills/", rel):
                continue
            out.append(rel)
    return len(out)


def count_feature_files(repo: Path) -> int:
    d = repo / "features"
    return len(list(d.glob("*.feature"))) if d.is_dir() else 0


def count_anchored_files(repo: Path) -> int:
    """讀 `verifier_manifest.json` 的 `files`——**範圍由 manifest 決定**,
    不由檔案在不在決定(拿目錄實際檔數去量,等於把「刪掉檔案」變成合法的離場方式)。
    """
    man = repo / "skills" / "ai-sdlc-autopilot" / "assets" / "verifier_manifest.json"
    try:
        return len(json.loads(man.read_text(encoding="utf-8"))["files"])
    except (OSError, ValueError, KeyError, TypeError):
        return -1          # 讀不到 → 回不可能相等的值,絕不靜默當成 0


MEASURES = {
    "test_files": count_test_files,
    "feature_files": count_feature_files,
    "anchored_files": count_anchored_files,
}


def load_registry(path: Path = REGISTRY) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))["claims"]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def reconcile(claims: list[dict], repo: Path = REPO) -> list[str]:
    """回問題清單(空 = 全部一致)。**清單為空本身就是一個問題**。"""
    problems: list[str] = []
    if not claims:
        return ["清單為空或讀不到——對零條宣稱回報「全部一致」是恆真回報(KN-001)"]

    for c in claims:
        cid = c.get("id", "<無 id>")
        missing = [k for k in ("file", "measure", "pattern") if not c.get(k)]
        if missing:
            problems.append(f"{cid}:清單條目缺欄位 {missing}")
            continue
        if c["measure"] not in MEASURES:
            problems.append(f"{cid}:未知的量測種類 {c['measure']!r}"
                            f"(可用:{sorted(MEASURES)})")
            continue
        f = repo / c["file"]
        if not f.is_file():
            problems.append(f"{cid}:宣稱所在的檔案不存在 {c['file']}")
            continue
        hits = re.findall(c["pattern"], f.read_text(encoding="utf-8"))
        if len(hits) != 1:
            problems.append(
                f"{cid}:pattern 在 {c['file']} 命中 {len(hits)} 次,必須剛好 1 次 — "
                + ("宣稱被改寫或搬走了,這條規則已經沒在看任何東西"
                   if not hits else "打到不只一處,分不出在驗哪一個"))
            continue
        claimed, actual = int(hits[0]), MEASURES[c["measure"]](repo)
        if claimed != actual:
            problems.append(
                f"{cid}:{c['file']} 宣稱 {claimed},實際 {actual}"
                f"({c['measure']})— 文件裡的數字過期了")
    return problems


def main() -> int:
    checks: list[tuple[str, bool]] = []
    claims = load_registry()

    checks.append((f"清單非空(實得 {len(claims)} 條)", bool(claims)))
    checks.append(("三種量測都量得到(非負)",
                   all(fn(REPO) >= 0 for fn in MEASURES.values())))

    problems = reconcile(claims)
    checks.append(("文件計數與現實一致"
                   + (f" — {problems[0]}" if problems else ""), not problems))
    for p in problems[1:]:
        print(f"          · {p}")

    # --- 自檢:這道閘自己的紅燈可達嗎 ---------------------------------------
    # 三條都在驗**判準本身**,不是驗 repo 現況。少了它們,把 reconcile() 改成
    # `return []` 不會有任何測試變紅——而那是讓這道閘消失最省事的方法。
    checks.append(("清單為空 → 失敗(不得回報一致)",
                   bool(reconcile([]))))
    checks.append(("pattern 命中 0 次 → 失敗(掃不到 ≠ 沒問題,KN-003)",
                   bool(reconcile([{"id": "probe", "file": "AGENTS.md",
                                    "measure": "test_files",
                                    "pattern": "這句話不會出現在任何檔案裡 (\\d+)"}]))))
    # 數值不符必須紅。用 tmpdir fixture 而不是拿本 repo 現況反著驗——
    # 「現況剛好相符」證明不了「不符會被抓到」,那是兩件事。
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="doccount-"))
    (tmp / "DOC.md").write_text("# 全部 99 支 test_*.py\n", encoding="utf-8")
    mismatch = reconcile([{"id": "probe", "file": "DOC.md", "measure": "test_files",
                           "pattern": "# 全部 (\\d+) 支 test_\\*\\.py"}], repo=tmp)
    checks.append(("數字不符 → 失敗(宣稱 99 / 實際 0)",
                   bool(mismatch) and "99" in mismatch[0]))
    checks.append(("未知的量測種類 → 失敗(不得靜默略過)",
                   bool(reconcile([{"id": "probe", "file": "DOC.md",
                                    "measure": "no_such_measure",
                                    "pattern": "(\\d+)"}], repo=tmp))))

    # 刻意留著的歷史數字不得被誤判:握手檔第 376 行寫「全部 29 支」是
    # CHG-20260810-01 的歷史記錄。判準寬到打中它,這道閘會要求把記錄改成謊話。
    wl = (REPO / "docs" / "worklog" / "handshake-autopilot.md").read_text(encoding="utf-8")
    checks.append(("握手檔裡刻意的歷史數字仍在(不得被這道閘逼改)",
                   "全部 29 支" in wl))

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
