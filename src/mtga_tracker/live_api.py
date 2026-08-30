"""Live Log API: /api/live served straight from SQLite.

The tracker maintains a single-row live_status snapshot and appends every
in-game turn-log line to game_events — the same table the /game page's
Timeline renders — so the dashboard can drive the Live Log page purely
from the database, and the live feed reads exactly like the game page.

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

#: Hard cap per response, delta requests included. A fresh page load pulls
#: the current game's timeline from its start.
MAX_EVENT_LINES = 800

#: Delta polls re-serve this many already-sent rows so in-place corrections
#: (an "[ID: N]" target resolving to its card once the object reveals) reach
#: the live page; the client merges rows by id.
REFRESH_TAIL_ROWS = 15


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


def _seat_colors(conn: sqlite3.Connection, game_id: Optional[str]) -> Dict[str, str]:
    """WUBRG colors revealed so far this game, per role, from the color
    identity of cards each side has played (fills in live as cards hit the
    board)."""
    out = {"player": "", "opponent": ""}
    if not game_id:
        return out
    try:
        rows = conn.execute(
            """
            SELECT p.role, c.color_identity
            FROM game_card_summary s
            JOIN participants p ON p.id = s.participant_id
            LEFT JOIN cards c ON c.id = s.card_id
            WHERE p.game_id = ? AND s.played_count > 0
            """,
            (game_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    seen: Dict[str, set] = {"player": set(), "opponent": set()}
    known: Dict[str, bool] = {"player": False, "opponent": False}
    for role, identity in rows:
        if role not in seen:
            continue
        if identity is not None:
            # '' is a KNOWN colorless card (Eldrazi, artifacts) — only NULL
            # means the card's identity is unknown.
            known[role] = True
        for letter in str(identity or ""):
            if letter in "WUBRG":
                seen[role].add(letter)
    for role, letters in seen.items():
        colored = "".join(letter for letter in "WUBRG" if letter in letters)
        out[role] = colored or ("C" if known[role] else "")
    return out


def _head_to_head(
    conn: sqlite3.Connection,
    opponent_name: Optional[str],
    current_game_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Lifetime record vs this opponent name (the current game excluded)."""
    name = str(opponent_name or "").strip()
    if not name:
        return None
    try:
        row = conn.execute(
            """
            SELECT
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses
            FROM games g
            JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
            WHERE o.display_name = ? AND g.id IS NOT ? AND g.outcome IN ('win', 'loss')
            """,
            (name, current_game_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    wins, losses = int(row[0] or 0), int(row[1] or 0)
    if wins + losses == 0:
        return None
    return {"wins": wins, "losses": losses}


def _deck_record(
    conn: sqlite3.Connection,
    deck_name: Optional[str],
    current_game_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Lifetime + today's record with this deck (the current game excluded)."""
    name = str(deck_name or "").strip()
    if not name:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        row = conn.execute(
            """
            SELECT
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              SUM(g.outcome = 'win' AND date(g.started_at) = ?) AS today_wins,
              SUM(g.outcome = 'loss' AND date(g.started_at) = ?) AS today_losses
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            WHERE p.deck_name = ? AND g.id IS NOT ? AND g.outcome IN ('win', 'loss')
            """,
            (today, today, name, current_game_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    wins, losses = int(row[0] or 0), int(row[1] or 0)
    if wins + losses == 0:
        return None
    return {
        "wins": wins,
        "losses": losses,
        "win_rate": round(100.0 * wins / (wins + losses), 1),
        "today_wins": int(row[2] or 0),
        "today_losses": int(row[3] or 0),
    }


def _rank_context(
    conn: sqlite3.Connection, format_label: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Latest rank snapshot for the game's ladder — shown for ranked games.

    Limited queues read from the limited ladder; everything else ranked reads
    from constructed. Non-ranked formats return None.
    """
    label = str(format_label or "").casefold()
    # "Unranked" contains "rank" — require the ranked marker without it.
    if "rank" not in label or "unranked" in label:
        return None
    is_limited = any(word in label for word in ("draft", "sealed", "limited"))
    rank_format = "limited" if is_limited else "constructed"
    try:
        cursor = conn.execute(
            """
            SELECT rank_class, rank_level, rank_step, rank_steps,
                   mythic_percentile, mythic_rank
            FROM rank_snapshots
            WHERE rank_format = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            (rank_format,),
        )
    except sqlite3.OperationalError:
        return None
    row = _dict_row(cursor)
    if row is None:
        return None
    row["rank_format"] = rank_format
    return row


#: An archetype guess needs at least this many of the opponent's revealed
#: cards matching the historical archetype's played cards.
ARCHETYPE_GUESS_MIN_MATCHES = 2


def _archetype_guess(
    conn: sqlite3.Connection,
    opponent_cards_json: Any,
    current_game_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Guess the opponent's archetype from their revealed cards, using past
    games whose opponents were identified (Deck AI) — no network, no model:
    the archetype whose historical played-cards overlap this game's revealed
    cards the most wins, with your record against it attached.
    """
    revealed = set(_json_list(opponent_cards_json))
    if len(revealed) < ARCHETYPE_GUESS_MIN_MATCHES:
        return None
    try:
        rows = conn.execute(
            """
            SELECT o.deck_archetype, s.display_name
            FROM participants o
            JOIN game_card_summary s ON s.participant_id = o.id
            WHERE o.role = 'opponent' AND o.deck_archetype IS NOT NULL
              AND o.game_id IS NOT ? AND s.played_count > 0
            """,
            (current_game_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    # Base card names, so "(Land)" suffixes and split faces still match.
    def base(name: str) -> str:
        return str(name or "").split(" (")[0].split(" // ")[0].strip().casefold()

    revealed_bases = {base(name) for name in revealed}
    matches: Dict[str, set] = {}
    for archetype, card_name in rows:
        if base(card_name) in revealed_bases:
            matches.setdefault(str(archetype), set()).add(base(card_name))
    if not matches:
        return None
    archetype, matched = max(matches.items(), key=lambda item: len(item[1]))
    if len(matched) < ARCHETYPE_GUESS_MIN_MATCHES:
        return None
    try:
        record = conn.execute(
            """
            SELECT SUM(g.outcome = 'win'), SUM(g.outcome = 'loss')
            FROM games g
            JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
            WHERE o.deck_archetype = ? AND g.id IS NOT ?
              AND g.outcome IN ('win', 'loss')
            """,
            (archetype, current_game_id),
        ).fetchone()
    except sqlite3.OperationalError:
        record = None
    return {
        "archetype": archetype,
        "matched_cards": len(matched),
        "wins": int(record[0] or 0) if record else 0,
        "losses": int(record[1] or 0) if record else 0,
    }


def _latest_event_game_id(
    conn: sqlite3.Connection, session_id: Optional[str]
) -> Optional[str]:
    """game_id of the newest game_events row in the CURRENT tracker session —
    the game whose feed the page should keep showing between games. The
    tracker clears live_status.game_id the moment a match completes, and
    Arena flushes the endgame log lines in the same burst, so without this
    fallback the final turns of a game would never be served (the client
    polls twice a second and misses the window).

    Scoped to the current session on purpose: a fresh tracker session (a
    restart, the next day) starts with a clean feed instead of resurrecting
    a previous session's last game — this also keeps the feed consistent
    with the empty Today's Games rail after a date rollover, while a session
    that plays across midnight keeps its previous game visible."""
    if not session_id:
        return None
    try:
        row = conn.execute(
            "SELECT game_id FROM game_events WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return str(row[0]) if row and row[0] else None


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
              g.outcome_reason,
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
    game_id: Optional[str],
    since: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """Timeline rows for the CURRENT game, straight from game_events — the
    exact same source the /game page's Timeline renders, so the live feed
    and the game page read identically. Between games there is nothing to
    stream (finished games live in the rail); match summaries never hit
    game_events, so they never reach the feed."""
    if not game_id:
        return [], since
    columns = """
              id,
              event_time,
              turn_number,
              phase,
              step,
              event_type,
              actor_role,
              text,
              player_life,
              opponent_life
    """
    if since > 0:
        # Delta poll: new rows plus a short tail of already-sent rows, so a
        # line patched in place after the fact still reaches the page.
        query = f"""
            SELECT {columns}
            FROM game_events
            WHERE game_id = ? AND (id > ? OR id IN (
                SELECT id FROM game_events WHERE game_id = ?
                ORDER BY id DESC LIMIT {REFRESH_TAIL_ROWS}
            ))
            ORDER BY id ASC
            LIMIT {MAX_EVENT_LINES}
            """
        params: Tuple[Any, ...] = (game_id, since, game_id)
    else:
        query = f"""
            SELECT {columns}
            FROM game_events
            WHERE game_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT {MAX_EVENT_LINES}
            """
        params = (game_id, since)
    rows = _dict_rows(conn.execute(query, params))
    if not rows:
        return [], since

    # Same card-link segmentation as the game page's timeline.
    from .dashboard import _clean_card_name, _timeline_text_segments

    linkable_cards: Dict[str, Optional[str]] = {}
    for display_name, type_category in conn.execute(
        "SELECT DISTINCT display_name, type_category FROM game_card_summary"
    ):
        clean_name = _clean_card_name(display_name)
        if clean_name and (clean_name not in linkable_cards or not linkable_cards[clean_name]):
            linkable_cards[clean_name] = type_category

    events = []
    for row in rows:
        events.append(
            {
                "id": row["id"],
                "at": row["event_time"],
                "turn_number": row["turn_number"],
                "phase": row["phase"],
                "step": row["step"],
                "event_type": row["event_type"],
                "actor_role": row["actor_role"],
                "text": row["text"],
                "text_segments": _timeline_text_segments(str(row["text"] or ""), linkable_cards),
                "player_life": row["player_life"],
                "opponent_life": row["opponent_life"],
            }
        )
    return events, events[-1]["id"]


def build_live_payload(db_path: Path, since: int = 0) -> Dict[str, Any]:
    db_uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    now = datetime.now()
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        status = _live_status(conn)
        state = _tracker_state(status, now)
        session_id = status.get("session_id") if status else None

        # Between games the tracker nulls every game-scoped live_status field,
        # but freezes the final in-game snapshot as JSON. Serving that frozen
        # snapshot back lets a fresh page load keep the previous game's
        # scoreboard up (the client alone can only preserve it while the page
        # stays mounted). Restricted to the same tracker session so a restart
        # doesn't resurrect a game from a session whose feed is gone.
        frozen: Optional[Dict[str, Any]] = None
        if status is not None and not status.get("in_game"):
            try:
                parsed = json.loads(status.get("last_game_json") or "")
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict) and parsed.get("session_id") == session_id:
                frozen = parsed

        # The game the feed should show: the live one, or — between games —
        # the game the last events belong to, so the feed's tail still lands
        # and the previous game stays on screen until the next one starts.
        feed_game_id = (
            (status.get("game_id") if status else None)
            or (frozen.get("game_id") if frozen else None)
            or _latest_event_game_id(conn, session_id)
        )

        now_payload: Optional[Dict[str, Any]] = None
        if status is not None:
            # Game-scoped fields come from the live row during a game, and
            # from the frozen last-game snapshot between games.
            source = frozen if frozen else status
            # The tracker writes live colors straight into live_status (from
            # cards played, via Arena's card DB); the game_card_summary query
            # is the fallback once the game has persisted — and the only
            # source for the previous-game scoreboard.
            colors = {
                "player": str(source.get("player_colors") or ""),
                "opponent": str(source.get("opponent_colors") or ""),
            }
            if not colors["player"] and not colors["opponent"]:
                colors = _seat_colors(conn, feed_game_id)
            now_payload = {
                "player_colors": colors["player"],
                "opponent_colors": colors["opponent"],
                "in_game": bool(status.get("in_game")),
                "last_game_frozen": frozen is not None,
                "match_id": source.get("match_id"),
                "game_id": feed_game_id,
                "format": source.get("format"),
                "match_type": source.get("match_type"),
                "game_number": source.get("game_number"),
                "player_name": source.get("player_name"),
                "opponent_name": source.get("opponent_name"),
                "deck_name": source.get("deck_name"),
                "turn_number": source.get("turn_number"),
                "active_role": source.get("active_role"),
                "on_play": (None if source.get("on_play") is None else bool(source.get("on_play"))),
                "player_life": source.get("player_life"),
                "opponent_life": source.get("opponent_life"),
                "mulligans": source.get("mulligans"),
                "game_started_at": source.get("game_started_at"),
                "player_commanders": _json_list(source.get("player_commanders")),
                "opponent_commanders": _json_list(source.get("opponent_commanders")),
                # Live scoreboard extras (columns absent in old DBs read None).
                "player_lands": source.get("player_lands"),
                "opponent_lands": source.get("opponent_lands"),
                "turn_started_at": source.get("turn_started_at"),
                "lands_seen": source.get("lands_seen"),
                "cards_seen": source.get("cards_seen"),
                "ramped_lands": source.get("ramped_lands"),
                "deck_size": source.get("deck_size"),
                "deck_lands": source.get("deck_lands"),
                "head_to_head": _head_to_head(
                    conn, source.get("opponent_name"), feed_game_id
                ),
                "deck_record": _deck_record(conn, source.get("deck_name"), feed_game_id),
                "rank": _rank_context(conn, source.get("format")),
                "archetype_guess": (
                    _archetype_guess(conn, status.get("opponent_cards"), feed_game_id)
                    if status.get("in_game")
                    else None
                ),
            }

        events, seq = _events_payload(conn, feed_game_id, since)
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


def build_status_payload(db_path: Path) -> Dict[str, Any]:
    """Cheap tracker-state-only payload for the sidebar's Live Log light."""
    db_uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    now = datetime.now()
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        status = _live_status(conn)
    return {
        "tracker": {
            "state": _tracker_state(status, now),
            "updated_at": status.get("updated_at") if status else None,
            "session_id": status.get("session_id") if status else None,
        }
    }


def handle_get(
    path: str, query: Dict[str, List[str]], db_path: Path
) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path != "/api/live":
        return None
    try:
        if query.get("status", ["0"])[0] == "1":
            return 200, build_status_payload(db_path)
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
