"""Main entry point for MTGA Tracker."""

import sys
import argparse
from pathlib import Path

from .tracker import CardTracker
from .log_parser import MTGALogParser


def main():
    """Main entry point for the MTGA Tracker application."""
    parser = argparse.ArgumentParser(
        description="Track cards played in Magic: The Gathering Arena",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Auto-detect MTGA log file
  %(prog)s --log-path /path/to/Player.log  # Use specific log file
  %(prog)s --help                   # Show this help message
        """,
    )

    parser.add_argument(
        "--log-path",
        type=str,
        help="Path to MTGA Player.log file (auto-detected if not specified)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="MTGA Tracker 0.1.0",
    )

    args = parser.parse_args()

    try:
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
