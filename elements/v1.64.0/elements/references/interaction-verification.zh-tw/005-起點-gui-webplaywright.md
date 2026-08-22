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

