#!/usr/bin/env python3
"""governance_health.py 的斷言(CHG-20260803-01 T8)。stdlib-only,三平台一致。

這支**刻意恆回 exit 0**(報告,非閘門)——所以退出碼完全不能拿來驗它。
唯一能驗的是**數字對不對**:給一個已知組成的 fixture 帳本,報告的統計必須等於
事先算好的答案。若只驗 exit 0,這支腳本就算把所有數字算成 0 也會「通過」。

Run: python3 test_governance_health.py → exit 0 全過。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).with_name("governance_health.py")
sys.path.insert(0, str(SCRIPT.parent))
import governance_health as GH  # noqa: E402


def chg(num, status, risk="低", extra=""):
    return f"""# CHG-2026010{num}-01 — fixture

- 日期:2026-01-0{num}(UTC+0)| 風險分級:{risk} | 實作者:fixture
{extra}
## 狀態
{status}
"""


def build(chgs, accs=()):
    d = Path(tempfile.mkdtemp())
    (d / "docs" / "changes").mkdir(parents=True)
    (d / "docs" / "acceptance").mkdir(parents=True)
    for i, text in enumerate(chgs, 1):
        (d / "docs" / "changes" / f"CHG-2026010{i}-01.md").write_text(text, encoding="utf-8")
    for i, text in enumerate(accs, 1):
        (d / "docs" / "acceptance" / f"ACC-2026010{i}-01.md").write_text(text, encoding="utf-8")
    return d


def run(d, *extra):
    """**In-process 呼叫,不是 subprocess。**

    這一份原本每一條都走 `subprocess.run`,而那有一個看不見的後果:
    **coverage 量不到子行程**,於是 `main()` 的 197 個 statement 在報告上永遠是
    「未覆蓋」——即使它每一條斷言都真的跑過它。覆蓋率因此低報,而低報的
    覆蓋率與真的沒測在數字上分不出來(KN-001 的一種)。

    改成 in-process 之後測的是同一件事,只是量得到了;另外保留一個
    `run_as_script()`,因為「當成腳本跑得起來」是 in-process 呼叫證明不了的
    另一件事(shebang、`if __name__`、argv 處理)。
    """
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = GH.main(["governance_health.py", "--repo", str(d), *extra])
    return rc, buf.getvalue()


def run_as_script(d, *extra):
    """真的當成腳本跑一次——這條證明的是 in-process 呼叫證明不了的那一半。"""
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(d), *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    checks = []

    # 已知組成:1 已驗收、1 待驗收(懸空)、1 暫停、1 草稿
    repo = build([chg(1, "已驗收(見 ACC)"), chg(2, "已實作,待驗收"),
                  chg(3, "暫停——等上游"), chg(4, "草稿")],
                 accs=["# ACC-20260101-01\n\n- 驗收者:fixture\n- 結論:通過\n- 風險分級:低\n"])

    rc, out = run(repo, "--json")
    checks.append(("--json → exit 0", rc == 0))
    data = None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        pass
    checks.append(("--json 輸出可解析為 JSON", data is not None))

    if data is not None:
        # 逐格斷言分類計數。fixture 的組成是事先決定的:
        # 1 已驗收 / 1 待驗收 / 1 暫停 / 1 草稿——報告必須完全複現這個分佈。
        st = data.get("chg_status", {})
        for key, want in (("accepted", 1), ("implemented", 1), ("paused", 1), ("draft", 1)):
            checks.append((f"chg_status.{key} = {want}", st.get(key) == want))
        checks.append(("四類加總 = 4(沒有 CHG 被漏數或重複數)",
                       sum(st.get(k, 0) for k in ("accepted", "implemented", "paused",
                                                  "draft", "unknown")) == 4))
        # 懸空驗收:待驗收那一筆且無對應 ACC → 必須被點名(這正是本腳本存在的理由)
        hanging = json.dumps(data.get("hanging_acceptance", []), ensure_ascii=False)
        checks.append(("懸空驗收點名 CHG-20260102-01", "CHG-20260102-01" in hanging))
        checks.append(("已驗收的那筆不得被誤列為懸空", "CHG-20260101-01" not in hanging))
        # 暫停清單長度 1(暫停是合法 WIP,要列出來但不算破損)
        checks.append(("暫停清單長度 = 1", len(data.get("paused", [])) == 1))

    # 人讀模式同樣 exit 0 且有內容
    rc, out = run(repo)
    checks.append(("人讀報告 → exit 0 且非空", rc == 0 and len(out.strip()) > 0))

    # 恆為報告、非閘門:即使帳本一團糟(全部懸空)仍須 exit 0
    messy = build([chg(1, "已實作,待驗收"), chg(2, "已實作,待驗收")])
    rc, _ = run(messy)
    checks.append(("帳本全懸空仍 exit 0(報告非閘門——要擋請用 doc_integrity_check)", rc == 0))

    # 空 repo 不得崩潰
    rc, _ = run(Path(tempfile.mkdtemp()))
    checks.append(("空目錄不崩潰 → exit 0", rc == 0))

    # --lease-days 參數可接受(停滯 claim 判定天數)
    rc, _ = run(repo, "--lease-days", "2")
    checks.append(("--lease-days 可接受", rc == 0))

    # 沒有帳本時不得印「健康」(CHG-20260805-04):一份全是 0 的報告
    # 與「檢查過而且沒問題」長得一樣。
    import tempfile as _tf
    bare = Path(_tf.mkdtemp())
    _, bare_out = run(bare)
    checks.append(("沒有帳本 → 明說不適用", "不適用" in bare_out))
    checks.append(("沒有帳本 → 不得印「(健康)」", "(健康)" not in bare_out))
    # 當成腳本跑一次:in-process 證明不了 shebang / __main__ / argv 這一段
    rc_s, out_s = run_as_script(bare)
    checks.append(("當成腳本跑得起來(退出碼 0)", rc_s == 0))
    checks.append(("腳本模式的輸出與 in-process 一致", "不適用" in out_s))

    # --- knowledge 階梯健康(CHG-20260809-01)-------------------------------
    #
    # 這一組的由來:那幾個數字被印了很久,**後面從來沒有判定**,而輸出還附了一句
    # 斷言式的「shallow 長期不升不退=該 review」。本 skill 的作者連續四輪把它讀成
    # 觸發中的警告。**一個沒有判定在後面的數字,遲早會被讀成一個判定。**
    def _e(tier, applied, seen=1, last="2026-08-01", kid="KN-X"):
        return {"id": kid, "tier": tier, "seen": seen, "applied": applied,
                "last_applied": last, "where": "synthetic"}

    # --- 三個純函式:整份報告的數字都建立在它們上面,而它們沒有直接單元測試 ---
    #
    # 覆蓋率棘輪指出這一段時,指的不是「缺幾行」——是**整份報告賴以成立的分類邏輯
    # 從來沒有被直接驗過**。補在這裡的每一條都是行為,不是行號。

    # `classify_chg`:先看「## 狀態」節,退回全文。這個順序有實質後果——
    # 一份內文提到「草稿」但狀態寫「已驗收」的 CHG,必須算已驗收。
    checks.append(("classify:狀態節優先於內文",
                   GH.classify_chg("# C\n\n草稿階段的討論\n\n## 狀態\n\n已驗收\n") == "accepted"))
    checks.append(("classify:沒有狀態節時退回全文",
                   GH.classify_chg("# C\n\n本筆已驗收\n") == "accepted"))
    checks.append(("classify:兩段都判不出 → unknown(不得猜一個)",
                   GH.classify_chg("# C\n\n完全沒有狀態字樣\n") == "unknown"))

    # `acc_conclusion`:**「未通過」這個字串包含「通過」**。
    # 程式碼先判未通過再判通過——**順序一反,每一份「未通過」都會變成「通過」**,
    # 而那是一個會靜默翻轉結論的錯,報告上完全看不出來。
    checks.append(("acc:未通過**不得**被讀成通過(子字串陷阱)",
                   GH.acc_conclusion("結論:未通過,需回修") == "fail"))
    checks.append(("acc:通過", GH.acc_conclusion("結論:通過") == "pass"))
    checks.append(("acc:部分通過", GH.acc_conclusion("結論:部分通過") == "partial"))
    checks.append(("acc:沒有結論行 → unknown", GH.acc_conclusion("# 沒有結論") == "unknown"))
    checks.append(("acc:有結論行但看不懂 → unknown",
                   GH.acc_conclusion("結論:再看看") == "unknown"))

    # `newest_date`:不合法的日期不得被當成日期(月份 13、日 32)
    checks.append(("date:取最新的一個",
                   str(GH.newest_date("2026-01-01 與 2026-08-05")) == "2026-08-05"))
    checks.append(("date:月份 13 不算日期", GH.newest_date("2026-13-01") is None))
    checks.append(("date:沒有日期回 None", GH.newest_date("沒有數字") is None))

    # --- 解析層:單檔與**拆檔**兩種模式都要驗 ------------------------------
    #
    # 拆檔模式(`entries/*.json`)**本 repo 完全不用**,但它是出貨給被治理專案的
    # 程式碼——一段出貨了卻從沒被執行過的路徑。覆蓋率棘輪抓到它的那一刻,
    # 才是它第一次被真的跑起來。
    import tempfile as _tf2
    kdir = Path(_tf2.mkdtemp()) / "knowledge"
    (kdir / "entries").mkdir(parents=True)
    (kdir / "knowledge.md").write_text(
        "# k\n\n## KN-101 — 單檔模式的條目\n\n- tier:shallow\n"
        "- 計數:seen 2 / applied 4 / last-applied 2026-08-01\n", encoding="utf-8")
    (kdir / "entries" / "KN-202.json").write_text(json.dumps(
        {"id": "KN-202", "tier": "deep", "rule": "r", "tags": ["t"],
         "status": "active", "counters": {"seen": 3, "applied": 5,
                                          "last-applied": "2026-08-02"}},
        ensure_ascii=False), encoding="utf-8")
    (kdir / "entries" / "broken.json").write_text("{ not json", encoding="utf-8")
    (kdir / "vocabulary.json").write_text('{"t": ["別名"]}', encoding="utf-8")
    # **合法 JSON 但不是條目**——`json.loads` 成功不代表拿到預期的形狀。
    # 那正是 CHG-20260808-01 一次抓到 7 個同族崩潰的根因,不在這裡再犯一次。
    (kdir / "entries" / "notdict.json").write_text("[1, 2, 3]", encoding="utf-8")
    (kdir / "entries" / "noid.json").write_text('{"tier": "deep"}', encoding="utf-8")
    (kdir / "INDEX.md").write_text("# INDEX\n\n## KN-999 — 不該被當成條目\n", encoding="utf-8")

    parsed = {e["id"]: e for e in GH.parse_knowledge_entries([kdir], GH.read)}
    checks.append(("解析:單檔模式讀得到條目", "KN-101" in parsed))
    checks.append(("解析:**拆檔模式**(entries/*.json)讀得到條目", "KN-202" in parsed))
    checks.append(("解析:壞掉的 JSON 跳過而非崩潰", "broken" not in parsed))
    checks.append(("解析:合法 JSON 但不是物件 → 跳過(loads 成功 ≠ 形狀對)",
                   not any(str(k).startswith("[") for k in parsed)))
    checks.append(("解析:JSON 沒有 id → 跳過(不得產生一條無名條目)",
                   None not in parsed and "" not in parsed))
    checks.append(("解析:INDEX.md 不得被當成條目來源", "KN-999" not in parsed))
    # vocabulary.json 不是條目——把它算進來會讓每個帳本平白多一條「缺計數欄」
    checks.append(("解析:vocabulary.json 不得被當成條目",
                   not any("vocab" in str(k).lower() for k in parsed)))
    if "KN-101" in parsed:
        e101 = parsed["KN-101"]
        checks.append(("解析:單檔模式的計數欄逐項讀對",
                       (e101["tier"], e101["seen"], e101["applied"],
                        e101["last_applied"]) == ("shallow", 2, 4, "2026-08-01")))
    if "KN-202" in parsed:
        e202 = parsed["KN-202"]
        checks.append(("解析:拆檔模式的 counters 逐項讀對",
                       (e202["tier"], e202["seen"], e202["applied"],
                        e202["last_applied"]) == ("deep", 3, 5, "2026-08-02")))
    # 缺欄回 None 而不是 0:「沒寫」與「寫了 0」的後續處置不同
    kdir2 = Path(_tf2.mkdtemp()) / "knowledge"
    kdir2.mkdir(parents=True)
    (kdir2 / "knowledge.md").write_text(
        "# k\n\n## KN-303 — 沒有計數欄\n\n- tier:shallow\n", encoding="utf-8")
    p303 = {e["id"]: e for e in GH.parse_knowledge_entries([kdir2], GH.read)}["KN-303"]
    checks.append(("解析:缺欄回 None 而非 0",
                   p303["applied"] is None and p303["last_applied"] is None))
    # 這條真的會被 ladder_health 說話——解析與判定接得起來,不是各自為政
    checks.append(("解析→判定 接得起來(KN-303 缺欄要被說)",
                   any("KN-303" in p for p in GH.ladder_health([p303]))))
    # 而 KN-101 的 applied=4 已達門檻,也要被說
    if "KN-101" in parsed:
        checks.append(("解析→判定 接得起來(KN-101 applied=4 要被說該升)",
                       any("KN-101" in p and "升級門檻" in p
                           for p in GH.ladder_health([parsed["KN-101"]]))))

    # 升級門檻的**邊界兩側**都要驗:只驗一側證明不了門檻在哪
    for applied, want in ((GH.PROMOTE_APPLIED - 1, False),
                          (GH.PROMOTE_APPLIED, True),
                          (GH.PROMOTE_APPLIED + 1, True)):
        hit = any("升級門檻" in p for p in GH.ladder_health([_e("shallow", applied)]))
        checks.append((f"階梯:shallow applied={applied} → {'該升' if want else '沉默'}",
                       hit is want))

    # `seen` **只對 shallow 要求**。對 deep 也要求會產生 4 條誤報(實測),
    # 而誤報會逼人關掉整道檢查——本輪前一筆才剛為此修過一次判準。
    checks.append(("階梯:deep 缺 seen 不得誤報",
                   not GH.ladder_health([_e("deep", 7, seen=None)])))
    checks.append(("階梯:shallow 缺 seen 要說話",
                   any("seen" in p for p in GH.ladder_health([_e("shallow", 2, seen=None)]))))
    checks.append(("階梯:DIR 不走 KN 的升級梯",
                   not GH.ladder_health([_e("directive", 99, seen=None, kid="DIR-1")])))
    for field, ent in (("applied", _e("shallow", None)),
                       ("last-applied", _e("shallow", 2, last=None))):
        checks.append((f"階梯:缺 {field} 要說話",
                       any(field in p for p in GH.ladder_health([ent]))))
    # 正常條目必須**沉默**——一個永遠說話的檢查會被連同真訊號一起忽略
    checks.append(("階梯:三欄齊全且未達門檻 → 沉默",
                   not GH.ladder_health([_e("shallow", 2)])))

    # 措辭不得回退成斷言句。舊版那句每次都印,而它讀起來像「它現在就不升不退」。
    repo_root = SCRIPT.resolve().parents[3]
    _, r2_out = run(repo_root)
    checks.append(("輸出不得含舊的斷言措辭",
                   "長期不升不退" not in r2_out))
    checks.append(("階梯說明仍在(不是把提示刪掉了事)",
                   "knowledge 階梯" in r2_out))
    # 規範是門檻的唯一出處:改門檻要兩邊一起改,所以這裡釘住它引用的是規範的值
    checks.append((f"升級門檻引用規範值 3(實得 {GH.PROMOTE_APPLIED})",
                   GH.PROMOTE_APPLIED == 3))

    # --- 封存帳本不進階梯統計,但必須具名(CHG-20260810-02)---
    #
    # 這一組的重點是**兩個方向都驗**:封存的不進總數(否則總數混進不可能動的東西),
    # 而且封存的不會消失(否則就從「混淆」換成「隱藏」,同一個錯的另一面)。
    import tempfile as _tf3
    KN_LIVE = ("# knowledge\n\n## KN-100 — 活的\n\n- tier:shallow\n"
               "- 計數:seen 2 / applied 1 / last-applied 2026-01-01\n")
    KN_DEAD = ("# knowledge\n\n## KN-200 — 封存帳本裡的\n\n- tier:shallow\n"
               "- 計數:seen 5 / applied 1 / last-applied 2026-01-01\n")

    def build_two_ledgers(archived_reason_text):
        d = Path(_tf3.mkdtemp())
        for name, kn in (("live", KN_LIVE), ("dead", KN_DEAD)):
            (d / "docs" / name / "changes").mkdir(parents=True)
            (d / "docs" / name / "acceptance").mkdir(parents=True)
            (d / "docs" / name / "knowledge").mkdir(parents=True)
            (d / "docs" / name / "knowledge" / "knowledge.md").write_text(kn, encoding="utf-8")
        if archived_reason_text is not None:
            (d / "docs" / "dead" / ".archived").write_text(archived_reason_text,
                                                           encoding="utf-8")
        return d

    d_dead = build_two_ledgers("併入前的歷史帳本,唯讀保留。")
    _, out_dead = run(d_dead, "--json")
    kn = json.loads(out_dead)["knowledge"]
    checks.append(("封存帳本的 shallow 不進統計(2 條 → 只算 1)", kn["shallow"] == 1))
    checks.append(("封存條目仍被讀出來(不是被丟掉)",
                   any(e["id"] == "KN-200" for e in kn["archived_entries"])))
    checks.append(("封存的 shallow 具名出現在警告",
                   any("KN-200" in p for p in kn["ladder_problems"])))
    checks.append(("活的那條**沒有**被誤報成封存",
                   not any("KN-100" in p and "封存" in p for p in kn["ladder_problems"])))
    checks.append(("封存帳本連同理由一起報出來",
                   kn["archived_ledgers"] and "唯讀保留" in kn["archived_ledgers"][0]["reason"]))

    # 未宣告 / 空白宣告 → 一律當活的(KN-006 空白豁免;KN-004 倒向多檢查)
    for label, reason in (("沒有 .archived", None), (".archived 空白", "  \n ")):
        _, out_live = run(build_two_ledgers(reason), "--json")
        kn_live = json.loads(out_live)["knowledge"]
        checks.append((f"{label} → 兩本都算活的(shallow=2)", kn_live["shallow"] == 2))
        checks.append((f"{label} → 沒有封存警告",
                       not any("封存" in p for p in kn_live["ladder_problems"])))

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
