"""Live version for source runs, read from git at startup.

``_version.py`` is written only when the package is (re)installed, so an
editable install keeps reporting the version from its last ``pip install -e``.
A source checkout asks ``git describe`` instead and formats the answer like
setuptools-scm's default scheme: a clean tag is the release itself
(``0.7.1``); anything after it is a dev build of the next patch
(``0.7.2.dev9+g7ee655fc4``), with ``.dYYYYMMDD`` added while there are
uncommitted changes. Frozen builds and installs outside a checkout return
None and keep the version baked in at build time.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

#: The repository root when this package runs from its checkout (src/mtga_tracker/..).
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]

_DESCRIBE = re.compile(r"^v?(?P<tag>.+)-(?P<distance>\d+)-g(?P<sha>[0-9a-f]+)(?P<dirty>-dirty)?$")
_RELEASE = re.compile(r"^\d+(\.\d+)*$")
#: A pre-release tag such as ``0.7.0-rc.4`` / ``0.7.0rc4``.
_PRERELEASE = re.compile(
    r"^(?P<base>\d+(?:\.\d+)*)[-.]?(?P<kind>a|b|rc|alpha|beta)[-.]?(?P<n>\d+)$"
)
_PRE_KIND = {"alpha": "a", "beta": "b"}


def _next_version(tag: str) -> Optional[str]:
    """The release a dev build after ``tag`` leads to (setuptools-scm guess-next-dev)."""
    if _RELEASE.match(tag):
        parts = tag.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    match = _PRERELEASE.match(tag)
    if match:
        kind = _PRE_KIND.get(match["kind"], match["kind"])
        return f"{match['base']}{kind}{int(match['n']) + 1}"
    return None


def format_describe(describe: str, today: Optional[datetime] = None) -> Optional[str]:
    """PEP 440 version for ``git describe --tags --long --dirty`` output, or None."""
    match = _DESCRIBE.match(describe.strip())
    if not match:
        return None
    tag, distance, dirty = match["tag"], int(match["distance"]), bool(match["dirty"])
    if distance == 0 and not dirty:
        if _RELEASE.match(tag):
            return tag
        pre = _PRERELEASE.match(tag)
        if pre:
            return f"{pre['base']}{_PRE_KIND.get(pre['kind'], pre['kind'])}{int(pre['n'])}"
        return None
    base = _next_version(tag)
    if base is None:
        return None
    local = f"g{match['sha']}"
    if dirty:
        local += (today or datetime.now(timezone.utc)).strftime(".d%Y%m%d")
    return f"{base}.dev{distance}+{local}"


def source_checkout_version(root: Path = _CHECKOUT_ROOT) -> Optional[str]:
    """The checkout's version from git, or None (frozen build, no checkout, no git)."""
    if getattr(sys, "frozen", False):
        return None
    if not ((root / ".git").exists() and (root / "pyproject.toml").is_file()):
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--long", "--dirty", "--abbrev=9", "--match", "v[0-9]*"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return format_describe(result.stdout)
