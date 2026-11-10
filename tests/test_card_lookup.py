"""The card page and card search on a long history: rows are found by name
through the card-name indexes, search answers from a per-name summary, and
neither changes a number."""

import json
import sqlite3
import threading

import pytest

from mtga_tracker import dashboard, game_derived
from tests.test_game_derived import _history_db

INDEX_NAMES = {name for name, _table in game_derived.CARD_NAME_INDEXES}


def _card_db(tmp_path):
    """The history database plus one card recorded under several names (bare,
    with a "(Type)" suffix, in another case), names with characters LIKE
    treats specially, and a Jump In game search must leave out."""
    db_path = _history_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into matches (id, session_id, format, queue, event_name, best_of) "
            "values ('match-jump', 'session-1', 'Jump_In_2026', 'Jump_In_2026', 'Jump_In_2026', 1)"
        )
        conn.execute(
            "insert into games (id, session_id, match_id, game_number, started_at, outcome) "
            "values ('game-jump', 'session-1', 'match-jump', 1, '2026-06-07T00:01:00', 'win')"
        )
        conn.executemany(
            "insert into participants (id, game_id, seat_id, role, display_name, deck_name) "
            "values (?, 'game-jump', ?, ?, ?, ?)",
            [
                ("player-jump", 1, "player", "Tapps", "Jump Deck"),
                ("opponent-jump", 2, "opponent", "Sparky", None),
            ],
        )
        conn.executemany(
            "insert into game_card_summary "
            "(game_id, participant_id, display_name, type_category, played_count, drawn_count) "
            "values (?, ?, ?, ?, ?, ?)",
            [
                # One card, four spellings; two of them in the same game.
                ("game-b", "player-b", "Opt (Instant)", "Instant", 2, 2),
                ("game-c", "player-c", "Opt", None, 1, 1),
                ("game-c", "opponent-c", "Opt (Instant)", "Instant", 1, 0),
                ("game-b", "opponent-b", "opt (Instant)", "Instant", 3, 1),
                ("game-1", "opponent-1", "opt", "Instant", 5, 0),
                ("game-1", "player-1", "Optimistic Scavenger (Creature 1/1)", "Creature", 1, 1),
                ("game-2", "player-2", "Optimistic Scavenger (Creature 2/2)", "Creature", 1, 1),
                ("game-2", "opponent-2", "Mjölnir, Hammer of Thor (Artifact)", "Artifact", 1, 0),
                ("game-b", "player-b", "100% Clean_Up", "Sorcery", 1, 0),
                ("game-c", "player-c", "1000 Cleanups", "Sorcery", 1, 0),
                ("game-jump", "player-jump", "Opt (Instant)", "Instant", 4, 1),
                ("game-jump", "player-jump", "Jump Start", "Sorcery", 1, 0),
            ],
        )
        conn.executemany(
            "insert into game_opening_hand_cards "
            "(game_id, participant_id, display_name, type_category, hand_position, copy_number) "
            "values (?, ?, ?, 'Instant', ?, 1)",
            [
                ("game-b", "player-b", "Opt", 8),
                ("game-c", "player-c", "Opt (Instant)", 8),
                ("game-c", "player-c", "opt", 9),
            ],
        )
        conn.executemany(
            "insert into game_drawn_cards "
            "(game_id, participant_id, display_name, type_category, turn_number, draw_position, "
            "copy_number) values (?, ?, ?, 'Instant', ?, ?, 1)",
            [
                ("game-b", "player-b", "Opt", 9, 9),
                ("game-b", "player-b", "opt (instant)", 10, 10),
            ],
        )
        conn.execute(
            "insert into game_deck_cards "
            "(game_id, participant_id, arena_id, display_name, type_category, deck_zone, "
            "quantity) values ('game-b', 'player-b', 70950, 'Opt', 'Instant', 'deck', 4)"
        )
        conn.execute(
            "insert into cards (id, name, first_seen_at, color_identity, mana_cost, mana_value) "
            "values (950, 'Opt', '2026-06-01T00:00:00', 'U', '{U}', 1.0)"
        )
    return db_path


def _card_pages(db_path):
    names = ["Opt", "opt", "Optimistic Scavenger", "Cut Down", "Island", "100% Clean_Up"]
    pages = {}
    for name in names:
        for label, filters in (
            ("all", {}),
            ("deck", {"deck": "Dimir Tempo"}),
            ("format", {"fmt": "Play"}),
            ("since", {"since": "2026-06-05"}),
        ):
            try:
                pages[f"{name}/{label}"] = dashboard.card_detail(db_path, name, **filters)
            except LookupError as exc:
                pages[f"{name}/{label}"] = str(exc)
    return json.loads(json.dumps(pages, sort_keys=True, default=str))


def test_card_page_counts_a_name_exactly_and_its_typed_suffix_in_any_case(tmp_path):
    """What the name match has always meant, which the indexed form must keep:
    the exact spelling, or the name before " (" in any case."""
    db_path = _card_db(tmp_path)

    page = dashboard.card_detail(db_path, "Opt")

    # "Opt", "Opt (Instant)" and "opt (Instant)" count; the bare "opt" and
    # "Optimistic Scavenger" do not, nor does the Jump In game.
    assert page["all_usage"]["total_played"] == 2 + 1 + 1 + 3
    assert page["all_usage"]["games_seen"] == 2
    assert page["summary"]["total_played"] == 2 + 1
    assert page["opener_impact"]["games_in_opener"] == 2
    assert page["opener_impact"]["times_drawn"] == 2
    assert page["multiplicity"]["games"] == 2
    assert dashboard.card_detail(db_path, "opt")["all_usage"]["total_played"] == 5 + 2 + 1 + 3


def test_card_page_is_the_same_with_and_without_the_name_indexes(tmp_path):
    db_path = _card_db(tmp_path)
    before = _card_pages(db_path)
    assert isinstance(before["Opt/all"], dict) and isinstance(before["Opt/deck"], dict)

    with sqlite3.connect(db_path) as conn:
        assert game_derived.build_card_name_indexes(conn) == len(INDEX_NAMES)
        assert game_derived.build_card_name_indexes(conn) == 0

    assert _card_pages(db_path) == before


def test_card_name_lookup_is_answered_by_the_name_indexes(tmp_path):
    """Both halves of the name match must stay indexable: a plain
    ``display_name = ?`` is not (the index is NOCASE) and turns every card
    page back into a scan of the table."""
    db_path = _card_db(tmp_path)
    variants = ["Unholy Annex", "Unholy Annex // Ritual Chamber"]
    with sqlite3.connect(db_path) as conn:
        game_derived.build_card_name_indexes(conn)
        for index, table in game_derived.CARD_NAME_INDEXES:
            plan = " | ".join(
                str(row[3])
                for row in conn.execute(
                    f"EXPLAIN QUERY PLAN SELECT t.id FROM {table} t "
                    f"WHERE {dashboard._card_name_clause('t', variants)}",
                    dashboard._card_name_params(variants),
                )
            )
            assert index in plan, plan
            # A covering-index scan may follow the two index searches; a scan
            # of the table itself must not.
            assert "SCAN t" not in plan.replace("SCAN t USING", ""), plan


def test_background_pass_builds_the_name_indexes_and_can_be_stopped(tmp_path):
    db_path = _card_db(tmp_path)

    def indexes():
        with sqlite3.connect(db_path) as conn:
            return {
                row[0]
                for row in conn.execute("select name from sqlite_master where type = 'index'")
            } & INDEX_NAMES

    assert indexes() == set()
    stop = threading.Event()
    stop.set()
    game_derived.run_backfill(db_path, stop, pause=0.0)
    assert indexes() == set()

    game_derived.run_backfill(db_path, pause=0.0)
    assert indexes() == INDEX_NAMES
    with sqlite3.connect(db_path) as conn:
        collations = {
            row[0]: conn.execute(f"PRAGMA index_xinfo({row[0]})").fetchone()[4]
            for row in conn.execute("select name from sqlite_master where type = 'index'")
            if row[0] in INDEX_NAMES
        }
    assert set(collations.values()) == {"NOCASE"}


def _search_row_by_row(db_path, query, limit):
    """Card search as it was first written: every matching row read and
    grouped in Python. The summary must give this answer for any query."""
    clean_query = (dashboard._clean_card_name(query) or "").strip()
    if not clean_query:
        return []
    escaped = clean_query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.game_id, s.display_name, s.type_category, s.played_count, p.role,
                   COALESCE(p.deck_name, '(unknown)'), COALESCE(g.started_at, g.ended_at)
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id
            JOIN games g ON g.id = s.game_id
            WHERE s.display_name LIKE ? ESCAPE '!' COLLATE NOCASE
              AND NOT EXISTS (
                SELECT 1 FROM matches mj
                WHERE mj.id = g.match_id AND mj.format LIKE 'Jump!_In%' ESCAPE '!'
              )
            ORDER BY s.id
            """,
            (f"%{escaped}%",),
        ).fetchall()
    matches = {}
    for game_id, display_name, type_category, played, role, deck_name, seen_at in rows:
        card_name = dashboard._clean_card_name(display_name) or display_name
        entry = matches.setdefault(
            card_name.casefold(),
            {
                "card_name": card_name,
                "type_category": type_category or "Other",
                "game_ids": set(),
                "deck_names": set(),
                "total_played": 0,
                "last_seen_at": None,
            },
        )
        entry["game_ids"].add(game_id)
        if role == "player" and deck_name != "(unknown)":
            entry["deck_names"].add(deck_name)
        entry["total_played"] += int(played or 0)
        if seen_at and (entry["last_seen_at"] is None or seen_at > entry["last_seen_at"]):
            entry["last_seen_at"] = seen_at
    folded = clean_query.casefold()
    ranked = sorted(
        matches.values(),
        key=lambda item: (
            (
                0
                if item["card_name"].casefold() == folded
                else 1 if item["card_name"].casefold().startswith(folded) else 2
            ),
            -len(item["game_ids"]),
            -item["total_played"],
            item["card_name"].casefold(),
        ),
    )
    return [
        {
            "card_name": item["card_name"],
            "type_category": item["type_category"],
            "games_seen": len(item["game_ids"]),
            "deck_count": len(item["deck_names"]),
            "total_played": item["total_played"],
            "last_seen_at": item["last_seen_at"],
        }
        for item in ranked[: max(1, min(limit, 25))]
    ]


SEARCHES = [
    "opt",
    "Opt",
    "OPT",
    "o",
    "t",
    "opt (instant)",
    "(instant",
    "instant",
    "(creature 2",
    "creature",
    "(",
    "1/1",
    "mj",
    "MJÖ",
    "ö",
    "Ö",
    "100%",
    "%",
    "_",
    "clean_up",
    "cleanup",
    "!",
    "jump",
    "island",
    "ghost",
    " opt ",
    "zzzz",
]


@pytest.mark.parametrize("limit", [1, 8, 25])
def test_search_gives_the_row_by_row_answer_for_every_kind_of_query(tmp_path, limit):
    db_path = _card_db(tmp_path)
    found_something = 0
    for query in SEARCHES:
        expected = _search_row_by_row(db_path, query, limit)
        assert dashboard.search_cards(db_path, query, limit) == expected, query
        found_something += bool(expected)
    assert found_something > len(SEARCHES) // 2


def test_search_counts_a_game_once_across_a_cards_names_and_skips_jump_in(tmp_path):
    db_path = _card_db(tmp_path)

    opt = dashboard.search_cards(db_path, "opt")[0]
    typed_suffix = dashboard.search_cards(db_path, "opt (instant")[0]

    assert opt["card_name"] == "Opt"
    # game-b and game-c hold two spellings each, game-1 one; Jump In is left out.
    assert opt["games_seen"] == 3
    assert opt["total_played"] == 2 + 1 + 1 + 3 + 5
    assert opt["deck_count"] == 2
    assert opt["last_seen_at"] == "2026-06-06T00:01:00"
    # Only the suffixed spellings match here: a subset of the card's names.
    assert typed_suffix["games_seen"] == 2
    assert typed_suffix["total_played"] == 2 + 1 + 3
    assert dashboard.search_cards(db_path, "jump") == []


def test_search_summary_is_built_once_and_again_when_the_history_changes(tmp_path, monkeypatch):
    db_path = _card_db(tmp_path)
    dashboard.clear_response_cache()
    builds = []
    real_build = dashboard._build_card_search_index

    def counting_build(conn):
        builds.append(1)
        return real_build(conn)

    monkeypatch.setattr(dashboard, "_build_card_search_index", counting_build)

    for query in ("o", "op", "opt"):
        dashboard.search_cards(db_path, query)
    assert len(builds) == 1
    assert dashboard.search_cards(db_path, "brand new") == []

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into games (id, session_id, match_id, game_number, started_at, outcome) "
            "values ('game-d', 'session-1', 'match-1', 1, '2026-06-08T00:01:00', 'win')"
        )
        conn.execute(
            "insert into participants (id, game_id, seat_id, role, display_name, deck_name) "
            "values ('player-d', 'game-d', 1, 'player', 'Tapps', 'Dimir Tempo')"
        )
        conn.execute(
            "insert into game_card_summary "
            "(game_id, participant_id, display_name, type_category, played_count) "
            "values ('game-d', 'player-d', 'Brand New Card', 'Creature', 1)"
        )

    assert [row["card_name"] for row in dashboard.search_cards(db_path, "brand new")] == [
        "Brand New Card"
    ]
    assert len(builds) == 2
    dashboard.clear_response_cache()
    dashboard.search_cards(db_path, "opt")
    assert len(builds) == 3


def test_a_search_result_cannot_change_the_summary_it_came_from(tmp_path):
    db_path = _card_db(tmp_path)
    first = dashboard.search_cards(db_path, "opt")
    first[0]["games_seen"] = -1

    assert dashboard.search_cards(db_path, "opt")[0]["games_seen"] == 3
