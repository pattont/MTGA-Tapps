"""Each seat's library size at the end of a game (Game Detail → Cards)."""

import sqlite3
from datetime import datetime

from mtga_tracker import dashboard
from mtga_tracker.analytics import AnalyticsStore

from test_tracker_combat_winner import make_tracker


def _libraries(tracker, sizes):
    tracker._observe_library_sizes(
        {
            "zones": [
                {
                    "zoneId": 10 * seat,
                    "type": "ZoneType_Library",
                    "ownerSeatId": seat,
                    "objectInstanceIds": list(range(1000 * seat, 1000 * seat + size)),
                }
                for seat, size in sizes.items()
            ]
        }
    )


def _tracker():
    tracker = make_tracker()
    g = tracker.game_state
    g.in_match = True
    g.player_seat_id = 1
    g.opponent_seat_id = 2
    g.turn_number = 9
    g.last_player_turn_number = 9
    g.last_opponent_turn_number = 8
    g.turns_taken_by_seat = {1: set(range(1, 18, 2)), 2: set(range(2, 17, 2))}
    return tracker


def test_final_library_sizes_are_saved_for_both_seats(tmp_path):
    tracker = _tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.session_start_time = datetime(2026, 11, 19, 20, 0, 0)
    g = tracker.game_state
    g.game_start_time = datetime(2026, 11, 19, 20, 5, 0)
    g.player_display_name = "Tapps"
    g.opponent_display_name = "Rival"
    g.format_str = "Standard"
    tracker._print_event = lambda *args, **kwargs: None

    g.observed_starting_deck_total_by_seat = {1: 60, 2: 60}
    _libraries(tracker, {1: 40, 2: 38})
    _libraries(tracker, {1: 31})  # a diff lists only the zone that changed
    _libraries(tracker, {2: 29})

    g.game_end_time = datetime(2026, 11, 19, 20, 20, 0)
    g.winner_seat = 1
    tracker._print_game_summary()

    conn = sqlite3.connect(tracker._console_db_path)
    rows = dict(
        conn.execute(
            "SELECT p.role, s.library_remaining FROM game_participant_stats s "
            "JOIN participants p ON p.id = s.participant_id"
        ).fetchall()
    )
    game_id = conn.execute("SELECT id FROM games").fetchone()[0]
    conn.close()
    assert rows == {"player": 31, "opponent": 29}

    # Game Detail shows each side's deck size beside it.
    detail = dashboard.game_detail(tracker._console_db_path, game_id)
    shown = {
        row["role"]: (row["deck_size"], row["library_remaining"])
        for row in detail["participant_stats"]
    }
    assert shown == {"player": (60, 31), "opponent": (60, 29)}

    # A database the tracker has not migrated yet: a dash, not an error.
    conn = sqlite3.connect(tracker._console_db_path)
    conn.execute("ALTER TABLE game_participant_stats DROP COLUMN library_remaining")
    conn.commit()
    conn.close()
    detail = dashboard.game_detail(tracker._console_db_path, game_id)
    assert {row["library_remaining"] for row in detail["participant_stats"]} == {None}


def test_a_summarized_message_leaves_a_library_unknown_until_listed_again():
    tracker = _tracker()
    _libraries(tracker, {1: 40, 2: 38})
    assert (tracker._final_library_size(1), tracker._final_library_size(2)) == (40, 38)

    # Half a library milled in a message Arena only summarized.
    tracker._process_line(
        "[UnityCrossThreadLogger]11/19/2026 8:26:07 PM: Match to X: GreToClientEvent\n"
        "[Message summarized because one or more GameStateMessages exceeded the 50 GameObject "
        "or 50 Annotation limit.]"
    )
    assert (tracker._final_library_size(1), tracker._final_library_size(2)) == (None, None)

    _libraries(tracker, {2: 12})
    assert (tracker._final_library_size(1), tracker._final_library_size(2)) == (None, 12)


def test_library_size_is_unknown_when_never_listed():
    tracker = _tracker()
    assert tracker._final_library_size(1) is None
    assert tracker._final_library_size(None) is None


def test_migration_v39_adds_the_column(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.sqlite3")
    AnalyticsStore.ensure_schema(conn)
    conn.execute("ALTER TABLE game_participant_stats DROP COLUMN library_remaining")
    conn.execute("DELETE FROM schema_migrations WHERE version = 39")
    conn.commit()

    AnalyticsStore.apply_pending_migrations(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(game_participant_stats)")}
    assert "library_remaining" in columns
    assert conn.execute("SELECT 1 FROM schema_migrations WHERE version = 39").fetchone()
    conn.close()
