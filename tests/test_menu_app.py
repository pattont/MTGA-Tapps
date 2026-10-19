from pathlib import Path

from PyQt6.QtGui import QImage

from mtga_tracker import menu_app


class _FakeSetProgName:
    def __init__(self):
        self.argtypes = None
        self.restype = object()
        self.calls = []

    def __call__(self, value):
        self.calls.append(value)


def test_set_macos_process_name_uses_native_program_name(monkeypatch):
    setter = _FakeSetProgName()
    library = type("FakeLibrary", (), {"setprogname": setter})()
    monkeypatch.setattr(menu_app.sys, "platform", "darwin")
    monkeypatch.setattr(menu_app.ctypes, "CDLL", lambda _name: library)

    menu_app._set_macos_process_name("Tapps Tracker")

    assert setter.calls == [b"Tapps Tracker"]
    assert setter.argtypes == [menu_app.ctypes.c_char_p]
    assert setter.restype is None


def test_set_macos_process_name_is_noop_off_macos(monkeypatch):
    monkeypatch.setattr(menu_app.sys, "platform", "linux")
    monkeypatch.setattr(
        menu_app.ctypes,
        "CDLL",
        lambda _name: (_ for _ in ()).throw(AssertionError("must not load native library")),
    )

    menu_app._set_macos_process_name("Tapps Tracker")


class _FakeLock:
    def __init__(self, path, *, acquired):
        self.path = path
        self.acquired = acquired
        self.timeout = None

    def tryLock(self, timeout):  # noqa: N802 - Qt API
        self.timeout = timeout
        return self.acquired


def test_instance_lock_is_shared_per_user(monkeypatch, tmp_path):
    created = []

    def make_lock(path):
        lock = _FakeLock(path, acquired=True)
        created.append(lock)
        return lock

    monkeypatch.setattr(menu_app.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(menu_app.os, "getuid", lambda: 501)
    monkeypatch.setattr(menu_app, "QLockFile", make_lock)

    lock = menu_app._acquire_instance_lock()

    assert lock is created[0]
    assert lock.path == str(tmp_path / "mtga-tracker-501.lock")
    assert lock.timeout == 0


def test_instance_lock_rejects_duplicate_launcher(monkeypatch):
    monkeypatch.setattr(
        menu_app,
        "QLockFile",
        lambda _path: _FakeLock(_path, acquired=False),
    )

    assert menu_app._acquire_instance_lock() is None


class _FakeTooltipTray:
    def __init__(self):
        self.tooltip = None

    def setToolTip(self, tooltip):  # noqa: N802 - Qt API
        self.tooltip = tooltip


def test_tray_tooltip_uses_application_identity():
    tray = _FakeTooltipTray()

    menu_app._set_tray_tooltip(tray)

    assert tray.tooltip == "Tapps Tracker"


class _FakeMenu:
    def __init__(self):
        self.popup_positions = []

    def popup(self, position):
        self.popup_positions.append(position)


def test_tray_click_uses_native_context_menu_on_macos(monkeypatch):
    fake_controller = type("FakeController", (), {"menu": _FakeMenu()})()
    monkeypatch.setattr(menu_app.sys, "platform", "darwin")
    monkeypatch.setattr(
        menu_app.QCursor,
        "pos",
        lambda: (_ for _ in ()).throw(AssertionError("must not manually open menu")),
    )

    menu_app.MenuBarController._tray_activated(
        fake_controller,
        menu_app.QSystemTrayIcon.ActivationReason.Trigger,
    )

    assert fake_controller.menu.popup_positions == []


def test_tray_click_manually_opens_menu_off_macos(monkeypatch):
    position = object()
    fake_controller = type(
        "FakeController",
        (),
        {"menu": _FakeMenu(), "_tray_menu_position": lambda self: position},
    )()
    monkeypatch.setattr(menu_app.sys, "platform", "linux")

    for reason in (
        menu_app.QSystemTrayIcon.ActivationReason.Trigger,
        menu_app.QSystemTrayIcon.ActivationReason.Context,
    ):
        menu_app.MenuBarController._tray_activated(fake_controller, reason)

    # Left and right click both open it, where _tray_menu_position says.
    assert fake_controller.menu.popup_positions == [position, position]


class _FakeTrayIcon:
    def __init__(self, _path):
        self.mask_values = []

    def isNull(self):  # noqa: N802 - Qt API
        return False

    def setIsMask(self, value):  # noqa: N802 - Qt API
        self.mask_values.append(value)


def test_tray_icon_is_adaptive_mask_on_macos(monkeypatch):
    icon = _FakeTrayIcon("unused")
    monkeypatch.setattr(menu_app.sys, "platform", "darwin")
    monkeypatch.setattr(menu_app, "QIcon", lambda _path: icon)

    result = menu_app.MenuBarController._tray_icon(object())

    assert result is icon
    assert icon.mask_values == [True]


def test_tray_icon_is_not_forced_to_mask_off_macos(monkeypatch):
    icon = _FakeTrayIcon("unused")
    monkeypatch.setattr(menu_app.sys, "platform", "linux")
    monkeypatch.setattr(menu_app, "QIcon", lambda _path: icon)

    result = menu_app.MenuBarController._tray_icon(object())

    assert result is icon
    assert icon.mask_values == []


def test_runtime_app_icon_has_transparent_corners():
    asset_path = Path(menu_app.__file__).resolve().parent / "assets" / "app-icon.png"
    image = QImage(str(asset_path))

    assert not image.isNull()
    assert image.width() == 1024
    assert image.height() == 1024
    assert image.hasAlphaChannel()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(image.width() - 1, image.height() - 1).alpha() == 0
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 255


def test_replay_fragment_targets_list_or_game():
    assert menu_app.replay_fragment(None) == "/#/replay"
    assert menu_app.replay_fragment("") == "/#/replay"
    assert menu_app.replay_fragment("abc-1") == "/#/replay/abc-1"
    assert menu_app.replay_fragment("a/b c") == "/#/replay/a%2Fb%20c"


def test_newest_finished_game_id_reads_latest_ended_game(tmp_path):
    import sqlite3

    db_path = tmp_path / "tracker.sqlite3"
    assert menu_app.newest_finished_game_id(db_path) is None
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE games (id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT)")
        conn.executemany(
            "INSERT INTO games VALUES (?, ?, ?)",
            [
                ("old", "2026-01-01T10:00:00", "2026-01-01T10:10:00"),
                ("new", "2026-01-02T10:00:00", "2026-01-02T10:10:00"),
                ("running", "2026-01-03T10:00:00", None),
            ],
        )
    assert menu_app.newest_finished_game_id(db_path) == "new"


def test_newest_finished_game_id_tolerates_a_database_without_games(tmp_path):
    import sqlite3

    db_path = tmp_path / "empty.sqlite3"
    sqlite3.connect(db_path).close()
    assert menu_app.newest_finished_game_id(db_path) is None


def test_tray_update_item_mirrors_the_updater(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from PyQt6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("MTGA_TRACKER_DISABLE_UPDATES", "1")
    application = QApplication.instance() or QApplication([])
    args = SimpleNamespace(
        host="127.0.0.1",
        port=0,
        db=tmp_path / "t.sqlite3",
        log_path=None,
        no_browser=True,
        after_update=False,
        updated_from=None,
        update_failed=None,
    )
    controller = menu_app.MenuBarController(application, args)
    messages = []
    monkeypatch.setattr(controller.tray, "showMessage", lambda *a: messages.append(a[1]))
    action = controller.update_action
    assert not action.isVisible()

    controller._sync_update_action({"state": "available", "latest_version": "0.6.6"})
    assert action.isVisible() and action.text() == "Update available: v0.6.6…"
    controller._sync_update_action(
        {"state": "downloading", "latest_version": "0.6.6", "progress": {"fraction": 0.42}}
    )
    assert action.text() == "Downloading update… 42%"
    controller._sync_update_action({"state": "ready", "latest_version": "0.6.6"})
    assert action.text() == "Restart to Update (v0.6.6)"
    assert messages and "ready" in messages[0]
    controller._sync_update_action({"state": "installing", "latest_version": "0.6.6"})
    assert action.text() == "Restarting…"
    controller._sync_update_action({"state": "up_to_date"})
    assert not action.isVisible()
    # The tracker-status slot is still a method (an attribute once shadowed it).
    controller._update_status("tracker-running")
    assert controller.status_action.text() == "Tracker: Running"


def test_abandoned_install_and_quit_is_reported_then_quits(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from PyQt6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("MTGA_TRACKER_DISABLE_UPDATES", "1")
    application = QApplication.instance() or QApplication([])
    args = SimpleNamespace(
        host="127.0.0.1",
        port=0,
        db=tmp_path / "t.sqlite3",
        log_path=None,
        no_browser=True,
        after_update=False,
        updated_from=None,
        update_failed=None,
    )
    controller = menu_app.MenuBarController(application, args)
    warnings, quits = [], []
    monkeypatch.setattr(menu_app.QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    monkeypatch.setattr(controller.app, "quit", lambda: quits.append(True))
    controller.updates = SimpleNamespace(
        status=lambda: {
            "state": "error",
            "error": {"code": "backup-failed", "message": "disk full"},
        }
    )
    controller._quitting_for_update = True
    controller._on_update_exit()
    assert quits == [True] and "disk full" in warnings[0]
    # A successful hand-off quits without a message.
    controller.updates = SimpleNamespace(status=lambda: {"state": "installing", "error": None})
    controller._on_update_exit()
    assert quits == [True, True] and len(warnings) == 1
