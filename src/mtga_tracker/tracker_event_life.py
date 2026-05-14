"""Life-total event helpers for CardTracker."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


class TrackerLifeMixin:
    """Focused event helpers used by TrackerEventsMixin."""

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
            (
                turn_override
                if turn_override is not None
                else (self.game_state.turn_number if self.game_state.turn_number > 0 else None)
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
                    self._format_actor_event(
                        "💚",
                        seat_id,
                        f"gained {diff} life{source_text} (now {life})",
                        turn_override=turn_for_display,
                    ),
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
                remaining = (
                    self.game_state.pending_damage_to_seat.get(int(seat_id), 0) - matched_damage
                )
                if remaining > 0:
                    self.game_state.pending_damage_to_seat[int(seat_id)] = remaining
                else:
                    self.game_state.pending_damage_to_seat.pop(int(seat_id), None)
            unmatched_life_loss = lost_life - matched_damage
            if unmatched_life_loss > 0:
                source_seat = (
                    source_seat_override
                    if source_seat_override
                    in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
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
                    self._format_actor_event(
                        "💔",
                        seat_id,
                        f"lost {-diff} life{source_text} (now {life})",
                        turn_override=turn_for_display,
                    ),
                    "life_loss",
                )

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
            and any(
                diff < 0 and seat_id in previous_attack_target_ids
                for seat_id, diff, _life in life_updates
            )
        ):
            return self.game_state.turn_number - 1
        return None

    def _apply_life_updates(
        self, life_updates: List[tuple], late_life_turn_override: Optional[int]
    ) -> None:
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
        source_obj = (
            self._lookup_object(source_instance_id, game_objects_by_id)
            if source_instance_id is not None
            else {}
        )
        if not source_obj and affector_id is not None:
            source_obj = self._lookup_object(int(affector_id), game_objects_by_id)
        source_seat = source_obj.get("controllerSeatId")
        if source_seat is None:
            source_seat = source_obj.get("ownerSeatId")
        source_label = None
        if source_obj:
            source_label = self._object_display_name(
                source_obj, source_obj.get("instanceId") or source_instance_id or affector_id
            )

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
