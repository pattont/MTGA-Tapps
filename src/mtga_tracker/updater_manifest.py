"""Pure update logic: versions, the signed release manifest, asset choice.

Nothing here touches the network or the filesystem. `updater.py` fetches
`latest.json` and `latest.json.sig`, hands the exact bytes to
:func:`load_signed_manifest`, and only a manifest whose Ed25519 signature
verifies against a key embedded in this module is ever parsed.

Manifest schema 1 (docs/plans/AUTO_UPDATE.md section 3.1)::

    {"schema": 1, "version": "0.6.6", "tag": "v0.6.6",
     "released_at": "...", "notes_url": "https://github.com/...",
     "minimum_version": null, "mandatory": false,
     "assets": [{"platform": "macos", "arch": "arm64", "kind": "app-zip",
                 "name": "...", "url": "https://github.com/...",
                 "size": 123, "sha256": "<64 hex>"}]}

Unknown keys are ignored so later schema-1 manifests can add fields.
"""

from __future__ import annotations

import base64
import binascii
import json
import platform as _platform
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

from packaging.version import InvalidVersion, Version

from . import ed25519_verify

#: Raw Ed25519 public keys (hex) whose signatures the updater accepts. A
#: tuple so a backup key can be added before the primary one is retired;
#: losing every private key means installed copies can never update again.
UPDATE_PUBLIC_KEYS: Tuple[str, ...] = (
    "c928a585f5d6a4934ddb35a171769b4a2a6cd5d40921d39d4dd26497fe59d9a7",
)

MANIFEST_SCHEMA = 1

#: Hosts a manifest URL may name and a download may be redirected to.
ALLOWED_DOWNLOAD_HOSTS: Tuple[str, ...] = (
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)

PLATFORMS = ("macos", "windows", "linux")
ARCHES = ("arm64", "x64")
ASSET_KINDS = ("app-zip", "dmg", "inno-setup", "portable-zip", "appimage")

#: Which asset kinds each install kind can apply, most preferred first.
_ASSET_PREFERENCE: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "macos-app": ("macos", ("app-zip", "dmg")),
    "windows-installer": ("windows", ("inno-setup",)),
}

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
#: Asset names become local file names; keep them to one safe path segment.
_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,199}$")


class ManifestError(ValueError):
    """The manifest is malformed, unsigned, or names something unsafe."""

    def __init__(self, message: str, code: str = "bad-manifest") -> None:
        super().__init__(message)
        self.code = code


# --- versions -----------------------------------------------------------------


def parse_version(text: Any) -> Optional[Version]:
    """PEP 440 version from a tag or package version, or None.

    Accepts `v0.6.5.3`, `0.6.3rc8`, `0.6.3-rc.8`, `0.7.0.dev3+g1a2b3c`. The
    setuptools-scm fallback `0.0.0+unknown` and garbage give None.
    """
    if not isinstance(text, str):
        return None
    value = text.strip()
    if value[:1] in ("v", "V"):
        value = value[1:]
    if not value:
        return None
    try:
        version = Version(value)
    except InvalidVersion:
        return None
    if not any(version.release):
        return None
    return version


def _public(version: Version) -> Version:
    """The version without its local segment, which never orders releases."""
    return Version(version.public)


def is_newer(candidate: Any, current: Any) -> bool:
    """True only when both parse and `candidate` sorts after `current`."""
    new, old = parse_version(candidate), parse_version(current)
    if new is None or old is None:
        return False
    return _public(new) > _public(old)


def versions_equal(left: Any, right: Any) -> bool:
    a, b = parse_version(left), parse_version(right)
    return a is not None and b is not None and _public(a) == _public(b)


def is_release_build(version: Any) -> bool:
    """A tagged build: parses, no dev segment, no local segment."""
    parsed = parse_version(version)
    return parsed is not None and not parsed.is_devrelease and parsed.local is None


# --- manifest -----------------------------------------------------------------


@dataclass(frozen=True)
class UpdateAsset:
    platform: str
    arch: str
    kind: str
    name: str
    url: str
    size: int
    sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Manifest:
    schema: int
    version: str
    tag: str
    released_at: Optional[str]
    notes_url: Optional[str]
    minimum_version: Optional[str]
    mandatory: bool
    assets: Tuple[UpdateAsset, ...]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["assets"] = [asset.to_dict() for asset in self.assets]
        return data


def _allowed_https_url(
    value: Any,
    hosts: Iterable[str] = ALLOWED_DOWNLOAD_HOSTS,
    *,
    extra_hosts: Iterable[str] = (),
    insecure_hosts: Iterable[str] = (),
) -> bool:
    """https on port 443 to an allow-listed host. `extra_hosts` (the
    release-validation override's host) may use any port, and plain http
    only when also listed in `insecure_hosts`."""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower()
    if host in tuple(extra_hosts):
        return parsed.scheme == "https" or (
            parsed.scheme == "http" and host in tuple(insecure_hosts)
        )
    if parsed.scheme != "https" or port not in (None, 443):
        return False
    return host in tuple(hosts)


def _require_str(document: Dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"Manifest field '{key}' must be a non-empty string.")
    return value.strip()


def _optional_str(document: Dict[str, Any], key: str) -> Optional[str]:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(f"Manifest field '{key}' must be a string or null.")
    return value.strip() or None


def _parse_asset(
    entry: Any, extra_hosts: Tuple[str, ...] = (), insecure_hosts: Tuple[str, ...] = ()
) -> UpdateAsset:
    if not isinstance(entry, dict):
        raise ManifestError("Every manifest asset must be an object.")
    platform_name = _require_str(entry, "platform")
    arch = _require_str(entry, "arch")
    kind = _require_str(entry, "kind")
    name = _require_str(entry, "name")
    url = _require_str(entry, "url")
    if platform_name not in PLATFORMS:
        raise ManifestError(f"Unknown asset platform {platform_name!r}.")
    if arch not in ARCHES:
        raise ManifestError(f"Unknown asset arch {arch!r}.")
    if kind not in ASSET_KINDS:
        raise ManifestError(f"Unknown asset kind {kind!r}.")
    if not _ASSET_NAME_RE.match(name) or name in (".", ".."):
        raise ManifestError(f"Unsafe asset name {name!r}.")
    if not _allowed_https_url(url, extra_hosts=extra_hosts, insecure_hosts=insecure_hosts):
        raise ManifestError(
            f"Asset URL for {name} is not an allowed https URL.", "host-not-allowed"
        )
    size = entry.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ManifestError(f"Asset {name} has an invalid size.")
    sha256 = entry.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
        raise ManifestError(f"Asset {name} has an invalid sha256.")
    return UpdateAsset(platform_name, arch, kind, name, url, size, sha256.lower())


def parse_manifest(
    document: Any,
    *,
    extra_hosts: Iterable[str] = (),
    insecure_hosts: Iterable[str] = (),
) -> Manifest:
    """Strictly validate a decoded schema-1 manifest. `extra_hosts` admits
    the release-validation override's host in asset URLs."""
    extra_hosts, insecure_hosts = tuple(extra_hosts), tuple(insecure_hosts)
    if not isinstance(document, dict):
        raise ManifestError("The manifest must be a JSON object.")
    schema = document.get("schema")
    if isinstance(schema, bool) or schema != MANIFEST_SCHEMA:
        raise ManifestError(f"Unsupported manifest schema {schema!r}.", "unknown-schema")
    version = _require_str(document, "version")
    if parse_version(version) is None:
        raise ManifestError(f"Manifest version {version!r} does not parse.")
    tag = _require_str(document, "tag")
    if not versions_equal(tag, version):
        raise ManifestError(f"Manifest tag {tag!r} does not match version {version!r}.")
    notes_url = _optional_str(document, "notes_url")
    if notes_url is not None and not _allowed_https_url(notes_url, ("github.com",)):
        raise ManifestError("The release notes URL is not an allowed https URL.")
    minimum_version = _optional_str(document, "minimum_version")
    if minimum_version is not None and parse_version(minimum_version) is None:
        raise ManifestError(f"Minimum version {minimum_version!r} does not parse.")
    mandatory = document.get("mandatory", False)
    if not isinstance(mandatory, bool):
        raise ManifestError("Manifest field 'mandatory' must be a boolean.")
    assets = document.get("assets")
    if not isinstance(assets, list):
        raise ManifestError("Manifest field 'assets' must be a list.")
    return Manifest(
        schema=MANIFEST_SCHEMA,
        version=version,
        tag=tag,
        released_at=_optional_str(document, "released_at"),
        notes_url=notes_url,
        minimum_version=minimum_version,
        mandatory=mandatory,
        assets=tuple(_parse_asset(entry, extra_hosts, insecure_hosts) for entry in assets),
    )


def decode_signature(text: Any) -> Optional[bytes]:
    """The 64 raw signature bytes from `latest.json.sig` (one base64 line)."""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("ascii")
        except UnicodeDecodeError:
            return None
    if not isinstance(text, str):
        return None
    compact = "".join(text.split())
    try:
        raw = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 64 else None


def verify_manifest_signature(
    manifest_bytes: bytes, signature_text: Any, keys: Optional[Iterable[str]] = None
) -> bool:
    signature = decode_signature(signature_text)
    if signature is None:
        return False
    for key in UPDATE_PUBLIC_KEYS if keys is None else keys:
        try:
            public_key = bytes.fromhex(key)
        except ValueError:
            continue
        if ed25519_verify.verify(public_key, bytes(manifest_bytes), signature):
            return True
    return False


def load_signed_manifest(
    manifest_bytes: bytes,
    signature_text: Any,
    keys: Optional[Iterable[str]] = None,
    *,
    extra_hosts: Iterable[str] = (),
    insecure_hosts: Iterable[str] = (),
) -> Manifest:
    """Verify the signature over the exact bytes FIRST, then parse."""
    if not verify_manifest_signature(manifest_bytes, signature_text, keys):
        raise ManifestError("The update manifest signature does not verify.", "bad-signature")
    try:
        document = json.loads(bytes(manifest_bytes).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"The update manifest is not JSON: {exc}") from None
    return parse_manifest(document, extra_hosts=extra_hosts, insecure_hosts=insecure_hosts)


# --- platform and asset choice -------------------------------------------------


def current_platform(system: Optional[str] = None) -> str:
    system = system or _platform.system()
    return {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(system, "unknown")


def current_arch(machine: Optional[str] = None) -> str:
    machine = (machine if machine is not None else _platform.machine()).lower()
    if machine in ("arm64", "aarch64", "armv8", "arm64e"):
        return "arm64"
    if machine in ("x86_64", "amd64", "x64"):
        return "x64"
    return machine or "unknown"


def select_asset(
    manifest: Manifest, *, platform: str, arch: str, install_kind: str
) -> Optional[UpdateAsset]:
    """The asset this install can apply, or None (link out instead)."""
    preference = _ASSET_PREFERENCE.get(install_kind)
    if preference is None:
        return None
    wanted_platform, kinds = preference
    if platform != wanted_platform:
        return None
    for kind in kinds:
        for asset in manifest.assets:
            if asset.platform == platform and asset.arch == arch and asset.kind == kind:
                return asset
    return None
