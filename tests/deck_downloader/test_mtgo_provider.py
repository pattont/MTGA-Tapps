from __future__ import annotations

import unittest

from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.providers.mtgo import MTGOProvider


class FakeScraper:
    def __init__(self) -> None:
        self.event_limit: int | None = None
        self.variant_limit: int | None = None

    def fetch_published_events(self, limit: int = 3) -> list[DeckEntry]:
        self.event_limit = limit
        return [event_entry()]

    def fetch_event_decks(self, event: DeckEntry, limit: int = 50) -> list[DeckEntry]:
        self.variant_limit = limit
        return [
            DeckEntry(
                name="Dimir Midrange",
                source_site="mtgo.com",
                source_url=event.source_url,
                format_label="Standard (Bo3)",
                player_name="Alice",
                deck_text="Deck\n4 Spyglass Siren",
            )
        ]


def event_entry() -> DeckEntry:
    return DeckEntry(
        name="Standard Challenge 32",
        source_site="mtgo.com",
        source_url="https://www.mtgo.com/decklist/standard-challenge-32-2026-07-25",
        format_label="Standard (Bo3)",
        event_date="07/25/2026",
    )


class MTGOProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = MTGOProvider.__new__(MTGOProvider)
        self.provider._scraper = FakeScraper()

    def test_source_is_standard_bo3_and_skips_source_picker(self) -> None:
        self.assertFalse(self.provider.uses_source_picker)
        self.assertEqual(self.provider.sources[0].name, "Standard Events")
        self.assertEqual(self.provider.sources[0].formats, (MatchFormat.BO3,))
        self.assertEqual(self.provider.list_sources(MatchFormat.BO1), [])

    def test_fetches_events_and_expands_them_to_decks(self) -> None:
        events = self.provider.fetch_decks(MatchFormat.BO3, limit=80)
        decks = self.provider.fetch_deck_variants(events[0], MatchFormat.BO3, limit=80)

        self.assertEqual(self.provider._scraper.event_limit, 3)
        self.assertEqual(self.provider._scraper.variant_limit, 50)
        self.assertEqual(decks[0].player_name, "Alice")
        self.assertEqual(
            self.provider.result_view_config().selection_action,
            "decklists",
        )
        self.assertEqual(
            self.provider.result_view_config(variants=True, parent=events[0]).title,
            "Standard Challenge 32 Decklists",
        )

    def test_bo1_and_non_event_rows_are_not_fetched(self) -> None:
        self.assertEqual(self.provider.fetch_decks(MatchFormat.BO1), [])
        other = DeckEntry(
            name="Other",
            source_site="example.com",
            source_url="https://example.com/deck",
            format_label="Standard",
        )
        self.assertIsNone(
            self.provider.fetch_deck_variants(other, MatchFormat.BO3)
        )


if __name__ == "__main__":
    unittest.main()
