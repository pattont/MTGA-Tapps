"""Analytics-related CardTracker mixin methods."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analytics import AnalyticsStore, SessionSnapshot
from .analytics_persistence import (
    persist_card_summary,
    persist_commanders,
    persist_drawn_cards,
    persist_opening_hand,
)
from .format_normalizer import is_momir_format, normalize_match_format
from .state import CardEvent


class TrackerAnalyticsMixin:
    """SQLite analytics and dashboard persistence helpers used by CardTracker."""

    def _is_bot_match(self) -> bool:
        """Return True for MTGA bot matches that should stay out of analytics."""
        opponent_name = str(self.game_state.opponent_display_name or "").strip().lower()
        if opponent_name == "sparky":
            return True
        format_text = str(self.game_state.format_str or "").strip().lower()
        return format_text.startswith("aibotmatch")

    def _is_untracked_match(self) -> bool:
        """Return True for matches intentionally excluded from saved analytics."""
        return self._is_bot_match() or is_momir_format(self.game_state.format_str)

    def _session_snapshot(self) -> SessionSnapshot:
        """Return the current session counters for analytics persistence."""
        return SessionSnapshot(
            session_id=self.session_id,
            started_at=self.session_start_time,
            games_played=self.session_games_played,
            wins=self.session_wins,
            losses=self.session_losses,
            draws=getattr(self, "session_draws", 0),
            unknown_results=self.session_unknown,
            runtime_seconds=self._session_play_runtime_seconds(),
        )

    def _analytics_store(self) -> AnalyticsStore:
        """Return an AnalyticsStore aligned with the current DB path."""
        path = getattr(self, "_console_db_path", None)
        store = getattr(self, "analytics", None)
        store_path = getattr(store, "path", None)
        desired_path = Path(path) if path is not None else None
        if store is None or store_path != desired_path:
            if store is not None:
                store.close()
            store = AnalyticsStore(desired_path)
            self.analytics = store
        return store

    def _record_console_log(self, text: str, style: Optional[str] = None) -> None:
        """Best-effort persistent storage for terminal output."""
        if self._is_untracked_match():
            return
        try:
            now = self._now()
            elapsed_seconds = None
            if self.game_state.game_start_time is not None:
                elapsed_seconds = max(
                    0, int((now - self.game_state.game_start_time).total_seconds())
                )
            self._analytics_store().record_console_log(
                self._session_snapshot(),
                created_at=now,
                match_started_at=self.game_state.game_start_time,
                elapsed_seconds=elapsed_seconds,
                turn_number=self.game_state.turn_number or None,
                active_player=self.game_state.active_player,
                style=style,
                text=text,
                player_life=self.game_state.player_life,
                opponent_life=self.game_state.opponent_life,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return

    def _record_raw_payload_snapshot(self, payload_type: str, payload_text: str) -> None:
        """Best-effort sanitized raw payload persistence for diagnostics/replay."""
        if self._is_untracked_match() or is_momir_format(payload_text):
            return
        try:
            game_id = self._current_game_id() if self.game_state.game_start_time else None
            match_id = self._current_match_id() if self.game_state.game_start_time else None
            self._analytics_store().record_raw_payload(
                session_id=self.session_id,
                created_at=self._now(),
                payload_type=payload_type,
                payload_json=str(payload_text or ""),
                match_id=match_id,
                game_id=game_id,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return

    def _analytics_connect(self) -> Optional[sqlite3.Connection]:
        """Return initialized analytics DB connection, or None when disabled/unavailable."""
        try:
            conn = self._analytics_store().connect()
            if conn is None:
                return None
            self._upsert_session_row(conn)
            return conn
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None

    def _ensure_analytics_schema(self, conn: sqlite3.Connection) -> None:
        """Create dashboard-friendly analytics tables if needed."""
        AnalyticsStore.ensure_schema(conn)

    @staticmethod
    def _ensure_table_column(
        conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str
    ) -> None:
        """Add a nullable column when an older analytics DB lacks it."""
        AnalyticsStore.ensure_table_column(conn, table_name, column_name, column_type)

    def _upsert_session_row(self, conn: sqlite3.Connection) -> None:
        """Persist current session counters."""
        runtime_seconds = self._session_play_runtime_seconds()
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
                self.session_id,
                self.session_start_time.isoformat(),
                datetime.now().isoformat(),
                None,
                self.session_games_played,
                self.session_wins,
                self.session_losses,
                getattr(self, "session_draws", 0),
                self.session_unknown,
                runtime_seconds,
            ),
        )

    def _current_game_ordinal(self) -> int:
        """Return stable 1-based game ordinal for DB ids."""
        return max(1, int(self.session_games_played or 1))

    def _current_match_ordinal(self) -> int:
        """Return stable 1-based match ordinal for DB ids."""
        game_ordinal = self._current_game_ordinal()
        if self.game_state.match_type == "best_of_3":
            return max(1, game_ordinal - int(self.game_state.game_number or 1) + 1)
        return game_ordinal

    def _current_match_id(self) -> str:
        """Return deterministic match id scoped to this tracker session."""
        return f"{self.session_id}:match:{self._current_match_ordinal()}"

    def _current_game_id(self) -> str:
        """Return deterministic game id scoped to this tracker session."""
        game_number = int(self.game_state.game_number or self._current_game_ordinal())
        return f"{self._current_match_id()}:game:{game_number}"

    def _participant_id_for_role(self, game_id: str, role: str) -> str:
        """Return deterministic participant id for player/opponent roles."""
        return f"{game_id}:participant:{role}"

    def _participant_id_for_seat(self, game_id: str, seat_id: Optional[int]) -> Optional[str]:
        """Map a seat id to a deterministic participant id."""
        if seat_id == self.game_state.player_seat_id:
            return self._participant_id_for_role(game_id, "player")
        if seat_id == self.game_state.opponent_seat_id:
            return self._participant_id_for_role(game_id, "opponent")
        return None

    def _participant_snapshot(
        self, game_id: str, role: str, seat_id: Optional[int]
    ) -> Dict[str, Any]:
        """Return current participant metadata for summary persistence."""
        is_player = role == "player"
        observed_deck_size = None
        if seat_id in self.game_state.observed_starting_deck_total_by_seat:
            observed_deck_size = self.game_state.observed_starting_deck_total_by_seat[seat_id]
        metadata_deck_size = self.game_state.player_deck_total_cards if is_player else None
        deck_size = metadata_deck_size or observed_deck_size
        deck_size_source = (
            "metadata" if metadata_deck_size else ("observed" if observed_deck_size else None)
        )
        return {
            "id": self._participant_id_for_role(game_id, role),
            "game_id": game_id,
            "seat_id": seat_id,
            "role": role,
            "display_name": (
                self.game_state.player_display_name
                if is_player
                else self.game_state.opponent_display_name
            )
            or ("You" if is_player else "Opponent"),
            "deck_name": self.game_state.player_deck_name if is_player else None,
            "deck_id": self.game_state.player_deck_id if is_player else None,
            "deck_archetype": None,
            "deck_size": deck_size,
            "deck_size_source": deck_size_source,
            "opening_hand_size": (
                len(self.game_state.starting_hand)
                if is_player and self.game_state.starting_hand
                else None
            ),
            "mulligans": self.game_state.mulligan_count if is_player else None,
            "starting_life": self._starting_life_total_for_current_format(),
            "ending_life": (
                self.game_state.player_life if is_player else self.game_state.opponent_life
            ),
            "went_first": (
                1 if seat_id is not None and self.game_state.first_player_seat == seat_id else 0
            ),
        }

    def _infer_event_actor(self, text: str) -> tuple:
        """Infer actor role/seat from formatted terminal text."""
        body = str(text or "")
        if "] " in body:
            body = body.split("] ", 1)[1]
        body = body.lstrip()
        if body.startswith("\t"):
            body = body.lstrip("\t ")
        if body.startswith("You:") or body.startswith("Combat:") and "(your" in body:
            return "player", self.game_state.player_seat_id
        if body.startswith("Opponent:") or body.startswith("Combat:") and "(opponent" in body:
            return "opponent", self.game_state.opponent_seat_id
        return None, None

    def _record_game_event(self, text: str, style: Optional[str] = None) -> None:
        """Best-effort structured event row for turn-log lines."""
        if not self.game_state.game_start_time:
            return
        if self._is_untracked_match():
            return
        conn = self._analytics_connect()
        if conn is None:
            return
        try:
            match_id = self._current_match_id()
            game_id = self._current_game_id()
            actor_role, seat_id = self._infer_event_actor(text)
            participant_id = self._participant_id_for_seat(game_id, seat_id)
            now = self._now()
            elapsed_seconds = max(0, int((now - self.game_state.game_start_time).total_seconds()))
            with conn:
                conn.execute(
                    """
                    INSERT INTO game_events (
                        session_id,
                        match_id,
                        game_id,
                        event_time,
                        elapsed_seconds,
                        turn_number,
                        phase,
                        step,
                        participant_id,
                        seat_id,
                        actor_role,
                        event_type,
                        text,
                        player_life,
                        opponent_life
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.session_id,
                        match_id,
                        game_id,
                        now.isoformat(),
                        elapsed_seconds,
                        self.game_state.turn_number or None,
                        self.game_state.phase or None,
                        self.game_state.step or None,
                        participant_id,
                        seat_id,
                        actor_role,
                        style,
                        str(text or ""),
                        self.game_state.player_life,
                        self.game_state.opponent_life,
                    ),
                )
        except sqlite3.Error:
            return

    def _persist_participant_stats(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        participant_id: str,
        seat_id: Optional[int],
        cards_played: int,
    ) -> None:
        """Persist per-game stats for one participant."""
        stats = self.game_state.match_stats.get(int(seat_id), {}) if seat_id in (1, 2) else {}
        damage_dealt = int(stats.get("total_damage", 0))
        life_lost = int(stats.get("life_lost", 0))
        conn.execute(
            """
            INSERT INTO game_participant_stats (
                game_id,
                participant_id,
                attack_steps,
                attacking_creatures,
                attackers_lost,
                blocking_creatures,
                blockers_lost,
                damage_dealt,
                damage_taken,
                life_lost,
                self_damage,
                life_gained,
                cards_played,
                cards_drawn,
                cards_discarded,
                cards_milled,
                cards_exiled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, participant_id) DO UPDATE SET
                attack_steps = excluded.attack_steps,
                attacking_creatures = excluded.attacking_creatures,
                attackers_lost = excluded.attackers_lost,
                blocking_creatures = excluded.blocking_creatures,
                blockers_lost = excluded.blockers_lost,
                damage_dealt = excluded.damage_dealt,
                damage_taken = excluded.damage_taken,
                life_lost = excluded.life_lost,
                self_damage = excluded.self_damage,
                life_gained = excluded.life_gained,
                cards_played = excluded.cards_played,
                cards_drawn = excluded.cards_drawn,
                cards_discarded = excluded.cards_discarded,
                cards_milled = excluded.cards_milled,
                cards_exiled = excluded.cards_exiled
            """,
            (
                game_id,
                participant_id,
                int(stats.get("attacks", 0)),
                int(stats.get("attacking_creatures", 0)),
                int(stats.get("attackers_lost", 0)),
                int(stats.get("blocking_creatures", 0)),
                int(stats.get("blockers_lost", 0)),
                damage_dealt,
                life_lost,
                life_lost,
                int(stats.get("self_damage", 0)),
                int(stats.get("life_gain", 0)),
                cards_played,
                int(stats.get("cards_drawn", 0)),
                int(stats.get("cards_discarded", 0)),
                int(stats.get("cards_milled", 0)),
                int(stats.get("cards_exiled", 0)),
            ),
        )

    def _refresh_session_participant_stats(self, conn: sqlite3.Connection) -> None:
        """Recompute session role aggregates from persisted game rows."""
        conn.execute(
            """
            INSERT INTO session_participant_stats (
                session_id,
                role,
                games,
                wins,
                losses,
                cards_played,
                cards_drawn,
                cards_discarded,
                cards_milled,
                damage_dealt,
                damage_taken
            )
            SELECT
                g.session_id,
                p.role,
                COUNT(*),
                SUM(CASE
                    WHEN (p.role = 'player' AND g.outcome = 'win')
                      OR (p.role = 'opponent' AND g.outcome = 'loss')
                    THEN 1 ELSE 0
                END),
                SUM(CASE
                    WHEN (p.role = 'player' AND g.outcome = 'loss')
                      OR (p.role = 'opponent' AND g.outcome = 'win')
                    THEN 1 ELSE 0
                END),
                SUM(s.cards_played),
                SUM(s.cards_drawn),
                SUM(s.cards_discarded),
                SUM(s.cards_milled),
                SUM(s.damage_dealt),
                SUM(s.damage_taken)
            FROM game_participant_stats s
            JOIN participants p ON p.id = s.participant_id
            JOIN games g ON g.id = s.game_id
            WHERE g.session_id = ?
            GROUP BY g.session_id, p.role
            ON CONFLICT(session_id, role) DO UPDATE SET
                games = excluded.games,
                wins = excluded.wins,
                losses = excluded.losses,
                cards_played = excluded.cards_played,
                cards_drawn = excluded.cards_drawn,
                cards_discarded = excluded.cards_discarded,
                cards_milled = excluded.cards_milled,
                damage_dealt = excluded.damage_dealt,
                damage_taken = excluded.damage_taken
            """,
            (self.session_id,),
        )

    def _upsert_match_analytics(
        self,
        conn: sqlite3.Connection,
        match_id: str,
        started_at: Optional[str],
        ended_at: str,
        winner_participant_id: Optional[str],
    ) -> None:
        """Persist the current match row."""
        normalized_format = normalize_match_format(
            self.game_state.format_str,
            default_best_of=3 if self.game_state.match_type == "best_of_3" else 1,
        )
        conn.execute(
            """
            INSERT INTO matches (
                id,
                session_id,
                started_at,
                ended_at,
                match_type,
                format,
                queue,
                event_name,
                best_of,
                games_played,
                winner_participant_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ended_at = excluded.ended_at,
                match_type = excluded.match_type,
                format = excluded.format,
                queue = excluded.queue,
                event_name = excluded.event_name,
                best_of = excluded.best_of,
                games_played = excluded.games_played,
                winner_participant_id = excluded.winner_participant_id
            """,
            (
                match_id,
                self.session_id,
                started_at,
                ended_at,
                self.game_state.match_type,
                self.game_state.format_str,
                self.game_state.player_deck_event_name,
                self.game_state.player_deck_event_name,
                normalized_format.best_of,
                int(self.game_state.game_number or 1),
                winner_participant_id,
            ),
        )

    def _upsert_game_analytics(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        match_id: str,
        started_at: Optional[str],
        ended_at: str,
        duration_seconds: Optional[int],
        outcome: str,
        reason: str,
        winner_participant_id: Optional[str],
    ) -> None:
        """Persist the current game row."""
        player_turns, opponent_turns = self._participant_turn_counts()
        conn.execute(
            """
            INSERT INTO games (
                id,
                session_id,
                match_id,
                game_number,
                started_at,
                ended_at,
                duration_seconds,
                total_turns,
                player_turns,
                opponent_turns,
                outcome,
                outcome_reason,
                winner_participant_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ended_at = excluded.ended_at,
                duration_seconds = excluded.duration_seconds,
                total_turns = excluded.total_turns,
                player_turns = excluded.player_turns,
                opponent_turns = excluded.opponent_turns,
                outcome = excluded.outcome,
                outcome_reason = excluded.outcome_reason,
                winner_participant_id = excluded.winner_participant_id
            """,
            (
                game_id,
                self.session_id,
                match_id,
                int(self.game_state.game_number or 1),
                started_at,
                ended_at,
                duration_seconds,
                self._turns_completed(),
                player_turns,
                opponent_turns,
                outcome,
                reason,
                winner_participant_id,
            ),
        )

    def _upsert_participant_analytics(
        self, conn: sqlite3.Connection, participants: List[Dict[str, Any]]
    ) -> None:
        """Persist player/opponent participant rows."""
        for participant in participants:
            conn.execute(
                """
                INSERT INTO participants (
                    id,
                    game_id,
                    seat_id,
                    role,
                    display_name,
                    deck_name,
                    deck_id,
                    deck_archetype,
                    deck_size,
                    deck_size_source,
                    opening_hand_size,
                    mulligans,
                    starting_life,
                    ending_life,
                    went_first
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    seat_id = excluded.seat_id,
                    display_name = excluded.display_name,
                    deck_name = excluded.deck_name,
                    deck_id = excluded.deck_id,
                    deck_archetype = excluded.deck_archetype,
                    deck_size = excluded.deck_size,
                    deck_size_source = excluded.deck_size_source,
                    opening_hand_size = excluded.opening_hand_size,
                    mulligans = excluded.mulligans,
                    starting_life = excluded.starting_life,
                    ending_life = excluded.ending_life,
                    went_first = excluded.went_first
                """,
                (
                    participant["id"],
                    participant["game_id"],
                    participant["seat_id"],
                    participant["role"],
                    participant["display_name"],
                    participant["deck_name"],
                    participant["deck_id"],
                    participant["deck_archetype"],
                    participant["deck_size"],
                    participant["deck_size_source"],
                    participant["opening_hand_size"],
                    participant["mulligans"],
                    participant["starting_life"],
                    participant["ending_life"],
                    participant["went_first"],
                ),
            )

    def _persist_game_detail_analytics(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        player_participant_id: str,
        opponent_participant_id: str,
    ) -> None:
        """Persist per-participant stats, cards, opening hand, commanders, and session aggregates."""
        self._persist_participant_stats(
            conn,
            game_id,
            player_participant_id,
            self.game_state.player_seat_id,
            len(self.player_cards),
        )
        self._persist_participant_stats(
            conn,
            game_id,
            opponent_participant_id,
            self.game_state.opponent_seat_id,
            len(self.opponent_cards),
        )
        persist_card_summary(
            conn,
            game_id,
            player_participant_id,
            self.player_cards,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_card_summary(
            conn,
            game_id,
            opponent_participant_id,
            self.opponent_cards,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_opening_hand(
            conn,
            game_id,
            player_participant_id,
            starting_hand_events=self.game_state.starting_hand_events,
            starting_hand=self.game_state.starting_hand,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        drawn_cards_by_seat = getattr(self.game_state, "drawn_card_events", {}) or {}
        persist_drawn_cards(
            conn,
            game_id,
            player_participant_id,
            drawn_cards_by_seat.get(self.game_state.player_seat_id, []),
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_drawn_cards(
            conn,
            game_id,
            opponent_participant_id,
            drawn_cards_by_seat.get(self.game_state.opponent_seat_id, []),
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_commanders(
            conn,
            player_participant_id,
            self.game_state.player_commanders,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        persist_commanders(
            conn,
            opponent_participant_id,
            self.game_state.opponent_commanders,
            refresh_display_name=self._refresh_fallback_name_text,
        )
        self._refresh_session_participant_stats(conn)

    def _persist_game_analytics(self, outcome: str, reason: str) -> None:
        """Persist dashboard-ready summary data for a completed game."""
        if self._is_untracked_match():
            return
        conn = self._analytics_connect()
        if conn is None:
            return
        try:
            match_id = self._current_match_id()
            game_id = self._current_game_id()
            player_participant_id = self._participant_id_for_role(game_id, "player")
            opponent_participant_id = self._participant_id_for_role(game_id, "opponent")
            winner_participant_id = None
            if outcome == "win":
                winner_participant_id = player_participant_id
            elif outcome == "loss":
                winner_participant_id = opponent_participant_id
            started_at = (
                self.game_state.game_start_time.isoformat()
                if self.game_state.game_start_time
                else None
            )
            ended_at = (self.game_state.game_end_time or datetime.now()).isoformat()
            duration_seconds = None
            if self.game_state.game_start_time:
                duration_seconds = max(
                    0,
                    int(
                        (
                            (self.game_state.game_end_time or datetime.now())
                            - self.game_state.game_start_time
                        ).total_seconds()
                    ),
                )
            player = self._participant_snapshot(game_id, "player", self.game_state.player_seat_id)
            opponent = self._participant_snapshot(
                game_id, "opponent", self.game_state.opponent_seat_id
            )

            with conn:
                self._upsert_session_row(conn)
                self._upsert_match_analytics(
                    conn, match_id, started_at, ended_at, winner_participant_id
                )
                self._upsert_game_analytics(
                    conn,
                    game_id,
                    match_id,
                    started_at,
                    ended_at,
                    duration_seconds,
                    outcome,
                    reason,
                    winner_participant_id,
                )
                self._upsert_participant_analytics(conn, [player, opponent])
                self._persist_game_detail_analytics(
                    conn,
                    game_id,
                    player_participant_id,
                    opponent_participant_id,
                )
        except sqlite3.Error:
            return
