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
    def test_creator_decks_match_author_latest_order_across_magic_formats(self) -> None:
        scraper = RecordingTCGPlayerScraper(
            [
                {
                    "result": {
                        "author": {
                            "uuid": "b332b7d9-a0c6-11ed-8d46-42010a8a038e",
                            "name": "Arne Huschenbeth",
                        },
                    }
                },
                {
                    "result": [
                        {
                            "id": 546993,
                            "deck": {
                                "created": "2026-06-12T14:06:03Z",
                                "name": "Jeskai Lessons",
                                "format": "standard",
                                "playerName": "Arne Huschenbeth",
                            },
                        },
                        {
                            "id": 546640,
                            "deck": {
                                "created": "2026-06-05T18:16:15Z",
                                "name": "Jeskai Lessons",
                                "format": "standard",
                                "playerName": "Arne Huschenbeth",
                            },
                        },
                        {
                            "id": 546073,
                            "deck": {
                                "created": "2026-05-23T15:41:47Z",
                                "name": "Mono-Green Landfall",
                                "format": "standard",
                                "playerName": "Arne Huschenbeth",
                            },
                        },
                    ]
                },
            ]
        )

        decks = scraper.fetch_creator_decks("Arne Huschenbeth", limit=3)

        self.assertEqual(
            [deck.name for deck in decks],
            ["Jeskai Lessons", "Jeskai Lessons", "Mono-Green Landfall"],
        )
        self.assertEqual(decks[0].source_url, "https://www.tcgplayer.com/magic-the-gathering/deck/Jeskai-Lessons/546993")
        self.assertEqual(decks[0].format_label, "Standard")
        self.assertEqual(decks[0].player_name, "Arne Huschenbeth")
        self.assertEqual(decks[0].event_date, "06/12/2026")
        self.assertEqual(decks[0].notes, "Created: 06/12/2026 | Creator: Arne Huschenbeth")
        self.assertEqual(
            scraper.requests,
            [
                (
                    "https://infinite-api.tcgplayer.com/content/author/Arne%20Huschenbeth/",
                    {
                        "rows": 1,
                        "offset": 0,
                    },
                ),
                (
                    "https://infinite-api.tcgplayer.com/decks/",
                    {
                        "authorID": "b332b7d9-a0c6-11ed-8d46-42010a8a038e",
                        "rows": 3,
                        "offset": 0,
                        "latest": True,
                        "sort": "created",
                        "order": "desc",
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
