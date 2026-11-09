"""`_find_nested`: the first non-null value of a key in pre-order, answered
from one index per message instead of one recursive walk per key."""

from test_tracker_combat_winner import make_tracker


def _reference(data, key):
    """The recursive search this indexed lookup replaced."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            result = _reference(value, key)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _reference(item, key)
            if result is not None:
                return result
    return None


def test_find_nested_matches_the_recursive_search():
    tracker = make_tracker()
    data = {
        "greToClientEvent": {
            "greToClientMessages": [
                {"type": "GREMessageType_GameStateMessage", "gameStateMessage": {"gameInfo": None}},
                {
                    "gameStateMessage": {
                        "gameInfo": {"stage": "GameStage_GameOver"},
                        "players": [{"systemSeatNumber": 1, "status": "PendingLoss"}],
                        "annotations": [
                            {"type": ["AnnotationType_LossOfGame"], "affectedIds": [2]}
                        ],
                    }
                },
            ]
        },
        "timestamp": "1",
        "winningTeamId": 2,
    }
    for key in ("gameInfo", "players", "winningTeamId", "annotations", "status", "missing", "type"):
        assert tracker._find_nested(data, key) == _reference(data, key), key


def test_find_nested_null_stops_the_search_inside_that_dict():
    # The recursive search returned at a dict holding the key as null and
    # never looked below it; siblings after it were still searched.
    tracker = make_tracker()
    data = {
        "outer": {"gameInfo": None, "deeper": {"gameInfo": {"stage": "hidden"}}},
        "later": {"gameInfo": {"stage": "seen"}},
    }

    assert (
        tracker._find_nested(data, "gameInfo") == _reference(data, "gameInfo") == {"stage": "seen"}
    )
    top = {"gameInfo": None, "child": {"gameInfo": {"stage": "hidden"}}}
    assert tracker._find_nested(top, "gameInfo") is None
    assert _reference(top, "gameInfo") is None


def test_find_nested_matches_the_recursive_search_on_random_structures():
    import random

    tracker = make_tracker()
    keys = ["a", "b", "c", "gameInfo", "players"]

    def build(rng, depth):
        if depth == 0 or rng.random() < 0.3:
            return rng.choice([None, 1, 2, "x", None])
        if rng.random() < 0.3:
            return [build(rng, depth - 1) for _ in range(rng.randint(0, 3))]
        return {k: build(rng, depth - 1) for k in rng.sample(keys, rng.randint(0, len(keys)))}

    for seed in range(400):
        rng = random.Random(seed)
        data = build(rng, 5)
        for key in keys:
            assert tracker._find_nested(data, key) == _reference(data, key), (seed, key, data)


def test_find_nested_skips_null_values_like_the_recursive_search_did():
    tracker = make_tracker()
    data = {"outer": {"loserSeatId": None}, "later": [{"loserSeatId": 2}]}

    assert tracker._find_nested(data, "loserSeatId") == 2


def test_find_nested_prefers_a_dicts_own_key_over_its_children():
    tracker = make_tracker()
    data = {"child": {"stage": "inner"}, "stage": "outer"}

    assert tracker._find_nested(data, "stage") == "outer"
    assert tracker._find_nested([{"a": {"stage": 1}}, {"stage": 2}], "stage") == 1


def test_find_nested_index_is_per_object():
    tracker = make_tracker()
    first = {"gameInfo": {"stage": "first"}}
    second = {"gameInfo": {"stage": "second"}}

    assert tracker._find_nested(first, "gameInfo")["stage"] == "first"
    assert tracker._find_nested(second, "gameInfo")["stage"] == "second"
    assert tracker._find_nested(first, "gameInfo")["stage"] == "first"
    assert tracker._find_nested("not a container", "gameInfo") is None
    assert tracker._find_nested(None, "gameInfo") is None
