"""Card tracking module.

Tracks cards played by the player and opponents.
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from .log_parser import MTGALogParser
from .card_database import CardDatabase
from .paths import DATA_DIR
from .analytics import AnalyticsStore
from .annotations import AnnotationDetails
from .tracker_analytics import TrackerAnalyticsMixin
from .tracker_combat import TrackerCombatMixin
from .tracker_lifecycle import TrackerLifecycleMixin
from .tracker_opening_deck import TrackerOpeningDeckMixin
from .tracker_summary import TrackerSummaryMixin
from .tracker_stack import TrackerStackMixin
from .tracker_zone_transfers import TrackerZoneTransferMixin
from .log_sanitize import scrub_raw_log
from .rendering import ANSI_RESET, ANSI_STYLES, apply_style, display_path_without_username, should_use_colors
from .state import CardEvent, GameState


class CardTracker(
    TrackerAnalyticsMixin,
    TrackerOpeningDeckMixin,
    TrackerLifecycleMixin,
    TrackerCombatMixin,
    TrackerSummaryMixin,
    TrackerStackMixin,
    TrackerZoneTransferMixin,
):
    """Tracks cards played during MTGA matches."""

    def __init__(self, log_parser: Optional[MTGALogParser] = None,
                 card_db: Optional[CardDatabase] = None,
                 mtga_data_dir: Optional[str] = None):
        """Initialize the card tracker.

        Args:
            log_parser: Optional MTGALogParser instance. If not provided, creates one.
            card_db: Optional CardDatabase instance. If not provided, creates one.
            mtga_data_dir: Optional path to MTGA data root for local card DB (Raw_CardDatabase_*.mtga).
        """
        self.parser = log_parser or MTGALogParser()
        self.card_db = card_db or CardDatabase(
            log_path=self.parser.log_path,
            mtga_data_dir=mtga_data_dir,
        )
        self.game_state = GameState()
        self.player_cards: List[CardEvent] = []
        self.opponent_cards: List[CardEvent] = []
        self.running = False
        self.match_games: List[Dict] = []  # Track games in the match for summary
        self.waiting_for_next_game: bool = False  # True if launched mid-game, waiting for next game
        self._pending_game_summary: bool = False  # Defer summary until end of line batch (so ConcedeReq can set winner)
        self.session_start_time = datetime.now()
        self.session_games_played = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_draws = 0
        self.session_unknown = 0
        self.session_player_cards_played = 0
        self.session_opponent_cards_played = 0
        self.session_total_mulligans = 0
        self.session_game_runtime_seconds = 0
        self.session_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        self._session_stats_recorded_this_game = False
        self._deck_candidates: Dict[str, Dict[str, Any]] = {}
        self._active_deck_candidate_key: Optional[str] = None
        self._metadata_backfilled = False
        self._format_from_backfill = False
        self._parsing_backfilled_metadata = False
        self._current_event_time: Optional[datetime] = None
        self._require_explicit_game_start: bool = False
        self._ansi_reset = ANSI_RESET
        self._ansi_styles: Dict[str, str] = ANSI_STYLES.copy()
        self.use_colors = self._should_use_colors()
        self._console_db_path = DATA_DIR / "mtga_tracker.sqlite3"
        self._diagnostic_text_path = DATA_DIR / "mtga_tracker_unhandled_annotations.log"
        self.analytics = AnalyticsStore(self._console_db_path)

    def _should_use_colors(self) -> bool:
        """Return True when ANSI colors should be emitted."""
        return should_use_colors()

    def _now(self) -> datetime:
        """Return the current source event time when available."""
        return getattr(self, "_current_event_time", None) or datetime.now()

    def _style(self, text: str, style: Optional[str] = None) -> str:
        """Apply ANSI style if enabled."""
        return apply_style(
            text,
            style,
            use_colors=self.use_colors,
            styles=self._ansi_styles,
            reset=self._ansi_reset,
        )

    @staticmethod
    def _display_path_without_username(path_value: Any) -> str:
        """Return a display path with the user's home directory shortened to ~/."""
        return display_path_without_username(path_value)

    @staticmethod
    def _is_arena_seat(seat_id: Any) -> bool:
        """Return True only for concrete MTGA player seats."""
        return seat_id in (1, 2)

    def _is_tracked_seat(self, seat_id: Any) -> bool:
        """Return True when a concrete seat maps to player or opponent."""
        return self._is_arena_seat(seat_id) and seat_id in (
            self.game_state.player_seat_id,
            self.game_state.opponent_seat_id,
        )

    def _print_line(self, text: str = "", style: Optional[str] = None) -> None:
        """Print one console line and persist the same logical output for dashboards."""
        raw_text = "" if text is None else str(text)
        self._record_console_log(raw_text, style=style)
        sys.stdout.write(self._style(raw_text, style) + "\n")

    def _print_event(self, text: str, style: Optional[str] = None) -> None:
        """Print an event line with optional style."""
        self._print_line(text, style=style)
        self._record_game_event(text, style=style)

    def _print_summary_heading(self, text: str, style: str = "turn") -> None:
        """Print a more prominent summary heading."""
        self._print_line(text.upper(), style=style)

    def _append_diagnostic_log(self, message: str, annotation: Dict[str, Any]) -> None:
        """Best-effort append of unhandled mechanics to a text diagnostic file."""
        path = getattr(self, "_diagnostic_text_path", None)
        if path is None:
            return
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat()} {message}\n")
                handle.write(f"annotation={json.dumps(annotation, sort_keys=True, default=str)}\n")
        except (OSError, TypeError, ValueError):
            return

    def _append_parser_diagnostic_log(self, body: str) -> None:
        """Best-effort append of unknown parser entries without UI noise."""
        path = getattr(self, "_diagnostic_text_path", None)
        if path is None:
            return
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            first_line = scrub_raw_log(str(body or "")).splitlines()[0] if body else ""
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat()} Tracker: unknown log entry\n")
                handle.write(f"entry={first_line[:500]}\n")
        except (OSError, TypeError, ValueError):
            return

    def _turn_prefix_for_number(self, turn_num: Optional[int]) -> str:
        """Return elapsed match time prefix for event lines."""
        if self.game_state.game_start_time is None:
            return "[0:00] "
        elapsed = max(0, int((self._now() - self.game_state.game_start_time).total_seconds()))
        return f"[{self._format_duration(elapsed)}] "

    @staticmethod
    def _annotation_signature(annotation: Dict[str, Any]) -> tuple:
        """Return stable signature used to dedupe unhandled-annotation diagnostics."""
        ann_type = annotation.get("type", [])
        if not isinstance(ann_type, list):
            ann_type = [ann_type] if ann_type else []
        details = annotation.get("details", [])
        detail_keys = tuple(
            sorted(
                str(detail.get("key"))
                for detail in details
                if isinstance(detail, dict) and detail.get("key")
            )
        )
        category = None
        for detail in details:
            if isinstance(detail, dict) and detail.get("key") == "category":
                values = detail.get("valueString", [])
                if isinstance(values, list) and values:
                    category = values[0]
                break
        return (tuple(sorted(str(item) for item in ann_type if item)), str(category or ""), detail_keys)

    def _log_unhandled_annotation(
        self,
        annotation: Dict[str, Any],
        *,
        game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
        note: Optional[str] = None,
    ) -> None:
        """Emit one-time diagnostics for annotation patterns the tracker does not yet model."""
        signature = self._annotation_signature(annotation)
        if signature in self.game_state.logged_unhandled_annotations:
            return
        self.game_state.logged_unhandled_annotations.add(signature)

        ann_types, category, detail_keys = signature
        parts = [", ".join(ann_types) if ann_types else "unknown annotation"]
        if category:
            parts.append(f"category={category}")
        if detail_keys:
            parts.append(f"keys={','.join(detail_keys)}")
        if note:
            parts.append(note)

        affected_ids = annotation.get("affectedIds", [])
        affected_name = None
        if isinstance(affected_ids, list) and affected_ids:
            instance_id = affected_ids[0]
            obj = self._lookup_object(instance_id, game_objects_by_id)
            name = self._object_display_name(obj, instance_id)
            if name and not name.startswith("ID "):
                affected_name = name
                parts.append(f"affected=[{name}]")

        message = "Tracker: unhandled annotation - " + " | ".join(parts)
        self._append_diagnostic_log(message, annotation)

    def _seat_label(self, seat_id: Optional[int]) -> str:
        """Map seat id to display actor label."""
        if seat_id == self.game_state.player_seat_id:
            return "You"
        if seat_id == self.game_state.opponent_seat_id:
            return "Opponent"
        return "Unknown"

    def _turn_for_seat(self, seat_id: Optional[int]) -> int:
        """Best-effort turn number for events attributed to a seat."""
        if seat_id == self.game_state.player_seat_id:
            return self.game_state.last_player_turn_number or self.game_state.last_turn_announced
        if seat_id == self.game_state.opponent_seat_id:
            return self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced
        return self.game_state.last_turn_announced

    def _event_turn_number(self, seat_id: Optional[int], preferred_turn: Optional[int] = None) -> int:
        """Best-effort event turn number with startup fallback when turnInfo has not arrived yet."""
        if preferred_turn is not None and int(preferred_turn) > 0:
            return int(preferred_turn)
        inferred = self._turn_for_seat(seat_id)
        if inferred > 0:
            return int(inferred)
        if (
            self.game_state.in_match
            and self.game_state.last_turn_announced == 0
            and seat_id in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
        ):
            return 1
        return int(inferred) if inferred else 0

    def _format_actor_event(
        self,
        icon: str,
        seat_id: Optional[int],
        text: str,
        *,
        turn_override: Optional[int] = None,
    ) -> str:
        """Format one event line with consistent turn + actor prefix."""
        turn_num = self._event_turn_number(seat_id, turn_override)
        self._ensure_turn_header_for_event(seat_id, turn_num)
        turn_prefix = self._turn_prefix_for_number(turn_num)
        return f"{turn_prefix}{self._seat_label(seat_id)}: {text}"

    def _ensure_turn_header_for_event(self, seat_id: Optional[int], turn_num: Optional[int]) -> None:
        """Ensure first missing turn header appears when the first stamped event arrives."""
        if not turn_num or turn_num <= 0:
            return
        if not self._is_tracked_seat(seat_id):
            return

        if seat_id == self.game_state.player_seat_id and self.game_state.pending_player_turn_header:
            self._flush_pending_player_turn_header()
            return
        if seat_id == self.game_state.opponent_seat_id and self.game_state.pending_opponent_turn_header:
            self._flush_pending_opponent_turn_header()
            return

        if self.game_state.last_turn_announced == 0:
            if seat_id == self.game_state.player_seat_id:
                self.game_state.pending_player_turn_header = self._turn_header_snapshot(turn_num, seat_id)
                self._flush_pending_player_turn_header()
            else:
                self.game_state.pending_opponent_turn_header = self._turn_header_snapshot(turn_num, seat_id)
                self._flush_pending_opponent_turn_header()

    @staticmethod
    def _extract_stat_value(value: Any) -> Optional[int]:
        """Extract integer stat value from MTGA stat objects."""
        if isinstance(value, int):
            return value
        if isinstance(value, dict):
            inner = value.get("value")
            if isinstance(inner, int):
                return inner
        return None

    def _snapshot_game_objects(self, game_objects: List[Dict[str, Any]]) -> None:
        """Persist latest known gameObject fields for later combat/summary lookups."""
        max_snapshots = 4000
        trim_batch = 200
        for obj in game_objects:
            if not isinstance(obj, dict):
                continue
            instance_id = obj.get("instanceId")
            if instance_id is None:
                continue
            previous = self.game_state.object_snapshots.get(instance_id, {}).copy()
            snap = previous.copy()
            snap.update({k: v for k, v in obj.items() if v is not None})
            self._maybe_log_identity_change(int(instance_id), previous, snap)
            self.game_state.object_snapshots[instance_id] = snap
        # Keep snapshot map bounded across long sessions.
        if len(self.game_state.object_snapshots) > max_snapshots:
            for old_id in list(self.game_state.object_snapshots.keys())[:trim_batch]:
                self.game_state.object_snapshots.pop(old_id, None)

    def _remove_deleted_instances(self, deleted_instance_ids: Any) -> None:
        """Purge deleted object ids from snapshot and combat caches."""
        if not isinstance(deleted_instance_ids, list):
            return
        deleted_ids = {
            int(instance_id)
            for instance_id in deleted_instance_ids
            if isinstance(instance_id, int)
        }
        if not deleted_ids:
            return

        for instance_id in deleted_ids:
            self.game_state.object_snapshots.pop(instance_id, None)
            self.game_state.current_combat_attackers.pop(instance_id, None)
            self.game_state.current_combat_blockers.pop(instance_id, None)

        self.game_state.attackers = [
            instance_id for instance_id in self.game_state.attackers
            if instance_id not in deleted_ids
        ]
        self.game_state.blockers = {
            blocker_id: [attacker_id for attacker_id in attacker_ids if attacker_id not in deleted_ids]
            for blocker_id, attacker_ids in self.game_state.blockers.items()
            if blocker_id not in deleted_ids
        }
        self.game_state.reported_attack_keys = {
            key for key in self.game_state.reported_attack_keys
            if not (isinstance(key, tuple) and len(key) > 1 and key[1] in deleted_ids)
        }
        self.game_state.reported_block_pairs = {
            key for key in self.game_state.reported_block_pairs
            if not (
                isinstance(key, tuple)
                and (
                    (len(key) > 1 and key[1] in deleted_ids)
                    or (len(key) > 2 and key[2] in deleted_ids)
                )
            )
        }
        self.game_state.combat_loss_events_counted = {
            key for key in self.game_state.combat_loss_events_counted
            if not (isinstance(key, tuple) and key and key[0] in deleted_ids)
        }
        self.game_state.seen_instance_ids -= deleted_ids

    def _canonical_instance_id(self, instance_id: Optional[int]) -> Optional[int]:
        """Resolve instance id to canonical root id across ObjectIdChanged events."""
        if instance_id is None:
            return None
        current = int(instance_id)
        seen: Set[int] = set()
        while current in self.game_state.instance_roots and current not in seen:
            seen.add(current)
            parent = self.game_state.instance_roots.get(current)
            if parent is None:
                break
            current = int(parent)
        return current

    def _record_object_id_change(self, orig_id: Optional[int], new_id: Optional[int]) -> None:
        """Track object id remaps so cast/resolve stages can be deduped as one spell."""
        if orig_id is None or new_id is None:
            return
        orig_root = self._canonical_instance_id(orig_id) or int(orig_id)
        self.game_state.instance_roots[int(orig_id)] = orig_root
        self.game_state.instance_roots[int(new_id)] = orig_root

    def _object_display_name(self, obj: Dict[str, Any], instance_id: Optional[int]) -> str:
        """Return best-effort card/permanent display name for a game object."""
        grp_id = obj.get("grpId") or obj.get("overlayGrpId") or obj.get("objectSourceGrpId")
        if grp_id:
            name = self._refresh_fallback_name_text(self.card_db.get_card_name(grp_id))
            if name:
                return name
        return f"ID {instance_id}" if instance_id is not None else "Unknown"

    def _object_pt(self, obj: Dict[str, Any]) -> str:
        """Return creature stats as P/T when available."""
        p = self._extract_stat_value(obj.get("power"))
        t = self._extract_stat_value(obj.get("toughness"))
        if p is not None and t is not None:
            return f"{p}/{t}"
        return "?/?"

    def _object_display_label(self, obj: Dict[str, Any], instance_id: Optional[int] = None) -> str:
        """Return card display text with P/T when the object is a creature."""
        name = self._object_display_name(obj, instance_id)
        if "CardType_Creature" in (obj.get("cardTypes") or []):
            pt = self._object_pt(obj)
            if pt != "?/?":
                return f"{name} ({pt})"
        return name

    @staticmethod
    def _object_identity_tuple(obj: Dict[str, Any]) -> tuple:
        """Return stable identity tuple used to detect permanent identity changes."""
        if not isinstance(obj, dict):
            return ()
        return (
            obj.get("grpId"),
            obj.get("overlayGrpId"),
            obj.get("objectSourceGrpId"),
        )

    def _maybe_log_identity_change(self, instance_id: int, previous: Dict[str, Any], current: Dict[str, Any]) -> None:
        """Log when a live permanent changes visible identity, such as copy effects."""
        if not self.game_state.in_match or not previous or not current:
            return

        seat_id = current.get("controllerSeatId")
        if seat_id is None:
            seat_id = current.get("ownerSeatId")
        seat_id = self._normalize_seat_id(seat_id)
        if not self._is_tracked_seat(seat_id):
            return

        prev_identity = self._object_identity_tuple(previous)
        new_identity = self._object_identity_tuple(current)
        if not prev_identity or prev_identity == new_identity:
            return

        prev_name = self._object_display_name(previous, instance_id)
        new_name = self._object_display_name(current, instance_id)
        if (
            not prev_name
            or not new_name
            or prev_name == new_name
            or prev_name.startswith("ID ")
            or new_name.startswith("ID ")
        ):
            return

        current_types = current.get("cardTypes") or []
        previous_types = previous.get("cardTypes") or []
        permanent_types = {
            "CardType_Creature",
            "CardType_Artifact",
            "CardType_Enchantment",
            "CardType_Planeswalker",
            "CardType_Land",
        }
        if not any(card_type in permanent_types for card_type in list(current_types) + list(previous_types)):
            return

        dedupe_key = (int(instance_id), new_identity)
        if dedupe_key in self.game_state.logged_identity_changes:
            return
        self.game_state.logged_identity_changes.add(dedupe_key)

        pt_suffix = ""
        if "CardType_Creature" in current_types:
            pt_suffix = f" ({self._object_pt(current)})"
        turn_override = self._turn_for_seat(seat_id)
        self._flush_pending_turn_header_for_seat(seat_id)
        self._print_event(
            self._format_actor_event(
                "",
                seat_id,
                f"[{prev_name}] became [{new_name}]{pt_suffix}",
                turn_override=turn_override,
            ),
            "ability",
        )

    @staticmethod
    def _format_mana_cost(mana_cost: Any) -> str:
        """Format MTGA manaCost arrays as {1}{R}-style text."""
        if not isinstance(mana_cost, list):
            return ""
        parts: List[str] = []
        for item in mana_cost:
            if not isinstance(item, dict):
                continue
            colors = item.get("color") or []
            count = item.get("count", 1)
            if not isinstance(count, int) or count <= 0:
                count = 1
            if not isinstance(colors, list) or not colors:
                continue
            tokens: List[str] = []
            for color in colors:
                raw = str(color).replace("ManaColor_", "")
                if raw == "Generic":
                    tokens.append(str(count))
                    continue
                if raw == "Colorless":
                    tokens.extend(["C"] * count)
                    continue
                if raw == "X":
                    tokens.extend(["X"] * count)
                    continue
                if raw.startswith("Phyrexian"):
                    tokens.extend([raw.replace("Phyrexian", "") + "/P"] * count)
                    continue
                if raw.startswith("Hybrid"):
                    symbol = raw.replace("Hybrid", "")
                    tokens.extend([symbol] * count)
                    continue
                tokens.extend([raw[:1]] * count)
            parts.extend(f"{{{token}}}" for token in tokens if token)
        return "".join(parts)

    @staticmethod
    def _normalize_ability_text(text: Optional[str]) -> str:
        """Convert MTGA localization ability text to a cleaner readable form."""
        if not isinstance(text, str):
            return ""
        cleaned = text.strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"\{o([^}]*)\}", lambda m: "".join(f"{{{tok}}}" for tok in re.findall(r"[A-Z]+|\d+", m.group(1))), cleaned)
        cleaned = re.sub(r"\{T\}", "tap", cleaned)
        cleaned = re.sub(r"\{Q\}", "untap", cleaned)
        cleaned = re.sub(r"\{([^{}]+)\}", r"\1", cleaned)
        cleaned = re.sub(r"CLASSLEVEL \[(\d+\+?)\] \[\] \[(.*)\]", r"Level \1: \2", cleaned)
        cleaned = cleaned.replace("oT", "T")
        return cleaned

    @staticmethod
    def _is_mana_ability_text(text: Optional[str]) -> bool:
        """Return True for visible mana abilities that should not clutter the log."""
        normalized = CardTracker._normalize_ability_text(text).lower()
        if not normalized:
            return False
        return bool(
            re.search(r"(^|:)\s*add\s+(\{|\w+ mana)", normalized)
            or re.search(r"\badd\s+\{", normalized)
            or re.search(r"(^|:)\s*add\s+[wubrgcx0-9]+(?:\.|,|$)", normalized)
        )

    def _emit_ability_event(
        self,
        icon: str,
        seat_id: Optional[int],
        card_name: str,
        ability_text: str,
        *,
        target_text: str = "",
        turn_override: Optional[int] = None,
        style: str = "ability",
    ) -> None:
        """Print one normalized ability event line."""
        normalized = self._normalize_ability_text(ability_text)
        if not normalized:
            normalized = "activated ability"
        self._print_event(
            self._format_actor_event(
                icon,
                seat_id,
                f"[{card_name}] - {normalized}{target_text}",
                turn_override=turn_override,
            ),
            style,
        )

    def _ability_turn_override(self, seat_id: Optional[int]) -> Optional[int]:
        """Best-effort turn number for ability logs that can resolve after turnInfo advances."""
        if seat_id == self.game_state.player_seat_id:
            return self.game_state.last_player_turn_number or self.game_state.last_turn_announced or None
        if seat_id == self.game_state.opponent_seat_id:
            return self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced or None
        return self.game_state.last_turn_announced or None

    def _should_log_ability_text(self, source_obj: Dict[str, Any], ability_text: Optional[str]) -> bool:
        """Filter out noisy abilities such as basic land mana taps."""
        normalized = self._normalize_ability_text(ability_text)
        if not normalized:
            return False
        if self._is_mana_ability_text(normalized):
            return False
        return True

    def _highest_known_creature_snapshot(self, seat_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Return highest P/T creature snapshot seen this game (optionally filtered by owner seat)."""
        if seat_id in (1, 2):
            observed = self.game_state.highest_creature_by_seat.get(int(seat_id))
            if isinstance(observed, dict):
                return observed
        best: Optional[Dict[str, Any]] = None
        for instance_id, obj in self.game_state.object_snapshots.items():
            if not isinstance(obj, dict):
                continue
            if seat_id in (1, 2) and obj.get("ownerSeatId") != seat_id:
                continue
            zone_id = obj.get("zoneId")
            if zone_id is not None and zone_id != 28:
                continue
            if obj.get("isFacedown"):
                continue
            card_types = obj.get("cardTypes")
            if isinstance(card_types, list):
                if "CardType_Creature" not in card_types:
                    continue
            else:
                # If card types are missing, skip to avoid false positives.
                continue
            p = self._extract_stat_value(obj.get("power"))
            t = self._extract_stat_value(obj.get("toughness"))
            if p is None or t is None:
                continue
            score = max(p, t)
            if best is None or score > best["score"]:
                best = {
                    "instance_id": instance_id,
                    "name": self._object_display_name(obj, instance_id),
                    "power": p,
                    "toughness": t,
                    "owner_seat": obj.get("ownerSeatId"),
                    "score": score,
                }
        return best

    def _observe_battlefield_creatures(self, data: Dict[str, Any]) -> None:
        """Track highest observed live battlefield creature stats by seat."""
        zones = data.get("zones", [])
        if not isinstance(zones, list):
            return
        battlefield_zone_ids = {
            zone.get("zoneId")
            for zone in zones
            if isinstance(zone, dict) and zone.get("type") == "ZoneType_Battlefield" and zone.get("zoneId") is not None
        }
        if not battlefield_zone_ids:
            return

        for obj in data.get("gameObjects", []) or []:
            if not isinstance(obj, dict):
                continue
            if obj.get("zoneId") not in battlefield_zone_ids:
                continue
            if obj.get("isFacedown"):
                continue
            card_types = obj.get("cardTypes")
            if not isinstance(card_types, list) or "CardType_Creature" not in card_types:
                continue
            owner_seat = self._normalize_seat_id(obj.get("ownerSeatId"))
            if owner_seat not in (1, 2):
                continue
            power = self._extract_stat_value(obj.get("power"))
            toughness = self._extract_stat_value(obj.get("toughness"))
            if power is None or toughness is None:
                continue

            score = max(power, toughness)
            instance_id = obj.get("instanceId")
            candidate = {
                "instance_id": instance_id,
                "name": self._object_display_name(obj, instance_id),
                "power": power,
                "toughness": toughness,
                "owner_seat": owner_seat,
                "score": score,
            }
            best = self.game_state.highest_creature_by_seat.get(owner_seat)
            if best is None or score > best.get("score", -1):
                self.game_state.highest_creature_by_seat[owner_seat] = candidate

    @staticmethod
    def _format_duration(total_seconds: int) -> str:
        """Format duration as H:MM:SS or M:SS."""
        total_seconds = max(0, int(total_seconds))
        hours, rem = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def _current_game_duration_seconds(self, *, now: Optional[datetime] = None) -> int:
        """Return elapsed seconds for the current game only."""
        if self.game_state.game_start_time is None:
            return 0
        end_time = self.game_state.game_end_time or now or datetime.now()
        return max(0, int((end_time - self.game_state.game_start_time).total_seconds()))

    def _session_play_runtime_seconds(self) -> int:
        """Return active game time, excluding tracker idle/lobby uptime."""
        total = max(0, int(self.session_game_runtime_seconds))
        if (
            self.game_state.in_match
            and not self.game_state.match_complete
            and not self._session_stats_recorded_this_game
        ):
            total += self._current_game_duration_seconds()
        return max(0, int(total))

    def _session_runtime_str(self) -> str:
        """Return active session game time."""
        return self._format_duration(self._session_play_runtime_seconds())

    def _session_stats_line(self) -> str:
        """Return one-line session W/L stats."""
        known_results = self.session_wins + self.session_losses
        win_rate = (self.session_wins / known_results * 100.0) if known_results > 0 else 0.0
        draw_part = f" D:{getattr(self, 'session_draws', 0)}" if getattr(self, "session_draws", 0) else ""
        unknown_part = f", ?:{self.session_unknown}" if self.session_unknown else ""
        return (
            f"W:{self.session_wins} L:{self.session_losses}{draw_part}{unknown_part} | "
            f"Games:{self.session_games_played} | WR:{win_rate:.1f}% | Play Time:{self._session_runtime_str()}"
        )

    def _refresh_fallback_name_text(self, text: Optional[str]) -> str:
        """Replace fallback ``Card #<id>`` tokens with local DB names when available."""
        if not isinstance(text, str) or not text:
            return text or ""

        def _replace(match: re.Match[str]) -> str:
            grp_id = int(match.group(1))
            resolved = self.card_db.get_card_name(grp_id)
            if isinstance(resolved, str) and resolved and not resolved.startswith("Card #"):
                return resolved
            return match.group(0)

        return re.sub(r"Card #(\d+)", _replace, text)

    def _extract_game_state_events(self, line: str) -> List[Dict[str, Any]]:
        """Return ordered game-state events from one raw log line."""
        extract_many = getattr(self.parser, "extract_game_state_events", None)
        if callable(extract_many):
            events = extract_many(line)
            if isinstance(events, list):
                return [event for event in events if isinstance(event, dict)]
        single = self.parser.extract_card_events(line)
        if isinstance(single, dict):
            return [single]
        return []

    def _extract_client_gre_payloads(self, line: str) -> List[Dict[str, Any]]:
        """Return ordered client-to-GRE payloads from one raw log line."""
        extract_many = getattr(self.parser, "extract_client_gre_payloads", None)
        if callable(extract_many):
            payloads = extract_many(line)
            if isinstance(payloads, list):
                return [payload for payload in payloads if isinstance(payload, dict)]
        data = self.parser.parse_json_from_line(line)
        if not isinstance(data, dict):
            return []
        direct = data.get("clientToGreMessage")
        if isinstance(direct, dict):
            payload = direct.get("payload")
            if isinstance(payload, dict):
                return [{"type": "client_gre_message", "data": payload}]
            if direct.get("type"):
                return [{"type": "client_gre_message", "data": direct}]
        if (
            data.get("clientToMatchServiceMessageType") == "ClientToMatchServiceMessageType_ClientToGREMessage"
            and isinstance(data.get("payload"), dict)
        ):
            return [{"type": "client_gre_message", "data": data["payload"]}]
        return []

    def _extract_gre_messages(self, line: str) -> List[Dict[str, Any]]:
        """Return ordered GRE-to-client messages from one raw log line."""
        data = self.parser.parse_json_from_line(line)
        if not isinstance(data, dict):
            return []
        gre_event = data.get("greToClientEvent")
        if not isinstance(gre_event, dict):
            return []
        messages = gre_event.get("greToClientMessages")
        if not isinstance(messages, list):
            return []
        return [message for message in messages if isinstance(message, dict)]

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        """Return value as a list, accepting Arena's singular-or-list response shapes."""
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    def _capture_casting_time_options_requests(self, message: Dict[str, Any]) -> None:
        """Remember modal-option prompts so client responses can be logged with card names."""
        if message.get("type") != "GREMessageType_CastingTimeOptionsReq":
            return
        game_state_id = message.get("gameStateId")
        options_req = message.get("castingTimeOptionsReq") or {}
        for option in self._as_list(options_req.get("castingTimeOptionReq")):
            if not isinstance(option, dict):
                continue
            if option.get("castingTimeOptionType") != "CastingTimeOptionType_Modal":
                continue
            cto_id = option.get("ctoId")
            modal_req = option.get("modalReq") or {}
            selected_options = [
                modal_option.get("grpId")
                for modal_option in self._as_list(modal_req.get("modalOptions"))
                if isinstance(modal_option, dict) and modal_option.get("grpId") is not None
            ]
            if game_state_id is None or cto_id is None:
                continue
            self.game_state.pending_modal_requests[(int(game_state_id), int(cto_id))] = {
                "source_grp_id": option.get("grpId"),
                "affected_id": option.get("affectedId"),
                "player_id": option.get("playerIdToPrompt"),
                "ability_grp_id": modal_req.get("abilityGrpId"),
                "modal_options": selected_options,
            }

    def _mode_text(self, ability_grp_id: int) -> Optional[str]:
        """Return concise display text for one selected modal ability."""
        get_text = getattr(self.card_db, "get_ability_text", None)
        raw_text = get_text(int(ability_grp_id)) if callable(get_text) else None
        text = self._normalize_ability_text(raw_text)
        if not text:
            return None
        text = re.sub(r"\s+", " ", text.replace("•", " ")).strip()
        return text

    def _handle_casting_time_options_response(self, payload: Dict[str, Any]) -> None:
        """Log selected modal choices from local client responses."""
        game_state_id = payload.get("gameStateId")
        options_resp = payload.get("castingTimeOptionsResp") or {}
        for option in self._as_list(options_resp.get("castingTimeOptionResp")):
            if not isinstance(option, dict):
                continue
            if option.get("castingTimeOptionType") != "CastingTimeOptionType_Modal":
                continue
            cto_id = option.get("ctoId")
            if game_state_id is None or cto_id is None:
                continue
            key = (int(game_state_id), int(cto_id))
            if key in self.game_state.logged_modal_choices:
                continue
            request = self.game_state.pending_modal_requests.get(key) or {}
            selected_grp_ids = [
                int(grp_id)
                for grp_id in self._as_list((option.get("chooseModalResp") or {}).get("grpIds"))
                if grp_id is not None
            ]
            mode_texts = [text for grp_id in selected_grp_ids if (text := self._mode_text(grp_id))]
            if not mode_texts:
                continue
            source_grp_id = request.get("source_grp_id")
            card_name = self.card_db.get_card_name(int(source_grp_id)) if source_grp_id is not None else "modal spell"
            seat_id = self.game_state.player_seat_id or request.get("player_id")
            self.game_state.logged_modal_choices.add(key)
            self._print_event(
                self._format_actor_event(
                    "",
                    seat_id,
                    f"chose modes for [{card_name}]: {'; '.join(mode_texts)}",
                    turn_override=self._event_turn_number(seat_id),
                ),
                "ability",
            )

    def _handle_client_gre_payload(self, payload_event: Dict[str, Any]) -> None:
        """Handle client-to-GRE responses that improve mulligan/opening-hand tracking."""
        payload = payload_event.get("data", {})
        if not isinstance(payload, dict):
            return
        normalized = payload_event.get("normalized")
        normalized = normalized if isinstance(normalized, dict) else {}
        payload_type = str(payload.get("type", ""))

        if payload_type == "ClientMessageType_CastingTimeOptionsResp":
            self._handle_casting_time_options_response(payload)
            return

        if payload_type == "ClientMessageType_MulliganResp":
            decision = str(
                normalized.get("decision")
                or (payload.get("mulliganResp") or {}).get("decision", "")
            )
            self.game_state.opening_mulligan_prompt_seen = True
            if decision in {"mulligan", "MulliganOption_Mulligan"}:
                self.game_state.explicit_mulligan_count += 1
                self.game_state.opening_keep_confirmed = False
                self.game_state.opening_select_n_ids = []
            elif decision in {"keep", "MulliganOption_AcceptHand"}:
                self.game_state.opening_keep_confirmed = True
                self._finalize_confirmed_opening_hand_candidate()
            return

        if payload_type == "ClientMessageType_SubmitDeckResp" or normalized.get("type") == "submit_deck_resp":
            deck_cards = normalized.get("deck_cards")
            sideboard_cards = normalized.get("sideboard_cards")
            if isinstance(deck_cards, list):
                self.game_state.submitted_deck_cards = [int(card) for card in deck_cards]
            if isinstance(sideboard_cards, list):
                self.game_state.submitted_sideboard_cards = [int(card) for card in sideboard_cards]
            return

        if payload_type != "ClientMessageType_SelectNResp":
            return
        if self.game_state.opening_hand_capture_closed:
            return
        if self.game_state.last_turn_announced > 0:
            return
        if not (self.game_state.opening_keep_confirmed or self.game_state.explicit_mulligan_count > 0):
            return
        select_resp = payload.get("selectNResp") or {}
        ids = normalized.get("selected_object_ids") or select_resp.get("selectedObjectIds") or select_resp.get("ids")
        if not isinstance(ids, list):
            return
        parsed_ids: List[int] = []
        for value in ids:
            try:
                parsed_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if parsed_ids:
            self.game_state.opening_select_n_ids = parsed_ids

    def _seat_stats(self, seat_id: Optional[int]) -> Optional[Dict[str, int]]:
        """Return mutable per-seat stats dict when seat is known."""
        if seat_id not in (1, 2):
            return None
        return self.game_state.match_stats[int(seat_id)]

    @staticmethod
    def _zone_index(data: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        """Map zone id to zone payload for the current update."""
        zones = data.get("zones", [])
        if not isinstance(zones, list):
            return {}
        return {
            int(zone.get("zoneId")): zone
            for zone in zones
            if isinstance(zone, dict) and zone.get("zoneId") is not None
        }

    def _extract_hand_sizes(self, data: Dict[str, Any]) -> Dict[int, int]:
        """Return visible hand sizes by seat from the current state packet."""
        sizes: Dict[int, int] = {}
        zones = data.get("zones", [])
        if not isinstance(zones, list):
            return sizes
        for zone in zones:
            if not isinstance(zone, dict) or zone.get("type") != "ZoneType_Hand":
                continue
            owner_seat = self._normalize_seat_id(zone.get("ownerSeatId"))
            obj_ids = zone.get("objectInstanceIds", [])
            if owner_seat not in (1, 2) or not isinstance(obj_ids, list):
                continue
            sizes[int(owner_seat)] = len(obj_ids)
        return sizes

    def _resolve_zone_transfer_seat(
        self,
        *,
        card_obj: Optional[Dict[str, Any]] = None,
        annotation: Optional[Dict[str, Any]] = None,
        game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
        zone_src: Optional[int] = None,
        zone_dest: Optional[int] = None,
        zones_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
        prefer_controller: bool = False,
    ) -> Optional[int]:
        """Infer which seat owns/controls a zone transfer event."""
        if isinstance(card_obj, dict):
            if prefer_controller:
                controller_seat = self._normalize_seat_id(card_obj.get("controllerSeatId"))
                if self._is_tracked_seat(controller_seat):
                    return controller_seat
            owner_seat = self._normalize_seat_id(card_obj.get("ownerSeatId"))
            if self._is_tracked_seat(owner_seat):
                return owner_seat

        for zone_id in (zone_src, zone_dest):
            zone = (zones_by_id or {}).get(int(zone_id)) if zone_id is not None else None
            if not isinstance(zone, dict):
                continue
            owner_seat = self._normalize_seat_id(zone.get("ownerSeatId"))
            if self._is_tracked_seat(owner_seat):
                return owner_seat

        if annotation is not None:
            return self._annotation_actor_seat(annotation, game_objects_by_id or {})
        return None

    def _known_hand_delta_by_seat(
        self,
        data: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Dict[int, Dict[str, Any]],
    ) -> Dict[int, int]:
        """Return hand-size delta already explained by explicit annotations in this packet."""
        deltas: Dict[int, int] = {}
        counted_departures: Set[int] = set()
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return deltas

        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_type = annotation.get("type", [])
            if not isinstance(ann_type, list):
                ann_type = [ann_type] if ann_type else []
            if "AnnotationType_ZoneTransfer" not in ann_type:
                continue

            details = annotation.get("details", [])
            if not isinstance(details, list):
                continue

            category = self._annotation_category(annotation)
            zone_src = None
            zone_dest = None
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                key = detail.get("key", "")
                if key == "zone_src":
                    zone_src = detail.get("valueInt32", [None])[0]
                elif key == "zone_dest":
                    zone_dest = detail.get("valueInt32", [None])[0]

            affected_ids = annotation.get("affectedIds", [])
            instance_id = affected_ids[0] if isinstance(affected_ids, list) and affected_ids else None
            canonical_id = self._canonical_instance_id(instance_id) if instance_id is not None else None
            card_obj = self._lookup_object(instance_id, game_objects_by_id) if instance_id is not None else {}
            seat_id = self._resolve_zone_transfer_seat(
                card_obj=card_obj,
                annotation=annotation,
                game_objects_by_id=game_objects_by_id,
                zone_src=zone_src,
                zone_dest=zone_dest,
                zones_by_id=zones_by_id,
                prefer_controller=category in ("PlayLand", "CastSpell", "PlaySpell", "Resolve"),
            )
            if not self._is_tracked_seat(seat_id):
                continue

            if category in ("Draw", "Return"):
                deltas[int(seat_id)] = deltas.get(int(seat_id), 0) + 1
                continue
            if category == "Discard":
                deltas[int(seat_id)] = deltas.get(int(seat_id), 0) - 1
                continue

            if category == "PlayLand":
                if canonical_id is None and instance_id is None:
                    continue
                key = int(canonical_id if canonical_id is not None else instance_id)
                if key not in counted_departures:
                    counted_departures.add(key)
                    deltas[int(seat_id)] = deltas.get(int(seat_id), 0) - 1
                continue

            if category in ("CastSpell", "PlaySpell", "Resolve"):
                src_zone = (zones_by_id or {}).get(int(zone_src)) if zone_src is not None else None
                src_type = src_zone.get("type") if isinstance(src_zone, dict) else None
                if src_type not in (None, "ZoneType_Hand"):
                    continue
                if canonical_id is None and instance_id is None:
                    continue
                key = int(canonical_id if canonical_id is not None else instance_id)
                if key not in counted_departures:
                    counted_departures.add(key)
                    deltas[int(seat_id)] = deltas.get(int(seat_id), 0) - 1
                continue

            if category == "Exile":
                src_zone = (zones_by_id or {}).get(int(zone_src)) if zone_src is not None else None
                if isinstance(src_zone, dict) and src_zone.get("type") == "ZoneType_Hand":
                    deltas[int(seat_id)] = deltas.get(int(seat_id), 0) - 1

        return deltas

    def _reconcile_hidden_hand_changes(
        self,
        data: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        """Infer hidden hand draws from zone-count deltas when MTGA omits draw annotations."""
        current_hand_sizes = self._extract_hand_sizes(data)
        if not current_hand_sizes:
            return

        previous_hand_sizes = dict(self.game_state.last_hand_size_by_seat)
        self.game_state.last_hand_size_by_seat = current_hand_sizes

        if not previous_hand_sizes:
            return
        if not self.game_state.opening_hand_capture_closed and self.game_state.turn_number <= 1:
            return

        known_delta = self._known_hand_delta_by_seat(data, game_objects_by_id, zones_by_id)
        for seat_id, current_size in current_hand_sizes.items():
            previous_size = previous_hand_sizes.get(int(seat_id))
            if previous_size is None:
                continue
            residual = int(current_size) - int(previous_size) - int(known_delta.get(int(seat_id), 0))
            if residual <= 0:
                continue
            stats = self._seat_stats(seat_id)
            if stats is not None:
                stats["cards_drawn"] += residual

    def _print_startup_legend(self) -> None:
        """Print a short event color legend."""
        self._print_line(" Card Event Colors:")
        self._print_line("  Turn / Session Header", "turn")
        self._print_line("  Cast / Spell Played", "cast")
        self._print_line("  Land Played", "land")
        self._print_line("  Ability / Trigger", "ability")
        self._print_line("  Stack Resolved", "stack_resolve")
        self._print_line("  Stack Countered / Unresolved", "stack_fail")
        self._print_line("  Attack", "attack")
        self._print_line("  Block", "block")
        self._print_line("  Combat Damage", "combat_damage")
        self._print_line("  Damage", "damage")
        self._print_line("  Life Gained", "life_gain")
        self._print_line("  Life Lost", "life_loss")
        self._print_line("  Draw", "draw")
        self._print_line("  Card Movement", "zone")
        if not self.use_colors:
            self._print_line("     (Color is off; set MTGA_TRACKER_COLOR=1 to force)")

    def start(self):
        """Start tracking cards."""
        self._print_line("\n" + "=" * 75)
        self._print_line("🟡 🔵 ⚫ 🔴 🟢 MTGA Card Tracker - Real-time Match Analyzer 🟡 🔵 ⚫ 🔴 🟢")
        self._print_line("=" * 75)
        self._print_line(f" Monitoring: {self._display_path_without_username(self.parser.log_path)}")
        card_db_path = None
        resolve_db_path = getattr(self.card_db, "_resolve_mtga_db_path", None)
        if callable(resolve_db_path):
            card_db_path = resolve_db_path()
        self._print_line(f" Local Card DB: {self._display_path_without_username(card_db_path)}")
        self._print_line(f" Log DB: {self._display_path_without_username(self._console_db_path)}")
        self._print_line("\n")

        self._print_startup_legend()
        #self._print_event(f"Session: {self._session_stats_line()}", "turn")

        # self._print_line("\n   Waiting for game events...")
        self._print_line("\n Now reaady to track games in MTGA!")
        self._print_line("\n Press Ctrl+C to stop")
        self._print_line("=" * 75 + "\n")

        # Deck metadata is often logged before startup; backfill from recent lines once.
        self._backfill_recent_match_metadata()

        # Start from current end of file
        self.parser.reset_position()
        
        # Check if we're launching mid-game
        self._check_if_mid_game()
        
        
        # Safety: If waiting_for_next_game is set, give it a timeout
        # After 5 minutes, assume we can start tracking
        self.waiting_start_time = time.time() if self.waiting_for_next_game else None
        
        self.running = True

        try:
            while self.running:
                # Safety: If we've been waiting for next game for more than 5 minutes, clear the flag
                if self.waiting_for_next_game and self.waiting_start_time:
                    if time.time() - self.waiting_start_time > 300:  # 5 minutes
                        self._print_line("\n" + "="*75)
                        self._print_line("⚠️  TIMEOUT: Clearing waiting flag - starting to track")
                        self._print_line("="*75 + "\n")
                        self.waiting_for_next_game = False
                        self.waiting_start_time = None
                
                self._process_new_events()
                time.sleep(0.5)  # Check for new events twice per second
        except KeyboardInterrupt:
            self._print_line("\n" + "=" * 75)
            self._print_line("🛑 Stopping tracker...")
            self._print_summary()
            self._print_line("=" * 75)
        finally:
            self.analytics.close()

    def stop(self):
        """Stop tracking cards."""
        self.running = False
        self.analytics.close()


    @staticmethod
    def _annotation_category(annotation: Dict[str, Any]) -> Optional[str]:
        """Get zone-transfer category string from one annotation payload."""
        details = annotation.get("details", [])
        if not isinstance(details, list):
            return None
        for detail in details:
            if not isinstance(detail, dict):
                continue
            if detail.get("key") != "category":
                continue
            value = detail.get("valueString", [])
            if isinstance(value, list) and value:
                first = value[0]
                return str(first) if first is not None else None
        return None

    @staticmethod
    def _is_ignored_diagnostic_annotation(ann_type: List[str]) -> bool:
        """Return True for routine annotations that are already represented elsewhere."""
        ignored_types = {
            "AnnotationType_ChoiceResult",
            "AnnotationType_CounterAdded",
            "AnnotationType_CounterRemoved",
            "AnnotationType_GainDesignation",
            "AnnotationType_LayeredEffectCreated",
            "AnnotationType_LayeredEffectDestroyed",
            "AnnotationType_ManaPaid",
            "AnnotationType_ModifiedLife",
            "AnnotationType_MultistepEffectComplete",
            "AnnotationType_MultistepEffectStarted",
            "AnnotationType_NewTurnStarted",
            "AnnotationType_PlayerSelectingTargets",
            "AnnotationType_PlayerSubmittedTargets",
            "AnnotationType_PowerToughnessModCreated",
            "AnnotationType_RevealedCardCreated",
            "AnnotationType_RevealedCardDeleted",
            "AnnotationType_ResolutionComplete",
            "AnnotationType_Shuffle",
            "AnnotationType_ShouldntPlay",
            "AnnotationType_SyntheticEvent",
            "AnnotationType_TappedUntappedPermanent",
            "AnnotationType_TokenCreated",
            "AnnotationType_TokenDeleted",
        }
        return any(item in ignored_types for item in ann_type)

    def _has_gameplay_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when annotations indicate gameplay has started (not mulligan setup)."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if any(
                ann in ann_types
                for ann in (
                    "AnnotationType_AttackerDeclared",
                    "AnnotationType_BlockerDeclared",
                    "AnnotationType_Damage",
                    "AnnotationType_DamageDealt",
                )
            ):
                return True
            if "AnnotationType_ZoneTransfer" in ann_types:
                category = self._annotation_category(annotation)
                if category in {
                    "PlayLand",
                    "CastSpell",
                    "PlaySpell",
                    "Resolve",
                    "Draw",
                    "Destroy",
                    "Exile",
                    "Countered",
                    "Sacrifice",
                    "Discard",
                    "Mill",
                }:
                    return True
        return False

    def _has_mulligan_prompt_in_state(self, data: Dict[str, Any]) -> bool:
        """Best-effort signal for mulligan/keep prompt presence in gameState payload."""
        if self.game_state.opening_mulligan_prompt_seen:
            return True
        players = data.get("players", [])
        if not isinstance(players, list):
            return False
        for player in players:
            if not isinstance(player, dict):
                continue
            pending = (
                player.get("pendingMessageType")
                or player.get("pendingMessage")
                or player.get("pendingDecisionType")
            )
            if pending is None:
                continue
            pending_text = str(pending).lower()
            if "mulligan" in pending_text or "choosestartingplayer" in pending_text:
                return True
        return False

    def _has_new_turn_action_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when payload likely contains real actions from the newly active turn."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if "AnnotationType_ZoneTransfer" in ann_types:
                category = self._annotation_category(annotation)
                if category in {"PlayLand", "CastSpell", "PlaySpell", "Resolve", "Draw"}:
                    return True
        return False

    def _has_resolution_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when a payload includes stack resolution annotations."""
        annotations = data.get("annotations", [])
        if not isinstance(annotations, list):
            return False
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if "AnnotationType_ResolutionStart" in ann_types:
                return True
        return False

    def _emit_life_change(
        self,
        seat_id: int,
        diff: int,
        life: int,
        turn_override: Optional[int] = None,
        source_seat_override: Optional[int] = None,
        source_label: Optional[str] = None,
    ) -> None:
        """Print one life-change line with optional turn override for late-arriving events."""
        if not self.game_state.in_match or diff == 0:
            return
        turn_for_display = self._event_turn_number(
            seat_id,
            turn_override if turn_override is not None else (
                self.game_state.turn_number if self.game_state.turn_number > 0 else None
            ),
        )
        life_event_key = (seat_id, diff, life, turn_for_display)
        if self.game_state.last_emitted_life_event == life_event_key:
            return
        self.game_state.last_emitted_life_event = life_event_key
        late_life_event = (
            self.game_state.turn_number > 0
            and turn_for_display > 0
            and turn_for_display < self.game_state.turn_number
        )
        if not late_life_event:
            self._flush_pending_turn_header_for_seat(seat_id)
        actor = self._seat_label(seat_id)
        turn_prefix = self._turn_prefix_for_number(turn_for_display)
        if diff > 0:
            stats = self._seat_stats(seat_id)
            if stats is not None:
                stats["life_gain"] += diff
            source_text = f" [{source_label}]" if source_label else ""
            text = f"{turn_prefix}{actor}: gained {diff} life{source_text} (now {life})"
            if late_life_event:
                self._print_event(text, "life_gain")
            else:
                self._print_event(
                    self._format_actor_event("💚", seat_id, f"gained {diff} life{source_text} (now {life})", turn_override=turn_for_display),
                    "life_gain",
                )
        elif diff < 0:
            lost_life = -diff
            stats = self._seat_stats(seat_id)
            if stats is not None:
                stats["life_lost"] += lost_life
            matched_damage = min(
                lost_life,
                self.game_state.pending_damage_to_seat.get(int(seat_id), 0),
            )
            if matched_damage:
                remaining = self.game_state.pending_damage_to_seat.get(int(seat_id), 0) - matched_damage
                if remaining > 0:
                    self.game_state.pending_damage_to_seat[int(seat_id)] = remaining
                else:
                    self.game_state.pending_damage_to_seat.pop(int(seat_id), None)
            unmatched_life_loss = lost_life - matched_damage
            if unmatched_life_loss > 0:
                source_seat = (
                    source_seat_override
                    if source_seat_override in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
                    else self._infer_life_loss_source_seat(seat_id, turn_override=turn_for_display)
                )
                self._record_damage_dealt(
                    unmatched_life_loss,
                    source_seat,
                    seat_id,
                    queue_life_reconciliation=False,
                )
            source_text = f" [{source_label}]" if source_label else ""
            text = f"{turn_prefix}{actor}: lost {-diff} life{source_text} (now {life})"
            if late_life_event:
                self._print_event(text, "life_loss")
            else:
                self._print_event(
                    self._format_actor_event("💔", seat_id, f"lost {-diff} life{source_text} (now {life})", turn_override=turn_for_display),
                    "life_loss",
                )

    def _refresh_game_state_metadata(self, data: Dict[str, Any]) -> None:
        """Refresh non-turn metadata from a game-state payload."""
        self._remove_deleted_instances(data.get("diffDeletedInstanceIds"))
        self._snapshot_game_objects(data.get("gameObjects", []))
        self._observe_battlefield_creatures(data)
        self._capture_starting_deck_totals(data)
        self._update_format_from_game_state(data)
        self._update_commanders_from_game_state(data)
        self._maybe_print_seat_resolution()
        self._maybe_print_pregame_commander_lines()

    def _detect_turn_change(self, turn_num: Optional[int], active_player: Optional[int]) -> bool:
        """Return True when a turn payload should produce a new turn header."""
        if turn_num and turn_num > self.game_state.turn_number:
            if active_player is not None and active_player != self.game_state.active_player:
                return True
            if self.game_state.active_player is None:
                return True
        return bool(turn_num == 1 and self.game_state.last_turn_announced < 1 and active_player is not None)

    def _warn_on_missing_initial_turns(self, turn_num: Optional[int], seats_known: bool) -> None:
        """Emit a diagnostic when tracking starts after the first turn."""
        if not (
            turn_num is not None
            and turn_num > 2
            and self.game_state.last_turn_announced == 0
            and seats_known
        ):
            return
        missed_turns = list(range(1, turn_num))
        missing_text = ", ".join(str(t) for t in missed_turns[:3])
        if len(missed_turns) > 3:
            missing_text += ", ..."
        self._print_event(
            f"⚠️ First observed turn is {turn_num}; earlier turn(s) ({missing_text}) were not present in the captured log stream.",
            "turn",
        )

    def _queue_turn_header(self, turn_num: int, active_player: Optional[int]) -> None:
        """Queue or flush deferred turn headers for the current turn owner."""
        header = self._turn_header_snapshot(turn_num, active_player)
        if turn_num == 1 and self.game_state.last_turn_announced < 1:
            if active_player == self.game_state.player_seat_id:
                self.game_state.pending_player_turn_header = header
            else:
                self.game_state.pending_opponent_turn_header = header
        elif turn_num > self.game_state.last_turn_announced:
            if active_player == self.game_state.player_seat_id:
                self._flush_pending_opponent_turn_header()
                self.game_state.pending_player_turn_header = header
            else:
                self._flush_pending_player_turn_header()
                self.game_state.pending_opponent_turn_header = header

    def _update_turn_context(self, data: Dict[str, Any]) -> tuple[bool, bool]:
        """Update turn, phase, and deferred-header state."""
        if "turnInfo" not in data:
            return False, False
        turn_info = data["turnInfo"]
        turn_num = turn_info.get("turnNumber")
        active_player = turn_info.get("activePlayer")
        phase = turn_info.get("phase", "")
        step = turn_info.get("step", "")
        seats_known = (
            self.game_state.player_seat_id in (1, 2)
            and self.game_state.opponent_seat_id in (1, 2)
        )
        turn_changed = self._detect_turn_change(turn_num, active_player)

        if turn_num is not None:
            self.game_state.turn_number = turn_num
        if active_player is not None:
            self.game_state.active_player = active_player
        if phase:
            self.game_state.phase = phase
        if step:
            self.game_state.step = step

        if turn_num == 1 and self.game_state.first_player_seat is None and active_player is not None:
            self.game_state.first_player_seat = active_player

        self._warn_on_missing_initial_turns(turn_num, seats_known)
        exited_combat_this_update = self._update_combat_phase(phase)

        if turn_changed and turn_num:
            self.game_state.reported_attack_keys = {
                k for k in self.game_state.reported_attack_keys if isinstance(k, tuple) and k and k[0] >= int(turn_num) - 1
            }

        if turn_changed and seats_known:
            self._queue_turn_header(int(turn_num), active_player)

        return turn_changed, exited_combat_this_update

    def _collect_life_updates(self, data: Dict[str, Any]) -> List[tuple]:
        """Return changed life totals as (seat_id, diff, new_life)."""
        life_updates: List[tuple] = []
        players = data.get("players", [])
        if isinstance(players, list):
            for player in players:
                seat_id = player.get("systemSeatNumber")
                life = player.get("lifeTotal")
                if life is None or seat_id is None:
                    continue
                old_life = None
                if seat_id == self.game_state.player_seat_id:
                    old_life = self.game_state.player_life
                elif seat_id == self.game_state.opponent_seat_id:
                    old_life = self.game_state.opponent_life
                if old_life is None or life == old_life:
                    continue
                life_updates.append((seat_id, life - old_life, life))
        return life_updates

    def _late_life_turn_override(
        self,
        data: Dict[str, Any],
        *,
        turn_changed: bool,
        exited_combat_this_update: bool,
        previous_attack_target_ids: Set[int],
        life_updates: List[tuple],
    ) -> Optional[int]:
        """Return previous turn number when Arena reports combat life loss late."""
        if (
            turn_changed
            and self.game_state.turn_number > 1
            and (exited_combat_this_update or self._has_combat_or_damage_annotations(data))
            and not self._has_new_turn_action_annotations(data)
        ):
            return self.game_state.turn_number - 1
        elif (
            turn_changed
            and self.game_state.turn_number > 1
            and previous_attack_target_ids
            and not self._has_new_turn_action_annotations(data)
            and any(diff < 0 and seat_id in previous_attack_target_ids for seat_id, diff, _life in life_updates)
        ):
            return self.game_state.turn_number - 1
        return None

    def _apply_life_updates(self, life_updates: List[tuple], late_life_turn_override: Optional[int]) -> None:
        """Apply changed life totals and emit visible life-change rows."""
        for seat_id, diff, life in life_updates:
            if seat_id == self.game_state.player_seat_id:
                self.game_state.player_life = life
            elif seat_id == self.game_state.opponent_seat_id:
                self.game_state.opponent_life = life
            self._emit_life_change(
                seat_id,
                diff,
                life,
                turn_override=late_life_turn_override,
            )

    def _flush_deferred_life_updates(self) -> None:
        """Emit life updates deferred until after stack resolution annotations."""
        deferred = getattr(self, "_deferred_life_updates", None)
        if not deferred:
            return
        self._deferred_life_updates = None
        life_updates, late_life_turn_override = deferred
        self._apply_life_updates(life_updates, late_life_turn_override)

    def _update_game_state(self, data: Dict[str, Any]):
        """Update the tracked game state from event data."""
        # Process turn info and print turn header FIRST so "Turn N - YOUR TURN" appears
        # before card plays and life changes from this same message.
        self._refresh_game_state_metadata(data)
        previous_attack_target_ids, previous_attack_sources_by_target = self._previous_attack_context()
        turn_changed, exited_combat_this_update = self._update_turn_context(data)
        life_updates = self._collect_life_updates(data)
        late_life_turn_override = self._late_life_turn_override(
            data,
            turn_changed=turn_changed,
            exited_combat_this_update=exited_combat_this_update,
            previous_attack_target_ids=previous_attack_target_ids,
            life_updates=life_updates,
        )
        self.game_state.recent_attack_sources_by_target = previous_attack_sources_by_target
        if (
            life_updates
            and late_life_turn_override is None
            and self._has_resolution_annotations(data)
        ):
            self._deferred_life_updates = (life_updates, late_life_turn_override)
        else:
            self._apply_life_updates(life_updates, late_life_turn_override)

    def _turn_header_snapshot(self, turn_num: int, active_player: Optional[int]) -> tuple:
        """Capture the visible life totals at the moment a turn header is queued."""
        return (
            turn_num,
            active_player,
            self.game_state.player_life,
            self.game_state.opponent_life,
        )

    def _pending_turn_header_parts(self, pending: tuple) -> tuple[int, Optional[int], int, int]:
        """Return pending-header fields, accepting legacy two-field test tuples."""
        turn_num = pending[0]
        active_player = pending[1] if len(pending) > 1 else None
        player_life = pending[2] if len(pending) > 2 else self.game_state.player_life
        opponent_life = pending[3] if len(pending) > 3 else self.game_state.opponent_life
        return turn_num, active_player, player_life, opponent_life

    def _flush_pending_opponent_turn_header(self) -> None:
        """Print and clear deferred 'Turn N - OPPONENT'S TURN' header if set.

        Called at start of _process_annotation (so opponent actions appear under the
        correct header) and before announcing 'Turn N - YOUR TURN' (so we don't
        skip the opponent turn header when opponent passed with no actions).
        """
        pending = self.game_state.pending_opponent_turn_header
        if not pending:
            return
        turn_num, active_player, player_life, opponent_life = self._pending_turn_header_parts(pending)
        self.game_state.pending_opponent_turn_header = None
        self.game_state.last_turn_announced = turn_num
        if active_player == self.game_state.opponent_seat_id:
            self.game_state.last_opponent_turn_number = turn_num
        self._print_line(f"\n{'='*75}")
        self._print_event(f"Turn {turn_num} - OPPONENT'S TURN", "turn")
        self._print_line(f"Life: You {player_life} - {opponent_life} Opponent")
        self._print_line(f"{'='*75}\n")

    def _flush_pending_player_turn_header(self) -> None:
        """Print and clear deferred 'Turn N - YOUR TURN' header if set."""
        pending = self.game_state.pending_player_turn_header
        if not pending:
            return
        turn_num, active_player, player_life, opponent_life = self._pending_turn_header_parts(pending)
        self.game_state.pending_player_turn_header = None
        self.game_state.last_turn_announced = turn_num
        if active_player == self.game_state.player_seat_id:
            self.game_state.last_player_turn_number = turn_num
        self._print_line(f"\n{'='*75}")
        self._print_event(f"Turn {turn_num} - YOUR TURN", "turn")
        self._print_line(f"Life: You {player_life} - {opponent_life} Opponent")
        self._print_line(f"{'='*75}\n")

    def _flush_pending_turn_header_for_seat(self, seat_id: Optional[int]) -> None:
        """Flush deferred turn header for the side that owns the current event."""
        if seat_id == self.game_state.player_seat_id:
            self._flush_pending_player_turn_header()
        elif seat_id == self.game_state.opponent_seat_id:
            self._flush_pending_opponent_turn_header()

    def _flush_pending_active_turn_header(self) -> Optional[int]:
        """Flush the pending header for the active turn and return its turn number."""
        active_player = self.game_state.active_player
        if active_player == self.game_state.player_seat_id and self.game_state.pending_player_turn_header:
            turn_num = self._pending_turn_header_parts(self.game_state.pending_player_turn_header)[0]
            self._flush_pending_player_turn_header()
            return turn_num
        if active_player == self.game_state.opponent_seat_id and self.game_state.pending_opponent_turn_header:
            turn_num = self._pending_turn_header_parts(self.game_state.pending_opponent_turn_header)[0]
            self._flush_pending_opponent_turn_header()
            return turn_num
        return None

    def _annotation_processing_priority(
        self,
        annotation: Dict[str, Any],
        user_action_instance_ids: Optional[Set[int]] = None,
    ) -> int:
        """Keep activation lines ahead of cost/result zone transfers emitted in the same payload."""
        ann_types = annotation.get("type", [])
        if not isinstance(ann_types, list):
            ann_types = [ann_types] if ann_types else []
        if "AnnotationType_ObjectIdChanged" in ann_types:
            return 0
        if "AnnotationType_AbilityInstanceCreated" in ann_types:
            return 0
        if "AnnotationType_UserActionTaken" in ann_types:
            return 1
        affector_id = annotation.get("affectorId")
        if (
            "AnnotationType_ZoneTransfer" in ann_types
            and self._annotation_category(annotation) in {"Discard", "Sacrifice", "Exile"}
            and affector_id is not None
            and int(affector_id) in (user_action_instance_ids or set())
        ):
            return 2
        return 10

    def _process_game_events(self, data: Dict[str, Any]):
        """Process and display important game events."""
        game_objects = data.get("gameObjects", [])
        game_objects_by_id = {
            obj.get("instanceId"): obj
            for obj in game_objects
            if isinstance(obj, dict) and obj.get("instanceId") is not None
        }
        zones_by_id = self._zone_index(data)

        # Newer MTGA logs often represent attackers via gameObjects.attackState
        # instead of AnnotationType_AttackerDeclared.
        if game_objects:
            self._handle_attack_state_objects(game_objects)
        self._capture_target_specs(data.get("persistentAnnotations"))

        # Process annotations for high-level events
        if "annotations" in data:
            annotations = list(data["annotations"])
            pending_seat = None
            if self.game_state.pending_player_turn_header:
                pending_seat = self.game_state.player_seat_id
            elif self.game_state.pending_opponent_turn_header:
                pending_seat = self.game_state.opponent_seat_id
            players = data.get("players", [])
            if not isinstance(players, list):
                players = []
            user_action_instance_ids = {
                int(annotation["affectedIds"][0])
                for annotation in annotations
                if isinstance(annotation, dict)
                and "AnnotationType_UserActionTaken" in (annotation.get("type", []) or [])
                and isinstance(annotation.get("affectedIds"), list)
                and annotation.get("affectedIds")
                and annotation.get("affectedIds")[0] is not None
            }
            target_selecting_instance_ids = {
                int(annotation["affectedIds"][0])
                for annotation in annotations
                if isinstance(annotation, dict)
                and "AnnotationType_PlayerSelectingTargets" in (annotation.get("type", []) or [])
                and isinstance(annotation.get("affectedIds"), list)
                and annotation.get("affectedIds")
                and annotation.get("affectedIds")[0] is not None
            }
            deferred_ability_instance_ids = user_action_instance_ids | target_selecting_instance_ids
            life_total_seats_in_payload = {
                int(player.get("systemSeatNumber"))
                for player in players
                if isinstance(player, dict)
                and player.get("systemSeatNumber") is not None
                and player.get("lifeTotal") is not None
            }
            annotations.sort(
                key=lambda annotation: (
                    (
                        self._annotation_actor_seat(annotation, game_objects_by_id) == pending_seat
                        if pending_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
                        else False
                    ),
                    self._annotation_processing_priority(annotation, user_action_instance_ids),
                )
            )
            for annotation in annotations:
                self._process_annotation(
                    annotation,
                    game_objects,
                    game_objects_by_id=game_objects_by_id,
                    zones_by_id=zones_by_id,
                    life_total_seats_in_payload=life_total_seats_in_payload,
                    user_action_instance_ids=deferred_ability_instance_ids,
                    deferred_spell_instance_ids=target_selecting_instance_ids,
                )

        self._flush_deferred_life_updates()
        self._reconcile_deleted_stack_items(data.get("diffDeletedInstanceIds"))
        self._reconcile_hidden_hand_changes(data, game_objects_by_id, zones_by_id)

    def _resolve_target_label(self, target_id: Optional[int], game_objects_by_id: Dict[int, Dict[str, Any]]) -> Optional[str]:
        """Return display text for attack targets (player or permanent)."""
        if target_id is None:
            return None
        if target_id == self.game_state.player_seat_id:
            return "you"
        if target_id == self.game_state.opponent_seat_id:
            return "opponent"

        target_obj = game_objects_by_id.get(target_id)
        if not target_obj:
            return f"ID {target_id}"

        grp_id = target_obj.get("grpId")
        target_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        owner_seat = target_obj.get("ownerSeatId")
        if owner_seat == self.game_state.player_seat_id:
            owner = "your"
        elif owner_seat == self.game_state.opponent_seat_id:
            owner = "opponent's"
        else:
            owner = "unknown"
        return f"{target_name} ({owner})"

    def _annotation_actor_seat(
        self,
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> Optional[int]:
        """Best-effort seat attribution for sorting late previous-turn annotations before new-turn actions."""
        affected_ids = annotation.get("affectedIds", [])
        details = annotation.get("details", [])
        affector_id = annotation.get("affectorId")
        source_id = None
        for detail in details if isinstance(details, list) else []:
            key = detail.get("key", "")
            if key in ("source", "source_id", "sourceId", "abilitySource", "affector", "cause"):
                values = detail.get("valueInt32", [])
                if isinstance(values, list) and values:
                    source_id = values[0]
                elif isinstance(values, int):
                    source_id = values
                if source_id is not None:
                    break

        candidate_ids: List[int] = []
        if source_id is not None:
            candidate_ids.append(int(source_id))
        if affector_id is not None:
            candidate_ids.append(int(affector_id))
        for value in affected_ids if isinstance(affected_ids, list) else []:
            if value is not None:
                candidate_ids.append(int(value))

        for instance_id in candidate_ids:
            obj = self._lookup_object(instance_id, game_objects_by_id)
            owner_seat = obj.get("ownerSeatId")
            controller_seat = obj.get("controllerSeatId")
            seat_id = controller_seat if controller_seat is not None else owner_seat
            if seat_id in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                return seat_id
            mapped_source = self.game_state.ability_instance_sources.get(instance_id)
            if mapped_source is not None:
                mapped_obj = self._lookup_object(mapped_source, game_objects_by_id)
                owner_seat = mapped_obj.get("ownerSeatId")
                controller_seat = mapped_obj.get("controllerSeatId")
                seat_id = controller_seat if controller_seat is not None else owner_seat
                if seat_id in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                    return seat_id
        return None

    def _handle_ability_instance_created(
        self,
        affected_ids: List[int],
        affector_id: Optional[int],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        user_action_instance_ids: Optional[Set[int]],
    ) -> None:
        """Track ability instance source and emit non-user-action ability text when useful."""
        if not affected_ids or affector_id is None:
            return
        ability_instance_id = int(affected_ids[0])
        self.game_state.ability_instance_sources[ability_instance_id] = int(affector_id)
        if ability_instance_id in (user_action_instance_ids or set()):
            return

        ability_obj = self._lookup_object(ability_instance_id, game_objects_by_id)
        source_obj = self._lookup_object(int(affector_id), game_objects_by_id)
        source_grp_id = source_obj.get("grpId") or ability_obj.get("objectSourceGrpId")
        owner_seat = (
            ability_obj.get("controllerSeatId")
            or ability_obj.get("ownerSeatId")
            or source_obj.get("controllerSeatId")
            or source_obj.get("ownerSeatId")
        )
        ability_grp_id = ability_obj.get("grpId")
        ability_text = (
            self.card_db.get_card_ability_text(int(source_grp_id), int(ability_grp_id))
            if source_grp_id is not None and ability_grp_id is not None
            else None
        )
        if (
            source_grp_id is not None
            and owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
            and self._should_log_ability_text(source_obj, ability_text)
        ):
            card_name = self.card_db.get_card_name(int(source_grp_id))
            normalized_ability_text = self._normalize_ability_text(ability_text)
            self.game_state.ability_instance_action_texts[ability_instance_id] = normalized_ability_text
            active_turn_override = self._flush_pending_active_turn_header()
            turn_override = active_turn_override or self._ability_turn_override(owner_seat)
            label = f"[{card_name}] - {normalized_ability_text}"
            if active_turn_override is None:
                self._flush_pending_turn_header_for_seat(owner_seat)
            self._print_event(
                self._format_actor_event("", owner_seat, label, turn_override=turn_override),
                "ability",
            )
            self._register_stack_item(
                ability_instance_id,
                seat_id=owner_seat,
                label=label,
                kind="ability",
                turn_override=turn_override,
            )

    def _handle_ability_instance_deleted(self, affected_ids: List[int]) -> None:
        """Clear ability instance metadata once Arena deletes the instance."""
        if not affected_ids:
            return
        ability_instance_id = int(affected_ids[0])
        self.game_state.ability_instance_sources.pop(ability_instance_id, None)
        self.game_state.ability_instance_action_texts.pop(ability_instance_id, None)
        self.game_state.instance_target_ids.pop(ability_instance_id, None)

    def _target_ids_for_instance(self, instance_id: Optional[int]) -> List[int]:
        """Return TargetSpec target ids for a spell or ability instance."""
        if instance_id is None:
            return []
        try:
            exact_id = int(instance_id)
        except (TypeError, ValueError):
            return []
        for key in (exact_id, self._stack_key(exact_id), self._canonical_instance_id(exact_id)):
            if key is None:
                continue
            targets = self.game_state.instance_target_ids.get(int(key))
            if isinstance(targets, list) and targets:
                return list(targets)
        return []

    def _capture_target_specs(self, annotations: Any) -> None:
        """Capture persistent TargetSpec annotations for later cast/ability display."""
        if not isinstance(annotations, list):
            return
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            ann_types = annotation.get("type", [])
            if not isinstance(ann_types, list):
                ann_types = [ann_types] if ann_types else []
            if "AnnotationType_TargetSpec" not in ann_types:
                continue
            target_ids = [
                int(target_id)
                for target_id in (annotation.get("affectedIds") or [])
                if target_id is not None
            ]
            if not target_ids:
                continue
            source_ids = []
            affector_id = annotation.get("affectorId")
            if affector_id is not None:
                source_ids.append(int(affector_id))
            for detail in annotation.get("details") or []:
                if not isinstance(detail, dict):
                    continue
                if detail.get("key") != "promptParameters":
                    continue
                for value in detail.get("valueInt32") or []:
                    if value is not None:
                        source_ids.append(int(value))
            for source_id in source_ids:
                self.game_state.instance_target_ids[source_id] = target_ids
                stack_key = self._stack_key(source_id)
                if stack_key is not None:
                    self.game_state.instance_target_ids[int(stack_key)] = target_ids

    def _handle_user_action_taken(
        self,
        affected_ids: List[int],
        details: List[Dict[str, Any]],
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        """Handle explicit user action annotations for activated abilities."""
        if not affected_ids:
            return
        ability_grp_id = None
        target_ids = []
        for detail in details:
            key = detail.get("key", "")
            if key == "abilityGrpId":
                ability_grp_id = detail.get("valueInt32", [None])[0]
            elif key in ("target", "target_id"):
                target_id = detail.get("valueInt32", [None])[0]
                if target_id is not None:
                    target_ids.append(target_id)
            elif key == "targets":
                target_list = detail.get("valueInt32", [])
                if isinstance(target_list, list):
                    target_ids.extend([tid for tid in target_list if tid is not None])

        ability_instance_id = int(affected_ids[0])
        if not target_ids:
            target_ids = self._target_ids_for_instance(ability_instance_id)
        if self._flush_pending_spell_cast(ability_instance_id, game_objects_by_id):
            return
        source_instance_id = self.game_state.ability_instance_sources.get(ability_instance_id)
        source_obj = self._lookup_object(source_instance_id, game_objects_by_id) if source_instance_id is not None else {}
        source_grp_id = source_obj.get("grpId")
        owner_seat = source_obj.get("ownerSeatId")
        ability_text = (
            self.card_db.get_card_ability_text(int(source_grp_id), int(ability_grp_id))
            if source_grp_id is not None and ability_grp_id is not None
            else None
        )
        if not (
            source_obj
            and owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
            and self._should_log_ability_text(source_obj, ability_text)
        ):
            return

        dedupe_key = (ability_instance_id, int(ability_grp_id), int(source_instance_id))
        if dedupe_key in self.game_state.logged_ability_actions:
            return
        self.game_state.logged_ability_actions.add(dedupe_key)
        active_turn_override = self._flush_pending_active_turn_header()
        if active_turn_override is None:
            self._flush_pending_turn_header_for_seat(owner_seat)
        card_name = self.card_db.get_card_name(int(source_grp_id))
        normalized_ability_text = self._normalize_ability_text(ability_text)
        self.game_state.ability_instance_action_texts[ability_instance_id] = normalized_ability_text
        target_str = ""
        if target_ids:
            target_names = []
            for t_id in target_ids:
                if t_id == self.game_state.player_seat_id:
                    target_names.append("[you]")
                elif t_id == self.game_state.opponent_seat_id:
                    target_names.append("[opponent]")
                else:
                    t_obj = self._lookup_object(t_id, game_objects_by_id)
                    if t_obj:
                        target_names.append(f"[{self._object_display_label(t_obj, t_id)}]")
                    else:
                        target_names.append(f"[ID {t_id}]")
            if target_names:
                target_str = f" -> {', '.join(target_names)}"
        turn_override = active_turn_override or self._ability_turn_override(owner_seat)
        label = f"[{card_name}] - {normalized_ability_text}{target_str}"
        self._print_event(
            self._format_actor_event("", owner_seat, label, turn_override=turn_override),
            "ability",
        )
        self._register_stack_item(
            ability_instance_id,
            seat_id=owner_seat,
            label=label,
            kind="ability",
            turn_override=turn_override,
        )

    def _handle_resolution_start(
        self,
        affected_ids: List[int],
        details: List[Dict[str, Any]],
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        """Handle stack item and ability resolution annotations."""
        resolution_grp_id = None
        for detail in details:
            if detail.get("key") == "grpid":
                resolution_grp_id = detail.get("valueInt32", [None])[0]
                break
        ability_instance_id = int(affected_ids[0]) if affected_ids else None
        if ability_instance_id is not None:
            stack_item = self.game_state.stack_items.get(self._stack_key(ability_instance_id))
            if isinstance(stack_item, dict) and stack_item.get("kind") == "spell":
                self._emit_stack_item_status(ability_instance_id, "resolved")
                return
        source_instance_id = (
            self.game_state.ability_instance_sources.get(ability_instance_id)
            if ability_instance_id is not None
            else None
        )
        if resolution_grp_id is None or source_instance_id is None:
            return

        source_obj = self._lookup_object(source_instance_id, game_objects_by_id)
        source_grp_id = source_obj.get("grpId")
        owner_seat = source_obj.get("ownerSeatId")
        ability_text = (
            self.card_db.get_card_ability_text(int(source_grp_id), int(resolution_grp_id))
            if source_grp_id is not None
            else None
        )
        if not (
            owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
            and self._should_log_ability_text(source_obj, ability_text)
        ):
            return

        dedupe_key = (ability_instance_id, int(resolution_grp_id), int(source_instance_id))
        normalized_ability_text = self._normalize_ability_text(ability_text)
        target_ids = self._target_ids_for_instance(ability_instance_id)
        target_id = target_ids[0] if target_ids else None
        target_obj = self._lookup_object(target_id, game_objects_by_id) if target_id else {}
        target_objs = self._target_objects_for_annotation(target_ids, game_objects_by_id) if target_ids else []
        target_str = self._format_target_suffix(target_id, target_obj, target_objs)
        resolution_label = f"[{self.card_db.get_card_name(int(source_grp_id))}] - {normalized_ability_text}{target_str}"
        if self._emit_stack_item_status(
            ability_instance_id,
            "resolved",
            resolution_label=resolution_label,
        ):
            self.game_state.logged_ability_resolutions.add(dedupe_key)
            return
        if dedupe_key in self.game_state.logged_ability_resolutions:
            return
        prior_text = self.game_state.ability_instance_action_texts.get(ability_instance_id)
        if prior_text == normalized_ability_text:
            self.game_state.logged_ability_resolutions.add(dedupe_key)
            return
        self.game_state.logged_ability_resolutions.add(dedupe_key)
        active_turn_override = self._flush_pending_active_turn_header()
        if active_turn_override is None:
            self._flush_pending_turn_header_for_seat(owner_seat)
        card_name = self.card_db.get_card_name(int(source_grp_id))
        self._emit_ability_event(
            "✨",
            owner_seat,
            card_name,
            ability_text,
            target_text=target_str,
            turn_override=active_turn_override or self._ability_turn_override(owner_seat),
        )

    def _handle_scry_annotation(self, affected_ids: List[int], card_obj: Dict[str, Any]) -> None:
        """Handle scry annotations."""
        if not affected_ids or not card_obj:
            return
        owner_seat = card_obj.get("ownerSeatId")
        self._flush_pending_turn_header_for_seat(owner_seat)
        self._print_event(
            self._format_actor_event("🔮", owner_seat, "scried"),
            "ability",
        )

    def _handle_tapped_untapped_permanent(
        self,
        affected_ids: List[int],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        """Log meaningful tap/untap results from non-mana abilities."""
        if not affected_ids:
            return
        tapped = None
        for detail in annotation.get("details") or []:
            if not isinstance(detail, dict) or detail.get("key") != "tapped":
                continue
            values = detail.get("valueInt32", [])
            if isinstance(values, list) and values:
                tapped = values[0]
            elif isinstance(values, int):
                tapped = values
            break
        if tapped not in (0, 1):
            return

        affector_id = annotation.get("affectorId")
        if affector_id is None:
            return
        ability_instance_id = int(affector_id)
        source_instance_id = self.game_state.ability_instance_sources.get(ability_instance_id)
        if source_instance_id is None:
            return
        ability_obj = self._lookup_object(ability_instance_id, game_objects_by_id)
        source_obj = self._lookup_object(source_instance_id, game_objects_by_id)
        target_id = int(affected_ids[0])
        target_obj = self._lookup_object(target_id, game_objects_by_id)
        if not source_obj or not target_obj:
            return

        source_grp_id = source_obj.get("grpId") or ability_obj.get("objectSourceGrpId")
        ability_grp_id = ability_obj.get("grpId")
        ability_text = (
            self.card_db.get_card_ability_text(int(source_grp_id), int(ability_grp_id))
            if source_grp_id is not None and ability_grp_id is not None
            else None
        )
        if not self._should_log_ability_text(source_obj, ability_text):
            return

        source_seat = source_obj.get("controllerSeatId")
        if source_seat is None:
            source_seat = source_obj.get("ownerSeatId")
        if source_seat not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            return

        action = "tapped" if int(tapped) == 1 else "untapped"
        dedupe_key = (ability_instance_id, target_id, action)
        if dedupe_key in self.game_state.logged_tap_untap_events:
            return
        self.game_state.logged_tap_untap_events.add(dedupe_key)

        source_name = self._object_display_name(source_obj, source_instance_id)
        target_label = self._object_display_label(target_obj, target_id)
        self._flush_pending_turn_header_for_seat(source_seat)
        self._print_event(
            self._format_actor_event(
                "",
                source_seat,
                f"[{source_name}] {action} [{target_label}]",
                turn_override=self._ability_turn_override(source_seat),
            ),
            "ability",
        )

    def _process_annotation(
        self,
        annotation: Dict[str, Any],
        game_objects: List[Dict[str, Any]],
        game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
        zones_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
        life_total_seats_in_payload: Optional[Set[int]] = None,
        user_action_instance_ids: Optional[Set[int]] = None,
        deferred_spell_instance_ids: Optional[Set[int]] = None,
    ):
        """Process a single annotation (game event)."""
        ann_type = annotation.get("type", [])
        if not isinstance(ann_type, list):
            ann_type = [ann_type] if ann_type else []
        affected_ids = annotation.get("affectedIds", [])
        details = annotation.get("details", [])
        affector_id = annotation.get("affectorId")

        if game_objects_by_id is None:
            game_objects_by_id = {
                obj.get("instanceId"): obj
                for obj in game_objects
                if isinstance(obj, dict) and obj.get("instanceId") is not None
            }

        parsed_details = AnnotationDetails.from_annotation(annotation)
        category = parsed_details.category
        zone_src = parsed_details.zone_src
        zone_dest = parsed_details.zone_dest
        target_id = parsed_details.target_id
        target_ids = parsed_details.target_ids
        source_id = parsed_details.source_id
        orig_instance_id = parsed_details.orig_instance_id
        new_instance_id = parsed_details.new_instance_id

        if "AnnotationType_ObjectIdChanged" in ann_type:
            self._record_object_id_change(orig_instance_id, new_instance_id)
            return

        if not target_ids:
            lookup_ids = []
            if affected_ids:
                lookup_ids.append(affected_ids[0])
            if affector_id is not None:
                lookup_ids.append(affector_id)
            for lookup_id in lookup_ids:
                target_ids = self._target_ids_for_instance(lookup_id)
                if target_ids:
                    target_id = target_ids[0]
                    break

        if self._process_pre_object_annotation(
            ann_type,
            affected_ids,
            details,
            affector_id,
            annotation,
            game_objects,
            game_objects_by_id,
            life_total_seats_in_payload,
            user_action_instance_ids,
        ):
            return

        # Only process if we have affected cards
        if not affected_ids:
            self._log_unhandled_annotation(
                annotation,
                game_objects_by_id=game_objects_by_id,
                note="no affected ids",
            )
            return

        instance_id = affected_ids[0]

        # Find the card object for this instance
        card_obj = self._lookup_object(instance_id, game_objects_by_id)
        target_obj = self._lookup_object(target_id, game_objects_by_id) if target_id else None
        target_objs = self._target_objects_for_annotation(target_ids, game_objects_by_id) if target_ids else []

        # Handle different annotation types
        if "AnnotationType_ZoneTransfer" in ann_type:
            if self._process_zone_transfer_annotation(
                category=category,
                instance_id=int(instance_id),
                card_obj=card_obj,
                annotation=annotation,
                game_objects_by_id=game_objects_by_id,
                zones_by_id=zones_by_id,
                zone_src=zone_src,
                zone_dest=zone_dest,
                source_id=source_id,
                affector_id=affector_id,
                target_id=target_id,
                target_obj=target_obj,
                target_objs=target_objs,
                deferred_spell_instance_ids=deferred_spell_instance_ids,
            ):
                return

        # Handle resolution annotations
        elif "AnnotationType_ResolutionStart" in ann_type:
            self._handle_resolution_start(affected_ids, details, game_objects_by_id)
            return

        elif "AnnotationType_Scry" in ann_type:
            self._handle_scry_annotation(affected_ids, card_obj)
            return

        if "AnnotationType_ZoneTransfer" in ann_type and self._known_zone_transfer_category(category):
            return

        self._log_unhandled_annotation(annotation, game_objects_by_id=game_objects_by_id)

    def _handle_modified_life(
        self,
        affected_ids: List[int],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        *,
        life_total_seats_in_payload: Set[int],
    ) -> None:
        """Handle life deltas when the payload does not include that player's new life total."""
        details = annotation.get("details", [])
        diff = None
        for detail in details if isinstance(details, list) else []:
            if detail.get("key") in ("life", "amount"):
                values = detail.get("valueInt32", [])
                if isinstance(values, list) and values:
                    diff = values[0]
                elif isinstance(values, int):
                    diff = values
                break
        if diff is None:
            return

        affector_id = annotation.get("affectorId")
        source_instance_id = (
            self.game_state.ability_instance_sources.get(int(affector_id))
            if affector_id is not None
            else None
        )
        source_obj = self._lookup_object(source_instance_id, game_objects_by_id) if source_instance_id is not None else {}
        if not source_obj and affector_id is not None:
            source_obj = self._lookup_object(int(affector_id), game_objects_by_id)
        source_seat = source_obj.get("controllerSeatId")
        if source_seat is None:
            source_seat = source_obj.get("ownerSeatId")
        source_label = None
        if source_obj:
            source_label = self._object_display_name(source_obj, source_obj.get("instanceId") or source_instance_id or affector_id)

        for raw_seat_id in affected_ids:
            seat_id = self._normalize_seat_id(raw_seat_id)
            if seat_id not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                continue
            if seat_id in life_total_seats_in_payload:
                continue
            old_life = (
                self.game_state.player_life
                if seat_id == self.game_state.player_seat_id
                else self.game_state.opponent_life
            )
            new_life = int(old_life) + int(diff)
            if seat_id == self.game_state.player_seat_id:
                self.game_state.player_life = new_life
            else:
                self.game_state.opponent_life = new_life
            self._emit_life_change(
                int(seat_id),
                int(diff),
                new_life,
                source_seat_override=source_seat,
                source_label=source_label,
            )

    def _format_card_type(self, card_types: List[str]) -> str:
        """Format card types for display."""
        if not card_types:
            return "Card"

        # Clean up and prioritize card types
        types = [t.replace("CardType_", "") for t in card_types]

        # Show main types
        main_types = []
        for t in ["Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker", "Land"]:
            if t in types:
                main_types.append(t)

        return ", ".join(main_types) if main_types else "Card"

    def _get_card_type_category(self, card_types: List[str]) -> str:
        """Return a single category for breakdown: Land, Creature, Instant, Sorcery, Enchantment, Artifact, Planeswalker, or Other."""
        if not card_types:
            return "Other"
        types = [t.replace("CardType_", "") for t in card_types]
        for cat in ["Land", "Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker"]:
            if cat in types:
                return cat
        return "Other"

    def _handle_ability_activated(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle activated ability events."""
        if not affected_ids:
            return
        
        details = annotation.get("details", [])
        ability_source_id = affected_ids[0] if affected_ids else None
        target_ids = []
        ability_grp_id = None
        
        # Extract ability details
        for detail in details:
            key = detail.get("key", "")
            if key == "target" or key == "target_id":
                target_id = detail.get("valueInt32", [None])[0]
                if target_id:
                    target_ids.append(target_id)
            elif key == "targets":
                target_list = detail.get("valueInt32", [])
                if target_list:
                    target_ids.extend(target_list)
            elif key == "abilityGrpId":
                ability_grp_id = detail.get("valueInt32", [None])[0]
        
        # Find the source card
        source_obj = None
        for obj in game_objects:
            if obj.get("instanceId") == ability_source_id:
                source_obj = obj
                break
        
        if source_obj:
            grp_id = source_obj.get("grpId")
            owner_seat = source_obj.get("ownerSeatId")
            active_turn_override = self._flush_pending_active_turn_header()
            if active_turn_override is None:
                self._flush_pending_turn_header_for_seat(owner_seat)
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            ability_text = (
                self.card_db.get_card_ability_text(int(grp_id), int(ability_grp_id))
                if grp_id is not None and ability_grp_id is not None
                else None
            )
            
            # Find targets
            target_str = ""
            if target_ids:
                target_names = []
                for t_id in target_ids:
                    # Check if it's a player seat
                    if t_id == self.game_state.player_seat_id:
                        target_names.append("you")
                    elif t_id == self.game_state.opponent_seat_id:
                        target_names.append("opponent")
                    else:
                        # Find target object
                        for obj in game_objects:
                            if obj.get("instanceId") == t_id:
                                t_grp_id = obj.get("grpId")
                                t_name = self.card_db.get_card_name(t_grp_id) if t_grp_id else f"[ID: {t_id}]"
                                t_owner_seat = obj.get("ownerSeatId")
                                t_owner = "your" if t_owner_seat == self.game_state.player_seat_id else "opponent's"
                                target_names.append(f"{t_name} ({t_owner})")
                                break
                        else:
                            target_names.append(f"[ID: {t_id}]")
                
                if target_names:
                    target_str = f" targeting {', '.join(target_names)}"

            if ability_text and self._should_log_ability_text(source_obj, ability_text):
                self._emit_ability_event(
                    "🔮",
                    owner_seat,
                    card_name,
                    ability_text,
                    target_text=target_str,
                    turn_override=active_turn_override or self._ability_turn_override(owner_seat),
                )
            elif ability_text:
                return
            else:
                self._print_event(
                    self._format_actor_event(
                        "🔮",
                        owner_seat,
                        f"activated ability: [{card_name}]{target_str}",
                        turn_override=active_turn_override or self._ability_turn_override(owner_seat),
                    ),
                    "ability",
                )

    def _handle_triggered_ability(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle triggered ability events."""
        if not affected_ids:
            return
        
        details = annotation.get("details", [])
        trigger_source_id = affected_ids[0] if affected_ids else None
        
        # Extract trigger details
        trigger_type = None
        for detail in details:
            key = detail.get("key", "")
            if key == "trigger_type" or key == "trigger":
                trigger_type = detail.get("valueString", [None])[0]
                break
        
        # Find the source card
        source_obj = None
        for obj in game_objects:
            if obj.get("instanceId") == trigger_source_id:
                source_obj = obj
                break
        
        if source_obj:
            grp_id = source_obj.get("grpId")
            owner_seat = source_obj.get("ownerSeatId")
            active_turn_override = self._flush_pending_active_turn_header()
            if active_turn_override is None:
                self._flush_pending_turn_header_for_seat(owner_seat)
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            trigger_desc = trigger_type if trigger_type else "triggered"
            owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
            self._print_event(
                self._format_actor_event(
                    "",
                    owner_seat,
                    f"Triggered: [{card_name}] ({owner}) - {trigger_desc}",
                    turn_override=active_turn_override or self._ability_turn_override(owner_seat),
                ),
                "ability",
            )

    def get_player_cards(self) -> List[CardEvent]:
        """Get list of cards played by the player."""
        return self.player_cards.copy()

    def get_opponent_cards(self) -> List[CardEvent]:
        """Get list of cards played by opponents."""
        return self.opponent_cards.copy()

    def clear_history(self):
        """Clear card history."""
        self.player_cards.clear()
        self.opponent_cards.clear()
