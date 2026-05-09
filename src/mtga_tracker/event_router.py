"""Lightweight log-entry router and parser health counters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .log_entry import LogEntry
from .log_json import parse_json_from_body


@dataclass
class RouterStats:
    """Counters describing parser health for a tracker session."""

    routed_count: int = 0
    unknown_count: int = 0
    timestamp_failure_count: int = 0
    malformed_json_count: int = 0


@dataclass(frozen=True)
class RoutedLogEvent:
    """A classified complete log entry."""

    category: str
    entry: LogEntry
    data: Optional[Any] = None


class EventRouter:
    """Classify complete log entries before tracker-specific interpretation."""

    def __init__(self) -> None:
        self.stats = RouterStats()

    def route(self, entry: LogEntry) -> RoutedLogEvent:
        """Return the category for a complete log entry and update health counters."""
        body = entry.body
        body_lower = body.lower()
        data = parse_json_from_body(body)
        if self._looks_like_json_entry(body) and data is None:
            self.stats.malformed_json_count += 1
        if self._looks_like_timestamped_entry(entry) and entry.timestamp is None:
            self.stats.timestamp_failure_count += 1

        category = self._category_for(body_lower, data)
        if category == "unknown":
            self.stats.unknown_count += 1
        else:
            self.stats.routed_count += 1
        return RoutedLogEvent(category=category, entry=entry, data=data)

    @staticmethod
    def _category_for(body_lower: str, data: Any) -> str:
        if "detailed logs:" in body_lower:
            return "metadata"
        if "gretoclientevent" in body_lower or "gamestatemessage" in body_lower:
            return "gre"
        if "clienttogremessage" in body_lower or "clienttogreuimessage" in body_lower:
            return "client_action"
        if "matchgameroomstatechangedevent" in body_lower:
            return "match_state"
        if "starthook(" in body_lower and isinstance(data, dict) and (
            "DeckSummaries" in data or "Decks" in data
        ):
            return "deck_collection"
        if "connectionmanager" in body_lower or body_lower.startswith("matchmaking:"):
            return "connection"
        return "unknown"

    @staticmethod
    def _looks_like_json_entry(body: str) -> bool:
        if "{" not in body and "[" not in body:
            return False
        lower = body.lower()
        return any(
            marker in lower
            for marker in (
                "gretoclientevent",
                "clienttogremessage",
                "matchgameroomstatechangedevent",
                "starthook(",
            )
        )

    @staticmethod
    def _looks_like_timestamped_entry(entry: LogEntry) -> bool:
        first = entry.first_line
        if not first.startswith("[") or "]" not in first:
            return False
        after = first.split("]", 1)[1].lstrip()
        return bool(after and after[0].isdigit())
