from mtga_tracker.opening_hand import (
    game_objects_by_instance,
    state_has_opening_hand_zone,
    visible_opening_hand_snapshots,
)


def test_state_has_opening_hand_zone_requires_non_empty_hand():
    assert state_has_opening_hand_zone({"zones": [{"type": "ZoneType_Hand", "objectInstanceIds": [1]}]})
    assert not state_has_opening_hand_zone({"zones": [{"type": "ZoneType_Hand", "objectInstanceIds": []}]})
    assert not state_has_opening_hand_zone({"zones": [{"type": "ZoneType_Library", "objectInstanceIds": [1]}]})


def test_visible_opening_hand_snapshots_ignores_partial_diff():
    data = {
        "zones": [
            {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [1, 2]},
        ],
        "gameObjects": [{"instanceId": 1, "grpId": 100, "cardTypes": ["CardType_Creature"]}],
    }
    objects_by_id = game_objects_by_instance(data["gameObjects"])

    visible_hands, owners = visible_opening_hand_snapshots(
        data,
        objects_by_id,
        object_snapshots={},
        card_name_for_grp_id=lambda grp_id: f"Card{grp_id}",
        type_category_for_card_types=lambda card_types: "Creature" if card_types else "Other",
    )

    assert owners == [1]
    assert visible_hands == []


def test_visible_opening_hand_snapshots_uses_object_snapshot_fallback():
    data = {
        "zones": [
            {"type": "ZoneType_Hand", "ownerSeatId": 1, "objectInstanceIds": [1, 2]},
        ],
        "gameObjects": [{"instanceId": 1, "grpId": 100, "cardTypes": ["CardType_Creature"]}],
    }
    objects_by_id = game_objects_by_instance(data["gameObjects"])

    visible_hands, owners = visible_opening_hand_snapshots(
        data,
        objects_by_id,
        object_snapshots={2: {"instanceId": 2, "grpId": 200, "cardTypes": ["CardType_Land"]}},
        card_name_for_grp_id=lambda grp_id: f"Card{grp_id}",
        type_category_for_card_types=lambda card_types: card_types[0].replace("CardType_", "") if card_types else "Other",
    )

    assert owners == [1]
    assert visible_hands[0]["owner_seat"] == 1
    assert visible_hands[0]["hand_cards"] == ["Card100", "Card200"]
    assert visible_hands[0]["hand_grp_ids"] == [100, 200]
    assert [event.card_type_category for event in visible_hands[0]["hand_events"]] == ["Creature", "Land"]
