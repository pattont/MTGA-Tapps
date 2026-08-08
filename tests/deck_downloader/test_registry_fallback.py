"""The frozen-build provider fallback must track the real provider modules.

PyInstaller builds can't always enumerate the bundled package with pkgutil,
so registry.py keeps a static module list. If someone adds or removes a
provider without updating it, the packaged Deck Finder silently loses that
provider — this test makes the drift loud instead.
"""

from pathlib import Path

from mtga_deck_downloader.providers import registry


def test_known_provider_fallback_matches_modules_on_disk():
    providers_dir = Path(registry.providers_pkg.__path__[0])
    on_disk = sorted(
        path.stem
        for path in providers_dir.glob("*.py")
        if path.stem not in ("__init__", "base", "registry")
    )
    assert sorted(registry._KNOWN_PROVIDER_MODULES) == on_disk


def test_fallback_names_load_the_same_providers(monkeypatch):
    import pkgutil

    monkeypatch.setattr(pkgutil, "iter_modules", lambda *a, **k: iter(()))
    names = [p.display_name for p in registry.load_providers()]
    assert "moxfield.com" in names
    assert len(names) == len(registry._KNOWN_PROVIDER_MODULES)
    assert not registry.LAST_PROVIDER_ERRORS
