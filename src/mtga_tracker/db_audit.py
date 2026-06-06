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
        return findings


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
