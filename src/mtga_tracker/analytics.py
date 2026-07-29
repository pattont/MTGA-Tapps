"""SQLite analytics persistence for MTGA tracker."""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .log_sanitize import scrub_raw_log


_PREVIOUS_TURN_DURATION_RE = re.compile(
    r"^Previous Turn \((You|Opponent)\): " r"(?:(\d+)h )?(?:(\d+)m )?(\d+)s$"
)


def _previous_turn_duration(text: str) -> Optional[tuple[str, int]]:
    """Parse one exact live duration emitted in a previous-turn header."""
    match = _PREVIOUS_TURN_DURATION_RE.fullmatch(str(text or "").strip())
    if match is None:
        return None
    label, hours, minutes, seconds = match.groups()
    total_seconds = int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(seconds)
    return label, total_seconds


@dataclass(frozen=True)
class SessionSnapshot:
    """Current session counters needed by analytics persistence."""

    session_id: str
    started_at: datetime
    games_played: int
    wins: int
    losses: int
    unknown_results: int
    draws: int = 0
    runtime_seconds: Optional[int] = None


class AnalyticsStore:
    """Owns the analytics SQLite connection and schema initialization."""

    def __init__(self, path: Optional[Path]):
        self.path = Path(path) if path is not None else None
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> Optional[sqlite3.Connection]:
        """Return the persistent initialized connection, or None when disabled/unavailable."""
        if self.path is None:
            return None
        if self._conn is not None:
            return self._conn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=10.0)
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self.ensure_schema(self._conn)
        return self._conn

    def close(self) -> None:
        """Close the persistent connection if open."""
        if self._conn is None:
            return
        try:
            self._conn.commit()
            self._conn.close()
        finally:
            self._conn = None

    @staticmethod
    def ensure_schema(conn: sqlite3.Connection) -> None:
        """Create dashboard-friendly analytics tables if needed."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tracker_sessions (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                app_version TEXT,
                games_played INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                draws INTEGER NOT NULL DEFAULT 0,
                unknown_results INTEGER NOT NULL DEFAULT 0,
                runtime_seconds INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                match_type TEXT,
                format TEXT,
                queue TEXT,
                event_name TEXT,
                best_of INTEGER,
                games_played INTEGER NOT NULL DEFAULT 0,
                winner_participant_id TEXT,
                raw_match_id TEXT,
                FOREIGN KEY(session_id) REFERENCES tracker_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                match_id TEXT NOT NULL,
                game_number INTEGER,
                started_at TEXT,
                ended_at TEXT,
                duration_seconds INTEGER,
                total_turns INTEGER,
                player_turns INTEGER,
                opponent_turns INTEGER,
                outcome TEXT,
                outcome_reason TEXT,
                winner_participant_id TEXT,
                FOREIGN KEY(session_id) REFERENCES tracker_sessions(id),
                FOREIGN KEY(match_id) REFERENCES matches(id)
            );

            CREATE TABLE IF NOT EXISTS participants (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                seat_id INTEGER,
                role TEXT NOT NULL,
                display_name TEXT,
                deck_name TEXT,
                deck_id TEXT,
                deck_archetype TEXT,
                deck_size INTEGER,
                deck_size_source TEXT,
                opening_hand_size INTEGER,
                mulligans INTEGER,
                starting_life INTEGER,
                ending_life INTEGER,
                went_first INTEGER,
                FOREIGN KEY(game_id) REFERENCES games(id)
            );

            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arena_id INTEGER UNIQUE,
                name TEXT NOT NULL UNIQUE,
                type_line TEXT,
                primary_type TEXT,
                power TEXT,
                toughness TEXT,
                first_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS participant_commanders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id TEXT NOT NULL,
                card_id INTEGER,
                card_name TEXT NOT NULL,
                UNIQUE(participant_id, card_name),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(card_id) REFERENCES cards(id)
            );

            CREATE TABLE IF NOT EXISTS game_card_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                card_id INTEGER,
                display_name TEXT NOT NULL,
                type_category TEXT,
                played_count INTEGER NOT NULL DEFAULT 0,
                drawn_count INTEGER NOT NULL DEFAULT 0,
                discarded_count INTEGER NOT NULL DEFAULT 0,
                milled_count INTEGER NOT NULL DEFAULT 0,
                exiled_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(game_id, participant_id, display_name),
                FOREIGN KEY(game_id) REFERENCES games(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(card_id) REFERENCES cards(id)
            );

            CREATE TABLE IF NOT EXISTS game_deck_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                card_id INTEGER,
                arena_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                type_category TEXT,
                deck_zone TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                UNIQUE(game_id, participant_id, deck_zone, arena_id),
                FOREIGN KEY(game_id) REFERENCES games(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(card_id) REFERENCES cards(id)
            );

            CREATE TABLE IF NOT EXISTS game_opening_hand_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                card_id INTEGER,
                display_name TEXT NOT NULL,
                type_category TEXT,
                hand_position INTEGER NOT NULL,
                copy_number INTEGER NOT NULL DEFAULT 1,
                UNIQUE(game_id, participant_id, hand_position),
                FOREIGN KEY(game_id) REFERENCES games(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(card_id) REFERENCES cards(id)
            );

            CREATE TABLE IF NOT EXISTS game_drawn_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                card_id INTEGER,
                display_name TEXT NOT NULL,
                type_category TEXT,
                draw_position INTEGER NOT NULL,
                turn_number INTEGER,
                copy_number INTEGER NOT NULL DEFAULT 1,
                UNIQUE(game_id, participant_id, draw_position),
                FOREIGN KEY(game_id) REFERENCES games(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id),
                FOREIGN KEY(card_id) REFERENCES cards(id)
            );

            CREATE TABLE IF NOT EXISTS game_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                match_id TEXT,
                game_id TEXT,
                event_time TEXT NOT NULL,
                elapsed_seconds INTEGER,
                turn_number INTEGER,
                phase TEXT,
                step TEXT,
                participant_id TEXT,
                seat_id INTEGER,
                actor_role TEXT,
                event_type TEXT,
                event_subtype TEXT,
                text TEXT NOT NULL,
                source_card_id INTEGER,
                target_card_id INTEGER,
                amount INTEGER,
                zone_from TEXT,
                zone_to TEXT,
                player_life INTEGER,
                opponent_life INTEGER,
                payload_json TEXT,
                FOREIGN KEY(session_id) REFERENCES tracker_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS game_participant_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                attack_steps INTEGER NOT NULL DEFAULT 0,
                attacking_creatures INTEGER NOT NULL DEFAULT 0,
                attackers_lost INTEGER NOT NULL DEFAULT 0,
                blocking_creatures INTEGER NOT NULL DEFAULT 0,
                blockers_lost INTEGER NOT NULL DEFAULT 0,
                damage_dealt INTEGER NOT NULL DEFAULT 0,
                damage_taken INTEGER NOT NULL DEFAULT 0,
                life_lost INTEGER NOT NULL DEFAULT 0,
                self_damage INTEGER NOT NULL DEFAULT 0,
                life_gained INTEGER NOT NULL DEFAULT 0,
                cards_played INTEGER NOT NULL DEFAULT 0,
                cards_drawn INTEGER NOT NULL DEFAULT 0,
                cards_discarded INTEGER NOT NULL DEFAULT 0,
                cards_milled INTEGER NOT NULL DEFAULT 0,
                cards_exiled INTEGER NOT NULL DEFAULT 0,
                UNIQUE(game_id, participant_id),
                FOREIGN KEY(game_id) REFERENCES games(id),
                FOREIGN KEY(participant_id) REFERENCES participants(id)
            );

            CREATE TABLE IF NOT EXISTS game_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                seat_id INTEGER,
                started_at TEXT,
                ended_at TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                timing_source TEXT NOT NULL DEFAULT 'live',
                UNIQUE(game_id, turn_number),
                FOREIGN KEY(game_id) REFERENCES games(id)
            );

            CREATE TABLE IF NOT EXISTS session_participant_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                games INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                cards_played INTEGER NOT NULL DEFAULT 0,
                cards_drawn INTEGER NOT NULL DEFAULT 0,
                cards_discarded INTEGER NOT NULL DEFAULT 0,
                cards_milled INTEGER NOT NULL DEFAULT 0,
                damage_dealt INTEGER NOT NULL DEFAULT 0,
                damage_taken INTEGER NOT NULL DEFAULT 0,
                UNIQUE(session_id, role),
                FOREIGN KEY(session_id) REFERENCES tracker_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS console_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                match_started_at TEXT,
                elapsed_seconds INTEGER,
                turn_number INTEGER,
                active_player INTEGER,
                style TEXT,
                text TEXT NOT NULL,
                player_life INTEGER,
                opponent_life INTEGER,
                FOREIGN KEY(session_id) REFERENCES tracker_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS raw_game_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                match_id TEXT,
                game_id TEXT,
                created_at TEXT NOT NULL,
                payload_type TEXT,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES tracker_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS rank_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                match_id TEXT,
                game_id TEXT,
                captured_at TEXT NOT NULL,
                season_ordinal INTEGER NOT NULL,
                rank_format TEXT NOT NULL DEFAULT 'constructed',
                rank_class TEXT NOT NULL,
                rank_level INTEGER NOT NULL,
                rank_step INTEGER NOT NULL,
                rank_steps INTEGER NOT NULL,
                raw_step INTEGER,
                matches_won INTEGER,
                matches_lost INTEGER,
                mythic_percentile INTEGER,
                mythic_rank INTEGER,
                UNIQUE(captured_at, season_ordinal, rank_format),
                FOREIGN KEY(session_id) REFERENCES tracker_sessions(id),
                FOREIGN KEY(match_id) REFERENCES matches(id),
                FOREIGN KEY(game_id) REFERENCES games(id)
            );

            CREATE INDEX IF NOT EXISTS idx_matches_session_id
            ON matches(session_id);

            CREATE INDEX IF NOT EXISTS idx_games_session_match
            ON games(session_id, match_id);

            CREATE INDEX IF NOT EXISTS idx_participants_game_role
            ON participants(game_id, role);

            CREATE INDEX IF NOT EXISTS idx_game_participant_stats_game
            ON game_participant_stats(game_id);

            CREATE INDEX IF NOT EXISTS idx_game_turns_game
            ON game_turns(game_id);

            CREATE INDEX IF NOT EXISTS idx_game_card_summary_game_participant
            ON game_card_summary(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_game_deck_cards_game_participant
            ON game_deck_cards(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_opening_hand_game_participant
            ON game_opening_hand_cards(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_opening_hand_card
            ON game_opening_hand_cards(display_name);

            CREATE INDEX IF NOT EXISTS idx_drawn_cards_game_participant
            ON game_drawn_cards(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_drawn_cards_card
            ON game_drawn_cards(display_name);

            CREATE INDEX IF NOT EXISTS idx_game_events_session_time
            ON game_events(session_id, event_time);

            CREATE INDEX IF NOT EXISTS idx_console_logs_session_created
            ON console_logs(session_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_rank_snapshots_season_time
            ON rank_snapshots(rank_format, season_ordinal, captured_at);

            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
            VALUES (1, datetime('now'));
            """
        )
        AnalyticsStore.ensure_table_column(conn, "game_events", "player_life", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "game_events", "opponent_life", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "participants", "opening_hand_size", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "participants", "mulligans", "INTEGER")
        AnalyticsStore.ensure_table_column(
            conn, "tracker_sessions", "draws", "INTEGER NOT NULL DEFAULT 0"
        )
        AnalyticsStore.ensure_table_column(conn, "games", "player_turns", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "games", "opponent_turns", "INTEGER")
        AnalyticsStore.ensure_table_column(
            conn, "game_turns", "timing_source", "TEXT NOT NULL DEFAULT 'live'"
        )
        AnalyticsStore.backfill_game_turn_counts(conn)
        AnalyticsStore.apply_pending_migrations(conn)

    @staticmethod
    def apply_pending_migrations(conn: sqlite3.Connection) -> None:
        """Apply numbered one-time schema/data migrations in order.

        The executescript baseline above is migration 1. Later migrations are
        recorded in schema_migrations so each runs exactly once per database.
        """
        applied = {
            int(row[0])
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        migrations = (
            (2, AnalyticsStore._migrate_v2_backfill_card_arena_ids),
            (3, AnalyticsStore._migrate_v3_backfill_summary_drawn_counts),
            (4, AnalyticsStore._migrate_v4_game_annotations),
            (5, AnalyticsStore._migrate_v5_backfill_drawn_card_names),
        )
        for version, migrate in migrations:
            if version in applied:
                continue
            migrate(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                "VALUES (?, datetime('now'))",
                (version,),
            )
        conn.commit()

    @staticmethod
    def _migrate_v2_backfill_card_arena_ids(conn: sqlite3.Connection) -> None:
        """Copy authoritative Arena ids from submitted decklists into cards.

        game_deck_cards.arena_id has always been populated while cards.arena_id
        never was, forcing fuzzy name-based Scryfall image lookups. UPDATE OR
        IGNORE skips the rare name variants that would collide on the UNIQUE
        arena_id constraint.
        """
        conn.execute(
            """
            UPDATE OR IGNORE cards SET arena_id = (
                SELECT gdc.arena_id
                FROM game_deck_cards gdc
                WHERE gdc.card_id = cards.id AND gdc.arena_id IS NOT NULL
                ORDER BY gdc.id DESC
                LIMIT 1
            )
            WHERE cards.arena_id IS NULL
              AND EXISTS (
                SELECT 1 FROM game_deck_cards gdc
                WHERE gdc.card_id = cards.id AND gdc.arena_id IS NOT NULL
              )
            """
        )

    @staticmethod
    def _migrate_v3_backfill_summary_drawn_counts(conn: sqlite3.Connection) -> None:
        """Backfill game_card_summary.drawn_count from visible drawn-card rows.

        drawn_count existed in the schema but was never written; the dashboard
        already queries it. Existing summary rows get real counts (matched by
        card_id) and drawn-but-never-played cards gain summary rows with
        played_count = 0.
        """
        conn.execute(
            """
            UPDATE game_card_summary SET drawn_count = COALESCE(
                (
                    SELECT COUNT(*)
                    FROM game_drawn_cards d
                    WHERE d.game_id = game_card_summary.game_id
                      AND d.participant_id = game_card_summary.participant_id
                      AND d.card_id = game_card_summary.card_id
                ),
                0
            )
            WHERE game_card_summary.card_id IS NOT NULL
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO game_card_summary (
                game_id, participant_id, card_id, display_name, type_category,
                played_count, drawn_count
            )
            SELECT
                d.game_id,
                d.participant_id,
                d.card_id,
                d.display_name,
                COALESCE(MAX(d.type_category), 'Other'),
                0,
                COUNT(*)
            FROM game_drawn_cards d
            WHERE d.card_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM game_card_summary s
                WHERE s.game_id = d.game_id
                  AND s.participant_id = d.participant_id
                  AND (s.card_id = d.card_id OR s.display_name = d.display_name)
              )
            GROUP BY d.game_id, d.participant_id, d.card_id
            """
        )

    @staticmethod
    def _migrate_v4_game_annotations(conn: sqlite3.Connection) -> None:
        """User notes and tags per game (the dashboard's first writable data)."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS game_annotations (
                game_id TEXT PRIMARY KEY,
                note TEXT,
                tags TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _migrate_v5_backfill_drawn_card_names(conn: sqlite3.Connection) -> None:
        """Rewrite historical "drew a card" timeline events with the card name.

        Visible drawn-card identities were persisted to game_drawn_cards all
        along, but the rendered event text never included them. Pair each
        game's draw events with its recorded draws — whole-game when the counts
        match exactly, otherwise per-turn where the counts match — and leave
        anything ambiguous untouched.
        """
        game_ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT game_id FROM game_events
                WHERE event_type = 'draw' AND text LIKE '%drew a card%'
                  AND game_id IS NOT NULL
                """
            )
        ]
        for game_id in game_ids:
            for role in ("player", "opponent"):
                participant = conn.execute(
                    "SELECT id FROM participants WHERE game_id = ? AND role = ?",
                    (game_id, role),
                ).fetchone()
                if participant is None:
                    continue
                drawn = conn.execute(
                    """
                    SELECT display_name, turn_number
                    FROM game_drawn_cards
                    WHERE game_id = ? AND participant_id = ?
                    ORDER BY draw_position
                    """,
                    (game_id, participant[0]),
                ).fetchall()
                events = conn.execute(
                    """
                    SELECT id, text, turn_number
                    FROM game_events
                    WHERE game_id = ? AND actor_role = ? AND event_type = 'draw'
                      AND text LIKE '%drew a card%'
                    ORDER BY event_time, id
                    """,
                    (game_id, role),
                ).fetchall()
                if not drawn or not events:
                    continue
                updates = []
                if len(drawn) == len(events):
                    for (event_id, text, _), (name, _) in zip(events, drawn):
                        updates.append(
                            (str(text).replace("drew a card", f"drew [{name}]", 1), event_id)
                        )
                else:
                    events_by_turn: dict = {}
                    drawn_by_turn: dict = {}
                    for event in events:
                        events_by_turn.setdefault(event[2], []).append(event)
                    for card in drawn:
                        drawn_by_turn.setdefault(card[1], []).append(card)
                    for turn, turn_events in events_by_turn.items():
                        turn_drawn = drawn_by_turn.get(turn, [])
                        if turn is None or len(turn_events) != len(turn_drawn):
                            continue
                        for (event_id, text, _), (name, _) in zip(turn_events, turn_drawn):
                            updates.append(
                                (str(text).replace("drew a card", f"drew [{name}]", 1), event_id)
                            )
                if updates:
                    conn.executemany(
                        "UPDATE game_events SET text = ? WHERE id = ?", updates
                    )

    @staticmethod
    def backfill_estimated_game_turn_times(conn: sqlite3.Connection) -> int:
        """Estimate missing turn durations from adjacent historical turn-header events.

        A turn's end boundary comes from the next adjacent turn header, or — when
        that header was never logged — from the next turn's already-persisted
        timing row. The last observed header is used only when it matches the
        game's stored total-turn count. Existing rows are never overwritten, so
        exact live timings remain authoritative.
        """
        changes_before = conn.total_changes
        conn.execute(
            """
            WITH header_events AS (
                SELECT
                    ge.game_id,
                    ge.turn_number,
                    MIN(ge.event_time) AS started_at,
                    CASE
                        WHEN MAX(CASE WHEN ge.text LIKE 'Turn % - YOUR TURN' THEN 1 ELSE 0 END) = 1
                        THEN 'player'
                        ELSE 'opponent'
                    END AS role
                FROM game_events ge
                WHERE ge.game_id IS NOT NULL
                  AND ge.turn_number IS NOT NULL
                  AND (
                      ge.text LIKE 'Turn % - YOUR TURN'
                      OR ge.text LIKE "Turn % - OPPONENT'S TURN"
                  )
                GROUP BY ge.game_id, ge.turn_number
            ), ordered_headers AS (
                SELECT
                    game_id,
                    turn_number,
                    started_at,
                    role,
                    LEAD(turn_number) OVER (
                        PARTITION BY game_id ORDER BY turn_number, started_at
                    ) AS next_turn_number,
                    LEAD(started_at) OVER (
                        PARTITION BY game_id ORDER BY turn_number, started_at
                    ) AS next_started_at
                FROM header_events
            ), estimable_turns AS (
                SELECT
                    h.game_id,
                    h.turn_number,
                    p.seat_id,
                    h.started_at,
                    COALESCE(
                        CASE
                            WHEN h.next_turn_number = h.turn_number + 1 THEN h.next_started_at
                        END,
                        (
                            SELECT gt.started_at
                            FROM game_turns gt
                            WHERE gt.game_id = h.game_id
                              AND gt.turn_number = h.turn_number + 1
                        ),
                        CASE
                            WHEN h.turn_number = g.total_turns THEN g.ended_at
                        END
                    ) AS ended_at
                FROM ordered_headers h
                JOIN games g ON g.id = h.game_id
                LEFT JOIN participants p
                  ON p.game_id = h.game_id AND p.role = h.role
            )
            INSERT OR IGNORE INTO game_turns (
                game_id,
                turn_number,
                seat_id,
                started_at,
                ended_at,
                duration_seconds,
                timing_source
            )
            SELECT
                game_id,
                turn_number,
                seat_id,
                started_at,
                ended_at,
                CAST(MAX(0, ROUND((julianday(ended_at) - julianday(started_at)) * 86400.0)) AS INTEGER),
                'estimated_header_events'
            FROM estimable_turns
            WHERE ended_at IS NOT NULL
              AND julianday(started_at) IS NOT NULL
              AND julianday(ended_at) IS NOT NULL
              AND julianday(ended_at) > julianday(started_at)
              AND ROUND((julianday(ended_at) - julianday(started_at)) * 86400.0) > 0
            """
        )
        return conn.total_changes - changes_before

    @staticmethod
    def backfill_recovered_game_turn_times(
        conn: sqlite3.Connection, game_id: Optional[str] = None
    ) -> int:
        """Recover exact live turn durations preserved in console turn headers.

        Each turn transition prints the completed turn's exact measured duration.
        The final turn is reconstructed from its observed header and the persisted
        game end. Existing timing rows are never overwritten.
        """
        changes_before = conn.total_changes
        params: tuple[str, ...] = ()
        game_filter = ""
        if game_id is not None:
            game_filter = "AND g.id = ?"
            params = (game_id,)
        games = conn.execute(
            f"""
            SELECT g.id, g.session_id, g.started_at, g.ended_at, g.total_turns
            FROM games g
            WHERE g.started_at IS NOT NULL
              AND g.ended_at IS NOT NULL
              AND COALESCE(g.total_turns, 0) > (
                  SELECT COUNT(*) FROM game_turns gt WHERE gt.game_id = g.id
              )
              {game_filter}
            ORDER BY g.started_at
            """,
            params,
        ).fetchall()

        for recovered_game_id, session_id, started_at, ended_at, total_turns in games:
            seats = {
                role: seat_id
                for role, seat_id in conn.execute(
                    "SELECT role, seat_id FROM participants WHERE game_id = ?",
                    (recovered_game_id,),
                )
                if role in {"player", "opponent"} and seat_id in (1, 2)
            }
            duration_rows = conn.execute(
                """
                SELECT turn_number, created_at, text
                FROM console_logs
                WHERE session_id = ?
                  AND substr(match_started_at, 1, 19) = substr(?, 1, 19)
                  AND text LIKE 'Previous Turn (%'
                ORDER BY turn_number, created_at
                """,
                (session_id, started_at),
            ).fetchall()
            for current_turn, completed_at, text in duration_rows:
                parsed = _previous_turn_duration(text)
                completed_turn = int(current_turn or 0) - 1
                if parsed is None or completed_turn < 1:
                    continue
                label, duration_seconds = parsed
                seat_id = seats.get("player" if label == "You" else "opponent")
                try:
                    ended_at_value = datetime.fromisoformat(str(completed_at))
                except ValueError:
                    continue
                started_at_value = ended_at_value - timedelta(seconds=duration_seconds)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO game_turns (
                        game_id, turn_number, seat_id, started_at, ended_at,
                        duration_seconds, timing_source
                    ) VALUES (?, ?, ?, ?, ?, ?, 'recovered_previous_turn_logs')
                    """,
                    (
                        recovered_game_id,
                        completed_turn,
                        seat_id,
                        started_at_value.isoformat(),
                        ended_at_value.isoformat(),
                        duration_seconds,
                    ),
                )

            final_turn = int(total_turns or 0)
            if final_turn < 1:
                continue
            final_exists = conn.execute(
                "SELECT 1 FROM game_turns WHERE game_id = ? AND turn_number = ?",
                (recovered_game_id, final_turn),
            ).fetchone()
            if final_exists is not None:
                continue
            final_header = conn.execute(
                """
                SELECT MIN(event_time), MAX(text)
                FROM game_events
                WHERE game_id = ?
                  AND turn_number = ?
                  AND text LIKE 'Turn % - %TURN'
                """,
                (recovered_game_id, final_turn),
            ).fetchone()
            if not final_header or not final_header[0]:
                continue
            try:
                final_started_at = datetime.fromisoformat(str(final_header[0]))
                final_ended_at = datetime.fromisoformat(str(ended_at))
            except ValueError:
                continue
            final_duration = int((final_ended_at - final_started_at).total_seconds())
            if final_duration <= 0:
                continue
            final_role = "player" if "YOUR TURN" in str(final_header[1] or "") else "opponent"
            conn.execute(
                """
                INSERT OR IGNORE INTO game_turns (
                    game_id, turn_number, seat_id, started_at, ended_at,
                    duration_seconds, timing_source
                ) VALUES (?, ?, ?, ?, ?, ?, 'recovered_previous_turn_logs')
                """,
                (
                    recovered_game_id,
                    final_turn,
                    seats.get(final_role),
                    final_started_at.isoformat(),
                    final_ended_at.isoformat(),
                    final_duration,
                ),
            )
        return conn.total_changes - changes_before

    @staticmethod
    def backfill_game_turn_counts(conn: sqlite3.Connection) -> None:
        """Backfill player/opponent turn counts from persisted turn header events."""
        conn.execute(
            """
            UPDATE games
            SET
                player_turns = COALESCE((
                    SELECT COUNT(DISTINCT ge.turn_number)
                    FROM game_events ge
                    WHERE ge.game_id = games.id
                      AND ge.text LIKE 'Turn % - YOUR TURN'
                ), 0),
                opponent_turns = COALESCE((
                    SELECT COUNT(DISTINCT ge.turn_number)
                    FROM game_events ge
                    WHERE ge.game_id = games.id
                      AND ge.text LIKE "Turn % - OPPONENT'S TURN"
                ), 0)
            WHERE player_turns IS NULL OR opponent_turns IS NULL
            """
        )
        conn.execute(
            """
            UPDATE games
            SET total_turns = player_turns + opponent_turns
            WHERE player_turns IS NOT NULL
              AND opponent_turns IS NOT NULL
              AND player_turns + opponent_turns > 0
            """
        )
        conn.execute(
            """
            UPDATE games
            SET
                player_turns = CASE
                    WHEN COALESCE(p.went_first, 0) = 1 THEN (COALESCE(games.total_turns, 0) + 1) / 2
                    ELSE COALESCE(games.total_turns, 0) / 2
                END,
                opponent_turns = CASE
                    WHEN COALESCE(p.went_first, 0) = 1 THEN COALESCE(games.total_turns, 0) / 2
                    ELSE (COALESCE(games.total_turns, 0) + 1) / 2
                END
            FROM participants p
            WHERE p.game_id = games.id
              AND p.role = 'player'
              AND COALESCE(games.total_turns, 0) > 0
              AND COALESCE(games.player_turns, 0) = 0
              AND COALESCE(games.opponent_turns, 0) = 0
            """
        )

    @staticmethod
    def ensure_table_column(
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        """Add a nullable column when an older analytics DB lacks it."""
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def upsert_session_row(
        self,
        conn: sqlite3.Connection,
        session: SessionSnapshot,
        *,
        now: Optional[datetime] = None,
    ) -> None:
        """Persist current session counters."""
        current_time = now or datetime.now()
        runtime_seconds = (
            max(0, int(session.runtime_seconds))
            if session.runtime_seconds is not None
            else max(0, int((current_time - session.started_at).total_seconds()))
        )
        conn.execute(
            """
            INSERT INTO tracker_sessions (
                id, started_at, ended_at, app_version, games_played, wins, losses, draws, unknown_results, runtime_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ended_at = excluded.ended_at,
                games_played = excluded.games_played,
                wins = excluded.wins,
                losses = excluded.losses,
                draws = excluded.draws,
                unknown_results = excluded.unknown_results,
                runtime_seconds = excluded.runtime_seconds
            """,
            (
                session.session_id,
                session.started_at.isoformat(),
                current_time.isoformat(),
                None,
                session.games_played,
                session.wins,
                session.losses,
                session.draws,
                session.unknown_results,
                runtime_seconds,
            ),
        )

    def record_console_log(
        self,
        session: SessionSnapshot,
        *,
        created_at: datetime,
        match_started_at: Optional[datetime],
        elapsed_seconds: Optional[int],
        turn_number: Optional[int],
        active_player: Optional[int],
        style: Optional[str],
        text: str,
        player_life: Optional[int],
        opponent_life: Optional[int],
    ) -> None:
        """Persist one rendered console line using the persistent connection."""
        conn = self.connect()
        if conn is None:
            return
        self.upsert_session_row(conn, session, now=created_at)
        conn.execute(
            """
            INSERT INTO console_logs (
                session_id,
                created_at,
                match_started_at,
                elapsed_seconds,
                turn_number,
                active_player,
                style,
                text,
                player_life,
                opponent_life
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                created_at.isoformat(),
                match_started_at.isoformat() if match_started_at else None,
                elapsed_seconds,
                turn_number,
                active_player,
                style,
                text,
                player_life,
                opponent_life,
            ),
        )
        conn.commit()

    def record_raw_payload(
        self,
        *,
        session_id: str,
        created_at: Optional[datetime],
        payload_type: Optional[str],
        payload_json: str,
        match_id: Optional[str] = None,
        game_id: Optional[str] = None,
    ) -> None:
        """Persist a sanitized raw payload snapshot for parser diagnostics/replay."""
        conn = self.connect()
        if conn is None:
            return
        now = created_at or datetime.now()
        conn.execute(
            """
            INSERT INTO raw_game_payloads (
                session_id,
                match_id,
                game_id,
                created_at,
                payload_type,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                match_id,
                game_id,
                now.isoformat(),
                payload_type,
                scrub_raw_log(payload_json),
            ),
        )
        conn.commit()

    def record_rank_snapshot(
        self,
        session: SessionSnapshot,
        *,
        captured_at: datetime,
        season_ordinal: int,
        rank_class: str,
        rank_level: int,
        rank_step: int,
        rank_steps: int,
        raw_step: Optional[int],
        matches_won: Optional[int],
        matches_lost: Optional[int],
        mythic_percentile: Optional[int],
        mythic_rank: Optional[int],
        match_id: Optional[str] = None,
        game_id: Optional[str] = None,
        rank_format: str = "constructed",
    ) -> bool:
        """Persist a changed rank snapshot for one format and return whether it was added."""
        conn = self.connect()
        if conn is None:
            return False
        self.upsert_session_row(conn, session, now=captured_at)
        previous = conn.execute(
            """
            SELECT rank_class, rank_level, rank_step, rank_steps, matches_won, matches_lost,
                   mythic_percentile, mythic_rank
            FROM rank_snapshots
            WHERE rank_format = ? AND season_ordinal = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            (rank_format, season_ordinal),
        ).fetchone()
        current = (
            rank_class,
            rank_level,
            rank_step,
            rank_steps,
            matches_won,
            matches_lost,
            mythic_percentile,
            mythic_rank,
        )
        if previous == current:
            return False
        conn.execute(
            """
            INSERT OR IGNORE INTO rank_snapshots (
                session_id, match_id, game_id, captured_at, season_ordinal, rank_format,
                rank_class, rank_level, rank_step, rank_steps, raw_step,
                matches_won, matches_lost, mythic_percentile, mythic_rank
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                match_id,
                game_id,
                captured_at.isoformat(),
                season_ordinal,
                rank_format,
                rank_class,
                rank_level,
                rank_step,
                rank_steps,
                raw_step,
                matches_won,
                matches_lost,
                mythic_percentile,
                mythic_rank,
            ),
        )
        added = conn.execute("SELECT changes()").fetchone()[0] > 0
        conn.commit()
        return added
