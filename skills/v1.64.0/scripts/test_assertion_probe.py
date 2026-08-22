#!/usr/bin/env python3
"""斷言反轉探針的單元斷言(CHG-20260805-06)。

探針自己也可能是裝飾:一個永遠回「沒有裝飾」的探針,與一個真的驗過的探針,
在輸出上完全一樣(KN-001)。所以三態各造一個 fixture,逐態驗。

Run: python3 test_assertion_probe.py → exit 0 全過,1 有失敗。
"""
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contextlib
import inspect
import io
import assertion_probe as AP  # noqa: E402

HEAD = ('import sys\n\n# 釘住輸出編碼——本 repo 每一支測試檔都這樣做(CHG-20260803-01 T1),\n# 而這份 fixture 一開始沒照做:它印中文,在 Windows 的 cp1252 管線上\n# 直接 UnicodeEncodeError,於是後面的斷言根本沒被執行到。\n# 探針把它判成「未執行」是**對的**——錯的是 fixture(CHG-20260805-06)。\nfor _s in (sys.stdout, sys.stderr):\n    if hasattr(_s, "reconfigure"):\n        _s.reconfigure(encoding="utf-8", errors="replace")\n\n\ndef main():\n    checks = []\n')
TAIL = ('    failed = [n for n, ok in checks if not ok]\n'
        '    for n, ok in checks:\n'
        '        print(f"  [{\'PASS\' if ok else \'FAIL\'}] {n}")\n'
        '    return 1 if failed else 0\n\n\n'
        'if __name__ == "__main__":\n    sys.exit(main())\n')


def write(body: str) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "t_fixture.py"
    p.write_text(HEAD + body + TAIL, encoding="utf-8")
    return p


def probe(p: Path) -> dict:
    return AP.probe_file(p)


def main() -> int:
    checks = []

    # (1) 正常:條件真的會判失敗
    ok_file = write('    checks.append(("正常斷言", 1 + 1 == 2))\n')
    r = probe(ok_file)
    checks.append(("條件取反後變紅 → 判為正常",
                   r["ok"] == 1 and not r["decorative"] and not r["not_run"]))

    # (2) 裝飾:排在計分之後 —— 執行了,但結果被丟掉
    dec_file = write(
        '    failed_early = [n for n, ok in checks if not ok]\n'
        '    print(f"early tally {len(failed_early)}")\n')
    dec_file.write_text(
        HEAD
        + '    checks.append(("先放一條正常的", 1 == 1))\n'
        + '    failed = [n for n, ok in checks if not ok]\n'
        + '    for n, ok in checks:\n'
        + '        print(f"  [{\'PASS\' if ok else \'FAIL\'}] {n}")\n'
        + '    checks.append(("排在計分之後", 2 == 2))\n'
        + '    print("  [PASS] 排在計分之後")\n'
        + '    return 1 if failed else 0\n\n\n'
        + 'if __name__ == "__main__":\n    sys.exit(main())\n',
        encoding="utf-8")
    r = probe(dec_file)
    # 條件寫成 `A or bool(x)` 這種恆真形態,自己就是一條裝飾性斷言——第一版就是這樣寫的。
    # 失敗訊息帶上實際結果:這條在 Windows 紅過,而原本的訊息只說「沒判成裝飾」,
    # 看不出是沒偵測到、還是根本沒探到(KN-003:紅要說得出實話)。
    checks.append((f"排在計分之後 → 判為裝飾(實得 {r})", len(r["decorative"]) == 1))
    checks.append(("裝飾的那一條被具名(含行號)",
                   all(":" in d for d in r["decorative"])))

    # (3) 未執行:分支永遠走不到 —— 不得判為裝飾
    nr_file = write(
        '    if False:\n'
        '        checks.append(("走不到的分支", 3 == 3))\n'
        '    checks.append(("會走到的", 1 == 1))\n')
    r = probe(nr_file)
    checks.append(("走不到的分支 → 判為未執行", len(r["not_run"]) == 1))
    checks.append(("走不到的分支 → **不得**判為裝飾", not r["decorative"]))

    # (4) 探針不得改動原始檔
    src_before = ok_file.read_text(encoding="utf-8")
    probe(ok_file)
    checks.append(("探針不改動原始檔", ok_file.read_text(encoding="utf-8") == src_before))
    checks.append(("探測後不留臨時檔",
                   [f.name for f in ok_file.parent.iterdir()] == [ok_file.name]))

    # ── CHG-20260815-01(#60-A):基線綠、同跑歸因、第四態 ────────────────
    #
    # 這支探針自己也可能是裝飾:一個「什麼都判 ok」的探針,與一個真的驗過的,
    # 在輸出上完全一樣(KN-001)。所以每一態各造一個**已知答案**的 fixture。

    # 洞 A:基線就紅的檔 → 整檔 `baseline-red`,**一個位置都不探**。
    #
    # 舊版沒有這一段,於是基線紅時兩個方向都會說謊:本來就在失敗的斷言取反後
    # 轉綠 → 誤判 `decorative`(誣指好斷言);取反後仍紅(紅在別條)→ 判 `ok`,
    # 也就是**假 verified**。後者是更貴的那一種:寬鬆錯放的代價不可見。
    red_file = write('    checks.append(("這一條本來就在失敗", 1 == 2))\n')
    r = probe(red_file)
    checks.append(("基線就紅 → 具名 baseline-red", bool(r.get("baseline_red"))))
    checks.append(("基線就紅 → **一個位置都不探**(不得產出任何判定)",
                   r["ok"] == 0 and not r["decorative"] and not r["not_run"]))
    checks.append(("baseline-red 的理由說得出「變異的紅證明不了任何事」",
                   "證明不了" in r.get("baseline_red", "")))
    checks.append(("baseline-red 仍然數得出有幾個位置(不是回 0 條)",
                   r["sites"] == 1))

    # **假 verified 那條路要真的走一次**:基線紅、而取反後仍紅。
    # 舊版對這種檔會回 `ok` —— 一條從沒被驗過的斷言拿到背書。
    fake_ok = write('    checks.append(("永遠失敗的別條", 1 == 2))\n'
                    '    checks.append(("被連坐的這條", 1 == 1))\n')
    r = probe(fake_ok)
    checks.append(("基線紅時**不得**有任何位置被判 ok(那是假 verified)",
                   r["ok"] == 0))

    # 洞 B:可達性與取反必須在**同一次行程**完成。
    #
    # 直接驗合成出來的那個運算式:它同時帶副作用標記、而值是取反後的值。
    # 分兩次跑的話,環境敏感的分支可以第一跑走到、第二跑沒走到 → 誤判 `decorative`。
    src_one = '    checks.append(("甲", 1 == 1))\n'
    whole = HEAD + src_one + TAIL
    sites = AP.assertion_sites(whole)
    mutated = AP.combined_at(whole, sites[0][0])
    checks.append(("合成的變異帶可達性標記(副作用證明它被求值過)",
                   AP.PROBE_MARK in mutated))
    checks.append(("合成的變異把原條件包成 not(...)——值就是取反後的值",
                   "not (1 == 1)" in mutated))
    checks.append(("合成的變異只有一次行程可觀測(標記與取反同一句)",
                   mutated.count(AP.PROBE_MARK) == 1))
    checks.append(("`slice_at` 取回的是原條件本身(三個切法同一套偏移)",
                   AP.slice_at(whole, sites[0][0]) == "1 == 1"))

    # 環境:探針的 cwd 必須與 `run_tests.sh` 一致(repo 根)。
    # 不一致時吃相對路徑的測試會在乾淨的樹上就紅,而那會被判成 baseline-red
    # ——**看起來像被測物有缺陷,實際上是環境沒接對**(C2 的 `PY` 那一格同族)。
    checks.append(("探針的 cwd 是 repo 根(與 run_tests.sh 相同)",
                   (AP.REPO_ROOT / ".github" / "run_tests.sh").is_file()))
    checks.append(("基線跑的是絕對路徑(cwd 被改動後相對路徑開不起來)",
                   "resolve()" in inspect.getsource(AP.baseline_green)))

    # 基線**逾時**:那是探不了,不是「這個檔沒有裝飾」。
    # 逾時與 rc 非零走同一個出口,但理由要說得出是逾時——
    # 兩者的處置不同(一個去修那個檔,一個去看機器或加預算)。
    orig_run = AP.subprocess.run

    def _timeout(*a, **k):
        raise AP.subprocess.TimeoutExpired(cmd="x", timeout=1)

    AP.subprocess.run = _timeout
    try:
        ok_base, why_base = AP.baseline_green(ok_file)
    finally:
        AP.subprocess.run = orig_run
    checks.append(("基線逾時 → 不是綠", not ok_base))
    checks.append(("基線逾時的理由說得出是逾時(不是「有裝飾」)",
                   "逾時" in why_base and "不是" in why_base))

    # `main()` 的人看輸出:基線紅的檔要**逐檔具名列出**,而且整輪走射程外出口。
    # 不列的話,它在輸出上與「探過 0 條而乾淨」長得一模一樣(KN-001)——
    # 這一格是我第一版真的漏掉的,補測試把它釘住。
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_main = AP.main(["assertion_probe.py", "--test-file", str(red_file)])
    shown = buf.getvalue()
    checks.append(("main 對基線紅的檔具名列出「基線就紅,整檔沒探」",
                   "基線就紅,整檔沒探" in shown))
    checks.append(("main 不把基線紅說成「無裝飾性斷言」",
                   "無裝飾性斷言" not in shown))
    checks.append(("全部基線紅 → 射程外出口 rc=3(與有裝飾 1、乾淨 0 都分得開)",
                   rc_main == 3))
    checks.append(("射程外的理由指向「要修的是那些檔為什麼紅」,不是去補涵蓋",
                   "不是去補涵蓋" in shown))

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
