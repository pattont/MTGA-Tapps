import time
import json
import os
import subprocess
import sys

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


def test_cold_site_picker_does_not_import_scrapers_or_create_network_clients(tmp_path):
    """Use a fresh interpreter so imports cached by other tests cannot hide eager work."""
    config = tmp_path / "creators.json"
    config.write_text("{}")
    script = '''
import importlib.abc
import sys
from mtga_tracker import deckfinder_api

class NoScrapers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("mtga_deck_downloader.scrapers") or fullname.split(".")[0] in {"requests", "cloudscraper", "bs4", "emoji"}:
            raise AssertionError("Site picker imported " + fullname)

sys.meta_path.insert(0, NoScrapers())
status, body = deckfinder_api.handle_get("/api/deckfinder/providers", {})
assert status == 200, body
assert len(body["providers"]) == 7, body
assert not body["errors"], body
for provider in body["providers"]:
    status, sources = deckfinder_api.handle_get("/api/deckfinder/sources", {"provider": [provider["key"]], "format": ["any"]})
    assert status == 200, sources
assert not deckfinder_api._JOBS and not deckfinder_api._CACHE
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "MTGA_DECK_DOWNLOADER_CONFIG": str(config)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


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


def test_youtube_creator_settings_preserve_older_payloads_and_unrelated_keys(
    tmp_path, monkeypatch, stub_provider
):
    path = tmp_path / "creators.json"
    monkeypatch.setenv("MTGA_DECK_DOWNLOADER_CONFIG", str(path))
    path.write_text(json.dumps({"custom": {"keep": True}}))
    body = deckfinder_api.write_creator_config(
        {"youtube": [{"name": "@SlothMtg", "short_name": "Sloth"}]}
    )
    assert body["youtube"] == [
        {
            "name": "Sloth",
            "short_name": "Sloth",
            "channel": "https://www.youtube.com/@SlothMtg/videos",
        }
    ]
    assert json.loads(path.read_text())["custom"] == {"keep": True}
    deckfinder_api.write_creator_config({"moxfield": [], "aetherhub": [], "tcgplayer": []})
    assert deckfinder_api.read_creator_config()["youtube"] == body["youtube"]
    deckfinder_api.write_creator_config({"youtube": []})
    assert deckfinder_api.read_creator_config()["youtube"] == []


def test_invalid_youtube_creator_never_overwrites_configuration(
    tmp_path, monkeypatch, stub_provider
):
    path = tmp_path / "creators.json"
    path.write_text('{"custom": "keep"}')
    monkeypatch.setenv("MTGA_DECK_DOWNLOADER_CONFIG", str(path))
    with pytest.raises(ValueError, match="channel"):
        deckfinder_api.write_creator_config({"youtube": [{"name": "https://evil.example/"}]})
    assert path.read_text() == '{"custom": "keep"}'


def test_youtube_result_warnings_are_visible_and_not_cached(monkeypatch, stub_provider):
    from mtga_deck_downloader.models import DeckFetchResult

    decks = stub_provider.fetch_decks(MatchFormat.ANY)
    monkeypatch.setattr(
        stub_provider,
        "fetch_decks",
        lambda *args, **kwargs: DeckFetchResult(decks, ["One video failed."]),
    )
    body = deckfinder_api._run_fetch("stub", "any", "", "", 15)
    assert "One video failed." in body["view"]["helper_text"]
    assert not deckfinder_api._CACHE


def test_youtube_creator_table_and_refresh_reuse_existing_cache(monkeypatch, stub_provider):
    stub_provider.key = "youtube"
    payload = {"provider": "youtube", "format": "any"}
    first = deckfinder_api._handle_fetch(payload)
    done = _wait_for_job(first["job"])
    assert "latest 15 YouTube videos" in done["note"]
    assert {"key": "player", "label": "Creator"} in done["view"]["columns"]
    assert deckfinder_api._handle_fetch(payload)["done"]
    assert stub_provider.fetch_calls == 1
    fresh = deckfinder_api._handle_fetch({**payload, "refresh": True})
    assert _wait_for_job(fresh["job"])["status"] == "done"
    assert stub_provider.fetch_calls == 2
