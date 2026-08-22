#!/usr/bin/env python3
"""程式碼審查面板的單元斷言(CHG-20260803-09)。

runner 早就會印「未給 --review-cmd:施工與審查為同模型(共享盲點)」——
它說出了問題卻沒有機制解決,而說出來卻不處理的警語,久了就是背景噪音。

本檔驗的是那個機制:座位、否決權、信心降級。最要緊的一條來自治理層的
review-panel——「分歧是調和或升級,**絕不平均**」——所以信心分數只能濾掉
沒把握的票,不能拿來加權出一個結論。

Run: python3 test_review_panel.py → exit 0 全過,1 有失敗。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import panel as PA    # noqa: E402

OLD_PASS = "[task-review] T1 | spec: pass | quality: pass | ok"
OLD_FAIL = "[task-review] T1 | spec: fail | quality: pass | 介面不符"
OLD_CV = "[task-review] T1 | spec: cannot-verify | quality: pass | diff 看不出"
NEW_FULL = "[task-review] T1 | defect | opus | spec: pass | quality: pass | conf: 90 | ok"
BRANCH = "[task-review] branch | spec: pass | quality: pass | ok"


def t1_parse(checks):
    """T1:新舊格式都解析得出來;缺欄位不臆造。"""
    for name, line, spec in (("舊 pass", OLD_PASS, "pass"),
                             ("舊 fail", OLD_FAIL, "fail"),
                             ("舊 cannot-verify", OLD_CV, "cannot-verify"),
                             ("新完整格式", NEW_FULL, "pass")):
        v = PA.parse_verdict(line)
        checks.append((f"解析成功[{name}]", v is not None))
        checks.append((f"spec 正確[{name}]", v and v["spec"] == spec))

    checks.append(("branch 判定行也解析得出", PA.parse_verdict(BRANCH) is not None))

    v = PA.parse_verdict(NEW_FULL)
    checks.append(("取得座位", v and v["seat"] == "defect"))
    checks.append(("取得模型", v and v["model"] == "opus"))
    checks.append(("取得信心", v and v["confidence"] == 90))

    # 舊格式沒有信心欄位——**不得臆造分數**,否則降級規則會建立在虛構的數字上
    v = PA.parse_verdict(OLD_PASS)
    checks.append(("舊格式信心為 None(不臆造)", v and v["confidence"] is None))
    checks.append(("舊格式座位為 None", v and v["seat"] is None))

    # 理由欄不得被誤讀成座位(位置欄只取 spec: 之前的)
    checks.append(("理由不會被誤讀為座位",
                   PA.parse_verdict(OLD_FAIL)["seat"] is None))

    # 壞輸入:回 None 而不是崩潰
    for bad in ("", "看起來還行", "[task-review] T1 | spec: pass", None):
        try:
            checks.append((f"壞輸入回 None[{str(bad)[:16]}]", PA.parse_verdict(bad) is None))
        except Exception:
            checks.append((f"壞輸入回 None[{str(bad)[:16]}]", False))


RUNNER = Path(__file__).with_name("autopilot_runner.py")
PY = f'"{sys.executable}"'

CHG_TMPL = """# CHG-20260101-05 — fixture:審查面板

- 風險分級:{risk} | 實作者:fixture agent

### Global Constraints
- 一律以 stdlib 實作

### Tasks
- [ ] T1. 寫一個 add
  - interfaces: consumes 兩數 / produces 和
  - test: 測試指令全綠

### Acceptance operation
- operate: 跑一次
- observe: 輸出
- pass: 正確

## 狀態
開單
"""

AGENT = '''
import pathlib
pathlib.Path("addmod.py").write_text("def add(a, b):\\n    return a + b\\n", encoding="utf-8")
pathlib.Path("test_addmod.py").write_text(
    "from addmod import add\\n"
    "def test_a():\\n    assert add(1, 2) == 3\\n"
    "def test_b():\\n    assert add(-1, 1) == 0\\n"
    "def test_c():\\n    assert add(0, 0) == 0\\n", encoding="utf-8")
print("agent wrote addmod")
'''

# 假座位:從 brief 讀出自己是哪一席,再依 verdicts 表回對應的判定行
SEAT_STUB = r'''
import json, pathlib, re, sys
# 釘住輸出編碼:這支 stub 會被 runner 以管線接走,而 Windows 主控台的預設編碼
# 吃不下非 ASCII——沒有這三行,判定行印不出來,面板會看成「全席無法判定」。
# 本 repo 每個測試檔開頭都有同樣的前言,fixture 也一樣需要。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
brief = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r"\*\*([a-z]+)\*\*", brief)
seat = m.group(1) if m else "single"
table = json.loads(pathlib.Path(__file__).with_name("_verdicts.json").read_text(encoding="utf-8"))
spec, conf = table.get(seat, ["pass", 95])
print(f"[seat] {seat}")
print(f"[task-review] T1 | {seat} | stub-model | spec: {spec} | quality: pass | conf: {conf} | ok")
'''


def _panel_repo(risk="中", verdicts=None):
    d = Path(tempfile.mkdtemp())
    (d / "CHG-20260101-05.md").write_text(CHG_TMPL.format(risk=risk), encoding="utf-8")
    (d / "_agent.py").write_text(AGENT, encoding="utf-8")
    (d / "_seat.py").write_text(SEAT_STUB, encoding="utf-8")
    # 測試指令寫成檔案而非 `python -c "..."`:內層雙引號在 cmd.exe 下會被吃掉。
    # 這個陷阱 test_e2e_build_gates.py 的註解裡記過一次,這裡又踩了一次。
    (d / "_runtests.py").write_text("import test_addmod\n", encoding="utf-8")
    table = {"conformance": ["pass", 95], "defect": ["pass", 95], "idiom": ["pass", 95],
             "single": ["pass", 95]}
    for k, v in (verdicts or {}).items():
        table[k] = [v[0], v[1]]
    (d / "_verdicts.json").write_text(json.dumps(table), encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=f", "-c", "user.email=f@e.com",
                  "commit", "-q", "-m", "CHG-20260101-05: fixture"]):
        subprocess.run(["git", *args], cwd=str(d), capture_output=True)
    return d


def _run_build(d, *extra):
    cmd = [sys.executable, str(RUNNER), "build", "--chg", str(d / "CHG-20260101-05.md"),
           "--repo", str(d), "--agent-cmd", f'{PY} "{d / "_agent.py"}"' + " {brief}",
           "--review-cmd", f'{PY} "{d / "_seat.py"}"' + " {brief}",
           "--test-cmd", f'{PY} "{d / "_runtests.py"}"',
           "--max-fix-rounds", "1", "--no-mutation", "--flaky-runs", "1",
           "--confirmed", "--no-commit", *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _v(seat, spec="pass", quality="pass", conf=90, model="m"):
    return {"target": "T1", "seat": seat, "model": model, "spec": spec,
            "quality": quality, "confidence": conf,
            "line": f"[task-review] T1 | {seat} | {model} | spec: {spec} | "
                    f"quality: {quality} | conf: {conf} | 理由"}


def t2_t3_seats(checks):
    """T2/T3:座位表與「只給自己那一列」的簡報。"""
    seats = PA.load_seats()
    checks.append(("三席齊全", set(seats) == {"conformance", "defect", "idiom"}))
    for name, spec in seats.items():
        checks.append((f"座位[{name}] 有非空 question", bool(spec.get("question", "").strip())))
        checks.append((f"座位[{name}] 有證據要求", bool(spec.get("evidence", "").strip())))
    checks.append(("只有 spec 席有否決權",
                   seats["conformance"].get("veto") is True
                   and not seats["defect"].get("veto")
                   and not seats["idiom"].get("veto")))

    chg = "### Global Constraints\n- 一律 stdlib\n\n### Tasks\n- [ ] T1. 甲\n"
    brief = PA.seat_brief(chg, {"tid": "T1", "title": "甲"}, "defect")
    checks.append(("簡報含自己的職責", "邊界值" in brief))
    checks.append(("簡報含自己的座位名", "defect" in brief))
    # panel view 屬於 dispatcher:給了整張表,座位就會開始揣測別人會怎麼投
    checks.append(("簡報不含其他座位的名稱",
                   "idiom" not in brief and "規格合規" not in brief))
    checks.append(("簡報要求引用證據", "file:line" in brief))
    checks.append(("簡報明講沒把握就給低分是正當結果", "不是失敗" in brief))
    checks.append(("簡報含全域約束", "一律 stdlib" in brief))


def t4_downgrade(checks):
    """T4:信心低於門檻 → 降級為 cannot-verify(不是扣分,更不是平均)。"""
    for conf, want in ((90, "pass"), (80, "pass"), (79, "cannot-verify"), (0, "cannot-verify")):
        g, note = PA.downgrade(_v("defect", conf=conf))
        checks.append((f"信心 {conf} → {want}", g["spec"] == want))
    g, note = PA.downgrade(_v("defect", conf=79))
    checks.append(("降級有註記", bool(note) and "79" in note))
    checks.append(("降級註記說明沒把握的綠燈不算綠燈", "不算綠燈" in (note or "")))

    # 舊格式沒有信心欄位:不降級,但註明未提供——不臆造分數
    g, note = PA.downgrade(_v("defect", conf=None))
    checks.append(("無信心欄位不降級", g["spec"] == "pass"))
    checks.append(("無信心欄位有註明", bool(note) and "未提供" in note))

    # 反對票同樣適用降級:沒把握的紅燈也不算紅燈
    g, _ = PA.downgrade(_v("defect", spec="fail", conf=20))
    checks.append(("低信心的反對票也被降級", g["spec"] == "cannot-verify"))


def t5_adjudicate(checks):
    """T5:否決、全體無法判定、以及「絕不平均」。"""
    cases = [
        ("三席全 pass", [_v("conformance"), _v("defect"), _v("idiom")], True),
        ("一席 spec fail、其餘 pass",
         [_v("conformance", spec="fail"), _v("defect"), _v("idiom")], False),
        ("一席 quality fail、其餘 pass",
         [_v("conformance"), _v("defect", quality="fail"), _v("idiom")], False),
        ("全席 cannot-verify",
         [_v("conformance", spec="cannot-verify"), _v("defect", spec="cannot-verify"),
          _v("idiom", spec="cannot-verify")], False),
        ("兩席 pass、一席 cannot-verify",
         [_v("conformance"), _v("defect"), _v("idiom", spec="cannot-verify")], True),
    ]
    for name, vs, want in cases:
        ok, _msg = PA.adjudicate(vs)
        checks.append((f"裁決[{name}] → {'放行' if want else '擋下'}", ok is want))

    # 這一條就是「絕不平均」的實質:平均的話兩票 pass 會蓋過一票 fail
    ok, msg = PA.adjudicate([_v("conformance", spec="fail"), _v("defect"), _v("idiom")])
    checks.append(("否決訊息點名該席", (not ok) and "conformance" in msg))
    checks.append(("否決訊息說明不得被推翻", "不得" in msg))

    ok, msg = PA.adjudicate([_v("conformance", spec="cannot-verify"),
                             _v("defect", spec="cannot-verify"),
                             _v("idiom", spec="cannot-verify")])
    checks.append(("全體無法判定時說明那不等於沒問題", "不等於" in msg))

    # 沒把握的反對票被降級,因此不成立為否決
    ok, msg = PA.adjudicate([_v("conformance", spec="fail", conf=20), _v("defect"), _v("idiom")])
    checks.append(("低信心的反對不構成否決", ok))
    checks.append(("但降級有留下紀錄", "降級" in msg))

    # 沒有任何判定行 = 沒有輸出,不算通過(沿用 CHG-20260803-02 T6 的處置)
    ok, msg = PA.adjudicate([])
    checks.append(("無判定行不算通過", not ok))


def t6_seats_for(checks):
    """T6:風險分級決定席次;覆寫不得低於下限。"""
    seats = PA.load_seats()
    for risk, want in (("low", 1), ("medium", 3), ("high", 3)):
        got, _ = PA.seats_for(risk, seats=seats)
        checks.append((f"{risk} 風險開 {want} 席", len(got) == want))
    got, _ = PA.seats_for("low", seats=seats)
    checks.append(("低風險開的是 conformance 席(最不可協商的排最前)", got == ["conformance"]))

    got, note = PA.seats_for("high", override=1, seats=seats)
    checks.append(("覆寫不得低於分級下限", len(got) == 3))
    checks.append(("被提升時要說明理由", bool(note) and "下限" in note))
    got, note = PA.seats_for("low", override=3, seats=seats)
    checks.append(("往上加席可以", len(got) == 3 and note is None))
    got, _ = PA.seats_for("低", seats=seats)
    checks.append(("未知風險字串退回最保守的 1 席", len(got) == 1))


def t7_cross(checks):
    """T7:交叉讀——分歧升級,不平均。"""
    cs = PA.parse_cross("[cross] conformance→defect | agree | 同意\n"
                        "[cross] defect->idiom | disagree | 我認為邊界沒處理")
    checks.append(("解析出兩條旗標", len(cs) == 2))
    checks.append(("箭頭兩種寫法都認", cs[0]["to"] == "defect" and cs[1]["to"] == "idiom"))
    checks.append(("agree/disagree 判讀正確", cs[0]["agree"] and not cs[1]["agree"]))
    checks.append(("壞輸入回空清單", PA.parse_cross("沒有旗標") == []))

    ok, msg = PA.adjudicate_cross(cs)
    checks.append(("有分歧即擋下", not ok))
    checks.append(("點名分歧雙方", "defect" in msg and "idiom" in msg))
    checks.append(("說明分歧是升級不是平均", "絕不平均" in msg))
    ok, _ = PA.adjudicate_cross([c for c in cs if c["agree"]])
    checks.append(("無分歧則放行", ok))

    brief = PA.cross_brief([_v("conformance"), _v("defect"), _v("idiom")], "defect")
    checks.append(("交叉簡報含其他席的判定", "conformance" in brief and "idiom" in brief))
    checks.append(("交叉簡報不含自己的判定行", brief.count("| defect |") == 0))
    checks.append(("交叉簡報明講不要為一致而讓步", "讓步" in brief))


def t8_wiring(checks):
    """T8:面板真的接在 build 上,且低風險維持單席快速路徑。"""
    d = _panel_repo(risk="中")
    rc, out = _run_build(d)
    checks.append(("中風險開三席", out.count("[seat]") == 3 or out.count("seat=") == 3
                   or "3/3 席" in out))
    checks.append(("中風險整體放行", rc == 0))

    # 一席 spec fail → 否決,即使其餘兩席 pass
    d2 = _panel_repo(risk="中", verdicts={"conformance": ("fail", 95)})
    rc2, out2 = _run_build(d2)
    checks.append(("一席 spec fail 即被否決", rc2 == 3 and "否決" in out2))
    checks.append(("否決訊息點名該席", "conformance 判 spec: fail" in out2))

    # 全席低信心 → 全體降級為無法判定 → 擋下
    d3 = _panel_repo(risk="中", verdicts={"conformance": ("pass", 50), "defect": ("pass", 50),
                                          "idiom": ("pass", 50)})
    rc3, out3 = _run_build(d3)
    checks.append(("全席低信心 → 擋下", rc3 == 3))
    checks.append(("訊息說明無法判定不等於沒問題", "不等於" in out3))

    # 低風險:單席快速路徑,且不印面板警語
    d4 = _panel_repo(risk="低")
    rc4, out4 = _run_build(d4)
    checks.append(("低風險整體放行", rc4 == 0))
    checks.append(("低風險不開面板(無同模型警語)", "同模型面板" not in out4))

    # 未逐席指定指令 → 同模型警語出現且只出現一次
    checks.append(("中風險印出同模型警語", "同模型面板" in out))
    checks.append(("同模型警語只印一次", out.count("同模型面板") == 1))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t1_parse(checks)
    t2_t3_seats(checks)
    t4_downgrade(checks)
    t5_adjudicate(checks)
    t6_seats_for(checks)
    t7_cross(checks)
    t8_wiring(checks)

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
