#!/usr/bin/env python3
"""授權合規與建置可重現的單元斷言(CHG-20260804-03)。

CHG-20260804-02 把非功能性九類分派好了,卻留下 C2 剛修掉的那個洞:
只驗「指令回 0 + 產物存在」,從不讀內容。一份寫著「12 個 GPL 相依」的報告,
只要檔案存在且非空就會被讀成通過。本檔驗的是補起來的那一層。

Run: python3 test_license_repro.py → exit 0 全過,1 有失敗。
"""
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import profile as PR        # noqa: E402
from lib import quality_judge as QJ  # noqa: E402

AFFIRMATIVE = ("驗證通過", "檢查通過", "全數通過", "已通過")


def _lic(license_file="LICENSE", deps=None):
    return json.dumps({"project": {"license_file": license_file,
                                   "searched": ["LICENSE", "LICENSE.md"]},
                       "dependencies": deps if deps is not None
                       else [{"name": "behave", "version": "1.2.6", "license": "BSD"}]})


def _repro(identical=True, idem=True, matches=True, files=None):
    return json.dumps({"identical": identical, "idempotent": idem,
                       "committed_matches_build": matches,
                       "differing_files": files or []})


def t2_license(checks):
    """T2:授權判讀。"""
    ok, msg, _ = QJ.judge("license-compliance", _lic(), {"findings": {}})
    checks.append(("寬鬆授權 + 有 LICENSE → 放行", ok))
    checks.append(("訊息列出本專案授權檔", "LICENSE" in msg))

    # 查別人卻不查自己,是最容易漏的一格——而本 repo 正好就漏了
    ok, msg, _ = QJ.judge("license-compliance", _lic(license_file=None), {"findings": {}})
    checks.append(("本專案缺 LICENSE → 擋下", not ok))
    checks.append(("擋下訊息點名缺 LICENSE", "沒有 LICENSE" in msg))
    checks.append(("擋下訊息說明為何要有", "散布" in msg))

    # copyleft 只指名不自動擋:開發期相依不感染散布物
    ok, msg, _ = QJ.judge("license-compliance",
                          _lic(deps=[{"name": "x", "version": "1", "license": "GPL-3.0"}]),
                          {"findings": {}})
    checks.append(("copyleft 相依指名但不自動擋", ok))
    checks.append(("指名時列出該相依", "x==1" in msg and "GPL-3.0" in msg))
    checks.append(("說明為何不自動擋", "不感染" in msg))

    # 查不到不等於沒有(KN-004)
    ok, msg, _ = QJ.judge("license-compliance",
                          _lic(deps=[{"name": "y", "version": "2", "license": "UNKNOWN"}]),
                          {"findings": {}})
    checks.append(("未知授權被指名", "y==2" in msg))

    # 基線可具名豁免
    f = {"kind": "license-compliance", "rule": "GPL-3.0", "file": "x==1",
         "message": "非寬鬆或未知授權"}
    base = {"findings": {QJ.fingerprint(f): {"reason": "僅開發期使用", "kind": "license-compliance"}}}
    ok, msg, _ = QJ.judge("license-compliance",
                          _lic(deps=[{"name": "x", "version": "1", "license": "GPL-3.0"}]), base)
    checks.append(("基線內的相依不再被指名", "x==1" not in msg))

    ok, msg, _ = QJ.judge("license-compliance", "不是 JSON", {"findings": {}})
    checks.append(("壞產物擋下", not ok))
    checks.append(("壞產物不得聲稱通過", not any(a in msg for a in AFFIRMATIVE)))


def t4_repro(checks):
    """T4:建置可重現——兩件不同的事都要成立。"""
    ok, msg, _ = QJ.judge("build-reproducibility", _repro(), {})
    checks.append(("一致 → 放行", ok))
    checks.append(("訊息說明兩件事都驗了", "兩次建置" in msg and "已提交" in msg))

    ok, msg, _ = QJ.judge("build-reproducibility",
                          _repro(identical=False, idem=False), {})
    checks.append(("同步不冪等 → 擋", not ok))
    checks.append(("指出建置本身不穩定", "不穩定" in msg))

    ok, msg, _ = QJ.judge("build-reproducibility",
                          _repro(identical=False, matches=False,
                                 files=["plugins/a/skills/x.py"]), {})
    checks.append(("已提交複本不符 → 擋", not ok))
    checks.append(("指出產物被手改過", "手改" in msg))
    checks.append(("列出差異檔", "plugins/a/skills/x.py" in msg))

    ok, msg, _ = QJ.judge("build-reproducibility", json.dumps({}), {})
    checks.append(("缺 identical 欄位 → 擋", not ok))
    checks.append(("缺欄位時不得聲稱通過", not any(a in msg for a in AFFIRMATIVE)))


def t6_defer(checks):
    """T6:逐類具名延後。"""
    spec = ("### Non-functional checks\n"
            "- kind: license-compliance\n- cmd: echo x\n- artifacts: a.json\n"
            "- kind: api-contract\n- defer: 需先決定契約快照格式\n")
    parsed = PR.parse_spec(spec)
    checks.append(("逐項解析不會把 defer 對錯人",
                   parsed[0]["defer"] is None and parsed[1]["defer"] == "需先決定契約快照格式"))
    checks.append(("有 cmd 的那項仍取得 cmd", parsed[0]["cmd"] == "echo x"))

    kinds = PR.load_kinds()
    chg = ("- Skill: ai-sdlc-autopilot v1.15.0\n\n### Acceptance operation\n- operate: x\n"
           "\n### Non-functional checks\n- kind: api-contract\n- defer: 需先決定契約快照格式\n")
    status, msg = PR.run_gate(".", chg, {"api-contract": kinds["api-contract"]},
                              ["library"], True)
    checks.append(("具名延後 → 未涵蓋而非通過", status == "uncovered"))
    checks.append(("延後訊息列出理由", "契約快照格式" in msg))
    checks.append(("延後不得寫成通過", not any(a in msg for a in AFFIRMATIVE)))

    chg_empty = chg.replace("- defer: 需先決定契約快照格式", "- defer:")
    status, msg = PR.run_gate(".", chg_empty, {"api-contract": kinds["api-contract"]},
                              ["library"], True)
    checks.append(("空延後被擋", status == "halt"))
    # 要擋在「空延後」這條路上,不是滑到「未指定 cmd」——訊息不同,人看到的指引也不同
    checks.append(("空延後的擋下理由正確", "空延後與沒宣告等價" in msg))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t2_license(checks)
    t4_repro(checks)
    t6_defer(checks)

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
