"""Capture, detach, reconstruct from disk, and optionally test one restored duplicate."""

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
from threading import Timer
import time
import uuid

from capture import documents
from disposable_copy import await_phase, persist


def validate_archive(archive):
    if (
        not isinstance(archive, dict)
        or archive.get("schema") != 1
        or archive.get("archive_kind") != "arena_typed_model_poc"
    ):
        raise ValueError("Unsupported typed deck archive.")
    report = dict(archive, decks=[archive["source_snapshot"]])
    if len(documents(report)) != 1:
        raise ValueError("The archive must contain one complete non-net deck.")
    for key in ("model_json", "summary_json"):
        text = archive.get(key)
        if not isinstance(text, str) or len(text) > 20_000:
            raise ValueError("Invalid bounded model JSON.")
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("The typed model must be a JSON object.")

        def check(item):
            if isinstance(item, dict):
                if "$type" in item:
                    raise ValueError("Archives cannot select arbitrary deserialization types.")
                for nested in item.values():
                    check(nested)
            elif isinstance(item, list):
                for nested in item:
                    check(nested)

        check(value)
    return archive


def capture_archive(exports, output, source_id=None):
    report = exports.cache()
    decks = documents(report)
    if not decks:
        raise ValueError("No complete ordinary deck is available.")
    source_id = source_id or decks[0]["metadata"]["arena_deck_id"]
    if source_id not in {d["metadata"]["arena_deck_id"] for d in decks}:
        raise ValueError("Choose a complete ordinary cached deck.")
    persist(output / "01-before.json", report)
    archive = validate_archive(exports.archivemodel(source_id))
    persist(output / "02-disk-archive.json", archive)
    return output / "02-disk-archive.json"


def load_archive(path):
    encoded = path.read_bytes()
    if len(encoded) > 2_000_000:
        raise ValueError("Archive is too large.")
    return validate_archive(json.loads(encoded)), hashlib.sha256(encoded).hexdigest()


def wait_for_decks(exports):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if exports.writeready():
            return
        time.sleep(0.2)
    raise TimeoutError("Decks screen did not finish rebuilding; test copy retained.")


def restore_experiment(exports, archive_path, output, execute=False):
    # Called only after the capture attachment has ended. Everything used for
    # reconstruction comes from this read, never an in-memory native clone.
    archive, digest = load_archive(archive_path)
    persist(output / "03-loaded-archive.json", {"sha256": digest})
    prepared = exports.preparerestore(archive, str(uuid.uuid4()))
    if prepared.get("reconstructed_from_disk") is not True:
        raise ValueError("The adapter did not confirm disk reconstruction.")
    persist(output / "04-reconstructed.json", prepared)
    if not execute:
        result = {"phase": "dry_run_complete", "native_writes_executed": False}
        persist(output / "05-result.json", result)
        return result
    persist(output / "05-create-intent.json", {"operation_id": prepared["operation_id"]})
    exports.createcopy()
    created = await_phase(exports, "created_verified")
    report = dict(archive, decks=[created["created_snapshot"]])
    documents(report)
    persist(output / "06-created.json", report)
    return verify_and_cleanup(exports, archive, prepared, output)


def verify_and_cleanup(exports, archive, prepared, output, execute=True):
    verified = exports.verifyrestoredcopy()
    fetched = dict(archive, decks=[verified["fetched_snapshot"]])
    documents(fetched)
    durable = persist(output / "07-fetched.json", fetched)
    persist(
        output / "08-verification.json",
        {k: v for k, v in verified.items() if k != "fetched_snapshot"},
    )
    if not execute:
        return {"phase": "verification_complete", "native_writes_executed": False}
    wait_for_decks(exports)
    persist(output / "09-delete-test-copy-intent.json", {"operation_id": prepared["operation_id"]})
    # Only the known new copy may be removed; even a fidelity failure retains
    # its fetched data durably before cleanup. Never delete the original.
    exports.deletecopy(durable["decks"][0])
    result = await_phase(exports, "complete")
    result.update(
        reconstructed_from_disk=True,
        native_disk_restore_proven=verified["restored_from_disk_verified"],
        full_deck_promise_successful=verified["full_deck_promise_successful"],
        native_transfers_proven=False,
    )
    persist(output / "10-result.json", result)
    return result


def resume_experiment(exports, original, output, execute=False):
    """Recover only the known created identity; there is no create path here."""
    archive, digest = load_archive(original / "02-disk-archive.json")
    if (
        digest
        != json.loads((original / "03-loaded-archive.json").read_text(encoding="utf-8"))["sha256"]
    ):
        raise ValueError("Original archive changed; recovery stopped.")
    before = json.loads((original / "01-before.json").read_text(encoding="utf-8"))
    documents(before)
    prepared = json.loads((original / "04-reconstructed.json").read_text(encoding="utf-8"))
    created_report = json.loads((original / "06-created.json").read_text(encoding="utf-8"))
    if len(documents(created_report)) != 1 or len(created_report["decks"]) != 1:
        raise ValueError("Recovery requires the recorded single created copy.")
    created = created_report["decks"][0]
    before_ids = [deck["arena_id"] for deck in before["decks"]]
    if (
        created["arena_id"] in before_ids
        or created["arena_id"] == archive["source_snapshot"]["arena_id"]
    ):
        raise ValueError("Recovery cannot target an original deck.")
    if (
        prepared["operation_id"]
        != json.loads((original / "05-create-intent.json").read_text(encoding="utf-8"))[
            "operation_id"
        ]
    ):
        raise ValueError("Recovery operation identity differs.")
    owned = exports.adoptrestoredcopy(archive, prepared, created, before_ids)
    persist(output / "04-recovered-copy.json", owned)
    return verify_and_cleanup(exports, archive, prepared, output, execute)


@contextmanager
def attached_probe(device, pid):
    session = device.attach(pid)
    timer = Timer(180, session.detach)
    timer.daemon = True
    script = None
    try:
        timer.start()
        script = session.create_script(
            Path(__file__).with_name("probe.js").read_text(encoding="utf-8")
        )
        script.load()
        yield script.exports_sync
    finally:
        if script:
            try:
                script.exports_sync.releasecopy()
            except Exception:
                pass
        timer.cancel()
        try:
            session.detach()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument(
        "--output", required=True, type=Path, help="New private experiment directory"
    )
    parser.add_argument("--source", type=uuid.UUID)
    parser.add_argument(
        "--resume",
        type=Path,
        help="Recover the existing copy from this private journal; never creates another",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Create, verify and remove the restored test duplicate",
    )
    args = parser.parse_args()
    if sys.platform != "darwin" or args.pid <= 0 or args.output.exists():
        parser.error("Use macOS, a positive Arena PID, and a new output directory.")
    try:
        import frida
    except ImportError:
        parser.error("Install the isolated POC requirements first.")
    try:
        device = frida.get_local_device()
        if {p.pid: p.name for p in device.enumerate_processes()}.get(args.pid) != "MTGA":
            raise ValueError("The selected process is not Arena.")
        args.output.mkdir(mode=0o700)
        if args.resume:
            with attached_probe(device, args.pid) as exports:
                result = resume_experiment(exports, args.resume, args.output, args.execute)
            if not args.execute:
                print("Existing copy fetched and archived; no deck writes.")
            elif result["native_disk_restore_proven"]:
                print("Existing disk-restored copy verified and removed.")
            else:
                raise ValueError(
                    "Restored data differed; test copy archived/removed, originals preserved."
                )
            return 0
        with attached_probe(device, args.pid) as exports:
            path = capture_archive(exports, args.output, str(args.source) if args.source else None)
        print(
            "Archive persisted; capture attachment ended. Reconstructing in a fresh attachment.",
            flush=True,
        )
        with attached_probe(device, args.pid) as exports:
            result = restore_experiment(exports, path, args.output, args.execute)
        if not args.execute:
            print("Disk reconstruction dry run verified; no Arena deck writes.")
        elif result["native_disk_restore_proven"]:
            print("Disk-restored duplicate verified and removed; original roster preserved.")
        else:
            raise ValueError(
                "Restored data differed; test copy archived/removed, originals preserved."
            )
        return 0
    except Exception as exc:
        print(
            f"Restore test stopped: {exc}. Inspect the journal before any write retry.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
