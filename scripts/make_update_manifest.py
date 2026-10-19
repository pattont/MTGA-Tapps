#!/usr/bin/env python3
"""Build (and optionally sign) the in-app update manifest for a release.

Run by the ``manifest`` job in ``.github/workflows/release.yml`` after both
platform builds, against the downloaded release artifacts:

    python scripts/make_update_manifest.py --tag v0.6.6 --repo pattont/MTGA-Tapps \
        --dist dist --out out --sign-key-env UPDATE_SIGNING_KEY \
        --verify-public-key c928a585f5d6a4934ddb35a171769b4a2a6cd5d40921d39d4dd26497fe59d9a7

Outputs, all in ``--out``:

- ``latest.json``: schema-1 manifest (docs/plans/AUTO_UPDATE.md section 3.1).
  Serialized once with ``json.dumps(indent=2, sort_keys=True)`` plus a trailing
  newline; the signature covers exactly those bytes, so never re-serialize it.
- ``latest.json.sig``: one line of base64 (no trailing newline, like
  ``base64 -w0``) of the 64-byte raw Ed25519 signature over ``latest.json``.
  Only written when a signing key is given.
- ``SHA256SUMS``: ``<hex>  <name>`` lines in ``sha256sum`` format.

Signing shells out to ``openssl pkeyutl -sign -rawin`` (OpenSSL 3+; macOS's
LibreSSL ``/usr/bin/openssl`` lacks Ed25519 raw signing, so set ``OPENSSL``
to a Homebrew openssl there). The private key is a PEM (PKCS#8) file, or the
PEM text in an environment variable, which is written to a 0600 temp file and
deleted afterwards. ``--verify-public-key`` re-verifies the signature against
the raw public key the app embeds, proving the CI secret matches it.

``--self-test`` exercises everything offline with dummy artifacts and a
throwaway key. Stdlib plus ``packaging``.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import quote

from packaging.version import InvalidVersion, Version

SCHEMA = 1
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
SIGNATURE_BYTES = 64

# Filename -> (platform, arch, kind). Order is the manifest's asset order.
# The DMG pattern is last and anchored on ".dmg", so it never swallows the
# suffixed names. Every kind is required: the client picks by platform/kind.
ASSET_PATTERNS = (
    (re.compile(r"^MTGA-Tracker-(?P<ver>.+)-macos\.zip$"), "macos", "arm64", "app-zip"),
    (re.compile(r"^MTGA-Tracker-(?P<ver>.+)\.dmg$"), "macos", "arm64", "dmg"),
    (re.compile(r"^MTGA-Tracker-(?P<ver>.+)-setup\.exe$"), "windows", "x64", "inno-setup"),
    (re.compile(r"^MTGA-Tracker-(?P<ver>.+)-windows\.zip$"), "windows", "x64", "portable-zip"),
)
REQUIRED_KINDS = tuple(kind for _, _, _, kind in ASSET_PATTERNS)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ManifestError(Exception):
    """A release that must not get a manifest."""


# --------------------------------------------------------------------------
# Manifest


def normalize_tag_version(tag: str) -> str:
    """``v0.6.3-rc.8`` -> ``0.6.3rc8`` (setuptools-scm's PEP 440 form)."""
    if not tag.startswith("v"):
        raise ManifestError(f"tag {tag!r} does not start with 'v'")
    try:
        version = Version(tag[1:])
    except InvalidVersion as exc:
        raise ManifestError(f"tag {tag!r} is not a PEP 440 version: {exc}") from None
    if version.local is not None:
        raise ManifestError(f"tag {tag!r} carries a local version label")
    return str(version)


def normalize_version(value: str, what: str) -> str:
    try:
        return str(Version(value))
    except InvalidVersion as exc:
        raise ManifestError(f"{what} {value!r} is not a PEP 440 version: {exc}") from None


def parse_released_at(value: Optional[str]) -> str:
    if value is None:
        moment = dt.datetime.now(dt.timezone.utc)
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = dt.datetime.fromisoformat(text)
        except ValueError:
            raise ManifestError(f"--released-at {value!r} is not an ISO 8601 timestamp") from None
        if moment.tzinfo is None:
            raise ManifestError(f"--released-at {value!r} needs a timezone (e.g. a trailing Z)")
        moment = moment.astimezone(dt.timezone.utc)
    return moment.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(name: str):
    for pattern, platform, arch, kind in ASSET_PATTERNS:
        match = pattern.match(name)
        if match:
            return match.group("ver"), platform, arch, kind
    return None


def collect_assets(dist: Path, version: str, repo: str, tag: str) -> List[Dict[str, object]]:
    """Find, validate and hash every release asset under ``dist`` (recursively,
    since downloaded Actions artifacts may land in per-artifact folders)."""
    if not dist.is_dir():
        raise ManifestError(f"--dist {dist} is not a directory")
    found: Dict[str, Dict[str, object]] = {}
    seen_names: Dict[str, Path] = {}
    problems: List[str] = []
    for path in sorted(p for p in dist.rglob("MTGA-Tracker-*") if p.is_file()):
        result = classify(path.name)
        if result is None:
            print(f"note: ignoring unrecognized file {path}", file=sys.stderr)
            continue
        file_version, platform, arch, kind = result
        if path.name in seen_names:
            problems.append(f"{path.name} appears twice ({seen_names[path.name]} and {path})")
            continue
        seen_names[path.name] = path
        if file_version != version:
            problems.append(
                f"{path.name}: filename version {file_version!r} differs from the tag's {version!r}"
            )
            continue
        if kind in found:
            problems.append(f"two {kind} assets: {found[kind]['name']} and {path.name}")
            continue
        size = path.stat().st_size
        if size == 0:
            problems.append(f"{path.name} is empty")
            continue
        found[kind] = {
            "platform": platform,
            "arch": arch,
            "kind": kind,
            "name": path.name,
            "url": (
                f"https://github.com/{repo}/releases/download/"
                f"{quote(tag, safe='')}/{quote(path.name, safe='')}"
            ),
            "size": size,
            "sha256": file_digest(path),
        }
    for kind in REQUIRED_KINDS:
        if kind not in found and not any(kind in p for p in problems):
            problems.append(f"missing required {kind} asset for version {version}")
    if problems:
        raise ManifestError("invalid release assets:\n  " + "\n  ".join(problems))
    return [found[kind] for kind in REQUIRED_KINDS]


def build_manifest(
    *,
    tag: str,
    repo: str,
    dist: Path,
    notes_url: Optional[str],
    minimum_version: Optional[str],
    mandatory: bool,
    released_at: Optional[str],
) -> Dict[str, object]:
    if not REPO_RE.match(repo):
        raise ManifestError(f"--repo {repo!r} is not owner/name")
    version = normalize_tag_version(tag)
    minimum = None
    if minimum_version:
        minimum = normalize_version(minimum_version, "--minimum-version")
        if Version(minimum) > Version(version):
            raise ManifestError(f"--minimum-version {minimum} is newer than the release {version}")
    return {
        "schema": SCHEMA,
        "version": version,
        "tag": tag,
        "released_at": parse_released_at(released_at),
        "notes_url": notes_url or f"https://github.com/{repo}/releases/tag/{quote(tag, safe='')}",
        "minimum_version": minimum,
        "mandatory": bool(mandatory),
        "assets": collect_assets(dist, version, repo, tag),
    }


def serialize_manifest(manifest: Dict[str, object]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256sums_text(assets: Sequence[Dict[str, object]]) -> str:
    lines = [f"{asset['sha256']}  {asset['name']}" for asset in sorted(assets, key=_name)]
    return "\n".join(lines) + "\n"


def _name(asset: Dict[str, object]) -> str:
    return str(asset["name"])


# --------------------------------------------------------------------------
# Signing (openssl subprocess)


def openssl_binary(explicit: Optional[str]) -> str:
    candidate = explicit or os.environ.get("OPENSSL") or "openssl"
    resolved = shutil.which(candidate)
    if not resolved:
        raise ManifestError(f"openssl not found ({candidate!r}); set --openssl or OPENSSL")
    return resolved


def _run_openssl(openssl: str, args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [openssl, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False
    )


def sign_file(openssl: str, key_path: Path, data_path: Path, sig_path: Path) -> bytes:
    proc = _run_openssl(
        openssl,
        ["pkeyutl", "-sign", "-inkey", str(key_path), "-rawin",
         "-in", str(data_path), "-out", str(sig_path)],
    )  # fmt: skip
    if proc.returncode != 0:
        # openssl's stderr never echoes key material; it names the failing step.
        raise ManifestError(f"openssl signing failed: {proc.stderr.strip() or proc.returncode}")
    signature = sig_path.read_bytes()
    if len(signature) != SIGNATURE_BYTES:
        raise ManifestError(
            f"expected a {SIGNATURE_BYTES}-byte Ed25519 signature, got {len(signature)} bytes; "
            "is the key an Ed25519 PEM?"
        )
    return signature


def public_key_hex_of(openssl: str, key_path: Path) -> str:
    """Raw 32-byte public key (hex) of a private key, as the app embeds it."""
    proc = subprocess.run(
        [openssl, "pkey", "-in", str(key_path), "-pubout", "-outform", "DER"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    der = proc.stdout
    if proc.returncode != 0 or len(der) != len(ED25519_SPKI_PREFIX) + 32:
        raise ManifestError("could not derive an Ed25519 public key from the signing key")
    if not der.startswith(ED25519_SPKI_PREFIX):
        raise ManifestError("the signing key is not an Ed25519 key")
    return der[-32:].hex()


def public_key_pem(raw_hex: str) -> str:
    try:
        raw = bytes.fromhex(raw_hex.strip())
    except ValueError:
        raise ManifestError("--verify-public-key is not hex") from None
    if len(raw) != 32:
        raise ManifestError(f"--verify-public-key must be 32 bytes, got {len(raw)}")
    body = base64.b64encode(ED25519_SPKI_PREFIX + raw).decode("ascii")
    return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----\n"


def verify_signature(openssl: str, public_hex: str, data_path: Path, sig_b64_path: Path) -> None:
    """Verify ``sig_b64_path`` (the published one-line base64) over ``data_path``."""
    signature = base64.b64decode(sig_b64_path.read_bytes().strip(), validate=True)
    if len(signature) != SIGNATURE_BYTES:
        raise ManifestError(f"signature is {len(signature)} bytes, expected {SIGNATURE_BYTES}")
    with tempfile.TemporaryDirectory(prefix="manifest-verify-") as scratch:
        pub_path = Path(scratch) / "public.pem"
        raw_sig = Path(scratch) / "sig.bin"
        pub_path.write_text(public_key_pem(public_hex), encoding="ascii")
        raw_sig.write_bytes(signature)
        proc = _run_openssl(
            openssl,
            ["pkeyutl", "-verify", "-pubin", "-inkey", str(pub_path), "-rawin",
             "-in", str(data_path), "-sigfile", str(raw_sig)],
        )  # fmt: skip
    if proc.returncode != 0:
        detail = (proc.stdout + proc.stderr).strip()
        raise ManifestError(
            "latest.json.sig does NOT verify against the embedded public key "
            f"{public_hex.strip()}: {detail}"
        )


class SigningKey:
    """A PEM private key on disk, materialized from an env var if needed."""

    def __init__(self, path: Optional[str], env_name: Optional[str]):
        self._path = Path(path) if path else None
        self._env_name = env_name
        self._temp: Optional[Path] = None

    def __enter__(self) -> Path:
        if self._path is not None:
            if not self._path.is_file():
                raise ManifestError(f"--sign-key {self._path} does not exist")
            return self._path
        assert self._env_name
        pem = os.environ.get(self._env_name, "")
        if not pem.strip():
            raise ManifestError(f"environment variable {self._env_name} is empty or unset")
        if "BEGIN" not in pem:
            raise ManifestError(f"{self._env_name} does not contain a PEM private key")
        fd, name = tempfile.mkstemp(prefix="update-signing-", suffix=".pem")  # mode 0600
        self._temp = Path(name)
        try:
            os.chmod(name, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(pem.strip() + "\n")
        except BaseException:
            self._cleanup()
            raise
        return self._temp

    def __exit__(self, *exc_info) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        if self._temp is not None:
            try:
                self._temp.unlink()
            except FileNotFoundError:
                pass
            self._temp = None


# --------------------------------------------------------------------------
# CLI


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", help="release tag, e.g. v0.6.6 or v0.6.7-rc.1")
    parser.add_argument("--repo", help="owner/name of the GitHub repository")
    parser.add_argument("--dist", type=Path, help="directory holding the release artifacts")
    parser.add_argument("--out", type=Path, help="directory to write the manifest files into")
    parser.add_argument("--notes-url", help="default: the release's tag page")
    parser.add_argument("--minimum-version", help="below this, the app links out")
    parser.add_argument("--mandatory", action="store_true", help="sticky update pill, no skip")
    parser.add_argument("--released-at", help="ISO 8601 timestamp (default: now, UTC)")
    key = parser.add_mutually_exclusive_group()
    key.add_argument("--sign-key", help="Ed25519 private key PEM file")
    key.add_argument("--sign-key-env", help="environment variable holding the PEM text")
    parser.add_argument(
        "--verify-public-key",
        metavar="HEX",
        help="raw 32-byte Ed25519 public key (hex) the signature must verify against",
    )
    parser.add_argument("--openssl", help="openssl binary (default: $OPENSSL or openssl)")
    parser.add_argument("--self-test", action="store_true", help="run the offline self-test")
    args = parser.parse_args(argv)
    if not args.self_test:
        missing = [flag for flag in ("tag", "repo", "dist", "out") if getattr(args, flag) is None]
        if missing:
            parser.error("missing " + ", ".join("--" + flag.replace("_", "-") for flag in missing))
        if args.verify_public_key and not (args.sign_key or args.sign_key_env):
            parser.error("--verify-public-key needs --sign-key or --sign-key-env")
    return args


def run(args: argparse.Namespace) -> Dict[str, object]:
    manifest = build_manifest(
        tag=args.tag,
        repo=args.repo,
        dist=args.dist,
        notes_url=args.notes_url,
        minimum_version=args.minimum_version,
        mandatory=args.mandatory,
        released_at=args.released_at,
    )
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "latest.json"
    sig_path = out / "latest.json.sig"
    for stale in (manifest_path, sig_path, out / "SHA256SUMS"):
        if stale.exists():
            stale.unlink()

    manifest_bytes = serialize_manifest(manifest)
    manifest_path.write_bytes(manifest_bytes)
    (out / "SHA256SUMS").write_text(sha256sums_text(manifest["assets"]), encoding="ascii")
    print(f"Wrote {manifest_path} ({len(manifest_bytes)} bytes, version {manifest['version']})")
    for asset in manifest["assets"]:
        print(f"  {asset['sha256']}  {asset['name']}  ({asset['size']} bytes)")

    if args.sign_key or args.sign_key_env:
        openssl = openssl_binary(args.openssl)
        with SigningKey(args.sign_key, args.sign_key_env) as key_path:
            derived = public_key_hex_of(openssl, key_path)
            with tempfile.TemporaryDirectory(prefix="manifest-sign-") as scratch:
                signature = sign_file(openssl, key_path, manifest_path, Path(scratch) / "sig.bin")
        if manifest_path.read_bytes() != manifest_bytes:
            raise ManifestError("latest.json changed while it was being signed")
        expected = (args.verify_public_key or "").strip().lower()
        if expected and derived != expected:
            raise ManifestError(
                f"signing key's public key {derived} is not the embedded key {expected}"
            )
        sig_path.write_bytes(base64.b64encode(signature))
        print(f"Wrote {sig_path} (signing public key {derived})")
        if expected:
            try:
                verify_signature(openssl, expected, manifest_path, sig_path)
            except ManifestError:
                sig_path.unlink()
                raise
            print(f"Verified latest.json.sig against embedded public key {expected}")
    else:
        print("No signing key given: latest.json.sig NOT written", file=sys.stderr)
    return manifest


# --------------------------------------------------------------------------
# Self-test


def self_test(openssl_explicit: Optional[str]) -> None:
    openssl = openssl_binary(openssl_explicit)

    def expect_failure(label: str, func, needle: str) -> None:
        try:
            func()
        except ManifestError as exc:
            if needle not in str(exc):
                raise AssertionError(f"{label}: wrong error {exc!r}") from None
            print(f"  ok: {label}")
            return
        raise AssertionError(f"{label}: expected a failure")

    assert normalize_tag_version("v0.6.3-rc.8") == "0.6.3rc8"
    assert normalize_tag_version("v0.6.6") == "0.6.6"
    assert normalize_tag_version("v0.6.5.3") == "0.6.5.3"
    assert parse_released_at("2026-10-20T18:00:00Z") == "2026-10-20T18:00:00Z"
    assert parse_released_at("2026-10-20T20:00:00.250000+02:00") == "2026-10-20T18:00:00Z"
    print("  ok: version and timestamp normalization")

    with tempfile.TemporaryDirectory(prefix="manifest-selftest-") as scratch_name:
        scratch = Path(scratch_name)
        key = scratch / "key.pem"
        proc = _run_openssl(openssl, ["genpkey", "-algorithm", "ed25519", "-out", str(key)])
        if proc.returncode != 0:
            raise ManifestError(f"{openssl} cannot generate Ed25519 keys: {proc.stderr.strip()}")
        public_hex = public_key_hex_of(openssl, key)

        tag, version = "v1.2.3-rc.4", "1.2.3rc4"
        dist = scratch / "dist"
        (dist / "macos-latest-build").mkdir(parents=True)
        (dist / "windows-latest-build").mkdir(parents=True)
        contents = {
            f"macos-latest-build/MTGA-Tracker-{version}-macos.zip": b"zip" * 100,
            f"macos-latest-build/MTGA-Tracker-{version}.dmg": b"dmg" * 200,
            f"windows-latest-build/MTGA-Tracker-{version}-setup.exe": b"exe" * 300,
            f"windows-latest-build/MTGA-Tracker-{version}-windows.zip": b"win" * 400,
            "windows-latest-build/notes.txt": b"ignored",
        }
        for rel, data in contents.items():
            (dist / rel).write_bytes(data)

        def argv(out: Path, *extra: str) -> List[str]:
            return [
                "--tag", tag, "--repo", "pattont/MTGA-Tapps", "--dist", str(dist),
                "--out", str(out), "--released-at", "2026-10-20T18:00:00Z", *extra,
            ]  # fmt: skip

        # 1. Signed from a key file, verified against the derived public key.
        out = scratch / "out"
        args = parse_args(argv(out, "--sign-key", str(key), "--verify-public-key", public_hex))
        args.openssl = openssl
        manifest = run(args)
        raw = (out / "latest.json").read_bytes()
        assert raw == serialize_manifest(json.loads(raw)), "not canonical"
        assert raw.endswith(b"}\n")
        loaded = json.loads(raw)
        assert set(loaded) == {
            "schema", "version", "tag", "released_at", "notes_url",
            "minimum_version", "mandatory", "assets",
        }  # fmt: skip
        assert loaded["schema"] == 1 and loaded["version"] == version and loaded["tag"] == tag
        assert loaded["minimum_version"] is None and loaded["mandatory"] is False
        assert loaded["notes_url"] == f"https://github.com/pattont/MTGA-Tapps/releases/tag/{tag}"
        assert [a["kind"] for a in loaded["assets"]] == list(REQUIRED_KINDS)
        for asset in loaded["assets"]:
            assert set(asset) == {"platform", "arch", "kind", "name", "url", "size", "sha256"}
            data = next(v for k, v in contents.items() if k.endswith("/" + asset["name"]))
            assert asset["size"] == len(data)
            assert asset["sha256"] == hashlib.sha256(data).hexdigest()
            assert asset["url"] == (
                f"https://github.com/pattont/MTGA-Tapps/releases/download/{tag}/{asset['name']}"
            )
        assert manifest == loaded
        sums = (out / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        assert len(sums) == 4 and all(re.match(r"^[0-9a-f]{64}  MTGA-Tracker-", s) for s in sums)
        sig_text = (out / "latest.json.sig").read_bytes()
        assert b"\n" not in sig_text and len(base64.b64decode(sig_text)) == SIGNATURE_BYTES
        print("  ok: manifest shape, hashes, SHA256SUMS, signature format")

        # 2. Independent openssl verification of the published files.
        verify_signature(openssl, public_hex, out / "latest.json", out / "latest.json.sig")
        print("  ok: signature verifies with the reconstructed public key")

        # 3. Tampering is detected.
        tampered = scratch / "tampered.json"
        tampered.write_bytes(raw.replace(b'"mandatory": false', b'"mandatory": true'))
        expect_failure(
            "tampered manifest rejected",
            lambda: verify_signature(openssl, public_hex, tampered, out / "latest.json.sig"),
            "does NOT verify",
        )
        other = scratch / "other.pem"
        _run_openssl(openssl, ["genpkey", "-algorithm", "ed25519", "-out", str(other)])
        other_hex = public_key_hex_of(openssl, other)
        expect_failure(
            "wrong public key rejected",
            lambda: verify_signature(
                openssl, other_hex, out / "latest.json", out / "latest.json.sig"
            ),
            "does NOT verify",
        )

        def run_with(extra: List[str], env: Optional[Dict[str, str]] = None):
            def call():
                saved = dict(os.environ)
                try:
                    os.environ.update(env or {})
                    parsed = parse_args(argv(scratch / "out-x", *extra))
                    parsed.openssl = openssl
                    run(parsed)
                finally:
                    os.environ.clear()
                    os.environ.update(saved)

            return call

        expect_failure(
            "mismatched embedded key fails the run",
            run_with(["--sign-key", str(key), "--verify-public-key", other_hex]),
            "is not the embedded key",
        )

        # 4. Key from an environment variable; the temp file is removed.
        before = set(Path(tempfile.gettempdir()).glob("update-signing-*.pem"))
        env_out = scratch / "out-env"
        os.environ["SELFTEST_SIGNING_KEY"] = key.read_text(encoding="ascii")
        try:
            args = parse_args(
                argv(env_out, "--sign-key-env", "SELFTEST_SIGNING_KEY",
                     "--verify-public-key", public_hex, "--minimum-version", "1.2.0",
                     "--mandatory")
            )  # fmt: skip
            args.openssl = openssl
            run(args)
        finally:
            del os.environ["SELFTEST_SIGNING_KEY"]
        after = set(Path(tempfile.gettempdir()).glob("update-signing-*.pem"))
        assert after <= before, "temporary key file left behind"
        env_manifest = json.loads((env_out / "latest.json").read_bytes())
        assert env_manifest["minimum_version"] == "1.2.0" and env_manifest["mandatory"] is True
        verify_signature(openssl, public_hex, env_out / "latest.json", env_out / "latest.json.sig")
        print("  ok: key from environment variable, temp key removed")
        expect_failure(
            "empty key env var rejected",
            run_with(["--sign-key-env", "SELFTEST_EMPTY_KEY"], {"SELFTEST_EMPTY_KEY": ""}),
            "empty or unset",
        )
        expect_failure(
            "release tag newer than its artifacts rejected",
            lambda: build_manifest(
                tag="v1.2.3",
                repo="pattont/MTGA-Tapps",
                dist=dist,
                notes_url=None,
                minimum_version=None,
                mandatory=False,
                released_at=None,
            ),
            "differs from the tag",
        )
    print("self-test passed")


def _asset_validation_self_test() -> None:
    def expect(label: str, files: Sequence[str], needle: str, tag: str = "v2.0.0") -> None:
        with tempfile.TemporaryDirectory(prefix="manifest-assets-") as scratch_name:
            dist = Path(scratch_name)
            for name in files:
                (dist / name).write_bytes(b"x")
            try:
                collect_assets(dist, normalize_tag_version(tag), "o/r", tag)
            except ManifestError as exc:
                if needle not in str(exc):
                    raise AssertionError(f"{label}: wrong error {exc!r}") from None
                print(f"  ok: {label}")
                return
            raise AssertionError(f"{label}: expected a failure")

    full = [
        "MTGA-Tracker-2.0.0-macos.zip",
        "MTGA-Tracker-2.0.0.dmg",
        "MTGA-Tracker-2.0.0-setup.exe",
        "MTGA-Tracker-2.0.0-windows.zip",
    ]
    for missing in full:
        rest = [name for name in full if name != missing]
        expect(f"missing {missing} rejected", rest, "missing required")
    expect(
        "filename version differing from the tag rejected",
        full[:3] + ["MTGA-Tracker-2.0.1-windows.zip"],
        "differs from the tag",
    )
    expect(
        "dev-version artifact rejected",
        full[:1] + ["MTGA-Tracker-2.0.1.dev3+gabc.dmg"] + full[2:],
        "differs from the tag",
    )
    expect("rc tag vs final artifacts rejected", full, "differs from the tag", tag="v2.0.0-rc.1")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.self_test:
            _asset_validation_self_test()
            self_test(args.openssl)
        else:
            run(args)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
