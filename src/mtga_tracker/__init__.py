"""Tapps Tracker - Track cards played in Magic: The Gathering Arena."""

# The version is derived from the git tag (setuptools-scm), never hand-edited.
# A source checkout reads it live from git at startup (source_version.py), so
# the dev version follows every commit without a reinstall. Otherwise it comes
# from _version.py, generated at install/build time and gitignored, then the
# package metadata. The last resort only appears when running from a raw source
# tree without git that was never `pip install -e`'d.
from .source_version import source_checkout_version

__version__ = source_checkout_version()
if __version__ is None:
    try:
        from ._version import __version__
    except ImportError:  # pragma: no cover - depends on install state
        try:
            from importlib.metadata import version as _dist_version

            __version__ = _dist_version("mtga-tracker")
        except Exception:  # noqa: BLE001 - any failure means "unknown", never a crash
            __version__ = "0.0.0+unknown"
