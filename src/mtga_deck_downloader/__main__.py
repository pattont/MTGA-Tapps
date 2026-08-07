from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
import sys

from mtga_deck_downloader.config import load_config, resolve_config_path
from mtga_deck_downloader.providers.registry import LAST_PROVIDER_ERRORS, load_providers
from mtga_deck_downloader.ui import run_app


PACKAGE_NAME = "mtga-deck-downloader"


def app_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return "0.1.0+source"


def run_diagnostics() -> int:
    config_path = resolve_config_path()
    config = load_config(config_path)
    providers = load_providers()
    provider_names = ", ".join(provider.display_name for provider in providers)

    print(f"MTGA Deck Downloader {app_version()}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Executable: {Path(sys.executable).resolve()}")
    print(f"Frozen: {'yes' if getattr(sys, 'frozen', False) else 'no'}")
    print(f"Config: {config_path}")
    print(f"Moxfield creators: {len(config.moxfield_creators)}")
    print(f"Aetherhub creators: {len(config.aetherhub_creators)}")
    print(f"TCGPlayer creators: {len(config.tcgplayer_creators)}")
    print(f"Providers ({len(providers)}): {provider_names or 'none'}")

    if LAST_PROVIDER_ERRORS:
        print("Provider errors:")
        for error in LAST_PROVIDER_ERRORS:
            print(f"- {error}")
        return 1
    if not providers:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mtga-deck-downloader")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {app_version()}",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="check packaged resources and provider discovery without network access",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.diagnose:
        return run_diagnostics()
    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
