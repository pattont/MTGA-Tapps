# Deprecated debug scripts

Early-development debug relics, moved out of the repo root in August 2026.
They are **not maintained, not collected by pytest, and likely broken** —
their `from src.mtga_tracker...` imports predate the packaged layout and
assume repo-root execution.

Kept for reference only:

- `debug_log.py` — dump raw MTGA log contents while developing the parser.
- `debug_seats.py` — probe seat-ID / life-total payload structure.
- `simulate_game.py` — simulate tracker console output without Arena running.

If one of these turns out to be useful again, rewrite it against the current
`mtga_tracker` package (and add a real test) instead of resurrecting it as-is.
