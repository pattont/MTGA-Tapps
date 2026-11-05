"""Deck Manager deck colors from Arena's local card DB, scored like the Overview's."""

from __future__ import annotations

import threading
import time

from .colors import BASIC_LAND_COLORS, score_deck_colors

# Rebuilt after this long so a set Arena downloads mid-session gains colors.
_TTL_SECONDS = 600
_LOCK = threading.Lock()
_INDEX = None
_BUILT = 0.0

# The commander's pips matter as much as the main deck's; a sideboard does not.
COLOR_SECTIONS = ("Deck", "Commander", "Companion")


_REFRESHING = False


def _build():
    try:
        from .card_database import CardDatabase

        return CardDatabase().deck_color_index()
    except Exception:
        return ({}, {})


def _refresh():
    """Rebuild an expired index off the request path (an Arena deck read waits on it)."""
    global _INDEX, _BUILT, _REFRESHING
    index = _build()
    with _LOCK:
        # Keep the old index when the rebuild came back empty (a transient failure).
        if index[0]:
            _INDEX = index
        _BUILT, _REFRESHING = time.monotonic(), False


def _index():
    global _INDEX, _BUILT, _REFRESHING
    with _LOCK:
        if _INDEX is None:
            _INDEX, _BUILT = _build(), time.monotonic()
        elif time.monotonic() - _BUILT > _TTL_SECONDS and not _REFRESHING:
            # Serve the current index now; a set Arena downloaded mid-session
            # gains colors on the next read.
            _REFRESHING = True
            threading.Thread(target=_refresh, name="deck-color-index", daemon=True).start()
        return _INDEX


def warm():
    """Build the index ahead of the first deck read."""
    _index()


def deck_colors(cards) -> str:
    """WUBRG letters ("C" when colorless, "" when unknown) for saved-deck cards.

    ``cards`` are dicts with section, quantity, name and an optional arena_id;
    text imports have no arena_id and are matched by name instead.
    """
    by_id, by_name = _index()
    rows = []
    for card in cards:
        if card.get("section") not in COLOR_SECTIONS:
            continue
        name = str(card.get("name") or "")
        basic = BASIC_LAND_COLORS.get(name)
        row = (
            ("Land", "", basic)
            if basic is not None
            else by_id.get(card.get("arena_id") or 0)
            or by_name.get(name)
            or by_name.get(name.split(" // ")[0].strip())
        )
        if row:
            rows.append((*row, card.get("quantity") or 1))
    return score_deck_colors(rows)
