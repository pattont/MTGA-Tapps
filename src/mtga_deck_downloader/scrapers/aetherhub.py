from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.scrapers.common import ScrapeError, decode_response_text


class AetherhubScraper:
    BASE_URL = "https://aetherhub.com"
    TOURNAMENT_URL = "https://aetherhub.com/Events/Standard/"
    TOURNAMENT_META_URL = "https://aetherhub.com/Metagame/Standard-Events/"
    BO1_META_URL = "https://aetherhub.com/Metagame/Standard-BO1/"
    BO3_META_URL = "https://aetherhub.com/Metagame/Standard-BO3/"
    USER_DECKS_PATTERN = re.compile(r"^/User/([^/]+)/Decks(?:/[^/]+)?/?$")
    USER_DECK_PAGE_ID_RE = re.compile(r'data-deckid="(\d+)"')
    DATE_TOKEN_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
    DECK_ID_RE = re.compile(r"-(\d+)(?:[/?#]|$)")
    MATCHES_RE = re.compile(r"(\d+)\s+matches", flags=re.IGNORECASE)
    ENGLISH_LANG_ID = 0
    CREATOR_FORMAT_IDS = {
        MatchFormat.BO1: 14,
        MatchFormat.BO3: 1,
    }

    def __init__(self) -> None:
        try:
            import cloudscraper
        except ImportError as exc:
            raise ScrapeError(
                "Aetherhub scraping requires cloudscraper. Install dependencies from requirements.txt."
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
        self._deck_text_cache: dict[str, str | None] = {}
        self._deck_id_cache: dict[str, str] = {}
        self._user_id_cache: dict[str, str] = {}

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source_urls: set[str] | None = None,
    ) -> list[DeckEntry]:
        feeds = self._feeds_for_format(selected_format)
        if source_urls:
            feeds = [feed for feed in feeds if feed[0] in source_urls]
        if not feeds:
            return []

        results: list[DeckEntry] = []
        seen_urls: set[str] = set()
        per_feed_limit = max(1, limit // len(feeds)) if selected_format is MatchFormat.ANY else limit

        for idx, (url, format_label) in enumerate(feeds):
            remaining = limit - len(results)
            if remaining <= 0:
                break

            feed_limit = remaining
            if selected_format is MatchFormat.ANY:
                feed_limit = min(remaining, per_feed_limit)
                # Let the final feed use any remaining slots.
                if idx == len(feeds) - 1:
                    feed_limit = remaining

            if self._is_user_decks_url(url):
                parsed = self.fetch_creator_decks(url, selected_format=selected_format, limit=feed_limit)
            else:
                html = self._get_text(url)
                if url == self.TOURNAMENT_URL:
                    parsed = self._parse_tournament_page(html=html, limit=feed_limit)
                else:
                    parsed = self._parse_meta_page(html=html, format_label=format_label, limit=feed_limit)

            for deck in parsed:
                if deck.source_url in seen_urls:
                    continue
                seen_urls.add(deck.source_url)
                results.append(deck)
                if len(results) >= limit:
                    break

        return results[:limit]

    def _feeds_for_format(self, selected_format: MatchFormat) -> list[tuple[str, str]]:
        if selected_format is MatchFormat.BO1:
            return [
                (self.BO1_META_URL, "Standard / Bo1"),
            ]
        if selected_format is MatchFormat.BO3:
            return [
                (self.TOURNAMENT_URL, "Standard / Bo3"),
                (self.TOURNAMENT_META_URL, "Standard / Bo3"),
                (self.BO3_META_URL, "Standard / Bo3"),
            ]
        return [
            (self.TOURNAMENT_URL, "Standard / Bo3"),
            (self.TOURNAMENT_META_URL, "Standard / Bo3"),
            (self.BO1_META_URL, "Standard / Bo1"),
            (self.BO3_META_URL, "Standard / Bo3"),
        ]

    def fetch_creator_decks(
        self,
        user_url: str,
        selected_format: MatchFormat,
        limit: int = 50,
        creator_label: str | None = None,
    ) -> list[DeckEntry]:
        username = self._extract_username_from_user_url(user_url)
        if not username:
            raise ScrapeError(f"Could not determine Aetherhub username from {user_url}.")
        creator_name = creator_label or username

        user_id = self._fetch_user_id(username)
        if not user_id:
            raise ScrapeError(f"Could not determine Aetherhub user id for {username}.")

        if selected_format is MatchFormat.ANY:
            formats = [MatchFormat.BO1, MatchFormat.BO3]
        else:
            formats = [selected_format]

        results: list[DeckEntry] = []
        any_format_results: list[tuple[float, int, DeckEntry]] = []
        seen_urls: set[str] = set()
        row_order = 0
        for match_format in formats:
            format_id = self.CREATOR_FORMAT_IDS.get(match_format)
            if format_id is None:
                continue
            payload = self._fetch_user_deck_rows(user_id=user_id, format_id=format_id, length=limit)
            for row in payload:
                row_order += 1
                deck = self._parse_user_deck_row(
                    row=row,
                    creator_name=creator_name,
                    selected_format=match_format,
                )
                if deck is None or deck.source_url in seen_urls:
                    continue
                seen_urls.add(deck.source_url)
                if selected_format is MatchFormat.ANY:
                    any_format_results.append(
                        (
                            self._timestamp_millis(row.get("updatedhidden") or row.get("updated")),
                            row_order,
                            deck,
                        )
                    )
                    continue
                results.append(deck)
                if len(results) >= limit:
                    return results[:limit]
        if selected_format is MatchFormat.ANY:
            any_format_results.sort(key=lambda item: (-item[0], item[1]))
            return [deck for _, _, deck in any_format_results[:limit]]
        return results[:limit]

    def _get_text(self, url: str) -> str:
        response = self._session.get(url, timeout=40)
        response.raise_for_status()
        return decode_response_text(response)

    def _parse_tournament_page(self, html: str, limit: int) -> list[DeckEntry]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="metalist")
        if table is None:
            raise ScrapeError("Aetherhub tournament table was not found.")

        results: list[DeckEntry] = []
        event_name: str | None = None
        event_date: str | None = None
        event_note: str | None = None

        for row in table.find_all("tr"):
            if row.find("th"):
                event_name, event_date, event_note = self._parse_tournament_header(row)
                continue

            entry = self._parse_tournament_deck_row(
                row=row,
                event_name=event_name,
                event_date=event_date,
                event_note=event_note,
            )
            if entry is None:
                continue
            results.append(entry)
            if len(results) >= limit:
                break

        return results

    def _parse_tournament_header(self, row: Tag) -> tuple[str | None, str | None, str | None]:
        event_link = row.find("a", href=re.compile(r"^/Events/Standard/"))
        raw_name = ""
        if isinstance(event_link, Tag):
            raw_name = event_link.get_text(" ", strip=True)
        if not raw_name:
            first_cell = row.find("th")
            raw_name = first_cell.get_text(" ", strip=True) if isinstance(first_cell, Tag) else ""

        normalized_name, event_date = self._normalize_event_name(raw_name)
        small = row.find("small")
        note = small.get_text(" ", strip=True) if isinstance(small, Tag) else None
        if note:
            note = " ".join(note.split())

        return normalized_name, event_date, note

    def _parse_tournament_deck_row(
        self,
        row: Tag,
        event_name: str | None,
        event_date: str | None,
        event_note: str | None,
    ) -> DeckEntry | None:
        if "deckdata" not in (row.get("class") or []):
            return None

        relative_url = str(row.get("data-url") or "").strip()
        if not relative_url:
            link = row.find("a", href=re.compile(r"/Metagame/.+/Deck/"))
            if not isinstance(link, Tag):
                return None
            relative_url = str(link.get("href") or "").strip()
        if not relative_url:
            return None

        source_url = urljoin(self.BASE_URL, relative_url)
        deck_name = str(row.get("data-name") or "").strip()
        if not deck_name:
            title_link = row.find("td", class_=re.compile("ae-decktitle"))
            if isinstance(title_link, Tag):
                deck_name = title_link.get_text(" ", strip=True)
        if not deck_name:
            links = row.find_all("a", href=True)
            if len(links) >= 2:
                deck_name = links[1].get_text(" ", strip=True)
        if not deck_name:
            return None

        placement = str(row.get("data-place") or "").strip()
        player = str(row.get("data-player") or "").strip()
        notes = self._join_notes(
            [f"{placement} - {player}" if placement and player else placement or player, event_note]
        )

        return DeckEntry(
            name=deck_name,
            source_site="aetherhub.com",
            source_url=source_url,
            format_label="Standard / Bo3",
            event_name=event_name,
            event_date=event_date,
            deck_text=None,
            notes=notes,
        )

    def _parse_meta_page(self, html: str, format_label: str, limit: int) -> list[DeckEntry]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="metagame-table")
        if table is None:
            raise ScrapeError("Aetherhub metagame table was not found.")

        rows = table.find_all("tr", class_="ae-deck-row")
        results: list[DeckEntry] = []
        for row in rows:
            deck_title_cell = row.find("td", class_=re.compile(r"ae-decktitle"))
            deck_link: Tag | None = None
            if isinstance(deck_title_cell, Tag):
                link = deck_title_cell.find("a", href=re.compile(r"/Metagame/.+/Deck/"))
                if isinstance(link, Tag):
                    deck_link = link
            if deck_link is None:
                link = row.find("a", href=re.compile(r"/Metagame/.+/Deck/"))
                if isinstance(link, Tag):
                    deck_link = link
            if not isinstance(deck_link, Tag):
                continue

            deck_name = deck_link.get_text(" ", strip=True)
            if not deck_name:
                continue
            source_url = urljoin(self.BASE_URL, str(deck_link.get("href") or "").strip())

            matches_text = ""
            matches_cell = row.find("td", class_=re.compile(r"ae-deckmatches"))
            if isinstance(matches_cell, Tag):
                matches_text = matches_cell.get_text(" ", strip=True)
            matches = self._extract_matches(matches_text)

            meta_row = row.find_next_sibling("tr")
            metagame_share = None
            change_note = None
            if isinstance(meta_row, Tag):
                share_span = meta_row.find("span", class_="percent-metagame")
                change_span = meta_row.find("div", class_="diffright")
                if isinstance(share_span, Tag):
                    metagame_share = " ".join(share_span.get_text(" ", strip=True).split())
                if isinstance(change_span, Tag):
                    change_note = " ".join(change_span.get_text(" ", strip=True).split())

            notes = self._join_notes([metagame_share, f"Weekly change: {change_note}" if change_note else None])

            results.append(
                DeckEntry(
                    name=deck_name,
                    source_site="aetherhub.com",
                    source_url=source_url,
                    format_label=format_label,
                    matches=matches,
                    deck_text=None,
                    notes=notes,
                )
            )
            if len(results) >= limit:
                break

        return results

    def fetch_deck_text(self, source_url: str) -> str | None:
        candidate_ids: list[str] = []
        for deck_id in (
            self._extract_deck_id(source_url),
            self._deck_id_cache.get(source_url, ""),
        ):
            if deck_id and deck_id not in candidate_ids:
                candidate_ids.append(deck_id)

        for deck_id in candidate_ids:
            deck_text = self._fetch_mtga_deck_text(deck_id)
            if deck_text:
                return deck_text

        page_deck_id = self._fetch_deck_id_from_page(source_url)
        if page_deck_id and page_deck_id not in candidate_ids:
            return self._fetch_mtga_deck_text(page_deck_id)
        return None

    def _fetch_mtga_deck_text(self, deck_id: str) -> str | None:
        if not deck_id:
            return None
        if deck_id in self._deck_text_cache:
            return self._deck_text_cache[deck_id]
        try:
            response = self._session.get(
                urljoin(self.BASE_URL, "/Deck/FetchMtgaDeckJson"),
                params={"deckId": deck_id, "langId": self.ENGLISH_LANG_ID, "simple": "true"},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self._deck_text_cache[deck_id] = None
            return None

        if not isinstance(payload, dict):
            self._deck_text_cache[deck_id] = None
            return None
        cards = payload.get("convertedDeck")
        if not isinstance(cards, list) or not cards:
            self._deck_text_cache[deck_id] = None
            return None

        lines: list[str] = []
        for row in cards:
            if not isinstance(row, dict):
                continue
            quantity = row.get("quantity")
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            if isinstance(quantity, int):
                line = f"{quantity} {name}"
                set_code = str(row.get("set") or "").strip()
                number = str(row.get("number") or "").strip()
                if set_code and number:
                    line = f"{line} ({set_code}) {number}"
            else:
                line = name
            lines.append(line)
        if not lines:
            self._deck_text_cache[deck_id] = None
            return None
        deck_text = "\n".join(lines)
        self._deck_text_cache[deck_id] = deck_text
        return deck_text

    def _normalize_event_name(self, raw_name: str) -> tuple[str | None, str | None]:
        clean = " ".join(raw_name.split())
        if not clean:
            return None, None
        match = self.DATE_TOKEN_RE.search(clean)
        if not match:
            return clean, None
        us_date = self._to_us_date(match.group(1))
        if not us_date:
            return clean, None
        normalized = f"{clean[:match.start()]}{us_date}{clean[match.end():]}".strip()
        return normalized, us_date

    @staticmethod
    def _to_us_date(token: str) -> str | None:
        parts = token.split("/")
        if len(parts) != 3:
            return None
        day_raw, month_raw, year_raw = parts
        try:
            day = int(day_raw)
            month = int(month_raw)
            year = int(year_raw)
        except ValueError:
            return None
        if year < 100:
            year += 2000
        try:
            parsed = datetime(year=year, month=month, day=day)
        except ValueError:
            return None
        return parsed.strftime("%m/%d/%Y")

    def _extract_deck_id(self, url: str) -> str:
        match = self.DECK_ID_RE.search(url)
        return match.group(1) if match else ""

    def _fetch_user_id(self, username: str) -> str:
        if username in self._user_id_cache:
            return self._user_id_cache[username]
        html = self._get_text(f"{self.BASE_URL}/User/{username}/Decks")
        match = re.search(r'id="metaHubTable"[^>]*data-user-id="(\d+)"', html)
        user_id = match.group(1) if match else ""
        if user_id:
            self._user_id_cache[username] = user_id
        return user_id

    def _fetch_user_deck_rows(self, user_id: str, format_id: int, length: int) -> list[dict[str, object]]:
        response = self._session.post(
            f"{self.BASE_URL}/Meta/FetchMetaListAdv?u={user_id}&formatId={format_id}",
            json=self._datatable_payload(length=length),
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("metadecks") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ScrapeError("Unexpected Aetherhub user deck payload.")
        return [row for row in rows if isinstance(row, dict)]

    def _parse_user_deck_row(
        self,
        row: dict[str, object],
        creator_name: str,
        selected_format: MatchFormat,
    ) -> DeckEntry | None:
        relative_url = str(row.get("url") or "").strip()
        deck_name = str(row.get("name") or "").strip()
        if not relative_url or not deck_name:
            return None

        source_url = urljoin(self.BASE_URL, relative_url)
        deck_id = str(row.get("id") or "").strip()
        if deck_id:
            self._deck_id_cache[source_url] = deck_id

        tags = row.get("tags")
        tag_list = [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
        exports = row.get("exports")
        views = row.get("views")
        note_parts: list[str] = [f"Creator: {creator_name}"]
        if tag_list:
            note_parts.append(f"Tags: {', '.join(tag_list[:3])}")
        if isinstance(exports, int):
            note_parts.append(f"Exports: {exports}")
        if isinstance(views, int):
            note_parts.append(f"Views: {views}")

        updated = self._format_timestamp(row.get("updatedhidden") or row.get("updated"))
        format_label = self._user_format_label(row, selected_format)

        return DeckEntry(
            name=deck_name,
            source_site="aetherhub.com",
            source_url=source_url,
            format_label=format_label,
            event_date=updated,
            notes=" | ".join(note_parts),
        )

    def _fetch_deck_id_from_page(self, source_url: str) -> str:
        if source_url in self._deck_id_cache:
            return self._deck_id_cache[source_url]
        html = self._get_text(source_url)
        match = self.USER_DECK_PAGE_ID_RE.search(html)
        deck_id = match.group(1) if match else ""
        if deck_id:
            self._deck_id_cache[source_url] = deck_id
        return deck_id

    @staticmethod
    def _datatable_payload(length: int) -> dict[str, object]:
        return {
            "draw": 1,
            "columns": [
                {"data": "name", "name": "", "searchable": True, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "color", "name": "", "searchable": True, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "tags", "name": "", "searchable": True, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "likes", "name": "", "searchable": True, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "views", "name": "", "searchable": True, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "exports", "name": "", "searchable": True, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "updated", "name": "", "searchable": True, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "updatedhidden", "name": "", "searchable": False, "orderable": True, "search": {"value": "", "regex": False}},
                {"data": "popularity", "name": "", "searchable": False, "orderable": True, "search": {"value": "", "regex": False}},
            ],
            "order": [{"column": 6, "dir": "desc"}],
            "start": 0,
            "length": max(1, length),
            "search": {"value": "", "regex": False},
        }

    @classmethod
    def _extract_username_from_user_url(cls, user_url: str) -> str:
        path = urlparse(user_url).path
        match = cls.USER_DECKS_PATTERN.match(path)
        return match.group(1) if match else ""

    @staticmethod
    def _is_user_decks_url(url: str) -> bool:
        return "/User/" in url and "/Decks" in url

    @staticmethod
    def _format_timestamp(value: object) -> str | None:
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value) / 1000.0, UTC).strftime("%m/%d/%Y")
            except (ValueError, OSError):
                return None
        return None

    @staticmethod
    def _timestamp_millis(value: object) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _user_format_label(row: dict[str, object], selected_format: MatchFormat) -> str:
        type_url = str(row.get("typeurl") or "").strip()
        type_name = str(row.get("type") or "").strip()
        lowered = " ".join([type_url, type_name]).lower()
        if "standard-bo1" in lowered or "arena standard" in lowered:
            return "Standard / Bo1"
        if "traditional-standard" in lowered or type_name == "Standard":
            return "Standard / Bo3"
        return selected_format.label

    def _extract_matches(self, text: str) -> int | None:
        match = self.MATCHES_RE.search(text or "")
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _join_notes(parts: list[str | None]) -> str | None:
        values = [part.strip() for part in parts if part and part.strip()]
        if not values:
            return None
        return " | ".join(values)
