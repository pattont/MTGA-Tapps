"""Complete MTGA log entry buffering.

Arena writes some events as one physical line and others as a header followed
by continuation JSON. This module groups raw file lines into complete entries
before higher-level parsing runs.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional


@dataclass(frozen=True)
class LogEntry:
    """A complete raw Arena log entry."""

    header: str
    body: str
    first_line: str


class LineBuffer:
    """Accumulate raw Player.log lines into complete log entries."""

    _HEADER_RE = re.compile(r"^\[(UnityCrossThreadLogger|Client GRE|ConnectionManager)\]")
    _DATE_AFTER_HEADER_RE = re.compile(r"^\[[^\]]+\]\s*\d")

    def __init__(self) -> None:
        self._header: Optional[str] = None
        self._lines: List[str] = []
        self._saw_entry = False

    def push_line(self, line: str) -> List[LogEntry]:
        """Push one physical log line and return completed entries."""
        line = line.rstrip("\r\n")
        header = self._detect_header(line)
        if header is None:
            if self._header is not None:
                self._lines.append(line)
            return []

        completed: List[LogEntry] = []
        if self._header is not None:
            completed.append(self._take_entry())

        self._saw_entry = True
        if self._is_single_line_header(header, line):
            completed.append(LogEntry(header=header, body=line, first_line=line))
            self._header = None
            self._lines = []
        else:
            self._header = header
            self._lines = [line]
        return completed

    def flush(self) -> List[LogEntry]:
        """Return the currently buffered entry, if any."""
        if self._header is None:
            return []
        return [self._take_entry()]

    def reset(self) -> None:
        """Clear buffered state after file rotation/truncation."""
        self._header = None
        self._lines = []
        self._saw_entry = False

    def _take_entry(self) -> LogEntry:
        first_line = self._lines[0] if self._lines else ""
        entry = LogEntry(
            header=self._header or "",
            body="\n".join(self._lines),
            first_line=first_line,
        )
        self._header = None
        self._lines = []
        return entry

    @classmethod
    def _detect_header(cls, line: str) -> Optional[str]:
        if line.startswith("Matchmaking:"):
            return "Matchmaking:"
        if line.startswith("DETAILED LOGS:"):
            return "DETAILED LOGS:"
        match = cls._HEADER_RE.match(line)
        if match:
            return f"[{match.group(1)}]"
        return None

    @classmethod
    def _is_single_line_header(cls, header: str, line: str) -> bool:
        if header in {"[ConnectionManager]", "Matchmaking:", "DETAILED LOGS:"}:
            return True
        if header == "[Client GRE]":
            return False
        if header == "[UnityCrossThreadLogger]":
            lower = line.lower()
            if any(
                token in lower
                for token in (
                    "gretoclientevent",
                    "clienttogremessage",
                    "clienttogreuimessage",
                    "gamestatemessage",
                )
            ):
                return False
            return cls._DATE_AFTER_HEADER_RE.match(line) is None
        return True
