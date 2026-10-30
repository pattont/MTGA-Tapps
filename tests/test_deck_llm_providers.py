"""Deck AI providers: labels, Grok, and the Settings page's model lists."""

import io
import json
import urllib.error

import pytest

from mtga_tracker import deck_llm, settings_api


@pytest.fixture
def deck_ai_settings(monkeypatch, tmp_path):
    """Point deck_llm at a temporary settings.json and clear key env vars."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(deck_llm, "settings_path", lambda: settings_file)
    monkeypatch.setattr(deck_llm, "_load_config", lambda: None)
    for name in (
        "DECK_LLM_PROVIDER",
        "GROK_API_KEY",
        "XAI_API_KEY",
        "CHATGPT_API_KEY",
        "OPENAI_API_KEY",
        "DECK_LLM_GROK_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    deck_llm._settings_cache = None
    deck_llm._settings_mtime = None

    def write(values):
        settings_file.write_text(json.dumps({"deck_ai": values}), encoding="utf-8")
        deck_llm._settings_cache = None
        deck_llm._settings_mtime = None

    yield write
    deck_llm._settings_cache = None
    deck_llm._settings_mtime = None


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture_urlopen(monkeypatch, replies):
    """Replace urlopen; `replies` maps a URL prefix to the JSON reply."""
    calls = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        calls.append({"url": req.full_url, "headers": dict(req.header_items()), "body": body})
        for prefix, reply in replies.items():
            if req.full_url.startswith(prefix):
                if isinstance(reply, Exception):
                    raise reply
                return _Response(json.dumps(reply).encode())
        raise AssertionError(f"unexpected URL {req.full_url}")

    monkeypatch.setattr(deck_llm.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_provider_labels_and_order():
    assert [(p.key, p.label) for p in deck_llm.PROVIDERS] == [
        ("openai", "OpenAI (ChatGPT)"),
        ("claude", "Anthropic (Claude)"),
        ("gemini", "Google (Gemini)"),
        ("grok", "xAI (Grok)"),
    ]
    assert all(p.models_url.startswith("https://") for p in deck_llm.PROVIDERS)
    assert deck_llm.provider_label("grok") == "xAI (Grok)"


def test_grok_provider_key_and_default_model(deck_ai_settings, monkeypatch):
    deck_ai_settings({"DECK_LLM_PROVIDER": "xai"})
    assert deck_llm._get_provider() == "grok"
    monkeypatch.setenv("XAI_API_KEY", "xai-env")
    assert deck_llm._get_api_key("grok") == "xai-env"
    assert deck_llm._get_model("grok") == "grok-4.20-0309-non-reasoning"
    deck_ai_settings({"DECK_LLM_PROVIDER": "Grok", "GROK_API_KEY": "xai-saved"})
    assert deck_llm._get_provider() == "grok"
    assert deck_llm._get_api_key("grok") == "xai-saved"


def test_grok_completion_uses_xai_and_low_effort_for_reasoning_models(
    deck_ai_settings, monkeypatch
):
    reply = {"choices": [{"message": {"content": "Izzet Control"}, "finish_reason": "stop"}]}
    calls = _capture_urlopen(monkeypatch, {"https://api.x.ai/v1/chat/completions": reply})

    deck_ai_settings(
        {
            "DECK_LLM_ENABLED": True,
            "DECK_LLM_PROVIDER": "grok",
            "GROK_API_KEY": "xai-key",
            "DECK_LLM_GROK_MODEL": "grok-4.7",
        }
    )
    assert deck_llm.identify_deck(["Opt", "Lightning Bolt", "Counterspell"]) == "Izzet Control"
    assert calls[-1]["headers"]["Authorization"] == "Bearer xai-key"
    assert calls[-1]["body"]["model"] == "grok-4.7"
    assert calls[-1]["body"]["reasoning_effort"] == "low"

    deck_ai_settings(
        {"DECK_LLM_ENABLED": True, "DECK_LLM_PROVIDER": "grok", "GROK_API_KEY": "xai-key"}
    )
    deck_llm.identify_deck(["Opt", "Lightning Bolt", "Counterspell"])
    assert calls[-1]["body"]["model"] == "grok-4.20-0309-non-reasoning"
    assert "reasoning_effort" not in calls[-1]["body"]
    assert len(calls) == 2  # one request per identification


def test_list_models_openai_keeps_chat_models_newest_first(monkeypatch):
    calls = _capture_urlopen(
        monkeypatch,
        {
            "https://api.openai.com/v1/models": {
                "data": [
                    {"id": "gpt-4o-mini", "created": 10},
                    {"id": "gpt-5-mini", "created": 30},
                    {"id": "text-embedding-3-small", "created": 40},
                    {"id": "gpt-4o-realtime-preview", "created": 41},
                    {"id": "gpt-image-1", "created": 42},
                    {"id": "o3-pro", "created": 43},
                    {"id": "dall-e-3", "created": 44},
                    {"id": "o4-mini", "created": 20},
                ]
            }
        },
    )
    models = deck_llm.list_models("openai", "sk-typed")
    assert [m["id"] for m in models] == ["gpt-5-mini", "o4-mini", "gpt-4o-mini"]
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-typed"


def test_list_models_claude_gemini_and_grok(monkeypatch):
    _capture_urlopen(
        monkeypatch,
        {
            "https://api.anthropic.com/v1/models": {
                "data": [{"id": "claude-haiku-9", "display_name": "Claude Haiku 9"}]
            },
            "https://generativelanguage.googleapis.com/v1beta/models": {
                "models": [
                    {
                        "name": "models/gemini-3-flash",
                        "displayName": "Gemini 3 Flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/gemini-embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                    {
                        "name": "models/gemini-3-flash-image",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                ]
            },
            "https://api.x.ai/v1/models": {
                "data": [
                    {"id": "grok-4.7", "created": 3},
                    {"id": "grok-imagine-image-2.0", "created": 4},
                    {"id": "grok-4.20-0309-non-reasoning", "created": 1},
                ]
            },
        },
    )
    assert deck_llm.list_models("claude", "k") == [
        {"id": "claude-haiku-9", "label": "Claude Haiku 9"}
    ]
    assert deck_llm.list_models("gemini", "k") == [
        {"id": "gemini-3-flash", "label": "Gemini 3 Flash"}
    ]
    assert [m["id"] for m in deck_llm.list_models("grok", "k")] == [
        "grok-4.7",
        "grok-4.20-0309-non-reasoning",
    ]


def test_list_models_errors_are_readable(deck_ai_settings, monkeypatch):
    deck_ai_settings({})
    with pytest.raises(deck_llm.ModelListError, match="Enter an API key"):
        deck_llm.list_models("grok")
    rejected = urllib.error.HTTPError("https://api.x.ai/v1/models", 401, "no", {}, None)
    _capture_urlopen(monkeypatch, {"https://api.x.ai/": rejected})
    with pytest.raises(deck_llm.ModelListError, match=r"xAI \(Grok\) did not accept"):
        deck_llm.list_models("grok", "bad")


def test_settings_api_lists_models_and_reports_failures(deck_ai_settings, monkeypatch):
    deck_ai_settings({"GROK_API_KEY": "xai-saved"})
    calls = _capture_urlopen(
        monkeypatch, {"https://api.x.ai/v1/models": {"data": [{"id": "grok-4.7"}]}}
    )
    status, body = settings_api.handle_post("/api/settings/deck-ai/models", {"provider": "grok"})
    assert status == 200
    assert body["models"] == [{"id": "grok-4.7", "label": "grok-4.7"}]
    assert calls[0]["headers"]["Authorization"] == "Bearer xai-saved"  # the saved key

    status, body = settings_api.handle_post(
        "/api/settings/deck-ai/models", {"provider": "nope", "api_key": "x"}
    )
    assert status == 400 and "Unknown AI provider" in body["error"]


def test_settings_payload_includes_grok_and_model_pages(deck_ai_settings):
    deck_ai_settings({"DECK_LLM_PROVIDER": "grok", "GROK_API_KEY": "xai-saved"})
    payload = settings_api._deck_ai_payload()
    assert payload["provider"] == "grok"
    grok = next(p for p in payload["providers"] if p["key"] == "grok")
    assert grok["label"] == "xAI (Grok)"
    assert grok["api_key"] == "xai-saved"
    assert grok["models_url"] == "https://docs.x.ai/developers/models"

    settings_api._save_deck_ai(
        {
            "enabled": True,
            "provider": "grok",
            "keys": {"grok": "xai-new"},
            "models": {"grok": "grok-4.7"},
        }
    )
    stored = deck_llm.load_settings()
    assert stored["GROK_API_KEY"] == "xai-new"
    assert stored["DECK_LLM_GROK_MODEL"] == "grok-4.7"


def test_defaults_are_current_and_old_stored_defaults_follow_them(deck_ai_settings):
    defaults = {p.key: p.default_model for p in deck_llm.PROVIDERS}
    assert defaults == {
        "openai": "gpt-6-luna",
        "claude": "claude-haiku-5-5",
        "gemini": "gemini-3.5-flash-lite",
        "grok": "grok-4.20-0309-non-reasoning",
    }
    # Earlier versions saved the default explicitly; those copies now mean
    # "use the default", while a real choice is kept.
    deck_ai_settings(
        {
            "DECK_LLM_GEMINI_MODEL": "gemini-2.0-flash",
            "DECK_LLM_CLAUDE_MODEL": "claude-3-5-haiku-20241022",
            "DECK_LLM_OPENAI_MODEL": "gpt-4o-mini",
            "DECK_LLM_GROK_MODEL": "grok-4.7",
        }
    )
    assert deck_llm._get_model("gemini") == "gemini-3.5-flash-lite"
    assert deck_llm._get_model("claude") == "claude-haiku-5-5"
    assert deck_llm._get_model("openai") == "gpt-6-luna"
    assert deck_llm._get_model("grok") == "grok-4.7"
    payload = {p["key"]: p["model"] for p in settings_api._deck_ai_payload()["providers"]}
    assert payload == {"openai": "", "claude": "", "gemini": "", "grok": "grok-4.7"}


def test_saving_a_blank_model_stores_blank(deck_ai_settings):
    deck_ai_settings({})
    settings_api._save_deck_ai(
        {"enabled": True, "provider": "gemini", "keys": {"gemini": "g"}, "models": {}}
    )
    assert deck_llm.load_settings()["DECK_LLM_GEMINI_MODEL"] == ""
    assert deck_llm._get_model("gemini") == "gemini-3.5-flash-lite"


@pytest.mark.parametrize(
    "model, effort",
    [("gpt-6-luna", "low"), ("gpt-5-mini", "low"), ("o4-mini", "low"), ("gpt-4.1-mini", None)],
)
def test_openai_reasoning_models_get_low_effort(model, effort):
    assert (("low" if deck_llm._wants_low_effort("openai", model) else None)) == effort
