"""Network side of the updater: manifest fetch and resumable asset download.

Every request goes through :func:`http_get`, which follows redirects by hand
so each hop can be checked against :data:`URL_POLICY` (https, and a host on
the release allow-list). `requests` is used for its certifi bundle; the
python.org macOS interpreter's default OpenSSL CA path is unreliable.

The session is injectable everywhere so the tests run offline against fake
sessions or a local `http.server` (with a test-only policy).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .updater_manifest import ALLOWED_DOWNLOAD_HOSTS, UpdateAsset

MANIFEST_URL = "https://github.com/pattont/MTGA-Tapps/releases/latest/download/latest.json"
SIGNATURE_URL = MANIFEST_URL + ".sig"
#: Release validation: fetch the manifest from here instead (".sig" appended
#: for the signature); its host joins the allow-list for that session.
MANIFEST_URL_ENV = "MTGA_TRACKER_UPDATE_MANIFEST_URL"

#: The manifest and its signature are tiny; anything larger is refused.
MAX_MANIFEST_BYTES = 256 * 1024
MAX_REDIRECTS = 5
REQUEST_TIMEOUT = 20.0
#: Free space needed beside a download, as a multiple of the asset size.
FREE_SPACE_FACTOR = 1.1
CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True)
class UrlPolicy:
    hosts: Tuple[str, ...] = ALLOWED_DOWNLOAD_HOSTS
    require_https: bool = True
    #: Hosts added by the validation override (MANIFEST_URL_ENV).
    extra_hosts: Tuple[str, ...] = ()
    #: Of those, the ones that may be reached over plain http.
    insecure_hosts: Tuple[str, ...] = ()

    def allows(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        if parsed.username or parsed.password:
            return False
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "http" and host in self.insecure_hosts:
            return True
        if self.require_https and parsed.scheme != "https":
            return False
        if parsed.scheme not in ("https", "http"):
            return False
        return host in self.hosts or host in self.extra_hosts

    @classmethod
    def for_override(cls, override: Optional[str]) -> "UrlPolicy":
        """The production policy, plus the override URL's host when set."""
        base = URL_POLICY
        if not override:
            return base
        parsed = urlparse(override)
        host = (parsed.hostname or "").lower()
        return cls(
            hosts=base.hosts,
            require_https=base.require_https,
            extra_hosts=base.extra_hosts + (host,),
            insecure_hosts=base.insecure_hosts + ((host,) if parsed.scheme == "http" else ()),
        )


def manifest_override(environ: Any = None) -> Optional[str]:
    """The validated MANIFEST_URL_ENV value, or None."""
    value = str((os.environ if environ is None else environ).get(MANIFEST_URL_ENV) or "").strip()
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return value


#: Production policy. Tests swap it for one that admits 127.0.0.1 over http.
URL_POLICY = UrlPolicy()


class UpdateNetworkError(Exception):
    """A request failed; `code` is a short machine-readable reason."""

    def __init__(self, message: str, code: str = "network") -> None:
        super().__init__(message)
        self.code = code


class DownloadError(Exception):
    def __init__(self, message: str, code: str = "download-failed") -> None:
        super().__init__(message)
        self.code = code


def user_agent() -> str:
    from . import __version__

    return f"TappsTracker/{__version__}"


def default_session() -> Any:
    import requests

    session = requests.Session()
    session.headers["User-Agent"] = user_agent()
    try:
        import certifi

        session.verify = certifi.where()
    except ImportError:  # pragma: no cover - requests depends on certifi
        pass
    return session


def http_get(
    session: Any,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    stream: bool = False,
    timeout: float = REQUEST_TIMEOUT,
    policy: Optional[UrlPolicy] = None,
) -> Any:
    """GET with manually followed, policy-checked redirects. Returns the
    final response (the caller closes it)."""
    policy = policy or URL_POLICY
    current = url
    request_headers = dict(headers or {})
    request_headers.setdefault("User-Agent", user_agent())
    for _hop in range(MAX_REDIRECTS + 1):
        if not policy.allows(current):
            raise UpdateNetworkError(f"Refusing to contact {current}", "host-not-allowed")
        try:
            response = session.get(
                current,
                headers=request_headers,
                stream=stream,
                timeout=timeout,
                allow_redirects=False,
            )
        except Exception as exc:  # requests raises many types; all mean "network"
            code = "timeout" if "timeout" in type(exc).__name__.lower() else "network"
            raise UpdateNetworkError(f"{type(exc).__name__}: {exc}", code) from None
        status = int(getattr(response, "status_code", 0) or 0)
        if status in (301, 302, 303, 307, 308):
            location = (getattr(response, "headers", {}) or {}).get("Location")
            _close(response)
            if not location:
                raise UpdateNetworkError("Redirect without a Location header")
            current = urljoin(current, location)
            continue
        return response
    raise UpdateNetworkError("Too many redirects", "redirect-loop")


def _close(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _read_limited(response: Any, limit: int) -> bytes:
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        chunks = []
        total = 0
        for chunk in iterator(chunk_size=16384):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise UpdateNetworkError("The update manifest is too large", "too-large")
            chunks.append(chunk)
        return b"".join(chunks)
    content = bytes(getattr(response, "content", b"") or b"")
    if len(content) > limit:
        raise UpdateNetworkError("The update manifest is too large", "too-large")
    return content


@dataclass(frozen=True)
class FetchResult:
    #: "ok", "not-modified", or "not-found"
    status: str
    body: Optional[bytes] = None
    etag: Optional[str] = None


def fetch_small(
    session: Any,
    url: str,
    *,
    etag: Optional[str] = None,
    timeout: float = REQUEST_TIMEOUT,
    policy: Optional[UrlPolicy] = None,
) -> FetchResult:
    """Fetch a small document (the manifest or its signature)."""
    headers = {"Accept": "application/octet-stream, application/json"}
    if etag:
        headers["If-None-Match"] = etag
    response = http_get(session, url, headers=headers, stream=True, timeout=timeout, policy=policy)
    try:
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 304:
            return FetchResult("not-modified", None, etag)
        if status == 404:
            return FetchResult("not-found")
        if status != 200:
            raise UpdateNetworkError(f"HTTP {status} from {url}", f"http-{status}")
        body = _read_limited(response, MAX_MANIFEST_BYTES)
        new_etag = (getattr(response, "headers", {}) or {}).get("ETag")
        return FetchResult("ok", body, new_etag)
    finally:
        _close(response)


def fetch_manifest(
    session: Any,
    *,
    etag: Optional[str] = None,
    url: str = MANIFEST_URL,
    timeout: float = 15.0,
    policy: Optional[UrlPolicy] = None,
) -> FetchResult:
    return fetch_small(session, url, etag=etag, timeout=timeout, policy=policy)


def fetch_signature(
    session: Any,
    *,
    url: str = SIGNATURE_URL,
    timeout: float = 15.0,
    policy: Optional[UrlPolicy] = None,
) -> FetchResult:
    return fetch_small(session, url, timeout=timeout, policy=policy)


# --- files --------------------------------------------------------------------


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, sha256: str, size: int) -> bool:
    """Size and SHA-256 both match. Run after the download and again
    immediately before the hand-off."""
    try:
        path = Path(path)
        if not path.is_file() or path.stat().st_size != int(size):
            return False
        return sha256_file(path) == str(sha256).lower()
    except OSError:
        return False


def _meta_path(part: Path) -> Path:
    return part.with_name(part.name + ".json")


def _read_meta(part: Path) -> Dict[str, Any]:
    try:
        data = json.loads(_meta_path(part).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_meta(part: Path, data: Dict[str, Any]) -> None:
    try:
        _meta_path(part).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _remove(*paths: Path) -> None:
    for path in paths:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _is_network_error(exc: BaseException) -> bool:
    """requests/urllib3 errors and ConnectionError subclass OSError too."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    module = type(exc).__module__ or ""
    return module.startswith(("requests", "urllib3", "socket", "ssl"))


def download_asset(
    asset: UpdateAsset,
    dest_dir: Path,
    *,
    session: Any,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Callable[[], bool] = lambda: False,
    disk_usage: Callable[[Any], Any] = shutil.disk_usage,
    chunk: int = CHUNK_BYTES,
    timeout: float = 30.0,
    policy: Optional[UrlPolicy] = None,
) -> Path:
    """Download `asset` into `dest_dir/<name>`, resuming a `.part` file.

    A resume sends `Range` plus `If-Range` (the ETag of the first response)
    to the github.com URL, never the expiring redirect target; a 200 instead
    of 206 restarts from zero. The SHA-256 is computed while streaming and
    checked with the size before the `.part` is renamed into place. On a
    hash mismatch the partial file is deleted.
    """
    report = progress or (lambda _received, _total: None)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / asset.name
    part = dest_dir / (asset.name + ".part")
    if verify_file(final, asset.sha256, asset.size):
        report(asset.size, asset.size)
        return final
    _remove(final)

    offset = 0
    if part.is_file():
        offset = part.stat().st_size
        if offset > asset.size:
            _remove(part, _meta_path(part))
            offset = 0
        elif offset == asset.size:
            # Every byte arrived but the process stopped before the rename:
            # finish locally instead of asking for an empty range (416).
            if verify_file(part, asset.sha256, asset.size):
                os.replace(part, final)
                _remove(_meta_path(part))
                report(asset.size, asset.size)
                return final
            _remove(part, _meta_path(part))
            offset = 0
    try:
        free = int(disk_usage(str(dest_dir)).free)
    except OSError:
        free = None
    if free is not None and free < asset.size * FREE_SPACE_FACTOR - offset:
        raise DownloadError(f"Not enough free disk space to download {asset.name}", "disk-space")

    meta = _read_meta(part) if offset else {}
    headers: Dict[str, str] = {"Accept": "application/octet-stream"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        if meta.get("etag"):
            headers["If-Range"] = str(meta["etag"])
    try:
        response = http_get(
            session, asset.url, headers=headers, stream=True, timeout=timeout, policy=policy
        )
    except UpdateNetworkError as exc:
        raise DownloadError(str(exc), exc.code) from None

    try:
        status = int(getattr(response, "status_code", 0) or 0)
        response_headers = getattr(response, "headers", {}) or {}
        digest = hashlib.sha256()
        if status == 206 and offset:
            content_range = str(response_headers.get("Content-Range") or "")
            if not content_range.startswith(f"bytes {offset}-"):
                _remove(part, _meta_path(part))
                raise DownloadError("The server resumed at the wrong offset", "bad-range")
            with open(part, "rb") as existing:
                for block in iter(lambda: existing.read(1 << 20), b""):
                    digest.update(block)
            mode = "ab"
        elif status == 200:
            offset = 0
            mode = "wb"
        elif status == 416 and offset:
            # The part is complete or stale; start over on the next attempt.
            _remove(part, _meta_path(part))
            raise DownloadError("The partial download could not be resumed", "bad-range")
        else:
            raise DownloadError(f"HTTP {status} downloading {asset.name}", f"http-{status}")

        etag = response_headers.get("ETag")
        if etag:
            _write_meta(part, {"etag": etag, "url": asset.url, "sha256": asset.sha256})
        received = offset
        report(received, asset.size)
        with open(part, mode) as handle:
            for block in response.iter_content(chunk_size=chunk):
                if cancelled():
                    raise DownloadError("The download was cancelled", "cancelled")
                if not block:
                    continue
                received += len(block)
                if received > asset.size:
                    handle.close()
                    _remove(part, _meta_path(part))
                    raise DownloadError(f"{asset.name} is larger than expected", "size-mismatch")
                handle.write(block)
                digest.update(block)
                report(received, asset.size)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
    except DownloadError:
        raise
    except OSError as exc:
        if _is_network_error(exc):
            raise DownloadError(f"{type(exc).__name__}: {exc}", "network") from None
        raise DownloadError(f"Could not write {asset.name}: {exc}", "write-failed") from None
    except Exception as exc:  # a dropped connection mid-stream
        raise DownloadError(f"{type(exc).__name__}: {exc}", "network") from None
    finally:
        _close(response)

    if received < asset.size:
        raise DownloadError(f"{asset.name} download ended early", "incomplete")
    if digest.hexdigest() != asset.sha256.lower():
        _remove(part, _meta_path(part))
        raise DownloadError(f"{asset.name} failed its SHA-256 check", "sha256-mismatch")
    os.replace(part, final)
    _remove(_meta_path(part))
    return final


def stale_download_files(dest_dir: Path, keep_names: Iterable[str]) -> list:
    """Downloaded assets and partials in `dest_dir` other than `keep_names`."""
    keep = set(keep_names)
    for name in list(keep):
        keep.add(name + ".part")
        keep.add(name + ".part.json")
    stale = []
    try:
        entries = list(Path(dest_dir).iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_file() or entry.name in keep:
            continue
        if entry.name.startswith("MTGA-Tracker-") or entry.name.endswith((".part", ".part.json")):
            stale.append(entry)
    return stale
