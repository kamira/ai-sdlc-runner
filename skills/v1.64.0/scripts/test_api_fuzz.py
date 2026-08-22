#!/usr/bin/env python3
"""對外契約與屬性測試的單元斷言(CHG-20260804-04)。

其中最要緊的一條不是任何一個判定,而是**紅燈可達性**:
模糊測試第一次跑就 0 個失敗,與模糊測試引擎壞掉,在輸出上完全一樣(KN-001)。
所以本檔注入一個故意會炸的目標,證明引擎真的抓得到。

Run: python3 test_api_fuzz.py → exit 0 全過,1 有失敗。
"""
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[2]
sys.path.insert(0, str(SCRIPTS))
from lib import fuzzing as FZ        # noqa: E402
from lib import quality_judge as QJ  # noqa: E402

AFFIRMATIVE = ("驗證通過", "檢查通過", "全數通過", "已通過")


def _contract(mods=None, flags=None):
    return {"version": 1,
            "modules": mods if mods is not None else
            {"m.py": {"f": {"params": ["a", "b"], "required": ["a"],
                            "kwonly": [], "varargs": False, "kwargs": False}}},
            "cli_flags": flags if flags is not None else ["--chg", "--repo"]}


def t_contract(checks):
    """對外契約:只擋破壞性,新增放行。"""
    base = {"api_contract": _contract()}

    ok, msg, _ = QJ.judge("api-contract", json.dumps(_contract()), base)
    checks.append(("同一份契約 → 放行", ok))

    # 尚無快照時要說清楚「這不是相容性通過」
    ok, msg, _ = QJ.judge("api-contract", json.dumps(_contract()), {"api_contract": {}})
    checks.append(("尚無快照時放行", ok))
    checks.append(("但明說這不是相容性通過", "不是" in msg and "相容性通過" in msg))

    cases = [
        ("模組消失", _contract(mods={}), False),
        ("公開函式消失", _contract(mods={"m.py": {}}), False),
        ("必填參數消失",
         _contract(mods={"m.py": {"f": {"params": ["b"], "required": ["b"],
                                        "kwonly": [], "varargs": False, "kwargs": False}}}), False),
        ("新增必填參數",
         _contract(mods={"m.py": {"f": {"params": ["a", "b", "c"], "required": ["a", "c"],
                                        "kwonly": [], "varargs": False, "kwargs": False}}}), False),
        ("CLI 旗標消失", _contract(flags=["--chg"]), False),
        # 新增不該擋:加函式、加旗標、把必填改成有預設值
        ("新增公開函式",
         _contract(mods={"m.py": {"f": {"params": ["a", "b"], "required": ["a"],
                                        "kwonly": [], "varargs": False, "kwargs": False},
                                  "g": {"params": [], "required": [],
                                        "kwonly": [], "varargs": False, "kwargs": False}}}), True),
        ("新增旗標", _contract(flags=["--chg", "--repo", "--new"]), True),
        ("必填改為有預設值",
         _contract(mods={"m.py": {"f": {"params": ["a", "b"], "required": [],
                                        "kwonly": [], "varargs": False, "kwargs": False}}}), True),
    ]
    for name, cur, want in cases:
        ok, msg, _ = QJ.judge("api-contract", json.dumps(cur), base)
        checks.append((f"契約[{name}] → {'放行' if want else '擋下'}", ok is want))

    ok, msg, _ = QJ.judge("api-contract", json.dumps(_contract(mods={})), base)
    checks.append(("破壞時指出會在執行期才炸", "執行期" in msg))
    checks.append(("破壞時指出要更新快照需授權", "指名授權" in msg))
    ok, msg, _ = QJ.judge("api-contract", "不是 JSON", base)
    checks.append(("壞產物擋下", not ok))
    checks.append(("壞產物不得聲稱通過", not any(a in msg for a in AFFIRMATIVE)))


def t_fuzz_judge(checks):
    """屬性測試的判讀。"""
    ok, msg, _ = QJ.judge("property-fuzz",
                          json.dumps({"cases": 100, "targets": ["a"], "failures": [],
                                      "seed": 1}), {})
    checks.append(("無崩潰 → 放行", ok))
    checks.append(("訊息帶 seed 供重現", "seed=1" in msg))

    ok, msg, _ = QJ.judge("property-fuzz", json.dumps(
        {"cases": 100, "seed": 1, "targets": ["p"],
         "failures": [{"target": "p", "exception": "IndexError: x", "input_repr": "'aa'"}]}), {})
    checks.append(("有崩潰 → 擋下", not ok))
    checks.append(("列出目標與例外", "p" in msg and "IndexError" in msg))
    checks.append(("說明崩潰與正確擋下分不開", "分不開" in msg))

    # 跑 0 次而回報 0 個失敗是恆真回報,與沒跑過等價
    ok, msg, _ = QJ.judge("property-fuzz",
                          json.dumps({"cases": 0, "failures": [], "seed": 1}), {})
    checks.append(("0 次呼叫不算通過", not ok))
    checks.append(("並說明那是沒跑過", "沒跑過" in msg))

    ok, msg, _ = QJ.judge("property-fuzz", json.dumps({}), {})
    checks.append(("缺欄位擋下", not ok))


def t_red_reachable(checks):
    """**紅燈可達性**:0 個失敗與引擎壞掉,在輸出上完全一樣(KN-001)。"""
    def fragile(text):
        return text.split(":")[1]        # 大多數輸入都會 IndexError

    r = FZ.run_fuzz([("fragile", fragile)], ["a:b"], 30, 1)
    checks.append(("引擎抓得到會炸的目標", len(r["failures"]) > 0))
    checks.append(("失敗紀錄帶目標名", r["failures"] and r["failures"][0]["target"] == "fragile"))
    checks.append(("失敗紀錄帶輸入供重現", r["failures"] and r["failures"][0]["input_repr"]))
    checks.append(("失敗紀錄帶例外型別",
                   r["failures"] and "Error" in r["failures"][0]["exception"]))

    # 不會炸的目標不該產生偽陽性
    r2 = FZ.run_fuzz([("safe", lambda t: len(t))], ["a:b"], 30, 1)
    checks.append(("安全的目標不產生偽陽性", r2["failures"] == []))
    checks.append(("同一 seed 可重現",
                   FZ.run_fuzz([("safe", lambda t: len(t))], ["a:b"], 5, 7)["cases"]
                   == FZ.run_fuzz([("safe", lambda t: len(t))], ["a:b"], 5, 7)["cases"]))
    # 變異器要真的改動輸入,否則等於只餵了種子
    import random
    rnd = random.Random(3)
    seeds = ["### Tasks\n- [ ] T1. x\n"]
    muts = {FZ.mutate(rnd, seeds[0]) for _ in range(40)}
    checks.append(("變異器產出多樣輸入", len(muts) > 10))

    # --- 讀檔型目標也要紅可達(CHG-20260808-01)-----------------------------
    # 那一類原本**在目標格式裡表達不出來**(引擎介面是 `fn(text)`,
    # 而 `_load_vocab` 吃的是路徑),所以是靠轉接器接進來的。
    # 轉接器最可能的失效是**變成裝飾品**:fixture 沒建對 → 被測分支提早返回 →
    # 每一輪都「0 失敗」,而它其實什麼都沒測。所以這裡分開驗兩件事:
    #   (a) 透過轉接器,會炸的解析器仍然抓得到;
    #   (b) 轉接器真的把那段文字送進了檔案(不是送了空字串)。
    import shutil
    import tempfile
    seen_text = []

    def via_file(parser):
        def call(text):
            d = Path(tempfile.mkdtemp(prefix="rr-fz-"))
            try:
                (d / "vocabulary.json").write_text(text, encoding="utf-8", errors="replace")
                return parser(d)
            finally:
                shutil.rmtree(d, ignore_errors=True)
        return call

    def fragile_reader(kdir):
        body = (kdir / "vocabulary.json").read_text(encoding="utf-8")
        seen_text.append(body)
        return body.split(":")[1]        # 大多數輸入都會 IndexError

    rf = FZ.run_fuzz([("fragile_path", via_file(fragile_reader))], ["a:b"], 30, 1)
    checks.append(("轉接器下,會炸的讀檔型目標仍抓得到", len(rf["failures"]) > 0))
    checks.append(("轉接器確實把變異文字寫進了檔案(不是空字串)",
                   bool(seen_text) and any(s for s in seen_text)))
    checks.append(("讀檔型失敗紀錄帶目標名",
                   rf["failures"] and rf["failures"][0]["target"] == "fragile_path"))


def t_fuzz_scope(checks):
    """**誰在射程內、處置對不對,都由證據回答**(CHG-20260808-01 建立;-03 改為推導)。

    第一版的清冊是人依函式名批次蓋的,而 lint 只驗「值合不合法」——
    39 條非目標處置裡 7 條是錯的,6 條落在同一格(`thin-wrapper`,
    它的判準與入選條件直接衝突)。所以現在處置由證據推導,宣告不一致就擋。
    """
    import importlib.util
    from lib import fuzz_scope as FS

    spec = importlib.util.spec_from_file_location(
        "rpf", REPO / ".github" / "run_property_fuzz.py")
    rpf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rpf)
    targeted = {n for n, _ in rpf.TARGETS}

    mods = ([REPO / "plugins" / "ai-sdlc-suite" / "mcp" / "ai_sdlc_mcp.py",
             SCRIPTS / "doc_integrity_check.py"]
            + sorted((SCRIPTS / "lib").glob("*.py")))
    found = FS.scan(mods)
    inv = FS.load_inventory()

    checks.append((f"掃描找得到解析器(實得 {len(found)} 個)", len(found) > 20))
    checks.append((f"清冊非空且讀得到(實得 {len(inv)} 條)",
                   bool(inv) and "__unreadable__" not in inv))
    probs = FS.reconcile(found, inv, targeted)
    checks.append(("掃描與清冊對得上" + (f" — {probs[0].splitlines()[0]}" if probs else ""),
                   not probs))

    # --- 判準必須跟得上現實 ------------------------------------------------
    # 三次都是被「**已經在目標清單裡的東西掃不出來**」抓到的:
    #   第一版只認 `re.match`   → 漏掉主流的 `TASK_RE.match`(11 個目標掃不到)
    #   第二版漏掉 `ast.parse`  → 漏掉 ratchet.test_metrics
    #   第三版漏掉迭代出來的 pattern → check_secrets 被推成「只讀不解析」
    # 判準比現實弱時,棘輪會漏掉下一個新解析器,而它不會抗議。
    for name in ("plan.parse_tasks", "ratchet.test_metrics", "doc_integrity_check.check_secrets"):
        checks.append((f"判準掃得到 {name}", name in found))
    checks.append(("check_secrets 被認出有 regex(迭代出來的 pattern 也算)",
                   "regex" in (found.get("doc_integrity_check.check_secrets")
                               or FS.Evidence((), (), False)).parses))

    # --- 四種處置都要真的發生過 --------------------------------------------
    # 一個從不發生的分類,與這個分類不存在分不出來(KN-001)。
    # 第一版的 `repo-asset` 推導出 **0 條**——接收者是區域變數 `p`,
    # 而判準沒有追賦值。這條斷言就是為了讓那種死分支自己叫出來。
    # **`registered-gap` 要分開判**(CHG-20260810-04)。另外三種是**由證據推導**的,
    # 清冊上一條都沒有就代表推導分支是死的——那正是本斷言要抓的。
    # 但 `registered-gap` 不是推導出來的結論,是「還沒做」的人為宣告,
    # **它歸零是目標本身**(待補項 #25 收尾)。拿「清冊上有沒有」去要求它,
    # 等於規定這個 repo 永遠得留一條沒做完的——**那會讓這道斷言懲罰成功**。
    #
    # 原本的意圖(死分支要自己叫)照樣守住,只是改成問對的問題:
    # 不問「清冊上有沒有」,問「這條推導路徑還走得到嗎」。
    DERIVED = FS.VALID_DISPOSITIONS - {"registered-gap"}
    used = {(v or {}).get("disposition") for v in inv.values()}
    missing = sorted(DERIVED - used)
    checks.append((f"推導型的三種處置在實際清冊上都出現過(缺:{missing or '無'})", not missing))
    checks.append(("registered-gap 的推導分支仍可達(不靠清冊上有沒有)",
                   FS.derive("probe.fn", FS.Evidence(("json.loads",), (), False), set())
                   == "registered-gap"))

    # --- 推導比對抓得到「合法但錯」的宣告 ----------------------------------
    # 這是本次新增的那一道判斷,也是唯一會去看「處置對不對」的一道。
    # 用 REVIEW 實際找到的錯誤條目當 fixture,不是編出來的。
    for key, wrong in (("interaction.required", FS.READS_ONLY),
                       ("profile.load_profile", FS.REPO_ASSET),
                       ("mcp._search_one", FS.READS_ONLY)):
        if key not in inv:
            checks.append((f"fixture 條目 {key} 仍在清冊內", False))
            continue
        bad = {k: dict(v) for k, v in inv.items()}
        bad[key] = {"disposition": wrong}
        hit = [p for p in FS.reconcile(found, bad, targeted) if p.startswith(f"{key}:")]
        checks.append((f"宣告「{wrong}」與證據不符 → 擋下({key})", bool(hit)))
        checks.append((f"擋下訊息要列出證據({key})",
                       bool(hit) and "證據" in hit[0]))

    # --- 順序:真實資料上互斥,所以用**合成**證據釘住定義 -------------------
    # CHG-20260808-03 的設計說明原本寫「順序寫錯會讓 plan.read_chg 被誤推成 gap」,
    # 而**實測推翻了它**:對調順序,69 條裡 0 條改變答案。
    # 不能假裝一個沒被觀察到的差別存在;但也不能因此讓順序變成未定義。
    synth = FS.Evidence(parses=(), reads=("SOME_REPO_CONST",), repo_paths=True)
    checks.append(("合成證據:只讀不解析 + 讀 repo 常數 → reads-only(順序有定義)",
                   FS.derive("x.y", synth, set()) == FS.READS_ONLY))
    real_overlap = [k for k, ev in found.items() if ev.repo_paths and not ev.interprets]
    checks.append((f"真實資料上兩條謂詞互斥(實得重疊 {len(real_overlap)} 條)",
                   not real_overlap))

    # --- 其餘護欄 ----------------------------------------------------------
    gap = next((k for k, v in inv.items()
                if (v or {}).get("disposition") == FS.REGISTERED_GAP), None)
    if gap:
        noreg = {k: dict(v) for k, v in inv.items()}
        noreg[gap] = {"disposition": FS.REGISTERED_GAP}
        checks.append(("registered-gap 沒帶待補項編號 → 擋下",
                       bool(FS.reconcile(found, noreg, targeted))))
    trimmed = {k: v for k, v in inv.items() if k != sorted(inv)[0]}
    checks.append(("清冊少一條 → 對帳擋下",
                   bool(FS.reconcile(found, trimmed, targeted))))
    checks.append(("清冊讀不到 → 對帳擋下",
                   bool(FS.reconcile(found, {"__unreadable__": {}}, targeted))))


def _rpf():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rpf", REPO / ".github" / "run_property_fuzz.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 每一支對應一段**該被抓到的壞內容**。用「會被抓到」而不是「沒炸」當判準,
# 是因為轉接器最可能的失效是變成裝飾品:fixture 建不對 → 被測分支提早返回 →
# 每輪都 0 失敗,而它其實什麼都沒測(CHG-20260808-01 踩過,-02 的兩個早退陷阱同形)。
DOC_BAD_INPUT = {
    "check_chg_acc": "# CHG-20260808-99\n\n狀態:已實作\n",
    "check_fields": "# CHG-20260808-99\n\n狀態:已實作\n",
    "check_recurrence_field": "# CHG-1\n\n- Skill: ai-sdlc v1.30.0\n\n沒有那一欄。\n",
    # 值刻意寫成一眼看得出是假的:第一版用了 AWS 文件裡的範例鍵,
    # 而 static_check 同時判 `aws-access-key` 與 `credential-assignment` 兩條。
    # 拿掉那個前綴之後豁免由兩條降為一條——**能不豁免的就不要豁免**。
    "check_secrets": 'api_key: "NOT-A-REAL-KEY-0123456789"\n',
    "check_regression_pointers": "迴歸集:`tests/does_not_exist.py`\n",
    "check_uncovered_registered": "# ACC\n\n## 未涵蓋\n\n沒有任何追蹤點。\n",
    "check_directive_shape": "## KN-099 — x\n\n- tier:**directive**\n",
    "check_knowledge_index": "# INDEX\n\n| KN-999 | x |\n",
    "check_coverage_registry": "## 未涵蓋\n\n| A-1 | x |\n| A-1 | y |\n",
    "check_entry_point": "# CLAUDE.md\n\n## 一\n\n見 AGENTS.md\n\n- a\n- b\n- c\n- d\n",
    "check_commits": "abc1234\t沒有編號的 commit\n",
}


def t_doc_fuzz_scope(checks):
    """待補項 #24:讀治理文件的 11 支要在射程內,而且轉接器不得是裝飾品。"""
    targets = dict(_rpf().TARGETS)
    for short, bad in DOC_BAD_INPUT.items():
        name = f"doc_integrity_check.{short}"
        fn = targets.get(name)
        checks.append((f"{short} 在 fuzz 目標內", fn is not None))
        if fn is None:
            continue
        try:
            out = fn(bad)
        except Exception as e:                     # noqa: BLE001
            checks.append((f"{short} 的轉接器本身不得炸掉({type(e).__name__})", False))
            continue
        checks.append((f"{short} 轉接器紅可達:壞內容真的被抓到", bool(out)))

    # 早退陷阱要被釘住:日期早於前瞻起點時**應該**沉默——
    # 這條同時證明上面那條紅可達不是碰巧,而是檔名日期真的有被讀到。
    import shutil
    import tempfile
    import doc_integrity_check as DIC
    d = Path(tempfile.mkdtemp(prefix="t24-"))
    try:
        p = d / "docs" / "ai-sdlc-suite" / "acceptance" / "ACC-20260101-99.md"
        p.parent.mkdir(parents=True)
        p.write_text(DOC_BAD_INPUT["check_uncovered_registered"], encoding="utf-8")
        checks.append(("前瞻起點之前的 ACC 不追殺(fixture 用錯日期=白跑)",
                       DIC.check_uncovered_registered(d) == []))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # `check_commits` 的注入點:注入路徑與出貨路徑必須是同一條。
    # 不給 runner 時要真的走 git —— 否則注入的是一條測試專用的假路。
    calls = []
    d2 = Path(tempfile.mkdtemp(prefix="t24g-"))
    try:
        (d2 / ".git").mkdir()

        def spy(*a):
            calls.append(a)
            return "abc1234\tCHG-20260809-02: x\n"
        out = DIC.check_commits(d2, "HEAD~1", runner=spy)
        checks.append(("注入 runner 時不呼叫 git", bool(calls)))
        checks.append(("引用了 CHG 的 commit 不被回報", out == []))
        real = DIC.check_commits(d2, "HEAD~1")
        checks.append(("不給 runner 時走真的 git(非 git repo → 有回報)", real != []))
    finally:
        shutil.rmtree(d2, ignore_errors=True)

    # 測試檔不得放在測試搜尋掃不到的目錄:`run_tests.sh` 找的是 `find skills plugins`。
    # 本筆原訂把轉接器測試放 `.github/`,那份測試會**一次都不會跑而且沒有人會抗議**。
    # 排除條件對**相對路徑**判:本 repo 常在 `<root>/.claude/worktrees/<名>/` 的
    # worktree 執行,絕對路徑裡人人都有 `.claude`——對絕對路徑判會把每一個檔案都排掉,
    # 而「沒有漏網的」與「一個都沒掃到」在斷言上長得一模一樣。
    # **這個誤判真的發生過**:本筆第一版就是這樣寫的,是行為規格那條把它叫出來的。
    rels = [p.relative_to(REPO) for p in REPO.rglob("test_*.py")]
    rels = [r for r in rels if ".claude" not in r.parts]
    checks.append((f"掃得到 test_*.py(實得 {len(rels)} 份)", len(rels) > 20))
    # 判準是「有沒有載具會執行它」,不是「在不在某個目錄」。本 repo 有兩個載具:
    #   · `run_tests.sh` —— `find skills plugins`
    #   · `behave`       —— `features/steps/`(那裡有一份叫 test_ratchet_steps.py)
    # 第一版寫成「必須在 skills/plugins 底下」,而那條規則會把一份**真的有在跑**的
    # 步驟檔判成漏網。誤報會逼人關掉整道檢查(上一輪才為同一件事修過判準)。
    stray = [r.as_posix() for r in rels
             if r.parts[0] not in ("skills", "plugins")
             and r.parts[:2] != ("features", "steps")]
    checks.append((f"每份 test_*.py 都有載具會執行(無載具者:{stray or '無'})", not stray))


def main() -> int:
    checks: list[tuple[str, bool]] = []
    t_contract(checks)
    t_fuzz_judge(checks)
    t_red_reachable(checks)
    t_fuzz_scope(checks)
    t_doc_fuzz_scope(checks)

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
