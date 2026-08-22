#!/usr/bin/env python3
"""autopilot lib(plan / policy / exec_util)的單元斷言(CHG-20260803-01 T9)。

三個模組都是 runner 的**決策核心**且不含 LLM——輸入決定輸出,適合逐格斷言:
  plan.py    計畫格式閘:過不了的計畫永遠不會開跑
  policy.py  風險 × 階段矩陣 + 永久停點 + Autonomy 只縮不放
  exec_util  退出碼訊息、簡報組裝、live handshake 落盤

Run: python3 test_lib_units.py → exit 0 全過,1 有失敗。
"""
import json
import sys
import pathlib
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import plan as P          # noqa: E402
from lib import policy as POL      # noqa: E402
from lib import exec_util as EU    # noqa: E402

GOOD = """### Global Constraints
- 一律 X

### Tasks
- [ ] T1. 甲
  - interfaces: consumes a / produces b
  - test: pytest -q
- [x] T2. 乙
  - interfaces: consumes b / produces c
  - test: 可斷言條件

### Acceptance operation
- operate: run
- observe: out
- pass: ok
"""


def main() -> int:
    REPO_ROOT = Path(__file__).resolve().parents[3]
    checks = []

    def eq(name, got, want):
        checks.append((f"{name}(得 {got!r})", got == want))

    # ---------- plan.py:四條格式規則各正反 ----------
    probs, tasks = P.parse_tasks(GOOD)
    checks.append(("合格計畫無問題", probs == []))
    eq("解析出 2 個 task", len(tasks), 2)
    eq("T2 已勾", tasks[1]["ticked"], True)
    eq("T1 未勾", tasks[0]["ticked"], False)

    probs, _ = P.parse_tasks(GOOD.replace("### Global Constraints", "### 全域約束"))
    checks.append(("缺 Global Constraints → 報問題",
                   any("Global Constraints" in p for p in probs)))

    probs, _ = P.parse_tasks(GOOD.replace("  - interfaces: consumes a / produces b\n", ""))
    checks.append(("task 缺 interfaces → 報問題", any("interfaces" in p for p in probs)))

    probs, _ = P.parse_tasks(GOOD.replace("  - test: pytest -q\n", ""))
    checks.append(("task 缺 test → 報問題", any("test" in p for p in probs)))

    probs, _ = P.parse_tasks(GOOD.replace("- [x] T2.", "- [x] T3."))
    checks.append(("task 編號不連續 → 報問題", any("連續" in p for p in probs)))

    probs, _ = P.parse_tasks("### Global Constraints\n- x\n\n### Tasks\n(無)\n")
    checks.append(("完全沒有 task → 報問題", any("找不到任何 task" in p for p in probs)))

    # risk_of:未知/缺值一律保守判 high
    eq("risk 低 → low", P.risk_of("- 風險分級:低"), "low")
    eq("risk 中 → medium", P.risk_of("- Risk: 中"), "medium")
    eq("risk 高 → high", P.risk_of("- Risk: high"), "high")
    eq("查無 risk → high(保守)", P.risk_of("(沒有風險欄)"), "high")

    # chg_id_of
    eq("抓得到 CHG 編號", P.chg_id_of("blah CHG-20260803-01 blah"), "CHG-20260803-01")
    eq("抓不到時用 fallback", P.chg_id_of("nothing", fallback="?"), "?")

    # tick_task:冪等,且只動指定的那一行
    d = Path(tempfile.mkdtemp())
    f = d / "CHG.md"
    f.write_text(GOOD, encoding="utf-8")
    P.tick_task(f, "T1")
    t1 = f.read_text(encoding="utf-8")
    checks.append(("tick_task 勾上 T1", "- [x] T1." in t1))
    checks.append(("tick_task 不動其他 task", t1.count("- [x]") == 2))
    P.tick_task(f, "T1")
    checks.append(("tick_task 冪等(重複勾不變)", f.read_text(encoding="utf-8") == t1))
    # 行結構必須完整保留:若 splitlines 沒帶 keepends,重組後整份檔會被壓成一行,
    # 而「內容仍找得到 - [x] T1.」這種寬鬆斷言抓不到(變異測試存活點 boolconst@L79)。
    eq("tick_task 保留行數", len(t1.splitlines()), len(GOOD.splitlines()))
    checks.append(("tick_task 保留換行(未被壓成一行)", t1.count("\n") >= 12))

    # 子行判定必須「縮排 AND 以 - 開頭」兩者皆成立。
    # 若誤成 OR,一個**未縮排**的 `- interfaces:` 也會被算進去——task 就能靠
    # 同層級的散文條列蒙混過關(變異測試存活點 boolop@L58)。
    NO_INDENT = """### Global Constraints
- 一律 X

### Tasks
- [ ] T1. 甲
- interfaces: consumes a / produces b
- test: pytest -q
"""
    probs, _ = P.parse_tasks(NO_INDENT)
    checks.append(("未縮排的 interfaces/test 不算子行(縮排與 - 必須同時成立)",
                   any("interfaces" in p for p in probs) and any("test" in p for p in probs)))

    # 判定行 regex:三種 spec 值 × 兩種 quality 值
    for spec in ("pass", "fail", "cannot-verify"):
        for q in ("pass", "fail"):
            line = f"[task-review] T1 | spec: {spec} | quality: {q} | 理由"
            checks.append((f"判定行可解析 spec={spec}/quality={q}",
                           P.VERDICT_RE.search(line) is not None))
    checks.append(("非判定行不得誤配",
                   P.VERDICT_RE.search("task review 看起來 ok") is None))

    # docs-only 標記與 Acceptance operation 節
    checks.append(("偵測 Acceptance operation 節", P.AOP_RE.search(GOOD) is not None))
    checks.append(("偵測 docs-only 標記",
                   P.DOCS_ONLY_RE.search("Acceptance-operation: n/a (docs-only)") is not None))
    checks.append(("永久停點標記可抓出",
                   P.PERM_RE.findall("- permanent-halt: payments") == ["payments"]))

    # ---------- policy.py:風險 × 階段全格 ----------
    # 期望值**硬編碼**在測試裡,不從 DEFAULT_POLICY 讀回來。
    # 自我參照的斷言(拿 DEFAULT_POLICY 驗 DEFAULT_POLICY)恆真:矩陣被改成什麼都會過,
    # 而字串值不在變異算子的射程內,所以連變異測試也照不到。這一格必須有外部期望值。
    EXPECTED_MATRIX = {
        "low":    {"confirm_gate": "auto",    "task_review": "auto", "operational_verify": "auto",
                   "acceptance": "auto",             "pr": "auto", "merge": "auto"},
        "medium": {"confirm_gate": "confirm", "task_review": "auto", "operational_verify": "auto",
                   "acceptance": "auto",             "pr": "auto", "merge": "halt"},
        "high":   {"confirm_gate": "halt",    "task_review": "auto", "operational_verify": "halt",
                   "acceptance": "halt_independent", "pr": "auto", "merge": "halt"},
    }
    m = POL.load_policy(None)
    for risk, row in EXPECTED_MATRIX.items():
        for stage, want in row.items():
            eq(f"矩陣 {risk}/{stage}", POL.stage_action(m, risk, stage, ""), want)
    checks.append(("內建矩陣與期望值完全一致(18 格無遺漏)",
                   POL.DEFAULT_POLICY == EXPECTED_MATRIX))
    # drive 層不得比治理層寬鬆:merge 閘逐風險比對治理層的 halt_policy.json
    # (兩層自 CHG-20260804-08 起同在一支 skill,但**契約仍是兩份**——
    #  合併的是封裝,不是責任;這條跨層斷言因此照舊成立)
    gov = json.loads((Path(__file__).resolve().parents[1] / "assets" / "halt_policy.json").read_text(encoding="utf-8-sig"))["gates"]
    looser = [r for r in ("low", "medium", "high")
              if gov["before_merge_or_release"][r] == "halt"
              and EXPECTED_MATRIX[r]["merge"] == "auto"]
    checks.append(("merge 閘不比 ai-sdlc 寬鬆(drive 層只准加嚴)", not looser))
    # 未知風險 → 落到 high 那一列(最嚴),不得放行
    eq("未知風險落到 high 列", POL.stage_action(m, "unknown", "merge", ""), "halt")
    eq("未知階段 → halt", POL.stage_action(m, "low", "no_such_stage", ""), "halt")
    # Autonomy 只縮不放:CHG 寫 halt 時,低風險的 confirm_gate/merge 也要變 halt
    chg_halt = "- Autonomy: halt\n"
    eq("Autonomy halt 加嚴 confirm_gate", POL.stage_action(m, "low", "confirm_gate", chg_halt), "halt")
    eq("Autonomy halt 加嚴 merge", POL.stage_action(m, "low", "merge", chg_halt), "halt")
    eq("Autonomy 不影響其他階段", POL.stage_action(m, "low", "task_review", chg_halt), "auto")
    # 永久停點清單不可被設定檔縮減
    d2 = Path(tempfile.mkdtemp())
    shrink = d2 / "shrink.json"
    shrink.write_text(json.dumps({"permanent_halts": ["payments"]}), encoding="utf-8")
    try:
        POL.load_policy(str(shrink))
        ok = False
    except ValueError:
        ok = True
    checks.append(("設定檔縮減 permanent_halts → 拒絕載入", ok))
    # 值域錯誤要 fail-loud
    bad = d2 / "bad.json"
    bad.write_text(json.dumps({"defaults": {"low": {"merge": "maybe"}}}), encoding="utf-8")
    try:
        POL.load_policy(str(bad))
        ok = False
    except ValueError:
        ok = True
    checks.append(("值域外的 action → 拒絕載入(fail-loud)", ok))
    checks.append(("永久停點四項齊全",
                   set(POL.PERMANENT_HALTS) == {"irreversible-delete", "payments",
                                                "prod-migration", "security-boundary"}))

    # --- 抽出來的純解析函式(CHG-20260810-04,待補項 #25)-------------------
    #
    # 這幾條是 fuzz 當場抓到的真崩潰改出來的。**分工是刻意的**:
    # `parse_*` 絕不拋例外(fuzz 的不變式),`load_policy` 照樣 raise(呼叫端契約)。
    from lib import profile as PRO_       # noqa: E402
    from lib import quality_judge as QJ_  # noqa: E402
    from lib import verify as VER_        # noqa: E402

    for label, raw in (("不是 JSON", "not json"),
                       ("合法 JSON 但不是物件", '[{"a": 1}]'),
                       ("permanent_halts 不可迭代", '{"permanent_halts": 3}')):
        m, err = POL.parse_policy_text(raw)
        checks.append((f"parse_policy_text:{label} → 回錯誤而非拋例外", m is None and bool(err)))
    m, err = POL.parse_policy_text('{"defaults": {"low": {"merge": "maybe"}}}')
    checks.append(("parse_policy_text:值域錯誤 → 回錯誤", m is None and "值域" in (err or "")))
    m, err = POL.parse_policy_text('{"permanent_halts": ["payments"]}')
    checks.append(("parse_policy_text:縮減 permanent_halts → 回錯誤",
                   m is None and "permanent_halts" in (err or "")))
    m, err = POL.parse_policy_text("{}")
    checks.append(("parse_policy_text:空物件 → 用預設矩陣", m == POL.DEFAULT_POLICY and err is None))

    for label, raw in (("不是 JSON", "boom"), ("合法 JSON 但不是物件", "[]"),
                       ("物件但缺 kill_rate", "{}")):
        res, msg = VER_.parse_mutation_result(raw)
        checks.append((f"parse_mutation_result:{label} → 回 None + 訊息", res is None and bool(msg)))
    res, msg = VER_.parse_mutation_result('{"kill_rate": 90}')
    checks.append(("parse_mutation_result:正常輸出 → 回結果", res == {"kill_rate": 90} and not msg))

    # 「合法 JSON 不等於預期形狀」這一族,本輪在四個檔案裡各出現一次
    d3 = pathlib.Path(tempfile.mkdtemp())
    (d3 / ".ai-sdlc").mkdir()
    (d3 / ".ai-sdlc" / "profile.json").write_text("[1, 2]", encoding="utf-8")
    prof, perr = PRO_.load_profile(d3)
    checks.append(("load_profile:合法 JSON 但不是物件 → 回錯誤而非崩潰",
                   prof is None and bool(perr)))
    b3 = d3 / "baseline.json"
    b3.write_text("[1, 2]", encoding="utf-8")
    base, berr = QJ_.load_baseline(b3)
    checks.append(("load_baseline:合法 JSON 但不是物件 → 回錯誤而非崩潰",
                   base == {} and bool(berr)))

    # --- verify.py 的純函式(CHG-20260810-04)------------------------------
    #
    # **這一組是被覆蓋率的跌幅逼出來的,而那個跌幅不是退步。** `verify.py` 在此之前
    # **從來沒有任何測試 import 過它**,所以它的 103 個 statement 根本不在報告裡;
    # 本輪一 import,77 行既有的未測程式**第一次現形**,總覆蓋率因此由 84.49% 掉到 83.64%。
    # 扣掉 verify.py 之後是 84.49% → 84.50%,既有受量測程式沒有退步。
    #
    # 正確的處置不是把 import 拿掉讓數字變好看——那是把「一直沒測」藏回去(KN-001 的鏡像)。
    # 下面補的是它真正好測的部分:純函式。剩下的 subprocess 路徑具名列在 ACC 的未涵蓋。
    checks.append(("_is_test_file:test_ 開頭", VER_._is_test_file(pathlib.Path("test_a.py"))))
    checks.append(("_is_test_file:_test.py 結尾", VER_._is_test_file(pathlib.Path("a_test.py"))))
    checks.append(("_is_test_file:tests/ 目錄下", VER_._is_test_file(pathlib.Path("tests/a.py"))))
    checks.append(("_is_test_file:一般程式不算",
                   not VER_._is_test_file(pathlib.Path("lib/plan.py"))))

    cur, missing = VER_.platform_coverage(None)
    checks.append(("platform_coverage:未宣告 → 無差集", isinstance(cur, str) and missing == []))
    cur2, missing2 = VER_.platform_coverage("linux, macos, windows")
    checks.append(("platform_coverage:宣告三平台 → 差集不含當前平台",
                   cur2 not in missing2 and len(missing2) == 2))

    class _Args:
        allow_untested = True
        mutation = True
        min_kill_rate = 10.0
        no_commit = True

    used, block = VER_.escape_hatches(_Args(), "沒有宣告逃生口的 CHG 內文")
    checks.append(("escape_hatches:門檻低於底線且未宣告 → 擋下",
                   bool(block) and any("min-kill-rate" in u for u in used)))
    used2, block2 = VER_.escape_hatches(_Args(), "Escape-hatch: 本輪為純文件,理由如下")
    checks.append(("escape_hatches:已宣告 Escape-hatch → 放行但仍列出",
                   block2 is None and len(used2) == 3))

    # ---------- exec_util ----------
    eq("die(3) 前綴 HALT", EU.die("x", 3), 3)
    eq("die(1) 前綴 ERROR", EU.die("x", 1), 1)
    eq("die(2) 前綴 INVALID-PLAN", EU.die("x", 2), 2)
    r = EU.run_shell(f'"{sys.executable}" -c "print(1)"', Path.cwd())
    checks.append(("run_shell 可取回 stdout", r.returncode == 0 and "1" in r.stdout))
    # 簡報必須自包含:含全域約束與該 task,且 build/review 兩種模式指示不同
    brief_b = EU.build_brief(GOOD, {"tid": "T1", "title": "甲"}, "build")
    brief_r = EU.build_brief(GOOD, {"tid": "T1", "title": "甲"}, "review")
    checks.append(("build 簡報含全域約束", "一律 X" in brief_b))
    checks.append(("build 簡報含該 task", "T1" in brief_b and "甲" in brief_b))
    checks.append(("build 簡報要求 TDD", "TDD" in brief_b))
    checks.append(("review 簡報要求輸出判定行", "[task-review]" in brief_r))
    checks.append(("兩種模式簡報不同", brief_b != brief_r))
    # live handshake 落盤:每個 task 邊界都要能被中斷後續作
    d3 = Path(tempfile.mkdtemp())
    EU.write_handshake(d3, "CHG-20260803-01", "task T1/2", "施工→測試→審查")
    hs = d3 / "docs" / "worklog" / "handshake-autopilot.md"
    checks.append(("handshake 檔已建立", hs.is_file()))
    hs_text = hs.read_text(encoding="utf-8")
    checks.append(("handshake 含 CHG 編號與續作點",
                   "CHG-20260803-01" in hs_text and "task T1/2" in hs_text
                   and "施工→測試→審查" in hs_text))
    checks.append(("handshake 標記 UTC+0", "UTC+0" in hs_text))

    # --- 模板宣告(CHG-20260805-11)---
    #
    # 反推「這是不是 plan-format」有邊界,而邊界上每份 CHG 都是一次擲骰子
    # (CHG-20260707-03 誤送檢、CHG-20260804-12 漏網)。更實際的代價是它**把人推向
    # 全套模板**:文書變更也得寫「本輪零程式改動,故不宣告行為規格」那種樣板話。
    # 文書最重要的是變更對、格式對,而樣板話兩樣都不買。
    LITE = "- Template: lite\n\n## 目標\n改一段措辭。\n"
    PLAN = "- Template: plan\n\n## 目標\n改一段措辭。\n"
    checks.append(("宣告 lite → 不要求 plan-format 欄位",
                   P.parse_tasks(LITE)[0] == []))
    checks.append(("宣告 lite → 不要求行為規格", not P.bspec_required(LITE)))
    checks.append(("宣告 plan → 照樣要求 Global Constraints",
                   any("Global Constraints" in x for x in P.parse_tasks(PLAN)[0])))
    checks.append(("沒宣告 → 行為不變(仍要求)",
                   any("Global Constraints" in x
                       for x in P.parse_tasks("## 目標\n改一段措辭。\n")[0])))
    checks.append(("模板值只認 lite/classic/plan",
                   P.declared_template("- Template: 隨便\n") is None))

    # ---- 設計圖閘(CHG-20260806-01)----
    # 確認閘要使用者確認的四樣東西全是散文與表格,而使用者要攔截的
    # 「模組接錯邊了」恰好是散文最不擅長表達的。一份看不懂的確認材料,
    # 拿到的不是確認,是默許。
    HEAD = ("- Template: plan\n- Risk: 中\n"
            "- Skill: ai-sdlc-autopilot v1.21.0\n")
    FIG = "### 設計圖\n\n```mermaid\nflowchart TD\n  A --> B\n```\n"
    checks.append(("v1.21 + plan + 中風險 + 缺圖 → 報問題",
                   any("設計圖" in x for x in P.diagram_problems(HEAD))))
    checks.append(("同上但有 mermaid 圍欄 → 無問題",
                   P.diagram_problems(HEAD + FIG) == []))
    checks.append(("ASCII 圍欄同樣算圖(格式不只 Mermaid)",
                   P.diagram_problems(HEAD + "### 設計圖\n\n```text\n A -> B\n```\n") == []))
    checks.append(("有節但只有散文 → 報問題(散文不是圖)",
                   any("圍欄" in x for x in
                       P.diagram_problems(HEAD + "### 設計圖\n\n先做 A 再做 B。\n"))))
    checks.append(("英文節名 Design diagrams 同樣認得",
                   P.diagram_problems(
                       HEAD + "### Design diagrams\n\n```mermaid\nflowchart TD\n  A-->B\n```\n") == []))
    # 跳過是使用者的權利,但它是一個**要簽名的欄位**——空白簽名不算簽名。
    checks.append(("宣告跳過且有理由 → 無問題",
                   P.diagram_problems(HEAD + "- Diagrams: skipped — 使用者:趕時間\n") == []))
    checks.append(("宣告跳過但理由空白 → 仍報問題",
                   any("理由" in x for x in P.diagram_problems(HEAD + "- Diagrams: skipped\n"))))
    checks.append(("破折號後全是標點也算空白理由",
                   any("理由" in x for x in P.diagram_problems(HEAD + "- Diagrams: skipped —\n"))))
    # 前瞻適用:不追殺存量。83 張既有 CHG 一張都不受影響。
    checks.append(("宣告 v1.20 → 不要求(前瞻適用)",
                   P.diagram_problems("- Template: plan\n- Risk: 中\n"
                                      "- Skill: ai-sdlc-autopilot v1.20.0\n") == []))
    checks.append(("未宣告 Skill 版本 → 行為與上線前相同",
                   P.diagram_problems("- Template: plan\n- Risk: 中\n") == []))
    checks.append(("低風險 → 免圖",
                   P.diagram_problems("- Template: plan\n- Risk: 低\n"
                                      "- Skill: ai-sdlc-autopilot v1.21.0\n") == []))
    checks.append(("Template: lite → 免圖(記帳成本隨風險縮放)",
                   P.diagram_problems("- Template: lite\n- Risk: 中\n"
                                      "- Skill: ai-sdlc-autopilot v1.21.0\n") == []))
    checks.append(("高風險 → 照樣要求",
                   P.diagram_required("- Template: plan\n- Risk: 高\n"
                                      "- Skill: ai-sdlc-autopilot v1.21.0\n")))
    checks.append(("section_body 到下一個同層標題為止(不吃到隔壁節)",
                   "Behaviour" not in P.section_body(
                       HEAD + FIG + "### Behaviour spec\n- feature: x.feature\n", P.DIAGRAM_RE)))
    # `## 設計圖` 若一路吃到檔尾,隔壁節的圍欄就會被當成自己的圖——散文照樣過閘。
    checks.append(("## 層級的設計圖同樣認得",
                   P.diagram_problems(
                       HEAD + "## 設計圖\n\n```mermaid\nflowchart TD\n  A-->B\n```\n") == []))
    checks.append(("## 設計圖只有散文時,不得借用隔壁節的圍欄",
                   any("圍欄" in x for x in P.diagram_problems(
                       HEAD + "## 設計圖\n\n先做 A。\n\n## 修改指引\n\n```bash\nls\n```\n"))))

    # ---- 合併前的本機自主檢查閘(CHG-20260806-04)----
    # 觸發證據不是假想的:CHG-20260806-01 帶著具名的「未涵蓋」合併進 main,
    # 而那項未涵蓋裡真的有缺陷(步驟片語撞名 → 23 份 feature 一份都沒跑到)。
    from lib import local_gate as LG
    CODE = ("- Template: plan\n- Risk: 中\n"
            "- Skill: ai-sdlc-autopilot v1.22.0\n")
    eq("本機閘的前瞻起點", LG.LOCAL_GATE_SINCE, (1, 22))
    checks.append(("程式類 v1.22 → 需要本機閘", LG.required(CODE)))
    checks.append(("純文件 → 免(僅限程式)",
                   not LG.required(CODE + "Acceptance-operation: n/a (docs-only)\n")))
    checks.append(("Template: lite → 免",
                   not LG.required("- Template: lite\n- Skill: ai-sdlc-autopilot v1.22.0\n")))
    checks.append(("宣告 v1.21 → 不要求(前瞻適用,不追殺存量)",
                   not LG.required("- Template: plan\n- Skill: ai-sdlc-autopilot v1.21.1\n")))
    checks.append(("未宣告版本 → 行為與上線前相同",
                   not LG.required("- Template: plan\n- Risk: 中\n")))
    DECL = CODE + "\n### 本機閘\n- cmd: bash run-checks.sh\n- pass: exit 0\n"
    eq("宣告的 cmd 可解析", LG.declared(DECL)[0], "bash run-checks.sh")
    eq("宣告的 pass 可解析", LG.declared(DECL)[1], "exit 0")
    eq("沒有該節時回 (None, None)", LG.declared(CODE), (None, None))
    checks.append(("英文節名 Local gate 同樣認得",
                   LG.declared(CODE + "\n### Local gate\n- cmd: make check\n")[0] == "make check"))
    # 信任邊界:cmd 來自 repo 內容,預設不執行(CHG-20260803-05 的同一條線)
    _c, _s, _b = LG.resolve(DECL, Path("."), None, trust_chg=False)
    checks.append(("CHG 宣告的指令預設不執行", _c is None and _b is not None))
    checks.append(("擋下的訊息點名內容驅動執行", "內容驅動執行" in (_b or "")))
    checks.append(("擋下的訊息附上宣告的指令原文", "bash run-checks.sh" in (_b or "")))
    _c, _s, _b = LG.resolve(DECL, Path("."), None, trust_chg=True)
    checks.append(("明示信任後才執行宣告的指令",
                   _c == "bash run-checks.sh" and _b is None))
    _c, _s, _b = LG.resolve(DECL, Path("."), "my-own-cmd", trust_chg=False)
    checks.append(("操作者的指令優先於 CHG 宣告",
                   _c == "my-own-cmd" and "操作者" in _s))
    # 慣例位置:本 repo 有 .github/ci_local.sh
    _c, _s, _b = LG.resolve(CODE, REPO_ROOT, None, trust_chg=False)
    checks.append(("沒宣告時退回慣例載具",
                   _c == "bash .github/ci_local.sh" and _b is None))
    # 查無 → fail-closed。merge 是單向門(KN-004)
    import tempfile as _tf
    _empty = Path(_tf.mkdtemp(prefix="lg-empty-"))
    _c, _s, _b = LG.resolve(CODE, _empty, None, trust_chg=False)
    checks.append(("查無載具 → 擋下而非放行(fail-closed)", _c is None and _b is not None))
    checks.append(("查無的訊息說明「沒跑過不等於通過」", "不等於通過" in (_b or "")))
    checks.append(("查無的訊息列出可用的慣例位置", "ci_local.sh" in (_b or "")))
    # 探測階段不得執行任何外部程序:`make -n` 會**求值** Makefile(shell 展開、include),
    # 而這一步只是在找載具,還沒到該執行任何東西的時候。
    # 用 AST 判,不用字串比對——第一版寫成 `"make -n" not in 原始碼`,而模組註解裡
    # 正好解釋了「為什麼不呼叫 make -n」,於是斷言被自己的註解命中。
    # 「字串比對分不出意圖」,本輪第三次(CHG-20260805-05/-06 各一次)。
    import ast as _ast
    _lg_tree = _ast.parse(pathlib.Path(LG.__file__).read_text(encoding="utf-8"))
    _imports = {n.module.split(".")[0] for n in _ast.walk(_lg_tree)
                if isinstance(n, _ast.ImportFrom) and n.module}
    _imports |= {a.name.split(".")[0] for n in _ast.walk(_lg_tree)
                 if isinstance(n, _ast.Import) for a in n.names}
    checks.append((f"探測階段不 import 任何執行外部程序的模組(實得 {sorted(_imports)})",
                   not (_imports & {"subprocess", "os"})))

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
