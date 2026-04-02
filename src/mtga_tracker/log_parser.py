"""MTGA log file parser.

Parses the MTGA Player.log file to extract game events.
"""

import json
import os
import platform
import re
from pathlib import Path
from typing import Optional, Generator, Dict, Any, List, Tuple


class MTGALogParser:
    """Parser for MTGA Player.log files."""

    def __init__(self, log_path: Optional[str] = None):
        """Initialize the log parser.

        Args:
            log_path: Optional path to the MTGA log file. If not provided,
                      will attempt to find it automatically.
        """
        self.log_path = log_path or self._find_log_path()
        self.last_position = 0

    @staticmethod
    def _find_log_path() -> str:
        """Find the MTGA log file path based on the operating system.

        Returns:
            Path to the Player.log file.

        Raises:
            FileNotFoundError: If the log file cannot be found.
        """
        system = platform.system()

        if system == "Windows":
            # Windows: %APPDATA%\LocalLow\Wizards Of The Coast\MTGA\Player.log
            appdata = os.getenv("APPDATA")
            if appdata:
                # LocalLow is a sibling of Roaming (APPDATA)
                local_low = Path(appdata).parent / "LocalLow"
                log_path = local_low / "Wizards Of The Coast" / "MTGA" / "Player.log"
            else:
                raise FileNotFoundError("Could not find APPDATA environment variable")
        elif system == "Darwin":
            # macOS: ~/Library/Logs/Wizards Of The Coast/MTGA/Player.log
            log_path = (
                Path.home() / "Library" / "Logs" / "Wizards Of The Coast" / "MTGA" / "Player.log"
            )
        else:
            raise FileNotFoundError(f"Unsupported operating system: {system}")

        if not log_path.exists():
            raise FileNotFoundError(
                f"MTGA log file not found at {log_path}. "
                f"Make sure MTGA is installed and has been run at least once."
            )

        return str(log_path)

    def read_new_lines(self) -> Generator[str, None, None]:
        """Read new lines from the log file since last read.

        Yields:
            New lines from the log file.
        """
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                # If file was truncated or rotated (e.g. new match, MTGA restart), start from beginning
                file_size = f.seek(0, 2)
                if file_size < self.last_position:
                    self.last_position = 0
                f.seek(self.last_position)

                pending_prefix: Optional[str] = None
                json_lines: List[str] = []
                for raw_line in f:
                    line = raw_line.rstrip("\n")
                    stripped = line.strip()

                    if json_lines:
                        json_lines.append(line)
                        parsed, compact = self._try_parse_json_blob(json_lines)
                        if parsed is None or compact is None:
                            continue
                        if pending_prefix:
                            yield f"{pending_prefix} {compact}"
                        else:
                            yield compact
                        pending_prefix = None
                        json_lines = []
                        continue

                    if stripped.startswith("{"):
                        if pending_prefix is not None:
                            json_lines = [line]
                            parsed, compact = self._try_parse_json_blob(json_lines)
                            if parsed is not None and compact is not None:
                                yield f"{pending_prefix} {compact}"
                                pending_prefix = None
                                json_lines = []
                            continue
                        json_lines = [line]
                        parsed, compact = self._try_parse_json_blob(json_lines)
                        if parsed is not None and compact is not None:
                            yield compact
                            json_lines = []
                        continue

                    if pending_prefix is not None:
                        yield pending_prefix
                        pending_prefix = None

                    if self._looks_like_json_prefix(line):
                        pending_prefix = line
                        continue

                    yield line

                if json_lines:
                    combined = "\n".join(json_lines)
                    if pending_prefix:
                        yield f"{pending_prefix} {combined}"
                    else:
                        yield combined
                elif pending_prefix is not None:
                    yield pending_prefix

                # Update position
                self.last_position = f.tell()
        except FileNotFoundError:
            print(f"Warning: Log file not found at {self.log_path}")
        except Exception as e:
            print(f"Error reading log file: {e}")

    @staticmethod
    def _try_parse_json_blob(lines: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Return parsed JSON object and compact string when buffered lines form valid JSON."""
        blob = "\n".join(lines).strip()
        if not blob:
            return None, None
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return None, None
        if not isinstance(data, dict):
            return None, None
        return data, json.dumps(data, separators=(",", ":"))

    @staticmethod
    def _looks_like_json_prefix(line: str) -> bool:
        """Return True when a non-JSON line is a prefix for a following JSON block."""
        lower = line.lower()
        return any(
            token in lower
            for token in (
                "gretoclientevent",
                "clienttogremessage",
                "clienttogreuimessage",
                "gamestatemessage",
            )
        )

    def parse_json_from_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON data from a log line.

        MTGA log lines often contain JSON data. This method extracts and parses it.

        Args:
            line: A line from the log file.

        Returns:
            Parsed JSON data as a dictionary, or None if no valid JSON found.
        """
        # Try to find JSON in the line
        # MTGA logs often have format: [timestamp] message {json...}
        json_match = re.search(r'\{.*\}', line)
        if json_match:
            try:
                json_str = json_match.group(0)
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        return None

    def extract_game_state_events(self, line: str) -> List[Dict[str, Any]]:
        """Extract ordered game-state events from one log line.

        Args:
            line: A line from the log file.

        Returns:
            Ordered event dictionaries, one per game-state payload found in the line.
        """
        # Look for common card event indicators in MTGA logs (case-insensitive)
        line_lower = line.lower()
        card_event_patterns = [
            "gamestatemessage",
            "gretoclientevent",
            "clienttogremessage",
            "greto",
        ]

        # Check if this line contains a card event indicator
        has_pattern = any(pattern in line_lower for pattern in card_event_patterns)
        
        # Also check if line starts with JSON (might be a JSON-only line)
        line_stripped = line.strip()
        is_json_line = line_stripped.startswith("{") and line_stripped.endswith("}")

        if not has_pattern and not is_json_line:
            return []

        # Parse JSON from line
        data = self.parse_json_from_line(line)
        if not data:
            return []
        events: List[Dict[str, Any]] = []

        # Check for game state messages
        if "gameStateMessage" in data:
            game_state = data["gameStateMessage"]
            if isinstance(game_state, dict):
                events.append({"type": "game_state", "data": game_state})
            return events

        # Check for GRE (Game Rules Engine) events. Preserve per-message ordering.
        if "greToClientEvent" in data:
            gre_event = data["greToClientEvent"]
            if "greToClientMessages" in gre_event:
                for message in gre_event["greToClientMessages"]:
                    msg_type = message.get("type", "")
                    if msg_type not in ("GREMessageType_GameStateMessage", "GREMessageType_QueuedGameStateMessage"):
                        continue
                    game_state = (
                        message.get("gameStateMessage")
                        or message.get("queuedGameStateMessage")
                        or {}
                    )
                    if isinstance(game_state, dict) and game_state:
                        events.append(
                            {
                                "type": "game_state",
                                "data": game_state,
                                "message_type": msg_type,
                            }
                        )

        return events

    def extract_client_gre_payloads(self, line: str) -> List[Dict[str, Any]]:
        """Extract ordered client-to-GRE payloads from one log line."""
        line_lower = line.lower()
        if not any(token in line_lower for token in ("clienttogremessage", "clienttogreuimessage")):
            data = self.parse_json_from_line(line)
        else:
            data = self.parse_json_from_line(line)
        if not isinstance(data, dict):
            return []

        payloads: List[Dict[str, Any]] = []
        direct = data.get("clientToGreMessage")
        if isinstance(direct, dict):
            direct_payload = direct.get("payload")
            if isinstance(direct_payload, dict):
                payloads.append({"type": "client_gre_message", "data": direct_payload})
            elif direct.get("type"):
                payloads.append({"type": "client_gre_message", "data": direct})

        service_type = data.get("clientToMatchServiceMessageType")
        payload = data.get("payload")
        if (
            service_type == "ClientToMatchServiceMessageType_ClientToGREMessage"
            and isinstance(payload, dict)
        ):
            payloads.append(
                {
                    "type": "client_gre_message",
                    "data": payload,
                    "service_type": service_type,
                }
            )

        return payloads

    def extract_card_events(self, line: str) -> Optional[Dict[str, Any]]:
        """Backward-compatible first game-state event extractor."""
        events = self.extract_game_state_events(line)
        return events[0] if events else None

    def reset_position(self):
        """Reset the read position to the end of the file.

        Useful for starting fresh and only tracking new events.
        """
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                f.seek(0, 2)  # Seek to end
                self.last_position = f.tell()
        except Exception as e:
            print(f"Error resetting position: {e}")
