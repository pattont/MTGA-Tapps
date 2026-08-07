from __future__ import annotations

import unittest

from mtga_deck_downloader.models import MatchFormat
from mtga_deck_downloader.scrapers.magic_gg import MagicGGScraper


class MagicGGScraperTests(unittest.TestCase):
    def test_traditional_ranked_decklist_uses_standard_bo3_format_label(self) -> None:
        html = """
        <html>
          <head><title>Traditional Standard Ranked Decklists: July 6, 2026</title></head>
          <body>
            <deck-list
              event-name="Traditional (Bo3)"
              event-date="July 6, 2026"
              deck-title="Platinum-Mythic Rank Player"
              format="Standard">
              <main-deck>
                4 Plains
                4 Island
                4 Swamp
                4 Mountain
                4 Forest
                4 Adarkar Wastes
                4 Battlefield Forge
                4 Demolition Field
                4 Patchwork Beastie
                4 Rapid Rescue
              </main-deck>
            </deck-list>
          </body>
        </html>
        """
        scraper = MagicGGScraper.__new__(MagicGGScraper)

        decks = scraper._extract_article_decks(
            article_html=html,
            article_url="https://magic.gg/decklists/traditional-standard-ranked-decklists-july-6-2026",
            selected_format=MatchFormat.ANY,
        )

        self.assertEqual(len(decks), 1)
        self.assertEqual(decks[0].format_label, "Standard (Bo3)")
        self.assertEqual(decks[0].event_date, "July 6, 2026")
        self.assertEqual(decks[0].notes, "Traditional (Bo3)")


if __name__ == "__main__":
    unittest.main()
