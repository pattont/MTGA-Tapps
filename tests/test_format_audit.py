import sqlite3

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.db_audit import audit_database, repair_database
from mtga_tracker.format_normalizer import (
    format_label,
    is_midweek_format,
    is_momir_format,
    normalize_match_format,
)


def test_format_normalizer_labels_constructed_queues():
    assert format_label("Play") == "Standard Best-of-1 (Unranked)"
    assert format_label("Unknown") == "Unknown"
    assert format_label("Ladder") == "Standard Best-of-1 (Ranked)"
    assert format_label("Ladder", default_best_of=3) == "Standard Best-of-3 (Ranked)"
    assert format_label("Constructed_BestOf3") == "Standard Best-of-3 (Unranked)"
    assert format_label("TraditionalLadder") == "Standard Best-of-3 (Ranked)"
    assert format_label("TraditionalStandard") == "Standard Best-of-3 (Unranked)"
    assert format_label("MWM_SlowStart_20260602") == "Midweek Magic - Slow Start"
    assert normalize_match_format("Play").best_of == 1
    assert normalize_match_format("TraditionalStandard").best_of == 3


def test_format_normalizer_labels_nonstandard_constructed_queues():
    # Traditional_* queues are Best-of-3 even outside Standard (alpha-tester
    # regression: Traditional_Historic_Play was labeled bare "Historic" Bo1).
    assert format_label("Traditional_Historic_Play") == "Historic Best-of-3 (Unranked)"
    assert normalize_match_format("Traditional_Historic_Play").best_of == 3
    assert format_label("Traditional_Historic_Ranked") == "Historic Best-of-3 (Ranked)"
    assert format_label("Historic_Ranked") == "Historic Best-of-1 (Ranked)"
    assert format_label("Timeless_Play") == "Timeless Best-of-1 (Unranked)"
    assert format_label("Explorer_Ranked") == "Explorer Best-of-1 (Ranked)"
    assert format_label("Traditional_Alchemy_Ranked") == "Alchemy Best-of-3 (Ranked)"
    assert format_label("Historic_Brawl") == "Historic Brawl"
    assert normalize_match_format("Historic_Brawl").is_brawl


def test_format_normalizer_labels_other_modes_and_events():
    assert format_label("DirectGame") == "Direct Challenge"
    assert normalize_match_format("Traditional_DirectGame").best_of == 3
    assert format_label("JumpIn_20260801") == "Jump In!"
    assert format_label("ColorChallenge_W") == "Color Challenge"
    assert format_label("Festival_TimelessBonanza_20260820") == "Festival Timeless Bonanza"
    assert normalize_match_format("Festival_TimelessBonanza_20260820").family == "event"
    assert normalize_match_format("QualifierWeekend_20260809").best_of == 3
    assert normalize_match_format("ArenaOpen_Day2_Traditional_Standard_20260815").best_of == 3
    # Unknown future modes: prettified label, Bo3 markers still honored.
    future = normalize_match_format("SomeFutureMode_Traditional_20270101")
    assert future.label == "Some Future Mode Traditional"
    assert future.best_of == 3
    assert future.family == "unknown"


def test_momir_format_detection_handles_midweek_and_plain_labels():
    assert is_momir_format("MWM_Momir")
    assert is_momir_format("Midweek Magic - Momir")
    assert not is_momir_format("MWM_SlowStart_20260602")


def test_midweek_format_detection_covers_event_and_label_spellings():
    assert is_midweek_format("MWM_SlowStart_20260602")
    assert is_midweek_format("MWM_Momir")
    assert is_midweek_format("Midweek Magic - Slow Start")
    assert is_midweek_format("MidWeekMagic_Brawl")
    assert not is_midweek_format("Play")
    assert not is_midweek_format("TraditionalLadder")
    assert not is_midweek_format(None)


def test_audit_database_finds_safe_format_queue_mismatch(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            """
            insert into tracker_sessions (id, started_at)
            values ('session-1', '2026-06-04T00:00:00')
            """
        )
        conn.execute(
            """
            insert into matches (id, session_id, started_at, format, queue, event_name)
            values ('match-1', 'session-1', '2026-06-04T00:01:00', 'MWM_SlowStart_20260602', 'Play', 'Play')
            """
        )

    findings = audit_database(db_path)

    assert len(findings) == 1
    assert findings[0].code == "FORMAT_QUEUE_MISMATCH"
    assert findings[0].table_name == "matches"
    assert findings[0].row_id == "match-1"
    assert findings[0].suggested_value == "Play"
    assert findings[0].repairable is True


def test_repair_database_updates_safe_format_mismatch_only(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            """
            insert into tracker_sessions (id, started_at)
            values ('session-1', '2026-06-04T00:00:00')
            """
        )
        conn.executemany(
            """
            insert into matches (id, session_id, format, queue, event_name)
            values (?, 'session-1', ?, ?, ?)
            """,
            [
                ("match-safe", "MWM_SlowStart_20260602", "Play", "Play"),
                (
                    "match-ok",
                    "MWM_SlowStart_20260602",
                    "MWM_SlowStart_20260602",
                    "MWM_SlowStart_20260602",
                ),
            ],
        )

    result = repair_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select id, format from matches order by id").fetchall()

    assert result.repaired_count == 1
    assert rows == [
        ("match-ok", "MWM_SlowStart_20260602"),
        ("match-safe", "Play"),
    ]


def test_audit_repairs_missing_exact_turn_timings_from_console_history(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('session-1', '2026-07-01T12:00:00')"
        )
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('match-1', 'session-1')")
        conn.execute(
            """
            INSERT INTO games (
                id, session_id, match_id, started_at, ended_at, total_turns, outcome
            ) VALUES (
                'game-1', 'session-1', 'match-1',
                '2026-07-01T12:00:00', '2026-07-01T12:01:30', 2, 'win'
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO participants (id, game_id, seat_id, role)
            VALUES (?, 'game-1', ?, ?)
            """,
            (("player-1", 1, "player"), ("opponent-1", 2, "opponent")),
        )
        conn.executemany(
            """
            INSERT INTO game_events (
                session_id, game_id, event_time, turn_number, event_type, text
            ) VALUES ('session-1', 'game-1', ?, ?, 'turn', ?)
            """,
            (
                ("2026-07-01T12:00:10", 1, "Turn 1 - YOUR TURN"),
                ("2026-07-01T12:00:40", 2, "Turn 2 - OPPONENT'S TURN"),
            ),
        )
        conn.execute(
            """
            INSERT INTO console_logs (
                session_id, created_at, match_started_at, turn_number, text
            ) VALUES (
                'session-1', '2026-07-01T12:00:40',
                '2026-07-01T12:00:00', 2, 'Previous Turn (You): 30s'
            )
            """
        )

    findings = audit_database(db_path)
    missing = [finding for finding in findings if finding.code == "MISSING_TURN_TIMINGS"]
    assert [finding.row_id for finding in missing] == ["game-1"]

    result = repair_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT turn_number, seat_id, duration_seconds, timing_source
            FROM game_turns
            ORDER BY turn_number
            """
        ).fetchall()
    assert result.repaired_count == 1
    assert rows == [
        (1, 1, 30, "recovered_previous_turn_logs"),
        (2, 2, 50, "recovered_previous_turn_logs"),
    ]


def test_audit_skips_turn_timings_lost_before_tracker_attached(tmp_path):
    """Turns with no console history and no header events are expected loss."""
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('session-1', '2026-07-22T01:00:00')"
        )
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('match-1', 'session-1')")
        conn.execute(
            """
            INSERT INTO games (
                id, session_id, match_id, started_at, ended_at, total_turns,
                player_turns, opponent_turns, outcome
            ) VALUES (
                'game-1', 'session-1', 'match-1',
                '2026-07-22T01:16:00', '2026-07-22T01:20:00', 6, 3, 3, 'win'
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO participants (id, game_id, seat_id, role)
            VALUES (?, 'game-1', ?, ?)
            """,
            (("player-1", 1, "player"), ("opponent-1", 2, "opponent")),
        )
        # The tracker attached mid-game: turns 3-6 have timings, 1-2 have nothing.
        conn.executemany(
            """
            INSERT INTO game_turns (
                game_id, turn_number, seat_id, started_at, ended_at, duration_seconds
            ) VALUES ('game-1', ?, ?, ?, ?, 30)
            """,
            (
                (3, 1, "2026-07-22T01:17:00", "2026-07-22T01:17:30"),
                (4, 2, "2026-07-22T01:17:30", "2026-07-22T01:18:00"),
                (5, 1, "2026-07-22T01:18:00", "2026-07-22T01:18:30"),
                (6, 2, "2026-07-22T01:18:30", "2026-07-22T01:19:00"),
            ),
        )

    findings = audit_database(db_path)
    assert [finding for finding in findings if finding.code == "MISSING_TURN_TIMINGS"] == []


def test_audit_repairs_missing_turn_bracketed_by_persisted_next_turn(tmp_path):
    """A headered turn whose next header was lost still recovers from the next timing row."""
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('session-1', '2026-07-21T01:00:00')"
        )
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('match-1', 'session-1')")
        conn.execute(
            """
            INSERT INTO games (
                id, session_id, match_id, started_at, ended_at, total_turns,
                player_turns, opponent_turns, outcome
            ) VALUES (
                'game-1', 'session-1', 'match-1',
                '2026-07-21T01:28:00', '2026-07-21T01:31:00', 4, 2, 2, 'win'
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO participants (id, game_id, seat_id, role)
            VALUES (?, 'game-1', ?, ?)
            """,
            (("player-1", 2, "player"), ("opponent-1", 1, "opponent")),
        )
        # Turn 3's header exists, but turn 4's header was never logged; turn 4's
        # timing row was recovered from console history instead.
        conn.executemany(
            """
            INSERT INTO game_events (
                session_id, game_id, event_time, turn_number, event_type, text
            ) VALUES ('session-1', 'game-1', ?, ?, 'turn', ?)
            """,
            (("2026-07-21T01:29:17", 3, "Turn 3 - YOUR TURN"),),
        )
        conn.executemany(
            """
            INSERT INTO game_turns (
                game_id, turn_number, seat_id, started_at, ended_at,
                duration_seconds, timing_source
            ) VALUES ('game-1', ?, ?, ?, ?, ?, ?)
            """,
            (
                (1, 2, "2026-07-21T01:28:30", "2026-07-21T01:28:50", 20, "live"),
                (2, 1, "2026-07-21T01:28:50", "2026-07-21T01:29:17", 27, "live"),
                (4, 1, "2026-07-21T01:29:24", "2026-07-21T01:29:47", 23, "recovered_previous_turn_logs"),
            ),
        )

    findings = audit_database(db_path)
    missing = [finding for finding in findings if finding.code == "MISSING_TURN_TIMINGS"]
    assert [finding.row_id for finding in missing] == ["game-1"]
    assert "turn(s) 3" in missing[0].message

    result = repair_database(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT seat_id, started_at, ended_at, duration_seconds, timing_source
            FROM game_turns
            WHERE game_id = 'game-1' AND turn_number = 3
            """
        ).fetchone()
    assert result.repaired_count == 1
    assert row == (
        2,
        "2026-07-21T01:29:17",
        "2026-07-21T01:29:24",
        7,
        "estimated_header_events",
    )

    assert [
        finding
        for finding in audit_database(db_path)
        if finding.code == "MISSING_TURN_TIMINGS"
    ] == []


def test_repair_database_reassigns_events_to_game_time_interval(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('session-1', '2026-07-01T12:00:00')"
        )
        conn.executemany(
            "INSERT INTO matches (id, session_id) VALUES (?, 'session-1')",
            (("match-1",), ("match-2",)),
        )
        conn.executemany(
            """
            INSERT INTO games (id, session_id, match_id, started_at, ended_at, outcome)
            VALUES (?, 'session-1', ?, ?, ?, 'win')
            """,
            (
                ("game-1", "match-1", "2026-07-01T12:00:00", "2026-07-01T12:05:00"),
                ("game-2", "match-2", "2026-07-01T12:10:00", "2026-07-01T12:15:00"),
            ),
        )
        conn.execute(
            """
            INSERT INTO game_events (
                session_id, match_id, game_id, event_time, actor_role, participant_id, text
            ) VALUES (
                'session-1', 'match-1', 'game-1', '2026-07-01T12:11:00',
                'player', 'game-1:participant:player', 'You: cast [Opt]'
            )
            """
        )

    findings = audit_database(db_path)
    assert any(finding.code == "GAME_EVENT_ASSIGNMENT_MISMATCH" for finding in findings)

    result = repair_database(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT match_id, game_id, participant_id FROM game_events").fetchone()
    assert result.repaired_count == 1
    assert row == ("match-2", "game-2", "game-2:participant:player")


def test_repair_database_deletes_only_empty_unknown_game(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO tracker_sessions (
                id, started_at, games_played, wins, unknown_results
            ) VALUES ('session-1', '2026-07-01T12:00:00', 2, 1, 1)
            """
        )
        conn.executemany(
            "INSERT INTO matches (id, session_id, games_played) VALUES (?, 'session-1', 1)",
            (("match-empty",), ("match-valid",)),
        )
        conn.executemany(
            """
            INSERT INTO games (
                id, session_id, match_id, started_at, ended_at, total_turns, outcome
            ) VALUES (?, 'session-1', ?, ?, ?, ?, ?)
            """,
            (
                (
                    "game-empty",
                    "match-empty",
                    "2026-07-01T12:00:00",
                    "2026-07-01T12:00:02",
                    1,
                    "unknown",
                ),
                (
                    "game-valid",
                    "match-valid",
                    "2026-07-01T12:10:00",
                    "2026-07-01T12:10:02",
                    1,
                    "win",
                ),
            ),
        )
        conn.executemany(
            "INSERT INTO participants (id, game_id, role) VALUES (?, ?, 'player')",
            (("empty-player", "game-empty"), ("valid-player", "game-valid")),
        )
        conn.executemany(
            "INSERT INTO game_participant_stats (game_id, participant_id) VALUES (?, ?)",
            (("game-empty", "empty-player"), ("game-valid", "valid-player")),
        )

    findings = audit_database(db_path)
    empty_findings = [finding for finding in findings if finding.code == "EMPTY_GAME_RECORD"]
    assert [finding.row_id for finding in empty_findings] == ["game-empty"]

    result = repair_database(db_path)

    with sqlite3.connect(db_path) as conn:
        games = conn.execute("SELECT id FROM games ORDER BY id").fetchall()
        matches = conn.execute("SELECT id FROM matches ORDER BY id").fetchall()
        session = conn.execute(
            "SELECT games_played, wins, unknown_results FROM tracker_sessions"
        ).fetchone()
    assert result.repaired_count == 1
    assert games == [("game-valid",)]
    assert matches == [("match-valid",)]
    assert session == (1, 1, 0)


def test_repair_database_recovers_completed_missing_game_but_not_incomplete_game(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO tracker_sessions (id, started_at, games_played, wins)
            VALUES ('session-1', '2026-07-22T12:00:00', 1, 1)
            """
        )
        conn.executemany(
            """
            INSERT INTO game_events (
                session_id, match_id, game_id, event_time, turn_number,
                actor_role, seat_id, text
            ) VALUES ('session-1', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "match-1",
                    "game-1",
                    "2026-07-22T12:00:10",
                    1,
                    "player",
                    2,
                    "Turn 1 - YOUR TURN",
                ),
                (
                    "match-2",
                    "game-incomplete",
                    "2026-07-22T12:10:10",
                    1,
                    "player",
                    2,
                    "Turn 1 - YOUR TURN",
                ),
            ),
        )
        completed_logs = (
            ("2026-07-22T12:00:00", "   Players: Tapps vs Opponent", None, 20, 20),
            ("2026-07-22T12:00:10", "Turn 1 - YOUR TURN", 1, 20, 20),
            ("2026-07-22T12:03:00", "GAME ENDED - YOU WON", 1, 18, 0),
            ("2026-07-22T12:03:01", "Reason: Opponent reached 0 life", 1, 18, 0),
            ("2026-07-22T12:03:02", "Format: Standard Best-of-1 (Ranked)", 1, 18, 0),
            ("2026-07-22T12:03:03", "   Your Deck: Boros Dragons", 1, 18, 0),
            ("2026-07-22T12:03:04", "   Mulligans: 1", 1, 18, 0),
        )
        conn.executemany(
            """
            INSERT INTO console_logs (
                session_id, created_at, match_started_at, text, turn_number,
                player_life, opponent_life
            ) VALUES ('session-1', ?, '2026-07-22T12:00:00', ?, ?, ?, ?)
            """,
            completed_logs,
        )
        conn.execute(
            """
            INSERT INTO console_logs (
                session_id, created_at, match_started_at, text, turn_number
            ) VALUES (
                'session-1', '2026-07-22T12:10:10',
                '2026-07-22T12:10:00', 'Turn 1 - YOUR TURN', 1
            )
            """
        )

    findings = audit_database(db_path)
    missing = [f.row_id for f in findings if f.code == "MISSING_COMPLETED_GAME_RECORD"]
    assert missing == ["game-1"]

    repair_database(db_path)

    with sqlite3.connect(db_path) as conn:
        game = conn.execute(
            """
            SELECT id, duration_seconds, outcome, outcome_reason, total_turns
            FROM games
            """
        ).fetchone()
        player = conn.execute(
            """
            SELECT display_name, deck_name, mulligans, ending_life, went_first
            FROM participants WHERE role = 'player'
            """
        ).fetchone()
    assert game == ("game-1", 180, "win", "Opponent reached 0 life", 1)
    assert player == ("Tapps", "Boros Dragons", 1, 18, 1)


def test_is_welcome_deck_format_matches_reported_shapes():
    from mtga_tracker.format_normalizer import is_welcome_deck_format

    assert is_welcome_deck_format("Welcome Deck Duels HOB")
    assert is_welcome_deck_format("Welcome_Deck_Duels_HOB")
    assert is_welcome_deck_format("WelcomeDeckDuels")
    # "welcome" alone must not be enough — only the welcome-deck stem.
    assert not is_welcome_deck_format("Welcome_To_Standard_2027")
    assert not is_welcome_deck_format("Ladder")
    assert not is_welcome_deck_format(None)
