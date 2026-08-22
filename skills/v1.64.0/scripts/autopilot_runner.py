#!/usr/bin/env python3
"""
autopilot_runner.py — ai-sdlc-autopilot 驅動器(狀態機與裁判;不含 LLM)

施工與審查由外部 headless agent 指令執行(--agent-cmd,模板中 {brief} 代入簡報檔路徑);
runner 只負責:解析計畫、裁決停點、驅動角色單元、打勾與 commit、維護 live handshake。

角色可單獨呼叫(拆指令**非治理繞道**:每個角色走同一 halt policy 與同一帳本,
前置條件缺失一律 halt);`run` 由這些角色組合而成。

用法:
  python3 autopilot_runner.py plan-check --chg <CHG.md>        # = plan
  python3 autopilot_runner.py plan   --chg <CHG.md>
  python3 autopilot_runner.py build  --chg <CHG.md> --repo . [--single] [--agent-cmd T] [--test-cmd C]
  python3 autopilot_runner.py review --chg <CHG.md> --repo .
  python3 autopilot_runner.py verify --chg <CHG.md> --repo . [--verify-cmd V]
  python3 autopilot_runner.py accept --chg <CHG.md> --repo . [--verified]
  python3 autopilot_runner.py run    --chg <CHG.md> --repo . [...]
  python3 autopilot_runner.py status --chg <CHG.md>
  python3 autopilot_runner.py sentinels --repo . [--chg <CHG.md>] [--reentry-count N]

退出碼:0=完成 | 1=非預期錯誤 | 2=計畫無效 | 3=合法停點(原因已印出;cron/CI 據此接線)
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import roles  # noqa: E402
from lib.exec_util import die  # noqa: E402

# 釘住輸出編碼(CHG-20260803-01 T1):不依賴主控台/locale 的 ambient 編碼。
# 非 UTF-8 主控台(如 Windows cp932)印 CJK/emoji 會 UnicodeEncodeError;
# 釘住後同一份程式在任何平台的輸出行為一致。errors="replace" 確保永不因輸出而崩潰。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 角色名 → 實作。plan-check 為 plan 的相容別名。
ROLES = {
    "plan": roles.role_plan,
    "plan-check": roles.role_plan,
    "build": roles.role_build,
    "review": roles.role_review,
    "verify": roles.role_verify,
    "accept": roles.role_accept,
    "run": roles.role_run,
    "status": roles.role_status,
}
NEEDS_REPO = ("build", "review", "verify", "accept", "run")


def cmd_sentinels(args) -> int:
    """drive 層委派:呼叫 autopilot_sentinels.py poll(兩層跳脫 + 排程尾遞迴)。"""
    here = Path(__file__).resolve().parent
    cmd = [sys.executable, str(here / "autopilot_sentinels.py"), "poll", "--repo", args.repo]
    for flag, val in (("--chg", args.chg), ("--policy", args.policy)):
        if val:
            cmd += [flag, val]
    if args.reentry_count:
        cmd += ["--reentry-count", str(args.reentry_count)]
    return subprocess.run(cmd).returncode


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="ai-sdlc-autopilot runner(角色單元 + 組合)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sentinels", help="確定性哨兵輪詢(兩層跳脫)")
    ps.add_argument("--repo", default=".")
    ps.add_argument("--chg", default=None)
    ps.add_argument("--policy", default=None)
    ps.add_argument("--reentry-count", type=int, default=0)

    for name in ROLES:
        p = sub.add_parser(name)
        p.add_argument("--chg", required=True)
        p.add_argument("--policy", default=None, help="autopilot_policy.json 路徑(預設內建矩陣)")
        p.add_argument("--interaction-kinds", default=None,
                       help="互動驗證分類表路徑(預設 assets/interaction_kinds.json);"
                            "可指向自己的表以增補種類")
        if name in NEEDS_REPO:
            p.add_argument("--repo", default=".")
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--confirmed", action="store_true", help="人已於確認閘核可")
        # review 也需要審查指令:整支 branch 的末端審查已不再是 no-op(CHG-20260803-02 T6),
        # 它必須真的把 diff 交給一個模型看過。
        if name in ("build", "run", "review"):
            p.add_argument("--agent-cmd", default=None, help="headless agent 指令模板,{brief}=簡報檔路徑")
            # 審查面板(CHG-20260803-09):席次由風險分級決定,低風險維持單席快速路徑。
            p.add_argument("--review-panel", type=int, default=None,
                           help="審查面板席次(可往上加,不得低於風險分級的下限:低 1 / 中 3 / 高 3)")
            p.add_argument("--seat-cmd", action="append", default=None, metavar="SEAT=CMD",
                           help="逐席指定審查指令(可重複),如 --seat-cmd spec='claude -p ...';"
                                "未指定則全席沿用 --review-cmd 並印出同模型警語")
            p.add_argument("--confidence-threshold", type=int, default=None,
                           help="判定行的信心門檻(預設 80);低於此值的判定降級為 cannot-verify,"
                                "**不會**被拿去平均")
            p.add_argument("--review-cmd", default=None,
                           help="審查用的指令模板(可指向與施工不同的模型);未給則回退 --agent-cmd 並註明「同模型」限制")
        if name in ("build", "run"):
            p.add_argument("--test-cmd", default=None, help="每個 task 的單元/build 測試指令")
            p.add_argument("--static-allowlist", default=None,
                           help="靜態/安全檢查的具名豁免清單(預設 ai-sdlc/assets/static_allowlist.json)")
            p.add_argument("--allow-untested", action="store_true",
                           help="明示允許不執行任何測試(agent 寫的程式碼將未經執行即打勾);"
                                "僅適用純文件 task,會印警告並留痕")
            # CHG-20260803-07:變異閘改為**預設開啟**。缺 --test-cmd 會 halt(存在性強制),
            # 而唯一檢驗「測試夠不夠強」的閘卻要人記得加旗標——這個排序反了。
            p.add_argument("--mutation", action="store_true",
                           help="(相容保留,已無作用)變異閘自 v1.10.0 起預設開啟")
            p.add_argument("--no-mutation", action="store_true",
                           help="明示關閉變異閘(測試強度本輪不驗);會印警告並留痕,須記入 ACC 的未涵蓋欄")
            # CHG-20260803-08:測試棘輪與不穩定測試偵測的兩個逃生口。
            p.add_argument("--allow-test-reduction", action="store_true",
                           help="明示允許本次變更淨減少測試/斷言數(正當的測試重構);"
                                "會印警告並留痕,須記入 ACC 的未涵蓋欄")
            p.add_argument("--flaky-runs", type=int, default=None,
                           help="單元測試轉綠後在同一份程式碼上總共跑幾次(預設 2,下限 1);"
                                "設為 1 等同關閉不穩定測試偵測,會留痕")
            p.add_argument("--max-fix-rounds", type=int, default=None,
                           help="單一 task 的回修輪數上限(預設 3,下限 1);"
                                "每一輪都會把上一輪的失敗原文帶進 brief")
            p.add_argument("--escalate-cmd", default=None,
                           help="最後一輪改用的施工指令(通常指向更強的模型);"
                                "未給則沿用 --agent-cmd 並註明「同模型升階只換提示不換盲點」")
            p.add_argument("--min-kill-rate", type=float, default=90.0,
                           help="變異閘門檻(預設 90);低於此值視同該 task 未通過")
            p.add_argument("--mutation-max", type=int, default=40,
                           help="每個檔案的變異體取樣上限(0=不設限);丟棄數會如實回報")
            p.add_argument("--test-platforms", default=None,
                           help="宣告本變更的測試應涵蓋哪些平台(逗號分隔,如 linux,macos,windows);"
                                "runner 不代跑,只記錄差集供 ACC 標注未涵蓋")
            p.add_argument("--no-commit", action="store_true")
            p.add_argument("--max-tasks", type=int, default=0)
        if name == "build":
            p.add_argument("--single", action="store_true", help="只做下一個未完成 task")
        if name in ("verify", "run"):
            p.add_argument("--verify-cmd", default=None, help="末端操作測試指令(把變更真的跑一次)")
        # 信任邊界的旗標掛在**所有會執行 repo 內容裡的指令**的階段(CHG-20260803-05;
        # CHG-20260806-04 起 accept 的本機閘也是其中之一)。build 永遠不在其中——
        # 那裡沒有任何指令來自 CHG 內容。
        if name in ("verify", "run", "accept"):
            p.add_argument("--trust-chg-commands", action="store_true",
                           help="明示信任 CHG 檔案內宣告的互動驗證指令並執行之。"
                                "預設不執行——那是內容驅動執行:能讓 CHG 進到 repo 的人"
                                "就能讓 autopilot 跑任意 shell 指令")
            p.add_argument("--interaction-cmd", default=None,
                           help="覆寫 CHG 宣告的互動驗證指令(供 CI 注入);產物檢查仍照 CHG 宣告")
            p.add_argument("--nonfunctional-kinds", default=None,
                           help="非功能性驗證的分類表(效能/負載/併發/資源/可重現/授權/合約/視覺/屬性);"
                                "適用範圍依 .ai-sdlc/profile.json 宣告的專案型態決定")
            p.add_argument("--quality-baseline", default=None,
                           help="委派驗證的基線檔(預設 autopilot/assets/quality_baseline.json);"
                                "基線內的發現放行(每條須具名理由),新增的一律擋,且基線只准往下")
            p.add_argument("--quality-kinds", default=None,
                           help="委派型驗證的分類表(型別/覆蓋率/SAST/相依漏洞);可指向自訂表")
            p.add_argument("--gherkin-cmd", default=None,
                           help="行為規格執行指令(預設 `behave --strict`);"
                                "CHG 的 ### Behaviour spec 宣告的每個 .feature 都會被跑一次")
        if name in ("accept", "run"):
            p.add_argument("--pr", default=None, help="PR 編號(供 CI 閘查詢;未給則由 gh 依分支推斷)")
            p.add_argument("--ci-cmd", default=None,
                           help="自訂 CI 狀態查詢指令,須輸出 [{name,bucket}] 的 JSON;"
                                "非 GitHub CI 用。查不到狀態一律不准合併(fail-closed)")
            p.add_argument("--allow-no-ci", action="store_true",
                           help="明示此專案沒有任何 CI 檢查(逃生口,會留痕);"
                                "「沒有檢查」與「檢查都通過」不是同一件事")
            # 合併前的本機自主檢查閘(CHG-20260806-04)。**只掛在 accept/run**——
            # 它是 merge 路徑上的閘,掛到 build 上等於把它變成別的東西。
            p.add_argument("--local-gate-cmd", default=None,
                           help="合併前在本機跑的自主檢查指令(操作者提供,優先於 CHG 宣告);"
                                "未給時依序找 CHG 的 ### 本機閘、專案的慣例載具"
                                "(.github/ci_local.sh / scripts/check.sh / make check / just check)")
            p.add_argument("--allow-no-local-gate", action="store_true",
                           help="明示略過合併前的本機自主檢查(逃生口,會留痕);"
                                "「沒有跑過」與「跑過而且通過」不是同一件事")
        if name == "accept":
            p.add_argument("--verified", action="store_true",
                           help="聲明操作驗收已通過(證據須入 ACC);缺此且未跑 verify → halt")

    args = ap.parse_args(argv[1:])
    if args.cmd == "sentinels":
        return cmd_sentinels(args)
    try:
        ctx = roles.Ctx(args)
    except ValueError as e:
        return die(str(e), 1)
    except FileNotFoundError as e:
        return die(str(e), 1)
    # build 明確分開呼叫:ROLES 是異質 callable 的 dict,mypy 只能取共同簽章,
    # 於是 fn(ctx, single=True) 被判為多餘參數——而 role_build 確實收 single。
    # 把特例寫成特例,比讓型別檢查器對整張表放水好。
    if args.cmd == "build":
        return roles.role_build(ctx, single=bool(getattr(args, "single", False)))
    return ROLES[args.cmd](ctx)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
