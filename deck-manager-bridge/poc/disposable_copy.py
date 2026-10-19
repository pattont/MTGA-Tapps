"""Prepare a disposable Arena duplicate; --execute explicitly enables its create/delete test.

Never removes the original deck. An uncertain write stops without retry or deletion.
This tests native services, not reconstruction of a deck from its disk archive.
"""

import argparse
import json
import os
from pathlib import Path
import sys
from threading import Timer
import time
import uuid

from capture import documents


def persist(path, value):
    """Exclusive, private, fsynced snapshot with a read-back check before further calls."""
    encoded = json.dumps(value, indent=2) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    if os.name != "nt":
        # Windows cannot open a directory as a file descriptor; NTFS journals the new
        # directory entry itself, so only POSIX needs the explicit directory fsync.
        directory_fd = os.open(Path(path).parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    restored = json.loads(Path(path).read_text(encoding="utf-8"))
    if restored != value:
        raise ValueError("Snapshot read-back differs; stop before further native calls.")
    return restored


def await_phase(exports, desired, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = exports.pollcopy()
        if result["phase"] == desired:
            return result
        time.sleep(0.2)
    raise TimeoutError("Native result is uncertain; stop without retrying or deleting anything.")


def experiment(exports, output, source_id=None, execute=False):
    """The disk check is a mandatory boundary between create and test-copy deletion."""
    report = exports.cache()
    decks = documents(report)
    if not decks:
        raise ValueError("No complete ordinary cached decks are available.")
    allowed = {deck["metadata"]["arena_deck_id"] for deck in decks}
    source_id = source_id or decks[0]["metadata"]["arena_deck_id"]
    if source_id not in allowed:
        raise ValueError("Choose a complete ordinary deck from this cache.")
    operation_id = str(uuid.uuid4())
    persist(output / "01-cache.json", report)
    prepared = exports.preparecopy(source_id, operation_id)
    source_report = dict(report, decks=[prepared["source_snapshot"]])
    documents(source_report)
    persist(output / "02-source.json", source_report)
    persist(output / "03-prepared.json", prepared)
    if not execute:
        result = {"phase": "dry_run_complete", "native_writes_executed": False}
        persist(output / "04-result.json", result)
        return result
    # Persist intent first. Any exception/timeout stops; no create retries.
    persist(output / "04-create-intent.json", {"operation_id": operation_id})
    exports.createcopy()
    created = await_phase(exports, "created_verified")
    created_report = dict(report, decks=[created["created_snapshot"]])
    documents(created_report)
    # Read the actual saved identity back from disk, not the proposed draft ID.
    archived = persist(output / "05-created.json", created_report)
    persist(output / "06-delete-test-copy-intent.json", {"operation_id": operation_id})
    exports.deletecopy(archived["decks"][0])
    result = await_phase(exports, "complete")
    persist(output / "07-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument(
        "--output", required=True, type=Path, help="New private experiment directory"
    )
    parser.add_argument("--source", type=uuid.UUID, help="Optional complete ordinary deck identity")
    parser.add_argument(
        "--execute", action="store_true", help="Create and remove only the new test copy"
    )
    args = parser.parse_args()
    if args.pid <= 0 or args.output.exists():
        parser.error("Use a positive Arena PID and a new output directory.")
    if sys.platform != "darwin":
        parser.error("This experiment has only been validated on macOS Unity 6 IL2CPP.")
    try:
        import frida
    except ImportError:
        parser.error("Install the isolated experiment requirements first.")
    session = timer = script = None
    try:
        device = frida.get_local_device()
        if {p.pid: p.name for p in device.enumerate_processes()}.get(args.pid) != "MTGA":
            raise ValueError("The selected PID is not Arena.")
        args.output.mkdir(mode=0o700)
        session = device.attach(args.pid)
        timer = Timer(120, session.detach)
        timer.daemon = True
        timer.start()
        script = session.create_script(
            Path(__file__).with_name("probe.js").read_text(encoding="utf-8")
        )
        script.load()
        result = experiment(
            script.exports_sync,
            args.output,
            str(args.source) if args.source else None,
            args.execute,
        )
        print(
            "Disposable copy created, archived, removed and roster verified."
            if result["phase"] == "complete"
            else "Dry run verified and archived an independent draft; no native deck writes executed."
        )
        return 0
    except Exception as exc:
        print(
            f"Experiment stopped: {exc}. Inspect the private journal before any retry.",
            file=sys.stderr,
        )
        return 1
    finally:
        if script:
            try:
                script.exports_sync.releasecopy()  # Releases handles only; never deletes a deck.
            except Exception:
                pass
        if timer:
            timer.cancel()
        if session:
            try:
                session.detach()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
