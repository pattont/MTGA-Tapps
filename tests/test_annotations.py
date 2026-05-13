from mtga_tracker.annotations import AnnotationDetails


def test_annotation_details_extracts_zone_transfer_fields():
    annotation = {
        "details": [
            {"key": "category", "valueString": ["Discard"]},
            {"key": "zone_src", "valueInt32": [1]},
            {"key": "zone_dest", "valueInt32": [2]},
            {"key": "source", "valueInt32": [44]},
            {"key": "orig_id", "valueInt32": [10]},
            {"key": "new_id", "valueInt32": [11]},
        ]
    }

    parsed = AnnotationDetails.from_annotation(annotation)

    assert parsed.category == "Discard"
    assert parsed.zone_src == 1
    assert parsed.zone_dest == 2
    assert parsed.source_id == 44
    assert parsed.orig_instance_id == 10
    assert parsed.new_instance_id == 11


def test_annotation_details_extracts_multiple_targets():
    parsed = AnnotationDetails.from_annotation(
        {"details": [{"key": "targets", "valueInt32": [101, 102]}]}
    )

    assert parsed.target_id == 101
    assert parsed.target_ids == [101, 102]


def test_annotation_details_normalizes_common_typed_fields():
    annotation = {
        "type": ["AnnotationType_TargetSpec"],
        "affectedIds": [555],
        "details": [
            {"key": "damage", "valueInt32": [3]},
            {"key": "type", "valueInt32": [7]},
            {"key": "counter_type", "valueInt32": [1]},
            {"key": "transaction_amount", "valueInt32": [2]},
            {"key": "abilityGrpId", "valueInt32": [9001]},
            {"key": "index", "valueInt32": [0]},
            {"key": "life", "valueInt32": [-2]},
            {"key": "power", "valueInt32": [4]},
            {"key": "toughness", "valueInt32": [-1]},
            {"key": "source_zone", "valueInt32": [31]},
            {"key": "id", "valueInt32": [12]},
            {"key": "color", "valueInt32": [5]},
            {"key": "actionType", "valueInt32": [2]},
            {"key": "topIds", "valueInt32": [101]},
            {"key": "bottomIds", "valueInt32": [102, 103]},
            {"key": "OldIds", "valueInt32": [201]},
            {"key": "NewIds", "valueInt32": [301]},
            {"key": "DesignationType", "valueInt32": [8]},
            {"key": "source_grpid", "valueInt32": [777]},
            {"key": "ControllerId", "valueInt32": [1]},
            {"key": "conjuration_type", "valueString": ["Spellbook"]},
        ],
    }

    parsed = AnnotationDetails.from_annotation(annotation)

    assert parsed.damage == 3
    assert parsed.damage_type == 7
    assert parsed.counter_type == 1
    assert parsed.counter_amount == 2
    assert parsed.ability_grp_id == 9001
    assert parsed.target_index == 0
    assert parsed.life == -2
    assert parsed.power == 4
    assert parsed.toughness == -1
    assert parsed.source_zone == 31
    assert parsed.mana_payment_id == 12
    assert parsed.mana_color == 5
    assert parsed.action_type == 2
    assert parsed.top_ids == [101]
    assert parsed.bottom_ids == [102, 103]
    assert parsed.shuffle_old_ids == [201]
    assert parsed.shuffle_new_ids == [301]
    assert parsed.designation_type == 8
    assert parsed.designation_instance_id == 555
    assert parsed.source_grp_id == 777
    assert parsed.controller_id == 1
    assert parsed.conjuration_type == "Spellbook"
