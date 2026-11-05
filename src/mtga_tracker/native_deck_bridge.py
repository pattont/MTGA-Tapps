"""Explicit, bounded attachment to Arena's native deck services."""

from __future__ import annotations

import time
from contextlib import contextmanager
import hashlib
import importlib.util
from pathlib import Path
import sys
from threading import Timer

from .deck_manager import DeckManagerError
from .paths import native_deck_platform_supported


def availability():
    if not native_deck_platform_supported():
        return False, "Direct transfers support Arena on Apple Silicon Macs and 64-bit Windows."
    # Locate Frida without importing it: the import loads its native library
    # into the tracker for good, and status is polled by pages that may never
    # attach. The attach itself imports it.
    if "frida" not in sys.modules and importlib.util.find_spec("frida") is None:
        return False, "The native deck adapter is missing from this installation."
    return True, "Open Arena’s Decks screen, then load its decks."


# Arena's process: "MTGA" on macOS, "MTGA.exe" on Windows.
ARENA_PROCESS_NAMES = ("MTGA", "MTGA.exe")


def account_key(account_id):
    if not isinstance(account_id, str) or not account_id or len(account_id) > 256:
        raise DeckManagerError("Arena account identity is unavailable.")
    return hashlib.sha256(("tapps-arena-account:" + account_id).encode()).hexdigest()


class ArenaBridge:
    def __init__(self, exports):
        self.exports = exports
        self.info = exports.open()
        self.account_id = self.info["account_id"]
        self.account_key = account_key(self.account_id)
        # Set once a create/delete is sent, so the Decks screen is redrawn on close.
        self.wrote = False
        # The last deck this attachment created, selected by that redraw.
        self.created = None

    def roster(self, refresh=True):
        """Arena's deck list. ``refresh=False`` (a plain load) reads the copy Arena
        already holds instead of asking its server first; checks around writes
        keep the server refresh."""
        report = self.exports.roster(self.account_id, bool(refresh))
        if report.get("account_id") != self.account_id or (
            refresh and report.get("roster_refreshed") is not True
        ):
            raise DeckManagerError("Arena account changed or roster refresh failed.")
        return report

    def archive(self, ids):
        return self.exports.archive(self.account_id, ids)

    def fetch(self, arena_id):
        return self.exports.fetchdeck(self.account_id, arena_id)

    def create(self, archive, arena_id):
        self.wrote = True
        result = self.exports.create(self.account_id, archive, arena_id)
        self.created = arena_id
        return result

    def prepare_create(self, archive, arena_id):
        try:
            return self.exports.preparecreate(self.account_id, archive, arena_id)
        except Exception as exc:
            raise DeckManagerError(
                "Arena could not prepare this backup. No deck was created; your saved deck remains."
            ) from exc

    def create_prepared(self, arena_id):
        self.wrote = True
        result = self.exports.createprepared(self.account_id, arena_id)
        self.created = arena_id
        return result

    def prepare_import(self, text, name, arena_id):
        return self.exports.prepareimport(self.account_id, text, name, arena_id)

    def remove(self, snapshot):
        self.wrote = True
        return self.exports.remove(self.account_id, snapshot)

    def favorite(self, arena_id, value):
        """Star or unstar a deck as Arena's own button does; verified by reading it back."""
        result = self.exports.favorite(self.account_id, arena_id, bool(value))
        if result.get("changed"):
            self.wrote = True
        if result.get("arena_id") != arena_id or result.get("is_favorite") is not bool(value):
            raise DeckManagerError("Arena did not save the favorite. Refresh to check it.")
        return result

    def refresh_screen(self):
        """Redraw Arena's open Decks screen. Best effort: the write is already verified."""
        if not self.wrote:
            return False
        try:
            return bool(self.exports.refreshscreen(self.account_id, self.created))
        except Exception:
            return False


@contextmanager
def attach():
    available, message = availability()
    if not available:
        raise DeckManagerError(message)
    # Seconds per connection step, for the job's timing line.
    steps = {}
    started = time.monotonic()

    def step(label):
        nonlocal started
        now = time.monotonic()
        steps[label] = round(now - started, 2)
        started = now

    import frida

    step("frida")
    device = frida.get_local_device()
    processes = [p for p in device.enumerate_processes() if p.name in ARENA_PROCESS_NAMES]
    if len(processes) != 1:
        raise DeckManagerError("Open Arena and return to Decks outside a match.")
    step("find")
    session = device.attach(processes[0].pid)
    step("attach")
    # Each explicit job attaches independently, never launches/restarts Arena.
    timer = Timer(600, session.detach)
    timer.daemon = True
    script = None
    bridge = None
    try:
        timer.start()
        script = session.create_script(
            (Path(__file__).parent / "assets" / "arena_decks.js").read_text(encoding="utf-8")
        )
        script.load()
        step("script")
        bridge = ArenaBridge(script.exports_sync)
        step("open")
        bridge.connect_timings = steps
        yield bridge
    finally:
        # Also after a failed or stopped batch: earlier decks may have changed.
        if bridge:
            bridge.refresh_screen()
        if script:
            try:
                script.exports_sync.close()
            except Exception:
                pass
        timer.cancel()
        try:
            session.detach()
        except Exception:
            pass
