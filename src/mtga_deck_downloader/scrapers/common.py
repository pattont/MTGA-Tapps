from __future__ import annotations

import requests


class ScrapeError(RuntimeError):
    """Raised when a scraper cannot fetch or parse expected data."""


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
