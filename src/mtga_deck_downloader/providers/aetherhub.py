from dataclasses import replace

from mtga_deck_downloader.config import CreatorConfig, load_config
from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider
from mtga_deck_downloader.scrapers.aetherhub import AetherhubScraper


class AetherhubProvider(DeckProvider):
    key = "aetherhub"
    display_name = "aetherhub.com"
    description = "Tournament and MTGA metagame decks with direct MTGA export text."
    homepage = "https://aetherhub.com/Metagame/Standard-Events/"

    def __init__(self) -> None:
        self._scraper = AetherhubScraper()

    def list_sources(self, selected_format: MatchFormat) -> list[DeckSource]:
        return [
            source
            for source in self.sources
            if source.supports(selected_format) and not self._is_creator_source(source)
        ]

    @property
    def format_screen_sources(self) -> list[DeckSource]:
        return [source for source in self.sources if self._is_creator_source(source)]

    @property
    def sources(self) -> list[DeckSource]:
        sources = [
            DeckSource(
                name="Tournament",
                url="https://aetherhub.com/Events/Standard/",
                description="Latest Standard tournament deck placements.",
                formats=(MatchFormat.BO3,),
            ),
            DeckSource(
                name="Tournament Meta",
                url="https://aetherhub.com/Metagame/Standard-Events/",
                description="Top-performing Standard tournament archetypes.",
                formats=(MatchFormat.BO3,),
            ),
            DeckSource(
                name="MTGA BO1 Meta",
                url="https://aetherhub.com/Metagame/Standard-BO1/",
                description="Arena Standard Best-of-1 metagame.",
                formats=(MatchFormat.BO1,),
            ),
            DeckSource(
                name="MTGA BO3 Meta",
                url="https://aetherhub.com/Metagame/Standard-BO3/",
                description="Arena Standard Best-of-3 metagame.",
                formats=(MatchFormat.BO3,),
            ),
        ]
        for creator in load_config().aetherhub_creators:
            sources.append(
                DeckSource(
                    name=f"Creator: {creator.name}",
                    url=f"https://aetherhub.com/User/{creator.name}/Decks",
                    description=f"Latest creator decks from {creator.name}.",
                    formats=(MatchFormat.BO1, MatchFormat.BO3),
                )
            )
        return sources

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source: DeckSource | None = None,
    ) -> list[DeckEntry]:
        if source is not None and "/User/" in source.url and "/Decks" in source.url:
            return self._scraper.fetch_creator_decks(
                source.url,
                selected_format=selected_format,
                limit=limit,
                creator_label=source.name.removeprefix("Creator:").strip(),
            )

        if source is None:
            source_urls = {source.url for source in self.list_sources(selected_format)}
            return self._scraper.fetch_decks(
                selected_format=selected_format,
                limit=limit,
                source_urls=source_urls,
            )

        source_urls = {source.url} if source is not None else None
        return self._scraper.fetch_decks(
            selected_format=selected_format,
            limit=limit,
            source_urls=source_urls,
        )

    def hydrate_deck(self, deck: DeckEntry) -> DeckEntry:
        if deck.source_site != "aetherhub.com" or deck.deck_text:
            return deck
        deck_text = self._scraper.fetch_deck_text(deck.source_url)
        if deck_text is None:
            return deck
        creator_name = self._creator_name_from_notes(deck.notes)
        if creator_name:
            creator_label = self._creator_label(creator_name)
            deck_text = f"About\nName {deck.name} ({creator_label})\n\n{deck_text}"
        return replace(deck, deck_text=deck_text)

    @staticmethod
    def _creator_label(creator_name: str) -> str:
        creator_by_name = {
            creator.name.lower(): creator for creator in load_config().aetherhub_creators
        }
        creator = creator_by_name.get(creator_name.lower(), CreatorConfig(name=creator_name))
        return creator.label

    @staticmethod
    def _creator_name_from_notes(notes: str | None) -> str | None:
        if not notes:
            return None
        for part in notes.split("|"):
            cleaned = part.strip()
            if cleaned.startswith("Creator:"):
                name = cleaned.removeprefix("Creator:").strip()
                return name or None
        return None

    @staticmethod
    def _is_creator_source(source: DeckSource) -> bool:
        return source.name.startswith("Creator: ")


PROVIDER_CLASS = AetherhubProvider
