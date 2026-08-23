"""Ability event helpers for CardTracker."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


class TrackerAbilitiesMixin:
    """Focused event helpers used by TrackerEventsMixin."""

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
            self.game_state.ability_instance_action_texts[ability_instance_id] = (
                normalized_ability_text
            )
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
        source_obj = (
            self._lookup_object(source_instance_id, game_objects_by_id)
            if source_instance_id is not None
            else {}
        )
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
        target_objs = (
            self._target_objects_for_annotation(target_ids, game_objects_by_id)
            if target_ids
            else []
        )
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

    def _handle_ability_activated(
        self,
        affected_ids: List[int],
        annotation: Dict[str, Any],
        game_objects: List[Dict[str, Any]],
    ):
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
                                t_name = (
                                    self.card_db.get_card_name(t_grp_id)
                                    if t_grp_id
                                    else f"[{self._register_unresolved_target(t_id)}]"
                                )
                                t_owner_seat = obj.get("ownerSeatId")
                                t_owner = (
                                    "your"
                                    if t_owner_seat == self.game_state.player_seat_id
                                    else "opponent's"
                                )
                                target_names.append(f"{t_name} ({t_owner})")
                                break
                        else:
                            target_names.append(f"[{self._register_unresolved_target(t_id)}]")

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
                        turn_override=active_turn_override
                        or self._ability_turn_override(owner_seat),
                    ),
                    "ability",
                )

    def _handle_triggered_ability(
        self,
        affected_ids: List[int],
        annotation: Dict[str, Any],
        game_objects: List[Dict[str, Any]],
    ):
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

    def _should_log_ability_text(
        self, source_obj: Dict[str, Any], ability_text: Optional[str]
    ) -> bool:
        """Filter out noisy abilities such as basic land mana taps."""
        normalized = self._normalize_ability_text(ability_text)
        if not normalized:
            return False
        if self._is_mana_ability_text(normalized):
            return False
        return True
