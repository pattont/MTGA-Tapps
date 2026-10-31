"""Per-OS update hand-off with fakes for subprocess and the registry. The
swap helper itself runs only against dummy bundles in a temp folder, with
its relaunch suppressed; nothing here touches an installed app."""

import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mtga_tracker import update_install as ui


def _plan(tmp_path, **overrides):
    values = dict(
        asset_path=tmp_path / "updates" / "MTGA-Tracker-0.6.6-setup.exe",
        asset_kind="inno-setup",
        install_kind="windows-installer",
        from_version="0.6.5.3",
        to_version="0.6.6",
        parent_pid=4242,
        updates_dir=tmp_path / "updates",
        app_path=tmp_path / "MTGA Tracker",
        executable=Path(r"C:\Users\Me\AppData\Local\Programs\MTGA Tracker\MTGA Tracker.exe"),
        log_path=Path(r"C:\Users\Me\AppData\Local\MTGA Tracker\updates\install-0.6.6.log"),
    )
    values.update(overrides)
    return ui.InstallPlan(**values)


# --- detection ------------------------------------------------------------------


def _bundle(tmp_path, root="Applications"):
    exe = tmp_path / root / "MTGA Tracker.app" / "Contents" / "MacOS" / "MTGA Tracker"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    return exe


def test_detect_source_and_linux():
    assert ui.detect_install(frozen=False).kind == "source"
    assert ui.detect_install(frozen=False).reason == "source"
    linux = ui.detect_install(
        frozen=True, executable=Path("/opt/t/t"), platform="linux", version="0.6.6"
    )
    assert (linux.kind, linux.can_install, linux.reason) == ("linux", False, "unsupported-platform")


def test_detect_macos_bundle_and_refusals(tmp_path):
    exe = _bundle(tmp_path)
    info = ui.detect_install(frozen=True, executable=exe, platform="darwin", version="0.6.5.3")
    assert info.kind == "macos-app" and info.can_install
    assert info.app_path == (tmp_path / "Applications" / "MTGA Tracker.app").resolve()

    dev = ui.detect_install(frozen=True, executable=exe, platform="darwin", version="0.6.6.dev1+g1")
    assert (dev.can_install, dev.reason) == (False, "unknown-version")

    readonly = ui.detect_install(
        frozen=True, executable=exe, platform="darwin", version="0.6.6", access=lambda *_a: False
    )
    assert readonly.reason == "not-writable"

    assert ui.macos_bundle_refusal(Path("/Volumes/MTGA Tracker/MTGA Tracker.app")) == "translocated"
    assert (
        ui.macos_bundle_refusal(Path("/private/var/folders/x/AppTranslocation/y/MTGA Tracker.app"))
        == "translocated"
    )


def _registry(**locations):
    return lambda hive, view: locations.get(f"{hive}:{view}")


def test_detect_windows_install_modes(tmp_path):
    exe = tmp_path / "Programs" / "MTGA Tracker" / "MTGA Tracker.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    location = str(exe.parent) + "\\"

    user = ui.detect_install(
        frozen=True,
        executable=exe,
        platform="win32",
        version="0.6.5.3",
        registry_reader=_registry(**{"HKCU:default": location}),
        samefile=lambda a, b: Path(a.rstrip("\\")).resolve() == Path(b).resolve(),
    )
    assert (user.kind, user.install_mode, user.can_install, user.needs_elevation) == (
        "windows-installer",
        "user",
        True,
        False,
    )
    admin = ui.detect_install(
        frozen=True,
        executable=exe,
        platform="win32",
        version="0.6.5.3",
        registry_reader=_registry(**{"HKLM:32": location}),
        samefile=lambda a, b: Path(a.rstrip("\\")).resolve() == Path(b).resolve(),
    )
    assert admin.install_mode == "admin" and admin.needs_elevation

    moved = ui.detect_install(
        frozen=True,
        executable=exe,
        platform="win32",
        version="0.6.5.3",
        registry_reader=_registry(**{"HKCU:default": r"D:\Elsewhere"}),
        samefile=lambda a, b: False,
    )
    assert (moved.kind, moved.reason) == ("windows-portable", "moved-install")

    portable = ui.detect_install(
        frozen=True,
        executable=exe,
        platform="win32",
        version="0.6.5.3",
        registry_reader=_registry(),
    )
    assert (portable.kind, portable.reason) == ("windows-portable", "portable")


def test_registry_lookup_order_is_user_then_both_hklm_views(tmp_path):
    seen = []

    def reader(hive, view):
        seen.append((hive, view))
        return None

    ui.inno_install_mode(tmp_path / "x.exe", reader=reader)
    assert seen == [("HKCU", "default"), ("HKLM", "32"), ("HKLM", "64")]
    assert ui.INNO_UNINSTALL_KEY.endswith(r"\Uninstall\{1F54E322-28D9-4929-8292-F5AAAA12CB5F}_is1")


# --- Windows hand-off --------------------------------------------------------------


def test_windows_command_line_is_exact(tmp_path):
    plan = _plan(tmp_path)
    assert ui.windows_command(plan) == (
        f'"{plan.asset_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL '
        "/CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS "
        f'/LOG="{plan.log_path}" /CURRENTUSER /WAITPID=4242 /RELAUNCH=1 '
        f'/UPDATEDFROM=0.6.5.3 /RELAUNCHEXE="{plan.executable}"'
    )
    admin_quit = ui.windows_command(_plan(tmp_path, all_users=True, relaunch=False))
    assert " /ALLUSERS " in admin_quit and "/CURRENTUSER" not in admin_quit
    assert "/RELAUNCH=1" not in admin_quit


def test_windows_spawn_is_detached_with_a_clean_environment(tmp_path):
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=1)

    reset = []
    environ = {
        "PATH": r"C:\app\_internal;C:\Windows",
        "_PYI_APPLICATION_HOME_DIR": "x",
        "KEEP": "1",
    }
    plan = _plan(tmp_path, executable=Path(r"C:\app\MTGA Tracker.exe"))
    ui.spawn_windows_installer(
        plan, popen=popen, reset_dll_directory=lambda: reset.append(True), environ=environ
    )
    command, kwargs = calls[0]
    assert isinstance(command, str) and command == ui.windows_command(plan)
    assert kwargs["creationflags"] == 0x00000008 | 0x00000200 | 0x01000000
    env = kwargs["env"]
    assert "_PYI_APPLICATION_HOME_DIR" not in env and env["KEEP"] == "1"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert reset == [True]
    assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["close_fds"] is True


def test_windows_spawn_falls_back_without_breakaway_and_retries_sharing_violations(tmp_path):
    attempts = []

    def popen(command, **kwargs):
        attempts.append(kwargs["creationflags"])
        if len(attempts) == 1:
            error = OSError("access denied")
            error.winerror = 5
            raise error
        if len(attempts) == 2:
            error = OSError("sharing violation")
            error.winerror = 32
            raise error
        return SimpleNamespace(pid=2)

    sleeps = []
    ui.spawn_windows_installer(
        _plan(tmp_path), popen=popen, sleep=sleeps.append, reset_dll_directory=lambda: None
    )
    assert attempts[0] & 0x01000000 and not attempts[1] & 0x01000000
    assert sleeps == [0.5] and len(attempts) == 3


# --- macOS hand-off ----------------------------------------------------------------


def _fake_runner(tmp_path, *, version="0.6.6", bundle_id=ui.BUNDLE_ID, codesign_ok=True):
    calls = []

    def run(args, **_kwargs):
        calls.append(list(args))
        if args[0] == "/usr/bin/ditto" and args[1] == "-x":
            app = Path(args[-1]) / "MTGA Tracker.app" / "Contents"
            app.mkdir(parents=True)
            with open(app / "Info.plist", "wb") as handle:
                plistlib.dump(
                    {"CFBundleIdentifier": bundle_id, "CFBundleShortVersionString": version},
                    handle,
                )
        if args[0] == "/usr/bin/codesign":
            return SimpleNamespace(returncode=0 if codesign_ok else 1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run, calls


def _mac_plan(tmp_path, **overrides):
    zip_path = tmp_path / "updates" / "MTGA-Tracker-0.6.6-macos.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(b"zip")
    target = tmp_path / "Applications" / "MTGA Tracker.app"
    target.mkdir(parents=True, exist_ok=True)
    values = dict(
        asset_path=zip_path,
        asset_kind="app-zip",
        install_kind="macos-app",
        app_path=target,
        executable=None,
        log_path=None,
    )
    values.update(overrides)
    return _plan(tmp_path, **values)


def test_macos_stage_extracts_with_ditto_and_verifies(tmp_path):
    run, calls = _fake_runner(tmp_path)
    plan = ui.prepare_install(_mac_plan(tmp_path), run=run)
    assert calls[0][:4] == ["/usr/bin/ditto", "-x", "-k", "--noqtn"]
    assert calls[1][:4] == ["/usr/bin/codesign", "--verify", "--deep", "--strict"]
    assert plan.staged_app == tmp_path / "updates" / "stage" / "MTGA Tracker.app"
    assert plan.rollback_dir == tmp_path / "updates" / "rollback"
    assert plan.staged_version == "0.6.6"
    assert plan.log_path == tmp_path / "updates" / "swap-0.6.6.log"


@pytest.mark.parametrize(
    "runner_kwargs,code",
    [
        ({"codesign_ok": False}, "codesign-failed"),
        ({"version": "0.6.5"}, "bad-archive"),
        ({"bundle_id": "com.example.evil"}, "bad-archive"),
    ],
)
def test_macos_stage_refuses_bad_bundles(tmp_path, runner_kwargs, code):
    run, _calls = _fake_runner(tmp_path, **runner_kwargs)
    with pytest.raises(ui.InstallError) as caught:
        ui.prepare_install(_mac_plan(tmp_path), run=run)
    assert caught.value.code == code


def test_macos_stage_uses_a_sibling_folder_across_volumes(tmp_path):
    plan = _mac_plan(tmp_path)
    devices = {plan.updates_dir: 1, plan.app_path.parent: 2}
    stage, rollback = ui.macos_work_dirs(plan, device=lambda p: devices.get(Path(p)))
    assert stage == plan.app_path.parent / ".tapps-update-0.6.6"
    assert rollback == plan.app_path.parent / ".tapps-update-rollback"


def test_macos_dmg_fallback_attaches_copies_and_detaches(tmp_path):
    calls = []

    def run(args, **_kwargs):
        calls.append(list(args))
        if args[:2] == ["/usr/bin/hdiutil", "attach"]:
            mount = Path(args[args.index("-mountpoint") + 1])
            (mount / "MTGA Tracker.app").mkdir()
        if args[0] == "/usr/bin/ditto":
            contents = Path(args[-1]) / "Contents"
            contents.mkdir(parents=True)
            with open(contents / "Info.plist", "wb") as handle:
                plistlib.dump(
                    {"CFBundleIdentifier": ui.BUNDLE_ID, "CFBundleShortVersionString": "0.6.6"},
                    handle,
                )
        return SimpleNamespace(returncode=0)

    dmg = tmp_path / "updates" / "MTGA-Tracker-0.6.6.dmg"
    dmg.parent.mkdir(parents=True, exist_ok=True)
    dmg.write_bytes(b"dmg")
    plan = ui.prepare_install(_mac_plan(tmp_path, asset_path=dmg, asset_kind="dmg"), run=run)
    attach = calls[0]
    assert attach[:2] == ["/usr/bin/hdiutil", "attach"]
    for flag in ("-nobrowse", "-noautoopen", "-noverify", "-readonly", "-mountpoint"):
        assert flag in attach
    assert calls[1][:2] == ["/usr/bin/ditto", "--noqtn"]
    assert calls[2][:2] == ["/usr/bin/hdiutil", "detach"]
    assert calls[3][0] == "/usr/bin/codesign"
    assert plan.staged_app.name == "MTGA Tracker.app"


def test_swap_helper_matches_the_reviewed_script():
    script = ui.MAC_SWAP_SCRIPT
    assert 'relaunch --after-update --updated-from "$OLD_VER"' in script
    assert script.count("relaunch --update-failed") == 6
    reviewed = Path(__file__).resolve().parents[1] / "docs/plans/auto-update/tapps_mac_swap.sh"
    if reviewed.is_file():
        expected = reviewed.read_text(encoding="utf-8").replace(
            'relaunch --updated-from "$OLD_VER"',
            'relaunch --after-update --updated-from "$OLD_VER"',
        )
        assert script == expected


def test_swap_helper_is_valid_bash(tmp_path):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")
    script = ui.write_swap_helper(tmp_path)
    assert os.access(script, os.X_OK)
    assert subprocess.run([bash, "-n", str(script)]).returncode == 0


def test_macos_spawn_is_detached_and_can_suppress_the_relaunch(tmp_path):
    calls = []

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(pid=3)

    run, _ = _fake_runner(tmp_path)
    plan = ui.prepare_install(_mac_plan(tmp_path, relaunch=False), run=run)
    ui.install_and_restart(plan, popen=popen, run=run)
    args, kwargs = calls[0]
    assert args[:2] == ["/bin/bash", str(tmp_path / "updates" / ui.SWAP_SCRIPT_NAME)]
    assert args[2:] == [
        "4242",
        str(plan.staged_app),
        str(plan.app_path),
        str(plan.rollback_dir),
        "0.6.5.3",
        "0.6.6",
        ui.BUNDLE_ID,
    ]
    assert kwargs["start_new_session"] is True and kwargs["cwd"] == "/"
    assert kwargs["env"]["TAPPS_SWAP_NO_LAUNCH"] == "1"
    assert not any(key.startswith("_PYI_") for key in kwargs["env"])


def test_unsupported_install_kinds_raise(tmp_path):
    plan = _plan(tmp_path, install_kind="linux")
    plan.asset_path.parent.mkdir(parents=True, exist_ok=True)
    plan.asset_path.write_bytes(b"x")
    with pytest.raises(ui.InstallError):
        ui.prepare_install(plan)
    with pytest.raises(ui.InstallError) as caught:
        ui.prepare_install(_plan(tmp_path, asset_path=tmp_path / "missing.exe"))
    assert caught.value.code == "missing-download"


# --- the real helper on dummy bundles (macOS only) -------------------------------------


def _dummy_bundle(folder: Path, version: str) -> Path:
    app = folder / "MTGA Tracker.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    exe = app / "Contents" / "MacOS" / "MTGA Tracker"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    with open(app / "Contents" / "Info.plist", "wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": ui.BUNDLE_ID,
                "CFBundleShortVersionString": version,
                "CFBundleExecutable": "MTGA Tracker",
                "CFBundlePackageType": "APPL",
            },
            handle,
        )
    return app


def _finished_pid() -> int:
    process = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    process.wait()
    return process.pid


@pytest.mark.skipif(sys.platform != "darwin", reason="the swap helper is macOS-only")
@pytest.mark.parametrize("signed", [True, False])
def test_swap_helper_on_dummy_bundles(tmp_path, signed):
    target = _dummy_bundle(tmp_path / "Applications", "0.6.5.3")
    staged = _dummy_bundle(tmp_path / "updates" / "stage", "0.6.6")
    if signed:
        result = subprocess.run(
            ["/usr/bin/codesign", "--force", "--deep", "-s", "-", str(staged)], capture_output=True
        )
        if result.returncode != 0:
            pytest.skip("ad-hoc signing is unavailable here")
    script = ui.write_swap_helper(tmp_path / "updates")
    rollback = tmp_path / "updates" / "rollback"
    env = dict(os.environ, TAPPS_SWAP_NO_LAUNCH="1", TAPPS_SWAP_WAIT_SECONDS="5")
    result = subprocess.run(
        [
            "/bin/bash",
            str(script),
            str(_finished_pid()),
            str(staged),
            str(target),
            str(rollback),
            "0.6.5.3",
            "0.6.6",
            ui.BUNDLE_ID,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    with open(target / "Contents" / "Info.plist", "rb") as handle:
        version = plistlib.load(handle)["CFBundleShortVersionString"]
    if signed:
        assert result.returncode == 0, result.stdout + result.stderr
        assert version == "0.6.6"
        assert (rollback / "MTGA Tracker.app").is_dir()
        assert "relaunch suppressed: --after-update --updated-from 0.6.5.3" in result.stdout
    else:
        assert result.returncode == 11
        assert version == "0.6.5.3" and staged.is_dir()


def test_detection_uses_the_paths_helpers(tmp_path, monkeypatch):
    from mtga_tracker import paths

    monkeypatch.setattr(paths, "current_platform_key", lambda: "linux")
    assert (
        ui.detect_install(frozen=True, executable=tmp_path / "t", version="0.6.6").kind == "linux"
    )
    seen = []
    monkeypatch.setattr(
        paths,
        "macos_bundle_location_issue",
        lambda bundle, access: seen.append(bundle) or "dmg-mounted",
    )
    exe = _bundle(tmp_path)
    info = ui.detect_install(frozen=True, executable=exe, platform="darwin", version="0.6.6")
    assert seen and info.reason == "translocated"  # a DMG copy keeps the existing reason


@pytest.mark.skipif(sys.platform != "darwin", reason="the swap helper is macOS-only")
def test_swap_helper_relaunches_the_old_app_when_the_overlay_will_not_quit(tmp_path):
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("perl is not available")
    target = _dummy_bundle(tmp_path / "Applications", "0.6.5.3")
    staged = _dummy_bundle(tmp_path / "updates" / "stage", "0.6.6")
    overlay = target / "Contents/Helpers/Tapps Overlay.app/Contents/MacOS/tapps-overlay"
    overlay.parent.mkdir(parents=True)
    # A stand-in overlay whose command line starts with the overlay path and
    # that ignores SIGTERM, as a hung overlay would.
    stubborn = subprocess.Popen(
        ["/bin/bash", "-c", f'exec -a "{overlay}" {perl} -e \'$SIG{{TERM}}="IGNORE"; sleep 60\''],
    )
    try:
        script = ui.write_swap_helper(tmp_path / "updates")
        env = dict(os.environ, TAPPS_SWAP_NO_LAUNCH="1", TAPPS_SWAP_WAIT_SECONDS="5")
        time.sleep(0.3)
        result = subprocess.run(
            [
                "/bin/bash",
                str(script),
                str(_finished_pid()),
                str(staged),
                str(target),
                str(tmp_path / "updates" / "rollback"),
                "0.6.5.3",
                "0.6.6",
                ui.BUNDLE_ID,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        stubborn.kill()
        stubborn.wait()
    assert result.returncode == 15, result.stdout + result.stderr
    assert "relaunch suppressed: --update-failed 0.6.6" in result.stdout
    with open(target / "Contents" / "Info.plist", "rb") as handle:
        assert plistlib.load(handle)["CFBundleShortVersionString"] == "0.6.5.3"
