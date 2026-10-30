from __future__ import annotations

import unittest
from typing import Any

from mtga_deck_downloader.scrapers.tcgplayer import TCGPlayerScraper


class RecordingTCGPlayerScraper(TCGPlayerScraper):
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((url, params))
        return self.payloads.pop(0)


class TCGPlayerScraperTests(unittest.TestCase):
    def test_creator_decks_search_by_author_name_across_magic_formats(self) -> None:
        scraper = RecordingTCGPlayerScraper(
            [
                {
                    "result": [
                        {
                            "contentType": "deck",
                            "date": "7/17/2026",
                            "deckData": {
                                "deckName": "Esper Goryo's",
                                "format": "modern",
                                "playerName": "Arne Huschenbeth",
                            },
                            "deckID": "548737",
                            "title": "Esper Goryo's",
                            "canonicalURL": "/magic-the-gathering/deck/Esper-Goryo's/548737",
                        },
                        {
                            "contentType": "deck",
                            "date": "6/12/2026",
                            "deckData": {
                                "deckName": "Jeskai Lessons",
                                "format": "standard",
                                "playerName": "Arne Huschenbeth",
                            },
                            "deckID": "546993",
                            "title": "Jeskai Lessons",
                            "canonicalURL": "/magic-the-gathering/deck/Jeskai-Lessons/546993",
                        },
                        {
                            "contentType": "deck",
                            "date": "6/5/2026",
                            "deckData": {
                                "deckName": "Jeskai Lessons",
                                "format": "standard",
                                "playerName": "Arne Huschenbeth",
                            },
                            "deckID": "546640",
                            "title": "Jeskai Lessons",
                            "canonicalURL": "/magic-the-gathering/deck/Jeskai-Lessons/546640",
                        },
                    ]
                },
            ]
        )

        decks = scraper.fetch_creator_decks("Arne Huschenbeth", limit=3)

        self.assertEqual(
            [deck.name for deck in decks],
            ["Esper Goryo's", "Jeskai Lessons", "Jeskai Lessons"],
        )
        self.assertEqual(
            decks[1].source_url,
            "https://www.tcgplayer.com/magic-the-gathering/deck/Jeskai-Lessons/546993",
        )
        self.assertEqual(decks[0].format_label, "Modern")
        self.assertEqual(decks[1].format_label, "Standard")
        self.assertEqual(decks[1].player_name, "Arne Huschenbeth")
        self.assertEqual(decks[1].event_date, "06/12/2026")
        self.assertEqual(decks[1].notes, "Created: 06/12/2026 | Creator: Arne Huschenbeth")
        self.assertEqual(
            scraper.requests,
            [
                (
                    "https://infinite-api.tcgplayer.com/content/search/",
                    {
                        "contentType": "deck",
                        "game": "magic",
                        "author": "Arne Huschenbeth",
                        "rows": 3,
                        "offset": 0,
                        "sort": "created",
                        "order": "desc",
                    },
                ),
            ],
        )

    def test_creator_with_no_decks_names_the_creator(self) -> None:
        scraper = RecordingTCGPlayerScraper([{"result": []}])

        with self.assertRaisesRegex(Exception, "no decks by Nobody Here"):
            scraper.fetch_creator_decks("Nobody Here")


if __name__ == "__main__":
    unittest.main()
