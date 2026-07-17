import sqlite3

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.db_audit import audit_database, repair_database
from mtga_tracker.format_normalizer import format_label, is_momir_format, normalize_match_format


def test_format_normalizer_labels_constructed_queues():
    assert format_label("Play") == "Standard Best-of-1 (Unranked)"
    assert format_label("Unknown") == "Standard Best-of-1 (Unranked)"
    assert format_label("Ladder") == "Standard Best-of-1 (Ranked)"
    assert format_label("Ladder", default_best_of=3) == "Standard Best-of-3 (Ranked)"
    assert format_label("Constructed_BestOf3") == "Standard Best-of-3 (Unranked)"
    assert format_label("TraditionalLadder") == "Standard Best-of-3 (Ranked)"
    assert format_label("TraditionalStandard") == "Standard Best-of-3 (Unranked)"
    assert format_label("MWM_SlowStart_20260602") == "Midweek Magic - Slow Start"
    assert normalize_match_format("Play").best_of == 1
    assert normalize_match_format("TraditionalStandard").best_of == 3


def test_momir_format_detection_handles_midweek_and_plain_labels():
    assert is_momir_format("MWM_Momir")
    assert is_momir_format("Midweek Magic - Momir")
    assert not is_momir_format("MWM_SlowStart_20260602")


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
