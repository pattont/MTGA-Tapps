"""Color-identity normalization and MTG color-combo naming."""

from __future__ import annotations

from typing import Iterable, Optional

WUBRG_ORDER = "WUBRG"

#: "C" is real color identity in MTG: a deck of Eldrazi and artifacts is
#: colorless, not "no data". Producers append a C per known-colorless card;
#: normalize_colors keeps it only when no actual color is present.
COLORLESS = "C"

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
    """Return the WUBRG-ordered unique color letters found in value.

    "C" survives only on its own: a colorless marker next to real colors is
    just noise (a Sol Ring in a Gruul deck), but with no colors at all it
    means the thing is genuinely colorless — and that shows as "C"."""
    if not value:
        return ""
    seen = {str(ch).upper() for ch in value}
    letters = "".join(letter for letter in WUBRG_ORDER if letter in seen)
    if letters:
        return letters
    return COLORLESS if COLORLESS in seen else ""


def color_combo_label(value: Optional[Iterable[str]]) -> Optional[str]:
    """Return the community name for a color combination, or None when unknown."""
    colors = normalize_colors(value)
    if not colors:
        return None
    if colors == COLORLESS:
        return "Colorless"
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


#: Basic (and snow) lands imply their color the moment they hit the table —
#: Arena's card DB gives lands no color identity, so without this a side would
#: read as colorless until its first spell.
BASIC_LAND_COLORS = {
    "Plains": "W",
    "Island": "U",
    "Swamp": "B",
    "Mountain": "R",
    "Forest": "G",
    "Snow-Covered Plains": "W",
    "Snow-Covered Island": "U",
    "Snow-Covered Swamp": "B",
    "Snow-Covered Mountain": "R",
    "Snow-Covered Forest": "G",
    "Wastes": "C",
}


def colors_from_label(label: Optional[str]) -> Optional[str]:
    """Reverse of color_combo_label for the leading word(s) of an archetype
    name: "Gruul Stompy" -> "RG", "Mono-Red Aggro" -> "R", "Esper Control"
    -> "WUB", "5c Legends" -> "WUBRG", "Colorless Eldrazi" -> "C". None when
    the name does not start with a recognised color word."""
    if not label:
        return None
    head = str(label).strip().split(" ", 1)[0]
    if head.lower() == "5c":
        return WUBRG_ORDER
    if head.lower() == "colorless":
        return COLORLESS
    if head.lower().startswith("mono-"):
        color_name = head[5:].strip().capitalize()
        for letter, name in COLOR_NAMES.items():
            if name == color_name:
                return letter
        return None
    for letters, name in COMBO_NAMES.items():
        if name.lower() == head.lower():
            return letters
    return None
