"""Main entry point for MTGA Tracker."""

import sys
import argparse
from pathlib import Path

from .tracker import CardTracker, GameState
from .log_parser import MTGALogParser


def main():
    """Main entry point for the MTGA Tracker application."""
    parser = argparse.ArgumentParser(
        description="Track cards played in Magic: The Gathering Arena",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Auto-detect everything
  %(prog)s --seat 1                 # Force your seat to 1
  %(prog)s --seat 2                 # Force your seat to 2
  %(prog)s --swap                   # Swap player/opponent if detection is wrong
  %(prog)s --log-path /path/to/Player.log  # Use specific log file
        """,
    )

    parser.add_argument(
        "--log-path",
        type=str,
        help="Path to MTGA Player.log file (auto-detected if not specified)",
    )

    parser.add_argument(
        "--seat",
        type=int,
        choices=[1, 2],
        help="Force your seat ID (1 or 2) instead of auto-detecting",
    )

    parser.add_argument(
        "--swap",
        action="store_true",
        help="Swap player/opponent if auto-detection is backwards",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="MTGA Tracker 0.4.0",
    )

    args = parser.parse_args()

    try:
        # Handle seat override
        if args.seat:
            GameState.MANUAL_PLAYER_SEAT = args.seat
            print(f"🎮 Manual seat override: You are Seat {args.seat}")
        elif args.swap:
            # Will swap after first detection
            GameState.MANUAL_PLAYER_SEAT = None
            print("🔄 Swap mode enabled - will swap player/opponent after detection")

        # Create log parser
        if args.log_path:
            log_path = Path(args.log_path)
            if not log_path.exists():
                print(f"Error: Log file not found at {log_path}", file=sys.stderr)
                sys.exit(1)
            log_parser = MTGALogParser(str(log_path))
        else:
            log_parser = MTGALogParser()

        # Create and start tracker
        tracker = CardTracker(log_parser)

        # Handle swap mode
        if args.swap:
            tracker.swap_players = True
        else:
            tracker.swap_players = False

        tracker.start()

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("\nMake sure MTGA is installed and has been run at least once.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
