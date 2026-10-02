"""Keyless, metadata-only YouTube creator decks. No browser or media downloads."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Iterator

import requests

from mtga_deck_downloader.config import YouTubeCreatorConfig
from mtga_deck_downloader.models import DeckEntry, DeckFetchResult
from mtga_deck_downloader.scrapers.common import ScrapeError, create_session
from mtga_deck_downloader.scrapers.youtube_decklist import (
    clean_video_title,
    format_from_video,
    import_deck_name,
    parse_description,
)
from mtga_deck_downloader.youtube_channels import channel_videos_url


class YouTubeBlocked(ScrapeError):
    pass


@dataclass(frozen=True)
class ChannelListing:
    video_ids: list[str]
    channel_id: str
    name: str
    context: dict[str, Any]


def _objects(value: Any) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _embedded_json(html: str, pattern: str, required: str | None = None) -> dict:
    for match in re.finditer(pattern, html):
        try:
            value, _ = json.JSONDecoder().raw_decode(html[match.end() :].lstrip())
        except ValueError:
            continue
        if isinstance(value, dict) and (required is None or required in value):
            return value
    raise ScrapeError("YouTube did not return the expected public video metadata.")


def _rich_grid(payload: dict) -> dict:
    contents = payload.get("contents", {})
    for item in _objects(contents):
        for tab in item.get("tabs", []):
            renderer = tab.get("tabRenderer", {})
            if renderer.get("selected"):
                for child in _objects(renderer.get("content", {})):
                    if "richGridRenderer" in child:
                        return child["richGridRenderer"]
    # Some browse responses contain just the selected grid.
    if "richGridRenderer" in contents:
        return contents["richGridRenderer"]
    raise ScrapeError("YouTube's Videos tab could not be read. Please try again later.")


def _latest_endpoint(grid: dict) -> dict | None:
    """A selected Latest chip/dropdown proves ordering; otherwise follow its command."""
    for item in _objects(grid.get("header", {})):
        modern = item.get("chipViewModel")
        legacy = item.get("chipCloudChipRenderer")
        chip = modern or legacy
        if not chip:
            continue
        text = chip.get("text", "")
        if isinstance(text, dict):
            text = text.get("simpleText", "")
        if text != "Latest":
            continue
        if chip.get("selected") or chip.get("isSelected"):
            return None
        # The current dropdown displays the active sort as its text, without
        # a selected flag. Its popup is not another feed grid.
        if modern and "selected" not in chip and "isSelected" not in chip:
            return None
        for command in _objects(chip):
            if "browseEndpoint" in command:
                return command["browseEndpoint"]
    raise ScrapeError("Could not confirm YouTube's Latest video order.")


def _video_ids(contents: list) -> list[str]:
    ids = []
    for item in contents:
        # Restrict discovery to actual video items, not menus/recommendations.
        content = item.get("richItemRenderer", {}).get("content", item)
        modern = content.get("lockupViewModel", {})
        legacy = content.get("videoRenderer", {})
        if modern.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO":
            video_id = modern.get("contentId", "")
        else:
            video_id = legacy.get("videoId", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            continue
        members_only = any(
            obj.get("metadataBadgeRenderer", {}).get("label") == "Members only"
            or obj.get("thumbnailBadgeViewModel", {}).get("text") == "Members only"
            for obj in _objects(content)
        )
        if not members_only and video_id not in ids:
            ids.append(video_id)
    return ids


def _continuation(contents: list) -> str | None:
    for item in contents:
        renderer = item.get("continuationItemRenderer")
        if renderer:
            for obj in _objects(renderer):
                token = obj.get("continuationCommand", {}).get("token")
                if token:
                    return token
    return None


class YouTubeScraper:
    VIDEO_LIMIT = 15
    WORKERS = 3
    DEADLINE_SECONDS = 60

    @staticmethod
    def _request(session: requests.Session, method: str, url: str, deadline: float, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ScrapeError("YouTube lookup timed out. Please try again.")
        response = session.request(
            method, url, timeout=(min(5, remaining), min(12, remaining)), **kwargs
        )
        if response.status_code in {403, 429}:
            raise YouTubeBlocked("YouTube is limiting requests. Please try again later.")
        response.raise_for_status()
        return response

    def _browse(self, session, context, command, deadline):
        response = self._request(
            session,
            "POST",
            "https://www.youtube.com/youtubei/v1/browse",
            deadline,
            params={"prettyPrint": "false"},
            json={"context": context, **command},
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ScrapeError("YouTube returned an invalid channel listing.")
        return payload

    def _listing(self, session, channel, deadline) -> ChannelListing:
        response = self._request(
            session,
            "GET",
            channel_videos_url(channel),
            deadline,
            params={"hl": "en", "sort": "dd", "view": "0"},
        )
        payload = _embedded_json(response.text, r"(?:var\s+)?ytInitialData\s*=\s*")
        config = _embedded_json(response.text, r"ytcfg\.set\s*\(\s*(?=\{)", "INNERTUBE_CONTEXT")
        context = config["INNERTUBE_CONTEXT"]
        metadata = payload.get("metadata", {}).get("channelMetadataRenderer", {})
        channel_id = metadata.get("externalId", "")
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
            raise ScrapeError("YouTube's channel identity could not be verified.")
        grid = _rich_grid(payload)
        latest = _latest_endpoint(grid)
        if latest:
            grid = _rich_grid(self._browse(session, context, latest, deadline))
        contents = grid.get("contents", [])
        ids = _video_ids(contents)
        token = _continuation(contents)
        seen = set()
        while len(ids) < self.VIDEO_LIMIT and token:
            if token in seen or len(seen) >= 3:
                raise ScrapeError("YouTube's latest video listing was incomplete.")
            seen.add(token)
            payload = self._browse(session, context, {"continuation": token}, deadline)
            contents = [
                entry
                for obj in _objects(payload)
                for entry in obj.get("appendContinuationItemsAction", {}).get(
                    "continuationItems", []
                )
            ]
            if not contents:
                raise ScrapeError("YouTube's video listing continuation could not be read.")
            ids.extend(video_id for video_id in _video_ids(contents) if video_id not in ids)
            token = _continuation(contents)
        return ChannelListing(
            ids[: self.VIDEO_LIMIT], channel_id, metadata.get("title", ""), context
        )

    def _metadata(self, session, video_id, context, deadline) -> dict:
        try:
            response = self._request(
                session,
                "POST",
                "https://www.youtube.com/youtubei/v1/player",
                deadline,
                params={"prettyPrint": "false", "fields": "videoDetails,microformat"},
                json={"context": context, "videoId": video_id},
            )
            payload = response.json()
            details = payload.get("videoDetails", {})
            if details.get("title") and isinstance(details.get("shortDescription"), str):
                return payload
        except YouTubeBlocked:
            raise
        except (requests.RequestException, ValueError, AttributeError):
            pass
        response = self._request(
            session,
            "GET",
            "https://www.youtube.com/watch",
            deadline,
            params={"v": video_id, "hl": "en"},
        )
        payload = _embedded_json(response.text, r"(?:var\s+)?ytInitialPlayerResponse\s*=\s*")
        details = payload.get("videoDetails", {})
        if not details.get("title") or not isinstance(details.get("shortDescription"), str):
            raise ScrapeError("The full video description is unavailable.")
        return payload

    def fetch_creator_decks(
        self, creator: YouTubeCreatorConfig, limit: int = 15
    ) -> DeckFetchResult:
        deadline = time.monotonic() + self.DEADLINE_SECONDS
        sessions = []
        local = threading.local()
        blocked = threading.Event()
        with create_session() as bootstrap:
            listing = self._listing(bootstrap, creator.channel, deadline)

            def fetch(video_id):
                if blocked.is_set():
                    raise YouTubeBlocked("YouTube is limiting requests. Please try again later.")
                if not hasattr(local, "session"):
                    local.session = create_session()
                    local.session.headers.update(bootstrap.headers)
                    local.session.cookies.update(bootstrap.cookies)
                    sessions.append(local.session)
                try:
                    payload = self._metadata(local.session, video_id, listing.context, deadline)
                except YouTubeBlocked:
                    blocked.set()
                    raise
                details = payload["videoDetails"]
                if (
                    details.get("channelId") != listing.channel_id
                    or details.get("videoId") != video_id
                ):
                    raise ScrapeError("The video's creator identity could not be verified.")
                title = details["title"]
                description = details["shortDescription"]
                label = format_from_video(title, description)
                parsed = parse_description(description, label)
                if parsed is None:
                    return None
                display_name = listing.name or creator.name
                name = clean_video_title(title)
                imported = import_deck_name(title, creator.short_name or display_name)
                date = payload.get("microformat", {}).get("playerMicroformatRenderer", {})
                return DeckEntry(
                    name=name,
                    source_site="youtube.com",
                    source_url=f"https://www.youtube.com/watch?v={video_id}",
                    format_label=label,
                    player_name=display_name,
                    event_date=(date.get("publishDate") or date.get("uploadDate") or "")[:10]
                    or None,
                    deck_text=f"About\nName {imported}\n\n{parsed.text}",
                    notes=f"Creator: {display_name} | Video title: {title}",
                )

            decks = {}
            errors = []
            try:
                with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
                    futures = {
                        pool.submit(fetch, video_id): video_id for video_id in listing.video_ids
                    }
                    for future in as_completed(futures):
                        try:
                            deck = future.result()
                            if deck:
                                decks[futures[future]] = deck
                        except (requests.RequestException, ScrapeError, ValueError) as exc:
                            errors.append(str(exc))
            finally:
                for session in sessions:
                    session.close()
        warnings = []
        if errors:
            warnings.append(
                f"{len(errors)} of {len(listing.video_ids)} videos could not be imported. {errors[0]}"
            )
        if errors and not decks:
            raise ScrapeError(warnings[0])
        return DeckFetchResult(
            [decks[video_id] for video_id in listing.video_ids if video_id in decks][:limit],
            warnings,
        )
