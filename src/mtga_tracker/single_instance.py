"""Process-wide single-instance guard for the unified tracker launcher."""

from __future__ import annotations

import errno
import os
import sys
import tempfile
from pathlib import Path
from typing import IO, Callable, Optional


_WINDOWS_ALREADY_EXISTS = 183
_WINDOWS_MUTEX_NAME = r"Local\TappsTracker.UnifiedLauncher"


def _default_lock_path() -> Path:
    """Return one lock path shared by source and installed launches."""
    user_id = str(os.getuid()) if hasattr(os, "getuid") else os.getenv("USERNAME", "user")
    return Path(tempfile.gettempdir()) / f"tapps-tracker-{user_id}.instance.lock"


class SingleInstanceGuard:
    """Hold an OS-owned lock for the lifetime of the tracker process.

    Windows uses a named mutex. POSIX systems use ``flock`` on a per-user
    temporary file. Both locks are released by the operating system when the
    process exits, including after a crash, so a stale marker cannot prevent a
    later launch.
    """

    def __init__(
        self,
        *,
        lock_path: Optional[Path] = None,
        mutex_name: str = _WINDOWS_MUTEX_NAME,
    ) -> None:
        self.lock_path = Path(lock_path) if lock_path is not None else _default_lock_path()
        self.mutex_name = mutex_name
        self._lock_file: Optional[IO[str]] = None
        self._mutex_handle: object | None = None
        self._close_mutex: Optional[Callable[[object], object]] = None

    def acquire(self) -> bool:
        """Acquire the guard without waiting; return false if one is held."""
        if self._lock_file is not None or self._mutex_handle is not None:
            return True
        if sys.platform == "win32":
            return self._acquire_windows_mutex()
        return self._acquire_posix_lock()

    def _acquire_windows_mutex(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        create_mutex.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        handle = create_mutex(None, False, self.mutex_name)
        if not handle:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, ctypes.FormatError(error_code))
        if ctypes.get_last_error() == _WINDOWS_ALREADY_EXISTS:
            close_handle(handle)
            return False

        self._mutex_handle = handle
        self._close_mutex = close_handle
        return True

    def _acquire_posix_lock(self) -> bool:
        import fcntl

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock_file.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise

        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"{os.getpid()}\n")
        lock_file.flush()
        self._lock_file = lock_file
        return True

    def release(self) -> None:
        """Release a held guard. Calling this more than once is safe."""
        lock_file = self._lock_file
        self._lock_file = None
        if lock_file is not None:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

        handle = self._mutex_handle
        close_mutex = self._close_mutex
        self._mutex_handle = None
        self._close_mutex = None
        if handle is not None and close_mutex is not None:
            close_mutex(handle)
