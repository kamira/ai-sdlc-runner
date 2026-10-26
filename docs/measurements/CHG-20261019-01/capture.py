#!/usr/bin/env python3
"""Numbered captures for the CHG-20261019-01 measurement report. (CHG-20261019-01, item 5)

Every command run and every setting the measurement depends on is kept twice: as plain text, and as
an image of exactly that text, so the image can be checked against the text. Each step also appends
one line to `steps/steps.jsonl`, which the report is written from.

    capture.py cmd  --step N --slug S --why TEXT -- CMD...      (or --shell "string")
    capture.py file --step N --slug S --why TEXT PATH
    capture.py page --step N --slug S --why TEXT URL [--wait-for SEL] [--header NAME:VALUE]
    capture.py watch --base-url URL --token-file PATH --every 60 --out-prefix N
    capture.py check

**Nothing secret is written.** Before any `.txt` or `.png` exists the text is redacted: the value of
every environment variable named like KEY / TOKEN / SECRET / PASSWORD / AUTH / CREDENTIAL (8
characters or more) and anything shaped like a CWA key, an `Authorization=` parameter, a bearer
token or an `sk-` key. A page is screenshotted only after password inputs are blanked and every
element showing a secret is hidden; if its visible text still holds one, the capture is refused
(exit 3) and nothing is written. `steps.jsonl` says *whether* anything was redacted, never what.
`check` scans every file under the measurement directory for the same things and fails on a hit.

Exit codes: 0 done (a captured command's own exit code is recorded, not returned); 1 `check` found
a secret; 2 bad arguments, or Playwright/Chromium unavailable; 3 a page capture refused because it
would show a secret.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

HERE = Path(__file__).resolve().parent

SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|AUTH|CREDENTIAL", re.IGNORECASE)
MIN_SECRET = 8
PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("cwa-key", re.compile(r"CWA-[0-9A-Fa-f-]{20,}")),
    ("Authorization", re.compile(r"Authorization=[^&\s]+")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("sk-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
]
REFUSED = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- redaction ---------------------------------------------------------------------------------
def env_secrets(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """name -> value for every environment variable that looks like a secret and is long enough."""
    env = os.environ if env is None else env
    return {n: v for n, v in env.items() if SECRET_NAME.search(n) and len(v) >= MIN_SECRET}


def redact(text: str, env: Optional[Dict[str, str]] = None) -> Tuple[str, bool]:
    """(text with secrets replaced, whether anything was). Longest env values first, so a value
    that contains another is not left half-shown."""
    changed = False
    for name, value in sorted(env_secrets(env).items(), key=lambda kv: -len(kv[1])):
        if value in text:
            text = text.replace(value, "[redacted:%s]" % name)
            changed = True
    for name, pat in PATTERNS:
        text, n = pat.subn("[redacted:%s]" % name, text)
        changed = changed or n > 0
    return text, changed


def secret_literals(text: str, env: Optional[Dict[str, str]] = None,
                    extra: Sequence[str] = ()) -> List[str]:
    """Every secret string that appears in `text`: env values, `extra`, and pattern matches."""
    found = [v for v in list(env_secrets(env).values()) + [e for e in extra if e] if v in text]
    for _name, pat in PATTERNS:
        found.extend(m.group(0) for m in pat.finditer(text))
    return sorted(set(found), key=lambda s: -len(s))


def strip_url(url: str) -> str:
    """The URL without its query string or fragment: either can carry a key or the console token."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


# -- files -------------------------------------------------------------------------------------
class Out:
    def __init__(self, root: Path):
        self.root = root
        self.steps = root / "steps"

    def name(self, step: int, slug: str, ext: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
            raise SystemExit("capture: --slug may hold letters, digits, '.', '_' and '-' only")
        return self.steps / ("%02d-%s.%s" % (step, slug, ext))

    def write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def record(self, entry: dict) -> None:
        self.steps.mkdir(parents=True, exist_ok=True)
        with open(self.steps / "steps.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


# -- Chromium ----------------------------------------------------------------------------------
class NoBrowser(Exception):
    pass


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = _launch(p)
            b.close()
        return True
    except Exception:
        return False


def _installed_chrome() -> Optional[str]:
    """A Chromium already on disk under PLAYWRIGHT_BROWSERS_PATH, for when the installed Playwright
    expects a newer build than the one pre-installed. Nothing is downloaded."""
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "/opt/pw-browsers")
    found = sorted(root.glob("chromium-*/chrome-linux*/chrome")) if root.is_dir() else []
    return str(found[-1]) if found else None


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception as first:  # Playwright raises its own Error
        exe = _installed_chrome()
        if exe:
            try:
                return p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
            except Exception:
                pass
        raise NoBrowser("Chromium would not start (%s). PLAYWRIGHT_BROWSERS_PATH=%s"
                        % (str(first).splitlines()[0] if str(first) else type(first).__name__,
                           os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "unset")))


TERMINAL_CSS = ("body{margin:0;background:#0d1117}"
                "pre{margin:0;padding:18px 22px;color:#d6dde6;background:#0d1117;"
                "font:13px/1.45 'DejaVu Sans Mono','Liberation Mono',Menlo,monospace;"
                "white-space:pre-wrap;word-break:break-all;width:1100px;box-sizing:border-box}")


def render_text(text: str, png: Path) -> None:
    """A full-page screenshot of `text` in a dark monospace block. Not truncated."""
    from playwright.sync_api import sync_playwright
    page_html = ("<!doctype html><meta charset=utf-8><style>%s</style><pre>%s</pre>"
                 % (TERMINAL_CSS, html.escape(text)))
    png.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            b = _launch(p)
            try:
                pg = b.new_page(viewport={"width": 1100, "height": 200})
                pg.set_content(page_html)
                pg.screenshot(path=str(png), full_page=True)
            finally:
                b.close()
    except NoBrowser:
        raise
    except ImportError as e:
        raise NoBrowser("Playwright is not installed: %s" % e)


# -- the steps ---------------------------------------------------------------------------------
class LiveRedactor:
    """Redacts streamed output without letting a secret split across two reads through: text is
    emitted only up to the last newline, redacted whole. A line with no newline for longer than
    any secret or pattern match is expected to run is emitted too, but for a held-back tail."""
    HOLD = 512

    def __init__(self):
        self.pending = ""

    def feed(self, piece: str) -> str:
        self.pending += piece
        cut = self.pending.rfind("\n") + 1
        if not cut:
            hold = max([self.HOLD] + [len(v) for v in env_secrets().values()])
            cut = len(self.pending) - hold if len(self.pending) > 2 * hold else 0
        out, self.pending = self.pending[:cut], self.pending[cut:]
        return redact(out)[0]

    def flush(self) -> str:
        out, self.pending = self.pending, ""
        return redact(out)[0]


def _entry(step, slug, kind, why, what: dict, start, end, code, files, redacted) -> dict:
    e = {"step": step, "slug": slug, "kind": kind, "why": redact(why)[0],
         "started_utc": start, "ended_utc": end, "exit_code": code,
         "files": files, "redacted": bool(redacted)}
    e.update(what)
    return e


def _text_and_image(out: Out, step: int, slug: str, text: str, image: bool) -> Tuple[List[str], bool]:
    text, changed = redact(text)
    txt, png = out.name(step, slug, "txt"), out.name(step, slug, "png")
    out.write_text(txt, text)
    files = [out.rel(txt)]
    if image:
        render_text(text, png)
        files.append(out.rel(png))
    return files, changed


def run_cmd(out: Out, step: int, slug: str, why: str, argv: Optional[Sequence[str]] = None,
            shell: Optional[str] = None, image: bool = True, echo: bool = True) -> dict:
    """Run a command, interleaving stdout and stderr as they came; write the step."""
    shown = shell if shell is not None else " ".join(_quote(a) for a in argv or [])
    start = utc_now()
    chunks: List[str] = []
    try:
        proc = subprocess.Popen(shell if shell is not None else list(argv or []),
                                shell=shell is not None, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, bufsize=0)
    except OSError as e:
        chunks.append("capture: could not start the command: %s\n" % e)
        code = 127
    else:
        assert proc.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        live = LiveRedactor()
        while True:
            data = _read_chunk(proc.stdout.fileno())
            piece = decoder.decode(data, final=not data)
            chunks.append(piece)
            if echo:
                sys.stdout.write(live.feed(piece) if data else live.flush())
                sys.stdout.flush()
            if not data:
                break
        code = proc.wait()
    end = utc_now()
    body = "".join(chunks)
    text = "$ %s\n# started %s\n# ended   %s\n# exit    %d\n\n%s" % (shown, start, end, code, body)
    if body and not body.endswith("\n"):
        text += "\n"
    files, changed = _text_and_image(out, step, slug, text, image)
    entry = _entry(step, slug, "cmd", why, {"command": redact(shown)[0]}, start, end, code,
                   files, changed)
    out.record(entry)
    return entry


def _read_chunk(fd: int) -> bytes:
    return os.read(fd, 65536)


def _quote(a: str) -> str:
    return a if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", a) else "'" + a.replace("'", "'\\''") + "'"


def run_file(out: Out, step: int, slug: str, why: str, path: str, image: bool = True) -> dict:
    start = utc_now()
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    text = "file   %s\nsha256 %s\ntime   %s\n\n%s" % (path, sha, start, raw.decode("utf-8", "replace"))
    if not text.endswith("\n"):
        text += "\n"
    files, changed = _text_and_image(out, step, slug, text, image)
    entry = _entry(step, slug, "file", why, {"path": path, "sha256": sha}, start, utc_now(), 0,
                   files, changed)
    out.record(entry)
    return entry


# What the fields hold: `innerText` leaves out an input's value, yet the screenshot shows it.
_FIELDS_JS = """
() => Array.from(document.querySelectorAll('input, textarea, select, [contenteditable]'))
  .filter(e => !(e.type === 'password'))
  .map(e => (e.isContentEditable && !('value' in e)) ? (e.textContent || '') : (e.value || ''))
"""

_HIDE_JS = """
(secrets) => {
  document.querySelectorAll('input[type=password]').forEach(i => { i.value = ''; });
  document.querySelectorAll('input, textarea, select').forEach(i => {
    if (secrets.some(s => (i.value || '').includes(s))) i.value = '';
  });
  document.querySelectorAll('[contenteditable]').forEach(e => {
    if (!('value' in e) && secrets.some(s => (e.textContent || '').includes(s))) e.textContent = '';
  });
  // Hide the innermost elements that show a secret, not the whole page above them.
  const all = Array.from(document.body.querySelectorAll('*'));
  const shows = e => secrets.some(s => (e.innerText || '').includes(s));
  all.forEach(e => {
    if (shows(e) && !Array.from(e.children).some(shows)) e.style.visibility = 'hidden';
  });
  return document.body.innerText;
}
"""


def capture_page(out: Out, step: int, slug: str, why: str, url: str, wait_for: Optional[str] = None,
                 headers: Sequence[str] = (), token: Optional[str] = None,
                 image: bool = True, name_suffix: str = "") -> dict:
    """Screenshot a page. `token` is the console's operator token: sent in the URL fragment (never
    to the server), and treated as a secret on the page. Raises Refused rather than write a capture
    whose visible text still holds a secret."""
    from playwright.sync_api import sync_playwright
    extra = [token] if token else []
    start = utc_now()
    target = url + ("#token=" + token if token else "")
    hdrs = {}
    for h in headers:
        k, _, v = h.partition(":")
        hdrs[k.strip()] = v.strip()
        if k.strip().lower() in ("authorization", "x-operator-token") and v.strip():
            extra.append(v.strip())
    base = slug + name_suffix
    png = out.name(step, base, "png")
    with sync_playwright() as p:
        b = _launch(p)
        try:
            ctx = b.new_context(viewport={"width": 1280, "height": 800}, extra_http_headers=hdrs)
            pg = ctx.new_page()
            pg.goto(target, wait_until="load")
            if wait_for:
                pg.wait_for_selector(wait_for, timeout=30000)
            pg.wait_for_timeout(400)
            fields = "\n".join(pg.evaluate(_FIELDS_JS))
            shown = secret_literals(pg.inner_text("body") + "\n" + fields, extra=extra)
            in_fields = bool(secret_literals(fields, extra=extra))
            secrets = shown + [s for s in (list(env_secrets().values()) + extra) if s not in shown]
            visible = pg.evaluate(_HIDE_JS, secrets)
            held = "\n".join(pg.evaluate(_FIELDS_JS))
            leaked = [s for s in secret_literals(visible + "\n" + held, extra=extra)]
            if leaked:
                raise Refused("the page still shows a secret value after hiding; nothing written")
            out.steps.mkdir(parents=True, exist_ok=True)
            if image:
                pg.screenshot(path=str(png), full_page=True)
        finally:
            b.close()
    end = utc_now()
    text = "url  %s\ntime %s\n\n%s\n" % (strip_url(url), end, visible)
    text, changed = redact(text)
    txt = out.name(step, base, "txt")
    out.write_text(txt, text)
    files = [out.rel(txt)] + ([out.rel(png)] if image else [])
    entry = _entry(step, slug, "page", why, {"url": strip_url(url)}, start, end, 0, files,
                   changed or bool(shown) or in_fields)
    out.record(entry)
    return entry


class Refused(Exception):
    pass


# -- watch -------------------------------------------------------------------------------------
class Watcher:
    """Captures the console when the node it shows changes, and at least every `every` seconds.
    Usable from a callback: `w.on_node(node)` captures immediately for that node."""

    def __init__(self, out: Out, base_url: str, token: str, every: float = 60.0,
                 prefix: int = 0, emit=print):
        self.out, self.base, self.token, self.every, self.prefix = out, base_url.rstrip("/"), \
            token, every, prefix
        self.node: Optional[str] = None
        self.last = 0.0
        self.seq = 0
        self.emit = emit

    def poll(self) -> Tuple[Optional[str], str]:
        req = urllib.request.Request(self.base + "/run", headers={"X-Operator-Token": self.token})
        with urllib.request.urlopen(req, timeout=10) as r:
            s = json.loads(r.read().decode("utf-8"))
        return s.get("at"), s.get("state", "")

    def capture(self, node: Optional[str]) -> dict:
        self.seq += 1
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", node or "none")
        slug = "console-%s-%s-%03d" % (safe, stamp, self.seq)
        entry = capture_page(self.out, self.prefix, slug,
                             "console at node %s, UTC %s" % (node or "(none)", utc_now()),
                             self.base + "/", wait_for="#state", token=self.token)
        entry["node"] = node
        self.last = time.monotonic()
        for f in entry["files"]:
            if f.endswith(".png"):
                self.emit("CAPTURED %s" % (self.out.root / f))
        return entry

    def on_node(self, node: str) -> dict:
        self.node = node
        return self.capture(node)

    def step(self) -> bool:
        """One poll. Returns False once the run has finished or stopped."""
        node, state = self.poll()
        if node != self.node or time.monotonic() - self.last >= self.every:
            self.node = node
            self.capture(node)
        return state not in ("finished", "stopped")


# -- check -------------------------------------------------------------------------------------
def check_tree(root: Path, env: Optional[Dict[str, str]] = None) -> List[str]:
    """Files under `root` holding a secret. Names the file and what kind, never the value."""
    bad: List[str] = []
    secrets = env_secrets(env)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        # capture.py itself holds the patterns as source text, which is not a secret.
        if path.resolve() == Path(__file__).resolve():
            continue
        raw = path.read_bytes()
        text = raw.decode("utf-8", "replace")
        hits = [("env:" + n) for n, v in secrets.items() if v.encode("utf-8") in raw]
        hits += [n for n, pat in PATTERNS if pat.search(text)]
        if hits:
            bad.append("%s: %s" % (path.relative_to(root).as_posix(), ", ".join(hits)))
    return bad


# -- command line ------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="capture.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(HERE), help="measurement directory (default: this one)")
    sub = ap.add_subparsers(dest="kind", required=True)

    def common(p):
        p.add_argument("--step", type=int, required=True)
        p.add_argument("--slug", required=True)
        p.add_argument("--why", required=True)
        p.add_argument("--no-image", action="store_true", help="write the .txt only")

    c = sub.add_parser("cmd")
    common(c)
    c.add_argument("--shell", metavar="STRING", help="run STRING through the shell")
    c.add_argument("argv", nargs="*", help="-- then the command, as argv")
    f = sub.add_parser("file")
    common(f)
    f.add_argument("path")
    g = sub.add_parser("page")
    common(g)
    g.add_argument("url")
    g.add_argument("--wait-for", metavar="SELECTOR")
    g.add_argument("--header", action="append", default=[], metavar="NAME:VALUE")
    g.add_argument("--token-file", help="the operator token, for the console")
    w = sub.add_parser("watch")
    w.add_argument("--base-url", required=True)
    w.add_argument("--token-file", required=True)
    w.add_argument("--every", type=float, default=60.0)
    w.add_argument("--out-prefix", type=int, required=True, help="the step number for the captures")
    sub.add_parser("check")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    out = Out(Path(args.root))
    try:
        if args.kind == "check":
            bad = check_tree(out.root)
            for line in bad:
                print("SECRET", line)
            print("check: %s" % ("FAILED, %d file(s)" % len(bad) if bad else "clean"))
            return 1 if bad else 0
        if args.kind == "cmd":
            if (args.shell is None) == (not args.argv):
                print("capture: give a command after `--`, or --shell STRING, not both",
                      file=sys.stderr)
                return 2
            e = run_cmd(out, args.step, args.slug, args.why, args.argv, args.shell,
                        image=not args.no_image)
        elif args.kind == "file":
            e = run_file(out, args.step, args.slug, args.why, args.path, image=not args.no_image)
        elif args.kind == "page":
            token = Path(args.token_file).read_text(encoding="utf-8").strip() \
                if args.token_file else None
            e = capture_page(out, args.step, args.slug, args.why, args.url, args.wait_for,
                             args.header, token, image=not args.no_image)
        else:
            token = Path(args.token_file).read_text(encoding="utf-8").strip()
            w = Watcher(out, args.base_url, token, args.every, args.out_prefix)
            try:
                while w.step():
                    time.sleep(2)
            except KeyboardInterrupt:
                pass
            return 0
    except NoBrowser as e:
        print("capture: %s" % e, file=sys.stderr)
        return 2
    except Refused as e:
        print("capture: refused: %s" % e, file=sys.stderr)
        return REFUSED
    for f in e["files"]:
        print("WROTE", out.root / f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
