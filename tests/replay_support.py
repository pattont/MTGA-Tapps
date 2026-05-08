"""Helpers for replaying trimmed MTGA log snippets through the tracker."""


def replay_lines(tracker, lines):
    """Replay lines and flush the deferred game summary like the live tail loop."""
    for line in lines:
        tracker._process_line(line)
    if tracker.game_state.match_complete and tracker._pending_game_summary:
        tracker._print_game_summary()
        tracker._pending_game_summary = False
    return tracker
