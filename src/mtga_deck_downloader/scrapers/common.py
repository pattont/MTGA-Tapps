from __future__ import annotations

import threading

import requests


class ScrapeError(RuntimeError):
    """Raised when a scraper cannot fetch or parse expected data."""


# Cloudflare judges the TLS handshake, which depends on the local OpenSSL build.
# cloudscraper's Chrome profile passes on macOS, but on Windows with Python 3.9's
# OpenSSL 1.1.1 every Chrome profile is refused (403) while the Firefox one passes.
CLOUDFLARE_PROFILES = (
    {"browser": "chrome", "platform": "darwin", "mobile": False},
    {"browser": "firefox", "platform": "windows", "mobile": False},
)


def _cloudflare_blocked(response) -> bool:
    server = (getattr(response, "headers", None) or {}).get("server", "")
    return getattr(response, "status_code", None) == 403 and "cloudflare" in server.lower()


class CloudflareSession:
    """A cloudscraper session that moves to the next browser profile when Cloudflare
    refuses the current one, and keeps the profile that worked."""

    def __init__(self, headers: dict[str, str], profiles=CLOUDFLARE_PROFILES, factory=None):
        if factory is None:
            import cloudscraper

            factory = cloudscraper.create_scraper
        self._factory = factory
        self._profiles = tuple(profiles)
        self._extra_headers = dict(headers)
        self._lock = threading.Lock()
        self._index = 0
        self._session = self._open(0)

    def _open(self, index: int):
        session = self._factory(browser=dict(self._profiles[index]))
        headers = dict(self._extra_headers)
        if index:
            # Keep the fallback profile's own User-Agent so it matches its handshake.
            headers.pop("User-Agent", None)
        session.headers.update(headers)
        return session

    @property
    def headers(self):
        return self._session.headers

    @property
    def profile(self) -> dict:
        return dict(self._profiles[self._index])

    def get(self, *args, **kwargs):
        return self._request("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._request("post", *args, **kwargs)

    def _request(self, method: str, *args, **kwargs):
        index, session = self._index, self._session
        response = getattr(session, method)(*args, **kwargs)
        while _cloudflare_blocked(response) and index + 1 < len(self._profiles):
            with self._lock:
                if self._index == index:
                    self._index, self._session = index + 1, self._open(index + 1)
                index, session = self._index, self._session
            response = getattr(session, method)(*args, **kwargs)
        return response


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
    )
    return session


def decode_response_text(response: requests.Response) -> str:
    encoding = response.encoding or ""
    apparent = response.apparent_encoding or ""
    if _is_latin1_default(encoding) and apparent.lower().replace("_", "-") == "utf-8":
        encoding = "utf-8"
    if not encoding:
        encoding = apparent or "utf-8"
    return response.content.decode(encoding, errors="replace")


def _is_latin1_default(encoding: str) -> bool:
    normalized = encoding.lower().replace("_", "-")
    return normalized in {"iso-8859-1", "latin-1", "windows-1252"}
