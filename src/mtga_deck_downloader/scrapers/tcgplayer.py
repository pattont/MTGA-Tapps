from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import quote, urljoin

from mtga_deck_downloader.models import DeckEntry
from mtga_deck_downloader.scrapers.common import ScrapeError, create_session


class TCGPlayerScraper:
    BASE_URL = "https://www.tcgplayer.com"
    API_BASE = "https://infinite-api.tcgplayer.com"
    SOURCE = "infinite-content"
    GAME = "magic"
    FORMAT = "standard"
    TRENDING_URL = f"{API_BASE}/content/decks/trending/"
    LATEST_URL = f"{API_BASE}/content/decks/{GAME}"
    EVENTS_URL = f"{API_BASE}/content/events/{GAME}/"
    SEARCH_URL = f"{API_BASE}/content/search/"
    AUTHOR_URL = f"{API_BASE}/content/author/{{author_name}}/"
    AFFILIATE_DECKS_URL = f"{API_BASE}/decks/"
    DECK_URL = f"{API_BASE}/deck/{GAME}/{{deck_id}}/"
    DEFAULT_DECK_LIMIT = 50
    DEFAULT_EVENT_LIMIT = 25
    EVENT_DECK_PAGE_SIZE = 24
    MAX_EVENT_DECK_PAGES = 5

    def __init__(self) -> None:
        self._session = create_session()
        self._session.headers.update({"Accept-Language": "en-US,en;q=0.9"})
        self._deck_payload_cache: dict[str, dict[str, Any] | None] = {}
        self._event_decks_cache: dict[tuple[str, str], list[DeckEntry]] = {}
        self._author_id_cache: dict[str, str] = {}

    def fetch_trending_decks(self, limit: int = DEFAULT_DECK_LIMIT) -> list[DeckEntry]:
        payload = self._get_json(
            self.TRENDING_URL,
            {
                "game": self.GAME,
                "format": self.FORMAT,
                "offset": 0,
                "rows": max(1, limit),
            },
        )
        rows = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ScrapeError("Unexpected TCGPlayer trending deck payload.")
        return [entry for row in rows[:limit] if (entry := self._parse_trending_row(row)) is not None]

    def fetch_latest_decks(self, limit: int = DEFAULT_DECK_LIMIT) -> list[DeckEntry]:
        payload = self._get_json(
            self.LATEST_URL,
            {
                "format": self.FORMAT,
                "offset": 0,
                "rows": max(1, limit),
                "latest": True,
                "sort": "created",
                "order": "desc",
            },
        )
        rows = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ScrapeError("Unexpected TCGPlayer latest deck payload.")
        return [entry for row in rows[:limit] if (entry := self._parse_latest_row(row)) is not None]

    def fetch_creator_decks(self, author_name: str, limit: int = DEFAULT_DECK_LIMIT) -> list[DeckEntry]:
        author_id = self._get_author_id(author_name)
        payload = self._get_json(
            self.AFFILIATE_DECKS_URL,
            {
                "authorID": author_id,
                "rows": max(1, limit),
                "offset": 0,
                "latest": True,
                "sort": "created",
                "order": "desc",
            },
        )
        rows = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ScrapeError("Unexpected TCGPlayer creator deck payload.")

        results: list[DeckEntry] = []
        for row in rows[:limit]:
            entry = self._parse_affiliate_deck_row(row)
            if entry is None:
                continue
            notes = self._join_notes([entry.notes, f"Creator: {author_name}"])
            results.append(replace(entry, notes=notes))
        return results

    def _get_author_id(self, author_name: str) -> str:
        cache = getattr(self, "_author_id_cache", {})
        if author_name in cache:
            return cache[author_name]

        payload = self._get_json(
            self.AUTHOR_URL.format(author_name=quote(author_name)),
            {
                "rows": 1,
                "offset": 0,
            },
        )
        result = payload.get("result") if isinstance(payload, dict) else None
        author = result.get("author") if isinstance(result, dict) else None
        author_id = str(author.get("uuid") or "").strip() if isinstance(author, dict) else ""
        if not author_id:
            raise ScrapeError(f"Could not find TCGPlayer author ID for {author_name}.")

        cache[author_name] = author_id
        self._author_id_cache = cache
        return author_id

    def fetch_events(self, limit: int = DEFAULT_EVENT_LIMIT) -> list[DeckEntry]:
        payload = self._get_json(
            self.EVENTS_URL,
            {
                "format": self.FORMAT,
                "offset": 0,
                "rows": max(1, limit),
                "sort": "created",
                "order": "desc",
            },
        )
        rows = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ScrapeError("Unexpected TCGPlayer events payload.")
        return [entry for row in rows[:limit] if (entry := self._parse_event_row(row)) is not None]

    def fetch_event_decks(self, event: DeckEntry, limit: int = DEFAULT_DECK_LIMIT) -> list[DeckEntry]:
        if not event.event_date:
            raise ScrapeError("Selected TCGPlayer event did not include an event date.")

        cache_key = (event.name, event.event_date)
        if cache_key in self._event_decks_cache:
            return list(self._event_decks_cache[cache_key][:limit])

        results: list[DeckEntry] = []
        seen_urls: set[str] = set()
        event_name = event.name.strip()
        event_date = event.event_date.strip()

        for page_index in range(self.MAX_EVENT_DECK_PAGES):
            offset = page_index * self.EVENT_DECK_PAGE_SIZE
            payload = self._get_json(
                self.SEARCH_URL,
                {
                    "contentType": "deck",
                    "sort": "created",
                    "order": "desc",
                    "game": self.GAME,
                    "format": self.FORMAT,
                    "rows": self.EVENT_DECK_PAGE_SIZE,
                    "offset": offset,
                    "eventNames": event_name,
                },
            )
            rows = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break

            matched_this_page = 0
            for row in rows:
                entry = self._parse_latest_row(row)
                if entry is None or entry.source_url in seen_urls:
                    continue
                detailed = self._hydrate_from_payload(entry)
                if detailed.event_name != event_name or detailed.event_date != event_date:
                    continue
                matched_this_page += 1
                seen_urls.add(detailed.source_url)
                results.append(detailed)
                if len(results) >= limit:
                    break

            if len(results) >= limit:
                break
            if matched_this_page == 0 and results:
                break

        results.sort(key=self._placement_sort_key)
        self._event_decks_cache[cache_key] = list(results)
        return results[:limit]

    def fetch_deck_text(self, deck_url: str) -> str | None:
        payload = self._get_deck_payload(self._extract_deck_id(deck_url))
        if not payload:
            return None
        return self._build_deck_text(payload)

    def hydrate_deck(self, deck: DeckEntry) -> DeckEntry:
        payload = self._get_deck_payload(self._extract_deck_id(deck.source_url))
        if not payload:
            return deck
        return self._apply_payload(deck, payload, include_text=deck.deck_text is None)

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {"source": self.SOURCE, **params}
        response = self._session.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ScrapeError(f"Unexpected TCGPlayer response from {url}.")
        return payload

    def _get_deck_payload(self, deck_id: str) -> dict[str, Any] | None:
        if not deck_id:
            return None
        if deck_id in self._deck_payload_cache:
            return self._deck_payload_cache[deck_id]

        payload = self._get_json(
            self.DECK_URL.format(deck_id=deck_id),
            {"subDecks": True, "cards": True, "stats": True},
        )
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            self._deck_payload_cache[deck_id] = None
            return None

        self._deck_payload_cache[deck_id] = result
        return result

    def _parse_trending_row(self, row: Any) -> DeckEntry | None:
        if not isinstance(row, dict):
            return None
        deck = row.get("deck")
        deck_id = row.get("id")
        if not isinstance(deck, dict) or deck_id is None:
            return None
        deck_name = str(deck.get("name") or "").strip()
        if not deck_name:
            return None

        canonical = str(row.get("canonicalURL") or "").strip()
        if not canonical:
            canonical = self._deck_canonical_url(deck_name, str(deck_id))

        return DeckEntry(
            name=deck_name,
            source_site="tcgplayer.com",
            source_url=urljoin(self.BASE_URL, canonical),
            format_label=self._format_label(str(deck.get("format") or "standard")),
            player_name=self._clean_text(deck.get("playerName")),
            placing=self._clean_text(deck.get("eventRank")),
            event_name=self._clean_text(deck.get("eventName")),
            event_date=self._format_date(str(deck.get("eventDate") or "").strip()),
        )

    def _parse_affiliate_deck_row(self, row: Any) -> DeckEntry | None:
        if not isinstance(row, dict):
            return None
        deck = row.get("deck")
        deck_id = str(row.get("id") or "").strip()
        if not isinstance(deck, dict) or not deck_id:
            return None
        deck_name = str(deck.get("name") or "").strip()
        if not deck_name:
            return None

        canonical = str(row.get("canonicalURL") or "").strip()
        if not canonical:
            canonical = self._deck_canonical_url(deck_name, deck_id)

        created = self._format_date(str(deck.get("created") or "").strip())
        return DeckEntry(
            name=deck_name,
            source_site="tcgplayer.com",
            source_url=urljoin(self.BASE_URL, canonical),
            format_label=self._format_label(str(deck.get("format") or "standard")),
            player_name=self._clean_text(deck.get("playerName")),
            event_date=created,
            notes=f"Created: {created}" if created else None,
        )

    def _parse_latest_row(self, row: Any) -> DeckEntry | None:
        if not isinstance(row, dict):
            return None
        deck_data = row.get("deckData")
        deck_id = str(row.get("deckID") or "").strip()
        if not isinstance(deck_data, dict) or not deck_id:
            return None

        deck_name = str(deck_data.get("deckName") or row.get("title") or "").strip()
        canonical = str(row.get("canonicalURL") or "").strip()
        if not canonical:
            canonical = self._deck_canonical_url(deck_name, deck_id)
        if not deck_name or not canonical:
            return None

        return DeckEntry(
            name=deck_name,
            source_site="tcgplayer.com",
            source_url=urljoin(self.BASE_URL, canonical),
            format_label=self._format_label(str(deck_data.get("format") or "standard")),
            player_name=self._clean_text(deck_data.get("playerName")),
            placing=self._clean_text(deck_data.get("eventRank")),
            event_name=self._clean_text(deck_data.get("eventName")),
            event_date=self._format_date(str(deck_data.get("eventDate") or "").strip()),
        )

    def _parse_event_row(self, row: Any) -> DeckEntry | None:
        if not isinstance(row, dict):
            return None
        title = str(row.get("title") or "").strip()
        canonical = str(row.get("canonicalURL") or "").strip()
        event_date = self._format_date(str(row.get("date") or "").strip())
        if not title or not canonical:
            return None

        notes_parts = []
        players = row.get("eventPlayers")
        if isinstance(players, int) and players > 0:
            notes_parts.append(f"{players} players")
        level = self._clean_text(row.get("eventLevel"))
        if level:
            notes_parts.append(level)

        return DeckEntry(
            name=title,
            source_site="tcgplayer.com",
            source_url=urljoin(self.BASE_URL, canonical),
            format_label="Standard",
            event_date=event_date,
            notes=" | ".join(notes_parts) or None,
        )

    def _hydrate_from_payload(self, deck: DeckEntry) -> DeckEntry:
        payload = self._get_deck_payload(self._extract_deck_id(deck.source_url))
        if not payload:
            return deck
        return self._apply_payload(deck, payload, include_text=False)

    def _apply_payload(
        self,
        deck: DeckEntry,
        payload: dict[str, Any],
        *,
        include_text: bool,
    ) -> DeckEntry:
        deck_meta = payload.get("deck") if isinstance(payload.get("deck"), dict) else {}
        if not isinstance(deck_meta, dict):
            deck_meta = {}

        source_url = deck.source_url
        canonical = str(payload.get("canonicalURL") or "").strip()
        if canonical:
            source_url = urljoin(self.BASE_URL, canonical)

        result = replace(
            deck,
            name=str(deck_meta.get("name") or deck.name).strip() or deck.name,
            source_url=source_url,
            format_label=self._format_label(str(deck_meta.get("format") or deck.format_label)),
            player_name=self._clean_text(deck_meta.get("playerName")) or deck.player_name,
            placing=self._clean_text(deck_meta.get("eventRank")) or deck.placing,
            event_name=self._clean_text(deck_meta.get("eventName")) or deck.event_name,
            event_date=self._format_date(str(deck_meta.get("eventDate") or "").strip()) or deck.event_date,
            notes=deck.notes,
        )
        if include_text:
            deck_text = self._build_deck_text(payload)
            if deck_text:
                result = replace(result, deck_text=deck_text)
        return result

    def _build_deck_text(self, payload: dict[str, Any]) -> str | None:
        deck = payload.get("deck")
        cards = payload.get("cards")
        if not isinstance(deck, dict) or not isinstance(cards, dict):
            return None
        sub_decks = deck.get("subDecks")
        if not isinstance(sub_decks, dict):
            return None

        section_names = {
            "maindeck": "Deck",
            "sideboard": "Sideboard",
            "commander": "Commander",
            "commandzone": "Commander",
            "companion": "Companion",
        }

        parts: list[str] = []
        for section_key in ["maindeck", "sideboard", "commander", "commandzone", "companion"]:
            cards_in_section = sub_decks.get(section_key)
            if not isinstance(cards_in_section, list) or not cards_in_section:
                continue
            lines: list[str] = []
            for row in cards_in_section:
                if not isinstance(row, dict):
                    continue
                quantity = row.get("quantity")
                card_id = str(row.get("cardID") or "").strip()
                if not isinstance(quantity, int) or quantity <= 0 or not card_id:
                    continue
                card_payload = cards.get(card_id)
                if not isinstance(card_payload, dict):
                    continue
                card_name = str(card_payload.get("displayName") or card_payload.get("name") or "").strip()
                if not card_name:
                    continue
                lines.append(f"{quantity} {card_name}")
            if not lines:
                continue
            if parts:
                parts.append("")
            parts.append(section_names.get(section_key, section_key.replace("_", " ").title()))
            parts.extend(lines)

        return "\n".join(parts) if parts else None

    @staticmethod
    def _extract_deck_id(deck_url: str) -> str:
        parts = deck_url.rstrip("/").split("/")
        if not parts:
            return ""
        last = parts[-1]
        return last if last.isdigit() else ""

    @staticmethod
    def _clean_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = " ".join(value.split()).strip()
        return cleaned or None

    @staticmethod
    def _format_label(value: str) -> str:
        cleaned = value.replace("-", " ").replace("_", " ").strip()
        if not cleaned:
            return "Standard"
        return " ".join(part.capitalize() for part in cleaned.split())

    @staticmethod
    def _format_date(value: str) -> str | None:
        if not value:
            return None
        if len(value) >= 10:
            value = value[:10]
        for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                return datetime.strptime(value, fmt).strftime("%m/%d/%Y")
            except ValueError:
                continue
        return None

    @staticmethod
    def _deck_canonical_url(deck_name: str, deck_id: str) -> str:
        slug = "-".join(deck_name.split()) or deck_id
        return f"/magic-the-gathering/deck/{slug}/{deck_id}"

    @staticmethod
    def _join_notes(parts: list[str | None]) -> str | None:
        values = [part.strip() for part in parts if part and part.strip()]
        if not values:
            return None
        return " | ".join(values)

    @staticmethod
    def _placement_sort_key(deck: DeckEntry) -> tuple[int, str]:
        if not deck.placing:
            return (9999, deck.name.lower())
        token = deck.placing.split("-")[0].strip().lower()
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits.isdigit():
            return (int(digits), deck.name.lower())
        return (9999, deck.name.lower())
