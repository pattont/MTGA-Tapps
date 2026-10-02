"""Pure parsing of Arena lists in YouTube descriptions and creator deck names."""

from __future__ import annotations

import re
from dataclasses import dataclass

import emoji


_MAIN_HEADER = re.compile(r"^deck(?:\s*list)?\s*:?$", re.IGNORECASE)
_CARD_ROW = re.compile(r"^([1-9]\d{0,2})\s+(.+)$")
_SECTIONS = {"sideboard": "Sideboard", "commander": "Commander", "companion": "Companion"}
_PLATFORM = re.compile(r"\b(?:mtg\s+arena|mtga|magic:?\s+the\s+gathering\s+arena)\b", re.I)
_FORMATS = (
    "Standard Brawl",
    "Historic Brawl",
    "Brawl",
    "Timeless",
    "Historic",
    "Alchemy",
    "Explorer",
    "Pioneer",
    "Standard",
    "Draft",
    "Sealed",
)


@dataclass(frozen=True)
class ParsedDeck:
    text: str
    main_count: int
    commander_count: int


def format_from_video(title: str, description: str) -> str:
    for text in (title, description):
        for label in _FORMATS:
            if re.search(r"\b" + re.escape(label) + r"\b", text, re.I):
                return label
    return "Unknown"


def clean_video_title(title: str) -> str:
    """Strip emoji and trailing metadata, preserving real title pipes and Unicode."""
    parts = emoji.replace_emoji(title, replace=" ").split("|")
    while len(parts) > 1:
        suffix = parts[-1].strip()
        if _PLATFORM.search(suffix) or re.fullmatch(
            r"(?:standard|historic|timeless|alchemy|explorer|pioneer|brawl|draft|sealed)"
            r"(?:\s+(?:bo[13]|best[ -]of[ -][13]))?",
            suffix,
            re.I,
        ):
            parts.pop()
        else:
            break
    return re.sub(r"\s+", " ", " | ".join(part.strip() for part in parts)).strip(" |–—-")


def import_deck_name(title: str, creator_label: str) -> str:
    name = clean_video_title(title)
    if not name:
        raise ValueError("The video title is empty after cleanup.")
    label = clean_video_title(creator_label).strip("() ")
    suffix = f" ({label})" if label else ""
    return name if not suffix or name.endswith(suffix) else name + suffix


def parse_description(description: str, format_label: str = "Unknown") -> ParsedDeck | None:
    """Return one complete list, or None when no standalone deck heading exists."""
    lines = [line.strip() for line in description.splitlines()]
    candidates: dict[str, ParsedDeck] = {}
    invalid = False
    for index, line in enumerate(lines):
        if not _MAIN_HEADER.fullmatch(line):
            continue
        # Arena exports can put Commander/Companion before Deck.
        start = index
        for previous in range(index - 1, -1, -1):
            preceding = lines[previous]
            if not preceding or _CARD_ROW.fullmatch(preceding):
                continue
            if preceding.lower().rstrip(":") in {"commander", "companion"}:
                start = previous
            break
        sections: dict[str, list[str]] = {}
        section = "Deck"
        malformed = False
        for position in range(start, len(lines)):
            row = lines[position]
            if not row:
                continue
            if _MAIN_HEADER.fullmatch(row):
                if position > index:
                    break
                section = "Deck"
                sections.setdefault(section, [])
                continue
            heading = _SECTIONS.get(row.lower().rstrip(":"))
            if heading:
                section = heading
                sections.setdefault(section, [])
                continue
            match = _CARD_ROW.fullmatch(row)
            if match:
                if int(match[1]) > 250 or "http" in match[2].lower():
                    malformed = True
                    break
                sections.setdefault(section, []).append(row)
                continue
            if re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\b", row):
                break  # Video chapters commonly follow Sloth's complete list.
            if re.match(r"^\d", row):
                malformed = True
            break
        main = sections.get("Deck", [])
        main_count = sum(int(row.split()[0]) for row in main)
        commander_count = sum(int(row.split()[0]) for row in sections.get("Commander", []))
        minimum = 40 if format_label in {"Draft", "Sealed"} else 60
        count = main_count + commander_count if "Brawl" in format_label else main_count
        if malformed or not main or count < minimum:
            invalid = True
            continue
        text = "\n\n".join(
            heading + "\n" + "\n".join(sections[heading])
            for heading in ("Commander", "Companion", "Deck", "Sideboard")
            if sections.get(heading)
        )
        candidates[text] = ParsedDeck(text, main_count, commander_count)
    if len(candidates) > 1:
        raise ValueError("The description contains multiple different decklists.")
    if not candidates and invalid:
        raise ValueError("The description's decklist is incomplete or malformed.")
    return next(iter(candidates.values()), None)
