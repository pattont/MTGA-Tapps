"""In-game overlay state: what is left in the player's library and the odds.

Pure functions, no tracker or Qt/Tauri imports. The tracker feeds this with
the submitted decklist (one name per copy), the cards it has seen leave the
library since the opening hand, the cards it has seen go back, and — when
Arena reported it — the live library size. The result is the JSON the
overlay draws: per-card copies left and draw odds, the land odds, and the
game context the header needs.

The odds are hypergeometric over the *reported* library size, not over the
cards the tracker can account for. If those two disagree (a card returned
to the library face down, a duplicate the log named differently) the
difference is exposed as ``unaccounted`` rather than hidden inside a wrong
percentage.
"""

from __future__ import annotations

from collections import Counter
from math import comb
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .colors import BASIC_LAND_COLORS

#: The overlay's "within N draws" columns.
ODDS_HORIZONS: Tuple[int, ...] = (1, 2, 3)

#: Shape of the per-name card facts the tracker supplies:
#: (type_category, mana_cost, mana_value). Any of them may be None.
CardInfo = Callable[[str], Tuple[Optional[str], Optional[str], Optional[float]]]


def odds_within(copies: int, library: int, draws: int) -> float:
    """Probability of drawing at least one of ``copies`` in ``draws`` from a
    library of ``library`` cards. 0 when nothing is left or the library is
    empty; 1 when the library cannot avoid it."""
    if copies <= 0 or library <= 0 or draws <= 0:
        return 0.0
    if copies >= library:
        return 1.0
    draws = min(draws, library)
    misses = library - copies
    if misses < draws:
        return 1.0
    return 1.0 - comb(misses, draws) / comb(library, draws)


def _pct(value: float) -> float:
    return round(100.0 * value, 1)


def is_basic_land(name: str) -> bool:
    return name in BASIC_LAND_COLORS


def _is_land(type_category: Optional[str], name: str) -> bool:
    if type_category and str(type_category).casefold() == "land":
        return True
    return is_basic_land(name)


def build_overlay_state(
    *,
    deck: Sequence[str],
    departures: Mapping[str, int],
    returns: Mapping[str, int],
    library_size: Optional[int],
    card_info: CardInfo,
    game_active: bool,
    mid_game_attach: bool = False,
    deck_name: Optional[str] = None,
    format_label: Optional[str] = None,
    match_type: Optional[str] = None,
    opponent_name: Optional[str] = None,
    turn_number: Optional[int] = None,
    on_play: Optional[bool] = None,
    player_commanders: Optional[Iterable[str]] = None,
    opponent_commanders: Optional[Iterable[str]] = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble the overlay payload. ``deck`` lists one entry per copy; the
    commander is not in it (it lives in the command zone)."""
    totals: Counter = Counter(str(name) for name in deck if name)
    left: Counter = Counter()
    for name, total in totals.items():
        remaining = total - int(departures.get(name, 0)) + int(returns.get(name, 0))
        left[name] = max(0, min(total, remaining))
    accounted = sum(left.values())
    deck_size = sum(totals.values())
    if library_size is None:
        library_size = accounted
    library_size = max(0, int(library_size))

    cards: List[Dict[str, Any]] = []
    lands_left = 0
    lands_total = 0
    for name in sorted(totals):
        type_category, mana_cost, mana_value = card_info(name)
        land = _is_land(type_category, name)
        copies_left = left[name]
        if land:
            lands_left += copies_left
            lands_total += totals[name]
        cards.append(
            {
                "name": name,
                "type_category": type_category or ("Land" if land else "Other"),
                "mana_cost": mana_cost,
                "mana_value": mana_value,
                "total": totals[name],
                "left": copies_left,
                "land": land,
                "basic": land and is_basic_land(name),
                "odds": {
                    str(n): _pct(odds_within(copies_left, library_size, n)) for n in ODDS_HORIZONS
                },
            }
        )

    return {
        "game_active": bool(game_active),
        "mid_game_attach": bool(mid_game_attach),
        "deck_name": deck_name,
        "format_label": format_label,
        "match_type": match_type,
        "opponent_name": opponent_name,
        "turn_number": turn_number,
        "on_play": on_play,
        "player_commanders": list(player_commanders or []),
        "opponent_commanders": list(opponent_commanders or []),
        "deck_size": deck_size,
        "library_size": library_size,
        "unaccounted": library_size - accounted,
        "lands_left": lands_left,
        "lands_total": lands_total,
        "land_odds": {
            str(n): _pct(odds_within(lands_left, library_size, n)) for n in ODDS_HORIZONS
        },
        "cards": cards,
        "updated_at": updated_at,
    }


def idle_overlay_state(
    *,
    game_active: bool = False,
    mid_game_attach: bool = False,
    deck_name: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """The payload between games or when the library cannot be known."""
    return build_overlay_state(
        deck=[],
        departures={},
        returns={},
        library_size=0,
        card_info=lambda _name: (None, None, None),
        game_active=game_active,
        mid_game_attach=mid_game_attach,
        deck_name=deck_name,
        updated_at=updated_at,
    )
