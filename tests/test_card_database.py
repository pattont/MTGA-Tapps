import sqlite3

from mtga_tracker import card_database
from mtga_tracker.card_database import CardDatabase


def _write_raw_card_db(path, grp_id=12345, title_id=67890, name="Recovered Card"):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE "Cards" ("GrpId" INTEGER, "TitleId" INTEGER)')
    conn.execute('CREATE TABLE "Localizations_enUS" ("LocId" INTEGER, "Loc" TEXT)')
    conn.execute('INSERT INTO "Cards" ("GrpId", "TitleId") VALUES (?, ?)', (grp_id, title_id))
    conn.execute(
        'INSERT INTO "Localizations_enUS" ("LocId", "Loc") VALUES (?, ?)', (title_id, name)
    )
    conn.commit()
    conn.close()


def test_card_database_retries_local_db_resolution_after_initial_miss(tmp_path, monkeypatch):
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    monkeypatch.setattr(
        card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None, log_path=None: [raw_dir]
    )

    db = CardDatabase()

    assert db.get_card_name(12345) == "Card #12345"

    _write_raw_card_db(raw_dir / "Raw_CardDatabase_test.mtga")

    assert db.get_card_name(12345) == "Recovered Card"


def test_card_database_resolves_primary_type_category_from_local_db(tmp_path, monkeypatch):
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "Raw_CardDatabase_test.mtga"
    conn = sqlite3.connect(raw_path)
    conn.execute('CREATE TABLE "Cards" ("GrpId" INTEGER, "TitleId" INTEGER, "Types" TEXT)')
    conn.execute('CREATE TABLE "Localizations_enUS" ("LocId" INTEGER, "Loc" TEXT)')
    conn.execute('INSERT INTO "Cards" ("GrpId", "TitleId", "Types") VALUES (111, 222, "5")')
    conn.execute('INSERT INTO "Localizations_enUS" ("LocId", "Loc") VALUES (222, "Forest")')
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None, log_path=None: [raw_dir]
    )

    db = CardDatabase()

    assert db.get_card_type_category(111) == "Land"


def test_new_set_db_dropped_alongside_old_is_picked_up_mid_session(tmp_path, monkeypatch):
    """Set-release day: Arena downloads a NEW Raw_CardDatabase while the old
    one still exists. The cached old path passes exists(), so the miss on a
    new-set card must trigger the switch — no tracker restart required."""
    import os
    import time as _time

    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    monkeypatch.setattr(
        card_database,
        "get_mtga_raw_card_db_folders",
        lambda mtga_data_dir=None, log_path=None: [raw_dir],
    )

    old_db = raw_dir / "Raw_CardDatabase_old.mtga"
    _write_raw_card_db(old_db, grp_id=111, name="Old Set Card")
    os.utime(old_db, (1000000, 1000000))

    db = CardDatabase()
    assert db.get_card_name(111) == "Old Set Card"  # resolves + caches old DB

    new_db = raw_dir / "Raw_CardDatabase_new.mtga"
    _write_raw_card_db(new_db, grp_id=222, name="New Set Card")
    os.utime(new_db, (_time.time(), _time.time()))

    db.allow_db_recheck()  # a game just ended
    assert db.get_card_name(222) == "New Set Card"  # miss → recheck → switch
    assert db._mtga_db_path == new_db
    assert db.get_card_name(111) == "Old Set Card"  # still cached from before


def test_db_recheck_runs_at_most_once_per_arming(tmp_path, monkeypatch):
    """Misses only re-scan the folder once per game boundary — repeated
    unknown ids (art variants, tokens) must not glob the disk per miss."""
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    monkeypatch.setattr(
        card_database,
        "get_mtga_raw_card_db_folders",
        lambda mtga_data_dir=None, log_path=None: [raw_dir],
    )
    _write_raw_card_db(raw_dir / "Raw_CardDatabase_only.mtga", grp_id=111, name="A Card")

    db = CardDatabase()
    assert db.get_card_name(111) == "A Card"

    calls = []
    original = db._find_mtga_card_database_paths

    def counting():
        calls.append(1)
        return original()

    db._find_mtga_card_database_paths = counting
    for _ in range(5):
        db.get_card_name(999999)  # repeated misses; initial arming allows ONE re-scan
    assert len(calls) == 1

    db.allow_db_recheck()  # game ended — one more re-scan allowed
    db.get_card_name(999999)
    db.get_card_name(999998)
    assert len(calls) == 2


def test_connect_mtga_db_never_creates_a_file(tmp_path):
    import pytest
    import sqlite3

    missing = tmp_path / "Raw_CardDatabase_gone.mtga"
    with pytest.raises(sqlite3.OperationalError):
        CardDatabase._connect_mtga_db(missing)
    assert not missing.exists()  # plain connect() would have created it


def test_parse_arena_mana_cost_formats():
    parse = CardDatabase.parse_arena_mana_cost
    # Old-school text
    assert parse("2BB") == ("{2}{B}{B}", 4.0)
    assert parse("X(W/U)(W/U)") == ("{X}{W/U}{W/U}", 2.0)
    assert parse("0") == ("{0}", 0.0)
    # GRE pip text ('o' separators)
    assert parse("o2oBoB") == ("{2}{B}{B}", 4.0)
    assert parse("oXo(G/W)") == ("{X}{G/W}", 1.0)
    assert parse("o10oGoG") == ("{10}{G}{G}", 12.0)
    # Already-braced Scryfall notation passes through
    assert parse("{1}{B/P}{U}") == ("{1}{B/P}{U}", 3.0)
    # Twobrid counts as 2; Phyrexian and snow pips count as 1
    assert parse("(2/W)(2/W)") == ("{2/W}{2/W}", 4.0)
    assert parse("(G/P)S") == ("{G/P}{S}", 2.0)
    # Lands / empty costs
    assert parse(None) == ("", 0.0)
    assert parse("   ") == ("", 0.0)
    # Garbage is refused, never guessed
    assert parse("2%%") is None
    assert parse("(W/Q)") is None
    assert parse("{unclosed") is None


def test_mana_cost_index_by_name_probes_cost_column(tmp_path, monkeypatch):
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "Raw_CardDatabase_test.mtga"
    conn = sqlite3.connect(raw_path)
    conn.execute(
        'CREATE TABLE "Cards" ("GrpId" INTEGER, "TitleId" INTEGER, "OldSchoolManaText" TEXT)'
    )
    conn.execute('CREATE TABLE "Localizations_enUS" ("LocId" INTEGER, "Loc" TEXT)')
    rows = [
        (1, 10, "1B"),
        (2, 20, "(G/W)(G/W)"),
        (3, 30, None),  # land: NULL cost stays out of the index
        (4, 40, "not-a-cost%%"),  # unparsable: skipped, not guessed
    ]
    for grp_id, title_id, cost in rows:
        conn.execute(
            'INSERT INTO "Cards" ("GrpId", "TitleId", "OldSchoolManaText") VALUES (?, ?, ?)',
            (grp_id, title_id, cost),
        )
    for title_id, name in ((10, "Dusk Rat"), (20, "Watchwolf"), (30, "Swamp"), (40, "Broken")):
        conn.execute(
            'INSERT INTO "Localizations_enUS" ("LocId", "Loc") VALUES (?, ?)', (title_id, name)
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None, log_path=None: [raw_dir]
    )

    db = CardDatabase()
    index = db.mana_cost_index_by_name()

    assert index["Dusk Rat"] == ("{1}{B}", 2.0)
    assert index["Watchwolf"] == ("{G/W}{G/W}", 2.0)
    assert "Swamp" not in index  # NULL cost filtered by the query
    assert "Broken" not in index  # unparsable value skipped


def test_mana_cost_index_single_localizations_table(tmp_path, monkeypatch):
    """Newer Arena clients renamed Localizations_enUS to a single
    Localizations table with a Format column — the cost index must still
    resolve names through it (a hard-coded join blanked the live pips)."""
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "Raw_CardDatabase_test.mtga"
    conn = sqlite3.connect(raw_path)
    conn.execute(
        'CREATE TABLE "Cards" ("GrpId" INTEGER, "TitleId" INTEGER, "OldSchoolManaText" TEXT)'
    )
    conn.execute('CREATE TABLE "Localizations" ("LocId" INTEGER, "Loc" TEXT, "Format" TEXT)')
    conn.execute('INSERT INTO "Cards" VALUES (1, 10, "1B")')
    conn.execute('INSERT INTO "Localizations" VALUES (10, "Dusk Rat", "en-US/1")')
    conn.execute('INSERT INTO "Localizations" VALUES (10, "Rat der Daemmerung", "de-DE/1")')
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None, log_path=None: [raw_dir]
    )

    db = CardDatabase()
    index = db.mana_cost_index_by_name()

    assert index["Dusk Rat"] == ("{1}{B}", 2.0)
    assert "Rat der Daemmerung" not in index


def test_color_identity_index_single_localizations_table(tmp_path, monkeypatch):
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "Raw_CardDatabase_test.mtga"
    conn = sqlite3.connect(raw_path)
    conn.execute('CREATE TABLE "Cards" ("GrpId" INTEGER, "TitleId" INTEGER, "Colors" TEXT)')
    conn.execute('CREATE TABLE "Localizations" ("LocId" INTEGER, "Loc" TEXT, "Format" TEXT)')
    conn.execute('INSERT INTO "Cards" VALUES (1, 10, "2,4")')
    conn.execute('INSERT INTO "Localizations" VALUES (10, "Izzet Bolt", "en-US/1")')
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None, log_path=None: [raw_dir]
    )

    db = CardDatabase()
    index = db.color_identity_index_by_name()

    assert index["Izzet Bolt"] == "UR"


def test_empty_cost_index_not_cached_for_the_session(tmp_path, monkeypatch):
    """A transient failure (no Arena DB reachable) must not pin an empty
    index for the rest of the session — the next call retries."""
    monkeypatch.setattr(
        card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None, log_path=None: []
    )
    db = CardDatabase()
    assert db.mana_cost_index_by_name() == {}
    assert db.color_identity_index_by_name() == {}

    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    raw_path = raw_dir / "Raw_CardDatabase_test.mtga"
    conn = sqlite3.connect(raw_path)
    conn.execute(
        'CREATE TABLE "Cards" ("GrpId" INTEGER, "TitleId" INTEGER, "OldSchoolManaText" TEXT, "Colors" TEXT)'
    )
    conn.execute('CREATE TABLE "Localizations_enUS" ("LocId" INTEGER, "Loc" TEXT)')
    conn.execute('INSERT INTO "Cards" VALUES (1, 10, "1B", "3")')
    conn.execute('INSERT INTO "Localizations_enUS" VALUES (10, "Dusk Rat")')
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        card_database, "get_mtga_raw_card_db_folders", lambda mtga_data_dir=None, log_path=None: [raw_dir]
    )
    # The DB "came back" — the empty result was not cached, so this resolves.
    assert db.mana_cost_index_by_name()["Dusk Rat"] == ("{1}{B}", 2.0)
    assert db.color_identity_index_by_name()["Dusk Rat"] == "B"
