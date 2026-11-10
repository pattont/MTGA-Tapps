"""Stored per-game values (game_derived): a stored row must always equal a
fresh computation, and anything that could make it differ must drop it."""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime

from mtga_tracker import dashboard, game_derived
from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.backup import MERGE_SKIP_TABLES
from mtga_tracker.draw_quality import draw_quality_metrics
from tests.test_dashboard import _sample_dashboard_db
from tests.test_tracker_combat_winner import make_tracker


def _history_db(tmp_path):
    """The sample database plus: a second deck with a decklist, a revealed
    opponent card, and a game of the first deck that submitted no decklist."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into cards (id, name, first_seen_at, color_identity, mana_cost, mana_value) "
            "values (?, ?, '2026-06-01T00:00:00', ?, ?, ?)",
            [
                (901, "Floodpits Drowner", "U", "{1}{U}", 2.0),
                (902, "Island", "U", "", 0.0),
                (903, "Cut Down", "B", "{B}", 1.0),
                (904, "Mystery Relic", None, None, None),
            ],
        )
        conn.executemany(
            "insert into games (id, session_id, match_id, game_number, started_at, outcome) "
            "values (?, 'session-1', 'match-1', 1, ?, ?)",
            [
                ("game-b", "2026-06-05T00:01:00", "loss"),
                ("game-c", "2026-06-06T00:01:00", "win"),
            ],
        )
        conn.executemany(
            "insert into participants (id, game_id, seat_id, role, display_name, deck_name, deck_size) "
            "values (?, ?, ?, ?, ?, ?, ?)",
            [
                ("player-b", "game-b", 1, "player", "Tapps", "Dimir Tempo", 60),
                ("opponent-b", "game-b", 2, "opponent", "Rival", None, None),
                ("player-c", "game-c", 1, "player", "Tapps", "Listless Deck", 60),
                ("opponent-c", "game-c", 2, "opponent", "Other", None, None),
            ],
        )
        conn.executemany(
            "insert into game_deck_cards "
            "(game_id, participant_id, card_id, arena_id, display_name, type_category, "
            "deck_zone, quantity) values (?, ?, ?, ?, ?, ?, 'deck', ?)",
            [
                ("game-b", "player-b", 901, 70901, "Floodpits Drowner", "Creature", 36),
                ("game-b", "player-b", 902, 70902, "Island", "Land", 24),
            ],
        )
        conn.executemany(
            "insert into game_opening_hand_cards "
            "(game_id, participant_id, display_name, type_category, hand_position, copy_number) "
            "values (?, ?, ?, ?, ?, 1)",
            [("game-b", "player-b", "Island", "Land", index) for index in range(1, 6)]
            + [("game-b", "player-b", "Floodpits Drowner", "Creature", index) for index in (6, 7)]
            + [("game-c", "player-c", "Forest", "Land", index) for index in range(1, 4)],
        )
        conn.executemany(
            "insert into game_drawn_cards "
            "(game_id, participant_id, display_name, type_category, turn_number, draw_position, "
            "copy_number) values (?, ?, ?, ?, ?, ?, 1)",
            [("game-b", "player-b", "Island", "Land", index, index) for index in range(1, 8)],
        )
        conn.executemany(
            "insert into game_card_summary "
            "(game_id, participant_id, card_id, display_name, type_category, played_count) "
            "values (?, ?, ?, ?, ?, ?)",
            [
                ("game-b", "opponent-b", 903, "Cut Down", "Instant", 1),
                ("game-b", "opponent-b", 904, "Mystery Relic", "Artifact", 1),
                ("game-c", "opponent-c", 903, "Cut Down", "Instant", 2),
            ],
        )
    return db_path


def _players(conn):
    return [
        (str(row[0]), row[1])
        for row in conn.execute(
            "select id, deck_size from participants where role = 'player' order by id"
        )
    ]


def _pages(db_path):
    """Every payload that reads a stored value, as plain JSON."""
    return json.loads(
        json.dumps(
            {
                "snapshot": dashboard.dashboard_snapshot(db_path),
                "games": dashboard.all_games(db_path),
                "deck": dashboard.deck_detail(db_path, "Dimir Tempo"),
                "deck2": dashboard.deck_detail(db_path, "Boros Mouse"),
                "opponent": dashboard.opponent_detail(db_path, "Rival"),
            },
            sort_keys=True,
            default=str,
        )
    )


def test_stored_values_equal_computed_values_and_pages_do_not_change(tmp_path):
    db_path = _history_db(tmp_path)
    before = _pages(db_path)
    with sqlite3.connect(db_path) as conn:
        players = _players(conn)
        ids = [pid for pid, _ in players]
        games = [str(row[0]) for row in conn.execute("select id from games")]
        computed_quality = dashboard._compute_draw_quality_batch(conn, players)
        computed_colors = dashboard._compute_participant_deck_color_map(conn, ids)
        computed_letters = dashboard._compute_opponent_letters(conn, games)

        assert game_derived.store(conn, ids) == len(ids)
        conn.commit()

        assert dashboard._draw_quality_batch(conn, players) == computed_quality
        assert dashboard._participant_deck_color_map(conn, ids) == computed_colors
        stored_letters = dashboard._opponent_letters(conn, games)
        for game_id in games:
            for fmt in ("Play", "Brawl_Ladder"):
                assert dashboard._display_opponent_colors(
                    fmt, *stored_letters.get(game_id, ("", ""))
                ) == dashboard._display_opponent_colors(
                    fmt, *computed_letters.get(game_id, ("", ""))
                )
        stored = game_derived.load_by_participant(conn, ids, draw_quality=True)
    # The game with its own decklist keeps its verdict; it floods on lands.
    assert stored["player-b"].draw_quality["is_flood"] is True
    assert stored["player-b"].deck_colors == "U"
    assert stored["player-b"].opp_revealed == "BC"
    assert _pages(db_path) == before


def test_a_game_that_borrows_a_decklist_is_never_answered_from_storage(tmp_path):
    """Its land rate comes from another game's list, which can change."""
    db_path = _history_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        game_derived.store(conn, ["player-c"])
        conn.commit()
        row = game_derived.load_by_participant(conn, ["player-c"], draw_quality=True)["player-c"]
        assert row.draw_quality is None
        assert row.deck_colors is None
        estimated = dashboard._draw_quality_batch(conn, [("player-c", 60)])["player-c"]
        assert estimated["land_rate_source"] == "estimate"

        # A later game of the same deck submits a list: the old game borrows it.
        conn.execute(
            "insert into games (id, session_id, match_id, game_number, started_at, outcome) "
            "values ('game-d', 'session-1', 'match-1', 1, '2026-06-07T00:01:00', 'win')"
        )
        conn.execute(
            "insert into participants (id, game_id, seat_id, role, display_name, deck_name) "
            "values ('player-d', 'game-d', 1, 'player', 'Tapps', 'Listless Deck')"
        )
        conn.executemany(
            "insert into game_deck_cards "
            "(game_id, participant_id, arena_id, display_name, type_category, deck_zone, quantity) "
            "values ('game-d', 'player-d', ?, ?, ?, 'deck', ?)",
            [(70911, "Forest", "Land", 17), (70912, "Llanowar Elves", "Creature", 23)],
        )
        conn.commit()

        borrowed = dashboard._draw_quality_batch(conn, [("player-c", 60)])["player-c"]
    assert borrowed["land_rate_source"] == "deck_history"
    assert (borrowed["deck_size"], borrowed["deck_lands"]) == (40, 17)


def _land_sections(conn):
    """The Overview sections answered from the summary columns."""
    return json.loads(
        json.dumps(
            {
                "readiness": dashboard._mana_readiness_rows(conn, "1 = 1", []),
                "opener": dashboard._opener_land_rows(conn, "1 = 1", []),
                "profile": dashboard._deck_land_profile(conn, "1 = 1", []),
            }
        )
    )


def test_summary_columns_equal_the_dict_and_the_card_rows(tmp_path):
    db_path = _history_db(tmp_path)
    for unknown_turn in (False, True):
        with sqlite3.connect(db_path) as conn:
            conn.execute("delete from game_derived")
            if unknown_turn:
                # One land of the flooding game was drawn on a turn not captured.
                conn.execute(
                    "update game_drawn_cards set turn_number = NULL "
                    "where participant_id = 'player-b' and draw_position = 3"
                )
            conn.commit()
            players = _players(conn)
            ids = [pid for pid, _ in players]
            computed = dashboard._compute_draw_quality_batch(conn, players)
            live, live_dicts = dashboard._draw_summary_batch(conn, players)
            assert live_dicts == computed
            own = {
                pid
                for pid, quality in computed.items()
                if quality["land_rate_source"] == "decklist"
            }
            assert "player-b" in own and "player-c" not in own
            opening = dashboard._compute_opening_lands(conn, ids)
            turns = dashboard._compute_land_draw_turns(conn, ids)
            sections = _land_sections(conn)

            game_derived.store(conn, ids)
            conn.commit()

            stored, recomputed = dashboard._draw_summary_batch(conn, players)
            # Only a game with its own decklist is answered from its row.
            assert set(ids) - set(recomputed) == own
            assert stored == live
            for pid in ids:
                assert stored[pid] == game_derived.draw_summary(computed[pid])
                assert [type(value) for value in stored[pid]] == [
                    type(value) for value in game_derived.draw_summary(computed[pid])
                ]
            assert stored["player-b"].is_flood is True
            for pid, cards, lands, text, seen in conn.execute(
                "select participant_id, opening_cards, opening_lands, land_draw_turns, "
                "cards_seen from game_derived"
            ):
                assert (cards, lands) == opening[pid]
                unknown_last = sorted(turns.get(pid, []), key=lambda turn: (turn is None, turn))
                assert game_derived.decode_turns(text) == unknown_last
                assert (seen is None) == (pid not in own)
            assert _land_sections(conn) == sections
    with sqlite3.connect(db_path) as conn:
        text = conn.execute(
            "select land_draw_turns from game_derived where participant_id = 'player-b'"
        ).fetchone()[0]
    assert text == "1,2,4,5,6,7,?"


def test_land_draw_turns_keep_every_draw():
    for turns in ([], [3], [5, 2, 2], [None], [4, None, 1, None]):
        text = game_derived.encode_turns(turns)
        assert sorted(
            game_derived.decode_turns(text), key=lambda turn: (turn is None, turn)
        ) == sorted(turns, key=lambda turn: (turn is None, turn))
    assert game_derived.encode_turns([]) == ""
    assert game_derived.decode_turns(None) == []


def test_a_table_made_before_the_summary_columns_is_read_as_empty(tmp_path):
    db_path = _history_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
    before = _pages(db_path)
    with sqlite3.connect(db_path) as conn:
        sections = _land_sections(conn)
        total = len(_players(conn))
        conn.executescript(
            """
            DROP TABLE game_derived;
            CREATE TABLE game_derived (
                participant_id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                rules_version INTEGER NOT NULL,
                draw_quality_json TEXT,
                deck_colors TEXT,
                opp_revealed TEXT NOT NULL DEFAULT '',
                opp_commander TEXT NOT NULL DEFAULT '',
                computed_at TEXT NOT NULL
            );
            INSERT INTO game_derived
            VALUES ('player-b', 'game-b', 1, '{"is_flood": "stale"}', 'WUBRG', '', '', 'x');
            """
        )
        assert not game_derived.columns_ready(conn)
        assert game_derived.load_draw_summaries(conn, ["player-b"]) == {}
        assert _land_sections(conn) == sections
    assert _pages(db_path) == before
    # Nothing is written until the tracker has opened the database.
    assert game_derived.run_backfill(db_path, pause=0.0) == 0

    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        conn.commit()
        assert game_derived.columns_ready(conn)
    assert game_derived.run_backfill(db_path, pause=0.0) == total
    with sqlite3.connect(db_path) as conn:
        assert _land_sections(conn) == sections
        found = game_derived.load_draw_summaries(conn, ["player-b", "player-c"])
        assert set(found) == {"player-b"}
    assert _pages(db_path) == before


def test_rows_from_older_rules_are_ignored_and_recomputed(tmp_path):
    db_path = _history_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        players = _players(conn)
        ids = [pid for pid, _ in players]
        expected = dashboard._compute_draw_quality_batch(conn, players)
        game_derived.store(conn, ids)
        conn.execute(
            "update game_derived set rules_version = ?, draw_quality_json = ?, deck_colors = 'WUBRG'",
            (game_derived.RULES_VERSION - 1, json.dumps({"is_flood": "stale"})),
        )
        conn.commit()

        assert game_derived.load_by_participant(conn, ids) == {}
        assert dashboard._draw_quality_batch(conn, players) == expected
        assert sorted(game_derived.pending(conn)) == sorted(ids)

    assert game_derived.run_backfill(db_path, pause=0.0) == len(ids)

    with sqlite3.connect(db_path) as conn:
        assert game_derived.pending(conn) == []
        versions = {row[0] for row in conn.execute("select rules_version from game_derived")}
        assert versions == {game_derived.RULES_VERSION}
        assert dashboard._draw_quality_batch(conn, players) == expected
        assert game_derived.load_by_participant(conn, ["player-b"])["player-b"].deck_colors == "U"


def test_backfill_fills_every_game_newest_first_and_drops_rows_of_deleted_games(tmp_path):
    db_path = _history_db(tmp_path)
    before = _pages(db_path)
    with sqlite3.connect(db_path) as conn:
        total = len(_players(conn))
        assert game_derived.pending(conn, 1) == ["player-c"]  # the newest game
        conn.execute(
            "insert into game_derived (participant_id, game_id, rules_version, computed_at) "
            "values ('gone', 'gone-game', ?, 'x')",
            (game_derived.RULES_VERSION,),
        )

    assert game_derived.run_backfill(db_path, pause=0.0) == total
    assert game_derived.run_backfill(db_path, pause=0.0) == 0

    with sqlite3.connect(db_path) as conn:
        stored = {row[0] for row in conn.execute("select participant_id from game_derived")}
        assert stored == {pid for pid, _ in _players(conn)}
    assert _pages(db_path) == before


def test_backfill_stops_when_asked_and_resumes_later(tmp_path, monkeypatch):
    db_path = _history_db(tmp_path)
    monkeypatch.setattr(game_derived, "BATCH", 1)
    stop = threading.Event()
    real_store = game_derived.store

    def store_then_stop(conn, ids):
        stop.set()
        return real_store(conn, ids)

    monkeypatch.setattr(game_derived, "store", store_then_stop)
    assert game_derived.run_backfill(db_path, stop, pause=0.0) == 1

    monkeypatch.setattr(game_derived, "store", real_store)
    with sqlite3.connect(db_path) as conn:
        left = len(game_derived.pending(conn, 100))
    assert left >= 1
    assert game_derived.run_backfill(db_path, pause=0.0) == left


def test_learning_a_cards_colour_drops_the_rows_of_games_that_used_it(tmp_path):
    db_path = _history_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        ids = [pid for pid, _ in _players(conn)]
        game_derived.store(conn, ids)
        conn.commit()
        assert game_derived.cards_missing_metadata(conn)[0] >= {904}

        # The Arena card database now knows the card: red.
        conn.execute("update cards set color_identity = 'R', mana_cost = '{2}' where id = 904")
        removed = game_derived.invalidate_for_cards(conn, [904])
        conn.commit()

        assert removed == 1
        left = {row[0] for row in conn.execute("select participant_id from game_derived")}
        assert left == set(ids) - {"player-b"}
        # The reader computes the game again, now with the colour.
        letters = dashboard._opponent_letters(conn, ["game-b"])["game-b"]
        assert dashboard._display_opponent_colors("Play", *letters) == "BR"
        assert game_derived.invalidate_for_cards(conn, []) == 0


def test_tracker_card_backfill_invalidates_only_when_a_card_was_learned(tmp_path):
    db_path = _history_db(tmp_path)
    tracker = make_tracker()

    class CardDb:
        def __init__(self, colors):
            self.colors = colors

        def color_identity_index_by_name(self):
            return self.colors

        def mana_cost_index_by_name(self):
            return {}

        def stats_index_by_name(self):
            return {}

    with sqlite3.connect(db_path) as conn:
        ids = [pid for pid, _ in _players(conn)]
        game_derived.store(conn, ids)
        conn.commit()

        tracker.card_db = CardDb({"Some Other Card": "G"})
        tracker._backfill_card_metadata(conn)
        assert conn.execute("select count(*) from game_derived").fetchone()[0] == len(ids)
        assert not getattr(tracker, "_game_derived_refill_needed", False)

        tracker.card_db = CardDb({"Mystery Relic": "R"})
        tracker._backfill_card_metadata(conn)
        left = {row[0] for row in conn.execute("select participant_id from game_derived")}
    assert left == set(ids) - {"player-b"}
    assert tracker._game_derived_refill_needed is True


def test_tracker_stores_a_finished_games_values_with_the_game(tmp_path):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.game_start_time = datetime(2026, 7, 22, 12, 0, 0)
    tracker.game_state.game_end_time = datetime(2026, 7, 22, 12, 3, 0)
    tracker.game_state.turns_taken_by_seat[1].add(1)

    assert tracker._persist_game_analytics("win", "Opponent conceded") is True

    with sqlite3.connect(tracker._console_db_path) as conn:
        row = conn.execute(
            "select d.game_id = p.game_id, d.rules_version from game_derived d "
            "join participants p on p.id = d.participant_id and p.role = 'player'"
        ).fetchone()
        assert game_derived.pending(conn) == []
    assert row == (1, game_derived.RULES_VERSION)
    assert not game_derived.WRITE_LOCK.locked()


def test_a_failed_derived_write_never_costs_the_game(tmp_path, monkeypatch, capsys):
    tracker = make_tracker()
    tracker._console_db_path = tmp_path / "analytics.sqlite3"
    tracker.game_state.in_match = True
    tracker.game_state.player_seat_id = 1
    tracker.game_state.opponent_seat_id = 2
    tracker.game_state.game_start_time = datetime(2026, 7, 22, 12, 0, 0)
    tracker.game_state.game_end_time = datetime(2026, 7, 22, 12, 3, 0)
    tracker.game_state.turns_taken_by_seat[1].add(1)

    def broken(_conn, _ids):
        raise KeyError("a bug in the derived computation")

    monkeypatch.setattr(game_derived, "store", broken)

    assert tracker._persist_game_analytics("loss", "Life reached 0") is True

    with sqlite3.connect(tracker._console_db_path) as conn:
        assert conn.execute("select outcome from games").fetchone() == ("loss",)
        assert conn.execute("select count(*) from game_derived").fetchone()[0] == 0
    assert "could not save derived values" in capsys.readouterr().out
    assert not game_derived.WRITE_LOCK.locked()


def test_stored_values_are_local_and_emptied_by_a_reset(tmp_path):
    assert game_derived.TABLE in MERGE_SKIP_TABLES
    assert game_derived.TABLE in dashboard.RESET_TABLES
    # A database that never had the table (an older file opened read-only).
    conn = sqlite3.connect(":memory:")
    assert game_derived.load_by_participant(conn, ["x"]) == {}
    assert game_derived.invalidate_all(conn) == 0
    assert game_derived.invalidate_for_cards(conn, [1]) == 0
    AnalyticsStore.ensure_schema(conn)
    assert game_derived.table_exists(conn)


def test_canonical_letters_keep_what_colour_normalisation_reads():
    from mtga_tracker.colors import normalize_colors

    for letters in ("", "C", "UCBCUC", "wgC", "RC", "CC"):
        assert normalize_colors(game_derived.canonical_letters(letters)) == normalize_colors(
            letters
        )
        assert bool(game_derived.canonical_letters(letters)) == bool(letters)
    assert game_derived.canonical_letters(None) == ""


#: draw_quality_metrics' answers for the fixed games below, at RULES_VERSION.
EXPECTED_RULES_DIGEST = "ee339fce73d28576"


def test_rules_version_is_bumped_when_draw_quality_changes():
    """Stored rows hold draw_quality_metrics' output. If this digest changes,
    the function now answers differently for a finished game: bump
    game_derived.RULES_VERSION (so every stored row is recomputed) and update
    EXPECTED_RULES_DIGEST in the same change. The version is part of the
    digest, so a bump for another reason (version 2 added the summary
    columns) changes it too."""

    def hand(lands, spells):
        return [{"display_name": "Island", "type_category": "Land"}] * lands + [
            {"display_name": "Opt", "type_category": "Instant"}
        ] * spells

    def draws(pattern):
        return [
            {
                "display_name": "Island" if kind == "L" else "Opt",
                "type_category": "Land" if kind == "L" else "Instant",
                "draw_position": index,
                "source": "draw",
            }
            for index, kind in enumerate(pattern, start=1)
        ]

    cases = [
        (hand(3, 4), draws("LSLSSLSS"), 8, 60, 24),
        (hand(5, 2), draws("LLLLLSLL"), 8, 60, 24),
        (hand(1, 6), draws("SSSSSS"), 6, 60, 24),
        (hand(2, 5), draws("SLLLLSSSLLLLLL"), 14, 60, 22),
        (hand(4, 3), draws("LSL"), 5, 40, 17),
        (hand(3, 4), [], 0, 100, 38),
        ([], [], 0, 60, None),
    ]
    answers = [
        draw_quality_metrics(opener, drawn, recorded, size, deck_lands=lands)
        for opener, drawn, recorded, size, lands in cases
    ]
    digest = hashlib.sha256(
        json.dumps([game_derived.RULES_VERSION, answers], sort_keys=True).encode()
    ).hexdigest()[:16]
    assert digest == EXPECTED_RULES_DIGEST
