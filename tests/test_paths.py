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

