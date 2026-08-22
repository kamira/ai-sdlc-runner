#!/usr/bin/env python3
"""變異測試引擎(CHG-20260803-01 T10)。stdlib-only、無 LLM、三平台一致。

**為什麼需要**:單元測試全綠只證明「測試沒失敗」,不證明「測試抓得到錯」。變異測試把
問題倒過來問——我故意在被測程式裡種一個錯,你的測試會不會紅?殺不掉的變異體
(surviving mutant)就是斷言的盲點:那一行改掉,沒有任何測試會知道。

**做法**:以 AST 逐點產生變異體 → 覆寫原檔 → 跑該模組的測試 → 還原。
測試非零 = 殺死;測試仍為零 = 存活。

**變異算子**(刻意只取「靜默翻轉治理語意」那一類,不做語法噪音):
  compare   比較運算子翻轉      ==↔!=  <↔>=  >↔<=  in↔not in  is↔is not
  boolconst 布林常數翻轉        True↔False
  boolop    and↔or
  num       數值常數 ±1        (退出碼、門檻、索引)
  not       移除 not
  return    `return X` → `return None`(整段判斷被短路的極端情形)

**基線護欄**:變異前先把「未變異但同樣經 ast.unparse 重寫」的版本跑一次測試。
若基線就紅,代表 unparse 本身破壞了程式——此時所有「殺死」都是假的,引擎會直接中止。
沒有這道護欄,kill rate 會虛高到 100%,而那正是最危險的假綠。

用法:
  python3 mutation_harness.py --target <module.py> --test "<測試指令>" [--min-kill-rate 90]
                              [--max-mutants N] [--json]
退出碼:0 = 達標;1 = kill rate 未達門檻;2 = 參數/基線錯誤。
"""
from __future__ import annotations
import argparse
import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

CMP_FLIP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
            ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.In: ast.NotIn, ast.NotIn: ast.In,
            ast.Is: ast.IsNot, ast.IsNot: ast.Is}


class Collector(ast.NodeVisitor):
    """收集所有可變異的點,回 [(算子, 路徑索引, 說明)]。"""

    def __init__(self):
        self.points = []

    def visit(self, node):
        for kind, desc in self._mutations_of(node):
            self.points.append((node, kind, desc))
        super().visit(node)

    @staticmethod
    def _mutations_of(node):
        out = []
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in CMP_FLIP:
                    out.append((f"compare:{i}",
                                f"{type(op).__name__} → {CMP_FLIP[type(op)].__name__}"))
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                out.append(("boolconst", f"{node.value} → {not node.value}"))
            elif isinstance(node.value, int):
                out.append(("num", f"{node.value} → {node.value + 1}"))
        elif isinstance(node, ast.BoolOp):
            out.append(("boolop", f"{type(node.op).__name__} → "
                                  f"{'Or' if isinstance(node.op, ast.And) else 'And'}"))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            out.append(("not", "移除 not"))
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                out.append(("return", "return X → return None"))
        return out


def apply_mutation(tree: ast.Module, index: int):
    """在 tree 的副本上套用第 index 個變異點;回 (新 tree, 說明, 行號)。"""
    clone = copy.deepcopy(tree)
    col = Collector()
    col.visit(clone)
    node, kind, desc = col.points[index]
    lineno = getattr(node, "lineno", 0)
    if kind.startswith("compare:"):
        i = int(kind.split(":")[1])
        node.ops[i] = CMP_FLIP[type(node.ops[i])]()
    elif kind == "boolconst":
        node.value = not node.value
    elif kind == "num":
        node.value = node.value + 1
    elif kind == "boolop":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif kind == "not":
        # 以 operand 取代整個 UnaryOp:改父節點做不到,故就地換成 operand 的內容
        node.__class__ = node.operand.__class__
        node.__dict__ = dict(node.operand.__dict__)
    elif kind == "return":
        node.value = ast.Constant(value=None)
    ast.fix_missing_locations(clone)
    return clone, f"{kind} @L{lineno}: {desc}", lineno


def run_test(cmd: str, cwd: Path) -> bool:
    """回 True = 測試通過(綠)。"""
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="要變異的模組檔")
    ap.add_argument("--test", required=True, help="判定生死的測試指令")
    ap.add_argument("--cwd", default=".", help="測試指令的工作目錄")
    ap.add_argument("--min-kill-rate", type=float, default=90.0)
    ap.add_argument("--max-mutants", type=int, default=0, help="0 = 不設限")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])

    target = Path(args.target).resolve()
    cwd = Path(args.cwd).resolve()
    if not target.is_file():
        print(f"找不到 target:{target}")
        return 2

    # 就地覆寫護欄(CHG-20260803-02,實地踩到才補的)。
    # 變異期間 target 的內容**不是原始碼**,而是變異體。若此時有人(或另一個 session)
    # 對 repo 下 `git add -A && git commit`,被永久收進版控的就是那個變異體——
    # 實測發生過一次:`doc_integrity_check.py` 的註解被 ast.unparse 洗掉並進了 commit。
    # 標記檔讓並行的工具與人看得見「現在不要碰這個 repo」,結束時一定移除。
    marker = target.parent / ".mutation-in-progress"
    if marker.exists():
        print(f"❌ 偵測到 {marker.name}:同一目錄已有變異在進行中。")
        print("   併行變異會互相覆寫彼此的還原點 → 拒絕執行。")
        return 2
    marker.write_text(f"target={target.name}\npid={__import__('os').getpid()}\n"
                      f"警告:變異進行中,此目錄的檔案內容為變異體,請勿 commit。\n",
                      encoding="utf-8")

    original = target.read_text(encoding="utf-8")
    tree = ast.parse(original)
    col = Collector()
    col.visit(copy.deepcopy(tree))
    total_points = len(col.points)
    if total_points == 0:
        print(f"{target.name}:找不到可變異的點——算子清單對這個模組無效,視同未驗證")
        return 2

    try:
        # --- 基線護欄:先用「unparse 後但未變異」的版本跑一次 ---
        target.write_text(ast.unparse(tree), encoding="utf-8")
        if not run_test(args.test, cwd):
            print("❌ 基線失敗:未變異的 unparse 版本就跑不過測試。")
            print("   代表 ast.unparse 改變了程式行為(或測試依賴原始碼文字),")
            print("   此時所有『殺死』都是假的 → 中止,不產出 kill rate。")
            return 2

        # --- 取樣(若設上限)。丟掉的必須明講,不做無聲截斷 ---
        indices = list(range(total_points))
        dropped = 0
        if args.max_mutants and total_points > args.max_mutants:
            step = total_points / args.max_mutants
            indices = sorted({int(i * step) for i in range(args.max_mutants)})
            dropped = total_points - len(indices)

        killed, survived = 0, []
        for n, idx in enumerate(indices, 1):
            mutant, desc, lineno = apply_mutation(tree, idx)
            try:
                target.write_text(ast.unparse(mutant), encoding="utf-8")
            except (ValueError, AttributeError, TypeError) as e:
                survived.append(f"{desc}(無法產生變異體:{e})")
                continue
            alive = run_test(args.test, cwd)
            if alive:
                survived.append(desc)          # 測試仍綠 = 沒殺掉
            else:
                killed += 1
            if not args.json:
                mark = "存活" if alive else "殺死"
                print(f"  [{n}/{len(indices)}] {mark} {desc}"[:76].ljust(78), end="\r")
    finally:
        target.write_text(original, encoding="utf-8")   # 一定還原
        marker.unlink(missing_ok=True)

    run_n = len(indices)
    rate = (killed / run_n * 100) if run_n else 0.0
    result = {"target": str(target), "mutants_total": total_points,
              "mutants_run": run_n, "dropped_by_cap": dropped,
              "killed": killed, "survived": len(survived),
              "kill_rate": round(rate, 1), "min_kill_rate": args.min_kill_rate,
              "survivors": survived}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(" " * 78, end="\r")
        print(f"\n{target.name}:變異點 {total_points},實跑 {run_n}"
              + (f"(取樣上限丟棄 {dropped} 個)" if dropped else "")
              + f",殺死 {killed},存活 {len(survived)} → kill rate {rate:.1f}%")
        for s in survived:
            print(f"  [存活] {s}")
    return 0 if rate >= args.min_kill_rate else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
