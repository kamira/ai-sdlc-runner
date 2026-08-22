#!/usr/bin/env python3
"""守閘門的閘門(CHG-20260803-02 T12)。stdlib-only,三平台一致。

其他測試驗的是「閘門的行為對不對」。本檔驗的是**閘門還在不在線上**——
因為讓所有驗證失效最省事的方法不是把它改錯,而是把它**拔掉**:

  · 把 `require_test_command` 從 `role_build` 的前置條件 tuple 裡刪掉
  · 把 `mutation_gate(...)` 那幾行註解掉
  · 讓 `role_review` 回到 `return 0`
  · 把 `run_tests.sh` 的「找不到測試 = 失敗」改成 `exit 0`
  · 給 CI 的測試 job 加一個 `if:` 條件讓它被跳過

以上每一種都不會讓任何既有測試變紅——被拔掉的閘門不會抗議。本檔以 AST/原始碼結構
直接斷言接線存在,是這類「消失式失效」唯一擋得住的地方。

Run: python3 test_gates_wired.py → exit 0 全過,1 有失敗。
"""
import ast
import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[2]
sys.path.insert(0, str(SCRIPTS))
import verifier_integrity as VI  # noqa: E402
sys.path.insert(0, str(SCRIPTS / "lib"))
import quality_judge as QJ_MOD  # noqa: E402

# 分層範圍(CHG-20260804-10)。這裡宣告的條數會被斷言比對,不是註解。
PLUGIN_LAYER = "plugins/ai-sdlc-suite/"
PLUGIN_CHECKS = 12

ROLES = SCRIPTS / "lib" / "roles.py"
RUN_TESTS = REPO / ".github" / "run_tests.sh"
RUN_GHERKIN = REPO / ".github" / "run_gherkin.sh"
WORKFLOW = REPO / ".github" / "workflows" / "governance.yml"
# CHG-20260806-02:測試 job 拆到獨立的手動 workflow——掛 `if:` 的 job 仍會以
# `skipping` 出現在 PR 的 check 清單裡,而使用者要的是「只有治理」。實測於 PR #18。
WF_TESTS = REPO / ".github" / "workflows" / "tests-manual.yml"

# 直譯器解析區塊的界標(CHG-20260804-15)。用界標而非猜測,是為了讓「區塊外不得出現
# bare python」這條斷言有精確的判定邊界——候選名單本來就必須提到 python/python3。
INTERP_START = "# --- interpreter-resolution:start"
INTERP_END = "# --- interpreter-resolution:end"
BARE_PY_RE = re.compile(r"(?<![\w$./-])python3?(?![\w.])")
# 輸出編碼慣例(見下方 KN-005 那段)。判準寬到容許排版差異(換行、引號),
# 但必須同時看到 utf-8 與 errors="replace"——只釘編碼而不 replace,
# 碰到編不出來的字元照樣崩,那正是這道閘要擋的事。
RECONFIGURE_RE = re.compile(
    r"reconfigure\(\s*encoding\s*=\s*[\"']utf-8[\"']\s*,\s*errors\s*=\s*[\"']replace[\"']")
# 「會印東西」的判準:出現 print( 或寫入 sys.stdout/stderr。
PRINTS_RE = re.compile(r"(?<![\w.])print\(|sys\.std(?:out|err)\.write\(")
# 「能被直接執行」的判準。範圍是這個而不是「會印東西」:`lib/` 底下的模組
# 永遠由某個進入點 import,而那個進入點已經釘過 stdout——對它們要求再釘一次,
# 是要求一個 library 在 import 時去改全域狀態,那是壞建議。
# 第一版判準寫成「會印東西」,當場把 4 支 lib 模組報成缺失;分界線不在會不會印,
# **在有沒有人替它釘過**。
ENTRYPOINT_RE = re.compile(r"__name__\s*==\s*[\"']__main__[\"']")


def outside_interpreter_block(src: str) -> str:
    """去掉註解與直譯器解析區塊,回傳其餘的可執行內容。"""
    keep, inside = [], False
    for line in src.splitlines():
        if INTERP_START in line:
            inside = True
            continue
        if INTERP_END in line:
            inside = False
            continue
        if inside or line.lstrip().startswith("#"):
            continue
        keep.append(line)
    return "\n".join(keep)


def func_source(tree: ast.Module, name: str, src: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


def calls_in(fn_src: str) -> set[str]:
    if not fn_src:
        return set()
    out = set()
    for node in ast.walk(ast.parse(fn_src)):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def dead_guards(fn_src: str) -> list[str]:
    """找出被常數短路掉的條件——`if False and ...` / `if ... and False` / `while False`。

    實測發現的洞:本檔原本只驗「呼叫有沒有出現在原始碼」,
    而 `if False and INT.required(...)` 讓閘門完全不執行,呼叫卻**照樣留在原始碼裡**——
    27 條斷言全過。移除閘門會被抓到,但**讓它變成死碼不會**。
    這是「消失式失效」的變形:程式碼還在,執行路徑不在。
    """
    if not fn_src:
        return []
    out = []
    for node in ast.walk(ast.parse(fn_src)):
        if not isinstance(node, (ast.If, ast.While)):
            continue
        test = node.test
        parts = test.values if isinstance(test, ast.BoolOp) else [test]
        for pt in parts:
            if isinstance(pt, ast.Constant) and isinstance(pt.value, bool):
                out.append(f"L{getattr(node, 'lineno', '?')}: 條件含常數 {pt.value}")
    return out


def main() -> int:
    checks = []
    out_of_scope: list[str] = []
    src = ROLES.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # --- 沒有任何閘門可以被常數短路成死碼 ---
    for fn in ("role_build", "_build_one", "role_review", "role_verify", "role_accept",
               "role_plan", "require_test_command", "require_interaction_declared"):
        dead = dead_guards(func_source(tree, fn, src))
        checks.append((f"{fn} 內無被常數短路的條件" + (f" — {dead}" if dead else ""), not dead))

    # --- 施工前置條件:四個 require_* 必須都還掛在 role_build 上 ---
    build_src = func_source(tree, "role_build", src)
    checks.append(("role_build 存在", bool(build_src)))
    for req in ("require_valid_plan", "require_no_permanent_halt",
                "require_confirm_gate", "require_test_command"):
        checks.append((f"role_build 仍掛著 {req}", req in build_src))

    # --- 設計圖閘:必須真的掛在 role_plan 上(CHG-20260806-01)---
    # 拔掉這一行不會弄壞任何測試——plan-check 照樣通過、退出碼照樣是 0,
    # 只是使用者再也拿不到圖。被拔掉的閘門不會抗議,所以由 AST 直接斷言它還在。
    plan_src = func_source(tree, "role_plan", src)
    checks.append(("role_plan 仍掛著 require_diagrams_declared",
                   "require_diagrams_declared" in plan_src))
    rdd = func_source(tree, "require_diagrams_declared", src)
    checks.append(("設計圖閘會 die(不是只印提示)", "die(" in rdd))
    checks.append(("設計圖閘的判定來自 plan.diagram_problems(未在此重寫一份)",
                   "diagram_problems" in calls_in(rdd)))
    checks.append(("跳過宣告仍經過 diagram_skipped(空理由才擋得住)",
                   "diagram_skipped" in calls_in(rdd)))

    # --- 單元閘:沒給測試指令時必須 die,不得只是 print ---
    rtc = func_source(tree, "require_test_command", src)
    checks.append(("require_test_command 會 die(不是只印訊息)", "die(" in rtc))
    checks.append(("--allow-untested 是明示逃生口而非預設",
                   "allow_untested" in rtc and "getattr" in rtc))

    # --- 變異閘:必須真的在 _build_one 內被呼叫 ---
    b1 = func_source(tree, "_build_one", src)
    checks.append(("_build_one 呼叫 mutation_gate", "mutation_gate" in calls_in(b1)))
    checks.append(("_build_one 仍執行 --test-cmd", "run_shell" in calls_in(b1)))
    checks.append(("_build_one 仍呼叫審查", "agent_call" in calls_in(b1)))
    # 審查自 CHG-20260803-09 起走 `_review_panel`(席次由風險分級決定),
    # 但「先擋再審」的次序不變:便宜且確定的閘要排在需要模型判斷的審查之前。
    checks.append(("變異閘位於 review 之前(先擋再審)",
                   b1.find("mutation_gate") < b1.find("_review_panel")
                   if "mutation_gate" in b1 and "_review_panel" in b1 else False))

    # --- 審查面板(CHG-20260803-09)---
    # 把裁決改回「單一審查者、二元判定」不會讓任何既有測試變紅:審查照樣被呼叫、
    # 判定行照樣被解析,只是否決權與降級規則悄悄消失。與前兩支同一種消失式失效。
    rp = func_source(tree, "_review_panel", src)
    checks.append(("_review_panel 存在", bool(rp)))
    rp_calls = calls_in(rp)
    checks.append(("面板席次由風險分級決定", "seats_for" in rp_calls))
    checks.append(("裁決由 runner 執行而非模型彙整", "adjudicate" in rp_calls))
    checks.append(("座位簡報走 seat_brief(只給自己那一列)", "seat_brief" in rp_calls))
    checks.append(("低風險仍走單席快速路徑", "len(seats) <= 1" in rp))
    checks.append(("高風險才跑交叉讀", 'ctx.risk != "high"' in rp))
    checks.append(("交叉讀有自己的裁決", "adjudicate_cross" in rp_calls))
    checks.append(("無判定行的席次算無法判定而非棄權", "cannot-verify" in rp))

    pn_src = (SCRIPTS / "lib" / "panel.py").read_text(encoding="utf-8")
    pn_tree = ast.parse(pn_src)
    adj = func_source(pn_tree, "adjudicate", pn_src)
    checks.append(("spec fail 為否決", "vetoes" in adj and "return False" in adj))
    checks.append(("全席無法判定即擋下", 'all(v["spec"] == "cannot-verify"' in adj))
    dg = func_source(pn_tree, "downgrade", pn_src)
    checks.append(("低信心降級為 cannot-verify", '"cannot-verify"' in dg))
    # 「分歧是調和或升級,絕不平均」——出現任何平均/加權即違反 review-panel
    for banned in ("mean(", "sum(", "average", "/ len("):
        checks.append((f"裁決層不得出現平均運算「{banned}」", banned not in adj + dg))
    cx = func_source(pn_tree, "adjudicate_cross", pn_src)
    checks.append(("交叉讀的分歧是升級而非平均", "return False" in cx))

    # --- 回修迴圈(CHG-20260803-07):回饋不得被拔掉 ---
    # 拔掉回饋不會讓任何測試變紅——迴圈照跑、次數照樣,只是每一輪都在重擲骰子。
    # 這正是「消失式失效」的另一種形態:機制還在,輸入不在。
    b1_calls = calls_in(b1)
    checks.append(("_build_one 擷取失敗原因(failure_note)", "failure_note" in b1_calls))
    checks.append(("_build_one 把回饋帶進施工 brief(compose_extra)", "compose_extra" in b1_calls))
    checks.append(("_build_one 把 findings 帶進複審 brief(compose_review_extra)",
                   "compose_review_extra" in b1_calls))
    checks.append(("回饋確實傳給 build_brief 而非算完丟掉",
                   "build_brief(ctx.text, t, \"build\", compose_extra(" in b1))
    checks.append(("_build_one 以 next_round 決定續作/停下", "next_round" in b1_calls))
    checks.append(("達上限時列出各輪未解項", "unresolved_report" in b1_calls))
    checks.append(("升階指令的選擇仍在線上", "agent_for_round" in b1_calls))
    # 變異預設開啟:判定必須走 mutation_enabled,不得退回 getattr(a, "mutation", False)
    checks.append(("變異閘的開關走 mutation_enabled(預設開)", "mutation_enabled" in b1_calls))
    checks.append(("變異閘未退回 opt-in 舊式判定",
                   'getattr(a, "mutation"' not in b1 and "getattr(a, 'mutation'" not in b1))

    # --- 測試棘輪與不穩定偵測(CHG-20260803-08)---
    # 這兩道閘被拔掉同樣不會讓任何既有測試變紅:單元指令照樣回 0(因為那支紅的測試
    # 已經被刪掉了),重跑也不會發生。與回饋路徑同一種「消失式失效」。
    checks.append(("_build_one 呼叫 ratchet_gate", "ratchet_gate" in b1_calls))
    checks.append(("_build_one 呼叫 flaky_gate", "flaky_gate" in b1_calls))
    checks.append(("棘輪排在靜態之前(先擋便宜的)",
                   b1.find("ratchet_gate") < b1.find("static_gate")
                   if "ratchet_gate" in b1 else False))
    checks.append(("flaky 排在變異之前",
                   b1.find("flaky_gate") < b1.find("mutation_gate")
                   if "flaky_gate" in b1 else False))
    checks.append(("棘輪失敗會進入回修來源", '"ratchet"' in b1))
    checks.append(("flaky 失敗會進入回修來源", '"flaky"' in b1))
    rt_src = (SCRIPTS / "lib" / "ratchet.py").read_text(encoding="utf-8")
    rt_tree = ast.parse(rt_src)
    checks.append(("棘輪以 AST 計數而非 grep",
                   "ast.parse" in func_source(rt_tree, "test_metrics", rt_src)))
    checks.append(("棘輪的逃生口是明示參數而非預設放行",
                   "allow_reduction: bool = False" in rt_src))
    dec = func_source(rt_tree, "decide", rt_src)
    checks.append(("未涵蓋語言不得被寫成通過",
                   "未涵蓋" in dec and "RATCHET_SUFFIXES" in dec))
    fd = func_source(rt_tree, "flaky_decide", rt_src)
    checks.append(("不穩定是 halt 而非警告後放行", "return False" in fd))
    eu_src = (SCRIPTS / "lib" / "exec_util.py").read_text(encoding="utf-8")
    sources_line = next((ln for ln in eu_src.splitlines()
                         if ln.startswith("FAILURE_SOURCES")), "")
    checks.append(("回修來源已含 ratchet / flaky",
                   "ratchet" in sources_line and "flaky" in sources_line))

    # --- 委派驗證的判讀(CHG-20260804-01)---
    # 把判讀拔掉不會讓任何既有測試變紅:指令照跑、產物照樣存在,只是內容沒人看。
    # 而讓退出碼重新定生死,則會讓這道閘從第一天恆紅——兩種都要擋。
    q_src = (SCRIPTS / "lib" / "quality.py").read_text(encoding="utf-8")
    q_tree = ast.parse(q_src)
    rg = func_source(q_tree, "run_gate", q_src)
    checks.append(("run_gate 呼叫判讀器", "judge" in calls_in(rg)))
    checks.append(("quality.run_gate:有判讀器的種類不以退出碼定生死", "not judged" in rg))
    checks.append(("產物存在這一關對所有種類都保留", "check_artifacts" in calls_in(rg)))
    checks.append(("產物讀不到時擋下而非放行", "讀不到的報告不等於沒問題" in rg))

    qj_src = (SCRIPTS / "lib" / "quality_judge.py").read_text(encoding="utf-8")
    qj_tree = ast.parse(qj_src)
    fpf = func_source(qj_tree, "fingerprint", qj_src)
    checks.append(("指紋不含行號", "line" not in fpf))
    lb = func_source(qj_tree, "load_baseline", qj_src)
    checks.append(("基線每條須有理由", "reason" in lb and "署名" in lb))
    checks.append(("基線壞掉時回報而非照跑", "無法解析" in lb))
    jf = func_source(qj_tree, "judge_findings", qj_src)
    checks.append(("新增發現一律擋下", "return False" in jf))
    checks.append(("基線只准往下(消失項會被提示)", "已不存在" in jf and "只准往下" in jf))
    checks.append(("解析失敗時擋下", "看不懂的報告不等於沒問題" in jf))
    jc = func_source(qj_tree, "judge_coverage", qj_src)
    checks.append(("覆蓋率是棘輪", "覆蓋率下降" in jc))
    checks.append(("四類判讀種類齊全",
                   all(k in qj_src for k in ("typecheck", "sast",
                                             "dependency-audit", "coverage"))))
    jq = REPO / ".github" / "judge_quality.py"
    checks.append(("CI 有判讀步驟", jq.is_file()))
    if jq.is_file():
        jq_src = jq.read_text(encoding="utf-8")
        checks.append(("CI 判讀器缺產物時視為失敗", "沒跑過不等於通過" in jq_src))
        checks.append(("基線更新須指名授權的 CHG",
                       "--update" in jq_src and "必須指名授權的 CHG" in jq_src))
        checks.append(("沒有理由的新發現不得寫入基線",
                       "拒絕寫入基線" in jq_src))
    # CHG-20260806-02:委派層的**場地**從 CI 的 quality job 搬到 `.github/run_quality.sh`,
    # 由本地載具呼叫。這兩條斷言因此改指向那支腳本——一條都沒刪。
    #
    # 順帶修掉一個既有缺陷:`ci_local.sh` 的說明一直寫著「--quick 跳過委派四工具」,
    # 而**完整模式從來沒有跑過它們**(一行呼叫都沒有)。若只是把 CI 的 job 刪掉,
    # 這一層會無聲消失,而說明還會繼續說它跑過了。
    ci_local_path = REPO / ".github" / "ci_local.sh"
    ci_src = ci_local_path.read_text(encoding="utf-8") if ci_local_path.is_file() else ""
    rq = REPO / ".github" / "run_quality.sh"
    checks.append(("委派層有可執行的腳本(run_quality.sh)", rq.is_file()))
    rq_src = rq.read_text(encoding="utf-8") if rq.is_file() else ""
    checks.append(("委派層跑四個工具", all(k in rq_src for k in
                                            ("mypy", "bandit", "pip_audit", "coverage"))))
    checks.append(("委派層由 judge_quality 判生死(不是看退出碼)",
                   "judge_quality.py" in rq_src))
    checks.append(("委派層工具缺席算未涵蓋而非通過",
                   "未涵蓋" in rq_src and "exit 2" in rq_src))
    # `gated_step` 也是呼叫行(CHG-20260813-08 / #59):旗標關掉它時,
    # 它**具名記錄跳過**而不是靜靜消失,所以它仍然是「本地載具有在呼叫委派層」的證據。
    checks.append(("本地載具真的呼叫委派層(錨定 step 行——說明裡提到不算跑過)",
                   re.search(r"^\s*(\[.*\]\s*&&\s*)?(gated_)?step .*run_quality\.sh",
                             ci_src, re.M) is not None))

    # --- 跑集護欄的 bootstrap(CHG-20260813-04)---
    # **靜態斷言守動態執行器**:對帳器守 34 種 check 的接線(複雜、常變),
    # 而這幾條只守一個布林——「reconcile 這一輪跑了或紅了」。
    # 層間異質,不是同構遞迴:任何守衛鏈都終止於一個不被守的受信基底,
    # 工程目標不是消滅它,是把它縮到**一行可 grep 的程度**且失效方向 fail-closed。
    #
    # 實際踩過:`--plan` 失敗時 `SCOPE_PLAN` 留 0,於是 `scope reconcile` 整塊
    # 不執行而腳本仍可 exit 0 —— **對帳閘自己無聲消失**,與它要殺的缺陷同形。
    checks.append(("本地載具真的跑跑集對帳(而不是只在說明裡提到)",
                   "scope_plan.py --repo . --reconcile" in ci_src))
    checks.append(("對帳失敗會進失敗清單(不是印一行就過去)",
                   re.search(r"--reconcile[^\n]*\n[^\n]*FAILED\+=\(\"scope reconcile\"\)",
                             ci_src) is not None))
    checks.append(("計畫產不出來是 **fail-closed**(而不是靜靜地全跑)",
                   'FAILED+=("scope plan")' in ci_src))
    checks.append(("計畫在所有 step 之前產生一次(同一輪問同一份)",
                   ci_src.index("scope_plan.py --repo . --plan")
                   < ci_src.index("step() {")))

    # --- 信任根的前提(CHG-20260813-04)---
    # 整條守衛鏈的頂端不是「有人執行 `--update`」那一下,而是那一下**必然留下的東西**:
    # `authorized_by` + CHG 編號寫進一份**受 git 追蹤**的基線檔,
    # 於是每次變動都以 diff 形式流過兩席審查與使用者可見面。
    # **信任根是「基線 diff 過兩席審查」,不是「執行者被信任」**
    # ——前者在我與席位都被換掉之後仍然成立,後者依 DIR-2 本來就不成立(fable)。
    #
    # 而它成立有一條可 grep 的前提:**基線檔必須維持在版控裡**。
    # 有人把它移進 `.gitignore` 或改成生成物不入庫,**這條鏈才真的斷**——
    # 那一刻不會有任何既有的閘轉紅,所以這一條要自己守。
    _ig = REPO / ".gitignore"
    _ig_src = _ig.read_text(encoding="utf-8") if _ig.is_file() else ""
    for _rel in ("skills/ai-sdlc-autopilot/assets/verifier_integrity.json",
                 "skills/ai-sdlc-autopilot/assets/check_scope_baseline.json"):
        _name = Path(_rel).name
        checks.append((f"信任根基線 {_name} 在版控裡(檔案存在)",
                       (REPO / _rel).is_file()))
        checks.append((f"信任根基線 {_name} 沒有被 .gitignore 排除",
                       not any(_name in ln and not ln.lstrip().startswith("#")
                               for ln in _ig_src.splitlines())))

    # --- 非功能性驗證(CHG-20260804-02)---
    # 這道閘被拔掉不會讓任何既有測試變紅——它只在 verify 階段出現一次,
    # 而「不適用」若被寫成「通過」,連紅燈都不會有。
    vf2 = func_source(tree, "role_verify", src)
    checks.append(("role_verify 呼叫非功能性閘", "PRO.run_gate" in vf2))
    checks.append(("三態的 not-applicable 有獨立分支", '"not-applicable"' in vf2))
    checks.append(("未涵蓋仍依風險分級處置", "未涵蓋" in vf2 and "ctx.risk" in vf2))
    pr_src = (SCRIPTS / "lib" / "profile.py").read_text(encoding="utf-8")
    pr_tree = ast.parse(pr_src)
    checks.append(("型態未宣告時倒向全部適用(最保守)",
                   "if not profiles:" in func_source(pr_tree, "applicable", pr_src)))
    na = func_source(pr_tree, "na_message", pr_src)
    checks.append(("不適用的措辭與未涵蓋分開", "與「未涵蓋」" in na))
    for banned in ("驗證通過", "檢查通過", "全數通過"):
        checks.append((f"不適用訊息不得出現「{banned}」", banned not in na))
    lp = func_source(pr_tree, "load_profile", pr_src)
    checks.append(("型態用讀的不用猜", "return None, None" in lp))
    checks.append(("未知型態被拒絕", "已知型態" in lp))
    rg2 = func_source(pr_tree, "run_gate", pr_src)
    checks.append(("空豁免視同未宣告", "空豁免與沒宣告等價" in rg2))
    checks.append(("適用而未宣告會擋下", "但未宣告" in rg2))
    checks.append(("指令仍受信任邊界約束", "trust_chg" in rg2))
    nf = SCRIPTS.parent / "assets" / "nonfunctional_checks.json"
    checks.append(("分類表存在", nf.is_file()))
    if nf.is_file():
        tbl = json.loads(nf.read_text(encoding="utf-8-sig"))["kinds"]
        checks.append(("九類齊全", len(tbl) == 9))
        checks.append(("每類都有 applies_to",
                       all(k.get("applies_to") for k in tbl.values())))
        checks.append(("負載不課在 CLI 身上",
                       "cli-tool" not in tbl["load-stress"]["applies_to"]))

    # --- 非功能性的產物判讀(CHG-20260804-03)---
    # 拔掉判讀不會讓任何測試變紅:指令照跑、產物照樣存在,只是內容沒人看——
    # 一份寫著「12 個 GPL 相依」的報告照樣「存在且非空」。
    pr_rg = func_source(ast.parse((SCRIPTS / "lib" / "profile.py")
                                  .read_text(encoding="utf-8")), "run_gate",
                        (SCRIPTS / "lib" / "profile.py").read_text(encoding="utf-8"))
    checks.append(("非功能性閘接了判讀器", "QJ.judge" in pr_rg))
    checks.append(("非功能性 run_gate:有判讀器的種類不以退出碼定生死",
                   "kind not in QJ.JUDGED_NONFUNCTIONAL" in pr_rg))
    checks.append(("逐類 defer 回報為未涵蓋而非通過",
                   "具名延後" in pr_rg and "uncovered.append" in pr_rg))
    checks.append(("空 defer 被擋", "空延後與沒宣告等價" in pr_rg))
    jl = func_source(qj_tree, "judge_license", qj_src)
    checks.append(("本專案缺 LICENSE 即擋", "沒有 LICENSE" in jl and "return False" in jl))
    checks.append(("copyleft 指名但不自動擋", "不感染" in jl))
    checks.append(("未知授權不被當成沒問題", "PERMISSIVE_LICENSES" in qj_src))
    jb = func_source(qj_tree, "judge_build_repro", qj_src)
    checks.append(("可重現要同時驗冪等與已提交複本",
                   "idempotent" in jb and "committed_matches_build" in jb))
    checks.append(("缺 identical 欄位不放行", "判不出來就不放行" in jb))
    lic = REPO / "LICENSE"
    checks.append(("本專案有 LICENSE 檔", lic.is_file()))

    # --- 對外契約與屬性測試(CHG-20260804-04)---
    jc = func_source(qj_tree, "judge_api_contract", qj_src)
    # 只擋破壞性:五種破壞都要在,而成功路徑要明說「無破壞性變更」
    checks.append(("五種破壞條件齊全",
                   all(s in jc for s in ("模組消失", "公開函式消失", "必填參數消失",
                                         "新增了必填參數", "CLI 旗標消失"))))
    checks.append(("成功路徑明說無破壞性變更", "無破壞性變更" in jc))
    checks.append(("移除公開函式算破壞", "公開函式消失" in jc))
    checks.append(("新增必填參數也算破壞", "新增了必填參數" in jc))
    checks.append(("尚無快照時不得被讀成相容性通過", "相容性通過" in jc))
    jf2 = func_source(qj_tree, "judge_property_fuzz", qj_src)
    checks.append(("任何崩潰即擋", "return False" in jf2))
    checks.append(("跑 0 次不算通過", "沒跑過" in jf2))
    checks.append(("訊息帶種子供重現", "seed" in jf2))
    lb2 = func_source(qj_tree, "load_baseline", qj_src)
    checks.append(("基線帶回 api_contract(否則判讀器恆綠)", "api_contract" in lb2))
    fz = SCRIPTS / "lib" / "fuzzing.py"
    checks.append(("模糊測試引擎與目標清單分開", fz.is_file()))
    if fz.is_file():
        fz_src = fz.read_text(encoding="utf-8")
        checks.append(("引擎可注入目標(才驗得了紅燈可達)", "def run_fuzz(targets" in fz_src))
        checks.append(("種子可固定(紅燈要能追查)", "random.Random(seed)" in fz_src))
    checks.append(("四類非功能性都接了判讀器",
                   all(k in qj_src for k in ("license-compliance", "build-reproducibility",
                                             "api-contract", "property-fuzz"))))

    # --- 效能基準(CHG-20260804-05)---
    # 這道閘有兩個對稱的風險:紅燈不可達(裝飾)與綠燈不穩定(無故轉紅 → 被關掉)。
    jp = func_source(qj_tree, "judge_performance", qj_src)
    checks.append(("比的是比值不是秒數", "ratio" in jp and "比值" in jp))
    checks.append(("門檻抓倍數", "tol" in jp and "PERF_TOLERANCE" in qj_src))
    checks.append(("0 個目標不算沒有退步", "不是「沒有退步」" in jp))
    checks.append(("校準失敗不放行", "量不出來就不放行" in jp))
    checks.append(("目標消失會被提示", "沒量到" in jp))
    bn = SCRIPTS / "lib" / "bench.py"
    checks.append(("基準引擎與目標清單分開", bn.is_file()))
    if bn.is_file():
        bn_src = bn.read_text(encoding="utf-8")
        # 逐目標重新校準:只在整輪開頭校準一次,分子與分母就不來自同一個時刻,
        # 負載在一輪之內變化時約不掉(CHG-20260804-09 實測 4.93 倍)
        checks.append(("逐目標重新校準(機器快慢才約得掉)",
                       bn_src.count("measure(calibration_workload") >= 2
                       and "secs / base" in bn_src))
        # 斷言的是**意圖**不是某一行的字面:CHG-20260804-18 把量測改寫成
        # 「每個視窗一個樣本、取最小」之後,原本比對 `return min(samples)` 的寫法
        # 就紅了——而取最小這件事一直都在。字面比對只擋得住它自己那一版。
        meas = func_source(ast.parse(bn_src), "measure", bn_src)
        checks.append(("量測取最小值(雜訊只會加時間不會減)",
                       "min(" in meas and "median" not in meas))
        checks.append(("校準量到 0 秒要回報", "計時器解析度不足" in bn_src))
        # --- CHG-20260804-18:量 CPU 時間、粒度實測、量不出來回未涵蓋 ---
        checks.append(("效能量的是 CPU 時間而非牆鐘",
                       "process_time" in bn_src and 'CLOCK_NAME = "process_time"' in bn_src))
        # 只驗「沒有真的去呼叫它」,而且用 AST 判——散文裡提到它是為了說明為什麼不用,
        # 那段要留著。字串比對分不出「提到」與「呼叫」,這正是本檔存在的理由的縮影。
        bn_tree = ast.parse(bn_src)
        calls_gci = any(
            isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Attribute) and n.func.attr == "get_clock_info")
                 or (isinstance(n.func, ast.Name) and n.func.id == "get_clock_info"))
            for n in ast.walk(bn_tree))
        checks.append(("粒度以實測為準(不呼叫 get_clock_info)",
                       "def effective_granularity" in bn_src and not calls_gci))
        checks.append(("自動調整視窗有牆鐘預算(閘不得卡住)",
                       "AUTORANGE_BUDGET_S" in bn_src and "perf_counter() > deadline" in bn_src))
        checks.append(("量不出來回未涵蓋而非沒有退步",
                       "class Unmeasurable" in bn_src
                       and bn_src.count("不等於沒有退步") >= 2))
        checks.append(("報告記下所用時鐘", '"clock": CLOCK_NAME' in bn_src))
        checks.append(("穩定性上限獨立且嚴於偵測門檻",
                       "PERF_STABILITY_MAX" in qj_src
                       and QJ_MOD.PERF_STABILITY_MAX < QJ_MOD.PERF_TOLERANCE))
    checks.append(("六類非功能性都接了判讀器",
                   all(k in qj_src for k in ("license-compliance", "build-reproducibility",
                                             "api-contract", "property-fuzz", "performance"))))

    # --- 未涵蓋登記簿的自洽性(CHG-20260804-06)---
    # 登記簿是唯一一份「用來記錄我們還不知道什麼」的文件。
    # 它一旦不可信,整套涵蓋率宣稱都不可信——而它踩過兩種說謊。
    di = REPO / "skills" / "ai-sdlc-autopilot" / "scripts" / "doc_integrity_check.py"
    di_src = di.read_text(encoding="utf-8") if di.is_file() else ""
    checks.append(("doc-integrity 檢查登記簿自洽性",
                   "check_coverage_registry" in di_src))
    checks.append(("該檢查有被掛進 main(不是只定義了)",
                   di_src.count("check_coverage_registry") >= 2))
    checks.append(("抓重複 ID", "重複的 ID" in di_src))
    checks.append(("抓宣告收尾卻仍列著", "宣告收尾" in di_src))

    # --- 治理基準點閘的接線(CHG-20260811-02,待補項 30)---
    # 施工中實測:把 `main()` 裡那一行呼叫拿掉,**沒有任何東西抗議**——
    # 規格照樣 12/12 綠,因為它們直接呼叫函式,驗的是函式對不對,
    # 不是「它有沒有接在流程上」。讓閘門失效最省事的方法是把它刪掉,
    # 而被刪掉的閘門不會抗議(CHG-20260804-10)。
    #
    # 判準用 **AST 看 `main()` 真的呼叫了它**,不用字串計數:
    # 「字串比對分不出意圖」在本 repo 出現過四次,四次的修法都是改用 AST
    # ——註解裡提一句、或另一個函式呼叫它,字串計數都會通過。
    if di_src:
        try:
            di_tree = ast.parse(di_src)
            main_src = func_source(di_tree, "main", di_src)
            wired = "check_governance_baseline" in calls_in(main_src)
        except (SyntaxError, ValueError):
            wired = False
        checks.append(("治理基準點閘定義存在",
                       "def check_governance_baseline" in di_src))
        checks.append(("治理基準點閘**被 main() 真的呼叫**(AST,非字串計數)", wired))
        # 三態不得壓成兩態:沒宣告的 repo 是「不適用」,而不適用不是通過。
        checks.append(("不適用與通過分得開(訊息裡具名『不適用』)",
                       "不適用" in di_src and "verbose" in di_src))

    # --- hook 與 MCP:治理工具不可成為故障點(CHG-20260804-07)---
    # 這一層屬於 **plugin**,不屬於 skill。skill 被單獨散佈時它不存在。
    # 範圍由**簽過名的清單**決定而不是由檔案在不在決定——否則「刪掉」就成了
    # 合法的離場方式,而那正是本檔在擋的事(CHG-20260804-10)。
    if VI.in_scope(PLUGIN_LAYER, repo=REPO):
        before = len(checks)
        hooks_dir = REPO / "plugins" / "ai-sdlc-suite" / "hooks"
        for h in ("pre_edit_gate.py", "session_start.py", "stop_closeout.py"):
            hp = hooks_dir / h
            # 清單列了而檔案不見 → 照樣紅。範圍化不吃掉真正的拔閘。
            checks.append((f"{h} 存在", hp.is_file()))
            # 條數必須與檔案在不在無關,否則缺檔會連帶拖紅「條數一致」那條,
            # 讓紅的理由變成兩個。缺檔時讀成空字串,該紅的仍然紅。
            hs = hp.read_text(encoding="utf-8") if hp.is_file() else ""
            # 治理工具不可成為故障點:任何例外都要吞掉並 exit 0
            checks.append((f"{h} 以 except 收尾(不得成為故障點)",
                           "except Exception" in hs and "return 0" in hs))
        peg_p = hooks_dir / "pre_edit_gate.py"
        peg = peg_p.read_text(encoding="utf-8") if peg_p.is_file() else ""
        checks.append(("略過路徑比對的是相對路徑(不是絕對路徑)",
                       "relative_to(root)" in peg))
        checks.append(("詞彙表含本 repo 實際在用的「施工中」", "施工中" in peg))
        checks.append(("狀態只取那一節的第一行結論", "status_scope" in peg))
        mcp = REPO / "plugins" / "ai-sdlc-suite" / "mcp" / "ai_sdlc_mcp.py"
        checks.append(("MCP server 存在", mcp.is_file()))
        ms = mcp.read_text(encoding="utf-8") if mcp.is_file() else ""
        checks.append(("MCP 對非物件請求不崩潰", "isinstance(req, dict)" in ms))
        checks.append(("MCP 對 handler 例外回錯誤而非死掉",
                       "-32603" in ms and "except Exception" in ms))
        # 印出去的條數必須是真的條數,否則「少了幾條」這個可稽核的量會失真
        checks.append((f"plugin 層條數與宣告一致(宣告 {PLUGIN_CHECKS})",
                       len(checks) - before == PLUGIN_CHECKS))
    else:
        out_of_scope.append(
            VI.out_of_scope_note("plugin 層(hooks / MCP)", PLUGIN_CHECKS))

    # --- 永遠停點與旗標契約(CHG-20260804-09)---
    si = SCRIPTS / "sentinel_install.py"
    checks.append(("sentinel_install 存在", si.is_file()))
    if si.is_file():
        si_src = si.read_text(encoding="utf-8")
        # 建立持久設定是永遠停點:沒有明示授權一律 halt,且即使授權也不逕自寫入系統
        checks.append(("建 cron 需明示授權", "i_authorize_cron" in si_src
                       or "i-authorize-cron" in si_src))
        checks.append(("即使授權也只產出可審閱的設定", "stdout" in si_src or "print" in si_src))
    checks.append(("旗標層有專屬測試",
                   (SCRIPTS / "test_sentinel_flags.py").is_file()))

    # --- 交接文件:機器不得整份覆寫人寫的內容 ---
    eu_tree = ast.parse(eu_src)
    wh = func_source(eu_tree, "write_handshake", eu_src)
    checks.append(("write_handshake 先讀既有內容", "read_text" in wh))
    checks.append(("write_handshake 走區塊合併而非整份覆寫", "handshake_block" in calls_in(wh)))
    hb = func_source(eu_tree, "handshake_block", eu_src)
    checks.append(("handshake_block 無標記時保留既有內容", "existing.rstrip" in hb))

    # --- 整支 review:必須真的呼叫 agent,不得回到 no-op ---
    rv = func_source(tree, "role_review", src)
    checks.append(("role_review 呼叫 agent_call(不是 no-op)", "agent_call" in calls_in(rv)))
    checks.append(("role_review 解析判定行", "VERDICT_RE" in rv))
    checks.append(("role_review 無判定行時 die", rv.count("die(") >= 2))

    # --- 驗收前置:操作驗收與全部完成的斷言仍在 ---
    ac = func_source(tree, "role_accept", src)
    checks.append(("role_accept 仍要求全部 task 完成", "require_all_built" in ac))
    checks.append(("role_accept 仍要求操作驗收已過", "verified" in ac))
    vf = func_source(tree, "role_verify", src)
    checks.append(("role_verify 仍要求宣告操作驗收", "require_operational_declared" in vf))

    # --- CI 載具:找不到測試必須是失敗 ---
    rt = RUN_TESTS.read_text(encoding="utf-8") if RUN_TESTS.is_file() else ""
    checks.append((".github/run_tests.sh 存在", bool(rt)))
    checks.append(("找不到測試檔 → 失敗(不得回綠)",
                   "-eq 0" in rt and "exit 1" in rt))
    checks.append(("逐檔失敗會累積並回非零", "FAILED" in rt and "exit 1" in rt))

    # --- CI 載具:直譯器不存在不得長得像測試失敗(CHG-20260804-15;KN-003 往上移一層) ---
    #
    # `run_tests.sh` 原本呼叫 bare `python`。在只有 `python3` 的機器上,28 支測試各回
    # exit 127(command not found),而載具把它彙總成「28/28 個測試檔失敗」——
    # 一個錯誤但高度可信的解釋:看到這句話的人會去查測試,不會去查 `command -v python`。
    #
    # 三條斷言,各擋一種退化:
    #   1. 區塊在      → 擋「整段解析被刪掉、改回 bare python」
    #   2. 區塊外沒有 bare python → 擋「解析留著但某一行仍直接呼叫 python」
    #   3. 探針是實跑   → 擋「退化成只 `command -v`」;存在不等於能用
    #      (Windows 市集的 python3 假替身:找得到、執行只會開市集)
    rg = RUN_GHERKIN.read_text(encoding="utf-8") if RUN_GHERKIN.is_file() else ""
    checks.append((".github/run_gherkin.sh 存在", bool(rg)))

    # 範圍由**發現**決定,不由手寫的檔名清單決定(CHG-20260807-02;KN-005)。
    #
    # 這三條斷言本來跑在 `for label, sh_src in (("run_tests.sh", rt), ("run_gherkin.sh", rg))`
    # 上——**兩支,寫死的**。而 `.github/*.sh` 實際有七支:其中四支是後來
    # 靠**有人記得**手動補上區塊的(`verify.sh` 由 CHG-20260806-02 補,即待補項 #8),
    # 第五支 `run_build_repro.sh` **沒有人記得**,於是它帶著 3 處 bare `python3`
    # 活了下來,而且沒有任何東西抗議——被拔掉的閘門不會抗議,**從沒裝上的更不會**。
    #
    # 規則早就寫成機器斷言了,漏的是**斷言的適用範圍**。那是同一條 KN-005:
    # 靠記性維持的東西會重複失效,所以範圍本身也要變成機器算得出來的。
    #
    # 只有「會呼叫 python」的載具進範圍:對不呼叫 python 的腳本要求解析區塊是噪音,
    # 而噪音會逼人把整道閘關掉。不進範圍的**具名列進 out_of_scope**,不靜靜跳過。
    # --- 輸出編碼慣例:同一條 KN-005,而它在 CHG-20260811-01 當場被違反一次 ---
    #
    # `skills/**/scripts/*.py` 每一支都在開頭把 stdout/stderr 釘成 utf-8 +
    # errors="replace"。少了它的代價實測過:平台預設編碼非 UTF-8 時(這台機器是
    # cp950),一句含 `❌` 的錯誤訊息會讓整支腳本 `UnicodeEncodeError` 崩掉——
    # **本來要告訴使用者「來源不存在」,結果給的是 traceback**,而崩潰與正確攔截
    # 在退出碼上一樣(KN-003)。
    #
    # 這條規則本來 44 支腳本 44 支都遵守,**而且完全靠記性**:沒有任何斷言守著它。
    # 於是 CHG-20260811-01 寫的第一支新腳本 `ledger_migrate.py` 就漏了,
    # 沒有任何東西抗議。這與待補項 #8(`run_build_repro.sh` 漏掉直譯器區塊)同形——
    # **規則對、範圍靠人記**。範圍改成 glob 自動發現,所以不會有第三次。
    #
    # 只有「會印東西」的腳本進範圍:純函式庫模組不印,要求它釘編碼是噪音,
    # 而噪音會逼人把整道閘關掉。不進範圍的**具名列進 out_of_scope**。
    py_files = sorted(SCRIPTS.glob("*.py")) + sorted((SCRIPTS / "lib").glob("*.py"))
    checks.append((f"發現 scripts/*.py(實得 {len(py_files)} 支)", len(py_files) >= 20))
    for must in ("doc_integrity_check.py", "governance_health.py"):
        checks.append((f"py 掃描發現結果涵蓋既有的 {must}(範圍只准擴大,不准縮小)",
                       must in {p.name for p in py_files}))
    for p in py_files:
        try:
            py_src = p.read_text(encoding="utf-8")
        except OSError:
            checks.append((f"py 掃描:{p.name} 讀得到(讀不到不等於沒問題)", False))  # diffcov-exempt: syserr — 讀真實原始碼時的 OSError 原則上可達,但要安全且跨平台可重複地觸發需注入檔案系統故障;本筆只改了訊息文字(拆撞名),判定語意一行未動 [signoff: codex+fable @ CHG-20260812-03]
            continue
        if not (PRINTS_RE.search(py_src) and ENTRYPOINT_RE.search(py_src)):
            why = ("不輸出到 stdout/stderr" if not PRINTS_RE.search(py_src)
                   else "非進入點(由 import 它的進入點釘編碼)")
            out_of_scope.append(f"{p.name}:{why},無需自行釘編碼")
            continue
        checks.append((f"{p.name} 釘住輸出編碼(utf-8 + errors=replace)",
                       RECONFIGURE_RE.search(py_src) is not None))

    # 範圍含 `skills/**/scripts/*.sh`:CHG-20260811-01 把 `toolchain_probe.sh` 從
    # `.github/` 搬進 `skills/`(它要**出貨**給消費者,留在 `.github/` 等於教人跑一支
    # 他們沒有的檔)。若這裡的 glob 沒跟著擴,那支腳本就**靜靜離開了這道閘的視野**
    # ——而「範圍縮小」不會有任何東西抗議,這正是待補項 #8 的形狀。
    sh_files = sorted((REPO / ".github").glob("*.sh")) if (REPO / ".github").is_dir() else []
    sh_files += sorted(SCRIPTS.glob("*.sh"))
    checks.append((f"發現 shell 載具(實得 {len(sh_files)} 支)", len(sh_files) >= 2))
    checks.append(("發現結果涵蓋出貨的 toolchain_probe.sh(搬家後範圍不得縮小)",
                   "toolchain_probe.sh" in {p.name for p in sh_files}))
    # 發現階段壞掉(glob 打錯、目錄搬走)會回空清單,而空清單跑完迴圈是**全過**。
    # 「搜尋壞了」與「全部合格」不可以都是綠燈——同 run_tests.sh 的「找不到測試 = 失敗」。
    found_names = {p.name for p in sh_files}
    for must in ("run_tests.sh", "run_gherkin.sh"):
        checks.append((f"shell 掃描發現結果涵蓋既有的 {must}(範圍只准擴大,不准縮小)",
                       must in found_names))
    scanned = 0
    for p in sh_files:
        try:
            sh_src = p.read_text(encoding="utf-8")
        except OSError:
            checks.append((f"shell 掃描:{p.name} 讀得到(讀不到不等於沒問題)", False))  # diffcov-exempt: syserr — 同上,shell 掃描側的同形防禦分支 [signoff: codex+fable @ CHG-20260812-03]
            continue
        has_block = INTERP_START in sh_src and INTERP_END in sh_src
        body = outside_interpreter_block(sh_src)
        leftover = BARE_PY_RE.findall(body)
        if not has_block and not leftover:
            out_of_scope.append(f"{p.name}:不呼叫 python,無需直譯器解析區塊")
            continue
        scanned += 1
        checks.append((f"{p.name} 有直譯器解析區塊", has_block))
        checks.append((f"{p.name} 解析區塊外不得直接呼叫 python/python3"
                       f"(實得 {len(leftover)} 處)", not leftover))
        block = sh_src[sh_src.find(INTERP_START):sh_src.find(INTERP_END)] if has_block else ""
        checks.append((f"{p.name} 候選以實跑探針驗可用(不只 command -v)",
                       '-c "import sys"' in block or "-c 'import sys'" in block))
    checks.append((f"至少有一支載具進入直譯器解析的檢查範圍(實得 {scanned} 支)",
                   scanned > 0))

    # --- 內嵌的 Python 程式必須真的是合法 Python(CHG-20260822-01)-------------
    #
    # 起因是本輪自己踩到的缺陷。`toolchain_probe.sh` 用 `$PY -c "$_cmp_prog"` 委派版本比對,
    # 而那段 shell 單引號寫壞了,程式字串前後各多一個字面單引號 —— 於是每一次呼叫都是
    # SyntaxError、輸出是空的。
    #
    # 兩件事讓它值得一道專屬的閘:
    #
    # ① **fail-closed 有守住,所以它不會自己浮出來。** 空輸出被判成「比不動」→ NOT_RUN,
    #    正是設計要的方向。缺陷因此**不會表現為假綠**,只會表現為「這個功能從來沒生效過」——
    #    而那種缺陷可以活很久。
    # ② **Gherkin 那層抓不到。** shim 靠 argv 子字串分派(`*packaging*`),而壞掉的程式裡
    #    照樣有 `packaging` 那幾個字,shim 就照常回答 SATISFIED,場景全綠。用替身測委派,
    #    測得到「有沒有委派出去」,測不到「委派出去的東西是不是合法的」。
    #
    # 能抓到它的只有一件事:把那段字串**真的當 Python 解析一次**。這道閘就是那一次解析。
    #
    # 慣例(被這條規則隱含要求):內嵌程式一律用 shell 單引號包、內部只用雙引號。
    # 這樣它既不會被 shell 展開,也能被下面這條規則整段取出。
    # **不錨在行首**:賦值可能寫在 `case` 分支後面(本輪那個缺陷正是),錨了就整段漏掉,
    # 而漏掉只會讓計數守衛在「總數變少」時才叫——新增一段寫在分支裡的程式仍會無聲未涵蓋。
    prog_re = re.compile(r"(_\w*prog)='([^']*)'")

    def _program_parses(prog_src: str) -> bool:
        """那段字串當成 Python 解析得動嗎?

        抽成具名函式**不是為了美觀**:判定藏在迴圈裡的 `try/except` 中就只能靠「真的有一支
        腳本壞掉」才會走到 False 那條路,於是這道閘的核心判定永遠沒被驗過——而一個從未回過
        False 的檢查,與恆真回報無法區分(KN-001)。抽出來之後,下面那兩條自檢就餵得進去。
        """
        try:
            ast.parse(prog_src)
            return True
        except SyntaxError:
            return False

    # 這道閘自己要被驗不空轉,而且用的就是本輪那個缺陷的**真實形狀**:
    # shell 引號寫壞之後,程式字串前後各多一個字面單引號。
    checks.append(("內嵌程式語法判定:合法程式判 True",
                   _program_parses("import sys\nprint(sys.argv[1])")))
    checks.append(("內嵌程式語法判定:被引號吃掉的程式判 False(本輪缺陷的形狀)",
                   not _program_parses("'import sys\nprint(sys.argv[1])'\n'")))

    progs_found = 0
    for p in sh_files:
        try:
            sh_src = p.read_text(encoding="utf-8")
        except OSError:  # diffcov-exempt: syserr — 同本檔其他掃描側的同形防禦分支;要安全且跨平台可重複地觸發需注入檔案系統故障 [signoff: codex+fable @ CHG-20260822-01]
            checks.append((f"內嵌程式掃描:{p.name} 讀得到(讀不到不等於沒問題)", False))  # diffcov-exempt: syserr — 同本檔其他掃描側的同形防禦分支;要安全且跨平台可重複地觸發需注入檔案系統故障 [signoff: codex+fable @ CHG-20260822-01]
            continue  # diffcov-exempt: syserr — 同本檔其他掃描側的同形防禦分支;要安全且跨平台可重複地觸發需注入檔案系統故障 [signoff: codex+fable @ CHG-20260822-01]
        for prog_name, prog_src in prog_re.findall(sh_src):
            progs_found += 1
            checks.append((f"{p.name} 的 {prog_name} 是合法 Python(不是被引號吃掉的字串)",
                           _program_parses(prog_src)))
    # 發現階段壞掉(regex 打錯、慣例被改成雙引號)會回零個,而零個跑完迴圈是**全過**。
    # 同本檔其他掃描:「搜尋壞了」與「全部合格」不可以都是綠燈。
    checks.append((f"發現內嵌 Python 程式(實得 {progs_found} 段;0 段代表掃描本身壞了)",
                   progs_found >= 2))

    # --- UTF-8 模式不得溢出到測試載具(CHG-20260807-02 T5)-------------------
    #
    # 起因是一個真缺陷:`pip_audit -r requirements-dev.txt` 在 cp950 機器上崩潰,
    # 因為 `pip_requirements_parser.auto_decode` 無 BOM 時**退回 locale 編碼**,
    # 而那份檔案的註解是 UTF-8 中文。修法是 `PYTHONUTF8=1`。
    #
    # 而最直覺的修法會**順手刪掉一整條涵蓋軸**:把它設在 `ci_local.sh` 或
    # `run_tests.sh` 上,整台機器的「`open()` 預設編碼 = cp950」就消失了——
    # 而那條軸是這台機器唯一給得起、CI 的 UTF-8 runner 給不起的東西
    # (CHG-20260803-01 的三個缺陷全部只在非 UTF-8 情境現形)。
    #
    # 判準:委派工具那一支**要有**(不然 pip-audit 又會崩),測試載具**不准有**。
    # 分界線是「誰是被測程式」:第三方工具讀不了 UTF-8 是它的問題;
    # 被測程式讀不了才是我們的缺陷,而那正是要留著被抓到的。
    # 判的是**賦值**,不是這個字出現過。第一版寫成 `"PYTHONUTF8" not in body`,
    # 而 `ci_local.sh` 的未涵蓋公告裡有一句「不要為了修工具而把 PYTHONUTF8 設到全域」
    # ——一句**警告不要做**的話,被斷言讀成**做了**。
    # 這是本 repo 撞過四次的同一個形狀:字串比對分不出意圖(CHG-20260805-05/-06)。
    # 賦值形式是機器判得出來的;「有沒有提到」不是。
    UTF8_FLAG = "PYTHONUTF8"
    UTF8_SET_RE = re.compile(rf"^\s*(?:export\s+)?{UTF8_FLAG}\s*=", re.MULTILINE)
    for name in ("run_tests.sh", "run_gherkin.sh", "ci_local.sh"):
        p = REPO / ".github" / name
        body = outside_interpreter_block(p.read_text(encoding="utf-8")) if p.is_file() else ""
        hits = UTF8_SET_RE.findall(body)
        checks.append((f"{name} 不得設定 {UTF8_FLAG}"
                       f"(那會刪掉本機的非 UTF-8 涵蓋軸;實得 {len(hits)} 處)", not hits))
    rq = (REPO / ".github" / "run_quality.sh")
    rq_src = rq.read_text(encoding="utf-8") if rq.is_file() else ""
    checks.append((f"run_quality.sh 必須設定 {UTF8_FLAG}"
                   f"(cp950 下 pip-audit 讀不了 requirements-dev.txt)",
                   bool(UTF8_SET_RE.search(outside_interpreter_block(rq_src)))))
    # 非 UTF-8 stdio 輪必須還在線上——拿掉它不會弄壞任何測試,只是那條軸靜靜消失。
    ci_src_now = (REPO / ".github" / "ci_local.sh").read_text(encoding="utf-8")
    checks.append(("ci_local.sh 仍掛著非 UTF-8 stdio 輪",
                   bool(re.search(r"PYTHONIOENCODING=cp9\d\d\s+bash\s+\.github/run_tests\.sh",
                                  ci_src_now))))
    # 找不到直譯器時的訊息必須把讀者導離「測試壞了」這個錯誤懷疑對象
    checks.append(("找不到直譯器的訊息與測試失敗可辨識",
                   "不是「測試失敗」" in rt or "不是『測試失敗』" in rt))

    # --- 測試不得被靜默略過:場地從 CI 搬到本地載具(CHG-20260806-02)---
    #
    # 使用者裁示 skill 自己的 repo「CI 只跑治理檢查」。下面這幾條原本錨在 workflow 的
    # tests job 上,而它們的存在目的就是**防止有人拿掉測試**(見本檔檔頭列的攻擊)。
    #
    # 所以一條都沒刪:要拿掉的是**場地**(GitHub Actions),不是「測試不得被靜默略過」
    # 這條保證。刪掉斷言等於把保證也刪了,而且刪得看不出來。改為:
    #   · workflow 側只留「tests 已限定手動、quality 已移除」這兩個**新事實**的斷言
    #   · 原本那幾條的職責搬到 `ci_local.sh` —— 它現在是合併依據(常設決定)
    wf = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
    # 全部錨定**行**而不是子字串。第一版寫成 `"github.event_name == 'workflow_dispatch'" in wf`
    # ——那個字串在 matrix 的 `fromJSON` 運算式裡也出現一次,所以拿掉 `if:` 閘之後
    # 斷言照樣通過:**裝飾性斷言,看起來還在守**。紅可達性探針當場抓到它。
    # 這是 CHG-20260805-05/-06 反覆撞到的同一個形狀:字串比對分不出意圖。
    wf_t = WF_TESTS.read_text(encoding="utf-8") if WF_TESTS.is_file() else ""
    checks.append(("測試 workflow 仍存在(保留三平台的回頭路)",
                   re.search(r"^  tests:\s*$", wf_t, re.M) is not None))
    # 新事實一:PR 上只剩 governance 一個 check。
    # 拆檔而不是掛 `if:` ——掛 if: 的 job 會以 skipping 出現在 check 清單裡,那也是一列。
    checks.append(("測試 workflow 只由手動觸發(on: 底下沒有 pull_request/push)",
                   re.search(r"^on:\s*$", wf_t, re.M) is not None
                   and re.search(r"^  workflow_dispatch:\s*$", wf_t, re.M) is not None
                   and re.search(r"^  (pull_request|push):", wf_t, re.M) is None))
    checks.append(("治理 workflow 裡沒有 tests job(否則 PR 上會多一列)",
                   re.search(r"^  tests:\s*$", wf, re.M) is None))
    # 新事實二:委派四工具的 job 整個移除(場地搬到本機)
    checks.append(("quality job 已從 workflow 移除",
                   re.search(r"^  quality:\s*$", wf, re.M) is None))
    # 場地搬移後,這四條錨定本地載具——它們才是現在真的在守的東西。
    # 同樣錨定**呼叫行**:註解裡提到腳本名不算「有跑」。
    checks.append(("本地載具跑 run_tests.sh(測試沒有消失,只是換地方)",
                   re.search(r"^\s*(\[.*\]\s*&&\s*)?step .*run_tests\.sh", ci_src, re.M) is not None))
    checks.append(("本地載具跑行為規格層(或在 behave 缺席時具名列為未涵蓋)",
                   re.search(r"^\s*(\[.*\]\s*&&\s*)?(gated_)?step .*run_gherkin\.sh",
                             ci_src, re.M) is not None
                   and "行為規格層" in ci_src))

    # --- #59:**旗標不得直接關掉一個 step**(CHG-20260813-08)---
    #
    # `[ "$QUICK" = "0" ] && step "X" …` 這個形狀讓那一關**既沒跑也沒具名跳過**,
    # 於是對帳恆等式在該模式下必紅。那個紅是對的,但**一道大家都知道會紅的閘,
    # 效果上等於 fail-open**:紅燈被習慣化之後,真紅也會被略過。
    #
    # 這條靜態斷言守的是**形狀不得回來**——處置寫在 `gated_step` 裡,
    # 而「記得用 gated_step」是靠記性維持的規則(KN-005),所以要變成機器判得出來的。
    bare_gated = [ln.strip() for ln in ci_src.splitlines()
                  if not ln.lstrip().startswith("#")
                  and re.match(r"^\s*\[.*\]\s*&&\s*step\s", ln)]
    checks.append((f"旗標不得直接關掉 step(要走 gated_step,實得 {len(bare_gated)} 行)",
                   not bare_gated))
    if bare_gated:
        print(f"          旗標直接關掉的 step:{bare_gated[:3]}")  # diffcov-exempt: defensive — 只在上一條斷言**已經失敗**時才走到的診斷輸出;要覆蓋它就得讓那條斷言先紅,而那正是它存在的理由 [signoff: codex+fable @ CHG-20260813-08]
    # **只看程式碼,不看註解。** 第一版兩條都打在註解上:`--record-skip` 出現在
    # 上一行的說明裡、`MODE_SKIPS` 出現在宣告與尾段裡,於是把記帳那一行整個換成
    # `true`、把計數那一行換成 `:`,兩條斷言**照樣綠**。判準比證據弱——
    # 這正是本輪反覆遇到的形狀,而這次的受害者是我自己剛寫的守衛。
    ci_code = "\n".join(ln for ln in ci_src.splitlines()
                        if not ln.lstrip().startswith("#"))
    checks.append(("gated_step 會把跳過記進帳(不是只印一行)",
                   re.search(r'--record-skip\s+"\$name"\s+--why\s+"\$why"', ci_code)
                   is not None))
    checks.append(("模式跳過真的計數(不只是宣告一個變數)",
                   re.search(r"MODE_SKIPS=\$\(\(MODE_SKIPS \+ 1\)\)", ci_code) is not None))
    checks.append(("模式跳過的條數每輪重印且明示不是驗收",
                   re.search(r'\[ "\$MODE_SKIPS" -gt 0 \]', ci_code) is not None
                   and "本輪不是驗收" in ci_code))
    checks.append(("本地載具恆印三平台未涵蓋(不是靜靜消失)",
                   "未涵蓋" in ci_src and "macOS / Windows" in ci_src))
    checks.append(("本地載具的測試步驟未被條件跳過",
                   "steps.changed" not in ci_src))
    # 舊斷言是 `三個平台字串都在 wf 裡`。CHG-20260805-08 把預設 matrix 收成只跑 ubuntu
    # 之後,那三個字串仍在檔案裡(在 `fromJSON` 的字面量中)——**斷言恆真通過,
    # 而實際上只跑一個平台**。那正是本 repo 定義的裝飾性斷言,留著比刪掉更糟,
    # 因為它看起來還在守。改為驗真不變量:
    #   要嘛跑全平台,要嘛把**未涵蓋**印出來,而且措辭不得像通過。
    # 錨定**觸發區塊的那一行**,不是「檔案裡有沒有這個字串」——
    # `workflow_dispatch` 在 matrix 運算式與公告步驟裡也會出現,
    # 用子字串判會恆真通過(第一版就是這樣,紅可達性驗不出來)。
    full_matrix_path = (re.search(r"^  workflow_dispatch:\s*$", wf_t, re.M) is not None
                        and re.search(r"^      full_matrix:\s*$", wf_t, re.M) is not None)
    discloses = "scope disclosure" in wf_t and "未涵蓋" in wf_t
    checks.append(("縮減 matrix 時有恆執行的未涵蓋公告", discloses))
    checks.append(("保留手動跑回全平台的路徑", full_matrix_path))
    checks.append(("未涵蓋公告不含肯定式通過措辭",
                   not any(a in wf + wf_t
                           for a in ("驗證通過", "檢查通過", "全數通過", "已通過"))))
    checks.append(("Windows 非 UTF-8 輪次仍在", "PYTHONIOENCODING" in wf_t))
    # 一次紅不得吃掉另一層的涵蓋(CHG-20260806-13,待補項 #10)。
    # Actions 預設在前一步失敗時跳過後續步驟——於是 run_tests 一紅,規格層整步被
    # 跳過,**該輪規格涵蓋率靜默歸零**,而 job 只顯示「失敗」。本輪已誤讀過一次。
    # 「規格失敗」與「規格根本沒跑」在 job 層長得一樣(KN-003)。
    for step_name in ("run behaviour specs", "operational verify",
                      "run all test_*.py (Windows"):
        i = wf_t.find(step_name)
        seg = wf_t[i:i + 260] if i >= 0 else ""
        checks.append((f"「{step_name}」不因前一步失敗而被跳過(if: always)",
                       "if: always()" in seg))
    # tests job 內的 run_tests.sh 步驟不得掛 steps.changed 的 fail-open 條件
    checks.append(("tests job 未套用變更範圍 fail-open",
                   "steps.changed" not in wf_t))
    # 同一條規則套在本地載具上:未涵蓋清單的措辭不得讀起來像通過。
    # 錨定**公告區塊本身**而不是整份檔案——整份檔案裡有各步驟的 ✅,
    # 用全檔判會把「有沒有守住」跟「檔案裡出現過什麼字」混為一談。
    _d = ci_src.find('⚪ **未涵蓋**')
    ci_disclosure = ci_src[_d:ci_src.find("\nFAILED=", _d)] if _d >= 0 else ""
    checks.append(("本地載具的未涵蓋公告存在且非空", len(ci_disclosure) > 40))
    checks.append(("本地載具的未涵蓋公告不含肯定式通過措辭",
                   bool(ci_disclosure) and not any(
                       a in ci_disclosure
                       for a in ("驗證通過", "檢查通過", "全數通過", "已通過"))))

    # --- 互動閘(第五道)必須接在 role_verify 上 ---
    checks.append(("role_verify 呼叫互動閘 run_gate", "run_gate" in calls_in(vf)))
    checks.append(("互動閘位於行為規格之後(先驗規格再驗使用面)",
                   vf.find("bspec_paths") < vf.find("INT.run_gate")
                   if "INT.run_gate" in vf else False))
    checks.append(("互動閘的未涵蓋依風險分級,非一律放行",
                   'ctx.risk == "low"' in vf and "停下交人" in vf))
    ri = func_source(tree, "require_interaction_declared", src)
    checks.append(("role_plan 掛著 require_interaction_declared",
                   "require_interaction_declared" in func_source(tree, "role_plan", src)))
    checks.append(("空豁免會被擋(豁免必須帶理由)", "空豁免" in ri and "die(" in ri))
    # 分類表不得被縮減成空表——那等同關閉這道閘
    kinds = json.loads((REPO / "skills" / "ai-sdlc-autopilot" / "assets" /
                        "interaction_kinds.json").read_text(encoding="utf-8-sig"))["kinds"]
    checks.append((f"互動分類表非空且含五種內建(實得 {len(kinds)})", len(kinds) >= 5))
    checks.append(("每種分類都要求可稽核產物",
                   all(k.get("artifacts") for k in kinds.values())))

    # --- 合併前的本機自主檢查閘(CHG-20260806-04)---
    # 拔掉這一行不會弄壞任何測試:accept 照樣跑完、退出碼照樣是 0,只是合併前
    # 再也沒有在本機跑過一次。而這道閘的觸發證據就是「帶著未涵蓋合併,而未涵蓋
    # 裡真的有缺陷」——被拔掉的閘門不會抗議,所以由 AST 直接斷言它還在。
    checks.append(("role_accept 掛著本機閘", "_local_gate" in ac))
    lg_fn = func_source(tree, "_local_gate", src)
    # 兩條擋下路徑要**各自**釘住。第一版只寫 `"die(" in lg_fn`,而函式裡有兩個 die——
    # 把其中一個改成 print,斷言照樣通過。紅可達性探針當場抓到:
    # 本輪第四次「字串比對分不出意圖」。改用 AST 逐分支判。
    def _branch_dies(fn_src: str, cond_substr: str) -> bool:
        """那個 if 分支的主體裡有沒有 return die(...)。"""
        for node in ast.walk(ast.parse(fn_src)):
            if not isinstance(node, ast.If):
                continue
            if cond_substr not in (ast.unparse(node.test) or ""):
                continue
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call)
                        and isinstance(sub.value.func, ast.Name)
                        and sub.value.func.id == "die"):
                    return True
        return False
    checks.append(("查無/不信任時走 die(不是只印訊息)",
                   _branch_dies(lg_fn, "blocked")))
    checks.append(("本機檢查沒過時走 die(不是只印訊息)",
                   _branch_dies(lg_fn, "returncode")))
    checks.append(("本機閘的判定來自 local_gate 模組(未在此重寫一份)",
                   "LG." in lg_fn))
    checks.append(("本機閘真的執行指令(不只是解析)", "run_shell" in calls_in(lg_fn)))
    checks.append(("本機閘排在 CI 閘之前",
                   ac.find("_local_gate") < ac.find("CI.check")))
    # 這道閘宣稱涵蓋**所有風險分級**,而它每被排到某個風險停點之後,就少涵蓋一級。
    # 已經發生兩次:
    #   -04 接在 merge 之後   → 只有 low(中/高的 merge 本來就 halt)
    #   -06 移到 merge 之前   → low + medium(high 停在更前面的 acceptance)
    # 兩次的斷言都只比對**一個**停點,於是下一個停點就成了新的漏洞。
    #
    # 所以這一條**列舉所有會提早 return 的風險停點**——新增停點時,
    # 忘了把它加進這張表會被下面那條「表非空且涵蓋矩陣所有階段」的斷言擋下。
    from lib import policy as POL_MOD  # noqa: E402  (套件式匯入,不走 sys.path 平放)
    RISK_HALTS = ('ctx.action("acceptance")', 'ctx.action("merge")')
    lg_pos = ac.find("_local_gate")
    late = [h for h in RISK_HALTS if 0 <= ac.find(h) < lg_pos]
    checks.append((f"本機閘排在**所有**風險停點之前(排在其後的:{late or '無'})",
                   lg_pos >= 0 and not late))
    # 這張表不得漏掉矩陣裡任何一個會 halt 的階段——漏一個就等於少守一級風險。
    matrix_stages = {s for row in POL_MOD.DEFAULT_POLICY.values() for s in row}
    halting = {s for s in matrix_stages
               if any(POL_MOD.DEFAULT_POLICY[r][s] != "auto" for r in POL_MOD.DEFAULT_POLICY)}
    listed = {h.split('"')[1] for h in RISK_HALTS}
    missed = (halting - listed) - {"confirm_gate", "operational_verify", "task_review", "pr"}
    checks.append((f"風險停點表未漏掉 accept 路徑上的階段(漏:{sorted(missed) or '無'})",
                   not missed))
    checks.append(("逃生口 --allow-no-local-gate 會留痕",
                   "allow_no_local_gate" in lg_fn and "write_handshake" in calls_in(lg_fn)))
    lg_src = (SCRIPTS / "lib" / "local_gate.py").read_text(encoding="utf-8")
    checks.append(("查無載具時 fail-closed(擋下,不是放行)",
                   "查無" in lg_src and "不等於通過" in lg_src))
    checks.append(("CHG 宣告的指令仍受信任邊界約束",
                   "trust_chg" in lg_src and "內容驅動執行" in lg_src))
    checks.append(("僅限程式:沿用既有兩個訊號,未新發明第三套",
                   "DOCS_ONLY_RE" in lg_src and "is_light" in lg_src))

    # --- 合併前的 CI 閘必須接在 role_accept 上 ---
    checks.append(("role_accept 呼叫 CI 閘", "check" in calls_in(ac) and "CI." in ac))
    checks.append(("CI 閘為 fail-closed(查不到不放行)",
                   "fail-closed" in ac or "難以回收" in ac))
    checks.append(("--allow-no-ci 是明示逃生口且留痕",
                   "allow_no_ci" in ac and "write_handshake" in ac))
    ci_src = (SCRIPTS / "lib" / "ci_gate.py").read_text(encoding="utf-8")
    green_line = ci_src.split("GREEN =")[1].splitlines()[0]
    checks.append(("pending 不得被歸為綠燈", '"pending"' not in green_line))
    checks.append(("查詢失敗一律回不放行",
                   "error is not None" in ci_src and "return False" in ci_src))

    # --- 內建靜態/安全檢查必須接在 build 上,且 CI 也跑 ---
    checks.append(("_build_one 呼叫 static_gate", "static_gate" in calls_in(b1)))
    checks.append(("靜態閘位於變異之前(先跑便宜的)",
                   b1.find("static_gate") < b1.find("mutation_gate")
                   if "static_gate" in b1 else False))
    checks.append(("CI 執行靜態/安全檢查", "static_check.py" in wf))
    sc = (REPO / "skills" / "ai-sdlc-autopilot" / "scripts" / "static_check.py").read_text(encoding="utf-8")
    checks.append(("靜態檢查涵蓋 secrets", "SECRET_PATTERNS" in sc))
    checks.append(("secrets 掃描不限 .py", '".yml"' in sc or "'.yml'" in sc))
    checks.append(("allowlist 損毀時不得略過檢查", "return 2" in sc and "allowlist 讀取失敗" in sc))
    vsrc = (SCRIPTS / "lib" / "verify.py").read_text(encoding="utf-8")
    checks.append(("檢查器不見時不得當成通過", "缺少檢查器不等於沒有問題" in vsrc))

    # --- 委派型驗證閘必須接在 verify 上 ---
    checks.append(("role_verify 呼叫委派閘", "Q.run_gate" in vf))
    checks.append(("委派閘的未涵蓋依風險分級", "工具不存在" in vf or "未涵蓋欄" in vf))

    # --- repo 內的 JSON 一律不得帶 BOM ---
    # CI 的 `python -m json.tool` 以純 utf-8 讀取,帶 BOM 直接失敗。
    # Windows 工具(PowerShell `Set-Content -Encoding UTF8`、記事本)預設會寫 BOM,
    # 而在 Windows 上跑任何測試都察覺不到——這一格只有 CI 會紅。
    bom = [str(f.relative_to(REPO)) for f in REPO.rglob("*.json")
           if not any(s in f.parts for s in (".git", "node_modules", "_site"))
           and f.read_bytes().startswith(b"\xef\xbb\xbf")]
    checks.append((f"repo 內無帶 BOM 的 JSON(實得 {len(bom)} 個)", not bom))
    if bom:
        print(f"          帶 BOM:{bom[:5]}")

    # --- 斷言的條件不得是恆真常數(CHG-20260805-05)---
    #
    # 「排在計分之後」是一種永遠不會判失敗的斷言;「條件是字面 True」是另一種。
    # 兩者的共通點:**印出 PASS 而它根本沒在檢查任何東西**,還讓通過數 +1。
    #
    # 只擋**恆真**,不擋恆假:常數 False 是刻意的硬失敗(例如 git 不存在時逼人去裝),
    # 那是「未涵蓋不得讀成通過」的實作,擋掉它等於擋掉正確的做法。
    #
    # 豁免「應拋例外」的既有慣例——同一個斷言名稱出現在 try/except 兩側
    # (try 內 False、except 內 True),兩個常數合起來才是判定。要求它改寫
    # 是讓程式去配合 lint。
    def const_true_checks(path: Path) -> list:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return []
        appends = []
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "append" and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "checks" and n.args
                    and isinstance(n.args[0], ast.Tuple) and len(n.args[0].elts) >= 2):
                appends.append((ast.dump(n.args[0].elts[0]), n.args[0].elts[1], n.lineno))
        paired = {name for name, cond, _ in appends
                  if isinstance(cond, ast.Constant) and cond.value is False}
        return [f"{path.name}:{ln}" for name, cond, ln in appends
                if isinstance(cond, ast.Constant) and cond.value is True
                and name not in paired]

    decorative = [h for f in sorted(SCRIPTS.glob("test_*.py")) for h in const_true_checks(f)]
    checks.append((f"斷言條件不是恆真常數(實得 {len(decorative)} 處)", not decorative))
    if decorative:
        print(f"          恆真斷言:{decorative[:5]}")

    # --- 斷言不得排在計分之後(CHG-20260805-04)---
    #
    # 我把三條新斷言插在 `failed = [...]` 之後。它們被算進總數、卻永遠不會判失敗——
    # **一條不可能變紅的斷言**,而且它還順便藏住了第二個缺陷(元組長度寫錯,
    # 因為從來沒被解包過)。是靠「斷言總數對不上」才發現的,那不該是發現機制。
    def appends_after_tally(path: Path) -> bool:
        lines = path.read_text(encoding="utf-8").splitlines()
        tally = next((i for i, l in enumerate(lines)
                      if l.strip().startswith("failed = [")), None)
        if tally is None:
            return False
        last_append = max((i for i, l in enumerate(lines)
                           if "checks.append(" in l and not l.lstrip().startswith("#")),
                          default=-1)
        return last_append > tally

    late = [f.name for f in sorted(SCRIPTS.glob("test_*.py")) if appends_after_tally(f)]
    checks.append((f"斷言不排在計分之後(實得 {len(late)} 檔)", not late))
    if late:
        print(f"          排在計分之後:{late}")

    # --- 給機器讀的路徑欄位不得用平台相依的分隔符(CHG-20260805-02)---
    #
    # `str(Path)` 在 Windows 給 `docs\\knowledge`、在 POSIX 給 `docs/knowledge`。
    # 同一個 repo 在不同平台回不同字串,任何比對它的呼叫端都會在其中一個平台壞掉。
    # 這一類缺陷在 Linux 上跑再多次也看不出來——本輪是 Windows CI 抓到的。
    mcp_py = REPO / "plugins" / "ai-sdlc-suite" / "mcp" / "ai_sdlc_mcp.py"
    if VI.in_scope(PLUGIN_LAYER, repo=REPO) and mcp_py.is_file():
        mcp_tree = ast.parse(mcp_py.read_text(encoding="utf-8"))
        stringified = [
            n.lineno for n in ast.walk(mcp_tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str"
            and n.args and isinstance(n.args[0], ast.Call)
            and isinstance(n.args[0].func, ast.Attribute)
            and n.args[0].func.attr in ("relative_to", "resolve", "absolute")]
        checks.append((f"MCP 的路徑輸出不用 str(Path)(實得 {len(stringified)} 處)",
                       not stringified))
        if stringified:
            print(f"          行號:{stringified[:5]} —— 改用 .as_posix()")

    # --- behave 的保留屬性不得被步驟檔覆寫(CHG-20260805-01)---
    #
    # `context.text` / `context.table` / `context.failed` 是 behave 自己的欄位。
    # 指派它們只會得到一個 ContextMaskWarning,而**讀回來不是你寫進去的東西**——
    # 於是斷言拿到空字串,錯誤訊息長得像「工具沒有產出」。
    #
    # 本機用 stub 頂替 behave 裝飾器的驅動器抓不到這件事(它沒有 behave 的 Context),
    # 三平台 CI 全紅才現形。這道 lint 讓下一次在提交前就擋住。
    # 用 AST 找**賦值目標**,不是正則。第一版寫成 `context\.(text|table)\s*=`,
    # 而真實的寫法是 tuple 解包 `context.text, context.obj = ...`——等號不在後面,
    # 於是那道 lint 抓不到自己的觸發案例。字串比對第四次分不出意圖。
    RESERVED = {"text", "table", "failed"}

    def masks_reserved(path: Path) -> list:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return []
        hits = []
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            flat = []
            for tgt in targets:
                flat += list(ast.walk(tgt))
            for n in flat:
                if (isinstance(n, ast.Attribute) and n.attr in RESERVED
                        and isinstance(n.value, ast.Name) and n.value.id == "context"):
                    hits.append(f"{path.name}:{n.lineno} context.{n.attr}")
        return hits

    masking = [h for f in sorted((REPO / "features" / "steps").glob("*.py"))
               for h in masks_reserved(f)]
    checks.append((f"步驟檔不覆寫 behave 保留屬性(實得 {len(masking)} 處)", not masking))
    if masking:
        print(f"          覆寫處:{masking[:5]}")

    # --- 本地 CI 不得與 workflow 漂移(CHG-20260805-10)---
    #
    # 本地載具的價值全繫於「它跑的和 CI 跑的是同一批」。一份手抄的副本必漂移——
    # 這個 repo 為此才把步驟抽成 `.github/run_*.sh`(見 `run_tests.sh` 檔頭)。
    # 這道斷言比對兩邊的**腳本呼叫**:workflow 加了新的 `.github/run_*.sh` 或
    # `scripts/*.py` 步驟而本地載具沒跟上,就紅。
    local_ci = REPO / ".github" / "ci_local.sh"
    checks.append((".github/ci_local.sh 存在", local_ci.is_file()))
    if local_ci.is_file():
        lc = local_ci.read_text(encoding="utf-8")
        wf_scripts = set(re.findall(r"(?:\.github/run_\w+\.sh|"
                                    r"skills/ai-sdlc-autopilot/scripts/\w+\.py|"
                                    r"plugins/\w+\.py)", wf))
        # GitHub 專屬的(需事件脈絡或 runner)本地跑不到,具名排除
        github_only = {".github/run_coverage.sh", ".github/run_license_check.py",
                       ".github/run_build_repro.sh", ".github/run_api_contract.py",
                       ".github/run_property_fuzz.py", ".github/run_performance.py"}
        missing = sorted(s for s in wf_scripts - github_only if s not in lc)
        checks.append((f"本地 CI 未漏掉 workflow 的腳本(實得 {len(missing)} 個)", not missing))
        if missing:
            print(f"          本地載具缺:{missing[:5]}")
        checks.append(("本地 CI 印出未涵蓋清單",
                       "未涵蓋" in lc and "不等於 CI 綠" in lc))

    # --- 驗證器完整性檢查本身必須存在且被 CI 執行 ---
    vi = REPO / "skills" / "ai-sdlc-autopilot" / "scripts" / "verifier_integrity.py"
    checks.append(("verifier_integrity.py 存在", vi.is_file()))
    checks.append(("CI 執行驗證器完整性檢查", "verifier_integrity.py" in wf))

    for note in out_of_scope:
        print(note)
    failed = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    if failed:
        print(f"❌ {len(failed)}/{len(checks)} 失敗 — 有閘門從流程上消失了")
        return 1
    print(f"✅ 全 {len(checks)} 斷言通過(閘門仍在線上)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
