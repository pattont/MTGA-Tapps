import sqlite3
from datetime import datetime

from mtga_tracker.analytics import AnalyticsStore, SessionSnapshot
from mtga_tracker.rank_progress import (
    iter_constructed_rank_snapshots,
    parse_constructed_rank_snapshot,
)


def test_parse_constructed_rank_snapshot_matches_arena_display_step():
    line = (
        "[UnityCrossThreadLogger]7/23/2026 1:25:18 AM "
        "<== RankGetCombinedRankInfo(request-id) "
        '{"constructedSeasonOrdinal":91,"constructedClass":"Platinum",'
        '"constructedLevel":3,"constructedStep":4,'
        '"constructedMatchesWon":60,"constructedMatchesLost":43}'
    )

    assert parse_constructed_rank_snapshot(line) == {
        "season_ordinal": 91,
        "rank_class": "Platinum",
        "rank_level": 3,
        "rank_step": 3,
        "rank_steps": 6,
        "raw_step": 4,
        "matches_won": 60,
        "matches_lost": 43,
        "mythic_percentile": None,
        "mythic_rank": None,
    }


def test_parse_constructed_rank_snapshot_ignores_outgoing_request():
    assert (
        parse_constructed_rank_snapshot(
            '[UnityCrossThreadLogger]==> RankGetCombinedRankInfo {"id":"request-id","request":"{}"}'
        )
        is None
    )


def test_iter_constructed_rank_snapshots_reads_timestamped_responses(tmp_path):
    log_path = tmp_path / "Player.log"
    log_path.write_text(
        "\n".join(
            [
                "[UnityCrossThreadLogger]7/23/2026 1:20:24 AM",
                "<== RankGetCombinedRankInfo(first)",
                '{"constructedSeasonOrdinal":91,"constructedClass":"Platinum","constructedLevel":3,'
                '"constructedStep":3,"constructedMatchesWon":59,"constructedMatchesLost":43}',
                "[UnityCrossThreadLogger]7/23/2026 1:25:18 AM",
                "<== RankGetCombinedRankInfo(second)",
                '{"constructedSeasonOrdinal":91,"constructedClass":"Platinum","constructedLevel":3,'
                '"constructedStep":4,"constructedMatchesWon":60,"constructedMatchesLost":43}',
            ]
        ),
        encoding="utf-8",
    )

    rows = list(iter_constructed_rank_snapshots(log_path))

    assert [row[0].isoformat() for row in rows] == [
        "2026-07-23T01:20:24",
        "2026-07-23T01:25:18",
    ]
    assert [row[1]["rank_step"] for row in rows] == [2, 3]


def test_rank_snapshot_store_deduplicates_unchanged_rank(tmp_path):
    db_path = tmp_path / "analytics.sqlite3"
    store = AnalyticsStore(db_path)
    session = SessionSnapshot(
        session_id="session-1",
        started_at=datetime(2026, 7, 23, 1, 0),
        games_played=0,
        wins=0,
        losses=0,
        unknown_results=0,
    )
    values = {
        "season_ordinal": 91,
        "rank_class": "Platinum",
        "rank_level": 3,
        "rank_step": 3,
        "rank_steps": 6,
        "raw_step": 4,
        "matches_won": 60,
        "matches_lost": 43,
        "mythic_percentile": None,
        "mythic_rank": None,
    }

    assert store.record_rank_snapshot(
        session, captured_at=datetime(2026, 7, 23, 1, 25, 18), **values
    )
    assert not store.record_rank_snapshot(
        session, captured_at=datetime(2026, 7, 23, 1, 26, 18), **values
    )
    store.close()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rank_snapshots").fetchone()[0] == 1
