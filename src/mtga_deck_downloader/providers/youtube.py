from __future__ import annotations

import random

from mtga_deck_downloader.config import load_config
from mtga_deck_downloader.models import DeckEntry, DeckFetchResult, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider, ResultViewConfig


class YouTubeProvider(DeckProvider):
    key = "youtube"
    display_name = "youtube.com"
    description = "Creators"
    homepage = "https://www.youtube.com/"

    _scraper_path = "mtga_deck_downloader.scrapers.youtube.YouTubeScraper"

    @property
    def source_picker_title(self) -> str:
        return "Creators"

    @property
    def source_picker_item_label(self) -> str:
        return "creator"

    @property
    def change_label(self) -> str:
        return "creator"

    @property
    def allow_all_sources(self) -> bool:
        return False

    @property
    def supported_formats(self) -> set[MatchFormat]:
        return {MatchFormat.ANY}

    @property
    def sources(self) -> list[DeckSource]:
        return [
            DeckSource(
                name=creator.name,
                url=creator.channel,
                description="Decklists from the latest 15 video descriptions.",
                formats=(MatchFormat.ANY,),
            )
            for creator in load_config().youtube_creators
        ]

    def fetch_decks(
        self, selected_format: MatchFormat, limit: int = 50, source: DeckSource | None = None
    ) -> list[DeckEntry]:
        creators = load_config().youtube_creators
        if selected_format is not MatchFormat.ANY or not creators:
            return DeckFetchResult()
        # No all-creators scrape: source-less calls (Surprise) choose just one.
        creator = next((item for item in creators if source and item.channel == source.url), None)
        if source and creator is None:
            raise ValueError("This YouTube creator is no longer configured.")
        return self._scraper.fetch_creator_decks(
            creator or random.choice(creators), limit=min(limit, 15)
        )

    def result_view_config(self, source=None, *, variants=False, parent=None) -> ResultViewConfig:
        return ResultViewConfig(
            title="Creator Decks",
            show_notes=False,
            helper_text="Decklists from the latest 15 video descriptions. Videos without a complete list are skipped.",
        )


PROVIDER_CLASS = YouTubeProvider
