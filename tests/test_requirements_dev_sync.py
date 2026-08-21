"""`requirements-dev.txt` must stay derived from `pyproject.toml`, and stay probe-readable.

Why this file exists at all (CHG-20260822-01): the ai-sdlc entry handshake runs
``toolchain_probe.sh``, which reads dev dependencies from ``requirements-dev.txt`` and nothing
else. This repo declares them in ``pyproject.toml``'s ``[project.optional-dependencies]``, so the
probe returned ``NOT_RUN`` (exit 4) on every single session -- *the check did not run*, which the
handshake protocol treats as stop-and-provision. ``requirements-dev.txt`` is the probe-facing view
of those extras; these tests are what keep it a *view* rather than a second, independently rotting
list of dependencies.

Two distinct properties are asserted, and they fail for different reasons:

1. **Sync** -- the distribution names match the extras. Guards the ordinary drift: someone adds a
   dev dependency to ``pyproject.toml`` and the probe keeps reporting PASS against a stale list.
2. **Probe-readability** -- every line is a bare distribution name. This one is easy to lose and
   expensive to lose silently. The probe classifies ``-e .[extras]``, ``PyYAML>=6.0`` and friends as
   *unparsable* and returns ``NOT_RUN``, so a well-meaning edit that "adds the version floors back"
   would return the gate to exactly the broken state this CHG fixed -- while the file looked more
   correct, not less. Measured behaviour, tabulated in CHG-20260822-01.

Stdlib only, and deliberately no ``tomllib``: CI's floor cell is py3.9 and ``tomllib`` landed in
3.11, so importing it would make this guard vanish from half the matrix.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"

# The probe's own unparsable-line patterns, mirrored: options/URLs/VCS/extras/env-markers/
# line-continuations, plus any PEP 440 version specifier. See toolchain_probe.sh.
_NOT_A_BARE_NAME = re.compile(r"[<>=!~;\[\]@\\]|://|^-")


def _normalize(dist_name):
    """PEP 503 normalization, so `PyYAML` and `pyyaml` are the same dependency, not drift."""
    return re.sub(r"[-_.]+", "-", dist_name).lower()


def _strip_specifier(requirement):
    """`PyYAML>=6.0` -> `PyYAML`. Also drops extras and environment markers if ever present."""
    return re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip()


def _pyproject_extra_dists():
    """Distribution names from every extra in `[project.optional-dependencies]`.

    Every extra, not a hardcoded subset: a hardcoded `{"yaml", "test"}` would go stale the moment a
    new extra is added, which is the same class of defect this test exists to prevent.
    """
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("[project.optional-dependencies]") + 1
    except ValueError:  # pragma: no cover - fails loudly via the assert in the test
        return None

    dists = set()
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("["):  # next TOML section: the block is over
            break
        if not stripped or stripped.startswith("#"):
            continue
        _, _, value = stripped.partition("=")
        for requirement in re.findall(r'"([^"]+)"', value):
            dists.add(_normalize(_strip_specifier(requirement)))
    return dists


def _requirements_dev_lines():
    """Non-empty, non-comment lines of `requirements-dev.txt`, verbatim (not normalized)."""
    return [
        line.strip()
        for line in REQUIREMENTS_DEV.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_requirements_dev_exists():
    """Absent file == probe returns NOT_RUN on every handshake. That is the bug, so assert it first."""
    assert REQUIREMENTS_DEV.is_file(), (
        f"{REQUIREMENTS_DEV.name} is missing; toolchain_probe.sh will return NOT_RUN (exit 4) "
        "for every entry handshake on this repo. See CHG-20260822-01."
    )


def test_requirements_dev_matches_pyproject_extras():
    """The two dependency lists must name the same distributions."""
    expected = _pyproject_extra_dists()
    assert expected is not None, (
        "`[project.optional-dependencies]` not found in pyproject.toml -- this guard cannot "
        "silently pass just because it lost track of where the dependencies are declared."
    )
    assert expected, "`[project.optional-dependencies]` parsed as empty; the scan is broken."

    actual = {_normalize(line) for line in _requirements_dev_lines()}
    assert actual == expected, (
        "requirements-dev.txt has drifted from pyproject.toml's optional-dependencies.\n"
        f"  only in pyproject.toml:      {sorted(expected - actual)}\n"
        f"  only in requirements-dev.txt: {sorted(actual - expected)}\n"
        "requirements-dev.txt is a derived view; update it (names only, no version ranges)."
    )


@pytest.mark.parametrize("line", _requirements_dev_lines() if REQUIREMENTS_DEV.is_file() else [])
def test_requirements_dev_lines_are_bare_names(line):
    """Every line must be a bare distribution name, or the probe silently reverts to NOT_RUN.

    Version constraints stay in pyproject.toml, which is the authority for them and is what pip
    actually enforces at install time. The probe answers a narrower question -- *are the dev
    dependencies installed* -- and answering it requires giving it only what it can parse.
    """
    assert not _NOT_A_BARE_NAME.search(line), (
        f"{line!r} is not a bare distribution name. toolchain_probe.sh treats version specifiers, "
        "`-e`/`-r` options, URLs, extras and environment markers as UNPARSABLE and returns NOT_RUN "
        "-- i.e. this line would silently disable the toolchain gate. Keep version constraints in "
        "pyproject.toml. See CHG-20260822-01."
    )
