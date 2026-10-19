"""Explicit, attach-only Arena IL2CPP probe; never launches or restarts Arena."""

import argparse
import json
import os
from pathlib import Path
import sys
from threading import Timer
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="Running Arena process ID")
    parser.add_argument("--output", type=Path, required=True, help="New local JSON report")
    parser.add_argument(
        "--mode", choices=("inspect", "cache", "service", "refresh", "folder"), default="inspect"
    )
    parser.add_argument(
        "--show-seconds", type=int, default=15, help="Temporary folder display time (5–60)"
    )
    args = parser.parse_args()
    if args.pid <= 0:
        parser.error("PID must be positive.")
    if not 5 <= args.show_seconds <= 60:
        parser.error("Display time must be between 5 and 60 seconds.")
    if args.output.exists():
        parser.error("Choose a new report file; existing files are not overwritten.")
    try:
        import frida
    except ImportError:
        parser.error("Install this experiment's requirements in an isolated virtualenv first.")
    session = None
    timer = None
    script = None
    folder_cleanup_needed = False
    try:
        device = frida.get_local_device()
        processes = {p.pid: p.name for p in device.enumerate_processes()}
        if processes.get(args.pid) not in ("MTGA", "MTGA.exe"):
            raise RuntimeError("The selected PID is not the running MTGA process.")
        session = device.attach(args.pid)
        duration = (
            60
            if args.mode == "refresh"
            else 30 + (args.show_seconds if args.mode == "folder" else 0)
        )
        timer = Timer(duration, session.detach)
        timer.daemon = True
        timer.start()
        script = session.create_script(
            Path(__file__).with_name("probe.js").read_text(encoding="utf-8")
        )
        script.load()
        if args.mode == "folder":
            folder_cleanup_needed = True
        report = getattr(script.exports_sync, args.mode)()
        if args.mode == "folder":
            print(
                "Temporary collection section shown. It will be removed automatically.", flush=True
            )
            time.sleep(args.show_seconds)
            report["cleanup"] = script.exports_sync.clearfolder()
            folder_cleanup_needed = False
            report["cleanup"].update(script.exports_sync.folderstatus())
            if report["cleanup"]["temporary_sections_remaining"]:
                raise RuntimeError("The temporary section is still present after cleanup.")
        report["frida_version"] = frida.__version__
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
        if args.mode == "inspect":
            print(f"Inspected {len(report['classes'])} deck/UI classes; no deck changes made.")
        elif args.mode == "cache":
            print(
                f"Read {len(report['decks'])} cached decks on Unity's thread; no deck changes made."
            )
        elif args.mode == "service":
            print("Invoked GetFullDeck through Arena's deck service; no deck changes made.")
        elif args.mode == "refresh":
            print("Arena roster refresh succeeded and was captured; no deck changes made.")
        else:
            print("Temporary native collection section created and removed; no deck changes made.")
        return 0
    except Exception as exc:
        print(f"Probe failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if folder_cleanup_needed and script:
            try:
                script.exports_sync.clearfolder()
            except Exception:
                print(
                    "Could not confirm temporary UI cleanup. Leaving the Decks screen removes scene objects.",
                    file=sys.stderr,
                )
        if timer:
            timer.cancel()
        if session:
            try:
                session.detach()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
