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
from .deck_llm import identify_deck, is_deck_llm_enabled, diagnose as deck_llm_diagnose
from .paths import DATA_DIR
from .analytics import AnalyticsStore
from .annotations import AnnotationDetails
from .tracker_analytics import TrackerAnalyticsMixin
from .tracker_stack import TrackerStackMixin
from .tracker_zone_transfers import TrackerZoneTransferMixin
from .log_sanitize import scrub_raw_log
from .opening_hand import (
    game_objects_by_instance,
    state_has_opening_hand_zone,
    visible_opening_hand_snapshots,
)
from .rendering import ANSI_RESET, ANSI_STYLES, apply_style, display_path_without_username, should_use_colors
from .state import CardEvent, GameState


class CardTracker(TrackerAnalyticsMixin, TrackerStackMixin, TrackerZoneTransferMixin):
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

    def _should_announce_attack(self, turn_num: int, instance_id: Optional[int], owner_seat: Optional[int]) -> bool:
        """Return True if this attacker for this turn has not already been announced."""
        if not turn_num or turn_num <= 0 or instance_id is None:
            return True
        key = (int(turn_num), int(instance_id), owner_seat)
        if key in self.game_state.reported_attack_keys:
            return False
        self.game_state.reported_attack_keys.add(key)
        return True

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

    @staticmethod
    def _unique_names(names: List[str]) -> List[str]:
        """Return ordered unique non-empty names."""
        out: List[str] = []
        seen: Set[str] = set()
        for name in names:
            if not isinstance(name, str):
                continue
            clean = name.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            out.append(clean)
        return out

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

    def _format_commander_names(self, names: List[str]) -> str:
        """Format one or two commander names for display."""
        unique = self._unique_names([self._refresh_fallback_name_text(name) for name in names])
        return " + ".join(unique) if unique else "Unknown"

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

    def _friendly_format_label(self, raw_format: Optional[str] = None) -> str:
        """Convert raw queue/format identifiers into user-facing labels."""
        raw = raw_format if raw_format is not None else self.game_state.format_str
        if not isinstance(raw, str) or not raw.strip() or raw == "Unknown":
            if self._is_brawl_format():
                return self._best_brawl_format_label()
            return "Standard Best-of-3" if self.game_state.match_type == "best_of_3" else "Standard Best-of-1"

        normalized = self._normalize_match_text(raw)
        if normalized.startswith("mwm") or normalized.startswith("midweekmagic"):
            return self._friendly_midweek_label(raw)
        if "historicbrawl" in normalized:
            return "Historic Brawl"
        if "brawl" in normalized:
            return "Brawl"
        if normalized in {"traditionalstandard", "constructedbestof3", "bestof3", "traditional_ladder"}:
            return "Standard Best-of-3"
        if normalized in {"standard", "ladder", "play", "constructedbestof1", "bestof1"}:
            return "Standard Best-of-1"
        if normalized == "historicplay" or normalized == "historic":
            return "Historic"
        if normalized == "explorerplay" or normalized == "explorer":
            return "Explorer"
        if normalized == "timelessplay" or normalized == "timeless":
            return "Timeless"
        if normalized == "alchemy":
            return "Alchemy"
        if "traditionalstandard" in normalized:
            return "Standard Best-of-3"
        if "historic" in normalized and "brawl" not in normalized:
            return "Historic"
        if "explorer" in normalized:
            return "Explorer"
        if "timeless" in normalized:
            return "Timeless"
        if "standard" in normalized:
            return "Standard Best-of-3" if "traditional" in normalized or "bestof3" in normalized else "Standard Best-of-1"
        return raw

    @staticmethod
    def _friendly_midweek_label(raw_format: str) -> str:
        """Convert MWM event identifiers into readable Midweek Magic labels."""
        text = re.sub(r"^MWM[_-]?", "", raw_format.strip(), flags=re.IGNORECASE)
        text = re.sub(r"[_-]?\d{8}$", "", text)
        text = re.sub(r"[_-]+", " ", text).strip()
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return f"Midweek Magic - {text}" if text else "Midweek Magic"

    def _set_match_format(self, fmt: str) -> bool:
        """Apply trusted live match format metadata and infer match length."""
        if not isinstance(fmt, str) or not fmt:
            return False
        updated = self.game_state.format_str != fmt
        self.game_state.format_str = fmt
        normalized = self._normalize_match_text(fmt)
        if "traditional" in normalized or "bestof3" in normalized or normalized in {"constructedbestof3", "bestof3"}:
            if self.game_state.match_type != "best_of_3":
                self.game_state.match_type = "best_of_3"
                updated = True
        elif (
            "bestof1" in normalized
            or normalized.startswith("mwm")
            or normalized.startswith("midweekmagic")
            or normalized in {"standard", "ladder", "play", "constructedbestof1", "bestof1"}
        ):
            if self.game_state.match_type != "best_of_1":
                self.game_state.match_type = "best_of_1"
                updated = True
        return updated

    def _seat_stats(self, seat_id: Optional[int]) -> Optional[Dict[str, int]]:
        """Return mutable per-seat stats dict when seat is known."""
        if seat_id not in (1, 2):
            return None
        return self.game_state.match_stats[int(seat_id)]

    def _record_damage_dealt(
        self,
        amount: int,
        source_seat: Optional[int],
        target_seat: Optional[int] = None,
        queue_life_reconciliation: bool = True,
    ) -> None:
        """Accumulate dealt/self-damage stats and queue player-life reconciliation."""
        if amount <= 0:
            return
        stats = self._seat_stats(source_seat)
        if stats is not None:
            stats["total_damage"] += int(amount)
            if source_seat == target_seat:
                stats["self_damage"] += int(amount)
        if (
            queue_life_reconciliation
            and target_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
        ):
            self.game_state.pending_damage_to_seat[int(target_seat)] = (
                self.game_state.pending_damage_to_seat.get(int(target_seat), 0) + int(amount)
            )

    def _infer_life_loss_source_seat(
        self,
        target_seat: Optional[int],
        turn_override: Optional[int] = None,
    ) -> Optional[int]:
        """Best-effort source seat for unmatched player life loss."""
        if target_seat not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            return None

        attacking_seats = {
            info.get("owner_seat")
            for info in self.game_state.current_combat_attackers.values()
            if isinstance(info, dict) and info.get("target_id") == target_seat
        }
        attacking_seats.discard(None)
        if len(attacking_seats) == 1:
            return next(iter(attacking_seats))

        recent_attackers = set(self.game_state.recent_attack_sources_by_target.get(int(target_seat), set()))
        recent_attackers.discard(None)
        if len(recent_attackers) == 1:
            return next(iter(recent_attackers))

        if self.game_state.active_player in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            return self.game_state.active_player
        return None

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

    def _set_player_commanders_from_ids(self, command_zone_ids: List[int]) -> None:
        """Store player's commander names from deck metadata command zone ids."""
        names = self._unique_names(
            [self.card_db.get_card_name(int(card_id)) for card_id in command_zone_ids if card_id is not None]
        )
        if names:
            self.game_state.player_commanders = names

    def _capture_starting_deck_totals(self, data: Dict[str, Any]) -> None:
        """Capture best-effort starting deck totals from early hand/library/command zone sizes."""
        if self.game_state.opening_hand_capture_closed:
            return
        if self.game_state.turn_number and self.game_state.turn_number > 1:
            return
        if self._has_gameplay_annotations(data):
            return

        zones = data.get("zones", [])
        if not isinstance(zones, list):
            return

        seat_totals: Dict[int, int] = {}
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            if zone.get("type") not in {"ZoneType_Hand", "ZoneType_Library", "ZoneType_Command"}:
                continue
            owner_seat = self._normalize_seat_id(zone.get("ownerSeatId"))
            obj_ids = zone.get("objectInstanceIds", [])
            if owner_seat not in (1, 2) or not isinstance(obj_ids, list):
                continue
            seat_totals[int(owner_seat)] = seat_totals.get(int(owner_seat), 0) + len(obj_ids)

        for seat_id, total in seat_totals.items():
            if total <= 0:
                continue
            previous = self.game_state.observed_starting_deck_total_by_seat.get(int(seat_id), 0)
            if total > previous:
                self.game_state.observed_starting_deck_total_by_seat[int(seat_id)] = total

    def _sync_commander_views_from_seats(self) -> None:
        """Sync player/opponent commander lists from seat-indexed commander map."""
        g = self.game_state
        if g.player_seat_id in g.commanders_by_seat:
            g.player_commanders = self._unique_names(g.commanders_by_seat[g.player_seat_id])
        if g.opponent_seat_id in g.commanders_by_seat:
            g.opponent_commanders = self._unique_names(g.commanders_by_seat[g.opponent_seat_id])

    def _best_brawl_format_label(self) -> str:
        """Return best Brawl label based on known metadata."""
        candidates = [self.game_state.format_str, self.game_state.player_deck_event_name]
        for candidate in self._deck_candidates.values():
            candidates.append(candidate.get("format_attr"))
            candidates.append(candidate.get("internal_event_name"))
        for raw in candidates:
            text = self._normalize_match_text(raw)
            if not text:
                continue
            if "historicbrawl" in text:
                return "Historic Brawl"
            if "brawl" in text:
                return "Brawl"
        return "Brawl"

    def _candidate_is_brawl(self, candidate: Dict[str, Any]) -> bool:
        """Return True when candidate metadata clearly identifies a Brawl deck."""
        for raw in (
            candidate.get("format_attr"),
            candidate.get("internal_event_name"),
        ):
            text = self._normalize_match_text(raw)
            if "brawl" in text:
                return True
        return False

    def _is_brawl_format(self, format_text: Optional[str] = None) -> bool:
        """Return True when the supplied/current format text clearly indicates Brawl."""
        text = self._normalize_match_text(format_text if format_text is not None else self.game_state.format_str)
        return "brawl" in text

    def _clear_commander_state(self) -> None:
        """Clear commander metadata when the current match is not a commander format."""
        self.game_state.commanders_by_seat = {}
        self.game_state.player_commanders = []
        self.game_state.opponent_commanders = []
        self.game_state.player_commanders_announced = False
        self.game_state.opponent_commanders_announced = False

    def _update_format_from_game_state(self, data: Dict[str, Any]) -> None:
        """Infer Brawl/Historic Brawl from live game state."""
        game_info = data.get("gameInfo")
        variant_text = ""
        if isinstance(game_info, dict):
            variant = game_info.get("variant")
            if isinstance(variant, str):
                variant_text = self._normalize_match_text(variant)
        deck_constraint = data.get("deckConstraintInfo")
        min_commander_size = None
        if isinstance(deck_constraint, dict):
            min_commander_size = deck_constraint.get("minCommanderSize")
        zones = data.get("zones", [])
        has_populated_command_zone = any(
            isinstance(zone, dict)
            and zone.get("type") == "ZoneType_Command"
            and bool(zone.get("objectInstanceIds"))
            for zone in zones
        ) if isinstance(zones, list) else False

        if "brawl" in variant_text or (isinstance(min_commander_size, int) and min_commander_size > 0) or has_populated_command_zone:
            self.game_state.format_str = self._best_brawl_format_label()
        elif isinstance(min_commander_size, int) and min_commander_size == 0 and not self._is_brawl_format():
            self._clear_commander_state()

    def _update_commanders_from_game_state(self, data: Dict[str, Any]) -> None:
        """Capture visible commanders from the shared command zone."""
        if not self._is_brawl_format():
            self._clear_commander_state()
            return
        zones = data.get("zones", [])
        if not isinstance(zones, list):
            return

        game_objects = data.get("gameObjects", [])
        game_objects_by_id = {
            obj.get("instanceId"): obj
            for obj in game_objects
            if isinstance(obj, dict) and obj.get("instanceId") is not None
        }

        command_by_seat: Dict[int, List[str]] = {}
        for zone in zones:
            if not isinstance(zone, dict) or zone.get("type") != "ZoneType_Command":
                continue
            for obj_id in zone.get("objectInstanceIds", []) or []:
                obj = self._lookup_object(obj_id, game_objects_by_id)
                if not isinstance(obj, dict) or obj.get("type") != "GameObjectType_Card":
                    continue
                owner_seat = obj.get("ownerSeatId")
                grp_id = obj.get("grpId") or obj.get("overlayGrpId") or obj.get("objectSourceGrpId")
                if owner_seat is None or grp_id is None:
                    continue
                command_by_seat.setdefault(int(owner_seat), []).append(self.card_db.get_card_name(int(grp_id)))

        if not command_by_seat:
            if not self.game_state.commanders_by_seat:
                self._clear_commander_state()
            return

        self.game_state.commanders_by_seat = {
            seat: self._unique_names(names)
            for seat, names in command_by_seat.items()
            if self._unique_names(names)
        }

        if self.game_state.player_seat_id not in (1, 2) and self.game_state.player_commanders:
            player_commander_names = set(self._unique_names(self.game_state.player_commanders))
            matching_seats = [
                seat for seat, names in self.game_state.commanders_by_seat.items()
                if set(names) == player_commander_names
            ]
            if len(matching_seats) == 1:
                self.game_state.player_seat_id = matching_seats[0]
                other_seats = [seat for seat in self.game_state.commanders_by_seat.keys() if seat != matching_seats[0]]
                if len(other_seats) == 1:
                    self.game_state.opponent_seat_id = other_seats[0]

        if self.game_state.player_seat_id in (1, 2) and self.game_state.opponent_seat_id not in (1, 2):
            other_seats = [seat for seat in self.game_state.commanders_by_seat.keys() if seat != self.game_state.player_seat_id]
            if len(other_seats) == 1:
                self.game_state.opponent_seat_id = other_seats[0]

        self._sync_commander_views_from_seats()
        if self.game_state._reserved_players:
            for r in self.game_state._reserved_players:
                if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                    self.game_state.player_display_name = self.game_state.player_display_name or r["name"]
                elif r.get("seat") == self.game_state.opponent_seat_id and r.get("name"):
                    self.game_state.opponent_display_name = r["name"]

    def _maybe_print_pregame_commander_lines(self) -> None:
        """Print commander lines after game start once discovered, before turn banners."""
        if not self.game_state.in_match or self.game_state.last_turn_announced > 0:
            return
        if not self._is_brawl_format():
            return
        if self.game_state.player_commanders and not self.game_state.player_commanders_announced:
            self._print_line(f"   Your Commander: {self._format_commander_names(self.game_state.player_commanders)}")
            self.game_state.player_commanders_announced = True
        if self.game_state.opponent_commanders and not self.game_state.opponent_commanders_announced:
            self._print_line(f"   Opponent Commander: {self._format_commander_names(self.game_state.opponent_commanders)}")
            self.game_state.opponent_commanders_announced = True

    def _maybe_print_seat_resolution(self) -> None:
        """Print seat resolution once if it becomes known after the start block."""
        if (
            not self.game_state.in_match
            or self.game_state.last_turn_announced > 0
            or self.game_state.game_start_time is None
            or self.game_state.seat_line_announced
        ):
            return
        if self.game_state.player_seat_id in (1, 2):
            self._print_line(f"   Seat: {self.game_state.player_seat_id}")
            self.game_state.seat_line_announced = True

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

    def _reset_game_state(self):
        """Reset game state for a new game."""
        self.game_state = GameState()
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False


    def _find_nested(self, data: Any, key: str) -> Any:
        """Find a key in nested data structure."""
        if isinstance(data, dict):
            if key in data:
                return data[key]
            for value in data.values():
                result = self._find_nested(value, key)
                if result is not None:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self._find_nested(item, key)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _normalize_seat_id(value: Any) -> Optional[int]:
        """Convert seat/team IDs to 1/2 when possible."""
        try:
            seat = int(value)
        except (TypeError, ValueError):
            return None
        return seat if seat in (1, 2) else None

    def _set_winner_seat(self, seat_id: Any, *, reason: str, priority: int) -> bool:
        """Set winner seat if source priority is strong enough.

        Priority guide:
          4: Structured game-over JSON (authoritative)
          3: Local client concede request
          2: Seat-specific concede / generic JSON hints
          1: Text heuristics (left/disconnect/concede phrases)
        """
        seat = self._normalize_seat_id(seat_id)
        if seat is None:
            return False

        current = self.game_state.winner_seat
        current_priority = getattr(self.game_state, "winner_priority", 0)

        # Never let weaker evidence override stronger evidence.
        if current is not None and priority < current_priority:
            return False

        # Avoid flip-flopping on same-priority contradictory hints.
        if current is not None and priority == current_priority:
            return False

        self.game_state.winner_seat = seat
        self.game_state.winner_priority = priority
        self.game_state.winner_reason = reason


        return True

    def _try_parse_winner_from_json(self, data: Optional[Dict[str, Any]]) -> Optional[int]:
        """Try to get winner seat (1 or 2) from parsed game-end JSON. Returns None if not found."""
        if not data or not isinstance(data, dict):
            return None

        latest_result = self._extract_latest_game_result(data)
        if latest_result is not None:
            seat = self._normalize_seat_id(
                latest_result.get("winningTeamId")
                or latest_result.get("winningteamid")
                or latest_result.get("winnerSeatId")
                or latest_result.get("winningSeatId")
            )
            if seat is not None:
                return seat

        # Loser seat → winner is the other seat
        loser = self._find_nested(data, "loserSeatId") or self._find_nested(data, "loserSeat")
        loser_seat = self._normalize_seat_id(loser)
        if loser_seat is not None:
            return 2 if loser_seat == 1 else 1

        # Winning team/seat fallback (MTGA may use different keys outside structured result arrays).
        for key in ("winningTeamId", "winningteamid", "winnerSeatId", "winnerSeat", "winningSeatId", "winner"):
            v = self._find_nested(data, key)
            seat = self._normalize_seat_id(v)
            if seat is not None:
                return seat

        # Fallback: infer from player statuses (PendingLoss/InGame) at game over.
        players = self._find_nested(data, "players")
        if isinstance(players, list):
            pending_loss_seats: List[int] = []
            in_game_seats: List[int] = []
            for player in players:
                if not isinstance(player, dict):
                    continue
                seat = self._normalize_seat_id(player.get("systemSeatNumber"))
                if seat is None:
                    continue
                status = str(player.get("status", ""))
                if "PendingLoss" in status:
                    pending_loss_seats.append(seat)
                elif "InGame" in status:
                    in_game_seats.append(seat)
            if len(in_game_seats) == 1:
                return in_game_seats[0]
            if len(pending_loss_seats) == 1:
                return 2 if pending_loss_seats[0] == 1 else 1

        # Fallback: infer from team statuses.
        teams = self._find_nested(data, "teams")
        if isinstance(teams, list):
            pending_loss_teams: List[int] = []
            for team in teams:
                if not isinstance(team, dict):
                    continue
                team_id = self._normalize_seat_id(team.get("id"))
                if team_id is None:
                    continue
                if "PendingLoss" in str(team.get("status", "")):
                    pending_loss_teams.append(team_id)
            if len(pending_loss_teams) == 1:
                return 2 if pending_loss_teams[0] == 1 else 1

        return None

    def _extract_latest_game_result(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the newest structured WinLoss game result, falling back to match scope."""
        return self._extract_latest_structured_result(data, "WinLoss")

    def _extract_latest_draw_result(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the newest structured draw result, falling back to match scope."""
        return self._extract_latest_structured_result(data, "Draw")

    def _extract_latest_structured_result(
        self,
        data: Dict[str, Any],
        result_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Return newest result matching `result_name`, preferring game scope."""
        result_groups: List[List[Dict[str, Any]]] = []
        game_info = self._find_nested(data, "gameInfo")
        if isinstance(game_info, dict) and isinstance(game_info.get("results"), list):
            result_groups.append([r for r in game_info["results"] if isinstance(r, dict)])
        final_match = self._find_nested(data, "finalMatchResult")
        if isinstance(final_match, dict) and isinstance(final_match.get("resultList"), list):
            result_groups.append([r for r in final_match["resultList"] if isinstance(r, dict)])
        intermission = self._find_nested(data, "intermissionReq")
        if isinstance(intermission, dict) and isinstance(intermission.get("result"), dict):
            result_groups.append([intermission["result"]])

        match_scope_fallback: Optional[Dict[str, Any]] = None
        unscoped_fallback: Optional[Dict[str, Any]] = None
        for results in result_groups:
            for result in reversed(results):
                result_type = str(result.get("result", ""))
                if result_name not in result_type:
                    continue
                scope = str(result.get("scope", ""))
                if "MatchScope_Game" in scope:
                    return result
                if match_scope_fallback is None and "MatchScope_Match" in scope:
                    match_scope_fallback = result
                elif match_scope_fallback is None and unscoped_fallback is None:
                    unscoped_fallback = result
        return match_scope_fallback or unscoped_fallback

    def _check_if_mid_game(self):
        """Only set mid-game if the tail of the log shows an active game and no match-end (lobby = match already ended)."""
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            tail = lines[-300:] if len(lines) > 300 else lines

            # If the tail contains match-end, we're in lobby or between games — not mid-game
            match_end_markers = (
                "matchcompleted", "gamecompleted", "concedereq", "matchendscene",
                "you left", "opponent left", "you concede", "opponent concede",
                "finalresults", "on sceneloaded for matchendscene"
            )
            tail_text = "\n".join(tail).lower()
            if any(m in tail_text for m in match_end_markers):
                return

            # No match-end in tail; check for active game state (turn > 0 or zones with cards)
            for line in reversed(tail):
                for event in self._extract_game_state_events(line):
                    if event.get("type") != "game_state":
                        continue
                    data = event.get("data", {})
                    if "turnInfo" in data:
                        turn_num = (data.get("turnInfo") or {}).get("turnNumber", 0)
                        if turn_num and turn_num > 0:
                            self.waiting_for_next_game = True
                            self._print_line("\n" + "="*75)
                            self._print_line("⚠️  DETECTED GAME IN PROGRESS")
                            self._print_line("="*75)
                            self._print_line("   Tracker launched mid-game.")
                            self._print_line("   Will start tracking at the beginning of the next game.")
                            self._print_line("="*75 + "\n")
                            return
                    if "zones" in data:
                        for zone in (data.get("zones") or []):
                            ztype = (zone.get("type") or "")
                            objs = zone.get("objectInstanceIds", [])
                            if objs and ("Battlefield" in ztype or "Hand" in ztype):
                                self.waiting_for_next_game = True
                                self._print_line("\n" + "="*75)
                                self._print_line("⚠️  DETECTED GAME IN PROGRESS")
                                self._print_line("="*75)
                                self._print_line("   Tracker launched mid-game.")
                                self._print_line("   Will start tracking at the beginning of the next game.")
                                self._print_line("="*75 + "\n")
                                return
        except Exception:
            pass

    def _process_new_events(self):
        """Process new events from the log file."""
        read_entries = getattr(self.parser, "read_new_entries", None)
        if callable(read_entries):
            for entry in read_entries():
                routed = self.parser.route_entry(entry) if hasattr(self.parser, "route_entry") else None
                if routed is not None:
                    category = getattr(routed, "category", None)
                    if category == "unknown":
                        self._append_parser_diagnostic_log(entry.body)
                    if (
                        category == "unknown"
                        or getattr(routed, "malformed_json", False)
                        or category
                        in {
                            "connection_state",
                            "tcp_connection_close",
                            "websocket_closed",
                            "connection_error",
                        }
                    ):
                        self._record_raw_payload_snapshot(str(category or "unknown"), entry.body)
                line = self.parser._entry_to_legacy_line(entry)
                self._process_line(line, timestamp=getattr(entry, "timestamp", None))
        else:
            for line in self.parser.read_new_lines():
                self._process_line(line)
        # Defer game summary until after all lines processed (so ConcedeReq can set winner before we print)
        if self.game_state.match_complete and self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False

    def _process_line(self, line: str, timestamp: Optional[datetime] = None):
        """Process a single line from the log file.

        Args:
            line: A line from the MTGA log file.
        """
        prior_event_time = getattr(self, "_current_event_time", None)
        self._current_event_time = timestamp
        try:
            # Always try to pick up match metadata (format, player name) from any line
            self._parse_match_metadata(line)
            for message in self._extract_gre_messages(line):
                self._capture_casting_time_options_requests(message)
            for payload in self._extract_client_gre_payloads(line):
                self._handle_client_gre_payload(payload)

            # Skip processing if we're waiting for the next game (launched mid-game)
            if self.waiting_for_next_game:
                # Only check for new game start, ignore everything else
                self._check_game_start(line)
                return

            # Try to detect player seat if not yet detected
            if self.game_state.player_seat_id is None:
                self._try_detect_player_seat(line)

            # Check for game start. A completed game keeps in_match=True until the next
            # game's first state packet arrives, so completed matches must still listen.
            if not self.game_state.in_match or self.game_state.match_complete:
                self._check_game_start(line)

            # Check for game end (always call when in_match so ConcedeReq can set winner even after MatchCompleted)
            if self.game_state.in_match:
                self._check_game_end(line)
                # Recent MTGA logs include DeclareBlockersReq; use it for snapshots only (not definitive block output).
                self._process_blocker_requests_from_line(line)

            # Look for card-related events in GRE message order.
            for event in self._extract_game_state_events(line):
                self._handle_event(event)
        finally:
            self._current_event_time = prior_event_time

    def _try_detect_player_seat(self, line: str):
        """Set player/opponent by hand visibility only: we can see our cards (grpId known), we cannot see opponent's."""
        for event in self._extract_game_state_events(line):
            if event.get("type") != "game_state":
                continue
            data = event.get("data", {})
            zones = data.get("zones", [])
            game_objects = data.get("gameObjects", [])

            instance_to_grp = {}
            for obj in game_objects:
                iid, gid = obj.get("instanceId"), obj.get("grpId", 0)
                if iid and gid and gid > 0:
                    instance_to_grp[iid] = gid

            hands = []
            for zone in zones:
                if "Hand" not in (zone.get("type") or ""):
                    continue
                owner_seat = zone.get("ownerSeatId")
                obj_ids = zone.get("objectInstanceIds", [])
                if not obj_ids or not owner_seat:
                    continue
                visible = sum(1 for oid in obj_ids if instance_to_grp.get(oid, 0) > 0)
                hands.append({"seat": owner_seat, "visible": visible, "total": len(obj_ids)})

            if len(hands) != 2 or hands[0]["total"] == 0 or hands[1]["total"] == 0:
                continue

            h1, h2 = hands[0], hands[1]
            # Hand we can see (visible > 0) = me. Hand we cannot see (visible == 0) = opponent.
            if h1["visible"] > 0 and h2["visible"] == 0:
                self.game_state.player_seat_id = h1["seat"]
                self.game_state.opponent_seat_id = h2["seat"]
            elif h2["visible"] > 0 and h1["visible"] == 0:
                self.game_state.player_seat_id = h2["seat"]
                self.game_state.opponent_seat_id = h1["seat"]
            elif h1["visible"] != h2["visible"]:
                # One hand we see more of = that seat is us
                if h1["visible"] > h2["visible"]:
                    self.game_state.player_seat_id = h1["seat"]
                    self.game_state.opponent_seat_id = h2["seat"]
                else:
                    self.game_state.player_seat_id = h2["seat"]
                    self.game_state.opponent_seat_id = h1["seat"]
            else:
                continue
            # Resolve player/opponent names from reservedPlayers if we have them (match room may have been parsed earlier)
            if self.game_state._reserved_players:
                for r in self.game_state._reserved_players:
                    if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                        self.game_state.player_display_name = self.game_state.player_display_name or r["name"]
                    elif r.get("seat") == self.game_state.opponent_seat_id and r.get("name"):
                        self.game_state.opponent_display_name = r["name"]
            self._maybe_print_seat_resolution()
            self._sync_commander_views_from_seats()
            self._maybe_print_pregame_commander_lines()
            return

    def _get_name_from_dict(self, d: Dict[str, Any]) -> Optional[str]:
        """Get first non-empty string from dict using common name keys (any casing)."""
        if not d or not isinstance(d, dict):
            return None
        for key in ("screenName", "ScreenName", "displayName", "DisplayName", "accountName", "userName", "name"):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    @staticmethod
    def _is_localized_placeholder_name(name: Optional[str]) -> bool:
        """Return True for MTGA localization placeholder deck names (e.g. '?=?Loc/...')."""
        if not isinstance(name, str):
            return False
        return name.startswith("?=?Loc/")

    @staticmethod
    def _normalize_match_text(value: Optional[str]) -> str:
        """Normalize strings for loose event/format matching."""
        if not isinstance(value, str):
            return ""
        return "".join(ch for ch in value.lower() if ch.isalnum())

    @staticmethod
    def _parse_attr_timestamp(value: Optional[str]) -> Optional[datetime]:
        """Parse MTGA timestamp attribute values, tolerating wrapped quotes."""
        if not isinstance(value, str):
            return None
        raw = value.strip().strip('"')
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.year < 1970:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    @staticmethod
    def _datetime_sort_timestamp(value: Any) -> float:
        """Return a safe sortable timestamp for optional metadata datetimes."""
        if not isinstance(value, datetime):
            return 0.0
        if value.year < 1970:
            return 0.0
        try:
            return value.timestamp()
        except (OverflowError, OSError, ValueError):
            return 0.0

    @staticmethod
    def _course_candidate_key(course: Dict[str, Any]) -> Optional[str]:
        """Return stable candidate key for a course metadata record."""
        if not isinstance(course, dict):
            return None
        summary = course.get("CourseDeckSummary")
        if not isinstance(summary, dict):
            return None
        deck_id = summary.get("DeckId")
        deck_name = summary.get("Name")
        if deck_id:
            return str(deck_id)
        if deck_name:
            return f"{course.get('InternalEventName')}::{deck_name}"
        return None

    @staticmethod
    def _course_from_deck_event_payload(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize EventSetDeck/DeckUpsert V3 payloads into CourseDeck-like metadata."""
        if not isinstance(data, dict):
            return None
        payload: Dict[str, Any] = data
        request = data.get("request")
        if isinstance(request, str) and request.strip():
            try:
                parsed_request = json.loads(request)
            except json.JSONDecodeError:
                parsed_request = None
            if isinstance(parsed_request, dict):
                payload = parsed_request

        summary = payload.get("CourseDeckSummary") or payload.get("Summary")
        if not isinstance(summary, dict):
            return None
        deck = payload.get("CourseDeck") or payload.get("Deck") or {}
        event_name = (
            payload.get("InternalEventName")
            or payload.get("EventName")
            or data.get("InternalEventName")
            or data.get("EventName")
        )
        return {
            "InternalEventName": event_name,
            "CurrentModule": "CreateMatch",
            "CourseDeckSummary": summary,
            "CourseDeck": deck if isinstance(deck, dict) else {},
        }

    def _ingest_course_deck_metadata(self, courses: List[Dict[str, Any]]) -> bool:
        """Capture deck metadata from inventory 'Courses' payloads."""
        if not isinstance(courses, list):
            return False
        now = datetime.now()
        updated = False
        for course in courses:
            if not isinstance(course, dict):
                continue
            summary = course.get("CourseDeckSummary")
            if not isinstance(summary, dict):
                continue
            deck_id = summary.get("DeckId")
            deck_name = summary.get("Name")
            if not deck_id and not deck_name:
                continue

            attrs_raw = summary.get("Attributes")
            attr_map: Dict[str, str] = {}
            if isinstance(attrs_raw, list):
                for attr in attrs_raw:
                    if not isinstance(attr, dict):
                        continue
                    key = attr.get("name")
                    val = attr.get("value")
                    if isinstance(key, str) and isinstance(val, str):
                        attr_map[key] = val

            last_played = self._parse_attr_timestamp(attr_map.get("LastPlayed"))
            key = self._course_candidate_key(course)
            if not key:
                continue
            candidate = self._deck_candidates.get(key, {})

            existing_name = candidate.get("deck_name")
            if isinstance(deck_name, str) and deck_name.strip():
                if (
                    not existing_name
                    or (
                        self._is_localized_placeholder_name(existing_name)
                        and not self._is_localized_placeholder_name(deck_name)
                    )
                ):
                    candidate["deck_name"] = deck_name.strip()
                    updated = True

            if isinstance(deck_id, str) and deck_id:
                if candidate.get("deck_id") != deck_id:
                    candidate["deck_id"] = deck_id
                    updated = True

            internal_event = course.get("InternalEventName")
            if isinstance(internal_event, str) and internal_event:
                if candidate.get("internal_event_name") != internal_event:
                    candidate["internal_event_name"] = internal_event
                    updated = True

            module = course.get("CurrentModule")
            if isinstance(module, str) and module:
                if candidate.get("current_module") != module:
                    candidate["current_module"] = module
                    updated = True

            format_attr = attr_map.get("Format")
            if isinstance(format_attr, str) and format_attr:
                if candidate.get("format_attr") != format_attr:
                    candidate["format_attr"] = format_attr
                    updated = True

            course_deck = course.get("CourseDeck")
            if isinstance(course_deck, dict):
                main_deck = course_deck.get("MainDeck")
                if isinstance(main_deck, list):
                    main_ids = {
                        int(entry.get("cardId"))
                        for entry in main_deck
                        if isinstance(entry, dict) and entry.get("cardId") is not None
                    }
                    if main_ids and candidate.get("main_deck_ids") != main_ids:
                        candidate["main_deck_ids"] = main_ids
                        updated = True
                    main_total = sum(
                        int(entry.get("quantity", 0))
                        for entry in main_deck
                        if isinstance(entry, dict) and entry.get("cardId") is not None
                    )
                    if main_total and candidate.get("main_deck_total") != main_total:
                        candidate["main_deck_total"] = main_total
                        updated = True
                command_zone = course_deck.get("CommandZone")
                if isinstance(command_zone, list):
                    command_zone_ids = [
                        int(entry.get("cardId"))
                        for entry in command_zone
                        if isinstance(entry, dict) and entry.get("cardId") is not None
                    ]
                    if command_zone_ids and candidate.get("command_zone_ids") != command_zone_ids:
                        candidate["command_zone_ids"] = command_zone_ids
                        updated = True
                    command_total = sum(
                        int(entry.get("quantity", 0))
                        for entry in command_zone
                        if isinstance(entry, dict) and entry.get("cardId") is not None
                    )
                    if candidate.get("command_zone_total") != command_total:
                        candidate["command_zone_total"] = command_total
                        updated = True

            if last_played is not None:
                existing_last_played = candidate.get("last_played")
                if not isinstance(existing_last_played, datetime) or last_played > existing_last_played:
                    candidate["last_played"] = last_played
                    updated = True

            candidate["last_seen"] = now
            self._deck_candidates[key] = candidate
        return updated

    def _candidate_score(self, candidate: Dict[str, Any], format_hint: str) -> tuple:
        """Return sortable score tuple for selecting likely active deck."""
        score = 0
        if candidate.get("trusted_active"):
            score += 20
        deck_name = candidate.get("deck_name")
        if isinstance(deck_name, str) and deck_name and not self._is_localized_placeholder_name(deck_name):
            score += 3
        module = str(candidate.get("current_module", "")).lower()
        if module == "creatematch":
            score += 5
        elif "create" in module:
            score += 3
        elif "match" in module:
            score += 2

        event_norm = self._normalize_match_text(candidate.get("internal_event_name"))
        format_norm = self._normalize_match_text(format_hint)
        format_attr_norm = self._normalize_match_text(candidate.get("format_attr"))

        if format_norm and event_norm:
            if format_norm == event_norm:
                score += 8
            elif format_norm in event_norm or event_norm in format_norm:
                score += 5
            else:
                score -= 2
        if format_norm and format_attr_norm:
            if format_norm == format_attr_norm:
                score += 6
            elif format_norm in format_attr_norm or format_attr_norm in format_norm:
                score += 3
            else:
                score -= 4
            if "bestof3" in format_norm and "traditionalstandard" in format_attr_norm:
                score += 2
            if "bestof1" in format_norm and format_attr_norm == "standard":
                score += 2

        if candidate.get("deck_id") and candidate.get("deck_id") == self.game_state.player_deck_id:
            score += 1

        last_played_ts = self._datetime_sort_timestamp(candidate.get("last_played"))
        last_seen_ts = self._datetime_sort_timestamp(candidate.get("last_seen"))
        return (score, last_played_ts, last_seen_ts)

    def _resolve_player_deck_from_candidates(self) -> None:
        """Pick most likely active player deck from observed course metadata."""
        if not self._deck_candidates:
            return
        if self._active_deck_candidate_key:
            locked_candidate = self._deck_candidates.get(self._active_deck_candidate_key)
            if isinstance(locked_candidate, dict):
                self._set_active_deck_from_candidate(locked_candidate)
                return
        format_hint = self.game_state.format_str if self.game_state.format_str != "Unknown" else ""
        if not format_hint:
            return
        ranked = sorted(
            self._deck_candidates.values(),
            key=lambda candidate: self._candidate_score(candidate, format_hint),
            reverse=True,
        )
        best = ranked[0]
        best_score = self._candidate_score(best, format_hint)[0]
        second_score = self._candidate_score(ranked[1], format_hint)[0] if len(ranked) > 1 else -999
        if best_score < 6:
            return
        # Avoid locking in a deck when candidates are similarly plausible.
        if (best_score - second_score) < 3:
            return

        self._set_active_deck_from_candidate(best)

    def _set_active_deck_from_candidate(self, candidate: Dict[str, Any]) -> bool:
        """Apply candidate as active deck and report whether it changed."""
        deck_name = candidate.get("deck_name")
        if self._is_localized_placeholder_name(deck_name):
            deck_name = None
        deck_id = candidate.get("deck_id")
        changed = (
            deck_name != self.game_state.player_deck_name
            or deck_id != self.game_state.player_deck_id
        )
        self.game_state.player_deck_name = deck_name
        self.game_state.player_deck_id = deck_id
        self.game_state.player_deck_event_name = candidate.get("internal_event_name")
        self.game_state.player_deck_last_played = candidate.get("last_played")
        main_total = candidate.get("main_deck_total")
        command_total = candidate.get("command_zone_total")
        self.game_state.player_deck_total_cards = (
            int(main_total) + int(command_total if isinstance(command_total, int) else 0)
            if isinstance(main_total, int)
            else None
        )
        format_attr = candidate.get("format_attr")
        if isinstance(format_attr, str) and format_attr and candidate.get("trusted_active"):
            format_norm = self._normalize_match_text(format_attr)
            implies_best_of_three = (
                "traditional" in format_norm
                or "bestof3" in format_norm
                or format_norm in {"constructedbestof3", "bestof3"}
            )
            if (
                not implies_best_of_three
                and (self.game_state.format_str == "Unknown" or self._format_from_backfill)
            ):
                self.game_state.format_str = format_attr
                self._format_from_backfill = bool(getattr(self, "_parsing_backfilled_metadata", False))
        command_zone_ids = candidate.get("command_zone_ids")
        if isinstance(command_zone_ids, list) and self._candidate_is_brawl(candidate):
            self._set_player_commanders_from_ids(command_zone_ids)
        elif not self.game_state.commanders_by_seat:
            self._clear_commander_state()
        return changed

    def _lock_active_deck_candidate(self, candidate_key: Optional[str]) -> None:
        """Pin the current match to an explicit active deck candidate."""
        if not candidate_key:
            return
        candidate = self._deck_candidates.get(candidate_key)
        if not isinstance(candidate, dict):
            return
        candidate["trusted_active"] = True
        self._deck_candidates[candidate_key] = candidate
        self._active_deck_candidate_key = candidate_key
        self._set_active_deck_from_candidate(candidate)

    def _resolve_player_deck_from_hand_ids(self, hand_grp_ids: List[int]) -> bool:
        """Resolve active deck by matching opening hand grpIds against known candidate main decks."""
        if not hand_grp_ids or not self._deck_candidates:
            return False
        hand_set = {int(grp_id) for grp_id in hand_grp_ids if grp_id}
        if not hand_set:
            return False

        format_hint = self.game_state.format_str if self.game_state.format_str != "Unknown" else ""
        best_candidate: Optional[Dict[str, Any]] = None
        best_key: Optional[tuple] = None
        for candidate in self._deck_candidates.values():
            deck_ids = candidate.get("main_deck_ids")
            if not isinstance(deck_ids, set) or not deck_ids:
                continue
            match_count = len(hand_set & deck_ids)
            if match_count <= 0:
                continue
            confidence = self._candidate_score(candidate, format_hint)
            key = (match_count, confidence[0], confidence[1], confidence[2])
            if best_key is None or key > best_key:
                best_key = key
                best_candidate = candidate

        if not best_candidate or not best_key or best_key[0] < 2:
            return False

        return self._set_active_deck_from_candidate(best_candidate)

    def _resolve_player_deck_fallback(self) -> bool:
        """Pick best-available deck candidate when strict matching could not determine one yet."""
        if not self._deck_candidates:
            return False
        format_hint = self.game_state.format_str if self.game_state.format_str != "Unknown" else ""
        ranked = sorted(
            self._deck_candidates.values(),
            key=lambda candidate: self._candidate_score(candidate, format_hint),
            reverse=True,
        )
        best = ranked[0]
        return self._set_active_deck_from_candidate(best)

    def _backfill_recent_match_metadata(
        self,
        max_lines: int = 1200,
        force: bool = False,
        trust_match_room_format: bool = True,
    ) -> None:
        """Scan recent log tail so metadata is available even when starting at EOF."""
        if self._metadata_backfilled and not force:
            return
        if not force:
            self._metadata_backfilled = True
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        end_markers = (
            "matchcompleted",
            "gamecompleted",
            "concedereq",
            "matchendscene",
            "gamestage_gameover",
            "matchstate_gamecomplete",
            "matchstate_matchcomplete",
            "scene change to home",
        )
        slice_start = 0
        for idx in range(len(tail) - 1, -1, -1):
            lowered = tail[idx].lower()
            if any(marker in lowered for marker in end_markers):
                slice_start = idx + 1
                break
        tail = tail[slice_start:]
        self._parsing_backfilled_metadata = True
        try:
            for raw_line in tail:
                line = raw_line.rstrip("\n")
                if line:
                    self._parse_match_metadata(
                        line,
                        from_backfill=True,
                        trust_match_room_format=trust_match_room_format,
                    )
        finally:
            self._parsing_backfilled_metadata = False

    def _parse_match_metadata(
        self,
        line: str,
        *,
        from_backfill: bool = False,
        trust_match_room_format: bool = True,
    ) -> None:
        """Extract format, players, and deck metadata from log lines."""
        data = self.parser.parse_json_from_line(line)
        if not data:
            return
        line_lower = line.lower()
        format_updated = False
        # Your screen name from authenticateResponse (seen when connecting). Try multiple keys.
        if "authenticateResponse" in data and self.game_state.player_display_name is None:
            auth = data.get("authenticateResponse")
            if isinstance(auth, dict):
                name = self._get_name_from_dict(auth)
                if name:
                    self.game_state.player_display_name = name
        # Format and reserved players from match room event (when a match is set up)
        if "matchGameRoomStateChangedEvent" in data:
            event = data.get("matchGameRoomStateChangedEvent") or {}
            room = event.get("gameRoomInfo") or {}
            config = room.get("gameRoomConfig") or {}
            # Reserved players: may include display/screen name per seat (e.g. "BigFudge55")
            reserved = config.get("reservedPlayers") or config.get("ReservedPlayers")
            reserved_event_ids: List[str] = []
            local_reserved_event_id: Optional[str] = None
            if isinstance(reserved, list) and reserved:
                self.game_state._reserved_players = []
                for p in reserved:
                    if isinstance(p, dict):
                        seat = p.get("systemSeatId") or p.get("systemSeat")
                        name = self._get_name_from_dict(p)
                        event_id = p.get("eventId") or p.get("EventId")
                        if isinstance(event_id, str) and event_id.strip():
                            clean_event_id = event_id.strip()
                            reserved_event_ids.append(clean_event_id)
                            if seat == self.game_state.player_seat_id:
                                local_reserved_event_id = clean_event_id
                        self.game_state._reserved_players.append({"seat": seat, "name": name})
                # If we know our seat, resolve our name and opponent's from reserved list
                if self.game_state.player_seat_id is not None and self.game_state._reserved_players:
                    for r in self.game_state._reserved_players:
                        if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                            self.game_state.player_display_name = self.game_state.player_display_name or r["name"]
                        elif r.get("seat") == self.game_state.opponent_seat_id and r.get("name"):
                            self.game_state.opponent_display_name = r["name"]
            # Format
            fmt = (
                config.get("eventType")
                or config.get("variant")
                or config.get("gameMode")
                or config.get("format")
            )
            if not fmt and isinstance(reserved, list):
                unique_event_ids = {event_id for event_id in reserved_event_ids if event_id}
                if local_reserved_event_id:
                    fmt = local_reserved_event_id
                elif len(unique_event_ids) == 1:
                    fmt = next(iter(unique_event_ids))
            if trust_match_room_format and isinstance(fmt, str) and fmt:
                if self._set_match_format(fmt):
                    format_updated = True
                self._format_from_backfill = from_backfill
            elif trust_match_room_format and isinstance(fmt, (int, float)):
                fmt_value = str(fmt)
                if self._set_match_format(fmt_value):
                    format_updated = True
                self._format_from_backfill = from_backfill

        courses = self._find_nested(data, "Courses")
        deck_updated = self._ingest_course_deck_metadata(courses) if isinstance(courses, list) else False
        trusted_single_course = (
            isinstance(data.get("CourseDeckSummary"), dict)
            and isinstance(data.get("InternalEventName"), str)
        )
        if trusted_single_course:
            single_course = [data]
            if self._ingest_course_deck_metadata(single_course):
                deck_updated = True
            if any(marker in line_lower for marker in ("eventsetdeckv2", "eventsetdeckv3", "deckupsertdeckv2", "deckupsertdeckv3")):
                candidate_key = self._course_candidate_key(data)
                self._lock_active_deck_candidate(candidate_key)
        deck_event_course = self._course_from_deck_event_payload(data)
        if deck_event_course is not None:
            if self._ingest_course_deck_metadata([deck_event_course]):
                deck_updated = True
            if any(marker in line_lower for marker in ("eventsetdeckv2", "eventsetdeckv3", "deckupsertdeckv2", "deckupsertdeckv3")):
                candidate_key = self._course_candidate_key(deck_event_course)
                self._lock_active_deck_candidate(candidate_key)
        if deck_updated or format_updated:
            self._resolve_player_deck_from_candidates()

    def _print_match_started_block(self) -> None:
        """Print match started time, format, and players (like reference UI)."""
        g = self.game_state
        time_str = g.game_start_time.strftime("%I:%M %p") if g.game_start_time else "?"
        self._print_line(f"   Match started: {time_str}")
        format_display = self._friendly_format_label(g.format_str)
        self._print_line(f"   Format: {format_display}")
        opponent_name_known = (
            isinstance(g.opponent_display_name, str)
            and g.opponent_display_name.strip()
            and g.opponent_display_name.strip().lower() != "opponent"
        )
        if opponent_name_known:
            player_label = g.player_display_name or "You"
            self._print_line(f"   Players: {player_label} vs {g.opponent_display_name.strip()}")
        if g.player_seat_id in (1, 2):
            self._print_line(f"   Seat: {g.player_seat_id}")
            g.seat_line_announced = True
        if self._is_brawl_format(g.format_str) and g.player_commanders:
            self._print_line(f"   Your Commander: {self._format_commander_names(g.player_commanders)}")
            g.player_commanders_announced = True
        if self._is_brawl_format(g.format_str) and g.opponent_commanders:
            self._print_line(f"   Opponent Commander: {self._format_commander_names(g.opponent_commanders)}")
            g.opponent_commanders_announced = True

    def _opening_hand_capture_blocked(self) -> bool:
        """Return True when opening-hand capture is already complete or too late."""
        if self.game_state.starting_hand:
            return True
        if self.game_state.opening_hand_capture_closed:
            return True
        if self.game_state.turn_number and self.game_state.turn_number > 1:
            if self._finalize_cached_opening_hand_if_safe():
                return True
            self.game_state.opening_hand_capture_closed = True
            return True
        return False

    def _finalize_starting_hand(
        self,
        hand_cards: List[str],
        hand_grp_ids: List[int],
        hand_events: List[CardEvent],
    ) -> None:
        """Persist and print the finalized opening hand."""
        self.game_state.starting_hand = hand_cards
        self.game_state.starting_hand_events = hand_events
        self.game_state.initial_hand_size = len(hand_cards)
        self.game_state.mulligan_count = max(
            self.game_state.mulligan_count,
            self.game_state.explicit_mulligan_count,
            7 - len(hand_cards),
        )
        self.session_total_mulligans += self.game_state.mulligan_count
        self._resolve_player_deck_from_hand_ids(hand_grp_ids)
        if self.game_state._hand_before_mulligan:
            thrown = [c for c in self.game_state._hand_before_mulligan if c not in hand_cards]
            if thrown:
                self._print_line(f"🔄 Mulliganed away: {', '.join(thrown)}")
        elif len(hand_cards) < 7:
            self._print_line(f"🔄 Mulligan to {len(hand_cards)} (mulligans: {self.game_state.mulligan_count})")
        self.game_state._hand_before_mulligan = []
        self.game_state._hand_before_mulligan_ids = []
        self.game_state._hand_before_mulligan_events = []
        self.game_state.opening_hand_capture_closed = True
        self.game_state.opening_keep_confirmed = False
        self.game_state.opening_select_n_ids = []
        n = len(self.game_state.starting_hand)
        self._print_line(f"\n🎴 Your Starting Hand ({n} cards):")
        for card in self.game_state.starting_hand:
            self._print_line(f"   • {card}")
        self._print_line()

    def _finalize_confirmed_opening_hand_candidate(self) -> None:
        """Finalize the cached opening hand when Arena confirms the player kept it."""
        if self.game_state.starting_hand or self.game_state.opening_hand_capture_closed:
            return
        if not self.game_state.opening_keep_confirmed:
            return
        hand_cards = self.game_state._hand_before_mulligan
        hand_grp_ids = self.game_state._hand_before_mulligan_ids
        hand_events = self.game_state._hand_before_mulligan_events
        if not hand_cards or len(hand_cards) != len(hand_grp_ids):
            return
        if len(hand_cards) > 7:
            return
        if len(hand_events) != len(hand_cards):
            hand_events = [
                CardEvent(card_name, "player")
                for card_name in hand_cards
            ]
        self._finalize_starting_hand(hand_cards, hand_grp_ids, hand_events)

    def _finalize_cached_opening_hand_if_safe(self) -> bool:
        """Finalize a cached seven-card opening hand once gameplay proves it was kept."""
        if self.game_state.starting_hand or self.game_state.opening_hand_capture_closed:
            return False
        hand_cards = self.game_state._hand_before_mulligan
        hand_grp_ids = self.game_state._hand_before_mulligan_ids
        hand_events = self.game_state._hand_before_mulligan_events
        if len(hand_cards) != 7 or len(hand_grp_ids) != 7:
            return False
        if not self.game_state.opening_keep_confirmed and (
            self.game_state.explicit_mulligan_count > 0 or self.game_state.mulligan_count > 0
        ):
            return False
        if len(hand_events) != len(hand_cards):
            hand_events = [CardEvent(card_name, "player") for card_name in hand_cards]
        self._finalize_starting_hand(hand_cards, hand_grp_ids, hand_events)
        return True

    def _visible_opening_hand_snapshots(
        self,
        data: Dict[str, Any],
        objects_by_id: Dict[int, Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], List[int]]:
        """Return fully visible hand snapshots and their owner seats."""
        return visible_opening_hand_snapshots(
            data,
            objects_by_id,
            object_snapshots=self.game_state.object_snapshots,
            card_name_for_grp_id=self.card_db.get_card_name,
            type_category_for_card_types=self._get_card_type_category,
        )

    def _choose_visible_opening_hand(self, visible_hands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Select the player hand from fully visible opening hand snapshots."""
        if not visible_hands:
            return None
        if self.game_state.player_seat_id is not None:
            hand = next(
                (hand for hand in visible_hands if hand["owner_seat"] == self.game_state.player_seat_id),
                None,
            )
            if hand is not None:
                return hand
            if len(visible_hands) == 1:
                # During opening hand capture, the only fully visible hand is ours.
                return visible_hands[0]
            return None
        if len(visible_hands) == 1:
            return visible_hands[0]
        return None

    def _sync_opening_hand_seats(self, owner_seat: int, hand_zone_owners: List[int], data: Dict[str, Any]) -> None:
        """Update player/opponent seats from the visible opening hand owner."""
        if self.game_state.player_seat_id != owner_seat:
            self.game_state.player_seat_id = owner_seat
            opponent_seat: Optional[int] = None
            players = data.get("players", [])
            if isinstance(players, list):
                seat_ids = [
                    p.get("systemSeatNumber")
                    for p in players
                    if isinstance(p, dict) and p.get("systemSeatNumber") is not None
                ]
                for seat_id in seat_ids:
                    if seat_id != owner_seat:
                        opponent_seat = seat_id
                        break
            if opponent_seat is None:
                for seat_id in hand_zone_owners:
                    if seat_id != owner_seat:
                        opponent_seat = seat_id
                        break
            self.game_state.opponent_seat_id = opponent_seat
            self._maybe_print_seat_resolution()
            self._sync_commander_views_from_seats()

    def _handle_opening_hand_snapshot(
        self,
        chosen_hand: Dict[str, Any],
        *,
        turn_num: Optional[int],
        mulligan_prompt_present: bool,
    ) -> None:
        """Apply mulligan/opening-hand inference for one visible hand snapshot."""
        hand_cards = chosen_hand["hand_cards"]
        hand_grp_ids = chosen_hand["hand_grp_ids"]
        hand_events = chosen_hand["hand_events"]

        if len(hand_cards) > 7:
            return

        if len(hand_cards) == 7:
            current_sig = sorted(hand_grp_ids)
            previous_sig = sorted(self.game_state._hand_before_mulligan_ids)
            if not self.game_state._hand_before_mulligan_ids:
                if self.game_state.opening_keep_confirmed or (turn_num and turn_num >= 1 and not mulligan_prompt_present):
                    self._finalize_starting_hand(hand_cards, hand_grp_ids, hand_events)
                    return
                self.game_state._hand_before_mulligan = hand_cards
                self.game_state._hand_before_mulligan_ids = hand_grp_ids
                self.game_state._hand_before_mulligan_events = hand_events
            elif current_sig == previous_sig and turn_num and turn_num >= 1:
                self._finalize_starting_hand(hand_cards, hand_grp_ids, hand_events)
                return
            elif current_sig != previous_sig:
                self.game_state.mulligan_count += 1
                self.game_state._hand_before_mulligan = hand_cards
                self.game_state._hand_before_mulligan_ids = hand_grp_ids
                self.game_state._hand_before_mulligan_events = hand_events
            return

        # Final kept hand (typically < 7 after London bottoming) finalizes mulligan count.
        can_finalize_short_hand = (
            bool(self.game_state._hand_before_mulligan_ids)
            or mulligan_prompt_present
            or (turn_num in (None, 0, 1) and self.game_state.last_turn_announced == 0)
        )
        if can_finalize_short_hand:
            self._finalize_starting_hand(hand_cards, hand_grp_ids, hand_events)

    def _capture_opening_hand(self, data: Dict[str, Any]) -> None:
        """Capture starting hand + mulligan count from early hand-zone snapshots."""
        if self._opening_hand_capture_blocked():
            return

        objects_by_id = game_objects_by_instance(data.get("gameObjects", []))
        if objects_by_id is None:
            return
        if self._has_gameplay_annotations(data):
            if not self._finalize_cached_opening_hand_if_safe():
                self.game_state.opening_hand_capture_closed = True
            return

        visible_hands, hand_zone_owners = self._visible_opening_hand_snapshots(data, objects_by_id)
        chosen_hand = self._choose_visible_opening_hand(visible_hands)
        if chosen_hand is None:
            return

        self._sync_opening_hand_seats(chosen_hand["owner_seat"], hand_zone_owners, data)
        turn_num = (data.get("turnInfo") or {}).get("turnNumber")
        self._handle_opening_hand_snapshot(
            chosen_hand,
            turn_num=turn_num,
            mulligan_prompt_present=self._has_mulligan_prompt_in_state(data),
        )

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

    def _line_indicates_live_mulligan_start(self, line: str) -> bool:
        """Return True when a mulligan marker line represents a live game start, not a game-over payload."""
        line_lower = line.lower()
        if not (
            "mulligantype" in line_lower
            or ("mulligan" in line_lower and ("gretolient" in line_lower or "gretoclient" in line_lower))
            or "mulliganreq" in line_lower
        ):
            return False

        json_data = self.parser.parse_json_from_line(line)
        if isinstance(json_data, dict):
            game_info = self._find_nested(json_data, "gameInfo")
            if isinstance(game_info, dict):
                stage = str(game_info.get("stage", ""))
                match_state = str(game_info.get("matchState", ""))
                if (
                    "GameStage_GameOver" in stage
                    or "MatchState_GameComplete" in match_state
                    or "MatchState_MatchComplete" in match_state
                ):
                    return False
        return True

    def _print_new_game_detected(self) -> None:
        """Print the marker used when a new game starts after a completed game."""
        self._print_line("\n" + "="*75)
        self._print_line("✅ NEW GAME DETECTED - Starting to track!")
        self._print_line("="*75 + "\n")

    def _line_has_state_game_start(self, line: str) -> bool:
        """Return True when state packets show turn 1 or an opening hand."""
        for event in self._extract_game_state_events(line):
            if event.get("type") != "game_state":
                continue
            data = event.get("data", {})
            if "turnInfo" in data:
                turn_info = data.get("turnInfo", {})
                if turn_info.get("turnNumber", 0) == 1:
                    return True
            if state_has_opening_hand_zone(data):
                return True
        return False

    def _release_waiting_for_next_game_if_detected(self, line: str) -> None:
        """Clear waiting mode when a new game's first marker appears."""
        if not self.waiting_for_next_game:
            return
        if self._line_indicates_live_mulligan_start(line):
            self.game_state.opening_mulligan_prompt_seen = True
            self.waiting_for_next_game = False
            self._print_new_game_detected()
        elif self._line_has_state_game_start(line):
            self.waiting_for_next_game = False
            self._print_new_game_detected()

    def _prepare_next_match_game(self) -> None:
        """Reset state when another game starts in the same match."""
        was_best_of_three = self.game_state.match_type == "best_of_3"
        next_game_number = int(self.game_state.game_number or 1) + 1
        completed_game = {
            "game_number": self.game_state.game_number,
            "winner": self.game_state.winner_seat,
            "player_cards": self.player_cards.copy(),
            "opponent_cards": self.opponent_cards.copy(),
            "player_life": self.game_state.player_life,
            "opponent_life": self.game_state.opponent_life,
        }
        if self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False
        if not was_best_of_three:
            return

        self.match_games.append(completed_game)

        self._print_line("\n" + "="*75)
        self._print_line(f"🔄 GAME {next_game_number} STARTING (Best-of-3 Match)")
        self._print_line("="*75 + "\n")
        self.game_state.reset()
        self.game_state.match_type = "best_of_3"
        self.game_state.game_number = next_game_number
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False
        self._active_deck_candidate_key = None

    def _finish_completed_best_of_one_before_new_start(self) -> None:
        """Flush a completed BO1 game before processing the next match start."""
        if self._pending_game_summary:
            self._print_game_summary()
            self._pending_game_summary = False
        else:
            self.game_state.reset()
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False
        self._active_deck_candidate_key = None
        self._require_explicit_game_start = False

    def _reset_new_game_tracking(self, *, opening_mulligan_prompt_seen: bool) -> None:
        """Initialize tracking fields for a newly detected game."""
        if self._format_from_backfill:
            self.game_state.format_str = "Unknown"
            self.game_state.match_type = "best_of_1"
            self._format_from_backfill = False
        self.game_state.game_start_time = self._now()
        self.game_state.in_match = True
        self.game_state.match_complete = False
        self.game_state.starting_hand = []
        self.game_state.starting_hand_events = []
        self.game_state.initial_hand_size = 7
        self.game_state.mulligan_count = 0
        self.game_state._hand_before_mulligan = []
        self.game_state._hand_before_mulligan_ids = []
        self.game_state._hand_before_mulligan_events = []
        self.game_state.opening_hand_capture_closed = False
        self.game_state.opening_mulligan_prompt_seen = opening_mulligan_prompt_seen
        self.game_state.explicit_mulligan_count = 0
        self.game_state.opening_keep_confirmed = False
        self.game_state.opening_select_n_ids = []
        self.player_cards = []
        self.opponent_cards = []
        self._session_stats_recorded_this_game = False
        self._deck_candidates = {}
        self._active_deck_candidate_key = None
        self.game_state.player_deck_name = None
        self.game_state.player_deck_id = None
        self.game_state.player_deck_event_name = None
        self.game_state.player_deck_last_played = None
        self._backfill_recent_match_metadata(max_lines=1800, force=True, trust_match_room_format=False)
        self._require_explicit_game_start = False

    def _hydrate_start_line_state(self, line: str) -> None:
        """Apply state metadata bundled on the same line as a start marker."""
        for state_event in self._extract_game_state_events(line):
            event_data = state_event.get("data", {})
            if isinstance(event_data, dict):
                self._update_format_from_game_state(event_data)
                self._remove_deleted_instances(event_data.get("diffDeletedInstanceIds"))
                self._snapshot_game_objects(event_data.get("gameObjects", []))
                self._update_commanders_from_game_state(event_data)
                self._capture_opening_hand(event_data)

    def _print_game_started_banner(self, *, verbose: bool) -> None:
        """Print the game-start banner."""
        self._print_line("\n" + "="*75)
        if verbose:
            self._print_line("🎮 🎮 🎮 GAME STARTED 🎮 🎮 🎮")
        else:
            format_display = "Standard Best-of-3" if self.game_state.match_type == "best_of_3" else "Standard Best-of-1"
            game_num_display = f" (Game {self.game_state.game_number})" if self.game_state.match_type == "best_of_3" else ""
            self._print_line(f"🎮 GAME STARTED - {format_display}{game_num_display}")
        self._print_line("="*75)
        self._print_match_started_block()

    def _check_game_start(self, line: str):
        """Check if a game is starting."""
        explicit_start_required = self._require_explicit_game_start and not self.waiting_for_next_game

        self._release_waiting_for_next_game_if_detected(line)
        if self.waiting_for_next_game:
            return

        if self.game_state.in_match and self.game_state.match_complete:
            if not (self._line_indicates_live_mulligan_start(line) or self._line_has_state_game_start(line)):
                return
            if self.game_state.match_type == "best_of_3":
                self._prepare_next_match_game()
            else:
                self._finish_completed_best_of_one_before_new_start()

        if self.game_state.in_match:
            return

        if self._line_indicates_live_mulligan_start(line):
            if self.waiting_for_next_game:
                self.waiting_for_next_game = False
                self._print_new_game_detected()
            self._reset_new_game_tracking(opening_mulligan_prompt_seen=True)
            self._hydrate_start_line_state(line)
            self._print_game_started_banner(verbose=True)
            return

        for event in self._extract_game_state_events(line):
            if event.get("type") != "game_state":
                continue
            data = event.get("data", {})

            if "turnInfo" in data:
                turn_info = data["turnInfo"]
                turn_num = turn_info.get("turnNumber", 0)
                if turn_num >= 1:
                    if explicit_start_required and turn_num != 1:
                        return
                    if self.waiting_for_next_game:
                        self.waiting_for_next_game = False
                        self._print_new_game_detected()
                    self._reset_new_game_tracking(opening_mulligan_prompt_seen=False)
                    self._print_game_started_banner(verbose=False)
                    return

            if explicit_start_required:
                break

            if state_has_opening_hand_zone(data) and not self.game_state.in_match:
                if self.waiting_for_next_game:
                    self.waiting_for_next_game = False
                    self._print_new_game_detected()
                self._reset_new_game_tracking(opening_mulligan_prompt_seen=self._has_mulligan_prompt_in_state(data))
                self._capture_opening_hand(data)
                self._print_game_started_banner(verbose=False)
                return

            self._capture_opening_hand(data)

    def _mark_match_complete_now(self) -> bool:
        """Mark the current match complete and queue summary printing."""
        if self.game_state.match_complete:
            return False
        self.game_state.match_complete = True
        self.game_state.game_end_time = self._now()
        self._pending_game_summary = True
        return True

    def _parse_line_winner_hint(self, line: str) -> tuple[Optional[Dict[str, Any]], bool]:
        """Parse a line for structured winner hints and return payload plus game-over flag."""
        json_data = self.parser.parse_json_from_line(line)
        structured_match_complete = False
        if json_data:
            game_info = self._find_nested(json_data, "gameInfo")
            if isinstance(game_info, dict):
                stage = str(game_info.get("stage", ""))
                match_state = str(game_info.get("matchState", ""))
                if (
                    "GameStage_GameOver" in stage
                    and "MatchState_GameComplete" in match_state
                ):
                    structured_match_complete = True
            winner = self._try_parse_winner_from_json(json_data)
            if winner is not None:
                winner_priority = 4 if structured_match_complete else 2
                winner_reason = "structured_game_over_json" if structured_match_complete else "json_winner_hint"
                self._set_winner_seat(winner, reason=winner_reason, priority=winner_priority)
            draw_result = self._extract_latest_draw_result(json_data)
            if draw_result is not None:
                self.game_state.result_type = str(draw_result.get("result") or "ResultType_Draw")
                self.game_state.result_reason = str(draw_result.get("reason") or "ResultReason_Draw")
                structured_match_complete = True
        return json_data, structured_match_complete

    def _handle_concede_end_line(self, line: str, line_lower: str, json_data: Optional[Dict[str, Any]]) -> bool:
        """Handle explicit concede request lines."""
        if "concedereq" not in line_lower and "clientmessagetype_concedereq" not in line_lower:
            return False
        seat_id = self._find_nested(json_data, "systemSeatId") if json_data else None
        if seat_id is not None:
            if seat_id == self.game_state.player_seat_id:
                self._set_winner_seat(
                    self.game_state.opponent_seat_id,
                    reason="concede_req:player_conceded",
                    priority=2,
                )
            elif seat_id == self.game_state.opponent_seat_id:
                self._set_winner_seat(
                    self.game_state.player_seat_id,
                    reason="concede_req:opponent_conceded",
                    priority=2,
                )
        elif "clienttogremessage" in line_lower or "clientmessagetype_concedereq" in line_lower:
            # This log stream is from the local client, so an outgoing concede request is ours.
            self._set_winner_seat(
                self.game_state.opponent_seat_id,
                reason="concede_req:local_player_conceded",
                priority=3,
            )
        return self.game_state.winner_seat is not None and self._mark_match_complete_now()

    @staticmethod
    def _line_indicates_local_player_loss(line_lower: str) -> bool:
        """Return True for text patterns showing the local player left or lost."""
        local_loss = any(pattern in line_lower for pattern in [
            "youleft", "you left", "i left",
            "i concede", "you concede", "conceded the match",
            "quit the match", "defeat", "you were defeated",
            "you disconnected", "i disconnected",
            "forfeit", "you forfeit", "i forfeit", "forfeited",
        ])
        opponent_left = any(pattern in line_lower for pattern in [
            "opponentleft", "opponent left", "opponent quit",
        ])
        return local_loss and not opponent_left

    def _handle_game_completion_pattern(self, line: str, line_lower: str) -> bool:
        """Handle explicit game-completion payload patterns."""
        if not any(pattern in line_lower for pattern in [
            "gamecompletedtype", "finalresults",
            "matchendscene", "on sceneloaded for matchendscene",
        ]):
            return False
        json_data = self.parser.parse_json_from_line(line)
        if not json_data or self.game_state.match_complete:
            return False
        self.game_state.match_complete = True
        self.game_state.game_end_time = self._now()
        winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(json_data, "winningteamid")
        if winner_team is not None and winner_team in (1, 2):
            self._set_winner_seat(winner_team, reason="game_complete_pattern:winner_team", priority=4)
        self._pending_game_summary = True
        return True

    def _handle_playing_to_completed_transition(self, line: str, line_lower: str) -> bool:
        """Handle state transition from Playing to MatchCompleted."""
        if '"old":"playing"' not in line_lower or '"new":"matchcompleted"' not in line_lower:
            return False
        if self.game_state.match_complete:
            return False
        self.game_state.match_complete = True
        self.game_state.game_end_time = self._now()
        json_data = self.parser.parse_json_from_line(line)
        if json_data:
            winner_team = self._find_nested(json_data, "winningTeamId") or self._find_nested(json_data, "winningteamid")
            if winner_team is not None and winner_team in (1, 2):
                self._set_winner_seat(winner_team, reason="state_transition:winner_team", priority=4)
        self._pending_game_summary = True
        return True

    def _check_game_end(self, line: str):
        """Check if the game has ended."""
        if not self.game_state.in_match:
            return
        line_lower = line.lower()
        json_data, structured_match_complete = self._parse_line_winner_hint(line)

        if self._handle_concede_end_line(line, line_lower, json_data):
            return

        # Structured end-of-game records from current MTGA logs.
        if structured_match_complete and self._mark_match_complete_now():
            return

        if self._line_indicates_local_player_loss(line_lower):
            self._set_winner_seat(
                self.game_state.opponent_seat_id,
                reason="text:player_left_or_forfeited",
                priority=1,
            )
            self._mark_match_complete_now()
            return

        # Check for match completion state changes - be very specific
        # Only set match_complete here; do NOT set winner_seat (we don't know who won from this line).
        if '"old":"matchcompleted"' in line_lower or '"old":"MatchCompleted"' in line:
            if '"new":"matchcompleted"' in line_lower or '"new":"MatchCompleted"' in line or '"new":"disconnected"' in line_lower:
                if self._mark_match_complete_now():
                    return

        if self._handle_game_completion_pattern(line, line_lower):
            return

        if self._handle_playing_to_completed_transition(line, line_lower):
            return

    def _handle_event(self, event: Dict[str, Any]):
        """Handle a card event.

        Args:
            event: Event data extracted from the log.
        """
        event_type = event.get("type")
        event_data = event.get("data", {})

        if event_type != "game_state":
            return

        # Process turn and print header FIRST so "Turn 1 - YOUR TURN" appears before
        # card plays and life changes from this message.
        self._update_game_state(event_data)
        self._capture_opening_hand(event_data)

        # Then process annotations (card plays, etc.) so they appear under the turn header.
        self._process_game_events(event_data)

    def _has_combat_or_damage_annotations(self, data: Dict[str, Any]) -> bool:
        """Return True when this payload includes combat/damage annotations."""
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

    def _previous_attack_context(self) -> tuple[Set[int], Dict[int, Set[int]]]:
        """Return combat context needed to attribute late-arriving life updates."""
        previous_attack_target_ids = {
            info.get("target_id")
            for info in self.game_state.current_combat_attackers.values()
            if isinstance(info, dict) and info.get("target_id") in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
        }
        previous_attack_sources_by_target: Dict[int, Set[int]] = {}
        for info in self.game_state.current_combat_attackers.values():
            if not isinstance(info, dict):
                continue
            target_id = info.get("target_id")
            owner_seat = info.get("owner_seat")
            if (
                target_id in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
                and owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
            ):
                previous_attack_sources_by_target.setdefault(int(target_id), set()).add(int(owner_seat))
        return previous_attack_target_ids, previous_attack_sources_by_target

    def _clear_combat_tracking(self) -> None:
        """Clear per-combat state while preserving aggregate match stats."""
        self.game_state.attackers = []
        self.game_state.blockers = {}
        self.game_state.current_combat_attackers = {}
        self.game_state.current_combat_blockers = {}
        self.game_state.combat_damage_events = []
        self.game_state.reported_block_pairs = set()
        self.game_state.recent_combat_returns = []

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

    def _update_combat_phase(self, phase: str) -> bool:
        """Update combat-phase state and return True if combat exited."""
        if phase and "Combat" in phase:
            if not self.game_state.combat_phase_active:
                self.game_state.combat_phase_active = True
                self._clear_combat_tracking()
            return False
        if not self.game_state.combat_phase_active:
            return False
        self._display_combat_summary()
        self.game_state.combat_phase_active = False
        self._clear_combat_tracking()
        return True

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

    def _handle_attack_state_objects(self, game_objects: List[Dict[str, Any]]) -> None:
        """Handle combat attacks emitted as gameObjects with attackState."""
        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for obj in game_objects:
            instance_id = obj.get("instanceId")
            if instance_id is not None:
                game_objects_by_id[instance_id] = obj

        for obj in game_objects:
            attack_state = str(obj.get("attackState", ""))
            if attack_state not in ("AttackState_Declared", "AttackState_Attacking"):
                continue

            instance_id = obj.get("instanceId")
            if instance_id is None or instance_id in self.game_state.attackers:
                continue
            self.game_state.attackers.append(instance_id)

            grp_id = obj.get("grpId")
            owner_seat = obj.get("ownerSeatId")
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            power = obj.get("power", {}).get("value", "?")
            toughness = obj.get("toughness", {}).get("value", "?")
            target_id = (obj.get("attackInfo") or {}).get("targetId")
            target_label = self._resolve_target_label(target_id, game_objects_by_id)

            self.game_state.current_combat_attackers[instance_id] = {
                "card_name": card_name,
                "power": power,
                "toughness": toughness,
                "owner_seat": owner_seat,
                "target": target_label,
                "target_id": target_id,
            }

            self._flush_pending_turn_header_for_seat(owner_seat)
            player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
            turn_for_display = (
                self.game_state.turn_number
                if owner_seat == self.game_state.active_player and self.game_state.turn_number > 0
                else self._turn_for_seat(owner_seat)
            )
            turn_for_display = self._event_turn_number(owner_seat, turn_for_display)
            stats = self._seat_stats(owner_seat)
            if stats is not None:
                stats["attacking_creatures"] += 1
                attack_turn_key = (int(turn_for_display or 0), int(owner_seat))
                if turn_for_display and attack_turn_key not in self.game_state.counted_attack_turns:
                    self.game_state.counted_attack_turns.add(attack_turn_key)
                    stats["attacks"] += 1
            if not self._should_announce_attack(turn_for_display, instance_id, owner_seat):
                continue
            self._ensure_turn_header_for_event(owner_seat, turn_for_display)
            turn_prefix = self._turn_prefix_for_number(turn_for_display)

            if target_label:
                self._print_event(
                    f"{turn_prefix}{player} attacking [{target_label}] with [{card_name} ({power}/{toughness})]",
                    "attack",
                )
            else:
                self._print_event(
                    f"{turn_prefix}{player} attacking with [{card_name} ({power}/{toughness})]",
                    "attack",
                )

    def _process_blocker_requests_from_line(self, line: str) -> None:
        """Handle GREMessageType_DeclareBlockersReq events from raw line JSON.

        Note: this message is a *request* to choose blockers, not authoritative proof that
        a block actually happened. We only use it to capture object snapshots for fallback
        card lookups and do not emit block lines from it.
        """
        if "declareblockersreq" not in line.lower():
            return

        data = self.parser.parse_json_from_line(line)
        if not data or not isinstance(data, dict):
            return
        gre_event = data.get("greToClientEvent")
        if not isinstance(gre_event, dict):
            return

        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for message in (gre_event.get("greToClientMessages") or []):
            if not isinstance(message, dict):
                continue
            msg_type = message.get("type")
            if msg_type == "GREMessageType_GameStateMessage":
                game_state = message.get("gameStateMessage") or {}
                game_objects = game_state.get("gameObjects") or []
                self._snapshot_game_objects(game_objects)
                for obj in game_objects:
                    if not isinstance(obj, dict):
                        continue
                    instance_id = obj.get("instanceId")
                    if instance_id is not None:
                        game_objects_by_id[instance_id] = obj

    def _handle_blockers_request(self, blockers: List[Dict[str, Any]], game_objects_by_id: Dict[int, Dict[str, Any]]) -> None:
        """Display blocker mappings from DeclareBlockersReq payloads."""
        for block in blockers:
            if not isinstance(block, dict):
                continue
            blocker_id = block.get("blockerInstanceId")
            if blocker_id is None:
                continue
            attacker_ids = block.get("attackerInstanceIds") or []
            if not isinstance(attacker_ids, list) or not attacker_ids:
                continue

            blocker_obj = self._lookup_object(blocker_id, game_objects_by_id)
            blocker_name = self._object_display_name(blocker_obj, blocker_id)
            blocker_owner_seat = blocker_obj.get("ownerSeatId")
            blocker_pt = self._object_pt(blocker_obj)

            self._flush_pending_turn_header_for_seat(blocker_owner_seat)
            if blocker_owner_seat == self.game_state.player_seat_id:
                player = "You"
            elif blocker_owner_seat == self.game_state.opponent_seat_id:
                player = "Opponent"
            else:
                player = "Unknown"
            inferred_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else self._turn_for_seat(blocker_owner_seat)
            for attacker_id in attacker_ids:
                if attacker_id is None:
                    continue
                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_owner_seat = attacker_obj.get("ownerSeatId")
                if attacker_owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                    inferred_turn = self._turn_for_seat(attacker_owner_seat) or inferred_turn
                    break
            self._ensure_turn_header_for_event(blocker_owner_seat, inferred_turn)
            turn_prefix = self._turn_prefix_for_number(inferred_turn)

            blocker_targets = self.game_state.blockers.setdefault(blocker_id, [])
            for attacker_id in attacker_ids:
                dedupe_key = (self.game_state.turn_number, blocker_id, attacker_id)
                if dedupe_key in self.game_state.reported_block_pairs:
                    continue
                self.game_state.reported_block_pairs.add(dedupe_key)

                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_name = self._object_display_name(attacker_obj, attacker_id)
                if attacker_name.startswith("ID "):
                    attacker_name = (self.game_state.current_combat_attackers.get(attacker_id) or {}).get("card_name")
                if not attacker_name:
                    attacker_name = f"ID {attacker_id}"

                turn_prefix = self._turn_prefix_for_number(inferred_turn)
                self._print_event(
                    f"\t{turn_prefix}{player} blocking [{attacker_name}] with [{blocker_name} ({blocker_pt})]",
                    "block",
                )

                if attacker_id not in blocker_targets:
                    blocker_targets.append(attacker_id)

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

    def _format_type_breakdown(self, events: List["CardEvent"]) -> str:
        """Return a 'By type: N Lands, M Creatures, ...' string for a list of card events (non-zero only)."""
        order = ["Land", "Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker", "Other"]
        plurals = {"Land": "Lands", "Creature": "Creatures", "Instant": "Instants", "Sorcery": "Sorceries",
                   "Enchantment": "Enchantments", "Artifact": "Artifacts", "Planeswalker": "Planeswalkers", "Other": "Other"}
        counts: Dict[str, int] = {cat: 0 for cat in order}
        for e in events:
            cat = getattr(e, "card_type_category", None) or "Other"
            counts[cat] = counts.get(cat, 0) + 1
        parts = [f"{counts[cat]} {plurals[cat]}" for cat in order if counts[cat] > 0]
        return "By type: " + ", ".join(parts) if parts else "By type: —"

    def _handle_attacker_declared(self, affected_ids: List[int], game_objects: List[Dict[str, Any]]):
        """Handle attacker declarations."""
        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for obj in game_objects:
            instance_id = obj.get("instanceId")
            if instance_id is not None:
                game_objects_by_id[instance_id] = obj

        for instance_id in affected_ids:
            if instance_id not in self.game_state.attackers:
                self.game_state.attackers.append(instance_id)

                # Find the attacker
                for obj in game_objects:
                    if obj.get("instanceId") == instance_id:
                        grp_id = obj.get("grpId")
                        owner_seat = obj.get("ownerSeatId")
                        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                        power = obj.get("power", {}).get("value", "?")
                        toughness = obj.get("toughness", {}).get("value", "?")
                        target_id = (obj.get("attackInfo") or {}).get("targetId")
                        target_label = self._resolve_target_label(target_id, game_objects_by_id)

                        # Store combat info for summary
                        self.game_state.current_combat_attackers[instance_id] = {
                            "card_name": card_name,
                            "power": power,
                            "toughness": toughness,
                            "owner_seat": owner_seat,
                            "target": target_label,
                            "target_id": target_id,
                        }

                        self._flush_pending_turn_header_for_seat(owner_seat)
                        player = "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                        turn_for_display = (
                            self.game_state.turn_number
                            if owner_seat == self.game_state.active_player and self.game_state.turn_number > 0
                            else self._turn_for_seat(owner_seat)
                        )
                        stats = self._seat_stats(owner_seat)
                        if stats is not None:
                            stats["attacking_creatures"] += 1
                            attack_turn_key = (int(turn_for_display or 0), int(owner_seat))
                            if turn_for_display and attack_turn_key not in self.game_state.counted_attack_turns:
                                self.game_state.counted_attack_turns.add(attack_turn_key)
                                stats["attacks"] += 1
                        if not self._should_announce_attack(turn_for_display, instance_id, owner_seat):
                            break
                        self._ensure_turn_header_for_event(owner_seat, turn_for_display)
                        turn_prefix = self._turn_prefix_for_number(turn_for_display)

                        if target_label:
                            self._print_event(
                                f"{turn_prefix}{player} attacking [{target_label}] with [{card_name} ({power}/{toughness})]",
                                "attack",
                            )
                        else:
                            self._print_event(
                                f"{turn_prefix}{player} attacking with [{card_name} ({power}/{toughness})]",
                                "attack",
                            )
                        break

    def _handle_blocker_declared(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle blocker declarations."""
        if not affected_ids:
            return

        blocker_id = affected_ids[0]

        # Try to find which attackers are being blocked
        attacker_ids: List[int] = []
        details = annotation.get("details", [])
        for detail in details:
            key = detail.get("key")
            if key in ("attacker_id", "target"):
                attacker_id = detail.get("valueInt32", [None])[0]
                if attacker_id is not None:
                    attacker_ids.append(attacker_id)
            elif key in ("attacker_ids", "targets"):
                ids = detail.get("valueInt32", [])
                if isinstance(ids, list):
                    attacker_ids.extend([i for i in ids if i is not None])
        if not attacker_ids:
            attacker_ids = [None]

        game_objects_by_id: Dict[int, Dict[str, Any]] = {}
        for obj in game_objects:
            instance_id = obj.get("instanceId")
            if instance_id is not None:
                game_objects_by_id[instance_id] = obj

        blocker_obj = self._lookup_object(blocker_id, game_objects_by_id)
        blocker_name = self._object_display_name(blocker_obj, blocker_id)
        blocker_owner_seat = blocker_obj.get("ownerSeatId")
        blocker_pt = self._object_pt(blocker_obj)
        if blocker_owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            if blocker_id not in self.game_state.current_combat_blockers:
                self.game_state.current_combat_blockers[blocker_id] = {
                    "owner_seat": blocker_owner_seat,
                    "name": blocker_name,
                }
                stats = self._seat_stats(blocker_owner_seat)
                if stats is not None:
                    stats["blocking_creatures"] += 1
        attackers_by_id: Dict[int, str] = {}
        for attacker_id in attacker_ids:
            if attacker_id is None:
                continue
            attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
            attackers_by_id[attacker_id] = self._object_display_name(attacker_obj, attacker_id)

        if blocker_owner_seat is not None:
            self._flush_pending_turn_header_for_seat(blocker_owner_seat)
            if blocker_owner_seat == self.game_state.player_seat_id:
                player = "You"
            elif blocker_owner_seat == self.game_state.opponent_seat_id:
                player = "Opponent"
            else:
                player = "Unknown"
            inferred_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else self._turn_for_seat(blocker_owner_seat)
            for attacker_id in attacker_ids:
                if attacker_id is None:
                    continue
                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_owner_seat = attacker_obj.get("ownerSeatId")
                if attacker_owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                    inferred_turn = self._turn_for_seat(attacker_owner_seat) or inferred_turn
                    break
            self._ensure_turn_header_for_event(blocker_owner_seat, inferred_turn)
            turn_prefix = self._turn_prefix_for_number(inferred_turn)

            blocker_targets = self.game_state.blockers.setdefault(blocker_id, [])
            for attacker_id in attacker_ids:
                dedupe_key = (self.game_state.turn_number, blocker_id, attacker_id)
                if dedupe_key in self.game_state.reported_block_pairs:
                    continue
                self.game_state.reported_block_pairs.add(dedupe_key)

                attacker_name = attackers_by_id.get(attacker_id) if attacker_id is not None else None
                if attacker_name:
                    self._print_event(
                        f"\t{turn_prefix}{player} blocking [{attacker_name}] with [{blocker_name} ({blocker_pt})]",
                        "block",
                    )
                else:
                    self._print_event(
                        f"\t{turn_prefix}{player} blocking with [{blocker_name} ({blocker_pt})]",
                        "block",
                    )

                if attacker_id is not None and attacker_id not in blocker_targets:
                    blocker_targets.append(attacker_id)

    def _handle_damage(self, affected_ids: List[int], annotation: Dict[str, Any], game_objects: List[Dict[str, Any]]):
        """Handle damage events."""
        # Extract damage amount
        details = annotation.get("details", [])
        damage_amount = None
        source_id = None
        is_combat_damage = False
        game_objects_by_id = {
            obj.get("instanceId"): obj
            for obj in game_objects
            if isinstance(obj, dict) and obj.get("instanceId") is not None
        }
        
        for detail in details:
            if detail.get("key") == "damage" or detail.get("key") == "amount":
                damage_amount = detail.get("valueInt32", [None])[0]
            elif detail.get("key") == "source" or detail.get("key") == "source_id":
                source_id = detail.get("valueInt32", [None])[0]
            elif detail.get("key") == "combat" or detail.get("key") == "is_combat":
                is_combat_damage = detail.get("valueBool", [False])[0] or detail.get("valueInt32", [0])[0] == 1

        if source_id is None:
            source_id = annotation.get("affectorId")
        source_obj = self._lookup_object(source_id, game_objects_by_id) if source_id is not None else {}
        canonical_source_id = self._canonical_instance_id(source_id) if source_id is not None else None
        source_card_types = source_obj.get("cardTypes") or []

        # Spells can deal damage during combat, but that is not combat damage.
        if self.game_state.combat_phase_active and not is_combat_damage:
            if source_id is None:
                is_combat_damage = True
            elif canonical_source_id in self.game_state.current_combat_attackers or source_id in self.game_state.current_combat_attackers:
                is_combat_damage = True
            elif canonical_source_id in self.game_state.current_combat_blockers or source_id in self.game_state.current_combat_blockers:
                is_combat_damage = True
            elif "CardType_Creature" in source_card_types and bool(source_obj.get("attackInfo")):
                is_combat_damage = True

        # If a spell's effect arrives before its Resolve annotation, emit the cast line first.
        self._flush_pending_spell_cast(source_id, game_objects_by_id)

        if damage_amount and affected_ids:
            for instance_id in affected_ids:
                source_seat = None
                if source_id is not None:
                    source_seat = source_obj.get("controllerSeatId")
                    if source_seat is None:
                        source_seat = source_obj.get("ownerSeatId")
                if instance_id in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                    self._record_damage_dealt(int(damage_amount), source_seat, instance_id)
                    continue
                for obj in game_objects:
                    if obj.get("instanceId") == instance_id:
                        grp_id = obj.get("grpId")
                        owner_seat = obj.get("ownerSeatId")
                        self._flush_pending_turn_header_for_seat(owner_seat)
                        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"

                        owner = "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                        
                        # Find source if available
                        source_name = None
                        if source_id:
                            for source_obj in game_objects:
                                if source_obj.get("instanceId") == source_id:
                                    source_grp_id = source_obj.get("grpId")
                                    source_name = self.card_db.get_card_name(source_grp_id) if source_grp_id else None
                                    source_seat = source_obj.get("controllerSeatId")
                                    if source_seat is None:
                                        source_seat = source_obj.get("ownerSeatId")
                                    break
                        self._record_damage_dealt(
                            int(damage_amount),
                            source_seat,
                            owner_seat if owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id) else None,
                            queue_life_reconciliation=False,
                        )

                        if is_combat_damage:
                            # Store for combat summary
                            self.game_state.combat_damage_events.append({
                                "source": source_name,
                                "target": card_name,
                                "target_owner": owner,
                                "amount": damage_amount
                            })
                            
                            event_seat = source_seat if source_seat in (
                                self.game_state.player_seat_id,
                                self.game_state.opponent_seat_id,
                            ) else owner_seat
                            turn_prefix = self._turn_prefix_for_number(self._event_turn_number(event_seat))
                            if source_name:
                                self._print_event(
                                    f"\t{turn_prefix}Combat: [{source_name}] dealt {damage_amount} damage to [{card_name}] ({owner})",
                                    "combat_damage",
                                )
                            else:
                                self._print_event(
                                    f"\t{turn_prefix}Combat: [{card_name}] ({owner}) took {damage_amount} damage",
                                    "combat_damage",
                                )
                        else:
                            event_seat = source_seat if source_seat in (
                                self.game_state.player_seat_id,
                                self.game_state.opponent_seat_id,
                            ) else owner_seat
                            turn_prefix = self._turn_prefix_for_number(self._event_turn_number(event_seat))
                            self._print_event(
                                f"{turn_prefix}[{card_name}] ({owner}) took {damage_amount} damage",
                                "damage",
                            )
                        break

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

    def _turns_completed(self) -> int:
        """Return best-effort total turn count for the finished game."""
        return max(
            int(self.game_state.turn_number or 0),
            int(self.game_state.last_turn_announced or 0),
            int(self.game_state.last_player_turn_number or 0),
            int(self.game_state.last_opponent_turn_number or 0),
        )

    def _print_match_stats_section(self) -> None:
        """Print per-player match stats block."""
        self._print_line()
        self._print_summary_heading("Match Stats", "turn")
        self._print_line(f"   Total Turns: {self._turns_completed()}")
        for seat_id, label in (
            (self.game_state.player_seat_id, "You"),
            (self.game_state.opponent_seat_id, "Opponent"),
        ):
            if seat_id not in (1, 2):
                continue
            stats = self.game_state.match_stats[int(seat_id)]
            cards_played = len(self.player_cards) if seat_id == self.game_state.player_seat_id else len(self.opponent_cards)
            self._print_line(f"\n   {label}:")
            self._print_line(
                f"      Combat: {stats['attacks']} attack step(s), {stats['attacking_creatures']} attacking creature(s), "
                f"{stats['attackers_lost']} attacker(s) lost"
            )
            self._print_line(
                f"      Defense: {stats['blocking_creatures']} blocker(s), {stats['blockers_lost']} blocker(s) lost"
            )
            self._print_line(
                f"      Damage/Life: {stats['total_damage']} damage dealt, {stats['life_lost']} life lost, "
                f"{stats['self_damage']} self-damage, {stats['life_gain']} life gained"
            )
            self._print_line(
                f"      Cards: {cards_played} played, {stats['cards_drawn']} drawn, "
                f"{stats['cards_discarded']} discarded, {stats['cards_milled']} milled, {stats['cards_exiled']} exiled"
            )
            stack_stats = self.game_state.stack_stats[int(seat_id)]
            self._print_line(
                f"      Stack: {stack_stats['put_on_stack']} put on stack, {stack_stats['resolved']} resolved, "
                f"{stack_stats['countered']} countered, {stack_stats['fizzled']} left unresolved"
            )

    def _starting_hand_heading(self) -> str:
        """Return the end-summary heading for the kept opening hand."""
        if not self.game_state.starting_hand:
            return "Starting Hand (Not Captured)"
        card_count = len(self.game_state.starting_hand)
        card_word = "Card" if card_count == 1 else "Cards"
        heading = f"Starting Hand ({card_count} {card_word}"
        if self.game_state.mulligan_count > 0:
            heading += f" - After {self.game_state.mulligan_count} mulligan(s)"
        heading += ")"
        return heading

    def _display_combat_summary(self):
        """Display a summary of combat after it ends."""
        if not self.game_state.current_combat_attackers and not self.game_state.combat_damage_events:
            return
        
        # Show combat summary if we have significant combat activity
        if self.game_state.combat_damage_events:
            self._print_line("\n" + self._style("⚔️ Combat Summary:", "attack"))
            for event in self.game_state.combat_damage_events:
                if event.get("source"):
                    self._print_event(f"   {event['source']} → {event['target']} ({event['target_owner']}): {event['amount']} damage", "combat_damage")
            self._print_line()

    def _resolve_game_outcome(self) -> tuple:
        """Resolve game outcome as ('win'|'loss'|'draw'|'unknown', reason)."""
        if str(getattr(self.game_state, "result_type", "")) == "ResultType_Draw":
            return "draw", self._draw_reason_text(getattr(self.game_state, "result_reason", None))

        pl, ol = self.game_state.player_life, self.game_state.opponent_life
        if pl <= 0:
            return "loss", "You reached 0 life"
        if ol <= 0:
            return "win", "Opponent reached 0 life"

        if self.game_state.winner_seat is not None and self.game_state.player_seat_id in (1, 2):
            if self.game_state.winner_seat == self.game_state.player_seat_id:
                return "win", "Opponent conceded/disconnected"
            if self.game_state.winner_seat == self.game_state.opponent_seat_id:
                return "loss", "You conceded/left the game"
            return "unknown", f"Winning seat: {self.game_state.winner_seat}"

        if self.game_state.winner_seat is not None:
            return "unknown", f"Winning seat: {self.game_state.winner_seat}"

        return "unknown", f"Life totals: You {pl} - {ol} Opponent"

    @staticmethod
    def _draw_reason_text(result_reason: Optional[str]) -> str:
        """Return a user-facing reason for a structured draw result."""
        if result_reason == "ResultReason_Force":
            return "Match ended in a forced draw"
        if result_reason:
            return str(result_reason).replace("ResultReason_", "").replace("_", " ")
        return "Match ended in a draw"

    def _record_session_outcome(self, outcome: str) -> None:
        """Record one game result in session totals exactly once."""
        if self._session_stats_recorded_this_game:
            return

        self.session_games_played += 1
        self.session_game_runtime_seconds += self._current_game_duration_seconds()
        if outcome == "win":
            self.session_wins += 1
        elif outcome == "loss":
            self.session_losses += 1
        elif outcome == "draw":
            self.session_draws = getattr(self, "session_draws", 0) + 1
        else:
            self.session_unknown += 1
        self._session_stats_recorded_this_game = True

    def _try_resolve_winner_from_log_tail(self) -> None:
        """Last-chance winner lookup from recent structured log payloads."""
        if self.game_state.winner_seat is not None:
            return
        try:
            with open(self.parser.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            tail = lines[-100:] if len(lines) > 100 else lines
            for line in reversed(tail):
                data = self.parser.parse_json_from_line(line)
                if not data:
                    continue
                winner = self._try_parse_winner_from_json(data)
                if winner is not None:
                    self._set_winner_seat(winner, reason="summary_tail:json_winner_hint", priority=2)
                    return
        except Exception:
            return

    def _game_duration_display(self) -> str:
        """Return the current game duration label."""
        if not (self.game_state.game_start_time and self.game_state.game_end_time):
            return "Unknown"
        duration = self.game_state.game_end_time - self.game_state.game_start_time
        minutes = int(duration.total_seconds() // 60)
        seconds = int(duration.total_seconds() % 60)
        return f"{minutes}m {seconds}s"

    @staticmethod
    def _summary_result_line(outcome: str) -> tuple[str, str]:
        """Return result header text and style for a resolved outcome."""
        if outcome == "win":
            return "GAME ENDED - YOU WON", "land"
        if outcome == "loss":
            return "GAME ENDED - YOU LOST", "damage"
        if outcome == "draw":
            return "GAME ENDED - DRAW", "turn"
        return "GAME ENDED - RESULT UNKNOWN", "turn"

    def _print_result_summary(self, outcome: str, reason: str, duration_display: str) -> None:
        """Print the consolidated game-end result block."""
        result_line, result_style = self._summary_result_line(outcome)
        self._print_line("\n" + "="*75)
        self._print_line(result_line, result_style)
        self._print_line(f"Reason: {reason}")
        if outcome == "unknown" and self.game_state.winner_seat is None:
            self._print_line("Result Note: Result unclear — possible concede or disconnect")
        self._print_line(f"Duration: {duration_display}")
        self._print_line(f"Session Stats: {self._session_stats_line()}")
        self._print_line("="*75)

    def _print_best_of_three_status(self) -> None:
        """Print best-of-three game status when applicable."""
        if self.game_state.match_type != "best_of_3":
            return
        self._print_line()
        self._print_summary_heading("Best-of-3 Match Status", "turn")
        self._print_line(f"   Game {self.game_state.game_number} of 3")
        if self.match_games:
            self._print_line("   Previous games:")
            for game in self.match_games:
                game_winner = "You" if game["winner"] == self.game_state.player_seat_id else "Opponent"
                self._print_line(f"      Game {game['game_number']}: {game_winner} won")

    def _print_starting_hand_summary(self) -> None:
        """Print captured starting hand details."""
        self._print_line()
        self._print_summary_heading(self._starting_hand_heading(), "ability")
        if self.game_state.starting_hand:
            for card in self.game_state.starting_hand:
                self._print_line(f"   • [{self._refresh_fallback_name_text(card)}]")
        else:
            self._print_line("   Not captured. Start the tracker before the mulligan/keep screen to record this.")

    def _print_cards_played_summary(self) -> None:
        """Print deck metadata and played-card counts."""
        self._print_line()
        self._print_summary_heading("Cards Played", "cast")
        if not self.game_state.player_deck_name:
            self._resolve_player_deck_from_candidates()
        self._print_line(
            f"   Your Deck: {self.game_state.player_deck_name or 'Unknown (not found in Arena metadata)'}"
        )
        if self.game_state.player_deck_total_cards:
            self._print_line(f"   Your deck total: {self.game_state.player_deck_total_cards}")
        elif self.game_state.player_seat_id in self.game_state.observed_starting_deck_total_by_seat:
            self._print_line(
                f"   Your deck total (estimated): "
                f"{self.game_state.observed_starting_deck_total_by_seat[self.game_state.player_seat_id]}"
            )
        if self._is_brawl_format() and self.game_state.player_commanders:
            self._print_line(f"   Your Commander: {self._format_commander_names(self.game_state.player_commanders)}")
        if self._is_brawl_format() and self.game_state.opponent_commanders:
            self._print_line(f"   Opponent Commander: {self._format_commander_names(self.game_state.opponent_commanders)}")
        self._print_line(f"   Mulligans: {self.game_state.mulligan_count}")
        self._print_line(f"   Your cards: {len(self.player_cards)}")
        self._print_line(f"   Opponent cards: {len(self.opponent_cards)}")
        if self.game_state.opponent_seat_id in self.game_state.observed_starting_deck_total_by_seat:
            self._print_line(
                f"   Opponent deck total (estimated): "
                f"{self.game_state.observed_starting_deck_total_by_seat[self.game_state.opponent_seat_id]}"
            )
        if is_deck_llm_enabled() and self.opponent_cards:
            self._print_opponent_deck_guess()

    def _print_opponent_deck_guess(self) -> None:
        """Print opponent archetype guess when deck LLM support is enabled."""
        card_names = [event.card_name for event in self.opponent_cards]
        archetype = identify_deck(card_names)
        if archetype:
            self._print_line(f"   Opponent deck: {archetype}")
            return
        diagnostics = deck_llm_diagnose()
        if not diagnostics.get("has_api_key"):
            key_name = {
                "gemini": "GEMINI_API_KEY",
                "openai": "CHATGPT_API_KEY",
                "claude": "CLAUDE_API_KEY",
            }.get(diagnostics.get("provider") or "gemini", "GEMINI_API_KEY")
            self._print_line(f"   Opponent deck: (LLM: no API key — set {key_name} in config.py or env)")
        else:
            self._print_line("   Opponent deck: (LLM: request failed — check key/network)")

    def _print_exile_and_match_stats_summary(self) -> None:
        """Print exile counters and aggregate match stats."""
        self._print_line()
        self._print_summary_heading("Cards Exiled", "zone")
        self._print_line(f"   By Me: {self.game_state.opponent_cards_exiled_by_player}")
        self._print_line(f"   By Opponent: {self.game_state.player_cards_exiled_by_opponent}")
        self._print_match_stats_section()

    def _print_card_collection_summary(
        self,
        cards: List[CardEvent],
        *,
        heading: str,
        seat_id: Optional[int],
    ) -> None:
        """Print card list and highest observed creature for one participant."""
        if not cards:
            return
        self._print_line()
        self._print_summary_heading(heading, "cast")
        self._print_line(f"      {self._format_type_breakdown(cards)}")
        card_counts = {}
        for event in cards:
            display_name = self._refresh_fallback_name_text(event.card_name)
            card_counts[display_name] = card_counts.get(display_name, 0) + 1

        for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
            card_name_str = str(card_name)
            suffix = f" x{count}" if count > 1 else ""
            self._print_line(f"      • [{card_name_str}]{suffix}")

        top_creature = self._highest_known_creature_snapshot(seat_id)
        if top_creature:
            self._print_line(
                f"      Highest observed creature: [{top_creature['name']}] "
                f"reached {top_creature['power']}/{top_creature['toughness']}"
            )

    def _print_game_summary(self):
        """Print summary when game ends."""
        self._try_resolve_winner_from_log_tail()
        duration_display = self._game_duration_display()
        outcome, reason = self._resolve_game_outcome()
        self._record_session_outcome(outcome)
        self._print_result_summary(outcome, reason, duration_display)
        self._print_best_of_three_status()
        self._print_starting_hand_summary()
        self._print_cards_played_summary()
        self._print_exile_and_match_stats_summary()
        self._print_card_collection_summary(self.player_cards, heading="Your Cards", seat_id=self.game_state.player_seat_id)
        self._print_card_collection_summary(self.opponent_cards, heading="Opponent's Cards", seat_id=self.game_state.opponent_seat_id)

        self._print_line("\n" + "="*75)
        self._print_line("Ready for next game...\n")

        self._persist_game_analytics(outcome, reason)

        # Reset game state for next game
        self.game_state.reset()
        self._active_deck_candidate_key = None
        self._require_explicit_game_start = True

    def _print_summary(self):
        """Print a summary of tracked cards."""
        self._print_line()
        self._print_summary_heading("Session Summary", "turn")
        self._print_line("=" * 75)
        known_results = self.session_wins + self.session_losses
        win_rate = (self.session_wins / known_results * 100.0) if known_results > 0 else 0.0

        if (
            not self.game_state.in_match
            and not self.player_cards
            and not self.opponent_cards
            and self.session_games_played == 0
            and self.session_player_cards_played == 0
            and self.session_opponent_cards_played == 0
        ):
            self._print_line("   No matches tracked this session.")
            self._print_line("   Make sure to start the tracker before playing a game!")
            return

        self._print_line(f"   Games Played: {self.session_games_played}")
        self._print_line(f"   Wins: {self.session_wins}")
        self._print_line(f"   Losses: {self.session_losses}")
        if getattr(self, "session_draws", 0):
            self._print_line(f"   Draws: {self.session_draws}")
        if self.session_unknown:
            self._print_line(f"   Unknown Results: {self.session_unknown}")
        self._print_line(f"   Win Rate: {win_rate:.1f}%")
        self._print_line(f"   Play Time: {self._session_runtime_str()}")
        self._print_line(f"   Total Mulligans: {self.session_total_mulligans}")
        self._print_line(f"   Total Cards Played: {self.session_player_cards_played}")
        self._print_line(f"   Total Opponent Cards Played: {self.session_opponent_cards_played}")

        if self.player_cards:
            self._print_line()
            self._print_summary_heading("Your Cards This Game", "cast")
            self._print_line(f"      {self._format_type_breakdown(self.player_cards)}")
            # Count duplicates
            card_counts = {}
            for event in self.player_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    self._print_line(f"      • [{card_name_str}] x{count}")
                else:
                    self._print_line(f"      • [{card_name_str}]")

        if self.opponent_cards:
            self._print_line()
            self._print_summary_heading("Opponent's Cards This Game", "cast")
            self._print_line(f"      {self._format_type_breakdown(self.opponent_cards)}")
            # Count duplicates
            card_counts = {}
            for event in self.opponent_cards:
                card_counts[event.card_name] = card_counts.get(event.card_name, 0) + 1

            for card_name, count in sorted(card_counts.items(), key=lambda x: (str(x[0]), x[1])):
                card_name_str = str(card_name)  # Same format as turn log: "Card Name (Type P/T)"
                if count > 1:
                    self._print_line(f"      • [{card_name_str}] x{count}")
                else:
                    self._print_line(f"      • [{card_name_str}]")

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
