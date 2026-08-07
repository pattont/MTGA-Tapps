"""Deck archetype identification via LLM (Gemini, OpenAI, or Claude).

Configure via config.py (project root) or env vars (env overrides config):
  DECK_LLM_ENABLED         - True/False in config, or "1"/"true"/"yes" in env (default: False)
  DECK_LLM_PROVIDER        - "Gemini" | "OpenAI" | "Claude" (default: "Gemini")
  GEMINI_API_KEY           - API key for Gemini (when provider is Gemini)
  CHATGPT_API_KEY          - API key for OpenAI (when provider is OpenAI)
  CLAUDE_API_KEY           - API key for Anthropic Claude (when provider is Claude)
  DECK_LLM_GEMINI_MODEL    - Gemini model (default: "gemini-2.0-flash")
  DECK_LLM_OPENAI_MODEL   - OpenAI model (default: "gpt-4o-mini"). Cheaper: "gpt-3.5-turbo"
  DECK_LLM_CLAUDE_MODEL   - Claude model (default: "claude-3-5-haiku-20241022")
"""

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, List, Optional

_config: Any = None


def _load_config() -> Any:
    global _config
    if _config is None:
        try:
            import sys
            from pathlib import Path
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


def is_deck_llm_enabled() -> bool:
    cfg = _load_config()
    if cfg is not None and hasattr(cfg, "DECK_LLM_ENABLED"):
        v = getattr(cfg, "DECK_LLM_ENABLED")
        if isinstance(v, bool):
            return v
    v = _env("DECK_LLM_ENABLED", "0").lower()
    return v in ("1", "true", "yes")


def _get_provider() -> str:
    cfg = _load_config()
    if cfg is not None and hasattr(cfg, "DECK_LLM_PROVIDER"):
        p = (getattr(cfg, "DECK_LLM_PROVIDER") or "").strip().lower()
        if p in ("gemini", "openai", "claude"):
            return p
    p = _env("DECK_LLM_PROVIDER", "Gemini").strip().lower()
    if p in ("gemini", "openai", "claude"):
        return p
    return "gemini"


def _get_api_key(provider: str) -> Optional[str]:
    def _val(cfg_key: str, env_keys: tuple) -> Optional[str]:
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
    """Model name for the given provider. Config: DECK_LLM_GEMINI_MODEL / OPENAI_MODEL / CLAUDE_MODEL or env."""
    cfg = _load_config()
    keys = {"gemini": "DECK_LLM_GEMINI_MODEL", "openai": "DECK_LLM_OPENAI_MODEL", "claude": "DECK_LLM_CLAUDE_MODEL"}
    key = keys.get(provider)
    if not key:
        return ""
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
    return f"""You are an expert on Magic: The Gathering Arena deck archetypes. Given a list of card names that one player was seen to play in a single game, respond with exactly one short deck archetype or deck name (e.g. "Izzet Control", "Mono-Red Aggro", "Selesnya Enchantments"). If you cannot tell, respond with "Unknown".

Cards seen (not necessarily the full deck):
{lines}

Reply with only the deck archetype or name, one short phrase, or "Unknown"."""


def _parse_reply(raw: str) -> Optional[str]:
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


def _candidates_prompt(card_names: List[str], limit: int) -> str:
    lines = "\n".join(f"  - {name}" for name in card_names[:80])
    return f"""You are an expert on current Magic: The Gathering Arena deck archetypes. A player was seen playing these cards in one game (not necessarily their full deck):

{lines}

List the 1 to {limit} most likely deck archetypes this player was playing, most likely first. Reply with ONLY a JSON array of short archetype names, e.g. ["Azorius Control", "Jeskai Convoke"]. If you cannot tell, reply []."""


def _parse_candidates(raw: Optional[str], limit: int) -> List[str]:
    """Extract up to `limit` archetype names from a (hopefully JSON) reply."""
    if not raw or not isinstance(raw, str):
        return []
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    names: List[str] = []
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                names = [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            names = []
    if not names:
        single = _parse_reply(raw)
        names = [single] if single else []
    cleaned: List[str] = []
    for name in names:
        if name.lower() in ("unknown", "n/a", "?"):
            continue
        if len(name) > 60:
            name = name[:60].rsplit(" ", 1)[0] or name[:60]
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned[:limit]


def _complete_raw(prompt: str, max_tokens: int = 128) -> Optional[str]:
    """Send a prompt to the configured provider; return the raw reply text."""
    if not is_deck_llm_enabled():
        return None
    provider = _get_provider()
    api_key = _get_api_key(provider)
    if not api_key:
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
            body = {
                "model": _get_openai_model(),
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": max_tokens,
            }
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
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
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError):
        return None
    return None


def identify_deck_candidates(card_names: List[str], limit: int = 3) -> List[str]:
    """Return up to `limit` likely archetypes for the seen cards, best first.

    One API call. Empty list when disabled, keyless, or the reply is unusable.
    """
    cards = [str(c).strip() for c in card_names if c and str(c).strip()]
    if not cards:
        return []
    raw = _complete_raw(_candidates_prompt(cards, limit))
    return _parse_candidates(raw, limit)


def _call_gemini(prompt: str, api_key: str, timeout: int = 15) -> Optional[str]:
    model = _get_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 64, "temperature": 0.2},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_reply(text)
    except (KeyError, IndexError):
        return None


def test_call(card_names: List[str]) -> tuple[Optional[str], Optional[str]]:
    """Returns (archetype, error_message). For test_deck_llm.py to show API errors."""
    if not is_deck_llm_enabled():
        return (None, "DECK_LLM_ENABLED is False")
    cards = [str(c).strip() for c in card_names if c and str(c).strip()]
    if not cards:
        return (None, "No cards")
    provider = _get_provider()
    api_key = _get_api_key(provider)
    if not api_key:
        return (None, "No API key in config or env")
    prompt = _build_prompt(cards)
    if provider == "gemini":
        model = _get_gemini_model()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 64, "temperature": 0.2}}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return (_parse_reply(text), None)
        except urllib.error.HTTPError as e:
            return (None, f"HTTP {e.code}: {e.read().decode()[:300]}")
        except urllib.error.URLError as e:
            return (None, f"Network: {e.reason}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return (None, str(e))
    if provider == "openai":
        model = _get_openai_model()
        url = "https://api.openai.com/v1/chat/completions"
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_completion_tokens": 64}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            text = data["choices"][0]["message"]["content"]
            return (_parse_reply(text), None)
        except urllib.error.HTTPError as e:
            return (None, f"HTTP {e.code}: {e.read().decode()[:500]}")
        except urllib.error.URLError as e:
            return (None, f"Network: {e.reason}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return (None, str(e))
    if provider == "claude":
        model = _get_claude_model()
        url = "https://api.anthropic.com/v1/messages"
        body = {"model": model, "max_tokens": 64, "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", api_key)
        req.add_header("anthropic-version", "2023-06-01")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return (_parse_reply(block.get("text", "")), None)
            return (None, "No text in response")
        except urllib.error.HTTPError as e:
            return (None, f"HTTP {e.code}: {e.read().decode()[:500]}")
        except urllib.error.URLError as e:
            return (None, f"Network: {e.reason}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return (None, str(e))
    return (identify_deck(cards), None)


def _call_openai(prompt: str, api_key: str, timeout: int = 15) -> Optional[str]:
    model = _get_openai_model()
    url = "https://api.openai.com/v1/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": 64,
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None
    try:
        text = data["choices"][0]["message"]["content"]
        return _parse_reply(text)
    except (KeyError, IndexError):
        return None


def _call_claude(prompt: str, api_key: str, timeout: int = 15) -> Optional[str]:
    model = _get_claude_model()
    url = "https://api.anthropic.com/v1/messages"
    body = {
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None
    try:
        for block in data.get("content", []):
            if block.get("type") == "text":
                return _parse_reply(block.get("text", ""))
        return None
    except (KeyError, IndexError):
        return None


def diagnose() -> dict:
    """Return config/API status for debugging. Use from test_deck_llm.py."""
    cfg = _load_config()
    enabled = is_deck_llm_enabled()
    provider = _get_provider()
    api_key = _get_api_key(provider)
    return {
        "config_loaded": cfg is not None,
        "enabled": enabled,
        "provider": provider,
        "has_api_key": bool(api_key and api_key.strip()),
    }


def identify_deck(card_names: List[str]) -> Optional[str]:
    """Identify deck archetype from a list of card names using the configured LLM.

    Reads DECK_LLM_ENABLED, DECK_LLM_PROVIDER, and the appropriate API key from
    config.py (if present) or env vars (env overrides config).
    Returns a short string (e.g. "Izzet Control") or None if disabled, no key, or error.
    """
    if not is_deck_llm_enabled():
        return None
    cards = [str(c).strip() for c in card_names if c and str(c).strip()]
    if not cards:
        return None
    provider = _get_provider()
    api_key = _get_api_key(provider)
    if not api_key:
        return None
    prompt = _build_prompt(cards)
    if provider == "gemini":
        return _call_gemini(prompt, api_key)
    if provider == "openai":
        return _call_openai(prompt, api_key)
    if provider == "claude":
        return _call_claude(prompt, api_key)
    return None
