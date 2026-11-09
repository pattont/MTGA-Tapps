#!/usr/bin/env python3
"""Dump the dashboard's read payloads for a database, time them, and compare
two dumps. The check that a performance change kept every page's numbers.

    # Before: the code on main, from a worktree
    git worktree add /tmp/tapps-main main
    venv/bin/python scripts/dashboard_payloads.py dump --db COPY.sqlite3 \\
        --out /tmp/payloads-main --src /tmp/tapps-main/src

    # After: this checkout
    venv/bin/python scripts/dashboard_payloads.py dump --db COPY.sqlite3 --out /tmp/payloads-new

    venv/bin/python scripts/dashboard_payloads.py diff /tmp/payloads-main /tmp/payloads-new

``dump`` calls the same functions the HTTP handler calls (no server, no
response cache) for a fixed set of requests derived from the database itself:
the Overview under several filters, All Games, the most-played decks, games
spread across the history, opponents and cards. Each payload is written as
one JSON file, with the cold time and size of every request printed and saved
as ``timings.json``. Use a copy of the database (``build_scaled_db.py`` or
SQLite's ``.backup``), never the live file's path: day-window filters depend
on the clock, so dump both sides within the same day.

Every connection is opened with SQLite's bound-parameter limit set to 32,766,
the limit in the Windows build's SQLite (the macOS build allows far more), so
a query that binds one parameter per game fails here the way it would for a
Windows user. ``--sql-variable-limit 0`` leaves the limit alone.

A request that raises is recorded as ``{"__error__": ...}`` and makes the
exit status 1. ``diff`` prints where two dumps differ and exits 1 if they do.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
#: The bound-parameter limit of the SQLite in the Windows build.
WINDOWS_SQL_VARIABLE_LIMIT = 32766
TIMINGS_FILE = "timings.json"


def pin_sql_variable_limit(limit: int) -> bool:
    """Make every later ``sqlite3.connect`` return a connection with this
    bound-parameter limit. False when this Python cannot set limits (< 3.11)."""
    if not hasattr(sqlite3.Connection, "setlimit"):
        return False
    real_connect = sqlite3.connect
    category = sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)
        conn.setlimit(category, limit)
        return conn

    sqlite3.connect = connect  # type: ignore[assignment]
    return True


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60] or "x"


def _spread(values: List[Any], count: int) -> List[Any]:
    """Up to ``count`` values spaced evenly through the list, ends included."""
    if len(values) <= count:
        return list(values)
    if count <= 1:
        return values[:1]
    step = (len(values) - 1) / (count - 1)
    return [values[round(index * step)] for index in range(count)]


def build_requests(
    dashboard: Any, db_path: Path, sample: int
) -> List[Tuple[str, Callable[[], Any]]]:
    """(file name, call) pairs covering every read endpoint, chosen from the
    database so two dumps of the same file ask the same questions."""
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        decks = [
            str(row[0])
            for row in conn.execute(
                "SELECT COALESCE(deck_name, '(unknown)') FROM participants WHERE role = 'player' "
                "GROUP BY 1 ORDER BY COUNT(*) DESC, 1"
            )
        ]
        formats = [
            str(row[0])
            for row in conn.execute(
                "SELECT COALESCE(format, '(unknown)') FROM matches GROUP BY 1 "
                "ORDER BY COUNT(*) DESC, 1"
            )
        ]
        games = [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM games ORDER BY COALESCE(started_at, ended_at), id"
            )
        ]
        opponents = [
            str(row[0])
            for row in conn.execute(
                "SELECT display_name FROM participants WHERE role = 'opponent' "
                "AND COALESCE(display_name, '') != '' GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT ?",
                (sample,),
            )
        ]
        cards = [
            str(row[0])
            for row in conn.execute(
                "SELECT display_name FROM game_card_summary GROUP BY 1 "
                "ORDER BY SUM(COALESCE(played_count, 0)) DESC, 1 LIMIT ?",
                (sample,),
            )
        ]
        try:
            season = conn.execute("SELECT MAX(season_ordinal) FROM rank_snapshots").fetchone()[0]
        except sqlite3.Error:
            season = None
    finally:
        conn.close()

    d = dashboard
    top_deck = decks[0] if decks else None
    top_format = formats[0] if formats else None
    requests: List[Tuple[str, Callable[[], Any]]] = [
        ("snapshot", lambda: d.dashboard_snapshot(db_path)),
        ("snapshot.days-7", lambda: d.dashboard_snapshot(db_path, days=7)),
        ("snapshot.days-30", lambda: d.dashboard_snapshot(db_path, days=30)),
        ("snapshot.trend-all", lambda: d.dashboard_snapshot(db_path, trend_days=0)),
        ("snapshot.trend-100-games", lambda: d.dashboard_snapshot(db_path, trend_games=100)),
        ("games", lambda: d.all_games(db_path)),
        ("games.days-30", lambda: d.all_games(db_path, days=30)),
        ("opponents", lambda: d.opponents_list(db_path)),
        ("audit", lambda: d.audit_report(db_path)),
    ]
    if top_deck:
        requests.append(
            ("snapshot.deck", lambda: d.dashboard_snapshot(db_path, deck=top_deck)),
        )
        requests.append(("games.deck", lambda: d.all_games(db_path, deck=top_deck)))
        requests.append(("search.deck", lambda: d.global_search(db_path, top_deck[:4], 8)))
    if top_format:
        requests.append(("snapshot.format", lambda: d.dashboard_snapshot(db_path, fmt=top_format)))
        requests.append(("games.format", lambda: d.all_games(db_path, fmt=top_format)))
    if season is not None:
        requests.append(
            ("snapshot.season", lambda: d.dashboard_snapshot(db_path, season=int(season)))
        )
    # The most-played decks carry the cost; the least-played ones the edge cases.
    for name in list(dict.fromkeys(decks[:sample] + decks[-max(1, sample // 3) :])):
        requests.append((f"deck.{_slug(name)}", lambda name=name: d.deck_detail(db_path, name)))
    if top_deck and top_format:
        requests.append(
            ("deck.format", lambda: d.deck_detail(db_path, top_deck, fmt=top_format)),
        )
    for game_id in _spread(games, sample):
        requests.append(
            (f"game.{_slug(game_id)}", lambda game_id=game_id: d.game_detail(db_path, game_id))
        )
    for name in opponents:
        requests.append(
            (f"opponent.{_slug(name)}", lambda name=name: d.opponent_detail(db_path, name))
        )
    for name in cards:
        requests.append((f"card.{_slug(name)}", lambda name=name: d.card_detail(db_path, name)))
        requests.append(
            (f"cards.{_slug(name)}", lambda name=name: d.search_cards(db_path, name[:5], 8))
        )
    # Distinct names can share a slug; keep every request.
    seen: Dict[str, int] = {}
    unique: List[Tuple[str, Callable[[], Any]]] = []
    for name, call in requests:
        seen[name] = seen.get(name, 0) + 1
        unique.append((name if seen[name] == 1 else f"{name}.{seen[name]}", call))
    return unique


def dump(db_path: Path, out_dir: Path, sample: int, limit: int, src: Optional[Path]) -> int:
    if src is not None:
        sys.path.insert(0, str(src.resolve()))
    else:
        sys.path.insert(0, str(ROOT / "src"))
    from mtga_tracker import dashboard  # noqa: E402

    loaded_from = Path(dashboard.__file__).resolve()
    expected = (src.resolve() if src is not None else ROOT / "src").resolve()
    if expected not in loaded_from.parents:
        print(f"error: mtga_tracker loaded from {loaded_from}, not {expected}", file=sys.stderr)
        return 2
    print(f"code: {expected}")
    if limit:
        if pin_sql_variable_limit(limit):
            print(f"SQLite bound-parameter limit pinned to {limit:,}")
        else:
            print("warning: this Python cannot pin SQLite limits (needs 3.11+)", file=sys.stderr)
    db_path = db_path.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        stale.unlink()

    timings: Dict[str, Dict[str, Any]] = {}
    errors = 0
    for name, call in build_requests(dashboard, db_path, sample):
        started = time.perf_counter()
        try:
            payload = call()
        except Exception as exc:  # noqa: BLE001 - the failure is the finding
            payload = {"__error__": f"{type(exc).__name__}: {exc}"}
            errors += 1
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        size = len(dashboard.render_snapshot_json(payload))
        (out_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        timings[name] = {"ms": round(elapsed_ms, 1), "bytes": size}
        if isinstance(payload, dict) and "__error__" in payload:
            timings[name]["error"] = payload["__error__"]
    (out_dir / TIMINGS_FILE).write_text(json.dumps(timings, indent=1), encoding="utf-8")

    print(f"\n{'request':<44}{'ms':>9}{'KB':>10}")
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for name, entry in timings.items():
        groups.setdefault(name.split(".", 1)[0], []).append(entry)
        if name.split(".", 1)[0] in ("snapshot", "games", "opponents", "audit") or "error" in entry:
            note = f"  {entry['error']}" if "error" in entry else ""
            print(f"{name:<44}{entry['ms']:>9.0f}{entry['bytes'] / 1024:>10.0f}{note}")
    for group in ("deck", "game", "opponent", "card", "cards"):
        entries = groups.get(group)
        if entries:
            worst = max(entry["ms"] for entry in entries)
            mean = sum(entry["ms"] for entry in entries) / len(entries)
            print(
                f"{group + ' (' + str(len(entries)) + ' requests)':<44}{mean:>9.0f}  mean, {worst:.0f} worst"
            )
    print(f"\n{len(timings)} payloads in {out_dir}" + (f", {errors} FAILED" if errors else ""))
    return 1 if errors else 0


def _differences(left: Any, right: Any, path: str = "") -> Iterator[str]:
    if type(left) is not type(right):
        yield f"{path or '.'}: {type(left).__name__} {left!r:.80} != {type(right).__name__} {right!r:.80}"
    elif isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                yield f"{path}.{key}: only in the second"
            elif key not in right:
                yield f"{path}.{key}: only in the first"
            else:
                yield from _differences(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list):
        if len(left) != len(right):
            yield f"{path or '.'}: {len(left)} items != {len(right)} items"
        for index, (a, b) in enumerate(zip(left, right)):
            yield from _differences(a, b, f"{path}[{index}]")
    elif left != right:
        yield f"{path or '.'}: {left!r:.80} != {right!r:.80}"


def diff(first: Path, second: Path, show: int) -> int:
    names_first = {path.name for path in first.glob("*.json")} - {TIMINGS_FILE}
    names_second = {path.name for path in second.glob("*.json")} - {TIMINGS_FILE}
    if not names_first or not names_second:
        print("error: a dump directory holds no payloads", file=sys.stderr)
        return 2
    changed = 0
    for name in sorted(names_first ^ names_second):
        changed += 1
        print(f"{name}: only in the {'first' if name in names_first else 'second'}")
    for name in sorted(names_first & names_second):
        left = json.loads((first / name).read_text(encoding="utf-8"))
        right = json.loads((second / name).read_text(encoding="utf-8"))
        found = list(_differences(left, right))
        if found:
            changed += 1
            print(f"{name}: {len(found)} difference(s)")
            for line in found[:show]:
                print(f"    {line}")
    same = len(names_first & names_second) - (changed - len(names_first ^ names_second))
    print(f"{same} identical, {changed} differ")
    try:
        before = json.loads((first / TIMINGS_FILE).read_text(encoding="utf-8"))
        after = json.loads((second / TIMINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1 if changed else 0
    print(f"\n{'request':<34}{'first ms':>10}{'second ms':>11}{'first KB':>10}{'second KB':>11}")
    for name in ("snapshot", "games", "opponents"):
        if name in before and name in after:
            print(
                f"{name:<34}{before[name]['ms']:>10.0f}{after[name]['ms']:>11.0f}"
                f"{before[name]['bytes'] / 1024:>10.0f}{after[name]['bytes'] / 1024:>11.0f}"
            )
    for group in ("deck", "game", "opponent", "card"):
        a = [entry["ms"] for name, entry in before.items() if name.startswith(group + ".")]
        b = [entry["ms"] for name, entry in after.items() if name.startswith(group + ".")]
        if a and b:
            print(f"{group + ' (worst)':<34}{max(a):>10.0f}{max(b):>11.0f}")
    return 1 if changed else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    dump_parser = commands.add_parser("dump", help="write every payload for a database")
    dump_parser.add_argument("--db", type=Path, required=True, help="a COPY of a tracker database")
    dump_parser.add_argument("--out", type=Path, required=True, help="directory for the payloads")
    dump_parser.add_argument(
        "--sample", type=int, default=12, help="decks, games, opponents and cards to request"
    )
    dump_parser.add_argument(
        "--sql-variable-limit",
        type=int,
        default=WINDOWS_SQL_VARIABLE_LIMIT,
        help="SQLite bound-parameter limit to pin (0 = this machine's own)",
    )
    dump_parser.add_argument(
        "--src", type=Path, default=None, help="another checkout's src directory to run"
    )
    diff_parser = commands.add_parser("diff", help="compare two dumps")
    diff_parser.add_argument("first", type=Path)
    diff_parser.add_argument("second", type=Path)
    diff_parser.add_argument("--show", type=int, default=8, help="differences to print per file")
    args = parser.parse_args(argv)
    if args.command == "dump":
        return dump(args.db, args.out, args.sample, args.sql_variable_limit, args.src)
    return diff(args.first, args.second, args.show)


if __name__ == "__main__":
    raise SystemExit(main())
