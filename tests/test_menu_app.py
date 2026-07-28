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

    menu_app._set_macos_process_name("MTGA Tracker")

    assert setter.calls == [b"MTGA Tracker"]
    assert setter.argtypes == [menu_app.ctypes.c_char_p]
    assert setter.restype is None


def test_set_macos_process_name_is_noop_off_macos(monkeypatch):
    monkeypatch.setattr(menu_app.sys, "platform", "linux")
    monkeypatch.setattr(
        menu_app.ctypes,
        "CDLL",
        lambda _name: (_ for _ in ()).throw(AssertionError("must not load native library")),
    )

    menu_app._set_macos_process_name("MTGA Tracker")


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

    assert tray.tooltip == "MTGA Tracker"


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
    fake_controller = type("FakeController", (), {"menu": _FakeMenu()})()
    position = object()
    monkeypatch.setattr(menu_app.sys, "platform", "linux")
    monkeypatch.setattr(menu_app.QCursor, "pos", lambda: position)

    menu_app.MenuBarController._tray_activated(
        fake_controller,
        menu_app.QSystemTrayIcon.ActivationReason.Trigger,
    )

    assert fake_controller.menu.popup_positions == [position]


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
