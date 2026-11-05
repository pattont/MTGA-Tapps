"""Cards revealed without moving: a hand shown to Stinging Vitriol or Duress.

Arena reveals through proxy objects (``GameObjectType_RevealedCard``), one
``RevealedCardCreated`` annotation each, sitting in the zone of the card they
show. The replay already records them; this prints one line per message:
"Opponent: revealed [A], [B] from hand". Your own hand revealed to the
opponent arrives without card names and prints nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .revealed_cards import is_known_card_name


class TrackerRevealsMixin:
    """Console lines for revealed cards."""

    def _note_revealed_cards(
        self, affected_ids: List[Any], game_objects_by_id: Dict[int, Dict[str, Any]]
    ) -> None:
        """Buffer this message's reveals; ``_flush_revealed_cards`` prints them."""
        pending = getattr(self, "_pending_reveals", None)
        if pending is None:
            pending = self._pending_reveals = []
        for raw_id in affected_ids or []:
            try:
                instance_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if instance_id in self.game_state.logged_reveal_ids:
                continue
            obj = self._lookup_object(instance_id, game_objects_by_id)
            grp_id = obj.get("grpId") if obj else None
            name = self.card_db.get_card_name(int(grp_id)) if grp_id else None
            seat = self._normalize_seat_id(obj.get("ownerSeatId")) if obj else None
            if not is_known_card_name(name) or not self._is_tracked_seat(seat):
                continue
            self.game_state.logged_reveal_ids.add(instance_id)
            pending.append((seat, obj.get("zoneId"), name))

    def _flush_revealed_cards(self, zones_by_id: Optional[Dict[int, Dict[str, Any]]]) -> None:
        """Print one line per seat and zone for the reveals buffered this message."""
        pending = getattr(self, "_pending_reveals", None)
        if not pending:
            return
        self._pending_reveals = []
        groups: Dict[tuple, List[str]] = {}
        for seat, zone_id, name in pending:
            groups.setdefault((seat, zone_id), []).append(f"[{name}]")
        event_turn = self.game_state.turn_number if self.game_state.turn_number > 0 else None
        for (seat, zone_id), names in groups.items():
            zone = self._replay_zone_name(zone_id, zones_by_id)
            where = f" from {zone}" if zone in ("hand", "library", "graveyard", "exile") else ""
            self._flush_pending_turn_header_for_seat(seat)
            self._print_event(
                self._format_actor_event(
                    "", seat, f"revealed {', '.join(names)}{where}", turn_override=event_turn
                ),
                "zone",
            )
