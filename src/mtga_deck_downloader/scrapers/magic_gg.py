from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.scrapers.common import ScrapeError, create_session, decode_response_text


class MagicGGScraper:
    BASE_URL = "https://magic.gg"
    INDEX_URL = "https://magic.gg/decklists"
    MAX_ARTICLES_TO_SCAN = 60
    MAX_DECKS_PER_ARTICLE = 12
    GENERIC_DECK_TITLES = {
        "platinum-mythic rank player",
        "diamond-mastery rank player",
        "gold-platinum rank player",
        "top player",
    }
    BASIC_LANDS = {"plains", "island", "swamp", "mountain", "forest"}
    LIKELY_LAND_MARKERS = (
        "verge",
        "fountain",
        "vents",
        "foundry",
        "monastery",
        "parlor",
        "bivouac",
        "cavern",
        "passage",
        "valley",
        "sanctum",
        "catacombs",
        "harbor",
        "citadel",
        "manor",
        "estate",
        "restless",
        "castle",
        "wilds",
        "temple",
        "tunnel",
        "grove",
        "campus",
        "bridge",
        "den",
        "lair",
        "grotto",
        "tower",
        "mire",
        "marsh",
        "thicket",
        "coast",
    )

    def __init__(self) -> None:
        self._session = create_session()
        self._results_cache: dict[tuple[str, int], list[DeckEntry]] = {}

    def fetch_decks(self, selected_format: MatchFormat, limit: int = 50) -> list[DeckEntry]:
        cache_key = (selected_format.value, limit)
        if cache_key in self._results_cache:
            return list(self._results_cache[cache_key])

        index_html = self._get_text(self.INDEX_URL)
        article_urls = self._extract_article_urls(index_html)
        if not article_urls:
            raise ScrapeError("No article links were discovered on magic.gg/decklists.")

        decks: list[DeckEntry] = []
        for article_url in article_urls[: self.MAX_ARTICLES_TO_SCAN]:
            hinted = self._hint_format_from_article_url(article_url)
            if selected_format is not MatchFormat.ANY and hinted is not None and hinted is not selected_format:
                continue
            article_html = self._get_text(article_url)
            article_decks = self._extract_article_decks(
                article_html=article_html,
                article_url=article_url,
                selected_format=selected_format,
            )
            decks.extend(article_decks[: self.MAX_DECKS_PER_ARTICLE])
            if len(decks) >= limit:
                break

        final = decks[:limit]
        self._results_cache[cache_key] = list(final)
        return final

    def _get_text(self, url: str) -> str:
        response = self._session.get(url, timeout=20)
        response.raise_for_status()
        return decode_response_text(response)

    def _extract_article_urls(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href")
            if not href:
                continue
            full_url = urljoin(self.BASE_URL, href)
            parsed = urlparse(full_url)
            if parsed.netloc not in {"magic.gg", "www.magic.gg"}:
                continue
            if not parsed.path.startswith("/decklists/") or parsed.path == "/decklists/":
                continue
            full_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if full_url in seen:
                continue
            seen.add(full_url)
            urls.append(full_url)
        return urls

    def _extract_article_decks(
        self,
        article_html: str,
        article_url: str,
        selected_format: MatchFormat,
    ) -> list[DeckEntry]:
        article_title = self._extract_article_title(article_html)
        decoded = self._decode_embedded_markup(article_html)
        raw_decklists = re.findall(
            r"<deck-list\b.*?</deck-list>", decoded, flags=re.IGNORECASE | re.DOTALL
        )

        results: list[DeckEntry] = []
        for index, raw_deck in enumerate(raw_decklists, start=1):
            deck_soup = BeautifulSoup(raw_deck, "html.parser")
            deck_tag = deck_soup.find("deck-list")
            if deck_tag is None:
                continue

            event_name = (deck_tag.get("event-name") or "").strip()
            detected_format = self._detect_format(
                event_name=event_name,
                article_title=article_title,
                article_url=article_url,
            )
            if selected_format is not MatchFormat.ANY and detected_format is not selected_format:
                continue

            deck_title = (deck_tag.get("deck-title") or "").strip()
            subtitle = (deck_tag.get("subtitle") or "").strip()
            event_date = (deck_tag.get("event-date") or "").strip()
            game_format = (deck_tag.get("format") or "").strip()
            main_lines = self._get_section_lines(deck_tag, "main-deck")

            name = self._compose_deck_name(
                deck_title=deck_title,
                subtitle=subtitle,
                article_title=article_title,
                index=index,
                main_lines=main_lines,
            )

            if not main_lines:
                continue
            side_lines = self._get_section_lines(deck_tag, "side-board")
            companion_lines = self._get_section_lines(deck_tag, "companion-card")
            deck_text = self._build_arena_text(main_lines, side_lines, companion_lines)

            format_label = self._format_label(
                game_format=game_format,
                detected_format=detected_format,
                event_name=event_name,
            )

            results.append(
                DeckEntry(
                    name=name,
                    source_site="magic.gg",
                    source_url=article_url,
                    format_label=format_label,
                    event_name=article_title,
                    event_date=event_date or None,
                    deck_text=deck_text,
                    notes=event_name if event_name and event_name != article_title else None,
                )
            )
        return results

    @staticmethod
    def _extract_article_title(article_html: str) -> str:
        soup = BeautifulSoup(article_html, "html.parser")
        title = soup.find("title")
        if not title:
            return "Magic.gg Decklist"
        text = title.get_text(strip=True)
        return text if text else "Magic.gg Decklist"

    @staticmethod
    def _format_label(
        game_format: str,
        detected_format: MatchFormat,
        event_name: str,
    ) -> str:
        normalized_format = " ".join((game_format or "").split())
        lowered = " ".join([normalized_format, event_name]).lower()
        if normalized_format.lower() == "standard":
            if "traditional" in lowered or detected_format is MatchFormat.BO3:
                return "Standard (Bo3)"
            if detected_format is MatchFormat.BO1:
                return "Standard (Bo1)"
        return normalized_format if normalized_format else detected_format.label

    def _compose_deck_name(
        self,
        deck_title: str,
        subtitle: str,
        article_title: str,
        index: int,
        main_lines: list[str],
    ) -> str:
        normalized_title = deck_title.lower().strip()
        if not deck_title or normalized_title in self.GENERIC_DECK_TITLES:
            signature = self._build_card_signature(main_lines)
            if signature:
                name = f"{signature} (Deck {index})"
            else:
                name = f"{article_title} Deck {index}"
        else:
            name = deck_title
        if subtitle:
            name = f"{name} - {subtitle}"
        return name

    def _build_card_signature(self, main_lines: list[str]) -> str:
        picked: list[str] = []
        for idx, line in enumerate(main_lines):
            # Most decklists list lands first; skip early lines to find archetype cards.
            if idx < 8:
                continue
            match = re.match(r"^\s*(\d+)\s+(.+?)\s*$", line)
            if not match:
                continue
            quantity = int(match.group(1))
            card_name = match.group(2).strip()
            if quantity < 3:
                continue
            lowered = card_name.lower()
            if lowered in self.BASIC_LANDS:
                continue
            if any(marker in lowered for marker in self.LIKELY_LAND_MARKERS):
                continue
            picked.append(card_name)
            if len(picked) == 2:
                break

        if not picked:
            return ""
        return " + ".join(picked)

    @staticmethod
    def _decode_embedded_markup(article_html: str) -> str:
        decoded = article_html
        replacements = {
            r"\u003C": "<",
            r"\u003E": ">",
            r"\u002F": "/",
            r"\u0026": "&",
            r"\n": "\n",
            r"\"": '"',
        }
        for old, new in replacements.items():
            decoded = decoded.replace(old, new)
        return unescape(decoded)

    @staticmethod
    def _detect_format(event_name: str, article_title: str = "", article_url: str = "") -> MatchFormat:
        lowered = " ".join([event_name, article_title, article_url]).lower()
        if "bo3" in lowered or "best of 3" in lowered or "traditional" in lowered:
            return MatchFormat.BO3
        if "bo1" in lowered or "best of 1" in lowered:
            return MatchFormat.BO1
        if "ranked decklists" in lowered and "traditional" not in lowered:
            return MatchFormat.BO1
        if any(
            keyword in lowered
            for keyword in (
                "pro tour",
                "regional championship",
                "championship",
                "magic series",
                "top ",
                "spotlight",
            )
        ):
            return MatchFormat.BO3
        return MatchFormat.ANY

    @staticmethod
    def _hint_format_from_article_url(article_url: str) -> MatchFormat | None:
        lowered = (article_url or "").lower()
        if not lowered:
            return None
        if "traditional" in lowered or "best-of-3" in lowered or "bo3" in lowered:
            return MatchFormat.BO3
        if "bo1" in lowered or "best-of-1" in lowered:
            return MatchFormat.BO1
        if "standard-ranked-decklists" in lowered and "traditional" not in lowered:
            return MatchFormat.BO1
        if any(
            token in lowered
            for token in (
                "pro-tour",
                "regional-championship",
                "championship",
                "spotlight",
                "top-",
            )
        ):
            return MatchFormat.BO3
        return None

    @staticmethod
    def _get_section_lines(deck_tag: BeautifulSoup, section_name: str) -> list[str]:
        section = deck_tag.find(section_name)
        if section is None:
            return []
        lines = [line.strip() for line in section.get_text("\n").splitlines()]
        return [line for line in lines if line]

    @staticmethod
    def _build_arena_text(
        main_lines: list[str],
        side_lines: list[str],
        companion_lines: list[str],
    ) -> str:
        parts = ["Deck", *main_lines]
        if side_lines:
            parts.extend(["", "Sideboard", *side_lines])
        if companion_lines:
            parts.extend(["", "Companion", *companion_lines])
        return "\n".join(parts)
