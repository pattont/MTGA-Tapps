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
