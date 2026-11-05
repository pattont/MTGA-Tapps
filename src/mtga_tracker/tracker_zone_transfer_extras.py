"""Zone transfers with less common Arena categories.

Surveil, Warp, copied spells, manifests and cards put from a library into a
graveyard all move cards both players can see (or, for a face-down manifest,
know about), but the main dispatcher had no handler for them, so the live log
printed nothing and the replay kept them as silent rows only.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .revealed_cards import is_known_card_name


class TrackerZoneTransferExtrasMixin:
    """Console lines for the less common zone-transfer categories."""

    def _handle_extra_zone_transfer(
        self,
        category: Optional[str],
        card_obj: Dict[str, Any],
        annotation: Dict[str, Any],
        game_objects_by_id: Dict[int, Dict[str, Any]],
        zones_by_id: Optional[Dict[int, Dict[str, Any]]],
        zone_src: Any,
        zone_dest: Any,
        affector_id: Optional[int],
    ) -> bool:
        """Print one line for a recognized move; return False to fall through."""
        zone_from = self._replay_zone_name(zone_src, zones_by_id)
        zone_to = self._replay_zone_name(zone_dest, zones_by_id)
        grp_id = card_obj.get("grpId") if isinstance(card_obj, dict) else None
        card_name = self.card_db.get_card_name(grp_id) if grp_id else None
        known = is_known_card_name(card_name)

        if category == "Surveil" and zone_to == "graveyard":
            text = f"surveilled [{card_name}] into graveyard" if known else "surveilled a card"
        elif category == "Put" and zone_from == "library" and zone_to == "graveyard":
            # Manifest dread's other card, "put the rest into your graveyard", ...
            # A Put elsewhere (a mulligan's bottomed card) stays with its own handler.
            text = (
                f"[{card_name}] was put into graveyard from library"
                if known
                else "a card was put into graveyard from library"
            )
        elif category == "Warp" and zone_to == "exile":
            # A warped permanent is exiled at the next end step.
            text = f"[{card_name}] was exiled (warp)" if known else "a card was exiled (warp)"
        elif category == "ManifestLike" and zone_to == "battlefield":
            # The opponent's manifested card is face down: Arena names no card.
            text = f"manifested [{card_name}]" if known else "manifested a face-down card"
        elif category == "Copy" and zone_to == "stack":
            source_name = self._extra_transfer_source_name(affector_id, game_objects_by_id)
            spell = f"[{card_name}]" if known else "a spell"
            text = f"[{source_name}] copied {spell}" if source_name else f"copied {spell}"
        else:
            return False

        seat = self._resolve_zone_transfer_seat(
            card_obj=card_obj,
            annotation=annotation,
            game_objects_by_id=game_objects_by_id,
            zone_src=zone_src,
            zone_dest=zone_dest,
            zones_by_id=zones_by_id,
        )
        if category == "Copy":
            # The copy belongs to whoever controls the copying effect.
            seat = card_obj.get("controllerSeatId") or seat
        if not self._is_tracked_seat(seat):
            return True
        self._flush_pending_turn_header_for_seat(seat)
        event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
        self._print_event(
            self._format_actor_event("", seat, text, turn_override=event_turn),
            "zone",
        )
        return True

    def _extra_transfer_source_name(
        self, affector_id: Optional[int], game_objects_by_id: Dict[int, Dict[str, Any]]
    ) -> Optional[str]:
        """Name the card behind an affector: a card itself, or an ability's source."""
        if affector_id is None:
            return None
        source = self._lookup_object(int(affector_id), game_objects_by_id)
        if not source:
            return None
        if source.get("type") == "GameObjectType_Ability":
            grp_id = source.get("objectSourceGrpId")
        else:
            grp_id = source.get("grpId")
        name = self.card_db.get_card_name(int(grp_id)) if grp_id else None
        return name if is_known_card_name(name) else None
