import sqlite3
from datetime import datetime, timedelta

from mtga_tracker.analytics import AnalyticsStore, SessionSnapshot
from mtga_tracker.payload_codec import compress_payload, decode_payload
from mtga_tracker.tracker_analytics import TrackerAnalyticsMixin


def test_payload_codec_round_trip_and_legacy_values():
    text = '{"payload": "data", "unicode": "Æther Vial ✨"}'
    stored = compress_payload(text)
    assert isinstance(stored, bytes)
    assert len(stored) < len(text.encode("utf-8")) or len(text) < 60
    assert decode_payload(stored) == text
    # Legacy plain-text rows and edge cases pass through unharmed.
    assert decode_payload(text) == text
    assert decode_payload(text.encode("utf-8")) == text
    assert decode_payload(None) == ""
    assert decode_payload(memoryview(stored)) == text


def _insert_deck_game(conn, game_id, deck_name, started_at, cards):
    conn.execute(
        "INSERT INTO games (id, session_id, match_id, started_at, outcome) "
        "VALUES (?, 'session-1', ?, ?, 'win')",
        (game_id, f"match-{game_id}", started_at),
    )
    participant_id = f"{game_id}-player"
    conn.execute(
        "INSERT INTO participants (id, game_id, role, deck_name) VALUES (?, ?, 'player', ?)",
        (participant_id, game_id, deck_name),
    )
    for arena_id, (name, qty) in enumerate(cards, start=1):
        conn.execute(
            "INSERT INTO game_deck_cards (game_id, participant_id, arena_id, display_name, deck_zone, quantity) "
            "VALUES (?, ?, ?, ?, 'deck', ?)",
            (game_id, participant_id, arena_id, name, qty),
        )
    return participant_id


def test_canonicalize_imported_deck_names_uses_exact_decklist_match(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    deck = [("Amalia", 4), ("Plains", 20), ("Swamp", 16), ("Deep-Cavern Bat", 4)]
    with conn:
        _insert_deck_game(conn, "game-import", "Imported Deck", "2026-08-02T23:31:43", deck)
        _insert_deck_game(conn, "game-named", "Orzhov Lifegain", "2026-08-02T23:50:00", deck)
        # Near-miss (different quantities) must NOT rename.
        _insert_deck_game(
            conn, "game-import-2", "Imported Deck (3)", "2026-07-26T00:56:53",
            [("Amalia", 4), ("Plains", 21), ("Swamp", 15), ("Deep-Cavern Bat", 4)],
        )

    renamed = AnalyticsStore.canonicalize_imported_deck_names(conn)

    names = dict(
        conn.execute("SELECT game_id, deck_name FROM participants WHERE role='player'")
    )
    store.close()
    assert renamed == 1
    assert names["game-import"] == "Orzhov Lifegain"
    assert names["game-import-2"] == "Imported Deck (3)"


def _insert_bo3_game(conn, session, match_n, started, ended, opponent, fmt="Constructed_BestOf3"):
    match_id = f"{session}:match:{match_n}"
    game_id = f"{match_id}:game:1"
    conn.execute(
        "INSERT OR IGNORE INTO matches (id, session_id, format, started_at) VALUES (?, ?, ?, ?)",
        (match_id, session, fmt, started),
    )
    conn.execute(
        "INSERT INTO games (id, session_id, match_id, game_number, started_at, ended_at, outcome) "
        "VALUES (?, ?, ?, 1, ?, ?, 'win')",
        (game_id, session, match_id, started, ended),
    )
    conn.execute(
        "INSERT INTO participants (id, game_id, role, display_name) VALUES (?, ?, 'opponent', ?)",
        (f"{game_id}:opp", game_id, opponent),
    )
    return game_id


def test_migration_v13_merges_split_bo3_matches(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    with conn:
        # Same opponent, 4 minutes apart, Bo3 queue -> one match.
        g1 = _insert_bo3_game(conn, "s1", 1, "2026-08-04T20:00:00", "2026-08-04T20:10:00", "NubianPrince")
        g2 = _insert_bo3_game(conn, "s1", 2, "2026-08-04T20:14:00", "2026-08-04T20:25:00", "NubianPrince")
        # Different opponent right after -> stays its own match.
        g3 = _insert_bo3_game(conn, "s1", 3, "2026-08-04T20:30:00", "2026-08-04T20:40:00", "Nico")
        conn.execute("DELETE FROM schema_migrations WHERE version = 13")
    AnalyticsStore.apply_pending_migrations(conn)

    rows = dict(conn.execute("SELECT id, match_id FROM games"))
    numbers = dict(conn.execute("SELECT id, game_number FROM games"))
    match_count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    merged_games_played = conn.execute(
        "SELECT games_played FROM matches WHERE id = 's1:match:1'"
    ).fetchone()[0]
    store.close()

    assert rows[g1] == "s1:match:1"
    assert rows[g2] == "s1:match:1"
    assert numbers[g2] == 2
    assert rows[g3] == "s1:match:3"
    assert match_count == 2
    assert merged_games_played == 2


def test_migration_v12_deletes_orphan_ghost_events_only(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    with conn:
        # Ghost: one stray cast event, no games row, no turns.
        conn.execute(
            "INSERT INTO game_events (session_id, match_id, game_id, event_time, event_type, text) "
            "VALUES ('s1', 's1:match:7', 's1:match:7:game:1', '2026-08-01T22:43:40', 'cast', 'ghost tail')"
        )
        # Real lost game: many events including turns — must be preserved so
        # db_audit can reconstruct it.
        for n in range(6):
            conn.execute(
                "INSERT INTO game_events (session_id, match_id, game_id, event_time, event_type, text) "
                "VALUES ('s1', 's1:match:8', 's1:match:8:game:1', '2026-08-01T23:00:00', ?, ?)",
                ("turn" if n == 0 else "cast", f"event {n}"),
            )
        conn.execute("DELETE FROM schema_migrations WHERE version = 12")
    AnalyticsStore.apply_pending_migrations(conn)
    ghost = conn.execute(
        "SELECT COUNT(*) FROM game_events WHERE game_id = 's1:match:7:game:1'"
    ).fetchone()[0]
    real = conn.execute(
        "SELECT COUNT(*) FROM game_events WHERE game_id = 's1:match:8:game:1'"
    ).fetchone()[0]
    store.close()
    assert ghost == 0
    assert real == 6


def test_migration_v11_compresses_legacy_payload_rows(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    legacy = '{"legacy": "plain text row", "n": 1}'
    conn = store.connect()
    with conn:
        conn.execute(
            """
            INSERT INTO raw_game_payloads (session_id, created_at, payload_type, payload_json)
            VALUES ('session-1', '2026-06-01T00:00:00', 'unknown', ?)
            """,
            (legacy,),
        )
        conn.execute("DELETE FROM schema_migrations WHERE version = 11")
    AnalyticsStore.apply_pending_migrations(conn)
    row = conn.execute("SELECT payload_json FROM raw_game_payloads").fetchone()
    store.close()

    assert isinstance(row[0], bytes)
    assert decode_payload(row[0]) == legacy


def test_analytics_store_uses_persistent_connection(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")

    first = store.connect()
    second = store.connect()

    assert first is second
    assert first is not None

    store.close()
    reopened = store.connect()

    assert reopened is not None
    assert reopened is not first
    store.close()


def test_analytics_store_records_console_log(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    started_at = datetime(2026, 5, 2, 12, 0, 0)
    created_at = started_at + timedelta(seconds=5)
    session = SessionSnapshot(
        session_id="session-1",
        started_at=started_at,
        games_played=1,
        wins=1,
        losses=0,
        unknown_results=0,
    )

    store.record_console_log(
        session,
        created_at=created_at,
        match_started_at=started_at,
        elapsed_seconds=5,
        turn_number=1,
        active_player=2,
        style="cast",
        text="[0:05] You: cast [Opt]",
        player_life=20,
        opponent_life=19,
    )
    store.close()

    with sqlite3.connect(db_path) as conn:
        session_row = conn.execute(
            "SELECT games_played, wins, losses, runtime_seconds FROM tracker_sessions WHERE id = ?",
            ("session-1",),
        ).fetchone()
        log_row = conn.execute(
            """
            SELECT session_id, elapsed_seconds, turn_number, active_player, style, text, player_life, opponent_life
            FROM console_logs
            """
        ).fetchone()

    assert session_row == (1, 1, 0, 5)
    assert log_row == (
        "session-1",
        5,
        1,
        2,
        "cast",
        "[0:05] You: cast [Opt]",
        20,
        19,
    )


def test_record_raw_payload_sanitizes_before_persisting(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)

    store.record_raw_payload(
        session_id="session-1",
        created_at=None,
        payload_type="unknown",
        payload_json='{"token":"secret","path":"/Users/travispatton/file","playerName":"Player#123"}',
    )
    store.close()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_type, payload_json FROM raw_game_payloads").fetchone()

    assert row[0] == "unknown"
    # Stored compressed; decode before inspecting.
    assert isinstance(row[1], bytes)
    payload_text = decode_payload(row[1])
    assert "secret" not in payload_text
    assert "/Users/travispatton/" not in payload_text
    assert "Player#123" not in payload_text
    assert "<redacted>" in payload_text


def test_tracker_raw_payload_snapshot_uses_current_match_context(tmp_path):
    from tests.test_tracker_combat_winner import make_tracker

    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.game_state.game_start_time = datetime(2026, 5, 13, 20, 0, 0)
    tracker.game_state.match_id = "match-1"
    tracker.game_state.game_number = 2

    tracker._record_raw_payload_snapshot(
        "connection_error",
        '{"playerName":"Player#123","path":"/Users/travispatton/log"}',
    )

    with sqlite3.connect(tracker._console_db_path) as conn:
        row = conn.execute(
            "SELECT match_id, game_id, payload_type, payload_json FROM raw_game_payloads"
        ).fetchone()

    assert row[0] == tracker._current_match_id()
    assert row[1] == tracker._current_game_id()
    assert row[2] == "connection_error"
    payload_text = decode_payload(row[3])
    assert "Player#123" not in payload_text
    assert "/Users/travispatton/" not in payload_text


def test_current_game_id_is_stable_before_and_after_outcome_is_counted():
    from tests.test_tracker_combat_winner import make_tracker

    tracker = make_tracker()
    tracker.session_games_played = 3
    tracker.game_state.in_match = True
    tracker.game_state.game_number = 1

    active_game_id = tracker._current_game_id()
    tracker.session_games_played = 4
    tracker._session_stats_recorded_this_game = True

    assert active_game_id == "test-session:match:4:game:1"
    assert tracker._current_game_id() == active_game_id


def test_backfill_estimated_game_turn_times_is_idempotent_and_preserves_live_rows(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    assert conn is not None
    conn.execute(
        "INSERT INTO tracker_sessions (id, started_at) VALUES ('session-1', '2026-07-01T12:00:00')"
    )
    conn.execute("INSERT INTO matches (id, session_id) VALUES ('match-1', 'session-1')")
    conn.execute(
        """
        INSERT INTO games (id, session_id, match_id, ended_at, total_turns)
        VALUES ('game-1', 'session-1', 'match-1', '2026-07-01T12:03:00', 3)
        """
    )
    conn.executemany(
        """
        INSERT INTO participants (id, game_id, seat_id, role)
        VALUES (?, 'game-1', ?, ?)
        """,
        (("player-1", 2, "player"), ("opponent-1", 1, "opponent")),
    )
    conn.executemany(
        """
        INSERT INTO game_events (
            session_id, game_id, event_time, turn_number, text
        ) VALUES ('session-1', 'game-1', ?, ?, ?)
        """,
        (
            ("2026-07-01T12:00:10", 1, "Turn 1 - YOUR TURN"),
            ("2026-07-01T12:00:50", 2, "Turn 2 - OPPONENT'S TURN"),
            ("2026-07-01T12:02:00", 3, "Turn 3 - YOUR TURN"),
        ),
    )
    conn.execute(
        """
        INSERT INTO game_turns (
            game_id, turn_number, seat_id, duration_seconds, timing_source
        ) VALUES ('game-1', 1, 2, 5, 'live')
        """
    )

    inserted = AnalyticsStore.backfill_estimated_game_turn_times(conn)
    inserted_again = AnalyticsStore.backfill_estimated_game_turn_times(conn)
    rows = conn.execute(
        """
        SELECT turn_number, seat_id, duration_seconds, timing_source
        FROM game_turns
        ORDER BY turn_number
        """
    ).fetchall()
    store.close()

    assert inserted == 2
    assert inserted_again == 0
    assert rows == [
        (1, 2, 5, "live"),
        (2, 1, 70, "estimated_header_events"),
        (3, 2, 60, "estimated_header_events"),
    ]


def test_connection_uses_wal_and_waits_for_transient_writers(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    assert conn is not None

    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
    store.close()


def test_analytics_write_retries_transient_database_locks(monkeypatch, tmp_path):
    conn = sqlite3.connect(tmp_path / "analytics.sqlite3")
    conn.execute("CREATE TABLE retries (attempt INTEGER)")
    attempts = 0
    monkeypatch.setattr("mtga_tracker.tracker_analytics.time.sleep", lambda _seconds: None)

    def write_after_two_locks():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        conn.execute("INSERT INTO retries (attempt) VALUES (?)", (attempts,))

    TrackerAnalyticsMixin._run_analytics_write(conn, write_after_two_locks)

    assert attempts == 3
    assert conn.execute("SELECT attempt FROM retries").fetchall() == [(3,)]
    conn.close()


def test_backfill_recovered_game_turn_times_uses_exact_console_durations(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    assert conn is not None
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
            '2026-07-01T12:00:00', '2026-07-01T12:03:00', 3, 'win'
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
    conn.executemany(
        """
        INSERT INTO game_events (
            session_id, game_id, event_time, turn_number, event_type, text
        ) VALUES ('session-1', 'game-1', ?, ?, 'turn', ?)
        """,
        (
            ("2026-07-01T12:00:10", 1, "Turn 1 - YOUR TURN"),
            ("2026-07-01T12:00:40", 2, "Turn 2 - OPPONENT'S TURN"),
            ("2026-07-01T12:01:50", 3, "Turn 3 - YOUR TURN"),
        ),
    )
    conn.executemany(
        """
        INSERT INTO console_logs (
            session_id, created_at, match_started_at, turn_number, text
        ) VALUES ('session-1', ?, '2026-07-01T12:00:00', ?, ?)
        """,
        (
            ("2026-07-01T12:00:40", 2, "Previous Turn (You): 30s"),
            ("2026-07-01T12:01:50", 3, "Previous Turn (Opponent): 1m 10s"),
        ),
    )

    inserted = AnalyticsStore.backfill_recovered_game_turn_times(conn)
    inserted_again = AnalyticsStore.backfill_recovered_game_turn_times(conn)
    rows = conn.execute(
        """
        SELECT turn_number, seat_id, duration_seconds, timing_source
        FROM game_turns
        ORDER BY turn_number
        """
    ).fetchall()
    store.close()

    assert inserted == 3
    assert inserted_again == 0
    assert rows == [
        (1, 2, 30, "recovered_previous_turn_logs"),
        (2, 1, 70, "recovered_previous_turn_logs"),
        (3, 2, 70, "recovered_previous_turn_logs"),
    ]


def test_migration_backfills_card_arena_ids_from_deck_cards(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()

    conn.execute(
        "INSERT INTO cards (name, first_seen_at) VALUES ('Llanowar Elves', datetime('now'))"
    )
    card_id = conn.execute(
        "SELECT id FROM cards WHERE name = 'Llanowar Elves'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO game_deck_cards (
            game_id, participant_id, card_id, arena_id, display_name,
            type_category, deck_zone, quantity
        )
        VALUES ('game-1', 'part-1', ?, 12345, 'Llanowar Elves', 'Creature', 'deck', 4)
        """,
        (card_id,),
    )
    # Remove the applied marker and re-run so the migration sees the new rows.
    conn.execute("DELETE FROM schema_migrations WHERE version = 2")
    AnalyticsStore.apply_pending_migrations(conn)

    arena_id = conn.execute(
        "SELECT arena_id FROM cards WHERE name = 'Llanowar Elves'"
    ).fetchone()[0]
    assert arena_id == 12345

    # Running again is a no-op.
    AnalyticsStore.apply_pending_migrations(conn)
    versions = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    assert {1, 2, 3} <= versions
    store.close()


def test_migration_backfills_summary_drawn_counts(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()

    conn.execute(
        "INSERT INTO cards (name, first_seen_at) VALUES ('Opt', datetime('now'))"
    )
    card_id = conn.execute("SELECT id FROM cards WHERE name = 'Opt'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO game_card_summary (
            game_id, participant_id, card_id, display_name, type_category, played_count
        )
        VALUES ('game-1', 'part-1', ?, 'Opt', 'Instant', 2)
        """,
        (card_id,),
    )
    for position in (1, 2, 3):
        conn.execute(
            """
            INSERT INTO game_drawn_cards (
                game_id, participant_id, card_id, display_name, type_category,
                draw_position, copy_number
            )
            VALUES ('game-1', 'part-1', ?, 'Opt', 'Instant', ?, ?)
            """,
            (card_id, position, position),
        )
    # A drawn-but-never-played card should gain its own summary row.
    conn.execute(
        "INSERT INTO cards (name, first_seen_at) VALUES ('Consider', datetime('now'))"
    )
    other_id = conn.execute("SELECT id FROM cards WHERE name = 'Consider'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO game_drawn_cards (
            game_id, participant_id, card_id, display_name, type_category,
            draw_position, copy_number
        )
        VALUES ('game-1', 'part-1', ?, 'Consider', 'Instant', 4, 1)
        """,
        (other_id,),
    )
    conn.execute("DELETE FROM schema_migrations WHERE version = 3")
    AnalyticsStore.apply_pending_migrations(conn)

    drawn = conn.execute(
        """
        SELECT drawn_count FROM game_card_summary
        WHERE game_id = 'game-1' AND participant_id = 'part-1' AND display_name = 'Opt'
        """
    ).fetchone()[0]
    assert drawn == 3
    row = conn.execute(
        """
        SELECT played_count, drawn_count FROM game_card_summary
        WHERE game_id = 'game-1' AND participant_id = 'part-1' AND display_name = 'Consider'
        """
    ).fetchone()
    assert row == (0, 1)
    store.close()


def test_migration_backfills_drawn_card_names_in_events(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()

    conn.execute(
        "insert into participants (id, game_id, role) values ('p1', 'g1', 'player')"
    )
    conn.executemany(
        """
        insert into game_drawn_cards (
            game_id, participant_id, display_name, type_category, draw_position,
            turn_number, copy_number
        ) values ('g1', 'p1', ?, 'Instant', ?, ?, 1)
        """,
        [("Opt", 1, 2), ("Consider", 2, 4)],
    )
    conn.executemany(
        """
        insert into game_events (
            session_id, game_id, event_time, turn_number, actor_role, event_type, text
        ) values ('s1', 'g1', ?, ?, 'player', 'draw', ?)
        """,
        [
            ("2026-06-04T00:01:00", 2, "[0:31] You: drew a card"),
            ("2026-06-04T00:02:00", 4, "[1:02] You: drew a card"),
        ],
    )
    # Ambiguous game: two events, one recorded draw, different turn counts.
    conn.execute(
        "insert into participants (id, game_id, role) values ('p2', 'g2', 'player')"
    )
    conn.execute(
        """
        insert into game_drawn_cards (
            game_id, participant_id, display_name, type_category, draw_position,
            turn_number, copy_number
        ) values ('g2', 'p2', 'Shock', 'Instant', 1, NULL, 1)
        """
    )
    conn.executemany(
        """
        insert into game_events (
            session_id, game_id, event_time, turn_number, actor_role, event_type, text
        ) values ('s1', 'g2', ?, NULL, 'player', 'draw', ?)
        """,
        [
            ("2026-06-04T00:03:00", "[0:10] You: drew a card"),
            ("2026-06-04T00:04:00", "[0:20] You: drew a card"),
        ],
    )
    conn.execute("DELETE FROM schema_migrations WHERE version = 5")
    AnalyticsStore.apply_pending_migrations(conn)

    texts = [
        row[0]
        for row in conn.execute(
            "SELECT text FROM game_events WHERE game_id = 'g1' ORDER BY event_time"
        )
    ]
    assert texts == ["[0:31] You: drew [Opt]", "[1:02] You: drew [Consider]"]
    ambiguous = [
        row[0]
        for row in conn.execute(
            "SELECT text FROM game_events WHERE game_id = 'g2' ORDER BY event_time"
        )
    ]
    assert all("drew a card" in text for text in ambiguous)
    store.close()


def test_migration_v14_purges_untracked_modes(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    with conn:
        # A Jump In match that slipped in with format Unknown but a telltale
        # queue name, a Midweek Magic match, a Sparky practice game, and a
        # normal ranked game that must survive.
        conn.execute(
            "INSERT INTO matches (id, session_id, format, queue, event_name) "
            "VALUES ('s1:match:1', 's1', 'Unknown', 'Jump_In_MSH', 'Jump_In_MSH')"
        )
        conn.execute(
            "INSERT INTO matches (id, session_id, format) VALUES ('s1:match:2', 's1', 'MWM_Pauper')"
        )
        conn.execute(
            "INSERT INTO matches (id, session_id, format) VALUES ('s1:match:3', 's1', 'Ladder')"
        )
        conn.execute(
            "INSERT INTO matches (id, session_id, format) VALUES ('s1:match:4', 's1', 'Play')"
        )
        for match_n, outcome in ((1, "win"), (2, "win"), (3, "loss"), (4, "win")):
            game_id = f"s1:match:{match_n}:game:1"
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, game_number, started_at, outcome) "
                "VALUES (?, 's1', ?, 1, '2026-06-23T23:43:23', ?)",
                (game_id, f"s1:match:{match_n}", outcome),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name) "
                "VALUES (?, ?, 'opponent', ?)",
                (f"{game_id}:opp", game_id, "Sparky" if match_n == 4 else "Human"),
            )
            conn.execute(
                "INSERT INTO game_events (session_id, match_id, game_id, event_time, "
                "turn_number, event_type, text) VALUES ('s1', ?, ?, '2026-06-23T23:44:00', 1, 'turn', 'Turn 1')",
                (f"s1:match:{match_n}", game_id),
            )
        # Stale unresolvable card label in the surviving game (old enough to purge).
        conn.execute(
            "INSERT INTO game_card_summary (game_id, participant_id, card_id, display_name, "
            "type_category, played_count) VALUES ('s1:match:3:game:1', 'p', 1, 'Card #99999', 'Other', 1)"
        )
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at, games_played, wins, losses, draws, unknown_results) "
            "VALUES ('s1', '2026-06-23T20:00:00', 4, 3, 1, 0, 0)"
        )
        conn.execute("DELETE FROM schema_migrations WHERE version = 14")
    AnalyticsStore.apply_pending_migrations(conn)

    games = [row[0] for row in conn.execute("SELECT id FROM games ORDER BY id")]
    matches = [row[0] for row in conn.execute("SELECT id FROM matches ORDER BY id")]
    events = conn.execute(
        "SELECT COUNT(*) FROM game_events WHERE game_id != 's1:match:3:game:1'"
    ).fetchone()[0]
    labels = conn.execute(
        "SELECT COUNT(*) FROM game_card_summary WHERE display_name LIKE 'Card #%'"
    ).fetchone()[0]
    session = conn.execute(
        "SELECT games_played, wins, losses FROM tracker_sessions WHERE id = 's1'"
    ).fetchone()
    store.close()

    assert games == ["s1:match:3:game:1"]
    assert matches == ["s1:match:3"]
    assert events == 0
    assert labels == 0
    assert session == (1, 0, 1)


def test_migration_v15_purges_welcome_deck_duels(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.sqlite3")
    conn = store.connect()
    with conn:
        conn.execute(
            "INSERT INTO matches (id, session_id, format) "
            "VALUES ('s1:match:1', 's1', 'Welcome Deck Duels HOB')"
        )
        conn.execute(
            "INSERT INTO matches (id, session_id, format, queue) "
            "VALUES ('s1:match:2', 's1', 'Unknown', 'Welcome_Deck_Duels_HOB')"
        )
        conn.execute(
            "INSERT INTO matches (id, session_id, format) VALUES ('s1:match:3', 's1', 'Ladder')"
        )
        for match_n, outcome in ((1, "win"), (2, "loss"), (3, "win")):
            game_id = f"s1:match:{match_n}:game:1"
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, game_number, started_at, outcome) "
                "VALUES (?, 's1', ?, 1, '2026-08-11T12:00:00', ?)",
                (game_id, f"s1:match:{match_n}", outcome),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name) "
                "VALUES (?, ?, 'opponent', 'Human')",
                (f"{game_id}:opp", game_id),
            )
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at, games_played, wins, losses, draws, unknown_results) "
            "VALUES ('s1', '2026-08-11T11:00:00', 3, 2, 1, 0, 0)"
        )
        conn.execute("DELETE FROM schema_migrations WHERE version = 15")
    AnalyticsStore.apply_pending_migrations(conn)

    games = [row[0] for row in conn.execute("SELECT id FROM games ORDER BY id")]
    matches = [row[0] for row in conn.execute("SELECT id FROM matches ORDER BY id")]
    session = conn.execute(
        "SELECT games_played, wins, losses FROM tracker_sessions WHERE id = 's1'"
    ).fetchone()
    store.close()

    assert games == ["s1:match:3:game:1"]  # both Welcome Deck games removed
    assert matches == ["s1:match:3"]
    assert session == (1, 1, 0)  # aggregates recomputed


def test_snapshot_commander_rows_group_brawl_records(tmp_path):
    from mtga_tracker.dashboard import dashboard_snapshot

    db_path = tmp_path / "analytics.sqlite3"
    conn = sqlite3.connect(db_path)
    AnalyticsStore.ensure_schema(conn)
    with conn:
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('s1', '2026-08-12T10:00:00')"
        )
        conn.execute(
            "INSERT INTO cards (name, color_identity, first_seen_at) "
            "VALUES ('Freyalise, Skyshroud Partisan', 'G', '2026-08-12T10:00:00')"
        )
        for n, (outcome, mine, theirs) in enumerate(
            (
                ("win", "Freyalise, Skyshroud Partisan", "Kaalia of the Vast"),
                ("loss", "Freyalise, Skyshroud Partisan", "Kaalia of the Vast"),
                ("win", "Freyalise, Skyshroud Partisan", "Atraxa, Grand Unifier"),
            ),
            start=1,
        ):
            conn.execute(
                "INSERT INTO matches (id, session_id, format) VALUES (?, 's1', 'Historic Brawl')",
                (f"m{n}",),
            )
            game_id = f"g{n}"
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, started_at, ended_at, outcome) "
                "VALUES (?, 's1', ?, '2026-08-12T10:00:00', '2026-08-12T10:10:00', ?)",
                (game_id, f"m{n}", outcome),
            )
            for role, commander in (("player", mine), ("opponent", theirs)):
                pid = f"{game_id}:participant:{role}"
                conn.execute(
                    "INSERT INTO participants (id, game_id, role, display_name) "
                    "VALUES (?, ?, ?, ?)",
                    (pid, game_id, role, role),
                )
                conn.execute(
                    "INSERT INTO participant_commanders (participant_id, card_name) "
                    "VALUES (?, ?)",
                    (pid, commander),
                )
    conn.close()

    snapshot = dashboard_snapshot(db_path)
    yours = snapshot["your_commanders"]
    faced = snapshot["faced_commanders"]
    assert yours == [
        {
            "commander": "Freyalise, Skyshroud Partisan",
            "colors": "G",
            "games": 3,
            "wins": 2,
            "losses": 1,
            "win_rate": yours[0]["win_rate"],
        }
    ]
    assert yours[0]["win_rate"] is not None and round(yours[0]["win_rate"], 1) == 66.7
    assert [(row["commander"], row["games"], row["wins"]) for row in faced] == [
        ("Kaalia of the Vast", 2, 1),
        ("Atraxa, Grand Unifier", 1, 1),
    ]


def test_snapshot_brawl_summary_counts_all_brawl_queues(tmp_path):
    from mtga_tracker.dashboard import dashboard_snapshot

    db_path = tmp_path / "analytics.sqlite3"
    conn = sqlite3.connect(db_path)
    AnalyticsStore.ensure_schema(conn)
    with conn:
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('s1', '2026-08-12T10:00:00')"
        )
        for n, (fmt, outcome) in enumerate(
            (
                ("Play_Brawl_Historic", "win"),
                ("Play_Brawl_Historic", "loss"),
                ("Brawl_Ladder", "win"),
                ("Ladder", "win"),  # constructed — must stay out of the Brawl record
            ),
            start=1,
        ):
            conn.execute(
                "INSERT INTO matches (id, session_id, format) VALUES (?, 's1', ?)",
                (f"m{n}", fmt),
            )
            conn.execute(
                "INSERT INTO games (id, session_id, match_id, started_at, ended_at, outcome) "
                "VALUES (?, 's1', ?, '2026-08-12T10:00:00', '2026-08-12T10:10:00', ?)",
                (f"g{n}", f"m{n}", outcome),
            )
            conn.execute(
                "INSERT INTO participants (id, game_id, role, display_name) "
                "VALUES (?, ?, 'player', 'you')",
                (f"g{n}:p", f"g{n}"),
            )
    conn.close()

    brawl = dashboard_snapshot(db_path)["brawl"]
    assert (brawl["games"], brawl["wins"], brawl["losses"]) == (3, 2, 1)
    assert round(brawl["win_rate"], 1) == 66.7
    assert [(q["format_label"], q["games"], q["wins"]) for q in brawl["queues"]] == [
        ("Historic Brawl", 2, 1),
        ("Brawl (Ranked)", 1, 1),
    ]


def _seed_events_backfill_db(conn):
    """Minimal game with a timeline that exercises every backfilled stat."""
    conn.execute(
        "INSERT INTO tracker_sessions (id, started_at) VALUES ('s1', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO matches (id, session_id) VALUES ('m1', 's1')"
    )
    conn.execute(
        "INSERT INTO games (id, match_id, session_id, game_number) VALUES ('g1', 'm1', 's1', 1)"
    )
    conn.execute(
        "INSERT INTO participants (id, game_id, role) VALUES ('p1', 'g1', 'player')"
    )
    conn.execute(
        "INSERT INTO participants (id, game_id, role) VALUES ('p2', 'g1', 'opponent')"
    )
    for participant in ("p1", "p2"):
        conn.execute(
            "INSERT INTO game_participant_stats (game_id, participant_id) VALUES ('g1', ?)",
            (participant,),
        )
    for name, primary_type in (
        ("Bear", "Creature"),
        ("Shrine", "Enchantment"),
        ("Forest", "Land"),
        ("Bolt", "Instant"),
        ("Ox", "Creature"),
    ):
        conn.execute(
            "INSERT INTO cards (name, primary_type, first_seen_at) VALUES (?, ?, '2026-01-01')",
            (name, primary_type),
        )
    events = [
        # (turn, actor_role, event_type, text)
        (1, "player", "cast", "[0:10] You: cast [Bear (Creature 2/2)]"),
        (1, "player", "cast", "[0:11] You: cast [Shrine (Enchantment)]"),
        (2, "opponent", "cast", "[0:20] Opponent: cast [Ox (Creature 4/4)]"),
        (3, "player", "cast", "[0:30] You: cast [Bolt (Instant)] -> [Ox (4/4)]"),
        # Player's creature and enchantment are removed.
        (4, "player", "zone", "[0:40] You: [Bear] was destroyed"),
        (4, "player", "zone", "[0:41] You: [Shrine] was exiled"),
        # A lethal-damage death must NOT count (combat vs burn is unknowable).
        (4, "opponent", "zone", "[0:42] Opponent: [Ox] was put into graveyard (lethal damage)"),
        # Opponent's land is destroyed on turn 5, replaced on turn 6.
        (5, "opponent", "zone", "[0:50] Opponent: [Forest] was destroyed"),
        (6, "opponent", "land", "[0:60] Opponent: played [Forest (Land)]"),
        # Opponent recasts the Ox, then it gets bounced back to hand.
        (6, "opponent", "cast", "[0:61] Opponent: cast [Ox (Creature 4/4)]"),
        (7, "opponent", "zone", "[0:70] Opponent: returned [Ox] to hand"),
        # An exile of something never seen on the battlefield is ignored.
        (7, "player", "zone", "[0:71] You: [Bolt] was exiled"),
        # Player's spell gets countered.
        (8, "player", "cast", "[0:80] You: cast [Bear (Creature 2/2)]"),
        (8, None, "stack_fail", "\t[0:81] Stack: [Bear (Creature 2/2)] [countered]"),
    ]
    for index, (turn, actor, event_type, text) in enumerate(events):
        conn.execute(
            "INSERT INTO game_events (session_id, game_id, event_time, turn_number, actor_role, event_type, text) "
            "VALUES ('s1', 'g1', ?, ?, ?, ?, ?)",
            (f"2026-01-01T00:00:{index:02d}", turn, actor, event_type, text),
        )


def test_events_backfill_fills_null_stats_only(tmp_path):
    from mtga_tracker.events_backfill import backfill_game_stats_from_events

    store = AnalyticsStore(tmp_path / "backfill.sqlite3")
    conn = store.connect()
    _seed_events_backfill_db(conn)
    # Pretend one column was live-tracked: it must survive the backfill.
    conn.execute(
        "UPDATE game_participant_stats SET creatures_removed = 9 "
        "WHERE participant_id = 'p1'"
    )

    updated = backfill_game_stats_from_events(conn)
    assert updated == 2

    player = dict(
        zip(
            (
                "creatures_removed",
                "noncreatures_removed",
                "creatures_bounced",
                "noncreatures_bounced",
                "lands_lost",
                "lands_replaced",
                "spells_countered",
            ),
            conn.execute(
                "SELECT creatures_removed, noncreatures_removed, creatures_bounced, "
                "noncreatures_bounced, lands_lost, lands_replaced, spells_countered "
                "FROM game_participant_stats WHERE participant_id = 'p1'"
            ).fetchone(),
        )
    )
    opponent = dict(
        zip(
            (
                "creatures_removed",
                "noncreatures_removed",
                "creatures_bounced",
                "noncreatures_bounced",
                "lands_lost",
                "lands_replaced",
                "spells_countered",
            ),
            conn.execute(
                "SELECT creatures_removed, noncreatures_removed, creatures_bounced, "
                "noncreatures_bounced, lands_lost, lands_replaced, spells_countered "
                "FROM game_participant_stats WHERE participant_id = 'p2'"
            ).fetchone(),
        )
    )

    assert player["creatures_removed"] == 9  # live value preserved
    assert player["noncreatures_removed"] == 1  # Shrine exiled from battlefield
    assert player["spells_countered"] == 1  # second Bear countered
    assert player["creatures_bounced"] == 0
    assert opponent["creatures_removed"] == 0  # lethal damage skipped
    assert opponent["lands_lost"] == 1
    assert opponent["lands_replaced"] == 1
    assert opponent["creatures_bounced"] == 1  # Ox returned to hand
    assert opponent["spells_countered"] == 0


def test_v21_repairs_month_day_swapped_timestamps(tmp_path):
    """Day-first-locale rows stored as Sep/Oct 8 return to 9/10 August.

    Regression for the Italian user whose Aug 8-12 games (dd/mm logs read as
    mm/dd) landed months in the future and scrambled every date-sorted view.
    The session row's system-clock started_at anchors the repair.
    """
    store = AnalyticsStore(tmp_path / "swapped.sqlite3")
    conn = store.connect()
    conn.execute(
        "INSERT INTO tracker_sessions (id, started_at) "
        "VALUES ('s-aug9', '2026-08-09T20:00:00')"
    )
    conn.execute(
        "INSERT INTO matches (id, session_id, started_at) "
        "VALUES ('m-bad', 's-aug9', '2026-09-08T20:05:00')"  # true date: 9 Aug
    )
    conn.executemany(
        "INSERT INTO games (id, session_id, match_id, started_at, ended_at) "
        "VALUES (?, 's-aug9', 'm-bad', ?, ?)",
        [
            # dd/mm read as mm/dd: 9 Aug -> 8 Sep; crossing midnight 10 Aug -> 8 Oct.
            ("g-swapped", "2026-09-08T20:05:00", "2026-09-08T20:20:00"),
            ("g-midnight", "2026-10-08T00:10:00", "2026-10-08T00:25:00"),
            # Legit row close to the session: must be untouched.
            ("g-fine", "2026-08-09T21:00:00", "2026-08-09T21:15:00"),
            # Far away AND swap would not land in the session: untouched.
            ("g-old", "2026-05-02T12:00:00", "2026-05-02T12:30:00"),
        ],
    )
    conn.execute(
        "INSERT INTO game_events (session_id, game_id, event_time, text) "
        "VALUES ('s-aug9', 'g-swapped', '2026-09-08T20:06:00', 'Turn 1 begins')"
    )
    conn.execute(
        "INSERT INTO rank_snapshots (session_id, captured_at, season_ordinal, "
        "rank_class, rank_level, rank_step, rank_steps) "
        "VALUES ('s-aug9', '2026-09-08T20:21:00', 91, 'Gold', 4, 1, 6)"
    )

    AnalyticsStore._migrate_v21_repair_swapped_log_dates(conn)

    started = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT id, started_at, ended_at FROM games")
    }
    assert started["g-swapped"] == ("2026-08-09T20:05:00", "2026-08-09T20:20:00")
    assert started["g-midnight"] == ("2026-08-10T00:10:00", "2026-08-10T00:25:00")
    assert started["g-fine"] == ("2026-08-09T21:00:00", "2026-08-09T21:15:00")
    assert started["g-old"] == ("2026-05-02T12:00:00", "2026-05-02T12:30:00")
    assert conn.execute("SELECT started_at FROM matches WHERE id='m-bad'").fetchone()[0] == (
        "2026-08-09T20:05:00"
    )
    assert conn.execute("SELECT event_time FROM game_events").fetchone()[0] == (
        "2026-08-09T20:06:00"
    )
    assert conn.execute("SELECT captured_at FROM rank_snapshots").fetchone()[0] == (
        "2026-08-09T20:21:00"
    )
    # Running again is a no-op (repaired rows now sit inside the window).
    AnalyticsStore._migrate_v21_repair_swapped_log_dates(conn)
    assert conn.execute(
        "SELECT started_at FROM games WHERE id='g-swapped'"
    ).fetchone()[0] == "2026-08-09T20:05:00"


def test_backfill_card_mana_fills_null_rows_only(tmp_path):
    db_path = tmp_path / "mana.sqlite3"
    conn = sqlite3.connect(db_path)
    AnalyticsStore.ensure_schema(conn)
    conn.executemany(
        "INSERT INTO cards (name, first_seen_at) VALUES (?, '2026-08-01T00:00:00')",
        [
            ("Forsaken Miner (Creature 2/2)",),  # base name lookup
            ("Fire // Ice",),                    # split: front-face fallback
            ("Already Set",),
            ("Unknown To Arena",),
        ],
    )
    conn.execute(
        "UPDATE cards SET mana_cost = '{9}', mana_value = 9 WHERE name = 'Already Set'"
    )
    index = {
        "Forsaken Miner": ("{B}", 1.0),
        "Fire": ("{1}{R}", 2.0),
        "Already Set": ("{1}", 1.0),
    }

    updated = AnalyticsStore.backfill_card_mana(conn, index)

    assert updated == 2
    rows = dict(
        (name, (cost, value))
        for name, cost, value in conn.execute(
            "SELECT name, mana_cost, mana_value FROM cards"
        )
    )
    assert rows["Forsaken Miner (Creature 2/2)"] == ("{B}", 1.0)
    assert rows["Fire // Ice"] == ("{1}{R}", 2.0)
    assert rows["Already Set"] == ("{9}", 9.0)  # non-NULL rows never touched
    assert rows["Unknown To Arena"] == (None, None)
    # Idempotent: nothing left to fill for known names.
    assert AnalyticsStore.backfill_card_mana(conn, index) == 0
