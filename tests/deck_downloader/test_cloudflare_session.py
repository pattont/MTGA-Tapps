from __future__ import annotations

from mtga_deck_downloader.scrapers.common import CLOUDFLARE_PROFILES, CloudflareSession


class FakeResponse:
    def __init__(self, status_code: int, server: str = "cloudflare") -> None:
        self.status_code = status_code
        self.headers = {"server": server}


class FakeScraper:
    def __init__(self, browser: dict, statuses: list[int], server: str = "cloudflare") -> None:
        self.browser = browser
        self.headers = {"User-Agent": f"{browser['browser']} profile UA"}
        self.statuses = list(statuses)
        self.server = server
        self.calls: list[tuple[str, tuple, dict]] = []

    def get(self, *args, **kwargs):
        self.calls.append(("get", args, kwargs))
        return FakeResponse(self.statuses.pop(0), self.server)

    def post(self, *args, **kwargs):
        self.calls.append(("post", args, kwargs))
        return FakeResponse(self.statuses.pop(0), self.server)


def factory_for(statuses_by_browser: dict[str, list[int]], server: str = "cloudflare"):
    created: list[FakeScraper] = []

    def factory(browser: dict) -> FakeScraper:
        scraper = FakeScraper(browser, statuses_by_browser[browser["browser"]], server)
        created.append(scraper)
        return scraper

    return factory, created


HEADERS = {"User-Agent": "Mac Chrome UA", "Accept-Language": "en-US"}


def test_chrome_profile_is_kept_when_cloudflare_accepts_it():
    factory, created = factory_for({"chrome": [200, 200]})
    session = CloudflareSession(HEADERS, factory=factory)

    assert session.get("https://moxfield.com/", timeout=5).status_code == 200
    assert session.get("https://moxfield.com/").status_code == 200
    assert [s.browser["browser"] for s in created] == ["chrome"]
    assert session.headers["User-Agent"] == "Mac Chrome UA"


def test_cloudflare_block_moves_to_firefox_and_stays_there():
    factory, created = factory_for({"chrome": [403], "firefox": [200, 200]})
    session = CloudflareSession(HEADERS, factory=factory)

    response = session.post("https://aetherhub.com/api", json={"a": 1}, timeout=40)

    assert response.status_code == 200
    assert [s.browser for s in created] == list(CLOUDFLARE_PROFILES)
    # The same request is repeated with the same arguments on the new profile.
    assert created[1].calls == [
        ("post", ("https://aetherhub.com/api",), {"json": {"a": 1}, "timeout": 40})
    ]
    # The fallback keeps its own User-Agent but the scraper's other headers.
    assert session.headers["User-Agent"] == "firefox profile UA"
    assert session.headers["Accept-Language"] == "en-US"
    assert session.profile["browser"] == "firefox"
    session.get("https://aetherhub.com/")
    assert len(created) == 2


def test_last_profile_block_is_returned_for_the_scraper_to_report():
    factory, created = factory_for({"chrome": [403], "firefox": [403]})
    session = CloudflareSession(HEADERS, factory=factory)

    assert session.get("https://moxfield.com/").status_code == 403
    assert len(created) == 2


def test_a_403_that_is_not_from_cloudflare_does_not_switch_profiles():
    factory, created = factory_for({"chrome": [403]}, server="nginx")
    session = CloudflareSession(HEADERS, factory=factory)

    assert session.get("https://moxfield.com/private").status_code == 403
    assert len(created) == 1
