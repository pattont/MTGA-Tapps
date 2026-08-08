from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider
from mtga_deck_downloader.scrapers.magic_gg import MagicGGScraper


class MagicGGProvider(DeckProvider):
    key = "magic_gg"
    display_name = "magic.gg"
    description = "Decklists from premier events and pro-level tournaments."
    homepage = "https://magic.gg/decklists"

    def __init__(self) -> None:
        self._scraper = MagicGGScraper()

    @property
    def sources(self) -> list[DeckSource]:
        return [
            DeckSource(
                name="Event Decklists",
                url="https://magic.gg/decklists",
                description="Official decklists with event results and standings.",
                formats=(MatchFormat.BO1, MatchFormat.BO3),
            )
        ]

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source: DeckSource | None = None,
    ) -> list[DeckEntry]:
        if source is not None and source.url != "https://magic.gg/decklists":
            return []
        return self._scraper.fetch_decks(selected_format=selected_format, limit=limit)


PROVIDER_CLASS = MagicGGProvider
