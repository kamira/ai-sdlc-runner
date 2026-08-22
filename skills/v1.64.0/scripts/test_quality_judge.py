#!/usr/bin/env python3
"""委派驗證產物判讀的單元斷言(CHG-20260804-01)。

這一層存在的理由是實作讀出來的:`run_gate` 以退出碼判生死 → mypy 在本 repo 有
72 個發現 → 閘從第一天就紅;改看產物存在則等於沒判——一份塞滿錯誤的報告
照樣「存在且非空」。恆紅與恆綠一樣等於沒有訊號。

所以判讀的單位是**相對基線的差集**:既有的入基線(具名理由),新增的一律擋,
而基線只准往下。

Run: python3 test_quality_judge.py → exit 0 全過,1 有失敗。
"""
import json
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import quality_judge as QJ    # noqa: E402


def _mypy_line(file="a.py", line=10, code="attr-defined", msg="x has no attribute y"):
    return json.dumps({"file": file, "line": line, "column": 1, "message": msg,
                       "code": code, "severity": "error"}, ensure_ascii=False)


def _bandit(sev="HIGH", conf="HIGH", test_id="B602", filename="a.py",
            text="subprocess with shell=True"):
    return json.dumps({"results": [{"filename": filename, "test_id": test_id,
                                    "issue_text": text, "issue_severity": sev,
                                    "issue_confidence": conf, "line_number": 3}]})


def _baseline(findings=None, coverage=None):
    return {"findings": findings or {}, "coverage": coverage or {}}


def t1_fingerprint(checks):
    """T1:指紋不含行號,但認得出檔案、規則與訊息。"""
    base = {"kind": "typecheck", "rule": "attr-defined", "file": "a.py", "message": "boom"}
    same_line = dict(base)          # 行號根本不在指紋輸入裡
    checks.append(("只有行號不同 → 指紋相同",
                   QJ.fingerprint(base) == QJ.fingerprint(same_line)))
    for field, val, name in (("file", "b.py", "檔案"), ("rule", "arg-type", "規則碼"),
                             ("message", "other", "訊息")):
        other = dict(base, **{field: val})
        checks.append((f"{name}不同 → 指紋不同",
                       QJ.fingerprint(base) != QJ.fingerprint(other)))
    # Windows 路徑分隔符不該產生不同指紋(同一個檔案兩種寫法)
    checks.append(("路徑分隔符不影響指紋",
                   QJ.fingerprint(dict(base, file="x/a.py"))
                   == QJ.fingerprint(dict(base, file="x\\a.py"))))


def t1b_baseline(checks):
    """T1:基線每條都要有理由;壞檔案要回報而不是照跑。"""
    d = Path(tempfile.mkdtemp())
    good = d / "good.json"
    good.write_text(json.dumps({"findings": {"abc": {"reason": "誤報:短路後 narrow 不到"}},
                                "coverage": {"total": 73}}), encoding="utf-8")
    b, err = QJ.load_baseline(good)
    checks.append(("合法基線載入成功", err is None and "abc" in b["findings"]))

    bad = d / "bad.json"
    bad.write_text(json.dumps({"findings": {"abc": {"reason": "   "}}}), encoding="utf-8")
    b, err = QJ.load_baseline(bad)
    checks.append(("無理由的基線被拒絕", err is not None))
    checks.append(("拒絕訊息說明豁免要署名", "署名" in (err or "")))

    broken = d / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    b, err = QJ.load_baseline(broken)
    checks.append(("壞掉的基線回報而非照跑", err is not None))

    b, err = QJ.load_baseline(d / "nope.json")
    checks.append(("基線不存在時視為空基線", err is None and b["findings"] == {}))


def t2_t3_t4_parsers(checks):
    """T2-T4:三個發現型工具的解析。"""
    fs, err = QJ.parse_mypy(_mypy_line() + "\n" + _mypy_line(file="b.py"))
    checks.append(("mypy 解析出兩筆", err is None and len(fs) == 2))
    checks.append(("mypy 取到錯誤碼", fs and fs[0]["rule"] == "attr-defined"))
    fs, err = QJ.parse_mypy("")
    checks.append(("mypy 空產物回空清單", err is None and fs == []))
    # 非 JSON 的雜訊行(mypy 會混印摘要)略過;但**看起來像 JSON 卻壞掉**的要回報,
    # 因為那是產物損毀,而看不懂的報告不等於沒問題(KN-004)
    fs, err = QJ.parse_mypy("Success: no issues found in 44 source files\n\n")
    checks.append(("mypy 的非 JSON 摘要行略過", err is None and fs == []))
    fs, err = QJ.parse_mypy('{"file": "a.py", ')
    checks.append(("mypy 壞 JSON 回報而非崩潰", err is not None))
    # note 級別不是 error,不該被當成發現
    fs, _ = QJ.parse_mypy(json.dumps({"file": "a.py", "message": "note", "code": "n",
                                      "severity": "note"}))
    checks.append(("mypy 的 note 不算發現", fs == []))

    fs, err = QJ.parse_bandit(_bandit())
    checks.append(("bandit 解析出一筆", err is None and len(fs) == 1))
    checks.append(("bandit 取到嚴重度與信心",
                   fs and fs[0]["severity"] == "HIGH" and fs[0]["confidence"] == "HIGH"))
    fs, err = QJ.parse_bandit("不是 JSON")
    checks.append(("bandit 壞 JSON 回報", err is not None))

    pa = json.dumps({"dependencies": [{"name": "foo", "version": "1.0",
                                       "vulns": [{"id": "GHSA-xxxx", "description": "RCE"}]}]})
    fs, err = QJ.parse_pip_audit(pa)
    checks.append(("pip-audit 解析出漏洞", err is None and len(fs) == 1))
    checks.append(("pip-audit 記下套件與版本", fs and "foo==1.0" in fs[0]["file"]))
    checks.append(("CVE 預設為可擋等級", fs and QJ.blocking(fs[0])))
    fs, err = QJ.parse_pip_audit(json.dumps({"dependencies": []}))
    checks.append(("pip-audit 無漏洞回空清單", err is None and fs == []))


def t3_grading(checks):
    """T3:severity × confidence 分級。"""
    for sev, conf, want in (("HIGH", "HIGH", False), ("MEDIUM", "HIGH", False),
                            ("LOW", "HIGH", True), ("HIGH", "LOW", True)):
        ok, msg, _ = QJ.judge("sast", _bandit(sev=sev, conf=conf), _baseline())
        checks.append((f"bandit[{sev}/{conf}] → {'放行' if want else '擋下'}", ok is want))
    # 放行的也要被列出——不擋不等於不說
    ok, msg, _ = QJ.judge("sast", _bandit(sev="LOW", conf="HIGH"), _baseline())
    checks.append(("未達門檻者仍被列出", "B602" in msg))
    checks.append(("訊息說明為何不擋", "噪音" in msg))


def t5_coverage(checks):
    """T5:覆蓋率棘輪。"""
    base = _baseline(coverage={"total": 73})
    for pct, want in ((80, True), (73, True), (72, False)):
        ok, msg, _ = QJ.judge("coverage", json.dumps({"totals": {"percent_covered": pct}}), base)
        checks.append((f"覆蓋率 {pct} → {'放行' if want else '擋下'}", ok is want))
    ok, msg, _ = QJ.judge("coverage", json.dumps({"totals": {"percent_covered": 60}}), base)
    checks.append(("下降時給出前後數字", "73.0%" in msg and "60.0%" in msg))
    ok, msg, _ = QJ.judge("coverage", json.dumps({"totals": {"percent_covered": 80}}), base)
    checks.append(("上升時提示可更新基線", "更新基線" in msg))
    ok, msg, _ = QJ.judge("coverage", "不是 JSON", base)
    checks.append(("壞產物擋下", not ok))
    checks.append(("壞產物不得聲稱通過", "通過" not in msg))
    ok, msg, _ = QJ.judge("coverage", json.dumps({"totals": {}}), base)
    checks.append(("缺欄位擋下", not ok))
    # 量測抖動的容忍帶:四捨五入會讓基線高於實測值,下一次一模一樣的跑就會被擋
    ok, _, _ = QJ.judge("coverage", json.dumps({"totals": {"percent_covered": 72.97}}), base)
    checks.append(("容忍帶內的微幅波動放行", ok))
    ok, _, _ = QJ.judge("coverage", json.dumps({"totals": {"percent_covered": 72.9}}), base)
    checks.append(("超出容忍帶的下降仍擋下", not ok))


def t5b_coverage_lines(checks):
    """T5b:整數行數棘輪(CHG-20260811-03,兩席交叉比對後的規則 1)。

    為什麼要有這一層:基線 85.92 對實測 85.9202%,餘裕 0.0002 個百分點——
    **那個懸崖是把連續量壓成兩位數百分比製造出來的**,不是真的風險。
    處理它的直覺做法(加緩衝)只是把懸崖搬到另一個任意位置;比整數對就沒有懸崖。

    這些不是為了讓覆蓋率數字好看而寫的測試——被測的是**決定要不要擋下合併的
    判斷邏輯本身**,而它判錯的兩個方向都很貴(誤擋會讓人想關掉閘,誤放會讓
    未測程式入庫)。
    """
    def art(c, s):
        return json.dumps({"totals": {"covered_lines": c, "num_statements": s,
                                      "percent_covered": 100 * c / s}})

    base = _baseline(coverage={"total": 85.92, "covered": 6200, "statements": 7216})

    ok, msg, det = QJ.judge("coverage", art(6200, 7216), base)
    checks.append(("同比值放行", ok))
    checks.append(("同比值訊息給整數對", "6200/7216" in msg))
    checks.append(("detail 帶整數行數", det.get("covered") == 6200
                   and det.get("statements") == 7216))

    ok, _, _ = QJ.judge("coverage", art(6201, 7216), base)
    checks.append(("多一行覆蓋 → 放行", ok))
    ok, msg, _ = QJ.judge("coverage", art(6199, 7216), base)
    checks.append(("少一行覆蓋 → 擋下", not ok))
    checks.append(("擋下時給出兩組整數對", "6200/7216" in msg and "6199/7216" in msg))

    # **零容差是刻意的,而代價要寫明**:普通的重構刪碼只要比值掉一點點就會擋,
    # 逃生口是連理由更新基線。這一條釘住那個行為,免得日後有人以為是 bug。
    ok, msg, _ = QJ.judge("coverage", art(6028, 7016), base)
    checks.append(("重構刪碼使比值微降 → 仍擋下(零容差)", not ok))
    checks.append(("分母變化要印出來(不得藏在百分比裡)", "7216 → 7016" in msg))

    # 刪掉未覆蓋的行會把比值推高——這一格**放行是對的**(未測程式真的變少了),
    # 但分母的變化同樣要看得見,否則「靠刪程式達標」會沒有痕跡。
    ok, msg, _ = QJ.judge("coverage", art(6200, 7016), base)
    checks.append(("刪掉未覆蓋行 → 放行", ok))
    checks.append(("放行時分母變化仍具名", "-200" in msg))

    # 降級路徑:舊基線沒有整數 → 退回百分比,而且**要講出來**。
    old = _baseline(coverage={"total": 73})
    ok, msg, _ = QJ.judge("coverage", art(7300, 10000), old)
    checks.append(("舊基線退回百分比判定", ok))
    checks.append(("降級要具名,不得靜靜換判法", "降級判定" in msg))

    # 產物少了整數欄位 → 同樣降級,而不是崩潰或誤判。
    ok, msg, _ = QJ.judge("coverage", json.dumps({"totals": {"percent_covered": 90}}), base)
    checks.append(("產物缺整數欄位 → 降級而非崩潰", ok and "降級判定" in msg))

    got, err = QJ.parse_coverage_lines(json.dumps({"totals": {"covered_lines": 1,
                                                              "num_statements": 0}}))
    checks.append(("分母為 0 → 回錯誤而不是除以零", got is None and err is not None))
    got, err = QJ.parse_coverage_lines("不是 JSON")
    checks.append(("壞產物 → 回錯誤", got is None and err is not None))


def t6_judge(checks):
    """T6:基線差集——既有放行、新增擋下、消失提示。"""
    art = _mypy_line()
    fp = QJ.fingerprint({"kind": "typecheck", "rule": "attr-defined", "file": "a.py",
                         "message": "x has no attribute y"})

    ok, msg, d = QJ.judge("typecheck", art, _baseline())
    checks.append(("不在基線內 → 擋下", not ok))
    checks.append(("訊息標明是新增項", "新增發現" in msg))
    checks.append(("訊息給出指紋供寫入基線", fp in msg))

    base = _baseline({fp: {"reason": "誤報:短路後 mypy narrow 不到", "kind": "typecheck"}})
    ok, msg, d = QJ.judge("typecheck", art, base)
    checks.append(("在基線內 → 放行", ok))
    checks.append(("列出該條的理由", "narrow 不到" in msg))

    # 基線只准往下:發現消失時要提示移除
    ok, msg, d = QJ.judge("typecheck", "", base)
    checks.append(("消失項仍放行", ok))
    checks.append(("消失項有提示移除", "已不存在" in msg and "只准往下" in msg))

    # 行號變了不該變成新發現
    ok, msg, _ = QJ.judge("typecheck", _mypy_line(line=999), base)
    checks.append(("行號改變不會變成新發現", ok))

    # 沒有判讀器的種類:回退而不是誤判
    ok, msg, _ = QJ.judge("unknown-kind", "{}", _baseline())
    checks.append(("未知種類回退為既有處置", ok and "回退" in msg))
    checks.append(("JUDGED_KINDS 四類齊全",
                   set(QJ.JUDGED_KINDS) == {"typecheck", "sast",
                                            "dependency-audit", "coverage"}))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t1_fingerprint(checks)
    t1b_baseline(checks)
    t2_t3_t4_parsers(checks)
    t3_grading(checks)
    t5_coverage(checks)
    t5b_coverage_lines(checks)
    t6_judge(checks)

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
