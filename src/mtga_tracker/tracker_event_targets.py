"""Target capture and actor inference helpers for CardTracker events."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class TrackerTargetsMixin:
    """Focused event helpers used by TrackerEventsMixin."""

    def _resolve_target_label(
        self, target_id: Optional[int], game_objects_by_id: Dict[int, Dict[str, Any]]
    ) -> Optional[str]:
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
