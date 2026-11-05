"""Deck tile art from local data, so tiles skip Scryfall's rate-limited API.

A page of deck tiles asking api.scryfall.com for ~100 images at once gets
turned away (and its by-name lookup allows only 2 requests a second), which
left many tiles on their placeholder. Each tile instead gets:

- ``art_url``: a cards.scryfall.io art crop when the printing is in the local
  ``set|collector`` → Scryfall id cache (no request limit), and
- ``art_print``: the printing's Scryfall ``set/number``, for the page to try
  before falling back to a name lookup.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from . import replay_builder as rb

_lock = threading.Lock()
_index: Optional[Dict[int, Tuple[str, str, str]]] = None
_by_name: Optional[Dict[str, List[Tuple[str, str]]]] = None


def _printings():
    """Arena's card DB as arena id → (name, set, number) and name → printings."""
    global _index, _by_name
    with _lock:
        if _index is None:
            try:
                from .card_database import CardDatabase

                _index = CardDatabase().export_index_by_arena_id() or {}
            except Exception:  # noqa: BLE001 - a missing Arena install is normal
                _index = {}
            names: Dict[str, List[Tuple[str, str]]] = {}
            for name, set_code, collector in _index.values():
                if name and set_code and collector:
                    # Double-faced cards answer to their full name and their front face.
                    for key in {name.lower(), name.split(" // ")[0].strip().lower()}:
                        names.setdefault(key, []).append((set_code, collector))
            _by_name = names
        return _index, _by_name or {}


def tile_art(
    arena_id: Optional[int] = None,
    name: Optional[str] = None,
    set_code: Optional[str] = None,
    collector: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """``{"art_url", "art_print"}`` for one tile card; both None when nothing local knows it."""
    index, by_name = _printings()
    choices: List[Tuple[str, str]] = []
    if set_code and collector:
        choices.append((set_code, str(collector)))
    entry = index.get(int(arena_id)) if isinstance(arena_id, int) and arena_id > 0 else None
    if entry and entry[1] and entry[2]:
        choices.append((entry[1], entry[2]))
    if not choices and name:
        # A list without printings: any of the card's printings will do.
        choices = by_name.get(name.lower()) or by_name.get(
            name.split(" // ")[0].strip().lower(), []
        )
    for chosen_set, number in choices:
        url = rb.cdn_image_url(chosen_set, number, "art_crop")
        if url:
            return {"art_url": url, "art_print": f"{chosen_set.lower()}/{number}"}
    first = choices[0] if choices else None
    return {"art_url": None, "art_print": f"{first[0].lower()}/{first[1]}" if first else None}
