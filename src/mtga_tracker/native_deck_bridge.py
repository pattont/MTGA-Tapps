"""Explicit, bounded attachment to Arena's native deck services."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
from threading import Timer

from .deck_manager import DeckManagerError
from .paths import native_deck_platform_supported


def availability():
    if not native_deck_platform_supported():
        return False, "Direct transfers support Arena on Apple Silicon Macs and 64-bit Windows."
    try:
        import frida  # noqa: F401
    except ImportError:
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

    def roster(self):
        report = self.exports.roster(self.account_id)
        if (
            report.get("account_id") != self.account_id
            or report.get("roster_refreshed") is not True
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
    import frida

    device = frida.get_local_device()
    processes = [p for p in device.enumerate_processes() if p.name in ARENA_PROCESS_NAMES]
    if len(processes) != 1:
        raise DeckManagerError("Open Arena and return to Decks outside a match.")
    session = device.attach(processes[0].pid)
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
        bridge = ArenaBridge(script.exports_sync)
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
