from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from mtga_deck_downloader.models import DeckEntry
from mtga_deck_downloader.scrapers.common import ScrapeError, decode_response_text


class MoxfieldScraper:
    USER_DECKS_URL = "https://api2.moxfield.com/v2/decks/search"
    DECK_DETAILS_URL = "https://api2.moxfield.com/v2/decks/all/{public_id}"
    ARENA_EXPORT_URL = "https://api2.moxfield.com/v2/decks/all/{public_id}/export/arena"
    DEFAULT_LIMIT = 15
    SPLIT_NAME_RE = re.compile(r"^(.*?)(?:\s+/+\s+.*?)(\s+\([^)]+\)\s+\S+)?$")

    def __init__(self) -> None:
        try:
            import cloudscraper
        except ImportError as exc:
            raise ScrapeError(
                "Moxfield scraping requires cloudscraper. Install dependencies from requirements.txt."
            ) from exc

        self._session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        )
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._deck_cache: dict[str, str | None] = {}

    def fetch_user_decks(self, username: str, limit: int = DEFAULT_LIMIT) -> list[DeckEntry]:
        response = self._session.get(
            self.USER_DECKS_URL,
            params={
                "pageNumber": 1,
                "pageSize": max(1, limit),
                "sortType": "updated",
                "sortDirection": "descending",
                "authorUserNames": username,
                "showIllegal": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ScrapeError(f"Unexpected Moxfield deck payload for {username}.")

        results: list[DeckEntry] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            public_url = str(row.get("publicUrl") or "").strip()
            if not public_url:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            format_label = self._format_label(str(row.get("format") or "").strip())
            updated_at = self._format_date(str(row.get("lastUpdatedAtUtc") or "").strip())
            notes = f"Creator: {username}"
            if updated_at:
                notes = f"{notes} | Updated: {updated_at}"
            results.append(
                DeckEntry(
                    name=name,
                    source_site="moxfield.com",
                    source_url=public_url,
                    format_label=format_label,
                    event_date=updated_at,
                    notes=notes,
                )
            )
        return results

    def fetch_deck_text(self, public_url: str) -> str | None:
        public_id = self._extract_public_id(public_url)
        if not public_id:
            return None
        if public_id in self._deck_cache:
            return self._deck_cache[public_id]

        response = self._session.get(
            self.DECK_DETAILS_URL.format(public_id=public_id),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            self._deck_cache[public_id] = None
            return None

        arena_export = self._fetch_arena_export(public_id, payload)
        if arena_export:
            self._deck_cache[public_id] = arena_export
            return arena_export

        sections = [
            ("Deck", payload.get("mainboard")),
            ("Sideboard", payload.get("sideboard")),
            ("Companion", payload.get("companions")),
            ("Commander", payload.get("commanders")),
            ("Signature Spells", payload.get("signatureSpells")),
            ("Attractions", payload.get("attractions")),
            ("Stickers", payload.get("stickers")),
        ]

        parts: list[str] = []
        for title, board in sections:
            lines = self._board_lines(board)
            if not lines:
                continue
            if parts:
                parts.append("")
            parts.append(title)
            parts.extend(lines)

        deck_text = "\n".join(parts) if parts else None
        self._deck_cache[public_id] = deck_text
        return deck_text

    def _fetch_arena_export(self, public_id: str, payload: dict[str, object]) -> str | None:
        export_id = payload.get("exportId")
        if not isinstance(export_id, str) or not export_id.strip():
            return None

        response = self._session.get(
            self.ARENA_EXPORT_URL.format(public_id=public_id),
            params={
                "arenaOnly": True,
                "format": "mtga",
                "includeTags": False,
                "indicateFoils": False,
                "exportId": export_id,
                "ignoreFlavorNames": False,
            },
            timeout=30,
        )
        response.raise_for_status()
        arena_text = decode_response_text(response).strip()
        return arena_text or None

    @staticmethod
    def _board_lines(board: object) -> list[str]:
        if not isinstance(board, dict):
            return []

        lines: list[str] = []
        for default_name, payload in board.items():
            if not isinstance(payload, dict):
                continue
            quantity = payload.get("quantity")
            if not isinstance(quantity, int) or quantity <= 0:
                continue
            card_info = payload.get("card")
            card_name = default_name
            if isinstance(card_info, dict):
                resolved_name = card_info.get("name")
                if isinstance(resolved_name, str) and resolved_name.strip():
                    card_name = resolved_name.strip()
            card_name = MoxfieldScraper._normalize_card_name(card_name)
            lines.append(f"{quantity} {card_name}")
        return lines

    @classmethod
    def _normalize_card_name(cls, card_name: str) -> str:
        match = cls.SPLIT_NAME_RE.match(card_name.strip())
        if not match:
            return card_name.strip()
        front_face = match.group(1).strip()
        suffix = (match.group(2) or "").strip()
        return f"{front_face} {suffix}".strip()

    @staticmethod
    def _extract_public_id(public_url: str) -> str:
        path = urlparse(public_url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "decks":
            return parts[1]
        return ""

    @staticmethod
    def _format_label(value: str) -> str:
        if not value:
            return "Unknown"
        return " ".join(part.capitalize() for part in value.replace("-", " ").split())

    @staticmethod
    def _format_date(value: str) -> str | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.strftime("%m/%d/%Y")
