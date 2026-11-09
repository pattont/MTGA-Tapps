"""Large-history guards: the scaled-database builder, the payload dump/diff
tool, and the rule that no dashboard query binds one parameter per game."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from mtga_tracker import dashboard
from tests.test_dashboard import _sample_dashboard_db

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_scaled_db = _load_script("build_scaled_db")
dashboard_payloads = _load_script("dashboard_payloads")


def _counts(db_path):
    with sqlite3.connect(db_path) as conn:
        return {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("tracker_sessions", "matches", "games", "participants", "cards")
        }


def test_scaled_copy_multiplies_the_history_and_keeps_it_consistent(tmp_path):
    source = _sample_dashboard_db(tmp_path)
    before = _counts(source)
    out = tmp_path / "scaled.sqlite3"

    result = build_scaled_db.scale_database(source, out, 4)

    after = _counts(out)
    assert result["games"] == after["games"] == before["games"] * 4
    for table in ("tracker_sessions", "matches", "participants"):
        assert after[table] == before[table] * 4
    # The shared card dictionary is not history and is not replicated.
    assert after["cards"] == before["cards"]
    assert _counts(source) == before
    with sqlite3.connect(out) as conn:
        orphans = conn.execute(
            """
            select
              (select count(*) from games g left join matches m on m.id = g.match_id
               where m.id is null)
              + (select count(*) from participants p left join games g on g.id = p.game_id
                 where g.id is null)
              + (select count(*) from game_card_summary s
                 left join participants p on p.id = s.participant_id where p.id is null)
            """
        ).fetchone()[0]
        newest_original, newest_replica = conn.execute(
            """
            select (select max(started_at) from games where id not like '%~%'),
                   (select max(started_at) from games where id like '%~%')
            """
        ).fetchone()
        player_names, opponent_names = conn.execute(
            """
            select count(distinct case when role = 'player' then display_name end),
                   count(distinct case when role = 'opponent' then display_name end)
            from participants
            """
        ).fetchone()
    assert orphans == 0
    # Replicas are older history: the real games stay the newest.
    assert newest_replica < newest_original
    # One player throughout, a new opponent in every replica.
    assert player_names == 1
    assert opponent_names == 4
    assert dashboard.all_games(out)["total"] == before["games"] * 4


def test_scaled_copy_shifts_tracker_session_ids_with_their_dates():
    sessions = ["20261109T010548731963", "legacy-session"]
    delta = build_scaled_db.timedelta(days=10)
    mapping = build_scaled_db._session_id_map(sessions, 2, delta)
    remap = build_scaled_db._id_remapper(mapping, 2)

    assert mapping["20261109T010548731963"] == "20261030T010548731963"
    assert mapping["legacy-session"] == "legacy-session~2"
    # A game id keeps starting with its session's id.
    assert remap("20261109T010548731963:match:1:game:2") == "20261030T010548731963:match:1:game:2"
    assert remap("game-1") == "game-1~2"
    assert remap(None) is None
    assert build_scaled_db._shift_timestamp("2026-11-09T01:06:05", delta) == "2026-10-30T01:06:05"
    assert (
        build_scaled_db._shift_timestamp("2026-11-09T01:06:05.250000", delta)
        == "2026-10-30T01:06:05.250000"
    )
    assert build_scaled_db._shift_timestamp("not a date", delta) == "not a date"


def test_scaled_copy_refuses_to_overwrite_its_source(tmp_path):
    source = _sample_dashboard_db(tmp_path)
    with pytest.raises(ValueError):
        build_scaled_db.scale_database(source, source, 2)


@pytest.mark.skipif(
    not hasattr(sqlite3.Connection, "setlimit"), reason="pinning SQLite limits needs Python 3.11"
)
def test_read_endpoints_work_with_more_games_than_sqlite_binds(tmp_path, monkeypatch):
    """Windows' SQLite binds at most 32,766 parameters per statement, and a
    long history holds more games than that. Same shape at a small scale: more
    games than the pinned limit, read through every page's endpoint."""
    source = _sample_dashboard_db(tmp_path)
    games_before = _counts(source)["games"]
    limit = 100
    factor = limit // games_before + 20
    db_path = tmp_path / "scaled.sqlite3"
    build_scaled_db.scale_database(source, db_path, factor)
    assert _counts(db_path)["games"] > limit

    def read_everything():
        return json.loads(
            json.dumps(
                {
                    "snapshot": dashboard.dashboard_snapshot(db_path),
                    "trend": dashboard.dashboard_snapshot(db_path, trend_days=0),
                    "games": dashboard.all_games(db_path),
                    "deck": dashboard.deck_detail(db_path, "Boros Mouse"),
                    "game": dashboard.game_detail(db_path, "game-1"),
                    "opponents": dashboard.opponents_list(db_path),
                    "search": dashboard.global_search(db_path, "Boros", 8),
                },
                sort_keys=True,
                default=str,
            )
        )

    unlimited = read_everything()

    real_connect = sqlite3.connect

    def limited_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, limit)
        return conn

    monkeypatch.setattr(sqlite3, "connect", limited_connect)
    monkeypatch.setattr(dashboard, "_SQL_IN_CHUNK", 40)

    # Slicing the id lists changes nothing in any payload.
    assert read_everything() == unlimited
    assert unlimited["games"]["total"] > limit


def test_in_chunks_puts_every_id_in_exactly_one_slice(monkeypatch):
    monkeypatch.setattr(dashboard, "_SQL_IN_CHUNK", 3)

    slices = list(dashboard._in_chunks(str(index) for index in range(8)))

    assert [ids for _, ids in slices] == [["0", "1", "2"], ["3", "4", "5"], ["6", "7"]]
    assert [marks for marks, _ in slices] == ["?,?,?", "?,?,?", "?,?"]
    assert list(dashboard._in_chunks([])) == []


def test_payload_dump_is_repeatable_and_diff_reports_a_changed_number(tmp_path, capsys):
    db_path = _sample_dashboard_db(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"

    assert dashboard_payloads.dump(db_path, first, 3, 0, None) == 0
    assert dashboard_payloads.dump(db_path, second, 3, 0, None) == 0
    assert (first / "snapshot.json").is_file()
    assert (first / "games.json").is_file()
    assert json.loads((first / dashboard_payloads.TIMINGS_FILE).read_text())["snapshot"]["bytes"]
    assert dashboard_payloads.diff(first, second, 8) == 0

    games = json.loads((second / "games.json").read_text())
    games["games"][0]["total_turns"] = 99
    (second / "games.json").write_text(json.dumps(games))
    capsys.readouterr()

    assert dashboard_payloads.diff(first, second, 8) == 1
    assert ".games[0].total_turns" in capsys.readouterr().out


def _two_deck_db(tmp_path):
    """The sample database plus a second deck and a game with no deck name."""
    db_path = _sample_dashboard_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into games (id, session_id, match_id, game_number, started_at, outcome) "
            "values (?, 'session-1', 'match-1', 1, ?, ?)",
            [
                ("game-b", "2026-06-05T00:01:00", "loss"),
                ("game-c", "2026-06-06T00:01:00", "win"),
            ],
        )
        conn.executemany(
            "insert into participants (id, game_id, seat_id, role, display_name, deck_name) "
            "values (?, ?, ?, ?, ?, ?)",
            [
                ("player-b", "game-b", 1, "player", "Tapps", "Dimir Tempo"),
                ("opponent-b", "game-b", 2, "opponent", "Rival", None),
                ("player-c", "game-c", 1, "player", "Tapps", None),
                ("opponent-c", "game-c", 2, "opponent", "Other", None),
            ],
        )
        conn.executemany(
            "insert into game_card_summary "
            "(game_id, participant_id, display_name, type_category, played_count) "
            "values (?, ?, ?, ?, ?)",
            [
                ("game-b", "player-b", "Floodpits Drowner (Creature 2/1)", "Creature", 3),
                ("game-b", "player-b", "Island", "Land", 5),
                ("game-c", "player-c", "Llanowar Elves (Creature 1/1)", "Creature", 2),
            ],
        )
    return db_path


def test_deck_maps_for_named_decks_match_the_whole_history_maps(tmp_path):
    """Pages ask for the decks they show; the answer for a deck must be the
    one the every-deck computation gives."""
    db_path = _two_deck_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        all_visuals = dashboard._deck_visuals(conn)
        all_colors = dashboard._deck_color_map(conn)
        assert {"Boros Mouse", "Dimir Tempo", "(unknown)"} <= set(all_visuals)
        for name in all_visuals:
            assert dashboard._deck_visuals(conn, [name]) == {name: all_visuals[name]}
        for name in all_colors:
            assert dashboard._deck_color_map(conn, [name]) == {name: all_colors[name]}
        assert dashboard._deck_visuals(conn, set(all_visuals)) == all_visuals
        assert dashboard._deck_color_map(conn, set(all_colors)) == all_colors
        # No decks asked for: no work, no rows.
        assert dashboard._deck_visuals(conn, []) == {}
        assert dashboard._deck_color_map(conn, []) == {}
        assert dashboard._deck_visuals(conn, ["No Such Deck"]) == {}


def test_deck_filter_matches_named_decks_and_games_without_a_deck_name(tmp_path):
    db_path = _two_deck_db(tmp_path)

    named = dashboard.all_games(db_path, deck="Dimir Tempo")
    unnamed = dashboard.all_games(db_path, deck="(unknown)")
    everything = dashboard.all_games(db_path)

    assert [row["game_id"] for row in named["games"]] == ["game-b"]
    assert [row["game_id"] for row in unnamed["games"]] == ["game-c"]
    assert unnamed["games"][0]["deck_name"] == "(unknown)"
    sample_games = dashboard.all_games(db_path, deck="Boros Mouse")["total"]
    assert sample_games >= 1
    assert everything["total"] == named["total"] + unnamed["total"] + sample_games
    assert dashboard.dashboard_snapshot(db_path, deck="Dimir Tempo")["summary"]["games"] == 1
    assert dashboard.deck_detail(db_path, "Dimir Tempo")["summary"]["games"] == 1


def test_format_normalisation_is_remembered_and_unchanged():
    from mtga_tracker import format_normalizer

    cases = [
        ("Ladder", 1),
        ("Traditional_Ladder", 3),
        ("Historic_Play", 3),
        ("Brawl_Ladder", 1),
        ("CubeDraft_Powered_20260908", 1),
        (None, 3),
        ("", 1),
    ]
    for raw, best_of in cases:
        remembered = format_normalizer.normalize_match_format(raw, default_best_of=best_of)
        computed = format_normalizer._normalize_match_format_uncached(raw, best_of)
        assert remembered == computed
        # The same frozen object on the next ask.
        assert format_normalizer.normalize_match_format(raw, default_best_of=best_of) is remembered
    # Anything that is not a plain string or None is computed, never cached.
    assert format_normalizer.normalize_match_format(12345).label == "Unknown"
