"""Opening-hand, deck, seat, and match metadata CardTracker mixin methods."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .format_normalizer import (
    format_label,
    friendly_midweek_label,
    normalize_match_format,
    normalize_match_text,
)
from .opening_hand import (
    game_objects_by_instance,
    visible_opening_hand_snapshots,
)
from .state import CardEvent


class TrackerOpeningDeckMixin:
    """Opening hand, deck metadata, commanders, and format helpers used by CardTracker."""

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

    def _format_commander_names(self, names: List[str]) -> str:
        """Format one or two commander names for display."""
        unique = self._unique_names([self._refresh_fallback_name_text(name) for name in names])
        return " + ".join(unique) if unique else "Unknown"

    def _friendly_format_label(self, raw_format: Optional[str] = None) -> str:
        """Convert raw queue/format identifiers into user-facing labels."""
        raw = raw_format if raw_format is not None else self.game_state.format_str
        default_best_of = 3 if self.game_state.match_type == "best_of_3" else 1
        return format_label(raw, default_best_of=default_best_of)

    @staticmethod
    def _friendly_midweek_label(raw_format: str) -> str:
        """Convert MWM event identifiers into readable Midweek Magic labels."""
        return friendly_midweek_label(raw_format)

    def _set_match_format(self, fmt: str) -> bool:
        """Apply trusted live match format metadata and infer match length."""
        if not isinstance(fmt, str) or not fmt:
            return False
        updated = self.game_state.format_str != fmt
        self.game_state.format_str = fmt
        normalized = normalize_match_format(fmt)
        if normalized.best_of == 3:
            if self.game_state.match_type != "best_of_3":
                self.game_state.match_type = "best_of_3"
                updated = True
        elif normalized.best_of == 1:
            if self.game_state.match_type != "best_of_1":
                self.game_state.match_type = "best_of_1"
                updated = True
        return updated

    def _set_player_commanders_from_ids(self, command_zone_ids: List[int]) -> None:
        """Store player's commander names from deck metadata command zone ids."""
        names = self._unique_names(
            [
                self.card_db.get_card_name(int(card_id))
                for card_id in command_zone_ids
                if card_id is not None
            ]
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
        text = self._normalize_match_text(
            format_text if format_text is not None else self.game_state.format_str
        )
        return "brawl" in text

    def _is_trusted_queue_event_name(self, event_name: Optional[str]) -> bool:
        """Return True for event names that identify a live queue rather than only deck format."""
        text = self._normalize_match_text(event_name)
        if not text:
            return False
        if text.startswith("mwm") or text.startswith("midweekmagic"):
            return True
        return text in {
            "play",
            "ladder",
            "standard",
            "traditionalstandard",
            "constructedbestof1",
            "constructedbestof3",
            "bestof1",
            "bestof3",
            "historic",
            "historicplay",
            "explorer",
            "explorerplay",
            "timeless",
            "timelessplay",
            "alchemy",
        }

    def _has_explicit_non_brawl_format(self) -> bool:
        """Return True when trusted event/deck metadata identifies a non-Brawl queue."""
        candidates = [self.game_state.format_str, self.game_state.player_deck_event_name]
        if self._active_deck_candidate_key:
            active = self._deck_candidates.get(self._active_deck_candidate_key, {})
            if isinstance(active, dict):
                candidates.extend([active.get("internal_event_name"), active.get("format_attr")])
        for raw in candidates:
            text = self._normalize_match_text(raw)
            if not text or text == "unknown":
                continue
            if "brawl" in text:
                return False
            if text.startswith("mwm") or text.startswith("midweekmagic"):
                return True
            if text in {
                "standard",
                "traditionalstandard",
                "constructedbestof1",
                "constructedbestof3",
                "bestof1",
                "bestof3",
                "play",
                "ladder",
                "historic",
                "historicplay",
                "explorer",
                "explorerplay",
                "timeless",
                "timelessplay",
                "alchemy",
            }:
                return True
            if any(
                marker in text
                for marker in ("standard", "historic", "explorer", "timeless", "alchemy")
            ):
                return True
        return False

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
        has_populated_command_zone = (
            any(
                isinstance(zone, dict)
                and zone.get("type") == "ZoneType_Command"
                and bool(zone.get("objectInstanceIds"))
                for zone in zones
            )
            if isinstance(zones, list)
            else False
        )

        command_zone_implies_brawl = (
            has_populated_command_zone and not self._has_explicit_non_brawl_format()
        )
        if (
            "brawl" in variant_text
            or (isinstance(min_commander_size, int) and min_commander_size > 0)
            or command_zone_implies_brawl
        ):
            self.game_state.format_str = self._best_brawl_format_label()
        elif (
            isinstance(min_commander_size, int)
            and min_commander_size == 0
            and not self._is_brawl_format()
        ):
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
                command_by_seat.setdefault(int(owner_seat), []).append(
                    self.card_db.get_card_name(int(grp_id))
                )

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
                seat
                for seat, names in self.game_state.commanders_by_seat.items()
                if set(names) == player_commander_names
            ]
            if len(matching_seats) == 1:
                self.game_state.player_seat_id = matching_seats[0]
                other_seats = [
                    seat
                    for seat in self.game_state.commanders_by_seat.keys()
                    if seat != matching_seats[0]
                ]
                if len(other_seats) == 1:
                    self.game_state.opponent_seat_id = other_seats[0]

        if self.game_state.player_seat_id in (1, 2) and self.game_state.opponent_seat_id not in (
            1,
            2,
        ):
            other_seats = [
                seat
                for seat in self.game_state.commanders_by_seat.keys()
                if seat != self.game_state.player_seat_id
            ]
            if len(other_seats) == 1:
                self.game_state.opponent_seat_id = other_seats[0]

        self._sync_commander_views_from_seats()
        if self.game_state._reserved_players:
            for r in self.game_state._reserved_players:
                if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                    self.game_state.player_display_name = (
                        self.game_state.player_display_name or r["name"]
                    )
                elif r.get("seat") == self.game_state.opponent_seat_id and r.get("name"):
                    self.game_state.opponent_display_name = r["name"]

    def _maybe_print_pregame_commander_lines(self) -> None:
        """Print commander lines after game start once discovered, before turn banners."""
        if not self.game_state.in_match or self.game_state.last_turn_announced > 0:
            return
        if not self._is_brawl_format():
            return
        if self.game_state.player_commanders and not self.game_state.player_commanders_announced:
            self._print_line(
                f"   Your Commander: {self._format_commander_names(self.game_state.player_commanders)}"
            )
            self.game_state.player_commanders_announced = True
        if (
            self.game_state.opponent_commanders
            and not self.game_state.opponent_commanders_announced
        ):
            self._print_line(
                f"   Opponent Commander: {self._format_commander_names(self.game_state.opponent_commanders)}"
            )
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
                        self.game_state.player_display_name = (
                            self.game_state.player_display_name or r["name"]
                        )
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
        for key in (
            "screenName",
            "ScreenName",
            "playerName",
            "PlayerName",
            "displayName",
            "DisplayName",
            "accountName",
            "userName",
            "name",
        ):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _resolve_seats_from_reserved_players(self) -> None:
        """Resolve seats when reserved player names identify the local player."""
        local_name = self.game_state.player_display_name
        if not isinstance(local_name, str) or not local_name.strip():
            return
        local_key = local_name.strip().casefold()
        reserved = [
            player
            for player in self.game_state._reserved_players
            if isinstance(player, dict) and player.get("seat") in (1, 2)
        ]
        if len(reserved) < 2:
            return

        local = None
        for player in reserved:
            name = player.get("name")
            if isinstance(name, str) and name.strip().casefold() == local_key:
                local = player
                break
        if local is None:
            return

        player_seat = local.get("seat")
        opponent = next(
            (player for player in reserved if player.get("seat") != player_seat),
            None,
        )
        if opponent is None:
            return

        self.game_state.player_seat_id = player_seat
        self.game_state.opponent_seat_id = opponent.get("seat")
        if local.get("name"):
            self.game_state.player_display_name = local["name"]
        if opponent.get("name"):
            self.game_state.opponent_display_name = opponent["name"]

    @staticmethod
    def _is_localized_placeholder_name(name: Optional[str]) -> bool:
        """Return True for MTGA localization placeholder deck names (e.g. '?=?Loc/...')."""
        if not isinstance(name, str):
            return False
        return name.startswith("?=?Loc/")

    @staticmethod
    def _normalize_match_text(value: Optional[str]) -> str:
        """Normalize strings for loose event/format matching."""
        return normalize_match_text(value)

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
                if not existing_name or (
                    self._is_localized_placeholder_name(existing_name)
                    and not self._is_localized_placeholder_name(deck_name)
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
                if (
                    not isinstance(existing_last_played, datetime)
                    or last_played > existing_last_played
                ):
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
        if (
            isinstance(deck_name, str)
            and deck_name
            and not self._is_localized_placeholder_name(deck_name)
        ):
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
        event_name = candidate.get("internal_event_name")
        used_trusted_queue_format = False
        if (
            candidate.get("trusted_active")
            and candidate.get("trusted_queue_format")
            and isinstance(event_name, str)
            and self._is_trusted_queue_event_name(event_name)
        ):
            self._set_match_format(event_name)
            self._format_from_backfill = bool(getattr(self, "_parsing_backfilled_metadata", False))
            used_trusted_queue_format = True
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
            if not used_trusted_queue_format and not implies_best_of_three and (
                self.game_state.format_str == "Unknown" or self._format_from_backfill
            ):
                self.game_state.format_str = format_attr
                self._format_from_backfill = bool(
                    getattr(self, "_parsing_backfilled_metadata", False)
                )
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
                self._resolve_seats_from_reserved_players()
                # If we know our seat, resolve our name and opponent's from reserved list
                if self.game_state.player_seat_id is not None and self.game_state._reserved_players:
                    for r in self.game_state._reserved_players:
                        if r.get("seat") == self.game_state.player_seat_id and r.get("name"):
                            self.game_state.player_display_name = (
                                self.game_state.player_display_name or r["name"]
                            )
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
        deck_updated = (
            self._ingest_course_deck_metadata(courses) if isinstance(courses, list) else False
        )
        trusted_single_course = isinstance(data.get("CourseDeckSummary"), dict) and isinstance(
            data.get("InternalEventName"), str
        )
        if trusted_single_course:
            single_course = [data]
            if self._ingest_course_deck_metadata(single_course):
                deck_updated = True
            if any(
                marker in line_lower
                for marker in (
                    "eventsetdeckv2",
                    "eventsetdeckv3",
                    "deckupsertdeckv2",
                    "deckupsertdeckv3",
                )
            ):
                candidate_key = self._course_candidate_key(data)
                if candidate_key and (
                    "eventsetdeckv3" in line_lower or "deckupsertdeckv3" in line_lower
                ):
                    candidate = self._deck_candidates.get(candidate_key)
                    if isinstance(candidate, dict):
                        candidate["trusted_queue_format"] = True
                self._lock_active_deck_candidate(candidate_key)
        deck_event_course = self._course_from_deck_event_payload(data)
        if deck_event_course is not None:
            if self._ingest_course_deck_metadata([deck_event_course]):
                deck_updated = True
            if any(
                marker in line_lower
                for marker in (
                    "eventsetdeckv2",
                    "eventsetdeckv3",
                    "deckupsertdeckv2",
                    "deckupsertdeckv3",
                )
            ):
                candidate_key = self._course_candidate_key(deck_event_course)
                if candidate_key and (
                    "eventsetdeckv3" in line_lower or "deckupsertdeckv3" in line_lower
                ):
                    candidate = self._deck_candidates.get(candidate_key)
                    if isinstance(candidate, dict):
                        candidate["trusted_queue_format"] = True
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
            self._print_line(
                f"   Your Commander: {self._format_commander_names(g.player_commanders)}"
            )
            g.player_commanders_announced = True
        if self._is_brawl_format(g.format_str) and g.opponent_commanders:
            self._print_line(
                f"   Opponent Commander: {self._format_commander_names(g.opponent_commanders)}"
            )
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
            self._print_line(
                f"🔄 Mulligan to {len(hand_cards)} (mulligans: {self.game_state.mulligan_count})"
            )
        self.game_state._hand_before_mulligan = []
        self.game_state._hand_before_mulligan_ids = []
        self.game_state._hand_before_mulligan_events = []
        self.game_state.opening_hand_capture_closed = True
        self.game_state.opening_keep_confirmed = False
        self.game_state.opening_select_n_ids = []
        n = len(self.game_state.starting_hand)
        self._print_line(f"\nYour Starting Hand ({n} cards):")
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
            hand_events = [CardEvent(card_name, "player") for card_name in hand_cards]
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

    def _choose_visible_opening_hand(
        self, visible_hands: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Select the player hand from fully visible opening hand snapshots."""
        if not visible_hands:
            return None
        if self.game_state.player_seat_id is not None:
            hand = next(
                (
                    hand
                    for hand in visible_hands
                    if hand["owner_seat"] == self.game_state.player_seat_id
                ),
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

    def _sync_opening_hand_seats(
        self, owner_seat: int, hand_zone_owners: List[int], data: Dict[str, Any]
    ) -> None:
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
                if self.game_state.opening_keep_confirmed or (
                    turn_num and turn_num >= 1 and not mulligan_prompt_present
                ):
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
