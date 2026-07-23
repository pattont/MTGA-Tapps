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
