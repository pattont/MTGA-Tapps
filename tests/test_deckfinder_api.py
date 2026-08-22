import time

import pytest

from mtga_deck_downloader.models import DeckEntry, DeckSource, MatchFormat
from mtga_deck_downloader.providers.base import DeckProvider
from mtga_tracker import deckfinder_api


class StubProvider(DeckProvider):
    key = "stub"
    display_name = "Stub Site"
    description = "Fixture decks for tests."
    homepage = "https://example.invalid/"

    def __init__(self) -> None:
        self.fetch_calls = 0

    @property
    def sources(self):
        return [
            DeckSource(
                name="Top Decks",
                url="https://example.invalid/top",
                description="The stub endpoint",
                formats=(MatchFormat.BO1, MatchFormat.BO3),
            )
        ]

    def fetch_decks(self, selected_format, limit=50, source=None):
        self.fetch_calls += 1
        return [
            DeckEntry(
                name="Stub Aggro",
                source_site="example.invalid",
                source_url="https://example.invalid/deck/1",
                format_label="Standard / Bo1",
                matches=120,
                win_rate=57.5,
                player_name="StubPlayer",
            )
        ]

    def hydrate_deck(self, deck):
        return DeckEntry(**{**deck.__dict__, "deck_text": "4 Stub Bear\n20 Forest"})


@pytest.fixture()
def stub_provider(monkeypatch):
    provider = StubProvider()
    monkeypatch.setattr(deckfinder_api, "_PROVIDERS", [provider])
    deckfinder_api._CACHE.clear()
    deckfinder_api._JOBS.clear()
    return provider


def _wait_for_job(job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = deckfinder_api._job_payload(job_id)
        if payload["status"] in ("done", "error"):
            return payload
        time.sleep(0.02)
    raise AssertionError("job never finished")


def test_providers_and_sources_endpoints(stub_provider):
    status, body = deckfinder_api.handle_get("/api/deckfinder/providers", {})
    assert status == 200
    assert body["providers"][0]["key"] == "stub"
    # Format options mirror the CLI's format screen: supported formats + Any.
    assert body["providers"][0]["format_options"] == ["bo1", "bo3", "any"]
    assert body["providers"][0]["creators"] == []

    status, body = deckfinder_api.handle_get(
        "/api/deckfinder/sources", {"provider": ["stub"], "format": ["bo1"]}
    )
    assert status == 200
    assert body["sources"][0]["url"] == "https://example.invalid/top"

    status, body = deckfinder_api.handle_get(
        "/api/deckfinder/sources", {"provider": ["nope"], "format": ["bo1"]}
    )
    assert status == 404


def test_fetch_runs_as_job_then_serves_from_cache(stub_provider):
    status, body = deckfinder_api.handle_post(
        "/api/deckfinder/fetch", {"provider": "stub", "format": "bo1"}
    )
    assert status == 200 and "job" in body
    result = _wait_for_job(body["job"])
    assert result["status"] == "done"
    assert result["decks"][0]["name"] == "Stub Aggro"
    assert result["view"]["count_label"] == "Decks found"
    # Table spec matches the CLI's dynamic columns for this data set:
    # win rate / matches / player present, no placing, no date.
    assert [column["key"] for column in result["view"]["columns"]] == [
        "index", "name", "win_rate", "matches", "player", "format", "notes",
    ]
    assert result["decks"][0]["cells"] == {
        "index": "1",
        "name": "Stub Aggro",
        "win_rate": "57.50%",
        "matches": "120",
        "player": "StubPlayer",
        "format": "Standard / Bo1",
        "notes": "-",
    }
    assert stub_provider.fetch_calls == 1

    # Second identical request: answered from cache, no new scrape.
    status, body = deckfinder_api.handle_post(
        "/api/deckfinder/fetch", {"provider": "stub", "format": "bo1"}
    )
    assert status == 200 and body.get("done") is True
    assert body["decks"][0]["name"] == "Stub Aggro"
    assert stub_provider.fetch_calls == 1

    # refresh=true forces a new scrape.
    status, body = deckfinder_api.handle_post(
        "/api/deckfinder/fetch", {"provider": "stub", "format": "bo1", "refresh": True}
    )
    _wait_for_job(body["job"])
    assert stub_provider.fetch_calls == 2


def test_untapped_bo3_without_win_rates_explains_why(monkeypatch):
    """untapped's free API has no Bo3 win rates (Premium-gated upstream);
    the view should say so instead of silently dropping the column."""

    class UntappedStub(StubProvider):
        key = "untapped"

        def fetch_decks(self, selected_format, limit=50, source=None):
            deck = super().fetch_decks(selected_format, limit, source)[0]
            return [DeckEntry(**{**deck.__dict__, "win_rate": None, "matches": 900})]

    provider = UntappedStub()
    monkeypatch.setattr(deckfinder_api, "_PROVIDERS", [provider])
    deckfinder_api._CACHE.clear()

    result = deckfinder_api._run_fetch("untapped", "bo3", "", "", 50)
    assert "Premium" in (result["view"]["helper_text"] or "")
    assert "win_rate" not in [c["key"] for c in result["view"]["columns"]]


def test_hydrate_resolves_deck_text(stub_provider):
    deck = {
        "name": "Stub Aggro",
        "source_site": "example.invalid",
        "source_url": "https://example.invalid/deck/1",
        "format_label": "Standard / Bo1",
    }
    status, body = deckfinder_api.handle_post(
        "/api/deckfinder/hydrate", {"provider": "stub", "deck": deck}
    )
    assert status == 200
    assert body["deck"]["deck_text"] == "4 Stub Bear\n20 Forest"


def test_creator_config_roundtrip(tmp_path, monkeypatch, stub_provider):
    """The Settings dialog reads/writes creators through these helpers."""
    config_path = tmp_path / "deckfinder_config.json"
    monkeypatch.setenv("MTGA_DECK_DOWNLOADER_CONFIG", str(config_path))

    body = deckfinder_api.write_creator_config(
        {
            "moxfield": [{"name": "SomeCreator", "short_name": "SC"}],
            "aetherhub": [{"name": "OtherCreator"}],
            "tcgplayer": [],
        }
    )
    assert body["moxfield"] == [{"name": "SomeCreator", "short_name": "SC"}]
    assert body["aetherhub"] == [{"name": "OtherCreator", "short_name": None}]
    assert config_path.exists()

    body = deckfinder_api.read_creator_config()
    assert body["moxfield"][0]["name"] == "SomeCreator"

    # The old HTTP config endpoints are gone (creators live in Settings now).
    assert deckfinder_api.handle_get("/api/deckfinder/config", {}) is None
    assert deckfinder_api.handle_post("/api/deckfinder/config", {}) is None
