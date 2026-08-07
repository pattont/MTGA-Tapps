"""PyInstaller entrypoint for the bundled Deck Downloader console tool."""

from mtga_deck_downloader.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
