"""Combat-related CardTracker mixin methods."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


class TrackerCombatMixin:
    """Combat, blocking, and damage helpers used by CardTracker."""

    def _should_announce_attack(
        self, turn_num: int, instance_id: Optional[int], owner_seat: Optional[int]
    ) -> bool:
        """Return True if this attacker for this turn has not already been announced."""
        if not turn_num or turn_num <= 0 or instance_id is None:
            return True
        key = (int(turn_num), int(instance_id), owner_seat)
        if key in self.game_state.reported_attack_keys:
            return False
        self.game_state.reported_attack_keys.add(key)
        return True

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
        if queue_life_reconciliation and target_seat in (
            self.game_state.player_seat_id,
            self.game_state.opponent_seat_id,
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

        recent_attackers = set(
            self.game_state.recent_attack_sources_by_target.get(int(target_seat), set())
        )
        recent_attackers.discard(None)
        if len(recent_attackers) == 1:
            return next(iter(recent_attackers))

        if self.game_state.active_player in (
            self.game_state.player_seat_id,
            self.game_state.opponent_seat_id,
        ):
            return self.game_state.active_player
        return None

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

    def _previous_attack_context(self) -> tuple[Set[int], Dict[int, Set[int]]]:
        """Return combat context needed to attribute late-arriving life updates."""
        previous_attack_target_ids = {
            info.get("target_id")
            for info in self.game_state.current_combat_attackers.values()
            if isinstance(info, dict)
            and info.get("target_id")
            in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
        }
        previous_attack_sources_by_target: Dict[int, Set[int]] = {}
        for info in self.game_state.current_combat_attackers.values():
            if not isinstance(info, dict):
                continue
            target_id = info.get("target_id")
            owner_seat = info.get("owner_seat")
            if target_id in (
                self.game_state.player_seat_id,
                self.game_state.opponent_seat_id,
            ) and owner_seat in (self.game_state.player_seat_id, self.game_state.opponent_seat_id):
                previous_attack_sources_by_target.setdefault(int(target_id), set()).add(
                    int(owner_seat)
                )
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

            self._record_observed_creature_snapshot(obj)
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
        for message in gre_event.get("greToClientMessages") or []:
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

    def _handle_blockers_request(
        self, blockers: List[Dict[str, Any]], game_objects_by_id: Dict[int, Dict[str, Any]]
    ) -> None:
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
            inferred_turn = (
                self.game_state.turn_number
                if self.game_state.turn_number > 0
                else self._turn_for_seat(blocker_owner_seat)
            )
            for attacker_id in attacker_ids:
                if attacker_id is None:
                    continue
                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_owner_seat = attacker_obj.get("ownerSeatId")
                if attacker_owner_seat in (
                    self.game_state.player_seat_id,
                    self.game_state.opponent_seat_id,
                ):
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
                    attacker_name = (
                        self.game_state.current_combat_attackers.get(attacker_id) or {}
                    ).get("card_name")
                if not attacker_name:
                    attacker_name = f"ID {attacker_id}"

                turn_prefix = self._turn_prefix_for_number(inferred_turn)
                self._print_event(
                    f"\t{turn_prefix}{player} blocking [{attacker_name}] with [{blocker_name} ({blocker_pt})]",
                    "block",
                )

                if attacker_id not in blocker_targets:
                    blocker_targets.append(attacker_id)

    def _display_combat_summary(self):
        """Display a summary of combat after it ends."""
        if (
            not self.game_state.current_combat_attackers
            and not self.game_state.combat_damage_events
        ):
            return

        # Show combat summary if we have significant combat activity
        if self.game_state.combat_damage_events:
            self._print_line("\n" + self._style("⚔️ Combat Summary:", "attack"))
            for event in self.game_state.combat_damage_events:
                if event.get("source"):
                    self._print_event(
                        f"   [{event['source']}] → [{event['target']}] ({event['target_owner']}): {event['amount']} damage",
                        "combat_damage",
                    )
            self._print_line()

    def _handle_attacker_declared(
        self, affected_ids: List[int], game_objects: List[Dict[str, Any]]
    ):
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
                        player = (
                            "You" if owner_seat == self.game_state.player_seat_id else "Opponent"
                        )
                        turn_for_display = (
                            self.game_state.turn_number
                            if owner_seat == self.game_state.active_player
                            and self.game_state.turn_number > 0
                            else self._turn_for_seat(owner_seat)
                        )
                        stats = self._seat_stats(owner_seat)
                        if stats is not None:
                            stats["attacking_creatures"] += 1
                            attack_turn_key = (int(turn_for_display or 0), int(owner_seat))
                            if (
                                turn_for_display
                                and attack_turn_key not in self.game_state.counted_attack_turns
                            ):
                                self.game_state.counted_attack_turns.add(attack_turn_key)
                                stats["attacks"] += 1
                        if not self._should_announce_attack(
                            turn_for_display, instance_id, owner_seat
                        ):
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

    def _handle_blocker_declared(
        self,
        affected_ids: List[int],
        annotation: Dict[str, Any],
        game_objects: List[Dict[str, Any]],
    ):
        """Handle blocker declarations.

        Arena normally emits ONE BlockerDeclared annotation per blocker, so
        a double block arrives as two annotations. Every affected id is
        still treated as a blocker here so a batched annotation can never
        silently drop blockers — the same failure shape as the multi-target
        TargetSpec overwrite (Ram Through) that hid a spell target.
        """
        if not affected_ids:
            return
        for blocker_id in affected_ids:
            if blocker_id is not None:
                self._handle_one_blocker_declared(blocker_id, annotation, game_objects)

    def _handle_one_blocker_declared(
        self,
        blocker_id: int,
        annotation: Dict[str, Any],
        game_objects: List[Dict[str, Any]],
    ):
        """Record and report one blocker from a BlockerDeclared annotation."""

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
            inferred_turn = (
                self.game_state.turn_number
                if self.game_state.turn_number > 0
                else self._turn_for_seat(blocker_owner_seat)
            )
            for attacker_id in attacker_ids:
                if attacker_id is None:
                    continue
                attacker_obj = self._lookup_object(attacker_id, game_objects_by_id)
                attacker_owner_seat = attacker_obj.get("ownerSeatId")
                if attacker_owner_seat in (
                    self.game_state.player_seat_id,
                    self.game_state.opponent_seat_id,
                ):
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

                attacker_name = (
                    attackers_by_id.get(attacker_id) if attacker_id is not None else None
                )
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

    def _handle_damage(
        self,
        affected_ids: List[int],
        annotation: Dict[str, Any],
        game_objects: List[Dict[str, Any]],
    ):
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
                is_combat_damage = (
                    detail.get("valueBool", [False])[0] or detail.get("valueInt32", [0])[0] == 1
                )

        if source_id is None:
            source_id = annotation.get("affectorId")
        source_obj = (
            self._lookup_object(source_id, game_objects_by_id) if source_id is not None else {}
        )
        canonical_source_id = (
            self._canonical_instance_id(source_id) if source_id is not None else None
        )
        source_card_types = source_obj.get("cardTypes") or []

        # Spells can deal damage during combat, but that is not combat damage.
        if self.game_state.combat_phase_active and not is_combat_damage:
            if source_id is None:
                is_combat_damage = True
            elif (
                canonical_source_id in self.game_state.current_combat_attackers
                or source_id in self.game_state.current_combat_attackers
            ):
                is_combat_damage = True
            elif (
                canonical_source_id in self.game_state.current_combat_blockers
                or source_id in self.game_state.current_combat_blockers
            ):
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
                if instance_id in (
                    self.game_state.player_seat_id,
                    self.game_state.opponent_seat_id,
                ):
                    self._record_damage_dealt(int(damage_amount), source_seat, instance_id)
                    continue
                for obj in game_objects:
                    if obj.get("instanceId") == instance_id:
                        grp_id = obj.get("grpId")
                        owner_seat = obj.get("ownerSeatId")
                        self._flush_pending_turn_header_for_seat(owner_seat)
                        card_name = self.card_db.get_card_name(grp_id) if grp_id else "Unknown"
                        target_label = self._object_display_label(obj, instance_id)

                        owner = (
                            "your" if owner_seat == self.game_state.player_seat_id else "opponent's"
                        )

                        # Find source if available
                        source_name = None
                        if source_id:
                            for candidate_source_obj in game_objects:
                                if candidate_source_obj.get("instanceId") == source_id:
                                    source_name = self._object_display_label(
                                        candidate_source_obj, source_id
                                    )
                                    source_seat = candidate_source_obj.get("controllerSeatId")
                                    if source_seat is None:
                                        source_seat = candidate_source_obj.get("ownerSeatId")
                                    break
                        self._record_damage_dealt(
                            int(damage_amount),
                            source_seat,
                            (
                                owner_seat
                                if owner_seat
                                in (
                                    self.game_state.player_seat_id,
                                    self.game_state.opponent_seat_id,
                                )
                                else None
                            ),
                            queue_life_reconciliation=False,
                        )

                        if is_combat_damage:
                            # Store for combat summary
                            self.game_state.combat_damage_events.append(
                                {
                                    "source": source_name,
                                    "target": target_label,
                                    "target_owner": owner,
                                    "amount": damage_amount,
                                }
                            )

                            event_seat = (
                                source_seat
                                if source_seat
                                in (
                                    self.game_state.player_seat_id,
                                    self.game_state.opponent_seat_id,
                                )
                                else owner_seat
                            )
                            turn_prefix = self._turn_prefix_for_number(
                                self._event_turn_number(event_seat)
                            )
                            if source_name:
                                self._print_event(
                                    f"\t{turn_prefix}Combat: [{source_name}] dealt {damage_amount} damage to [{target_label}] ({owner})",
                                    "combat_damage",
                                )
                            else:
                                self._print_event(
                                    f"\t{turn_prefix}Combat: [{target_label}] ({owner}) took {damage_amount} damage",
                                    "combat_damage",
                                )
                        else:
                            event_seat = (
                                source_seat
                                if source_seat
                                in (
                                    self.game_state.player_seat_id,
                                    self.game_state.opponent_seat_id,
                                )
                                else owner_seat
                            )
                            turn_prefix = self._turn_prefix_for_number(
                                self._event_turn_number(event_seat)
                            )
                            self._print_event(
                                f"{turn_prefix}[{card_name}] ({owner}) took {damage_amount} damage",
                                "damage",
                            )
                        break
