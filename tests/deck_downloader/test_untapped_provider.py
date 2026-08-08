from __future__ import annotations

import unittest

from mtga_deck_downloader.models import DeckEntry
from mtga_deck_downloader.providers.untapped import UntappedProvider


class UntappedProviderTests(unittest.TestCase):
    def test_display_name_and_source_picker_behavior(self) -> None:
        provider = UntappedProvider.__new__(UntappedProvider)

        self.assertEqual(provider.display_name, "untapped.gg")
        self.assertFalse(provider.uses_source_picker)

    def test_result_views_add_main_helper_and_hide_variant_notes(self) -> None:
        provider = UntappedProvider.__new__(UntappedProvider)
        archetype = DeckEntry(
            name="Izzet Prowess",
            source_site="mtga.untapped.gg",
            source_url="https://mtga.untapped.gg/constructed/standard/archetypes/1/izzet-prowess",
            format_label="Standard / Bo1",
        )

        main_config = provider.result_view_config()
        variant_config = provider.result_view_config(variants=True, parent=archetype)

        self.assertEqual(
            main_config.helper_text,
            "Select deck below to view variants of the deck",
        )
        self.assertIsNone(main_config.show_notes)
        self.assertFalse(variant_config.show_notes)


if __name__ == "__main__":
    unittest.main()
