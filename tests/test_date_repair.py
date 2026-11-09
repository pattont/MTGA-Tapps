"""Month/day-swapped date repair (issue #51)."""

from mtga_tracker.analytics import AnalyticsStore
from mtga_tracker.date_repair import repair_swapped_log_dates, session_clock_time
from mtga_tracker.db_audit import audit_database, repair_database


def _seed_us_log_on_day_first_windows(conn):
    """A US log (11/4/2026) read day-first: 4 November stored as 11 April.

    The second session began after a break, so even its started_at came
    from the misread log; only its id holds the true clock time.
    """
    conn.execute(
        "INSERT INTO tracker_sessions (id, started_at) "
        "VALUES ('20261104T213000000000', '2026-04-11T21:30:00')"
    )
    conn.execute(
        "INSERT INTO matches (id, session_id, started_at, ended_at) VALUES "
        "('m1', '20261104T213000000000', '2026-04-11T21:54:39', '2026-04-11T22:04:18')"
    )
    conn.executemany(
        "INSERT INTO games (id, session_id, match_id, started_at, ended_at) "
        "VALUES (?, '20261104T213000000000', 'm1', ?, ?)",
        [
            ("g-swapped", "2026-04-11T21:54:39", "2026-04-11T22:04:18"),
            ("g-fine", "2026-11-04T22:10:00", "2026-11-04T22:20:00"),
        ],
    )
    conn.execute(
        "INSERT INTO game_turns (game_id, turn_number, started_at, ended_at) "
        "VALUES ('g-swapped', 1, '2026-04-11T21:55:00', '2026-04-11T21:56:00')"
    )


def test_session_clock_time_reads_minted_ids():
    assert session_clock_time("20261104T213000123456").isoformat() == "2026-11-04T21:30:00"
    assert session_clock_time("s-aug9") is None


def test_repair_anchors_on_the_session_id_clock(tmp_path):
    conn = AnalyticsStore(tmp_path / "a.sqlite3").connect()
    _seed_us_log_on_day_first_windows(conn)

    assert repair_swapped_log_dates(conn, dry_run=True) == 4
    assert conn.execute("SELECT started_at FROM games WHERE id='g-swapped'").fetchone()[0] == (
        "2026-04-11T21:54:39"
    )
    assert repair_swapped_log_dates(conn) == 4

    rows = dict(conn.execute("SELECT id, started_at FROM games").fetchall())
    assert rows == {"g-swapped": "2026-11-04T21:54:39", "g-fine": "2026-11-04T22:10:00"}
    assert conn.execute("SELECT started_at FROM tracker_sessions").fetchone()[0] == (
        "2026-11-04T21:30:00"
    )
    assert conn.execute("SELECT started_at, ended_at FROM matches").fetchone() == (
        "2026-11-04T21:54:39",
        "2026-11-04T22:04:18",
    )
    assert conn.execute("SELECT started_at FROM game_turns").fetchone()[0] == (
        "2026-11-04T21:55:00"
    )
    assert repair_swapped_log_dates(conn) == 0


def test_repair_can_be_limited_to_merged_sessions(tmp_path):
    conn = AnalyticsStore(tmp_path / "b.sqlite3").connect()
    _seed_us_log_on_day_first_windows(conn)

    assert repair_swapped_log_dates(conn, session_ids=["other"]) == 0
    assert repair_swapped_log_dates(conn, session_ids=[]) == 0
    assert repair_swapped_log_dates(conn, session_ids=["20261104T213000000000"]) == 4


def test_migration_37_reruns_the_repair():
    steps = dict(AnalyticsStore.migration_steps())
    assert steps[37] is AnalyticsStore._migrate_v21_repair_swapped_log_dates


def test_db_audit_reports_and_repairs_swapped_dates(tmp_path):
    db_path = tmp_path / "audit.sqlite3"
    store = AnalyticsStore(db_path)
    conn = store.connect()
    _seed_us_log_on_day_first_windows(conn)
    conn.commit()
    conn.close()

    findings = [f for f in audit_database(db_path) if f.code == "SWAPPED_LOG_DATES"]
    assert len(findings) == 1 and findings[0].current_value == "4"

    repair_database(db_path)

    assert not [f for f in audit_database(db_path) if f.code == "SWAPPED_LOG_DATES"]
