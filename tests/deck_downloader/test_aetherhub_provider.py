from __future__ import annotations

import unittest

from mtga_deck_downloader.config import AppConfig, CreatorConfig
from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.providers import aetherhub as provider_module
from mtga_deck_downloader.providers.aetherhub import AetherhubProvider


class FakeScraper:
    def __init__(self) -> None:
        self.source_urls: set[str] | None = None
        self.creator_calls = 0

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source_urls: set[str] | None = None,
    ) -> list[DeckEntry]:
        self.source_urls = source_urls
        return [
            DeckEntry(
                name="Domain",
                source_site="aetherhub.com",
                source_url="https://aetherhub.com/Deck/domain",
                format_label=selected_format.label,
            )
        ]

    def fetch_creator_decks(
        self,
        user_url: str,
        selected_format: MatchFormat,
        limit: int = 50,
        creator_label: str | None = None,
    ) -> list[DeckEntry]:
        self.creator_calls += 1
        return [
            DeckEntry(
                name="Boros Mouse Offense",
                source_site="aetherhub.com",
                source_url=user_url,
                format_label=selected_format.label,
                notes=f"Creator: {creator_label}",
            )
        ]

    def fetch_deck_text(self, source_url: str) -> str | None:
        return "Deck\n4 Heartfire Hero"


class AetherhubProviderTests(unittest.TestCase):
    def test_creator_sources_and_import_names_use_configured_short_names(self) -> None:
        original_load_config = provider_module.load_config
        provider_module.load_config = lambda: AppConfig(
            moxfield_creators=(),
            aetherhub_creators=(CreatorConfig(name="MTGMalone", short_name="Malone"),),
        )
        provider = AetherhubProvider.__new__(AetherhubProvider)
        provider._scraper = FakeScraper()
        try:
            creator_sources = [source for source in provider.sources if source.name.startswith("Creator: ")]
            decks = provider.fetch_decks(MatchFormat.BO1, limit=1, source=creator_sources[0])
            hydrated = provider.hydrate_deck(decks[0])
        finally:
            provider_module.load_config = original_load_config

        self.assertEqual(creator_sources[0].name, "Creator: MTGMalone")
        self.assertEqual(creator_sources[0].url, "https://aetherhub.com/User/MTGMalone/Decks")
        self.assertEqual(decks[0].name, "Boros Mouse Offense")
        self.assertEqual(
            hydrated.deck_text,
            "About\nName Boros Mouse Offense (Malone)\n\nDeck\n4 Heartfire Hero",
        )

    def test_creator_sources_show_on_format_screen_not_endpoint_picker(self) -> None:
        original_load_config = provider_module.load_config
        provider_module.load_config = lambda: AppConfig(
            moxfield_creators=(),
            aetherhub_creators=(
                CreatorConfig(name="MTGMalone"),
                CreatorConfig(name="ManaMan"),
            ),
        )
        provider = AetherhubProvider.__new__(AetherhubProvider)
        provider._scraper = FakeScraper()
        try:
            format_screen_names = [source.name for source in provider.format_screen_sources]
            bo3_source_names = [source.name for source in provider.list_sources(MatchFormat.BO3)]
        finally:
            provider_module.load_config = original_load_config

        self.assertEqual(format_screen_names, ["Creator: MTGMalone", "Creator: ManaMan"])
        self.assertEqual(
            bo3_source_names,
            ["Tournament", "Tournament Meta", "MTGA BO3 Meta"],
        )

    def test_all_aetherhub_endpoints_do_not_fetch_creator_pages(self) -> None:
        original_load_config = provider_module.load_config
        provider_module.load_config = lambda: AppConfig(
            moxfield_creators=(),
            aetherhub_creators=(CreatorConfig(name="ManaMan"),),
        )
        provider = AetherhubProvider.__new__(AetherhubProvider)
        scraper = FakeScraper()
        provider._scraper = scraper
        try:
            decks = provider.fetch_decks(MatchFormat.BO3, limit=50, source=None)
        finally:
            provider_module.load_config = original_load_config

        self.assertEqual(decks[0].name, "Domain")
        self.assertEqual(scraper.creator_calls, 0)
        self.assertEqual(
            scraper.source_urls,
            {
                "https://aetherhub.com/Events/Standard/",
                "https://aetherhub.com/Metagame/Standard-Events/",
                "https://aetherhub.com/Metagame/Standard-BO3/",
            },
        )


if __name__ == "__main__":
    unittest.main()
