"""Shared helpers for the updater tests: a test-only Ed25519 signer, signed
manifests, and fake HTTP sessions. Nothing here touches the network."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Callable, Dict, List, Optional

from mtga_tracker import ed25519_verify as ed

#: A throwaway signing seed for tests (never the release key).
TEST_SEED = bytes(range(32))
TEST_PUBLIC_HEX = ed.public_key_from_seed(TEST_SEED).hex()


def sign(seed: bytes, message: bytes) -> bytes:
    """RFC 8032 signing, for tests only (the app never signs)."""
    digest = hashlib.sha512(seed).digest()
    scalar = bytearray(digest[:32])
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    a = int.from_bytes(bytes(scalar), "little")
    public = ed.public_key_from_seed(seed)
    r = int.from_bytes(hashlib.sha512(digest[32:] + message).digest(), "little") % ed._L
    encoded_r = ed._compress(ed._multiply(r, ed._BASE))
    k = int.from_bytes(hashlib.sha512(encoded_r + public + message).digest(), "little") % ed._L
    s = (r + k * a) % ed._L
    return encoded_r + s.to_bytes(32, "little")


def sign_b64(message: bytes, seed: bytes = TEST_SEED) -> str:
    return base64.b64encode(sign(seed, message)).decode("ascii") + "\n"


def asset(
    platform="macos", arch="arm64", kind="app-zip", name=None, payload=b"payload", version="0.6.6"
):
    name = name or {
        "app-zip": f"MTGA-Tracker-{version}-macos.zip",
        "dmg": f"MTGA-Tracker-{version}.dmg",
        "inno-setup": f"MTGA-Tracker-{version}-setup.exe",
        "portable-zip": f"MTGA-Tracker-{version}-windows.zip",
    }.get(kind, f"MTGA-Tracker-{version}-{kind}")
    return {
        "platform": platform,
        "arch": arch,
        "kind": kind,
        "name": name,
        "url": f"https://github.com/pattont/MTGA-Tapps/releases/download/v{version}/{name}",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def manifest_doc(version="0.6.6", assets=None, **overrides) -> Dict[str, Any]:
    document = {
        "schema": 1,
        "version": version,
        "tag": f"v{version}",
        "released_at": "2026-10-20T18:00:00Z",
        "notes_url": f"https://github.com/pattont/MTGA-Tapps/releases/tag/v{version}",
        "minimum_version": None,
        "mandatory": False,
        "assets": assets if assets is not None else [asset(version=version)],
    }
    document.update(overrides)
    return document


def manifest_bytes(document: Dict[str, Any]) -> bytes:
    return json.dumps(document, indent=2).encode("utf-8")


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None, chunks=None, fail_after=None):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._body = body
        self._chunks = chunks
        self._fail_after = fail_after
        self.closed = False

    @property
    def content(self):
        return self._body

    def iter_content(self, chunk_size=1024):
        chunks = self._chunks
        if chunks is None:
            chunks = [self._body[i : i + chunk_size] for i in range(0, len(self._body), chunk_size)]
        for index, chunk in enumerate(chunks):
            if self._fail_after is not None and index >= self._fail_after:
                raise ConnectionError("connection reset")
            yield chunk

    def close(self):
        self.closed = True


class FakeSession:
    """Routes URL -> handler(headers) -> FakeResponse; records every call."""

    def __init__(
        self, routes: Optional[Dict[str, Callable[[Dict[str, str]], FakeResponse]]] = None
    ):
        self.routes = dict(routes or {})
        self.calls: List[Dict[str, Any]] = []

    def get(self, url, headers=None, stream=False, timeout=None, allow_redirects=True):
        self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        handler = self.routes.get(url)
        if handler is None:
            return FakeResponse(404)
        result = handler(dict(headers or {}))
        if isinstance(result, Exception):
            raise result
        return result


def static(body: bytes, status=200, headers=None):
    return lambda _headers: FakeResponse(status, body, headers)
