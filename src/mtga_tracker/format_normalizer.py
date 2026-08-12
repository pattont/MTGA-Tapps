"""Canonical queue and format normalization for constructed MTGA matches."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

#: Families whose Bo1/Bo3 split comes from the queue name alone — and can
#: therefore be upgraded when the caller has authoritative knowledge (Arena's
#: matchWinCondition) that the match is actually best-of-three.
_BEST_OF_UPGRADABLE_FAMILIES = frozenset(
    {"standard", "historic", "explorer", "timeless", "alchemy", "direct_challenge", "unknown", "event"}
)


@dataclass(frozen=True)
class NormalizedFormat:
    """Normalized constructed queue/format metadata."""

    raw: str
    label: str
    family: str
    best_of: int
    is_brawl: bool = False
    is_midweek: bool = False


def normalize_match_text(value: Optional[str]) -> str:
    """Normalize strings for loose event/format matching."""
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def is_momir_format(value: Optional[str]) -> bool:
    """Return True when Arena metadata identifies a Momir event or format."""
    return "momir" in normalize_match_text(value)


def is_midweek_format(value: Optional[str]) -> bool:
    """Return True when Arena metadata identifies a Midweek Magic event."""
    normalized = normalize_match_text(value)
    return normalized.startswith("mwm") or "midweekmagic" in normalized


def is_welcome_deck_format(value: Optional[str]) -> bool:
    """Return True when Arena metadata identifies a Welcome Deck event.

    Welcome Deck Duels (e.g. "Welcome Deck Duels HOB" / Welcome_Deck_...)
    pit one pre-made deck against another — no deck building, no ladder
    relevance — so they stay out of saved analytics. Matching the
    "welcomedeck" stem keeps ordinary event names containing "welcome"
    alone from being swept up.
    """
    return "welcomedeck" in normalize_match_text(value)


def is_jump_in_format(value: Optional[str]) -> bool:
    """Return True when Arena metadata identifies a Jump In! event.

    Covers queue/event identifiers like Jump_In_MSH and Jumpstart variants.
    """
    normalized = normalize_match_text(value)
    return normalized.startswith(("jumpin", "jumpstart"))


def friendly_midweek_label(raw_format: str) -> str:
    """Convert MWM event identifiers into readable Midweek Magic labels."""
    text = re.sub(r"^MWM[_-]?", "", raw_format.strip(), flags=re.IGNORECASE)
    text = re.sub(r"[_-]?\d{8}$", "", text)
    text = re.sub(r"[_-]+", " ", text).strip()
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return f"Midweek Magic - {text}" if text else "Midweek Magic"


def friendly_limited_label(raw_format: str) -> str:
    """Convert limited event identifiers into readable labels."""
    raw = raw_format.strip()
    patterns = (
        (r"^PremierDraft[_-]?", "Premier Draft"),
        (r"^QuickDraft[_-]?", "Quick Draft"),
        (r"^TradDraft[_-]?", "Traditional Draft"),
        (r"^TraditionalDraft[_-]?", "Traditional Draft"),
        (r"^Sealed[_-]?", "Sealed"),
        (r"^Trad[_-]?Sealed[_-]?", "Traditional Sealed"),
        (r"^TraditionalSealed[_-]?", "Traditional Sealed"),
    )
    for pattern, prefix in patterns:
        text = re.sub(pattern, "", raw, flags=re.IGNORECASE)
        if text != raw:
            text = re.sub(r"[_-]?\d{8}$", "", text)
            text = re.sub(r"[_-]+", " ", text).strip()
            text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return f"{prefix} - {text}" if text else prefix
    return raw


def _standard_label(best_of: int, *, ranked: bool) -> str:
    tier = "Ranked" if ranked else "Unranked"
    return f"Standard Best-of-{best_of} ({tier})"


def _prettify_event(raw: str) -> str:
    """Humanize an event identifier: strip date suffixes, split words."""
    text = re.sub(r"[_-]?\d{8}$", "", raw.strip())
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return re.sub(r"\s+", " ", text).strip() or raw


def normalize_match_format(
    raw_format: Optional[str], *, default_best_of: int = 1
) -> NormalizedFormat:
    """Return canonical display metadata for a raw Arena queue/format identifier.

    default_best_of expresses the caller's own knowledge of the match length
    (Arena's matchWinCondition via the tracker's match_type, or the stored
    matches.best_of). When it says 3 but the queue string alone reads as Bo1
    — e.g. a Bo3 match whose format resolved to plain "Historic_Play" — the
    caller's knowledge wins and the result is upgraded to Best-of-3.
    """
    result = _normalize_match_format_inner(raw_format, default_best_of=default_best_of)
    if (
        default_best_of == 3
        and result.best_of == 1
        and result.family in _BEST_OF_UPGRADABLE_FAMILIES
    ):
        result = replace(
            result, best_of=3, label=result.label.replace("Best-of-1", "Best-of-3")
        )
    return result


def _normalize_match_format_inner(
    raw_format: Optional[str], *, default_best_of: int = 1
) -> NormalizedFormat:
    """normalize_match_format without the caller-knowledge best-of upgrade."""
    raw = raw_format if isinstance(raw_format, str) and raw_format.strip() else "Unknown"
    normalized = normalize_match_text(raw)
    if not normalized or normalized == "unknown":
        best_of = 3 if default_best_of == 3 else 1
        return NormalizedFormat(
            raw="Unknown",
            label="Unknown",
            family="unknown",
            best_of=best_of,
        )
    if normalized.startswith("mwm") or normalized.startswith("midweekmagic"):
        return NormalizedFormat(
            raw=raw,
            label=friendly_midweek_label(raw),
            family="midweek_magic",
            best_of=1,
            is_midweek=True,
        )
    if normalized.startswith(("premierdraft", "quickdraft", "traddraft", "traditionaldraft")):
        return NormalizedFormat(
            raw=raw,
            label=friendly_limited_label(raw),
            family="draft",
            best_of=1,
        )
    if normalized.startswith(("sealed", "tradsealed", "traditionalsealed")):
        return NormalizedFormat(
            raw=raw,
            label=friendly_limited_label(raw),
            family="sealed",
            best_of=1,
        )
    # Arena's Brawl queues (verified against a real log):
    #   Play_Brawl_Historic → the unranked 100-card play queue → "Historic Brawl"
    #   Brawl_Ladder        → the ranked Brawl queue          → "Brawl (Ranked)"
    #   Play_Brawl          → the unranked Standard Brawl queue → "Standard Brawl"
    if "historicbrawl" in normalized or "brawlhistoric" in normalized:
        return NormalizedFormat(
            raw=raw, label="Historic Brawl", family="historic_brawl", best_of=1, is_brawl=True
        )
    if "brawlladder" in normalized or ("brawl" in normalized and "ranked" in normalized):
        return NormalizedFormat(
            raw=raw, label="Brawl (Ranked)", family="brawl", best_of=1, is_brawl=True
        )
    if "standardbrawl" in normalized or "playbrawl" in normalized:
        return NormalizedFormat(
            raw=raw, label="Standard Brawl", family="standard_brawl", best_of=1, is_brawl=True
        )
    if "brawl" in normalized:
        return NormalizedFormat(raw=raw, label="Brawl", family="brawl", best_of=1, is_brawl=True)
    if "directgame" in normalized or "directchallenge" in normalized:
        best_of = 3 if "traditional" in normalized or "bestof3" in normalized else 1
        return NormalizedFormat(
            raw=raw, label="Direct Challenge", family="direct_challenge", best_of=best_of
        )
    if "jumpin" in normalized or "jumpstart" in normalized:
        return NormalizedFormat(raw=raw, label="Jump In!", family="jump_in", best_of=1)
    if "colorchallenge" in normalized or normalized.startswith("npe"):
        return NormalizedFormat(
            raw=raw, label="Color Challenge", family="color_challenge", best_of=1
        )
    # Scheduled events keep their (prettified) own name: Arena Opens,
    # Qualifiers, Metagame Challenges, Festivals, championship qualifiers.
    if any(
        token in normalized
        for token in ("arenaopen", "qualifier", "metagamechallenge", "festival", "arenachampionship")
    ):
        best_of = 3 if any(
            token in normalized for token in ("traditional", "bestof3", "bo3", "weekend", "day2")
        ) else 1
        return NormalizedFormat(raw=raw, label=_prettify_event(raw), family="event", best_of=best_of)
    if normalized in {"traditionalstandard", "constructedbestof3", "bestof3", "traditionalladder"}:
        # "Ladder" queues are ranked; Constructed_BestOf3/Play are unranked.
        ranked = "ladder" in normalized
        return NormalizedFormat(
            raw=raw, label=_standard_label(3, ranked=ranked), family="standard", best_of=3
        )
    if normalized in {"standard", "ladder", "play", "constructedbestof1", "bestof1"}:
        ranked = normalized == "ladder"
        best_of = 3 if normalized == "ladder" and default_best_of == 3 else 1
        return NormalizedFormat(
            raw=raw, label=_standard_label(best_of, ranked=ranked), family="standard", best_of=best_of
        )
    if "traditionalstandard" in normalized:
        ranked = "ladder" in normalized
        return NormalizedFormat(
            raw=raw, label=_standard_label(3, ranked=ranked), family="standard", best_of=3
        )
    # Non-Standard constructed families. "Traditional" queues are Best-of-3
    # (e.g. Traditional_Historic_Play) and Ranked/Ladder queues are ranked —
    # mirror the Standard labels so Bo1/Bo3 records don't get lumped together.
    for token, name, family in (
        ("historic", "Historic", "historic"),
        ("explorer", "Explorer", "explorer"),
        ("pioneer", "Explorer", "explorer"),
        ("timeless", "Timeless", "timeless"),
        ("alchemy", "Alchemy", "alchemy"),
    ):
        if token in normalized and not (token == "historic" and "brawl" in normalized):
            best_of = 3 if "traditional" in normalized or "bestof3" in normalized else 1
            ranked = "ranked" in normalized or "ladder" in normalized
            return NormalizedFormat(
                raw=raw,
                label=f"{name} Best-of-{best_of} ({'Ranked' if ranked else 'Unranked'})",
                family=family,
                best_of=best_of,
            )
    if "standard" in normalized:
        best_of = 3 if "traditional" in normalized or "bestof3" in normalized else 1
        ranked = "ladder" in normalized or "ranked" in normalized
        return NormalizedFormat(
            raw=raw, label=_standard_label(best_of, ranked=ranked), family="standard", best_of=best_of
        )
    # Unknown queue: prettify rather than leaking the raw identifier, and
    # still honor Bo3 markers so future modes get sane match grouping.
    best_of = 3 if "traditional" in normalized or "bestof3" in normalized else 1
    return NormalizedFormat(raw=raw, label=_prettify_event(raw), family="unknown", best_of=best_of)


def format_label(raw_format: Optional[str], *, default_best_of: int = 1) -> str:
    """Return the user-facing label for a raw Arena queue/format identifier."""
    return normalize_match_format(raw_format, default_best_of=default_best_of).label


def trusted_queue_raw(
    format_value: Optional[str], queue: Optional[str], event_name: Optional[str]
) -> Optional[str]:
    """Return the queue/event raw value that should own match format when it is unambiguous."""
    values = [
        value.strip() for value in (event_name, queue) if isinstance(value, str) and value.strip()
    ]
    if values and len(set(values)) == 1:
        raw = values[0]
        normalized = normalize_match_format(raw)
        if normalized.family != "unknown":
            return raw
    if isinstance(format_value, str) and format_value.strip():
        return format_value.strip()
    return None
