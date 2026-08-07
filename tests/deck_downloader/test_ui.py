from __future__ import annotations

import io
import unittest

from rich.console import Console

import mtga_deck_downloader.ui as ui_module
from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.ui import (
    _date_column_label,
    _notes_column_label,
    _pick_format,
    _pick_provider,
    _show_player_column,
    _show_notes_column,
    _show_posted_date_column,
    _source_context_label,
    _split_creator_sources,
    _table_note,
)


class FakeConsole:
    is_terminal = False

    def clear(self) -> None:
        return None

    def print(self, *args: object, **kwargs: object) -> None:
        return None


class UISourceTests(unittest.TestCase):
    def test_top_level_menu_has_quit_default(self) -> None:
        class FakeProvider:
            display_name = "Example"
            description = "Example decks"

        calls: list[dict[str, object]] = []
        original_ask = ui_module.Prompt.ask

        def fake_ask(prompt: str, **kwargs: object) -> str:
            calls.append(kwargs)
            return str(kwargs["default"])

        ui_module.Prompt.ask = fake_ask
        try:
            selected = _pick_provider(FakeConsole(), [FakeProvider()])
        finally:
            ui_module.Prompt.ask = original_ask

        self.assertIsNone(selected)
        self.assertEqual(calls[0]["default"], "q")
        self.assertFalse(calls[0]["show_choices"])

    def test_top_level_menu_has_compact_header_and_spaced_site_rows(self) -> None:
        class FakeProvider:
            display_name = "Example"
            description = "Example decks"

        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=100)
        original_ask = ui_module.Prompt.ask

        def fake_ask(prompt: str, **kwargs: object) -> str:
            return "q"

        ui_module.Prompt.ask = fake_ask
        try:
            _pick_provider(console, [FakeProvider()])
        finally:
            ui_module.Prompt.ask = original_ask

        rendered = output.getvalue()
        lines = rendered.splitlines()
        table_header_index = next(
            index
            for index, line in enumerate(lines)
            if "Site" in line and "Description" in line
        )
        site_row_index = next(
            index for index, line in enumerate(lines) if "Example decks" in line
        )

        self.assertIn("Magic: The Gathering Arena", rendered)
        self.assertIn("DECK FINDER & DOWNLOADER", rendered)
        self.assertIn("Example", rendered)
        self.assertTrue(lines[table_header_index - 1].startswith("┏"))
        self.assertTrue(lines[table_header_index + 1].startswith("┡"))
        self.assertNotIn("Example", lines[site_row_index - 1])
        self.assertNotIn("Example", lines[site_row_index + 1])

    def test_wide_top_level_menu_uses_ascii_logo(self) -> None:
        class FakeProvider:
            display_name = "Example"
            description = "Example decks"

        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=140)
        original_ask = ui_module.Prompt.ask

        def fake_ask(prompt: str, **kwargs: object) -> str:
            return "q"

        ui_module.Prompt.ask = fake_ask
        try:
            _pick_provider(console, [FakeProvider()])
        finally:
            ui_module.Prompt.ask = original_ask

        rendered = output.getvalue()
        self.assertIn("|  \\/  |__ _ __", rendered)
        self.assertIn("DECK FINDER & DOWNLOADER", rendered)

    def test_logo_selection_uses_responsive_width_boundaries(self) -> None:
        cases = (
            (119, True, False, False),
            (120, False, True, False),
            (197, False, True, False),
            (198, False, False, True),
            (200, False, False, True),
        )

        for width, has_plain, has_compact, has_colossal in cases:
            with self.subTest(width=width):
                output = io.StringIO()
                console = Console(file=output, force_terminal=False, width=width)

                ui_module._render_site_header(console)

                rendered = output.getvalue()
                self.assertEqual("Magic: The Gathering Arena" in rendered, has_plain)
                self.assertEqual("|  \\/  |__ _ __" in rendered, has_compact)
                self.assertEqual("888b     d888" in rendered, has_colossal)

    def test_compact_logo_has_distinct_colon_and_arena_spacing(self) -> None:
        lines = ui_module.MTGA_COMPACT_LOGO.splitlines()
        colon_column = ui_module._COMPACT_MAGIC_WIDTH
        arena_column = (
            colon_column
            + 1
            + 2
            + ui_module._COMPACT_THE_GATHERING_WIDTH
            + 3
        )

        self.assertEqual(
            [line[colon_column] for line in lines],
            [" ", ":", " ", ":", " "],
        )
        for line, arena_line in zip(lines, ui_module._COMPACT_ARENA):
            self.assertEqual(line[arena_column:].rstrip(), arena_line)

    def test_embedded_logos_fit_inside_their_minimum_widths(self) -> None:
        panel_overhead = 8

        self.assertLessEqual(
            max(len(line) for line in ui_module.MTGA_COMPACT_LOGO.splitlines()),
            ui_module.COMPACT_LOGO_MIN_WIDTH - panel_overhead,
        )
        self.assertLessEqual(
            max(len(line) for line in ui_module.MTGA_COLOSSAL_LOGO.splitlines()),
            ui_module.COLOSSAL_LOGO_MIN_WIDTH - panel_overhead,
        )

    def test_deck_pages_have_at_most_twenty_rows(self) -> None:
        decks = [
            DeckEntry(
                name=f"Deck {index}",
                source_site="example.test",
                source_url=f"https://example.test/{index}",
                format_label="Standard",
            )
            for index in range(1, 51)
        ]

        first, first_page, first_start, page_count = ui_module._deck_page(decks, 0)
        second, second_page, second_start, _ = ui_module._deck_page(decks, 1)
        third, third_page, third_start, _ = ui_module._deck_page(decks, 2)

        self.assertEqual([len(first), len(second), len(third)], [20, 20, 10])
        self.assertEqual([first_page, second_page, third_page], [0, 1, 2])
        self.assertEqual([first_start, second_start, third_start], [1, 21, 41])
        self.assertEqual(page_count, 3)

    def test_deck_browser_navigates_between_twenty_row_pages(self) -> None:
        class FakeProvider:
            change_label = "format"

            def result_view_config(self, *args: object, **kwargs: object) -> object:
                return ui_module.ResultViewConfig()

        decks = [
            DeckEntry(
                name=f"Deck {index}",
                source_site="example.test",
                source_url=f"https://example.test/{index}",
                format_label="Standard",
            )
            for index in range(1, 51)
        ]
        responses = iter(("n", "n", "f"))
        rendered_pages: list[tuple[int, int, int, int]] = []
        prompts: list[str] = []
        original_ask = ui_module.Prompt.ask
        original_show = ui_module._show_deck_table

        def fake_ask(prompt: str, **kwargs: object) -> str:
            prompts.append(prompt)
            return next(responses)

        def fake_show(*args: object, **kwargs: object) -> None:
            visible_decks = args[3]
            rendered_pages.append(
                (
                    len(visible_decks),
                    int(kwargs["start_index"]),
                    int(kwargs["page_number"]),
                    int(kwargs["page_count"]),
                )
            )

        ui_module.Prompt.ask = fake_ask
        ui_module._show_deck_table = fake_show
        try:
            action = ui_module._browse_decks(
                FakeConsole(),
                FakeProvider(),
                MatchFormat.ANY,
                decks,
            )
        finally:
            ui_module.Prompt.ask = original_ask
            ui_module._show_deck_table = original_show

        self.assertEqual(action, "f")
        self.assertEqual(
            rendered_pages,
            [(20, 1, 1, 3), (20, 21, 2, 3), (10, 41, 3, 3)],
        )
        self.assertIn("n=next page", prompts[0])
        self.assertNotIn("p=previous page", prompts[0])
        self.assertIn("p=previous page", prompts[1])
        self.assertIn("n=next page", prompts[1])
        self.assertIn("p=previous page", prompts[2])
        self.assertNotIn("n=next page", prompts[2])

    def test_variant_browser_uses_the_same_pagination(self) -> None:
        class FakeProvider:
            change_label = "format"

            def result_view_config(self, *args: object, **kwargs: object) -> object:
                return ui_module.ResultViewConfig()

        variants = [
            DeckEntry(
                name=f"Variant {index}",
                source_site="example.test",
                source_url=f"https://example.test/{index}",
                format_label="Standard",
            )
            for index in range(1, 26)
        ]
        responses = iter(("n", "b"))
        rendered_pages: list[tuple[int, int]] = []
        original_ask = ui_module.Prompt.ask
        original_show = ui_module._show_deck_table

        def fake_ask(prompt: str, **kwargs: object) -> str:
            return next(responses)

        def fake_show(*args: object, **kwargs: object) -> None:
            rendered_pages.append(
                (len(kwargs["decks"]), int(kwargs["start_index"]))
            )

        ui_module.Prompt.ask = fake_ask
        ui_module._show_deck_table = fake_show
        try:
            action = ui_module._browse_variants(
                FakeConsole(),
                FakeProvider(),
                MatchFormat.ANY,
                variants[0],
                variants,
            )
        finally:
            ui_module.Prompt.ask = original_ask
            ui_module._show_deck_table = original_show

        self.assertEqual(action, "b")
        self.assertEqual(rendered_pages, [(20, 1), (5, 21)])

    def test_format_menu_defaults_to_back(self) -> None:
        class FakeProvider:
            display_name = "untapped.gg"
            description = "Arena archetypes"
            homepage = "https://mtga.untapped.gg/constructed/standard/meta"
            supported_formats = {MatchFormat.ANY, MatchFormat.BO1, MatchFormat.BO3}
            format_screen_sources: list[DeckSource] = []

        calls: list[dict[str, object]] = []
        original_ask = ui_module.Prompt.ask

        def fake_ask(prompt: str, **kwargs: object) -> str:
            calls.append(kwargs)
            return str(kwargs["default"])

        ui_module.Prompt.ask = fake_ask
        try:
            selected = _pick_format(FakeConsole(), FakeProvider())
        finally:
            ui_module.Prompt.ask = original_ask

        self.assertIsNone(selected)
        self.assertEqual(calls[0]["default"], "b")
        self.assertFalse(calls[0]["show_choices"])

    def test_format_menu_only_shows_formats_supported_by_provider(self) -> None:
        class FakeProvider:
            display_name = "mtgo.com"
            description = "Standard events"
            homepage = "https://www.mtgo.com/decklists"
            supported_formats = {MatchFormat.BO3}
            format_screen_sources: list[DeckSource] = []

        output = io.StringIO()
        console = Console(file=output, force_terminal=False, width=100)
        original_ask = ui_module.Prompt.ask

        def fake_ask(prompt: str, **kwargs: object) -> str:
            return "2"

        ui_module.Prompt.ask = fake_ask
        try:
            selected = _pick_format(console, FakeProvider())
        finally:
            ui_module.Prompt.ask = original_ask

        rendered = output.getvalue()
        self.assertIs(selected, MatchFormat.BO3)
        self.assertIn("Any Format", rendered)
        self.assertIn("Best of 3 (Bo3)", rendered)
        self.assertNotIn("Best of 1 (Bo1)", rendered)

    def test_split_creator_sources_keeps_creators_in_trailing_group(self) -> None:
        latest = DeckSource(
            name="Latest Decks",
            url="https://example.test/latest",
            description="Latest",
            formats=(MatchFormat.ANY,),
        )
        creator = DeckSource(
            name="Creator: Arne Huschenbeth",
            url="https://example.test/arne",
            description="Creator",
            formats=(MatchFormat.ANY,),
        )
        events = DeckSource(
            name="Events",
            url="https://example.test/events",
            description="Events",
            formats=(MatchFormat.ANY,),
        )

        regular_sources, creator_sources = _split_creator_sources([latest, creator, events])

        self.assertEqual(regular_sources, [latest, events])
        self.assertEqual(creator_sources, [creator])

    def test_source_context_label_uses_provider_item_label(self) -> None:
        class FakeProvider:
            source_picker_item_label = "section"

        self.assertEqual(_source_context_label(FakeProvider()), "Section")

    def test_table_note_shows_only_tags_for_aetherhub_creator_source(self) -> None:
        creator_source = DeckSource(
            name="Creator: ManaMan",
            url="https://aetherhub.com/User/ManaMan/Decks",
            description="Creator decks",
            formats=(MatchFormat.BO1, MatchFormat.BO3),
        )
        deck = DeckEntry(
            name="Big Boros Burn",
            source_site="aetherhub.com",
            source_url="https://aetherhub.com/Deck/big-boros-burn",
            format_label="Standard / Bo3",
            notes="Creator: ManaMan | Tags: Control | Exports: 20 | Views: 76",
        )

        self.assertEqual(
            _table_note(deck, truncate=False, selected_source=creator_source),
            "Control",
        )

    def test_posted_date_column_is_only_shown_for_aetherhub_rows_with_dates(self) -> None:
        class AetherhubProvider:
            key = "aetherhub"

        class MoxfieldProvider:
            key = "moxfield"

        dated_deck = DeckEntry(
            name="Big Boros Burn",
            source_site="aetherhub.com",
            source_url="https://aetherhub.com/Deck/big-boros-burn",
            format_label="Standard / Bo3",
            event_date="07/09/2026",
        )
        undated_deck = DeckEntry(
            name="Boros Burn",
            source_site="aetherhub.com",
            source_url="https://aetherhub.com/Deck/boros-burn",
            format_label="Standard / Bo3",
        )

        self.assertTrue(_show_posted_date_column(AetherhubProvider(), [dated_deck]))
        self.assertFalse(_show_posted_date_column(AetherhubProvider(), [undated_deck]))
        self.assertFalse(_show_posted_date_column(MoxfieldProvider(), [dated_deck]))

    def test_tcgplayer_hides_player_column_and_uses_created_date_column(self) -> None:
        class TCGPlayerProvider:
            key = "tcgplayer"

        creator_source = DeckSource(
            name="Creator: Arne Huschenbeth",
            url="https://www.tcgplayer.com/content/author/Arne%20Huschenbeth/",
            description="Creator decks",
            formats=(MatchFormat.ANY,),
        )
        deck = DeckEntry(
            name="Jeskai Lessons",
            source_site="tcgplayer.com",
            source_url="https://www.tcgplayer.com/magic-the-gathering/deck/Jeskai-Lessons/546993",
            format_label="Standard",
            player_name="Arne Huschenbeth",
            event_date="06/12/2026",
            notes="Created: 06/12/2026 | Creator: Arne Huschenbeth",
        )

        self.assertFalse(_show_player_column(TCGPlayerProvider(), [deck]))
        self.assertFalse(_show_notes_column(TCGPlayerProvider()))
        self.assertEqual(_date_column_label(TCGPlayerProvider(), creator_source, [deck]), "Created")
        self.assertEqual(
            _table_note(deck, truncate=False, selected_source=creator_source),
            "-",
        )

        event_deck = DeckEntry(
            name="Regional Championship",
            source_site="tcgplayer.com",
            source_url="https://www.tcgplayer.com/content/magic-the-gathering/decks/event/regional-championship",
            format_label="Standard",
            event_date="06/12/2026",
            notes="128 players",
        )
        self.assertIsNone(_date_column_label(TCGPlayerProvider(), None, [event_deck]))

    def test_moxfield_uses_updated_notes_column_without_creator_text(self) -> None:
        class MoxfieldProvider:
            key = "moxfield"

        deck = DeckEntry(
            name="Orzhov Offense Lifegain",
            source_site="moxfield.com",
            source_url="https://moxfield.com/decks/pjrbWDUR40CUnVEiZnrBPA",
            format_label="Standard",
            event_date="05/16/2026",
            notes="Creator: Ashlizzlle | Updated: 05/16/2026",
        )

        self.assertEqual(_notes_column_label(MoxfieldProvider()), "Updated")
        self.assertTrue(_show_notes_column(MoxfieldProvider()))
        self.assertIsNone(_date_column_label(MoxfieldProvider(), None, [deck]))
        self.assertEqual(_table_note(deck, truncate=False), "05/16/2026")

    def test_magic_gg_ranked_decklists_use_date_column_and_hide_ranked_title(self) -> None:
        class MagicGGProvider:
            key = "magic_gg"

        deck = DeckEntry(
            name="Patchwork Beastie + Rapid Rescue",
            source_site="magic.gg",
            source_url="https://magic.gg/decklists/traditional-standard-ranked-decklists-july-6-2026",
            format_label="Standard (Bo3)",
            event_name="Traditional Standard Ranked Decklists: July 6, 2026",
            event_date="July 6, 2026",
            notes="Traditional (Bo3)",
        )

        self.assertFalse(_show_notes_column(MagicGGProvider()))
        self.assertEqual(_date_column_label(MagicGGProvider(), None, [deck]), "Date")
        self.assertEqual(_table_note(deck, truncate=False), "-")

    def test_mtgo_events_use_date_column(self) -> None:
        class MTGOProvider:
            key = "mtgo"

        event = DeckEntry(
            name="Standard Challenge 32",
            source_site="mtgo.com",
            source_url="https://www.mtgo.com/decklist/standard-challenge-32",
            format_label="Standard (Bo3)",
            event_date="07/25/2026",
        )

        self.assertEqual(_date_column_label(MTGOProvider(), None, [event]), "Date")


if __name__ == "__main__":
    unittest.main()
