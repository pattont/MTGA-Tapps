"""State, object snapshot, and lookup CardTracker mixin methods."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


class TrackerStateLookupMixin:
    """Extracted helpers used by CardTracker."""

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
            int(instance_id) for instance_id in deleted_instance_ids if isinstance(instance_id, int)
        }
        if not deleted_ids:
            return

        for instance_id in deleted_ids:
            self.game_state.object_snapshots.pop(instance_id, None)
            self.game_state.current_combat_attackers.pop(instance_id, None)
            self.game_state.current_combat_blockers.pop(instance_id, None)

        self.game_state.attackers = [
            instance_id
            for instance_id in self.game_state.attackers
            if instance_id not in deleted_ids
        ]
        self.game_state.blockers = {
            blocker_id: [
                attacker_id for attacker_id in attacker_ids if attacker_id not in deleted_ids
            ]
            for blocker_id, attacker_ids in self.game_state.blockers.items()
            if blocker_id not in deleted_ids
        }
        self.game_state.reported_attack_keys = {
            key
            for key in self.game_state.reported_attack_keys
            if not (isinstance(key, tuple) and len(key) > 1 and key[1] in deleted_ids)
        }
        self.game_state.reported_block_pairs = {
            key
            for key in self.game_state.reported_block_pairs
            if not (
                isinstance(key, tuple)
                and (
                    (len(key) > 1 and key[1] in deleted_ids)
                    or (len(key) > 2 and key[2] in deleted_ids)
                )
            )
        }
        self.game_state.combat_loss_events_counted = {
            key
            for key in self.game_state.combat_loss_events_counted
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

    def _maybe_log_identity_change(
        self, instance_id: int, previous: Dict[str, Any], current: Dict[str, Any]
    ) -> None:
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
        if not any(
            card_type in permanent_types for card_type in list(current_types) + list(previous_types)
        ):
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

    def _highest_known_creature_snapshot(
        self, seat_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
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
            if isinstance(zone, dict)
            and zone.get("type") == "ZoneType_Battlefield"
            and zone.get("zoneId") is not None
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

    def _format_card_type(self, card_types: List[str]) -> str:
        """Format card types for display."""
        if not card_types:
            return "Card"

        # Clean up and prioritize card types
        types = [t.replace("CardType_", "") for t in card_types]

        # Show main types
        main_types = []
        for t in [
            "Creature",
            "Instant",
            "Sorcery",
            "Enchantment",
            "Artifact",
            "Planeswalker",
            "Land",
        ]:
            if t in types:
                main_types.append(t)

        return ", ".join(main_types) if main_types else "Card"

    def _get_card_type_category(self, card_types: List[str]) -> str:
        """Return a single category for breakdown: Land, Creature, Instant, Sorcery, Enchantment, Artifact, Planeswalker, or Other."""
        if not card_types:
            return "Other"
        types = [t.replace("CardType_", "") for t in card_types]
        for cat in [
            "Land",
            "Creature",
            "Instant",
            "Sorcery",
            "Enchantment",
            "Artifact",
            "Planeswalker",
        ]:
            if cat in types:
                return cat
        return "Other"
