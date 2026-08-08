from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import sys


DEFAULT_MOXFIELD_NAMES = (
    "Ashlizzlle",
    "Swayzemtg",
    "covertgoblue",
    "carlomtg",
)

DEFAULT_AETHERHUB_CREATORS = (
    "MTGMalone",
)

BUNDLED_CONFIG_PATH = Path(__file__).resolve().with_name("default_config.json")
PROJECT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "deckfinder_config.json"
CONFIG_ENV_VAR = "MTGA_DECK_DOWNLOADER_CONFIG"


def user_config_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "MTGA Deck Downloader"
            / "deckfinder_config.json"
        )
    if sys.platform.startswith("win"):
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
        return base / "MTGA Deck Downloader" / "deckfinder_config.json"
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "mtga-deck-downloader" / "deckfinder_config.json"


def resolve_config_path(explicit_path: str | Path | None = None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path).expanduser().resolve()

    configured_path = os.environ.get(CONFIG_ENV_VAR)
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    user_path = user_config_path()
    if user_path.exists():
        return user_path

    if not getattr(sys, "frozen", False) and PROJECT_CONFIG_PATH.exists():
        return PROJECT_CONFIG_PATH

    return BUNDLED_CONFIG_PATH


@dataclass(frozen=True)
class CreatorConfig:
    name: str
    short_name: str | None = None

    @property
    def label(self) -> str:
        short_name = self.short_name.strip() if self.short_name else ""
        return short_name or self.name


@dataclass(frozen=True)
class AppConfig:
    moxfield_creators: tuple[CreatorConfig, ...]
    aetherhub_creators: tuple[CreatorConfig, ...] = ()
    tcgplayer_creators: tuple[CreatorConfig, ...] = ()

    @property
    def moxfield_names(self) -> tuple[str, ...]:
        return tuple(creator.name for creator in self.moxfield_creators)


MoxfieldCreator = CreatorConfig


def load_config(config_path: str | Path | None = None) -> AppConfig:
    raw_moxfield_creators: list[CreatorConfig] = [
        CreatorConfig(name=name) for name in DEFAULT_MOXFIELD_NAMES
    ]
    raw_aetherhub_creators: list[CreatorConfig] = [
        CreatorConfig(name=name) for name in DEFAULT_AETHERHUB_CREATORS
    ]
    raw_tcgplayer_creators: list[CreatorConfig] = []

    resolved_path = resolve_config_path(config_path)
    if resolved_path.exists():
        try:
            payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            candidate_names = payload.get("MoxfieldNames")
            if isinstance(candidate_names, list):
                raw_moxfield_creators = [
                    creator
                    for item in candidate_names
                    if (creator := _parse_creator_config(item)) is not None
                ]

            candidate_aetherhub_creators = payload.get("AtherhubCreators")
            if isinstance(candidate_aetherhub_creators, list):
                raw_aetherhub_creators = [
                    creator
                    for item in candidate_aetherhub_creators
                    if (creator := _parse_creator_config(item)) is not None
                ]

            candidate_tcgplayer_creators = (
                payload.get("TcgplayerCreators")
                or payload.get("TCGPlayerCreators")
                or payload.get("TcgPlayerCreators")
            )
            if isinstance(candidate_tcgplayer_creators, list):
                raw_tcgplayer_creators = [
                    creator
                    for item in candidate_tcgplayer_creators
                    if (creator := _parse_creator_config(item)) is not None
                ]

    return AppConfig(
        moxfield_creators=_dedupe_creators(raw_moxfield_creators),
        aetherhub_creators=_dedupe_creators(raw_aetherhub_creators),
        tcgplayer_creators=_dedupe_creators(raw_tcgplayer_creators),
    )


def _dedupe_creators(creators: list[CreatorConfig]) -> tuple[CreatorConfig, ...]:
    deduped_creators: list[CreatorConfig] = []
    seen: set[str] = set()
    for creator in creators:
        lowered = creator.name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped_creators.append(creator)
    return tuple(deduped_creators)


def _parse_creator_config(item: object) -> CreatorConfig | None:
    if isinstance(item, str):
        name = item.strip()
        return CreatorConfig(name=name) if name else None

    if not isinstance(item, dict):
        return None

    raw_name = item.get("Name") or item.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        return None

    raw_short_name = (
        item.get("ShortName")
        or item.get("shortName")
        or item.get("short_name")
        or item.get("Short")
        or item.get("short")
    )
    short_name = raw_short_name.strip() if isinstance(raw_short_name, str) else None
    return CreatorConfig(name=raw_name.strip(), short_name=short_name or None)
