"""Native transfer boundaries with a fake Arena; never attach to a game."""

from contextlib import contextmanager
import copy
import json
import uuid

import pytest

from mtga_tracker import deck_manager as dm, deck_transfers as dt, deck_native_api as api
from mtga_tracker import native_deck_archive as na


def deck():
    identity = str(uuid.uuid4())
    return {
        "arena_id": identity,
        "name": "Offline native fixture",
        "is_net_deck": False,
        "contents_loaded": True,
        "summary": {
            "DeckId": identity,
            "Name": "Offline native fixture",
            "Description": "",
            "Attributes": [
                {"key": "Version", "value": "11"},
                {"key": "Format", "value": "Standard"},
            ],
        },
        "piles": [
            {"pile": 1, "entries": [{"id": 123, "quantity": 60}]},
            {"pile": 2, "entries": []},
            {"pile": 3, "entries": []},
            {"pile": 4, "entries": []},
        ],
        "skins": [{"GrpId": "9007199254740993", "CCV": "style", "ArtId": "456"}],
    }


def archive(snapshot):
    return {
        "schema": 1,
        "archive_kind": "arena_typed_model_poc",
        "source_snapshot": copy.deepcopy(snapshot),
        "pile_names": {"1": "Main", "2": "Sideboard", "3": "CommandZone", "4": "Companions"},
        "model_json": '{"style":9007199254740993}',
        "summary_json": json.dumps(snapshot["summary"]),
    }


class Arena:
    account_key = "fixture-account"

    def __init__(self):
        self.source = deck()
        self.decks = {self.source["arena_id"]: self.source}
        self.calls = []
        self.full = False
        self.on_decks = True
        self.after_write = None

    def roster(self):
        return {
            "roster_refreshed": True,
            "decks": copy.deepcopy(list(self.decks.values())),
            "limit": 100,
            "limit_reached": self.full,
            "deck_screen_open": self.on_decks,
        }

    def archive(self, ids):
        self.calls.append("archive")
        return [archive(self.decks[i]) for i in ids]

    def fetch(self, identity):
        self.calls.append("fetch")
        return copy.deepcopy(self.decks[identity])

    def remove(self, snapshot):
        self.calls.append("remove")
        del self.decks[snapshot["arena_id"]]
        if self.after_write:
            self.after_write()

    def prepare_create(self, saved, identity):
        self.prepared = (saved, identity)
        rebuilt = json.loads(saved["summary_json"])
        snapshot = saved["source_snapshot"]["summary"]
        # Arena rebuilds the summary from summary_json and checks it against the snapshot.
        if isinstance(rebuilt["Attributes"], dict):
            rebuilt["Attributes"] = [
                {"key": k, "value": v} for k, v in rebuilt["Attributes"].items()
            ]
        assert {k: rebuilt[k] for k in snapshot} == snapshot

    def create_prepared(self, identity):
        saved, prepared_id = self.prepared
        assert prepared_id == identity
        return self.create(saved, identity)

    def create(self, saved, identity):
        self.calls.append("create")
        restored = copy.deepcopy(saved["source_snapshot"])
        restored["arena_id"] = restored["summary"]["DeckId"] = identity
        if na.attribute(restored, "Version") is None:
            # CreateDeck adds bookkeeping a parser draft lacks, as Arena does.
            restored["summary"]["Attributes"] = [
                {"key": "Version", "value": "11"},
                {"key": "TileID", "value": "0"},
                *restored["summary"]["Attributes"],
                {"key": "IsFavorite", "value": "false"},
            ]
            restored["summary"]["CardBack"] = ""
        self.decks[identity] = restored
        if self.after_write:
            self.after_write()
        return copy.deepcopy(restored)


@pytest.fixture
def conn(tmp_path):
    connection = dm.library_connection(tmp_path / "tracker.db")
    yield connection
    connection.close()


def store(conn, arena, request_id=None):
    return dt.transfer(
        conn,
        arena,
        "store",
        {"id": arena.source["arena_id"]},
        request_id or str(uuid.uuid4()),
        arena.roster(),
        lambda _: "Forest",
    )


def saved(conn):
    return dm.deck_detail(conn, dm.list_decks(conn)[0]["id"])


def restore(conn, arena, request_id=None):
    return dt.transfer(
        conn,
        arena,
        "restore",
        {"id": saved(conn)["id"]},
        request_id or str(uuid.uuid4()),
        arena.roster(),
    )


def test_store_commits_complete_read_back_archive_and_intent_before_remove(conn):
    arena = Arena()
    remove = arena.remove

    def checked(snapshot):
        detail = saved(conn)
        assert na.equivalent(
            detail["deck"]["metadata"]["native_archive"]["source_snapshot"], snapshot
        )
        assert dt.pending(conn)[0]["phase"] == "write_started"
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
        remove(snapshot)

    arena.remove = checked
    store(conn, arena)
    assert arena.decks == {}
    assert dt.pending(conn) == []
    assert conn.execute("SELECT presence FROM managed_deck_bindings").fetchone()[0] == "absent"
    assert saved(conn)["deck"]["cards"][0]["name"] == "Forest"
    assert (
        json.loads(saved(conn)["deck"]["metadata"]["native_archive"]["model_json"])["style"]
        == 9007199254740993
    )


def test_restore_uses_saved_archive_and_new_identity_without_clipboard(conn):
    arena = Arena()
    store(conn, arena)
    restore(conn, arena)
    assert len(arena.decks) == 1
    identity, actual = next(iter(arena.decks.items()))
    assert identity != arena.source["arena_id"]
    assert na.equivalent(actual, arena.source, restored_id=identity)
    assert arena.calls.count("create") == 1
    assert dt.pending(conn) == []


def test_disk_failure_prevents_original_deletion(conn, monkeypatch):
    arena = Arena()

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(dm, "save_deck", fail)
    with pytest.raises(OSError):
        store(conn, arena)
    assert "remove" not in arena.calls
    assert arena.source["arena_id"] in arena.decks


def test_external_edit_after_backup_prevents_deletion(conn):
    arena = Arena()
    fetch = arena.fetch

    def changed(identity):
        result = fetch(identity)
        result["piles"][0]["entries"][0]["quantity"] = 59
        return result

    arena.fetch = changed
    with pytest.raises(dm.DeckManagerError, match="changed"):
        store(conn, arena)
    assert "remove" not in arena.calls
    assert saved(conn)["deck"]["cards"][0]["quantity"] == 60


@pytest.mark.parametrize("failure", ["capacity", "account", "duplicate", "screen"])
def test_restore_guards_prevent_native_create(conn, failure):
    arena = Arena()
    store(conn, arena)
    if failure == "capacity":
        arena.full = True
    elif failure == "account":
        arena.account_key = "another-account"
    elif failure == "duplicate":
        arena.decks[arena.source["arena_id"]] = arena.source
    else:
        arena.on_decks = False
    with pytest.raises(dm.DeckManagerError):
        restore(conn, arena)
    assert "create" not in arena.calls


def test_interrupted_removal_reconciles_read_only_after_commit(conn):
    arena = Arena()

    def disconnect():
        raise TimeoutError("connection lost")

    arena.after_write = disconnect
    with pytest.raises(TimeoutError):
        store(conn, arena)
    assert dt.pending(conn)[0]["phase"] == "uncertain"
    calls = list(arena.calls)
    dt.reconcile(conn, arena, arena.roster())
    assert arena.calls == calls
    assert dt.pending(conn) == []


def test_interrupted_restore_reconciles_after_commit_without_second_creation(conn):
    arena = Arena()
    store(conn, arena)

    def disconnect():
        raise TimeoutError("connection lost")

    arena.after_write = disconnect
    with pytest.raises(TimeoutError):
        restore(conn, arena)
    assert dt.pending(conn)[0]["action"] == "restore"
    dt.reconcile(conn, arena, arena.roster())
    assert arena.calls.count("create") == 1
    assert dt.pending(conn) == []


def test_unknown_restore_absence_does_not_allow_create_retry(conn):
    arena = Arena()
    store(conn, arena)

    def disconnected(*args):
        arena.calls.append("create")
        raise TimeoutError("unknown")

    arena.create = disconnected
    request_id = str(uuid.uuid4())
    with pytest.raises(TimeoutError):
        restore(conn, arena, request_id)
    with pytest.raises(dm.DeckManagerError, match="not confirmed"):
        dt.reconcile(conn, arena, arena.roster())
    with pytest.raises(dm.DeckManagerError, match="already started"):
        restore(conn, arena, request_id)
    assert arena.calls.count("create") == 1


def test_completed_request_replay_is_idempotent(conn):
    arena = Arena()
    request_id = str(uuid.uuid4())
    store(conn, arena, request_id)
    calls = list(arena.calls)
    store(conn, arena, request_id)
    assert arena.calls == calls


def test_completed_request_cannot_be_replayed_for_a_different_account(conn):
    arena = Arena()
    request_id = str(uuid.uuid4())
    store(conn, arena, request_id)
    arena.account_key = "another-account"
    with pytest.raises(dm.DeckManagerError, match="another account"):
        store(conn, arena, request_id)
    assert arena.calls.count("remove") == 1


def test_pending_transfer_blocks_local_permanent_deletion(conn):
    arena = Arena()

    def fail(*args):
        raise TimeoutError("unknown")

    arena.remove = fail
    with pytest.raises(TimeoutError):
        store(conn, arena)
    detail = saved(conn)
    dm.update_metadata(conn, detail["id"], {"trashed": True})
    with pytest.raises(dm.DeckManagerError, match="Reconcile"):
        dm.delete_deck(conn, detail["id"])
    other = dm.save_deck(conn, dm.parse_import("Deck\n4 Forest"))
    dm.update_metadata(conn, other["id"], {"trashed": True})
    with pytest.raises(dm.DeckManagerError, match="Reconcile"):
        dm.remove_decks(conn, [other["id"], detail["id"]], "delete")
    assert dm.deck_detail(conn, other["id"])
    assert saved(conn)


def test_missing_other_deck_keeps_transfer_unresolved(conn):
    arena = Arena()
    other = deck()
    arena.decks[other["arena_id"]] = other
    arena.after_write = lambda: arena.decks.pop(other["arena_id"])
    with pytest.raises(dm.DeckManagerError, match="Other Arena decks"):
        store(conn, arena)
    assert dt.pending(conn)


def test_status_get_never_attaches_or_creates_database(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("GET must not attach")

    monkeypatch.setattr(api.nb, "attach", forbidden)
    path = tmp_path / "missing.db"
    assert api.handle_get("/api/deck-manager/native", {}, path)[0] == 200
    assert not path.exists()


def test_background_bulk_backup_reads_actual_roster_without_deletes(tmp_path, monkeypatch):
    arena = Arena()
    arena.decks[deck()["arena_id"]] = deck()
    # Rebuild keys to reflect fixture IDs.
    arena.decks = {d["arena_id"]: d for d in arena.decks.values()}

    @contextmanager
    def attach():
        yield arena

    monkeypatch.setattr(api.nb, "attach", attach)
    monkeypatch.setattr(api, "_resolve_names", lambda: lambda _: "Forest")
    path = tmp_path / "library.db"
    result = api.execute(path, "backup", [], str(uuid.uuid4()), lambda _: None)
    assert result["count"] == 2
    # Both decks are read in one batch (one Arena frame when already loaded).
    assert arena.calls == ["archive"]
    with dm.library_connection(path) as conn:
        assert len(dm.list_decks(conn)) == 2
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def test_native_move_endpoint_requires_confirmation_before_starting_job(tmp_path):
    status, _ = api.handle_post(
        "/api/deck-manager/native/run",
        {"action": "store", "decks": [{"id": str(uuid.uuid4())}], "request_id": str(uuid.uuid4())},
        tmp_path / "db",
    )
    assert status == 400


def test_native_move_endpoint_rejects_an_invalid_destination_before_starting_job(tmp_path):
    status, _ = api.handle_post(
        "/api/deck-manager/native/run",
        {
            "action": "store",
            "decks": [{"id": str(uuid.uuid4())}],
            "request_id": str(uuid.uuid4()),
            "confirm": "MOVE",
            "collection_id": 7,
        },
        tmp_path / "db",
    )
    assert status == 400


def test_store_saves_into_the_chosen_collection_including_an_earlier_backup(conn):
    from mtga_tracker.deck_collections import save_collection

    arena = Arena()
    store(conn, arena)
    deck_id = saved(conn)["id"]
    assert saved(conn)["collection_id"] is None
    restore(conn, arena)
    target = save_collection(conn, "Retired")["id"]
    dt.transfer(
        conn,
        arena,
        "store",
        {"id": next(iter(arena.decks)), "collection_id": target},
        str(uuid.uuid4()),
        arena.roster(),
        lambda _: "Forest",
    )
    assert arena.decks == {}
    assert saved(conn)["id"] == deck_id
    assert saved(conn)["collection_id"] == target


def test_store_refuses_a_missing_collection_before_removing_from_arena(conn):
    arena = Arena()
    with pytest.raises(dm.DeckManagerError, match="existing collection"):
        dt.transfer(
            conn,
            arena,
            "store",
            {"id": arena.source["arena_id"], "collection_id": str(uuid.uuid4())},
            str(uuid.uuid4()),
            arena.roster(),
            lambda _: "Forest",
        )
    assert arena.source["arena_id"] in arena.decks
    assert "remove" not in arena.calls


@pytest.mark.parametrize("payload", [{"$type": "Arbitrary"}, {"nested": [{"$type": "Arbitrary"}]}])
def test_native_archive_refuses_arbitrary_deserialization_types(payload):
    value = archive(deck())
    value["model_json"] = json.dumps(payload)
    with pytest.raises(dm.DeckManagerError, match="executable"):
        na.validate_archive(value)


def test_portable_native_backup_restores_only_on_its_original_account(conn):
    arena = Arena()
    store(conn, arena)
    portable = dm.import_document(dm.export_document(saved(conn)))
    imported = dm.save_deck(conn, portable)
    dt.transfer(conn, arena, "restore", {"id": imported["id"]}, str(uuid.uuid4()), arena.roster())
    assert len(arena.decks) == 1
    assert arena.calls.count("create") == 1


def test_edited_card_list_cannot_silently_restore_stale_native_data(conn):
    arena = Arena()
    store(conn, arena)
    original = saved(conn)
    changed = copy.deepcopy(original["deck"])
    changed["cards"][0]["quantity"] = 59
    dm.save_deck(conn, changed, deck_id=original["id"])
    with pytest.raises(dm.DeckManagerError, match="differs from its native backup"):
        restore(conn, arena)
    assert "create" not in arena.calls


def test_tracked_game_blocks_attachment_before_any_native_call(tmp_path, monkeypatch):
    path = tmp_path / "tracker.db"
    with dm.library_connection(path) as conn:
        conn.execute("INSERT INTO live_status(id,in_game,updated_at) VALUES(1,1,?)", (dm.now(),))

    def forbidden():
        raise AssertionError("Do not attach during a tracked game")

    monkeypatch.setattr(api.nb, "attach", forbidden)
    with pytest.raises(dm.DeckManagerError, match="Finish your game first"):
        api.execute(path, "connect", [], str(uuid.uuid4()), lambda _: None)
    assert api.status(path)["in_game"] is True


def imported_arena(quantity=4):
    arena = Arena()

    def prepare(text, name, identity):
        # Arena's parser draft: no Format, no tile, no server bookkeeping.
        arena.calls.append("prepare_import")
        prepared = deck()
        prepared["name"] = prepared["summary"]["Name"] = name
        prepared["arena_id"] = prepared["summary"]["DeckId"] = identity
        prepared["summary"]["Attributes"] = [{"key": "LastUpdated", "value": '"now"'}]
        prepared["summary"]["DeckTileId"] = 0
        prepared["piles"][0]["entries"][0]["quantity"] = quantity
        result = archive(prepared)
        summary = copy.deepcopy(prepared["summary"])
        summary["Attributes"] = {"LastUpdated": '"now"'}
        result["summary_json"] = json.dumps(summary)
        return result

    arena.prepare_import = prepare
    return arena


def test_native_text_import_uses_journaled_creation_and_never_repeats_request(conn):
    arena = imported_arena()
    request_id = str(uuid.uuid4())
    selection = {
        "text": "Deck\n2 Forest\n2 Forest",
        "name": "Finder deck",
        "format_name": "Standard",
    }
    report = dt.add_import(conn, arena, selection, request_id, arena.roster(), lambda _: "Forest")
    assert len(report["decks"]) == 2
    assert arena.calls.count("create") == 1
    assert arena.calls.count("prepare_import") == 1
    assert dt.pending(conn) == []
    dt.add_import(conn, arena, selection, request_id, report, lambda _: "Forest")
    assert arena.calls.count("create") == 1
    assert arena.calls.count("prepare_import") == 1
    with pytest.raises(dm.DeckManagerError, match="another decklist"):
        dt.add_import(
            conn,
            arena,
            {**selection, "text": "Deck\n1 Forest"},
            request_id,
            report,
            lambda _: "Forest",
        )


def test_native_text_import_rejects_inventory_clamping_without_create_or_backup(conn):
    arena = imported_arena(quantity=3)
    with pytest.raises(
        dm.DeckManagerError,
        match=r"changed the card list.*Differences: Deck: 4 Forest in the list, 3 from Arena\.$",
    ):
        dt.add_import(
            conn,
            arena,
            {"text": "Deck\n4 Forest", "name": "Finder deck", "format_name": "Standard"},
            str(uuid.uuid4()),
            arena.roster(),
            lambda _: "Forest",
        )
    assert "create" not in arena.calls
    assert dm.list_decks(conn) == []


def test_native_text_import_accepts_a_cards_interchangeable_name(conn):
    # The list says the Omenpath name; Arena's importer returns the Universes Beyond
    # printing the player owns, which the card DB names "Superior Spider-Man".
    selection = {
        "text": "Deck\n4 Kavaero, Mind-Bitten",
        "name": "Finder deck",
        "format_name": "Standard",
    }
    arena = imported_arena()
    with pytest.raises(
        dm.DeckManagerError,
        match=r"Deck: 4 Kavaero, Mind-Bitten in the list, 0 from Arena; "
        r"Deck: 0 Superior Spider-Man in the list, 4 from Arena\.$",
    ):
        dt.add_import(
            conn,
            arena,
            selection,
            str(uuid.uuid4()),
            arena.roster(),
            lambda _: "Superior Spider-Man",
        )
    assert "create" not in arena.calls

    aliases = {
        "superior spider-man": "kavaero, mind-bitten",
        "kavaero, mind-bitten": "kavaero, mind-bitten",
    }
    arena = imported_arena()
    report = dt.add_import(
        conn,
        arena,
        selection,
        str(uuid.uuid4()),
        arena.roster(),
        lambda _: "Superior Spider-Man",
        aliases=aliases,
    )
    assert arena.calls.count("create") == 1
    assert len(report["decks"]) == 2
    assert dt.pending(conn) == []


def test_interchangeable_names_never_hide_a_quantity_change(conn):
    aliases = {
        "superior spider-man": "kavaero, mind-bitten",
        "kavaero, mind-bitten": "kavaero, mind-bitten",
    }
    arena = imported_arena(quantity=3)
    with pytest.raises(
        dm.DeckManagerError,
        match=r"Deck: 4 Kavaero, Mind-Bitten in the list, 3 from Arena\.$",
    ):
        dt.add_import(
            conn,
            arena,
            {
                "text": "Deck\n4 Kavaero, Mind-Bitten",
                "name": "Finder deck",
                "format_name": "Standard",
            },
            str(uuid.uuid4()),
            arena.roster(),
            lambda _: "Superior Spider-Man",
            aliases=aliases,
        )
    assert "create" not in arena.calls


def test_native_text_import_rejects_full_slots_before_parser_call(conn):
    arena = imported_arena()
    arena.full = True
    with pytest.raises(dm.DeckManagerError, match="free deck slot"):
        dt.add_import(
            conn,
            arena,
            {"text": "Deck\n4 Forest", "name": "Finder deck", "format_name": "Standard"},
            str(uuid.uuid4()),
            arena.roster(),
            lambda _: "Forest",
        )
    assert arena.calls == []


def test_public_arena_roster_exposes_art_without_another_native_call():
    arena = Arena()
    arena.source["summary"]["DeckArtId"] = 456
    report = api._public_roster(arena.roster())
    assert report["decks"][0]["art_card_id"] == 456
    del arena.source["summary"]["DeckArtId"]
    assert api._public_roster(arena.roster())["decks"][0]["art_card_id"] == 123
    assert arena.calls == []


def test_failed_preparation_is_cancelled_without_creation_and_new_request_can_proceed(conn):
    arena = Arena()
    store(conn, arena)
    prepare = arena.prepare_create

    def failing(archive, arena_id):
        assert dt.pending(conn)[0]["phase"] == "prepared"
        raise dm.DeckManagerError("Rebuilt deck differs")

    arena.prepare_create = failing
    with pytest.raises(dm.DeckManagerError, match="Rebuilt"):
        restore(conn, arena)
    assert dt.pending(conn) == []
    assert arena.calls.count("create") == 0
    assert len(saved(conn)["revisions"]) == 1
    assert (
        conn.execute("SELECT phase FROM managed_deck_transfers WHERE action='restore'").fetchone()[
            0
        ]
        == "cancelled"
    )
    arena.prepare_create = prepare
    restore(conn, arena)
    assert arena.calls.count("create") == 1


def test_finder_add_upgrades_saved_entry_and_preserves_collection_notes_and_revision(conn):
    from mtga_tracker import deck_collections as dc

    arena = imported_arena()
    collection = dc.save_collection(conn, "Green")
    original = dm.save_deck(
        conn,
        dm.parse_import("Deck\n4 Forest", "Finder deck", "Standard"),
        collection_id=collection["id"],
    )
    dm.update_metadata(conn, original["id"], {"notes": "Keep this note"})
    dt.add_import(
        conn,
        arena,
        {
            "text": "Deck\n4 Forest",
            "name": "Finder deck",
            "format_name": "Standard",
            "saved_deck_id": original["id"],
        },
        str(uuid.uuid4()),
        arena.roster(),
        lambda _: "Forest",
    )
    assert len(dm.list_decks(conn)) == 1
    upgraded = dm.deck_detail(conn, original["id"])
    assert upgraded["notes"] == "Keep this note"
    assert upgraded["collection_id"] == collection["id"]
    assert len(upgraded["revisions"]) == 3  # text, import draft, Arena's created copy
    assert na.revision_archive(upgraded["deck"])


def test_backup_progress_counts_reads_and_verified_commits(tmp_path, monkeypatch):
    arena = Arena()
    other = deck()
    arena.decks[other["arena_id"]] = other

    @contextmanager
    def attach():
        yield arena

    monkeypatch.setattr(api.nb, "attach", attach)
    monkeypatch.setattr(api, "_resolve_names", lambda: lambda _: "Forest")
    progress = []
    api.execute(tmp_path / "progress.db", "backup", [], str(uuid.uuid4()), progress.append)
    steps = [p for p in progress if isinstance(p, dict)]
    # Reads advance per batch (both decks at once), commits per deck.
    assert [p["completed"] for p in steps] == [0, 2, 3, 4]
    assert all(p["total"] == 4 for p in steps)


def finder_selection(text="Deck\n4 Forest", format_name="Standard / Bo3"):
    return {"text": text, "name": "Finder deck", "format_name": format_name}


def test_finder_add_sets_arena_format_and_adopts_arenas_created_copy(conn):
    arena = imported_arena()
    report = dt.add_import(
        conn, arena, finder_selection(), str(uuid.uuid4()), arena.roster(), lambda _: "Forest"
    )
    created = next(d for d in report["decks"] if d["name"] == "Finder deck")
    assert na.attribute(created, "Format") == "TraditionalStandard"
    assert dt.pending(conn) == []
    backup = saved(conn)
    assert backup["format_name"] == "TraditionalStandard"
    assert not na.import_draft(backup["deck"])
    assert len(backup["revisions"]) == 2
    # The adopted backup is Arena's stored copy, so a later move verifies exactly.
    assert na.equivalent(
        arena.fetch(created["arena_id"]), na.revision_archive(backup["deck"])["source_snapshot"]
    )


def test_finder_add_sets_a_creature_tile_in_both_summary_forms(conn):
    arena = imported_arena()
    arena.source["piles"][0]["entries"] = [
        {"id": 1, "quantity": 20},
        {"id": 2, "quantity": 2},
        {"id": 3, "quantity": 4},
    ]
    prepare = arena.prepare_import

    def mixed(text, name, identity):
        result = prepare(text, name, identity)
        result["source_snapshot"]["piles"][0]["entries"] = copy.deepcopy(
            arena.source["piles"][0]["entries"]
        )
        return result

    arena.prepare_import = mixed
    kinds = {1: "Land", 2: "Creature", 3: "Instant"}
    dt.add_import(
        conn,
        arena,
        finder_selection("Deck\n20 Forest\n2 Bear\n4 Shock", "Standard"),
        str(uuid.uuid4()),
        arena.roster(),
        {1: "Forest", 2: "Bear", 3: "Shock"}.get,
        card_type=kinds.get,
    )
    created_archive = arena.prepared[0]
    assert json.loads(created_archive["summary_json"])["DeckTileId"] == 2
    assert created_archive["source_snapshot"]["summary"]["DeckTileId"] == 2
    assert json.loads(created_archive["summary_json"])["Attributes"] == {
        "LastUpdated": '"now"',
        "Format": "Standard",
    }


@pytest.mark.parametrize(
    "kinds, expected",
    [({1: "Land", 2: "Instant", 3: "Instant"}, 3), ({}, 1), ({1: "Land", 2: "Creature"}, 2)],
)
def test_tile_card_prefers_most_played_creature_then_nonland(kinds, expected):
    snapshot = {
        "piles": [
            {
                "pile": 1,
                "entries": [
                    {"id": 1, "quantity": 20},
                    {"id": 2, "quantity": 2},
                    {"id": 3, "quantity": 4},
                ],
            }
        ]
    }
    assert na.tile_card(snapshot, kinds.get) == expected


def test_finder_add_changed_by_arena_is_uncertain_then_reconciles_to_arenas_copy(conn):
    arena = imported_arena()
    create = arena.create

    def clamped(saved, identity):
        result = create(saved, identity)
        arena.decks[identity]["piles"][0]["entries"][0]["quantity"] = 3
        result["piles"][0]["entries"][0]["quantity"] = 3
        return result

    arena.create = clamped
    with pytest.raises(dm.DeckManagerError, match="differs from the backup"):
        dt.add_import(
            conn, arena, finder_selection(), str(uuid.uuid4()), arena.roster(), lambda _: "Forest"
        )
    assert dt.pending(conn)[0]["phase"] == "uncertain"
    dt.reconcile(conn, arena, arena.roster())
    assert dt.pending(conn) == []
    assert arena.calls.count("create") == 1
    backup = saved(conn)
    assert [c["quantity"] for c in backup["deck"]["cards"]] == [3]
    assert len(backup["revisions"]) == 2  # Arena's copy sits on top of the import draft


def test_restored_deck_edited_in_arena_reconciles_and_keeps_original_revision(conn):
    arena = Arena()
    store(conn, arena)

    def disconnect():
        raise TimeoutError("connection lost")

    arena.after_write = disconnect
    with pytest.raises(TimeoutError):
        restore(conn, arena)
    arena.after_write = None
    restored_id = dt.pending(conn)[0]["arena_deck_id"]
    edited = arena.decks[restored_id]
    edited["name"] = edited["summary"]["Name"] = "Renamed in Arena"
    edited["summary"]["DeckTileId"] = 123
    dt.reconcile(conn, arena, arena.roster())
    assert dt.pending(conn) == []
    assert arena.calls.count("create") == 1
    backup = saved(conn)
    assert backup["name"] == "Renamed in Arena"
    assert len(backup["revisions"]) == 2


def test_uncertain_finder_add_from_a_draft_reconciles_without_another_create(conn):
    """A created deck left uncertain (e.g. by the old exact draft check) completes on reconcile."""
    arena = imported_arena()

    def created_then_lost(identity):
        Arena.create_prepared(arena, identity)
        raise TimeoutError("connection lost")

    arena.create_prepared = created_then_lost
    with pytest.raises(TimeoutError):
        dt.add_import(
            conn, arena, finder_selection(), str(uuid.uuid4()), arena.roster(), lambda _: "Forest"
        )
    assert dt.pending(conn)[0]["phase"] == "uncertain"
    dt.reconcile(conn, arena, arena.roster(), lambda _: "Forest")
    assert dt.pending(conn) == []
    assert arena.calls.count("create") == 1
    assert not na.import_draft(saved(conn)["deck"])


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Standard", "Standard"),
        ("Standard / Bo1", "Standard"),
        ("Standard (Bo3)", "TraditionalStandard"),
        ("Traditional Historic", "TraditionalHistoric"),
        ("Historic Brawl", "HistoricBrawl"),
        ("Brawl", "Brawl"),
        ("Pioneer", "Explorer"),
        ("Timeless Bo3", "Timeless"),
        ("", "Standard"),
    ],
)
def test_arena_format_maps_deck_finder_labels(label, expected):
    assert na.arena_format(label) == expected


def native_job(tmp_path, monkeypatch, arena):
    @contextmanager
    def attach():
        yield arena

    monkeypatch.setattr(api.nb, "attach", attach)
    monkeypatch.setattr(api, "_resolve_names", lambda: lambda _: "Forest")
    return tmp_path / "jobs.db"


def test_cancelled_backup_keeps_decks_already_read_and_reads_no_more(tmp_path, monkeypatch):
    arena = Arena()
    for _ in range(3):
        extra = deck()
        arena.decks[extra["arena_id"]] = extra
    db = native_job(tmp_path, monkeypatch, arena)
    monkeypatch.setattr(api, "BACKUP_BATCH", 2)
    result = api.execute(
        db, "backup", [], str(uuid.uuid4()), lambda _: None, lambda: "archive" in arena.calls
    )
    # Stopping takes effect between batches: the first batch of two is kept.
    assert arena.calls.count("archive") == 1
    assert result == {"count": 2, "action": "backup", "cancelled": True}
    conn = dm.library_connection(db)
    try:
        assert len(dm.list_decks(conn)) == 2
    finally:
        conn.close()


def test_cancelled_bulk_move_finishes_the_current_deck_only(tmp_path, monkeypatch):
    arena = Arena()
    second = deck()
    arena.decks[second["arena_id"]] = second
    db = native_job(tmp_path, monkeypatch, arena)
    selections = [{"id": arena.source["arena_id"]}, {"id": second["arena_id"]}]
    result = api.execute(
        db, "store", selections, str(uuid.uuid4()), lambda _: None, lambda: "remove" in arena.calls
    )
    assert result == {"count": 1, "action": "store", "cancelled": True}
    assert arena.calls.count("remove") == 1
    assert second["arena_id"] in arena.decks


def test_cancel_endpoint_only_flags_running_bulk_jobs(tmp_path):
    db = tmp_path / "cancel.db"
    job_id = str(uuid.uuid4())
    api._JOBS[job_id] = {"db": api._key(db), "action": "backup", "state": "running", "detail": ""}
    try:
        status, body = api.handle_post("/api/deck-manager/native/cancel", {"job_id": job_id}, db)
        assert status == 200 and body["cancel"] is True
        assert api._JOBS[job_id]["detail"].startswith("Stopping")
        api._JOBS[job_id].update(action="add", cancel=False)
        assert (
            api.handle_post("/api/deck-manager/native/cancel", {"job_id": job_id}, db)[1]["cancel"]
            is False
        )
        assert (
            api.handle_post("/api/deck-manager/native/cancel", {"job_id": "missing"}, db)[0] == 404
        )
    finally:
        api._JOBS.pop(job_id, None)


def test_import_drafts_are_added_from_text_not_restored(conn, tmp_path):
    from mtga_tracker import deck_manager_api

    arena = imported_arena()

    def fail(identity):
        raise TimeoutError("lost before Arena answered")

    arena.create_prepared = fail
    with pytest.raises(TimeoutError):
        dt.add_import(
            conn, arena, finder_selection(), str(uuid.uuid4()), arena.roster(), lambda _: "Forest"
        )
    draft = saved(conn)
    assert na.import_draft(draft["deck"])
    db = tmp_path / "tracker.db"
    listed = deck_manager_api.handle_get("/api/deck-manager", {}, db)[1]["decks"]
    assert [d["native_restorable"] for d in listed] == [False]
    detail = deck_manager_api.handle_get("/api/deck-manager/deck", {"id": [draft["id"]]}, db)[1]
    assert detail["native_restorable"] is False
    store_conn = dm.library_connection(tmp_path / "other.db")
    try:
        store(store_conn, Arena())
        listed = deck_manager_api.handle_get("/api/deck-manager", {}, tmp_path / "other.db")[1]
        assert [d["native_restorable"] for d in listed["decks"]] == [True]
    finally:
        store_conn.close()


def test_job_failures_show_the_adapters_reason_and_fit_the_action():
    class RPCException(Exception):
        pass

    reason = (
        "Arena isn’t on its Decks screen. Go to Decks in Arena, outside a match, then try again."
    )
    assert api._failure_message(RPCException(reason), "connect") == reason
    # Frida's "Error:" prefix and script stack never reach the user.
    raw = f"Error: {reason} at <anonymous> (/script1.js:479) at onEnter (/script1.js:427)"
    assert api._failure_message(RPCException(raw), "add") == reason
    assert (
        api._failure_message(RPCException(f"Error: {reason}\n    at x (/s.js:1)"), "add") == reason
    )
    assert "Refresh Arena" in api._failure_message(OSError("gone"), "connect")
    assert "reconcile" in api._failure_message(OSError("gone"), "store")
    assert api._failure_message(KeyError("Saved deck not found."), "restore") == (
        "Saved deck not found."
    )


def test_arena_text_export_adds_printings_from_card_ids(monkeypatch):
    from mtga_tracker import deck_manager_api

    monkeypatch.setattr(deck_manager_api, "_PRINTINGS", {123: ("Forest", "DMU", "281")})
    deck = {
        "name": "Native",
        "import_text": None,
        "cards": [
            {"section": "Deck", "quantity": 4, "name": "Forest", "arena_id": 123},
            {"section": "Deck", "quantity": 1, "name": "Mystery", "arena_id": 999},
        ],
    }
    text = dm.portable_text(deck_manager_api._with_printings(deck))
    assert "4 Forest (DMU) 281" in text and "1 Mystery\n" not in text and text.endswith("1 Mystery")
    # Original import text always wins over a rebuilt list.
    assert deck_manager_api._with_printings({**deck, "import_text": "Deck\n4 Forest"}) == {
        **deck,
        "import_text": "Deck\n4 Forest",
    }
