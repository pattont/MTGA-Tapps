"""Live Log API: /api/live served straight from SQLite.

The tracker maintains a single-row live_status snapshot and appends every
rendered console line to console_logs (with style, turn, and life totals),
so the dashboard can drive the Live Log page purely from the database —
whether it runs inside the unified app or standalone.

GET /api/live?since=<console_logs.id> returns:

    {
      "tracker": {"state": "live"|"idle"|"offline", "updated_at": ...},
      "now": {...live_status fields...} | null,
      "session": {games, wins, losses, draws, win_rate, runtime_seconds,
                  started_at} | null,
      "games": [{id, started_at, deck_name, opponent_name, outcome,
                 total_turns, duration_seconds, game_number, format}],
      "events": [{id, at, turn, style, text, player_life, opponent_life}],
      "seq": <highest console_logs id sent>
    }

`since` makes events a delta; the first call (since omitted or 0) returns
the most recent lines. `state` is "offline" when live_status.updated_at is
stale (tracker not running), "live" during a game, "idle" otherwise.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: live_status.updated_at older than this means the tracker is not running
#: (its idle heartbeat writes every ~5 seconds).
OFFLINE_AFTER_SECONDS = 20.0

#: Lines returned on a fresh page load (no `since`).
INITIAL_EVENT_LINES = 150

#: Hard cap per response, delta requests included.
MAX_EVENT_LINES = 500


def _dict_row(cursor: sqlite3.Cursor) -> Optional[Dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


def _dict_rows(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _json_list(value: Any) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _live_status(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    try:
        cursor = conn.execute("SELECT * FROM live_status WHERE id = 1")
    except sqlite3.OperationalError:
        # Database predates the live_status table (dashboard-only install
        # that never ran a new tracker).
        return None
    return _dict_row(cursor)


def _tracker_state(status: Optional[Dict[str, Any]], now: datetime) -> str:
    if status is None:
        return "offline"
    updated_at = _parse_iso(status.get("updated_at"))
    if updated_at is None or now - updated_at > timedelta(seconds=OFFLINE_AFTER_SECONDS):
        return "offline"
    return "live" if status.get("in_game") else "idle"


def _session_payload(conn: sqlite3.Connection, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if session_id:
        cursor = conn.execute(
            """
            SELECT id, started_at, games_played, wins, losses, draws, runtime_seconds
            FROM tracker_sessions WHERE id = ?
            """,
            (session_id,),
        )
    else:
        cursor = conn.execute(
            """
            SELECT id, started_at, games_played, wins, losses, draws, runtime_seconds
            FROM tracker_sessions ORDER BY started_at DESC LIMIT 1
            """
        )
    row = _dict_row(cursor)
    if row is None:
        return None
    decided = (row["wins"] or 0) + (row["losses"] or 0)
    row["win_rate"] = round(100.0 * (row["wins"] or 0) / decided, 1) if decided else None
    return row


def _games_payload(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Today's finished games, newest first, ready to link to #/game/<id>."""
    today = datetime.now().strftime("%Y-%m-%d")
    return _dict_rows(
        conn.execute(
            """
            SELECT
              g.id,
              g.started_at,
              g.outcome,
              g.total_turns,
              g.duration_seconds,
              g.game_number,
              m.format,
              m.best_of,
              p.deck_name,
              o.display_name AS opponent_name
            FROM games g
            JOIN matches m ON m.id = g.match_id
            LEFT JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            LEFT JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
            WHERE date(g.started_at) = ?
            ORDER BY g.started_at DESC
            LIMIT 40
            """,
            (today,),
        )
    )


def _events_payload(
    conn: sqlite3.Connection,
    session_id: Optional[str],
    since: int,
) -> Tuple[List[Dict[str, Any]], int]:
    params: List[Any] = []
    where = "1=1"
    if session_id:
        where = "session_id = ?"
        params.append(session_id)
    if since > 0:
        rows = _dict_rows(
            conn.execute(
                f"""
                SELECT id, created_at, turn_number, style, text, player_life, opponent_life
                FROM console_logs
                WHERE {where} AND id > ?
                ORDER BY id ASC
                LIMIT {MAX_EVENT_LINES}
                """,
                (*params, since),
            )
        )
    else:
        rows = _dict_rows(
            conn.execute(
                f"""
                SELECT id, created_at, turn_number, style, text, player_life, opponent_life
                FROM console_logs
                WHERE {where}
                ORDER BY id DESC
                LIMIT {INITIAL_EVENT_LINES}
                """,
                params,
            )
        )
        rows.reverse()
    events = [
        {
            "id": row["id"],
            "at": row["created_at"],
            "turn": row["turn_number"],
            "style": row["style"],
            "text": row["text"],
            "player_life": row["player_life"],
            "opponent_life": row["opponent_life"],
        }
        for row in rows
    ]
    seq = events[-1]["id"] if events else since
    return events, seq


def build_live_payload(db_path: Path, since: int = 0) -> Dict[str, Any]:
    db_uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    now = datetime.now()
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        status = _live_status(conn)
        state = _tracker_state(status, now)
        session_id = status.get("session_id") if status else None

        now_payload: Optional[Dict[str, Any]] = None
        if status is not None:
            now_payload = {
                "in_game": bool(status.get("in_game")),
                "match_id": status.get("match_id"),
                "game_id": status.get("game_id"),
                "format": status.get("format"),
                "match_type": status.get("match_type"),
                "game_number": status.get("game_number"),
                "player_name": status.get("player_name"),
                "opponent_name": status.get("opponent_name"),
                "deck_name": status.get("deck_name"),
                "turn_number": status.get("turn_number"),
                "active_role": status.get("active_role"),
                "on_play": (None if status.get("on_play") is None else bool(status.get("on_play"))),
                "player_life": status.get("player_life"),
                "opponent_life": status.get("opponent_life"),
                "mulligans": status.get("mulligans"),
                "game_started_at": status.get("game_started_at"),
                "player_commanders": _json_list(status.get("player_commanders")),
                "opponent_commanders": _json_list(status.get("opponent_commanders")),
            }

        events, seq = _events_payload(conn, session_id, since)
        return {
            "tracker": {
                "state": state,
                "updated_at": status.get("updated_at") if status else None,
                "session_id": session_id,
            },
            "now": now_payload,
            "session": _session_payload(conn, session_id),
            "games": _games_payload(conn),
            "events": events,
            "seq": seq,
        }


def handle_get(
    path: str, query: Dict[str, List[str]], db_path: Path
) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path != "/api/live":
        return None
    try:
        since_raw = query.get("since", ["0"])[0]
        try:
            since = max(0, int(since_raw))
        except (TypeError, ValueError):
            since = 0
        return 200, build_live_payload(db_path, since)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
