"""Lossless zlib codec for the raw payload archive.

raw_game_payloads is a reprocessing archive (it made the bottomed-card and
explore-draw backfills possible) but raw Arena JSON dominated the database:
~78% of the file, compressing to ~11% of its size. Payloads are stored
zlib-compressed; readers accept both compressed bytes and legacy plain text,
so old rows keep working before/without the compaction migration.
"""

from __future__ import annotations

import zlib

#: First byte of every zlib stream produced here (default 32KB window).
_ZLIB_MAGIC = b"\x78"


def compress_payload(text: str) -> bytes:
    """Compress payload JSON for storage (lossless, ~9x smaller)."""
    return zlib.compress(str(text or "").encode("utf-8"), 6)


def decode_payload(value: object) -> str:
    """Return payload JSON text from a stored value.

    Accepts zlib-compressed bytes (current format), plain bytes, or legacy
    TEXT rows. Never raises on malformed input — diagnostics readers should
    see best-effort text rather than crash.
    """
    if value is None:
        return ""
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if raw[:1] == _ZLIB_MAGIC:
            try:
                return zlib.decompress(raw).decode("utf-8")
            except (zlib.error, UnicodeDecodeError):
                pass
        return raw.decode("utf-8", "replace")
    return str(value)
