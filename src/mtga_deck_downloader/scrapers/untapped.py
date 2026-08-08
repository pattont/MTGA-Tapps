from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from mtga_deck_downloader.models import DeckEntry, MatchFormat
from mtga_deck_downloader.scrapers.common import ScrapeError, create_session, decode_response_text
from mtga_deck_downloader.scrapers.untapped_deckstring import UntappedDeckstringDecoder


@dataclass(frozen=True)
class _Tag:
    name: str
    tag_type: int | None


class UntappedScraper:
    API_BASE = "https://api.mtga.untapped.gg/api/v1"
    STANDARD_BO1_URL = "https://mtga.untapped.gg/constructed/standard/meta"
    STANDARD_BO3_URL = "https://mtga.untapped.gg/constructed/standard/meta?wincon=bo3"
    NEXT_DATA_RE = re.compile(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        re.DOTALL,
    )

    def __init__(self) -> None:
        self._session = create_session()
        self._session.headers.update({"Accept": "application/json"})
        self._deckstring_decoder = UntappedDeckstringDecoder(self._session)
        self._deck_text_cache: dict[str, str | None] = {}

    def fetch_decks(self, selected_format: MatchFormat, limit: int = 50) -> list[DeckEntry]:
        if selected_format is MatchFormat.BO1:
            return self._fetch_mode("Ladder", MatchFormat.BO1, limit)
        if selected_format is MatchFormat.BO3:
            return self._fetch_mode("Traditional_Ladder", MatchFormat.BO3, limit)

        half = max(1, limit // 2)
        bo1 = self._fetch_mode("Ladder", MatchFormat.BO1, half)
        bo3 = self._fetch_mode("Traditional_Ladder", MatchFormat.BO3, limit - half)
        return (bo1 + bo3)[:limit]

    def fetch_archetype_variants(
        self,
        archetype_entry: DeckEntry,
        selected_format: MatchFormat,
        limit: int = 50,
    ) -> list[DeckEntry]:
        parsed = self._parse_archetype_url(archetype_entry.source_url)
        if parsed is None:
            return []
        archetype_id, slug = parsed

        if selected_format is MatchFormat.ANY:
            match_format = self._infer_match_format(archetype_entry.format_label)
        else:
            match_format = selected_format
        archetype_url = self._build_archetype_url(archetype_id, slug, match_format)

        payload = self._extract_next_data_payload(archetype_url)
        page_props = payload.get("props", {}).get("pageProps", {})
        ssr_props = page_props.get("ssrProps", {})
        api_deck_data = ssr_props.get("apiDeckData", {})
        rows = api_deck_data.get("data") if isinstance(api_deck_data, dict) else None
        if not isinstance(rows, list):
            rows = []
        if not rows:
            rows = self._fetch_variant_rows_from_api(archetype_id, match_format)
        if not rows:
            return []

        format_label = "Standard / Bo3" if match_format is MatchFormat.BO3 else "Standard / Bo1"
        variants: list[DeckEntry] = []
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue

            deckstring = str(row.get("ds") or "").strip()
            if not deckstring:
                continue

            matches, wins = self._aggregate_ranked_stats(row.get("rs") or {})
            win_rate = (wins / matches) * 100 if wins is not None and matches > 0 else None
            deck_url = self._build_deck_url(archetype_id, slug, deckstring, match_format)
            name = self._build_variant_name(archetype_entry.name, deckstring, idx)

            notes_parts: list[str] = []
            notes_parts.append("Deck text is decoded on demand when opening details.")
            if win_rate is None:
                notes_parts.append(
                    f"Win-rate is not exposed for {format_label} in this payload."
                )
            notes = " ".join(notes_parts) if notes_parts else None

            variants.append(
                DeckEntry(
                    name=name,
                    source_site="mtga.untapped.gg",
                    source_url=deck_url,
                    format_label=format_label,
                    matches=matches if matches > 0 else None,
                    win_rate=win_rate,
                    deck_text=None,
                    notes=notes,
                )
            )

        variants.sort(
            key=lambda item: (
                item.win_rate is not None,
                item.win_rate if item.win_rate is not None else -1.0,
                item.matches if item.matches is not None else -1,
            ),
            reverse=True,
        )
        return variants[:limit]

    def _fetch_mode(
        self, event_name: str, match_format: MatchFormat, limit: int
    ) -> list[DeckEntry]:
        meta_period_id = self._get_meta_period_id(event_name)
        decks = self._get_json(
            (
                f"{self.API_BASE}/analytics/query/decks_by_event_scope_and_rank_v2/free"
                f"?MetaPeriodId={meta_period_id}&RankingClassScopeFilter=BRONZE_TO_PLATINUM"
            )
        )
        archetypes = self._get_json(
            (
                f"{self.API_BASE}/analytics/query/archetypes_by_event_scope_and_rank_v2/free"
                f"?MetaPeriodId={meta_period_id}&RankingClassScopeFilter=BRONZE_TO_PLATINUM"
            )
        )
        tags = self._get_json(f"{self.API_BASE}/tags")

        if not isinstance(decks, list):
            raise ScrapeError("Unexpected deck payload from Untapped API.")
        if not isinstance(archetypes, list):
            raise ScrapeError("Unexpected archetype payload from Untapped API.")

        variants_by_archetype = Counter()
        for deck in decks:
            if not isinstance(deck, dict):
                continue
            archetype_id = deck.get("ptg")
            deckstring = str(deck.get("ds") or "").strip()
            if isinstance(archetype_id, int) and deckstring:
                variants_by_archetype[archetype_id] += 1

        tags_by_id = self._build_tag_lookup(tags)
        archetype_names = self._build_archetype_names(archetypes, tags_by_id)
        format_label = "Standard / Bo3" if match_format is MatchFormat.BO3 else "Standard / Bo1"

        results: list[DeckEntry] = []
        for archetype in archetypes:
            if not isinstance(archetype, dict):
                continue

            archetype_id = archetype.get("primary_tag_group_id")
            if not isinstance(archetype_id, int):
                continue
            variants_count = variants_by_archetype.get(archetype_id, 0)
            if variants_count <= 0:
                continue

            matches, wins = self._aggregate_archetype_stats(archetype.get("stats") or {})
            if matches <= 0:
                continue

            win_rate = (wins / matches) * 100 if wins is not None and matches > 0 else None
            archetype_name = archetype_names.get(archetype_id, f"Archetype {archetype_id}")
            slug = self._slugify(archetype_name)
            source_url = self._build_archetype_url(archetype_id, slug, match_format)

            notes = f"{variants_count} variant decks available."

            results.append(
                DeckEntry(
                    name=archetype_name,
                    source_site="mtga.untapped.gg",
                    source_url=source_url,
                    format_label=format_label,
                    matches=matches,
                    win_rate=win_rate,
                    notes=notes,
                )
            )

        results.sort(
            key=lambda item: (
                item.win_rate is not None,
                item.win_rate if item.win_rate is not None else -1.0,
                item.matches if item.matches is not None else -1,
            ),
            reverse=True,
        )
        return results[:limit]

    def _get_meta_period_id(self, event_name: str) -> int:
        periods = self._get_json(f"{self.API_BASE}/meta-periods/active")
        if not isinstance(periods, list):
            raise ScrapeError("Unexpected meta period payload from Untapped API.")

        candidates = [period for period in periods if period.get("event_name") == event_name]
        if not candidates:
            raise ScrapeError(f"No active meta period found for {event_name}.")

        current = [period for period in candidates if period.get("end_ts") is None]
        chosen = current[0] if current else candidates[0]
        period_id = chosen.get("id")
        if not isinstance(period_id, int):
            raise ScrapeError("Meta period id is missing or invalid.")
        return period_id

    def _get_json(self, url: str) -> list[dict] | dict:
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ScrapeError(f"Unsupported JSON payload from {url}.")
        return payload

    def _extract_next_data_payload(self, url: str) -> dict:
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        match = self.NEXT_DATA_RE.search(decode_response_text(response))
        if not match:
            raise ScrapeError("Could not find __NEXT_DATA__ payload on Untapped page.")
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ScrapeError("Untapped page returned invalid __NEXT_DATA__ JSON.") from exc
        if not isinstance(payload, dict):
            raise ScrapeError("Untapped page returned invalid __NEXT_DATA__ payload.")
        return payload

    @staticmethod
    def _build_tag_lookup(tags_payload: list[dict] | dict) -> dict[int, _Tag]:
        if not isinstance(tags_payload, list):
            return {}
        lookup: dict[int, _Tag] = {}
        for row in tags_payload:
            if not isinstance(row, dict):
                continue
            tag_id = row.get("id")
            name = row.get("name")
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            tag_type = metadata.get("type")
            if isinstance(tag_id, int) and isinstance(name, str):
                lookup[tag_id] = _Tag(
                    name=name,
                    tag_type=tag_type if isinstance(tag_type, int) else None,
                )
        return lookup

    def _build_archetype_names(
        self, archetypes_payload: list[dict] | dict, tags_by_id: dict[int, _Tag]
    ) -> dict[int, str]:
        if not isinstance(archetypes_payload, list):
            return {}
        names: dict[int, str] = {}
        for row in archetypes_payload:
            if not isinstance(row, dict):
                continue
            group_id = row.get("primary_tag_group_id")
            tag_ids = row.get("primary_tags")
            if not isinstance(group_id, int) or not isinstance(tag_ids, list):
                continue
            resolved = [tags_by_id[tag_id] for tag_id in tag_ids if tag_id in tags_by_id]
            names[group_id] = self._compose_archetype_name(group_id, resolved)
        return names

    @staticmethod
    def _compose_archetype_name(group_id: int, tags: list[_Tag]) -> str:
        known_as = next((tag.name for tag in tags if tag.tag_type == 4), None)
        if known_as:
            return known_as

        color = next((tag.name for tag in tags if tag.tag_type == 7), None)
        strategy = next(
            (tag.name for tag in tags if tag.tag_type in {6, 2, 3, 1, 0}),
            None,
        )

        if color and strategy:
            return f"{color} {strategy}"
        if strategy:
            return strategy
        if color:
            return color
        if tags:
            return tags[0].name
        return f"Archetype {group_id}"

    @staticmethod
    def _aggregate_ranked_stats(rank_stats: dict) -> tuple[int, int | None]:
        matches = 0
        wins = 0
        has_win_data = False
        if not isinstance(rank_stats, dict):
            return matches, None

        for payload in rank_stats.values():
            if not isinstance(payload, list) or not payload:
                continue
            raw_matches = payload[0]
            raw_wins = payload[1] if len(payload) > 1 else None
            if isinstance(raw_matches, (int, float)):
                matches += int(raw_matches)
            if isinstance(raw_wins, (int, float)):
                has_win_data = True
                wins += int(raw_wins)
        if not has_win_data:
            return matches, None
        return matches, wins

    @staticmethod
    def _aggregate_archetype_stats(stats: dict) -> tuple[int, int | None]:
        matches = 0
        weighted_wins = 0.0
        has_win_data = False
        if not isinstance(stats, dict):
            return matches, None

        for rank_payload in stats.values():
            if not isinstance(rank_payload, dict):
                continue
            total_matches = rank_payload.get("total_matches")
            if not isinstance(total_matches, (int, float)):
                continue
            rank_matches = int(total_matches)
            if rank_matches <= 0:
                continue
            matches += rank_matches

            win_rate = rank_payload.get("winrate")
            if isinstance(win_rate, (int, float)):
                has_win_data = True
                weighted_wins += (float(win_rate) / 100.0) * rank_matches

        if not has_win_data:
            return matches, None
        return matches, int(round(weighted_wins))

    def _build_archetype_url(self, archetype_id: int, slug: str, match_format: MatchFormat) -> str:
        base = f"https://mtga.untapped.gg/constructed/standard/archetypes/{archetype_id}/{slug}"
        if match_format is MatchFormat.BO3:
            return f"{base}?wincon=bo3"
        return base

    def _build_deck_url(
        self,
        archetype_id: int,
        slug: str,
        deckstring: str,
        match_format: MatchFormat,
    ) -> str:
        base = (
            f"https://mtga.untapped.gg/constructed/standard/decks/"
            f"{archetype_id}/{slug}/{deckstring}"
        )
        if match_format is MatchFormat.BO3:
            return f"{base}?wincon=bo3"
        return base

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "archetype"

    @staticmethod
    def _parse_archetype_url(url: str) -> tuple[int, str] | None:
        match = re.search(r"/archetypes/(\d+)/([^/?#]+)", url)
        if not match:
            return None
        return int(match.group(1)), match.group(2)

    @staticmethod
    def _infer_match_format(format_label: str) -> MatchFormat:
        lowered = (format_label or "").lower()
        if "bo3" in lowered or "best of 3" in lowered:
            return MatchFormat.BO3
        return MatchFormat.BO1

    def _build_variant_name(self, archetype_name: str, deckstring: str, index: int) -> str:
        return f"{archetype_name} Deck {index} [{deckstring[:8]}]"

    def decode_deckstring(self, deckstring: str) -> str | None:
        if not deckstring:
            return None
        if deckstring in self._deck_text_cache:
            return self._deck_text_cache[deckstring]
        text = self._deckstring_decoder.decode_to_arena_text(deckstring)
        self._deck_text_cache[deckstring] = text
        return text

    def decode_deck_from_url(self, deck_url: str) -> str | None:
        match = re.search(r"/decks/\d+/[^/]+/([^/?#]+)", deck_url)
        if not match:
            return None
        return self.decode_deckstring(match.group(1))

    @staticmethod
    def _build_deck_signature(deck_text: str | None) -> str | None:
        if not deck_text:
            return None
        lines = [line.strip() for line in deck_text.splitlines() if line.strip()]
        if not lines:
            return None

        names: list[str] = []
        for line in lines:
            lowered = line.lower()
            if lowered in {"deck", "sideboard", "companion", "commander"}:
                if lowered != "deck":
                    break
                continue
            match = re.match(r"^\d+\s+(.+?)(?:\s+\([A-Za-z0-9]+\)\s+[^\s]+)?$", line)
            if not match:
                continue
            names.append(match.group(1).strip())
            if len(names) == 2:
                break
        if not names:
            return None
        return " / ".join(names)

    def _fetch_variant_rows_from_api(
        self, archetype_id: int, match_format: MatchFormat
    ) -> list[dict]:
        event_name = self._event_name_for_format(match_format)
        meta_period_id = self._get_meta_period_id(event_name)
        decks = self._get_json(
            (
                f"{self.API_BASE}/analytics/query/decks_by_event_scope_and_rank_v2/free"
                f"?MetaPeriodId={meta_period_id}&RankingClassScopeFilter=BRONZE_TO_PLATINUM"
            )
        )
        if not isinstance(decks, list):
            return []
        rows: list[dict] = []
        for row in decks:
            if not isinstance(row, dict):
                continue
            if row.get("ptg") != archetype_id:
                continue
            if not str(row.get("ds") or "").strip():
                continue
            rows.append(row)
        return rows

    @staticmethod
    def _event_name_for_format(match_format: MatchFormat) -> str:
        if match_format is MatchFormat.BO3:
            return "Traditional_Ladder"
        return "Ladder"
