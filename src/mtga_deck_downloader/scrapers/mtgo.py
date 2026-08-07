from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from mtga_deck_downloader.models import DeckEntry
from mtga_deck_downloader.scrapers.common import (
    ScrapeError,
    create_session,
    decode_response_text,
)


class MTGOScraper:
    BASE_URL = "https://www.mtgo.com"
    DECKLISTS_URL = f"{BASE_URL}/decklists"
    DATA_MARKER = "window.MTGO.decklists.data"
    INDEX_FETCH_ATTEMPTS = 2
    EVENT_FETCH_ATTEMPTS = 2
    PUBLISHED_EVENT_LIMIT = 3
    PUBLISHED_EVENT_SCAN_LIMIT = 8
    EVENT_VALIDATION_WORKERS = 4

    def __init__(self) -> None:
        self._session = create_session()
        self._session_factory = create_session
        self._event_cache: dict[str, list[DeckEntry]] = {}

    def fetch_events(self, limit: int = 50) -> list[DeckEntry]:
        failure = "no Standard event rows"
        for attempt in range(self.INDEX_FETCH_ATTEMPTS):
            session = self._session if attempt == 0 else self._session_factory()
            try:
                response = session.get(self.DECKLISTS_URL, timeout=8)
                response.raise_for_status()
                events = self._parse_events(decode_response_text(response), limit)
            except Exception as exc:
                failure = str(exc)
                continue
            if events:
                self._session = session
                return events
        raise ScrapeError(
            "MTGO did not return a usable Standard event index after "
            f"{self.INDEX_FETCH_ATTEMPTS} fresh sessions; last response {failure}."
        )

    def fetch_published_events(self, limit: int = PUBLISHED_EVENT_LIMIT) -> list[DeckEntry]:
        target = min(limit, self.PUBLISHED_EVENT_LIMIT)
        candidates = self.fetch_events(limit=self.PUBLISHED_EVENT_SCAN_LIMIT)
        with ThreadPoolExecutor(max_workers=self.EVENT_VALIDATION_WORKERS) as executor:
            validated = executor.map(self._validate_published_event, candidates)

        results: list[DeckEntry] = []
        failures: list[str] = []
        for validation in validated:
            if isinstance(validation, str):
                failures.append(validation)
                continue
            event, decks = validation
            self._event_cache[event.source_url] = decks
            results.append(event)
            if len(results) >= target:
                break

        if not results:
            failure_counts = Counter(failures)
            summary = ", ".join(
                f"{count} {reason}" for reason, count in sorted(failure_counts.items())
            )
            raise ScrapeError(
                f"MTGO listed {len(candidates)} recent Standard events, but none "
                "returned published deck data"
                f"{f' ({summary})' if summary else ''}."
            )
        return results

    def fetch_event_decks(self, event: DeckEntry, limit: int = 50) -> list[DeckEntry]:
        if event.source_url in self._event_cache:
            return list(self._event_cache[event.source_url][:limit])

        payload = self._fetch_event_payload(event)
        decks = self._parse_event_decks(payload, event)
        if not decks:
            raise ScrapeError(
                f"No decklists have been published for {event.name} yet."
            )

        self._event_cache[event.source_url] = decks
        return list(decks[:limit])

    def _fetch_event_payload(self, event: DeckEntry) -> dict[str, Any]:
        failure = "no event payload"
        for attempt in range(self.EVENT_FETCH_ATTEMPTS):
            session = self._session if attempt == 0 else self._session_factory()
            try:
                response = session.get(
                    event.source_url,
                    timeout=8,
                    allow_redirects=False,
                )
            except Exception as exc:
                failure = f"failed with {type(exc).__name__}"
                continue
            if response.status_code in {301, 302, 303, 307, 308}:
                location = str(response.headers.get("location") or "")
                failure = f"redirected to {location or 'another page'}"
                continue

            response.raise_for_status()
            if self._canonical_event_url(response.url) != event.source_url:
                failure = f"returned {response.url}"
                continue

            try:
                payload = self._extract_event_payload(decode_response_text(response))
            except ScrapeError as exc:
                failure = str(exc)
                continue

            self._session = session
            return payload

        raise ScrapeError(
            f"MTGO did not serve event data for {event.name} after "
            f"{self.EVENT_FETCH_ATTEMPTS} fresh sessions; last response {failure}."
        )

    def _validate_published_event(
        self,
        event: DeckEntry,
    ) -> tuple[DeckEntry, list[DeckEntry]] | str:
        session = self._session_factory()
        try:
            response = session.get(
                event.source_url,
                timeout=8,
                allow_redirects=False,
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                return "redirected to the decklist index"
            if response.status_code != 200:
                return f"returned HTTP {response.status_code}"
            if self._canonical_event_url(response.url) != event.source_url:
                return "returned the wrong page"
            payload = self._extract_event_payload(decode_response_text(response))
            decks = self._parse_event_decks(payload, event)
        except ScrapeError:
            return "omitted event data"
        except Exception as exc:
            return f"failed with {type(exc).__name__}"
        if not decks:
            return "had no published decks"
        return event, decks

    def _parse_events(self, html: str, limit: int) -> list[DeckEntry]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[tuple[datetime, DeckEntry]] = []
        seen_urls: set[str] = set()

        for link in soup.select("a.decklists-link[href], li.decklists-item > a[href]"):
            heading = link.find("h3")
            time = link.find("time")
            if heading is None:
                continue

            name = heading.get_text(" ", strip=True)
            if not name.lower().startswith("standard"):
                continue

            url = self._canonical_event_url(str(link.get("href") or ""))
            if not url or url in seen_urls:
                continue

            timestamp = str(time.get("datetime") or "").strip() if time else ""
            parsed_date = self._parse_datetime(timestamp)
            event_date = parsed_date.strftime("%m/%d/%Y") if parsed_date else None
            rows.append(
                (
                    parsed_date or datetime.min,
                    DeckEntry(
                        name=name,
                        source_site="mtgo.com",
                        source_url=url,
                        format_label="Standard (Bo3)",
                        event_name=name,
                        event_date=event_date,
                    ),
                )
            )
            seen_urls.add(url)

        rows.sort(key=lambda row: row[0], reverse=True)
        return [entry for _, entry in rows[:limit]]

    def _extract_event_payload(self, html: str) -> dict[str, Any]:
        marker_index = html.find(self.DATA_MARKER)
        if marker_index < 0:
            raise ScrapeError("Could not find MTGO event decklist data.")

        assignment_index = html.find("=", marker_index + len(self.DATA_MARKER))
        if assignment_index < 0:
            raise ScrapeError("Could not find MTGO event decklist assignment.")

        json_start = assignment_index + 1
        candidate = html[json_start:].lstrip()
        try:
            payload, _ = json.JSONDecoder().raw_decode(candidate)
        except json.JSONDecodeError as exc:
            raise ScrapeError("Could not parse MTGO event decklist data.") from exc
        if not isinstance(payload, dict):
            raise ScrapeError("Unexpected MTGO event decklist data.")
        return payload

    def _parse_event_decks(
        self,
        payload: dict[str, Any],
        event: DeckEntry,
    ) -> list[DeckEntry]:
        raw_decks = payload.get("decklists")
        if not isinstance(raw_decks, list):
            return []

        winloss = self._rows_by_login_id(payload.get("winloss"))
        final_rank = self._rows_by_login_id(payload.get("final_rank"))
        event_name = self._clean_text(payload.get("description")) or event.name
        event_date = (
            self._format_date(payload.get("starttime"))
            or self._format_date(payload.get("publish_date"))
            or event.event_date
        )

        results: list[DeckEntry] = []
        for row in raw_decks:
            if not isinstance(row, dict):
                continue
            login_id = self._clean_text(row.get("loginid"))
            player = self._clean_text(row.get("player")) or login_id
            main_deck = row.get("main_deck")
            sideboard = row.get("sideboard_deck")
            if not isinstance(main_deck, list):
                continue

            deck_text = self._build_deck_text(main_deck, sideboard)
            if not deck_text:
                continue

            record = winloss.get(login_id or "", {})
            wins = self._as_int(record.get("wins"))
            losses = self._as_int(record.get("losses"))
            matches = wins + losses if wins is not None and losses is not None else None
            win_rate = (wins / matches * 100) if wins is not None and matches else None
            rank = self._clean_text(final_rank.get(login_id or "", {}).get("rank"))

            results.append(
                DeckEntry(
                    name=self._deck_name(main_deck),
                    source_site="mtgo.com",
                    source_url=event.source_url,
                    format_label="Standard (Bo3)",
                    matches=matches,
                    win_rate=win_rate,
                    player_name=player,
                    placing=rank,
                    event_name=event_name,
                    event_date=event_date,
                    deck_text=deck_text,
                )
            )

        results.sort(key=self._placement_sort_key)
        return results

    @classmethod
    def _build_deck_text(cls, main_deck: list[Any], sideboard: Any) -> str | None:
        main_lines = cls._card_lines(main_deck)
        if not main_lines:
            return None

        sections = ["Deck", *main_lines]
        sideboard_lines = cls._card_lines(sideboard if isinstance(sideboard, list) else [])
        if sideboard_lines:
            sections.extend(["", "Sideboard", *sideboard_lines])
        return "\n".join(sections)

    @classmethod
    def _deck_name(cls, cards: list[Any]) -> str:
        candidates: list[tuple[int, str]] = []
        for card in cards:
            quantity, name, card_type = cls._card_values(card)
            if not name or "land" in card_type.lower():
                continue
            candidates.append((quantity or 0, name))

        high_quantity = [name for quantity, name in candidates if quantity >= 3]
        names = high_quantity[:2] or [name for _, name in candidates[:2]]
        return " + ".join(names) if names else "Standard Deck"

    @classmethod
    def _card_lines(cls, cards: list[Any]) -> list[str]:
        lines: list[str] = []
        for card in cards:
            quantity, name, _ = cls._card_values(card)
            if quantity and quantity > 0 and name:
                lines.append(f"{quantity} {name}")
        return lines

    @classmethod
    def _card_values(cls, card: Any) -> tuple[int | None, str | None, str]:
        if not isinstance(card, dict):
            return None, None, ""
        attributes = card.get("card_attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        return (
            cls._as_int(card.get("qty")),
            cls._clean_text(attributes.get("card_name")),
            cls._clean_text(attributes.get("card_type")) or "",
        )

    @classmethod
    def _rows_by_login_id(cls, value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, list):
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for row in value:
            if not isinstance(row, dict):
                continue
            login_id = cls._clean_text(row.get("loginid"))
            if login_id:
                rows[login_id] = row
        return rows

    @classmethod
    def _canonical_event_url(cls, href: str) -> str | None:
        url = urljoin(cls.BASE_URL, href.strip())
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"mtgo.com", "www.mtgo.com"}:
            return None
        if not parsed.path.startswith("/decklist/"):
            return None
        return f"{cls.BASE_URL}{parsed.path.rstrip('/')}"

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    @classmethod
    def _format_date(cls, value: Any) -> str | None:
        parsed = cls._parse_datetime(str(value or "").strip())
        return parsed.strftime("%m/%d/%Y") if parsed else None

    @staticmethod
    def _clean_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _placement_sort_key(deck: DeckEntry) -> tuple[int, str]:
        try:
            rank = int(deck.placing or "")
        except ValueError:
            rank = 1_000_000
        return rank, (deck.player_name or "").lower()
