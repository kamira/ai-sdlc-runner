#!/usr/bin/env python3
"""非功能性驗證閘的單元斷言(CHG-20260804-02)。

重點不是九道新閘,而是**三態要分得開**:通過 / 未涵蓋 / 不適用。
把「不適用」讀成「通過」,與把「未涵蓋」讀成「通過」是同一個錯誤——
兩者的後續動作完全不同:未涵蓋要補環境,不適用是永久結論。

Run: python3 test_nonfunctional.py → exit 0 全過,1 有失敗。
"""
import json
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import profile as PR    # noqa: E402

CODE_CHG = "- Skill: ai-sdlc-autopilot v1.14.0\n\n### Acceptance operation\n- operate: x\n"
OLD_CHG = "- Skill: ai-sdlc-autopilot v1.13.0\n\n### Acceptance operation\n- operate: x\n"

# 肯定式的通過措辭。裸比對「通過」會把「非通過」也算進去(KN-003)。
AFFIRMATIVE = ("驗證通過", "檢查通過", "全數通過", "已通過")


def t1_table(checks):
    """T1:分類表九類齊全,每類都有 asks / artifacts / applies_to。"""
    kinds = PR.load_kinds()
    want = {"performance", "load-stress", "concurrency", "resource-leak",
            "build-reproducibility", "license-compliance", "api-contract",
            "visual-regression", "property-fuzz"}
    checks.append(("九類齊全", set(kinds) == want))
    for k, spec in kinds.items():
        checks.append((f"[{k}] 有 asks", bool(spec.get("asks"))))
        checks.append((f"[{k}] 有必要產物", bool(spec.get("artifacts"))))
        checks.append((f"[{k}] 有 applies_to", bool(spec.get("applies_to"))))
        checks.append((f"[{k}] applies_to 全為已知型態",
                       all(p in PR.KNOWN_PROFILES for p in spec.get("applies_to", []))))
    # 使用者的限定條件:後端才獨有的,只在後端納入
    checks.append(("負載只適用於會服務負載的型態",
                   set(kinds["load-stress"]["applies_to"]) == {"backend-service", "data-pipeline"}))
    checks.append(("併發同理", "cli-tool" not in kinds["concurrency"]["applies_to"]))
    checks.append(("視覺回歸只適用前端",
                   kinds["visual-regression"]["applies_to"] == ["frontend-web"]))
    # 與型態無關的兩類不該被縮限
    checks.append(("授權合規適用於所有會散布的型態",
                   len(kinds["license-compliance"]["applies_to"]) >= 5))


def t2_profile(checks):
    """T2:型態宣告用讀的,不用猜。"""
    d = Path(tempfile.mkdtemp())
    (d / ".ai-sdlc").mkdir()
    (d / ".ai-sdlc" / "profile.json").write_text(
        json.dumps({"profiles": ["cli-tool", "library"]}), encoding="utf-8")
    p, err = PR.load_profile(d)
    checks.append(("多型態可讀", err is None and p == ["cli-tool", "library"]))

    d2 = Path(tempfile.mkdtemp())
    p, err = PR.load_profile(d2)
    checks.append(("未宣告回 None 而不是猜", p is None and err is None))

    d3 = Path(tempfile.mkdtemp())
    (d3 / ".ai-sdlc").mkdir()
    (d3 / ".ai-sdlc" / "profile.json").write_text("{壞掉", encoding="utf-8")
    p, err = PR.load_profile(d3)
    checks.append(("壞檔案回報而非照跑", err is not None))
    checks.append(("錯誤訊息說明照跑等於靜默略過", "靜默略過" in (err or "")))

    d4 = Path(tempfile.mkdtemp())
    (d4 / ".ai-sdlc").mkdir()
    (d4 / ".ai-sdlc" / "profile.json").write_text(
        json.dumps({"profiles": ["不存在的型態"]}), encoding="utf-8")
    p, err = PR.load_profile(d4)
    checks.append(("未知型態被拒絕", err is not None and "已知型態" in err))


def t3_applicable(checks):
    """T3:交集運算——後端才獨有的,只在後端適用。"""
    kinds = PR.load_kinds()
    on, off = PR.applicable(["backend-service"], kinds)
    checks.append(("後端適用負載與併發",
                   "load-stress" in on and "concurrency" in on))
    checks.append(("後端不適用視覺回歸", "visual-regression" in off))

    on, off = PR.applicable(["cli-tool", "library"], kinds)
    checks.append(("CLI+library 不被課負載測試的稅", "load-stress" in off))
    checks.append(("CLI+library 不被課併發的稅", "concurrency" in off))
    checks.append(("但仍適用授權合規", "license-compliance" in on))
    checks.append(("仍適用 API 合約(library 有對外契約)", "api-contract" in on))

    on, off = PR.applicable(["frontend-web"], kinds)
    checks.append(("前端適用視覺回歸", "visual-regression" in on))

    # 未宣告 → 全部適用:錯誤方向倒向多驗而非少驗
    on, off = PR.applicable(None, kinds)
    checks.append(("未宣告型態時全部適用(最保守)", len(on) == len(kinds) and off == []))


def t4_t5_gate(checks):
    """T4/T5:三態。"""
    kinds = PR.load_kinds()

    # 不適用:訊息不得出現肯定式的通過措辭
    status, msg = PR.run_gate(".", CODE_CHG, {k: kinds[k] for k in ("load-stress",)},
                              ["cli-tool"])
    checks.append(("全數不適用 → not-applicable", status == "not-applicable"))
    checks.append(("不適用的訊息不得聲稱通過",
                   not any(a in msg for a in AFFIRMATIVE)))
    checks.append(("不適用要說明它與未涵蓋不同", "與「未涵蓋」" in msg))
    checks.append(("不適用要列出理由", "型態不符" in msg or "才有" in msg or "才需要" in msg))

    # 適用但未宣告 → halt 並列出可選項
    status, msg = PR.run_gate(".", CODE_CHG, {k: kinds[k] for k in ("license-compliance",)},
                              ["cli-tool"])
    checks.append(("適用而未宣告 → halt", status == "halt"))
    checks.append(("halt 訊息列出可選項", "license-compliance" in msg and "必要產物" in msg))

    # 空 n/a 視同未宣告
    status, msg = PR.run_gate(".", CODE_CHG + "\n- Non-functional: n/a\n",
                              {k: kinds[k] for k in ("license-compliance",)}, ["cli-tool"])
    checks.append(("空豁免被擋", status == "halt"))
    checks.append(("空豁免的訊息說明它與沒宣告等價", "等價" in msg))

    # 具名豁免 → not-applicable 且列出理由
    status, msg = PR.run_gate(".", CODE_CHG + "\n- Non-functional: n/a(純判定層,無執行期元件)\n",
                              {k: kinds[k] for k in ("license-compliance",)}, ["cli-tool"])
    checks.append(("具名豁免放行", status == "not-applicable"))
    checks.append(("具名豁免列出理由", "純判定層" in msg))

    # 宣告了但指令來自 CHG 內容 → 預設不執行(信任邊界)
    spec_chg = (CODE_CHG + "\n### Non-functional checks\n"
                "- kind: license-compliance\n- cmd: echo x > r.json\n- artifacts: r.json\n")
    status, msg = PR.run_gate(".", spec_chg, {k: kinds[k] for k in ("license-compliance",)},
                              ["cli-tool"])
    checks.append(("CHG 內容宣告的指令預設不執行", status == "halt" and "信任邊界" in msg))

    # 前瞻適用:舊版本的 CHG 不要求
    checks.append(("v1.14 起要求", PR.required(CODE_CHG)))
    checks.append(("v1.13 不要求(前瞻適用)", not PR.required(OLD_CHG)))
    checks.append(("docs-only 不要求", not PR.required("Acceptance-operation: n/a (docs-only)")))


def t7_this_repo(checks):
    """T7:本 repo 的型態宣告與逐類判定。"""
    repo = Path(__file__).resolve().parents[3]
    profiles, err = PR.load_profile(repo)
    checks.append(("本 repo 已宣告型態", err is None and profiles == ["cli-tool", "library"]))
    on, off = PR.applicable(profiles, PR.load_kinds())
    for k in ("load-stress", "concurrency", "resource-leak", "visual-regression"):
        checks.append((f"本 repo 不適用 {k}", k in off))
    for k in ("license-compliance", "build-reproducibility", "api-contract",
              "performance", "property-fuzz"):
        checks.append((f"本 repo 適用 {k}", k in on))
    prof = json.loads((repo / ".ai-sdlc" / "profile.json").read_text(encoding="utf-8"))
    checks.append(("型態宣告附了為什麼是這幾種", bool(prof.get("_why"))))
    checks.append(("也附了為什麼不是那幾種", bool(prof.get("_not"))))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t1_table(checks)
    t2_profile(checks)
    t3_applicable(checks)
    t4_t5_gate(checks)
    t7_this_repo(checks)

    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        if not ok:
            print(f"  [FAIL] {n}")
    if failed:
        print(f"❌ {len(failed)}/{len(checks)} 失敗")
        return 1
    print(f"✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
