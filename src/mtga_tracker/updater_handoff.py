"""The install hand-off and the next launch's reconciliation.

Mixed into `UpdateManager`: `_perform_install` runs plan section 6 in order
(re-verify, journal, pre-update backup, stop tracker, release database
handles, stop overlay, spawn the detached installer, request exit), and the
startup tasks reconcile `pending.json`, re-validate a cached download, clean
stale files, and after a minute of healthy runtime drop the macOS rollback
copy. See docs/plans/AUTO_UPDATE.md sections 6 and 9.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import update_install as installer_module
from .updater_download import stale_download_files, verify_file
from .updater_manifest import ManifestError, parse_version, select_asset, versions_equal
from .updater_support import (
    EXIT_BACKSTOP_S,
    HEALTHY_AFTER_S,
    _read_json,
    _utc_iso,
    _write_json_atomic,
    relaunch_arguments,
)


class UpdateHandoffMixin:
    def _plan(self, relaunch: bool) -> installer_module.InstallPlan:
        info = self.install_info()
        assert self._asset is not None and self._latest is not None
        return installer_module.InstallPlan(
            asset_path=Path(self._download_path or (self.state_dir / self._asset.name)),
            asset_kind=self._asset.kind,
            install_kind=info.kind,
            from_version=self.current_version,
            to_version=self._latest.version,
            parent_pid=os.getpid(),
            updates_dir=self.state_dir,
            app_path=info.app_path,
            executable=info.executable,
            relaunch=relaunch,
            all_users=info.install_mode == "admin",
        )

    def _backup(self, from_version: str) -> None:
        if self.db_path is None or not Path(self.db_path).is_file():
            return
        if self._backup_fn is not None:
            self._backup_fn(Path(self.db_path), from_version)
            return
        from .backup import pre_update_backup

        pre_update_backup(Path(self.db_path), from_version)

    def _release_db_handles(self) -> None:
        if self._release_handles is not None:
            self._release_handles(Path(self.db_path) if self.db_path else None)
            return
        from . import live_api
        from .dashboard import clear_response_cache

        live_api.reset_poll_connections()
        clear_response_cache()
        if self.db_path is not None and Path(self.db_path).is_file():
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=10.0)
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                self._log(f"checkpoint skipped: {exc}")

    def _overlay(self) -> Any:
        if self._overlay_factory is not None:
            return self._overlay_factory()
        from .overlay_launcher import get_manager as get_overlay_manager

        return get_overlay_manager()

    def _remove_stage_dirs(self) -> None:
        for folder in installer_module.remove_stage_dirs(
            self.state_dir, self.install_info().app_path
        ):
            self._log(f"removed staging folder {folder}")

    def _abort_install(self, code: str, message: str, *, stopped: bool = False) -> None:
        """Give up on this install. `stopped`: the tracker was already
        stopped, so a --no-gui foreground loop must start it again.

        For "Install update and quit" the user asked to quit: report the
        error and quit normally instead of resuming."""
        self._pending_file.unlink(missing_ok=True)
        try:
            self._remove_stage_dirs()
        except Exception as exc:
            self._log(f"could not remove staging folders: {exc}")
        self._fail(code, message)
        quitting = self._quit_after_install
        with self._lock:
            self._handoff_outcome = "resumed" if stopped and not quitting else "none"
            self._quit_after_install = False
        self._handoff_done.set()
        if quitting:
            self._log("install and quit: the install was abandoned; quitting anyway")
            self._console(f"The update was not installed ({code}); quitting.")
            self._request_exit()

    def _wait_tracker_stopped(self, launcher: Any, timeout: float) -> bool:
        """A --no-gui tracker runs on the main thread, so stop_tracker() only
        asks; wait for the session to really return before touching files."""
        wait = getattr(launcher, "wait_tracker_stopped", None)
        if callable(wait):
            return bool(wait(timeout))
        return not getattr(launcher, "tracker_is_running", False)

    def _resume_services(self, tracker_was_running: bool, overlay_was_running: bool) -> None:
        if self._quit_after_install:
            return  # "Install update and quit": the app is quitting anyway
        launcher = self.launcher
        still_running = launcher is not None and (
            getattr(launcher, "tracker_is_running", False)
            or getattr(launcher, "tracker_active", False)
        )
        if (
            tracker_was_running
            and not self._foreground_tracker
            and launcher is not None
            and not still_running  # never a second tracker beside a slow one
        ):
            try:
                launcher.start_tracker()
            except Exception as exc:
                self._log(f"could not restart the tracker: {exc}")
        if overlay_was_running:
            try:
                self._overlay().start_if_enabled()
            except Exception as exc:
                self._log(f"could not restart the overlay: {exc}")

    def _perform_install(
        self, *, gate: str, relaunch: bool, reasons: Optional[List[str]] = None
    ) -> None:
        """Plan section 6, in order. Runs on the updater thread. `reasons`:
        the gate the caller just evaluated (else it is evaluated here)."""
        with self._lock:
            self._quit_after_install = not relaunch
            self._handoff_abandoned = False
        asset, latest = self._asset, self._latest
        path = self._download_path
        if asset is None or latest is None or path is None:
            self._abort_install("not-ready", "No verified update is ready.")
            return
        if not verify_file(path, asset.sha256, asset.size):
            Path(path).unlink(missing_ok=True)
            with self._lock:
                self._runtime.pop("download", None)
                self._save_runtime()
                self._download_path = None
            self._abort_install("sha256-mismatch", "The downloaded update no longer verifies.")
            return
        if reasons is None:
            reasons = self.busy_reasons(gate=gate)
        if reasons and not relaunch:
            self._abort_install(reasons[0], "The update could not be installed right now.")
            return
        if reasons:
            self._log(f"install postponed: {', '.join(reasons)}")
            with self._lock:
                self._handoff_outcome = "none"
            self._handoff_done.set()
            self._set_state("ready")
            return
        with self._lock:
            # An armed "install after this game" is used up by this attempt;
            # a failure must not quietly re-fire it.
            if self._runtime.pop("pending_install", None) is not None:
                self._save_runtime()
        try:
            plan = self._installer.prepare_install(self._plan(relaunch))
        except Exception as exc:
            self._abort_install(getattr(exc, "code", "stage-failed"), str(exc))
            return

        pending = {
            "from": self.current_version,
            "to": latest.version,
            "asset": asset.name,
            "sha256": asset.sha256,
            "notes_url": latest.notes_url,
            "pid": os.getpid(),
            "install_kind": plan.install_kind,
            "log": str(plan.log_path) if plan.log_path else None,
            "started_at": _utc_iso(self._clock()),
            # The relaunched app (new on success, old on failure) re-reads
            # these so it comes back with the same --db, --port, --no-gui.
            "relaunch_args": relaunch_arguments(self._argv),
        }
        _write_json_atomic(self._pending_file, pending)
        self._log(f"installing {self.current_version} -> {latest.version} ({gate})")
        self._console(f"Installing update v{latest.version}; Tapps Tracker will restart.")

        try:
            self._backup(self.current_version)
        except Exception as exc:
            self._abort_install("backup-failed", f"The pre-update backup failed: {exc}")
            return

        launcher = self.launcher
        tracker_was_running = bool(
            launcher is not None
            and (
                getattr(launcher, "tracker_is_running", False)
                or getattr(launcher, "tracker_active", False)
                or getattr(launcher, "tracker", None)
            )
        )
        if launcher is not None:
            launcher.stop_tracker(timeout=5.0)
            if not self._wait_tracker_stopped(launcher, 5.0):
                self._resume_services(tracker_was_running, False)
                self._abort_install(
                    "tracker-busy", "The tracker did not stop in time.", stopped=True
                )
                return
        try:
            self._release_db_handles()
        except Exception as exc:
            self._log(f"releasing database handles failed: {exc}")
        overlay = None
        overlay_was_running = False
        try:
            overlay = self._overlay()
            overlay_was_running = bool(overlay.running)
            overlay.stop()
        except Exception as exc:
            self._log(f"stopping the overlay failed: {exc}")
        with self._lock:
            abandoned = self._handoff_abandoned
            self._spawning = not abandoned
        if abandoned:
            # The --no-gui wait gave up and already restarted tracking.
            self._log("hand-off abandoned before the installer was spawned")
            self._resume_services(False, overlay_was_running)
            return
        try:
            self._installer.install_and_restart(plan)
        except Exception as exc:
            with self._lock:
                self._spawning = False
            self._resume_services(tracker_was_running, overlay_was_running)
            self._abort_install(
                "handoff-failed", f"Could not start the installer: {exc}", stopped=True
            )
            return
        self._log("hand-off spawned; exiting")
        with self._lock:
            self._spawning = False
            self._handoff_outcome = "exit"
        self._handoff_done.set()
        try:
            self._request_exit()
        finally:
            backstop = self._exit_backstop or (lambda: os._exit(0))
            timer = threading.Timer(EXIT_BACKSTOP_S, backstop)
            timer.daemon = True
            timer.start()

    def _startup_tasks(self) -> None:
        with self._lock:
            self._load_runtime()
            # "Install after this game" belongs to the session that armed it.
            if self._runtime.pop("pending_install", None) is not None:
                self._save_runtime()
        self._reconcile_pending()
        self._restore_cached()
        self._cleanup_stale(startup=True)
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / f"healthy-{self.current_version}").write_text(
                _utc_iso(self._clock()) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
        self._notify()

    def _record_result(self, pending: Dict[str, Any], ok: bool) -> None:
        self._runtime["last_result"] = {
            "from": pending.get("from"),
            "to": pending.get("to"),
            "notes_url": pending.get("notes_url"),
            "ok": ok,
            "at": _utc_iso(self._clock()),
            "acknowledged": False,
        }
        if not ok and parse_version(pending.get("to")) is not None:
            failed = list(self._runtime.get("failed_versions") or [])
            if pending["to"] not in failed:
                failed.append(pending["to"])
            self._runtime["failed_versions"] = failed[-5:]

    def _reconcile_pending(self) -> None:
        pending = _read_json(self._pending_file)
        failed_flag = self._launch_flags.get("update_failed")
        if not pending and not failed_flag:
            return
        if pending and versions_equal(pending.get("to"), self.current_version):
            with self._lock:
                self._record_result(pending, True)
                self._runtime.pop("download", None)
                self._runtime.pop("pending_install", None)
                self._save_runtime()
            for stale in stale_download_files(self.state_dir, []):
                stale.unlink(missing_ok=True)
            self._pending_file.unlink(missing_ok=True)
            message = f"Updated from {pending.get('from')} to {self.current_version}"
            self._log(message)
            self._console(message)
            self._reassert_after_update = True
            return
        if not pending:
            known = failed_flag if parse_version(failed_flag) is not None else None
            pending = {"from": self.current_version, "to": known}
        log = pending.get("log") or self._newest_install_log()
        with self._lock:
            self._record_result(pending, False)
            self._runtime.pop("pending_install", None)
            self._save_runtime()
        self._pending_file.unlink(missing_ok=True)
        code = "install-failed" if failed_flag else "install-not-applied"
        if pending.get("to"):
            message = f"The update to v{pending.get('to')} was not installed. Details: {log}"
        else:
            message = f"The last update did not finish. Details: {log}"
        self._log(message)
        self._console(message)
        with self._lock:
            self._state = "error"
            self._error = {"code": code, "message": message}

    def _newest_install_log(self) -> str:
        logs = list(self.state_dir.glob("install-*.log")) + list(self.state_dir.glob("swap-*.log"))
        try:
            newest = max(logs, key=lambda path: path.stat().st_mtime) if logs else None
        except OSError:
            newest = None
        return str(newest or self.state_dir)

    def _restore_cached(self) -> None:
        raw = self._runtime.get("manifest")
        signature = self._runtime.get("signature")
        if not raw or not signature:
            return
        try:
            manifest = self._load_manifest(str(raw).encode("utf-8"), signature)
        except ManifestError as exc:
            self._log(f"cached manifest rejected: {exc}")
            with self._lock:
                for key in ("manifest", "signature", "etag"):
                    self._runtime.pop(key, None)
                self._save_runtime()
            return
        if self._state == "error":
            # A failed install keeps its verified download for a retry.
            asset = select_asset(
                manifest,
                platform=self._platform,
                arch=self._arch,
                install_kind=self.install_info().kind,
            )
            record = self._runtime.get("download") or {}
            with self._lock:
                self._latest, self._asset = manifest, asset
                if asset and record.get("sha256") == asset.sha256 and record.get("path"):
                    cached = Path(record["path"])
                    if verify_file(cached, asset.sha256, asset.size):
                        self._download_path = cached
            return
        if self._state in ("disabled", "unsupported"):
            return
        self._apply_manifest(manifest)

    def _cleanup_stale(self, *, startup: bool) -> None:
        record = self._runtime.get("download") or {}
        keep = [record["name"]] if record.get("name") and self._download_path else []
        if self._state in ("available", "downloading") and self._asset is not None:
            keep.append(self._asset.name)  # a resumable .part
        for stale in stale_download_files(self.state_dir, keep):
            stale.unlink(missing_ok=True)
        if not keep and record:
            with self._lock:
                self._runtime.pop("download", None)
                self._save_runtime()
        if startup:
            self._remove_stage_dirs()
            for healthy in self.state_dir.glob("healthy-*"):
                if healthy.name != f"healthy-{self.current_version}":
                    healthy.unlink(missing_ok=True)

    def _healthy_tasks(self) -> None:
        if self._healthy_done or self._started_at is None:
            return
        if self._monotonic() - self._started_at < HEALTHY_AFTER_S:
            return
        self._healthy_done = True
        info = self.install_info()
        rollbacks = [self.state_dir / installer_module.ROLLBACK_DIR_NAME]
        if info.app_path is not None:
            rollbacks.append(Path(info.app_path).parent / installer_module.SIBLING_ROLLBACK_NAME)
        for folder in rollbacks:
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
                self._log(f"removed rollback copy {folder}")
        logs = sorted(self.state_dir.glob("install-*.log")) + sorted(
            self.state_dir.glob("swap-*.log")
        )
        for old in logs[:-3]:
            old.unlink(missing_ok=True)
        if self._reassert_after_update:
            self._reassert_login_start()

    def _reassert_login_start(self) -> None:
        try:
            from .startup import registration_status, set_start_at_login

            if self._settings().start_at_login and not registration_status().registered:
                set_start_at_login(True)
                self._log("re-registered start at login after the update")
        except Exception as exc:
            self._log(f"could not re-register start at login: {exc}")
