"""Core GRE event-processing orchestration for CardTracker."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .annotations import AnnotationDetails
from .tracker_event_abilities import TrackerAbilitiesMixin
from .tracker_event_client_actions import TrackerClientActionsMixin
from .tracker_event_life import TrackerLifeMixin
from .tracker_event_targets import TrackerTargetsMixin
from .tracker_event_turns import TrackerTurnStateMixin


class TrackerEventsMixin(
    TrackerClientActionsMixin,
    TrackerTurnStateMixin,
    TrackerLifeMixin,
    TrackerTargetsMixin,
    TrackerAbilitiesMixin,
):
    """Core event orchestration used by CardTracker."""

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
                        if pending_seat
                        in (self.game_state.player_seat_id, self.game_state.opponent_seat_id)
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
        target_objs = (
            self._target_objects_for_annotation(target_ids, game_objects_by_id)
            if target_ids
            else []
        )

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

        if "AnnotationType_ZoneTransfer" in ann_type and self._known_zone_transfer_category(
            category
        ):
            return

        self._log_unhandled_annotation(annotation, game_objects_by_id=game_objects_by_id)

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
            instance_id = (
                affected_ids[0] if isinstance(affected_ids, list) and affected_ids else None
            )
            canonical_id = (
                self._canonical_instance_id(instance_id) if instance_id is not None else None
            )
            card_obj = (
                self._lookup_object(instance_id, game_objects_by_id)
                if instance_id is not None
                else {}
            )
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
            residual = (
                int(current_size) - int(previous_size) - int(known_delta.get(int(seat_id), 0))
            )
            if residual <= 0:
                continue
            stats = self._seat_stats(seat_id)
            if stats is not None:
                stats["cards_drawn"] += residual
