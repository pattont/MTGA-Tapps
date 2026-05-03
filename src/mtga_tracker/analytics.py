"""SQLite analytics persistence for MTGA tracker."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SessionSnapshot:
    """Current session counters needed by analytics persistence."""

    session_id: str
    started_at: datetime
    games_played: int
    wins: int
    losses: int
    unknown_results: int


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
        self._conn = sqlite3.connect(self.path)
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

            CREATE INDEX IF NOT EXISTS idx_matches_session_id
            ON matches(session_id);

            CREATE INDEX IF NOT EXISTS idx_games_session_match
            ON games(session_id, match_id);

            CREATE INDEX IF NOT EXISTS idx_participants_game_role
            ON participants(game_id, role);

            CREATE INDEX IF NOT EXISTS idx_game_participant_stats_game
            ON game_participant_stats(game_id);

            CREATE INDEX IF NOT EXISTS idx_game_card_summary_game_participant
            ON game_card_summary(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_opening_hand_game_participant
            ON game_opening_hand_cards(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_opening_hand_card
            ON game_opening_hand_cards(display_name);

            CREATE INDEX IF NOT EXISTS idx_game_events_session_time
            ON game_events(session_id, event_time);

            CREATE INDEX IF NOT EXISTS idx_console_logs_session_created
            ON console_logs(session_id, created_at);

            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
            VALUES (1, datetime('now'));
            """
        )
        AnalyticsStore.ensure_table_column(conn, "game_events", "player_life", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "game_events", "opponent_life", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "participants", "opening_hand_size", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "participants", "mulligans", "INTEGER")

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
        runtime_seconds = max(0, int((current_time - session.started_at).total_seconds()))
        conn.execute(
            """
            INSERT INTO tracker_sessions (
                id, started_at, ended_at, app_version, games_played, wins, losses, unknown_results, runtime_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ended_at = excluded.ended_at,
                games_played = excluded.games_played,
                wins = excluded.wins,
                losses = excluded.losses,
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
