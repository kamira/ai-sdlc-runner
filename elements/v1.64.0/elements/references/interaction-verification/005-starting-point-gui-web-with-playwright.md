## Starting point: gui-web with Playwright

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.goto("http://localhost:3000")
    page.get_by_role("button", name="Save").click()      # mouse
    page.get_by_label("Title").fill("hello")             # keyboard
    page.keyboard.press("Tab")                           # focus order
    page.screenshot(path="artifacts/home.png")           # ← the artefact
    b.close()
```

