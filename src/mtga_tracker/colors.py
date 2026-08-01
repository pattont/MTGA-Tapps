"""Color-identity normalization and MTG color-combo naming."""

from __future__ import annotations

from typing import Iterable, Optional

WUBRG_ORDER = "WUBRG"

COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}

# Canonical keys are WUBRG-ordered strings.
COMBO_NAMES = {
    "WU": "Azorius",
    "WR": "Boros",
    "UB": "Dimir",
    "BG": "Golgari",
    "RG": "Gruul",
    "UR": "Izzet",
    "WB": "Orzhov",
    "BR": "Rakdos",
    "WG": "Selesnya",
    "UG": "Simic",
    "WUG": "Bant",
    "WUB": "Esper",
    "UBR": "Grixis",
    "BRG": "Jund",
    "WRG": "Naya",
    "WBG": "Abzan",
    "WUR": "Jeskai",
    "WBR": "Mardu",
    "UBG": "Sultai",
    "URG": "Temur",
    "WBRG": "Dune",
    "UBRG": "Glint",
    "WURG": "Ink",
    "WUBG": "Witch",
    "WUBR": "Yore",
}

# Arena's Raw_CardDatabase encodes colors as integers.
ARENA_COLOR_CODES = {1: "W", 2: "U", 3: "B", 4: "R", 5: "G"}


def normalize_colors(value: Optional[Iterable[str]]) -> str:
    """Return the WUBRG-ordered unique color letters found in value."""
    if not value:
        return ""
    seen = {str(ch).upper() for ch in value}
    return "".join(letter for letter in WUBRG_ORDER if letter in seen)


def color_combo_label(value: Optional[Iterable[str]]) -> Optional[str]:
    """Return the community name for a color combination, or None when unknown."""
    colors = normalize_colors(value)
    if not colors:
        return None
    if len(colors) == 1:
        return f"Mono-{COLOR_NAMES[colors]}"
    if len(colors) == 5:
        return "5c"
    named = COMBO_NAMES.get(colors)
    if named:
        return named
    return colors


def arena_color_codes_to_letters(raw: Optional[str]) -> str:
    """Convert Arena's '1,3'-style color lists to WUBRG letters."""
    if not raw:
        return ""
    letters = []
    for part in str(raw).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            letter = ARENA_COLOR_CODES.get(int(part))
        except ValueError:
            letter = part.upper() if part.upper() in COLOR_NAMES else None
        if letter:
            letters.append(letter)
    return normalize_colors(letters)
