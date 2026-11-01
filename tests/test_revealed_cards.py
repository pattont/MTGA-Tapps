"""Opponent cards revealed by mills, discards and exiles reach the Opponent
Deck summary (game_card_summary milled/discarded/exiled counts)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tracker_combat_winner import make_tracker  # noqa: E402

from mtga_tracker.analytics import AnalyticsStore  # noqa: E402
from mtga_tracker.analytics_persistence import persist_card_summary  # noqa: E402
from mtga_tracker.revealed_cards import backfill_revealed_card_counts  # noqa: E402
from mtga_tracker.state import CardEvent  # noqa: E402

OPP_LIBRARY, OPP_HAND, OPP_GRAVE, BATTLEFIELD, EXILE = 21, 22, 23, 28, 29
ZONES = {
    OPP_LIBRARY: {"zoneId": OPP_LIBRARY, "type": "ZoneType_Library", "ownerSeatId": 2},
    OPP_HAND: {"zoneId": OPP_HAND, "type": "ZoneType_Hand", "ownerSeatId": 2},
    OPP_GRAVE: {"zoneId": OPP_GRAVE, "type": "ZoneType_Graveyard", "ownerSeatId": 2},
    BATTLEFIELD: {"zoneId": BATTLEFIELD, "type": "ZoneType_Battlefield"},
    EXILE: {"zoneId": EXILE, "type": "ZoneType_Exile"},
}


def _tracker():
    tracker = make_tracker()
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.in_match = True
    tracker.game_state.turn_number = 3
    tracker.card_db.names.update(
        {501: "Angel of Unity", 502: "Youthful Valkyrie", 503: "Resplendent Angel"}
    )
    return tracker


def _transfer(tracker, instance_id, category, src, dest, **obj_fields):
    obj = {
        "instanceId": instance_id,
        "grpId": obj_fields.pop("grpId", 501),
        "type": "GameObjectType_Card",
        "ownerSeatId": 2,
        "controllerSeatId": 2,
        "zoneId": dest,
        "visibility": "Visibility_Public",
        "cardTypes": ["CardType_Creature"],
        **obj_fields,
    }
    annotation = {
        "type": ["AnnotationType_ZoneTransfer"],
        "affectedIds": [instance_id],
        "details": [
            {"key": "category", "valueString": [category]},
            {"key": "zone_src", "valueInt32": [src]},
            {"key": "zone_dest", "valueInt32": [dest]},
        ],
    }
    tracker._process_annotation(annotation, [obj], zones_by_id=ZONES)


def _revealed(tracker):
    return [
        (event.card_name, event.source)
        for event in tracker.game_state.revealed_card_events.get(2, [])
    ]


def test_opponent_mill_discard_and_hidden_zone_exile_are_recorded(capsys):
    tracker = _tracker()
    _transfer(tracker, 901, "Mill", OPP_LIBRARY, OPP_GRAVE, grpId=501)
    _transfer(tracker, 902, "Mill", OPP_LIBRARY, OPP_GRAVE, grpId=502)
    _transfer(tracker, 903, "Discard", OPP_HAND, OPP_GRAVE, grpId=503)
    _transfer(tracker, 904, "Exile", OPP_LIBRARY, EXILE, grpId=501)
    capsys.readouterr()

    assert _revealed(tracker) == [
        ("Angel of Unity", "mill"),
        ("Youthful Valkyrie", "mill"),
        ("Resplendent Angel", "discard"),
        ("Angel of Unity", "exile"),
    ]
    assert tracker.game_state.revealed_card_events[2][0].turn_number == 3


def test_already_public_exiles_tokens_and_hidden_cards_are_not_revealed(capsys):
    tracker = _tracker()
    # Exiled from the battlefield: it was already public when played.
    _transfer(tracker, 911, "Exile", BATTLEFIELD, EXILE, grpId=501)
    # A token, a face-down exile and a card the player cannot see.
    _transfer(tracker, 912, "Exile", OPP_HAND, EXILE, grpId=502, type="GameObjectType_Token")
    _transfer(tracker, 913, "Exile", OPP_HAND, EXILE, grpId=502, isFacedown=True)
    _transfer(tracker, 914, "Mill", OPP_LIBRARY, OPP_GRAVE, visibility="Visibility_Private")
    # An unresolved card id never becomes a row.
    tracker.card_db.names[505] = "Card #505"
    _transfer(tracker, 915, "Mill", OPP_LIBRARY, OPP_GRAVE, grpId=505)
    capsys.readouterr()

    assert _revealed(tracker) == []
    # The seat-level stats still count every move.
    assert tracker.game_state.match_stats[2]["cards_milled"] == 2
    assert tracker.game_state.match_stats[2]["cards_exiled"] == 3


def _store(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    assert conn is not None
    with conn:
        conn.execute("insert into tracker_sessions (id, started_at) values ('s', '2026-11-01')")
        conn.execute("insert into matches (id, session_id) values ('m', 's')")
    return conn


def _add_game(conn, game_id, *, replay_version=None):
    conn.execute(
        "insert into games (id, session_id, match_id, replay_version) values (?, 's', 'm', ?)",
        (game_id, replay_version),
    )
    for role in ("player", "opponent"):
        conn.execute(
            "insert into participants (id, game_id, role) values (?, ?, ?)",
            (f"{game_id}:{role}", game_id, role),
        )


def _summary(conn, participant_id):
    return {
        row[0]: tuple(row[1:])
        for row in conn.execute(
            """
            select display_name, played_count, drawn_count, discarded_count,
                   milled_count, exiled_count
            from game_card_summary where participant_id = ? order by display_name
            """,
            (participant_id,),
        )
    }


def test_persist_card_summary_writes_revealed_counts(tmp_path):
    conn = _store(tmp_path)
    with conn:
        _add_game(conn, "g")
        persist_card_summary(
            conn,
            "g",
            "g:opponent",
            [CardEvent("Angel of Unity (Creature 3/3)", "opponent", card_type_category="Creature")],
            refresh_display_name=lambda name: name,
            revealed_events=[
                CardEvent("Angel of Unity", "opponent", source="mill"),
                CardEvent(
                    "Archangel Elspeth",
                    "opponent",
                    card_type_category="Planeswalker",
                    source="mill",
                ),
                CardEvent("Archangel Elspeth", "opponent", source="mill"),
                CardEvent("Phial of Galadriel", "opponent", source="discard"),
                CardEvent("Giada, Font of Hope", "opponent", source="exile"),
            ],
        )

    assert _summary(conn, "g:opponent") == {
        # Played and later milled: one row, both counts.
        "Angel of Unity (Creature 3/3)": (1, 0, 0, 1, 0),
        "Archangel Elspeth": (0, 0, 0, 2, 0),
        "Giada, Font of Hope": (0, 0, 0, 0, 1),
        "Phial of Galadriel": (0, 0, 1, 0, 0),
    }
    assert (
        conn.execute(
            "select type_category from game_card_summary where display_name = 'Archangel Elspeth'"
        ).fetchone()[0]
        == "Planeswalker"
    )


def _event(conn, game_id, role, text, *, reason=None, arena_id=None, zone_from=None, **payload):
    conn.execute(
        """
        insert into game_events (
            session_id, match_id, game_id, event_time, participant_id, actor_role,
            event_type, event_subtype, text, arena_id, zone_from, payload_json, visible
        ) values ('s', 'm', ?, '2026-11-01T00:00:00', ?, ?, 'zone', ?, ?, ?, ?, ?, 1)
        """,
        (
            game_id,
            f"{game_id}:{role}",
            role,
            "move" if reason else None,
            text,
            arena_id,
            zone_from,
            json.dumps({"reason": reason, **payload}) if reason else None,
        ),
    )


def test_backfill_fills_recorded_and_legacy_games(tmp_path):
    conn = _store(tmp_path)
    with conn:
        _add_game(conn, "rec", replay_version=1)
        conn.execute(
            """
            insert into game_card_summary (game_id, participant_id, display_name,
                type_category, played_count)
            values ('rec', 'rec:opponent', 'Angel of Unity (Creature 3/3)', 'Creature', 1)
            """
        )
        mill = dict(reason="mill", zone_from="library")
        _event(
            conn,
            "rec",
            "opponent",
            "Opponent: milled [Angel of Unity]",
            arena_id=1,
            name="Angel of Unity",
            type="Creature",
            **mill,
        )
        _event(
            conn,
            "rec",
            "opponent",
            "Opponent: milled [Archangel Elspeth]",
            arena_id=2,
            name="Archangel Elspeth",
            type="Planeswalker",
            **mill,
        )
        _event(
            conn,
            "rec",
            "opponent",
            "Opponent: [Phial of Galadriel] was exiled",
            arena_id=3,
            name="Phial of Galadriel",
            type="Artifact",
            reason="exile",
            zone_from="library",
        )
        # Not revealing: exiled from the battlefield, a token, a hidden card,
        # and the player's own mill.
        _event(
            conn,
            "rec",
            "opponent",
            "Opponent: [Giada, Font of Hope] was exiled",
            arena_id=4,
            name="Giada, Font of Hope",
            reason="exile",
            zone_from="battlefield",
        )
        _event(
            conn,
            "rec",
            "opponent",
            "Opponent: [Spirit] was exiled",
            arena_id=5,
            name="Spirit",
            token=True,
            reason="exile",
            zone_from="hand",
        )
        _event(
            conn, "rec", "opponent", "Opponent: milled a card", reason="mill", zone_from="library"
        )
        _event(conn, "rec", "player", "You: milled [Island]", arena_id=6, name="Island", **mill)

        _add_game(conn, "old")
        _event(conn, "old", "opponent", "[0:51] Opponent: milled [Righteous Valkyrie]")
        _event(conn, "old", "opponent", "[0:51] Opponent: milled [Righteous Valkyrie]")
        _event(conn, "old", "opponent", "[1:10] Opponent: [Resplendent Angel] was discarded")
        _event(conn, "old", "opponent", "[1:12] Opponent: milled [Card #3]")
        _event(conn, "old", "opponent", "[1:20] Opponent: [Ajani, Outland Chaperone] was exiled")

        # An opponent written live already has counts: left untouched.
        _add_game(conn, "live", replay_version=1)
        conn.execute(
            """
            insert into game_card_summary (game_id, participant_id, display_name, milled_count)
            values ('live', 'live:opponent', 'Swamp', 1)
            """
        )
        _event(
            conn, "live", "opponent", "Opponent: milled [Swamp]", arena_id=7, name="Swamp", **mill
        )

        backfill_revealed_card_counts(conn)

    assert _summary(conn, "rec:opponent") == {
        "Angel of Unity (Creature 3/3)": (1, 0, 0, 1, 0),
        "Archangel Elspeth": (0, 0, 0, 1, 0),
        "Phial of Galadriel": (0, 0, 0, 0, 1),
    }
    assert _summary(conn, "rec:player") == {}
    assert _summary(conn, "old:opponent") == {
        "Resplendent Angel": (0, 0, 1, 0, 0),
        "Righteous Valkyrie": (0, 0, 0, 2, 0),
    }
    assert _summary(conn, "live:opponent") == {"Swamp": (0, 0, 0, 1, 0)}


def test_migration_36_is_registered():
    versions = [version for version, _ in AnalyticsStore.migration_steps()]
    assert 36 in versions
