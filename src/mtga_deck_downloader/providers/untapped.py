from dataclasses import replace

from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider, ResultViewConfig
from mtga_deck_downloader.scrapers.untapped import UntappedScraper


class UntappedProvider(DeckProvider):
    key = "untapped"
    display_name = "untapped.gg"
    description = "Arena archetypes with win-rate data and variant decklists."
    homepage = "https://mtga.untapped.gg/constructed/standard/meta"

    def __init__(self) -> None:
        self._scraper = UntappedScraper()

    @property
    def sources(self) -> list[DeckSource]:
        return [
            DeckSource(
                name="Standard Meta (Bo1)",
                url="https://mtga.untapped.gg/constructed/standard/meta",
                description="Best of 1 Standard meta with win percentage.",
                formats=(MatchFormat.BO1,),
            ),
            DeckSource(
                name="Standard Meta (Bo3)",
                url="https://mtga.untapped.gg/constructed/standard/meta?wincon=bo3",
                description="Best of 3 Standard meta with win percentage.",
                formats=(MatchFormat.BO3,),
            ),
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
        if source is not None:
            forced_format = MatchFormat.BO3 if "wincon=bo3" in source.url else MatchFormat.BO1
            return self._scraper.fetch_decks(selected_format=forced_format, limit=limit)
        return self._scraper.fetch_decks(selected_format=selected_format, limit=limit)

    def fetch_deck_variants(
        self,
        deck: DeckEntry,
        selected_format: MatchFormat,
        limit: int = 50,
    ) -> list[DeckEntry] | None:
        if "/archetypes/" not in deck.source_url:
            return None
        return self._scraper.fetch_archetype_variants(
            archetype_entry=deck,
            selected_format=selected_format,
            limit=limit,
        )

    def hydrate_deck(self, deck: DeckEntry) -> DeckEntry:
        if deck.source_site != "mtga.untapped.gg" or deck.deck_text:
            return deck
        if "/constructed/standard/decks/" not in deck.source_url:
            return deck
        deck_text = self._scraper.decode_deck_from_url(deck.source_url)
        if deck_text is None:
            return deck
        return replace(deck, deck_text=deck_text)

    def result_view_config(
        self,
        source: DeckSource | None = None,
        *,
        variants: bool = False,
        parent: DeckEntry | None = None,
    ) -> ResultViewConfig:
        if variants and parent is not None:
            return ResultViewConfig(
                title=f"{parent.name} Variants",
                count_label="Deck variants",
                show_notes=False,
            )
        return ResultViewConfig(
            count_label="Archetypes found",
            name_column_label="Archetype",
            selection_label="Archetype",
            selection_action="variants",
            helper_text="Select deck below to view variants of the deck",
        )


PROVIDER_CLASS = UntappedProvider
