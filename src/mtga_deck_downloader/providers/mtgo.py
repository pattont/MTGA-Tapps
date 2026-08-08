from __future__ import annotations

from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider, ResultViewConfig
from mtga_deck_downloader.scrapers.mtgo import MTGOScraper


class MTGOProvider(DeckProvider):
    key = "mtgo"
    display_name = "mtgo.com"
    description = "Recent official Standard events and their published player decklists."
    homepage = "https://www.mtgo.com/decklists"

    def __init__(self) -> None:
        self._scraper = MTGOScraper()

    @property
    def sources(self) -> list[DeckSource]:
        return [
            DeckSource(
                name="Standard Events",
                url=self.homepage,
                description="Official MTGO Standard leagues and tournaments.",
                formats=(MatchFormat.BO3,),
            )
        ]

    @property
    def uses_source_picker(self) -> bool:
        return False

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source: DeckSource | None = None,
    ) -> list[DeckEntry]:
        if selected_format is MatchFormat.BO1:
            return []
        return self._scraper.fetch_published_events(limit=min(limit, 3))

    def fetch_deck_variants(
        self,
        deck: DeckEntry,
        selected_format: MatchFormat,
        limit: int = 50,
    ) -> list[DeckEntry] | None:
        if deck.source_site != "mtgo.com" or "/decklist/" not in deck.source_url:
            return None
        if deck.deck_text:
            return None
        return self._scraper.fetch_event_decks(deck, limit=min(limit, 50))

    def result_view_config(
        self,
        source: DeckSource | None = None,
        *,
        variants: bool = False,
        parent: DeckEntry | None = None,
    ) -> ResultViewConfig:
        if variants and parent is not None:
            return ResultViewConfig(
                title=f"{parent.name} Decklists",
                count_label="Decks found",
                selection_label="Deck",
                selection_action="details",
                show_notes=False,
            )
        return ResultViewConfig(
            title="Recent MTGO Standard Events",
            count_label="Events found",
            name_column_label="Event",
            selection_label="Event",
            selection_action="decklists",
            show_notes=False,
        )


PROVIDER_CLASS = MTGOProvider
