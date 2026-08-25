"""Dashboard settings endpoints: Deck AI + Deck Finder creators.

The dashboard only serves localhost, so the same values the desktop
Settings dialog edits (settings.json's "deck_ai" section and
deckfinder_config.json) are readable/writable from the web Settings page.

Endpoints (all under /api/settings):
- GET  /api/settings           -> {deck_ai, deck_finder}
- POST /api/settings/deck-ai   -> save AI provider/keys/models
- POST /api/settings/deck-finder -> save the creator lists
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: (internal name, display label, settings key for the key, settings key for
#: the model, default model) — mirrors settings_dialog._PROVIDERS.
AI_PROVIDERS = (
    ("openai", "OpenAI", "CHATGPT_API_KEY", "DECK_LLM_OPENAI_MODEL", "gpt-4o-mini"),
    ("claude", "Anthropic (Claude)", "CLAUDE_API_KEY", "DECK_LLM_CLAUDE_MODEL", "claude-3-5-haiku-20241022"),
    ("gemini", "Gemini", "GEMINI_API_KEY", "DECK_LLM_GEMINI_MODEL", "gemini-2.0-flash"),
)


def _deck_ai_payload() -> Dict[str, Any]:
    from . import deck_llm

    stored = deck_llm.load_settings()
    providers = []
    for internal, label, key_name, model_name, default_model in AI_PROVIDERS:
        providers.append(
            {
                "key": internal,
                "label": label,
                "api_key": str(stored.get(key_name) or deck_llm._get_api_key(internal) or ""),
                "model": str(stored.get(model_name) or ""),
                "default_model": default_model,
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
    if provider not in {p[0] for p in AI_PROVIDERS}:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    keys = payload.get("keys") if isinstance(payload.get("keys"), dict) else {}
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}

    values: Dict[str, Any] = {
        "DECK_LLM_ENABLED": bool(payload.get("enabled")),
        "DECK_LLM_PROVIDER": provider,
    }
    for internal, _label, key_name, model_name, default_model in AI_PROVIDERS:
        key_value = str(keys.get(internal) or "").strip()
        model_value = str(models.get(internal) or "").strip()
        if internal == provider:
            # The selected provider's fields are authoritative (an empty key
            # clears it); an empty model falls back to the default.
            values[key_name] = key_value
            values[model_name] = model_value or default_model
        else:
            # Keep edits to non-selected providers without clearing values
            # the page never loaded.
            if key_value:
                values[key_name] = key_value
            if model_value:
                values[model_name] = model_value
    deck_llm.save_settings(values)
    return _deck_ai_payload()


def _tilde(value: Any) -> Optional[str]:
    """Shorten an absolute path with the user's home directory to ~/..."""
    if not value:
        return None
    text = str(value)
    home = str(Path.home())
    if home and text.startswith(home):
        return "~" + text[len(home):]
    return text


def _deck_ai_summary() -> str:
    from . import deck_llm

    try:
        status = deck_llm.diagnose()
    except Exception:
        return "unknown"
    if not status.get("enabled"):
        return "disabled"
    provider_label = {
        "openai": "OpenAI",
        "claude": "Anthropic (Claude)",
        "gemini": "Gemini",
    }.get(str(status.get("provider") or ""), str(status.get("provider") or "?"))
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

    system = "macos" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "other"
    return {
        "system": system,
        # Collection export reads process memory, which only the macOS/Windows
        # readers implement.
        "collection_export": system in {"macos", "windows"},
    }


def handle_get(path: str, db_path: Optional[Path] = None) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path != "/api/settings":
        return None
    try:
        from .deckfinder_api import read_creator_config

        return 200, {
            "tracker": _tracker_info(db_path),
            "deck_ai": _deck_ai_payload(),
            "deck_finder": read_creator_config(),
            # Drives the collection-export section: the macOS admin-prompt
            # warning shows only on darwin, and export is offered only where
            # a memory reader exists.
            "platform": _platform_info(),
        }
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}


def handle_post(path: str, payload: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
    try:
        if path == "/api/settings/deck-ai":
            return 200, {"deck_ai": _save_deck_ai(payload)}
        if path == "/api/settings/deck-finder":
            from .deckfinder_api import write_creator_config

            return 200, {"deck_finder": write_creator_config(payload)}
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive surface
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return None
