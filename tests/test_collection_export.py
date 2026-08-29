"""Tests for the collection exporter's pure core and format writers.

The memory readers themselves need a running MTGA process and can only be
smoke-tested on a real machine; everything reachable without process access —
block extraction, scoring/validation, anchor derivation, aggregation, and the
three writers — is covered here with synthetic inputs.
"""

import json
import sqlite3
import struct

import pytest

from mtga_tracker import collection_export as ce


def _pack_pairs(pairs):
    return b"".join(struct.pack("<II", k, v) for k, v in pairs)


def test_extract_blocks_finds_a_clean_stride2_block():
    pairs = [(2000 + i, (i % 4) + 1) for i in range(80)]
    data = b"\x00" * 40 + _pack_pairs(pairs) + b"\xff" * 400
    blocks = ce.extract_blocks(data)
    assert blocks
    biggest = max(blocks, key=lambda b: len(b[0]))
    block, dupes = biggest
    assert len(block) == 80
    assert dupes == 0
    assert block[2000] == 1


def test_extract_blocks_counts_duplicates_as_dirty_signal():
    # 55 distinct ids (clears MIN_BLOCK_SIZE) with 8 of them repeated once.
    pairs = [(3000 + i, 4) for i in range(55)] + [(3000 + i, 4) for i in range(8)]
    data = _pack_pairs(pairs)
    blocks = ce.extract_blocks(data)
    dirty = max(blocks, key=lambda b: b[1])
    assert len(dirty[0]) >= ce.MIN_BLOCK_SIZE
    assert dirty[1] == 8


def test_extract_blocks_ignores_out_of_range_pairs():
    # ids/quantities outside the plausible windows never form a block.
    pairs = [(10, 9999) for _ in range(200)]
    assert ce.extract_blocks(_pack_pairs(pairs)) == []


def test_score_and_validate_prefers_the_known_heavy_block():
    known = set(range(2000, 2400))
    clean = {i: 4 for i in range(2000, 2300)}  # 300 known ids
    junk = {i: 1 for i in range(500000, 500160)}  # 160 unknown ids
    anchors = [ce.Anchor(2000, 4), ce.Anchor(2001, 4)]
    result = ce.score_and_validate(
        [(clean, 0), (junk, 0)], anchors, known
    )
    assert result == clean


def test_score_and_validate_rejects_low_known_ratio():
    known = set(range(2000, 2005))
    mostly_unknown = {i: 1 for i in range(400000, 400060)}
    assert ce.score_and_validate([(mostly_unknown, 0)], [], known) is None


def test_score_and_validate_rejects_high_duplicates():
    known = set(range(2000, 2400))
    block = {i: 4 for i in range(2000, 2300)}
    # duplicates far above the 5%/25 threshold
    assert ce.score_and_validate([(block, 999)], [], known) is None


def test_score_and_validate_accepts_low_known_ratio_when_anchors_cluster():
    # The real-collection shape: a big block that's mostly cards the tracker
    # has NEVER seen played (low known-ratio), but with several of the
    # player's own cards present. This is what timed out before.
    anchors = [ce.Anchor(2000, 4), ce.Anchor(2001, 4), ce.Anchor(2002, 4), ce.Anchor(2003, 4)]
    known = {2000, 2001, 2002, 2003}  # only the anchors are "known"
    block = {i: (i % 4) + 1 for i in range(2000, 2600)}  # 600 cards, 4 known
    # 4/600 ≈ 0.7% known — far below any ratio bar, but 4 anchors present.
    assert ce.score_and_validate([(block, 0)], anchors, known) == block


def test_score_and_validate_still_needs_evidence_without_anchors():
    known = {2000, 2001}
    block = {i: 1 for i in range(2000, 2600)}  # 2/600 known, no anchors
    assert ce.score_and_validate([(block, 0)], [], known) is None


def _tracker_db(tmp_path):
    path = tmp_path / "tracker.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE participants (id TEXT PRIMARY KEY, game_id TEXT, role TEXT);
        CREATE TABLE game_deck_cards (
            game_id TEXT, participant_id TEXT, arena_id INTEGER,
            display_name TEXT, deck_zone TEXT, quantity INTEGER
        );
        CREATE TABLE cards (arena_id INTEGER, name TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO participants VALUES (?, ?, ?)",
        [("p1", "g1", "player"), ("p2", "g1", "opponent"), ("p3", "g2", "player")],
    )
    conn.executemany(
        "INSERT INTO game_deck_cards VALUES (?, ?, ?, ?, ?, ?)",
        [
            # player playsets across two decks — 90573 appears in both
            ("g1", "p1", 90573, "Sheoldred", "deck", 4),
            ("g2", "p3", 90573, "Sheoldred", "deck", 4),
            ("g1", "p1", 91234, "Bloodtithe Harvester", "deck", 4),
            ("g1", "p1", 60001, "Swamp", "deck", 12),  # not a 4-of
            # opponent cards must be ignored by the anchor query
            ("g1", "p2", 88888, "Opponent Card", "deck", 4),
        ],
    )
    conn.commit()
    return conn


def test_derive_anchors_from_player_playsets(tmp_path):
    conn = _tracker_db(tmp_path)
    anchors = ce.derive_anchors(conn)
    ids = [a.arena_id for a in anchors]
    # Only the player's 4-ofs; the two-deck card ranks first; no opponent card.
    assert ids[0] == 90573
    assert 91234 in ids
    assert 60001 not in ids  # 12-of, not an anchor
    assert 88888 not in ids  # opponent's
    assert all(a.quantity == 4 for a in anchors)


def test_known_arena_ids_unions_tables(tmp_path):
    conn = _tracker_db(tmp_path)
    conn.execute("INSERT INTO cards VALUES (70000, 'Some Card')")
    conn.commit()
    ids = ce.known_arena_ids(conn)
    assert {90573, 91234, 60001, 88888, 70000} <= ids


class FakeMemory:
    """A single readable region holding a collection block at a known offset."""

    def __init__(self, pairs, *, base=0x1000):
        self.base = base
        self._data = b"\x11" * 256 + _pack_pairs(pairs) + b"\x22" * 256
        self.process_id = 4242

    def readable_regions(self):
        yield self.base, len(self._data)

    def read_bytes(self, address, length):
        offset = address - self.base
        if offset < 0:
            # ±window reads can start before the region; clamp like a real read.
            length += offset
            offset = 0
        if length <= 0:
            return b""
        return self._data[offset : offset + length]


def test_scan_collection_end_to_end_with_fake_memory(tmp_path):
    conn = _tracker_db(tmp_path)
    # A collection that includes the derived anchor id (90573) so the pattern
    # scan locates the block.
    collection = {90573: 4, 91234: 3, 60001: 20}
    collection.update({4000 + i: (i % 3) + 1 for i in range(300)})
    # The tracker has seen most of the collection (its `cards` table), which
    # is what the scan scores candidate blocks against.
    conn.executemany(
        "INSERT INTO cards VALUES (?, ?)", [(aid, f"card {aid}") for aid in collection]
    )
    conn.commit()
    mem = FakeMemory(list(collection.items()))

    result = ce.scan_collection(conn, memory=mem)
    assert result[90573] == 4
    assert result[91234] == 3
    assert len(result) == len(collection)


def test_scan_collection_raises_when_no_block(tmp_path):
    conn = _tracker_db(tmp_path)
    mem = FakeMemory([(999999, 1)])  # nothing resembling a collection
    with pytest.raises(ce.CollectionNotFound):
        ce.scan_collection(conn, memory=mem)


# --- Aggregation & writers --------------------------------------------------

METADATA = {
    90573: ("Sheoldred, the Apocalypse", "DMU", "107"),
    91234: ("Bloodtithe Harvester", "VOW", "232"),
    60001: ("Swamp", "SLD", "1"),
    70500: ("A-Vivi Ornitier", "FIN", "999"),
    70501: ("Vivi Ornitier", "FIN", "999"),
}


def test_aggregate_maps_names_and_collapses_alchemy_prefix():
    collection = {90573: 3, 91234: 4, 70500: 1, 70501: 2, 12345: 9}
    entries = ce.aggregate(collection, METADATA)
    by_name = {e.name: e for e in entries}
    assert by_name["Sheoldred, the Apocalypse"].count == 3
    # A-Vivi collapses onto Vivi Ornitier (base name known): 1 + 2 = 3
    assert "A-Vivi Ornitier" not in by_name
    assert by_name["Vivi Ornitier"].count == 3
    # Unknown id 12345 is skipped (no name to import).
    assert 12345 not in {aid for e in entries for aid in e.arena_ids}


def test_aggregate_keeps_a_prefix_when_requested():
    entries = ce.aggregate({70500: 1}, METADATA, keep_a_prefix=True)
    assert entries[0].name == "A-Vivi Ornitier"


def test_writers_produce_importable_files(tmp_path):
    entries = ce.aggregate({90573: 3, 91234: 4}, METADATA)

    json_path = tmp_path / "c.json"
    ce.write_json(entries, json_path, database_size=5, now="2026-08-25T00:00:00")
    data = json.loads(json_path.read_text())
    assert data["total_unique"] == 2
    assert data["total_cards"] == 7
    assert {c["name"] for c in data["cards"]} == {
        "Sheoldred, the Apocalypse",
        "Bloodtithe Harvester",
    }

    csv_path = tmp_path / "c.csv"
    ce.write_csv(entries, csv_path)
    import csv as _csv

    with open(csv_path, newline="") as handle:
        rows = list(_csv.reader(handle))
    assert rows[0] == ["Count", "Name", "Edition", "Condition", "Language", "Foil", "Tag"]
    sheoldred = next(r for r in rows[1:] if r[1].startswith("Sheoldred"))
    assert sheoldred[0] == "3" and sheoldred[2] == "DMU"

    txt_path = tmp_path / "c.txt"
    ce.write_txt(entries, txt_path)
    txt = txt_path.read_text()
    assert "4 Bloodtithe Harvester (VOW) 232" in txt
    assert not txt.startswith("MTGA Collection")  # no header banner


def test_run_scan_cli_reports_arena_not_running(tmp_path, monkeypatch, capsys):
    db = tmp_path / "tracker.sqlite3"
    sqlite3.connect(db).close()
    out = tmp_path / "out.json"

    def boom(*_args, **_kwargs):
        raise ce.ProcessNotFound("MTGA")

    monkeypatch.setattr(ce, "scan_collection", boom)
    code = ce.run_scan_cli(["--scan-json", str(db), str(out)])
    assert code == 4
    assert "arena_not_running" in capsys.readouterr().err


def test_run_scan_cli_writes_result(tmp_path, monkeypatch):
    db = tmp_path / "tracker.sqlite3"
    sqlite3.connect(db).close()
    out = tmp_path / "out.json"
    monkeypatch.setattr(ce, "scan_collection", lambda *_a, **_k: {90573: 4, 91234: 3})
    code = ce.run_scan_cli(["--scan-json", str(db), str(out)])
    assert code == 0
    assert json.loads(out.read_text()) == {"90573": 4, "91234": 3}


def test_windows_readable_regions_survives_null_base_address():
    """ctypes reads a NULL c_void_p back as None; the first VirtualQueryEx at
    address 0 reports a NULL-based region, which crashed the whole Windows
    scan with "int() argument must be ... not 'NoneType'" before this fix."""
    import ctypes

    mem = ce.WindowsMemory.__new__(ce.WindowsMemory)
    mem._handle = 1
    regions = [
        # (BaseAddress as ctypes reads it back, RegionSize, State, Protect)
        (None, 0x1000, ce.WindowsMemory._MEM_COMMIT, 0x04),  # NULL base, readable
        (0x1000, 0x2000, 0, 0),  # free region, skipped
        (0x3000, 0x1000, ce.WindowsMemory._MEM_COMMIT, 0x02),  # readable
    ]
    calls = {"n": 0}

    class FakeK32:
        @staticmethod
        def VirtualQueryEx(_handle, _addr, info_ref, _size):
            if calls["n"] >= len(regions):
                return 0
            base, size, state, protect = regions[calls["n"]]
            info = info_ref._obj
            info.BaseAddress = base
            info.RegionSize = size
            info.State = state
            info.Protect = protect
            calls["n"] += 1
            return ctypes.sizeof(info)

    mem._k32 = FakeK32()
    got = list(mem.readable_regions())
    assert got == [(0, 0x1000), (0x3000, 0x1000)]


def test_deck_sized_block_is_never_the_collection():
    """The 34-cards-exported bug: Arena keeps deck objects in memory that are
    indistinguishable from a collection except by size — all owned cards,
    quantities 1-4, anchors included (anchors ARE deck 4-ofs). They must be
    rejected outright, even at a perfect known-ratio with anchors present."""
    anchors = [ce.Anchor(2000, 4), ce.Anchor(2001, 4), ce.Anchor(2002, 4), ce.Anchor(2003, 4)]
    deck = {i: (i % 4) + 1 for i in range(2000, 2060)}  # 60 uniques, a Bo1 deck
    known = set(deck)  # the tracker knows every card in it
    assert ce.score_and_validate([(deck, 0)], anchors, known) is None


def test_collection_beats_deck_block_when_both_present():
    """When a deck object AND the real collection are both in memory, the
    collection must win regardless of the deck's (deceptively perfect) score."""
    anchors = [ce.Anchor(2000, 4), ce.Anchor(2001, 4), ce.Anchor(2002, 4), ce.Anchor(2003, 4)]
    deck = {i: (i % 4) + 1 for i in range(2000, 2060)}
    collection = {i: (i % 4) + 1 for i in range(2000, 8000)}  # 6000 uniques
    known = set(deck)  # tracker only knows the played cards
    result = ce.score_and_validate([(deck, 0), (collection, 0)], anchors, known)
    assert result == collection


def test_scan_does_not_return_early_on_a_deck_block(tmp_path):
    """Region order must not decide the result: a deck-shaped region arriving
    before the collection region (the Windows report) must not end the scan."""
    conn = _tracker_db(tmp_path)
    # Two more player 4-ofs so the anchor set is >= 3 (the override's floor).
    conn.executemany(
        "INSERT INTO game_deck_cards VALUES (?, ?, ?, ?, ?, ?)",
        [("g1", "p1", 70000, "Anchor Three", "deck", 4),
         ("g1", "p1", 70001, "Anchor Four", "deck", 4)],
    )
    # The tracker knows the deck's cards (they've all been played).
    conn.executemany(
        "INSERT INTO cards VALUES (?, ?)",
        [(2000 + i, f"card {i}") for i in range(58)] + [(90573, "Sheoldred"), (91234, "Bloodtithe")],
    )
    conn.commit()

    # Both blocks contain the anchor cards (90573/91234) — a deck object
    # always does, which is exactly why anchors alone can't identify the
    # collection.
    deck_pairs = [(90573, 4), (91234, 4), (70000, 4), (70001, 4)] + [(2000 + i, (i % 4) + 1) for i in range(56)]
    collection_pairs = [(90573, 4), (91234, 4), (70000, 4), (70001, 4)] + [
        (2000 + i, (i % 4) + 1) for i in range(5996)
    ]

    class FakeMemory:
        def readable_regions(self):
            yield 0x1000, len(deck_pairs) * 8
            yield 0x2000, len(collection_pairs) * 8

        def read_bytes(self, address, length):
            pairs = deck_pairs if address == 0x1000 else collection_pairs
            return _pack_pairs(pairs)

    result = ce.scan_collection(conn, memory=FakeMemory())
    assert len(result) == 6000
    assert result[90573] == 4
    conn.close()


def _fake_arena_db(tmp_path, *, loc_table: str):
    """A minimal Raw_CardDatabase with either localization-table shape."""
    raw_dir = tmp_path / "Raw"
    raw_dir.mkdir()
    db = raw_dir / "Raw_CardDatabase_fake.mtga"
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE "Cards" (GrpId INTEGER, TitleId INTEGER, '
        "ExpansionCode TEXT, CollectorNumber TEXT)"
    )
    conn.execute('INSERT INTO "Cards" VALUES (90573, 1, "DMU", "107")')
    conn.execute('INSERT INTO "Cards" VALUES (91234, 2, "VOW", "232")')
    if loc_table == "Localizations_enUS":
        conn.execute('CREATE TABLE "Localizations_enUS" (LocId INTEGER, Loc TEXT)')
        conn.execute(
            'INSERT INTO "Localizations_enUS" VALUES (1, "<nobr>Sheoldred</nobr>, the Apocalypse")'
        )
        conn.execute('INSERT INTO "Localizations_enUS" VALUES (2, "Bloodtithe Harvester")')
    else:
        conn.execute('CREATE TABLE "Localizations" (LocId INTEGER, Loc TEXT, Format TEXT)')
        conn.execute(
            'INSERT INTO "Localizations" VALUES (1, "<nobr>Sheoldred</nobr>, the Apocalypse", "en-US")'
        )
        conn.execute('INSERT INTO "Localizations" VALUES (2, "Bloodtithe Harvester", "en-US")')
    conn.commit()
    conn.close()
    return raw_dir


def test_export_index_strips_markup_and_reads_set_codes(tmp_path):
    from mtga_tracker.card_database import CardDatabase

    raw_dir = _fake_arena_db(tmp_path, loc_table="Localizations_enUS")
    db = CardDatabase(cache_path=str(tmp_path / "cache.json"), mtga_data_dir=str(raw_dir))
    index = db.export_index_by_arena_id()
    # <nobr> markup is stripped — Moxfield can't import "<nobr>…</nobr>" names.
    assert index[90573] == ("Sheoldred, the Apocalypse", "DMU", "107")
    assert index[91234] == ("Bloodtithe Harvester", "VOW", "232")


def test_export_index_falls_back_to_single_localizations_table(tmp_path):
    from mtga_tracker.card_database import CardDatabase

    raw_dir = _fake_arena_db(tmp_path, loc_table="Localizations")
    db = CardDatabase(cache_path=str(tmp_path / "cache.json"), mtga_data_dir=str(raw_dir))
    index = db.export_index_by_arena_id()
    assert index[90573] == ("Sheoldred, the Apocalypse", "DMU", "107")
