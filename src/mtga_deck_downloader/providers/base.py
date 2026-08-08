from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat


@dataclass(frozen=True)
class ResultViewConfig:
    title: str = "Scraped Deck Results"
    count_label: str = "Decks found"
    name_column_label: str = "Deck"
    selection_label: str = "Deck"
    selection_action: str = "details"
    helper_text: str | None = None
    show_notes: bool | None = None


class DeckProvider(ABC):
    key: str
    display_name: str
    description: str
    homepage: str

    def list_sources(self, selected_format: MatchFormat) -> list[DeckSource]:
        return [source for source in self.sources if source.supports(selected_format)]

    @property
    def sources(self) -> list[DeckSource]:
        raise NotImplementedError("Providers must expose sources.")

    @property
    def supported_formats(self) -> set[MatchFormat]:
        formats: set[MatchFormat] = set()
        for source in self.sources:
            formats.update(source.formats)
        return formats

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source: DeckSource | None = None,
    ) -> list[DeckEntry]:
        raise NotImplementedError("Providers must implement deck fetching.")

    def fetch_deck_variants(
        self,
        deck: DeckEntry,
        selected_format: MatchFormat,
        limit: int = 50,
    ) -> list[DeckEntry] | None:
        return None

    def hydrate_deck(self, deck: DeckEntry) -> DeckEntry:
        return deck

    @property
    def source_picker_title(self) -> str:
        return "Deck Source Endpoints"

    @property
    def source_picker_item_label(self) -> str:
        return "endpoint"

    @property
    def source_picker_all_label(self) -> str:
        return "all matching endpoints"

    @property
    def change_label(self) -> str:
        return "format"

    @property
    def allow_all_sources(self) -> bool:
        return True

    @property
    def uses_source_picker(self) -> bool:
        return True

    @property
    def format_screen_sources(self) -> list[DeckSource]:
        return []

    def result_view_config(
        self,
        source: DeckSource | None = None,
        *,
        variants: bool = False,
        parent: DeckEntry | None = None,
    ) -> ResultViewConfig:
        return ResultViewConfig()
