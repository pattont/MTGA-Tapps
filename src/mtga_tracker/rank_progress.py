"""Parse and normalize MTGA constructed rank snapshots."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from .log_json import parse_json_from_body
from .log_timestamp import extract_entry_timestamp


def parse_constructed_rank_snapshot(line: str) -> Optional[Dict[str, Any]]:
    """Return normalized constructed rank data from a rank response entry."""
    if "<== RankGetCombinedRankInfo(" not in line:
        return None
    payload = parse_json_from_body(line)
    if not isinstance(payload, dict) or "constructedSeasonOrdinal" not in payload:
        return None
    return _normalized_rank_payload(payload, prefix="constructed")


def parse_limited_rank_snapshot(line: str) -> Optional[Dict[str, Any]]:
    """Return normalized limited (draft/sealed) rank data from a rank response entry."""
    if "<== RankGetCombinedRankInfo(" not in line:
        return None
    payload = parse_json_from_body(line)
    if not isinstance(payload, dict) or "limitedSeasonOrdinal" not in payload:
        return None
    return _normalized_rank_payload(payload, prefix="limited")


def _normalized_rank_payload(payload: Dict[str, Any], *, prefix: str) -> Optional[Dict[str, Any]]:
    """Normalize one rank family ("constructed" or "limited") from the payload."""
    try:
        season_ordinal = int(payload[f"{prefix}SeasonOrdinal"])
        rank_level = int(payload.get(f"{prefix}Level") or 1)
        raw_step = int(payload.get(f"{prefix}Step") or 0)
    except (TypeError, ValueError, KeyError):
        return None

    rank_class = str(payload.get(f"{prefix}Class") or "").strip()
    if not rank_class:
        return None

    def optional_int(key: str) -> Optional[int]:
        value = payload.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    # Arena reports the number of filled pips shown in the client. A missing step
    # is normalized to zero above; constructedStep 1 is displayed as 1/6.
    display_step = max(0, raw_step)
    return {
        "season_ordinal": season_ordinal,
        "rank_class": rank_class,
        "rank_level": rank_level,
        "rank_step": display_step,
        "rank_steps": 6,
        "raw_step": raw_step,
        "matches_won": optional_int(f"{prefix}MatchesWon"),
        "matches_lost": optional_int(f"{prefix}MatchesLost"),
        "mythic_percentile": optional_int(f"{prefix}Percentile"),
        "mythic_rank": optional_int(f"{prefix}LeaderboardPlace"),
    }


def iter_constructed_rank_snapshots(
    log_path: Path | str,
) -> Iterator[Tuple[datetime, Dict[str, Any]]]:
    """Yield timestamped constructed-rank responses from an existing Player.log."""
    last_timestamp: Optional[datetime] = None
    awaiting_payload = False
    response_prefix = ""
    with Path(log_path).open("r", encoding="utf-8", errors="ignore") as stream:
        for raw_line in stream:
            line = raw_line.rstrip("\r\n")
            timestamp = extract_entry_timestamp(line)
            if timestamp is not None:
                last_timestamp = timestamp
            if "<== RankGetCombinedRankInfo(" in line:
                awaiting_payload = True
                response_prefix = line
                continue
            if not awaiting_payload:
                continue
            if line.lstrip().startswith("{"):
                snapshot = parse_constructed_rank_snapshot(f"{response_prefix} {line}")
                if snapshot is not None and last_timestamp is not None:
                    yield last_timestamp, snapshot
                awaiting_payload = False
                response_prefix = ""
            elif line.startswith("["):
                awaiting_payload = False
                response_prefix = ""
