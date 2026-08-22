#!/usr/bin/env python3
"""doc_integrity_check.py 的斷言(CHG-20260803-01 T7)。stdlib-only,三平台一致。

方法:先造一個**乾淨的受治理 fixture repo**(必須 exit 0),再對每一項檢查
各做一次「只破壞這一項」的變體(必須 exit 1 且訊息指名該項)。
正例與反例成對——只有反例會讓「檢查根本沒在跑」看起來也像通過。

合法例外也要驗:CHG-lite(低風險+自驗)免 ACC、暫停/草稿不要求 ACC。
這三條若被誤擋,治理流程會逼人為了過閘而造假 ACC。

fixture 一律建在 tmpdir,不讀本 repo 帳本。
Run: python3 test_doc_integrity_check.py  → exit 0 全過,1 有失敗。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).with_name("doc_integrity_check.py")

CHG = """# CHG-20260101-01 — fixture 變更

- 日期:2026-01-01(UTF+0)| 分支:main | 風險分級:低 | 實作者:Claude(fixture)
- Commit/PR:(fixture)
- 重複性檢查:非重複——fixture
- Skill: ai-sdlc v1.18

## 修改指引
fixture 步驟。

## 狀態
已驗收(見 ../acceptance/ACC-20260101-01.md)。
"""

ACC = """# ACC-20260101-01 — fixture 驗收

- 驗收者:Claude(fixture)
- 風險分級:低
- 分支:main
- 對應變更:CHG-20260101-01

## 總結
- 結論:通過
"""

AGENTS = "# AGENTS.md — fixture 進入點\n1. 先讀 docs/。\n"


sys.path.insert(0, str(Path(__file__).resolve().parent))
from doc_integrity_check import ledger_roots as _ledger_roots  # noqa: E402


def build(chg=CHG, acc=ACC, agents=AGENTS, knowledge=True, extra=None):
    """造一個乾淨的受治理 repo;extra = {相對路徑: 內容} 追加或覆寫。"""
    d = Path(tempfile.mkdtemp())
    (d / "docs" / "changes").mkdir(parents=True)
    (d / "docs" / "acceptance").mkdir(parents=True)
    if chg is not None:
        (d / "docs" / "changes" / "CHG-20260101-01.md").write_text(chg, encoding="utf-8")
    if acc is not None:
        (d / "docs" / "acceptance" / "ACC-20260101-01.md").write_text(acc, encoding="utf-8")
    if agents is not None:
        (d / "AGENTS.md").write_text(agents, encoding="utf-8")
    if knowledge:
        (d / "docs" / "knowledge").mkdir(parents=True)
        (d / "docs" / "knowledge" / "knowledge.md").write_text("# knowledge\n\n## INDEX\n", encoding="utf-8")
    for rel, content in (extra or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


def run(repo, *extra):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=fixture",
                           "-c", "user.email=fixture@example.com", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def main() -> int:
    checks = []

    # 「擋下」必須是**乾淨的問題報告**,不是崩潰。
    # 崩潰同樣回退出碼 1,而 traceback 裡常常含有函式名 → 寬鬆的關鍵字比對會把
    # 「程式炸了」誤判為「正確擋下」。變異測試在這裡抓到一整批存活點:
    # 把 `return []` 改成 `return None` 會讓 `problems += None` 拋 TypeError,
    # 而舊版斷言照樣通過。故一律加驗「輸出不含 Traceback」。
    def _no_crash(out):
        return "Traceback" not in out and "Error:" not in out.replace("❌", "")

    def expect_clean(name, repo, *extra):
        rc, out = run(repo, *extra)
        checks.append((name, rc == 0 and _no_crash(out),
                       ["崩潰" if not _no_crash(out) else (out.strip().splitlines()[-1:] or [""])[0]]))

    def expect_flag(name, repo, needle, *extra):
        rc, out = run(repo, *extra)
        ok = rc == 1 and needle in out and _no_crash(out)
        detail = "崩潰(非乾淨報告)" if not _no_crash(out) else f"期望訊號:{needle}"
        checks.append((name, ok, [detail]))

    # ---------- 正例:乾淨 repo 必須 exit 0 ----------
    expect_clean("乾淨受治理 repo → exit 0", build())

    # ---------- 1) CHG↔ACC 連結 ----------
    expect_flag("已實作 CHG 缺 ACC → 擋", build(acc=None), "驗收懸空")
    # 合法例外三則(誤擋會逼人造假 ACC)
    expect_clean("CHG-lite(低風險+自驗)免獨立 ACC",
                 build(chg=CHG.replace("已驗收(見 ../acceptance/ACC-20260101-01.md)。",
                                       "已驗收——自驗(低風險白名單)。"), acc=None))
    expect_clean("狀態=暫停(合法 WIP)不要求 ACC",
                 build(chg=CHG.replace("已驗收(見 ../acceptance/ACC-20260101-01.md)。", "暫停"), acc=None))
    expect_clean("狀態=草稿不要求 ACC",
                 build(chg=CHG.replace("已驗收(見 ../acceptance/ACC-20260101-01.md)。", "草稿"), acc=None))
    # 高風險已實作但無審議判決
    expect_flag("高風險已實作缺審議判決 → 擋",
                build(chg=CHG.replace("風險分級:低", "風險分級:高")), "審議")

    # ---------- 2) 模板欄位 lint ----------
    expect_flag("CHG 缺「## 狀態」→ 擋",
                build(chg=CHG.replace("## 狀態", "## 收尾")), "狀態")
    expect_flag("CHG 缺實作者 → 擋",
                build(chg=CHG.replace("| 實作者:Claude(fixture)", "")), "實作者")
    expect_flag("ACC 缺驗收者 → 擋",
                build(acc=ACC.replace("- 驗收者:Claude(fixture)", "")), "驗收者")
    expect_flag("ACC 缺結論 → 擋",
                build(acc=ACC.replace("- 結論:通過", "- 心得:還行")), "結論")
    # --require-commit / --require-branch 為選用加嚴
    expect_flag("--require-commit 且缺 Commit/PR 欄 → 擋",
                build(chg=CHG.replace("- Commit/PR:(fixture)", "")), "Commit", "--require-commit")
    expect_clean("未加 --require-commit 時缺該欄不擋",
                 build(chg=CHG.replace("- Commit/PR:(fixture)", "")))
    # 逃生口必須真的能逃
    expect_clean("--no-field-lint 可略過欄位檢查",
                 build(chg=CHG.replace("## 狀態", "## 收尾")), "--no-field-lint")

    # ---------- 3) secrets 掃描 ----------
    for label, payload in (
        ("AWS key", "AKIA" + "A" * 16),
        ("GitHub token", "ghp_" + "a" * 36),
        ("private key", "-----BEGIN RSA PRIVATE KEY-----"),
        ("credential 指派", 'api_key = "abcdefghijklmno123"'),
    ):
        expect_flag(f"docs/ 含 {label} → 擋",
                    build(extra={"docs/notes.md": f"# notes\n\n{payload}\n"}), "secret")
    expect_clean("--no-secret-scan 可略過",
                 build(extra={"docs/notes.md": "AKIA" + "A" * 16}), "--no-secret-scan")

    # ---------- 4) 迴歸集指向腐爛 ----------
    expect_flag("regression.md 指向不存在的檔 → 擋",
                build(extra={"docs/acceptance/regression.md":
                             "- 條件 A:`tests/test_gone.py::test_x`\n"}), "腐爛")
    expect_clean("regression.md 指向存在的檔 → 過",
                 build(extra={"docs/acceptance/regression.md": "- 條件 A:`AGENTS.md`\n"}))

    # ---------- 5) root 進入點 ----------
    expect_flag("治理專案缺 AGENTS.md → 擋", build(agents=None), "AGENTS.md")
    expect_flag("CLAUDE.md 未指向 AGENTS.md → 擋",
                build(extra={"CLAUDE.md": "# 自己一套規則\n"}), "stub")
    expect_clean("CLAUDE.md 為指向 AGENTS.md 的 stub → 過",
                 build(extra={"CLAUDE.md": "見 AGENTS.md。\n"}))

    # ---------- 6) 知識庫先建 ----------
    expect_flag("治理專案缺 docs/knowledge/ → 擋", build(knowledge=False), "knowledge")

    # ---------- 7) 重複性檢查欄(v1.17 起前瞻適用)----------
    expect_flag("v1.18 CHG 缺重複性檢查欄 → 擋",
                build(chg=CHG.replace("- 重複性檢查:非重複——fixture\n", "")), "重複性檢查")
    expect_clean("v1.16 CHG 缺該欄不追溯(前瞻適用)",
                 build(chg=CHG.replace("- 重複性檢查:非重複——fixture\n", "")
                            .replace("ai-sdlc v1.18", "ai-sdlc v1.16")))

    # ---------- 8) knowledge 條目 fail-loud ----------
    expect_flag("條目 JSON 解析失敗 → 擋(不得靜默跳過)",
                build(extra={"docs/knowledge/entries/KN-001.json": "{ not json"}), "解析失敗")
    expect_flag("條目缺必填欄 → 擋",
                build(extra={"docs/knowledge/entries/KN-001.json":
                             json.dumps({"id": "KN-001", "tier": "shallow"})}), "KN-001")

    # ---------- 9) knowledge INDEX 交叉 ----------
    expect_flag("entries/ 存在但無 INDEX.md → 擋",
                build(extra={"docs/knowledge/entries/KN-001.md": "# KN-001\n"}), "INDEX")
    expect_flag("INDEX 未列出條目 → 擋",
                build(extra={"docs/knowledge/entries/KN-001.md": "# KN-001\n",
                             "docs/knowledge/INDEX.md": "# INDEX\n\n(空)\n"}), "INDEX")

    # ---------- 以下為變異測試指出的盲點補強(kill rate 62.4% → 目標 ≥90%)----------
    # 這批斷言不是「想到就加」,而是逐一對應存活變異體:每一條都對著一個
    # 「改掉這行、所有既有測試仍全綠」的位置。

    # knowledge 條目 schema 的每一格(原本只驗了解析失敗與缺必填欄)
    VOCAB = json.dumps({"verification": {}, "autopilot": {}}, ensure_ascii=False)
    def kn(**over):
        d = {"id": "KN-001", "tier": "shallow", "rule": "一句規則",
             "status": "observing", "tags": ["verification"]}
        d.update(over)
        return json.dumps(d, ensure_ascii=False)

    base_kn = {"docs/knowledge/vocabulary.json": VOCAB,
               "docs/knowledge/INDEX.md": "# INDEX\n\n| KN-001 |\n"}
    expect_clean("合格 knowledge 條目 → 過",
                 build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn()}))
    expect_flag("條目 id ≠ 檔名 → 擋",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(id="KN-999")}),
                "檔名")
    expect_flag("tier 不在 enum → 擋",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(tier="medium")}),
                "tier")
    expect_flag("status 不在 enum → 擋",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(status="ok")}),
                "status")
    expect_flag("tags 非陣列 → 擋",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(tags="verification")}),
                "tags")
    expect_flag("tags 為空陣列 → 擋",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(tags=[])}),
                "tags")
    expect_flag("tag 未註冊於 vocabulary → 擋(擋 tag 增殖)",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(tags=["未登記的標籤"])}),
                "未註冊")
    expect_flag("keywords 非字串陣列 → 擋",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(keywords=[1, 2])}),
                "keywords")
    expect_flag("條目含未知欄位 → 擋(打錯欄名=資料靜默消失)",
                build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn(tierr="shallow")}),
                "KN-001")

    # INDEX 反向:列了條目但 entries/ 沒有該檔
    expect_flag("INDEX 列了不存在的條目 → 擋(雙向偵測)",
                build(extra={"docs/knowledge/entries/KN-001.md": "# KN-001\n",
                             "docs/knowledge/INDEX.md": "# INDEX\n\n| KN-001 |\n| KN-777 |\n"}),
                "KN-777")

    # 欄位 lint 的選用加嚴:--require-branch(原本只測了 --require-commit)
    expect_flag("--require-branch 且缺 Branch 欄 → 擋",
                build(chg=CHG.replace("| 分支:main ", "")), "Branch", "--require-branch")
    expect_clean("--require-branch 且有 Branch 欄 → 過", build(), "--require-branch")

    # 重複性檢查欄的**版本邊界**:v1.17 是強制起點,v1.16 不追溯
    for ver, should_block in (("v1.17", True), ("v1.16", False)):
        r = build(chg=CHG.replace("- 重複性檢查:非重複——fixture\n", "")
                       .replace("ai-sdlc v1.18", f"ai-sdlc {ver}"))
        if should_block:
            expect_flag(f"{ver} 缺重複性檢查欄 → 擋(邊界:強制起點)", r, "重複性檢查")
        else:
            expect_clean(f"{ver} 缺該欄不追溯(邊界:起點前一版)", r)

    # 狀態分類的交界:同時出現「草稿」與「已驗收」時不得被當成草稿而豁免 ACC
    expect_flag("狀態同時含草稿與已驗收 → 不當草稿,仍要求 ACC",
                build(chg=CHG.replace("已驗收(見 ../acceptance/ACC-20260101-01.md)。",
                                      "草稿階段的內容,已驗收"), acc=None), "驗收懸空")

    # CHG 編號取自內文:檔名符合 CHG-*.md 但不含完整編號時,仍要能由內文對應到 ACC。
    # (檔名完全不以 CHG- 開頭者不在 glob 射程內——那是刻意的:帳本條目就是叫 CHG-*.md。)
    d_noname = build(acc=None)
    (d_noname / "docs" / "changes" / "CHG-20260101-01.md").rename(
        d_noname / "docs" / "changes" / "CHG-notes.md")
    expect_flag("檔名無完整編號時由內文取 CHG 編號 → 缺 ACC 照樣擋", d_noname, "驗收懸空")
    expect_clean("檔名不以 CHG- 開頭者不在帳本射程內(刻意的範圍)",
                 build(acc=None, extra={"docs/changes/notes.md": "隨手筆記\n"},
                       chg=None))

    # secrets 掃描只看 docs/:非 docs/ 的檔案不在射程內(已知範圍,明示而非誤以為有掃)
    expect_clean("非 docs/ 的檔案不在 secrets 射程內(已知範圍)",
                 build(extra={"src/config.py": 'api_key = "abcdefghijklmno123"'}))

    # ---------- 第二批盲點補強(對應 78.9% 那一輪的 20 個實質存活點)----------
    # 這批全部是「錯誤路徑」與「空回傳」:程式在這些分支回空清單代表沒問題,
    # 而沒有任何斷言證明那條線真的被走過且回了空——把 `return []` 改成 `return None`
    # 都不會有東西變紅。

    # classify_status 的五個分支直接單元測(子行程層的粗測蓋不到分支交界)
    sys.path.insert(0, str(SCRIPT.parent))
    import doc_integrity_check as DI
    for text, want in (("## 狀態\n草稿\n", "draft"),
                       ("## 狀態\n暫停——等上游\n", "paused"),
                       ("## 狀態\n已實作,待驗收\n", "implemented_or_accepted"),
                       ("## 狀態\n已驗收\n", "implemented_or_accepted"),
                       ("## 狀態\n(什麼都沒寫)\n", "unknown"),
                       # 交界:同時出現草稿與已驗收 → 不得被當草稿而豁免 ACC
                       ("## 狀態\n草稿階段的內容,已驗收\n", "implemented_or_accepted"),
                       # 暫停優先於其他字樣(合法 WIP 不該被誤判為已實作)
                       ("## 狀態\n暫停,原本已實作一半\n", "paused")):
        got = DI.classify_status(text)
        checks.append((f"classify_status({want}) 正確(實得 {got})", got == want, []))

    # git 輔助函式的契約:回傳 str(不是 bytes)、且真的捕捉到 stdout
    if shutil.which("git"):
        dg = build()
        subprocess.run("git init -q", shell=True, cwd=str(dg), capture_output=True)
        out = DI.git(dg, "status", "--porcelain")
        checks.append(("git() 回傳字串而非 bytes", isinstance(out, str), []))
        checks.append(("git() 確實捕捉 stdout(非 None)", out is not None, []))
    # 非 git 目錄下取 staged 檔案 → 空清單,不得崩潰
    nogit = build()
    rc, out = run(nogit, "--staged")
    checks.append(("非 git 目錄下 --staged → 不崩潰",
                   rc in (0, 1) and _no_crash(out), ["崩潰"]))

    # 結構漂移:docs/ 底下的 model 檔**不算**結構性程式變更(排除條件的正例)
    if shutil.which("git"):
        d = build()
        git(d, "init", "-q")
        (d / "docs" / "models").mkdir(parents=True)
        (d / "docs" / "models" / "note.md").write_text("# m\n", encoding="utf-8")
        git(d, "add", "-A")
        rc, out = run(d, "--staged")
        checks.append(("docs/ 底下的 model 檔不算結構性變更", rc == 0 and _no_crash(out), []))

    # CHG 編號:檔名有完整編號、內文沒有 → 仍須由檔名取得(or 的另一邊)
    d = build(acc=None, chg=CHG.replace("# CHG-20260101-01 — fixture 變更", "# 一份沒有編號的標題"))
    expect_flag("內文無編號時由檔名取 CHG 編號 → 缺 ACC 照樣擋", d, "驗收懸空")

    # 沒有 docs/ 目錄的 repo:各檢查回空、不得崩潰
    bare = Path(tempfile.mkdtemp())
    (bare / "AGENTS.md").write_text("# A\n", encoding="utf-8")
    rc, out = run(bare)
    checks.append(("無 docs/ 的 repo → 乾淨通過不崩潰", rc == 0 and _no_crash(out), []))

    # 迴歸集:純指令名(無 / 也無 .)不驗存在性——豁免條件的正例
    expect_clean("regression.md 內的純指令名不驗(如 `make`)",
                 build(extra={"docs/acceptance/regression.md": "- 條件:`make` 跑得起來\n"}))
    expect_clean("regression.md 內的 URL 不驗",
                 build(extra={"docs/acceptance/regression.md": "- 條件:`https://example.com/x`\n"}))

    # knowledge 條目:keywords 為**選填**——沒有這個欄位必須照樣通過
    expect_clean("條目沒有 keywords 欄 → 過(選填)",
                 build(extra={**base_kn, "docs/knowledge/entries/KN-001.json": kn()}))
    expect_clean("條目 keywords 為合法字串陣列 → 過",
                 build(extra={**base_kn,
                              "docs/knowledge/entries/KN-001.json": kn(keywords=["甲", "乙"])}))

    # 這個 fixture 有 docs/acceptance/ 與 AGENTS.md 卻沒有 docs/changes/ ——
    # **那正是「治理 repo 掉了帳本」的形狀**。CHG-20260805-04 起它被擋下,
    # 所以本斷言的 `rc == 0` 部分隨之改為 `rc == 1`:那是刻意的行為變更,不是把測試折彎。
    #
    # 原本的意圖(**不得崩潰**)完整保留,而且更要緊了:崩潰同樣回非零退出碼,
    # 若不同時驗「不是 traceback」,這條斷言就分不出「正確擋下」與「炸了」(KN-003)。
    nochg = Path(tempfile.mkdtemp())
    (nochg / "docs" / "acceptance").mkdir(parents=True)
    (nochg / "AGENTS.md").write_text("# A\n", encoding="utf-8")
    rc, out = run(nochg)
    checks.append(("有 docs/ 無 changes/ → 擋下,且是**正確地**擋而非崩潰",
                   rc == 1 and _no_crash(out) and "帳本不見了" in out, []))

    # ---------- 10/11) git 相關:結構漂移與 commit 治理 ----------
    if shutil.which("git") is None:
        checks.append(("git 不存在 → 結構漂移與 commit 掃描無法驗證(明示,不當作通過)",
                       False, ["需要 git"]))
    else:
        # 結構漂移:staged 了 models/ 卻沒動 docs/structure/
        d = build()
        git(d, "init", "-q")
        (d / "models").mkdir()
        (d / "models" / "user.py").write_text("class User: pass\n", encoding="utf-8")
        git(d, "add", "-A")
        rc, out = run(d, "--staged")
        checks.append(("改結構性程式未同步 docs/structure/ → 擋",
                       rc == 1 and "docs/structure/" in out, ["docs/structure/"]))
        # 同步了就該過
        (d / "docs" / "structure").mkdir(parents=True)
        (d / "docs" / "structure" / "data.md").write_text("# data\n", encoding="utf-8")
        git(d, "add", "-A")
        rc, out = run(d, "--staged")
        checks.append(("同步了結構文件 → 過", rc == 0, [out.strip()[-60:]]))

        # commit 治理掃描:commit message 未引用 CHG 編號
        d2 = build()
        git(d2, "init", "-q")
        git(d2, "add", "-A")
        git(d2, "commit", "-q", "-m", "CHG-20260101-01: 初始")
        base = git(d2, "rev-parse", "HEAD").stdout.strip()
        (d2 / "docs" / "notes2.md").write_text("x\n", encoding="utf-8")
        git(d2, "add", "-A")
        git(d2, "commit", "-q", "-m", "隨手改一下")
        rc, out = run(d2, "--commits-since", base)
        checks.append(("commit 未引用 CHG 編號 → 擋",
                       rc == 1 and "CHG" in out and _no_crash(out), ["未治理 commit"]))
        # 錯誤路徑:錨點不存在 → 明確訊息,不得是 traceback
        rc, out = run(d2, "--commits-since", "no_such_ref_xyz")
        checks.append(("--commits-since 錨點不存在 → 明確訊息(非 traceback)",
                       rc == 1 and _no_crash(out) and ("錨點" in out or "無法讀取" in out),
                       ["錨點不存在的乾淨訊息"]))
        # 錯誤路徑:非 git repo 用 --commits-since → 明確訊息
        d3 = build()
        rc, out = run(d3, "--commits-since", "HEAD")
        checks.append(("--commits-since 但非 git repo → 明確訊息(非 traceback)",
                       rc == 1 and _no_crash(out) and "git" in out,
                       ["無 git 的乾淨訊息"]))
        # 引用了就該過
        (d2 / "docs" / "notes3.md").write_text("y\n", encoding="utf-8")
        git(d2, "add", "-A")
        git(d2, "commit", "-q", "-m", "CHG-20260101-01: 補一筆")
        rc2, _ = run(d2, "--commits-since", "HEAD~1")
        checks.append(("commit 有引用 CHG 編號 → 過", rc2 == 0, []))

    # ── 未涵蓋登記簿的自洽性(CHG-20260804-06)──────────────────────────
    # 這份檔案的用途是讓「測試全綠」不被讀成「全部都驗過了」。
    # 那它自己就不能說謊——而它踩過的兩種說謊都要擋得住。
    with tempfile.TemporaryDirectory() as td4:
        d4 = Path(td4)
        acc = d4 / "docs" / "proj" / "acceptance"
        acc.mkdir(parents=True)
        (d4 / "docs" / "proj" / "changes").mkdir(parents=True)
        vc = acc / "verification-coverage.md"

        vc.write_text("| # | 標的 |\n|---|---|\n| C-1 | 甲 |\n| C-2 | 乙 |\n",
                      encoding="utf-8")
        rc, out = run(d4)
        checks.append(("登記簿無矛盾 → 不因它而紅", "登記簿" not in out, []))

        vc.write_text("| C-1 | 甲 |\n| C-1 | 又一個甲 |\n", encoding="utf-8")
        rc, out = run(d4)
        checks.append(("重複的 ID 被抓到", "重複的 ID" in out and "C-1" in out,
                       ["同一個編號指兩件事"]))

        # 收尾宣告在一節,而**未涵蓋的列留在另一節**——這才是真實會發生的形狀
        vc.write_text("## C. 本輪未涵蓋\n\n| C-2 | 還沒做 |\n\n"
                      "## C-2 收尾(CHG-x)\n\n已補上。\n", encoding="utf-8")
        rc, out = run(d4)
        checks.append(("宣告收尾卻在別節仍列著 → 被抓到", "宣告收尾" in out and "C-2" in out,
                       ["兩邊都是真話,合起來是假的"]))

        vc.write_text("## C-2 收尾(CHG-x)\n\n已補上。\n", encoding="utf-8")
        rc, out = run(d4)
        checks.append(("收尾且已移除該列 → 過", "登記簿" not in out, []))

        # 收尾小節裡的**摘要表**不是待辦,不得誤報。
        # 第一版沒分開這兩者,第一次有人在收尾節裡放摘要表就誤報了——
        # 而那個人是這道檢查的作者(CHG-20260804-09)。
        vc.write_text("## C-2 / C-3 收尾(CHG-x)\n\n| 項目 | 結果 |\n|---|---|\n"
                      "| C-2 甲 | 已補 |\n| C-3 乙 | 已補 |\n", encoding="utf-8")
        rc, out = run(d4)
        checks.append(("收尾小節內的摘要表不被誤報", "登記簿" not in out,
                       ["摘要不是待辦"]))

    # --- 沒有帳本的目錄不得得到肯定式的通過(CHG-20260805-04)---
    #
    # 兩種「沒帳本」的代價不同(KN-004):
    #   · 連 docs/ 都沒有 → 不適用。誤擋非治理專案的代價低 → exit 0,但措辭不得像通過。
    #   · 有 docs/ 卻沒有 changes/ → 那是治理 repo 掉了帳本的形狀 → 擋。
    AFFIRM = ("檢查通過", "驗證通過", "全數通過", "已通過")
    d_bare = Path(tempfile.mkdtemp())
    rc_b, out_b = run(d_bare)
    checks.append(("完全沒有帳本 → 退出碼 0(不適用不是失敗)", rc_b == 0, []))
    checks.append(("完全沒有帳本 → 訊息不含肯定式通過措辭",
                   not any(a in out_b for a in AFFIRM), []))
    checks.append(("完全沒有帳本 → 訊息明說不適用",
                   "不適用" in out_b and "沒有東西可檢查" in out_b, []))

    d_lost = Path(tempfile.mkdtemp())
    (d_lost / "docs" / "structure").mkdir(parents=True)
    (d_lost / "docs" / "structure" / "logical.md").write_text("x\n", encoding="utf-8")
    expect_flag("有 docs/ 卻沒有任何 changes/ → 擋(帳本不見了)", d_lost, "帳本不見了")

    # --- 帳本分目錄:檢查不得靜默空轉(CHG-20260804-17)---
    #
    # 原本寫死 docs/changes/。分目錄帳本的 repo 會讓整批檢查的輸入變成空集合——
    # 同一份壞 CHG 放 docs/<ledger>/changes/ 得到 ✅,放 docs/changes/ 立刻被擋三項。
    # 恆真回報「沒問題」比恆真回報「有問題」更難發現:沒有人會去追查一個綠燈。
    import shutil as _sh
    d_split = build()
    _sh.move(str(d_split / "docs" / "changes"), str(d_split / "docs" / "led" / "changes"))
    _sh.move(str(d_split / "docs" / "acceptance"), str(d_split / "docs" / "led" / "acceptance"))
    _sh.move(str(d_split / "docs" / "knowledge"), str(d_split / "docs" / "led" / "knowledge"))
    (d_split / "docs" / "led" / "changes" / "CHG-20260101-01.md").write_text(
        "# CHG-20260101-01\n\n- Project: x\n\n## 動機\n缺實作者、缺狀態。\n", encoding="utf-8")
    expect_flag("分目錄帳本裡的壞 CHG 照樣被擋(不得空轉)", d_split, "缺必填欄")
    # 帳本名前綴**只在多本時**才加(一本時加了是雜訊)。原本的 fixture 只造了一本,
    # 所以這條斷言從一開始就是錯的——而它排在計分之後,錯了也沒人知道。
    # 補第二本才對得上它自己的名字。
    (d_split / "docs" / "led2" / "changes").mkdir(parents=True)
    (d_split / "docs" / "led2" / "acceptance").mkdir(parents=True)
    (d_split / "docs" / "led2" / "knowledge").mkdir(parents=True)
    (d_split / "docs" / "led2" / "knowledge" / "knowledge.md").write_text(
        "# knowledge\n\n## INDEX\n", encoding="utf-8")
    (d_split / "docs" / "led2" / "changes" / "CHG-20260101-02.md").write_text(
        "# CHG-20260101-02\n\n- Project: x\n\n## 動機\n缺實作者、缺狀態。\n", encoding="utf-8")
    rc_s, out_s = run(d_split)
    checks.append(("多本帳本時訊息標出是哪一本",
                   "[led]" in out_s and "[led2]" in out_s, []))

    d_single = build()
    checks.append(("單帳本專案只解析出一本(行為不變)",
                   len(_ledger_roots(d_single)) == 1, []))

    # ↑ 這一組自 CHG-20260804-17 起就排在計分之後,**從未被評估過**——
    #   包括招牌的那條「分目錄帳本裡的壞 CHG 照樣被擋」。而且元組長度也寫錯了
    #   (二元組),因為從來沒被解包。兩個缺陷互相遮蔽,由 CHG-20260805-04 的
    #   結構 lint 抓出來。

    # --- 帳本封存宣告(CHG-20260810-02)---
    #
    # 四例的分界線是**理由有沒有內容**,不是檔案在不在:空白豁免看起來像有交代,
    # 比漏寫更糟(KN-006)。而未宣告一律倒向「活的」——多算一本只是統計多幾筆,
    # 漏算是整本帳沒有人看管,而且不會有人抗議(KN-004)。
    d_arch = build()
    led = _ledger_roots(d_arch)[0]
    from doc_integrity_check import archived_reason, is_archived  # noqa: E402

    marker = led / ".archived"
    checks.append(("沒有 .archived → 視為活的", is_archived(led) is False, []))

    marker.write_text("", encoding="utf-8")
    checks.append((".archived 空白 → 視同沒宣告(活的)", is_archived(led) is False, []))

    marker.write_text("   \n\t\n  ", encoding="utf-8")
    checks.append((".archived 只有空白字元 → 視同沒宣告(活的)",
                   is_archived(led) is False, []))

    marker.write_text("併入前的歷史帳本,唯讀保留。\n細節第二行。\n", encoding="utf-8")
    checks.append((".archived 有理由 → 封存", is_archived(led) is True, []))
    checks.append(("理由原文取得(全文,不截斷)",
                   (archived_reason(led) or "").startswith("併入前的歷史帳本")
                   and "細節第二行。" in (archived_reason(led) or ""), []))

    # 非 UTF-8 的 `.archived` **不得讓整支崩潰**。這一條是 fuzz 清冊逼出來的:
    # `read_text(encoding="utf-8")` 碰到壞位元組拋 `UnicodeDecodeError`,
    # 而它是 `ValueError` 不是 `OSError`——第一版的 `except OSError` 接不到,
    # 於是 `doc_integrity_check`(ci_local.sh 第一步 + git hook)當場 traceback。
    marker.write_bytes(b"\xff\xfe \x80\x81")
    try:
        crashed = False
        archived_state = is_archived(led)
    except Exception:
        crashed, archived_state = True, None
    checks.append(("非 UTF-8 的 .archived 不得崩潰", not crashed, []))
    checks.append(("讀不出來 → 視為活的(倒向多檢查)", archived_state is False, []))
    marker.write_text("併入前的歷史帳本,唯讀保留。\n", encoding="utf-8")

    # **封存不得縮小閘的範圍**:同一本帳被宣告封存之後,壞掉的 CHG 照樣要被擋。
    # 這是本 CHG 最容易犯、代價最大的誤用——一次讓整本帳離開檢查範圍,
    # 而且不會有人抗議(KN-001 的鏡像)。
    (led / "changes" / "CHG-20260101-09.md").write_text(
        "# CHG-20260101-09\n\n- Project: x\n\n## 動機\n缺實作者、缺狀態。\n",
        encoding="utf-8")
    rc_arch, out_arch = run(d_arch)
    checks.append(("封存帳本裡的壞 CHG **照樣被擋**(閘不得因封存而變弱)",
                   rc_arch == 1 and "CHG-20260101-09" in out_arch,
                   ["rc=1", "CHG-20260101-09"]))

    failed = [n for n, ok, _ in checks if not ok]
    for n, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
        if not ok and detail:
            print(f"          期望訊號:{detail}")
    if failed:
        print(f"❌ {len(failed)}/{len(checks)} 失敗")
        return 1
    print(f"✅ 全 {len(checks)} 斷言通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
