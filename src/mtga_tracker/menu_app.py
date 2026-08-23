"""PyQt menu-bar controller for the unified MTGA tracker application."""

from __future__ import annotations

import ctypes
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QStyle,
    QSystemTrayIcon,
)

from .app import CallbackTextStream, UnifiedLauncher
from .paths import DATA_DIR
from .settings import AppSettings, load_app_settings


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_APP_NAME = "MTGA Tracker"
_XTERM_BASE_COLORS = (
    "#000000",
    "#800000",
    "#008000",
    "#808000",
    "#000080",
    "#800080",
    "#008080",
    "#c0c0c0",
    "#808080",
    "#ff0000",
    "#00ff00",
    "#ffff00",
    "#0000ff",
    "#ff00ff",
    "#00ffff",
    "#ffffff",
)


def _xterm_color(index: int) -> QColor:
    """Convert an xterm 256-color index to a Qt color."""
    index = max(0, min(255, index))
    if index < 16:
        return QColor(_XTERM_BASE_COLORS[index])
    if index < 232:
        cube_index = index - 16
        levels = (0, 95, 135, 175, 215, 255)
        red = levels[cube_index // 36]
        green = levels[(cube_index // 6) % 6]
        blue = levels[cube_index % 6]
        return QColor(red, green, blue)
    gray = 8 + (index - 232) * 10
    return QColor(gray, gray, gray)


def _set_macos_process_name(name: str) -> None:
    """Set the Unix process label used by diagnostics such as Activity Monitor."""
    if sys.platform != "darwin":
        return
    try:
        setprogname = ctypes.CDLL(None).setprogname
        setprogname.argtypes = [ctypes.c_char_p]
        setprogname.restype = None
        setprogname(name.encode("utf-8"))
    except (AttributeError, OSError):
        return


def _instance_lock_path() -> Path:
    """Return one per-user lock path shared by source and packaged launches."""
    user_id = str(os.getuid()) if hasattr(os, "getuid") else os.getenv("USERNAME", "user")
    return Path(tempfile.gettempdir()) / f"mtga-tracker-{user_id}.lock"


def _acquire_instance_lock() -> QLockFile | None:
    """Keep duplicate source and packaged menu controllers from running together."""
    lock = QLockFile(str(_instance_lock_path()))
    if not lock.tryLock(0):
        return None
    return lock


def _set_tray_tooltip(tray: QSystemTrayIcon) -> None:
    tray.setToolTip(_APP_NAME)


class AppSignals(QObject):
    log_text = pyqtSignal(str)
    status_changed = pyqtSignal(str)


class LiveLogWindow(QMainWindow):
    """Read-only window containing the current tracker session output."""

    def __init__(
        self,
        window_icon: QIcon | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        settings = settings or AppSettings()
        # Windows appends the application display name ("MTGA Tracker") to
        # every window title, so the base title must not repeat it there.
        self.setWindowTitle("Live Log" if sys.platform == "win32" else "MTGA Tracker - Live Log")
        if window_icon is not None:
            self.setWindowIcon(window_icon)
        self.resize(settings.live_log_width, settings.live_log_height)
        self.setMinimumSize(820, 560)
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.document().setMaximumBlockCount(5000)
        log_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if sys.platform == "win32":
            # Windows' default fixed font is Courier New, which looks rough.
            # Prefer the modern terminal fonts that ship with Windows 10/11.
            families = set(QFontDatabase.families())
            for family in ("Cascadia Mono", "Cascadia Code", "Consolas"):
                if family in families:
                    log_font = QFont(family)
                    break
        log_font.setPointSize(max(12, log_font.pointSize()))
        self.log_view.setFont(log_font)
        self.setCentralWidget(self.log_view)
        self._text_format = QTextCharFormat()

    def _apply_ansi_sequence(self, sequence: str) -> None:
        if not sequence.endswith("m"):
            return
        try:
            codes = [int(value) if value else 0 for value in sequence[2:-1].split(";")]
        except ValueError:
            return
        index = 0
        while index < len(codes):
            code = codes[index]
            if code == 0:
                self._text_format = QTextCharFormat()
            elif code == 1:
                self._text_format.setFontWeight(QFont.Weight.Bold)
            elif code == 22:
                self._text_format.setFontWeight(QFont.Weight.Normal)
            elif code == 38 and codes[index : index + 2] == [38, 5] and index + 2 < len(codes):
                self._text_format.setForeground(_xterm_color(codes[index + 2]))
                index += 2
            elif code == 39:
                self._text_format.clearForeground()
            index += 1

    def append_text(self, text: str) -> None:
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        text_start = 0
        for match in _ANSI_ESCAPE.finditer(text):
            if match.start() > text_start:
                cursor.insertText(text[text_start : match.start()], self._text_format)
            self._apply_ansi_sequence(match.group(0))
            text_start = match.end()
        if text_start < len(text):
            cursor.insertText(text[text_start:], self._text_format)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        event.ignore()
        self.hide()


class MenuBarController(QObject):
    """Coordinate the native menu, tracker worker, dashboard, and log window."""

    STATUS_LABELS = {
        "tracker-starting": "Tracker: Starting",
        "tracker-running": "Tracker: Running",
        "tracker-stopped": "Tracker: Stopped",
        "tracker-error": "Tracker: Error",
        "dashboard-running": "Dashboard: Running",
        "dashboard-stopped": "Dashboard: Stopped",
    }

    def __init__(self, app: QApplication, args: Any):
        super().__init__()
        self.app = app
        self.args = args
        self.signals = AppSignals()
        self.app_icon = QIcon(str(_ASSET_DIR / "app-icon.png"))
        self.settings = load_app_settings()
        self.log_window = LiveLogWindow(self.app_icon, self.settings)
        self.log_stream = CallbackTextStream(self.signals.log_text.emit)
        self.launcher = UnifiedLauncher(
            host=args.host,
            port=args.port,
            db_path=args.db,
            log_path=args.log_path,
            output_stream=self.log_stream,
            status_callback=self.signals.status_changed.emit,
            use_colors=True,
        )
        self._shutting_down = False

        self.tray = QSystemTrayIcon(self._tray_icon(), self)
        _set_tray_tooltip(self.tray)
        self.menu = QMenu()

        self.status_action = QAction("Tracker: Starting", self)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()

        # Order matters (same on macOS and Windows): Live Log, Dashboard,
        # Deck Finder, Settings — then the utility items.
        self.show_log_action = QAction("Live Log", self)
        self.show_log_action.triggered.connect(self.open_live_log)
        self.menu.addAction(self.show_log_action)

        self.open_dashboard_action = QAction("Dashboard", self)
        self.open_dashboard_action.triggered.connect(lambda: self.open_dashboard())
        self.menu.addAction(self.open_dashboard_action)

        self.deck_downloader_action = QAction("Deck Finder", self)
        self.deck_downloader_action.triggered.connect(self.open_deck_downloader)
        self.menu.addAction(self.deck_downloader_action)

        self.settings_action = QAction("Settings", self)
        self.settings_action.triggered.connect(self.open_settings)
        self.menu.addAction(self.settings_action)

        self.open_data_action = QAction("Open Data Folder", self)
        self.open_data_action.triggered.connect(self.open_data_folder)
        self.menu.addAction(self.open_data_action)

        self.menu.addSeparator()
        self.toggle_tracker_action = QAction("Stop Tracking", self)
        self.toggle_tracker_action.triggered.connect(self.toggle_tracker)
        self.menu.addAction(self.toggle_tracker_action)

        self.menu.addSeparator()
        self.quit_action = QAction("Quit MTGA Tracker", self)
        self.quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.signals.log_text.connect(self.log_window.append_text)
        self.signals.status_changed.connect(self._update_status)
        self.app.aboutToQuit.connect(self.shutdown)

    def _tray_icon(self) -> QIcon:
        if sys.platform == "win32":
            # The monochrome template glyph vanishes on Windows' dark
            # taskbar; the colored app icon reads on any background.
            colored = QIcon(str(_ASSET_DIR / "app-icon.png"))
            if not colored.isNull():
                return colored
        icon = QIcon(str(_ASSET_DIR / "tray-iconTemplate.svg"))
        if not icon.isNull():
            if sys.platform == "darwin":
                icon.setIsMask(True)
            return icon
        return self.app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    def start(self) -> None:
        self.tray.show()
        # The live log now lives in the dashboard (#/live). The Qt window is
        # a buried debug fallback: set MTGA_TRACKER_QT_LOG=1 to get it back.
        if os.environ.get("MTGA_TRACKER_QT_LOG") == "1":
            self.show_live_log()
        try:
            url = self.launcher.start_dashboard()
            self.log_window.append_text(f"Dashboard: {url}\n")
            self.launcher.start_tracker(background=True)
            if not self.args.no_browser:
                QTimer.singleShot(350, self.open_dashboard)
        except Exception as exc:
            self.log_window.append_text(f"Application startup failed: {exc}\n")
            self.log_window.show()
            QMessageBox.critical(self.log_window, "MTGA Tracker", str(exc))

    def open_dashboard(self, fragment: str = "") -> None:
        try:
            self.launcher.open_dashboard(fragment)
        except Exception as exc:
            self.log_window.append_text(f"Could not open dashboard: {exc}\n")
            self.show_live_log()

    def open_deck_downloader(self) -> None:
        """Deck Finder lives inside the dashboard now (#/deck-finder)."""
        self.open_dashboard("/#/deck-finder")

    def open_live_log(self) -> None:
        """The live log lives in the dashboard now (#/live)."""
        self.open_dashboard("/#/live")

    def show_live_log(self) -> None:
        """Show the legacy Qt log window (debug fallback; see start())."""
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))

    def open_settings(self) -> None:
        """Settings live in the dashboard now (#/settings); the old Qt
        dialog stays as a fallback if the browser can't be opened."""
        try:
            self.launcher.open_dashboard("/#/settings")
            return
        except Exception as exc:
            self.log_window.append_text(f"⚠️ Could not open Settings page: {exc}\n")

        from .settings_dialog import open_settings_dialog

        try:
            if open_settings_dialog(self.log_window):
                self.log_window.append_text(
                    "⚙️ Settings saved — AI deck identification applies from the next game.\n"
                )
        except Exception as exc:
            self.log_window.append_text(f"⚠️ Could not open Settings: {exc}\n")

    def toggle_tracker(self) -> None:
        if self.launcher.tracker_is_running:
            self.toggle_tracker_action.setEnabled(False)
            self.launcher.stop_tracker()
        else:
            self.toggle_tracker_action.setEnabled(False)
            self.launcher.start_tracker(background=True)

    def _update_status(self, status: str) -> None:
        if status.startswith("tracker-"):
            self.status_action.setText(self.STATUS_LABELS.get(status, status))
            running = status in {"tracker-starting", "tracker-running"}
            self.toggle_tracker_action.setText("Stop Tracking" if running else "Start Tracking")
            self.toggle_tracker_action.setEnabled(status not in {"tracker-starting"})
            if status == "tracker-error":
                self.tray.showMessage(
                    "MTGA Tracker",
                    "Tracking stopped. Open the live log for details.",
                    QSystemTrayIcon.MessageIcon.Warning,
                    5000,
                )

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # macOS opens the registered context menu automatically. Manually
        # popping it there creates a second, overlapping copy of the menu.
        if (
            sys.platform != "darwin"
            and reason == QSystemTrayIcon.ActivationReason.Trigger
        ):
            self.menu.popup(QCursor.pos())

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.toggle_tracker_action.setEnabled(False)
        self.launcher.shutdown()
        self.tray.hide()


def run_menu_app(args: Any) -> int:
    _set_macos_process_name(_APP_NAME)
    QApplication.setApplicationName(_APP_NAME)
    QApplication.setApplicationDisplayName(_APP_NAME)
    QApplication.setOrganizationName(_APP_NAME)
    app = QApplication.instance() or QApplication([])
    instance_lock = _acquire_instance_lock()
    if instance_lock is None:
        # Windowed builds have no console — tell the user visibly. This is
        # the path hit when relaunching before the old process finishes
        # shutting down.
        QMessageBox.information(
            None,
            "MTGA Tracker",
            "MTGA Tracker is already running — look for its icon in the "
            "menu bar (macOS) or system tray (Windows).\n\n"
            "If you just quit it, wait a few seconds and try again.",
        )
        return 0
    # QApplication owns the lifetime of the lock for the complete event loop.
    app._mtga_instance_lock = instance_lock
    app.setApplicationName("MTGA Tracker")
    app.setApplicationDisplayName("MTGA Tracker")
    app.setOrganizationName("MTGA Tracker")
    app_icon = QIcon(str(_ASSET_DIR / "app-icon.png"))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    app.setQuitOnLastWindowClosed(False)
    controller = MenuBarController(app, args)
    controller.start()
    return app.exec()
