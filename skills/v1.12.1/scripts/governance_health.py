#!/usr/bin/env python3
"""
governance_health.py — 治理健康度報告 / governance health report(唯讀、不設閘門)

回答「這個 repo 的治理流程本身健不健康」:CHG 狀態分佈、懸空驗收、暫停項、停滯 claim、
緊急追溯與文件同步(漂移)次數、ACC 通過率、迴歸集規模、歸檔量。定期跑(或 CI 非阻斷),
趨勢異常(懸空變多、緊急通道常用、通過率下滑)就是流程問題的訊號;回顧發現寫進 knowledge。

用法:
  python3 governance_health.py --repo .            # 人讀報告
  python3 governance_health.py --repo . --json     # 機器可讀
  python3 governance_health.py --repo . --lease-days 2   # 停滯 claim 判定天數(預設 1)

退出碼:恆為 0(報告非閘門;要擋提交用 doc_integrity_check.py)。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

CHG_RE = re.compile(r"X?CHG-\d{8}-\d+", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

PAUSED = ["暫停", "paused"]
ACCEPTED = ["已驗收", "accepted"]
IMPLEMENTED = ["已實作", "implemented", "待驗收", "pending acceptance"]
DRAFT = ["草稿", "draft"]
EMERGENCY = ["緊急", "emergency", "追溯", "retroactive"]
DOCSYNC = ["文件同步", "doc sync", "doc-sync"]
IN_PROGRESS = ["進行中", "in progress"]

PASS_HINTS = ["部分通過", "partial pass", "通過", "pass", "未通過", "fail"]  # 順序:長字先判


def read(f: Path) -> str:
    return f.read_text(encoding="utf-8", errors="ignore")


def classify_chg(text: str) -> str:
    low = text.lower()
    # 取「## 狀態 / Status」段之後的內容優先判斷,退回全文
    m = re.search(r"^##\s*(狀態|Status)\b(.*?)(?=^#|\Z)", text, re.MULTILINE | re.DOTALL)
    scope = (m.group(2) if m else text).lower()
    for hints, label in ((PAUSED, "paused"), (ACCEPTED, "accepted"),
                         (IMPLEMENTED, "implemented"), (DRAFT, "draft")):
        if any(h in scope for h in hints):
            return label
    for hints, label in ((PAUSED, "paused"), (ACCEPTED, "accepted"),
                         (IMPLEMENTED, "implemented"), (DRAFT, "draft")):
        if any(h in low for h in hints):
            return label
    return "unknown"


def acc_conclusion(text: str) -> str:
    m = re.search(r"(結論|Conclusion)\s*[::]\s*(.+)", text)
    if not m:
        return "unknown"
    val = m.group(2).strip().lower()
    if "部分" in val or "partial" in val:
        return "partial"
    if "未通過" in val or "fail" in val:
        return "fail"
    if "通過" in val or "pass" in val:
        return "pass"
    return "unknown"


def newest_date(text: str) -> date | None:
    ds = [date(int(y), int(mo), int(d)) for y, mo, d in DATE_RE.findall(text)
          if 2000 <= int(y) <= 2100 and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31]
    return max(ds) if ds else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lease-days", type=int, default=1, help="claim 超過幾天無更新視為停滯")
    ap.add_argument("--hanging-max", type=int, default=3, help="懸空驗收警戒值(超過→警示)")
    ap.add_argument("--stale-max", type=int, default=0, help="停滯 claim 警戒值(超過→警示)")
    ap.add_argument("--gate", action="store_true", help="超過警戒值時退出碼 1(預設報告不擋)")
    args = ap.parse_args(argv[1:])
    repo = Path(args.repo).resolve()
    today = datetime.now(timezone.utc).date()  # 治理慣例:一律 UTC+0

    r: dict = {"repo": str(repo), "date": today.isoformat(), "timezone": "UTC+0"}

    # --- CHG 狀態分佈 + 懸空 + 緊急/文件同步 ---
    ch_dir = repo / "docs" / "changes"
    acc_dir = repo / "docs" / "acceptance"
    acc_text = ""
    if acc_dir.is_dir():
        for a in acc_dir.glob("ACC-*.md"):
            acc_text += read(a).lower() + "\n"

    status_counts = {"draft": 0, "implemented": 0, "paused": 0, "accepted": 0, "unknown": 0}
    hanging, paused_list, emergency_n, docsync_n = [], [], 0, 0
    lite_n, preauth_n = 0, 0
    lite_re = re.compile(r"自驗|self-?verified", re.IGNORECASE)
    lowrisk_re = re.compile(r"(風險分級|Risk)\s*[::]\s*[^\n]{0,40}?(低|low)", re.IGNORECASE)
    preauth_re = re.compile(r"預授權|pre-?auth", re.IGNORECASE)
    if ch_dir.is_dir():
        for chg in sorted(ch_dir.glob("CHG-*.md")):
            text = read(chg)
            st = classify_chg(text)
            status_counts[st] += 1
            low = text.lower()
            if sum(h in low for h in EMERGENCY) >= 2:
                emergency_n += 1
            if any(h in low for h in DOCSYNC):
                docsync_n += 1
            if lite_re.search(text) and lowrisk_re.search(text):
                lite_n += 1
            if preauth_re.search(text):
                preauth_n += 1
            chg_id = (CHG_RE.search(chg.stem) or CHG_RE.search(text))
            cid = chg_id.group(0) if chg_id else chg.stem
            if st == "implemented" and cid.lower() not in acc_text:
                hanging.append(cid)
            if st == "paused":
                paused_list.append(cid)
    r["chg_status"] = status_counts
    r["hanging_acceptance"] = hanging
    r["paused"] = paused_list
    r["emergency_retroactive_chg"] = emergency_n
    r["doc_sync_chg(drift_signal)"] = docsync_n
    r["lite_chg"] = lite_n
    r["preauth_usage"] = preauth_n

    # --- ACC 結論率 ---
    concl = {"pass": 0, "partial": 0, "fail": 0, "unknown": 0}
    if acc_dir.is_dir():
        for a in sorted(acc_dir.glob("ACC-*.md")):
            concl[acc_conclusion(read(a))] += 1
    total_acc = sum(concl.values())
    r["acc_conclusions"] = concl
    r["acc_pass_rate"] = round(concl["pass"] / total_acc, 2) if total_acc else None

    # --- 停滯 claim(coordination.md + coordination/claims/*.md)---
    stale, active = [], 0
    sources = [repo / "docs" / "coordination.md"]
    claims_dir = repo / "docs" / "coordination" / "claims"
    if claims_dir.is_dir():
        sources += sorted(claims_dir.glob("*.md"))
    for src in sources:
        if not src.is_file():
            continue
        for line in read(src).splitlines():
            low = line.lower()
            if any(h in low for h in IN_PROGRESS):
                active += 1
                d = newest_date(line) or newest_date(read(src))
                if d and (today - d).days > args.lease_days:
                    stale.append(f"{src.name}: {line.strip()[:70]}")
    r["claims_in_progress"] = active
    r["stale_claims(lease_days=%d)" % args.lease_days] = stale

    # --- knowledge 階梯統計(DIR / deep / shallow)---
    kn_dir_n = kn_deep = kn_shallow = 0
    kn_path = repo / "docs" / "knowledge"
    if kn_path.is_dir():
        for kf in sorted(kn_path.rglob("*.json")):  # JSON 正典:結構化讀,不 regex
            if "archive" in kf.parts:
                continue
            try:
                kd = json.loads(read(kf))
            except json.JSONDecodeError:
                continue  # 壞檔由 doc_integrity fail-loud 把關,統計端跳過
            tier = kd.get("tier")
            if tier == "user-confirmed" or str(kd.get("id", "")).startswith("DIR"):
                kn_dir_n += 1
            elif tier == "deep":
                kn_deep += 1
            elif tier == "shallow":
                kn_shallow += 1
        for kf in sorted(kn_path.rglob("*.md")):  # 過渡期 md 條目
            if "archive" in kf.parts or kf.name == "INDEX.md":
                continue
            kt = read(kf)
            kn_dir_n += len(re.findall(r"^##\s*DIR-", kt, re.MULTILINE))
            kn_deep += len(re.findall(r"tier\s*[::]\s*deep", kt, re.IGNORECASE))
            kn_shallow += len(re.findall(r"tier\s*[::]\s*shallow", kt, re.IGNORECASE))
    r["knowledge"] = {"directives": kn_dir_n, "deep": kn_deep, "shallow": kn_shallow}

    # --- 迴歸集規模 + 歸檔量 ---
    reg = acc_dir / "regression.md"
    reg_items = 0
    if reg.is_file():
        rows = [l for l in read(reg).splitlines() if l.strip().startswith(("|", "- "))]
        reg_items = max(0, len([l for l in rows if not re.match(r"^\|[\s\-:|]+\|$", l.strip())]) - 1) \
            if any(l.strip().startswith("|") for l in rows) else len(rows)
    r["regression_items"] = reg_items
    r["archived"] = {
        "changes": len(list((ch_dir / "archive").glob("*.md"))) if (ch_dir / "archive").is_dir() else 0,
        "acceptance": len(list((acc_dir / "archive").glob("*.md"))) if (acc_dir / "archive").is_dir() else 0,
    }

    # --- 閾值 → 行動(超標=先收尾、停開新需求;見 doc-integrity)---
    warnings = []
    if len(hanging) > args.hanging_max:
        warnings.append(f"懸空驗收 {len(hanging)} > {args.hanging_max}:先收尾再開新需求")
    if len(stale) > args.stale_max:
        warnings.append(f"停滯 claim {len(stale)} > {args.stale_max}:先依租約規則接管/釋放")
    total_chg = sum(status_counts.values())
    if total_chg >= 10 and emergency_n / total_chg > 0.1:
        warnings.append(f"緊急/追溯占比 {emergency_n}/{total_chg} 超過 10%:正常流程太慢,檢討流程本身")
    r["warnings"] = warnings

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 1 if (args.gate and warnings) else 0

    print(f"# 治理健康度 — {r['repo']}({r['date']} UTC+0)\n")
    sc = r["chg_status"]
    print(f"CHG 狀態:草稿 {sc['draft']} | 已實作 {sc['implemented']} | 暫停 {sc['paused']}"
          f" | 已驗收 {sc['accepted']} | 無法判讀 {sc['unknown']}")
    print(f"懸空驗收:{len(hanging)}" + (f" ← {', '.join(hanging)}(需優先收尾)" if hanging else "(健康)"))
    print(f"暫停中:{len(paused_list)}" + (f" ← {', '.join(paused_list)}" if paused_list else ""))
    print(f"ACC 結論:通過 {concl['pass']} / 部分 {concl['partial']} / 未通過 {concl['fail']}"
          f"(通過率 {r['acc_pass_rate']})")
    print(f"緊急/追溯 CHG:{emergency_n}(常態性偏高=正常流程太慢的訊號)")
    print(f"文件同步 CHG(漂移訊號):{docsync_n}")
    print(f"lite 佔比:{lite_n}/{sum(status_counts.values())};預授權使用:{preauth_n}(異常偏高=白名單/邊界該 review)")
    print(f"knowledge 階梯:DIR {kn_dir_n} / deep {kn_deep} / shallow {kn_shallow}(shallow 長期不升不退=該 review)")
    print(f"進行中 claim:{active};停滯:{len(stale)}")
    for s in stale:
        print(f"  - {s}")
    print(f"迴歸集項目:{reg_items};歸檔:changes {r['archived']['changes']} / acceptance {r['archived']['acceptance']}")
    for w in warnings:
        print(f"⚠️  {w}")
    return 1 if (args.gate and warnings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
