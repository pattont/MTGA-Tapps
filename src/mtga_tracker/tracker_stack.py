"""Stack-related CardTracker mixin methods."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .state import CardEvent


class TrackerStackMixin:
    """Stack tracking helpers used by CardTracker."""

    def _seat_stack_stats(self, seat_id: Optional[int]) -> Optional[Dict[str, int]]:
        """Return mutable per-seat stack stats dict when seat is known."""
        if seat_id not in (1, 2):
            return None
        return self.game_state.stack_stats[int(seat_id)]

    def _stack_key(self, instance_id: Optional[int]) -> Optional[int]:
        """Return canonical key for a stack object or ability instance."""
        if instance_id is None:
            return None
        try:
            return self._canonical_instance_id(int(instance_id)) or int(instance_id)
        except (TypeError, ValueError):
            return None

    def _register_stack_item(
        self,
        instance_id: Optional[int],
        *,
        seat_id: Optional[int],
        label: str,
        kind: str,
        turn_override: Optional[int] = None,
    ) -> Optional[int]:
        """Record one spell/ability as currently pending on the stack."""
        stack_key = self._stack_key(instance_id)
        if stack_key is None:
            return None
        pending_keys = [
            key
            for key, existing in self.game_state.stack_items.items()
            if key != stack_key and isinstance(existing, dict) and existing.get("status") == "pending"
        ]
        for key in pending_keys:
            self.game_state.stack_items[key]["show_lifecycle"] = True
        item = self.game_state.stack_items.get(stack_key)
        if not isinstance(item, dict) or item.get("status") not in {"pending", "resolved", "countered", "fizzled"}:
            stats = self._seat_stack_stats(seat_id)
            if stats is not None:
                stats["put_on_stack"] += 1
        self.game_state.stack_items[stack_key] = {
            "seat": seat_id,
            "label": label,
            "kind": kind,
            "turn": self._event_turn_number(seat_id, turn_override),
            "status": "pending",
            "show_lifecycle": bool(pending_keys) or (isinstance(item, dict) and bool(item.get("show_lifecycle"))),
        }
        return stack_key

    def _is_mana_ability_stack_item(self, item: Dict[str, Any]) -> bool:
        """Return True for mana abilities that should not produce stack failure noise."""
        if item.get("kind") != "ability":
            return False
        return self._is_mana_ability_text(str(item.get("label") or ""))

    def _emit_stack_item_status(
        self,
        instance_id: Optional[int],
        status: str,
        *,
        resolution_label: Optional[str] = None,
    ) -> bool:
        """Emit an indented stack lifecycle line for a tracked spell/ability."""
        stack_key = self._stack_key(instance_id)
        if stack_key is None:
            return False
        item = self.game_state.stack_items.get(stack_key)
        if not isinstance(item, dict) or item.get("status") != "pending":
            return False

        if status == "fizzled" and item.get("kind") == "ability":
            # An activated ability leaving the stack almost always resolved —
            # the "fizzled" inference is noise (dual-land mana taps, Soulstone
            # Sanctuary-style animations). Count it as resolved, silently.
            item["status"] = "resolved"
            stats = self._seat_stack_stats(item.get("seat"))
            if stats is not None:
                stats["resolved"] += 1
            return True

        seat_id = item.get("seat")
        label = resolution_label or item.get("label") or "stack item"
        if status == "resolved":
            status_text = "[resolved]"
            style = "stack_resolve"
            stat_key = "resolved"
        elif status == "countered":
            status_text = "[countered]"
            style = "stack_fail"
            stat_key = "countered"
        elif status == "fizzled":
            status_text = "[left stack without resolving - inferred]"
            style = "stack_fail"
            stat_key = "fizzled"
        else:
            return False

        item["status"] = status
        stats = self._seat_stack_stats(seat_id)
        if stats is not None:
            stats[stat_key] += 1
        if stat_key == "countered":
            match_stats = self._seat_stats(seat_id)
            if match_stats is not None:
                match_stats["spells_countered"] += 1
        if status == "resolved" and not item.get("show_lifecycle"):
            return True
        turn_prefix = self._turn_prefix_for_number(self._event_turn_number(seat_id, item.get("turn")))
        self._print_event(f"\t{turn_prefix}Stack: {label} {status_text}", style)
        return True

    def _record_played_card_once(
        self,
        *,
        instance_id: int,
        canonical_instance_id: int,
        seat_id: Optional[int],
        track_name: str,
        card_types: List[str],
        grp_id: Optional[int] = None,
    ) -> None:
        """Count a card as played/cast exactly once, even if it later fails to resolve."""
        if instance_id in self.game_state.seen_instance_ids or canonical_instance_id in self.game_state.seen_instance_ids:
            return
        player = self._seat_label(seat_id).lower()
        type_category = self._get_card_type_category(card_types)
        event = CardEvent(track_name, player, card_type_category=type_category)
        if seat_id == self.game_state.player_seat_id:
            self.player_cards.append(event)
            self.session_player_cards_played += 1
        else:
            self.opponent_cards.append(event)
            self.session_opponent_cards_played += 1
        self.game_state.seen_instance_ids.add(int(instance_id))
        self.game_state.seen_instance_ids.add(int(canonical_instance_id))
        self._count_played_card_roles(seat_id, grp_id)

    def _count_played_card_roles(self, seat_id: Optional[int], grp_id: Optional[int]) -> None:
        """Bump removal/wipe/bounce played counters for a classified cast."""
        if grp_id is None:
            return
        stats = self._seat_stats(seat_id)
        if stats is None:
            return
        roles = self._card_roles(grp_id)
        if "removal" in roles:
            stats["removal_played"] += 1
        if "wipe" in roles:
            stats["wipes_played"] += 1
        if "bounce" in roles:
            stats["bounces_played"] += 1
        if "counter" in roles:
            stats["counters_played"] += 1

    def _reconcile_deleted_stack_items(self, deleted_instance_ids: Any) -> None:
        """Infer unresolved stack exits after the payload's annotations have had a chance to resolve them."""
        if not isinstance(deleted_instance_ids, list):
            return
        for instance_id in deleted_instance_ids:
            stack_key = self._stack_key(instance_id)
            if stack_key is None:
                continue
            item = self.game_state.stack_items.get(stack_key)
            if isinstance(item, dict) and item.get("status") == "pending":
                self._emit_stack_item_status(stack_key, "fizzled")

    def _lookup_object(self, instance_id: Optional[int], game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Get best-known object payload from current state + snapshot fallback."""
        if instance_id is None:
            return {}
        canonical_id = self._canonical_instance_id(instance_id)
        current_obj = (game_objects_by_id or {}).get(instance_id) or {}
        snapshot_obj = self.game_state.object_snapshots.get(instance_id) or {}
        if canonical_id is not None and canonical_id != instance_id:
            canonical_current = (game_objects_by_id or {}).get(canonical_id) or {}
            canonical_snapshot = self.game_state.object_snapshots.get(canonical_id) or {}
        else:
            canonical_current = {}
            canonical_snapshot = {}
        merged = canonical_snapshot.copy()
        merged.update(canonical_current)
        merged.update(snapshot_obj)
        merged.update(current_obj)
        return merged

    def _flush_pending_spell_cast(
        self,
        source_id: Optional[int],
        game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> bool:
        """Emit a deferred cast line before downstream spell effects log."""
        if source_id is None:
            return False
        canonical_source_id = self._canonical_instance_id(source_id) or int(source_id)
        if canonical_source_id in self.game_state.seen_instance_ids:
            return False
        pending = self.game_state.pending_spell_roots.get(canonical_source_id)
        if not isinstance(pending, dict):
            return False

        source_obj = self._lookup_object(source_id, game_objects_by_id)
        if not isinstance(source_obj, dict) or not source_obj:
            return False

        owner_seat = source_obj.get("ownerSeatId")
        controller_seat = source_obj.get("controllerSeatId")
        determining_seat = controller_seat if controller_seat is not None else owner_seat
        if determining_seat not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            determining_seat = pending.get("seat")
        if determining_seat not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            return False

        grp_id = source_obj.get("grpId")
        card_name = pending.get("name")
        if not card_name:
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        card_types = source_obj.get("cardTypes", [])
        type_str = self._format_card_type(card_types)
        self._flush_pending_turn_header_for_seat(determining_seat)

        turn_for_display = (
            self.game_state.last_player_turn_number
            if determining_seat == self.game_state.player_seat_id
            else (self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced)
        )
        turn_for_display = self._event_turn_number(determining_seat, turn_for_display)

        if "CardType_Creature" in card_types:
            power = source_obj.get("power", {}).get("value", "?")
            toughness = source_obj.get("toughness", {}).get("value", "?")
            track_name = f"{card_name} ({type_str} {power}/{toughness})"
        else:
            track_name = f"{card_name} ({type_str})"
        target_ids = self._target_ids_for_instance(source_id)
        target_id = target_ids[0] if target_ids else None
        target_obj = self._lookup_object(target_id, game_objects_by_id) if target_id else {}
        target_objs = self._target_objects_for_annotation(target_ids, game_objects_by_id or {}) if target_ids else []
        target_str = self._format_target_suffix(target_id, target_obj, target_objs)
        text = f"cast [{track_name}]{target_str}"
        self._print_event(
            self._format_actor_event(">", determining_seat, text, turn_override=turn_for_display),
            "cast",
        )
        self._register_stack_item(
            canonical_source_id,
            seat_id=determining_seat,
            label=f"[{track_name}]{target_str}",
            kind="spell",
            turn_override=turn_for_display,
        )

        self._record_played_card_once(
            instance_id=int(source_id),
            canonical_instance_id=canonical_source_id,
            seat_id=determining_seat,
            track_name=track_name,
            card_types=card_types,
            grp_id=source_obj.get("grpId"),
        )
        self.game_state.pending_spell_roots.pop(canonical_source_id, None)
        return True

    def _flush_pending_spell_cast_from_any(
        self,
        source_ids: List[Optional[int]],
        game_objects_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> bool:
        """Emit a deferred cast line using the first matching source id."""
        for source_id in source_ids:
            if source_id is None:
                continue
            if self._flush_pending_spell_cast(source_id, game_objects_by_id):
                return True
        return False
