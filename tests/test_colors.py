import sqlite3

from mtga_tracker.card_database import CardDatabase
from mtga_tracker.colors import arena_color_codes_to_letters, color_combo_label, normalize_colors


def test_normalize_colors_orders_and_dedupes():
    assert normalize_colors("RU") == "UR"
    assert normalize_colors("GWWG") == "WG"
    assert normalize_colors("") == ""
    assert normalize_colors(None) == ""


def test_color_combo_labels_match_community_names():
    assert color_combo_label("B") == "Mono-Black"
    assert color_combo_label("RU") == "Izzet"
    assert color_combo_label("GB") == "Golgari"
    assert color_combo_label("WRU") == "Jeskai"
    assert color_combo_label("BUG") == "Sultai"
    assert color_combo_label("UBRG") == "Glint"
    assert color_combo_label("WUBRG") == "5c"
    assert color_combo_label("") is None


def test_arena_color_codes_translate_to_wubrg():
    assert arena_color_codes_to_letters("2,4") == "UR"
    assert arena_color_codes_to_letters("1") == "W"
    assert arena_color_codes_to_letters(None) == ""
    assert arena_color_codes_to_letters("5,3,3") == "BG"


def test_color_identity_index_reads_arena_card_database(tmp_path, monkeypatch):
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    db_path = raw_dir / "Raw_CardDatabase_test.mtga"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE Cards (GrpId INTEGER, TitleId INTEGER, ColorIdentity TEXT)")
        conn.execute("CREATE TABLE Localizations_enUS (LocId INTEGER, loc TEXT)")
        conn.executemany(
            "INSERT INTO Cards (GrpId, TitleId, ColorIdentity) VALUES (?, ?, ?)",
            [(100, 1, "2,4"), (101, 2, "3"), (102, 3, None)],
        )
        conn.executemany(
            "INSERT INTO Localizations_enUS (LocId, loc) VALUES (?, ?)",
            [(1, "Steam Vents"), (2, "Duress"), (3, "Wastes")],
        )

    card_db = CardDatabase(cache_path=str(tmp_path / "cache.json"))
    card_db._mtga_db_path = db_path
    card_db._mtga_db_resolved = True

    index = card_db.color_identity_index_by_name()

    assert index["Steam Vents"] == "UR"
    assert index["Duress"] == "B"
    assert "Wastes" not in index
