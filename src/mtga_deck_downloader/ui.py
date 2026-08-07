from __future__ import annotations

import importlib.util
import random
import shutil
import subprocess
import sys
from pathlib import Path

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider, ResultViewConfig
from mtga_deck_downloader.providers.registry import LAST_PROVIDER_ERRORS, load_providers

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"

MTGA_COLOSSAL_LOGO = r'''888b     d888                d8b              88888888888888                 .d8888b.         888   888                    d8b                          d8888
8888b   d8888                Y8P                  888    888                d88P  Y88b        888   888                    Y8P                         d88888
88888b.d88888                                     888    888                888    888        888   888                                               d88P888
888Y88888P888 8888b.  .d88b. 888 .d8888bd8b       888    88888b.  .d88b.    888        8888b. 88888888888b.  .d88b. 888d88888888888b.  .d88b.        d88P 888888d888 .d88b. 88888b.  8888b.
888 Y888P 888    "88bd88P"88b888d88P"   Y8P       888    888 "88bd8P  Y8b   888  88888    "88b888   888 "88bd8P  Y8b888P"  888888 "88bd88P"88b      d88P  888888P"  d8P  Y8b888 "88b    "88b
888  Y8P  888.d888888888  888888888               888    888  88888888888   888    888.d888888888   888  88888888888888    888888  888888  888     d88P   888888    88888888888  888.d888888
888   "   888888  888Y88b 888888Y88b.   d8b       888    888  888Y8b.       Y88b  d88P888  888Y88b. 888  888Y8b.    888    888888  888Y88b 888    d8888888888888    Y8b.    888  888888  888
888       888"Y888888 "Y88888888 "Y8888PY8P       888    888  888 "Y8888     "Y8888P88"Y888888 "Y888888  888 "Y8888 888    888888  888 "Y88888   d88P     888888     "Y8888 888  888"Y888888
                          888                                                                                                              888
                     Y8b d88P                                                                                                         Y8b d88P
                      "Y88P"                                                                                                           "Y88P"'''

_COMPACT_MAGIC = (
    " __  __           _",
    "|  \\/  |__ _ __ _(_)__",
    "| |\\/| / _` / _` | / _|",
    "|_|  |_\\__,_\\__, |_\\__|",
    "            |___/",
)
_COMPACT_THE_GATHERING = (
    " _____ _           ___      _   _            _",
    "|_   _| |_  ___   / __|__ _| |_| |_  ___ _ _(_)_ _  __ _",
    "  | | | ' \\/ -_) | (_ / _` |  _| ' \\/ -_) '_| | ' \\/ _` |",
    "  |_| |_||_\\___|  \\___\\__,_|\\__|_||_\\___|_| |_|_||_\\__, |",
    "                                                   |___/",
)
_COMPACT_ARENA = (
    "   _",
    "  /_\\  _ _ ___ _ _  __ _",
    " / _ \\| '_/ -_) ' \\/ _` |",
    "/_/ \\_\\_| \\___|_||_\\__,_|",
    "",
)
_COMPACT_MAGIC_WIDTH = max(len(line) for line in _COMPACT_MAGIC)
_COMPACT_THE_GATHERING_WIDTH = max(len(line) for line in _COMPACT_THE_GATHERING)
MTGA_COMPACT_LOGO = "\n".join(
    f"{magic.ljust(_COMPACT_MAGIC_WIDTH)}{':' if index in {1, 3} else ' '}  "
    f"{gathering.ljust(_COMPACT_THE_GATHERING_WIDTH)}   {arena}"
    for index, (magic, gathering, arena) in enumerate(
        zip(_COMPACT_MAGIC, _COMPACT_THE_GATHERING, _COMPACT_ARENA)
    )
)

COMPACT_LOGO_MIN_WIDTH = 120
COLOSSAL_LOGO_MIN_WIDTH = 198
DECK_PAGE_SIZE = 20


def _clear_screen(console: Console) -> None:
    console.clear()
    # Request scrollback purge on terminals that support CSI 3J.
    if console.is_terminal:
        try:
            console.file.write("\x1b[3J")
            console.file.flush()
        except Exception:
            pass


def _render_site_header(console: Console) -> None:
    width = getattr(console, "width", 80)
    if width >= COLOSSAL_LOGO_MIN_WIDTH:
        logo = Text(MTGA_COLOSSAL_LOGO, style="bold bright_white")
    elif width >= COMPACT_LOGO_MIN_WIDTH:
        logo = Text(MTGA_COMPACT_LOGO, style="bold bright_white")
    else:
        logo = Text("Magic: The Gathering Arena", style="bold bright_white")

    header = Group(
        Align.center(logo),
        Align.center(Text("DECK FINDER & DOWNLOADER", style="bold bright_yellow")),
        Text(),
        Align.center(Text("🟡   🔵   ⚫   🔴   🟢")),
        Text(),
        Align.center(
            Text(
                "Select a decklist source website or choose random to get a random "
                "deck from all available sites / creators.",
                style="white",
            )
        ),
    )
    console.print(
        Panel(
            header,
            border_style="bright_yellow",
            padding=(1, 3),
        )
    )


def _missing_runtime_modules() -> list[str]:
    required = {
        "requests": "requests",
        "bs4": "beautifulsoup4",
        "cloudscraper": "cloudscraper",
    }
    missing: list[str] = []
    for module_name, package_name in required.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)
    return missing


def _render_dependency_error(console: Console, missing_packages: list[str]) -> None:
    lines = [
        "[bold red]Required application components are missing.[/bold red]",
        "",
        f"[bold]Missing:[/bold] {', '.join(missing_packages)}",
    ]

    if getattr(sys, "frozen", False):
        lines.extend(
            [
                "",
                "[bold]Fix:[/bold] Reinstall MTGA Deck Downloader from its official release.",
                f"[bold]Executable:[/bold] {sys.executable}",
            ]
        )
    else:
        install_cmd = f"{sys.executable} -m pip install -r {REQUIREMENTS_PATH}"
        lines.extend(
            [
                "",
                f"[bold]Python:[/bold] {sys.executable}",
                "",
                "[bold]Fix:[/bold]",
                install_cmd,
            ]
        )

    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if (
        not getattr(sys, "frozen", False)
        and venv_python.exists()
        and Path(sys.executable) != venv_python
    ):
        lines.extend(
            [
                "",
                "[bold]Repo virtualenv:[/bold]",
                f"{venv_python} {REPO_ROOT / 'app.py'}",
            ]
        )

    console.print(
        Panel(
            "\n".join(lines),
            title="Missing Dependencies",
            border_style="red",
        )
    )


def _continue_or_quit(console: Console, message: str) -> bool:
    raw = console.input(f"\n[dim]{message}[/dim] ").strip().lower()
    return raw == "q"


def run_app() -> None:
    console = Console()
    missing_packages = _missing_runtime_modules()
    if missing_packages:
        _render_dependency_error(console, missing_packages)
        return

    providers = load_providers()

    if not providers:
        if LAST_PROVIDER_ERRORS:
            console.print(
                Panel(
                    "\n".join(LAST_PROVIDER_ERRORS),
                    title="Provider Load Errors",
                    border_style="yellow",
                )
            )
        console.print("[bold red]No providers found. Add provider modules first.[/bold red]")
        return

    while True:
        provider = _pick_provider(console, providers)
        if provider is None:
            console.print("\n[bold]Exiting MTGA Deck Downloader.[/bold]")
            return
        if provider == "random":
            action = _play_random_deck(console, providers)
            if action == "q":
                _clear_screen(console)
                console.print("\n[bold]Exiting MTGA Deck Downloader.[/bold]")
                return
            continue

        while True:
            format_selection = _pick_format(console, provider)
            if format_selection == "q":
                _clear_screen(console)
                console.print("\n[bold]Exiting MTGA Deck Downloader.[/bold]")
                return
            if format_selection is None:
                _clear_screen(console)
                break

            if isinstance(format_selection, DeckSource):
                selected_format = MatchFormat.ANY
                selected_source = format_selection
            else:
                selected_format = format_selection
                selected_source = None
                if provider.uses_source_picker:
                    selected_source = _pick_source(console, provider, selected_format)
                    if selected_source == "q":
                        _clear_screen(console)
                        console.print("\n[bold]Exiting MTGA Deck Downloader.[/bold]")
                        return
                    if selected_source == "b":
                        _clear_screen(console)
                        if provider.supported_formats == {MatchFormat.ANY}:
                            break
                        continue

            decks = _fetch_decks(
                console=console,
                provider=provider,
                selected_format=selected_format,
                limit=50,
                selected_source=selected_source,
            )
            if decks is None:
                if _continue_or_quit(console, "Press Enter to continue or q to quit"):
                    _clear_screen(console)
                    console.print("\n[bold]Exiting MTGA Deck Downloader.[/bold]")
                    return
                continue

            action = _browse_decks(
                console,
                provider,
                selected_format,
                decks,
                selected_source=selected_source,
            )
            if action == "q":
                _clear_screen(console)
                console.print("\n[bold]Exiting MTGA Deck Downloader.[/bold]")
                return
            if action == "s":
                _clear_screen(console)
                break
            if action == "f":
                _clear_screen(console)


def _fetch_decks(
    console: Console,
    provider: DeckProvider,
    selected_format: MatchFormat,
    limit: int,
    selected_source: DeckSource | None,
) -> list[DeckEntry] | None:
    _clear_screen(console)
    source_label = selected_source.name if selected_source else "all matching endpoints"
    try:
        with console.status(
            f"[bold cyan]Fetching deck data from {provider.display_name} ({source_label})...[/bold cyan]"
        ):
            decks = provider.fetch_decks(
                selected_format=selected_format,
                limit=limit,
                source=selected_source,
            )
    except Exception as exc:
        console.print(
            f"\n[bold red]Failed to fetch deck data from {provider.display_name}.[/bold red]"
        )
        console.print(f"[red]{exc}[/red]")
        return None

    if not decks:
        console.print("\n[yellow]No decks found for the selected filter.[/yellow]")
        return None
    return decks


def _play_random_deck(console: Console, providers: list[DeckProvider]) -> str:
    _clear_screen(console)
    with console.status("[bold cyan]Choosing a random deck...[/bold cyan]"):
        selection = _select_random_deck(providers)

    if selection is None:
        console.print(
            "\n[yellow]No random deck is available right now. All providers failed or returned no decks.[/yellow]"
        )
        if _continue_or_quit(console, "Press Enter to continue or q to quit"):
            return "q"
        return "continue"

    provider, deck = selection
    detailed_deck = _show_deck_detail(console, provider, deck)
    return "q" if detailed_deck == "q" else "continue"


def _select_random_deck(
    providers: list[DeckProvider],
    *,
    rng: object = random,
    limit: int = 50,
) -> tuple[DeckProvider, DeckEntry] | None:
    for provider in rng.sample(providers, len(providers)):
        try:
            decks = provider.fetch_decks(
                selected_format=MatchFormat.ANY,
                limit=limit,
                source=None,
            )
        except Exception:
            continue
        if not decks:
            continue

        selected_deck = rng.choice(decks)
        try:
            variants = provider.fetch_deck_variants(
                deck=selected_deck,
                selected_format=MatchFormat.ANY,
                limit=limit,
            )
        except Exception:
            variants = None
        if variants:
            selected_deck = rng.choice(variants)
        return provider, selected_deck
    return None


def _browse_decks(
    console: Console,
    provider: DeckProvider,
    selected_format: MatchFormat,
    decks: list[DeckEntry],
    selected_source: DeckSource | None = None,
) -> str:
    view_config = provider.result_view_config(selected_source)
    change_label = provider.change_label
    page_index = 0
    while True:
        page_decks, page_index, start_index, page_count = _deck_page(decks, page_index)
        _show_deck_table(
            console,
            provider,
            selected_format,
            page_decks,
            selected_source=selected_source,
            title=view_config.title,
            count_label=view_config.count_label,
            name_column_label=view_config.name_column_label,
            helper_text=view_config.helper_text,
            show_notes=view_config.show_notes,
            all_decks=decks,
            start_index=start_index,
            page_number=page_index + 1,
            page_count=page_count,
        )
        page_actions = _page_prompt_actions(page_index, page_count)
        navigation = f", {', '.join(page_actions)}" if page_actions else ""
        prompt = (
            f"\n[bold cyan]{view_config.selection_label} # for {view_config.selection_action}, "
            f"f={change_label}, s=site{navigation}, q=quit[/bold cyan]"
        )
        raw = Prompt.ask(
            prompt,
            default="f",
            show_choices=False,
        ).strip()
        lowered = raw.lower()
        if lowered == "n" and page_index + 1 < page_count:
            page_index += 1
            continue
        if lowered == "p" and page_index > 0:
            page_index -= 1
            continue
        if lowered in {"f", "s", "q"}:
            return lowered
        if raw.isdigit():
            index = int(raw)
            if start_index <= index < start_index + len(page_decks):
                selected = decks[index - 1]
                try:
                    _clear_screen(console)
                    with console.status(
                        f"[bold cyan]Fetching variant decks for {selected.name}...[/bold cyan]"
                    ):
                        variants = provider.fetch_deck_variants(
                            deck=selected,
                            selected_format=selected_format,
                            limit=50,
                        )
                except Exception as exc:
                    console.print(f"[red]Failed to load variant decks: {exc}[/red]")
                    if _continue_or_quit(console, "Press Enter to return to results or q to quit"):
                        return "q"
                    continue

                if variants:
                    variant_action = _browse_variants(
                        console=console,
                        provider=provider,
                        selected_format=selected_format,
                        selected_source=selected_source,
                        archetype=selected,
                        variants=variants,
                    )
                    if variant_action in {"f", "s", "q"}:
                        return variant_action
                    continue

                detailed_deck = _show_deck_detail(console, provider, selected)
                if detailed_deck == "q":
                    return "q"
                decks[index - 1] = detailed_deck
                continue
        valid_actions = ["a visible deck number", *page_actions, "f", "s", "q"]
        console.print(
            f"[yellow]Invalid input. Enter {', '.join(valid_actions)}.[/yellow]"
        )


def _deck_page(
    decks: list[DeckEntry],
    page_index: int,
) -> tuple[list[DeckEntry], int, int, int]:
    page_count = max(1, (len(decks) + DECK_PAGE_SIZE - 1) // DECK_PAGE_SIZE)
    page_index = min(max(page_index, 0), page_count - 1)
    start = page_index * DECK_PAGE_SIZE
    return decks[start : start + DECK_PAGE_SIZE], page_index, start + 1, page_count


def _page_prompt_actions(page_index: int, page_count: int) -> list[str]:
    actions: list[str] = []
    if page_index > 0:
        actions.append("p=previous page")
    if page_index + 1 < page_count:
        actions.append("n=next page")
    return actions


def _show_deck_table(
    console: Console,
    provider: DeckProvider,
    selected_format: MatchFormat,
    decks: list[DeckEntry],
    selected_source: DeckSource | None = None,
    title: str = "Scraped Deck Results",
    count_label: str = "Decks found",
    name_column_label: str = "Deck",
    helper_text: str | None = None,
    show_notes: bool | None = None,
    all_decks: list[DeckEntry] | None = None,
    start_index: int = 1,
    page_number: int = 1,
    page_count: int = 1,
) -> None:
    _clear_screen(console)
    column_decks = all_decks if all_decks is not None else decks
    suppress_event_names = (
        provider.key == "tcgplayer"
        and selected_source is not None
        and selected_source.name == "Events"
        and title.endswith("Top Decks")
    )
    source_text = (
        f"{_source_context_label(provider)}: [bold cyan]{selected_source.name}[/bold cyan]\n"
        if selected_source is not None
        else ""
    )
    summary_lines = [
        f"[bold green]{provider.display_name}[/bold green]",
        f"Format filter: [bold cyan]{selected_format.label}[/bold cyan]",
    ]
    if source_text:
        summary_lines.append(source_text.rstrip("\n"))
    summary_lines.append(f"{count_label}: [bold]{len(column_decks)}[/bold]")
    if page_count > 1:
        summary_lines.append(f"Page: [bold]{page_number} of {page_count}[/bold]")
    if helper_text:
        summary_lines.append(f"[dim]{helper_text}[/dim]")

    console.print(
        Panel(
            "\n".join(summary_lines),
            title=title,
            border_style="cyan",
        )
    )

    show_win_rate = any(deck.win_rate is not None for deck in column_decks)
    show_matches = any(deck.matches is not None for deck in column_decks)
    show_player = _show_player_column(provider, column_decks)
    show_placing = any(deck.placing is not None for deck in column_decks)
    show_notes = _show_notes_column(provider) if show_notes is None else show_notes
    date_column_label = _date_column_label(provider, selected_source, column_decks)
    is_magic_gg = provider.key == "magic_gg"

    table = Table(show_header=True, header_style="bold magenta", show_lines=True)
    table.add_column("#", justify="right", style="bold")
    table.add_column(name_column_label, style="bold")
    if show_win_rate:
        table.add_column("Win %", justify="right")
    if show_matches:
        table.add_column("Matches", justify="right")
    if show_placing:
        table.add_column("Place", no_wrap=True)
    if show_player:
        table.add_column("Player", overflow="fold", max_width=20)
    table.add_column("Format", no_wrap=True)
    if show_notes:
        table.add_column(
            _notes_column_label(provider),
            overflow="fold" if is_magic_gg else "ellipsis",
            max_width=72 if is_magic_gg else 44,
        )
    if date_column_label:
        table.add_column(date_column_label, no_wrap=True)

    for idx, deck in enumerate(decks, start=start_index):
        note = _table_note(
            deck,
            truncate=not is_magic_gg,
            include_event_name=not suppress_event_names,
            selected_source=selected_source,
        )
        row = [str(idx), deck.name]
        if show_win_rate:
            row.append(_format_percent(deck.win_rate))
        if show_matches:
            row.append(str(deck.matches) if deck.matches is not None else "-")
        if show_placing:
            row.append(deck.placing or "-")
        if show_player:
            row.append(deck.player_name or "-")
        row.append(deck.format_label)
        if show_notes:
            row.append(note)
        if date_column_label:
            row.append(deck.event_date or "-")
        table.add_row(*row)
    console.print(table)


def _browse_variants(
    console: Console,
    provider: DeckProvider,
    selected_format: MatchFormat,
    archetype: DeckEntry,
    variants: list[DeckEntry],
    selected_source: DeckSource | None = None,
) -> str:
    view_config = provider.result_view_config(
        selected_source,
        variants=True,
        parent=archetype,
    )
    change_label = provider.change_label
    page_index = 0
    while True:
        page_variants, page_index, start_index, page_count = _deck_page(
            variants,
            page_index,
        )
        _show_deck_table(
            console=console,
            provider=provider,
            selected_format=selected_format,
            decks=page_variants,
            selected_source=selected_source,
            title=view_config.title,
            count_label=view_config.count_label,
            name_column_label=view_config.name_column_label,
            helper_text=view_config.helper_text,
            show_notes=view_config.show_notes,
            all_decks=variants,
            start_index=start_index,
            page_number=page_index + 1,
            page_count=page_count,
        )
        page_actions = _page_prompt_actions(page_index, page_count)
        navigation = f", {', '.join(page_actions)}" if page_actions else ""
        raw = Prompt.ask(
            f"\n[bold cyan]{view_config.selection_label} # for {view_config.selection_action}, "
            f"b=back, f={change_label}, s=site{navigation}, q=quit[/bold cyan]",
            default="b",
            show_choices=False,
        ).strip()
        lowered = raw.lower()
        if lowered == "n" and page_index + 1 < page_count:
            page_index += 1
            continue
        if lowered == "p" and page_index > 0:
            page_index -= 1
            continue
        if lowered in {"b", "f", "s", "q"}:
            return lowered
        if raw.isdigit():
            index = int(raw)
            if start_index <= index < start_index + len(page_variants):
                detailed_deck = _show_deck_detail(console, provider, variants[index - 1])
                if detailed_deck == "q":
                    return "q"
                variants[index - 1] = detailed_deck
                continue
        valid_actions = ["a visible deck number", *page_actions, "b", "f", "s", "q"]
        console.print(
            f"[yellow]Invalid input. Enter {', '.join(valid_actions)}.[/yellow]"
        )


def _show_deck_detail(console: Console, provider: DeckProvider, deck: DeckEntry) -> DeckEntry | str:
    hydrated = deck
    if hydrated.deck_text is None:
        try:
            with console.status("[bold cyan]Loading deck details...[/bold cyan]"):
                hydrated = provider.hydrate_deck(deck)
        except Exception as exc:
            console.print(f"[yellow]Could not load additional deck detail: {exc}[/yellow]")

    _clear_screen(console)
    info_lines = [
        f"[bold]Deck:[/bold] {hydrated.name}",
        f"[bold]Source:[/bold] {hydrated.source_site}",
    ]
    if hydrated.event_name:
        info_lines.append(f"[bold]Event:[/bold] {hydrated.event_name}")
    info_lines.extend(
        [
            f"[bold]URL:[/bold] {hydrated.source_url}",
            f"[bold]Format:[/bold] {hydrated.format_label}",
        ]
    )
    if hydrated.win_rate is not None:
        info_lines.append(f"[bold]Win Rate:[/bold] {_format_percent(hydrated.win_rate)}")
    if hydrated.matches is not None:
        info_lines.append(f"[bold]Matches:[/bold] {hydrated.matches}")
    if hydrated.placing:
        info_lines.append(f"[bold]Place:[/bold] {hydrated.placing}")
    if hydrated.player_name:
        info_lines.append(f"[bold]Player:[/bold] {hydrated.player_name}")
    if hydrated.event_date:
        info_lines.append(f"[bold]Event Date:[/bold] {hydrated.event_date}")
    if hydrated.notes:
        info_lines.append(f"[bold]Note:[/bold] {hydrated.notes}")

    console.print(Panel("\n".join(info_lines), title="Deck Details", border_style="green"))

    formatted_deck_text = _format_arena_import_text(hydrated.deck_text)
    if formatted_deck_text:
        console.print("\n[bold cyan]Arena Import Text[/bold cyan]\n")
        console.print(formatted_deck_text, soft_wrap=True)
        copied, error = _copy_to_clipboard(formatted_deck_text)
        if copied:
            console.print("\n[bold green]Decklist copied to clipboard automatically.[/bold green]")
        else:
            console.print(
                "\n[yellow]Could not copy automatically. Select the text manually.[/yellow]"
            )
            if error:
                console.print(f"[dim]{error}[/dim]")
    else:
        console.print(
            "[yellow]This source did not provide direct MTGA import text for this deck.[/yellow]"
        )

    while True:
        raw = (
            console.input(
                "\n[bold cyan]Press Enter to go back, q=quit[/bold cyan]: "
            )
            .strip()
            .lower()
        )
        if raw == "":
            break
        if raw == "q":
            return "q"
        console.print("[yellow]Invalid input. Press Enter to go back or q to quit.[/yellow]")
    return hydrated


def _format_arena_import_text(deck_text: str | None) -> str | None:
    if not deck_text:
        return None

    section_headers = {"sideboard", "companion", "commander", "maybeboard"}
    lines = deck_text.splitlines()
    formatted: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower() in section_headers:
            if formatted and formatted[-1].strip():
                formatted.append("")
            formatted.append(stripped)
            continue
        formatted.append(line.rstrip())

    return "\n".join(formatted).strip("\n")


def _copy_to_clipboard(text: str) -> tuple[bool, str | None]:
    if not text:
        return False, "No text to copy."

    def _run(cmd: list[str], use_shell: bool = False) -> tuple[bool, str | None]:
        try:
            subprocess.run(
                cmd if not use_shell else " ".join(cmd),
                input=text,
                text=True,
                check=True,
                shell=use_shell,
            )
            return True, None
        except Exception as exc:
            return False, str(exc)

    if sys.platform == "darwin":
        return _run(["pbcopy"])

    if sys.platform.startswith("win"):
        ok, _ = _run(
            ["powershell", "-NoProfile", "-Command", "Set-Clipboard"],
            use_shell=False,
        )
        if ok:
            return True, None
        return _run(["clip"], use_shell=True)

    if shutil.which("wl-copy"):
        return _run(["wl-copy"])
    if shutil.which("xclip"):
        return _run(["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        return _run(["xsel", "--clipboard", "--input"])

    return False, "No clipboard command found (tried pbcopy, powershell/clip, wl-copy, xclip, xsel)."


def _format_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _show_player_column(provider: DeckProvider, decks: list[DeckEntry]) -> bool:
    return provider.key != "tcgplayer" and any(deck.player_name is not None for deck in decks)


def _notes_column_label(provider: DeckProvider) -> str:
    if provider.key == "moxfield":
        return "Updated"
    return "Event/Notes"


def _show_notes_column(provider: DeckProvider) -> bool:
    return provider.key not in {"magic_gg", "tcgplayer"}


def _date_column_label(
    provider: DeckProvider,
    selected_source: DeckSource | None,
    decks: list[DeckEntry],
) -> str | None:
    if not any(deck.event_date for deck in decks):
        return None
    if provider.key == "aetherhub":
        return "Posted"
    if provider.key == "magic_gg":
        return "Date"
    if provider.key == "mtgo":
        return "Date"
    if provider.key == "tcgplayer" and any(_note_value(deck.notes, "Created") for deck in decks):
        return "Created"
    return None


def _show_posted_date_column(provider: DeckProvider, decks: list[DeckEntry]) -> bool:
    return _date_column_label(provider, None, decks) == "Posted"


def _table_note(
    deck: DeckEntry,
    truncate: bool,
    include_event_name: bool = True,
    selected_source: DeckSource | None = None,
) -> str:
    if _is_aetherhub_creator_source(deck, selected_source):
        note = _aetherhub_creator_tags(deck.notes)
        return _truncate(note, 42) if truncate else note
    if deck.source_site == "moxfield.com":
        return deck.event_date or _note_value(deck.notes, "Updated") or "-"
    if deck.source_site == "magic.gg" and _is_magic_gg_ranked_decklist(deck.event_name):
        return "-"

    note_parts: list[str] = []
    if include_event_name and deck.event_name:
        note_parts.append(deck.event_name)
    if deck.notes:
        note_parts.extend(_display_note_parts(deck.notes, deck.source_site))
    if not note_parts:
        return "-"
    note = " | ".join(note_parts).replace("\n", " ").strip()
    return _truncate(note, 42) if truncate else note


def _is_aetherhub_creator_source(deck: DeckEntry, selected_source: DeckSource | None) -> bool:
    return (
        deck.source_site == "aetherhub.com"
        and selected_source is not None
        and selected_source.name.startswith("Creator: ")
    )


def _aetherhub_creator_tags(notes: str | None) -> str:
    if not notes:
        return "-"
    for part in notes.split("|"):
        cleaned = part.strip()
        if cleaned.startswith("Tags:"):
            tags = cleaned.removeprefix("Tags:").strip()
            return tags or "-"
    return "-"


def _display_note_parts(notes: str, source_site: str) -> list[str]:
    values: list[str] = []
    for part in notes.split("|"):
        cleaned = part.strip()
        if not cleaned:
            continue
        if source_site == "tcgplayer.com" and (
            cleaned.startswith("Creator:") or cleaned.startswith("Created:")
        ):
            continue
        values.append(cleaned)
    return values


def _note_value(notes: str | None, label: str) -> str | None:
    if not notes:
        return None
    prefix = f"{label}:"
    for part in notes.split("|"):
        cleaned = part.strip()
        if cleaned.startswith(prefix):
            value = cleaned.removeprefix(prefix).strip()
            return value or None
    return None


def _is_magic_gg_ranked_decklist(event_name: str | None) -> bool:
    lowered = (event_name or "").lower()
    return "standard ranked decklists" in lowered


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _pick_provider(console: Console, providers: list[DeckProvider]) -> DeckProvider | str | None:
    while True:
        _clear_screen(console)
        _render_site_header(console)

        table = Table(
            show_header=True,
            header_style="bold magenta",
            padding=(0, 1),
        )
        table.add_column("#", justify="right", style="bold")
        table.add_column("Site", style="bold green")
        table.add_column("Description")

        for idx, provider in enumerate(providers, start=1):
            table.add_row(
                f"\n{idx}\n",
                f"\n{provider.display_name}\n",
                f"\n{provider.description}\n",
            )

        console.print(table)

        raw = Prompt.ask(
            "\n[bold cyan]Select site number, r=random deck from all sites / creators, q=quit[/bold cyan]",
            default="q",
            show_choices=False,
        ).strip()
        if raw.lower() == "q":
            return None
        if raw.lower() == "r":
            return "random"
        if raw.isdigit():
            selection = int(raw)
            if 1 <= selection <= len(providers):
                return providers[selection - 1]
        console.print("[yellow]Invalid selection. Try again.[/yellow]")


def _pick_format(console: Console, provider: DeckProvider) -> MatchFormat | DeckSource | str | None:
    if provider.supported_formats == {MatchFormat.ANY}:
        return MatchFormat.ANY

    format_options = [MatchFormat.ANY]
    format_options.extend(
        match_format
        for match_format in (MatchFormat.BO1, MatchFormat.BO3)
        if match_format in provider.supported_formats
    )

    while True:
        _clear_screen(console)
        console.print(
            Panel(
                f"[bold green]{provider.display_name}[/bold green]\n"
                f"{provider.description}\n"
                f"[cyan]{provider.homepage}[/cyan]",
                title="Selected Site",
                border_style="green",
            )
        )

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", justify="right", style="bold")
        table.add_column("Format")
        for idx, match_format in enumerate(format_options, start=1):
            table.add_row(str(idx), match_format.label)
        console.print(table)

        format_screen_sources = provider.format_screen_sources
        creator_start = len(format_options) + 1
        if format_screen_sources:
            creator_table = Table(show_header=True, header_style="bold magenta")
            creator_table.add_column("#", justify="right", style="bold")
            creator_table.add_column("Creator")
            for idx, source in enumerate(format_screen_sources, start=creator_start):
                creator_table.add_row(str(idx), source.name.removeprefix("Creator: ").strip() or source.name)
            console.print()
            console.print(creator_table)

        raw = Prompt.ask(
            "\n[bold cyan]Select format or creator, b=back, q=quit[/bold cyan]",
            default="b",
            show_choices=False,
        ).strip()
        if raw.lower() == "q":
            return "q"
        if raw.lower() == "b":
            return None
        if raw.isdigit():
            selection = int(raw)
            format_index = selection - 1
            if 0 <= format_index < len(format_options):
                return format_options[format_index]
        if raw.isdigit() and format_screen_sources:
            selection = int(raw)
            creator_index = selection - creator_start
            if 0 <= creator_index < len(format_screen_sources):
                return format_screen_sources[creator_index]
        console.print("[yellow]Invalid selection. Try again.[/yellow]")


def _pick_source(
    console: Console, provider: DeckProvider, selected_format: MatchFormat
) -> DeckSource | str | None:
    sources = provider.list_sources(selected_format)
    regular_sources, creator_sources = _split_creator_sources(sources)
    numbered_sources = regular_sources + creator_sources
    _clear_screen(console)
    console.print(
        Panel(
            f"[bold green]{provider.display_name}[/bold green]\n"
            f"Format filter: [bold cyan]{selected_format.label}[/bold cyan]",
            title=provider.source_picker_title,
            border_style="cyan",
        )
    )

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", justify="right", style="bold")
    table.add_column("Name", style="bold")
    table.add_column("URL", overflow="fold")

    if not sources:
        console.print(
            f"[yellow]No {_plural_source_item_label(provider)} match that format.[/yellow]"
        )
        return "b"

    for idx, source in enumerate(regular_sources, start=1):
        table.add_row(str(idx), source.name, source.url)
    console.print(table)

    if creator_sources:
        creator_table = Table(show_header=True, header_style="bold magenta")
        creator_table.add_column("#", justify="right", style="bold")
        creator_table.add_column("Creator", style="bold")
        creator_table.add_column("URL", overflow="fold")
        for idx, source in enumerate(creator_sources, start=len(regular_sources) + 1):
            creator_table.add_row(
                str(idx),
                source.name.removeprefix("Creator: ").strip() or source.name,
                source.url,
            )
        console.print()
        console.print(creator_table)

    if len(numbered_sources) == 1:
        console.print(
            f"\n[dim]Only one {provider.source_picker_item_label} matches this filter. "
            "Using it automatically...[/dim]"
        )
        return numbered_sources[0]

    while True:
        options = [
            f"Select {provider.source_picker_item_label} #",
        ]
        if provider.allow_all_sources:
            options.append(f"a={provider.source_picker_all_label}")
        options.append("b=back")
        options.append("q=quit")
        raw = Prompt.ask(
            f"\n[bold cyan]{', '.join(options)}[/bold cyan]",
            default="a" if provider.allow_all_sources else "b",
            show_choices=False,
        ).strip()
        lowered = raw.lower()
        if lowered == "q":
            return "q"
        if lowered == "b":
            return "b"
        if lowered == "a" and provider.allow_all_sources:
            return None
        if raw.isdigit():
            selection = int(raw)
            if 1 <= selection <= len(numbered_sources):
                return numbered_sources[selection - 1]
        valid_choices = "a, b, or q" if provider.allow_all_sources else "b or q"
        console.print(
            f"[yellow]Invalid selection. Enter a number, {valid_choices}.[/yellow]"
        )


def _split_creator_sources(sources: list[DeckSource]) -> tuple[list[DeckSource], list[DeckSource]]:
    regular_sources = [source for source in sources if not source.name.startswith("Creator: ")]
    creator_sources = [source for source in sources if source.name.startswith("Creator: ")]
    return regular_sources, creator_sources


def _source_context_label(provider: DeckProvider) -> str:
    return provider.source_picker_item_label.strip().capitalize() or "Source"


def _plural_source_item_label(provider: DeckProvider) -> str:
    label = provider.source_picker_item_label.strip() or "source"
    if label.endswith("s"):
        return label
    return f"{label}s"
