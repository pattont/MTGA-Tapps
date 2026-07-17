"""Canonical queue and format normalization for constructed MTGA matches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


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


def normalize_match_format(
    raw_format: Optional[str], *, default_best_of: int = 1
) -> NormalizedFormat:
    """Return canonical display metadata for a raw Arena queue/format identifier."""
    raw = raw_format if isinstance(raw_format, str) and raw_format.strip() else "Unknown"
    normalized = normalize_match_text(raw)
    if not normalized or normalized == "unknown":
        # Untagged queues are the Play queue in practice: unranked.
        best_of = 3 if default_best_of == 3 else 1
        return NormalizedFormat(
            raw="Unknown",
            label=_standard_label(best_of, ranked=False),
            family="standard",
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
    if "historicbrawl" in normalized:
        return NormalizedFormat(
            raw=raw, label="Historic Brawl", family="historic_brawl", best_of=1, is_brawl=True
        )
    if "brawl" in normalized:
        return NormalizedFormat(raw=raw, label="Brawl", family="brawl", best_of=1, is_brawl=True)
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
    if normalized in {"historicplay", "historic"}:
        return NormalizedFormat(raw=raw, label="Historic", family="historic", best_of=1)
    if normalized in {"explorerplay", "explorer", "pioneerplay", "pioneer"}:
        return NormalizedFormat(raw=raw, label="Explorer", family="explorer", best_of=1)
    if normalized in {"timelessplay", "timeless"}:
        return NormalizedFormat(raw=raw, label="Timeless", family="timeless", best_of=1)
    if normalized == "alchemy":
        return NormalizedFormat(raw=raw, label="Alchemy", family="alchemy", best_of=1)
    if "traditionalstandard" in normalized:
        ranked = "ladder" in normalized
        return NormalizedFormat(
            raw=raw, label=_standard_label(3, ranked=ranked), family="standard", best_of=3
        )
    if "historic" in normalized and "brawl" not in normalized:
        return NormalizedFormat(raw=raw, label="Historic", family="historic", best_of=1)
    if "explorer" in normalized or "pioneer" in normalized:
        return NormalizedFormat(raw=raw, label="Explorer", family="explorer", best_of=1)
    if "timeless" in normalized:
        return NormalizedFormat(raw=raw, label="Timeless", family="timeless", best_of=1)
    if "standard" in normalized:
        best_of = 3 if "traditional" in normalized or "bestof3" in normalized else 1
        ranked = "ladder" in normalized or "ranked" in normalized
        return NormalizedFormat(
            raw=raw, label=_standard_label(best_of, ranked=ranked), family="standard", best_of=best_of
        )
    return NormalizedFormat(raw=raw, label=raw, family="unknown", best_of=1)


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
