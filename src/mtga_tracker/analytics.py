"""SQLite analytics persistence for MTGA tracker."""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from .log_sanitize import scrub_raw_log
from .payload_codec import compress_payload


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

            CREATE TABLE IF NOT EXISTS game_mulligan_hands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                hand_number INTEGER NOT NULL,
                hand_position INTEGER NOT NULL,
                card_id INTEGER,
                display_name TEXT NOT NULL,
                type_category TEXT,
                bottomed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(game_id, participant_id, hand_number, hand_position),
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
                source TEXT,
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
                removal_drawn INTEGER,
                removal_played INTEGER,
                wipes_drawn INTEGER,
                wipes_played INTEGER,
                bounces_drawn INTEGER,
                bounces_played INTEGER,
                creatures_removed INTEGER,
                noncreatures_removed INTEGER,
                creatures_bounced INTEGER,
                noncreatures_bounced INTEGER,
                poison_added INTEGER,
                counters_drawn INTEGER,
                counters_played INTEGER,
                spells_countered INTEGER,
                lands_lost INTEGER,
                lands_replaced INTEGER,
                tokens_created INTEGER,
                tokens_destroyed INTEGER,
                tokens_sacrificed INTEGER,
                tokens_exiled INTEGER,
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

            -- Single-row "what is happening right now" snapshot for the
            -- dashboard's Live Log page. The tracker upserts it alongside
            -- every console line (same transaction) plus an idle heartbeat,
            -- so the dashboard can serve /api/live from SQLite alone.
            CREATE TABLE IF NOT EXISTS live_status (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                session_id TEXT,
                updated_at TEXT NOT NULL,
                in_game INTEGER NOT NULL DEFAULT 0,
                match_id TEXT,
                game_id TEXT,
                format TEXT,
                match_type TEXT,
                game_number INTEGER,
                player_name TEXT,
                opponent_name TEXT,
                deck_name TEXT,
                turn_number INTEGER,
                active_role TEXT,
                on_play INTEGER,
                player_life INTEGER,
                opponent_life INTEGER,
                mulligans INTEGER,
                game_started_at TEXT,
                player_commanders TEXT,
                opponent_commanders TEXT,
                log_path TEXT,
                card_db_path TEXT,
                db_path TEXT,
                tracker_version TEXT,
                player_colors TEXT,
                opponent_colors TEXT
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

            CREATE INDEX IF NOT EXISTS idx_games_session_window
            ON games(session_id, started_at, ended_at);

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

            CREATE INDEX IF NOT EXISTS idx_mulligan_hands_game_participant
            ON game_mulligan_hands(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_opening_hand_card
            ON game_opening_hand_cards(display_name);

            CREATE INDEX IF NOT EXISTS idx_drawn_cards_game_participant
            ON game_drawn_cards(game_id, participant_id);

            CREATE INDEX IF NOT EXISTS idx_drawn_cards_card
            ON game_drawn_cards(display_name);

            CREATE INDEX IF NOT EXISTS idx_game_events_session_time
            ON game_events(session_id, event_time);

            CREATE INDEX IF NOT EXISTS idx_game_events_game_time
            ON game_events(game_id, event_time);

            CREATE INDEX IF NOT EXISTS idx_raw_game_payloads_game
            ON raw_game_payloads(game_id);

            CREATE INDEX IF NOT EXISTS idx_console_logs_session_created
            ON console_logs(session_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_rank_snapshots_season_time
            ON rank_snapshots(rank_format, season_ordinal, captured_at);

            -- Dashboard read paths that look cards up by participant alone
            -- (opener-land stats, mana readiness, draw quality batches) and
            -- games by match (Bo3 records). Without these each of them scans
            -- the whole table once per game.
            CREATE INDEX IF NOT EXISTS idx_opening_hand_participant
            ON game_opening_hand_cards(participant_id);

            CREATE INDEX IF NOT EXISTS idx_drawn_cards_participant
            ON game_drawn_cards(participant_id);

            CREATE INDEX IF NOT EXISTS idx_game_deck_cards_participant_zone
            ON game_deck_cards(participant_id, deck_zone);

            CREATE INDEX IF NOT EXISTS idx_game_card_summary_participant
            ON game_card_summary(participant_id);

            CREATE INDEX IF NOT EXISTS idx_participants_role_deck
            ON participants(role, deck_name);

            CREATE INDEX IF NOT EXISTS idx_games_match
            ON games(match_id);

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
        AnalyticsStore.ensure_table_column(conn, "cards", "color_identity", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "cards", "mana_cost", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "cards", "mana_value", "REAL")
        AnalyticsStore.ensure_table_column(conn, "live_status", "log_path", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "card_db_path", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "db_path", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "tracker_version", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "player_colors", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "opponent_colors", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "player_lands", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "live_status", "opponent_lands", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "live_status", "turn_started_at", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "lands_seen", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "live_status", "cards_seen", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "live_status", "ramped_lands", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "live_status", "deck_size", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "live_status", "deck_lands", "INTEGER")
        AnalyticsStore.ensure_table_column(conn, "live_status", "opponent_cards", "TEXT")
        AnalyticsStore.ensure_table_column(conn, "live_status", "last_game_json", "TEXT")
        AnalyticsStore.backfill_game_turn_counts(conn)
        AnalyticsStore.apply_pending_migrations(conn)
        AnalyticsStore.canonicalize_imported_deck_names(conn)

    @staticmethod
    def canonicalize_imported_deck_names(conn: sqlite3.Connection) -> int:
        """Rename Arena's "Imported Deck" placeholders to the deck's real name.

        Importing a list and playing before renaming makes Arena submit the
        deck as "Imported Deck" / "Imported Deck (3)"; the tracker records
        what Arena said. Once the same exact maindeck shows up under a real
        name, this pass (run at every startup) retitles the placeholder games.
        Only an exact card-for-card maindeck match may rename — near-misses
        stay untouched. Returns the number of participants renamed.
        """
        placeholder = re.compile(r"^Imported Deck( \(\d+\))?$")
        candidates = [
            (row[0], str(row[1]))
            for row in conn.execute(
                """
                SELECT p.id, p.deck_name
                FROM participants p
                WHERE p.role = 'player' AND p.deck_name LIKE 'Imported Deck%'
                """
            )
            if placeholder.match(str(row[1] or ""))
        ]
        if not candidates:
            return 0

        def maindeck_signature(participant_id: object) -> tuple:
            return tuple(
                sorted(
                    (str(name), int(qty or 0))
                    for name, qty in conn.execute(
                        """
                        SELECT display_name, quantity FROM game_deck_cards
                        WHERE participant_id = ? AND deck_zone = 'deck'
                        """,
                        (participant_id,),
                    )
                )
            )

        # Newest real-named game per signature wins, matching what the deck
        # is called in Arena today.
        names_by_signature: dict = {}
        named_rows = conn.execute(
            """
            SELECT p.id, p.deck_name
            FROM participants p
            JOIN games g ON g.id = p.game_id
            WHERE p.role = 'player'
              AND COALESCE(p.deck_name, '') != ''
              AND p.deck_name NOT LIKE 'Imported Deck%'
              AND EXISTS (
                SELECT 1 FROM game_deck_cards d
                WHERE d.participant_id = p.id AND d.deck_zone = 'deck'
              )
            ORDER BY COALESCE(g.started_at, g.ended_at) ASC
            """
        ).fetchall()
        for participant_id, deck_name in named_rows:
            signature = maindeck_signature(participant_id)
            if signature:
                names_by_signature[signature] = str(deck_name)

        renamed = 0
        with conn:
            for participant_id, old_name in candidates:
                signature = maindeck_signature(participant_id)
                real_name = names_by_signature.get(signature) if signature else None
                if not real_name:
                    continue
                conn.execute(
                    "UPDATE participants SET deck_name = ? WHERE id = ?",
                    (real_name, participant_id),
                )
                print(f'📝 Renamed "{old_name}" game to its real deck: {real_name}')
                renamed += 1
        return renamed

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
            (6, AnalyticsStore._migrate_v6_merge_split_card_summary_rows),
            (7, AnalyticsStore._migrate_v7_backfill_bottomed_hands_from_console),
            (8, AnalyticsStore._migrate_v8_backfill_library_to_hand_draws),
            (9, AnalyticsStore._migrate_v9_delete_ghost_games),
            (10, AnalyticsStore._migrate_v10_delete_unknown_deck_games),
            (11, AnalyticsStore._migrate_v11_compress_raw_payloads),
            (12, AnalyticsStore._migrate_v12_delete_orphan_ghost_events),
            (13, AnalyticsStore._migrate_v13_merge_split_bo3_matches),
            (14, AnalyticsStore._migrate_v14_purge_untracked_modes),
            (15, AnalyticsStore._migrate_v15_purge_welcome_deck_duels),
            (16, AnalyticsStore._migrate_v16_removal_and_token_stats),
            (17, AnalyticsStore._migrate_v17_counter_magic_stats),
            (18, AnalyticsStore._migrate_v18_removal_loss_and_bounce_stats),
            (19, AnalyticsStore._migrate_v19_backfill_stats_from_events),
            (20, AnalyticsStore._migrate_v20_poison_stat),
            (21, AnalyticsStore._migrate_v21_repair_swapped_log_dates),
            (22, AnalyticsStore._migrate_v22_backfill_ramped_lands),
            (23, AnalyticsStore._migrate_v23_tag_ramped_lands_source),
            (24, AnalyticsStore._migrate_v24_reclassify_removal_stats),
            # v25 is the same recount, re-run because the classifier's rules
            # changed after v24 shipped (edicts, Split Up, airbend, O-Ring,
            # land-destruction lookahead). Any future rules change should add
            # another version pointing at the same function.
            (25, AnalyticsStore._migrate_v24_reclassify_removal_stats),
            # v26: threshold-sweeper ruling (outcome-based wipes; history
            # defaults them to removal) — same recount, new rules.
            (26, AnalyticsStore._migrate_v24_reclassify_removal_stats),
            (27, AnalyticsStore._migrate_v27_clear_self_named_opponents),
        )
        ran: list = []
        for version, migrate in migrations:
            if version in applied:
                continue
            migrate(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                "VALUES (?, datetime('now'))",
                (version,),
            )
            ran.append(version)
        conn.commit()
        if 11 in ran:
            # Compaction only frees pages; VACUUM returns them to the OS.
            # Must run outside any transaction, hence after the commit above.
            print("🗜️  Reclaiming disk space from the payload archive (VACUUM)…")
            conn.execute("VACUUM")
            print("🗜️  Done — database file compacted.")
        # Cheap per-launch maintenance: refreshes stale query-planner stats
        # for whichever indexes need it (no-op most launches).
        try:
            conn.execute("PRAGMA optimize")
        except sqlite3.Error:
            pass

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
    def backfill_card_colors(conn: sqlite3.Connection, colors_by_name) -> int:
        """Fill cards.color_identity for rows without one, matching by base name.

        colors_by_name maps clean card names to WUBRG letter strings (from the
        Arena card database). Only NULL rows are touched, so this is cheap to
        re-run at startup and after each game.
        """
        if not colors_by_name:
            return 0
        from .analytics_persistence import analytics_card_base_name

        updated = 0
        for card_id, name in conn.execute(
            "SELECT id, name FROM cards WHERE color_identity IS NULL"
        ).fetchall():
            base = analytics_card_base_name(str(name or ""))
            letters = colors_by_name.get(base)
            if letters is None and " // " in base:
                halves = [half.strip() for half in base.split(" // ")]
                merged = "".join(colors_by_name.get(half, "") for half in halves)
                if merged or all(half in colors_by_name for half in halves):
                    from .colors import normalize_colors

                    letters = normalize_colors(merged)
            if letters is None:
                continue
            conn.execute(
                "UPDATE cards SET color_identity = ? WHERE id = ?", (letters, card_id)
            )
            updated += 1
        if updated:
            conn.commit()
        return updated

    @staticmethod
    def backfill_card_mana(conn: sqlite3.Connection, mana_by_name) -> int:
        """Fill cards.mana_cost/mana_value for rows without one, by base name.

        mana_by_name maps clean card names to (Scryfall-style cost, mana value)
        tuples from the Arena card database (CardDatabase.mana_cost_index_by_name).
        Only NULL rows are touched, so this is cheap to re-run at startup and
        after each game. Split cards fall back to their front face's cost.
        """
        if not mana_by_name:
            return 0
        from .analytics_persistence import analytics_card_base_name

        updated = 0
        for card_id, name in conn.execute(
            "SELECT id, name FROM cards WHERE mana_cost IS NULL"
        ).fetchall():
            base = analytics_card_base_name(str(name or ""))
            entry = mana_by_name.get(base)
            if entry is None and " // " in base:
                entry = mana_by_name.get(base.split(" // ")[0].strip())
            if entry is None:
                continue
            cost, value = entry
            conn.execute(
                "UPDATE cards SET mana_cost = ?, mana_value = ? WHERE id = ?",
                (cost, float(value), card_id),
            )
            updated += 1
        if updated:
            conn.commit()
        return updated

    @staticmethod
    def _migrate_v10_delete_unknown_deck_games(conn: sqlite3.Connection) -> None:
        """Delete half-tracked games recorded without a player deck name.

        These are early-tracker and mid-game-attach games whose deck was never
        identified — they surface as an "(unknown)" deck with partial data
        (missing openers, unidentified draws) that pollutes every aggregate.
        Mid-game joins are no longer persisted at all, so this population
        cannot grow back.
        """
        doomed = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT g.id
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                WHERE COALESCE(p.deck_name, '') = ''
                """
            )
        ]
        for game_id in doomed:
            context = conn.execute(
                "SELECT session_id, match_id, started_at FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            if context is None:
                continue
            session_id, match_id, started_at = context
            conn.execute(
                """
                DELETE FROM participant_commanders
                WHERE participant_id IN (SELECT id FROM participants WHERE game_id = ?)
                """,
                (game_id,),
            )
            for table_name in (
                "game_opening_hand_cards",
                "game_mulligan_hands",
                "game_drawn_cards",
                "game_card_summary",
                "game_participant_stats",
                "game_turns",
                "game_events",
                "game_deck_cards",
                "game_annotations",
                "raw_game_payloads",
            ):
                conn.execute(f"DELETE FROM {table_name} WHERE game_id = ?", (game_id,))
            conn.execute("DELETE FROM participants WHERE game_id = ?", (game_id,))
            if session_id and started_at:
                conn.execute(
                    """
                    DELETE FROM console_logs
                    WHERE session_id = ? AND substr(match_started_at, 1, 19) = substr(?, 1, 19)
                    """,
                    (session_id, started_at),
                )
            conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
            conn.execute(
                "UPDATE matches SET games_played = (SELECT COUNT(*) FROM games WHERE match_id = ?) WHERE id = ?",
                (match_id, match_id),
            )
            conn.execute(
                "DELETE FROM matches WHERE id = ? AND NOT EXISTS (SELECT 1 FROM games WHERE match_id = ?)",
                (match_id, match_id),
            )
        conn.execute(
            """
            UPDATE tracker_sessions SET
                games_played = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id),
                wins = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id AND outcome = 'win'),
                losses = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id AND outcome = 'loss'),
                draws = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id AND outcome = 'draw'),
                unknown_results = (
                    SELECT COUNT(*) FROM games
                    WHERE session_id = tracker_sessions.id
                      AND COALESCE(outcome, 'unknown') NOT IN ('win', 'loss', 'draw')
                )
            """
        )

    @staticmethod
    def _migrate_v13_merge_split_bo3_matches(conn: sqlite3.Connection) -> None:
        """Merge Bo3 games that were split into separate one-game matches.

        Before the format normalizer learned that Traditional_* queues are
        Best-of-3, game 2/3 of such a match was recorded as a brand-new match
        (two "1-0 matches" instead of one 2-0). Merge criteria are strict:
        same session, a Bo3 queue, the SAME opponent name, consecutive games,
        and at most 20 minutes between one game's end and the next's start.
        """
        from datetime import datetime as _dt

        from .format_normalizer import normalize_match_format

        def _parse(ts: object) -> Optional[_dt]:
            try:
                return _dt.fromisoformat(str(ts))
            except (TypeError, ValueError):
                return None

        rows = conn.execute(
            """
            SELECT g.id, g.session_id, g.match_id, g.started_at, g.ended_at,
                   m.format,
                   (SELECT display_name FROM participants p
                     WHERE p.game_id = g.id AND p.role = 'opponent') AS opponent
            FROM games g
            JOIN matches m ON m.id = g.match_id
            ORDER BY g.session_id, COALESCE(g.started_at, g.ended_at), g.id
            """
        ).fetchall()

        chains: list = []
        current: list = []
        previous = None
        for row in rows:
            game_id, session_id, match_id, started_at, ended_at, fmt, opponent = row
            is_bo3 = normalize_match_format(str(fmt or "")).best_of == 3
            linkable = False
            if previous is not None and is_bo3 and opponent:
                prev_end = _parse(previous[4] or previous[3])
                this_start = _parse(started_at)
                linkable = (
                    previous[1] == session_id
                    and previous[6] == opponent
                    and previous[2] != match_id
                    and normalize_match_format(str(previous[5] or "")).best_of == 3
                    and prev_end is not None
                    and this_start is not None
                    and 0 <= (this_start - prev_end).total_seconds() <= 1200
                )
            if linkable:
                current.append(row)
            else:
                if len(current) > 1:
                    chains.append(current)
                current = [row]
            previous = row
        if len(current) > 1:
            chains.append(current)

        merged_games = 0
        for chain in chains:
            target_match = chain[0][2]
            for position, row in enumerate(chain, start=1):
                game_id, _session, match_id, *_rest = row
                conn.execute(
                    "UPDATE games SET match_id = ?, game_number = ? WHERE id = ?",
                    (target_match, position, game_id),
                )
                if match_id != target_match:
                    merged_games += 1
                    conn.execute(
                        "DELETE FROM matches WHERE id = ? AND NOT EXISTS "
                        "(SELECT 1 FROM games WHERE match_id = ?)",
                        (match_id, match_id),
                    )
            conn.execute(
                "UPDATE matches SET games_played = "
                "(SELECT COUNT(*) FROM games WHERE match_id = ?), "
                "ended_at = (SELECT MAX(COALESCE(ended_at, started_at)) FROM games WHERE match_id = ?) "
                "WHERE id = ?",
                (target_match, target_match, target_match),
            )
        if merged_games:
            print(
                f"🔗 Merged {merged_games} Bo3 game(s) back into their matches "
                f"({len(chains)} match(es) repaired)."
            )

    @staticmethod
    def _delete_games_and_recompute_sessions(conn: sqlite3.Connection, doomed_games) -> None:
        """Delete games (and all their child rows), drop emptied matches, and
        recompute the aggregates of every session that lost games. Shared by
        the untracked-mode purge migrations (v14 Jump In/MWM/Momir/Sparky,
        v15 Welcome Deck Duels)."""
        affected_sessions = {
            str(row[0])
            for game_id in doomed_games
            for row in conn.execute("SELECT session_id FROM games WHERE id = ?", (game_id,))
        }
        for game_id in doomed_games:
            conn.execute(
                "DELETE FROM participant_commanders WHERE participant_id IN "
                "(SELECT id FROM participants WHERE game_id = ?)",
                (game_id,),
            )
            for table_name in (
                "game_card_summary",
                "game_deck_cards",
                "game_opening_hand_cards",
                "game_mulligan_hands",
                "game_drawn_cards",
                "game_events",
                "game_turns",
                "game_participant_stats",
                "game_annotations",
                "participants",
            ):
                conn.execute(f"DELETE FROM {table_name} WHERE game_id = ?", (game_id,))
            conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
        conn.execute(
            "DELETE FROM matches WHERE NOT EXISTS (SELECT 1 FROM games g WHERE g.match_id = matches.id)"
        )

        # Recompute the aggregates of sessions that lost games.
        for session_id in affected_sessions:
            counts = conn.execute(
                """
                SELECT COUNT(*),
                       SUM(outcome = 'win'),
                       SUM(outcome = 'loss'),
                       SUM(outcome = 'draw'),
                       SUM(outcome NOT IN ('win', 'loss', 'draw'))
                FROM games WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if not counts or not counts[0]:
                conn.execute("DELETE FROM tracker_sessions WHERE id = ?", (session_id,))
                continue
            conn.execute(
                "UPDATE tracker_sessions SET games_played = ?, wins = ?, losses = ?, "
                "draws = ?, unknown_results = ? WHERE id = ?",
                (
                    int(counts[0]),
                    int(counts[1] or 0),
                    int(counts[2] or 0),
                    int(counts[3] or 0),
                    int(counts[4] or 0),
                    session_id,
                ),
            )

    @staticmethod
    def _migrate_v16_removal_and_token_stats(conn: sqlite3.Connection) -> None:
        """Add removal/board-wipe/land-destruction/token columns to stats.

        Nullable on purpose: games recorded before this feature stay NULL so
        the dashboard can distinguish "not tracked yet" from a real zero.
        """
        existing = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(game_participant_stats)")
        }
        for column in (
            "removal_drawn",
            "removal_played",
            "wipes_drawn",
            "wipes_played",
            "bounces_drawn",
            "bounces_played",
            "lands_lost",
            "lands_replaced",
            "tokens_created",
            "tokens_destroyed",
            "tokens_sacrificed",
            "tokens_exiled",
        ):
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE game_participant_stats ADD COLUMN {column} INTEGER"
                )

    @staticmethod
    def _migrate_v17_counter_magic_stats(conn: sqlite3.Connection) -> None:
        """Add counter-magic columns (nullable, like the v16 removal set)."""
        existing = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(game_participant_stats)")
        }
        for column in ("counters_drawn", "counters_played", "spells_countered"):
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE game_participant_stats ADD COLUMN {column} INTEGER"
                )

    @staticmethod
    def _migrate_v18_removal_loss_and_bounce_stats(conn: sqlite3.Connection) -> None:
        """Add creature/non-creature removal-loss and bounce columns (nullable)."""
        existing = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(game_participant_stats)")
        }
        for column in (
            "creatures_removed",
            "noncreatures_removed",
            "creatures_bounced",
            "noncreatures_bounced",
        ):
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE game_participant_stats ADD COLUMN {column} INTEGER"
                )

    #: (table, timestamp columns, SQL producing "<rowid>, <session started_at>")
    #: for every log-derived timestamp the swapped-date repair must cover.
    _SWAPPED_DATE_TARGETS = (
        ("matches", ("started_at", "ended_at"),
         "SELECT m.id, s.started_at FROM matches m "
         "JOIN tracker_sessions s ON s.id = m.session_id"),
        ("games", ("started_at", "ended_at"),
         "SELECT g.id, s.started_at FROM games g "
         "JOIN tracker_sessions s ON s.id = g.session_id"),
        ("game_turns", ("started_at", "ended_at"),
         "SELECT t.id, s.started_at FROM game_turns t "
         "JOIN games g ON g.id = t.game_id "
         "JOIN tracker_sessions s ON s.id = g.session_id"),
        ("game_events", ("event_time",),
         "SELECT e.id, s.started_at FROM game_events e "
         "JOIN tracker_sessions s ON s.id = e.session_id"),
        ("console_logs", ("created_at",),
         "SELECT c.id, s.started_at FROM console_logs c "
         "JOIN tracker_sessions s ON s.id = c.session_id"),
        ("rank_snapshots", ("captured_at",),
         "SELECT r.id, s.started_at FROM rank_snapshots r "
         "JOIN tracker_sessions s ON s.id = r.session_id"),
        ("raw_game_payloads", ("created_at",),
         "SELECT p.id, s.started_at FROM raw_game_payloads p "
         "JOIN tracker_sessions s ON s.id = p.session_id"),
    )

    @staticmethod
    def _swapped_date_repair(value: object, session_start: datetime) -> Optional[str]:
        """Return the month/day-swapped timestamp when that is clearly the truth.

        Trackers before the locale-aware log parser read day-first log dates
        as month-first, storing e.g. 9 August as September 8. The session row's
        started_at comes from the system clock (never log-parsed), so it
        anchors reality: a timestamp far from its session whose month/day swap
        lands inside the session window was mis-parsed. Conservative on
        purpose — anything ambiguous is left alone.
        """
        text = str(value or "")
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            return None
        if abs((stamp - session_start).total_seconds()) <= 5 * 86400:
            return None  # close enough to the session to be legitimate
        if stamp.day > 12:
            return None  # swapping would produce month > 12
        try:
            swapped = stamp.replace(month=stamp.day, day=stamp.month)
        except ValueError:
            return None
        delta = (swapped - session_start).total_seconds()
        # A session's log timestamps live near its start: allow the previous
        # day (log lines read at startup) through a generous multi-day session.
        if -2 * 86400 <= delta <= 3 * 86400:
            return swapped.isoformat()
        return None

    @staticmethod
    def _migrate_v21_repair_swapped_log_dates(conn: sqlite3.Connection) -> None:
        """One-time repair of timestamps stored with month and day swapped.

        Fixes games recorded by day-first-locale users (dd/mm log dates read
        as mm/dd) that landed months in the future and scrambled every
        date-ordered view. See _swapped_date_repair for the detection rule.
        """
        repaired = 0
        for table, columns, query in AnalyticsStore._SWAPPED_DATE_TARGETS:
            column_list = ", ".join(columns)
            for row_id, session_start_text in conn.execute(query).fetchall():
                try:
                    session_start = datetime.fromisoformat(str(session_start_text))
                except (TypeError, ValueError):
                    continue
                current = conn.execute(
                    f"SELECT {column_list} FROM {table} WHERE id = ?", (row_id,)
                ).fetchone()
                if current is None:
                    continue
                updates = {}
                for column, value in zip(columns, current):
                    fixed = AnalyticsStore._swapped_date_repair(value, session_start)
                    if fixed is not None:
                        updates[column] = fixed
                if updates:
                    assignments = ", ".join(f"{c} = ?" for c in updates)
                    conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE id = ?",
                        tuple(updates.values()) + (row_id,),
                    )
                    repaired += 1
        if repaired:
            print(
                f"🗓️  Repaired {repaired} row(s) whose dates were stored month/day-"
                "swapped by older versions (day-first locales)."
            )

    @staticmethod
    def _migrate_v20_poison_stat(conn: sqlite3.Connection) -> None:
        """Add the poison_added column (nullable — not reconstructable)."""
        existing = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(game_participant_stats)")
        }
        if "poison_added" not in existing:
            conn.execute(
                "ALTER TABLE game_participant_stats ADD COLUMN poison_added INTEGER"
            )

    @staticmethod
    def _migrate_v19_backfill_stats_from_events(conn: sqlite3.Connection) -> None:
        """One-time backfill of behavioral stats from the game_events timeline.

        Every game's structured timeline already records destroys, exiles,
        bounces, land drops, and countered spells, so historical games can be
        given real values for the stats that need no card-text classification:
        creatures/non-creatures removed and bounced, lands lost/replaced, and
        spells countered. Only NULL columns are filled — games tracked live by
        a version that already counts these are never overwritten. Games with
        no timeline rows stay NULL ("not tracked"), and known limitations are
        deliberate undercounts: lethal-damage deaths are skipped (burn kills
        cannot be split from combat deaths after the fact) and forced
        sacrifices are skipped (the forcing player is not in the timeline).
        """
        from .events_backfill import backfill_game_stats_from_events

        backfill_game_stats_from_events(conn)

    @staticmethod
    def _migrate_v15_purge_welcome_deck_duels(conn: sqlite3.Connection) -> None:
        """Delete Welcome Deck Duels games (pre-made deck vs pre-made deck).

        The mode joined the untracked list after some games had already
        persisted (e.g. format "Welcome Deck Duels HOB"); like the other
        novelty modes, it would skew constructed win rates and draw math.
        """
        from .format_normalizer import is_welcome_deck_format

        doomed_matches = [
            str(row[0])
            for row in conn.execute("SELECT id, format, queue, event_name FROM matches")
            if any(is_welcome_deck_format(value) for value in row[1:])
        ]
        doomed_games = set()
        for match_id in doomed_matches:
            for row in conn.execute("SELECT id FROM games WHERE match_id = ?", (match_id,)):
                doomed_games.add(str(row[0]))
        if not doomed_games:
            return
        AnalyticsStore._delete_games_and_recompute_sessions(conn, doomed_games)
        print(
            f"🚫 Removed {len(doomed_games)} Welcome Deck Duels game(s) "
            "(pre-made deck mode; not tracked)."
        )

    @staticmethod
    def _migrate_v14_purge_untracked_modes(conn: sqlite3.Connection) -> None:
        """Delete games from modes the tracker intentionally does not track.

        Jump In, Midweek Magic, Momir, and practice games vs Sparky slipped
        into some databases before the exclusion checked the raw queue/event
        name (a Jump In game could persist with format "Unknown" while the
        event still said Jump_In_MSH). Also removes permanently unresolvable
        "Card #N" summary/opening-hand labels that the startup backfill can
        never fix, so db_audit stops warning about them.
        """
        from .format_normalizer import is_jump_in_format, is_midweek_format, is_momir_format

        doomed_matches = [
            str(row[0])
            for row in conn.execute("SELECT id, format, queue, event_name FROM matches")
            if any(
                is_jump_in_format(value) or is_midweek_format(value) or is_momir_format(value)
                for value in row[1:]
            )
        ]
        doomed_games = {
            str(row[0])
            for row in conn.execute(
                "SELECT game_id FROM participants "
                "WHERE role = 'opponent' AND LOWER(COALESCE(display_name, '')) = 'sparky'"
            )
        }
        for match_id in doomed_matches:
            for row in conn.execute("SELECT id FROM games WHERE match_id = ?", (match_id,)):
                doomed_games.add(str(row[0]))

        AnalyticsStore._delete_games_and_recompute_sessions(conn, doomed_games)

        # Only labels in games older than a week are truly dead: a brand-new
        # set's card can resolve once Arena updates its local card database,
        # and the startup backfill retries recent ones every launch.
        label_rows = 0
        for table_name in ("game_card_summary", "game_opening_hand_cards"):
            cursor = conn.execute(
                f"""
                DELETE FROM {table_name}
                WHERE display_name LIKE 'Card #%'
                  AND game_id IN (
                    SELECT id FROM games
                    WHERE COALESCE(started_at, '') < datetime('now', '-7 days')
                  )
                """
            )
            label_rows += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        if doomed_games or label_rows:
            print(
                f"🚫 Removed {len(doomed_games)} untracked-mode game(s) "
                f"(Jump In / Midweek Magic / Momir / vs Sparky) and "
                f"{label_rows} unresolvable card label row(s)."
            )

    @staticmethod
    def _migrate_v12_delete_orphan_ghost_events(conn: sqlite3.Connection) -> None:
        """Delete stray events left behind by skipped ghost games.

        The ghost guard refuses to persist post-concede tails, but events
        stream to SQLite live, so a stray row could survive under a game id
        that has no games row. Only ghost-thin evidence is removed: at most
        three events, no turn events, and no recorded turn timings — a real
        lost game (which db_audit can reconstruct) has far more than that.
        """
        doomed = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT e.game_id
                FROM game_events e
                WHERE e.game_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM games g WHERE g.id = e.game_id)
                GROUP BY e.game_id
                HAVING COUNT(*) <= 3
                   AND SUM(e.event_type = 'turn') = 0
                   AND NOT EXISTS (
                     SELECT 1 FROM game_turns t WHERE t.game_id = e.game_id
                   )
                """
            ).fetchall()
        ]
        for game_id in doomed:
            conn.execute("DELETE FROM game_events WHERE game_id = ?", (game_id,))
        if doomed:
            print(f"👻 Removed stray events from {len(doomed)} skipped ghost game(s).")

    @staticmethod
    def _migrate_v11_compress_raw_payloads(conn: sqlite3.Connection) -> None:
        """Compress legacy plain-text rows in the raw payload archive.

        raw_game_payloads held ~78% of the database as uncompressed Arena
        JSON. New rows are written zlib-compressed; this one-time pass brings
        the existing archive into the same format (lossless — decode_payload
        returns byte-identical JSON). The follow-up VACUUM in
        apply_pending_migrations reclaims the freed pages.
        """
        total = conn.execute("SELECT COUNT(*) FROM raw_game_payloads").fetchone()[0]
        if not total:
            return
        print(f"🗜️  Compressing raw payload archive ({total} rows)…")
        compressed = 0
        cursor = conn.execute(
            "SELECT id, payload_json FROM raw_game_payloads"
        )
        write = conn.cursor()
        while True:
            batch = cursor.fetchmany(500)
            if not batch:
                break
            for row_id, payload in batch:
                # Bytes rows are already compressed (or at least binary) —
                # only legacy TEXT rows need converting.
                if not isinstance(payload, str):
                    continue
                write.execute(
                    "UPDATE raw_game_payloads SET payload_json = ? WHERE id = ?",
                    (compress_payload(payload), row_id),
                )
                compressed += 1
        if compressed:
            print(f"🗜️  Compressed {compressed} payload rows.")

    @staticmethod
    def _migrate_v9_delete_ghost_games(conn: sqlite3.Connection) -> None:
        """Delete ghost games spawned by post-concede message tails.

        A trailing game-state after a concede could be misread as a new game,
        creating a record with zero turns, zero duration, no opening hand, and
        no draws. Remove them and their dependents; drop the parent match when
        it holds no other games.
        """
        ghosts = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT g.id FROM games g
                WHERE COALESCE(g.total_turns, 0) = 0
                  AND COALESCE(
                g.duration_seconds,
                CAST((julianday(g.ended_at) - julianday(g.started_at)) * 86400 AS INTEGER),
                0
              ) <= 1
                  AND NOT EXISTS (SELECT 1 FROM game_turns t WHERE t.game_id = g.id)
                  AND NOT EXISTS (SELECT 1 FROM game_opening_hand_cards h WHERE h.game_id = g.id)
                  AND NOT EXISTS (SELECT 1 FROM game_drawn_cards d WHERE d.game_id = g.id)
                """
            )
        ]
        for game_id in ghosts:
            context = conn.execute(
                "SELECT session_id, match_id FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            if context is None:
                continue
            session_id, match_id = context
            conn.execute(
                """
                DELETE FROM participant_commanders
                WHERE participant_id IN (SELECT id FROM participants WHERE game_id = ?)
                """,
                (game_id,),
            )
            for table_name in (
                "game_opening_hand_cards",
                "game_mulligan_hands",
                "game_drawn_cards",
                "game_card_summary",
                "game_participant_stats",
                "game_turns",
                "game_events",
                "game_deck_cards",
                "game_annotations",
                "raw_game_payloads",
            ):
                conn.execute(f"DELETE FROM {table_name} WHERE game_id = ?", (game_id,))
            conn.execute("DELETE FROM participants WHERE game_id = ?", (game_id,))
            conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
            conn.execute(
                "UPDATE matches SET games_played = (SELECT COUNT(*) FROM games WHERE match_id = ?) WHERE id = ?",
                (match_id, match_id),
            )
            conn.execute(
                "DELETE FROM matches WHERE id = ? AND NOT EXISTS (SELECT 1 FROM games WHERE match_id = ?)",
                (match_id, match_id),
            )
            conn.execute(
                """
                UPDATE tracker_sessions SET
                    games_played = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id),
                    wins = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id AND outcome = 'win'),
                    losses = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id AND outcome = 'loss'),
                    draws = (SELECT COUNT(*) FROM games WHERE session_id = tracker_sessions.id AND outcome = 'draw'),
                    unknown_results = (
                        SELECT COUNT(*) FROM games
                        WHERE session_id = tracker_sessions.id
                          AND COALESCE(outcome, 'unknown') NOT IN ('win', 'loss', 'draw')
                    )
                WHERE id = ?
                """,
                (session_id,),
            )

    #: Basic land names, recognized even when the local card DB predates them.
    _BASIC_LAND_NAMES = frozenset(
        {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}
    )

    @staticmethod
    def _name_is_land(conn: sqlite3.Connection, name: str) -> bool:
        """True when a card name is a land — the only 'put onto battlefield'
        cards a historical backfill can safely attribute to library ramp.

        The stored timeline never recorded the source zone, so a creature
        'put onto battlefield' is ambiguous (reanimation, blink, a library
        cheat, a token). Lands are not: a land entering play this way is
        overwhelmingly a ramp/search from the library, so restricting to
        lands keeps the backfill honest.
        """
        base = name.split(" (")[0].strip()
        if base in AnalyticsStore._BASIC_LAND_NAMES:
            return True
        row = conn.execute(
            "SELECT type_line, primary_type FROM cards WHERE name = ? OR name LIKE ? LIMIT 1",
            (name, f"{base} (%"),
        ).fetchone()
        if not row:
            return False
        type_line = str(row[0] or "")
        primary = str(row[1] or "")
        return "land" in type_line.casefold() or primary.casefold() == "land"

    @staticmethod
    def _migrate_v22_backfill_ramped_lands(conn: sqlite3.Connection) -> None:
        """Count historical lands ramped/searched onto the battlefield.

        A land pulled from the library straight onto the battlefield (Lumbering
        Worldwagon, Cultivate, fetch lands, …) printed a "put [Land] onto
        battlefield" timeline event but was never recorded in game_drawn_cards,
        so it was invisible to Lands Seen and flood/screw detection. This is
        the battlefield twin of v8's library-to-hand backfill, restricted to
        lands because the stored events did not keep the source zone.
        """
        put_pattern = re.compile(r"put \[([^\]]+)\] onto battlefield\b")
        games = conn.execute(
            """
            SELECT DISTINCT game_id FROM game_events
            WHERE actor_role = 'player' AND text LIKE '%onto battlefield%'
              AND game_id IS NOT NULL
            """
        ).fetchall()
        for (game_id,) in games:
            participant_row = conn.execute(
                "SELECT id FROM participants WHERE game_id = ? AND role = 'player'",
                (game_id,),
            ).fetchone()
            if not participant_row:
                continue
            participant_id = str(participant_row[0])
            put_events = []
            for event_time, event_id, text in conn.execute(
                """
                SELECT event_time, id, text FROM game_events
                WHERE game_id = ? AND actor_role = 'player'
                  AND text LIKE '%put [%] onto battlefield%'
                ORDER BY event_time, id
                """,
                (game_id, ),
            ):
                match = put_pattern.search(str(text or ""))
                if not match:
                    continue
                name = match.group(1).strip()
                if not AnalyticsStore._name_is_land(conn, name):
                    continue  # only lands can be safely attributed to ramp
                turn_row = conn.execute(
                    "SELECT turn_number FROM game_events WHERE id = ?", (event_id,)
                ).fetchone()
                put_events.append(
                    {"name": name, "turn": turn_row[0] if turn_row else None}
                )
            if not put_events:
                continue
            drawn_rows = [
                {"id": row[0], "name": str(row[1] or ""), "turn": row[2], "position": int(row[3] or 0)}
                for row in conn.execute(
                    """
                    SELECT id, display_name, turn_number, draw_position
                    FROM game_drawn_cards
                    WHERE game_id = ? AND participant_id = ?
                    ORDER BY draw_position
                    """,
                    (game_id, participant_id),
                )
            ]
            already_counted = {(e["name"], e["turn"]) for e in put_events} & {
                (row["name"], row["turn"]) for row in drawn_rows
            }
            if already_counted:
                # A tracker new enough to record these already counted them.
                continue
            # Slot each ramped land after the last draw of the same-or-earlier
            # turn, so draw order stays sensible.
            merged = list(drawn_rows)
            for entry in put_events:
                insert_at = len(merged)
                for index in range(len(merged) - 1, -1, -1):
                    row_turn = merged[index].get("turn")
                    if row_turn is not None and entry["turn"] is not None and int(row_turn) <= int(entry["turn"]):
                        insert_at = index + 1
                        break
                    if row_turn is not None and entry["turn"] is not None:
                        insert_at = index
                merged.insert(insert_at, {"name": entry["name"], "turn": entry["turn"], "id": None})
            # Move existing rows clear of the UNIQUE(draw_position) constraint,
            # then renumber everything and insert the ramped lands.
            conn.execute(
                "UPDATE game_drawn_cards SET draw_position = draw_position + 1000 "
                "WHERE game_id = ? AND participant_id = ?",
                (game_id, participant_id),
            )
            copy_counts: dict = {}
            for position, item in enumerate(merged, start=1):
                copy_counts[item["name"]] = copy_counts.get(item["name"], 0) + 1
                if item["id"] is not None:
                    conn.execute(
                        "UPDATE game_drawn_cards SET draw_position = ?, copy_number = ? WHERE id = ?",
                        (position, copy_counts[item["name"]], item["id"]),
                    )
                    continue
                card_row = conn.execute(
                    "SELECT id, primary_type FROM cards WHERE name = ? OR name LIKE ? LIMIT 1",
                    (item["name"], f"{item['name'].split(' (')[0]} (%"),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO game_drawn_cards (
                        game_id, participant_id, card_id, display_name,
                        type_category, draw_position, turn_number, copy_number
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        participant_id,
                        card_row[0] if card_row else None,
                        item["name"],
                        card_row[1] if card_row else "Land",
                        position,
                        item["turn"],
                        copy_counts[item["name"]],
                    ),
                )
                summary = conn.execute(
                    """
                    SELECT id FROM game_card_summary
                    WHERE game_id = ? AND participant_id = ?
                      AND (display_name = ? OR display_name LIKE ?)
                    """,
                    (game_id, participant_id, item["name"], f"{item['name'].split(' (')[0]} (%"),
                ).fetchone()
                if summary:
                    conn.execute(
                        "UPDATE game_card_summary SET drawn_count = drawn_count + 1 WHERE id = ?",
                        (summary[0],),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO game_card_summary (
                            game_id, participant_id, card_id, display_name,
                            type_category, played_count, drawn_count
                        ) VALUES (?, ?, ?, ?, ?, 0, 1)
                        """,
                        (
                            game_id,
                            participant_id,
                            card_row[0] if card_row else None,
                            item["name"],
                            card_row[1] if card_row else "Land",
                        ),
                    )
            conn.execute(
                "UPDATE game_participant_stats SET cards_drawn = cards_drawn + ? "
                "WHERE game_id = ? AND participant_id = ?",
                (len(put_events), game_id, participant_id),
            )

    @staticmethod
    def _migrate_v24_reclassify_removal_stats(conn: sqlite3.Connection) -> None:
        """Recompute removal/wipe/bounce/counter stats with the fixed classifier.

        The removal patterns used to match graveyard hate ("exile target card
        from a graveyard"), so cards like Intrepid Paleontologist counted as
        removal played in every historical game. These counts derive purely
        from played/drawn cards x the text classifier, so they can be rebuilt
        exactly. Requires Arena's card database for ability texts; when it
        isn't available (Arena not installed on this machine) the migration
        leaves the stats untouched — the next launch that can read it will
        not rerun, but live games count correctly either way.
        """
        try:
            from .card_database import CardDatabase
            from .removal_classifier import RemovalClassifier
        except Exception:
            return
        try:
            card_db = CardDatabase()
            classifier = RemovalClassifier(card_db)
        except Exception:
            return

        def base(name: str) -> str:
            return str(name or "").split(" (")[0].strip()

        # name -> arena_id from the analytics DB's own cards table.
        name_to_id: dict = {}
        try:
            for name, arena_id in conn.execute(
                "SELECT name, arena_id FROM cards WHERE arena_id IS NOT NULL"
            ):
                if name:
                    name_to_id.setdefault(base(str(name)), int(arena_id))
        except sqlite3.OperationalError:
            return

        roles_cache: dict = {}
        texts_seen = 0

        def roles_for_name(display_name: str):
            nonlocal texts_seen
            key = base(display_name)
            if key in roles_cache:
                return roles_cache[key]
            arena_id = name_to_id.get(key)
            roles = frozenset()
            if arena_id is not None:
                roles = classifier.roles_for(arena_id)
                try:
                    if card_db.get_card_ability_texts(arena_id):
                        texts_seen += 1
                except Exception:
                    pass
            roles_cache[key] = roles
            return roles

        role_to_played = {
            "removal": "removal_played",
            "wipe": "wipes_played",
            # Historical games can't verify whether a conditional sweeper
            # actually cleared the board — counted as removal (the ruling's
            # default); live games judge these by outcome.
            "threshold_wipe": "removal_played",
            "bounce": "bounces_played",
            "counter": "counters_played",
        }
        role_to_drawn = {
            "removal": "removal_drawn",
            "wipe": "wipes_drawn",
            "threshold_wipe": "removal_drawn",
            "bounce": "bounces_drawn",
            "counter": "counters_drawn",
        }

        updates = []
        for (participant_id,) in conn.execute(
            "SELECT participant_id FROM game_participant_stats"
        ).fetchall():
            played = {column: 0 for column in role_to_played.values()}
            for display_name, count in conn.execute(
                "SELECT display_name, played_count FROM game_card_summary "
                "WHERE participant_id = ? AND played_count > 0",
                (participant_id,),
            ):
                for role in roles_for_name(str(display_name or "")):
                    column = role_to_played.get(role)
                    if column:
                        played[column] += int(count or 0)
            drawn = {column: 0 for column in role_to_drawn.values()}
            for (display_name,) in conn.execute(
                "SELECT display_name FROM game_drawn_cards WHERE participant_id = ?",
                (participant_id,),
            ):
                for role in roles_for_name(str(display_name or "")):
                    column = role_to_drawn.get(role)
                    if column:
                        drawn[column] += 1
            updates.append((participant_id, played, drawn))

        # Sample check: if the card DB yielded no ability texts at all, the
        # classifier saw nothing and every count would collapse to zero —
        # that is data loss, not a fix. Leave history alone in that case.
        if texts_seen == 0:
            return

        for participant_id, played, drawn in updates:
            assignments = {**played, **drawn}
            set_clause = ", ".join(f"{column} = ?" for column in assignments)
            conn.execute(
                f"UPDATE game_participant_stats SET {set_clause} WHERE participant_id = ?",
                (*assignments.values(), participant_id),
            )

    @staticmethod
    def _migrate_v27_clear_self_named_opponents(conn: sqlite3.Connection) -> None:
        """Clear opponent names that are actually the player's own name.

        A name-attribution bug briefly wrote the local player's display name
        onto the opponent seat (opponent deck NULL, clearly another player's
        cards), so 'you' showed up in your own opponents list. Arena names
        are stored without discriminators, so a same-string opponent IS the
        misattribution in practice; the real name was never captured and
        cannot be recovered — these games fall back to the unnamed-opponent
        placeholder behavior.
        """
        conn.execute(
            """
            UPDATE participants SET display_name = NULL
            WHERE role = 'opponent' AND display_name IS NOT NULL
              AND display_name = (
                SELECT p.display_name FROM participants p
                WHERE p.game_id = participants.game_id AND p.role = 'player'
              )
            """
        )

    @staticmethod
    def _migrate_v23_tag_ramped_lands_source(conn: sqlite3.Connection) -> None:
        """Tag ramped/searched lands in game_drawn_cards with source='ramp'.

        v22 recorded lands put from the library onto the battlefield into
        game_drawn_cards, but with no way to tell them apart from lands that
        were actually drawn. This adds the ``source`` column (older databases
        lack it) and marks those ramped lands so the flood/screw math can keep
        them in Lands Seen while excluding them from the flood side — a land
        searched out on purpose is not a land drawn against your will.

        Ramped rows are re-identified from the same "put [Land] onto
        battlefield" timeline events v22 used, matched to their drawn rows by
        base card name and turn (v22 stamped each inserted row with the event's
        turn). This also covers games a newer tracker had already recorded live
        (which v22 skipped), so every historical ramped land is tagged.
        """
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(game_drawn_cards)").fetchall()
        }
        if "source" not in columns:
            conn.execute("ALTER TABLE game_drawn_cards ADD COLUMN source TEXT")

        put_pattern = re.compile(r"put \[([^\]]+)\] onto battlefield\b")

        def base_name(name: str) -> str:
            return str(name or "").split(" (")[0].strip().casefold()

        games = conn.execute(
            """
            SELECT DISTINCT game_id FROM game_events
            WHERE actor_role = 'player' AND text LIKE '%onto battlefield%'
              AND game_id IS NOT NULL
            """
        ).fetchall()
        for (game_id,) in games:
            participant_row = conn.execute(
                "SELECT id FROM participants WHERE game_id = ? AND role = 'player'",
                (game_id,),
            ).fetchone()
            if not participant_row:
                continue
            participant_id = str(participant_row[0])
            # Multiset of (base name, turn) for each land put onto the battlefield.
            wanted: dict = {}
            for event_id, text in conn.execute(
                """
                SELECT id, text FROM game_events
                WHERE game_id = ? AND actor_role = 'player'
                  AND text LIKE '%put [%] onto battlefield%'
                """,
                (game_id,),
            ):
                match = put_pattern.search(str(text or ""))
                if not match:
                    continue
                name = match.group(1).strip()
                if not AnalyticsStore._name_is_land(conn, name):
                    continue
                turn_row = conn.execute(
                    "SELECT turn_number FROM game_events WHERE id = ?", (event_id,)
                ).fetchone()
                turn = turn_row[0] if turn_row else None
                key = (base_name(name), turn)
                wanted[key] = wanted.get(key, 0) + 1
            if not wanted:
                continue
            for row_id, display_name, turn_number in conn.execute(
                """
                SELECT id, display_name, turn_number
                FROM game_drawn_cards
                WHERE game_id = ? AND participant_id = ? AND source IS NULL
                ORDER BY draw_position
                """,
                (game_id, participant_id),
            ).fetchall():
                key = (base_name(display_name), turn_number)
                if wanted.get(key, 0) > 0:
                    conn.execute(
                        "UPDATE game_drawn_cards SET source = 'ramp' WHERE id = ?",
                        (row_id,),
                    )
                    wanted[key] -= 1

    @staticmethod
    def _migrate_v8_backfill_library_to_hand_draws(conn: sqlite3.Connection) -> None:
        """Count historical library-to-hand transfers as drawn cards.

        Explore, discover, and similar effects printed "put [X] into your
        hand" timeline events but never recorded the card in game_drawn_cards,
        so those cards were invisible to the drawn list and flood/screw
        detection. Merge them into the draw order (by event time when the
        game's named draw events pair cleanly with its drawn rows, otherwise
        by turn), renumber positions, and update the summary/stat counters.
        """
        put_pattern = re.compile(r"put \[([^\]]+)\] into your hand")
        games = conn.execute(
            """
            SELECT DISTINCT game_id FROM game_events
            WHERE actor_role = 'player' AND text LIKE '%into your hand%'
              AND game_id IS NOT NULL
            """
        ).fetchall()
        for (game_id,) in games:
            participant_row = conn.execute(
                "SELECT id FROM participants WHERE game_id = ? AND role = 'player'",
                (game_id,),
            ).fetchone()
            if not participant_row:
                continue
            participant_id = str(participant_row[0])
            put_events = []
            for event_time, event_id, text in conn.execute(
                """
                SELECT event_time, id, text FROM game_events
                WHERE game_id = ? AND actor_role = 'player'
                  AND text LIKE '%put [%] into your hand%'
                ORDER BY event_time, id
                """,
                (game_id,),
            ):
                match = put_pattern.search(str(text or ""))
                if match:
                    turn_row = conn.execute(
                        "SELECT turn_number FROM game_events WHERE id = ?", (event_id,)
                    ).fetchone()
                    put_events.append(
                        {
                            "name": match.group(1).strip(),
                            "time": str(event_time or ""),
                            "turn": turn_row[0] if turn_row else None,
                        }
                    )
            if not put_events:
                continue
            drawn_rows = [
                {
                    "id": row[0],
                    "name": str(row[1] or ""),
                    "turn": row[2],
                    "position": int(row[3] or 0),
                }
                for row in conn.execute(
                    """
                    SELECT id, display_name, turn_number, draw_position
                    FROM game_drawn_cards
                    WHERE game_id = ? AND participant_id = ?
                    ORDER BY draw_position
                    """,
                    (game_id, participant_id),
                )
            ]
            already_counted = {
                (entry["name"], entry["turn"]) for entry in put_events
            } & {
                (row["name"], row["turn"]) for row in drawn_rows
            }
            if already_counted:
                # A tracker new enough to record these already counted them.
                continue
            named_draws = [
                str(row[0] or "")
                for row in conn.execute(
                    """
                    SELECT event_time FROM game_events
                    WHERE game_id = ? AND actor_role = 'player'
                      AND text LIKE '%drew [%'
                    ORDER BY event_time, id
                    """,
                    (game_id,),
                )
            ]
            if len(named_draws) == len(drawn_rows):
                for row, event_time in zip(drawn_rows, named_draws):
                    row["time"] = event_time
                merged = sorted(
                    drawn_rows + [
                        {"name": e["name"], "turn": e["turn"], "time": e["time"], "id": None}
                        for e in put_events
                    ],
                    key=lambda item: item.get("time") or "",
                )
            else:
                # No clean event pairing: slot each put after the last draw of
                # the same or an earlier turn.
                merged = list(drawn_rows)
                for entry in put_events:
                    insert_at = len(merged)
                    for index in range(len(merged) - 1, -1, -1):
                        row_turn = merged[index].get("turn")
                        if (
                            row_turn is not None
                            and entry["turn"] is not None
                            and int(row_turn) <= int(entry["turn"])
                        ):
                            insert_at = index + 1
                            break
                        if row_turn is not None and entry["turn"] is not None:
                            insert_at = index
                    merged.insert(
                        insert_at,
                        {"name": entry["name"], "turn": entry["turn"], "time": None, "id": None},
                    )
            # Renumber every position (moving existing rows out of the way of
            # the UNIQUE constraint first), then insert the new put rows.
            conn.execute(
                """
                UPDATE game_drawn_cards SET draw_position = draw_position + 1000
                WHERE game_id = ? AND participant_id = ?
                """,
                (game_id, participant_id),
            )
            copy_counts: dict = {}
            for position, item in enumerate(merged, start=1):
                copy_counts[item["name"]] = copy_counts.get(item["name"], 0) + 1
                if item["id"] is not None:
                    conn.execute(
                        """
                        UPDATE game_drawn_cards
                        SET draw_position = ?, copy_number = ?
                        WHERE id = ?
                        """,
                        (position, copy_counts[item["name"]], item["id"]),
                    )
                    continue
                card_row = conn.execute(
                    "SELECT id, primary_type FROM cards WHERE name = ? OR name LIKE ? LIMIT 1",
                    (item["name"], f"{item['name']} (%"),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO game_drawn_cards (
                        game_id, participant_id, card_id, display_name,
                        type_category, draw_position, turn_number, copy_number
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        participant_id,
                        card_row[0] if card_row else None,
                        item["name"],
                        card_row[1] if card_row else None,
                        position,
                        item["turn"],
                        copy_counts[item["name"]],
                    ),
                )
                summary = conn.execute(
                    """
                    SELECT id FROM game_card_summary
                    WHERE game_id = ? AND participant_id = ?
                      AND (display_name = ? OR display_name LIKE ?)
                    """,
                    (game_id, participant_id, item["name"], f"{item['name']} (%"),
                ).fetchone()
                if summary:
                    conn.execute(
                        "UPDATE game_card_summary SET drawn_count = drawn_count + 1 WHERE id = ?",
                        (summary[0],),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO game_card_summary (
                            game_id, participant_id, card_id, display_name,
                            type_category, played_count, drawn_count
                        ) VALUES (?, ?, ?, ?, ?, 0, 1)
                        """,
                        (
                            game_id,
                            participant_id,
                            card_row[0] if card_row else None,
                            item["name"],
                            card_row[1] if card_row else None,
                        ),
                    )
            conn.execute(
                """
                UPDATE game_participant_stats
                SET cards_drawn = cards_drawn + ?
                WHERE game_id = ? AND participant_id = ?
                """,
                (len(put_events), game_id, participant_id),
            )

    @staticmethod
    def _migrate_v7_backfill_bottomed_hands_from_console(conn: sqlite3.Connection) -> None:
        """Reconstruct the final mulligan hand from historical console logs.

        The tracker has always printed "Mulliganed away: <cards>" at keep
        time, and those lines persist in console_logs. For games recorded
        before mulligan-hand history (or before bottomed-card capture), the
        final full hand is kept hand + thrown cards with the thrown cards
        flagged as bottomed — applied only when the counts reconcile exactly
        (thrown == mulligans and kept + thrown == 7), so ambiguous lines
        (e.g. comma-named cards in multi-mulligan keeps) are left alone.
        """
        games = conn.execute(
            """
            SELECT g.id, p.id, p.mulligans, g.session_id, g.started_at
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            WHERE COALESCE(p.mulligans, 0) > 0
            """
        ).fetchall()
        for game_id, participant_id, mulligans, session_id, started_at in games:
            mulligans = int(mulligans or 0)
            have_bottomed = conn.execute(
                """
                SELECT 1 FROM game_mulligan_hands
                WHERE game_id = ? AND participant_id = ? AND bottomed = 1
                LIMIT 1
                """,
                (game_id, participant_id),
            ).fetchone()
            if have_bottomed:
                continue
            kept = conn.execute(
                """
                SELECT display_name, type_category, card_id
                FROM game_opening_hand_cards
                WHERE game_id = ? AND participant_id = ?
                ORDER BY hand_position
                """,
                (game_id, participant_id),
            ).fetchall()
            if not kept:
                continue
            line = conn.execute(
                """
                SELECT text FROM console_logs
                WHERE session_id = ?
                  AND substr(match_started_at, 1, 19) = substr(?, 1, 19)
                  AND text LIKE '%Mulliganed away:%'
                ORDER BY id
                LIMIT 1
                """,
                (session_id, started_at),
            ).fetchone()
            if not line:
                continue
            remainder = str(line[0]).split("Mulliganed away:", 1)[1].strip()
            thrown = [name.strip() for name in remainder.split(",") if name.strip()]
            if len(thrown) != mulligans and mulligans == 1 and remainder:
                # A single bottomed card whose name contains a comma.
                thrown = [remainder]
            if len(thrown) != mulligans or len(kept) + len(thrown) != 7:
                continue
            existing_max = conn.execute(
                """
                SELECT COALESCE(MAX(hand_number), 0) FROM game_mulligan_hands
                WHERE game_id = ? AND participant_id = ?
                """,
                (game_id, participant_id),
            ).fetchone()[0]
            hand_number = max(mulligans + 1, int(existing_max) + 1)
            position = 0
            for display_name, type_category, card_id in kept:
                position += 1
                conn.execute(
                    """
                    INSERT OR IGNORE INTO game_mulligan_hands (
                        game_id, participant_id, hand_number, hand_position,
                        card_id, display_name, type_category, bottomed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (game_id, participant_id, hand_number, position,
                     card_id, display_name, type_category),
                )
            for name in thrown:
                position += 1
                card_row = conn.execute(
                    "SELECT id, primary_type FROM cards WHERE name = ? OR name LIKE ? LIMIT 1",
                    (name, f"{name} (%"),
                ).fetchone()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO game_mulligan_hands (
                        game_id, participant_id, hand_number, hand_position,
                        card_id, display_name, type_category, bottomed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (game_id, participant_id, hand_number, position,
                     card_row[0] if card_row else None, name,
                     card_row[1] if card_row else None),
                )

    @staticmethod
    def _migrate_v6_merge_split_card_summary_rows(conn: sqlite3.Connection) -> None:
        """Merge card-summary rows recorded under split-card half names.

        Arena resolves each door/half of a split or Room card as its own game
        object, so historical play events were summarized under half names
        ("Unholy Annex", "Ritual Chamber") while draws and decklists used the
        full name ("Unholy Annex // Ritual Chamber"). Rewrite half rows to the
        full name and merge counts where both variants exist in one game.
        """
        from .analytics_persistence import (
            analytics_card_base_name,
            canonical_split_display,
            split_card_half_map,
        )

        half_map = split_card_half_map(conn)
        if not half_map:
            return
        full_card_ids = {
            analytics_card_base_name(name): card_id
            for card_id, name in conn.execute(
                "SELECT id, name FROM cards WHERE name LIKE '% // %'"
            )
        }
        rows = conn.execute(
            """
            SELECT id, game_id, participant_id, display_name, type_category,
                   played_count, drawn_count, discarded_count, milled_count, exiled_count
            FROM game_card_summary
            """
        ).fetchall()
        for (
            row_id,
            game_id,
            participant_id,
            display_name,
            type_category,
            played,
            drawn,
            discarded,
            milled,
            exiled,
        ) in rows:
            canonical = canonical_split_display(str(display_name or ""), half_map)
            if canonical == display_name:
                continue
            base = analytics_card_base_name(canonical)
            target = conn.execute(
                """
                SELECT id, type_category FROM game_card_summary
                WHERE game_id = ? AND participant_id = ? AND id != ?
                  AND (display_name = ? OR display_name LIKE ?)
                """,
                (game_id, participant_id, row_id, base, f"{base} (%"),
            ).fetchone()
            if target is None:
                conn.execute(
                    """
                    UPDATE game_card_summary
                    SET display_name = ?, card_id = COALESCE(?, card_id)
                    WHERE id = ?
                    """,
                    (canonical, full_card_ids.get(base), row_id),
                )
                continue
            target_id, target_type = target
            conn.execute(
                """
                UPDATE game_card_summary
                SET played_count = played_count + ?,
                    drawn_count = drawn_count + ?,
                    discarded_count = discarded_count + ?,
                    milled_count = milled_count + ?,
                    exiled_count = exiled_count + ?,
                    card_id = COALESCE(?, card_id),
                    type_category = CASE
                        WHEN COALESCE(type_category, 'Other') = 'Other'
                             AND COALESCE(?, 'Other') != 'Other'
                        THEN ? ELSE type_category END
                WHERE id = ?
                """,
                (
                    played,
                    drawn,
                    discarded,
                    milled,
                    exiled,
                    full_card_ids.get(base),
                    type_category,
                    type_category,
                    target_id,
                ),
            )
            conn.execute("DELETE FROM game_card_summary WHERE id = ?", (row_id,))

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
        live: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist one rendered console line using the persistent connection."""
        conn = self.connect()
        if conn is None:
            return
        # One scoped transaction: commits on success, rolls back on error, so
        # a failed write can never leave the WAL write lock held while idle.
        with conn:
            self.upsert_session_row(conn, session, now=created_at)
            if live is not None:
                self._upsert_live_status(conn, live)
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

    #: Columns of live_status that _upsert_live_status accepts (id excluded).
    _LIVE_STATUS_COLUMNS = (
        "session_id",
        "updated_at",
        "in_game",
        "match_id",
        "game_id",
        "format",
        "match_type",
        "game_number",
        "player_name",
        "opponent_name",
        "deck_name",
        "turn_number",
        "active_role",
        "on_play",
        "player_life",
        "opponent_life",
        "mulligans",
        "game_started_at",
        "player_commanders",
        "opponent_commanders",
        "log_path",
        "card_db_path",
        "db_path",
        "tracker_version",
        "player_colors",
        "opponent_colors",
        "player_lands",
        "opponent_lands",
        "turn_started_at",
        "lands_seen",
        "cards_seen",
        "ramped_lands",
        "deck_size",
        "deck_lands",
        "opponent_cards",
        "last_game_json",
    )

    def _upsert_live_status(self, conn: sqlite3.Connection, live: Dict[str, Any]) -> None:
        """Replace the single live_status row (id=1) inside `conn`'s txn."""
        values = {column: live.get(column) for column in self._LIVE_STATUS_COLUMNS}
        columns = ", ".join(values)
        placeholders = ", ".join(f":{column}" for column in values)
        conn.execute(
            f"INSERT OR REPLACE INTO live_status (id, {columns}) VALUES (1, {placeholders})",
            values,
        )

    def patch_event_texts(
        self,
        *,
        session_id: str,
        game_id: str,
        needle: str,
        replacement: str,
    ) -> None:
        """Rewrite a placeholder (e.g. "[ID: 301]") inside already-recorded
        lines once the tracker learns what the object actually was — a target
        can be hidden (a graveyard card Arena only listed by id) at the
        moment its line logs, then reveal seconds later."""
        conn = self.connect()
        if conn is None:
            return
        like = f"%{needle}%"
        with conn:
            conn.execute(
                "UPDATE game_events SET text = REPLACE(text, ?, ?) "
                "WHERE game_id = ? AND text LIKE ?",
                (needle, replacement, game_id, like),
            )
            conn.execute(
                "UPDATE console_logs SET text = REPLACE(text, ?, ?) "
                "WHERE session_id = ? AND text LIKE ?",
                (needle, replacement, session_id, like),
            )

    def touch_live_status(self, session_id: str, now: datetime) -> None:
        """Idle heartbeat: bump updated_at so the dashboard can tell a quiet
        tracker from a stopped one. Creates the row if it doesn't exist."""
        conn = self.connect()
        if conn is None:
            return
        with conn:
            updated = conn.execute(
                "UPDATE live_status SET updated_at = ?, session_id = ? WHERE id = 1",
                (now.isoformat(), session_id),
            )
            if updated.rowcount == 0:
                self._upsert_live_status(
                    conn,
                    {"session_id": session_id, "updated_at": now.isoformat(), "in_game": 0},
                )

    def mark_live_status_stopped(self) -> None:
        """Stamp live_status stale (and out of game) the moment tracking stops,
        so the dashboard flips to "offline" immediately instead of waiting out
        the heartbeat-recency window."""
        conn = self.connect()
        if conn is None:
            return
        stale = datetime.now() - timedelta(seconds=120)
        with conn:
            conn.execute(
                "UPDATE live_status SET updated_at = ?, in_game = 0 WHERE id = 1",
                (stale.isoformat(),),
            )

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
        with conn:
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
                    compress_payload(scrub_raw_log(payload_json)),
                ),
            )

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
        # The whole check-and-insert runs in one scoped transaction. The
        # unchanged-rank early return previously left the session upsert
        # uncommitted, holding the WAL write lock for as long as the tracker
        # idled and blocking dashboard writes with "database is locked".
        with conn:
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
        return added
