from __future__ import annotations

import importlib
import pkgutil

import mtga_deck_downloader.providers as providers_pkg
from mtga_deck_downloader.providers.base import DeckProvider

LAST_PROVIDER_ERRORS: list[str] = []


def load_providers() -> list[DeckProvider]:
    providers: list[DeckProvider] = []
    LAST_PROVIDER_ERRORS.clear()

    for module_info in pkgutil.iter_modules(
        providers_pkg.__path__, f"{providers_pkg.__name__}."
    ):
        if module_info.name.endswith(".base") or module_info.name.endswith(".registry"):
            continue

        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:
            LAST_PROVIDER_ERRORS.append(f"{module_info.name}: {exc}")
            continue

        provider_class = getattr(module, "PROVIDER_CLASS", None)
        if provider_class and issubclass(provider_class, DeckProvider):
            try:
                providers.append(provider_class())
            except Exception as exc:
                LAST_PROVIDER_ERRORS.append(f"{module_info.name}: {exc}")

    return sorted(providers, key=lambda provider: provider.display_name.lower())
