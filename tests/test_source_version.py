"""Source runs read their version live from git (source_version.py)."""

import subprocess
import sys
from datetime import datetime, timezone

import pytest

from mtga_tracker import __version__, source_version
from mtga_tracker.source_version import format_describe, source_checkout_version

DAY = datetime(2026, 10, 28, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "describe, expected",
    [
        ("v0.7.1-0-g7ee655fc4", "0.7.1"),
        ("v0.7.1-9-g7ee655fc4", "0.7.2.dev9+g7ee655fc4"),
        ("v0.7.1-9-g7ee655fc4-dirty", "0.7.2.dev9+g7ee655fc4.d20261028"),
        ("v0.7.1-0-g7ee655fc4-dirty", "0.7.2.dev0+g7ee655fc4.d20261028"),
        ("v0.5.9.1-3-gabc123def", "0.5.9.2.dev3+gabc123def"),
        ("v0.7.0-rc.4-0-gabc123def", "0.7.0rc4"),
        ("v0.7.0-rc.4-2-gabc123def", "0.7.0rc5.dev2+gabc123def"),
        ("vnext-2-gabc123def", None),
        ("not a describe", None),
    ],
)
def test_describe_formats_like_setuptools_scm(describe, expected):
    assert format_describe(describe + "\n", today=DAY) == expected


def test_a_checkout_without_git_falls_back(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("")

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert source_checkout_version(tmp_path) is None


def test_not_a_checkout_or_a_frozen_build_skips_git(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("git must not run")

    monkeypatch.setattr(subprocess, "run", unexpected)
    assert source_checkout_version(tmp_path) is None
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert source_checkout_version(tmp_path) is None


def test_this_checkout_reports_its_git_version():
    if not (source_version._CHECKOUT_ROOT / ".git").exists():
        pytest.skip("not running from a git checkout")
    live = source_checkout_version()
    if live is None:
        pytest.skip("git is unavailable")
    assert __version__ == live
