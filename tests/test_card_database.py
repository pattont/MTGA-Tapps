import sqlite3

from mtga_tracker import card_database
from mtga_tracker.card_database import CardDatabase


def _write_raw_card_db(path, grp_id=12345, title_id=67890, name="Recovered Card"):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE "Cards" ("GrpId" INTEGER, "TitleId" INTEGER)')
    conn.execute('CREATE TABLE "Localizations_enUS" ("LocId" INTEGER, "Loc" TEXT)')
    conn.execute('INSERT INTO "Cards" ("GrpId", "TitleId") VALUES (?, ?)', (grp_id, title_id))
    conn.execute('INSERT INTO "Localizations_enUS" ("LocId", "Loc") VALUES (?, ?)', (title_id, name))
    conn.commit()
    conn.close()


def test_card_database_retries_local_db_resolution_after_initial_miss(tmp_path, monkeypatch):
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    monkeypatch.setattr(card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None: [raw_dir])

    db = CardDatabase()

    assert db.get_card_name(12345) == "Card #12345"

    _write_raw_card_db(raw_dir / "Raw_CardDatabase_test.mtga")

    assert db.get_card_name(12345) == "Recovered Card"
