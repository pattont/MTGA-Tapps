"""Dependency-free local dashboard for the MTGA tracker SQLite DB."""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from .analytics import AnalyticsStore
from .format_normalizer import format_label
from .paths import DATA_DIR


DEFAULT_DB_PATH = DATA_DIR / "mtga_tracker.sqlite3"


def _dict_rows(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
    columns = [column[0] for column in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def dashboard_snapshot(db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Return dashboard-friendly aggregate data from SQLite."""
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        AnalyticsStore.ensure_schema(conn)
        summary = conn.execute(
            """
            SELECT
              COUNT(*) AS games,
              SUM(g.outcome = 'win') AS wins,
              SUM(g.outcome = 'loss') AS losses,
              SUM(g.outcome = 'draw') AS draws,
              ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
            FROM games g
            """
        ).fetchone()
        deck_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                GROUP BY p.deck_name
                ORDER BY games DESC, win_rate DESC
                LIMIT 20
                """
            )
        )
        format_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  COALESCE(m.format, '(unknown)') AS raw_format,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN matches m ON m.id = g.match_id
                GROUP BY m.format
                ORDER BY games DESC
                LIMIT 20
                """
            )
        )
        play_draw_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  CASE p.went_first WHEN 1 THEN 'On the play' WHEN 0 THEN 'On the draw' ELSE 'Unknown' END AS play_draw,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                GROUP BY p.went_first
                ORDER BY play_draw
                """
            )
        )
        deck_play_draw_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  CASE p.went_first WHEN 1 THEN 'On the play' WHEN 0 THEN 'On the draw' ELSE 'Unknown' END AS play_draw,
                  COUNT(*) AS games,
                  SUM(g.outcome = 'win') AS wins,
                  SUM(g.outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(g.outcome = 'win') / NULLIF(SUM(g.outcome IN ('win', 'loss')), 0), 1) AS win_rate
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                GROUP BY p.deck_name, p.went_first
                ORDER BY deck_name, play_draw
                LIMIT 40
                """
            )
        )
        draw_quality_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  COALESCE(g.started_at, g.ended_at) AS started_at,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  g.outcome,
                  COUNT(seen.display_name) AS cards_seen,
                  COALESCE(SUM(CASE
                    WHEN seen.type_category = 'Land' OR seen.display_name LIKE '%(Land)' THEN 1
                    ELSE 0
                  END), 0) AS lands_seen,
                  ROUND(
                    100.0 * COALESCE(SUM(CASE
                      WHEN seen.type_category = 'Land' OR seen.display_name LIKE '%(Land)' THEN 1
                      ELSE 0
                    END), 0) / NULLIF(COUNT(seen.display_name), 0),
                    1
                  ) AS land_seen_pct,
                  COALESCE(SUM(CASE WHEN seen.source = 'opening' THEN 1 ELSE 0 END), 0) AS opening_cards,
                  COALESCE(SUM(CASE WHEN seen.source = 'draw' THEN 1 ELSE 0 END), 0) AS known_draws
                FROM games g
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                LEFT JOIN (
                  SELECT game_id, participant_id, display_name, type_category, 'opening' AS source
                  FROM game_opening_hand_cards
                  UNION ALL
                  SELECT game_id, participant_id, display_name, type_category, 'draw' AS source
                  FROM game_drawn_cards
                ) seen ON seen.game_id = g.id AND seen.participant_id = p.id
                GROUP BY g.id
                ORDER BY COALESCE(g.started_at, g.ended_at) DESC, g.id DESC
                LIMIT 25
                """
            )
        )
        drawn_card_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  d.display_name,
                  COALESCE(d.type_category, 'Other') AS type_category,
                  COUNT(*) AS times_drawn,
                  COUNT(DISTINCT d.game_id) AS games_seen,
                  ROUND(100.0 * COUNT(DISTINCT d.game_id) / NULLIF((SELECT COUNT(*) FROM games), 0), 1) AS pct_of_games
                FROM game_drawn_cards d
                JOIN participants p ON p.id = d.participant_id AND p.role = 'player'
                GROUP BY d.display_name, d.type_category
                ORDER BY times_drawn DESC, d.display_name
                LIMIT 25
                """
            )
        )
        momentum_rows = _dict_rows(
            conn.execute(
                """
                WITH ordered_games AS (
                  SELECT
                    g.id,
                    g.outcome,
                    p.went_first,
                    p.mulligans,
                    LAG(g.outcome) OVER (
                      ORDER BY COALESCE(g.started_at, g.ended_at), g.id
                    ) AS previous_outcome
                  FROM games g
                  JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                )
                SELECT
                  CASE previous_outcome WHEN 'win' THEN 'After a win' WHEN 'loss' THEN 'After a loss' END AS split,
                  COUNT(*) AS games,
                  SUM(outcome = 'win') AS wins,
                  SUM(outcome = 'loss') AS losses,
                  ROUND(100.0 * SUM(outcome = 'win') / NULLIF(SUM(outcome IN ('win', 'loss')), 0), 1) AS win_rate,
                  ROUND(AVG(COALESCE(mulligans, 0)), 2) AS avg_mulligans,
                  ROUND(100.0 * SUM(went_first = 1) / NULLIF(SUM(went_first IN (0, 1)), 0), 1) AS on_play_pct
                FROM ordered_games
                WHERE previous_outcome IN ('win', 'loss')
                GROUP BY previous_outcome
                ORDER BY split
                """
            )
        )
        recent_rows = _dict_rows(
            conn.execute(
                """
                SELECT
                  g.started_at,
                  g.outcome,
                  g.duration_seconds,
                  m.format AS raw_format,
                  COALESCE(p.deck_name, '(unknown)') AS deck_name,
                  p.mulligans
                FROM games g
                JOIN matches m ON m.id = g.match_id
                JOIN participants p ON p.game_id = g.id AND p.role = 'player'
                ORDER BY g.started_at DESC
                LIMIT 25
                """
            )
        )

    summary_dict = {
        "games": int(summary[0] or 0),
        "wins": int(summary[1] or 0),
        "losses": int(summary[2] or 0),
        "draws": int(summary[3] or 0),
        "win_rate": summary[4],
    }
    for row in format_rows:
        row["format_label"] = format_label(row.get("raw_format"))
    for row in recent_rows:
        row["format_label"] = format_label(row.get("raw_format"))
    return {
        "summary": summary_dict,
        "decks": deck_rows,
        "formats": format_rows,
        "play_draw": play_draw_rows,
        "deck_play_draw": deck_play_draw_rows,
        "draw_quality": draw_quality_rows,
        "drawn_cards": drawn_card_rows,
        "momentum": momentum_rows,
        "recent": recent_rows,
    }


def _table(headers: List[str], rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<p class='empty'>No rows yet.</p>"
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(row.get(header, '') if row.get(header, '') is not None else ''))}</td>"
                for header in headers
            )
            + "</tr>"
        )
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_dashboard_html(snapshot: Dict[str, Any]) -> str:
    """Render a simple dashboard HTML document from a snapshot."""
    summary = snapshot["summary"]
    deck_rows = [
        {
            "Deck": row["deck_name"],
            "Games": row["games"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "WR": row["win_rate"],
        }
        for row in snapshot["decks"]
    ]
    format_rows = [
        {
            "Format": row["format_label"],
            "Raw": row["raw_format"],
            "Games": row["games"],
            "WR": row["win_rate"],
        }
        for row in snapshot["formats"]
    ]
    play_draw_rows = [
        {
            "Split": row["play_draw"],
            "Games": row["games"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "WR": row["win_rate"],
        }
        for row in snapshot["play_draw"]
    ]
    deck_play_draw_rows = [
        {
            "Deck": row["deck_name"],
            "Split": row["play_draw"],
            "Games": row["games"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "WR": row["win_rate"],
        }
        for row in snapshot["deck_play_draw"]
    ]
    draw_quality_rows = [
        {
            "Started": row["started_at"],
            "Deck": row["deck_name"],
            "Outcome": row["outcome"],
            "Seen": row["cards_seen"],
            "Lands": row["lands_seen"],
            "Land %": row["land_seen_pct"],
            "Opening": row["opening_cards"],
            "Known Draws": row["known_draws"],
        }
        for row in snapshot["draw_quality"]
    ]
    drawn_card_rows = [
        {
            "Card": row["display_name"],
            "Type": row["type_category"],
            "Draws": row["times_drawn"],
            "Games": row["games_seen"],
            "% Games": row["pct_of_games"],
        }
        for row in snapshot["drawn_cards"]
    ]
    momentum_rows = [
        {
            "Split": row["split"],
            "Games": row["games"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "WR": row["win_rate"],
            "Avg Mulligans": row["avg_mulligans"],
            "On Play %": row["on_play_pct"],
        }
        for row in snapshot["momentum"]
    ]
    recent_rows = [
        {
            "Started": row["started_at"],
            "Deck": row["deck_name"],
            "Format": row["format_label"],
            "Outcome": row["outcome"],
            "Mulligans": row["mulligans"],
            "Minutes": round((row["duration_seconds"] or 0) / 60.0, 1),
        }
        for row in snapshot["recent"]
    ]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="20">
  <title>MTGA Tracker Dashboard</title>
  <style>
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; background: #111827; color: #f9fafb; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 18px; font-size: 32px; }}
    h2 {{ margin-top: 30px; color: #bfdbfe; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; }}
    .card {{ background: linear-gradient(135deg, #1f2937, #0f172a); border: 1px solid #374151; border-radius: 16px; padding: 18px; }}
    .label {{ color: #9ca3af; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; }}
    .value {{ font-size: 30px; font-weight: 800; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; background: #0f172a; border: 1px solid #374151; border-radius: 14px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #1f2937; }}
    th {{ color: #93c5fd; background: #111827; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{ color: #9ca3af; }}
    .note {{ color: #cbd5e1; margin: 8px 0 14px; max-width: 900px; line-height: 1.45; }}
  </style>
</head>
<body>
<main>
  <h1>MTGA Tracker Dashboard</h1>
  <section class="cards">
    <div class="card"><div class="label">Games</div><div class="value">{summary["games"]}</div></div>
    <div class="card"><div class="label">Wins</div><div class="value">{summary["wins"]}</div></div>
    <div class="card"><div class="label">Losses</div><div class="value">{summary["losses"]}</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value">{summary["win_rate"] or ""}%</div></div>
  </section>
  <h2>Decks</h2>{_table(["Deck", "Games", "Wins", "Losses", "WR"], deck_rows)}
  <h2>Formats</h2>{_table(["Format", "Raw", "Games", "WR"], format_rows)}
  <h2>Play / Draw</h2>{_table(["Split", "Games", "Wins", "Losses", "WR"], play_draw_rows)}
  <h2>Deck Play / Draw</h2>{_table(["Deck", "Split", "Games", "Wins", "Losses", "WR"], deck_play_draw_rows)}
  <h2>Draw Quality</h2>
  <p class="note">Opening hands plus known visible draws. Older games may only have opening-hand data.</p>
  {_table(["Started", "Deck", "Outcome", "Seen", "Lands", "Land %", "Opening", "Known Draws"], draw_quality_rows)}
  <h2>Visible Drawn Cards</h2>{_table(["Card", "Type", "Draws", "Games", "% Games"], drawn_card_rows)}
  <h2>Momentum</h2>
  <p class="note">Next-game results after wins and losses, including mulligans and on-play percentage.</p>
  {_table(["Split", "Games", "Wins", "Losses", "WR", "Avg Mulligans", "On Play %"], momentum_rows)}
  <h2>Recent Games</h2>{_table(["Started", "Deck", "Format", "Outcome", "Mulligans", "Minutes"], recent_rows)}
</main>
</body>
</html>"""


def render_snapshot_json(snapshot: Dict[str, Any]) -> bytes:
    """Return UTF-8 encoded dashboard JSON."""
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _send_bytes(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    content_type: str,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler rendering the dashboard on each request."""

    db_path: Path = DEFAULT_DB_PATH

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        request_path = parsed.path
        if request_path == "/api/snapshot":
            try:
                body = render_snapshot_json(dashboard_snapshot(self.db_path))
            except Exception as exc:
                _send_bytes(self, 500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                return
            _send_bytes(self, 200, body, "application/json; charset=utf-8")
            return
        if request_path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        try:
            body = render_dashboard_html(dashboard_snapshot(self.db_path)).encode("utf-8")
        except Exception as exc:
            _send_bytes(self, 500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        _send_bytes(self, 200, body, "text/html; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local MTGA tracker dashboard.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port.")
    args = parser.parse_args()

    DashboardHandler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nExiting dashboard...")


if __name__ == "__main__":
    main()
