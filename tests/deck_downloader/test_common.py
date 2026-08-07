from __future__ import annotations

import unittest

from mtga_deck_downloader.scrapers.common import decode_response_text


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        *,
        encoding: str | None = None,
        apparent_encoding: str | None = None,
    ) -> None:
        self.content = content
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding


class CommonScraperTests(unittest.TestCase):
    def test_decode_response_text_prefers_utf8_over_latin1_default_when_detected(self) -> None:
        response = FakeResponse(
            "2 Mjölnir, Hammer of Thor".encode("utf-8"),
            encoding="ISO-8859-1",
            apparent_encoding="utf-8",
        )

        self.assertEqual(decode_response_text(response), "2 Mjölnir, Hammer of Thor")

    def test_decode_response_text_keeps_declared_utf8_plain_text(self) -> None:
        response = FakeResponse(
            "Deck\n4 Island".encode("utf-8"),
            encoding="utf-8",
            apparent_encoding="utf-8",
        )

        self.assertEqual(decode_response_text(response), "Deck\n4 Island")


if __name__ == "__main__":
    unittest.main()
