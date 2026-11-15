"""A long history's Overview: statements side by side, a trend range that
reuses the page, and the page made ready at launch. The numbers must be the
ones the page gives built in line, as it always was."""

import importlib.util
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from mtga_tracker import dashboard, game_derived
from tests.test_dashboard import _sample_dashboard_db

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _scaled_db(tmp_path, factor=12):
    spec = importlib.util.spec_from_file_location("build_scaled_db", SCRIPTS / "build_scaled_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = _sample_dashboard_db(tmp_path)
    db_path = tmp_path / "scaled.sqlite3"
    module.scale_database(source, db_path, factor)
    return db_path


def _side_by_side(monkeypatch, reads=4):
    """Every page counts as a long history on a machine with cores to spare."""
    monkeypatch.setattr(dashboard, "_SIDE_BY_SIDE_MIN_GAMES", 0)
    monkeypatch.setattr(dashboard, "_SIDE_BY_SIDE_READS", reads)
    monkeypatch.setattr(dashboard.os, "cpu_count", lambda: 8)


def _in_line(monkeypatch):
    monkeypatch.setattr(dashboard, "_SIDE_BY_SIDE_MIN_GAMES", 10**9)


def _read_threads():
    return [t for t in threading.enumerate() if t.name.startswith("dashboard-read")]


@pytest.fixture(autouse=True)
def _fresh_cache():
    dashboard.clear_response_cache()
    dashboard.forget_warm_views()
    yield
    dashboard.clear_response_cache()
    dashboard.forget_warm_views()


OVERVIEWS = (
    {},
    {"days": 30},
    {"deck": "Boros Mouse"},
    {"fmt": "Play"},
    {"since": "2026-01-01", "until": "2026-12-31"},
    {"trend_days": 0},
    {"trend_games": 25},
    {"deck": "No Such Deck"},
    {"days": 1},
)


@pytest.mark.parametrize("stored", [False, True])
def test_overview_side_by_side_is_the_overview_in_line(tmp_path, monkeypatch, stored):
    db_path = _scaled_db(tmp_path)
    if stored:
        game_derived.run_backfill(db_path, pause=0)

    def overviews():
        return [
            json.dumps(dashboard.dashboard_snapshot(db_path, **filters), sort_keys=True)
            for filters in OVERVIEWS
        ]

    _in_line(monkeypatch)
    in_line = overviews()

    ran_on = set()
    combat_rows = dashboard._combat_deck_rows

    def noting_thread(*args, **kwargs):
        ran_on.add(threading.current_thread().name)
        return combat_rows(*args, **kwargs)

    monkeypatch.setattr(dashboard, "_combat_deck_rows", noting_thread)
    for reads in (2, 4):
        _side_by_side(monkeypatch, reads)
        assert overviews() == in_line
    # The page really was spread over other threads, and none outlives it.
    assert any(name.startswith("dashboard-read") for name in ran_on)
    assert _read_threads() == []


def test_side_by_side_only_for_a_long_history_with_cores_and_someone_waiting(monkeypatch):
    monkeypatch.setattr(dashboard, "_SIDE_BY_SIDE_MIN_GAMES", 2000)
    monkeypatch.setattr(dashboard, "_SIDE_BY_SIDE_READS", 4)
    cores = {"count": 8}
    monkeypatch.setattr(dashboard.os, "cpu_count", lambda: cores["count"])
    assert dashboard._side_by_side_reads(1999) == 1
    assert dashboard._side_by_side_reads(2000) == 4
    cores["count"] = 3
    assert dashboard._side_by_side_reads(50_000) == 2
    for few in (2, 1, None):
        cores["count"] = few
        assert dashboard._side_by_side_reads(50_000) == 1
    cores["count"] = 8
    dashboard._unhurried.on = True
    try:
        assert dashboard._side_by_side_reads(50_000) == 1
    finally:
        dashboard._unhurried.on = False
    assert dashboard._side_by_side_reads(50_000) == 4


def test_a_rebuild_nobody_waits_for_is_built_in_line(tmp_path, monkeypatch):
    db_path = _sample_dashboard_db(tmp_path)
    _side_by_side(monkeypatch)
    seen = []

    def compute():
        seen.append(dashboard._side_by_side_reads(50_000))
        return b"{}"

    dashboard._build_behind(db_path, "/api/snapshot", "behind", compute)
    assert seen == [1]
    # The thread is not left marked: its next page may be one someone awaits.
    assert dashboard._side_by_side_reads(50_000) == 4


def test_a_failing_read_fails_the_page_and_leaves_no_thread(tmp_path, monkeypatch):
    db_path = _scaled_db(tmp_path, factor=3)

    def broken(conn, where, params):
        raise sqlite3.OperationalError("no such table: opponent cards")

    monkeypatch.setattr(dashboard, "_opponent_threat_rows", broken)
    for arrange in (_in_line, _side_by_side):
        arrange(monkeypatch)
        with pytest.raises(sqlite3.OperationalError, match="opponent cards"):
            dashboard.dashboard_snapshot(db_path)
        assert _read_threads() == []


def test_page_reads_in_line_run_at_once_in_order_and_raise_there(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    order = []
    with dashboard._PageReads(uri, conn) as reads:
        reads.expect(1)  # a normal history: nothing changes
        first = reads.call(lambda c: order.append("first") or threading.current_thread().name)
        second = reads.call(lambda c, word: order.append(word) or c, "second", first=True)
        assert order == ["first", "second"]
        assert first.result() == threading.current_thread().name
        assert second.result() is conn
        assert reads.row("SELECT COUNT(*) FROM games").result()[0] > 0
        with pytest.raises(sqlite3.OperationalError):
            reads.rows("SELECT * FROM no_such_table")
    assert _read_threads() == []
    conn.close()


def test_page_reads_side_by_side_use_their_own_connections(tmp_path, monkeypatch):
    db_path = _sample_dashboard_db(tmp_path)
    _side_by_side(monkeypatch, reads=3)
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    gate = threading.Event()
    started = threading.Semaphore(0)

    def held(c):
        started.release()
        gate.wait(5)
        return (threading.current_thread().name, c is conn)

    with dashboard._PageReads(uri, conn) as reads:
        reads.expect(50_000)
        assert len(_read_threads()) == 2
        # Two reads occupy the two other threads until the gate opens.
        blocked = [reads.call(held), reads.call(held)]
        assert started.acquire(timeout=5) and started.acquire(timeout=5)
        rows = reads.rows("SELECT id FROM games ORDER BY id")
        count = reads.row("SELECT COUNT(*) FROM games")
        broken = reads.rows("SELECT * FROM no_such_table")
        # The calling thread works through the queue while it waits.
        assert count.result()[0] == len(rows.result())
        with pytest.raises(sqlite3.OperationalError):
            broken.result()
        gate.set()
        for name, callers_connection in (read.result() for read in blocked):
            assert name.startswith("dashboard-read")
            assert not callers_connection
        # A read can be asked for twice.
        assert rows.result() == rows.result()
    assert _read_threads() == []
    conn.close()


def test_page_reads_drop_what_is_still_queued_when_the_page_fails(tmp_path, monkeypatch):
    db_path = _sample_dashboard_db(tmp_path)
    _side_by_side(monkeypatch, reads=2)
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    gate = threading.Event()
    started = threading.Event()
    ran = []

    def held(c):
        started.set()
        gate.wait(5)

    with pytest.raises(ValueError):
        with dashboard._PageReads(uri, conn) as reads:
            reads.expect(50_000)
            reads.call(held)
            assert started.wait(5)
            never = reads.call(lambda c: ran.append("never"))
            threading.Timer(0.05, gate.set).start()
            raise ValueError("the page failed")
    assert ran == []
    with pytest.raises(RuntimeError):
        never.result()
    assert _read_threads() == []
    conn.close()


TRENDS = (
    {"trend_days": 30},
    {"trend_days": 0},
    {"trend_days": 7},
    {"trend_games": 10},
    {"trend_games": 100},
)


def test_a_trend_range_gives_the_same_body_without_rebuilding_the_overview(tmp_path, monkeypatch):
    db_path = _scaled_db(tmp_path, factor=4)
    expected = {}
    for filters in ({}, {"deck": "Boros Mouse"}, {"days": 30, "fmt": "Play"}):
        for trend in ({},) + TRENDS:
            arguments = {**filters, **trend}
            expected[json.dumps(arguments, sort_keys=True)] = dashboard.render_snapshot_json(
                dashboard.dashboard_snapshot(db_path, **arguments)
            )

    built = []
    snapshot = dashboard.dashboard_snapshot

    def counting(*args, **kwargs):
        built.append(kwargs)
        return snapshot(*args, **kwargs)

    monkeypatch.setattr(dashboard, "dashboard_snapshot", counting)
    for key, body in expected.items():
        assert dashboard.snapshot_body(db_path, **json.loads(key)) == body, key
    # One Overview per set of filters, however many trend ranges were asked.
    assert len(built) == 3
    assert all("trend_days" not in call and "trend_games" not in call for call in built)
    # Asked again, a range is the same bytes object: nothing is put together twice.
    first = dashboard.snapshot_body(db_path, trend_games=10)
    assert dashboard.snapshot_body(db_path, trend_games=10) is first
    assert len(built) == 3


def test_snapshot_trend_is_the_overviews_trend(tmp_path):
    db_path = _scaled_db(tmp_path, factor=4)
    for filters in ({}, {"deck": "Boros Mouse"}, {"fmt": "Play"}):
        for trend in TRENDS:
            assert (
                dashboard.snapshot_trend(db_path, filters.get("deck"), filters.get("fmt"), **trend)
                == dashboard.dashboard_snapshot(db_path, **filters, **trend)["trend"]
            )
    with pytest.raises(FileNotFoundError):
        dashboard.snapshot_trend(tmp_path / "missing.sqlite3", trend_days=30)


def _served(db_path):
    server = dashboard.create_dashboard_server(port=0, db_path=db_path)
    server.server_close()


def test_the_overview_is_made_ready_at_launch_for_a_long_history_only(tmp_path, monkeypatch):
    db_path = _sample_dashboard_db(tmp_path)
    built = []
    snapshot = dashboard.dashboard_snapshot

    def counting(*args, **kwargs):
        built.append(dashboard._side_by_side_reads(50_000))
        return snapshot(*args, **kwargs)

    monkeypatch.setattr(dashboard, "dashboard_snapshot", counting)
    monkeypatch.setattr(dashboard, "_served_databases", {})

    # No dashboard in this process serves the database: nothing to get ready.
    assert dashboard.warm_overview(db_path) is None

    _served(db_path)
    # A normal history: the page is quick anyway, so it is left alone.
    monkeypatch.setattr(dashboard, "_SIDE_BY_SIDE_MIN_GAMES", 2000)
    thread = dashboard.warm_overview(db_path)
    thread.join(10)
    assert built == []

    # A long one, named the way the tracker names it: built once, in line,
    # and the page the dashboard opens on then waits for nothing.
    _side_by_side(monkeypatch)
    thread = dashboard.warm_overview(tmp_path / "." / db_path.name)
    thread.join(10)
    assert built == [1]
    body = dashboard.snapshot_body(db_path, trend_days=30)
    assert built == [1]
    assert json.loads(body)["summary"]["games"] > 0


def test_start_backfill_calls_then_once_the_pass_has_finished(tmp_path):
    db_path = _sample_dashboard_db(tmp_path)
    game_derived.stop_backfill()
    called = threading.Event()
    stored = []

    def then():
        with sqlite3.connect(db_path) as conn:
            stored.append(len(game_derived.pending(conn)))
        called.set()

    try:
        assert game_derived.start_backfill(db_path, then)
        assert called.wait(10)
        # Called after the games' values were stored, not before.
        assert stored == [0]
    finally:
        game_derived.stop_backfill()
