---
name: interaction-verification
description: >
  第五道閘:會被重複使用的 AI 產出,其使用面必須有可重跑的驗證——UI 的滑鼠點擊、
  CLI 的參數與 stdin、函式庫 API 的錯誤路徑。在 CHG 宣告 `### Interaction spec`
  或接線這道閘時讀本檔。
---

# interaction-verification — 使用面必須被真的用過一次

> 語言 / Language: **繁體中文** · [English](interaction-verification.md)

## 這道閘為什麼存在

一次性腳本錯了就重寫,成本到此為止。**會被重複使用**的產物不一樣:每一次複用都在放大
同一個未被驗證的假設。而且失效往往不在邏輯,而在**使用面**——按了沒反應的按鈕、
會跳過某個欄位的 Tab 順序、缺必填參數卻回 0 的 CLI、對壞輸入丟出未文件化例外的函式庫。

單元測試照不到那裡,而**自己寫測試的 agent 最照不到**:它覆蓋的是它想得到的呼叫路徑,
而使用面的錯恰恰是「使用者會這樣用,寫的人從沒想過」。

## runner 實際檢查什麼

三件事,而且它不安裝任何東西:

1. 宣告的**種類**存在於 `assets/interaction_kinds.json`(這張表你可以增補)。
2. 宣告的**指令**跑得過且回 0。
3. 宣告的**產物真的出現**,而且不是空檔。

第三條承擔了全部的重量。少了它,`--interaction-cmd 'echo ok'` 就能過關,而那正是這道閘
要防的東西。退出碼 0 是一種**聲稱**;產物才是**證據**。

## 怎麼宣告

```markdown
### Interaction spec
- kind: gui-web
- cmd: python tools/ui_check.py
- artifacts: artifacts/home.png, artifacts/trace.zip
```

可以宣告多筆,一個使用面一筆。豁免必須帶理由:
`Interaction-spec: n/a(一次性遷移腳本,不會被複用)`。
**空豁免視同完全沒宣告**——否則它會看起來像個交代,實際上什麼都沒說。

## 刻意沒有預設驅動

runner 永遠不替你挑驅動。什麼都沒宣告就停下來,並印出表裡所有種類。
靜默的預設會替你決定一件你從未想過的事;而在這道閘派得上用場的專案裡,那個決定該是你的。

下面兩份是起點,都不是強制。

## 起點:gui-web(Playwright)

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.goto("http://localhost:3000")
    page.get_by_role("button", name="儲存").click()       # 滑鼠
    page.get_by_label("標題").fill("hello")               # 鍵盤
    page.keyboard.press("Tab")                            # 焦點順序
    page.screenshot(path="artifacts/home.png")            # ← 產物
    b.close()
```

## 起點:cli

```python
import subprocess, pathlib
log = []
for args, want in ((["--help"], 0), ([], 2), (["--bad-flag"], 2)):
    r = subprocess.run(["mytool", *args], capture_output=True, text=True)
    log.append(f"{args} -> {r.returncode}(期望 {want})")
    assert r.returncode == want, log[-1]
pathlib.Path("artifacts/session.log").write_text("
".join(log))   # ← 產物
```

## 信任邊界:指令是誰給的

這道閘會以 shell 執行指令。指令有兩種來源,而它們的可信度不同:

- **操作者**——`--interaction-cmd`,你自己在命令列打的
- **repo 內容**——CHG 檔案裡的 `cmd:` 那一行

後者是**內容驅動執行**:任何能讓一份 CHG 進到 repo 的人——比如來自 fork 的 PR——
就能讓 autopilot 執行任意 shell,而只要宣告的產物出現,這道閘就會判它通過。

所以內容宣告的指令**預設不執行**。要嘛你自己用 `--interaction-cmd` 提供,
要嘛用 `--trust-chg-commands` 為那份檔案背書。無論哪一種,指令都會在執行前被印出來,
而來源會記進進 ACC 的訊息裡——你**背書**的指令,證據強度低於你**自己寫**的。

## 跑不起來的時候

無頭 CI、沒有 GUI、沒有瀏覽器——限制是真的。處置沿用既有的風險分級:
**低風險**記為「未涵蓋」並放行(寫進 handshake 與 ACC);**中/高風險停下**。
「會被重複使用」本身就是錯誤會被放大的理由,所以標準不會為它降低。
