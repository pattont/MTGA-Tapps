from __future__ import annotations

import json
import unittest

from mtga_deck_downloader.models import DeckEntry
from mtga_deck_downloader.scrapers.common import ScrapeError
from mtga_deck_downloader.scrapers.mtgo import MTGOScraper


class FakeResponse:
    def __init__(
        self,
        text: str,
        *,
        url: str = "https://www.mtgo.com/decklists",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = text.encode()
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        return None


class SequenceSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests = 0

    def get(
        self,
        url: str,
        timeout: int,
        allow_redirects: bool = True,
    ) -> FakeResponse:
        self.requests += 1
        return self.responses.pop(0)


class MTGOScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scraper = MTGOScraper.__new__(MTGOScraper)

    def test_event_index_keeps_standard_events_in_date_order(self) -> None:
        html = """
        <ul>
          <li class="decklists-item">
            <a href="/decklist/standard-league-2026-07-251">
              <h3>Standard League</h3>
              <time datetime="2026-07-25T00:00:00Z">July 25</time>
            </a>
          </li>
          <li class="decklists-item">
            <a href="/decklist/modern-challenge-2026-07-263">
              <h3>Modern Challenge 32</h3>
              <time datetime="2026-07-26T00:00:00Z">July 26</time>
            </a>
          </li>
          <li class="decklists-item">
            <a href="/decklist/standard-challenge-32-2026-07-262">
              <h3>Standard Challenge 32</h3>
              <time datetime="2026-07-26T00:00:00Z">July 26</time>
            </a>
          </li>
          <li class="decklists-item">
            <a href="/decklist/standard-challenge-32-2026-07-262">
              <h3>Duplicate</h3>
            </a>
          </li>
        </ul>
        """

        events = self.scraper._parse_events(html, limit=10)

        self.assertEqual(
            [event.name for event in events],
            ["Standard Challenge 32", "Standard League"],
        )
        self.assertEqual(events[0].event_date, "07/26/2026")
        self.assertEqual(
            events[0].source_url,
            "https://www.mtgo.com/decklist/standard-challenge-32-2026-07-262",
        )
        self.assertEqual(events[0].format_label, "Standard (Bo3)")
        self.assertIsNone(events[0].deck_text)

    def test_event_index_accepts_decklist_links_without_list_wrapper(self) -> None:
        html = """
        <div>
          <a class="decklists-link" href="/decklist/standard-league-2026-07-251">
            <h3>Standard League</h3>
            <time datetime="2026-07-25T00:00:00Z">July 25</time>
          </a>
        </div>
        """

        events = self.scraper._parse_events(html, limit=10)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "Standard League")

    def test_event_fetch_retries_an_empty_index_response(self) -> None:
        event_html = """
        <a class="decklists-link" href="/decklist/standard-league-2026-07-251">
          <h3>Standard League</h3>
          <time datetime="2026-07-25T00:00:00Z">July 25</time>
        </a>
        """
        empty_session = SequenceSession([FakeResponse("<html></html>")])
        recovered_session = SequenceSession([FakeResponse(event_html)])
        self.scraper._session = empty_session
        self.scraper._session_factory = lambda: recovered_session

        events = self.scraper.fetch_events(limit=10)

        self.assertEqual(len(events), 1)
        self.assertEqual(empty_session.requests, 1)
        self.assertEqual(recovered_session.requests, 1)
        self.assertIs(self.scraper._session, recovered_session)

    def test_event_fetch_reports_repeated_empty_index_responses(self) -> None:
        self.scraper._session = SequenceSession([FakeResponse("<html></html>")])
        self.scraper._session_factory = lambda: SequenceSession(
            [FakeResponse("<html></html>")]
        )

        with self.assertRaisesRegex(ScrapeError, "no Standard event rows"):
            self.scraper.fetch_events(limit=10)

    def test_event_payload_rotates_session_after_mtgo_index_redirect(self) -> None:
        event = DeckEntry(
            name="Standard Challenge 32",
            source_site="mtgo.com",
            source_url=(
                "https://www.mtgo.com/decklist/"
                "standard-challenge-32-2026-07-2512848200"
            ),
            format_label="Standard (Bo3)",
        )
        redirected_session = SequenceSession(
            [
                FakeResponse(
                    "",
                    url=event.source_url,
                    status_code=302,
                    headers={"location": "/decklists"},
                )
            ]
        )
        recovered_session = SequenceSession(
            [
                FakeResponse(
                    (
                        "<script>window.MTGO.decklists.data = "
                        '{"decklists": []};</script>'
                    ),
                    url=event.source_url,
                )
            ]
        )
        self.scraper._session = redirected_session
        self.scraper._session_factory = lambda: recovered_session

        payload = self.scraper._fetch_event_payload(event)

        self.assertEqual(payload, {"decklists": []})
        self.assertEqual(redirected_session.requests, 1)
        self.assertEqual(recovered_session.requests, 1)
        self.assertIs(self.scraper._session, recovered_session)

    def test_published_event_results_are_validated_and_cached_before_display(self) -> None:
        unavailable = DeckEntry(
            name="Standard League",
            source_site="mtgo.com",
            source_url="https://www.mtgo.com/decklist/unavailable",
            format_label="Standard (Bo3)",
        )
        published = DeckEntry(
            name="Standard Challenge 32",
            source_site="mtgo.com",
            source_url="https://www.mtgo.com/decklist/published",
            format_label="Standard (Bo3)",
        )
        published_deck = DeckEntry(
            name="Dimir Midrange",
            source_site="mtgo.com",
            source_url=published.source_url,
            format_label="Standard (Bo3)",
            deck_text="Deck\n4 Spyglass Siren",
        )
        self.scraper._event_cache = {}
        self.scraper.fetch_events = lambda limit: [unavailable, published]
        self.scraper._validate_published_event = (
            lambda event: (event, [published_deck])
            if event is published
            else "redirected to the decklist index"
        )

        events = self.scraper.fetch_published_events(limit=8)
        decks = self.scraper.fetch_event_decks(events[0], limit=50)

        self.assertEqual(events, [published])
        self.assertEqual(decks, [published_deck])

    def test_published_event_fetch_rejects_an_entirely_dead_index(self) -> None:
        unavailable = DeckEntry(
            name="Standard League",
            source_site="mtgo.com",
            source_url="https://www.mtgo.com/decklist/unavailable",
            format_label="Standard (Bo3)",
        )
        self.scraper._event_cache = {}
        self.scraper.fetch_events = lambda limit: [unavailable]
        self.scraper._validate_published_event = (
            lambda event: "redirected to the decklist index"
        )

        with self.assertRaisesRegex(
            ScrapeError,
            "1 redirected to the decklist index",
        ):
            self.scraper.fetch_published_events(limit=8)

    def test_event_payload_builds_arena_text_and_applies_results(self) -> None:
        payload = {
            "description": "Standard Challenge 32",
            "starttime": "2026-07-25T15:00:00Z",
            "decklists": [
                {
                    "loginid": "alice-id",
                    "player": "Alice",
                    "main_deck": [
                        {
                            "qty": 4,
                            "card_attributes": {
                                "card_name": "Patchwork Beastie",
                                "card_type": "Creature",
                            },
                        },
                        {
                            "qty": "4",
                            "card_attributes": {
                                "card_name": "Rapid Rescue",
                                "card_type": "Instant",
                            },
                        },
                        {
                            "qty": 20,
                            "card_attributes": {
                                "card_name": "Plains",
                                "card_type": "Basic Land",
                            },
                        },
                    ],
                    "sideboard_deck": [
                        {
                            "qty": 2,
                            "card_attributes": {
                                "card_name": "Disdainful Stroke",
                                "card_type": "Instant",
                            },
                        }
                    ],
                }
            ],
            "winloss": [{"loginid": "alice-id", "wins": 5, "losses": 1}],
            "final_rank": [{"loginid": "alice-id", "rank": 2}],
        }
        html = (
            "<script>window.MTGO.decklists.data = "
            + json.dumps(payload)
            + ";\nwindow.MTGO.ready = true;</script>"
        )
        event = DeckEntry(
            name="Standard Challenge",
            source_site="mtgo.com",
            source_url="https://www.mtgo.com/decklist/standard-challenge",
            format_label="Standard (Bo3)",
            event_date="07/25/2026",
        )

        parsed_payload = self.scraper._extract_event_payload(html)
        decks = self.scraper._parse_event_decks(parsed_payload, event)

        self.assertEqual(len(decks), 1)
        deck = decks[0]
        self.assertEqual(deck.name, "Patchwork Beastie + Rapid Rescue")
        self.assertEqual(deck.player_name, "Alice")
        self.assertEqual(deck.matches, 6)
        self.assertAlmostEqual(deck.win_rate or 0, 83.3333, places=3)
        self.assertEqual(deck.placing, "2")
        self.assertEqual(deck.event_name, "Standard Challenge 32")
        self.assertEqual(deck.event_date, "07/25/2026")
        self.assertEqual(
            deck.deck_text,
            "Deck\n"
            "4 Patchwork Beastie\n"
            "4 Rapid Rescue\n"
            "20 Plains\n"
            "\n"
            "Sideboard\n"
            "2 Disdainful Stroke",
        )

    def test_missing_or_invalid_embedded_payload_raises(self) -> None:
        with self.assertRaisesRegex(ScrapeError, "find MTGO"):
            self.scraper._extract_event_payload("<html></html>")
        with self.assertRaisesRegex(ScrapeError, "parse MTGO"):
            self.scraper._extract_event_payload(
                "<script>window.MTGO.decklists.data = {oops};</script>"
            )

    def test_unpublished_event_has_no_parsed_decks(self) -> None:
        event = DeckEntry(
            name="Standard League",
            source_site="mtgo.com",
            source_url="https://www.mtgo.com/decklist/standard-league",
            format_label="Standard (Bo3)",
        )

        self.assertEqual(self.scraper._parse_event_decks({"decklists": []}, event), [])


if __name__ == "__main__":
    unittest.main()
