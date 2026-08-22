#!/usr/bin/env python3
"""閘門金絲雀的單元斷言與**校準樣本**(CHG-20260813-09,C2 第一筆)。

金絲雀自己也可能是裝飾:一個「什麼都判 blocks」的金絲雀,與一個真的驗過的,
在輸出上完全一樣(KN-001)。所以四態各造一個**已知答案**的樣本,逐態驗:

  · 已知會擋的假閘   → 必須報 `blocks`
  · 已知 fail-open 的假閘(永遠 exit 0)→ 必須報 **`fail-open`**
  · 已知基線就紅的假閘 → 必須報 `baseline-red`(而不是「沒擋」)
  · 造不出壞樣本      → 必須報 `unverified-blocked`(而不是 `fail-open`)

**最後兩態與前兩態分得開,是這支工具唯一的價值**:混在一起的話,
一道真的 fail-open 的閘會被讀成「這台機器驗不了」,而人就不會去修它。

另有一條**跨實作對帳**:`gate_canary.discover` 與 `build_claim_manifest.gate_claims`
是兩份程式裡的兩個抽取器,而 artifact 要靠 digest 對得上清冊才不會被拒用。
兩邊分岔 = 金絲雀白跑,所以這裡拿同一份 fixture 餵兩邊,要求逐條相同。

Run: python3 test_gate_canary.py → exit 0 全過,1 有失敗。
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import gate_canary as GC  # noqa: E402


def _load(name: str, rel: str):
    """按路徑載入被測模組。**讀不到就當場拋**——回一個空模組會讓後面每一條斷言
    都紅在同一個無關的理由上,而那看起來會像被測程式有一堆缺陷(KN-003)。"""
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"載入不了 {rel}——那不是「它沒有缺陷」")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BCM = _load("bcm", ".github/build_claim_manifest.py")

CI_FIXTURE = '''#!/usr/bin/env bash
step "甲關"   python3 .github/check_a.py --repo .
# step "註解裡的閘"  這一行不是呼叫點
gated_step "乙關" "$(_why_quick)" bash .github/run_b.sh
step "$name" "$@"
step "甲關"   python3 .github/check_a.py --quick
'''


def _sample_fixture() -> Path:
    """一個**齊備到讓 13 則樣本都種得下去**的最小 fixture。

    只給空目錄的話,吃 JSON 的那幾則會提早回「讀不到」——**內層的變異邏輯
    一行都沒被執行**,而那正是 `replace` 是 no-op 那個缺陷藏身的地方。
    """
    d = Path(tempfile.mkdtemp(prefix="gc-sample-"))
    (d / ".github").mkdir(parents=True)
    (d / ".github" / "ci_local.sh").write_text('step "甲關"   true\n', encoding="utf-8")
    assets = d / "skills" / "ai-sdlc-autopilot" / "assets"
    assets.mkdir(parents=True)
    one = {"claims": [{"claim_id": "x", "claim_text": "原本的文字"}]}
    (assets / "claim_manifest.json").write_text(json.dumps(one), encoding="utf-8")
    (assets / "doc_claims.json").write_text(json.dumps(one), encoding="utf-8")
    (assets / "verifier_manifest.json").write_text(
        json.dumps({"files": [".github/x.py", "skills/ai-sdlc-autopilot/scripts/y.py"]}),
        encoding="utf-8")
    (d / ".claude-plugin").mkdir()
    (d / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "p", "version": "1.0.0"}]}), encoding="utf-8")
    copy = d / "plugins" / "ai-sdlc-suite" / "skills" / "ai-sdlc-autopilot"
    copy.mkdir(parents=True)
    (copy / "SKILL.md").write_text("# SKILL\n", encoding="utf-8")
    # 乙丙組 8 則要的前置(C2 第三筆)。**齊備到讓每一則都真的種得下去**——
    # 缺一格,那一則就停在早退分支回具名理由,而**內層的變異邏輯一行都沒被執行**。
    # C2 第二筆的④(`replace` 是 no-op)就藏在那種沒被執行的內層裡,
    # 而抓到它的是全量掃描,不是斷言。
    (assets / "doc_counts.json").write_text(json.dumps({"claims": [
        {"id": "agents-tests", "file": "AGENTS.md", "measure": "test_files",
         "pattern": r"# 全部 (\d+) 支 test_\*\.py"},
        {"id": "worklog-tests", "file": "docs/worklog/wl.md", "measure": "test_files",
         "pattern": r"\| 測試檔 \| \*\*(\d+)\*\*"},
    ]}, ensure_ascii=False), encoding="utf-8")
    (d / "AGENTS.md").write_text(
        "bash .github/run_tests.sh   # 全部 35 支 test_*.py\n", encoding="utf-8")
    (d / "docs" / "worklog").mkdir(parents=True)
    (d / "docs" / "worklog" / "wl.md").write_text(
        "| 測試檔 | **35** |\n", encoding="utf-8")
    scripts = d / "skills" / "ai-sdlc-autopilot" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "verifier_integrity.py").write_text(
        "def main():\n    changed = added = removed = []\n"
        "    if changed or added or removed:\n        return 1\n    return 0\n",
        encoding="utf-8")
    (assets / "verifier_manifest.json").write_text(
        json.dumps({"files": ["skills/ai-sdlc-autopilot/scripts/verifier_integrity.py",
                              "skills/ai-sdlc-autopilot/assets/doc_counts.json"]}),
        encoding="utf-8")
    return d


def _repo_with_ci(body: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="gc-unit-"))
    (d / ".github").mkdir(parents=True)
    (d / ".github" / "ci_local.sh").write_text(body, encoding="utf-8")
    return d


def blocking_gate(fx: Path) -> str:
    """壞樣本存在就紅,**而且印出它擋到了什麼**。

    真的閘都會印;而金絲雀的歸因(`witness`)正是靠那一行分辨
    「紅在這個樣本上」與「紅在別的地方」。第一版的假閘什麼都不印,
    於是新語意上線後它被判成 `sample-out-of-range`——**校準樣本沒跟上判準**。
    """
    return 'bash -c "test -f bad.txt && { echo 發現 bad.txt; exit 1; } || exit 0"'


# 永遠 exit 0,**而且輸出提過那個樣本**——證明它在射程內卻沒被擋 = 真的 fail-open。
FAIL_OPEN_GATE = 'bash -c "echo 掃到了 bad.txt 的位置; exit 0"'
BASELINE_RED_GATE = 'bash -c "exit 1"'


def plant_bad(fx: Path) -> None:
    (fx / "bad.txt").write_text("壞樣本\n", encoding="utf-8")
    return None


def cannot_build(fx: Path) -> str:
    return "這台機器沒有造壞樣本的前置(具名阻礙)"




def _audit_samples(samples) -> list:
    """逐則實跑樣本:要嘛**真的改到東西**、要嘛具名說為什麼不行,沒有第三種。

    抽成獨立函式,是為了**讓這個檢查器自己也受測**——注入三種已知的壞樣本,
    三種都必須被指名。否則它就是一個沒有人驗過的檢查器,
    而那正是本輪反覆遇到的形狀。
    """
    bad_samples = []
    for gate_name, smp in sorted(samples.items()):
        fxs = _sample_fixture()
        before = {q: q.read_bytes() for q in fxs.rglob("*") if q.is_file()}
        try:
            got = smp.mutate(fxs)
        except Exception as e:                      # noqa: BLE001
            bad_samples.append(f"{gate_name}:拋了 {type(e).__name__}")
            continue
        if got is not None:
            if not str(got).strip():
                bad_samples.append(f"{gate_name}:回了空理由(等同沒宣告,KN-006)")
            continue
        after = {q: q.read_bytes() for q in fxs.rglob("*") if q.is_file()}
        if after == before:
            # **回 None 表示「種好了」,那就得真的改到東西**——這正是
            # `replace` 是 no-op 那個缺陷的形狀(KN-008 第 0 問)。
            bad_samples.append(f"{gate_name}:說種好了而 fixture 一個位元組都沒變")
    return bad_samples


def main() -> int:
    checks = []

    # ---- 抽取:與清冊同一組判準 ----
    d = _repo_with_ci(CI_FIXTURE)
    g = GC.discover(d)
    checks.append(("抽得到字面命名的閘", set(g) == {"甲關", "乙關"}))
    checks.append(("註解行不是呼叫點", "註解裡的閘" not in g))
    checks.append(("`$name` 那種展開不是 kind 名", "$name" not in g))
    checks.append(("`gated_step` 也是呼叫點", "乙關" in g))

    # **跨實作對帳**:兩個抽取器對同一份 fixture 必須給出相同的 claim_id 與 digest。
    gate_rows, _ = BCM.gate_claims(d)
    theirs = {c["claim_id"]: c["condition_digest"] for c in gate_rows}
    mine = {f"gate::{n}": v["digest"] for n, v in g.items()}
    checks.append(("兩個抽取器的 claim_id 逐條相同", set(mine) == set(theirs)))
    checks.append(("兩個抽取器的 condition_digest 逐條相同(**分岔 = 金絲雀白跑**)",
                   mine == theirs))
    # 同名跑兩次:兩次的指令都要進摘要,否則改第二次沒有人看著。
    one = GC.discover(_repo_with_ci('step "甲關"   python3 .github/check_a.py --repo .\n'))
    checks.append(("同名兩次的摘要不同於只出現一次",
                   g["甲關"]["digest"] != one["甲關"]["digest"]))
    checks.append(("一道閘都沒有時回空(讓呼叫端判 KN-001)",
                   GC.discover(_repo_with_ci("# 什麼都沒有\n")) == {}))
    checks.append(("讀不到 ci_local.sh 回空,不拋",
                   GC.discover(Path(tempfile.mkdtemp())) == {}))

    # ---- 續行進 digest:**負向測試,而且不信任新解析器** ----
    #
    # fable 席的條件:「兩邊都是新程式算出來的、彼此自然一致」不能當證據。
    # 所以這裡的期望值**不由解析器產生**,而是直接問兩件事:
    # 改續行上的內容 → digest **必須變**;剝掉理由參數 → digest **必須不變**。
    CONT = ('#!/usr/bin/env bash\n'
            'gated_step "續行閘" "$(_why_quick)" \\\n'
            "    bash -c 'PYTHONIOENCODING=cp932 bash .github/run_tests.sh'\n")
    base = GC.discover(_repo_with_ci(CONT))["續行閘"]
    checks.append(("重播指令含**續行上**的真正指令",
                   "PYTHONIOENCODING=cp932" in base["cmd"]))
    checks.append(("重播指令**不含**理由參數(留著會讓 bash 拿空字串當指令名)",
                   "_why_quick" not in base["cmd"]))

    changed = GC.discover(_repo_with_ci(
        CONT.replace("cp932", "cp932x")))["續行閘"]["digest"]
    checks.append(("改續行上的編碼 → **digest 必須變**(舊版看不到這一格)",
                   changed != base["digest"]))

    same_reason = GC.discover(_repo_with_ci(
        CONT.replace('"$(_why_quick)"', '"$(_why_heavy)"')))["續行閘"]["digest"]
    checks.append(("換掉理由參數 → digest **也要變**(它也在原始跨度內)",
                   same_reason != base["digest"]))

    # 沒有續行的閘,digest 與舊行為一致——19 道不該因為這次修改而churn。
    plain = GC.discover(_repo_with_ci('step "平常閘"   true\n'))["平常閘"]
    checks.append(("沒有續行時 digest 就是那一行名字之後的內容",
                   plain["digest"] == GC.text_digest("   true")))

    # ---- 四態校準:每一態都用**已知答案**的假閘 ----
    fx = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx, blocking_gate(fx), GC.Sample(plant_bad))
    checks.append(("已知會擋的假閘 → blocks", v == "blocks"))
    checks.append(("blocks 的證據說得出基線與壞樣本的退出碼", "基線綠" in why))

    fx2 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx2, FAIL_OPEN_GATE, GC.Sample(plant_bad, "bad.txt"))
    checks.append(("**已知 fail-open 的假閘 → fail-open**(不是 blocks)", v == "fail-open"))
    checks.append(("fail-open 的證據說樣本在射程內而閘沒擋", "射程內而它沒擋" in why))

    fx3 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx3, BASELINE_RED_GATE, GC.Sample(plant_bad))
    checks.append(("基線就紅 → baseline-red(**不是 fail-open**)", v == "baseline-red"))
    checks.append(("baseline-red 的證據說變異的紅證明不了東西", "證明不了" in why))

    fx4 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx4, blocking_gate(fx4), GC.Sample(cannot_build))
    checks.append(("造不出壞樣本 → unverified-blocked(**不是 fail-open**)",
                   v == "unverified-blocked"))
    checks.append(("blocked 的理由具名", "具名阻礙" in why))

    # 逾時:沒驗成,不是轉紅。
    fx5 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    orig_run = GC.run_gate
    calls = {"n": 0}

    def slow(cwd, cmd, timeout=GC.DEFAULT_PROBE_BUDGET, env=None):
        calls["n"] += 1
        return (0, "") if calls["n"] == 1 else (-1, "TIMEOUT")

    setattr(GC, "run_gate", slow)
    try:
        v, why, _x = GC.probe_gate(fx5, "irrelevant", GC.Sample(plant_bad))
    finally:
        setattr(GC, "run_gate", orig_run)
    checks.append(("壞樣本上逾時 → unverified-blocked(不是轉紅)", v == "unverified-blocked"))

    # ---- Fixture:worktree 由 commit 保證位元組 ----
    leftover: Path | None = None
    with GC.Fixture(REPO) as f:
        wt = f.path                      # 與上面四態校準的 `fx` 分開命名:同名重用會撞型別
        made = wt is not None and (wt / ".github" / "ci_local.sh").is_file()
        checks.append(("worktree fixture 建得起來且內容在", made))
        if made and wt is not None:
            # **位元組同一性由 commit 保證**,而證明它的方式是問 fixture 自己站在哪個
            # commit ——直接比對檔案位元組會被 Windows 的 autocrlf 弄成假紅,
            # 而第一版用 `same or True` 繞過它,那是一條**恆真斷言**
            # (本 repo 明文禁止的形狀,`test_gates_wired` 有一條專門在抓它)。
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                                  capture_output=True, text=True).stdout.strip()
            fx_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(wt),
                                     capture_output=True, text=True).stdout.strip()
            checks.append(("fixture 與真樹站在同一個 commit(內容來自 HEAD,不是工作樹)",
                           bool(head) and head == fx_head))
            checks.append(("fixture 不是真樹本身", wt.resolve() != REPO.resolve()))
            checks.append(("髒樹會被記下來(否則量到的是 HEAD,不是你在跑的那份)",
                           isinstance(f.dirty, list)))
            leftover = wt
    checks.append(("離開後 fixture 已清掉", leftover is not None and not leftover.exists()))

    # ---- 錯誤路徑:每一條都要能分得出「壞了」與「沒事」(KN-003)----
    import subprocess as _sp
    orig_sprun = _sp.run

    def boom(*a, **k):
        raise OSError("裝不到 git")

    _sp.run = boom
    try:
        rc, why = GC._git(REPO, "status")
        checks.append(("git 叫不起來回 (-1, 理由),不拋", rc == -1 and "git" in why))
        rc, why = GC.run_gate(REPO, "irrelevant")
        checks.append(("閘的指令叫不起來回 -2(與逾時的 -1 分得開)", rc == -2))
    finally:
        _sp.run = orig_sprun

    def timeout(*a, **k):
        raise _sp.TimeoutExpired(cmd="x", timeout=1)

    _sp.run = timeout
    try:
        rc, why = GC._git(REPO, "status")
        checks.append(("git 逾時也回 (-1, 理由)", rc == -1))
        rc, why = GC.run_gate(REPO, "irrelevant")
        checks.append(("閘的指令逾時回 (-1, TIMEOUT)", (rc, why) == (-1, "TIMEOUT")))
    finally:
        _sp.run = orig_sprun

    # 正常路徑:真的起一個子行程,拿得到退出碼與輸出。
    rc, out = GC.run_gate(REPO, 'bash -c "echo 甲 >&2; exit 3"')
    checks.append(("閘的指令跑得起來且退出碼取得到", rc == 3 and "甲" in out))

    # worktree 建不起來:**path 為 None,而不是拿一個半成品往下跑**。
    orig_git = GC._git
    setattr(GC, "_git", lambda repo, *a, **k: (1, "worktree 建不起來"))
    try:
        with GC.Fixture(REPO) as bad:
            checks.append(("worktree 建不起來 → path 為 None(不往下跑)", bad.path is None))
            checks.append(("失敗理由留得下來", "建不起來" in getattr(bad, "error", "")))
    # `path` 為 None 時 `__exit__` 直接 return —— 上面的 `with` 正常離開就是證據,
    # 再補一條 `("…", True)` 只是恆真斷言(本 repo 明文禁止的形狀)。
    finally:
        setattr(GC, "_git", orig_git)

    # `_load` 讀不到就當場拋——回一個空模組會讓後面每條斷言紅在無關的理由上。
    # 路徑要挑**副檔名不認得**的:不存在的 `.py` 仍然生得出 spec,
    # 直到 `exec_module` 才炸,那條 `raise` 反而走不到(第一版就是這樣,
    # 而 diff coverage 當場指著那一行說它沒被執行過)。
    ok_load = True
    try:
        _load("nope", "AGENTS.md")
    except RuntimeError:
        ok_load = False
    checks.append(("載入不了被測模組要當場拋(不是回空)", not ok_load))

    # ---- main() 的退出碼三態 ----
    def run_main(repo: Path, *argv) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = GC.main(["gate_canary.py", "--repo", str(repo), *argv])
        return rc, buf.getvalue()

    rc, out = run_main(_repo_with_ci("# 什麼都沒有\n"))
    checks.append(("一道閘都沒發現 → rc 2(**發現階段壞了**,不是沒有閘)", rc == 2))
    checks.append(("訊息說出是發現階段壞了", "發現階段壞了" in out))
    rc, out = run_main(d, "--list")
    checks.append(("--list → rc 0", rc == 0))
    checks.append(("--list 印出 digest 與 claim_id", "gate::甲關" in out))
    rc, out = run_main(d, "--list", "--json")
    checks.append(("--list --json 只吐 JSON", out.lstrip().startswith("[")))
    # fixture 的閘與樣本表對不上 → **對帳先擋下**(rc 2),而不是往下判「未證明」。
    # 樣本表是手寫的資料,而手寫的表會與現實分岔;分岔要先現形,再談判定。
    rc, out = run_main(d)
    checks.append(("樣本表對不到 fixture 的閘 → rc 2(對帳先擋)", rc == 2))
    checks.append(("對帳說得出是名字漂了", "對不到任何閘" in out))


    # ---- C2 第二筆:歸因、第五態、第 0 問(CHG-20260814-01)----
    fx6 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx6, blocking_gate(fx6), GC.Sample(plant_bad, "bad.txt"))
    checks.append(("紅了且輸出指名壞樣本 → blocks", v == "blocks"))

    # 閘紅了,而輸出**沒有**指名這個壞樣本 —— 紅在別的地方,歸因不到。
    fx7 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx7, blocking_gate(fx7),
                               GC.Sample(plant_bad, "不會出現的字串"))
    checks.append(("紅了而歸因不到 → sample-out-of-range(不是 blocks)",
                   v == "sample-out-of-range"))
    checks.append(("證據說得出是紅在別的地方", "紅在別的地方" in why))

    # **綠燈時沒有射程證明,一律歸「樣本沒打中」**——誣指一道好閘是 fail-open,
    # 會讓人去改一道本來就對的閘。
    fx8 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx8, FAIL_OPEN_GATE,
                               GC.Sample(plant_bad, "不會出現的字串"))
    checks.append(("綠燈且無射程證明 → sample-out-of-range(**不是 fail-open**)",
                   v == "sample-out-of-range"))
    checks.append(("證據說得出無法證明落在射程內", "無法證明" in why))

    # 綠燈**而基線輸出提過這個樣本** → 樣本在射程內而閘沒擋 = 真的 fail-open。
    fx9 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v, why, _x = GC.probe_gate(fx9, 'bash -c "echo 提到了 bad.txt; exit 0"',
                               GC.Sample(plant_bad, "bad.txt"))
    checks.append(("綠燈而樣本在射程內 → fail-open", v == "fail-open"))
    checks.append(("fail-open 的證據說樣本在射程內", "射程內" in why))

    # `_edit_json` 內建的第 0 問:改完位元組沒變 = 壞樣本沒種下去。
    fxa = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    (fxa / "x.json").write_text('{"a": 1}', encoding="utf-8")
    blocked_why = GC._edit_json(fxa, "x.json", lambda d: None)   # 什麼都不改
    checks.append(("變異沒改動任何一格 → 具名擋下(KN-008 第 0 問)",
                   blocked_why is not None and "沒種下去" in blocked_why))
    checks.append(("真的改了就放行",
                   GC._edit_json(fxa, "x.json", lambda d: d.update({"a": 2})) is None))
    missing_why = GC._edit_json(fxa, "沒有這個檔.json", lambda d: None)
    checks.append(("讀不到就回具名理由(不是靜靜當作種好了)",
                   missing_why is not None and "讀不到" in missing_why))

    # `resolve_py` 回**名字**不回絕對路徑——回路徑會讓 Git Bash 執行不了。
    checks.append(("resolve_py 回得出東西", bool(GC.resolve_py())))

    # 樣本表與接線的對帳:表裡有而接線沒有 = 名字漂了。
    checks.append(("樣本對不到任何閘要說出來",
                   bool(GC.reconcile({}))) if GC.SAMPLES else ("樣本表非空", False))
    checks.append(("接線與樣本一致時對帳沉默",
                   GC.reconcile({k: {} for k in GC.SAMPLES}) == []))

    # `--json` 只吐 JSON,不混人看的摘要(CHG-20260805-06 的同一個坑)。
    rc, out = run_main(REPO, "--list", "--json")
    checks.append(("--list --json 解析得動", _json_ok(out)))
    checks.append(("非 JSON 的輸出認得出來(否則這條純度檢查是裝飾)",
                   _json_ok("這不是 JSON") is False))

    # **每道閘一個 fixture**:共用一個 worktree 會讓前一道的壞樣本污染下一道的基線,
    # 於是判定塌縮成 `baseline-red`——而那看起來像閘壞了。
    opened = {"n": 0}
    OrigFixture = GC.Fixture

    class Counting(OrigFixture):  # type: ignore[misc,valid-type]
        def __enter__(self):
            opened["n"] += 1
            return self

        def __exit__(self, *exc):
            return None

    orig_probe = GC.probe_gate
    setattr(GC, "Fixture", Counting)
    setattr(GC, "probe_gate", lambda *a, **k: ("blocks", "fixture", {}))
    orig_samples = GC.SAMPLES
    setattr(GC, "SAMPLES", {"甲關": orig_samples["doc integrity"]})
    try:
        rows, _ = GC.probe_all(d)
    finally:
        setattr(GC, "Fixture", OrigFixture)
        setattr(GC, "probe_gate", orig_probe)
        setattr(GC, "SAMPLES", orig_samples)
    sampled = sum(1 for r in rows if r["verdict"] != "no-sample")
    checks.append(("有樣本的每一道閘各開一個 fixture(不共用)",
                   opened["n"] == sampled and sampled > 0))

    # **每一則樣本都逐則實跑。** 樣本函式只有在真跑金絲雀時才會執行,
    # 於是它們的缺陷(打錯路徑、`replace` 是 no-op)要到全量掃描才現形
    # ——而那一輪要跑二十分鐘。這裡對一個空 fixture 逐則呼叫:
    # **要嘛種下去(回 None)、要嘛具名說為什麼不行(回字串),沒有第三種。**
    bad_samples = _audit_samples(GC.SAMPLES)
    # **檢查器自己也要能報壞。** 注入三種已知的壞樣本:拋例外、回空理由、
    # 說種好了卻一個位元組都沒改——三種都必須被指名,否則這個檢查是裝飾。
    injected = _audit_samples({
        "會拋的": GC.Sample(lambda fx: (_ for _ in ()).throw(RuntimeError("x")), "w"),
        "空理由的": GC.Sample(lambda fx: "   ", "w"),
        "說種好了而沒改的": GC.Sample(lambda fx: None, "w"),
    })
    checks.append(("逐則檢查器抓得到三種壞樣本", len(injected) == 3))
    checks.append(("壞樣本的理由各自具名",
                   any("拋了" in x for x in injected)
                   and any("空理由" in x for x in injected)
                   and any("一個位元組都沒變" in x for x in injected)))
    checks.append((f"每則樣本都**真的改到東西**或具名說不行"
                   f"(實得 {len(bad_samples)} 則有問題:{bad_samples[:2]})",
                   not bad_samples))
    checks.append((f"樣本表涵蓋接線上**每一道**閘(實得 {len(GC.SAMPLES)} 則)",
                   set(GC.SAMPLES) == set(GC.discover(REPO))))
    # **棘輪**:沒有 witness 的樣本,它的 `blocks` 比別人弱一級。
    # 條數固定成 0,新樣本就不能無聲地走弱的那一級(fable)。
    no_witness = sorted(k for k, s in GC.SAMPLES.items() if not s.witness)
    checks.append((f"每則樣本都有歸因 witness(實得 {len(no_witness)} 則沒有)",
                   not no_witness))

    # ── C2 第三筆:preflight / setup / 預算三層 ────────────────────────
    #
    # 三層各有一條**失效方向**要釘住,而三條的方向都是「看起來像閘壞了」。

    # preflight 是**純觀測**:blocked 與 error 都落 unverified-blocked,
    # 而措辭必須分得開——「探不了」與「探壞了」不是同一件事(KN-003)。
    fxp = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_pb, why_pb, _x = GC.probe_gate(fxp, blocking_gate(fxp), GC.Sample(
        plant_bad, "bad.txt", preflight=lambda fx: ("blocked", "工具不在")))
    checks.append(("preflight 判 blocked → unverified-blocked 且說「前置不在」",
                   v_pb == "unverified-blocked" and "前置不在" in why_pb))
    fxe = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_pe, why_pe, _x = GC.probe_gate(fxe, blocking_gate(fxe), GC.Sample(
        plant_bad, "bad.txt", preflight=lambda fx: ("error", "探針自己炸了")))
    checks.append(("preflight 判 error → 措辭與 blocked **分得開**(探壞了≠探不了)",
                   v_pe == "unverified-blocked" and "自己壞了" in why_pe
                   and "前置不在" not in why_pe))
    # 回了看不懂的值,一樣走 error 那條——**不得當成 ready 往下走**。
    fxq = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_pq, _w, _x = GC.probe_gate(fxq, blocking_gate(fxq), GC.Sample(
        plant_bad, "bad.txt", preflight=lambda fx: ("嗯?", "")))
    checks.append(("preflight 回不認得的狀態不得被當成 ready",
                   v_pq == "unverified-blocked"))
    # preflight 在 fixture 開出來就跑,而且**排在基線之前**:前置不在時
    # 不該先花一輪 15 分鐘跑基線。用一個基線必紅的閘來證明它真的沒跑到。
    fxr = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_pr, _w, _x = GC.probe_gate(fxr, BASELINE_RED_GATE, GC.Sample(
        plant_bad, "bad.txt", preflight=lambda fx: ("blocked", "工具不在")))
    checks.append(("preflight 排在基線**之前**(不是先跑完才問前置)",
                   v_pr == "unverified-blocked"))

    # setup 的第 0 問:宣稱種了產物,就驗產物真的在。
    fxs1 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_s1, why_s1, _x = GC.probe_gate(fxs1, blocking_gate(fxs1), GC.Sample(
        plant_bad, "bad.txt", setup=lambda fx: (None, {"files": ["沒種下去.json"]})))
    checks.append(("setup 說種了而檔案不在 → unverified-blocked(KN-008 第 0 問)",
                   v_s1 == "unverified-blocked" and "產物沒種下去" in why_s1))
    checks.append(("setup 的第 0 問**做在 harness 裡**,不是各樣本自律",
                   GC.verify_setup(fxs1, {"files": ["也沒有.json"]}) is not None))
    (fxs1 / "空的.json").write_text("   ", encoding="utf-8")
    checks.append(("setup 種了一個空產物 → 具名擋下(空 ≠ 有,KN-006)",
                   "是空的" in (GC.verify_setup(fxs1, {"files": ["空的.json"]}) or "")))
    (fxs1 / "壞的.json").write_text("{不是 JSON", encoding="utf-8")
    checks.append(("setup 種的 JSON parse 不動 → 具名擋下(否則閘紅在解析)",
                   "不是合法 JSON" in (GC.verify_setup(fxs1, {"files": ["壞的.json"]}) or "")))
    checks.append(("setup 宣告的 env 是空字串 → 具名擋下(空值會被讀成沒給)",
                   "空字串" in (GC.verify_setup(fxs1, {"env": {"X": "  "}}) or "")))
    # setup 失敗**不得漏到 baseline-red**:漏過去的話,失效方向會變成
    # 「這道閘在乾淨的樹上就紅」,而那是最貴的一種錯誤答案。
    fxs2 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_s2, why_s2, _x = GC.probe_gate(fxs2, BASELINE_RED_GATE, GC.Sample(
        plant_bad, "bad.txt", setup=lambda fx: ("種不出來", {})))
    checks.append(("setup 失敗 → 具名 unverified-blocked,**不是 baseline-red**",
                   v_s2 == "unverified-blocked" and "種不出來" in why_s2))
    # seeded fixture 上的 blocks 與裸 fixture 上的 blocks 是**兩個不同強度的宣稱**,
    # 所以 setup 要具名進 artifact row(fable)。
    fxs3 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    (fxs3 / "種好的.json").write_text('{"a": 1}', encoding="utf-8")
    _v, _w, x_s3 = GC.probe_gate(fxs3, blocking_gate(fxs3), GC.Sample(
        plant_bad, "bad.txt",
        setup=lambda fx: (None, {"files": ["種好的.json"], "env": {"K": "v"},
                                 "note": "頂替了某條路徑"})))
    checks.append(("setup 具名進 artifact row(seeded 的 blocks 是較弱的宣稱)",
                   x_s3.get("setup", {}).get("files") == ["種好的.json"]
                   and x_s3["setup"]["env"] == ["K"]
                   and "頂替" in x_s3["setup"]["note"]))
    checks.append(("每一輪都記下基線牆鐘秒數(**預算判定要有數字,不要推論**)",
                   isinstance(x_s3.get("baseline_s"), float)))

    # 預算:上限之上沒有撥盤。宣告超過上限 → **具名紅,不是靜靜夾住**。
    fxb = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_b, why_b, _x = GC.probe_gate(fxb, blocking_gate(fxb), GC.Sample(
        plant_bad, "bad.txt", budget=GC.MAX_PROBE_BUDGET + 1))
    checks.append(("樣本宣告的預算超過治理過的上限 → 具名 unverified-blocked",
                   v_b == "unverified-blocked" and "上限之上沒有撥盤" in why_b))
    checks.append(("上限**大於**預設值(否則撥盤沒有可撥的空間)",
                   GC.MAX_PROBE_BUDGET > GC.DEFAULT_PROBE_BUDGET))
    # 硬截止在外層:`run_gate` 自己也要夾,不能只靠欄位驗證(codex)。
    seen_timeout = {}
    orig_sub = GC.subprocess.run

    def spy(*a, **k):
        seen_timeout["t"] = k.get("timeout")
        raise OSError("不真的跑")

    setattr(GC.subprocess, "run", spy)
    try:
        GC.run_gate(REPO, "irrelevant", GC.MAX_PROBE_BUDGET * 10)
    finally:
        setattr(GC.subprocess, "run", orig_sub)
    checks.append(("`run_gate` 把逾時**硬夾**到上限(欄位驗證之外的第二層)",
                   seen_timeout.get("t") == GC.MAX_PROBE_BUDGET))

    # 差分:這一輪紅**而對照輪綠**才算擋得住那條軸。
    fxd = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_d, why_d, _x = GC.probe_gate(fxd, blocking_gate(fxd), GC.Sample(
        plant_bad, "bad.txt", also_green='bash -c "exit 0"'))
    checks.append(("這輪紅、對照輪綠 → blocks 且證據說「差分成立」",
                   v_d == "blocks" and "差分成立" in why_d))
    fxd2 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_d2, why_d2, _x = GC.probe_gate(fxd2, blocking_gate(fxd2), GC.Sample(
        plant_bad, "bad.txt",
        also_green='bash -c "if test -f bad.txt; then echo 對照輪也看到 bad.txt; exit 1; fi"'))
    checks.append(("兩輪都紅**而對照輪也指名了樣本** → 樣本不是軸專屬的",
                   v_d2 == "sample-out-of-range" and "不是軸專屬" in why_d2))
    # 對照輪紅**在別處**:那是儀器的問題,不記在樣本頭上(fable 的第三格)。
    fxd3 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_d3, why_d3, _x = GC.probe_gate(fxd3, blocking_gate(fxd3), GC.Sample(
        plant_bad, "bad.txt",
        also_green='bash -c "if test -f bad.txt; then echo 紅在別的地方; exit 1; fi"'))
    checks.append(("對照輪紅在別處 → unverified-blocked,**不記在樣本頭上**",
                   v_d3 == "unverified-blocked" and "紅在別處" in why_d3))
    # 對照輪在**未變異**的 fixture 上就紅 → 兩輪都要先綠,差分才有意義。
    fxd4 = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_d4, why_d4, _x = GC.probe_gate(fxd4, blocking_gate(fxd4), GC.Sample(
        plant_bad, "bad.txt", also_green=BASELINE_RED_GATE))
    checks.append(("對照輪的基線就紅 → baseline-red(**兩輪都要先綠**)",
                   v_d4 == "baseline-red" and "兩輪都要先綠" in why_d4))

    # **差分軸的成立條件站在 `run_gate` 的一行 env 上。**
    # 這台機器原生非 UTF-8,裸印 emoji 在原生 stdio 下**對照輪也會紅**;
    # 對照輪之所以綠,是因為 `run_gate` 強制供給 `PYTHONIOENCODING=utf-8`。
    # 日後有人動掉那一行,兩輪皆紅 → out-of-range,而**沒有東西會抗議**。
    # 把這個耦合從記性變成機器(fable)。
    seen_env = {}

    def spy_env(*a, **k):
        seen_env.update(k.get("env") or {})
        raise OSError("不真的跑")

    setattr(GC.subprocess, "run", spy_env)
    try:
        GC.run_gate(REPO, "irrelevant")
    finally:
        setattr(GC.subprocess, "run", orig_sub)
    checks.append(("`run_gate` 供給 PYTHONIOENCODING=utf-8(cp932 差分的對照輪靠它才綠)",
                   seen_env.get("PYTHONIOENCODING") == "utf-8"))
    checks.append(("`run_gate` 供給 $PY(接線上每一行都引用它)", "PY" in seen_env))
    # 樣本專屬的 env 走 setup 宣告,**不進全域預設**——混進去的話,
    # 一個樣本改掉的環境會無聲地跟著下一道閘走。
    checks.append(("樣本專屬的 env 不在 `run_gate` 的全域預設裡",
                   "DIFFCOV_CHG" not in seen_env))

    # 乙丙組 8 則各自的宣告要對:差分兩則互為對照、兩則帶 preflight、一則帶 setup。
    cp932 = GC.SAMPLES["run all test_*.py(非 UTF-8 stdio 輪:cp932)"]
    utf8 = GC.SAMPLES["run all test_*.py(UTF-8 profile 輪:= hosted runner 的編碼環境)"]
    gates_now = GC.discover(REPO)
    checks.append(("cp932 那則的對照輪**真的是接線上的預設輪**",
                   cp932.also_green is not None
                   and cp932.also_green.split()
                   == gates_now["run all test_*.py"]["cmd"].split()))
    checks.append(("UTF-8 那則的對照輪**真的是接線上的 cp932 輪**",
                   utf8.also_green is not None
                   and utf8.also_green.split()
                   == gates_now["run all test_*.py(非 UTF-8 stdio 輪:cp932)"]["cmd"].split()))
    checks.append(("UTF-8 那則先探差分軸在不在(原生就是 UTF-8 時軸不存在)",
                   utf8.preflight is not None))
    checks.append(("behave 那兩道都先探 behave 在不在",
                   GC.SAMPLES["run behaviour specs"].preflight is not None
                   and GC.SAMPLES["operational verify"].preflight is not None))
    checks.append(("diff coverage 那則靠 setup 種產物與宣告 env",
                   GC.SAMPLES["diff coverage"].setup is not None))
    # 樣本種在 coverage 量得到的地方——`.github` 在 `--source` 之外,
    # 種在那裡會恆走 out_of_scope,等於量到一個真閘給不出的 `blocks`(fable)。
    fxdc = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    setup_dc = GC.SAMPLES["diff coverage"].setup
    assert setup_dc is not None, "上一條斷言已經要求它非 None"
    _why_dc, decl_dc = setup_dc(fxdc)
    rep_dc = json.loads((fxdc / "artifacts/coverage-report.json")
                        .read_text(encoding="utf-8"))
    checks.append(("diff coverage 的合成 report 只列 skills/ 下的檔"
                   "(`.github` 在 coverage --source 之外,種在那裡恆走 out_of_scope)",
                   bool(rep_dc["files"])
                   and all(k.startswith("skills/") for k in rep_dc["files"])))
    checks.append(("合成 report 真的把樣本的行列進 missing_lines"
                   "(沒有條目時 `miss is None` → out_of_scope → rc 0,樣本會靜靜飄過)",
                   all(d.get("missing_lines") for d in rep_dc["files"].values())))
    checks.append(("`DIFFCOV_CHG` 走 setup 宣告(fixture 是 detached,分支名推不出編號)",
                   "DIFFCOV_CHG" in decl_dc["env"] and "頂替" in decl_dc["note"]))
    _bad_dc = GC.SAMPLES["diff coverage"].mutate(fxdc)
    checks.append(("diff coverage 的變異種在 report 列的那支檔上(兩邊要對得上)",
                   _bad_dc is None
                   and all((fxdc / k).is_file() for k in rep_dc["files"])))

    # **證據字串不得說一件沒做過的檢查。**
    fxw = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    _v, why_w, _x = GC.probe_gate(fxw, blocking_gate(fxw),
                                  GC.Sample(plant_bad, "bad.txt"))
    checks.append(("有 witness 的證據說「輸出指名了」", "指名了" in why_w))
    fxn = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    _v, why_n, _x = GC.probe_gate(fxn, blocking_gate(fxn), GC.Sample(plant_bad))
    checks.append(("沒有 witness 的證據**明說未做歸因**(不得抄一句沒發生的檢查)",
                   "未做歸因" in why_n and "指名了" not in why_n))

    # 綠燈的射程證明:變異**後**的輸出提過樣本,一樣算在射程內。
    fxo = Path(tempfile.mkdtemp(prefix="gc-fx-"))
    v_o, why_o, _x = GC.probe_gate(
        fxo, 'bash -c "test -f bad.txt && echo 掃到 bad.txt 但放行; exit 0"',
        GC.Sample(plant_bad, "bad.txt"))
    checks.append(("掃到了卻放行 → fail-open(變異後的輸出也算射程證明)",
                   v_o == "fail-open" and "變異後" in why_o))

    # `resolve_py` 三個候選都探不到時**不得回絕對路徑**(那是缺陷①的還魂)。
    orig_sp = GC.subprocess.run
    setattr(GC.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("無")))
    try:
        fallback = GC.resolve_py()
    finally:
        setattr(GC.subprocess, "run", orig_sp)
    checks.append(("直譯器都探不到時不回絕對路徑", fallback == ""))
    # 大小寫樣本的兩條負路徑:清單空的、以及沒有 `skills/` 開頭的路徑。
    checks.append(("錨定清單空的 → 具名說改不出來",
                   "空的" in (GC._wrong_case_path({"files": []}) or "")))
    checks.append(("沒有 skills/ 開頭的路徑 → 具名說改不出來",
                   "沒有以 skills/ 開頭" in (GC._wrong_case_path({"files": [".github/a"]}) or "")))

    # ---- 樣本的負路徑:讀不到 / 內容不合用,一律**具名**,不得靜靜當作種好了 ----
    bare = Path(tempfile.mkdtemp(prefix="gc-bare-"))
    named = []
    for gate_name, smp in sorted(GC.SAMPLES.items()):
        got = smp.mutate(bare)
        if got is not None and str(got).strip():
            named.append(gate_name)
    checks.append((f"空 fixture 上,吃檔案的樣本都具名說不行(實得 {len(named)} 則)",
                   len(named) >= 5))

    # 內容在、但不合用:空清冊、沒有帶版號的 plugin 條目。
    edge = _sample_fixture()
    (edge / "skills" / "ai-sdlc-autopilot" / "assets" / "claim_manifest.json").write_text(
        json.dumps({"claims": []}), encoding="utf-8")
    checks.append(("清冊是空的 → 具名說改不出不一致",
                   "空的" in (GC.SAMPLES["claim manifest"].mutate(edge) or "")))
    (edge / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "p"}]}), encoding="utf-8")
    checks.append(("沒有帶版號的 plugin 條目 → 具名說改不出來",
                   "找不到帶版號" in (GC.SAMPLES["catalog version"].mutate(edge) or "")))

    # ---- 兩個 preflight 的每一條分支 ----
    #
    # 它們是**純觀測**函式,所以可以直接餵它們真的 repo,再用替身走另外幾條。
    # 不直接測的話,那幾條分支只有在「這台機器剛好缺工具」時才走得到
    # ——而那等於把判準交給環境的運氣。
    checks.append(("behave 在場時 preflight 回 ready 並帶版本",
                   GC._behave_present(REPO)[0] == "ready"))
    # **不寫死這台機器的編碼**:UTF-8 那一輪(`PYTHONUTF8=1`)會讓往返探針成功,
    # 於是任何「原生非 UTF-8」的斷言都會在那一輪紅——而那是斷言依賴環境,
    # 不是被測物有缺陷。真呼叫只驗它**與能力探針的答案一致**,兩條分支用替身走。
    sys.path.insert(0, str(REPO / "skills/ai-sdlc-autopilot/scripts"))
    from lib.capabilities import supports  # noqa: E402
    _axis = GC._utf8_axis_exists(REPO)[0]
    checks.append(("差分軸探測的答案與能力探針一致(在任何編碼環境下都成立)",
                   _axis == ("blocked" if supports("utf8_locale") else "ready")))

    def _fake_run(rc, out):
        return lambda *a, **k: (rc, out)

    orig_rg = GC.run_gate
    try:
        setattr(GC, "run_gate", _fake_run(1, "ModuleNotFoundError"))
        st, why = GC._behave_present(REPO)
        checks.append(("behave 缺席 → blocked(**規格層不會執行**,不是通過)",
                       st == "blocked" and "不會執行" in why))
        setattr(GC, "run_gate", _fake_run(-1, "TIMEOUT"))
        st, why = GC._behave_present(REPO)
        checks.append(("探測 behave 時逾時 → error(探壞了 ≠ 探不到,KN-003)",
                       st == "error" and "自己出錯" in why))
        setattr(GC, "run_gate", _fake_run(1, ""))
        st, why = GC._utf8_axis_exists(REPO)
        checks.append(("往返探針跑不起來 → error(不得沉默當成 ready)",
                       st == "error" and "跑不起來" in why))
        setattr(GC, "run_gate", _fake_run(0, "no\n"))
        st, why = GC._utf8_axis_exists(REPO)
        checks.append(("往返失敗 = 非 UTF-8 機器 → ready,差分軸在",
                       st == "ready" and "差分軸在" in why))
        setattr(GC, "run_gate", _fake_run(0, "yes\n"))
        st, why = GC._utf8_axis_exists(REPO)
        checks.append(("原生就是 UTF-8 → blocked:**差分軸不存在**,樣本不可能只紅一邊",
                       st == "blocked" and "差分軸不存在" in why))
        setattr(GC, "run_gate", _fake_run(0, "誰知道\n"))
        st, _w = GC._utf8_axis_exists(REPO)
        checks.append(("往返探針回了看不懂的答案 → error", st == "error"))
        # 基線在預算內跑不完:那是**沒驗成**,不是「這道閘壞了」。
        setattr(GC, "run_gate", _fake_run(-1, "TIMEOUT"))
        v_to, why_to, _x = GC.probe_gate(Path(tempfile.mkdtemp(prefix="gc-fx-")),
                                         "irrelevant", GC.Sample(plant_bad, "bad.txt"))
        checks.append(("基線在預算內跑不完 → unverified-blocked(不是 baseline-red)",
                       v_to == "unverified-blocked" and "跑不完" in why_to))
    finally:
        setattr(GC, "run_gate", orig_rg)

    # ---- 剝理由參數的兩條早退 ----
    checks.append(("不是以引號開頭就原樣回(那不是 `gated_step` 的理由參數)",
                   GC._strip_reason_arg("  bash x.sh") == "  bash x.sh"))
    checks.append(("引號沒有收尾也原樣回——**猜一個結尾比留著更糟**",
                   GC._strip_reason_arg(' "沒收尾 bash x.sh') == ' "沒收尾 bash x.sh'))

    # ---- 「樣本過期」那幾條路必須真的走得到 ----
    #
    # 每一則樣本都綁在真樹的某個形狀上(AGENTS.md 的句型、錨定清單的內容)。
    # 那些形狀會變,而**樣本沉默地失效比它紅掉更糟**——沉默的那一種會讓
    # 「這道閘擋得住」繼續掛在清冊上。所以具名的過期路徑要有斷言看著。
    exp = _sample_fixture()
    (exp / "skills/ai-sdlc-autopilot/assets/doc_counts.json").write_text(
        json.dumps({"claims": [{"id": "x", "file": "AGENTS.md",
                                "measure": "feature_files", "pattern": "x"}]}),
        encoding="utf-8")
    checks.append(("doc_counts 裡沒有 test_files 的宣稱 → 具名說樣本過期",
                   "樣本過期" in (GC._bump_test_counts(exp) or "")))

    exp2 = _sample_fixture()
    (exp2 / "AGENTS.md").write_text("句型被改寫過了\n", encoding="utf-8")
    checks.append(("支數的句型被改寫 → 具名說命中 0 次(**不是靜靜跳過**)",
                   "命中 0 次" in (GC._bump_test_counts(exp2) or "")))

    # 錨定清單裡**只剩驗證器自己**:竄改它會讓紅的形狀不可預測,所以要跳過;
    # 跳完沒有別的可改時,回具名理由——不是回 None 假裝種好了。
    exp3 = _sample_fixture()
    (exp3 / "skills/ai-sdlc-autopilot/assets/verifier_manifest.json").write_text(
        json.dumps({"files": ["skills/ai-sdlc-autopilot/scripts/verifier_integrity.py"]}),
        encoding="utf-8")
    why3 = GC._bad_verifier_integrity(exp3)
    checks.append(("錨定清單只剩驗證器自己 → 具名阻礙(**不自噬**)",
                   why3 is not None and "只剩驗證器自己" in why3))

    # 中和用的插入點會隨 `verifier_integrity.py` 改版而消失,而**樣本沉默失效
    # 比它紅掉更糟**:沉默的那一種會讓「這道閘擋得住」繼續掛在清冊上。
    exp4 = _sample_fixture()
    (exp4 / "skills/ai-sdlc-autopilot/scripts/verifier_integrity.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8")
    why4 = GC._bad_operational_verify(exp4)
    checks.append(("中和的插入點不見了 → 具名說樣本過期(不是靜靜當作種好了)",
                   why4 is not None and "樣本過期" in why4))

    # ---- probe_all / main 的真實輸出路徑 ----
    # `Fixture` 換成一個**真的有目錄**的輕量替身:走完 `probe_all` 的主體,
    # 而不必為了覆蓋率開 21 個 worktree(那要二十分鐘)。
    class LightFixture:
        def __init__(self, repo, allow_dirty=False):
            self.path = Path(tempfile.mkdtemp(prefix="gc-light-"))
            self.dirty = ["M x.py"]          # 髒樹那一格也要走到

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    two = _repo_with_ci('step "甲關"   true\nstep "乙關"   true\n')
    orig_fx, orig_samples = GC.Fixture, GC.SAMPLES
    setattr(GC, "Fixture", LightFixture)
    setattr(GC, "SAMPLES", {"甲關": GC.Sample(lambda fx: None, "甲")})
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rows, probs = GC.probe_all(two)
        by = {r["claim_id"]: r for r in rows}
        checks.append(("有樣本的閘走完探測流程", "gate::甲關" in by))
        checks.append(("沒樣本的閘記成 no-sample(**不是「沒問題」**)",
                       by["gate::乙關"]["verdict"] == "no-sample"))
        checks.append(("髒工作樹被記在該筆上", by["gate::甲關"].get("dirty_worktree") == 1))
        checks.append(("樣本表與接線一致時對帳沉默", probs == []))
        with contextlib.redirect_stdout(io.StringIO()):
            only_rows, _ = GC.probe_all(two, only="甲關")
        checks.append(("`--gate` 只探那一道",
                       [r["claim_id"] for r in only_rows] == ["gate::甲關"]))

        rc, out = run_main(two)
        checks.append(("有未證明的閘 → rc 3", rc == 3))
        checks.append(("輸出印出髒工作樹的警告", "未提交內容" in out))
        checks.append(("輸出逐條印出判定", "gate::乙關" in out))
    finally:
        setattr(GC, "Fixture", orig_fx)
        setattr(GC, "SAMPLES", orig_samples)

    # 全部擋得住 → rc 0;有 fail-open → rc 1。兩條退出碼各走一次。
    setattr(GC, "Fixture", LightFixture)
    orig_probe2 = GC.probe_gate
    one_gate = _repo_with_ci('step "甲關"   true\n')
    try:
        setattr(GC, "SAMPLES", {"甲關": GC.Sample(lambda fx: None, "甲")})
        setattr(GC, "probe_gate", lambda *a, **k: ("blocks", "fixture", {}))
        rc, out = run_main(one_gate)
        checks.append(("每道閘都擋得住 → rc 0", rc == 0))
        checks.append(("訊息說每道閘都轉紅了", "都對壞樣本轉紅" in out))
        setattr(GC, "probe_gate", lambda *a, **k: ("fail-open", "fixture", {}))
        rc, out = run_main(one_gate)
        checks.append(("有 fail-open → rc 1", rc == 1))
        checks.append(("訊息說它沒在擋", "沒在擋任何東西" in out))
        rc, out = run_main(one_gate, "--json")
        checks.append(("--json 下不印人看的摘要", _json_ok(out)))
    finally:
        setattr(GC, "Fixture", orig_fx)
        setattr(GC, "probe_gate", orig_probe2)
        setattr(GC, "SAMPLES", orig_samples)

    # ---- 這支測試檔本身報得出失敗嗎 ----
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_bad = report([("假的失敗", False), ("假的通過", True)])
    checks.append(("報告函式對失敗回 1 並指名哪一條",
                   rc_bad == 1 and "[FAIL] 假的失敗" in buf.getvalue()))
    return report(checks)


# **定義在 `main()` 之後**:`test_gates_wired` 有一條規則是「斷言不得排在計分之後」
# (CHG-20260805-04)。那條規則以**行序**判定,而 `report()` 裡就有 `failed = [`
# ——定義在前會讓這支檔被誤判。CHG-20260813-08 在 `test_behave_step_probe.py`
# 踩過一模一樣的一次,而我在下一個檔又踩了一次:**靠記性維持的規則會重複違反**
# (KN-005)。這條註解不能防止第三次,`test_gates_wired` 那條規則才能。
def _json_ok(text: str) -> bool:
    """輸出是不是**純** JSON。`--json` 混進人看的摘要時,解析當場炸掉。"""
    import json as _j
    try:
        _j.loads(text)
        return True
    except ValueError:
        return False


def report(checks: list) -> int:
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
