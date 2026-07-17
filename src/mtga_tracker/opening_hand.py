"""Opening-hand payload helpers."""

from typing import Any, Callable, Dict, List, Optional

from .state import CardEvent


def game_objects_by_instance(game_objects: Any) -> Optional[Dict[int, Dict[str, Any]]]:
    """Index game objects by instance id, or return None for invalid payloads."""
    if not isinstance(game_objects, list):
        return None
    return {
        obj.get("instanceId"): obj
        for obj in game_objects
        if isinstance(obj, dict) and obj.get("instanceId") is not None
    }


def state_has_opening_hand_zone(data: Dict[str, Any]) -> bool:
    """Return True when a state payload includes a non-empty hand zone."""
    zones = data.get("zones", [])
    if not isinstance(zones, list):
        return False
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        if zone.get("type") == "ZoneType_Hand" and zone.get("objectInstanceIds"):
            return True
    return False


def visible_opening_hand_snapshots(
    data: Dict[str, Any],
    objects_by_id: Dict[int, Dict[str, Any]],
    *,
    object_snapshots: Dict[int, Dict[str, Any]],
    card_name_for_grp_id: Callable[[int], str],
    type_category_for_card_types: Callable[[List[str]], str],
) -> tuple[List[Dict[str, Any]], List[int]]:
    """Return fully visible hand snapshots and their owner seats."""
    visible_hands: List[Dict[str, Any]] = []
    hand_zone_owners: List[int] = []

    zones = data.get("zones", [])
    if not isinstance(zones, list) or not zones:
        return visible_hands, hand_zone_owners
    for zone in zones:
        if not isinstance(zone, dict) or zone.get("type") != "ZoneType_Hand":
            continue
        owner_seat = zone.get("ownerSeatId")
        obj_ids = zone.get("objectInstanceIds", [])
        if owner_seat is None or not obj_ids:
            continue
        hand_zone_owners.append(owner_seat)

        hand_cards: List[str] = []
        hand_grp_ids: List[int] = []
        hand_instance_ids: List[int] = []
        hand_events: List[CardEvent] = []
        for obj_id in obj_ids:
            obj = objects_by_id.get(obj_id) or object_snapshots.get(obj_id) or {}
            grp_id = obj.get("grpId")
            if grp_id:
                grp_id = int(grp_id)
                card_name = card_name_for_grp_id(grp_id)
                card_types = obj.get("cardTypes", []) if isinstance(obj, dict) else []
                type_category = type_category_for_card_types(card_types)
                hand_cards.append(card_name)
                hand_grp_ids.append(grp_id)
                hand_instance_ids.append(int(obj_id))
                hand_events.append(CardEvent(card_name, "player", card_type_category=type_category))

        if not hand_grp_ids:
            continue
        # Partial gameState diffs can omit most hand objects; don't finalize from incomplete snapshots.
        if len(hand_grp_ids) < len(obj_ids):
            continue

        visible_hands.append(
            {
                "owner_seat": owner_seat,
                "hand_cards": hand_cards,
                "hand_grp_ids": hand_grp_ids,
                "hand_instance_ids": hand_instance_ids,
                "hand_events": hand_events,
            }
        )
    return visible_hands, hand_zone_owners
