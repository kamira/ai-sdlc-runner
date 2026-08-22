# 第三方聲明 — ai-sdlc-autopilot

本 skill 的執行方法論改寫自 Jesse Vincent(obra)的 **Superpowers**
——<https://github.com/obra/superpowers>——MIT License。改寫的概念(未複製任何原始碼):
計畫的全域約束/逐 task 介面塊;單 reviewer 雙判定(規格+品質)含合法的「diff 看不出
(cannot-verify)」判定;末端整支 review;TDD 與系統化除錯紀律。所有改寫內容均重寫為
落入 ai-sdlc 帳本的平台中立契約。

## MIT License(Superpowers;依授權要求保留英文原文)

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Matt Pocock 的 agent skills(需求訪談 + 使用者故事)

本 skill 有兩處契約改編自 Matt Pocock 的 **mattpocock/skills**
——<https://github.com/mattpocock/skills>——依 MIT License。改編概念(未複製原始碼):

- **CHG 模板的使用者故事段**——改編自 `to-spec` skill 的 spec 模板(Problem / Solution /
  User Stories / Implementation Decisions),特別是「作為&lt;角色&gt;,我要&lt;功能&gt;,以便&lt;效益&gt;」
  的格式,以及「清單須涵蓋各面向、而非只寫快樂路徑」的要求。
- **`requirement-analysis` 的提問紀律**——改編自 `grilling` / `grill-me` skill:走決策樹一次一題、
  每題附上建議答案、能由環境查得的事實自己查而不問使用者、以「使用者確認共識」為停止條件。

**與原作的差異。** 上游 `to-spec` 把 spec 發佈到 issue tracker;本 suite 讓故事**留在 CHG 內**
——本 suite 禁止平行帳本,故一份產物同時承載計畫、決策與故事,且故事成為 ACC 驗收條件的第一
順位來源。上游 `grill-with-docs` 另寫 ADR 檔;本 suite 的 CHG「決策與取捨」表已擔此職,故不建
ADR 目錄。上游 skill 為使用者手動呼叫的 slash 指令;本 suite 把同一紀律寫進治理層本來就會跑的
分階段流程。

## MIT License(mattpocock/skills)

Copyright (c) Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 附註

`ai-sdlc-autopilot` skill 有自己的第三方聲明(Superpowers, MIT),位於
`skills/ai-sdlc-autopilot/THIRD-PARTY-NOTICES.md`;suite plugin 則有 i-have-adhd 的聲明,位於
`plugins/ai-sdlc-suite/THIRD-PARTY-NOTICES.md`。
