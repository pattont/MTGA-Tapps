import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

from mtga_tracker import startup


def test_macos_registration_round_trip(tmp_path):
    bundle = tmp_path / "Applications" / "MTGA Tracker.app"
    bundle.mkdir(parents=True)
    arguments = startup._macos_arguments(bundle)

    startup._set_macos_registered(arguments, True, home=tmp_path)

    plist_path = startup._macos_plist_path(tmp_path)
    assert startup._macos_registered(arguments, home=tmp_path) is True
    with plist_path.open("rb") as stream:
        document = plistlib.load(stream)
    assert document == {
        "Label": startup.MACOS_LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            "/usr/bin/open",
            "-g",
            str(bundle),
            "--args",
            "--login-start",
        ],
        "RunAtLoad": True,
    }

    startup._set_macos_registered(arguments, False, home=tmp_path)

    assert plist_path.exists() is False
    assert startup._macos_registered(arguments, home=tmp_path) is False


def test_macos_registration_detects_a_stale_bundle(tmp_path):
    original = tmp_path / "MTGA Tracker.app"
    moved = tmp_path / "Applications" / "MTGA Tracker.app"
    original.mkdir()
    moved.mkdir(parents=True)
    startup._set_macos_registered(startup._macos_arguments(original), True, home=tmp_path)

    assert startup._macos_registered(startup._macos_arguments(moved), home=tmp_path) is False


def test_windows_command_quotes_an_executable_path_with_spaces():
    executable = Path(r"C:\Program Files\MTGA Tracker\MTGA Tracker.exe")

    assert startup._windows_command([str(executable), startup.LOGIN_ARGUMENT]) == (
        '"C:\\Program Files\\MTGA Tracker\\MTGA Tracker.exe" --login-start'
    )


def test_windows_registration_round_trip(monkeypatch):
    values = {}

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def query_value(_key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_SET_VALUE=2,
        REG_SZ=1,
        CreateKey=lambda *_args: Key(),
        OpenKey=lambda *_args: Key(),
        QueryValueEx=query_value,
        SetValueEx=lambda _key, name, _reserved, _kind, value: values.__setitem__(name, value),
        DeleteValue=lambda _key, name: values.pop(name),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    executable = Path(r"C:\Program Files\MTGA Tracker\MTGA Tracker.exe")
    arguments = [str(executable), startup.LOGIN_ARGUMENT]

    startup._set_windows_registered(arguments, True)

    assert startup._windows_registered(arguments) is True
    assert list(values) == [startup.WINDOWS_VALUE_NAME]

    startup._set_windows_registered(arguments, False)

    assert startup._windows_registered(arguments) is False


def test_source_checkout_uses_the_current_python_environment(monkeypatch):
    monkeypatch.delattr(startup.sys, "frozen", raising=False)
    monkeypatch.setattr(startup.sys, "platform", "darwin")
    monkeypatch.setattr(startup.sys, "executable", "/tmp/tapps-venv/bin/python")

    target = startup._launch_target()

    assert target == (
        "macos",
        [
            str(Path("/tmp/tapps-venv/bin/python").resolve()),
            "-m",
            "mtga_tracker.app",
            "--login-start",
        ],
    )


def test_unsupported_platform_reports_login_start_unavailable(monkeypatch):
    monkeypatch.setattr(startup.sys, "platform", "linux")

    status = startup.registration_status()

    assert status.available is False
    assert status.registered is False
    assert startup.set_start_at_login(False) == status


def test_macos_app_running_from_a_mounted_image_is_not_registered(monkeypatch):
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(startup.sys, "platform", "darwin")
    monkeypatch.setattr(
        startup,
        "_macos_app_bundle",
        lambda: Path("/Volumes/Tapps Tracker/MTGA Tracker.app"),
    )

    assert startup.registration_status().available is False
