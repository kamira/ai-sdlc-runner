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

