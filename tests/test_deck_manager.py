import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
from http.client import HTTPConnection
from threading import Thread

import pytest

from mtga_tracker.backup import merge_snapshot_into
from mtga_tracker import backup
from mtga_tracker.deck_capture import DeckCapture, capture_log
from mtga_tracker import deck_manager as dm, deck_manager_api as api
from mtga_tracker.log_entry import LogEntry

TEXT = "About\nName Favorite deck\n\nCommander\n1 Atraxa, Praetors' Voice (MUL) 1\n\nCompanion\n1 Jegantha, the Wellspring (IKO) 222\n\nDeck\n4 Forest (DMU) 281\n2 Wedding Announcement // Wedding Festivity (VOW) 45\n\nSideboard\n2 Negate (MOM) 68\n"


@pytest.fixture
def conn(tmp_path):
    connection = dm.library_connection(tmp_path / "tracker.sqlite3")
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


def entry(name="DeckUpsertDeckV3", *, deck_id="original-deck", quantity=4):
    payload = {
        "Summary": {
            "DeckId": deck_id,
            "Name": "Any deck",
            "Attributes": [{"name": "Format", "value": "Standard"}],
        },
        "Deck": {
            "MainDeck": [{"cardId": 123, "quantity": quantity}],
            "Sideboard": [],
            "CommandZone": [],
            "Companions": [],
            "CardSkins": [],
        },
    }
    body = f"[UnityCrossThreadLogger]==> {name} " + json.dumps(
        {"id": "request-1", "request": json.dumps(payload)}
    )
    return LogEntry(header="[UnityCrossThreadLogger]", body=body, first_line=body)


def test_lossless_portable_backup_and_duplicate_names(conn):
    parsed = dm.parse_import(TEXT)
    assert parsed["import_text"] == TEXT
    assert [c["section"] for c in parsed["cards"]] == [
        "Commander",
        "Companion",
        "Deck",
        "Deck",
        "Sideboard",
    ]
    assert parsed["cards"][2]["set_code"] == "DMU"
    first = dm.save_deck(conn, parsed)
    second = dm.save_deck(conn, parsed)
    assert first["id"] != second["id"]
    imported = dm.import_document(dm.export_document(first))
    assert imported == parsed
    assert dm.portable_text(imported) == TEXT
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Deck\n0 Forest",
        "Deck\n-1 Forest",
        "Deck\n4 Forest\nUnexpected section",
        "Deck\n10001 Forest",
    ],
)
def test_invalid_import_does_not_partially_save(conn, text):
    with pytest.raises(dm.DeckManagerError):
        dm.save_deck(conn, dm.parse_import(text))
    assert dm.list_decks(conn) == []


def test_empty_deck_and_unknown_cards_preserved(conn):
    empty = dm.save_deck(conn, dm.parse_import("About\nName Work in progress\nDeck\n"))
    assert empty["deck"]["cards"] == []
    capture = DeckCapture(conn)
    deck_id = capture.consume(entry())
    captured = dm.deck_detail(conn, deck_id)
    assert captured["deck"]["cards"][0]["arena_id"] == 123
    with pytest.raises(dm.DeckManagerError, match="unresolved"):
        dm.portable_text(captured["deck"])
    assert dm.import_document(dm.export_document(captured))["cards"][0]["arena_id"] == 123


def test_revisions_and_trash_never_change_history(conn):
    original = dm.save_deck(conn, dm.parse_import(TEXT))
    changed = dm.save_deck(
        conn, dm.parse_import(TEXT.replace("4 Forest", "5 Forest")), deck_id=original["id"]
    )
    assert len(changed["revisions"]) == 2
    old = dm.deck_detail(conn, original["id"], original["revision_id"])
    assert dm.portable_text(old["deck"]) == TEXT
    dm.update_metadata(
        conn,
        original["id"],
        {"notes": "For later", "tags": ["Favorite", "Favorite"], "trashed": True},
    )
    assert dm.deck_detail(conn, original["id"])["trashed_at"]
    dm.update_metadata(conn, original["id"], {"trashed": False})
    assert dm.deck_detail(conn, original["id"])["notes"] == "For later"
    assert len(dm.deck_detail(conn, original["id"])["revisions"]) == 2


@pytest.mark.parametrize("signal", ["DeckUpsertDeckV3", "EventSetDeckV3"])
def test_submitted_lists_capture_without_game_persistence_and_deduplicate(conn, signal):
    capture = DeckCapture(conn, lambda _: "Forest")
    first = capture.consume(entry(signal))
    assert capture.consume(entry(signal)) == first
    assert len(dm.deck_detail(conn, first)["revisions"]) == 1
    capture.consume(entry(signal, quantity=5))
    assert len(dm.deck_detail(conn, first)["revisions"]) == 2
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_bindings").fetchone()[0] == 0


def native_copy(quantity=4):
    card = {"section": "Deck", "quantity": quantity, "arena_id": 123, "name": "Forest"}
    card.update(set_code=None, collector_number=None)
    return {"name": "Any deck", "format_name": "Standard", "cards": [card], "metadata": {}}


def test_arena_saving_a_deck_manager_transfer_keeps_one_entry(conn):
    saved = dm.save_deck(conn, native_copy())
    # Arena logs its save while the transfer is in flight, before the deck is bound.
    conn.execute(
        "INSERT INTO managed_deck_transfers VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "t",
            "account",
            saved["id"],
            saved["revision_id"],
            "original-deck",
            "restore",
            "write_started",
            "[]",
            None,
            dm.now(),
            dm.now(),
        ),
    )
    capture = DeckCapture(conn, lambda _: "Forest")
    assert capture.consume(entry()) == saved["id"]
    assert [d["id"] for d in dm.list_decks(conn)] == [saved["id"]]
    assert len(dm.deck_detail(conn, saved["id"])["revisions"]) == 1
    # A later edit in Arena becomes a revision of the same entry.
    assert capture.consume(entry(quantity=5)) == saved["id"]
    assert len(dm.list_decks(conn)) == 1
    assert len(dm.deck_detail(conn, saved["id"])["revisions"]) == 2
    # Rescanning the older save adds nothing and keeps the newer list current.
    edited = dm.deck_detail(conn, saved["id"])["revision_id"]
    assert capture.consume(entry()) == saved["id"]
    assert dm.deck_detail(conn, saved["id"])["revision_id"] == edited
    assert len(dm.deck_detail(conn, saved["id"])["revisions"]) == 2


def test_arena_saving_a_bound_deck_adds_nothing(conn):
    saved = dm.save_deck(conn, native_copy(), account_key="account", arena_deck_id="original-deck")
    assert DeckCapture(conn, lambda _: "Forest").consume(entry()) == saved["id"]
    assert len(dm.list_decks(conn)) == 1


def test_native_backup_adopts_the_logged_entry_for_that_arena_deck(conn):
    logged = DeckCapture(conn, lambda _: "Forest").consume(entry())
    saved = dm.save_deck(conn, native_copy(), account_key="account", arena_deck_id="original-deck")
    assert saved["id"] == logged
    assert len(dm.list_decks(conn)) == 1
    # A logged copy in Trash stays there; the backup gets its own entry.
    dm.update_metadata(conn, logged, {"trashed": True})
    conn.execute("DELETE FROM managed_deck_bindings")
    other = dm.save_deck(conn, native_copy(), account_key="account", arena_deck_id="original-deck")
    assert other["id"] != logged


def test_capture_rejects_malformed_quantities_and_summary_only(conn):
    capture = DeckCapture(conn)
    with pytest.raises(dm.DeckManagerError):
        capture.consume(entry(quantity=True))
    summary = entry()
    payload = json.loads(json.loads(summary.body.split(" ", 2)[2])["request"])
    payload.pop("Deck")
    body = "[UnityCrossThreadLogger]==> DeckUpsertDeckV3 " + json.dumps(
        {"request": json.dumps(payload)}
    )
    assert capture.consume(replace(summary, body=body)) is None
    assert dm.list_decks(conn) == []


def test_explicit_log_scan_reuses_buffer_and_is_repeatable(conn, tmp_path):
    path = tmp_path / "Player.log"
    path.write_text(entry().body + "\n" + entry("EventSetDeckV3", deck_id="other").body + "\n")
    assert capture_log(conn, path)["captured"] == 2
    assert capture_log(conn, path)["captured"] == 2
    assert len(dm.list_decks(conn)) == 2
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_revisions").fetchone()[0] == 2


def test_backup_merge_keeps_independent_library_and_does_not_copy_bindings(tmp_path):
    local_path, source_path = tmp_path / "local.db", tmp_path / "source.db"
    with dm.library_connection(source_path) as remote:
        saved = dm.save_deck(
            remote, dm.parse_import(TEXT), account_key="owner", arena_deck_id="arena-id"
        )
    with dm.library_connection(local_path) as local:
        result = merge_snapshot_into(local, source_path)
        assert result["managed_decks"] == 1
        assert dm.deck_detail(local, saved["id"])["deck"]["import_text"] == TEXT
        assert local.execute("SELECT COUNT(*) FROM managed_deck_bindings").fetchone()[0] == 0
        result = merge_snapshot_into(local, source_path)
        assert result["managed_decks"] == result["managed_deck_revisions"] == 0


def test_merge_unions_revisions_preserves_newer_notes_and_rolls_back_corruption(tmp_path):
    local_path, source_path = tmp_path / "local.db", tmp_path / "source.db"
    with dm.library_connection(source_path) as remote:
        original = dm.save_deck(remote, dm.parse_import(TEXT))
    with dm.library_connection(local_path) as local:
        merge_snapshot_into(local, source_path)
        dm.update_metadata(local, original["id"], {"notes": "Local notes"})
        with dm.library_connection(source_path) as remote:
            changed = dm.save_deck(
                remote,
                dm.parse_import(TEXT.replace("4 Forest", "5 Forest")),
                deck_id=original["id"],
            )
            remote.execute("UPDATE managed_decks SET updated_at = '2000-01-01'")
        merge_snapshot_into(local, source_path)
        assert len(dm.deck_detail(local, original["id"])["revisions"]) == 2
        assert dm.deck_detail(local, original["id"])["notes"] == "Local notes"
        with sqlite3.connect(source_path) as remote:
            remote.execute(
                "UPDATE managed_deck_revisions SET content_hash = 'corrupt' WHERE id = ?",
                (changed["revision_id"],),
            )
        with pytest.raises(dm.DeckManagerError, match="verification"):
            merge_snapshot_into(local, source_path)
        assert len(dm.deck_detail(local, original["id"])["revisions"]) == 2


def test_permanent_delete_removes_all_revisions_and_bindings_only_for_selected_deck(conn):
    saved = dm.save_deck(conn, dm.parse_import(TEXT))
    dm.save_deck(conn, dm.parse_import(TEXT.replace("4 Forest", "5 Forest")), deck_id=saved["id"])
    other = dm.save_deck(conn, dm.parse_import(TEXT))
    with conn:
        conn.execute(
            "INSERT INTO managed_deck_bindings (account_key, arena_deck_id, deck_id, observed_at) "
            "VALUES ('account', 'arena-id', ?, '2026-10-06')",
            (saved["id"],),
        )
        conn.execute(
            "INSERT INTO tracker_sessions (id, started_at) VALUES ('session', '2026-10-06')"
        )
        conn.execute("INSERT INTO matches (id, session_id) VALUES ('match', 'session')")
        conn.execute(
            "INSERT INTO games (id, session_id, match_id) VALUES ('game', 'session', 'match')"
        )
        conn.execute(
            "INSERT INTO participants (id, game_id, role, deck_id, deck_name) "
            "VALUES ('player', 'game', 'player', ?, 'Favorite deck')",
            (saved["id"],),
        )
    dm.update_metadata(conn, saved["id"], {"trashed": True})
    dm.delete_deck(conn, saved["id"])
    with pytest.raises(KeyError):
        dm.deck_detail(conn, saved["id"])
    assert dm.deck_detail(conn, other["id"])["deck"]["import_text"] == TEXT
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_revisions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_cards").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_bindings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
    assert (
        conn.execute("SELECT deck_id FROM participants WHERE id = 'player'").fetchone()[0]
        == saved["id"]
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_permanent_delete_requires_trash_even_after_restore(conn):
    saved = dm.save_deck(conn, dm.parse_import(TEXT))
    for restored in (False, True):
        if restored:
            dm.update_metadata(conn, saved["id"], {"trashed": True})
            dm.update_metadata(conn, saved["id"], {"trashed": False})
        with pytest.raises(dm.DeckManagerError, match="Trash"):
            dm.delete_deck(conn, saved["id"])
        assert dm.deck_detail(conn, saved["id"])["deck"]["import_text"] == TEXT
    with pytest.raises(KeyError, match="not found"):
        dm.delete_deck(conn, "missing")


def test_permanent_delete_failure_rolls_back_children(conn):
    saved = dm.save_deck(conn, dm.parse_import(TEXT))
    dm.update_metadata(conn, saved["id"], {"trashed": True})
    with conn:
        conn.execute(
            "INSERT INTO managed_deck_bindings (account_key, arena_deck_id, deck_id, observed_at) "
            "VALUES ('account', 'arena-id', ?, '2026-10-06')",
            (saved["id"],),
        )
        conn.execute(
            "CREATE TRIGGER fail_delete BEFORE DELETE ON managed_decks "
            "BEGIN SELECT RAISE(ABORT, 'Deletion failed'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="Deletion failed"):
        dm.delete_deck(conn, saved["id"])
    assert dm.deck_detail(conn, saved["id"])["deck"]["import_text"] == TEXT
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_cards").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_bindings").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_bulk_trash_preserves_revisions_and_unselected_decks(conn):
    decks = [dm.save_deck(conn, dm.parse_import(TEXT)) for _ in range(3)]
    ids = [d["id"] for d in decks[:2]]
    assert dm.remove_decks(conn, ids, "trash") == 2
    assert all(dm.deck_detail(conn, i)["trashed_at"] for i in ids)
    assert not dm.deck_detail(conn, decks[2]["id"])["trashed_at"]
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_revisions").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_transfers").fetchone()[0] == 0
    assert dm.remove_decks(conn, ids, "delete") == 2
    assert [d["id"] for d in dm.list_decks(conn)] == [decks[2]["id"]]
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_cards").fetchone()[0] == 5
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_bulk_removal_rolls_back_when_selection_changes_or_a_delete_fails(conn):
    decks = [dm.save_deck(conn, dm.parse_import(TEXT)) for _ in range(2)]
    ids = [d["id"] for d in decks]
    with pytest.raises(KeyError):
        dm.remove_decks(conn, [ids[0], "missing"], "trash")
    assert all(not dm.deck_detail(conn, i)["trashed_at"] for i in ids)
    dm.update_metadata(conn, ids[1], {"trashed": True})
    with pytest.raises(dm.DeckManagerError, match="selection changed"):
        dm.remove_decks(conn, ids, "delete")
    dm.update_metadata(conn, ids[0], {"trashed": True})
    with conn:
        conn.execute(
            "CREATE TRIGGER fail_last_delete BEFORE DELETE ON managed_decks "
            f"WHEN OLD.id='{ids[1]}' BEGIN SELECT RAISE(ABORT, 'Deletion failed'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        dm.remove_decks(conn, ids, "delete")
    assert len(dm.list_decks(conn)) == 2
    assert conn.execute("SELECT COUNT(*) FROM managed_deck_cards").fetchone()[0] == 10


def test_bulk_removal_api_requires_confirmation_and_validates_all_ids(tmp_path):
    path = tmp_path / "selected.db"
    conn = dm.library_connection(path)
    saved = dm.save_deck(conn, dm.parse_import(TEXT))
    conn.close()
    endpoint = "/api/deck-manager/remove-selected"
    for invalid in ([], [saved["id"], saved["id"]], [None], "all", ["missing"]):
        response = api.handle_post(
            endpoint, {"ids": invalid, "action": "trash", "confirm": "TRASH"}, path
        )
        assert response[0] in (400, 404)
    assert api.handle_post(endpoint, {"ids": [saved["id"]], "action": "trash"}, path)[0] == 400
    assert api.handle_post(
        endpoint, {"ids": [saved["id"]], "action": "trash", "confirm": "TRASH"}, path
    ) == (200, {"ok": True, "count": 1})


def test_delete_api_requires_confirmation_and_uses_selected_database(tmp_path):
    selected = tmp_path / "chosen.db"
    path = "/api/deck-manager/delete"
    for invalid in (
        {"id": "deck"},
        {"id": "", "confirm": "DELETE"},
        {"id": 1, "confirm": "DELETE"},
        {"id": "deck", "confirm": True},
        [],
    ):
        assert api.handle_post(path, invalid, selected)[0] == 400
        assert not selected.exists()
    _, saved = api.handle_post("/api/deck-manager/import", {"text": TEXT}, selected)
    payload = {"id": saved["id"], "confirm": "DELETE"}
    assert api.handle_post(path, payload, selected)[0] == 400
    assert (
        api.handle_post("/api/deck-manager/update", {"id": saved["id"], "trashed": True}, selected)[
            0
        ]
        == 200
    )
    assert api.handle_post(path, payload, selected) == (200, {"ok": True})
    assert api.handle_get("/api/deck-manager", {}, selected)[1]["decks"] == []
    assert api.handle_post(path, payload, selected)[0] == 404


def test_read_only_library_and_selected_database(tmp_path, monkeypatch):
    from mtga_tracker import deck_native_api

    monkeypatch.setattr(deck_native_api.nb, "availability", lambda: (True, "Available"))
    selected = tmp_path / "chosen.db"
    assert api.handle_get("/api/deck-manager", {}, selected)[1]["decks"] == []
    assert not selected.exists()
    status, imported = api.handle_post("/api/deck-manager/import", {"text": TEXT}, selected)
    assert status == 200
    library = api.handle_get("/api/deck-manager", {}, selected)[1]
    assert library["decks"][0]["id"] == imported["id"]
    assert library["capabilities"]["arena_transfers"] is True
    assert library["capabilities"]["native_section"] is False
    status, export = api.handle_get(
        "/api/deck-manager/export", {"id": [imported["id"]], "format": ["arena"]}, selected
    )
    assert status == 200 and export["text"] == TEXT
    assert (
        api.handle_post("/api/deck-manager/import", {"text": "Deck\n0 Forest"}, selected)[0] == 400
    )
    assert api.handle_get("/api/deck-manager/deck", {"id": ["missing"]}, selected)[0] == 404


def test_replayed_capture_keeps_latest_but_new_reversion_advances_it(conn):
    capture = DeckCapture(conn, lambda _: "Forest")

    def stamped(quantity, minute):
        return replace(
            entry(quantity=quantity),
            timestamp=datetime(2026, 10, 6, 10, minute, tzinfo=timezone.utc),
        )

    deck_id = capture.consume(stamped(4, 0))
    capture.consume(stamped(5, 1))
    capture.consume(stamped(4, 0))
    assert dm.deck_detail(conn, deck_id)["deck"]["cards"][0]["quantity"] == 5
    capture.consume(stamped(4, 2))
    assert dm.deck_detail(conn, deck_id)["deck"]["cards"][0]["quantity"] == 4
    capture.consume(stamped(5, 1))
    assert dm.deck_detail(conn, deck_id)["deck"]["cards"][0]["quantity"] == 4
    assert len(dm.deck_detail(conn, deck_id)["revisions"]) == 2


def test_full_backup_roundtrip_and_old_backup_requires_library_loss_confirmation(tmp_path):
    db = tmp_path / "source.db"
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    with dm.library_connection(db):
        pass
    options = dict(
        settings_path=settings,
        overlay_path=tmp_path / "none",
        deckfinder_path=tmp_path / "none",
        record=False,
    )
    old = backup.export_backup(db, tmp_path / "old", **options)
    with dm.library_connection(db) as source:
        saved = dm.save_deck(source, dm.parse_import(TEXT))
        dm.update_metadata(source, saved["id"], {"notes": "Keep forever", "tags": ["Any format"]})
    made = backup.export_backup(db, tmp_path / "new", **options)
    assert made["managed_decks"] == 1
    assert "managed_revision_ids" not in made
    preview = backup.inspect_backup(old["path"], db, settings_path=settings)
    assert preview["local"]["games"] == 0
    assert preview["requires_confirm"] and preview["deck_drops"] == preview["revision_drops"] == 1
    with pytest.raises(backup.BackupError, match="saved deck"):
        backup.restore_backup(
            old["path"], db, **{k: v for k, v in options.items() if k != "record"}
        )
    restored = tmp_path / "restored.db"
    backup.restore_backup(
        made["path"], restored, **{k: v for k, v in options.items() if k != "record"}
    )
    with dm.library_connection(restored) as target:
        assert dm.deck_detail(target, saved["id"])["notes"] == "Keep forever"
        assert dm.deck_detail(target, saved["id"])["deck"]["import_text"] == TEXT
    preview = backup.inspect_backup(made["path"], tmp_path / "fresh.db", settings_path=settings)
    assert preview["adds"] == 0 and preview["deck_adds"] == preview["revision_adds"] == 1


def test_http_import_rejects_external_origin_and_invalid_bodies_before_writes(tmp_path):
    from mtga_tracker.dashboard import create_dashboard_server

    db = tmp_path / "selected.db"
    server = create_dashboard_server("127.0.0.1", 0, db_path=db)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def request(body, headers):
        client = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            client.request("POST", "/api/deck-manager/import", body=body, headers=headers)
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    try:
        body = json.dumps({"text": TEXT})
        assert request(body, {"Content-Type": "text/plain"})[0] == 403
        assert (
            request(body, {"Content-Type": "application/json", "Origin": "https://example.com"})[0]
            == 403
        )
        assert request("{", {"Content-Type": "application/json"})[0] == 400
        assert not db.exists()
        status, saved = request(body, {"Content-Type": "application/json"})
        assert status == 200
        assert api.handle_get("/api/deck-manager", {}, db)[1]["decks"][0]["id"] == saved["id"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_validation_rejects_text_that_would_restore_a_different_list(conn):
    deck = dm.parse_import(TEXT)
    deck["cards"][2]["quantity"] = 9
    with pytest.raises(dm.DeckManagerError, match="disagree"):
        dm.save_deck(conn, deck)
    assert dm.list_decks(conn) == []


def test_capture_keeps_trackers_connection_row_factory(conn):
    conn.row_factory = None
    capture = DeckCapture(conn, lambda _: "Forest")
    capture.consume(entry())
    assert conn.row_factory is None
    assert isinstance(conn.execute("SELECT id FROM managed_decks").fetchone(), tuple)


def test_collection_moves_are_atomic_and_removal_retains_all_revisions(conn):
    from mtga_tracker import deck_collections as dc

    group = dc.save_collection(conn, "Control")
    decks = [dm.save_deck(conn, dm.parse_import(TEXT)) for _ in range(2)]
    ids = [d["id"] for d in decks]
    with pytest.raises(dm.DeckManagerError):
        dc.move_decks(conn, [ids[0], "missing"], group["id"])
    assert dm.deck_detail(conn, ids[0])["collection_id"] is None
    dc.move_decks(conn, ids, group["id"])
    dm.update_metadata(conn, ids[1], {"trashed": True})
    dc.save_collection(conn, "Control decks", group["id"])
    with pytest.raises(dm.DeckManagerError, match="already exists"):
        dc.save_collection(conn, "control decks")
    assert dc.remove_collection(conn, group["id"]) == 2
    assert not dc.list_collections(conn)
    for deck_id in ids:
        detail = dm.deck_detail(conn, deck_id)
        assert detail["collection_id"] is None
        assert len(detail["revisions"]) == 1
        assert detail["deck"]["import_text"] == TEXT
    assert dm.deck_detail(conn, ids[1])["trashed_at"]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_collection_backup_merge_maps_names_and_preserves_membership(tmp_path):
    from mtga_tracker import deck_collections as dc

    local_path, source_path = tmp_path / "local.db", tmp_path / "source.db"
    with dm.library_connection(local_path) as local, dm.library_connection(source_path) as source:
        local_group = dc.save_collection(local, "Control")
        source_group = dc.save_collection(source, "control")
        original = dm.save_deck(source, dm.parse_import(TEXT), collection_id=source_group["id"])
    with dm.library_connection(local_path) as local:
        merge_snapshot_into(local, source_path)
    with dm.library_connection(local_path) as local:
        assert len(dc.list_collections(local)) == 1
        assert dm.deck_detail(local, original["id"])["collection_id"] == local_group["id"]
        assert local.execute("PRAGMA foreign_key_check").fetchall() == []


def test_collection_import_api_validates_destination_before_saving(tmp_path):
    path = tmp_path / "api.db"
    code, group = api.handle_post("/api/deck-manager/collections/save", {"name": "Green"}, path)
    assert code == 200
    code, saved = api.handle_post(
        "/api/deck-manager/import", {"text": TEXT, "collection_id": group["id"]}, path
    )
    assert code == 200 and saved["collection_id"] == group["id"]
    code, _ = api.handle_post(
        "/api/deck-manager/import", {"text": TEXT, "collection_id": "missing"}, path
    )
    assert code == 400
    code, library = api.handle_get("/api/deck-manager", {}, path)
    assert code == 200 and len(library["decks"]) == 1
    assert library["collections"][0]["id"] == group["id"]
    code, _ = api.handle_post("/api/deck-manager/collections/remove", {"id": group["id"]}, path)
    assert code == 400


def test_gameplay_reset_preserves_collections_and_membership(tmp_path):
    from mtga_tracker import deck_collections as dc
    from mtga_tracker.dashboard import reset_database

    path = tmp_path / "reset.db"
    with dm.library_connection(path) as conn:
        group = dc.save_collection(conn, "Control")
        saved = dm.save_deck(conn, dm.parse_import(TEXT), collection_id=group["id"])
    reset_database(path)
    with dm.library_connection(path) as conn:
        assert dc.list_collections(conn)[0]["id"] == group["id"]
        assert dm.deck_detail(conn, saved["id"])["collection_id"] == group["id"]


def test_saving_an_edited_revision_retains_membership_until_explicit_destination(conn):
    from mtga_tracker import deck_collections as dc

    group = dc.save_collection(conn, "Control")
    saved = dm.save_deck(conn, dm.parse_import(TEXT), collection_id=group["id"])
    dm.save_deck(conn, dm.parse_import(TEXT.replace("4 Forest", "5 Forest")), deck_id=saved["id"])
    assert dm.deck_detail(conn, saved["id"])["collection_id"] == group["id"]
    dm.save_deck(conn, dm.parse_import(TEXT), deck_id=saved["id"], assign_collection=True)
    assert dm.deck_detail(conn, saved["id"])["collection_id"] is None
