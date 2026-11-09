# Raw log archive (a game's original Player.log entries)

Status: planned, not built. Decided 2026-11-08 during the performance pass; to be
revisited before implementation.

## Why

Nothing keeps a game's original Arena log entries. `raw_game_payloads`, despite
its name, archives only unrecognised and connection-state entries for parser
diagnostics and prunes them after 30 days; the GRE game-state messages that
every stat and replay row is derived from are never stored. Arena itself keeps
only `Player.log` and `Player-prev.log`, so two Arena launches after a game its
source is gone for good.

Every historical repair so far (date order, revealed cards, turn timings,
event reassignment) had to work from the printed console text and the replay
rows, which only hold what the tracker of the day knew to extract. With the
original entries on hand, a future fix could re-derive a game exactly, and a
user's bug report could be reproduced from their own data instead of a
hand-made fixture.

Travis's framing: storing the originals is a better use of the space than
storing the console text twice (`console_logs` plus printed `game_events`),
which is the duplication the storage review found.

## Measured cost (2026-11-08, 10 games from a 22 MB Player-prev.log)

| | Per game |
| --- | --- |
| GRE / match-service lines, raw | ~0.8 MB |
| The same, zlib level 6 | ~215 KB (10.3x) |
| The same, zlib level 9 | ~205 KB (10.8x) |
| What a game costs in the database today, everything included | ~128 KB |

So an unbounded archive roughly triples database growth: the 1,256-game
database measured at 160 MB would carry about 250 MB of archived log. Bounded,
it is modest: 200 games is about 40 MB.

## Ground rules

- **Bounded, and visible.** A retention window the user can see (Settings shows
  the space used), oldest games pruned first. Default to be decided; the
  working proposal is the newer of the last 200 games or 90 days. Never
  "forever": a tracker that quietly grows by a gigabyte is the complaint this
  whole pass guards against.
- **Exact bytes.** Store each game's entries as they were read, compressed with
  the existing `payload_codec` (zlib), after the same privacy scrub
  `log_sanitize` applies to `raw_game_payloads`. No reformatting, no JSON
  re-serialisation: the point is to be able to replay the original.
- **Never on the live path's critical section.** Capture appends to a per-game
  buffer as entries are routed and writes the compressed blob once at game
  end (or in bounded chunks for very long games), the way replay capture
  batches rows. A failure drops the archive for that game, never the game.
- **Untracked matches** (mid-game attach, Midweek Magic, bot matches) are not
  archived, like every other history.

## Design sketch

- Table `game_raw_log (game_id TEXT PRIMARY KEY, session_id, started_at,
  entry_count INTEGER, raw_bytes INTEGER, payload BLOB)`; `payload` is the zlib
  stream of the game's entries joined by newlines, exactly as read.
- Capture point: `tracker_lifecycle._process_new_events` already sees every
  `LogEntry` with its body; between game start and the summary, append the
  body to `GameState`'s buffer. Game end writes the row inside the existing
  end-of-game persistence.
- Pruning: at startup maintenance, delete rows beyond the retention window;
  report the count. Uses a `maintenance_state` watermark like the other
  passes so it stays cheap.
- Reading: `python -m mtga_tracker.raw_log_dump <game_id>` prints the entries
  (the `payload_dump` pattern), and `scripts/export_replay_fixture.py` can
  grow a flag to export the archived entries anonymised, so a reported game
  becomes a parser fixture.
- Backups: a full `.tappsbackup` carries the table (it is the game's source of
  truth); merge skips it like `raw_game_payloads` unless the games it belongs
  to are merged. Reset deletes it (`RESET_TABLES`). Settings shows its size
  and a "Clear archive" action.
- Database health (`db_audit`) reports games with and without an archive and
  the archive's total size.

## Open questions to settle before building

- Default retention: by count, by age, or the newer of the two?
- Should the archive be on by default, or opt-in from Settings? (Default on
  with a visible bound is the current leaning.)
- Whether to also keep the non-GRE entries of the game window (deck
  submission, match room, rank updates) — they are a small fraction and make
  the archive self-contained.
- Whether `console_logs` can then become a rolling window, since the
  archive plus `game_events` would hold everything it holds.
