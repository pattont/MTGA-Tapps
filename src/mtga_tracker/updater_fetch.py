"""Checking and downloading, mixed into `UpdateManager`: fetch the signed
manifest (signature verified before parsing), decide available / up to
date, keep a verified download through a failed or empty re-check, and
download the chosen asset with retries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .updater_download import (
    DownloadError,
    UpdateNetworkError,
    download_asset,
    fetch_manifest,
    fetch_signature,
    stale_download_files,
    verify_file,
)
from .updater_manifest import (
    Manifest,
    ManifestError,
    UpdateAsset,
    load_signed_manifest,
    select_asset,
)
from .updater_support import (
    _RETRYABLE,
    CHECK_INTERVAL_S,
    DOWNLOAD_ATTEMPTS,
    ERROR_RETRY_S,
    _utc_iso,
)


class UpdateFetchMixin:
    def _restore_ready(self, reason: str) -> bool:
        """After a re-check that failed or found nothing newer, go back to
        the verified download that was ready before it. False when nothing
        was ready."""
        with self._lock:
            snapshot, self._ready_snapshot = self._ready_snapshot, None
        if snapshot is None:
            return False
        latest, asset, path = snapshot
        if asset is None or path is None or not verify_file(path, asset.sha256, asset.size):
            return False
        with self._lock:
            self._latest, self._asset, self._download_path = latest, asset, path
        self._log(f"re-check {reason}; keeping the verified v{latest.version} download")
        self._set_state("ready")
        return True

    def _check(self) -> None:
        if self._state != "checking":
            with self._lock:
                if self._state == "ready" and self._download_path is not None:
                    self._ready_snapshot = (self._latest, self._asset, self._download_path)
            self._set_state("checking")
        try:
            self._check_once()
        finally:
            with self._lock:
                self._ready_snapshot = None

    def _check_once(self) -> None:
        with self._lock:
            self._load_runtime()
            etag = self._runtime.get("etag") if self._runtime.get("manifest") else None
        try:
            session = self._session()
            result = fetch_manifest(
                session, etag=etag, url=self._manifest_url, policy=self._url_policy
            )
            if result.status == "not-modified":
                body = str(self._runtime.get("manifest") or "").encode("utf-8")
                signature = self._runtime.get("signature")
            elif result.status == "not-found":
                self._runtime["last_check"] = _utc_iso(self._clock())
                self._save_runtime()
                self._log("no manifest published (404)")
                self._schedule_next_check(CHECK_INTERVAL_S)
                if self._restore_ready("found no manifest"):
                    return
                if self._latest is None:
                    # Nothing published and nothing seen before: no release
                    # information, which is not the same as "up to date".
                    self._set_state("idle")
                else:
                    self._set_state("available" if self._latest_is_newer() else "up_to_date")
                return
            else:
                body = result.body or b""
                sig = fetch_signature(session, url=self._signature_url, policy=self._url_policy)
                if sig.status != "ok":
                    raise ManifestError("The manifest signature is missing.", "bad-signature")
                signature = (sig.body or b"").decode("ascii", "replace")
            manifest = self._load_manifest(body, signature)
        except (UpdateNetworkError, ManifestError) as exc:
            self._schedule_next_check(ERROR_RETRY_S)
            if self._restore_ready(f"failed ({getattr(exc, 'code', 'check-failed')}: {exc})"):
                return
            self._fail(getattr(exc, "code", "check-failed"), str(exc))
            return
        with self._lock:
            self._runtime.update(
                {
                    "last_check": _utc_iso(self._clock()),
                    "etag": result.etag if result.status == "ok" else etag,
                    "manifest": body.decode("utf-8"),
                    "signature": signature,
                }
            )
            self._save_runtime()
        self._apply_manifest(manifest)
        self._schedule_next_check(CHECK_INTERVAL_S)

    def _load_manifest(self, body: bytes, signature: Any) -> Manifest:
        """Signature first, then parse; the validation override's host may
        appear in asset URLs (the signature is still required)."""
        return load_signed_manifest(
            body,
            signature,
            extra_hosts=self._url_policy.extra_hosts,
            insecure_hosts=self._url_policy.insecure_hosts,
        )

    def _apply_manifest(self, manifest: Manifest) -> None:
        info = self.install_info()
        asset = select_asset(
            manifest, platform=self._platform, arch=self._arch, install_kind=info.kind
        )
        with self._lock:
            self._latest = manifest
            self._asset = asset
            newer = self._latest_is_newer()
            record = self._runtime.get("download") or {}
            cached = (
                Path(record["path"])
                if newer and asset and record.get("sha256") == asset.sha256 and record.get("path")
                else None
            )
        if not newer:
            if self._restore_ready("found nothing newer"):
                return
            self._log(f"up to date ({self.current_version}; latest {manifest.version})")
            self._set_state("up_to_date")
            return
        if cached is not None:
            if verify_file(cached, asset.sha256, asset.size):
                self._download_path = cached
                self._set_state("ready")
                return
            self._log(f"cached download {cached.name} no longer verifies; deleting it")
            cached.unlink(missing_ok=True)
            with self._lock:
                self._runtime.pop("download", None)
                self._save_runtime()
        self._log(f"update available: {manifest.version}")
        self._set_state("available")

    def _maybe_download(self, settings: Any) -> None:
        with self._lock:
            requested = self._download_requested
            self._download_requested = False
            if self._state != "available" or not self._latest_is_newer():
                return
            can_install, _reason = self._capability()
            if not can_install or self.install_info().kind == "source":
                return
            automatic = settings.update_auto_download and not self._skipped(settings)
            if not (requested or automatic):
                return
            asset = self._asset
        self._download(asset)

    def _on_progress(self, received: int, total: int) -> None:
        with self._lock:
            self._progress = {
                "received": int(received),
                "total": int(total),
                "fraction": round(received / total, 4) if total else 0.0,
            }
        now = self._monotonic()
        if now - self._last_progress_notify >= 0.5 or received >= total:
            self._last_progress_notify = now
            self._notify()

    def _download(self, asset: UpdateAsset) -> None:
        self._set_state("downloading")
        self._on_progress(0, asset.size)
        last_error: Optional[DownloadError] = None
        for attempt in range(DOWNLOAD_ATTEMPTS):
            if self._stop.is_set():
                return
            try:
                path = download_asset(
                    asset,
                    self.state_dir,
                    session=self._session(),
                    progress=self._on_progress,
                    cancelled=self._stop.is_set,
                    policy=self._url_policy,
                )
            except DownloadError as exc:
                last_error = exc
                self._log(f"download attempt {attempt + 1} failed: {exc.code}: {exc}")
                if exc.code not in _RETRYABLE and not exc.code.startswith("http-5"):
                    break
                self._stop.wait(2.0 * (attempt + 1))
                continue
            with self._lock:
                self._download_path = path
                self._runtime["download"] = {
                    "version": self._latest.version if self._latest else None,
                    "name": asset.name,
                    "path": str(path),
                    "kind": asset.kind,
                    "size": asset.size,
                    "sha256": asset.sha256,
                    "verified": True,
                }
                self._save_runtime()
            for stale in stale_download_files(self.state_dir, [asset.name]):
                stale.unlink(missing_ok=True)
            version = self._latest.version if self._latest else "?"
            self._console(f"Update v{version} downloaded and verified; restart to install it.")
            self._set_state("ready")
            return
        if last_error is not None and last_error.code != "cancelled":
            self._fail(last_error.code, str(last_error))
