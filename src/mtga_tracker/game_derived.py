"""Per-game values the dashboard derives from a finished game, stored once.

The Overview, All Games and the deck page classify every game in view (flood,
screw, land streak) and colour its deck and its opponent. Those answers do not
change once a game is over, so they are computed once, kept in the
``game_derived`` table (one row per game, keyed by the player's participant
id) and read back. See docs/plans/SCALING_LARGE_HISTORIES.md.

Rules that keep a stored row exactly equal to a fresh computation:

- **One writer function.** ``store`` calls the same dashboard functions that
  compute the values live. The tracker calls it at game end; the background
  pass calls it for games recorded before this table existed.
- **Only self-contained answers are stored.** A game with no decklist of its
  own borrows the nearest decklist of the same deck for its land rate, and
  that answer moves when other games are added, renamed or re-dated. Such a
  game's draw quality is stored as NULL and always computed live.
- **A row is used only at the current ``RULES_VERSION``.** Change what
  ``draw_quality_metrics``, the deck-colour scoring or colour normalisation
  return, and bump it: every row is then recomputed, and until the pass
  reaches a game the readers compute it live.
- **A writer that changes a stored row's inputs deletes the row.** Card
  colours and costs filled in later (``invalidate_for_cards``), repaired card
  labels and audit repairs (``invalidate_all``).

Readers never wait: a game without a current row is computed the old way.

The same background pass builds the card-name indexes (``CARD_NAME_INDEXES``)
on a database that has none yet: on a long history that takes seconds, which
the schema baseline would spend on the launcher's main thread before tracking
starts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple

#: Bump when a stored value's computation changes (see the module docstring;
#: tests/test_game_derived.py fails when the draw-quality output changes
#: without it).
RULES_VERSION = 1
#: Games computed and written per transaction by the background pass.
BATCH = 500
TABLE = "game_derived"
_CHUNK = 900

#: (index, table): ``display_name COLLATE NOCASE`` on the per-game card tables.
#: The card page finds a card's rows through them
#: (``dashboard._card_name_clause``); without them the same rows come from a
#: scan of each table. Built by the background pass, never by the schema
#: baseline (see the module docstring).
CARD_NAME_INDEXES: Tuple[Tuple[str, str], ...] = (
    ("idx_card_summary_name_nocase", "game_card_summary"),
    ("idx_opening_hand_name_nocase", "game_opening_hand_cards"),
    ("idx_drawn_cards_name_nocase", "game_drawn_cards"),
    ("idx_game_deck_cards_name_nocase", "game_deck_cards"),
)

#: Held by the tracker while it saves a finished game and by the background
#: pass while it computes and writes a batch, so the pass never reads a game
#: whose rows are half written and then stores that answer over the real one.
WRITE_LOCK = threading.Lock()


class Stored(NamedTuple):
    """One game's stored values. ``draw_quality`` is the decoded dict, or None
    when the game's land rate is not its own; ``deck_colors`` is None when
    the game submitted no decklist."""

    participant_id: str
    game_id: str
    draw_quality: Optional[Dict[str, Any]]
    deck_colors: Optional[str]
    opp_revealed: str
    opp_commander: str


def _chunks(values: Iterable[Any]) -> Iterator[Tuple[str, List[Any]]]:
    items = list(values)
    for start in range(0, len(items), _CHUNK):
        chunk = items[start : start + _CHUNK]
        yield ",".join("?" * len(chunk)), chunk


def table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
        ).fetchone()
        is not None
    )


def canonical_letters(letters: Optional[str]) -> str:
    """The distinct colour letters of a concatenated identity string, sorted.
    ``normalize_colors`` reads only which letters are present, so this keeps
    everything it needs and stays the same whatever order SQLite joined in."""
    return "".join(sorted({ch.upper() for ch in str(letters or "")}))


def _load(
    conn: sqlite3.Connection, column: str, ids: Iterable[Any], *, draw_quality: bool
) -> List[Stored]:
    rows: List[Stored] = []
    quality_column = "draw_quality_json" if draw_quality else "NULL"
    try:
        if not table_exists(conn):
            return rows
        for placeholders, chunk in _chunks(ids):
            for pid, game_id, quality, deck_colors, revealed, commander in conn.execute(
                f"""
                SELECT participant_id, game_id, {quality_column}, deck_colors,
                       opp_revealed, opp_commander
                FROM {TABLE}
                WHERE rules_version = ? AND {column} IN ({placeholders})
                """,
                [RULES_VERSION, *chunk],
            ):
                rows.append(
                    Stored(
                        str(pid),
                        str(game_id),
                        json.loads(quality) if quality is not None else None,
                        deck_colors,
                        str(revealed or ""),
                        str(commander or ""),
                    )
                )
    except (sqlite3.Error, ValueError):
        # An unreadable row is no row: the caller computes the game live.
        return []
    return rows


def load_by_participant(
    conn: sqlite3.Connection, participant_ids: Iterable[Any], *, draw_quality: bool = False
) -> Dict[str, Stored]:
    """Current stored rows for these player participant ids. The draw-quality
    dict is decoded only when asked for (it is most of a row)."""
    return {
        row.participant_id: row
        for row in _load(conn, "participant_id", participant_ids, draw_quality=draw_quality)
    }


def load_by_game(conn: sqlite3.Connection, game_ids: Iterable[Any]) -> Dict[str, Stored]:
    """Current stored rows for these game ids, without the draw-quality dict."""
    return {row.game_id: row for row in _load(conn, "game_id", game_ids, draw_quality=False)}


def store(conn: sqlite3.Connection, participant_ids: Iterable[Any]) -> int:
    """Compute and write the rows of these player participants. The caller
    owns the transaction. Returns the number of rows written."""
    from . import dashboard

    wanted = [str(pid) for pid in participant_ids if pid]
    players: List[Tuple[str, str, Optional[int]]] = []
    for placeholders, chunk in _chunks(wanted):
        players.extend(
            (str(pid), str(game_id), deck_size)
            for pid, game_id, deck_size in conn.execute(
                f"SELECT id, game_id, deck_size FROM participants "
                f"WHERE role = 'player' AND id IN ({placeholders})",
                chunk,
            )
        )
    if not players:
        return 0
    ids = [pid for pid, _, _ in players]
    quality = dashboard._compute_draw_quality_batch(conn, [(pid, size) for pid, _, size in players])
    deck_colors = dashboard._compute_participant_deck_color_map(conn, ids)
    letters = dashboard._compute_opponent_letters(conn, [game_id for _, game_id, _ in players])
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for pid, game_id, _size in players:
        game_quality = quality.get(pid)
        # Only a land rate from the game's own decklist is this game's alone.
        own = game_quality is not None and game_quality.get("land_rate_source") == "decklist"
        revealed, commander = letters.get(game_id, ("", ""))
        rows.append(
            (
                pid,
                game_id,
                RULES_VERSION,
                json.dumps(game_quality, separators=(",", ":")) if own else None,
                deck_colors.get(pid),
                canonical_letters(revealed),
                canonical_letters(commander),
                now,
            )
        )
    conn.executemany(
        f"""
        INSERT OR REPLACE INTO {TABLE} (
            participant_id, game_id, rules_version, draw_quality_json, deck_colors,
            opp_revealed, opp_commander, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def pending(conn: sqlite3.Connection, limit: Optional[int] = None) -> List[str]:
    """Player participants of recorded games with no current row, newest first."""
    limit = BATCH if limit is None else limit
    return [
        str(row[0])
        for row in conn.execute(
            f"""
            SELECT p.id
            FROM participants p
            JOIN games g ON g.id = p.game_id
            LEFT JOIN {TABLE} d ON d.participant_id = p.id AND d.rules_version = ?
            WHERE p.role = 'player' AND d.participant_id IS NULL
            ORDER BY COALESCE(g.started_at, g.ended_at) DESC
            LIMIT ?
            """,
            (RULES_VERSION, int(limit)),
        )
    ]


def invalidate_all(conn: sqlite3.Connection) -> int:
    """Forget every stored row; the next pass recomputes them. The caller
    owns the transaction."""
    if not table_exists(conn):
        return 0
    return conn.execute(f"DELETE FROM {TABLE}").rowcount


def invalidate_for_cards(conn: sqlite3.Connection, card_ids: Iterable[int]) -> int:
    """Forget the rows of games that used these cards (a colour or a cost was
    just filled in for them). The caller owns the transaction."""
    ids = [int(card_id) for card_id in card_ids]
    if not ids or not table_exists(conn):
        return 0
    if conn.execute(f"SELECT 1 FROM {TABLE} LIMIT 1").fetchone() is None:
        return 0
    removed = 0
    for placeholders, chunk in _chunks(ids):
        removed += conn.execute(
            f"""
            DELETE FROM {TABLE} WHERE game_id IN (
              SELECT game_id FROM game_card_summary WHERE card_id IN ({placeholders})
              UNION
              SELECT game_id FROM game_deck_cards WHERE card_id IN ({placeholders})
              UNION
              SELECT p.game_id
              FROM cards c
              JOIN participant_commanders pc ON pc.card_name = c.name
              JOIN participants p ON p.id = pc.participant_id
              WHERE c.id IN ({placeholders})
            )
            """,
            chunk * 3,
        ).rowcount
    return removed


def cards_missing_metadata(conn: sqlite3.Connection) -> Tuple[set, set]:
    """Card ids with no colour identity, and with no mana cost."""
    no_color: set = set()
    no_cost: set = set()
    for card_id, color_missing, cost_missing in conn.execute(
        "SELECT id, color_identity IS NULL, mana_cost IS NULL FROM cards "
        "WHERE color_identity IS NULL OR mana_cost IS NULL"
    ):
        if color_missing:
            no_color.add(card_id)
        if cost_missing:
            no_cost.add(card_id)
    return no_color, no_cost


def index_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def build_card_name_indexes(
    conn: sqlite3.Connection, stop: Optional[threading.Event] = None
) -> int:
    """Create the card-name indexes this database lacks, one transaction
    each. Returns how many were built. An index cannot be built in parts, so
    each holds the write lock for its whole build (a second and a half for
    the largest table at 38,000 games); the game-end save waits on
    ``WRITE_LOCK`` rather than on SQLite's busy timeout."""
    built = 0
    for name, table in CARD_NAME_INDEXES:
        if stop is not None and stop.is_set():
            break
        if index_exists(conn, name):
            continue
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            is None
        ):
            continue
        with WRITE_LOCK, conn:
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {name} ON {table}(display_name COLLATE NOCASE)"
            )
        built += 1
    return built


# --- background pass ---------------------------------------------------------

_worker: Optional[threading.Thread] = None
_worker_stop = threading.Event()
_worker_guard = threading.Lock()
#: Set when a pass is asked for while one is running: rows were dropped after
#: it last looked, so it must look once more before it ends.
_refill_requested = False


def _take_refill_request() -> bool:
    global _refill_requested
    with _worker_guard:
        requested, _refill_requested = _refill_requested, False
    return requested


def run_backfill(
    db_path: Path, stop: Optional[threading.Event] = None, *, pause: float = 0.01
) -> int:
    """Store a row for every recorded game that has no current one, in
    batches, newest games first, then build any missing card-name index.
    Returns the number of rows written. Safe to stop at any point: what is
    left is found again on the next run."""
    written = 0
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        while True:
            written += _store_pending(conn, stop, pause)
            build_card_name_indexes(conn, stop)
            # Rows dropped while an index was being built are stored now.
            if (stop is not None and stop.is_set()) or not _take_refill_request():
                break
    finally:
        conn.close()
    return written


def _store_pending(conn: sqlite3.Connection, stop: Optional[threading.Event], pause: float) -> int:
    written = 0
    if not table_exists(conn):
        return 0
    with WRITE_LOCK, conn:
        # Rows of games deleted since (an audit repair, a deleted match).
        conn.execute(
            f"DELETE FROM {TABLE} WHERE participant_id NOT IN (SELECT id FROM participants)"
        )
    while stop is None or not stop.is_set():
        # One look for everything outstanding, then batches: asking again
        # before every batch re-reads the whole history each time.
        outstanding = pending(conn, 1_000_000_000)
        if not outstanding and not _take_refill_request():
            break
        for start in range(0, len(outstanding), BATCH):
            if stop is not None and stop.is_set():
                break
            with WRITE_LOCK, conn:
                written += store(conn, outstanding[start : start + BATCH])
            # Let the tracker thread take the lock (and the GIL) between batches.
            time.sleep(pause)
    return written


def start_backfill(db_path: Optional[Path]) -> bool:
    """Run the pass on a daemon thread unless one is already running."""
    global _worker, _refill_requested
    if db_path is None:
        return False
    with _worker_guard:
        if _worker is not None and _worker.is_alive():
            _refill_requested = True
            return False
        _refill_requested = False
        _worker_stop.clear()

        def work() -> None:
            try:
                run_backfill(Path(db_path), _worker_stop)
            except Exception:
                # Stored values are an optimisation: the dashboard computes
                # live without them. Never take the tracker down for one.
                return

        _worker = threading.Thread(target=work, name="game-derived-backfill", daemon=True)
        _worker.start()
        return True


def stop_backfill(timeout: float = 5.0) -> None:
    """Ask the pass to stop after its current batch and wait for it."""
    with _worker_guard:
        worker = _worker
        _worker_stop.set()
    if worker is not None and worker.is_alive():
        worker.join(timeout)
