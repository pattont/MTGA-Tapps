"""Replay capture, part 2: facts the console never prints.

Taps, summoning sickness, P/T changes, opening hands, mulligans, hidden draws, counters, tokens,
attachments, shuffles, reveals and the combat facts (attack, block, damage).
Each helper is called by the tracker mixin that already handles the payload
(no second pass over a message). Types and the row buffer live in
``replay_capture``; contract: docs/REPLAY_FORMAT.md section 1.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .replay_capture import (
    ReplayCaptureMixin,
    ReplayFact,
    counter_type_name,
    replay_safe,
    stat_value,
)

#: Annotations the console never prints; ``_process_replay_annotation`` owns them.
_REPLAY_ANNOTATIONS = frozenset(
    (
        "AnnotationType_CounterAdded",
        "AnnotationType_CounterRemoved",
        "AnnotationType_AttachmentCreated",
        "AnnotationType_TokenDeleted",
        "AnnotationType_Shuffle",
        "AnnotationType_RevealedCardCreated",
        "AnnotationType_RevealedCardDeleted",
        "AnnotationType_PowerToughnessModCreated",
        "AnnotationType_PlayerSubmittedTargets",
        "AnnotationType_NewTurnStarted",
    )
)


class ReplayEventsMixin(ReplayCaptureMixin):
    """Silent-row producers and combat fact builders."""

    # -- objects ----------------------------------------------------------
    @replay_safe()
    def _replay_observe_object(self, instance_id: int, obj: Dict[str, Any]) -> None:
        """Queue one full gameObject from the snapshot loop (no copy).

        The diff runs when the message is done, after its ObjectIdChanged
        annotations, so a land entering tapped is keyed by its root id."""
        self._replay_state().observed.append((instance_id, obj))

    def _replay_diff_object(self, state, instance_id: int, obj: Dict[str, Any]) -> None:
        """Tap and P/T changes of one observed gameObject."""
        zone_id = obj.get("zoneId")
        battlefield = self.game_state.battlefield_zone_id or 28
        root = self._replay_root(instance_id)
        if root is None:
            return
        state.latest[root] = instance_id
        if zone_id != battlefield:
            if zone_id is not None:
                state.tapped.discard(root)
                state.pt.pop(root, None)
                state.sick.discard(root)
            return
        seat = self._normalize_seat_id(obj.get("controllerSeatId") or obj.get("ownerSeatId"))
        tapped = bool(obj.get("isTapped"))
        if tapped != (root in state.tapped):
            if tapped:
                state.tapped.add(root)
                state.pending_taps.setdefault(seat, []).append(root)
            else:
                state.tapped.discard(root)
                state.pending_untaps.setdefault(seat, []).append(root)
        # Arena sets this only on creatures that can't attack or use {T} yet;
        # it already accounts for haste, printed or granted.
        sick = bool(obj.get("hasSummoningSickness"))
        if sick != (root in state.sick):
            if sick:
                state.sick.add(root)
                state.pending_sick.setdefault(seat, []).append(root)
            else:
                state.sick.discard(root)
                state.pending_unsick.setdefault(seat, []).append(root)
        if "power" in obj or "toughness" in obj:
            power = stat_value(obj, "power")
            toughness = stat_value(obj, "toughness")
            if power is None or toughness is None:
                return
            value = (power, toughness)
            previous = state.pt.get(root)
            state.pt[root] = value
            if previous is not None and previous != value:
                state.pending_pt[root] = value

    @replay_safe()
    def _replay_flush_object_changes(self) -> None:
        """Write the message's batched tap/untap, summoning sickness and P/T rows."""
        state = getattr(self, "_replay_capture_state", None)
        if state is None:
            return
        if state.observed:
            observed = state.observed
            state.observed = []
            for instance_id, obj in observed:
                self._replay_diff_object(state, instance_id, obj)
        if not (
            state.pending_taps
            or state.pending_untaps
            or state.pending_pt
            or state.pending_sick
            or state.pending_unsick
        ):
            return
        capturing = self._replay_capturing() and (self.game_state.turn_number or 0) >= 1
        if capturing:
            for kind, pending in (
                ("untap", state.pending_untaps),
                ("tap", state.pending_taps),
                ("unsick", state.pending_unsick),
                ("sick", state.pending_sick),
            ):
                for seat, ids in pending.items():
                    self._record_silent_event(
                        ReplayFact(
                            kind,
                            seat_id=seat,
                            controller_seat=seat,
                            amount=len(ids),
                            payload={"object_ids": ids},
                        )
                    )
            for root, (power, toughness) in state.pending_pt.items():
                self._record_silent_event(
                    ReplayFact(
                        "pt", object_id=root, payload={"power": power, "toughness": toughness}
                    )
                )
        state.pending_taps = {}
        state.pending_untaps = {}
        state.pending_pt = {}
        state.pending_sick = {}
        state.pending_unsick = {}

    # -- opening hand / mulligans ------------------------------------------
    @replay_safe()
    def _replay_record_hand_ids(self, seat_id: int, ids: List[int]) -> None:
        self._replay_state().hand_ids[int(seat_id)] = ids

    @replay_safe()
    def _replay_emit_opening_hands(self, data: Dict[str, Any]) -> None:
        """At the first turn, one hidden-or-named draw per card in each hand."""
        if not self._replay_capturing():
            return
        state = self._replay_state()
        if state.opening_emitted:
            return
        state.opening_emitted = True
        hands = dict(state.hand_ids)
        for zone in data.get("zones") or []:
            if isinstance(zone, dict) and zone.get("type") == "ZoneType_Hand":
                seat = self._normalize_seat_id(zone.get("ownerSeatId"))
                ids = zone.get("objectInstanceIds")
                if seat in (1, 2) and isinstance(ids, list):
                    hands[int(seat)] = ids
        player = self.game_state.player_seat_id
        for seat in (player, self.game_state.opponent_seat_id):
            if seat not in (1, 2):
                continue
            for instance_id in hands.get(int(seat), []):
                payload: Dict[str, Any] = {"reason": "draw", "opening": True}
                grp_id = None
                if seat == player:
                    obj = self.game_state.object_snapshots.get(instance_id) or {}
                    grp_id = self._replay_card_payload(obj, payload)
                root = self._replay_root(instance_id)
                self._record_silent_event(
                    ReplayFact(
                        "move",
                        object_id=root,
                        arena_id=grp_id,
                        seat_id=int(seat),
                        controller_seat=int(seat),
                        zone_from="library",
                        zone_to="hand",
                        payload=payload,
                    )
                )
                if root is not None:
                    state.zone_of[root] = "hand"

    @replay_safe()
    def _replay_observe_mulligan(self, seat_id: int, count: int) -> None:
        if not self._replay_capturing():
            return
        state = self._replay_state()
        previous = state.mulligans.get(int(seat_id), 0)
        if count <= previous:
            return
        state.mulligans[int(seat_id)] = count
        for step in range(previous + 1, count + 1):
            to_size = max(0, 7 - step)
            self._record_silent_event(
                ReplayFact(
                    "mulligan",
                    seat_id=int(seat_id),
                    amount=to_size,
                    payload={"from_size": to_size + 1, "to_size": to_size},
                )
            )

    @replay_safe()
    def _replay_hidden_hand_draws(
        self, seat_id: int, residual: int, previous_ids: Optional[List[int]]
    ) -> None:
        """Hand grew without a Draw annotation: hidden library -> hand moves."""
        if residual <= 0 or not self._replay_capturing():
            return
        state = self._replay_state()
        current = state.hand_ids.get(int(seat_id)) or []
        known = set(previous_ids or [])
        emitted = 0
        for instance_id in current:
            if emitted >= residual:
                break
            if instance_id in known:
                continue
            root = self._replay_root(instance_id)
            if root in state.hand_arrivals:
                continue
            payload: Dict[str, Any] = {"reason": "draw"}
            grp_id = None
            if seat_id == self.game_state.player_seat_id:
                grp_id = self._replay_card_payload(
                    self.game_state.object_snapshots.get(instance_id) or {}, payload
                )
            self._record_silent_event(
                ReplayFact(
                    "move",
                    object_id=root,
                    arena_id=grp_id,
                    seat_id=int(seat_id),
                    controller_seat=int(seat_id),
                    zone_from="library",
                    zone_to="hand",
                    payload=payload,
                )
            )
            if root is not None:
                state.zone_of[root] = "hand"
            emitted += 1

    # -- annotations with no console line -----------------------------------
    def _process_replay_annotation(
        self,
        ann_type: List[Any],
        annotation: Dict[str, Any],
        affected_ids: List[Any],
        affector_id: Optional[int],
        details: Any,
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> bool:
        """Capture annotations the console never prints. True when handled.

        Handled means "owned by replay": the annotation never reaches the
        printed-event path or the diagnostics log, even if capturing it fails.
        """
        if not any(item in _REPLAY_ANNOTATIONS for item in ann_type):
            return False
        self._capture_replay_annotation(
            ann_type, affected_ids, affector_id, details, game_objects_by_id
        )
        return True

    @replay_safe()
    def _capture_replay_annotation(
        self,
        ann_type: List[Any],
        affected_ids: List[Any],
        affector_id: Optional[int],
        details: Any,
        game_objects_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        if "AnnotationType_CounterAdded" in ann_type or "AnnotationType_CounterRemoved" in ann_type:
            sign = 1 if "AnnotationType_CounterAdded" in ann_type else -1
            self._replay_counter(affected_ids, details, sign)
        elif "AnnotationType_AttachmentCreated" in ann_type:
            if affector_id is not None and affected_ids and self._replay_capturing():
                aura = self._lookup_object(affector_id, game_objects_by_id)
                seat = self._normalize_seat_id(
                    aura.get("controllerSeatId") or aura.get("ownerSeatId")
                )
                self._record_silent_event(
                    ReplayFact(
                        "attach",
                        object_id=self._replay_root(affector_id),
                        target_object_id=self._replay_root(affected_ids[0]),
                        seat_id=seat,
                        controller_seat=seat,
                    )
                )
        elif "AnnotationType_TokenDeleted" in ann_type:
            self._replay_token_ceased(affected_ids, game_objects_by_id)
        elif "AnnotationType_Shuffle" in ann_type:
            seat = self._normalize_seat_id(affected_ids[0]) if affected_ids else None
            # Pre-game (mulligan) shuffles are already folded into the opening hands.
            if (
                seat in (1, 2)
                and (self.game_state.turn_number or 0) >= 1
                and self._replay_capturing()
            ):
                self._record_silent_event(ReplayFact("shuffle", seat_id=seat))
        elif "AnnotationType_RevealedCardCreated" in ann_type:
            self._replay_reveal(affected_ids, game_objects_by_id)

    @replay_safe()
    def _replay_counter(self, affected_ids: List[Any], details: Any, sign: int) -> None:
        if not affected_ids or not self._replay_capturing():
            return
        counter_type = None
        amount = None
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict):
                continue
            values = detail.get("valueInt32") or []
            value = values[0] if isinstance(values, list) and values else None
            if detail.get("key") == "counter_type":
                counter_type = value
            elif detail.get("key") == "transaction_amount":
                amount = value
        if not isinstance(amount, int):
            amount = 1
        type_name = counter_type_name(counter_type)
        state = self._replay_state()
        for affected in affected_ids:
            root = self._replay_root(affected)
            if root is None or root in (1, 2):
                continue
            key = (root, type_name)
            total = max(0, state.counters.get(key, 0) + sign * amount)
            state.counters[key] = total
            self._record_silent_event(
                ReplayFact(
                    "counter",
                    object_id=root,
                    amount=sign * amount,
                    payload={"type": type_name, "total": total},
                )
            )

    @replay_safe()
    def _replay_token_created(
        self, affected_ids: List[Any], game_objects_by_id: Dict[int, Dict[str, Any]]
    ) -> None:
        if not self._replay_capturing():
            return
        state = self._replay_state()
        for raw_id in affected_ids or []:
            obj = self._lookup_object(raw_id, game_objects_by_id)
            root = self._replay_root(raw_id)
            if root is None or state.zone_of.get(root) == "battlefield":
                continue
            payload: Dict[str, Any] = {"reason": "token_create", "token": True}
            grp_id = self._replay_card_payload(obj, payload)
            power = stat_value(obj, "power")
            toughness = stat_value(obj, "toughness")
            if power is not None and toughness is not None:
                payload["power"] = power
                payload["toughness"] = toughness
            controller = self._normalize_seat_id(
                obj.get("controllerSeatId") or obj.get("ownerSeatId")
            )
            zone_to = self._replay_zone_name(obj.get("zoneId")) or "battlefield"
            self._record_silent_event(
                ReplayFact(
                    "move",
                    object_id=root,
                    arena_id=grp_id,
                    seat_id=self._normalize_seat_id(obj.get("ownerSeatId")) or controller,
                    controller_seat=controller,
                    zone_from="limbo",
                    zone_to=zone_to,
                    payload=payload,
                )
            )
            state.zone_of[root] = zone_to

    @replay_safe()
    def _replay_token_ceased(
        self, affected_ids: List[Any], game_objects_by_id: Dict[int, Dict[str, Any]]
    ) -> None:
        if not self._replay_capturing():
            return
        state = self._replay_state()
        for raw_id in affected_ids or []:
            root = self._replay_root(raw_id)
            if root is None or state.zone_of.get(root) == "limbo":
                continue
            obj = self._lookup_object(raw_id, game_objects_by_id)
            payload: Dict[str, Any] = {"reason": "token_cease", "token": True}
            grp_id = self._replay_card_payload(obj, payload)
            seat = self._normalize_seat_id(obj.get("ownerSeatId"))
            self._record_silent_event(
                ReplayFact(
                    "move",
                    object_id=root,
                    arena_id=grp_id,
                    seat_id=seat,
                    controller_seat=self._normalize_seat_id(obj.get("controllerSeatId")) or seat,
                    zone_from=state.zone_of.get(root, "battlefield"),
                    zone_to="limbo",
                    payload=payload,
                )
            )
            state.zone_of[root] = "limbo"
            state.tapped.discard(root)
            state.pt.pop(root, None)

    @replay_safe()
    def _replay_reveal(
        self, affected_ids: List[Any], game_objects_by_id: Dict[int, Dict[str, Any]]
    ) -> None:
        if not self._replay_capturing():
            return
        for raw_id in affected_ids or []:
            obj = self._lookup_object(raw_id, game_objects_by_id)
            payload: Dict[str, Any] = {}
            grp_id = self._replay_card_payload(obj, payload)
            payload.pop("token", None)
            if grp_id is None:
                continue
            seat = self._normalize_seat_id(obj.get("ownerSeatId"))
            self._record_silent_event(
                ReplayFact(
                    "reveal",
                    object_id=self._replay_root(raw_id),
                    arena_id=grp_id,
                    seat_id=seat,
                    controller_seat=seat,
                    payload=payload or None,
                )
            )

    # -- life -------------------------------------------------------------
    @replay_safe()
    def _replay_life_fact(
        self, seat_id: Any, diff: int, source_object_id: Optional[int]
    ) -> Optional[ReplayFact]:
        """``life`` fact for a printed life-change line."""
        if not self._replay_capturing():
            return None
        source_root = self._replay_root(source_object_id)
        return ReplayFact(
            "life",
            seat_id=self._normalize_seat_id(seat_id),
            amount=int(diff),
            payload={"source_object_id": source_root} if source_root is not None else None,
        )

    # -- combat -----------------------------------------------------------
    @replay_safe()
    def _replay_attack_fact(
        self, instance_id: Any, owner_seat: Any, target_id: Any
    ) -> Optional[ReplayFact]:
        if not self._replay_capturing():
            return None
        payload: Dict[str, Any] = {"object_ids": [self._replay_root(instance_id)]}
        target_object = None
        if target_id in (1, 2):
            payload["target_seat"] = int(target_id)
        elif target_id is not None:
            target_object = self._replay_root(target_id)
            payload["target_object_id"] = target_object
        seat = self._normalize_seat_id(owner_seat)
        return ReplayFact(
            "attack",
            object_id=self._replay_root(instance_id),
            target_object_id=target_object,
            seat_id=seat,
            controller_seat=seat,
            payload=payload,
        )

    @replay_safe()
    def _replay_block_fact(
        self, blocker_id: Any, attacker_id: Any, blocker_seat: Any
    ) -> Optional[ReplayFact]:
        if not self._replay_capturing():
            return None
        blocker = self._replay_root(blocker_id)
        attacker = self._replay_root(attacker_id)
        blocks = self._replay_state().blocks
        key = (self.game_state.turn_number, blocker, attacker)
        if key in blocks:
            return None
        blocks.add(key)
        seat = self._normalize_seat_id(blocker_seat)
        return ReplayFact(
            "block",
            object_id=blocker,
            target_object_id=attacker,
            seat_id=seat,
            controller_seat=seat,
            payload={"pairs": [{"blocker": blocker, "attacker": attacker}]},
        )

    @replay_safe()
    def _replay_observe_block_states(self, game_objects: List[Dict[str, Any]]) -> None:
        """Blocks Arena reports only as ``blockState``/``blockInfo`` on objects."""
        if not self._replay_capturing():
            return
        state = self._replay_state()
        by_seat: Dict[Optional[int], List[Dict[str, int]]] = {}
        for obj in game_objects:
            if not isinstance(obj, dict):
                continue
            block_state = str(obj.get("blockState") or "")
            if block_state not in ("BlockState_Declared", "BlockState_Blocking"):
                continue
            info = obj.get("blockInfo") or {}
            attacker_ids = info.get("attackerIds") if isinstance(info, dict) else None
            if not isinstance(attacker_ids, list) or not attacker_ids:
                # Without blockInfo the pair is unknown; BlockerDeclared covers it.
                continue
            blocker = self._replay_root(obj.get("instanceId"))
            for attacker_id in attacker_ids:
                attacker = self._replay_root(attacker_id)
                key = (self.game_state.turn_number, blocker, attacker)
                if key in state.blocks:
                    continue
                state.blocks.add(key)
                seat = self._normalize_seat_id(
                    obj.get("controllerSeatId") or obj.get("ownerSeatId")
                )
                by_seat.setdefault(seat, []).append({"blocker": blocker, "attacker": attacker})
        for seat, pairs in by_seat.items():
            self._record_silent_event(
                ReplayFact(
                    "block",
                    object_id=pairs[0]["blocker"],
                    target_object_id=pairs[0]["attacker"],
                    seat_id=seat,
                    controller_seat=seat,
                    payload={"pairs": pairs},
                )
            )

    @replay_safe()
    def _replay_damage_fact(
        self,
        source_id: Any,
        target_object_id: Any,
        amount: Any,
        *,
        combat: bool,
        target_seat: Optional[int] = None,
    ) -> Optional[ReplayFact]:
        if not self._replay_capturing():
            return None
        payload: Dict[str, Any] = {"combat": bool(combat)}
        if target_seat is not None:
            payload["target_seat"] = int(target_seat)
        source_obj = self._lookup_object(source_id) if source_id is not None else {}
        source_seat = self._normalize_seat_id(
            source_obj.get("controllerSeatId") or source_obj.get("ownerSeatId")
        )
        try:
            damage = int(amount)
        except (TypeError, ValueError):
            damage = None
        return ReplayFact(
            "damage",
            object_id=self._replay_root(source_id),
            target_object_id=self._replay_root(target_object_id),
            arena_id=source_obj.get("grpId") if isinstance(source_obj.get("grpId"), int) else None,
            controller_seat=source_seat,
            seat_id=target_seat if target_seat is not None else source_seat,
            amount=damage,
            payload=payload,
        )
