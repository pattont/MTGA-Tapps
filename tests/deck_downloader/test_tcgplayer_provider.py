from __future__ import annotations

import unittest
from dataclasses import replace

from mtga_deck_downloader.config import AppConfig, CreatorConfig
from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.providers import tcgplayer as provider_module
from mtga_deck_downloader.providers.tcgplayer import TCGPlayerProvider


class FakeScraper:
    def fetch_creator_decks(self, author_name: str, limit: int = 50) -> list[DeckEntry]:
        return [
            DeckEntry(
                name="Dimir Control",
                source_site="tcgplayer.com",
                source_url="https://www.tcgplayer.com/magic-the-gathering/deck/Dimir-Control/496327",
                format_label="Standard",
                notes=f"Creator: {author_name}",
            )
        ]

    def hydrate_deck(self, deck: DeckEntry) -> DeckEntry:
        return replace(deck, deck_text="Deck\n4 Island")


class TCGPlayerProviderTests(unittest.TestCase):
    def test_creator_sources_and_import_names_use_configured_short_names(self) -> None:
        original_load_config = provider_module.load_config
        provider_module.load_config = lambda: AppConfig(
            moxfield_creators=(),
            aetherhub_creators=(),
            tcgplayer_creators=(CreatorConfig(name="Arne Huschenbeth", short_name="Arne"),),
        )
        provider = TCGPlayerProvider.__new__(TCGPlayerProvider)
        provider._scraper = FakeScraper()
        try:
            creator_sources = [source for source in provider.sources if source.name.startswith("Creator: ")]
            decks = provider.fetch_decks(MatchFormat.ANY, limit=1, source=creator_sources[0])
            hydrated = provider.hydrate_deck(decks[0])
        finally:
            provider_module.load_config = original_load_config

        self.assertEqual(creator_sources[0].name, "Creator: Arne Huschenbeth")
        self.assertEqual(
            creator_sources[0].url,
            "https://www.tcgplayer.com/content/author/Arne%20Huschenbeth/",
        )
        self.assertEqual(decks[0].name, "Dimir Control")
        self.assertEqual(
            hydrated.deck_text,
            "About\nName Dimir Control (Arne)\n\nDeck\n4 Island",
        )


if __name__ == "__main__":
    unittest.main()
