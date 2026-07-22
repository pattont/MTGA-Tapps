"""SQLite analytics consistency audit and safe repair helpers."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from .analytics import AnalyticsStore
from .format_normalizer import trusted_queue_raw
from .paths import DATA_DIR


DEFAULT_DB_PATH = DATA_DIR / "mtga_tracker.sqlite3"


@dataclass(frozen=True)
class AuditFinding:
    """One database consistency finding."""

    code: str
    severity: str
    table_name: str
    row_id: str
    message: str
    current_value: Optional[str] = None
    suggested_value: Optional[str] = None
    repairable: bool = False


@dataclass(frozen=True)
class RepairResult:
    """Summary of repair execution."""

    findings: List[AuditFinding]
    repaired_count: int
    backup_path: Optional[Path] = None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    AnalyticsStore.ensure_schema(conn)
    return conn


def _format_queue_findings(conn: sqlite3.Connection) -> Iterable[AuditFinding]:
    for row in conn.execute(
        """
        SELECT id, format, queue, event_name
        FROM matches
        WHERE COALESCE(queue, '') <> ''
           OR COALESCE(event_name, '') <> ''
        """
    ):
        match_id, format_value, queue, event_name = row
        trusted = trusted_queue_raw(format_value, queue, event_name)
        if not trusted or trusted == format_value:
            continue
        yield AuditFinding(
            code="FORMAT_QUEUE_MISMATCH",
            severity="warning",
            table_name="matches",
            row_id=str(match_id),
            message=(
                f"Match format is {format_value!r}, but queue/event identify "
                f"the match as {trusted!r}."
            ),
            current_value=format_value,
            suggested_value=trusted,
            repairable=True,
        )


def _turn_count_findings(conn: sqlite3.Connection) -> Iterable[AuditFinding]:
    for row in conn.execute(
        """
        SELECT id, total_turns, player_turns, opponent_turns
        FROM games
        WHERE total_turns IS NOT NULL
          AND player_turns IS NOT NULL
          AND opponent_turns IS NOT NULL
          AND total_turns <> player_turns + opponent_turns
        """
    ):
        game_id, total_turns, player_turns, opponent_turns = row
        suggested = int(player_turns or 0) + int(opponent_turns or 0)
        yield AuditFinding(
            code="TURN_COUNT_MISMATCH",
            severity="warning",
            table_name="games",
            row_id=str(game_id),
            message=(f"total_turns={total_turns} but player_turns + opponent_turns = {suggested}."),
            current_value=str(total_turns),
            suggested_value=str(suggested),
            repairable=True,
        )


def _missing_deck_name_findings(conn: sqlite3.Connection) -> Iterable[AuditFinding]:
    for row in conn.execute(
        """
        SELECT id, game_id, deck_id
        FROM participants
        WHERE role = 'player'
          AND COALESCE(deck_id, '') <> ''
          AND COALESCE(deck_name, '') = ''
        """
    ):
        participant_id, game_id, deck_id = row
        yield AuditFinding(
            code="MISSING_DECK_NAME",
            severity="warning",
            table_name="participants",
            row_id=str(participant_id),
            message=f"Game {game_id} has deck_id={deck_id!r} but no deck_name.",
            current_value="",
            suggested_value=None,
            repairable=False,
        )


def _unknown_card_label_findings(conn: sqlite3.Connection) -> Iterable[AuditFinding]:
    for table_name, column_name in (
        ("game_card_summary", "display_name"),
        ("game_opening_hand_cards", "display_name"),
    ):
        for row in conn.execute(
            f"""
            SELECT id, {column_name}
            FROM {table_name}
            WHERE {column_name} LIKE 'Card #%'
            LIMIT 250
            """
        ):
            row_id, display_name = row
            yield AuditFinding(
                code="UNKNOWN_CARD_LABEL",
                severity="warning",
                table_name=table_name,
                row_id=str(row_id),
                message=f"{table_name}.{column_name} still has unresolved card label {display_name!r}.",
                current_value=display_name,
                suggested_value=None,
                repairable=False,
            )


def _game_event_assignment_findings(conn: sqlite3.Connection) -> Iterable[AuditFinding]:
    row = conn.execute(
        """
        WITH assignments AS (
            SELECT
                e.game_id AS current_game_id,
                (
                    SELECT g.id
                    FROM games g
                    WHERE g.session_id = e.session_id
                      AND g.started_at IS NOT NULL
                      AND g.ended_at IS NOT NULL
                      AND e.event_time >= g.started_at
                      AND e.event_time <= g.ended_at
                    ORDER BY g.started_at DESC
                    LIMIT 1
                ) AS expected_game_id
            FROM game_events e
        )
        SELECT COUNT(*)
        FROM assignments
        WHERE COALESCE(current_game_id, '') <> COALESCE(expected_game_id, '')
        """
    ).fetchone()
    mismatched = int(row[0] or 0) if row else 0
    if mismatched:
        yield AuditFinding(
            code="GAME_EVENT_ASSIGNMENT_MISMATCH",
            severity="error",
            table_name="game_events",
            row_id="bulk",
            message=(
                f"{mismatched} event rows are attached to a game that does not contain "
                "the event timestamp."
            ),
            current_value=str(mismatched),
            suggested_value="Assign by session and game time interval",
            repairable=True,
        )


def _empty_game_findings(conn: sqlite3.Connection) -> Iterable[AuditFinding]:
    for row in conn.execute(
        """
        SELECT g.id
        FROM games g
        WHERE COALESCE(g.outcome, 'unknown') = 'unknown'
          AND COALESCE(g.total_turns, 0) <= 1
          AND NOT EXISTS (SELECT 1 FROM game_events e WHERE e.game_id = g.id)
          AND NOT EXISTS (SELECT 1 FROM game_turns t WHERE t.game_id = g.id)
          AND NOT EXISTS (SELECT 1 FROM game_opening_hand_cards h WHERE h.game_id = g.id)
          AND NOT EXISTS (SELECT 1 FROM game_drawn_cards d WHERE d.game_id = g.id)
          AND NOT EXISTS (SELECT 1 FROM game_card_summary c WHERE c.game_id = g.id)
          AND NOT EXISTS (
              SELECT 1
              FROM game_participant_stats s
              WHERE s.game_id = g.id
                AND (
                    s.attack_steps <> 0
                    OR s.attacking_creatures <> 0
                    OR s.attackers_lost <> 0
                    OR s.blocking_creatures <> 0
                    OR s.blockers_lost <> 0
                    OR s.damage_dealt <> 0
                    OR s.damage_taken <> 0
                    OR s.life_lost <> 0
                    OR s.self_damage <> 0
                    OR s.life_gained <> 0
                    OR s.cards_played <> 0
                    OR s.cards_drawn <> 0
                    OR s.cards_discarded <> 0
                    OR s.cards_milled <> 0
                    OR s.cards_exiled <> 0
                )
          )
        """
    ):
        game_id = str(row[0])
        yield AuditFinding(
            code="EMPTY_GAME_RECORD",
            severity="error",
            table_name="games",
            row_id=game_id,
            message=(
                "Unknown-result game has no cards, draws, turns, events, or meaningful "
                "participant statistics."
            ),
            current_value="empty",
            suggested_value="delete",
            repairable=True,
        )


def audit_database(db_path: Path = DEFAULT_DB_PATH) -> List[AuditFinding]:
    """Return consistency findings for the analytics DB."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Analytics DB not found: {db_path}")
    with _connect(db_path) as conn:
        findings = []
        findings.extend(_format_queue_findings(conn))
        findings.extend(_turn_count_findings(conn))
        findings.extend(_missing_deck_name_findings(conn))
        findings.extend(_unknown_card_label_findings(conn))
        findings.extend(_game_event_assignment_findings(conn))
        findings.extend(_empty_game_findings(conn))
        return findings


def _repair_game_event_assignments(conn: sqlite3.Connection) -> int:
    conn.execute("DROP TABLE IF EXISTS temp.game_event_assignment_repairs")
    conn.execute(
        """
        CREATE TEMP TABLE game_event_assignment_repairs (
            event_id INTEGER PRIMARY KEY,
            game_id TEXT,
            match_id TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO game_event_assignment_repairs (event_id, game_id, match_id)
        SELECT
            e.id,
            (
                SELECT g.id
                FROM games g
                WHERE g.session_id = e.session_id
                  AND g.started_at IS NOT NULL
                  AND g.ended_at IS NOT NULL
                  AND e.event_time >= g.started_at
                  AND e.event_time <= g.ended_at
                ORDER BY g.started_at DESC
                LIMIT 1
            ),
            (
                SELECT g.match_id
                FROM games g
                WHERE g.session_id = e.session_id
                  AND g.started_at IS NOT NULL
                  AND g.ended_at IS NOT NULL
                  AND e.event_time >= g.started_at
                  AND e.event_time <= g.ended_at
                ORDER BY g.started_at DESC
                LIMIT 1
            )
        FROM game_events e
        """
    )
    repaired = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM game_events e
            JOIN game_event_assignment_repairs r ON r.event_id = e.id
            WHERE COALESCE(e.game_id, '') <> COALESCE(r.game_id, '')
            """
        ).fetchone()[0]
        or 0
    )
    conn.execute(
        """
        UPDATE game_events
        SET
            game_id = (
                SELECT r.game_id
                FROM game_event_assignment_repairs r
                WHERE r.event_id = game_events.id
            ),
            match_id = (
                SELECT r.match_id
                FROM game_event_assignment_repairs r
                WHERE r.event_id = game_events.id
            ),
            participant_id = CASE
                WHEN actor_role IN ('player', 'opponent') THEN (
                    SELECT r.game_id || ':participant:' || actor_role
                    FROM game_event_assignment_repairs r
                    WHERE r.event_id = game_events.id AND r.game_id IS NOT NULL
                )
                ELSE NULL
            END
        WHERE id IN (
            SELECT e.id
            FROM game_events e
            JOIN game_event_assignment_repairs r ON r.event_id = e.id
            WHERE COALESCE(e.game_id, '') <> COALESCE(r.game_id, '')
        )
        """
    )
    conn.execute("DROP TABLE game_event_assignment_repairs")
    return repaired


def _delete_empty_game(conn: sqlite3.Connection, game_id: str) -> int:
    context = conn.execute(
        "SELECT session_id, match_id FROM games WHERE id = ?", (game_id,)
    ).fetchone()
    if context is None:
        return 0
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
        "game_drawn_cards",
        "game_card_summary",
        "game_participant_stats",
        "game_turns",
        "game_events",
        "raw_game_payloads",
    ):
        conn.execute(f"DELETE FROM {table_name} WHERE game_id = ?", (game_id,))
    conn.execute("DELETE FROM participants WHERE game_id = ?", (game_id,))
    deleted = conn.execute("DELETE FROM games WHERE id = ?", (game_id,)).rowcount
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
        UPDATE tracker_sessions
        SET
            games_played = (SELECT COUNT(*) FROM games WHERE session_id = ?),
            wins = (SELECT COUNT(*) FROM games WHERE session_id = ? AND outcome = 'win'),
            losses = (SELECT COUNT(*) FROM games WHERE session_id = ? AND outcome = 'loss'),
            draws = (SELECT COUNT(*) FROM games WHERE session_id = ? AND outcome = 'draw'),
            unknown_results = (
                SELECT COUNT(*)
                FROM games
                WHERE session_id = ? AND COALESCE(outcome, 'unknown') NOT IN ('win', 'loss', 'draw')
            )
        WHERE id = ?
        """,
        (session_id, session_id, session_id, session_id, session_id, session_id),
    )
    return int(deleted or 0)


def repair_database(db_path: Path = DEFAULT_DB_PATH, *, backup: bool = False) -> RepairResult:
    """Repair safe DB inconsistencies and return findings seen before repair."""
    db_path = Path(db_path)
    findings = audit_database(db_path)
    repairable = [finding for finding in findings if finding.repairable]
    backup_path: Optional[Path] = None
    if repairable and backup:
        backup_path = db_path.with_name(
            f"{db_path.name}.backup.{datetime.now().strftime('%Y%m%d%H%M%S')}.audit-repair"
        )
        shutil.copy2(db_path, backup_path)

    with _connect(db_path) as conn:
        repaired_count = 0
        for finding in repairable:
            if finding.code == "FORMAT_QUEUE_MISMATCH" and finding.suggested_value is not None:
                conn.execute(
                    "UPDATE matches SET format = ? WHERE id = ?",
                    (finding.suggested_value, finding.row_id),
                )
                repaired_count += 1
            elif finding.code == "TURN_COUNT_MISMATCH" and finding.suggested_value is not None:
                conn.execute(
                    "UPDATE games SET total_turns = ? WHERE id = ?",
                    (int(finding.suggested_value), finding.row_id),
                )
                repaired_count += 1
            elif finding.code == "GAME_EVENT_ASSIGNMENT_MISMATCH":
                repaired_count += _repair_game_event_assignments(conn)
            elif finding.code == "EMPTY_GAME_RECORD":
                repaired_count += _delete_empty_game(conn, finding.row_id)
        conn.commit()
    return RepairResult(findings=findings, repaired_count=repaired_count, backup_path=backup_path)


def _print_findings(findings: List[AuditFinding]) -> None:
    if not findings:
        print("No DB consistency findings.")
        return
    for finding in findings:
        repair_text = "repairable" if finding.repairable else "manual"
        print(
            f"{finding.severity.upper()} {finding.code} [{repair_text}] "
            f"{finding.table_name}:{finding.row_id} - {finding.message}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit MTGA tracker SQLite analytics DB.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path.")
    parser.add_argument("--repair", action="store_true", help="Apply safe repairs.")
    args = parser.parse_args()

    if args.repair:
        result = repair_database(args.db, backup=True)
        _print_findings(result.findings)
        if result.backup_path:
            print(f"Backup: {result.backup_path}")
        print(f"Repaired: {result.repaired_count}")
    else:
        _print_findings(audit_database(args.db))


if __name__ == "__main__":
    main()
