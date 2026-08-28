"""MTGA Tracker - Track cards played in Magic: The Gathering Arena."""

# The version is derived from the git tag (setuptools-scm), never hand-edited.
# _version.py is generated at install/build time and gitignored; installed
# builds fall back to the package metadata. The last resort only appears when
# running from a raw source tree that was never `pip install -e`'d.
try:
    from ._version import __version__
except ImportError:  # pragma: no cover - depends on install state
    try:
        from importlib.metadata import version as _dist_version

        __version__ = _dist_version("mtga-tracker")
    except Exception:  # noqa: BLE001 - any failure means "unknown", never a crash
        __version__ = "0.0.0+unknown"
