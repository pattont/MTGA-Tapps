"""Dashboard settings endpoints.

The dashboard only serves localhost, so the same values the desktop
Settings dialog edits (settings.json's "deck_ai" section and
deckfinder_config.json) are readable/writable from the web Settings page.

Endpoints (all under /api/settings):
- GET  /api/settings           -> tracker, startup, Deck AI/Finder, platform, overlay
- POST /api/settings/startup   -> save login and automatic-browser preferences
- POST /api/settings/updates   -> save update preferences (partial booleans:
                                  check, auto_download, auto_install)
- POST /api/settings/deck-ai   -> save AI provider/keys/models
- POST /api/settings/deck-ai/models -> {provider, api_key?} list the models
                                  that key can use (asks the provider)
- POST /api/settings/deck-finder -> save the creator lists
- POST /api/settings/overlay   -> {enabled} start/stop the in-game overlay, or
                                  {request: "open-settings"} to open its ⚙ flyout
- POST /api/settings/buy-on-paper -> {enabled} show Buy on Paper; off stops store
                                  price downloads and deletes the saved lists
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _ai_providers():
    from .deck_llm import PROVIDERS

    return PROVIDERS


def _deck_ai_payload() -> Dict[str, Any]:
    from . import deck_llm

    stored = deck_llm.load_settings()
    providers = []
    for info in _ai_providers():
        providers.append(
            {
                "key": info.key,
                "label": info.label,
                "api_key": str(
                    stored.get(info.api_key_setting) or deck_llm._get_api_key(info.key) or ""
                ),
                "model": deck_llm.stored_model(info.key),
                "default_model": info.default_model,
                "models_url": info.models_url,
            }
        )
    return {
        "enabled": deck_llm.is_deck_llm_enabled(),
        "provider": deck_llm._get_provider(),
        "providers": providers,
    }


def _save_deck_ai(payload: Dict[str, Any]) -> Dict[str, Any]:
    from . import deck_llm

    provider = str(payload.get("provider") or "").strip().lower()
    if provider not in {p.key for p in _ai_providers()}:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    keys = payload.get("keys") if isinstance(payload.get("keys"), dict) else {}
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}

    values: Dict[str, Any] = {
        "DECK_LLM_ENABLED": bool(payload.get("enabled")),
        "DECK_LLM_PROVIDER": provider,
    }
    for info in _ai_providers():
        internal, key_name, model_name = info.key, info.api_key_setting, info.model_setting
        key_value = str(keys.get(internal) or "").strip()
        model_value = str(models.get(internal) or "").strip()
        if internal == provider:
            # The selected provider's fields are authoritative (an empty key
            # clears it). An empty model is stored empty so it follows the
            # provider default when that changes.
            values[key_name] = key_value
            values[model_name] = model_value
        else:
            # Keep edits to non-selected providers without clearing values
            # the page never loaded.
            if key_value:
                values[key_name] = key_value
            if model_value:
                values[model_name] = model_value
    deck_llm.save_settings(values)
    return _deck_ai_payload()


def _list_deck_ai_models(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the provider which models the key can use. The key may be one the
    page has not saved yet; it goes only to that provider."""
    from . import deck_llm

    provider = str(payload.get("provider") or "").strip().lower()
    api_key = str(payload.get("api_key") or "").strip() or None
    return {"provider": provider, "models": deck_llm.list_models(provider, api_key)}


def _tilde(value: Any) -> Optional[str]:
    """Hide the username in a path shown on the Settings page.

    ``~/...`` on macOS and Linux; ``%USERPROFILE%\\...`` on Windows, where
    ``~`` means nothing to Explorer or cmd but ``%USERPROFILE%`` expands, so
    the shown path still pastes straight into the address bar.
    """
    if not value:
        return None
    from .rendering import display_path_without_username

    return display_path_without_username(value)


def _deck_ai_summary() -> str:
    from . import deck_llm

    try:
        status = deck_llm.diagnose()
    except Exception:
        return "unknown"
    if not status.get("enabled"):
        return "disabled"
    provider_label = deck_llm.provider_label(str(status.get("provider") or ""))
    if not status.get("has_api_key"):
        return f"enabled — {provider_label} (no API key set)"
    return f"enabled — {provider_label} ({status.get('model') or '?'})"


def _tracker_info(db_path: Optional[Path]) -> Dict[str, Any]:
    """Startup facts the tracker records into live_status (refreshed every
    time the tracker starts), plus the Deck AI summary and version."""
    from . import __version__ as tracker_version

    info: Dict[str, Any] = {
        "monitoring": None,
        "card_db": None,
        "log_db": _tilde(db_path),
        "deck_ai": _deck_ai_summary(),
        "version": tracker_version,
    }
    if db_path is not None and Path(db_path).is_file():
        try:
            import sqlite3

            db_uri = Path(db_path).expanduser().resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(db_uri, uri=True) as conn:
                row = conn.execute(
                    "SELECT log_path, card_db_path, db_path, tracker_version "
                    "FROM live_status WHERE id = 1"
                ).fetchone()
            if row is not None:
                info["monitoring"] = _tilde(row[0])
                info["card_db"] = _tilde(row[1])
                info["log_db"] = _tilde(row[2]) or info["log_db"]
                info["version"] = row[3] or info["version"]
        except Exception:
            pass
    return info


def _platform_info() -> Dict[str, Any]:
    import sys

    system = (
        "macos" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "other"
    )
    return {
        "system": system,
        # Collection export reads process memory, which only the macOS/Windows
        # readers implement.
        "collection_export": system in {"macos", "windows"},
    }


def _overlay_status() -> Dict[str, Any]:
    """Whether the in-game overlay is shipped, enabled, and running."""
    from .overlay_launcher import get_manager

    return get_manager().refresh()


def _startup_payload() -> Dict[str, Any]:
    from .settings import load_app_settings
    from .startup import registration_status

    settings = load_app_settings(create=False)
    return {
        "start_at_login": settings.start_at_login,
        "open_dashboard_on_launch": settings.open_dashboard_on_launch,
        **registration_status().to_dict(),
    }


def _save_startup(payload: Dict[str, Any]) -> Dict[str, Any]:
    from .settings import load_app_settings, save_startup_settings
    from .startup import set_start_at_login

    keys = ("start_at_login", "open_dashboard_on_launch")
    if not any(key in payload for key in keys):
        raise ValueError("A startup setting is required.")
    for key in keys:
        if key in payload and not isinstance(payload[key], bool):
            raise ValueError(f"'{key}' must be a boolean")

    current = load_app_settings(create=False)
    start_at_login = payload.get("start_at_login", current.start_at_login)
    open_dashboard = payload.get("open_dashboard_on_launch", current.open_dashboard_on_launch)
    registration_changed = "start_at_login" in payload
    if registration_changed:
        set_start_at_login(start_at_login)
    try:
        save_startup_settings(
            start_at_login=start_at_login,
            open_dashboard_on_launch=open_dashboard,
        )
    except Exception:
        if registration_changed:
            try:
                set_start_at_login(current.start_at_login)
            except Exception:
                pass
        raise
    return _startup_payload()


UPDATE_SETTING_KEYS = ("check", "auto_download", "auto_install")


def _updates_payload() -> Dict[str, Any]:
    from .settings import load_app_settings
    from .updater import get_manager

    settings = load_app_settings(create=False)
    try:
        support = get_manager().support()
    except Exception:  # pragma: no cover - defensive surface
        support = {"supported": False, "install_kind": "unknown"}
    return {
        "check": settings.update_check,
        "auto_download": settings.update_auto_download,
        "auto_install": settings.auto_install_updates,
        "channel": settings.update_channel,
        "skipped_version": settings.skipped_update_version,
        "supported": bool(support.get("supported")),
        "install_kind": str(support.get("install_kind") or "unknown"),
    }


def _save_updates(payload: Dict[str, Any]) -> Dict[str, Any]:
    from .settings import load_app_settings, save_update_settings
    from .updater import get_manager

    if not any(key in payload for key in UPDATE_SETTING_KEYS):
        raise ValueError("An update setting is required.")
    for key in UPDATE_SETTING_KEYS:
        if key in payload and not isinstance(payload[key], bool):
            raise ValueError(f"'{key}' must be a boolean")

    current = load_app_settings(create=False)
    save_update_settings(
        check=payload.get("check", current.update_check),
        auto_download=payload.get("auto_download", current.update_auto_download),
        auto_install=payload.get("auto_install", current.auto_install_updates),
        channel=current.update_channel,
        skipped_version=current.skipped_update_version,
    )
    try:
        get_manager().settings_changed()
    except Exception:  # pragma: no cover - the save itself succeeded
        pass
    return _updates_payload()


def _sessions_payload() -> Dict[str, Any]:
    from .settings import SESSION_BREAK_HOURS_CHOICES, session_break_hours

    return {
        "break_hours": session_break_hours(),
        "choices": list(SESSION_BREAK_HOURS_CHOICES),
    }


def _set_overlay_enabled(payload: Dict[str, Any]) -> Dict[str, Any]:
    from .overlay_launcher import get_manager

    manager = get_manager()
    if "request" in payload:
        # e.g. {"request": "open-settings"} — the overlay's ⚙ flyout.
        if not manager.send(str(payload["request"])):
            raise ValueError("The overlay is not running.")
        return manager.status()
    if "enabled" not in payload:
        raise ValueError("'enabled' is required")
    enabled = bool(payload.get("enabled"))
    if enabled and not manager.available:
        raise ValueError("The overlay is not included in this build.")
    status = manager.set_enabled(enabled)
    if enabled and not status.get("running"):
        raise ValueError(status.get("error") or "The overlay could not be started.")
    return status


def handle_get(path: str, db_path: Optional[Path] = None) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path != "/api/settings":
        return None
    try:
        from . import paper_prices
        from .deckfinder_api import read_creator_config

        return 200, {
            "tracker": _tracker_info(db_path),
            "deck_ai": _deck_ai_payload(),
            "deck_finder": read_creator_config(),
            # Drives the collection-export section: the macOS admin-prompt
            # warning shows only on darwin, and export is offered only where
            # a memory reader exists.
            "platform": _platform_info(),
            "startup": _startup_payload(),
            "overlay": _overlay_status(),
            "updates": _updates_payload(),
            "buy_on_paper": paper_prices.status(),
            "sessions": _sessions_payload(),
        }
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}


def handle_post(path: str, payload: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
    try:
        if path == "/api/settings/deck-ai":
            return 200, {"deck_ai": _save_deck_ai(payload)}
        if path == "/api/settings/deck-ai/models":
            return 200, _list_deck_ai_models(payload)
        if path == "/api/settings/deck-finder":
            from .deckfinder_api import write_creator_config

            return 200, {"deck_finder": write_creator_config(payload)}
        if path == "/api/settings/startup":
            return 200, {"startup": _save_startup(payload)}
        if path == "/api/settings/sessions":
            from .settings import save_session_break_hours

            save_session_break_hours(payload.get("break_hours"))
            return 200, {"sessions": _sessions_payload()}
        if path == "/api/settings/overlay":
            return 200, {"overlay": _set_overlay_enabled(payload)}
        if path == "/api/settings/updates":
            return 200, {"updates": _save_updates(payload)}
        if path == "/api/settings/buy-on-paper":
            from . import paper_prices

            if not isinstance(payload.get("enabled"), bool):
                raise ValueError("'enabled' must be a boolean")
            return 200, {"buy_on_paper": paper_prices.set_enabled(payload["enabled"])}
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return None
