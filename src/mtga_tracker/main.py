"""Main entry point for MTGA Tracker."""

import sys
import argparse
import json
from pathlib import Path

# #region agent log
try:
    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:9","message":"Module imported","data":{"sys_path":sys.path[:3],"python_version":sys.version},"timestamp":__import__('time').time()*1000})+'\n')
except: pass
# #endregion

from .tracker import CardTracker
from .log_parser import MTGALogParser

# #region agent log
try:
    with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"main.py:15","message":"Imports successful","data":{},"timestamp":__import__('time').time()*1000})+'\n')
except: pass
# #endregion


def main():
    """Main entry point for the MTGA Tracker application."""
    # #region agent log
    try:
        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:18","message":"main() called","data":{"argv":sys.argv},"timestamp":__import__('time').time()*1000})+'\n')
    except: pass
    # #endregion
    parser = argparse.ArgumentParser(
        description="Track cards played in Magic: The Gathering Arena",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                   # Auto-detect everything
  %(prog)s --log-path /path/to/Player.log    # Use specific log file
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
        version="MTGA Tracker 0.5.0",
    )

    args = parser.parse_args()
    # #region agent log
    try:
        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:38","message":"Args parsed","data":{"log_path":args.log_path},"timestamp":__import__('time').time()*1000})+'\n')
    except: pass
    # #endregion

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
        # #region agent log
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:50","message":"Log parser created","data":{},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion

        # Create and start tracker
        tracker = CardTracker(log_parser)
        # #region agent log
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:55","message":"Tracker created, starting","data":{},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        tracker.start()

    except FileNotFoundError as e:
        # #region agent log
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"main.py:60","message":"FileNotFoundError","data":{"error":str(e)},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        print(f"Error: {e}", file=sys.stderr)
        print("\nMake sure MTGA is installed and has been run at least once.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        # #region agent log
        try:
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:66","message":"KeyboardInterrupt","data":{},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        # #region agent log
        try:
            import traceback as tb
            with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"main.py:72","message":"Unexpected error","data":{"error":str(e),"traceback":tb.format_exc()},"timestamp":__import__('time').time()*1000})+'\n')
        except: pass
        # #endregion
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # #region agent log
    try:
        with open('/Users/travispatton/Repo/MTGA-Tapps/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"main.py:82","message":"__main__ block executed","data":{"__file__":__file__},"timestamp":__import__('time').time()*1000})+'\n')
    except: pass
    # #endregion
    main()
