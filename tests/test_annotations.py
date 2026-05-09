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

