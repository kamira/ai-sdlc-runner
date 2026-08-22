## Runner 指令與 exit codes

```
plan-check --chg <CHG.md>                      # 只驗計畫格式(操作測試提示為非阻斷)
run  --chg <CHG.md> --repo . [--agent-cmd T] [--test-cmd C] [--verify-cmd V] [--dry-run] [--no-commit] [--max-tasks N]
status --chg <CHG.md>                          # 已勾/未勾、下一個 task、當前階段
```

`--test-cmd` 跑每個 task 的單元/build 測試;`--verify-cmd` 跑末端操作測試(把變更真的操作一次)。Exit codes:`0` 完成 · `1` 非預期錯誤 · `2` 計畫無效 · `3` 合法停點(印出原因)。cron/CI 接 3(帶原因通知人)與 0(接下一筆 CHG)。`--dry-run` 模擬施工/測試/審查**與操作驗收**成功,不需 agent 即可演練狀態機與停點策略。

