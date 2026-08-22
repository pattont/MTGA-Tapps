"""Deck Finder HTTP API: dashboard endpoints over the deck-downloader providers.

The terminal Deck Finder's provider layer (mtga_deck_downloader.providers) is
UI-agnostic; this module exposes it to the dashboard's React page. Scrapes run
as background jobs (they take seconds and are rate-limited), results are
TTL-cached per (provider, format, source), and everything from the
deck-downloader package is imported lazily so the dashboard stays stdlib-only
until the Deck Finder page is actually opened.

Endpoints (all under /api/deckfinder/):
- GET  providers                 -> provider metadata for the picker
- GET  sources?provider=&format= -> source list for one provider
- POST fetch    {provider, format, source_url?, source_name?, limit?, refresh?}
                                 -> {done, decks, view} on cache hit or {job}
- GET  job?id=                   -> {status, note?, error?, decks?, view?}
- POST hydrate  {provider, deck} -> {deck} with deck_text resolved
- POST variants {provider, format, deck, source_name?}
                                 -> {job} (archetype variants / event decklists)
- POST surprise {format?}        -> {job} resolving to one random hydrated deck

Result payloads carry a per-site table spec ("columns" on the view plus a
"cells" dict per deck) computed with the same column rules as the terminal
Deck Finder (_show_deck_table in mtga_deck_downloader.ui), so each site's
table looks the same in the dashboard as it does in the terminal. Creator
lists are edited in the desktop Settings dialog (settings_dialog.py) through
read_creator_config/write_creator_config below.
"""

from __future__ import annotations

import dataclasses
import json
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: (provider_key, format, source_url, source_name) -> (monotonic_ts, decks, view)
_CACHE: Dict[
    Tuple[str, str, str, str], Tuple[float, List[Dict[str, Any]], Dict[str, Any]]
] = {}
_CACHE_TTL_SECONDS = 600.0

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOB_MAX_AGE_SECONDS = 3600.0

_PROVIDERS: Optional[list] = None
_PROVIDERS_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Provider access (lazy)


def _providers() -> list:
    global _PROVIDERS
    with _PROVIDERS_LOCK:
        if _PROVIDERS is None:
            from mtga_deck_downloader.providers.registry import load_providers

            _PROVIDERS = load_providers()
        return _PROVIDERS


def _invalidate_providers() -> None:
    """Drop provider instances and caches (after a config change)."""
    global _PROVIDERS
    with _PROVIDERS_LOCK:
        _PROVIDERS = None
    _CACHE.clear()


def _provider_by_key(key: str):
    for provider in _providers():
        if provider.key == key:
            return provider
    raise LookupError(f"Unknown Deck Finder provider: {key}")


def _match_format(raw: Optional[str]):
    from mtga_deck_downloader.models import MatchFormat

    value = str(raw or "any").lower()
    if value == "bo1":
        return MatchFormat.BO1
    if value == "bo3":
        return MatchFormat.BO3
    return MatchFormat.ANY


# --------------------------------------------------------------------------
# Serialization


def _serialize_source(source) -> Dict[str, Any]:
    return {
        "name": source.name,
        "url": source.url,
        "description": source.description,
        "formats": [fmt.value for fmt in source.formats],
    }


def _serialize_deck(deck) -> Dict[str, Any]:
    return dataclasses.asdict(deck)


def _deck_from_payload(payload: Dict[str, Any]):
    from mtga_deck_downloader.models import DeckEntry

    fields = {field.name for field in dataclasses.fields(DeckEntry)}
    kwargs = {key: value for key, value in payload.items() if key in fields}
    return DeckEntry(**kwargs)


def _serialize_view(view) -> Dict[str, Any]:
    return {
        "title": view.title,
        "count_label": view.count_label,
        "name_column_label": view.name_column_label,
        "selection_label": view.selection_label,
        "selection_action": view.selection_action,
        "helper_text": view.helper_text,
        "show_notes": view.show_notes,
    }


def _format_options(provider) -> List[str]:
    """Formats to offer after the site is picked, mirroring the terminal
    app's _pick_format: Any-only providers skip the choice entirely, others
    offer only the formats their sources actually carry (plus Any)."""
    from mtga_deck_downloader.models import MatchFormat

    supported = provider.supported_formats
    if supported == {MatchFormat.ANY}:
        return ["any"]
    options = [
        fmt.value for fmt in (MatchFormat.BO1, MatchFormat.BO3) if fmt in supported
    ]
    options.append("any")
    return options


def _serialize_provider(provider) -> Dict[str, Any]:
    return {
        "key": provider.key,
        "display_name": provider.display_name,
        "description": provider.description,
        "homepage": provider.homepage,
        "format_options": _format_options(provider),
        "uses_source_picker": provider.uses_source_picker,
        "allow_all_sources": provider.allow_all_sources,
        "source_picker_title": provider.source_picker_title,
        "source_picker_all_label": provider.source_picker_all_label,
        # Aetherhub shows its configured creators next to the format choice
        # (the terminal app's format screen); picking one fetches directly.
        "creators": [
            {
                "label": source.name.removeprefix("Creator: ").strip() or source.name,
                "name": source.name,
                "url": source.url,
                "description": source.description,
            }
            for source in provider.format_screen_sources
        ],
    }


# --------------------------------------------------------------------------
# Per-site table spec — a port of the terminal Deck Finder's column logic
# (_show_deck_table and friends in mtga_deck_downloader.ui). Keep the two in
# sync: each site's table should look the same in both UIs.


def _format_percent(value) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _note_value(notes: Optional[str], label: str) -> Optional[str]:
    if not notes:
        return None
    prefix = f"{label}:"
    for part in notes.split("|"):
        cleaned = part.strip()
        if cleaned.startswith(prefix):
            value = cleaned.removeprefix(prefix).strip()
            return value or None
    return None


def _display_note_parts(notes: str, source_site: str) -> List[str]:
    values: List[str] = []
    for part in notes.split("|"):
        cleaned = part.strip()
        if not cleaned:
            continue
        if source_site == "tcgplayer.com" and (
            cleaned.startswith("Creator:") or cleaned.startswith("Created:")
        ):
            continue
        values.append(cleaned)
    return values


def _aetherhub_creator_tags(notes: Optional[str]) -> str:
    if not notes:
        return "-"
    for part in notes.split("|"):
        cleaned = part.strip()
        if cleaned.startswith("Tags:"):
            tags = cleaned.removeprefix("Tags:").strip()
            return tags or "-"
    return "-"


def _is_magic_gg_ranked_decklist(event_name: Optional[str]) -> bool:
    lowered = (event_name or "").lower()
    return "standard ranked decklists" in lowered


def _table_note(
    deck,
    truncate: bool,
    include_event_name: bool = True,
    source_name: str = "",
) -> str:
    if deck.source_site == "aetherhub.com" and source_name.startswith("Creator: "):
        note = _aetherhub_creator_tags(deck.notes)
        return _truncate(note, 42) if truncate else note
    if deck.source_site == "moxfield.com":
        return deck.event_date or _note_value(deck.notes, "Updated") or "-"
    if deck.source_site == "magic.gg" and _is_magic_gg_ranked_decklist(deck.event_name):
        return "-"

    note_parts: List[str] = []
    if include_event_name and deck.event_name:
        note_parts.append(deck.event_name)
    if deck.notes:
        note_parts.extend(_display_note_parts(deck.notes, deck.source_site))
    if not note_parts:
        return "-"
    note = " | ".join(note_parts).replace("\n", " ").strip()
    return _truncate(note, 42) if truncate else note


def _notes_column_label(provider_key: str) -> str:
    if provider_key == "moxfield":
        return "Updated"
    return "Event/Notes"


def _date_column_label(provider_key: str, decks) -> Optional[str]:
    if not any(deck.event_date for deck in decks):
        return None
    if provider_key == "aetherhub":
        return "Posted"
    if provider_key in ("magic_gg", "mtgo"):
        return "Date"
    if provider_key == "tcgplayer" and any(
        _note_value(deck.notes, "Created") for deck in decks
    ):
        return "Created"
    return None


def _table_spec(
    provider,
    decks,
    view,
    source_name: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Column list + one display-cell dict per deck, matching the CLI table."""
    provider_key = provider.key
    show_win_rate = any(deck.win_rate is not None for deck in decks)
    show_matches = any(deck.matches is not None for deck in decks)
    show_placing = any(deck.placing is not None for deck in decks)
    show_player = provider_key != "tcgplayer" and any(
        deck.player_name is not None for deck in decks
    )
    show_notes = (
        provider_key not in {"magic_gg", "tcgplayer"}
        if view.show_notes is None
        else view.show_notes
    )
    date_label = _date_column_label(provider_key, decks)
    is_magic_gg = provider_key == "magic_gg"
    suppress_event_names = (
        provider_key == "tcgplayer"
        and source_name == "Events"
        and view.title.endswith("Top Decks")
    )

    columns: List[Dict[str, Any]] = [
        {"key": "index", "label": "#", "numeric": True},
        {"key": "name", "label": view.name_column_label},
    ]
    if show_win_rate:
        columns.append({"key": "win_rate", "label": "Win %", "numeric": True})
    if show_matches:
        columns.append({"key": "matches", "label": "Matches", "numeric": True})
    if show_placing:
        columns.append({"key": "placing", "label": "Place"})
    if show_player:
        columns.append({"key": "player", "label": "Player"})
    columns.append({"key": "format", "label": "Format"})
    if show_notes:
        columns.append({"key": "notes", "label": _notes_column_label(provider_key)})
    if date_label:
        columns.append({"key": "date", "label": date_label})

    cells: List[Dict[str, str]] = []
    for idx, deck in enumerate(decks, start=1):
        row = {
            "index": str(idx),
            "name": deck.name,
            "format": deck.format_label,
        }
        if show_win_rate:
            row["win_rate"] = _format_percent(deck.win_rate)
        if show_matches:
            row["matches"] = str(deck.matches) if deck.matches is not None else "-"
        if show_placing:
            row["placing"] = deck.placing or "-"
        if show_player:
            row["player"] = deck.player_name or "-"
        if show_notes:
            row["notes"] = _table_note(
                deck,
                truncate=not is_magic_gg,
                include_event_name=not suppress_event_names,
                source_name=source_name,
            )
        if date_label:
            row["date"] = deck.event_date or "-"
        cells.append(row)
    return columns, cells


# --------------------------------------------------------------------------
# Jobs


def _prune_jobs() -> None:
    cutoff = time.monotonic() - _JOB_MAX_AGE_SECONDS
    with _JOBS_LOCK:
        for job_id in [jid for jid, job in _JOBS.items() if job["created"] < cutoff]:
            _JOBS.pop(job_id, None)


def _start_job(runner, note: str) -> str:
    _prune_jobs()
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "running",
            "note": note,
            "created": time.monotonic(),
            "result": None,
            "error": None,
        }

    def _run() -> None:
        try:
            result = runner()
        except Exception as exc:  # surface scraper failures as readable errors
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job is not None:
                    job["status"] = "error"
                    job["error"] = f"{type(exc).__name__}: {exc}"
            return
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
            if job is not None:
                job["status"] = "done"
                job["result"] = result

    threading.Thread(target=_run, name=f"deckfinder-{job_id[:8]}", daemon=True).start()
    return job_id


def _job_payload(job_id: str) -> Dict[str, Any]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return {"status": "unknown"}
        payload: Dict[str, Any] = {"status": job["status"], "note": job["note"]}
        if job["status"] == "error":
            payload["error"] = job["error"]
        if job["status"] == "done":
            payload.update(job["result"] or {})
        return payload


# --------------------------------------------------------------------------
# Fetch / hydrate / variants / surprise


def _resolve_source(provider, source_url: Optional[str], source_name: str = ""):
    """Find a source across ALL of the provider's sources (creator sources
    included — Aetherhub keeps those off list_sources). Some providers reuse
    one URL for several sources (TCGplayer's sections), so the name
    disambiguates when given."""
    if not source_url and not source_name:
        return None
    for source in provider.sources:
        if source_url and source.url != source_url:
            continue
        if source_name and source.name != source_name:
            continue
        return source
    raise LookupError(f"Unknown source for {provider.key}: {source_name or source_url}")


def _run_fetch(
    provider_key: str,
    fmt_value: str,
    source_url: str,
    source_name: str,
    limit: int,
) -> Dict[str, Any]:
    provider = _provider_by_key(provider_key)
    fmt = _match_format(fmt_value)
    source = _resolve_source(provider, source_url or None, source_name)
    decks = provider.fetch_decks(fmt, limit=limit, source=source)
    view = provider.result_view_config(source)
    if (
        provider_key == "untapped"
        and decks
        and not any(deck.win_rate is not None for deck in decks)
    ):
        # untapped.gg's free API carries win rates for the Bo1 ladder only;
        # Bo3 (Traditional) meta stats are Premium-gated upstream. Say so
        # instead of silently dropping the Win % column.
        import dataclasses as _dc

        note = (
            "untapped.gg only shares Bo3 win rates with Premium subscribers, "
            "so these archetypes are ranked by matches played."
        )
        view = _dc.replace(
            view,
            helper_text=f"{view.helper_text} {note}" if view.helper_text else note,
        )
    columns, cells = _table_spec(provider, decks, view, source.name if source else "")
    serialized = [
        {**_serialize_deck(deck), "cells": row} for deck, row in zip(decks, cells)
    ]
    view_payload = {**_serialize_view(view), "columns": columns}
    _CACHE[(provider_key, fmt_value, source_url, source_name)] = (
        time.monotonic(),
        serialized,
        view_payload,
    )
    return {"decks": serialized, "view": view_payload}


def _handle_fetch(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider_key = str(payload.get("provider") or "")
    fmt_value = str(payload.get("format") or "any").lower()
    source_url = str(payload.get("source_url") or "")
    source_name = str(payload.get("source_name") or "")
    limit = max(1, min(int(payload.get("limit") or 50), 100))
    refresh = bool(payload.get("refresh"))

    _provider_by_key(provider_key)  # validate early, before spawning a job
    if not refresh:
        cached = _CACHE.get((provider_key, fmt_value, source_url, source_name))
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return {"done": True, "decks": cached[1], "view": cached[2]}

    job_id = _start_job(
        lambda: _run_fetch(provider_key, fmt_value, source_url, source_name, limit),
        note=f"Fetching decks from {provider_key}…",
    )
    return {"job": job_id}


def _handle_variants(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider_key = str(payload.get("provider") or "")
    fmt_value = str(payload.get("format") or "any").lower()
    source_name = str(payload.get("source_name") or "")
    deck_payload = payload.get("deck")
    if not isinstance(deck_payload, dict):
        raise ValueError("variants requires a deck payload")
    provider = _provider_by_key(provider_key)
    parent = _deck_from_payload(deck_payload)

    def _run() -> Dict[str, Any]:
        fmt = _match_format(fmt_value)
        variants = provider.fetch_deck_variants(parent, fmt) or []
        view = provider.result_view_config(None, variants=True, parent=parent)
        columns, cells = _table_spec(provider, variants, view, source_name)
        return {
            "decks": [
                {**_serialize_deck(deck), "cells": row}
                for deck, row in zip(variants, cells)
            ],
            "view": {**_serialize_view(view), "columns": columns},
        }

    return {"job": _start_job(_run, note=f"Loading variants of {parent.name}…")}


def _handle_hydrate(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = _provider_by_key(str(payload.get("provider") or ""))
    deck_payload = payload.get("deck")
    if not isinstance(deck_payload, dict):
        raise ValueError("hydrate requires a deck payload")
    hydrated = provider.hydrate_deck(_deck_from_payload(deck_payload))
    return {"deck": _serialize_deck(hydrated)}


def _handle_surprise(payload: Dict[str, Any]) -> Dict[str, Any]:
    fmt_value = str(payload.get("format") or "any").lower()

    def _run() -> Dict[str, Any]:
        fmt = _match_format(fmt_value)
        candidates = [
            provider
            for provider in _providers()
            if fmt in provider.supported_formats or fmt.value == "any"
        ]
        random.shuffle(candidates)
        last_error: Optional[str] = None
        for provider in candidates:
            try:
                decks = provider.fetch_decks(fmt, limit=25)
            except Exception as exc:
                last_error = f"{provider.display_name}: {exc}"
                continue
            if not decks:
                continue
            deck = provider.hydrate_deck(random.choice(decks))
            return {
                "provider": provider.key,
                "deck": _serialize_deck(deck),
            }
        raise RuntimeError(last_error or "No provider returned any decks")

    return {"job": _start_job(_run, note="Finding you a surprise deck…")}


# --------------------------------------------------------------------------
# Creator config (read/written by the desktop Settings dialog)


def _creator_list(creators) -> List[Dict[str, Any]]:
    return [
        {"name": creator.name, "short_name": creator.short_name}
        for creator in creators
    ]


def read_creator_config() -> Dict[str, Any]:
    from mtga_deck_downloader.config import load_config, resolve_config_path

    config = load_config()
    return {
        "path": str(resolve_config_path()),
        "moxfield": _creator_list(config.moxfield_creators),
        "aetherhub": _creator_list(config.aetherhub_creators),
        "tcgplayer": _creator_list(config.tcgplayer_creators),
    }


def _writable_config_path() -> Path:
    from mtga_deck_downloader.config import (
        BUNDLED_CONFIG_PATH,
        resolve_config_path,
        user_config_path,
    )

    resolved = resolve_config_path()
    if resolved == BUNDLED_CONFIG_PATH:
        # Never write into the bundled default — promote to the user config.
        return user_config_path()
    return resolved


def write_creator_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    def _entries(key: str) -> List[Dict[str, str]]:
        entries = []
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            entry: Dict[str, str] = {"Name": name}
            short = str(item.get("short_name") or "").strip()
            if short:
                entry["ShortName"] = short
            entries.append(entry)
        return entries

    document = {
        "MoxfieldNames": _entries("moxfield"),
        "AtherhubCreators": _entries("aetherhub"),
        "TcgplayerCreators": _entries("tcgplayer"),
    }
    path = _writable_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _invalidate_providers()
    return read_creator_config()


# --------------------------------------------------------------------------
# HTTP dispatch (called from dashboard.py; returns (status, json_dict) or None)


def handle_get(path: str, query: Dict[str, List[str]]) -> Optional[Tuple[int, Dict[str, Any]]]:
    try:
        if path == "/api/deckfinder/providers":
            return 200, {"providers": [_serialize_provider(p) for p in _providers()]}
        if path == "/api/deckfinder/sources":
            provider = _provider_by_key(query.get("provider", [""])[0])
            fmt = _match_format(query.get("format", [None])[0])
            sources = provider.list_sources(fmt) if provider.uses_source_picker else []
            return 200, {"sources": [_serialize_source(s) for s in sources]}
        if path == "/api/deckfinder/job":
            return 200, _job_payload(query.get("id", [""])[0])
    except LookupError as exc:
        return 404, {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return None


def handle_post(path: str, payload: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
    try:
        if path == "/api/deckfinder/fetch":
            return 200, _handle_fetch(payload)
        if path == "/api/deckfinder/variants":
            return 200, _handle_variants(payload)
        if path == "/api/deckfinder/hydrate":
            return 200, _handle_hydrate(payload)
        if path == "/api/deckfinder/surprise":
            return 200, _handle_surprise(payload)
    except LookupError as exc:
        return 404, {"error": str(exc)}
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return None
