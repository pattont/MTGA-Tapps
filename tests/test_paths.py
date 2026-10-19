from pathlib import Path

from mtga_tracker import paths as paths_mod


def test_get_mtga_raw_card_db_folders_windows_common_paths(monkeypatch):
    monkeypatch.delenv("MTGA_DATA_DIR", raising=False)
    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Windows")

    expected = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\MTGA\MTGA_Data\Downloads\Raw"),
        Path(r"C:\Program Files\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw"),
        Path(r"C:\Program Files (x86)\Wizards of the Coast\MTGA\MTGA_Data\Downloads\Raw"),
    ]
    existing = {str(expected[0]), str(expected[2])}
    real_is_dir = Path.is_dir

    def fake_is_dir(self):
        s = str(self)
        if s in existing:
            return True
        if s in {str(p) for p in expected}:
            return False
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)

    assert paths_mod.get_mtga_raw_card_db_folders() == [expected[0], expected[2]]


def test_get_mtga_raw_card_db_folders_override_dir_takes_priority(tmp_path, monkeypatch):
    override = tmp_path / "Raw"
    override.mkdir()
    monkeypatch.setenv("MTGA_DATA_DIR", str(tmp_path / "ignored"))
    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Windows")

    assert paths_mod.get_mtga_raw_card_db_folders(str(override)) == [override]


def test_installed_app_data_dir_uses_macos_application_support(monkeypatch):
    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Darwin")

    assert paths_mod._installed_app_data_dir() == (
        Path.home() / "Library" / "Application Support" / "MTGA Tracker"
    )


def test_default_data_dir_honors_environment_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGA_TRACKER_DATA_DIR", str(tmp_path))

    assert paths_mod._default_data_dir() == tmp_path


def test_parse_steam_library_paths_handles_escaped_backslashes():
    vdf = '''
"libraryfolders"
{
    "0"
    {
        "path"		"C:\\\\Program Files (x86)\\\\Steam"
        "label"		""
    }
    "1"
    {
        "path"		"D:\\\\SteamLibrary"
    }
}
'''
    assert paths_mod._parse_steam_library_paths(vdf) == [
        r"C:\Program Files (x86)\Steam",
        r"D:\SteamLibrary",
    ]


def test_steam_mtga_raw_dirs_finds_secondary_library(tmp_path):
    steam_root = tmp_path / "Steam"
    library = tmp_path / "OtherDrive" / "SteamLibrary"
    raw = library / "steamapps" / "common" / "MTGA" / "MTGA_Data" / "Downloads" / "Raw"
    raw.mkdir(parents=True)
    vdf_dir = steam_root / "steamapps"
    vdf_dir.mkdir(parents=True)
    (vdf_dir / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n  "0"\n  {\n    "path"\t\t"%s"\n  }\n}\n'
        % str(library).replace("\\", "\\\\"),
        encoding="utf-8",
    )

    assert paths_mod._steam_mtga_raw_dirs(steam_root) == [raw]


def test_steam_mtga_raw_dirs_without_vdf_checks_default_root(tmp_path):
    steam_root = tmp_path / "Steam"
    raw = steam_root / "steamapps" / "common" / "MTGA" / "MTGA_Data" / "Downloads" / "Raw"
    raw.mkdir(parents=True)

    assert paths_mod._steam_mtga_raw_dirs(steam_root) == [raw]


def _fake_raw_dir(tmp_path, *parts):
    raw = tmp_path.joinpath(*parts)
    raw.mkdir(parents=True)
    return raw


def test_unity_data_dirs_parse_subsystems_and_mono_lines():
    # Real line shape from a macOS Steam Player.log (Unity 2022.3 / IL2CPP);
    # current Arena has NO "Mono path" line, so [Subsystems] is load-bearing.
    head = (
        "Input System module state changed to: Initialized.\n"
        "[Subsystems] Discovering subsystems at path "
        "/Users/someone/Library/Application Support/Steam/steamapps/common/MTGA/"
        "MTGA.app/Contents/Resources/Data/UnitySubsystems\n"
        "Mono path[0] = 'G:/MTGA/MTGA_Data/Managed'\n"
        "GfxDevice: creating device client; threaded=1; jobified=0\n"
    )
    dirs = paths_mod._unity_data_dirs_from_log_head(head)
    assert [str(d) for d in dirs] == [
        "/Users/someone/Library/Application Support/Steam/steamapps/common/MTGA/"
        "MTGA.app/Contents/Resources/Data",
        "G:/MTGA/MTGA_Data",
    ]


def test_unity_data_dirs_accept_windows_backslashes():
    head = r"[Subsystems] Discovering subsystems at path G:\MTGA\MTGA_Data\UnitySubsystems"
    dirs = paths_mod._unity_data_dirs_from_log_head(head)
    assert len(dirs) == 1


def test_raw_dir_near_unity_data_dir_windows_shape(tmp_path):
    # Windows: data dir IS <install>/MTGA_Data; Raw sits inside it.
    raw = _fake_raw_dir(tmp_path, "MTGA", "MTGA_Data", "Downloads", "Raw")
    data_dir = tmp_path / "MTGA" / "MTGA_Data"
    assert paths_mod._raw_dir_near_unity_data_dir(data_dir) == raw


def test_raw_dir_near_unity_data_dir_macos_bundle_shape(tmp_path):
    # macOS Steam: data dir is inside the .app; MTGA_Data sits NEXT TO it.
    raw = _fake_raw_dir(tmp_path, "common", "MTGA", "MTGA_Data", "Downloads", "Raw")
    data_dir = tmp_path / "common" / "MTGA" / "MTGA.app" / "Contents" / "Resources" / "Data"
    data_dir.mkdir(parents=True)
    assert paths_mod._raw_dir_near_unity_data_dir(data_dir) == raw


def test_mtga_raw_dir_from_player_log_finds_standalone_install(tmp_path):
    # The reported case: standalone installer on a non-system drive. The log
    # lives in the user profile; the install is somewhere else entirely.
    raw = _fake_raw_dir(tmp_path, "drive_g", "MTGA", "MTGA_Data", "Downloads", "Raw")
    install_data = tmp_path / "drive_g" / "MTGA" / "MTGA_Data"
    log = tmp_path / "profile" / "Player.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        f"[Subsystems] Discovering subsystems at path {install_data}/UnitySubsystems\n",
        encoding="utf-8",
    )
    assert paths_mod.mtga_raw_dir_from_player_log(log) == raw


def test_mtga_raw_dir_from_player_log_falls_back_to_prev_log(tmp_path):
    raw = _fake_raw_dir(tmp_path, "MTGA", "MTGA_Data", "Downloads", "Raw")
    install_data = tmp_path / "MTGA" / "MTGA_Data"
    log_dir = tmp_path / "profile"
    log_dir.mkdir()
    (log_dir / "Player.log").write_text("no header here\n", encoding="utf-8")
    (log_dir / "Player-prev.log").write_text(
        f"[Subsystems] Discovering subsystems at path {install_data}/UnitySubsystems\n",
        encoding="utf-8",
    )
    assert paths_mod.mtga_raw_dir_from_player_log(log_dir / "Player.log") == raw


def test_mtga_raw_dir_from_player_log_never_raises(tmp_path):
    # Missing log, header pointing at a removed drive, no log at all.
    assert paths_mod.mtga_raw_dir_from_player_log(tmp_path / "nope" / "Player.log") is None
    log = tmp_path / "Player.log"
    log.write_text(
        "[Subsystems] Discovering subsystems at path Q:/Gone/MTGA_Data/UnitySubsystems\n",
        encoding="utf-8",
    )
    assert paths_mod.mtga_raw_dir_from_player_log(log) is None
    assert paths_mod.mtga_raw_dir_from_player_log(None) is None


def test_log_derived_dir_leads_and_env_override_still_wins(tmp_path, monkeypatch):
    raw = _fake_raw_dir(tmp_path, "MTGA", "MTGA_Data", "Downloads", "Raw")
    log = tmp_path / "Player.log"
    log.write_text(
        f"[Subsystems] Discovering subsystems at path "
        f"{tmp_path / 'MTGA' / 'MTGA_Data'}/UnitySubsystems\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MTGA_DATA_DIR", raising=False)
    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Windows")
    folders = paths_mod.get_mtga_raw_card_db_folders(log_path=str(log))
    assert folders[0] == raw

    override = _fake_raw_dir(tmp_path, "override")
    monkeypatch.setenv("MTGA_DATA_DIR", str(override))
    assert paths_mod.get_mtga_raw_card_db_folders(log_path=str(log)) == [override]


def test_localization_line_yields_raw_dir_directly(tmp_path):
    # Real line shape from a Windows standalone-install user's log, mixed
    # separators included — it names a file inside Downloads\Raw itself.
    raw = _fake_raw_dir(tmp_path, "Games", "MTGA", "MTGA_Data", "Downloads", "Raw")
    base = str(tmp_path).replace("\\", "/")
    head = (
        f"[UnityCrossThreadLogger]Loading SqlLocalizationManager from file: "
        f"{base}/Games/MTGA/MTGA_Data\\Downloads\\Raw\\Raw_ClientLocalization_abc.mtga {{}}\n"
    )
    log = tmp_path / "Player.log"
    log.write_text(head, encoding="utf-8")
    assert paths_mod.mtga_raw_dir_from_player_log(log) == raw


def test_arena_probe_on_macos(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Darwin")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=codes.pop(0), stdout="")

    codes = [0, 1, 2]
    assert paths_mod.arena_process_running(run=run) is True
    assert paths_mod.arena_process_running(run=run) is False
    assert paths_mod.arena_process_running(run=run) is None
    assert calls[0] == ["/usr/bin/pgrep", "-x", "MTGA"]

    def broken(*_args, **_kwargs):
        raise OSError("no pgrep")

    assert paths_mod.arena_process_running(run=broken) is None


def test_arena_probe_on_windows_never_flashes_a_console(monkeypatch):
    import subprocess
    import sys
    from types import SimpleNamespace

    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    seen = []

    def run(args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(returncode=0, stdout=outputs.pop(0))

    outputs = ['"MTGA.exe","1234","Console","1","500,000 K"\r\n', "INFO: No tasks are running.\r\n"]
    assert paths_mod.arena_process_running(run=run) is True
    assert paths_mod.arena_process_running(run=run) is False
    assert seen[0]["creationflags"] == 0x08000000
    assert (
        paths_mod.arena_process_running(
            run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="")
        )
        is None
    )


def test_arena_probe_is_unknown_on_other_platforms(monkeypatch):
    monkeypatch.setattr(paths_mod.platform, "system", lambda: "Linux")
    assert paths_mod.arena_process_running(run=lambda *a, **k: None) is None


def test_macos_bundle_location_issue(tmp_path):
    bundle = tmp_path / "Applications" / "MTGA Tracker.app"
    bundle.mkdir(parents=True)
    assert paths_mod.macos_bundle_location_issue(bundle) is None
    assert (
        paths_mod.macos_bundle_location_issue(Path("/Volumes/MTGA Tracker/MTGA Tracker.app"))
        == "dmg-mounted"
    )
    assert (
        paths_mod.macos_bundle_location_issue(
            Path("/private/var/folders/x/AppTranslocation/y/MTGA Tracker.app")
        )
        == "translocated"
    )
    assert paths_mod.macos_bundle_location_issue(bundle, access=lambda *_a: False) == "not-writable"


def test_current_platform_key(monkeypatch):
    import sys

    for raw, key in (
        ("darwin", "darwin"),
        ("win32", "win32"),
        ("linux", "linux"),
        ("linux2", "linux"),
    ):
        monkeypatch.setattr(sys, "platform", raw)
        assert paths_mod.current_platform_key() == key
