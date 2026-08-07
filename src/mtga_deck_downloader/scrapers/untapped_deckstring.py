from __future__ import annotations

import base64
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class _DecodedDeck:
    main_deck_title_ids: list[int]
    sideboard_title_ids: list[int]
    wishboard_title_ids: list[int]
    commanders_title_ids: list[int]
    companions_title_ids: list[int]


class _DeckstringReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.index = 0

    def read_byte(self) -> int:
        if self.index >= len(self.payload):
            raise ValueError("Unexpected end of deckstring.")
        value = self.payload[self.index]
        self.index += 1
        return value

    def read_varint(self, optional: bool = False) -> int:
        if optional and self.index >= len(self.payload):
            return 0
        result = 0
        shift = 0
        while True:
            if self.index >= len(self.payload):
                if optional:
                    return result
                raise ValueError("Unexpected end of deckstring while reading varint.")
            value = self.read_byte()
            result |= (value & 0x7F) << shift
            if (value & 0x80) == 0:
                return result
            shift += 7
            if shift > 63:
                raise ValueError("Invalid varint in deckstring.")


class UntappedDeckstringDecoder:
    CARDS_URL = "https://mtgajson.untapped.gg/v1/latest/cards.json"
    LOCALE_URL = "https://mtgajson.untapped.gg/v1/latest/loc_en.json"

    _title_to_card: dict[int, dict] | None = None
    _title_to_name: dict[int, str] | None = None

    def __init__(self, session: requests.Session) -> None:
        self._session = session

    def decode_to_arena_text(self, deckstring: str) -> str | None:
        if not deckstring:
            return None
        self._ensure_lookups()
        if self._title_to_card is None or self._title_to_name is None:
            return None

        try:
            decoded = self._decode_deckstring(deckstring)
        except Exception:
            return None

        main_lines = self._title_ids_to_lines(decoded.main_deck_title_ids)
        if not main_lines:
            return None

        side_lines = self._title_ids_to_lines(decoded.wishboard_title_ids + decoded.sideboard_title_ids)
        companion_lines = self._title_ids_to_lines(decoded.companions_title_ids)
        commander_lines = self._title_ids_to_lines(decoded.commanders_title_ids)

        parts = ["Deck", *main_lines]
        if side_lines:
            parts.extend(["", "Sideboard", *side_lines])
        if companion_lines:
            parts.extend(["", "Companion", *companion_lines])
        if commander_lines:
            parts.extend(["", "Commander", *commander_lines])
        return "\n".join(parts)

    def _ensure_lookups(self) -> None:
        if self._title_to_card is not None and self._title_to_name is not None:
            return

        cards_resp = self._session.get(self.CARDS_URL, timeout=40)
        cards_resp.raise_for_status()
        cards_payload = cards_resp.json()

        locale_resp = self._session.get(self.LOCALE_URL, timeout=40)
        locale_resp.raise_for_status()
        locale_payload = locale_resp.json()

        title_to_card: dict[int, dict] = {}
        if isinstance(cards_payload, list):
            for card in cards_payload:
                if not isinstance(card, dict):
                    continue
                title_id = card.get("titleId")
                if isinstance(title_id, int):
                    title_to_card[title_id] = card

        title_to_name: dict[int, str] = {}
        if isinstance(locale_payload, list):
            for row in locale_payload:
                if not isinstance(row, dict):
                    continue
                title_id = row.get("id")
                text = row.get("text")
                if isinstance(title_id, int) and isinstance(text, str) and text:
                    title_to_name[title_id] = text

        self.__class__._title_to_card = title_to_card
        self.__class__._title_to_name = title_to_name

    def _decode_deckstring(self, deckstring: str) -> _DecodedDeck:
        payload = self._decode_payload(deckstring)
        reader = _DeckstringReader(payload)

        if reader.read_byte() != 0:
            raise ValueError("Invalid deckstring header.")
        version = reader.read_varint()

        if version == 1:
            return self._parse_v1(reader)
        if version == 2:
            return self._parse_v2(reader)
        if version == 3:
            return self._parse_v3(reader)
        if version == 4:
            return self._parse_v4(reader)
        raise ValueError(f"Unsupported Untapped deckstring version: {version}")

    @staticmethod
    def _decode_payload(deckstring: str) -> bytes:
        normalized = deckstring.replace("-", "+").replace("_", "/")
        padding = "=" * ((4 - (len(normalized) % 4)) % 4)
        return base64.b64decode(normalized + padding)

    def _parse_v1(self, reader: _DeckstringReader) -> _DecodedDeck:
        _ = reader.read_varint(optional=True)
        main = self._read_title_ids_block(reader)
        side = []
        if reader.read_varint(optional=True) == 1:
            side = self._read_title_ids_block(reader)
        return _DecodedDeck(main, side, [], [], [])

    def _parse_v2(self, reader: _DeckstringReader) -> _DecodedDeck:
        commanders = self._read_quantity_group(reader, 1)
        main = self._read_title_ids_block(reader)
        side = []
        if reader.read_varint(optional=True) == 1:
            side = self._read_title_ids_block(reader)
        return _DecodedDeck(main, side, [], commanders, [])

    def _parse_v3(self, reader: _DeckstringReader) -> _DecodedDeck:
        mechanics = self._read_mechanics(reader)
        commanders = mechanics.get(1, [])
        companions = mechanics.get(2, [])
        main = self._read_title_ids_block(reader)
        side = []
        if reader.read_varint(optional=True) == 1:
            side = self._read_title_ids_block(reader)
        return _DecodedDeck(main, side, [], commanders, companions)

    def _parse_v4(self, reader: _DeckstringReader) -> _DecodedDeck:
        mechanics = self._read_mechanics(reader)
        commanders = mechanics.get(1, [])
        companions = mechanics.get(2, [])

        main: list[int] = []
        side: list[int] = []
        wish: list[int] = []

        section = reader.read_varint(optional=True)
        while section > 0:
            cards = self._read_title_ids_block(reader)
            if section == 1:
                main = cards
            elif section == 2:
                side = cards
            elif section == 3:
                wish = cards
            section = reader.read_varint(optional=True)

        return _DecodedDeck(main, side, wish, commanders, companions)

    def _read_mechanics(self, reader: _DeckstringReader) -> dict[int, list[int]]:
        count = reader.read_varint()
        mechanics: dict[int, list[int]] = {}
        title_id = 0
        for _ in range(count):
            title_id += reader.read_varint()
            mechanic = reader.read_varint()
            mechanics.setdefault(mechanic, []).append(title_id)
        return mechanics

    def _read_title_ids_block(self, reader: _DeckstringReader) -> list[int]:
        cards: list[int] = []
        for quantity in (1, 2, 3, 4, None):
            cards.extend(self._read_quantity_group(reader, quantity))
        return cards

    def _read_quantity_group(self, reader: _DeckstringReader, quantity: int | None) -> list[int]:
        cards: list[int] = []
        entries = reader.read_varint(optional=True)
        title_id = 0
        for _ in range(entries):
            qty = quantity if quantity is not None else reader.read_varint()
            title_id += reader.read_varint()
            cards.extend([title_id] * qty)
        return cards

    def _title_ids_to_lines(self, title_ids: list[int]) -> list[str]:
        if not title_ids or self._title_to_card is None or self._title_to_name is None:
            return []

        counts: dict[int, int] = {}
        ordered_title_ids: list[int] = []
        for title_id in title_ids:
            if title_id not in counts:
                counts[title_id] = 0
                ordered_title_ids.append(title_id)
            counts[title_id] += 1

        lines: list[str] = []
        for title_id in ordered_title_ids:
            quantity = counts[title_id]
            card = self._title_to_card.get(title_id)
            name = self._title_to_name.get(title_id) or f"Unknown Card {title_id}"
            set_code = card.get("set") if isinstance(card, dict) else None
            collector_number = card.get("collectorNumber") if isinstance(card, dict) else None

            if isinstance(set_code, str) and isinstance(collector_number, str):
                lines.append(f"{quantity} {name} ({set_code}) {collector_number}")
            else:
                lines.append(f"{quantity} {name}")
        return lines
