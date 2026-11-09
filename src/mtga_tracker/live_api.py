"""Live Log API: /api/live served straight from SQLite.

The tracker maintains a single-row live_status snapshot and appends every
in-game turn-log line to game_events — the same table the /game page's
Timeline renders — so the dashboard can drive the Live Log page purely
from the database, and the live feed reads exactly like the game page.

GET /api/live?since=<game_events.id> returns:

    {
      "tracker": {"state": "live"|"idle"|"offline", "updated_at": ...},
      "now": {...live_status fields...} | null,
      "session": {games, wins, losses, draws, win_rate, runtime_seconds,
                  started_at, play, draw} | null,
      "today": {games, wins, losses, draws, win_rate, play, draw} | null,
      "games": [{id, started_at, deck_name, opponent_name, outcome,
                 total_turns, duration_seconds, game_number, format, replay}],
      "events": [{id, at, turn, style, text, player_life, opponent_life}],
      "seq": <highest game_events id sent>
    }

`since` makes events a delta; the first call (since omitted or 0) returns
the most recent lines. `state` is "offline" when live_status.updated_at is
stale (tracker not running), "live" during a game, "idle" otherwise.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .colors import BASIC_LAND_COLORS, colors_from_label

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


def _open_readonly(db_uri: str, **kwargs: Any) -> sqlite3.Connection:
    """Open a read-only connection, retrying once when SQLite says it could
    not open the file. A `mode=ro` open of a WAL database can lose a race
    with the writer's checkpoint (the -wal file it just listed is gone), and
    a process at its open-file limit gets the same message; both are worth
    one more try 50 ms later, and both are worth a diagnostic line when the
    retry fails too, because the message itself explains nothing."""
    try:
        return sqlite3.connect(db_uri, uri=True, **kwargs)
    except sqlite3.OperationalError as exc:
        if "unable to open" not in str(exc).lower():
            raise
        time.sleep(0.05)
        try:
            return sqlite3.connect(db_uri, uri=True, **kwargs)
        except sqlite3.OperationalError:
            _log_cantopen(db_uri, exc)
            raise


def _log_cantopen(db_uri: str, exc: BaseException) -> None:
    """Append what a "unable to open database file" needs to be understood:
    whether the file and its WAL companions exist, and how close the process
    is to its open-file limit."""
    try:
        from .paths import DATA_DIR

        path = Path(db_uri.split("?", 1)[0].replace("file://", "")).expanduser()
        exists = {
            suffix: (path.parent / (path.name + suffix)).exists() for suffix in ("", "-wal", "-shm")
        }
        fds: Any = "?"
        limit: Any = "?"
        try:
            import resource

            limit = resource.getrlimit(resource.RLIMIT_NOFILE)
            fd_dir = Path("/dev/fd")
            if fd_dir.is_dir():
                fds = sum(1 for _ in fd_dir.iterdir())
        except Exception:
            pass
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "dashboard-errors.log", "a", encoding="utf-8") as handle:
            handle.write(
                f"{datetime.now().isoformat()} {type(exc).__name__}: {exc} | files={exists} "
                f"open_fds={fds} limit={limit}\n"
            )
    except Exception:
        pass


def _live_status(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    try:
        cursor = conn.execute("SELECT * FROM live_status WHERE id = 1")
    except sqlite3.OperationalError:
        # Database predates the live_status table (dashboard-only install
        # that never ran a new tracker).
        return None
    return _dict_row(cursor)


def _naive_local(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _tracker_state(status: Optional[Dict[str, Any]], now: datetime) -> str:
    """live / idle / offline from the live row: the single place the
    heartbeat age (OFFLINE_AFTER_SECONDS) decides whether a tracker runs."""
    if status is None:
        return "offline"
    updated_at = _naive_local(_parse_iso(status.get("updated_at")))
    now = _naive_local(now) or datetime.now()
    if updated_at is None or now - updated_at > timedelta(seconds=OFFLINE_AFTER_SECONDS):
        return "offline"
    return "live" if status.get("in_game") else "idle"


def _json_value(value: Any, kind: type) -> Any:
    """A JSON column parsed to `kind` (dict or list), else None."""
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, kind) else None


def _session_payload(
    conn: sqlite3.Connection, session_id: Optional[str]
) -> Optional[Dict[str, Any]]:
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


#: The overlay polls several times a second during a game and the record
#: against this opponent cannot change until the game ends (which brings a
#: new game id), so one lookup per (opponent, game) is enough.
_head_to_head_cache: Dict[Tuple[str, str, Optional[str]], Optional[Dict[str, Any]]] = {}


def _head_to_head(
    conn: sqlite3.Connection,
    opponent_name: Optional[str],
    current_game_id: Optional[str],
    cache_scope: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Lifetime record vs this opponent name (the current game excluded).
    With a `cache_scope` (the database path) the answer is memoised per
    (database, opponent, game) for the overlay's poll."""
    name = str(opponent_name or "").strip()
    if not name:
        return None
    if cache_scope is None or current_game_id is None:
        return _head_to_head_query(conn, name, current_game_id)
    key = (cache_scope, name, current_game_id)
    if key in _head_to_head_cache:
        return _head_to_head_cache[key]
    result = _head_to_head_query(conn, name, current_game_id)
    if len(_head_to_head_cache) > 32:
        _head_to_head_cache.clear()
    _head_to_head_cache[key] = result
    return result


def _head_to_head_query(
    conn: sqlite3.Connection, name: str, current_game_id: Optional[str]
) -> Optional[Dict[str, Any]]:
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


#: The overlay's session record changes only when a game ends, so the
#: play/draw split is looked up once per (database, session, totals).
_overlay_session_cache: Dict[Tuple[str, str, Tuple[int, ...]], Dict[str, Any]] = {}


def _play_draw_split(
    conn: sqlite3.Connection, where: str, params: Tuple[Any, ...]
) -> Dict[str, Dict[str, int]]:
    """Wins and losses on the play and on the draw for the games `where`
    selects (`participants.went_first`; unknown turn order counts in neither)."""
    split = {"play": {"wins": 0, "losses": 0}, "draw": {"wins": 0, "losses": 0}}
    try:
        rows = conn.execute(
            f"""
            SELECT p.went_first, g.outcome, COUNT(*)
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            WHERE {where} AND g.outcome IN ('win', 'loss')
              AND p.went_first IS NOT NULL
            GROUP BY p.went_first, g.outcome
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for went_first, outcome, count in rows:
        side = split["play" if went_first else "draw"]
        side["wins" if outcome == "win" else "losses"] += int(count or 0)
    return split


def _today_record(conn: sqlite3.Connection, today: str) -> Optional[Dict[str, Any]]:
    """Every game finished today (local date, like Today's Games), across
    sessions: the Record widget's "Today" view, with the play/draw split."""
    try:
        row = conn.execute(
            """
            SELECT COUNT(*),
                   SUM(outcome = 'win'), SUM(outcome = 'loss'), SUM(outcome = 'draw')
            FROM games
            WHERE date(started_at) = ? AND outcome IN ('win', 'loss', 'draw')
            """,
            (today,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    games, wins, losses, draws = (int(value or 0) for value in row)
    decided = wins + losses
    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": round(100.0 * wins / decided, 1) if decided else None,
        **_play_draw_split(conn, "date(g.started_at) = ?", (today,)),
    }


def _overlay_session(
    conn: sqlite3.Connection, session_id: Optional[str], cache_scope: str
) -> Optional[Dict[str, Any]]:
    """This tracker session's record for the overlay footer: the same totals
    as the Stream Kit record widget, plus wins/losses on the play and on the
    draw (`participants.went_first`; unknown turn order counts in neither)."""
    if not session_id:
        return None
    try:
        row = conn.execute(
            "SELECT games_played, wins, losses, draws FROM tracker_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    totals = tuple(int(value or 0) for value in row)
    key = (cache_scope, session_id, totals)
    cached = _overlay_session_cache.get(key)
    if cached is not None:
        return cached
    games, wins, losses, draws = totals
    split = _play_draw_split(conn, "g.session_id = ?", (session_id,))
    decided = wins + losses
    result = {
        "games": games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": round(100.0 * wins / decided, 1) if decided else None,
        **split,
    }
    if len(_overlay_session_cache) > 32:
        _overlay_session_cache.clear()
    _overlay_session_cache[key] = result
    return result


def _commander_record(
    conn: sqlite3.Connection,
    opponent_commanders: Any,
    current_game_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Lifetime record against each of the opponent's commanders (Brawl),
    the current game excluded. Commanders you have never faced before are
    left out — an empty list means nothing to show."""
    records: List[Dict[str, Any]] = []
    for name in _json_list(opponent_commanders):
        commander = str(name or "").strip()
        if not commander:
            continue
        try:
            row = conn.execute(
                """
                SELECT
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses
                FROM games g
                JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
                JOIN participant_commanders pc ON pc.participant_id = o.id
                WHERE pc.card_name = ? AND g.id IS NOT ? AND g.outcome IN ('win', 'loss')
                """,
                (commander, current_game_id),
            ).fetchone()
        except sqlite3.OperationalError:
            return []
        wins, losses = int(row[0] or 0), int(row[1] or 0)
        if wins + losses == 0:
            continue
        records.append({"commander": commander, "wins": wins, "losses": losses})
    return records


#: Results listed in deck_record's recent form, newest first.
DECK_RECENT_GAMES = 10


def _deck_record(
    conn: sqlite3.Connection,
    deck_name: Optional[str],
    current_game_id: Optional[str],
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Lifetime, today's and this session's record with this deck (the current
    game excluded), split like Deck Manager's record into ranked / unranked
    queues and on the play / on the draw, with the last results."""
    from .format_normalizer import normalize_match_format

    name = str(deck_name or "").strip()
    if not name:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        rows = conn.execute(
            """
            SELECT
              m.format,
              MAX(COALESCE(m.best_of, 1)),
              p.went_first,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              SUM(g.outcome = 'win' AND date(g.started_at) = ?) AS today_wins,
              SUM(g.outcome = 'loss' AND date(g.started_at) = ?) AS today_losses,
              SUM(g.outcome = 'win' AND g.session_id IS ?) AS session_wins,
              SUM(g.outcome = 'loss' AND g.session_id IS ?) AS session_losses
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            LEFT JOIN matches m ON m.id = g.match_id
            WHERE p.deck_name = ? AND g.id IS NOT ? AND g.outcome IN ('win', 'loss')
            GROUP BY m.format, p.went_first
            """,
            (today, today, session_id, session_id, name, current_game_id),
        ).fetchall()
        recent = conn.execute(
            f"""
            SELECT g.outcome
            FROM games g
            JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            WHERE p.deck_name = ? AND g.id IS NOT ? AND g.outcome IN ('win', 'loss')
            ORDER BY g.started_at DESC
            LIMIT {DECK_RECENT_GAMES}
            """,
            (name, current_game_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    record: Dict[str, Any] = {
        "wins": 0,
        "losses": 0,
        "today_wins": 0,
        "today_losses": 0,
        "session_wins": 0,
        "session_losses": 0,
        **{split: {"wins": 0, "losses": 0} for split in ("ranked", "unranked", "play", "draw")},
    }
    ranked_formats: Dict[Any, bool] = {}
    for (
        raw_format,
        best_of,
        went_first,
        wins,
        losses,
        today_wins,
        today_losses,
        *in_session,
    ) in rows:
        if raw_format not in ranked_formats:
            label = normalize_match_format(str(raw_format or ""), default_best_of=best_of).label
            ranked_formats[raw_format] = "(Ranked)" in label
        targets = [record["ranked" if ranked_formats[raw_format] else "unranked"]]
        if went_first is not None:
            targets.append(record["play" if went_first else "draw"])
        for target in [record, *targets]:
            target["wins"] += int(wins or 0)
            target["losses"] += int(losses or 0)
        record["today_wins"] += int(today_wins or 0)
        record["today_losses"] += int(today_losses or 0)
        if session_id:
            record["session_wins"] += int(in_session[0] or 0)
            record["session_losses"] += int(in_session[1] or 0)
    if record["wins"] + record["losses"] == 0:
        return None
    record["win_rate"] = round(100.0 * record["wins"] / (record["wins"] + record["losses"]), 1)
    record["recent"] = [str(row[0]) for row in recent]
    return record


def _match_score(
    conn: sqlite3.Connection, match_id: Optional[str], current_game_id: Optional[str]
) -> Optional[Dict[str, int]]:
    """Games won and lost so far in this match (a Bo3's score), the current
    game excluded."""
    if not match_id:
        return None
    try:
        row = conn.execute(
            """
            SELECT SUM(outcome = 'win'), SUM(outcome = 'loss'), SUM(outcome = 'draw')
            FROM games WHERE match_id = ? AND id IS NOT ?
            """,
            (match_id, current_game_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return {"wins": int(row[0] or 0), "losses": int(row[1] or 0), "draws": int(row[2] or 0)}


def _rank_context(
    conn: sqlite3.Connection,
    format_label: Optional[str],
    session_started_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Latest rank snapshot for the game's ladder — shown for ranked games.

    Limited queues read from the limited ladder; everything else ranked reads
    from constructed. Non-ranked formats return None. `start` is the rank
    before the session began (the last snapshot older than it), for the
    climb this session; None when there is none.
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
    row["start"] = None
    if session_started_at:
        try:
            start = _dict_row(
                conn.execute(
                    """
                    SELECT rank_class, rank_level, rank_step, rank_steps,
                           mythic_percentile, mythic_rank
                    FROM rank_snapshots
                    WHERE rank_format = ? AND captured_at < ?
                    ORDER BY captured_at DESC, id DESC
                    LIMIT 1
                    """,
                    (rank_format, session_started_at),
                )
            )
        except sqlite3.OperationalError:
            start = None
        row["start"] = start
    return row


#: An archetype guess needs at least this many of the opponent's revealed
#: cards matching the historical archetype's played cards.
ARCHETYPE_GUESS_MIN_MATCHES = 2


def _archetype_contradicts_colors(archetype: str, table_colors: set) -> bool:
    """True when the archetype's colour word cannot contain the colours the
    opponent has already shown (a "Mono-Red" guess after a Forest). Names
    without a recognised colour word never contradict."""
    letters = colors_from_label(archetype)
    if not letters or letters == "C":
        return False
    return not table_colors <= set(letters)


def _archetype_guess(
    conn: sqlite3.Connection,
    opponent_cards_json: Any,
    current_game_id: Optional[str],
    opponent_colors: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Guess the opponent's archetype from their revealed cards, using past
    games whose opponents were identified (Deck AI) — no network, no model:
    the archetype whose historical played-cards overlap this game's revealed
    cards the most wins, with your record against it attached.

    Lands never count as evidence (a Mountain matches every red deck ever
    faced), and a guess whose colour word contradicts the colours already on
    the table is thrown out — "Mono-Red" cannot be right once a Forest has
    been played.
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
              AND COALESCE(s.type_category, '') != 'Land'
              AND s.display_name NOT LIKE '%(Land)'
            """,
            (current_game_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None

    # Base card names, so "(Land)" suffixes and split faces still match.
    def base(name: str) -> str:
        return str(name or "").split(" (")[0].split(" // ")[0].strip().casefold()

    revealed_bases = {base(name) for name in revealed} - {
        name.casefold() for name in BASIC_LAND_COLORS
    }
    table_colors = set(str(opponent_colors or "")) & set("WUBRG")
    matches: Dict[str, set] = {}
    for archetype, card_name in rows:
        if base(card_name) in revealed_bases:
            matches.setdefault(str(archetype), set()).add(base(card_name))
    if table_colors:
        matches = {
            archetype: cards
            for archetype, cards in matches.items()
            if not _archetype_contradicts_colors(archetype, table_colors)
        }
    if not matches:
        return None
    archetype, matched = max(matches.items(), key=lambda item: (len(item[1]), item[0]))
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


def _latest_event_game_id(conn: sqlite3.Connection, session_id: Optional[str]) -> Optional[str]:
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
            "SELECT game_id FROM game_events WHERE session_id = ? AND visible = 1 "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return str(row[0]) if row and row[0] else None


def _games_payload(
    conn: sqlite3.Connection, session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Today's finished games plus this tracker session's, and always the
    most recent game, newest first, ready to link to #/game/<id>. The
    session's games matter past midnight: a game that started at 23:58 must
    still be the "previous game" — with its outcome — at 00:05, not vanish
    because the calendar day rolled over; the most recent game keeps the
    "Last game: …" line honest after a restart."""
    from .dashboard import _attach_replay_availability

    today = datetime.now().strftime("%Y-%m-%d")
    session_prefix = f"{session_id}:%" if session_id else ""
    rows = _dict_rows(
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
              p.went_first,
              o.display_name AS opponent_name
            FROM games g
            JOIN matches m ON m.id = g.match_id
            LEFT JOIN participants p ON p.game_id = g.id AND p.role = 'player'
            LEFT JOIN participants o ON o.game_id = g.id AND o.role = 'opponent'
            WHERE date(g.started_at) = ?
               OR (? != '' AND g.id LIKE ?)
               OR g.id = (SELECT id FROM games ORDER BY started_at DESC LIMIT 1)
            ORDER BY g.started_at DESC
            LIMIT 40
            """,
            (today, session_prefix, session_prefix),
        )
    )
    _attach_replay_availability(conn, rows, key="id")
    return rows


def _events_payload(
    conn: sqlite3.Connection,
    game_id: Optional[str],
    since: int,
    cache_scope: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Timeline rows for the CURRENT game, straight from game_events — the
    exact same source the /game page's Timeline renders, so the live feed
    and the game page read identically. Between games there is nothing to
    stream (finished games live in the rail); match summaries never hit
    game_events, so they never reach the feed."""
    if not game_id:
        return [], since
    from .dashboard import _visible_events_clause

    # Silent replay-only rows (visible = 0) are not printed history.
    visible = _visible_events_clause(conn)
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
            WHERE game_id = ?{visible} AND (id > ? OR id IN (
                SELECT id FROM game_events WHERE game_id = ?{visible}
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
            WHERE game_id = ? AND id > ?{visible}
            ORDER BY id ASC
            LIMIT {MAX_EVENT_LINES}
            """
        params = (game_id, since)
    rows = _dict_rows(conn.execute(query, params))
    if not rows:
        return [], since

    # Same card-link segmentation as the game page's timeline.
    from .dashboard import _timeline_text_segments

    linkable_cards = _linkable_cards(conn, cache_scope)

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


def _linkable_cards(
    conn: sqlite3.Connection, cache_scope: Optional[str]
) -> Dict[str, Optional[str]]:
    """Clean card name -> type for every name in game_card_summary. With a
    `cache_scope` (the database) the DISTINCT over the whole table is reused
    until the table gains or loses rows or a type is filled in (one
    aggregate query), or LINKABLE_MEMO_TTL_SECONDS pass."""
    from .dashboard import _clean_card_name

    key: Optional[Tuple[Any, ...]] = None
    if cache_scope is not None:
        try:
            key = tuple(
                conn.execute(
                    "SELECT MAX(rowid), COUNT(*), COUNT(type_category) FROM game_card_summary"
                ).fetchone()
            )
        except sqlite3.Error:
            key = None
        if key is not None:
            with _live_payload_lock:
                entry = _linkable_cards_cache.get(cache_scope)
                if entry is not None and entry[0] == key and time.monotonic() < entry[2]:
                    return entry[1]
    linkable_cards: Dict[str, Optional[str]] = {}
    for display_name, type_category in conn.execute(
        "SELECT DISTINCT display_name, type_category FROM game_card_summary"
    ):
        clean_name = _clean_card_name(display_name)
        if clean_name and (clean_name not in linkable_cards or not linkable_cards[clean_name]):
            linkable_cards[clean_name] = type_category
    if cache_scope is not None and key is not None:
        with _live_payload_lock:
            _linkable_cards_cache[cache_scope] = (
                key,
                linkable_cards,
                time.monotonic() + LINKABLE_MEMO_TTL_SECONDS,
            )
    return linkable_cards


def build_live_payload(
    db_path: Path, since: int = 0, include_events: bool = True
) -> Dict[str, Any]:
    """The Live Scoreboard payload. include_events=False skips the event feed
    (stream widgets that show only the scoreboard ask for that)."""
    db_uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    now = datetime.now()
    # Read the version BEFORE the row: a commit landing in between makes the
    # body newer than its key, never older, and the next poll rebuilds.
    data_version = _poll_data_version(db_uri)
    with _open_readonly(db_uri) as conn:
        conn.execute("PRAGMA query_only = ON")
        status = _live_status(conn)
        state = _tracker_state(status, now)
        session_id = status.get("session_id") if status else None
        memo_key: Optional[Tuple[Any, ...]] = (
            (data_version, state, now.strftime("%Y-%m-%d"))
            if data_version is not None
            else None
        )
        cached = None
        if memo_key is not None:
            with _live_payload_lock:
                entry = _live_payload_cache.get(db_uri)
                if entry is not None and entry[0] == memo_key and time.monotonic() < entry[3]:
                    cached = entry
        if cached is not None:
            body, feed_game_id = cached[1], cached[2]
        else:
            body, feed_game_id = _live_body(conn, db_uri, status, session_id, now)
            if memo_key is not None:
                with _live_payload_lock:
                    _live_payload_cache[db_uri] = (
                        memo_key,
                        body,
                        feed_game_id,
                        time.monotonic() + LIVE_MEMO_TTL_SECONDS,
                    )
        if include_events:
            events, seq = _events_payload(conn, feed_game_id, since, db_uri)
        else:
            events, seq = [], since
    return {
        "tracker": {
            "state": state,
            "updated_at": status.get("updated_at") if status else None,
            "session_id": session_id,
        },
        **body,
        "events": events,
        "seq": seq,
    }


def _live_body(
    conn: sqlite3.Connection,
    db_uri: str,
    status: Optional[Dict[str, Any]],
    session_id: Optional[str],
    now: datetime,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Everything in the live payload but the tracker block and the event
    feed, plus the game the feed should show. Memoised by build_live_payload;
    callers must not mutate the result."""
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

    session = _session_payload(conn, session_id)
    if session:
        # The Record widget's play/draw columns: the overlay footer's split.
        split = _overlay_session(conn, session.get("id"), db_uri)
        if split:
            session["play"] = split["play"]
            session["draw"] = split["draw"]
    # Records exclude the game being played, but not the finished game
    # on screen between games.
    record_exclude = feed_game_id if (status and status.get("in_game")) else None
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
            "head_to_head": _head_to_head(conn, source.get("opponent_name"), feed_game_id),
            "deck_record": _deck_record(
                conn,
                source.get("deck_name"),
                record_exclude,
                session.get("id") if session else None,
            ),
            "match_score": _match_score(conn, source.get("match_id"), record_exclude),
            "opponent_seen": _json_value(source.get("opponent_seen"), list) or [],
            "draw_quality": _json_value(source.get("draw_quality"), dict),
            "commander_record": _commander_record(
                conn, source.get("opponent_commanders"), feed_game_id
            ),
            "rank": _rank_context(
                conn, source.get("format"), session.get("started_at") if session else None
            ),
            "archetype_guess": (
                _archetype_guess(
                    conn,
                    status.get("opponent_cards"),
                    feed_game_id,
                    source.get("opponent_colors"),
                )
                if status.get("in_game")
                else None
            ),
        }

    body = {
        "now": now_payload,
        "session": session,
        "today": _today_record(conn, now.strftime("%Y-%m-%d")),
        "games": _games_payload(conn, session_id),
    }
    return body, feed_game_id


def build_status_payload(db_path: Path) -> Dict[str, Any]:
    """Cheap tracker-state-only payload for the sidebar's Live Log light."""
    db_uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    now = datetime.now()
    with _open_readonly(db_uri) as conn:
        conn.execute("PRAGMA query_only = ON")
        status = _live_status(conn)
    return {
        "tracker": {
            "state": _tracker_state(status, now),
            "updated_at": status.get("updated_at") if status else None,
            "session_id": status.get("session_id") if status else None,
        }
    }


def game_activity(db_path: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    """What the database says about play right now, from one read-only
    connection: the tracker state (live / idle / offline by heartbeat age),
    the live row's raw `in_game` flag, and when the newest game ended.

    `in_game` is reported whatever the heartbeat's age; callers that need a
    running tracker combine it with `tracker`. A missing database or table
    reads as offline and idle; any other database error propagates so a
    guard can fail closed.
    """
    result: Dict[str, Any] = {
        "tracker": "offline",
        "in_game": False,
        "updated_at": None,
        "last_game_ended_at": None,
    }
    path = Path(db_path).expanduser()
    if not path.is_file():
        return result
    current = _naive_local(now) or datetime.now()
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('live_status', 'games')"
            )
        }
        status = _live_status(conn) if "live_status" in tables else None
        if "games" in tables:
            row = conn.execute("SELECT MAX(ended_at) FROM games").fetchone()
            result["last_game_ended_at"] = row[0] if row and row[0] else None
    finally:
        conn.close()
    if status is not None:
        result["in_game"] = bool(status.get("in_game"))
        result["updated_at"] = status.get("updated_at")
    result["tracker"] = _tracker_state(status, current)
    return result


#: The overlay polls three times a second; between console lines the live
#: row is byte-for-byte the same, so the encoded answer (and its ETag) is
#: kept per database and handed straight back while the row's identity —
#: its timestamp, overlay state, opponent, game, and the derived
#: live/idle/offline state — has not moved. One SELECT per unchanged poll.
_overlay_response_cache: Dict[str, Tuple[Tuple[Any, ...], bytes, str, float]] = {}

#: The memo's safety net: even with an unchanged key the body is rebuilt
#: this often, so nothing the key fails to capture can stick for long.
OVERLAY_MEMO_TTL_SECONDS = 60.0

#: `/api/live` without its event feed, memoised per database on SQLite's
#: data_version (which moves on any other connection's commit: a console
#: line, the heartbeat, a finished game, a backfill, a reset), the derived
#: live/idle/offline state and the local date. Polled twice a second by the
#: Live Scoreboard and every two seconds by each Stream Kit source, it used
#: to run its dozen queries (several over the whole history) on every poll.
_live_payload_cache: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Any], Optional[str], float]] = {}
_live_payload_lock = threading.Lock()
LIVE_MEMO_TTL_SECONDS = 30.0

#: The card names the live feed may link (every name ever in
#: game_card_summary), per database, keyed on that table's shape.
_linkable_cards_cache: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Optional[str]], float]] = {}
LINKABLE_MEMO_TTL_SECONDS = 60.0


#: One read-only connection per database for the poll's live-row check:
#: opening a connection is most of the cost of an unchanged poll. Guarded
#: by a lock because the dashboard serves each request on its own thread.
_poll_connections: Dict[str, sqlite3.Connection] = {}
_poll_lock = threading.Lock()


def _poll_live_status(db_uri: str) -> Optional[Dict[str, Any]]:
    with _poll_lock:
        conn = _poll_connections.get(db_uri)
        if conn is None:
            conn = _open_readonly(db_uri, check_same_thread=False)
            conn.execute("PRAGMA query_only = ON")
            _poll_connections[db_uri] = conn
        try:
            return _live_status(conn)
        except sqlite3.Error:
            # A closed or replaced database (reset, restore): reopen next time.
            _poll_connections.pop(db_uri, None)
            try:
                conn.close()
            except sqlite3.Error:
                pass
            raise


def reset_poll_connections() -> None:
    """Drop the poll's read-only connections and memos (the database was
    replaced or reset); the next poll reopens."""
    with _poll_lock:
        for conn in _poll_connections.values():
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _poll_connections.clear()
    _overlay_response_cache.clear()
    _overlay_session_cache.clear()
    with _live_payload_lock:
        _live_payload_cache.clear()
        _linkable_cards_cache.clear()


def _poll_data_version(db_uri: str) -> Optional[int]:
    """SQLite's data_version as seen by the poll connection: it changes
    whenever another connection commits, so it is an exact "anything new?"
    for the memos. None when it cannot be read (the memo is then skipped)."""
    with _poll_lock:
        conn = _poll_connections.get(db_uri)
        if conn is None:
            try:
                conn = _open_readonly(db_uri, check_same_thread=False)
                conn.execute("PRAGMA query_only = ON")
            except sqlite3.Error:
                return None
            _poll_connections[db_uri] = conn
        try:
            row = conn.execute("PRAGMA data_version").fetchone()
        except sqlite3.Error:
            return None
    return int(row[0]) if row else None


def overlay_response(db_path: Path) -> Tuple[bytes, str]:
    """`GET /api/overlay` as (JSON bytes, ETag), memoised while the live row
    is unchanged."""
    import hashlib

    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    db_uri = path.as_uri() + "?mode=ro"
    now = datetime.now()
    status = _poll_live_status(db_uri)
    # Every input of the body: the live row's overlay state, opponent, game
    # and session (the head-to-head record is memoised by opponent and game
    # itself), the session's totals for the footer, and live/idle/offline.
    # Not updated_at: the tracker's 5 s heartbeat bumps it without changing
    # anything the overlay shows, and every poller would get a full 200 and
    # a re-render each time instead of a 304.
    session_id = status.get("session_id") if status else None
    key = (
        status.get("overlay_json") if status else None,
        status.get("opponent_name") if status else None,
        status.get("game_id") if status else None,
        session_id,
        _session_totals(db_uri, session_id),
        _tracker_state(status, now),
    )
    monotonic = time.monotonic()
    cached = _overlay_response_cache.get(db_uri)
    if cached is not None and cached[0] == key and monotonic < cached[3]:
        return cached[1], cached[2]
    payload = json.dumps(
        build_overlay_payload(db_path, status=status, now=now), separators=(",", ":")
    ).encode("utf-8")
    etag = '"' + hashlib.sha1(payload).hexdigest()[:20] + '"'
    _overlay_response_cache[db_uri] = (key, payload, etag, monotonic + OVERLAY_MEMO_TTL_SECONDS)
    return payload, etag


def _session_totals(db_uri: str, session_id: Optional[str]) -> Optional[Tuple[Any, ...]]:
    """The tracker session's counters (one primary-key read on the poll
    connection), so a finished game refreshes the overlay's footer."""
    if not session_id:
        return None
    with _poll_lock:
        conn = _poll_connections.get(db_uri)
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT games_played, wins, losses, draws FROM tracker_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
    return tuple(row) if row else None


def build_overlay_payload(
    db_path: Path,
    *,
    status: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The in-game overlay's poll target: tracker state, the library state the
    tracker last wrote (see overlay_state.py), the head-to-head record the
    overlay header shows next to the opponent's name, and the session record
    its footer shows."""
    db_uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
    now = now or datetime.now()
    with _open_readonly(db_uri) as conn:
        conn.execute("PRAGMA query_only = ON")
        if status is None:
            status = _live_status(conn)
        state_raw = status.get("overlay_json") if status else None
        state: Optional[Dict[str, Any]] = None
        if state_raw:
            try:
                parsed = json.loads(state_raw)
                if isinstance(parsed, dict):
                    state = parsed
            except (TypeError, ValueError):
                state = None
        head_to_head = None
        if state and state.get("game_active") and status:
            head_to_head = _head_to_head(
                conn, status.get("opponent_name"), status.get("game_id"), cache_scope=db_uri
            )
        session = _overlay_session(conn, status.get("session_id") if status else None, db_uri)
    tracker_state = _tracker_state(status, now)
    if tracker_state == "offline":
        # A stale row must not keep a finished game's library on screen.
        state = None
        session = None
    return {
        "tracker": {
            "state": tracker_state,
            "session_id": status.get("session_id") if status else None,
        },
        "state": state,
        "head_to_head": head_to_head,
        "session": session,
    }


def handle_get(
    path: str, query: Dict[str, List[str]], db_path: Path
) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path == "/api/overlay":
        try:
            return 200, build_overlay_payload(db_path)
        except FileNotFoundError as exc:
            return 404, {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive surface
            return 500, {"error": f"{type(exc).__name__}: {exc}"}
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
        include_events = query.get("events", ["1"])[0] != "0"
        return 200, build_live_payload(db_path, since, include_events=include_events)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
