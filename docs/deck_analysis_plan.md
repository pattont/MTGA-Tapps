# Opponent Deck Identification & Search - Implementation Plan

## Overview
At the end of each game, analyze all cards played by the opponent to identify their deck archetype, then search online deck databases (like untapped.gg) to find the exact deck or similar decks.

---

## 1. Data Collection (Already in Place ✅)
- Track opponent cards played (`self.opponent_cards`)
- Store card names, quantities, and game context
- Capture at game end in `_print_game_summary()`

---

## 2. Deck Archetype Identification

### Option A: LLM-Based Identification
- **Approach**: Use OpenAI/Anthropic/Claude API
- **Prompt**: "Given these cards played by an opponent in MTG Arena, identify the deck archetype/name. Cards: [list]. Format: 'Deck Name' or 'Archetype Name'"
- **Pros**: 
  - Handles partial information well
  - Understands context and meta game
  - Can identify new/unknown archetypes
- **Cons**: 
  - API costs per game
  - Requires API key
  - Latency (API call time)

### Option B: Rule-Based Matching
- **Approach**: Build local database of common archetypes and their key cards
- **Method**: Match played cards against archetype signatures
- **Scoring**: Match percentage based on key cards found
- **Pros**: 
  - Fast and free
  - No API dependency
  - Works offline
- **Cons**: 
  - Requires maintenance (update archetype DB)
  - Less flexible for new archetypes
  - May miss nuanced deck names

### Option C: Hybrid Approach (Recommended)
- **Strategy**: 
  1. Try rule-based first (fast, free)
  2. Fall back to LLM if confidence is low or no match found
- **Best of both worlds**: Speed + accuracy

---

## 3. Deck Search Integration

### Target Sites:
- **Untapped.gg**: Popular MTGA deck tracker, has API/deck search
- **MTGGoldfish**: Deck database with search functionality
- **AetherHub**: MTGA deck sharing platform
- **Scryfall**: Card search (less useful for full decks)

### Search Strategies:
- **Direct API** (if available): Query by deck name/archetype
- **Web Scraping**: Search pages, parse results (respect robots.txt, rate limits)
- **Deck Code**: If sites support deck codes, generate from cards and search

---

## 4. Implementation Flow

```
Game Ends
  ↓
Extract opponent cards played
  ↓
Identify Deck Archetype:
  ├─ Try rule-based matching (local DB)
  │  └─ If match found (>70% confidence) → Use it
  └─ Else → Call LLM API
     └─ Get archetype name
  ↓
Search Online:
  ├─ Format search query (deck name + key cards)
  ├─ Query Untapped.gg API/search
  ├─ Query MTGGoldfish search
  └─ Return top 3-5 similar decks
  ↓
Display Results:
  ├─ "Opponent Deck: [Archetype Name]"
  ├─ "Similar Decks Found:"
  │  ├─ [Deck 1] - [Match %] - [Link]
  │  ├─ [Deck 2] - [Match %] - [Link]
  │  └─ ...
  └─ "Key Cards Identified: [list]"
```

---

## 5. Technical Components Needed

### New Files/Modules:
- `deck_identifier.py`: Archetype identification logic
- `deck_searcher.py`: Online deck search integration
- `archetype_db.json`: Local archetype database (key cards per archetype)
- `config.py`: API keys (LLM, optional Untapped.gg API key)

### Dependencies to Add:
- `requests` (if not already): HTTP requests for APIs
- `openai` or `anthropic`: LLM API client (if using LLM)
- `beautifulsoup4` or `lxml`: Web scraping (if needed)

### Configuration:
- Optional LLM API key in `config.py`
- Enable/disable LLM vs rule-based
- Search site preferences

---

## 6. Data Structure

```python
# Opponent deck analysis result
{
    "archetype_name": "Izzet Control",
    "confidence": 0.85,
    "identification_method": "llm" | "rule_based",
    "cards_played": ["Lightning Bolt", "Counterspell", ...],
    "key_cards_matched": ["Lightning Bolt", "Counterspell"],
    "similar_decks": [
        {
            "name": "Izzet Control - Standard",
            "source": "untapped.gg",
            "match_percentage": 92,
            "url": "https://...",
            "key_differences": ["Missing: Snapcaster Mage"]
        },
        ...
    ]
}
```

---

## 7. Considerations

### Privacy/Ethics:
- Only use cards actually played (public information)
- No hand/library data
- Clear user messaging about what data is used

### Performance:
- Cache LLM results for common archetypes
- Rate limit API calls
- Async/background processing to avoid blocking

### Accuracy:
- **Partial Information**: Only cards seen during game
- **Sideboard vs Maindeck**: Ambiguity in identification
- **Format Detection**: Standard, Historic, etc.

### Cost Management:
- LLM API costs per game
- Consider caching, batching, or user opt-in
- Free tier limits

---

## 8. User Experience

### Output Format:
```
======================================================================
📊 OPPONENT DECK ANALYSIS
======================================================================
Deck Archetype: Izzet Control
Confidence: 85%
Method: LLM Analysis

Cards Observed (12):
  - Lightning Bolt x2
  - Counterspell x3
  - Snapcaster Mage x1
  ...

Similar Decks Found:
  1. Izzet Control - Standard (92% match)
     Source: untapped.gg
     Link: https://untapped.gg/deck/...
     
  2. Izzet Tempo - Historic (78% match)
     Source: untapped.gg
     Link: https://untapped.gg/deck/...
======================================================================
```

---

## 9. Phased Implementation

### Phase 1: Basic Identification
- Rule-based matching with local archetype DB
- Simple card matching algorithm
- Display archetype name

### Phase 2: LLM Integration
- Add LLM API support
- Fallback logic
- Improve accuracy

### Phase 3: Search Integration
- Integrate Untapped.gg search
- Parse and display results
- Add multiple source support

### Phase 4: Polish
- Caching
- Performance optimization
- User preferences/config

---

## 10. Open Questions

1. **Which LLM provider?** (OpenAI, Anthropic, local model)
2. **Untapped.gg API availability?** (may need scraping)
3. **Format detection?** (Standard, Historic, etc.)
4. **User opt-in for LLM?** (cost/privacy)
5. **Cache strategy?** (per archetype, per card set)

---

## Next Steps

1. Research Untapped.gg API availability and documentation
2. Build initial archetype database (common Standard/Historic decks)
3. Implement Phase 1 (rule-based matching)
4. Test with real game data
5. Evaluate accuracy and decide on LLM integration
