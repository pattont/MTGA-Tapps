"""PyInstaller entry point for the MTGA Tracker menu-bar application."""

import os
import sys

# Windowed (console=False) builds on Windows run with no console attached, so
# sys.stdout / sys.stderr are None and the first print() or .write() raises
# AttributeError: 'NoneType' object has no attribute 'write'. Give the
# interpreter safe sinks before anything imports or prints; the GUI's live-log
# redirection takes over the streams it cares about once it starts.
for _stream_name in ("stdout", "stderr"):
    if getattr(sys, _stream_name) is None:
        setattr(sys, _stream_name, open(os.devnull, "w", encoding="utf-8"))

from mtga_tracker.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
