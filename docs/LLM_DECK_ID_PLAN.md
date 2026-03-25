# LLM Deck Identification at Game End – Plan

## Scope (Phase 1)

**Goal:** At the end of each game, call an LLM with the list of cards the opponent played and get back a short deck archetype/name (e.g. "Izzet Control", "Mono-Red Aggro").

**In scope:**
- Collect opponent cards at game end (already have `self.opponent_cards`)
- Call one LLM with a small, fixed prompt
- Show the result in the existing game summary (e.g. "Opponent deck: Izzet Control")
- Support at least one free option

**Out of scope for now:**
- Online deck search (Untapped.gg, etc.)
- Rule-based archetype DB
- Confidence scores, caching, or multiple providers in the first version

---

## Free LLM Options

### 1. **Ollama (local)** – Best “truly free” option

| | |
|--|--|
| **Cost** | Free, no account, no API key |
| **How** | User runs Ollama on their machine, we call `http://localhost:11434/v1/chat/completions` (OpenAI-compatible) |
| **Models** | Llama 3.2, Mistral, Gemma, etc. – user chooses via `ollama run <model>` |
| **Setup** | User: `ollama pull llama3.2` (or similar). App: just use base URL, no keys |
| **Pros** | No keys, no rate limits, works offline, private |
| **Cons** | User must install Ollama and pull a model; needs ~8GB RAM (+ GPU helps) |

**Use when:** You want zero cost, no signup, and are ok with “run Ollama locally.”

---

### 2. **Groq (cloud, free tier)**

| | |
|--|--|
| **Cost** | Free tier, no credit card to start |
| **How** | REST API with API key from [console.groq.com](https://console.groq.com) |
| **Models** | Llama 3, etc.; very fast inference |
| **Setup** | User gets API key, puts it in config/env |
| **Pros** | Fast, simple API, good for “one call per game” |
| **Cons** | Rate limits, requires signup and key |

**Use when:** You want a free cloud API and don’t mind signup + API key.

---

### 3. **Google Gemini (cloud, free tier)**

| | |
|--|--|
| **Cost** | Free tier, no credit card |
| **How** | REST/ SDK with API key from [Google AI Studio](https://aistudio.google.com) |
| **Models** | e.g. `gemini-1.5-flash` – good quality, 1M-token context |
| **Limits** | ~15 RPM, 1000 requests/day – fine for “1 call per game” |
| **Pros** | Strong model, generous free tier |
| **Cons** | Needs Google account and API key |

**Use when:** You want a strong free cloud model and are ok with Google + API key.

---

## Recommended approach: “Local first, cloud optional”

1. **Default: Ollama**
   - Use `OPENAI_API_BASE=http://localhost:11434/v1` and `OPENAI_API_KEY=dummy` (or skip key if your client allows).
   - If Ollama isn’t running or times out, skip LLM and just show “Opponent deck: (analyze with Ollama for archetype)” or nothing.
   - Docs: “For deck archetype, run `ollama serve` and e.g. `ollama run llama3.2`.”

2. **Optional: Groq or Gemini**
   - Config (env or config file): e.g. `DECK_LLM_PROVIDER=groq` / `gemini` / `ollama`, plus `GROQ_API_KEY` or `GEMINI_API_KEY` when using cloud.
   - If provider is set and key is present, use that instead of Ollama.
   - Keeps Phase 1 simple: one provider at a time.

3. **Fallback**
   - If the chosen provider errors or is unconfigured, print the opponent card list as today and do not block the game summary.

---

## Implementation Plan

### Step 1: Abstraction

- Add a small module, e.g. `src/mtga_tracker/deck_llm.py`, with:
  - `identify_deck(card_names: list[str]) -> str | None`
  - Inside: build prompt, call the selected backend (Ollama vs Groq vs Gemini), parse one-line or one-sentence answer, return it or `None`.

### Step 2: Prompt

- Keep it short and role-focused, e.g.:

  ```text
  You are an expert on Magic: The Gathering Arena deck archetypes. Given a list of card names that one player was seen to play in a single game, respond with exactly one short deck archetype or deck name (e.g. "Izzet Control", "Mono-Red Aggro", "Selesnya Enchantments"). If you cannot tell, respond with "Unknown".

  Cards seen (not necessarily complete deck):
  - Card One
  - Card Two
  ...

  Deck archetype or name (one short phrase only):
  ```

- Parse the last line or first line of the reply and strip to a single phrase; use as “Opponent deck: …” or “Unknown” if empty/unclear.

### Step 3: Wiring at game end

- In `_print_game_summary()` (or a helper it calls):
  - Build `card_names = [e.card_name for e in self.opponent_cards]`.
  - If `card_names` is non-empty, call `identify_deck(card_names)` (optionally behind a config flag like `DECK_LLM_ENABLED=1`).
  - If a non-empty string is returned, add a line to the summary, e.g. `Opponent deck: Izzet Control`.
  - Do this after the existing “Opponent’s Cards” section so the flow stays the same; only add one line when LLM is used.

### Step 4: Configuration

- Use env vars or your existing config:
  - `DECK_LLM_ENABLED` – 1/true to try LLM at all.
  - `DECK_LLM_PROVIDER` – `ollama` | `groq` | `gemini`.
  - `DECK_LLM_OLLAMA_HOST` – default `http://localhost:11434` for Ollama.
  - `GROQ_API_KEY` / `GEMINI_API_KEY` – only when provider is groq/gemini.

- No keys required for Ollama; for Groq/Gemini, “not set” means “skip LLM.”

### Step 5: Dependencies

- **Ollama:** `requests` or `httpx` (you may already use one).
- **Groq:** `groq` SDK or `requests` to `https://api.groq.com/openai/v1/...` (OpenAI-compatible).
- **Gemini:** `google-generativeai` or REST with `requests`.

- Prefer one HTTP client and keep the “backend” behind `identify_deck()` so adding/changing providers is one place.

### Step 6: Resilience

- Timeout for LLM call (e.g. 10–15 s for Ollama, 5–10 s for cloud).
- Catch errors and log; on failure, do not show “Opponent deck” and do not break the summary.
- Optionally retry once on timeout/5xx for cloud only.

---

## Example flow

```text
Game ends → _print_game_summary()
  → opponent_cards = [CardEvent("Lightning Bolt"), CardEvent("Counterspell"), ...]
  → card_names = ["Lightning Bolt", "Counterspell", ...]
  → if DECK_LLM_ENABLED and card_names:
       archetype = identify_deck(card_names)   # e.g. "Izzet Control"
       if archetype:
         print("   Opponent deck: " + archetype)
  → rest of summary (life, your cards, opponent cards list, etc.)
```

---

## Later phases (not in Phase 1)

- **Rule-based fallback:** Small local JSON of “archetype → key cards”; if no LLM or LLM says “Unknown,” try matching.
- **Caching:** Hash of sorted `card_names` → archetype, to avoid repeating the same analysis.
- **Deck search:** Use archetype + key cards to hit Untapped.gg / MTGGoldfish (separate doc/phase).

---

## Proposed output (when DECK_LLM_ENABLED and LLM returns an archetype)

When deck LLM is enabled and the chosen provider (Gemini / OpenAI / Claude) returns a deck name, the game-end summary includes one extra line under "Cards Played":

```text
======================================================================
🏁 GAME ENDED - Best-of-1
======================================================================

⏱️  Game Duration: 5m 32s

======================================================================
🎉🎉🎉 YOU WON THIS GAME! 🎉🎉🎉
   (Opponent reached 0 life)
======================================================================
   Final Life: You 20 - 0 Opponent

📊 Cards Played:
   Your cards: 12
   Opponent cards: 8
   Opponent deck: Izzet Control

   🎯 Your Cards:
      • Lightning Bolt x2
      • Mountain x4
      • ...
   👤 Opponent's Cards:
      • Counterspell x2
      • Steam Vents
      • ...

======================================================================
Ready for next game...
```

The only addition is **`   Opponent deck: Izzet Control`** (or whatever archetype the LLM returns), placed after "Opponent cards: N" and before the card lists. If the LLM is disabled or returns nothing, that line is omitted and the rest of the summary is unchanged.

---

## Summary

| Option   | Cost     | Setup              | Best for                          |
|----------|----------|--------------------|-----------------------------------|
| Ollama   | Free     | Install + pull     | Local, no keys, offline, privacy  |
| Groq     | Free tier| API key            | Fast cloud, one key               |
| Gemini   | Free tier| API key            | Strong model, one key             |

**Recommendation:** Implement Phase 1 with **Ollama as the default** (no keys), and add **Groq or Gemini as an optional override** via `DECK_LLM_PROVIDER` + API key so users can choose “free local” or “free cloud” without touching code.
