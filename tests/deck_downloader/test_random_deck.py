from __future__ import annotations

import unittest

from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider
from mtga_deck_downloader.ui import _select_random_deck


class FakeRandom:
    def sample(self, items: list[DeckProvider], count: int) -> list[DeckProvider]:
        return list(items[:count])

    def choice(self, items: list[DeckEntry]) -> DeckEntry:
        return items[-1]


class FakeProvider(DeckProvider):
    key = "fake"
    display_name = "fake.test"
    description = "Fake provider"
    homepage = "https://example.test"

    def __init__(
        self,
        decks: list[DeckEntry] | Exception,
        variants: list[DeckEntry] | Exception | None = None,
    ) -> None:
        self._decks = decks
        self._variants = variants
        self.fetch_calls: list[tuple[MatchFormat, int, object]] = []
        self.variant_calls: list[tuple[DeckEntry, MatchFormat, int]] = []

    @property
    def sources(self) -> list[object]:
        return []

    def fetch_decks(
        self,
        selected_format: MatchFormat,
        limit: int = 50,
        source: object | None = None,
    ) -> list[DeckEntry]:
        self.fetch_calls.append((selected_format, limit, source))
        if isinstance(self._decks, Exception):
            raise self._decks
        return self._decks

    def fetch_deck_variants(
        self,
        deck: DeckEntry,
        selected_format: MatchFormat,
        limit: int = 50,
    ) -> list[DeckEntry] | None:
        self.variant_calls.append((deck, selected_format, limit))
        if isinstance(self._variants, Exception):
            raise self._variants
        return self._variants


def deck(name: str) -> DeckEntry:
    return DeckEntry(
        name=name,
        source_site="fake.test",
        source_url=f"https://example.test/{name}",
        format_label="Standard",
    )


class RandomDeckTests(unittest.TestCase):
    def test_select_random_deck_skips_failed_providers_and_resolves_variants(self) -> None:
        broken = FakeProvider(RuntimeError("offline"))
        empty = FakeProvider([])
        selected = FakeProvider([deck("archetype")], variants=[deck("variant 1"), deck("variant 2")])

        result = _select_random_deck([broken, empty, selected], rng=FakeRandom())

        self.assertIsNotNone(result)
        provider, random_deck = result
        self.assertIs(provider, selected)
        self.assertEqual(random_deck.name, "variant 2")
        self.assertEqual(selected.fetch_calls, [(MatchFormat.ANY, 50, None)])
        self.assertEqual(selected.variant_calls[0][1:], (MatchFormat.ANY, 50))

    def test_select_random_deck_returns_none_when_no_provider_has_decks(self) -> None:
        result = _select_random_deck(
            [FakeProvider(RuntimeError("offline")), FakeProvider([])],
            rng=FakeRandom(),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
