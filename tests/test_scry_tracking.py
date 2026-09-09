"""Scry tracking: counts per seat, the timeline line, and the per-event rows.

The packets mirror what Arena actually logs (captured from a real Player.log):
the scried cards appear as private-visibility game objects with a grpId in
the packet where the player is shown them, and the ``AnnotationType_Scry``
annotation arrives afterwards with the card instance ids in ``affectedIds``
split into ``topIds`` / ``bottomIds``, its ``affectorId`` being the scry
ability instance whose object (from an earlier packet) names the controller
and the source card.
"""

import json
import sqlite3
from datetime import datetime

from mtga_tracker.analytics import AnalyticsStore
from test_tracker_combat_winner import make_tracker


SCRY_ABILITY_GRP = 100685
SOURCE_GRP = 90667


def _tracker(*, player_seat=1):
    tracker = make_tracker()
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = player_seat
    tracker.game_state.opponent_seat_id = 3 - player_seat
    tracker.game_state.turn_number = 7
    tracker.game_state.last_player_turn_number = 7
    tracker.game_state.last_opponent_turn_number = 6
    tracker.card_db.names[SOURCE_GRP] = "Simulacrum Synthesizer"
    tracker.card_db.names[94825] = "Sol Talisman"
    tracker.card_db.names[96601] = "Plains"
    tracker.card_db.names[SCRY_ABILITY_GRP] = f"Card{SCRY_ABILITY_GRP}"
    return tracker


def _look_packet(seat, with_grp=True):
    """The packet where the scrying seat is shown the top cards."""
    cards = []
    for instance_id, grp in ((170, 94825), (169, 96601)):
        card = {
            "instanceId": instance_id,
            "type": "GameObjectType_Card",
            "zoneId": 32,
            "visibility": "Visibility_Private",
            "ownerSeatId": seat,
            "controllerSeatId": seat,
        }
        if with_grp:
            card["grpId"] = grp
        cards.append(card)
    ability = {
        "instanceId": 378,
        "grpId": SCRY_ABILITY_GRP,
        "type": "GameObjectType_Ability",
        "zoneId": 27,
        "visibility": "Visibility_Public",
        "ownerSeatId": seat,
        "controllerSeatId": seat,
        "objectSourceGrpId": SOURCE_GRP,
        "parentId": 374,
    }
    return {"type": "game_state", "data": {"gameObjects": cards + [ability], "annotations": []}}


def _scry_packet(top, bottom):
    details = []
    if top:
        details.append({"key": "topIds", "type": "KeyValuePairValueType_int32", "valueInt32": top})
    else:
        details.append({"key": "topIds"})
    if bottom:
        details.append(
            {"key": "bottomIds", "type": "KeyValuePairValueType_int32", "valueInt32": bottom}
        )
    else:
        details.append({"key": "bottomIds"})
    return {
        "type": "game_state",
        "data": {
            "gameObjects": [],
            "annotations": [
                {
                    "id": 324,
                    "affectorId": 378,
                    "affectedIds": top + bottom,
                    "type": ["AnnotationType_Scry"],
                    "details": details,
                },
                {
                    "id": 326,
                    "affectorId": 378,
                    "affectedIds": [378],
                    "type": ["AnnotationType_ResolutionComplete"],
                    "details": [{"key": "grpid", "valueInt32": [SCRY_ABILITY_GRP]}],
                },
            ],
        },
    }


def test_player_scry_counts_cards_and_names_where_they_went(capsys):
    tracker = _tracker()
    tracker._handle_event(_look_packet(1))
    tracker._handle_event(_scry_packet(top=[170], bottom=[169]))
    out = capsys.readouterr().out

    assert "You: scried 2 — kept [Sol Talisman] on top, bottomed [Plains]" in out
    stats = tracker._seat_stats(1)
    assert (stats["scries"], stats["scry_cards"], stats["scry_top"], stats["scry_bottom"]) == (
        1,
        2,
        1,
        1,
    )
    # The other seat is untouched.
    assert tracker._seat_stats(2)["scries"] == 0


def test_player_scry_all_one_way_reads_naturally(capsys):
    tracker = _tracker()
    tracker._handle_event(_look_packet(1))
    tracker._handle_event(_scry_packet(top=[170, 169], bottom=[]))
    tracker._handle_event(_scry_packet(top=[], bottom=[170, 169]))
    out = capsys.readouterr().out

    assert "You: scried 2 — kept [Sol Talisman], [Plains] on top" in out
    assert "You: scried 2 — bottomed [Sol Talisman], [Plains]" in out
    stats = tracker._seat_stats(1)
    assert (stats["scries"], stats["scry_cards"], stats["scry_top"], stats["scry_bottom"]) == (
        2,
        4,
        2,
        2,
    )


def test_opponent_scry_counts_only_with_hidden_cards(capsys):
    tracker = _tracker(player_seat=1)
    # The opponent's library cards are never shown to us: no grpId.
    tracker._handle_event(_look_packet(2, with_grp=False))
    tracker._handle_event(_scry_packet(top=[170], bottom=[169]))
    out = capsys.readouterr().out

    assert "Opponent: scried 2 — 1 top, 1 bottom" in out
    stats = tracker._seat_stats(2)
    assert (stats["scries"], stats["scry_cards"], stats["scry_top"], stats["scry_bottom"]) == (
        1,
        2,
        1,
        1,
    )
    assert tracker._seat_stats(1)["scries"] == 0


def test_scry_line_is_styled_scry_and_falls_back_to_card_owner_for_the_seat(capsys):
    tracker = _tracker()
    styles = []
    original = tracker._print_event
    tracker._print_event = lambda text, style=None: (styles.append(style), original(text, style))
    # No ability object known at all: the seat comes from the cards' owner.
    packet = _look_packet(1)
    packet["data"]["gameObjects"] = packet["data"]["gameObjects"][:2]
    tracker._handle_event(packet)
    tracker._handle_event(_scry_packet(top=[], bottom=[170, 169]))
    out = capsys.readouterr().out

    assert styles[-1] == "scry" and styles.count("scry") == 1
    assert "You: scried 2 — bottomed [Sol Talisman], [Plains]" in out


def test_scry_persists_library_event_rows_and_participant_totals(tmp_path):
    tracker = _tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.session_start_time = datetime(2026, 9, 9, 20, 0, 0)
    tracker.game_state.game_start_time = datetime(2026, 9, 9, 20, 5, 0)
    tracker.game_state.player_display_name = "Tapps"
    tracker.game_state.opponent_display_name = "Rival"
    tracker.game_state.format_str = "Standard"
    tracker._print_event = lambda *args, **kwargs: None

    tracker._handle_event(_look_packet(1))
    tracker._handle_event(_scry_packet(top=[170], bottom=[169]))

    conn = sqlite3.connect(tracker._console_db_path)
    rows = conn.execute(
        "SELECT kind, looked, kept_top, bottomed, to_graveyard, source_card, top_names, bottom_names "
        "FROM game_library_events"
    ).fetchall()
    assert len(rows) == 1
    kind, looked, top, bottom, grave, source, top_names, bottom_names = rows[0]
    assert (kind, looked, top, bottom, grave, source) == (
        "scry",
        2,
        1,
        1,
        0,
        "Simulacrum Synthesizer",
    )
    assert json.loads(top_names) == ["Sol Talisman"]
    assert json.loads(bottom_names) == ["Plains"]

    # The participant totals land with the game summary.
    tracker.game_state.game_end_time = datetime(2026, 9, 9, 20, 20, 0)
    tracker.game_state.winner_seat = 1
    tracker._print_game_summary()
    stats = conn.execute(
        "SELECT scries, scry_cards, scry_top, scry_bottom, surveils "
        "FROM game_participant_stats s JOIN participants p ON p.id = s.participant_id "
        "WHERE p.role = 'player'"
    ).fetchone()
    assert stats == (1, 2, 1, 1, None)
    conn.close()


def test_migration_v29_adds_columns_and_backfills_scry_counts_from_timelines(tmp_path):
    db_path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(db_path)
    AnalyticsStore.ensure_schema(conn)
    # Pretend the columns were never there (an install from before scry).
    for column in AnalyticsStore._LIBRARY_STAT_COLUMNS:
        conn.execute(f"ALTER TABLE game_participant_stats DROP COLUMN {column}")
    conn.execute("DROP TABLE game_library_events")
    conn.execute("DELETE FROM schema_migrations WHERE version = 29")
    conn.executemany(
        "INSERT INTO games (id, session_id, match_id, started_at) VALUES (?, ?, ?, ?)",
        [("g1", "s", "m1", "2026-08-01T10:00:00"), ("g2", "s", "m2", "2026-08-01T11:00:00")],
    )
    conn.executemany(
        "INSERT INTO participants (id, game_id, role) VALUES (?, ?, ?)",
        [("g1-p", "g1", "player"), ("g1-o", "g1", "opponent"), ("g2-p", "g2", "player")],
    )
    conn.executemany(
        "INSERT INTO game_participant_stats (game_id, participant_id) VALUES (?, ?)",
        [("g1", "g1-p"), ("g1", "g1-o"), ("g2", "g2-p")],
    )
    conn.executemany(
        "INSERT INTO game_events (session_id, game_id, participant_id, event_time, text) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("s", "g1", "g1-p", "2026-08-01T10:01:00", "[1:00] You: scried"),
            ("s", "g1", "g1-p", "2026-08-01T10:02:00", "[2:00] You: scried"),
            ("s", "g1", "g1-o", "2026-08-01T10:03:00", "[3:00] Opponent: cast [Opt]"),
        ],
    )
    conn.commit()

    AnalyticsStore.apply_pending_migrations(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(game_participant_stats)")}
    assert set(AnalyticsStore._LIBRARY_STAT_COLUMNS) <= columns
    assert conn.execute("SELECT COUNT(*) FROM game_library_events").fetchone()[0] == 0
    rows = dict(
        conn.execute(
            "SELECT participant_id, scries FROM game_participant_stats"
        ).fetchall()
    )
    # g1 has a timeline: the player's two "scried" lines count, the opponent
    # gets 0; g2 has no timeline at all and stays "not tracked".
    assert rows == {"g1-p": 2, "g1-o": 0, "g2-p": None}
    assert conn.execute(
        "SELECT scry_cards FROM game_participant_stats WHERE participant_id = 'g1-p'"
    ).fetchone() == (None,)
    conn.close()
