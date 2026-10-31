"""Verification-only Ed25519 (RFC 8032, section 5.1) on the standard library.

The updater checks the release manifest's detached signature with this
module. The frozen bundle ships neither `cryptography` nor PyNaCl, and the
signature check runs once per update check on a background thread, so a
small pure-Python verifier is the right trade: about 100 lines, no native
code, and slow only in the sense of tens of milliseconds.

Only verification is implemented. There is no signing code here and no
secret ever touches this process.
"""

from __future__ import annotations

import hashlib
from typing import Optional, Tuple

#: The field prime 2^255 - 19.
_P = 2**255 - 19
#: The prime order of the base point.
_L = 2**252 + 27742317777372353535851937790883648493
#: The curve constant d = -121665 / 121666.
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
#: sqrt(-1) mod p, used when recovering x from y.
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)

_Point = Tuple[int, int, int, int]  # extended coordinates (X, Y, Z, T)


def _inv(value: int) -> int:
    return pow(value, _P - 2, _P)


def _recover_x(y: int, sign: int) -> Optional[int]:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
assert _GX is not None
_BASE: _Point = (_GX, _GY, 1, _GX * _GY % _P)
_IDENTITY: _Point = (0, 1, 1, 0)


def _add(a: _Point, b: _Point) -> _Point:
    # RFC 8032 section 5.1.4, add-2008-hwcd-3.
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = t1 * 2 * _D * t2 % _P
    dd = z1 * 2 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _multiply(scalar: int, point: _Point) -> _Point:
    result = _IDENTITY
    addend = point
    while scalar > 0:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        scalar >>= 1
    return result


def _equal(a: _Point, b: _Point) -> bool:
    x1, y1, z1, _ = a
    x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % _P == 0 and (y1 * z2 - y2 * z1) % _P == 0


def _compress(point: _Point) -> bytes:
    x, y, z, _ = point
    zi = _inv(z)
    x, y = x * zi % _P, y * zi % _P
    return int(y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(encoded: bytes) -> Optional[_Point]:
    if len(encoded) != 32:
        return None
    y = int.from_bytes(encoded, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` is a valid Ed25519 signature of `message` by
    the raw 32-byte `public_key`. Never raises on malformed input."""
    try:
        public_key = bytes(public_key)
        signature = bytes(signature)
        message = bytes(message)
    except TypeError:
        return False
    if len(public_key) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public_key)
    if point_a is None:
        return False
    encoded_r = signature[:32]
    point_r = _decompress(encoded_r)
    if point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    digest = hashlib.sha512(encoded_r + public_key + message).digest()
    h = int.from_bytes(digest, "little") % _L
    return _equal(_multiply(s, _BASE), _add(point_r, _multiply(h, point_a)))


def public_key_from_seed(seed: bytes) -> bytes:
    """The raw public key for a 32-byte private seed (tests and tooling
    only; derives, never signs)."""
    if len(seed) != 32:
        raise ValueError("An Ed25519 seed is 32 bytes.")
    digest = bytearray(hashlib.sha512(seed).digest()[:32])
    digest[0] &= 248
    digest[31] &= 127
    digest[31] |= 64
    return _compress(_multiply(int.from_bytes(bytes(digest), "little"), _BASE))
