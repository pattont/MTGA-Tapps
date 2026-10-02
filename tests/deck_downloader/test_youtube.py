import json
import time
from pathlib import Path

import pytest
import requests

from mtga_deck_downloader.config import AppConfig, DEFAULT_YOUTUBE_CREATORS, load_config
from mtga_deck_downloader.models import MatchFormat
from mtga_deck_downloader.providers.youtube import YouTubeProvider
from mtga_deck_downloader.scrapers.common import ScrapeError
from mtga_deck_downloader.scrapers.youtube import (
    ChannelListing,
    YouTubeBlocked,
    YouTubeScraper,
    _embedded_json,
    _latest_endpoint,
    _rich_grid,
    _video_ids,
)
from mtga_deck_downloader.scrapers.youtube_decklist import (
    clean_video_title,
    import_deck_name,
    parse_description,
)
from mtga_deck_downloader.youtube_channels import channel_videos_url


FIXTURES = Path(__file__).parent / "fixtures" / "youtube"
CHANNEL_ID = "UC9A1QEVgRm10zVgv0VMNu-A"


@pytest.mark.parametrize("file,count", [("hgg.txt", 14), ("sloth.txt", 22)])
def test_real_creator_lists_preserve_cards_and_normalize_heading(file, count):
    description = (FIXTURES / file).read_text()
    parsed = parse_description(description, "Standard")
    assert parsed.main_count == 60
    assert len(parsed.text.splitlines()) == count + 1
    assert parsed.text.splitlines()[0] == "Deck"
    expected = description.splitlines()[1 : count + 1]
    assert parsed.text.splitlines()[1:] == expected


@pytest.mark.parametrize("heading", ["Deck", "deck:", "Decklist:", "DECK LIST"])
def test_heading_variants_and_explicit_sections(heading):
    parsed = parse_description(
        f"Intro\n{heading}\n36 Forest\n24 Llanowar Elves\n\nSideboard\n2 Bushwhack\n\nWatch more: https://example.com"
    )
    assert parsed.text == "Deck\n36 Forest\n24 Llanowar Elves\n\nSideboard\n2 Bushwhack"


def test_commander_before_deck_and_unicode_card_names():
    parsed = parse_description(
        "Commander\n1 Éowyn, Shieldmaiden\n\nDeck\n59 Plains", "Standard Brawl"
    )
    assert parsed.commander_count == 1
    assert parsed.main_count == 59
    assert parsed.text.startswith("Commander\n1 Éowyn, Shieldmaiden\n\nDeck\n")


def test_missing_marker_and_marker_in_prose_are_not_lists():
    assert parse_description("My deck list is linked below\n60 Forest") is None
    assert parse_description("Deckbuilding tutorial\n60 Forest") is None


@pytest.mark.parametrize(
    "body",
    ["Deck\n59 Forest", "Deck\n0 Forest", "Deck\n60 Forest\n2", "Deck\n60 Forest\nDeck\n60 Island"],
)
def test_incomplete_malformed_or_ambiguous_lists_are_rejected(body):
    with pytest.raises(ValueError):
        parse_description(body)


def test_identical_repeated_lists_are_deduplicated():
    assert parse_description("Deck\n60 Forest\n\nDecklist:\n60 Forest").main_count == 60


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Ramp 5 Lands at Once | MTG Arena Standard", "Ramp 5 Lands at Once"),
        (
            "We BROKE Emrakul On Day 1?!! Turn 4.. It's OVER🔥🔥 | Reality Fracture MTG Arena",
            "We BROKE Emrakul On Day 1?!! Turn 4.. It's OVER",
        ),
        ("👨‍👩‍👧‍👦 🇺🇸 👍🏽 1️⃣ Éowyn’s Plan ❤️ | Standard", "Éowyn’s Plan"),
        ("Draw | Go | A Future Set MTG Arena", "Draw | Go"),
        ("Éowyn | A different approach", "Éowyn | A different approach"),
    ],
)
def test_title_cleanup(title, expected):
    assert clean_video_title(title) == expected
    assert import_deck_name(title, "Sloth") == expected + " (Sloth)"


def test_import_suffix_once_and_empty_title():
    assert import_deck_name("Ramp (HGG)", "HGG") == "Ramp (HGG)"
    with pytest.raises(ValueError):
        import_deck_name("🔥 | MTG Arena", "HGG")


@pytest.mark.parametrize(
    "reference",
    ["@SlothMtg", "https://youtube.com/@SlothMtg", "https://www.youtube.com/@SlothMtg/videos/"],
)
def test_channel_references(reference):
    assert channel_videos_url(reference) == "https://www.youtube.com/@SlothMtg/videos"


@pytest.mark.parametrize(
    "reference",
    [
        "https://evil.example/@SlothMtg",
        "http://youtube.com/@SlothMtg",
        "https://www.youtube.com/watch?v=OVM43LPOhD4",
        "https://youtube.com@evil.example/@SlothMtg",
        "@SlothMtg?url=https://evil.example",
    ],
)
def test_channel_validation_rejects_arbitrary_urls(reference):
    with pytest.raises(ValueError):
        channel_videos_url(reference)


def test_youtube_defaults_empty_config_and_alias_deduplication(tmp_path):
    path = tmp_path / "creators.json"
    path.write_text("{}")
    assert load_config(path).youtube_creators == DEFAULT_YOUTUBE_CREATORS
    path.write_text('{"YouTubeCreators": []}')
    assert load_config(path).youtube_creators == ()
    path.write_text(
        json.dumps(
            {
                "YouTubeCreators": [
                    {"Channel": "@SlothMtg", "ShortName": "Sloth"},
                    {"Channel": "https://www.youtube.com/@SlothMtg/videos", "ShortName": "Sloth"},
                ]
            }
        )
    )
    creators = load_config(path).youtube_creators
    assert len(creators) == 1
    assert creators[0].name == "Sloth"
    assert creators[0].label == "Sloth"


def video_item(video_id):
    return {
        "richItemRenderer": {
            "content": {
                "lockupViewModel": {
                    "contentId": video_id,
                    "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                }
            }
        }
    }


def grid_contents(ids):
    return {
        "header": {"chipViewModel": {"text": "Latest", "displayType": "DROPDOWN"}},
        "contents": [video_item(video_id) for video_id in ids],
    }


def listing_payload(ids):
    return {
        "metadata": {
            "channelMetadataRenderer": {"externalId": CHANNEL_ID, "title": "Hello Good Game"}
        },
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [
                    {
                        "tabRenderer": {
                            "selected": False,
                            "content": {"richGridRenderer": grid_contents(["wrong000000"])},
                        }
                    },
                    {
                        "tabRenderer": {
                            "selected": True,
                            "content": {"richGridRenderer": grid_contents(ids)},
                        }
                    },
                ]
            }
        },
    }


def html_listing(ids):
    return (
        "ytcfg.set({}); ytcfg.set("
        + json.dumps(
            {"INNERTUBE_CONTEXT": {"client": {"clientName": "WEB", "clientVersion": "test"}}}
        )
        + ");var ytInitialData = "
        + json.dumps(listing_payload(ids))
        + ";"
    )


class Response:
    status_code = 200

    def __init__(self, payload=None, text=""):
        self.payload = payload
        self.text = text

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def test_listing_only_selected_grid_latest_window_and_limit(monkeypatch):
    ids = [f"video{i:06d}" for i in range(18)]
    scraper = YouTubeScraper()
    monkeypatch.setattr(
        scraper, "_request", lambda *args, **kwargs: Response(text=html_listing(ids))
    )
    listing = scraper._listing(None, "@HelloGoodGame", time.monotonic() + 30)
    assert listing.video_ids == ids[:15]
    assert listing.channel_id == CHANNEL_ID
    assert _latest_endpoint(grid_contents(ids)) is None
    assert _rich_grid(listing_payload(ids))["contents"][0] == video_item(ids[0])


def test_unrecognized_listing_or_unconfirmed_sort_is_error():
    with pytest.raises(ScrapeError):
        _rich_grid({"contents": {}})
    with pytest.raises(ScrapeError):
        _latest_endpoint({"header": {"chipViewModel": {"text": "Popular"}}})
    assert _latest_endpoint(
        {
            "header": {
                "chipCloudChipRenderer": {
                    "text": {"simpleText": "Latest"},
                    "isSelected": False,
                    "navigationEndpoint": {
                        "browseEndpoint": {"browseId": CHANNEL_ID, "params": "latest"}
                    },
                }
            }
        }
    ) == {"browseId": CHANNEL_ID, "params": "latest"}


def test_members_only_and_non_video_items_are_skipped():
    member = video_item("member00000")
    member["richItemRenderer"]["content"]["lockupViewModel"]["badges"] = [
        {"thumbnailBadgeViewModel": {"text": "Members only"}}
    ]
    assert _video_ids(
        [
            member,
            video_item("video000000"),
            video_item("video000000"),
            {"watchEndpoint": {"videoId": "wrong000000"}},
        ]
    ) == ["video000000"]


def test_bounded_listing_continuation_and_small_channels(monkeypatch):
    scraper = YouTubeScraper()
    payload = listing_payload(["video000000"])
    grid = _rich_grid(payload)
    grid["contents"].append(
        {
            "continuationItemRenderer": {
                "continuationEndpoint": {"continuationCommand": {"token": "next"}}
            }
        }
    )
    html = (
        "ytcfg.set("
        + json.dumps({"INNERTUBE_CONTEXT": {}})
        + ");var ytInitialData = "
        + json.dumps(payload)
        + ";"
    )
    monkeypatch.setattr(scraper, "_request", lambda *args, **kwargs: Response(text=html))
    monkeypatch.setattr(
        scraper,
        "_browse",
        lambda *args: {
            "onResponseReceivedActions": [
                {
                    "appendContinuationItemsAction": {
                        "continuationItems": [video_item("video000001")]
                    }
                }
            ]
        },
    )
    assert scraper._listing(None, "@HelloGoodGame", time.monotonic() + 30).video_ids == [
        "video000000",
        "video000001",
    ]


def test_full_metadata_and_html_fallback(monkeypatch):
    scraper = YouTubeScraper()
    details = {"title": "Ramp", "shortDescription": (FIXTURES / "hgg.txt").read_text()}
    calls = []

    def request(session, method, url, deadline, **kwargs):
        calls.append((method, kwargs))
        if method == "POST":
            return Response(payload={})
        return Response(
            text="var ytInitialPlayerResponse = " + json.dumps({"videoDetails": details}) + ";"
        )

    monkeypatch.setattr(scraper, "_request", request)
    assert (
        scraper._metadata(None, "BfEESYLUBLQ", {}, time.monotonic() + 30)["videoDetails"] == details
    )
    assert calls[0][1]["params"]["fields"] == "videoDetails,microformat"
    assert "key" not in calls[0][1]["params"]
    assert [method for method, _ in calls] == ["POST", "GET"]


def test_blocked_metadata_does_not_fallback_or_hammer_youtube(monkeypatch):
    scraper = YouTubeScraper()

    def request(*args, **kwargs):
        raise YouTubeBlocked("Try later")

    monkeypatch.setattr(scraper, "_request", request)
    with pytest.raises(YouTubeBlocked):
        scraper._metadata(None, "BfEESYLUBLQ", {}, time.monotonic() + 30)


def test_timeout_is_checked_before_request():
    with pytest.raises(ScrapeError, match="timed out"):
        YouTubeScraper._request(None, "GET", "https://www.youtube.com", time.monotonic() - 1)


def test_fetch_orders_results_and_reports_failures_without_caching(monkeypatch):
    scraper = YouTubeScraper()
    ids = ["video000000", "video000001", "video000002"]
    monkeypatch.setattr(
        scraper, "_listing", lambda *args: ChannelListing(ids, CHANNEL_ID, "Hello Good Game", {})
    )

    def metadata(session, video_id, context, deadline):
        if video_id == ids[1]:
            raise requests.Timeout("A read timed out")
        if video_id == ids[0]:
            time.sleep(0.01)  # Complete the second successful video first.
        return {
            "videoDetails": {
                "videoId": video_id,
                "channelId": CHANNEL_ID,
                "title": f"🔥 {video_id} | Reality Fracture MTG Arena",
                "shortDescription": "Deck\n60 Forest",
            }
        }

    monkeypatch.setattr(scraper, "_metadata", metadata)
    decks = scraper.fetch_creator_decks(DEFAULT_YOUTUBE_CREATORS[0], limit=1)
    assert len(decks) == 1 and decks[0].name == ids[0]
    assert decks[0].deck_text == f"About\nName {ids[0]} (HGG)\n\nDeck\n60 Forest"
    assert decks.warnings and not decks.cacheable


def test_failed_creator_identity_is_never_imported(monkeypatch):
    scraper = YouTubeScraper()
    monkeypatch.setattr(
        scraper, "_listing", lambda *args: ChannelListing(["video000000"], CHANNEL_ID, "HGG", {})
    )
    monkeypatch.setattr(
        scraper,
        "_metadata",
        lambda *args: {
            "videoDetails": {
                "videoId": "video000000",
                "channelId": "other",
                "title": "Deck",
                "shortDescription": "Deck\n60 Forest",
            }
        },
    )
    with pytest.raises(ScrapeError, match="identity"):
        scraper.fetch_creator_decks(DEFAULT_YOUTUBE_CREATORS[0])


def test_provider_matches_creator_ui_and_hydration_requires_no_network(monkeypatch):
    monkeypatch.setattr(
        "mtga_deck_downloader.providers.youtube.load_config", lambda: AppConfig(())
    )
    provider = YouTubeProvider()
    assert provider.display_name == "youtube.com" and provider.description == "Creators"
    assert provider.source_picker_title == "Creators" and not provider.allow_all_sources
    assert provider.supported_formats == {MatchFormat.ANY}
    assert [source.name for source in provider.sources] == ["Hello Good Game", "Sloth"]
    called = []
    monkeypatch.setattr(
        provider._scraper,
        "fetch_creator_decks",
        lambda creator, limit: called.append((creator.label, limit)) or [],
    )
    provider.fetch_decks(MatchFormat.ANY, source=provider.sources[1])
    assert called == [("Sloth", 15)]
    assert provider.fetch_decks(MatchFormat.BO3) == []


def test_embedded_json_decodes_full_multiline_description():
    value = {"videoDetails": {"shortDescription": "Deck\n60 Forest\n#tags"}}
    assert (
        _embedded_json(
            "var ytInitialPlayerResponse = " + json.dumps(value) + ";",
            r"ytInitialPlayerResponse\s*=\s*",
        )
        == value
    )
