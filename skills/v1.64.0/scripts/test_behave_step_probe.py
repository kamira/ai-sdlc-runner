#!/usr/bin/env python3
"""behave 步驟反轉探針的單元斷言(CHG-20260813-06)。

行為規格(`features/behave_step_probe.feature`)驗的是**判定**;這一份驗的是
**抽取與改寫**——那兩層在規格裡是被 mock 的 `_run_behave` 之外的部分,
而施工中的三個真缺陷全部落在這一層(哨兵讀數取錯來源、行尾正規化、
`col_offset` 當字元索引切)。

`_run_behave` 一律換成假的:這份檔不起 behave。真實管線的證明在規格那一側
(「真實管線能認出裝飾性斷言」——不 mock,種一條被 `try/except` 吞掉的斷言)。

Run: python3 test_behave_step_probe.py → exit 0 全過,1 有失敗。
"""
import ast
import fnmatch
import json
import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import behave_step_probe as BSP  # noqa: E402

REPO = Path(__file__).resolve().parents[3]

BLOCKING_STEP = """from behave import then


@then('某事應擋下')
def s(context):
    assert context.rc != 0, "預期擋下,實得通過"
"""

MULTILINE_STEP = """from behave import then


@then('某事應擋下')
def s(context):
    assert (context.rc
            != 0), "預期擋下,實得通過"
"""

NO_BLOCKING_STEP = """from behave import then


@then('某事應成功')
def s(context):
    assert context.rc == 0, "預期成功"
"""

FSTRING_STEP = """from behave import then


@then('某事應擋下')
def s(context):
    assert context.rc != 0, f"預期擋下而實得通過:{context.rc}"
"""

SWALLOWED_STEP = """from behave import then


@then('某事應擋下')
def s(context):
    try:
        assert context.rc != 0, "預期擋下,實得通過"
    except AssertionError:
        pass
"""


def write(body: str, crlf: bool = False) -> Path:
    d = Path(tempfile.mkdtemp(prefix="bsp-unit-"))
    p = d / "x_steps.py"
    data = body.replace("\n", "\r\n") if crlf else body
    p.write_bytes(data.encode("utf-8"))
    return p


class FakeBehave:
    """依序回傳預先寫好的 (rc, 輸出)。用完之後一律回綠。"""

    def __init__(self, *runs):
        self.runs = list(runs)
        self.calls = 0

    def __call__(self, feature, timeout):
        self.calls += 1
        return self.runs.pop(0) if self.runs else (0, "")


@contextlib.contextmanager
def faked(*runs):
    orig = BSP._run_behave
    fake = FakeBehave(*runs)
    setattr(BSP, "_run_behave", fake)
    try:
        yield fake
    finally:
        setattr(BSP, "_run_behave", orig)


@contextlib.contextmanager
def patched(name: str, value):
    orig = getattr(BSP, name)
    setattr(BSP, name, value)
    try:
        yield
    finally:
        setattr(BSP, name, orig)


def first_site(src: str):
    return next(iter(BSP.claim_targets(src).values()))[0]


def parses(src: str) -> bool:
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False




def main() -> int:
    checks = []

    # ---- 抽取:單位是步驟定義,判準是函式體 ----
    t = BSP.claim_targets(BLOCKING_STEP)
    checks.append(("抽得到帶阻斷語意的步驟", list(t) == ["某事應擋下"]))
    checks.append(("不含阻斷語意的步驟不進射程",
                   BSP.claim_targets(NO_BLOCKING_STEP) == {}))
    checks.append(("跨行條件抽不到位置(留給 out-of-range)",
                   BSP.claim_targets(MULTILINE_STEP)["某事應擋下"] == []))
    checks.append(("編不過的原始碼回空 dict,不拋",
                   BSP.claim_targets("def (") == {}))
    checks.append(("step_texts 讀得到 @then 文字",
                   BSP.step_texts(BLOCKING_STEP) == {"s": ["某事應擋下"]}))
    checks.append(("step_texts 對編不過的原始碼回空 dict",
                   BSP.step_texts("def (") == {}))
    checks.append(("沒有 @then 的函式不進 step_texts",
                   BSP.step_texts("def s(context):\n    pass\n") == {}))
    # `@then(某變數)` —— 裝飾器參數不是字面字串,那本來就不是步驟文字。
    checks.append(("非字面的 @then 參數不算步驟文字",
                   BSP.step_texts("from behave import then\n\n\n"
                                  "@then(NAME)\ndef s(context):\n"
                                  "    assert context.rc != 0, '不得通過'\n") == {}))
    checks.append(("claim_targets 對沒有 @then 的函式沉默",
                   BSP.claim_targets("def s(context):\n"
                                     "    assert context.rc != 0, '不得通過'\n") == {}))

    # ---- 改寫:以位元組計算,中文訊息不得被吃掉 ----
    site = first_site(BLOCKING_STEP)
    sentinel = BSP._patched(BLOCKING_STEP, site, BSP.REACH)
    negated = BSP._negated(BLOCKING_STEP, site)
    checks.append(("哨兵版含 SystemExit(97)", f"SystemExit({BSP.PROBE_EXIT})" in sentinel))
    checks.append(("哨兵版保留中文訊息", '"預期擋下,實得通過"' in sentinel))
    checks.append(("取反版包住原條件", "not (context.rc != 0)" in negated))
    checks.append(("取反版保留中文訊息", '"預期擋下,實得通過"' in negated))
    for name, src in (("哨兵版", sentinel), ("取反版", negated)):
        checks.append((f"{name}編得過", parses(src)))
    # 反向:`parses` 自己要認得出編不過的東西,否則上面兩條恆真(KN-001)。
    checks.append(("parses 認得出編不過的原始碼", parses("def (") is False))

    # ---- 零腳印:CRLF 不得被正規化 ----
    p = write(BLOCKING_STEP, crlf=True)
    before = p.read_bytes()
    with faked():
        BSP.probe_one(p, first_site(BSP._read(p)), [])
    checks.append(("探完位元組完全相同(含 CRLF)", p.read_bytes() == before))
    checks.append(("_read 不翻譯行尾", "\r\n" in BSP._read(p)))

    # ---- 歸因錨 ----
    checks.append(("字面訊息取整串",
                   BSP.assert_anchor(BLOCKING_STEP, site) == "預期擋下,實得通過"))
    fs = FSTRING_STEP
    checks.append(("f-string 取佔位符前的前綴",
                   BSP.assert_anchor(fs, first_site(fs)) == "預期擋下而實得通過:"))
    checks.append(("錨太短視同抽不到",
                   BSP.assert_anchor("assert x != 0, '預期'\n", (1, 7, 13)) is None))
    checks.append(("編不過時回 None", BSP.assert_anchor("def (", (1, 0, 1)) is None))
    checks.append(("有錨且出現在輸出裡才算歸因",
                   BSP._attributable("Assertion Failed: 預期擋下", "預期擋下") is True))
    checks.append(("錨不在輸出裡不算歸因",
                   BSP._attributable("Assertion Failed: 別的", "預期擋下") is False))
    checks.append(("**抽不到錨一律不算歸因**(不推定成功)",
                   BSP._attributable("Assertion Failed: 什麼", None) is False))
    checks.append(("不是斷言類的紅不算歸因",
                   BSP._attributable("ImportError: x", "預期擋下") is False))

    # ---- 四態 ----
    p = write(BLOCKING_STEP)
    site_p = first_site(BSP._read(p))
    feats = [Path("FAKE")]
    with faked((BSP.PROBE_EXIT, ""), (1, "Assertion Failed: 預期擋下,實得通過")):
        v, where = BSP.probe_one(p, site_p, feats, green={"FAKE": ""})
    checks.append(("哨兵響 + 歸因得到 → ok", v == "ok"))
    checks.append(("回報哨兵響過的那一支", where == "FAKE"))
    with faked((BSP.PROBE_EXIT, ""), (0, "")):
        v, _ = BSP.probe_one(p, site_p, feats, green={"FAKE": ""})
    checks.append(("取反後照樣綠 → decorative", v == "decorative"))
    with faked():
        v, _ = BSP.probe_one(p, site_p, [], green=None)
    checks.append(("哨兵沒響 → not-run(**不是 decorative**)", v == "not-run"))
    with faked():
        v, _ = BSP.probe_one(p, site_p, feats, green={})
    checks.append(("基線本來就紅 → out-of-range", v == "out-of-range"))
    with faked((BSP.PROBE_EXIT, ""), (-1, "Assertion Failed: 預期擋下,實得通過")):
        v, _ = BSP.probe_one(p, site_p, feats, green={"FAKE": ""})
    checks.append(("逾時 → out-of-range(**不是轉紅**)", v == "out-of-range"))
    with faked((BSP.PROBE_EXIT, ""), (1, "ImportError: x")):
        v, _ = BSP.probe_one(p, site_p, feats, green={"FAKE": ""})
    checks.append(("紅在別處 → out-of-range", v == "out-of-range"))

    # ---- dry_run_features:只當選片器 ----
    feat_dir = Path(tempfile.mkdtemp(prefix="bsp-feat-"))
    (feat_dir / "hit.feature").write_text("那麼 某事應擋下\n", encoding="utf-8")
    (feat_dir / "miss.feature").write_text("那麼 別的事\n", encoding="utf-8")
    with patched("FEATURES", feat_dir):
        pf = write(BLOCKING_STEP)
        picked = [f.name for f in BSP.dry_run_features(pf)]
        checks.append(("選片器挑得到含該步驟文字的 feature", picked == ["hit.feature"]))
        checks.append(("沒有步驟文字就不選任何 feature",
                       BSP.dry_run_features(write(NO_BLOCKING_STEP)) != []
                       or BSP.dry_run_features(write("x = 1\n")) == []))

    # ---- _run_behave:真的起子行程 + 逾時 ----
    rc, out = BSP._run_behave(Path("does-not-exist.feature"), timeout=60)
    checks.append(("跑不存在的 feature 回非零而不是拋", rc != 0))
    checks.append(("輸出不是空的(拿得到理由)", out != ""))

    class _Timeout:
        def __call__(self, *a, **k):
            raise subprocess.TimeoutExpired(cmd="behave", timeout=1)

    import subprocess as _sp
    orig_run = _sp.run
    _sp.run = _Timeout()
    try:
        rc, out = BSP._run_behave(Path("x.feature"), timeout=1)
    finally:
        _sp.run = orig_run
    checks.append(("逾時回 (-1, TIMEOUT) 而不是拋", (rc, out) == (-1, "TIMEOUT")))

    # ---- assert_anchor:找不到該位置 ----
    checks.append(("位置對不上任何 assert 時回 None",
                   BSP.assert_anchor(BLOCKING_STEP, (999, 0, 1)) is None))

    # ---- 基線綠 ----
    with faked((0, ""), (1, "")):
        green = BSP.baseline_green([Path("A"), Path("B")])
    # 契約改了(待補項 #58):回的是 {feature 名: 那一輪的輸出},不是集合
    # ——**那份輸出是錨的鑑別力的零近似基準**,舊版把它丟掉了。
    checks.append(("只留基線綠的 feature", set(green) == {"A"}))
    checks.append(("**基線輸出留下來**(它是鑑別力檢查的免費基準)",
                   isinstance(green, dict) and "A" in green))

    # ---- probe_file:四個桶 ----
    p = write(BLOCKING_STEP)
    orig_dry = BSP.dry_run_features
    setattr(BSP, "dry_run_features", lambda f, timeout=120: [Path("FAKE")])
    try:
        with faked((0, ""), (BSP.PROBE_EXIT, ""),
                   (1, "Assertion Failed: 預期擋下,實得通過")):
            r = BSP.probe_file(p)
        checks.append(("probe_file 記下 ok", r["ok_steps"] == ["某事應擋下"]))
        checks.append(("probe_file 記下基線綠集合", r["baseline_green"] == ["FAKE"]))
        checks.append(("四個桶都在",
                       all(k in r for k in
                           ("ok_steps", "decorative", "not_run", "out_of_range"))))
        with faked((0, "")):
            rn = BSP.probe_file(write(BLOCKING_STEP))
        checks.append(("哨兵沒響 → 落 not_run 桶",
                       rn["not_run"] == ["某事應擋下"] and rn["ok_steps"] == []))
        with faked((0, ""), (BSP.PROBE_EXIT, ""), (0, "")):
            rd = BSP.probe_file(write(BLOCKING_STEP))
        checks.append(("取反照樣綠 → 落 decorative 桶",
                       rd["decorative"] == ["某事應擋下"]))
        with faked((0, "")):
            rmax = BSP.probe_file(write(BLOCKING_STEP), max_sites=1)
        checks.append(("--max 只取前 N 個步驟", rmax["sites"] == 1))
        with faked((1, "")):        # 基線就紅 → 選片全被濾掉 → 判定射程外
            ro = BSP.probe_file(write(BLOCKING_STEP))
        checks.append(("有位置而判定全部射程外 → 落 out_of_range 桶",
                       ro["out_of_range"] == ["某事應擋下"]
                       and ro["not_run"] == [] and ro["ok_steps"] == []))
        pm = write(MULTILINE_STEP)
        with faked((0, "")):
            rm = BSP.probe_file(pm)
        checks.append(("跨行條件落 out-of-range 而非 not_run",
                       rm["out_of_range"] == ["某事應擋下"] and rm["not_run"] == []))
        # 被 try/except 吞掉的斷言:抽得到(函式體含阻斷語意),判定由實跑決定
        ps = write(SWALLOWED_STEP)
        checks.append(("吞掉的斷言仍在射程內", "某事應擋下" in BSP.claim_targets(BSP._read(ps))))

        # ---- main():三態退出碼 ----
        def run(*argv) -> tuple[int, str]:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = BSP.main(["behave_step_probe.py", *argv])
            return rc, buf.getvalue()

        rc, out = run()
        checks.append(("沒給 --steps-file 也沒給 --all → rc 2", rc == 2))
        with faked((0, ""), (BSP.PROBE_EXIT, ""),
                   (1, "Assertion Failed: 預期擋下,實得通過")):
            rc, out = run("--steps-file", str(p))
        checks.append(("探過且乾淨 → rc 0", rc == 0))
        checks.append(("訊息說出實際反轉幾條", "實際反轉" in out))
        with faked((0, ""), (BSP.PROBE_EXIT, ""), (0, "")):
            rc, out = run("--steps-file", str(p))
        checks.append(("有裝飾 → rc 1", rc == 1))
        checks.append(("訊息指名裝飾", "裝飾" in out))
        pn = write(NO_BLOCKING_STEP)
        rc, out = run("--steps-file", str(pn))
        checks.append(("一個位置都沒有 → rc 3(**射程外,不是通過**)", rc == 3))
        checks.append(("訊息說出為什麼探不到", "射程外" in out or "0 條" in out))
        # 一個檔都沒掃到:與「沒有步驟」在退出碼上一樣(KN-001)
        empty = Path(tempfile.mkdtemp(prefix="bsp-empty-"))
        with patched("STEPS_DIR", empty):
            rc, out = run("--all")
        checks.append(("一個步驟檔都沒掃到 → rc 3", rc == 3))
        checks.append(("訊息說出是搜尋壞了", "一個步驟檔都沒掃到" in out))
        # 全部未執行:探了,而一條都沒真探到
        with faked((0, "")):
            rc, out = run("--steps-file", str(p))
        checks.append(("位置全部未執行 → rc 3", rc == 3))
        checks.append(("訊息印出未執行那一行", "未執行(哨兵沒響" in out))
        with faked((0, "")):
            rc, out = run("--steps-file", str(pm))
        checks.append(("全部射程外 → rc 3", rc == 3))
        checks.append(("訊息印出射程外那一行", "射程外(探不了" in out))
        with faked((0, ""), (BSP.PROBE_EXIT, ""), (0, "")):
            rc, out = run("--steps-file", str(p))
        checks.append(("裝飾那一行有印出來", "裝飾(場景沒因為它轉紅)" in out))
        with faked((0, ""), (BSP.PROBE_EXIT, ""),
                   (1, "Assertion Failed: 預期擋下,實得通過")):
            rc, out = run("--steps-file", str(p), "--json")
        checks.append(("--json 只吐 JSON", out.lstrip().startswith("[")))
    finally:
        setattr(BSP, "dry_run_features", orig_dry)

    # **這支測試檔本身報不報得出失敗?** 報不出來的話,上面 60 幾條全是裝飾。
    # 這一組斷言是本檔唯一會走到 `report()` 失敗那條路的地方——
    # 而第一版把它寫進了 `report()` 自己的本體,於是 `report()` 成了無限遞迴的死碼,
    # **測試照樣全綠**(沒有人呼叫它)。抓到它的是 diff coverage,不是斷言。
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_bad = report([("假的失敗", False), ("假的通過", True)])
    checks.append(("報告函式對失敗回 1 並指名哪一條",
                   rc_bad == 1 and "[FAIL] 假的失敗" in buf.getvalue()))
    checks.append(("報告函式不會把通過的那條也印成 FAIL",
                   "[FAIL] 假的通過" not in buf.getvalue()))
    return report(checks)


# **定義在 `main()` 之後**:`test_gates_wired` 有一條規則是「斷言不得排在計分之後」
# (CHG-20260805-04:排在 `failed = [...]` 之後的斷言永遠不會判失敗)。
# 那條規則以**行序**判定,而 `report()` 裡就有 `failed = [`——定義在前會誤判。
# 這是規則的射程略寬,而讓步的該是這一份檔:規則保護的東西比這裡的排版重要。
def report(checks: list) -> int:
    """把結果印出來並回退出碼。**抽成函式是為了讓失敗那條路自己受測**——
    一支報不出失敗的測試檔,與一支全過的測試檔,在退出碼上一樣(KN-001)。"""
    # ── 共用判準檔(CHG-20260815-03,待補項 #55 + #56)────────────────────
    #
    # 判準原本是兩個字面 tuple 與兩個字面 glob,內容逐字相同而**沒有機制維持**。
    # 抽成資料檔之後,新的失效方向是「**檔案讀不到或是空的,被讀成沒有阻斷步驟**」
    # ——空判準與「沒有宣稱」在退出碼上一樣(KN-001),所以每一種畸形都要具名紅。
    #
    # 而載入器在兩支程式裡逐字相同,**等價性由這裡釘住**:
    # 同一組非法輸入必須在兩側得到一致的結果(codex 席)——各自手寫驗證規則
    # 就是把剛消滅的分岔換一個地方長出來。
    import importlib.util as _ilu

    _bcm_spec = _ilu.spec_from_file_location(
        "bcm_x", REPO / ".github" / "build_claim_manifest.py")
    assert _bcm_spec is not None and _bcm_spec.loader is not None,         "載不到 build_claim_manifest——**兩側等價性就無從比對**"
    _bcm = _ilu.module_from_spec(_bcm_spec)
    _bcm_spec.loader.exec_module(_bcm)

    def _crit(body) -> Path:
        d = Path(tempfile.mkdtemp(prefix="crit-"))
        f = d / "c.json"
        if body is not None:
            f.write_text(body, encoding="utf-8")
        return f

    def _both(f: Path):
        """同一份輸入餵兩側,回 (探針結果, 清冊結果)。異常一律收成訊息字串。"""
        out = []
        for mod in (BSP, _bcm):
            try:
                out.append(("ok", mod.load_criteria(f)))
            except mod.CriteriaError as e:
                out.append(("err", str(e)))
        return out

    BAD = [
        ("判準檔缺席", None, "讀不到"),
        ("不是合法 JSON", "{ 壞掉", "不是合法 JSON"),
        ("頂層不是 object", '["a"]', "頂層不是 object"),
        ("blocking_hints 缺席", '{"steps_glob": "*.py"}', "缺席或是空的"),
        ("blocking_hints 是空 list", '{"blocking_hints": [], "steps_glob": "*.py"}',
         "缺席或是空的"),
        ("blocking_hints 混進非字串", '{"blocking_hints": ["擋下", 7], "steps_glob": "*.py"}',
         "非字串"),
        ("steps_glob 缺席", '{"blocking_hints": ["擋下"]}', "缺席或是空的"),
        ("steps_glob 是空字串", '{"blocking_hints": ["擋下"], "steps_glob": "  "}',
         "缺席或是空的"),
    ]
    for label, body, want in BAD:
        a, b = _both(_crit(body))
        checks.append((f"{label} → 具名拒收(不是當成「沒有阻斷步驟」)",
                       a[0] == "err" and want in a[1]))
        checks.append((f"{label} → **兩側結果一致**(載入器沒有分岔)", a == b))

    # 正向:兩側讀到的值逐字相同,且就是真實判準檔的內容。
    real = REPO / "skills/ai-sdlc-autopilot/assets/step_probe_criteria.json"
    ra, rb = _both(real)
    raw = json.loads(real.read_text(encoding="utf-8"))
    checks.append(("兩側載入真實判準檔的結果逐字相同", ra == rb and ra[0] == "ok"))
    checks.append(("載入值就是檔案內容(不是程式裡另留一份)",
                   ra[1] == (tuple(raw["blocking_hints"]), raw["steps_glob"])))
    checks.append(("探針的 BLOCKING 來自判準檔",
                   BSP.BLOCKING == tuple(raw["blocking_hints"])))
    checks.append(("探針的 STEPS_GLOB 來自判準檔",
                   BSP.STEPS_GLOB == raw["steps_glob"]))

    # #56 的回歸鎖:命名不合 `*_steps.py` 的步驟檔,兩側都要看得到。
    # 舊版探針掃 `*_steps.py`、清冊掃 `*.py`——**一支 `helpers.py` 裡的步驟
    # 在 behave 的宇宙裡是活的**,而探針看不到它。
    checks.append(("判準檔的 glob 是 `*.py`(不是 `*_steps.py`)",
                   raw["steps_glob"] == "*.py"))
    checks.append(("命名不合 `*_steps.py` 的檔也在 glob 的射程內",
                   fnmatch.fnmatch("helpers.py", raw["steps_glob"])))

    # ---- 錨的鑑別力(待補項 #58)----
    #
    # `ANCHOR_MIN = 3` 是**長度**的啟發式,而真正的判準是**鑑別力**:
    # 一個夠長卻在歸因窗口裡到處都是的錨,`anchor in out` 對它恆真
    # ——歸因退化成只剩「有沒有 Assertion Failed」,而那正是本探針要消滅的東西。
    SAME_FILE = (
        'from behave import then\n\n\n'
        "@then('甲步驟')\n"
        'def a(context):\n'
        '    assert context.ok, "放行了:實得通過"\n\n\n'
        "@then('乙步驟')\n"
        'def b(context):\n'
        '    assert context.ok, "對帳放行了:實得通過"\n'
    )
    site_a = (6, 11, 6)          # 甲的 assert.test 位置
    checks.append(("C1:錨被**同檔另一條**的訊息包住 → 具名不具鑑別力",
                   (BSP.anchor_discriminating("放行了:", "", SAME_FILE, site_a) or "")
                   .find("同檔另一條") >= 0))
    # 用一個**真正獨一無二**的錨。第一版我拿了「對帳放行了:」,而那正是同檔乙的訊息
    # ——C1 判它降級是**對的**,錯的是我的期望值。
    checks.append(("C1:錨沒被別條包住 → 具鑑別力(不誤殺)",
                   BSP.anchor_discriminating("獨一無二的前綴:", "", SAME_FILE, site_a) is None))
    checks.append(("C1 只比對**其他** assert,不拿自己撞自己",
                   BSP.anchor_discriminating(
                       "放行了:", "", 'assert x, "放行了:"\n', (1, 7, 1)) is None))

    # C2 是**動態**的:比對基線綠那一輪的真實輸出。
    checks.append(("C2:錨已在**基線綠輸出**裡 → 具名不具鑑別力",
                   (BSP.anchor_discriminating("退出碼", "Given 退出碼應為 0\n",
                                              SAME_FILE, site_a) or "")
                   .find("基線綠輸出") >= 0))
    checks.append(("C2:錨不在基線輸出裡 → 不因此降級",
                   BSP.anchor_discriminating("獨一無二的前綴:", "Given 別的步驟\n",
                                             SAME_FILE, site_a) is None))
    # **feature 註解裡的撞名不得降級**——註解不進 behave 的輸出。
    # 這一條是「動態量比靜態猜精確」的活證據:實測 `退出碼` 在某 feature 只出現在
    # `#` 註解裡,而綠跑輸出 grep 到 0 次。靜態掃 feature 原始碼會誤殺它。
    checks.append(("feature **註解**裡的撞名不得降級(註解不進輸出)",
                   BSP.anchor_discriminating(
                       "退出碼", "Feature: x\n  Scenario: y\n    Given 別的\n",
                       SAME_FILE, site_a) is None))
    # 分不出時走**與抽不到錨同一條路**:out-of-range,不推定成功。
    checks.append(("不具鑑別力的錨回的是**具名理由**(不是 True/False)",
                   isinstance(BSP.anchor_discriminating("放行了:", "", SAME_FILE, site_a), str)))

    # f-string 訊息也要進 C1 的比對來源:格式化後的值不可預測,所以佔位符當**斷點**
    # ——只有佔位符**之前**的字面段能拿來比對,與 `assert_anchor` 同一條理由。
    FSTR_FILE = (
        'from behave import then\n\n\n'
        "@then('甲步驟')\n"
        'def a(context):\n'
        '    assert context.ok, "計畫放行了:實得通過"\n\n\n'
        "@then('乙步驟')\n"
        'def b(context):\n'
        '    assert context.ok, f"計畫放行了:{context.out}"\n'
    )
    checks.append(("C1 的比對來源含 **f-string** 訊息的字面段",
                   (BSP.anchor_discriminating("計畫放行了:", "", FSTR_FILE, (6, 11, 6))
                    or "").find("同檔另一條") >= 0))
    checks.append(("f-string 的**佔位符之後**不算比對來源(值不可預測)",
                   BSP.anchor_discriminating("實得通過", "", FSTR_FILE, (6, 11, 6)) is None))
    checks.append(("C1 對編不過的原始碼回 None(不拋)",
                   BSP.anchor_discriminating("任何錨", "", "def (", (1, 0, 1)) is None))

    # 端對端:錨不具鑑別力時,`probe_one` 必須落 out-of-range——
    # **與抽不到錨同一條路,不推定成功**。
    p2 = write(
        'from behave import then\n\n\n'
        "@then('某事應擋下')\n"
        'def s(context):\n'
        '    assert context.rc != 0, "放行了:實得通過"\n\n\n'
        "@then('別的事應擋下')\n"
        'def t(context):\n'
        '    assert context.rc != 0, "對帳放行了:實得通過"\n')
    site2 = first_site(BSP._read(p2))
    with faked((BSP.PROBE_EXIT, ""), (1, "Assertion Failed: 放行了:實得通過")):
        v2, _ = BSP.probe_one(p2, site2, [Path("FAKE")], green={"FAKE": ""})
    checks.append(("錨不具鑑別力 → out-of-range(**不推定成功**)", v2 == "out-of-range"))
    # 反向:同一份輸入,錨唯一時要判 ok——否則上一條恆真(KN-001)。
    p3 = write(
        'from behave import then\n\n\n'
        "@then('某事應擋下')\n"
        'def s(context):\n'
        '    assert context.rc != 0, "獨一無二地放行了:實得通過"\n')
    site3 = first_site(BSP._read(p3))
    with faked((BSP.PROBE_EXIT, ""), (1, "Assertion Failed: 獨一無二地放行了:實得通過")):
        v3, _ = BSP.probe_one(p3, site3, [Path("FAKE")], green={"FAKE": ""})
    checks.append(("錨唯一 → 照樣判 ok(鑑別力檢查不誤殺)", v3 == "ok"))

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
