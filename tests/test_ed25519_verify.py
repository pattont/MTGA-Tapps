"""The vendored Ed25519 verifier: RFC 8032 section 7.1 vectors, tampering,
malformed input, and a signature produced by openssl (the release tooling's
signer) over a manifest-shaped file."""

import base64
import shutil
import subprocess

import pytest

from mtga_tracker import ed25519_verify as ed
from mtga_tracker.updater_manifest import load_signed_manifest, verify_manifest_signature
from tests.update_support import manifest_bytes, manifest_doc

# (secret seed, public key, message, signature), all hex, from RFC 8032 7.1.
RFC8032_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
    (
        "833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
        "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
        "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
        "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
        "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704",
    ),
]


@pytest.mark.parametrize("seed,public,message,signature", RFC8032_VECTORS)
def test_rfc8032_vectors_verify(seed, public, message, signature):
    public_key = bytes.fromhex(public)
    assert ed.public_key_from_seed(bytes.fromhex(seed)) == public_key
    assert ed.verify(public_key, bytes.fromhex(message), bytes.fromhex(signature))


@pytest.mark.parametrize("seed,public,message,signature", RFC8032_VECTORS)
def test_tampered_message_or_signature_fails(seed, public, message, signature):
    public_key = bytes.fromhex(public)
    msg = bytes.fromhex(message)
    sig = bytearray.fromhex(signature)
    assert not ed.verify(public_key, msg + b"x", bytes(sig))
    sig[0] ^= 1
    assert not ed.verify(public_key, msg, bytes(sig))
    sig[0] ^= 1
    sig[40] ^= 0x10
    assert not ed.verify(public_key, msg, bytes(sig))


def test_wrong_key_and_malformed_input_never_raise():
    _seed, public, message, signature = RFC8032_VECTORS[1]
    other = bytes.fromhex(RFC8032_VECTORS[0][1])
    assert not ed.verify(other, bytes.fromhex(message), bytes.fromhex(signature))
    assert not ed.verify(b"short", b"", bytes(64))
    assert not ed.verify(bytes.fromhex(public), b"", b"short")
    assert not ed.verify(b"\xff" * 32, b"", bytes(64))  # y >= p does not decode
    # S >= L is rejected (signature malleability).
    sig = bytearray.fromhex(signature)
    sig[32:] = (ed._L).to_bytes(32, "little")
    assert not ed.verify(bytes.fromhex(public), bytes.fromhex(message), bytes(sig))
    assert not ed.verify(None, b"", bytes(64))  # type: ignore[arg-type]


def test_embedded_release_key_is_a_valid_point():
    from mtga_tracker.updater_manifest import UPDATE_PUBLIC_KEYS

    assert UPDATE_PUBLIC_KEYS[0] == (
        "c928a585f5d6a4934ddb35a171769b4a2a6cd5d40921d39d4dd26497fe59d9a7"
    )
    for key in UPDATE_PUBLIC_KEYS:
        assert ed._decompress(bytes.fromhex(key)) is not None


def _openssl():
    path = shutil.which("openssl")
    if path is None:
        pytest.skip("openssl is not available")
    probe = subprocess.run([path, "genpkey", "-algorithm", "ed25519"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("this openssl has no Ed25519 support")
    return path


def test_openssl_signed_manifest_verifies(tmp_path):
    openssl = _openssl()
    key = tmp_path / "key.pem"
    subprocess.run([openssl, "genpkey", "-algorithm", "ed25519", "-out", str(key)], check=True)
    public_der = subprocess.run(
        [openssl, "pkey", "-in", str(key), "-pubout", "-outform", "DER"],
        check=True,
        capture_output=True,
    ).stdout
    public_hex = public_der[-32:].hex()  # SubjectPublicKeyInfo ends with the raw key
    manifest = tmp_path / "latest.json"
    body = manifest_bytes(manifest_doc())
    manifest.write_bytes(body)
    signature = subprocess.run(
        [openssl, "pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(manifest)],
        check=True,
        capture_output=True,
    ).stdout
    sig_line = base64.b64encode(signature).decode("ascii") + "\n"

    assert verify_manifest_signature(body, sig_line, keys=(public_hex,))
    assert load_signed_manifest(body, sig_line, keys=(public_hex,)).version == "0.6.6"
    assert not verify_manifest_signature(body + b" ", sig_line, keys=(public_hex,))
    # The embedded release key did not sign this throwaway manifest.
    assert not verify_manifest_signature(body, sig_line)
