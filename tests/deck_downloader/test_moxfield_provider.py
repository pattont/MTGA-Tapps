from __future__ import annotations

import unittest

from mtga_deck_downloader.config import AppConfig, MoxfieldCreator
from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.providers import moxfield as provider_module
from mtga_deck_downloader.providers.moxfield import MoxfieldProvider


class FakeScraper:
    def __init__(self, deck_text: str = "Deck\n4 Heartfire Hero") -> None:
        self.deck_text = deck_text

    def fetch_user_decks(self, username: str, limit: int = 15) -> list[DeckEntry]:
        return [
            DeckEntry(
                name="Boros Mouse Offense",
                source_site="moxfield.com",
                source_url=f"https://moxfield.com/decks/{username}",
                format_label="Standard",
                notes=f"Creator: {username}",
            )
        ]

    def fetch_deck_text(self, public_url: str) -> str | None:
        return self.deck_text


class MoxfieldProviderTests(unittest.TestCase):
    def test_fetch_decks_keeps_ui_names_clean_and_import_name_gets_creator_label(self) -> None:
        original_load_config = provider_module.load_config
        provider_module.load_config = lambda: AppConfig(
            moxfield_creators=(
                MoxfieldCreator(name="Ashlizzlle", short_name="Ash"),
                MoxfieldCreator(name="SwayzeMTG"),
            )
        )
        provider = MoxfieldProvider.__new__(MoxfieldProvider)
        provider._scraper = FakeScraper()
        try:
            decks = provider.fetch_decks(MatchFormat.ANY, limit=2)
        finally:
            provider_module.load_config = original_load_config

        self.assertEqual(
            [deck.name for deck in decks],
            ["Boros Mouse Offense", "Boros Mouse Offense"],
        )

        hydrated = provider.hydrate_deck(decks[0])

        self.assertEqual(
            hydrated.deck_text,
            "About\nName Boros Mouse Offense (Ash)\n\nDeck\n4 Heartfire Hero",
        )

    def test_hydrate_deck_rewrites_existing_about_name_with_creator_label(self) -> None:
        original_load_config = provider_module.load_config
        provider_module.load_config = lambda: AppConfig(
            moxfield_creators=(MoxfieldCreator(name="Ashlizzlle", short_name="Ash"),)
        )
        provider = MoxfieldProvider.__new__(MoxfieldProvider)
        provider._scraper = FakeScraper("About\nName Boros Mouse Offense \n\nDeck\n4 Heartfire Hero")
        deck = DeckEntry(
            name="Boros Mouse Offense",
            source_site="moxfield.com",
            source_url="https://moxfield.com/decks/Ashlizzlle",
            format_label="Standard",
            notes="Creator: Ashlizzlle",
        )
        try:
            hydrated = provider.hydrate_deck(deck)
        finally:
            provider_module.load_config = original_load_config

        self.assertEqual(
            hydrated.deck_text,
            "About\nName Boros Mouse Offense (Ash)\n\nDeck\n4 Heartfire Hero",
        )


if __name__ == "__main__":
    unittest.main()
