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


def handle_get(path: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path != "/api/settings":
        return None
    try:
        from .deckfinder_api import read_creator_config

        return 200, {
            "deck_ai": _deck_ai_payload(),
            "deck_finder": read_creator_config(),
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
