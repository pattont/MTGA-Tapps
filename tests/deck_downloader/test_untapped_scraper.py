from __future__ import annotations

import unittest

from mtga_deck_downloader.models import MatchFormat
from mtga_deck_downloader.scrapers.untapped import UntappedScraper


class RecordingUntappedScraper(UntappedScraper):
    def __init__(self) -> None:
        self.payloads = {
            "decks_by_event_scope": [
                {"ptg": 1001, "ds": "deckstring-1"},
                {"ptg": 1001, "ds": "deckstring-2"},
            ],
            "archetypes_by_event_scope": [
                {
                    "primary_tag_group_id": 1001,
                    "primary_tags": [1, 2],
                    "stats": {"rank": {"total_matches": 10, "winrate": 60.0}},
                }
            ],
            "tags": [
                {"id": 1, "name": "Izzet", "metadata": {"type": 7}},
                {"id": 2, "name": "Prowess", "metadata": {"type": 6}},
            ],
        }

    def _get_meta_period_id(self, event_name: str) -> int:
        return 1

    def _get_json(self, url: str) -> object:
        for key, payload in self.payloads.items():
            if key in url:
                return payload
        raise AssertionError(f"Unexpected URL: {url}")


class UntappedScraperTests(unittest.TestCase):
    def test_fetch_mode_notes_only_show_variant_count(self) -> None:
        scraper = RecordingUntappedScraper()

        decks = scraper._fetch_mode("Ladder", MatchFormat.BO1, limit=10)

        self.assertEqual(len(decks), 1)
        self.assertEqual(decks[0].notes, "2 variant decks available.")


if __name__ == "__main__":
    unittest.main()
