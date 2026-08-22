---
name: interaction-verification
description: >
  The fifth gate: reusable AI-generated artefacts must have re-runnable verification of their
  usage surface — mouse clicks for a UI, argument and stdin handling for a CLI, error paths for
  a library API. Read this when declaring `### Interaction spec` in a CHG or wiring the gate.
---

# interaction-verification — the usage surface must be used, once, for real

> Language: **English** · [繁體中文](interaction-verification.zh-tw.md)

## Why this gate exists

A one-off script that is wrong gets rewritten; the cost stops there. A **reused** artefact is
different: every reuse amplifies the same unverified assumption. And the failures tend not to be
in the logic — they are on the **usage surface**: the button that does nothing, the tab order
that skips a field, the CLI that returns 0 with a required argument missing, the library that
raises an undocumented exception on bad input.

Unit tests do not reach there, and an agent writing its own tests reaches there least of all: it
covers the call paths it thought of, and usage-surface bugs are precisely the ones where *the
user does this, and the author never considered it*.

## What the runner actually checks

Three things, and it installs nothing:

1. The declared **kind** exists in `assets/interaction_kinds.json` (a table you can extend).
2. The declared **command** runs and exits zero.
3. The declared **artefacts really appeared** — and are non-empty.

The third one carries the weight. Without it `--interaction-cmd 'echo ok'` passes, which is
exactly what this gate is for. Exit zero is a claim; an artefact is evidence.

## Declaring it

```markdown
### Interaction spec
- kind: gui-web
- cmd: python tools/ui_check.py
- artifacts: artifacts/home.png, artifacts/trace.zip
```

Multiple entries are allowed — declare one per surface. An exemption must carry a reason:
`Interaction-spec: n/a (one-off migration script, not reused)`. **An empty exemption is treated
as no declaration at all** — it would otherwise look like an answer while being none.

## No default driver, on purpose

The runner never picks a driver for you. Declaring nothing halts and prints every kind in the
table. A silent default would decide something you never thought about — and for the kind of
project where this gate matters, that decision belongs to you.

`references/` ships two starting points below; neither is required.

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

## Starting point: cli

```python
import subprocess, pathlib
log = []
for args, want in ((["--help"], 0), ([], 2), (["--bad-flag"], 2)):
    r = subprocess.run(["mytool", *args], capture_output=True, text=True)
    log.append(f"{args} -> {r.returncode} (want {want})")
    assert r.returncode == want, log[-1]
pathlib.Path("artifacts/session.log").write_text("
".join(log))   # ← the artefact
```

## The trust boundary: where the command came from

The gate executes a shell command. There are two possible origins, and they are not equally
trustworthy:

- **the operator** — `--interaction-cmd`, typed on the command line
- **repo content** — the `cmd:` line inside a CHG file

The second one is *content-driven execution*: anyone who can land a CHG in the repo — a pull
request from a fork, say — can make autopilot run arbitrary shell, and the gate would pass it as
long as the declared artefact appears.

So content-declared commands **are not executed by default**. Supply `--interaction-cmd` yourself,
or vouch for the file with `--trust-chg-commands`. Either way the command is printed before it
runs, and its origin is recorded in the message that goes into the ACC — a command you vouched
for is weaker evidence than one you wrote.

## When it cannot run

Headless CI, no GUI, no browser — the limit is real. The disposition follows the existing risk
grade: **low** records "not covered" and proceeds (written to the handshake and the ACC);
**medium and high** halt. Being reusable is itself a reason the error would be amplified, so the
bar is not lowered for it.
