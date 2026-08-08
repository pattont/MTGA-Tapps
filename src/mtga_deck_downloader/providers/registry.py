from __future__ import annotations

import importlib
import pkgutil

import mtga_deck_downloader.providers as providers_pkg
from mtga_deck_downloader.providers.base import DeckProvider

LAST_PROVIDER_ERRORS: list[str] = []

#: Fallback module list for frozen (PyInstaller) builds, where pkgutil cannot
#: always enumerate the bundled package. Keep in sync with providers/*.py.
_KNOWN_PROVIDER_MODULES = (
    "aetherhub",
    "magic_gg",
    "moxfield",
    "mtgo",
    "tcgplayer",
    "untapped",
)


def _provider_module_names() -> list[str]:
    prefix = f"{providers_pkg.__name__}."
    names = [
        module_info.name
        for module_info in pkgutil.iter_modules(providers_pkg.__path__, prefix)
    ]
    if names:
        return names
    return [prefix + name for name in _KNOWN_PROVIDER_MODULES]


def load_providers() -> list[DeckProvider]:
    providers: list[DeckProvider] = []
    LAST_PROVIDER_ERRORS.clear()

    for module_name in _provider_module_names():
        if module_name.endswith(".base") or module_name.endswith(".registry"):
            continue

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            LAST_PROVIDER_ERRORS.append(f"{module_name}: {exc}")
            continue

        provider_class = getattr(module, "PROVIDER_CLASS", None)
        if provider_class and issubclass(provider_class, DeckProvider):
            try:
                providers.append(provider_class())
            except Exception as exc:
                LAST_PROVIDER_ERRORS.append(f"{module_name}: {exc}")

    return sorted(providers, key=lambda provider: provider.display_name.lower())
