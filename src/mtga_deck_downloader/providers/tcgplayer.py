from __future__ import annotations

from urllib.parse import quote

from mtga_deck_downloader.config import CreatorConfig, load_config
from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider, ResultViewConfig
from mtga_deck_downloader.scrapers.tcgplayer import TCGPlayerScraper


class TCGPlayerProvider(DeckProvider):
    key = "tcgplayer"
    display_name = "tcgplayer.com"
    description = "Standard trending decks, latest decks, and recent event finishes with MTGA export text."
    homepage = "https://www.tcgplayer.com/content/magic-the-gathering/decks/format/standard"

    def __init__(self) -> None:
        self._scraper = TCGPlayerScraper()

    @property
    def sources(self) -> list[DeckSource]:
        sources = [
            DeckSource(
                name="Trending Decks",
                url="https://www.tcgplayer.com/content/magic-the-gathering/decks/format/standard",
                description="Popular Standard decks on TCGPlayer.",
                formats=(MatchFormat.ANY,),
            ),
            DeckSource(
                name="Latest Decks",
                url="https://www.tcgplayer.com/content/magic-the-gathering/decks/format/standard",
                description="Most recently added Standard decks.",
                formats=(MatchFormat.ANY,),
            ),
            DeckSource(
                name="Events",
                url="https://www.tcgplayer.com/content/magic-the-gathering/decks/format/standard",
                description="Recent Standard events and their top decks.",
                formats=(MatchFormat.ANY,),
            ),
        ]
        for creator in load_config().tcgplayer_creators:
            sources.append(
                DeckSource(
                    name=f"Creator: {creator.name}",
                    url=f"https://www.tcgplayer.com/content/author/{quote(creator.name)}/",
                    description=f"Latest decks from {creator.name}.",
                    formats=(MatchFormat.ANY,),
                )
            )
        return sources

    @property
    def source_picker_title(self) -> str:
        return "TCGPlayer Sections"

    @property
    def source_picker_item_label(self) -> str:
        return "section"

    @property
    def change_label(self) -> str:
        return "section"

    @property
    def allow_all_sources(self) -> bool:
        return False

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source: DeckSource | None = None,
    ) -> list[DeckEntry]:
        chosen = source.name if source is not None else "Latest Decks"
        if chosen == "Trending Decks":
            return self._scraper.fetch_trending_decks(limit=min(limit, 50))
        if chosen == "Events":
            return self._scraper.fetch_events(limit=min(limit, 25))
        if chosen.startswith("Creator: "):
            creator_name = chosen.removeprefix("Creator: ").strip()
            return self._scraper.fetch_creator_decks(creator_name, limit=min(limit, 50))
        return self._scraper.fetch_latest_decks(limit=min(limit, 50))

    def fetch_deck_variants(
        self,
        deck: DeckEntry,
        selected_format: MatchFormat,
        limit: int = 50,
    ) -> list[DeckEntry] | None:
        if deck.source_site != "tcgplayer.com" or deck.event_date is None:
            return None
        if "/decks/event/" not in deck.source_url:
            return None
        return self._scraper.fetch_event_decks(deck, limit=min(limit, 32))

    def hydrate_deck(self, deck: DeckEntry) -> DeckEntry:
        if deck.source_site != "tcgplayer.com" or deck.deck_text:
            return deck
        if "/deck/" not in deck.source_url:
            return deck
        hydrated = self._scraper.hydrate_deck(deck)
        if not hydrated.deck_text:
            return hydrated
        return DeckEntry(
            name=hydrated.name,
            source_site=hydrated.source_site,
            source_url=hydrated.source_url,
            format_label=hydrated.format_label,
            matches=hydrated.matches,
            win_rate=hydrated.win_rate,
            player_name=hydrated.player_name,
            placing=hydrated.placing,
            event_name=hydrated.event_name,
            event_date=hydrated.event_date,
            deck_text=f"About\nName {self._import_deck_name(hydrated)}\n\n{hydrated.deck_text}",
            notes=hydrated.notes,
        )

    def _import_deck_name(self, deck: DeckEntry) -> str:
        creator_label = self._creator_label_for_deck(deck)
        if not creator_label:
            return deck.name

        suffix = f" ({creator_label})"
        return deck.name if deck.name.endswith(suffix) else f"{deck.name}{suffix}"

    @staticmethod
    def _creator_label_for_deck(deck: DeckEntry) -> str | None:
        if not deck.notes:
            return None
        creator_prefix = "Creator: "
        creator_name = ""
        for part in deck.notes.split("|"):
            stripped = part.strip()
            if stripped.startswith(creator_prefix):
                creator_name = stripped.removeprefix(creator_prefix).strip()
                break
        if not creator_name:
            return None

        creator_by_name = {
            creator.name.lower(): creator for creator in load_config().tcgplayer_creators
        }
        creator = creator_by_name.get(creator_name.lower(), CreatorConfig(name=creator_name))
        return creator.label

    def result_view_config(
        self,
        source: DeckSource | None = None,
        *,
        variants: bool = False,
        parent: DeckEntry | None = None,
    ) -> ResultViewConfig:
        if variants and parent is not None:
            return ResultViewConfig(
                title=f"{parent.name} Top Decks",
                count_label="Top decks",
                selection_label="Deck",
                selection_action="details",
            )
        if source is not None and source.name == "Events":
            return ResultViewConfig(
                title="Recent Events",
                count_label="Events found",
                name_column_label="Event",
                selection_label="Event",
                selection_action="top decks",
            )
        if source is not None and source.name == "Trending Decks":
            return ResultViewConfig(title="Trending Decks")
        if source is not None and source.name == "Latest Decks":
            return ResultViewConfig(title="Latest Decks")
        if source is not None and source.name.startswith("Creator: "):
            return ResultViewConfig(title=source.name.removeprefix("Creator: ").strip())
        return ResultViewConfig()


PROVIDER_CLASS = TCGPlayerProvider
