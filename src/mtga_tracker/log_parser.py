"""MTGA log file parser.

Parses the MTGA Player.log file to extract game events.
"""

import json
import os
import platform
import re
from pathlib import Path
from typing import Optional, Generator, Dict, Any


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
                # Seek to last known position
                f.seek(self.last_position)

                # Read new lines
                # Handle case where JSON might be on next line after log prefix
                prev_line = None
                for line in f:
                    line = line.rstrip()
                    
                    # If current line is JSON and previous had a pattern, combine
                    if line.startswith("{") and prev_line:
                        if any(pattern in prev_line.lower() for pattern in ["gretoclientevent", "gamestatemessage", "greto"]):
                            # Combine previous line with JSON
                            combined = prev_line + " " + line
                            yield combined
                            prev_line = None
                            continue
                    
                    # If we had a previous line, yield it
                    if prev_line:
                        yield prev_line
                    
                    prev_line = line

                # Yield any remaining line
                if prev_line:
                    yield prev_line

                # Update position
                self.last_position = f.tell()
        except FileNotFoundError:
            print(f"Warning: Log file not found at {self.log_path}")
        except Exception as e:
            print(f"Error reading log file: {e}")

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

    def extract_card_events(self, line: str) -> Optional[Dict[str, Any]]:
        """Extract card-related events from a log line.

        Args:
            line: A line from the log file.

        Returns:
            Dictionary with event data if a card event is found, None otherwise.
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
            return None

        # Parse JSON from line
        data = self.parse_json_from_line(line)
        if not data:
            return None

        # Extract card play information
        event_info = {}

        # Check for game state messages
        if "gameStateMessage" in data:
            game_state = data["gameStateMessage"]
            event_info["type"] = "game_state"
            event_info["data"] = game_state
            return event_info

        # Check for GRE (Game Rules Engine) events
        if "greToClientEvent" in data:
            gre_event = data["greToClientEvent"]
            if "greToClientMessages" in gre_event:
                for message in gre_event["greToClientMessages"]:
                    msg_type = message.get("type", "")
                    if msg_type == "GREMessageType_GameStateMessage":
                        event_info["type"] = "game_state"
                        event_info["data"] = message.get("gameStateMessage", {})
                        return event_info

        return event_info if event_info else None

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
