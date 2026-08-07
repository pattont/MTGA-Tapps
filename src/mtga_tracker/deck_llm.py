"""Deck archetype identification via LLM (Gemini, OpenAI, or Claude).

Configuration is resolved in this order (first hit wins per value):
  1. settings.json in the tracker data dir (written by the Settings dialog)
  2. config.py at the project root (source checkouts)
  3. Environment variables

Recognized values (same names in settings.json, config.py, and env):
  DECK_LLM_ENABLED         - True/False (default: False)
  DECK_LLM_PROVIDER        - "OpenAI" | "Claude" | "Gemini" (default: "Gemini")
  CHATGPT_API_KEY          - API key for OpenAI ("OPENAI_API_KEY" also honored in env)
  CLAUDE_API_KEY           - API key for Anthropic Claude
  GEMINI_API_KEY           - API key for Gemini
  DECK_LLM_OPENAI_MODEL    - OpenAI model (default: "gpt-4o-mini")
  DECK_LLM_CLAUDE_MODEL    - Claude model (default: "claude-3-5-haiku-20241022")
  DECK_LLM_GEMINI_MODEL    - Gemini model (default: "gemini-2.0-flash")

The archetype call is intentionally cheap: one small request per game, made
after the game completes, with reasoning-class models asked for low effort.
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

_config: Any = None


def _load_config() -> Any:
    global _config
    if _config is None:
        try:
            import sys

            # Ensure project root is on path so config.py is found when run from any CWD
            _here = Path(__file__).resolve().parent
            _root = _here.parent.parent
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            import config as _config_mod  # type: ignore[import-not-found]
            _config = _config_mod
        except ImportError:
            _config = False  # no config module
    return _config if _config else None


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or "").strip() or default


# ---------------------------------------------------------------------------
# Deck AI section of settings.json (written by the menu bar Settings dialog).
# The file is shared with the desktop app's other settings (window size,
# dashboard port) — this module only touches the "deck_ai" key.
# ---------------------------------------------------------------------------

_settings_cache: Optional[Dict[str, Any]] = None
_settings_mtime: Optional[float] = None


def settings_path() -> Path:
    from .settings import SETTINGS_PATH

    return SETTINGS_PATH


def load_settings() -> Dict[str, Any]:
    """Read the "deck_ai" section of settings.json, cached by mtime so a
    running tracker picks up Settings-dialog edits without a restart."""
    global _settings_cache, _settings_mtime
    path = settings_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _settings_cache, _settings_mtime = {}, None
        return {}
    if _settings_cache is not None and _settings_mtime == mtime:
        return _settings_cache
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        section = data.get("deck_ai") if isinstance(data, dict) else None
        _settings_cache = section if isinstance(section, dict) else {}
    except (OSError, json.JSONDecodeError):
        _settings_cache = {}
    _settings_mtime = mtime
    return _settings_cache


def save_settings(values: Dict[str, Any]) -> Path:
    """Merge `values` into settings.json's "deck_ai" section, leaving every
    other section (window size, dashboard port, ...) untouched."""
    global _settings_cache, _settings_mtime
    path = settings_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            document = {}
    except (OSError, json.JSONDecodeError):
        document = {}
    section = document.get("deck_ai")
    if not isinstance(section, dict):
        section = {}
    section.update(values)
    document["deck_ai"] = section
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _settings_cache = None
    _settings_mtime = None
    return path


def _setting(key: str) -> Any:
    """Value from settings.json, or None if absent/blank."""
    value = load_settings().get(key)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def is_deck_llm_enabled() -> bool:
    v = _setting("DECK_LLM_ENABLED")
    if isinstance(v, bool):
        return v
    cfg = _load_config()
    if cfg is not None and hasattr(cfg, "DECK_LLM_ENABLED"):
        cv = getattr(cfg, "DECK_LLM_ENABLED")
        if isinstance(cv, bool):
            return cv
    return _env("DECK_LLM_ENABLED", "0").lower() in ("1", "true", "yes")


def _get_provider() -> str:
    for raw in (
        _setting("DECK_LLM_PROVIDER"),
        getattr(_load_config(), "DECK_LLM_PROVIDER", None) if _load_config() else None,
        _env("DECK_LLM_PROVIDER"),
    ):
        p = (raw or "").strip().lower() if isinstance(raw, str) else ""
        if p in ("gemini", "openai", "claude"):
            return p
    return "gemini"


def _get_api_key(provider: str) -> Optional[str]:
    def _val(cfg_key: str, env_keys: tuple) -> Optional[str]:
        s = _setting(cfg_key)
        if isinstance(s, str) and s:
            return s
        cfg = _load_config()
        if cfg is not None and hasattr(cfg, cfg_key):
            k = getattr(cfg, cfg_key)
            if k and isinstance(k, str) and k.strip():
                return k.strip()
        for ek in env_keys:
            v = _env(ek)
            if v:
                return v
        return None

    if provider == "gemini":
        return _val("GEMINI_API_KEY", ("GEMINI_API_KEY",))
    if provider == "openai":
        return _val("CHATGPT_API_KEY", ("CHATGPT_API_KEY", "OPENAI_API_KEY"))
    if provider == "claude":
        return _val("CLAUDE_API_KEY", ("CLAUDE_API_KEY",))
    return None


def _get_model(provider: str) -> str:
    """Model name for the given provider, from settings.json / config.py / env."""
    keys = {"gemini": "DECK_LLM_GEMINI_MODEL", "openai": "DECK_LLM_OPENAI_MODEL", "claude": "DECK_LLM_CLAUDE_MODEL"}
    key = keys.get(provider)
    if not key:
        return ""
    s = _setting(key)
    if isinstance(s, str) and s:
        return s
    cfg = _load_config()
    if cfg is not None and hasattr(cfg, key):
        m = getattr(cfg, key, None)
        if m and isinstance(m, str) and m.strip():
            return m.strip()
    v = _env(key)
    if provider == "openai":
        v = v or _env("OPENAI_MODEL")
    if v:
        return v
    defaults = {"gemini": "gemini-2.0-flash", "openai": "gpt-4o-mini", "claude": "claude-3-5-haiku-20241022"}
    return defaults.get(provider, "")


def _get_openai_model() -> str:
    return _get_model("openai")


def _get_gemini_model() -> str:
    return _get_model("gemini")


def _get_claude_model() -> str:
    return _get_model("claude")


def _build_prompt(card_names: List[str]) -> str:
    lines = "\n".join(f"  - {name}" for name in card_names[:80])  # cap for token safety
    return f"""You are an expert on Magic: The Gathering Arena deck archetypes. A player was seen playing these cards in a single game (not necessarily their full deck):

{lines}

Respond with exactly one short deck archetype name (e.g. "Izzet Control", "Mono-Red Aggro", "Selesnya Enchantments"). Rules:
- Name the deck by its DOMINANT colors and strategy. If a color appears in only a card or two, it is a splash — leave it out of the name (a mostly-Jeskai deck with one black card is still "Jeskai ...").
- If you do not recognize the specific cards (they may be from a newer set than you know), infer the colors and strategy from the card names and answer with a descriptive name like "Azorius Artifacts" or "Golgari Midrange" — never refuse.

Reply with ONLY the archetype name, one short phrase."""


def _parse_reply(raw: Optional[str]) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw or raw.lower() in ("unknown", "n/a", "?"):
        return None
    # Take first line and clean
    first = raw.split("\n")[0].strip()
    first = re.sub(r"^['\"]|['\"]$", "", first)
    if len(first) > 120:
        first = first[:120].rsplit(" ", 1)[0] or first[:120]
    return first if first else None


#: Last _complete_raw failure, for diagnostics (scripts/test_deck_ai.py).
_last_error: Optional[str] = None


def last_error() -> Optional[str]:
    return _last_error


#: OpenAI models that spend completion tokens on hidden reasoning.
_REASONING_MODEL_RE = re.compile(r"^(o\d|gpt-5)", re.IGNORECASE)


def _openai_complete(prompt: str, api_key: str, max_tokens: int) -> Optional[str]:
    """OpenAI chat completion, tolerant of reasoning-family models.

    Reasoning models (gpt-5 family, o-series) burn completion tokens on
    hidden reasoning before emitting any visible text — and those hidden
    tokens are billed. Two mitigations, both cost-savers: request low
    reasoning effort when the model looks reasoning-class, and retry once
    with a modestly larger budget only if the reply still comes back empty
    with finish_reason=length.
    """
    global _last_error
    model = _get_openai_model()

    def _call(tokens: int, effort: Optional[str]) -> dict:
        body: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": tokens,
        }
        if effort:
            body["reasoning_effort"] = effort
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())["choices"][0]

    # "low" is accepted across reasoning families (gpt-5, o-series); the
    # cheapest label varies by model, so don't chase it. Non-reasoning
    # models (gpt-4o-mini etc.) get no effort parameter at all.
    effort: Optional[str] = "low" if _REASONING_MODEL_RE.match(model) else None
    try:
        choice = _call(max_tokens, effort)
    except urllib.error.HTTPError as exc:
        if effort and exc.code == 400:
            # Model rejected reasoning_effort — drop it for every call.
            effort = None
            choice = _call(max_tokens, effort)
        else:
            raise
    text = (choice.get("message", {}).get("content") or "").strip()
    if not text and choice.get("finish_reason") == "length":
        # Hidden reasoning consumed the whole budget; one modest retry.
        choice = _call(2048, effort)
        text = (choice.get("message", {}).get("content") or "").strip()
    if not text:
        _last_error = (
            f"empty reply (finish_reason={choice.get('finish_reason')}) — "
            "reasoning model consumed the token budget even after retry"
        )
        return None
    return text


def _complete_raw(prompt: str, max_tokens: int = 1024) -> Optional[str]:
    """Send a prompt to the configured provider; return the raw reply text.

    max_tokens is generous because reasoning-class models (OpenAI gpt-5
    family, o-series) burn completion tokens on hidden reasoning before any
    visible text — a small cap returns an EMPTY reply, not a shorter one.
    """
    global _last_error
    _last_error = None
    if not is_deck_llm_enabled():
        _last_error = "deck LLM disabled"
        return None
    provider = _get_provider()
    api_key = _get_api_key(provider)
    if not api_key:
        _last_error = "no API key"
        return None
    try:
        if provider == "gemini":
            model = _get_gemini_model()
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
            }
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            return data["candidates"][0]["content"]["parts"][0]["text"]
        if provider == "openai":
            return _openai_complete(prompt, api_key, max_tokens)
        if provider == "claude":
            body = {
                "model": _get_claude_model(),
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(body).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("x-api-key", api_key)
            req.add_header("anthropic-version", "2023-06-01")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block.get("text", "")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode()[:300]
        except Exception:
            detail = ""
        _last_error = f"HTTP {exc.code}: {detail}"
        return None
    except urllib.error.URLError as exc:
        _last_error = f"network: {exc.reason}"
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        _last_error = f"unexpected response shape: {exc}"
        return None
    _last_error = "no text in response"
    return None


def diagnose() -> dict:
    """Return config/API status for debugging (scripts/test_deck_ai.py)."""
    cfg = _load_config()
    enabled = is_deck_llm_enabled()
    provider = _get_provider()
    api_key = _get_api_key(provider)
    return {
        "config_loaded": cfg is not None,
        "settings_file": settings_path().is_file(),
        "enabled": enabled,
        "provider": provider,
        "model": _get_model(provider),
        "has_api_key": bool(api_key and api_key.strip()),
    }


def identify_deck(card_names: List[str]) -> Optional[str]:
    """Identify the opponent's deck archetype from observed card names.

    One cheap API call. Returns a short string (e.g. "Izzet Control") or
    None when disabled, keyless, or the reply is unusable. Callers should
    invoke this off the tracking thread — it can take seconds.
    """
    cards = [str(c).strip() for c in card_names if c and str(c).strip()]
    if not cards:
        return None
    return _parse_reply(_complete_raw(_build_prompt(cards)))
