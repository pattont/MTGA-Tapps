from __future__ import annotations

from dataclasses import replace

from mtga_deck_downloader.config import MoxfieldCreator, load_config
from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider
from mtga_deck_downloader.scrapers.moxfield import MoxfieldScraper


class MoxfieldProvider(DeckProvider):
    key = "moxfield"
    display_name = "moxfield.com"
    description = "Creator decks from public Moxfield profiles loaded from config.json."
    homepage = "https://moxfield.com/"

    def __init__(self) -> None:
        self._scraper = MoxfieldScraper()

    @property
    def source_picker_title(self) -> str:
        return "Configured Creators"

    @property
    def source_picker_item_label(self) -> str:
        return "creator"

    @property
    def source_picker_all_label(self) -> str:
        return "all configured creators"

    @property
    def change_label(self) -> str:
        return "creator"

    @property
    def sources(self) -> list[DeckSource]:
        config = load_config()
        return [
            DeckSource(
                name=creator.name,
                url=f"https://moxfield.com/users/{creator.name}",
                description="First 15 public decks from this creator's All Decks list.",
                formats=(MatchFormat.ANY,),
            )
            for creator in config.moxfield_creators
        ]

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source: DeckSource | None = None,
    ) -> list[DeckEntry]:
        sources = [source] if source is not None else self.sources
        decks: list[DeckEntry] = []
        for item in sources:
            decks.extend(self._scraper.fetch_user_decks(item.name, limit=min(limit, 15)))
            if len(decks) >= limit:
                break
        return decks[:limit]

    def hydrate_deck(self, deck: DeckEntry) -> DeckEntry:
        if deck.source_site != "moxfield.com" or deck.deck_text:
            return deck
        deck_text = self._scraper.fetch_deck_text(deck.source_url)
        if deck_text is None:
            return deck
        deck_text = self._with_import_deck_name(deck_text, self._import_deck_name(deck))
        return replace(deck, deck_text=deck_text)

    def _import_deck_name(self, deck: DeckEntry) -> str:
        creator_label = self._creator_label_for_deck(deck)
        if not creator_label:
            return deck.name

        suffix = f" ({creator_label})"
        return deck.name if deck.name.endswith(suffix) else f"{deck.name}{suffix}"

    @staticmethod
    def _with_import_deck_name(deck_text: str, import_deck_name: str) -> str:
        if not deck_text.startswith("About\n"):
            return f"About\nName {import_deck_name}\n\n{deck_text}"

        lines = deck_text.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("Name "):
                lines[index] = f"Name {import_deck_name}"
                return "\n".join(lines)
            if index > 0 and not line.strip():
                break

        return f"About\nName {import_deck_name}\n" + "\n".join(lines[1:])

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
            creator.name.lower(): creator for creator in load_config().moxfield_creators
        }
        creator = creator_by_name.get(creator_name.lower(), MoxfieldCreator(name=creator_name))
        return creator.label


PROVIDER_CLASS = MoxfieldProvider
