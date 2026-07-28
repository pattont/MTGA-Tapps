"""Zone-transfer and annotation dispatch CardTracker mixin methods."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .state import CardEvent


class TrackerZoneTransferMixin:
    """Zone-transfer helpers used by CardTracker."""

    def _emit_state_based_zone_transfer(
        self,
        *,
        category: str,
        instance_id: int,
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Optional[int],
        zone_dest: Optional[int],
    ) -> bool:
        """Emit user-facing lines for state-based actions that move permanents."""
        reason_by_category = {
            "SBA_Damage": "lethal damage",
            "SBA_ZeroToughness": "0 toughness",
            "SBA_ZeroLoyalty": "0 loyalty",
            "SBA_UnattachedAura": "unattached Aura",
        }
        reason = reason_by_category.get(str(category))
        if reason is None:
            return False

        owner_seat = self._resolve_zone_transfer_seat(
            card_obj=card_obj,
            annotation=annotation,
            game_objects_by_id=game_objects_by_id,
            zone_src=zone_src,
            zone_dest=zone_dest,
            zones_by_id=zones_by_id,
        )
        if not self._is_tracked_seat(owner_seat):
            return True

        grp_id = card_obj.get("grpId") if isinstance(card_obj, dict) else None
        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        self._flush_pending_turn_header_for_seat(owner_seat)
        event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
        self._print_event(
            self._format_actor_event(
                "",
                owner_seat,
                f"[{card_name}] was put into graveyard ({reason})",
                turn_override=event_turn,
            ),
            "zone",
        )

        card_types = (card_obj or {}).get("cardTypes") or []
        if "CardType_Creature" in card_types:
            stats = self._seat_stats(owner_seat)
            if stats is not None:
                combat_loss_key = (int(instance_id), str(category))
                if combat_loss_key not in self.game_state.combat_loss_events_counted:
                    if instance_id in self.game_state.current_combat_attackers:
                        stats["attackers_lost"] += 1
                        self.game_state.combat_loss_events_counted.add(combat_loss_key)
                    elif instance_id in self.game_state.current_combat_blockers:
                        stats["blockers_lost"] += 1
                        self.game_state.combat_loss_events_counted.add(combat_loss_key)
        return True

    def _handle_countered_zone_transfer(
        self,
        instance_id: int,
        canonical_instance_id: int,
        card_obj: Dict[str, Any],
    ) -> None:
        """Handle a zone-transfer category showing a spell was countered."""
        if card_obj:
            grp_id = card_obj.get("grpId")
            owner_seat = card_obj.get("ownerSeatId")
            card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
            if not self._emit_stack_item_status(canonical_instance_id, "countered"):
                self._flush_pending_turn_header_for_seat(owner_seat)
                event_turn = (
                    self.game_state.turn_number if self.game_state.turn_number > 0 else None
                )
                self._print_event(
                    self._format_actor_event(
                        "🚫",
                        owner_seat,
                        f"[{card_name}] was countered",
                        turn_override=event_turn,
                    ),
                    "counter",
                )
        self.game_state.pending_spell_roots.pop(canonical_instance_id, None)

    def _handle_draw_zone_transfer(
        self,
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Optional[int],
        zone_dest: Optional[int],
    ) -> None:
        """Handle a draw zone transfer and update draw stats."""
        owner_seat = self._resolve_zone_transfer_seat(
            card_obj=card_obj,
            annotation=annotation,
            game_objects_by_id=game_objects_by_id,
            zone_src=zone_src,
            zone_dest=zone_dest,
            zones_by_id=zones_by_id,
        )
        if owner_seat not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            return
        self._flush_pending_turn_header_for_seat(owner_seat)
        event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
        self._print_event(
            self._format_actor_event("📥", owner_seat, "drew a card", turn_override=event_turn),
            "draw",
        )
        stats = self._seat_stats(owner_seat)
        if stats is not None:
            stats["cards_drawn"] += 1
        grp_id = card_obj.get("grpId") if isinstance(card_obj, dict) else None
        if grp_id:
            try:
                seat_id = int(owner_seat)
            except (TypeError, ValueError):
                seat_id = None
            if seat_id in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                card_name = self.card_db.get_card_name(grp_id)
                card_types = card_obj.get("cardTypes") or []
                type_category = self._get_card_type_category(card_types)
                if type_category == "Other":
                    type_category = self.card_db.get_card_type_category(grp_id) or "Other"
                draw_event = CardEvent(
                    card_name,
                    "player" if seat_id == self.game_state.player_seat_id else "opponent",
                    timestamp=self._now(),
                    card_type_category=type_category,
                )
                draw_event.turn_number = event_turn
                self.game_state.drawn_card_events.setdefault(seat_id, []).append(draw_event)

    def _handle_mill_zone_transfer(
        self,
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Optional[int],
        zone_dest: Optional[int],
        source_id: Optional[int],
        affector_id: Optional[int],
    ) -> None:
        """Handle a mill zone transfer and update mill stats."""
        self._flush_pending_spell_cast_from_any([source_id, affector_id], game_objects_by_id)
        owner_seat = self._resolve_zone_transfer_seat(
            card_obj=card_obj,
            annotation=annotation,
            game_objects_by_id=game_objects_by_id,
            zone_src=zone_src,
            zone_dest=zone_dest,
            zones_by_id=zones_by_id,
        )
        if owner_seat not in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
            return
        grp_id = card_obj.get("grpId") if isinstance(card_obj, dict) else None
        self._flush_pending_turn_header_for_seat(owner_seat)
        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
        self._print_event(
            self._format_actor_event(
                "🌊",
                owner_seat,
                f"milled [{card_name}]" if grp_id else "milled a card",
                turn_override=event_turn,
            ),
            "zone",
        )
        stats = self._seat_stats(owner_seat)
        if stats is not None:
            stats["cards_milled"] += 1

    def _handle_state_based_zone_transfer(
        self,
        category: str,
        instance_id: int,
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Optional[int],
        zone_dest: Optional[int],
    ) -> bool:
        """Emit user-visible state-based zone transfers when recognized."""
        return self._emit_state_based_zone_transfer(
            category=str(category),
            instance_id=int(instance_id),
            card_obj=card_obj,
            annotation=annotation,
            game_objects_by_id=game_objects_by_id,
            zones_by_id=zones_by_id,
            zone_src=zone_src,
            zone_dest=zone_dest,
        )

    def _handle_removal_zone_transfer(
        self,
        category: str,
        instance_id: int,
        canonical_instance_id: int,
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Optional[int],
        zone_dest: Optional[int],
        source_id: Optional[int],
        affector_id: Optional[int],
    ) -> None:
        """Handle destroy/exile/sacrifice/discard zone transfers and related stats."""
        self._flush_pending_spell_cast_from_any([source_id, affector_id], game_objects_by_id)
        self.game_state.pending_spell_roots.pop(canonical_instance_id, None)
        owner_seat = self._resolve_zone_transfer_seat(
            card_obj=card_obj,
            annotation=annotation,
            game_objects_by_id=game_objects_by_id,
            zone_src=zone_src,
            zone_dest=zone_dest,
            zones_by_id=zones_by_id,
        )
        if not (
            card_obj
            or owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
        ):
            return

        grp_id = card_obj.get("grpId") if card_obj else None
        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        card_types = (card_obj or {}).get("cardTypes") or []
        self._flush_pending_turn_header_for_seat(owner_seat)

        if category == "Destroy":
            icon = "💥"
            action = "destroyed"
        elif category == "Exile":
            icon = "🚫"
            action = "exiled"
        elif category == "Sacrifice":
            icon = "⚰️"
            action = "sacrificed"
        elif category == "Discard":
            icon = "🗑️"
            action = "discarded"
        else:
            icon = "💥"
            action = category.lower()
        event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
        is_stack_cost = (
            category in {"Discard", "Sacrifice", "Exile"}
            and affector_id is not None
            and isinstance(self.game_state.stack_items.get(self._stack_key(affector_id)), dict)
            and self.game_state.stack_items.get(self._stack_key(affector_id), {}).get("status")
            == "pending"
        )
        action_text = f"[{card_name}] was {action}"
        if is_stack_cost:
            action_text += " as cost"

        formatted_event = self._format_actor_event(
            icon,
            owner_seat,
            action_text,
            turn_override=event_turn,
        )
        if is_stack_cost:
            formatted_event = "\t" + formatted_event
        self._print_event(formatted_event, "zone")

        if "CardType_Creature" in card_types and owner_seat in (
            self.game_state.player_seat_id,
            self.game_state.opponent_seat_id,
        ):
            stats = self._seat_stats(owner_seat)
            if stats is not None:
                combat_loss_key = (int(instance_id), str(category))
                if combat_loss_key not in self.game_state.combat_loss_events_counted:
                    if instance_id in self.game_state.current_combat_attackers:
                        stats["attackers_lost"] += 1
                        self.game_state.combat_loss_events_counted.add(combat_loss_key)
                    elif instance_id in self.game_state.current_combat_blockers:
                        stats["blockers_lost"] += 1
                        self.game_state.combat_loss_events_counted.add(combat_loss_key)

        if category == "Exile":
            if owner_seat == self.game_state.player_seat_id:
                self.game_state.player_cards_exiled += 1
            elif owner_seat == self.game_state.opponent_seat_id:
                self.game_state.opponent_cards_exiled += 1
            stats = self._seat_stats(owner_seat)
            if stats is not None:
                stats["cards_exiled"] += 1
            exiler_seat = None
            if source_id is not None:
                source_obj = self._lookup_object(source_id, game_objects_by_id)
                exiler_seat = source_obj.get("controllerSeatId")
                if exiler_seat is None:
                    exiler_seat = source_obj.get("ownerSeatId")
            if exiler_seat is None and self.game_state.active_player in (
                self.game_state.player_seat_id,
                self.game_state.opponent_seat_id,
            ):
                exiler_seat = self.game_state.active_player

            if (
                owner_seat == self.game_state.player_seat_id
                and exiler_seat == self.game_state.opponent_seat_id
            ):
                self.game_state.player_cards_exiled_by_opponent += 1
            elif (
                owner_seat == self.game_state.opponent_seat_id
                and exiler_seat == self.game_state.player_seat_id
            ):
                self.game_state.opponent_cards_exiled_by_player += 1
        elif category == "Discard":
            stats = self._seat_stats(owner_seat)
            if stats is not None:
                stats["cards_discarded"] += 1

    def _handle_return_or_put_zone_transfer(
        self,
        category: str,
        canonical_instance_id: int,
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_dest: Optional[int],
        source_id: Optional[int],
        affector_id: Optional[int],
    ) -> None:
        """Handle return/put zone transfers and combat-swap inference."""
        self.game_state.pending_spell_roots.pop(canonical_instance_id, None)
        if not card_obj:
            return

        grp_id = card_obj.get("grpId")
        owner_seat = card_obj.get("ownerSeatId")
        controller_seat = card_obj.get("controllerSeatId")
        determining_seat = controller_seat if controller_seat is not None else owner_seat
        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        self._flush_pending_turn_header_for_seat(determining_seat)

        turn_for_display = self._turn_for_seat(determining_seat)
        # Mulligan/opening-hand setup can emit generic Return/Put zone transfers before
        # turn flow starts; suppress those so they are not misreported as battlefield actions.
        pre_turn_zone_noise = turn_for_display <= 0 and not self.game_state.combat_phase_active
        if category == "Return":
            if pre_turn_zone_noise:
                return
            source_obj = {}
            for candidate_id in (source_id, affector_id):
                if candidate_id is None:
                    continue
                source_obj = self._lookup_object(int(candidate_id), game_objects_by_id)
                if source_obj:
                    break
            source_seat = source_obj.get("controllerSeatId") if source_obj else None
            if source_seat is None and source_obj:
                source_seat = source_obj.get("ownerSeatId")
            source_name = (
                self._object_display_name(source_obj, source_obj.get("instanceId") or affector_id)
                if source_obj
                else None
            )
            if (
                source_obj
                and source_name
                and source_seat
                in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
            ):
                source_stack_key = self._stack_key(source_obj.get("instanceId") or affector_id)
                source_pending = isinstance(self.game_state.stack_items.get(source_stack_key), dict)
                if source_seat == determining_seat and source_pending:
                    message = f"returned [{card_name}] to hand as cost for [{source_name}]"
                else:
                    hand_owner = (
                        "your"
                        if determining_seat == self.game_state.player_seat_id
                        else "opponent's"
                    )
                    message = f"[{source_name}] returned [{card_name}] to {hand_owner} hand"
                self._print_event(
                    self._format_actor_event(
                        "↩️",
                        source_seat,
                        message,
                        turn_override=turn_for_display,
                    ),
                    "zone",
                )
            else:
                self._print_event(
                    self._format_actor_event(
                        "↩️",
                        determining_seat,
                        f"returned [{card_name}] to hand",
                        turn_override=turn_for_display,
                    ),
                    "zone",
                )
            if self.game_state.combat_phase_active:
                self.game_state.recent_combat_returns.append(
                    {
                        "seat_id": determining_seat,
                        "turn": turn_for_display,
                        "card_name": card_name,
                    }
                )
                self.game_state.recent_combat_returns = self.game_state.recent_combat_returns[-6:]
            return

        destination_zone = (
            (zones_by_id or {}).get(int(zone_dest)) if zone_dest is not None else None
        )
        destination_type = (
            destination_zone.get("type") if isinstance(destination_zone, dict) else None
        )
        if destination_type == "ZoneType_Hand":
            if pre_turn_zone_noise:
                return
            source_obj = {}
            for candidate_id in (source_id, affector_id):
                if candidate_id is None:
                    continue
                source_obj = self._lookup_object(int(candidate_id), game_objects_by_id)
                if source_obj:
                    break
            source_seat = source_obj.get("controllerSeatId") if source_obj else None
            if source_seat is None and source_obj:
                source_seat = source_obj.get("ownerSeatId")
            source_name = (
                self._object_display_name(source_obj, source_obj.get("instanceId") or affector_id)
                if source_obj
                else None
            )
            hand_owner = (
                "your" if determining_seat == self.game_state.player_seat_id else "opponent's"
            )
            if source_name and self._is_tracked_seat(source_seat):
                message = f"[{source_name}] put [{card_name}] into {hand_owner} hand"
                actor_seat = source_seat
            else:
                message = f"put [{card_name}] into {hand_owner} hand"
                actor_seat = determining_seat
            self._print_event(
                self._format_actor_event(
                    "",
                    actor_seat,
                    message,
                    turn_override=turn_for_display,
                ),
                "zone",
            )
            return

        # "Put" is a generic Arena category used for several destinations, including
        # the card bottomed after a London mulligan. Only describe it as entering the
        # battlefield when the destination is actually the battlefield (or unavailable
        # in older payloads that do not include zone metadata).
        if destination_type not in (None, "ZoneType_Battlefield"):
            return

        attack_state = str(card_obj.get("attackState", ""))
        put_in_attacking = "Attacking" in attack_state or bool(card_obj.get("attackInfo"))
        if pre_turn_zone_noise and not put_in_attacking:
            return
        matched_return = None
        if put_in_attacking and self.game_state.recent_combat_returns:
            for idx in range(len(self.game_state.recent_combat_returns) - 1, -1, -1):
                prev = self.game_state.recent_combat_returns[idx]
                if prev.get("seat_id") == determining_seat and prev.get("turn") == turn_for_display:
                    matched_return = self.game_state.recent_combat_returns.pop(idx)
                    break
        if matched_return:
            self._print_event(
                self._format_actor_event(
                    "🥷",
                    determining_seat,
                    f"Combat swap: returned [{matched_return['card_name']}] and put [{card_name}] onto battlefield attacking (possible Ninjutsu/Sneak)",
                    turn_override=turn_for_display,
                ),
                "attack",
            )
        else:
            put_suffix = " onto battlefield attacking" if put_in_attacking else " onto battlefield"
            self._print_event(
                self._format_actor_event(
                    "✨",
                    determining_seat,
                    f"put [{card_name}]{put_suffix}",
                    turn_override=turn_for_display,
                ),
                "zone",
            )

    def _card_name_from_game_object(self, card_obj: Dict[str, Any]) -> str:
        """Resolve a display card name from DB, overlay ID, or embedded log fields."""
        grp_id = card_obj.get("grpId")
        card_name_from_log = None
        for name_field in ["name", "cardName", "titleId", "displayName", "title", "cardTitle"]:
            if name_field in card_obj:
                potential_name = card_obj.get(name_field)
                if (
                    potential_name
                    and isinstance(potential_name, str)
                    and not potential_name.isdigit()
                    and len(potential_name) > 1
                ):
                    card_name_from_log = potential_name
                    break

        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
        if card_name.startswith("Card #") and card_name_from_log:
            card_name = card_name_from_log
            if grp_id:
                self.card_db.cache[grp_id] = card_name
                self.card_db._save_cache()
                if hasattr(self.card_db, "log_cache"):
                    self.card_db.log_cache[grp_id] = card_name

        if card_name.startswith("Card #") and card_obj:
            overlay_grp_id = card_obj.get("overlayGrpId")
            if overlay_grp_id is not None:
                try:
                    overlay_id_int = int(overlay_grp_id)
                    overlay_name = self.card_db.get_card_name(overlay_id_int)
                    if overlay_name and not overlay_name.startswith("Card #"):
                        card_name = overlay_name
                        if grp_id:
                            self.card_db.cache[grp_id] = card_name
                            self.card_db._save_cache()
                            if hasattr(self.card_db, "log_cache"):
                                self.card_db.log_cache[grp_id] = card_name
                        self.card_db.cache[overlay_id_int] = card_name
                        self.card_db._save_cache()
                except (ValueError, TypeError):
                    pass

        if card_name.startswith("Card #") and card_obj:
            for name_field in ["name", "cardName", "titleId", "displayName", "title", "cardTitle"]:
                if name_field in card_obj:
                    potential_name = card_obj.get(name_field)
                    if (
                        potential_name
                        and isinstance(potential_name, str)
                        and not potential_name.isdigit()
                        and len(potential_name) > 1
                    ):
                        card_name = potential_name
                        if grp_id:
                            self.card_db.cache[grp_id] = card_name
                            self.card_db._save_cache()
                            if hasattr(self.card_db, "log_cache"):
                                self.card_db.log_cache[grp_id] = card_name
                        break
        return card_name

    def _format_target_suffix(
        self,
        target_id: Optional[int],
        target_obj: Dict[str, Any],
        target_objs: List[Dict[str, Any]],
    ) -> str:
        """Return the target suffix used by cast/play log lines."""
        if target_objs:
            target_names = []
            for t_obj in target_objs:
                target_names.append(
                    f"[{self._object_display_label(t_obj, t_obj.get('instanceId'))}]"
                )
            return f" -> {', '.join(target_names)}"
        if target_obj:
            return f" -> [{self._object_display_label(target_obj, target_obj.get('instanceId'))}]"
        if target_id:
            if target_id == self.game_state.player_seat_id:
                return " -> [you]"
            if target_id == self.game_state.opponent_seat_id:
                return " -> [opponent]"
            return f" -> [ID: {target_id}]"
        return ""

    def _track_name_for_card(
        self, card_name: str, type_str: str, card_types: List[str], card_obj: Dict[str, Any]
    ) -> str:
        """Return summary/display track name for a played card."""
        if "CardType_Creature" in card_types:
            power = card_obj.get("power", {}).get("value", "?")
            toughness = card_obj.get("toughness", {}).get("value", "?")
            return f"{card_name} ({type_str} {power}/{toughness})"
        return f"{card_name} ({type_str})"

    def _handle_cast_play_zone_transfer(
        self,
        category: str,
        instance_id: int,
        canonical_instance_id: int,
        card_obj: Dict[str, Any],
        target_id: Optional[int],
        target_obj: Dict[str, Any],
        target_objs: List[Dict[str, Any]],
        deferred_spell_instance_ids: Optional[Set[int]] = None,
    ) -> bool:
        """Handle cast/play/land/resolve zone transfers.

        Returns True when the caller should stop processing the annotation immediately.
        """
        if not card_obj:
            return False

        owner_seat = card_obj.get("ownerSeatId")
        controller_seat = card_obj.get("controllerSeatId")
        determining_seat = controller_seat if controller_seat is not None else owner_seat
        card_name = self._card_name_from_game_object(card_obj)
        player = self._seat_label(determining_seat)
        self._flush_pending_turn_header_for_seat(determining_seat)

        card_types = card_obj.get("cardTypes", [])
        type_str = self._format_card_type(card_types)
        target_str = self._format_target_suffix(target_id, target_obj, target_objs)
        if category in ["CastSpell", "PlaySpell"] and "CardType_Land" not in card_types:
            turn_for_display = (
                self.game_state.last_player_turn_number
                if determining_seat == self.game_state.player_seat_id
                else (
                    self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced
                )
            )
            turn_for_display = self._event_turn_number(determining_seat, turn_for_display)
            track_name = self._track_name_for_card(card_name, type_str, card_types, card_obj)
            deferred_ids = deferred_spell_instance_ids or set()
            if not target_str and (
                int(instance_id) in deferred_ids or int(canonical_instance_id) in deferred_ids
            ):
                self.game_state.pending_spell_roots[int(canonical_instance_id)] = {
                    "seat": determining_seat,
                    "name": card_name,
                }
                return True
            self._print_event(
                self._format_actor_event(
                    ">",
                    determining_seat,
                    f"cast [{track_name}]{target_str}",
                    turn_override=turn_for_display,
                ),
                "cast",
            )
            self._register_stack_item(
                canonical_instance_id,
                seat_id=determining_seat,
                label=f"[{track_name}]{target_str}",
                kind="spell",
                turn_override=turn_for_display,
            )
            self._record_played_card_once(
                instance_id=int(instance_id),
                canonical_instance_id=int(canonical_instance_id),
                seat_id=determining_seat,
                track_name=track_name,
                card_types=card_types,
            )
            return True

        turn_for_display = (
            self.game_state.last_player_turn_number
            if owner_seat == self.game_state.player_seat_id
            else (self.game_state.last_opponent_turn_number or self.game_state.last_turn_announced)
        )
        if (
            category == "PlayLand"
            and determining_seat
            in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
            and self.game_state.active_player
            in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
            and determining_seat != self.game_state.active_player
            and self.game_state.turn_number > 1
        ):
            turn_for_display = self.game_state.turn_number - 1
        turn_for_display = self._event_turn_number(determining_seat, turn_for_display)
        late_marker = ""

        if category == "PlayLand":
            self._print_event(
                self._format_actor_event(
                    "⛰️",
                    determining_seat,
                    f"{late_marker}played [{card_name} ({type_str})]",
                    turn_override=turn_for_display,
                ),
                "land",
            )
        elif "CardType_Creature" in card_types:
            power = card_obj.get("power", {}).get("value", "?")
            toughness = card_obj.get("toughness", {}).get("value", "?")
            self._print_event(
                self._format_actor_event(
                    ">",
                    determining_seat,
                    f"{late_marker}cast [{card_name} ({type_str} {power}/{toughness})]{target_str}",
                    turn_override=turn_for_display,
                ),
                "cast",
            )
        else:
            self._print_event(
                self._format_actor_event(
                    ">",
                    determining_seat,
                    f"{late_marker}cast [{card_name} ({type_str})]{target_str}",
                    turn_override=turn_for_display,
                ),
                "cast",
            )

        track_name = self._track_name_for_card(card_name, type_str, card_types, card_obj)
        type_category = self._get_card_type_category(card_types)
        event = CardEvent(track_name, player.lower(), card_type_category=type_category)
        if determining_seat == self.game_state.player_seat_id:
            self.player_cards.append(event)
            self.session_player_cards_played += 1
        else:
            self.opponent_cards.append(event)
            self.session_opponent_cards_played += 1
        self.game_state.seen_instance_ids.add(instance_id)
        self.game_state.seen_instance_ids.add(canonical_instance_id)
        self.game_state.pending_spell_roots.pop(canonical_instance_id, None)
        return False

    def _known_zone_transfer_category(self, category: Optional[str]) -> bool:
        """Return True when the zone-transfer category is intentionally handled."""
        return category in {
            "CastSpell",
            "PlaySpell",
            "PlayLand",
            "Resolve",
            "Return",
            "Put",
            "Destroy",
            "Exile",
            "Sacrifice",
            "Discard",
            "Countered",
            "Draw",
            "Mill",
        }

    def _process_pre_object_annotation(
        self,
        ann_type: List[Any],
        affected_ids: List[int],
        details: List[Dict[str, Any]],
        affector_id: Optional[int],
        annotation: Dict[str, Any],
        game_objects: List[Dict[str, Any]],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        life_total_seats_in_payload: Optional[Set[int]],
        user_action_instance_ids: Optional[Set[int]],
    ) -> bool:
        """Handle annotations that do not require the primary card lookup."""
        if "AnnotationType_AttackerDeclared" in ann_type:
            self._handle_attacker_declared(affected_ids, game_objects)
            return True
        if "AnnotationType_BlockerDeclared" in ann_type:
            self._handle_blocker_declared(affected_ids, annotation, game_objects)
            return True
        if "AnnotationType_Damage" in ann_type or "AnnotationType_DamageDealt" in ann_type:
            self._handle_damage(affected_ids, annotation, game_objects)
            return True
        if "AnnotationType_AbilityInstanceCreated" in ann_type:
            self._handle_ability_instance_created(
                affected_ids,
                affector_id,
                game_objects_by_id,
                user_action_instance_ids,
            )
            return True
        if "AnnotationType_AbilityInstanceDeleted" in ann_type:
            self._handle_ability_instance_deleted(affected_ids)
            return True
        if "AnnotationType_UserActionTaken" in ann_type:
            self._handle_user_action_taken(affected_ids, details, game_objects_by_id)
            return True
        if "AnnotationType_TappedUntappedPermanent" in ann_type:
            self._handle_tapped_untapped_permanent(affected_ids, annotation, game_objects_by_id)
            return True
        if (
            "AnnotationType_AbilityActivated" in ann_type
            or "AnnotationType_ActivatedAbility" in ann_type
        ):
            self._handle_ability_activated(affected_ids, annotation, game_objects)
            return True
        if "AnnotationType_TriggeredAbility" in ann_type or "AnnotationType_Triggered" in ann_type:
            self._handle_triggered_ability(affected_ids, annotation, game_objects)
            return True
        if "AnnotationType_PhaseOrStepModified" in ann_type:
            return True
        if "AnnotationType_ModifiedLife" in ann_type:
            self._handle_modified_life(
                affected_ids,
                annotation,
                game_objects_by_id,
                life_total_seats_in_payload=life_total_seats_in_payload or set(),
            )
            return True
        return self._is_ignored_diagnostic_annotation(ann_type)

    def _target_objects_for_annotation(
        self,
        target_ids: List[int],
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Resolve unique target objects from annotation target ids."""
        target_objs = []
        seen_targets = set()
        for target_id in target_ids:
            if target_id in seen_targets:
                continue
            seen_targets.add(target_id)
            target_obj = self._lookup_object(target_id, game_objects_by_id)
            if target_obj:
                target_objs.append(target_obj)
        return target_objs

    def _process_zone_transfer_annotation(
        self,
        *,
        category: Optional[str],
        instance_id: int,
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Optional[str],
        zone_dest: Optional[str],
        source_id: Optional[int],
        affector_id: Optional[int],
        target_id: Optional[int],
        target_obj: Optional[Dict[str, Any]],
        target_objs: List[Dict[str, Any]],
        deferred_spell_instance_ids: Optional[Set[int]] = None,
    ) -> bool:
        """Process zone-transfer annotations and return True when handled."""
        canonical_instance_id = self._canonical_instance_id(instance_id) or int(instance_id)

        if (
            category in ["CastSpell", "PlaySpell", "PlayLand", "Resolve"]
            and instance_id not in self.game_state.seen_instance_ids
            and canonical_instance_id not in self.game_state.seen_instance_ids
        ):
            return self._handle_cast_play_zone_transfer(
                str(category),
                int(instance_id),
                int(canonical_instance_id),
                card_obj,
                target_id,
                target_obj,
                target_objs,
                deferred_spell_instance_ids,
            )

        if category in ["Return", "Put"]:
            self._handle_return_or_put_zone_transfer(
                str(category),
                int(canonical_instance_id),
                card_obj,
                annotation,
                game_objects_by_id,
                zones_by_id,
                zone_dest,
                source_id,
                affector_id,
            )
            return True

        if category in ["Destroy", "Exile", "Sacrifice", "Discard"]:
            self._handle_removal_zone_transfer(
                str(category),
                int(instance_id),
                int(canonical_instance_id),
                card_obj,
                annotation,
                game_objects_by_id,
                zones_by_id,
                zone_src,
                zone_dest,
                source_id,
                affector_id,
            )
            return True

        if category == "Countered":
            self._handle_countered_zone_transfer(
                int(instance_id),
                int(canonical_instance_id),
                card_obj,
            )
            return True

        if category == "Draw":
            self._handle_draw_zone_transfer(
                card_obj,
                annotation,
                game_objects_by_id,
                zones_by_id,
                zone_src,
                zone_dest,
            )
            return True

        if category == "Mill":
            self._handle_mill_zone_transfer(
                card_obj,
                annotation,
                game_objects_by_id,
                zones_by_id,
                zone_src,
                zone_dest,
                source_id,
                affector_id,
            )
            return True

        return self._handle_state_based_zone_transfer(
            str(category),
            int(instance_id),
            card_obj,
            annotation,
            game_objects_by_id,
            zones_by_id,
            zone_src,
            zone_dest,
        )
